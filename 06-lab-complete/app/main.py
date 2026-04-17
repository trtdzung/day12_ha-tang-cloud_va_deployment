"""
Production AI Agent — Kết hợp tất cả Day 12 concepts

Checklist:
  ✅ Config từ environment (12-factor)
  ✅ Structured JSON logging
  ✅ API Key authentication
  ✅ Rate limiting — Redis-backed sliding window (in-memory fallback)
  ✅ Cost guard — Redis INCRBYFLOAT với daily TTL
  ✅ Conversation history — Redis list per user, TTL 24h
  ✅ Input validation (Pydantic)
  ✅ Health check + Readiness probe
  ✅ Graceful shutdown
  ✅ Security headers
  ✅ CORS
  ✅ Error handling
"""
import os
import time
import signal
import logging
import json
from datetime import datetime, timezone
from collections import defaultdict, deque
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Security, Depends, Request, Response
from fastapi.security.api_key import APIKeyHeader
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
import uvicorn

from app.config import settings

# Mock LLM (thay bằng OpenAI/Anthropic khi có API key)
from utils.mock_llm import ask as llm_ask

# ─────────────────────────────────────────────────────────
# Logging — JSON structured
# ─────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.DEBUG if settings.debug else logging.INFO,
    format='{"ts":"%(asctime)s","lvl":"%(levelname)s","msg":"%(message)s"}',
)
logger = logging.getLogger(__name__)

START_TIME = time.time()
_is_ready = False
_error_count = 0

# ─────────────────────────────────────────────────────────
# Redis client (optional) — state stateless khi có Redis, fallback in-memory
# ─────────────────────────────────────────────────────────
_redis = None
if settings.redis_url:
    try:
        import redis
        _redis = redis.from_url(settings.redis_url, decode_responses=True)
        _redis.ping()
        logger.info(json.dumps({"event": "redis_connected", "url": settings.redis_url.split("@")[-1]}))
    except Exception as e:
        logger.warning(json.dumps({"event": "redis_connect_failed", "err": str(e)}))
        _redis = None

USE_REDIS = _redis is not None

# In-memory fallback structures
_mem_rate: dict[str, deque] = defaultdict(deque)
_mem_cost: dict[str, float] = defaultdict(float)
_mem_history: dict[str, list] = defaultdict(list)
_mem_request_count = 0

# ─────────────────────────────────────────────────────────
# Rate limiter — Redis sorted set sliding window / in-memory deque
# ─────────────────────────────────────────────────────────
def check_rate_limit(bucket: str):
    now = time.time()
    limit = settings.rate_limit_per_minute
    if USE_REDIS:
        key = f"rl:{bucket}"
        pipe = _redis.pipeline()
        pipe.zremrangebyscore(key, 0, now - 60)
        pipe.zcard(key)
        pipe.zadd(key, {f"{now}:{os.getpid()}:{int(now*1e6)}": now})
        pipe.expire(key, 120)
        _, count, *_ = pipe.execute()
        if count >= limit:
            # Rollback the add if over limit
            _redis.zrem(key, f"{now}:{os.getpid()}:{int(now*1e6)}")
            raise HTTPException(
                status_code=429,
                detail=f"Rate limit exceeded: {limit} req/min",
                headers={"Retry-After": "60"},
            )
    else:
        window = _mem_rate[bucket]
        while window and window[0] < now - 60:
            window.popleft()
        if len(window) >= limit:
            raise HTTPException(
                status_code=429,
                detail=f"Rate limit exceeded: {limit} req/min",
                headers={"Retry-After": "60"},
            )
        window.append(now)


# ─────────────────────────────────────────────────────────
# Cost guard — Redis INCRBYFLOAT với TTL / in-memory dict
# ─────────────────────────────────────────────────────────
def _today_key() -> str:
    return time.strftime("%Y-%m-%d")


def check_and_record_cost(input_tokens: int, output_tokens: int):
    today = _today_key()
    cost = (input_tokens / 1000) * 0.00015 + (output_tokens / 1000) * 0.0006
    if USE_REDIS:
        key = f"cost:{today}"
        current = float(_redis.get(key) or 0)
        if current >= settings.daily_budget_usd:
            raise HTTPException(503, "Daily budget exhausted. Try tomorrow.")
        _redis.incrbyfloat(key, cost)
        _redis.expire(key, 2 * 24 * 3600)
    else:
        if _mem_cost[today] >= settings.daily_budget_usd:
            raise HTTPException(503, "Daily budget exhausted. Try tomorrow.")
        _mem_cost[today] += cost


def get_daily_cost() -> float:
    today = _today_key()
    if USE_REDIS:
        return float(_redis.get(f"cost:{today}") or 0)
    return _mem_cost[today]


# ─────────────────────────────────────────────────────────
# Request counter — Redis INCR / in-memory
# ─────────────────────────────────────────────────────────
def incr_request_count():
    global _mem_request_count
    if USE_REDIS:
        _redis.incr("stats:requests:total")
    else:
        _mem_request_count += 1


def get_request_count() -> int:
    if USE_REDIS:
        return int(_redis.get("stats:requests:total") or 0)
    return _mem_request_count


# ─────────────────────────────────────────────────────────
# Conversation history — Redis list per user, TTL 24h
# ─────────────────────────────────────────────────────────
HISTORY_MAX_LEN = 20  # 10 turns (user + assistant)
HISTORY_TTL_SECONDS = 24 * 3600


def append_history(user_id: str, role: str, content: str):
    entry = {
        "role": role,
        "content": content,
        "ts": datetime.now(timezone.utc).isoformat(),
    }
    if USE_REDIS:
        key = f"history:{user_id}"
        pipe = _redis.pipeline()
        pipe.rpush(key, json.dumps(entry))
        pipe.ltrim(key, -HISTORY_MAX_LEN, -1)
        pipe.expire(key, HISTORY_TTL_SECONDS)
        pipe.execute()
    else:
        h = _mem_history[user_id]
        h.append(entry)
        if len(h) > HISTORY_MAX_LEN:
            _mem_history[user_id] = h[-HISTORY_MAX_LEN:]


def load_history(user_id: str) -> list[dict]:
    if USE_REDIS:
        items = _redis.lrange(f"history:{user_id}", 0, -1)
        return [json.loads(i) for i in items]
    return list(_mem_history.get(user_id, []))


def clear_history_entry(user_id: str) -> int:
    if USE_REDIS:
        return _redis.delete(f"history:{user_id}")
    removed = 1 if user_id in _mem_history else 0
    _mem_history.pop(user_id, None)
    return removed


# ─────────────────────────────────────────────────────────
# Auth
# ─────────────────────────────────────────────────────────
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def verify_api_key(api_key: str = Security(api_key_header)) -> str:
    if not api_key or api_key != settings.agent_api_key:
        raise HTTPException(
            status_code=401,
            detail="Invalid or missing API key. Include header: X-API-Key: <key>",
        )
    return api_key


# ─────────────────────────────────────────────────────────
# Lifespan
# ─────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    global _is_ready
    logger.info(json.dumps({
        "event": "startup",
        "app": settings.app_name,
        "version": settings.app_version,
        "environment": settings.environment,
        "storage": "redis" if USE_REDIS else "in-memory",
    }))
    time.sleep(0.1)  # simulate init
    _is_ready = True
    logger.info(json.dumps({"event": "ready"}))

    yield

    _is_ready = False
    logger.info(json.dumps({"event": "shutdown"}))


# ─────────────────────────────────────────────────────────
# App
# ─────────────────────────────────────────────────────────
app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    lifespan=lifespan,
    docs_url="/docs" if (settings.environment != "production" or settings.expose_docs) else None,
    redoc_url="/redoc" if (settings.environment != "production" or settings.expose_docs) else None,
    openapi_url="/openapi.json" if (settings.environment != "production" or settings.expose_docs) else None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["Authorization", "Content-Type", "X-API-Key"],
)


@app.middleware("http")
async def request_middleware(request: Request, call_next):
    global _error_count
    start = time.time()
    incr_request_count()
    try:
        response: Response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        if "server" in response.headers:
            del response.headers["server"]
        duration = round((time.time() - start) * 1000, 1)
        logger.info(json.dumps({
            "event": "request",
            "method": request.method,
            "path": request.url.path,
            "status": response.status_code,
            "ms": duration,
        }))
        return response
    except Exception:
        _error_count += 1
        raise


# ─────────────────────────────────────────────────────────
# Models
# ─────────────────────────────────────────────────────────
class AskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000,
                          description="Your question for the agent")
    user_id: str = Field("default", min_length=1, max_length=64,
                         description="User identifier for conversation history")


class HistoryMessage(BaseModel):
    role: str
    content: str
    ts: str


class AskResponse(BaseModel):
    question: str
    answer: str
    model: str
    timestamp: str
    user_id: str
    turn: int
    history_size: int


# ─────────────────────────────────────────────────────────
# Endpoints
# ─────────────────────────────────────────────────────────

@app.get("/", tags=["Info"])
def root():
    return {
        "app": settings.app_name,
        "version": settings.app_version,
        "environment": settings.environment,
        "storage": "redis" if USE_REDIS else "in-memory",
        "endpoints": {
            "ask": "POST /ask (requires X-API-Key)",
            "history_get": "GET /history/{user_id} (requires X-API-Key)",
            "history_clear": "DELETE /history/{user_id} (requires X-API-Key)",
            "health": "GET /health",
            "ready": "GET /ready",
            "metrics": "GET /metrics (requires X-API-Key)",
            "docs": "GET /docs",
        },
    }


@app.post("/ask", response_model=AskResponse, tags=["Agent"])
async def ask_agent(
    body: AskRequest,
    request: Request,
    _key: str = Depends(verify_api_key),
):
    """
    Hỏi agent. Conversation history lưu theo `user_id` trong Redis (TTL 24h, giữ 20 messages gần nhất).

    **Authentication:** `X-API-Key: <your-key>`
    """
    # Rate limit per user
    check_rate_limit(f"user:{body.user_id}")

    # Budget check
    input_tokens = len(body.question.split()) * 2
    check_and_record_cost(input_tokens, 0)

    # Load + save history
    history_before = load_history(body.user_id)
    append_history(body.user_id, "user", body.question)

    logger.info(json.dumps({
        "event": "agent_call",
        "user_id": body.user_id,
        "q_len": len(body.question),
        "history_turns": len(history_before) // 2,
        "client": str(request.client.host) if request.client else "unknown",
    }))

    # Mock LLM không dùng history, nhưng real LLM sẽ concat history_before + body.question
    answer = llm_ask(body.question)

    append_history(body.user_id, "assistant", answer)
    output_tokens = len(answer.split()) * 2
    check_and_record_cost(0, output_tokens)

    final_history = load_history(body.user_id)
    return AskResponse(
        question=body.question,
        answer=answer,
        model=settings.llm_model,
        timestamp=datetime.now(timezone.utc).isoformat(),
        user_id=body.user_id,
        turn=len([m for m in final_history if m["role"] == "user"]),
        history_size=len(final_history),
    )


@app.get("/history/{user_id}", tags=["Agent"])
def get_history(user_id: str, _key: str = Depends(verify_api_key)):
    """Xem conversation history của một user."""
    messages = load_history(user_id)
    return {
        "user_id": user_id,
        "messages": messages,
        "count": len(messages),
        "storage": "redis" if USE_REDIS else "in-memory",
    }


@app.delete("/history/{user_id}", tags=["Agent"])
def delete_history(user_id: str, _key: str = Depends(verify_api_key)):
    """Xóa conversation history của một user."""
    removed = clear_history_entry(user_id)
    return {"cleared": bool(removed), "user_id": user_id}


@app.get("/health", tags=["Operations"])
def health():
    """Liveness probe. Platform restarts container if this fails."""
    redis_ok = None
    if USE_REDIS:
        try:
            _redis.ping()
            redis_ok = True
        except Exception:
            redis_ok = False
    return {
        "status": "ok" if (not USE_REDIS or redis_ok) else "degraded",
        "version": settings.app_version,
        "environment": settings.environment,
        "uptime_seconds": round(time.time() - START_TIME, 1),
        "total_requests": get_request_count(),
        "checks": {
            "llm": "mock" if not settings.openai_api_key else "openai",
            "storage": "redis" if USE_REDIS else "in-memory",
            "redis_connected": redis_ok,
        },
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/ready", tags=["Operations"])
def ready():
    """Readiness probe. Load balancer stops routing here if not ready."""
    if not _is_ready:
        raise HTTPException(503, "Not ready")
    if USE_REDIS:
        try:
            _redis.ping()
        except Exception:
            raise HTTPException(503, "Redis unavailable")
    return {"ready": True}


@app.get("/metrics", tags=["Operations"])
def metrics(_key: str = Depends(verify_api_key)):
    """Basic metrics (protected)."""
    cost = get_daily_cost()
    return {
        "uptime_seconds": round(time.time() - START_TIME, 1),
        "total_requests": get_request_count(),
        "error_count": _error_count,
        "daily_cost_usd": round(cost, 4),
        "daily_budget_usd": settings.daily_budget_usd,
        "budget_used_pct": round(cost / settings.daily_budget_usd * 100, 2),
        "storage": "redis" if USE_REDIS else "in-memory",
    }


# ─────────────────────────────────────────────────────────
# Graceful Shutdown
# ─────────────────────────────────────────────────────────
def _handle_signal(signum, _frame):
    logger.info(json.dumps({"event": "signal", "signum": signum}))


signal.signal(signal.SIGTERM, _handle_signal)


if __name__ == "__main__":
    logger.info(f"Starting {settings.app_name} on {settings.host}:{settings.port}")
    logger.info(f"API Key: {settings.agent_api_key[:4]}****")
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
        timeout_graceful_shutdown=30,
    )
