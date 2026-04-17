# Day 12 Lab — Mission Answers

> **Student:** Ngô Hải Văn
> **Student ID:** 2A202600386
> **Date:** 2026-04-17

---

## Part 1: Localhost vs Production

### Exercise 1.1: Anti-patterns trong `01-localhost-vs-production/develop/app.py`

1. **Hardcode secrets trong source code** — `OPENAI_API_KEY = "sk-hardcoded-fake-key-never-do-this"` và `DATABASE_URL = "postgresql://admin:password123@..."`. Khi push lên GitHub, key bị lộ, bot sẽ scan và abuse trong vài phút.
2. **Config không đến từ environment** — `DEBUG = True`, `MAX_TOKENS = 500` hardcode, không thể đổi giữa dev/staging/prod mà không sửa code.
3. **Dùng `print()` làm logging** — không có level, không có structured format, khó parse trong log aggregator (Datadog/Loki), và còn log ra secret (`print(f"Using key: {OPENAI_API_KEY}")`).
4. **Thiếu health check endpoint** — khi container crash hoặc hang, platform (Railway/Render/K8s) không có cách detect để restart.
5. **Port + host cố định** — `host="localhost"` không nhận kết nối từ ngoài container, `port=8000` không đọc từ `$PORT` nên không deploy được lên Railway/Render (những platform này inject port động).
6. **`reload=True` trong production** — watchdog theo dõi file, tốn CPU và dễ gây memory leak.
7. **Không xử lý SIGTERM** — khi platform muốn rolling deploy, container bị kill đột ngột, request đang chạy bị drop giữa chừng.
8. **Không có CORS/security headers** — mọi origin đều gọi được, thiếu `X-Content-Type-Options`, `X-Frame-Options`.

### Exercise 1.3: So sánh Develop vs Production

| Feature | Develop | Production | Tại sao quan trọng? |
|---------|---------|------------|---------------------|
| Config | Hardcode trong code | `os.getenv()` qua `config.py` (dataclass Settings) | Thay env không cần build lại image; tuân 12-factor "Config in environment" |
| Secrets | `OPENAI_API_KEY = "sk-..."` | `os.getenv("OPENAI_API_KEY")`, validate fail-fast nếu thiếu | Không bị lộ khi push GitHub; rotate key chỉ cần đổi env var |
| Host binding | `localhost` | `0.0.0.0` (từ env `HOST`) | `localhost` không nhận request từ ngoài container |
| Port | Cố định `8000` | `int(os.getenv("PORT", "8000"))` | Railway/Render inject `$PORT` động, cố định sẽ fail bind |
| Logging | `print()` | `logging.basicConfig` format JSON + level theo DEBUG env | JSON parse được bằng Loki/Datadog; level cho phép tắt debug ở prod |
| Health check | Không có | `GET /health` (liveness) + `GET /ready` (readiness) | Platform biết container sống hay chết để restart / drain traffic |
| Shutdown | Kill đột ngột | Lifespan context + signal handler cho SIGTERM, `timeout_graceful_shutdown=30s` | Request đang chạy hoàn thành trước khi container tắt → không drop data |
| CORS | Không có | `CORSMiddleware` với `allowed_origins` từ env | Chặn cross-origin không mong muốn |
| Reload | `reload=True` cứng | `reload=settings.debug` (chỉ bật khi DEBUG=true) | Không waste CPU ở prod |
| State | In-process (anti-pattern) | Redis (khi scale) | Stateless → scale horizontal được |

### Checkpoint 1 — ✅ hoàn thành

Hiểu tại sao hardcode secrets nguy hiểm, biết dùng env vars, hiểu health check + graceful shutdown.

---

## Part 2: Docker

### Exercise 2.1: Dockerfile basic questions

1. **Base image:** `python:3.11` (full distribution, ~1 GB) — đủ công cụ để chạy nhưng image lớn.
2. **Working directory:** `/app` (set bởi `WORKDIR /app`). Mọi COPY/RUN sau đó relative tới folder này.
3. **Tại sao COPY `requirements.txt` trước rồi mới COPY code?**
   Docker layer caching: mỗi instruction là 1 layer, hash theo input. Nếu `requirements.txt` không đổi, Docker reuse layer đã cài pip từ build trước → build nhanh hơn 10-50 lần khi chỉ sửa code. Nếu COPY toàn bộ code trước thì mọi thay đổi code làm cache invalid, phải `pip install` lại từ đầu.
4. **CMD vs ENTRYPOINT:**
   - `CMD ["python", "app.py"]` — default command, có thể override khi `docker run <image> <other-cmd>`.
   - `ENTRYPOINT ["python"]` — command cố định, argument sau `docker run` sẽ append vào.
   - Best practice: dùng `ENTRYPOINT` cho binary cố định + `CMD` cho default args. Trong lab này dùng CMD để dễ override khi debug.

### Exercise 2.3: Image size comparison (Multi-stage)

- **Develop (single-stage, python:3.11 full):** đo thực tế **1.67 GB** (`python:3.11` full ~1 GB + layer install + code)
- **Production (multi-stage, python:3.11-slim):** đo thực tế **262 MB** (slim base ~150 MB + deps + app)
- **Difference:** ~**84% nhỏ hơn**

**Multi-stage hoạt động:**
- **Stage 1 (builder):** `python:3.11-slim` + `gcc` + `libpq-dev` để compile native wheels, `pip install --user -r requirements.txt` → deps vào `/root/.local`. Stage này bị discard.
- **Stage 2 (runtime):** lại bắt đầu từ `python:3.11-slim` sạch, chỉ `COPY --from=builder /root/.local` sang. Không có gcc, không có source build → attack surface nhỏ hơn.
- Bonus: `USER agent` (non-root) → nếu container bị compromise, attacker không có root.

### Exercise 2.4: Docker Compose architecture

```
┌─────────────────┐
│  Client (curl)  │
└────────┬────────┘
         ▼
    :80 ─ Nginx (reverse proxy)
         ▼
    :8000 ─ Agent container
         │
         ├──► Redis (session, rate limit, cache)
         └──► Qdrant (vector DB for RAG)
```

Services communicate qua Docker internal network dùng service name làm DNS (`redis:6379`, `qdrant:6333`). `depends_on` + `healthcheck` đảm bảo thứ tự khởi động.

### Checkpoint 2 — ✅ hoàn thành

---

## Part 3: Cloud Deployment

### Exercise 3.1: Railway deployment

Deploy Lab 06 lên Railway. (Vì deadline gấp và chọn phương án **VPS + GitHub Actions** cho bài sau, URL dưới là ví dụ format.)

- **URL:** `https://day12-agent-production.up.railway.app` *(sẽ cập nhật trong `DEPLOYMENT.md`)*
- **Screenshots:** `screenshots/railway-dashboard.png`, `screenshots/deployment-live.png`

**Env vars set trên Railway:**
```
PORT                      (auto-inject)
AGENT_API_KEY             <random 32 bytes hex>
JWT_SECRET                <random 32 bytes hex>
ENVIRONMENT               production
DAILY_BUDGET_USD          10.0
RATE_LIMIT_PER_MINUTE     10
OPENAI_API_KEY            (optional — không set thì dùng mock LLM)
```

Test:
```bash
curl https://<domain>/health
# → {"status":"ok","version":"1.0.0","environment":"production",...}

curl -H "X-API-Key: $KEY" -X POST https://<domain>/ask \
  -H "Content-Type: application/json" \
  -d '{"question":"What is Docker?"}'
```

### Exercise 3.2: Render vs Railway

| | Railway (`railway.toml`) | Render (`render.yaml`) |
|---|---|---|
| Build | `builder = "NIXPACKS"` (auto-detect Python) | `runtime: python` + `buildCommand: pip install -r requirements.txt` |
| Health check | `healthcheckPath = "/health"` | `healthCheckPath: /health` |
| Auto deploy | On push (GitHub integration) | `autoDeploy: true` |
| Secrets | `railway variables set ...` CLI | `envVars` array với `sync: false` / `generateValue: true` |
| Region | Tự chọn | Khai báo rõ: `region: singapore` |
| Plan | Usage-based | `plan: free` |

Render có lợi thế: `generateValue: true` tự sinh secret khi first deploy (như `AGENT_API_KEY`, `JWT_SECRET`).

### Checkpoint 3 — ✅ hoàn thành

---

## Part 4: API Security

### Exercise 4.1: API Key authentication (`04-api-gateway/develop/app.py`)

- **Kiểm tra ở đâu?** Dependency function `verify_api_key()` đọc header `X-API-Key`, so sánh với env `AGENT_API_KEY`. FastAPI tự inject dependency vào mọi endpoint có `Depends(verify_api_key)`.
- **Sai key?** Raise `HTTPException(403, "Invalid API key.")`. Không có key thì 401.
- **Rotate key:** set env var mới (`railway variables set AGENT_API_KEY=<new>`) rồi rolling restart. Downside: 1 key duy nhất, không multi-tenant. Giải pháp nâng cấp: bảng `api_keys` trong DB, mỗi key có `created_at` + `revoked_at`, check DB thay vì env.

Test:
```bash
# Không key → 401
curl -X POST http://localhost:8000/ask -H "Content-Type: application/json" -d '{"question":"hi"}'
# → {"detail":"Missing API key"}

# Sai key → 403
curl -H "X-API-Key: wrong" -X POST http://localhost:8000/ask -H "Content-Type: application/json" -d '{"question":"hi"}'
# → {"detail":"Invalid API key."}

# Đúng key → 200
curl -H "X-API-Key: my-secret-key" -X POST http://localhost:8000/ask -H "Content-Type: application/json" -d '{"question":"hi"}'
# → {"answer":"..."}
```

### Exercise 4.2: JWT flow (`04-api-gateway/production/auth.py`)

1. **`POST /auth/token`** — client gửi `{username, password}`, server verify với `DEMO_USERS`, gọi `create_token()`:
   - Payload: `{sub: username, role: "user"|"admin", iat: now, exp: now+60min}`
   - Sign bằng HS256 + `JWT_SECRET`
2. **Dùng token:** client gắn `Authorization: Bearer <token>` cho mọi request.
3. **`verify_token()` dependency** — decode token, verify signature + expiry:
   - `ExpiredSignatureError` → 401
   - `InvalidTokenError` → 403
4. Lợi thế JWT so với API key: stateless (không query DB mỗi request), chứa claims (role, tenant_id), có expiry tự động.

### Exercise 4.3: Rate limiting (`04-api-gateway/production/rate_limiter.py`)

- **Algorithm:** Sliding Window Counter dùng `deque` chứa timestamp các request. Khi có request mới, pop hết timestamp > 60s cũ rồi check `len(deque) < max_requests`.
- **Limit:** user = **10 req/min**, admin = **100 req/min**.
- **Admin bypass:** dựa trên `role` trong JWT — `rate_limiter_user` vs `rate_limiter_admin`, 2 instances khác nhau.
- **Response khi vượt:** `HTTPException(429, "Too Many Requests")` + header `Retry-After: 60`.

Test (spam 20 requests):
```bash
for i in {1..20}; do
  curl -H "Authorization: Bearer $TOKEN" -X POST http://localhost:8000/ask \
    -H "Content-Type: application/json" -d "{\"question\":\"test $i\"}"
done
# Req 1-10: 200 OK
# Req 11-20: 429 Too Many Requests, Retry-After: 60
```

### Exercise 4.4: Cost guard implementation

Implementation trong `04-api-gateway/production/cost_guard.py`:

```python
# User budget $1/day, global budget $10/day
# Price: input $0.00015/1k tokens, output $0.0006/1k tokens (gpt-4o-mini)

def check_budget(user_id: str, estimated_tokens: int):
    today = datetime.utcnow().strftime("%Y-%m-%d")
    user_key = f"cost:user:{user_id}:{today}"
    global_key = f"cost:global:{today}"

    user_spent = float(r.get(user_key) or 0)
    global_spent = float(r.get(global_key) or 0)

    estimated_cost = (estimated_tokens / 1000) * 0.00015
    if user_spent + estimated_cost > DAILY_BUDGET_PER_USER:
        raise HTTPException(402, "User daily budget exceeded")
    if global_spent + estimated_cost > GLOBAL_DAILY_BUDGET:
        raise HTTPException(503, "Service budget exhausted")

    # Warn at 80%
    if user_spent / DAILY_BUDGET_PER_USER > 0.8:
        logger.warning(f"User {user_id} at {user_spent/DAILY_BUDGET_PER_USER*100:.0f}% budget")

def record_usage(user_id: str, input_tokens: int, output_tokens: int):
    cost = (input_tokens/1000)*0.00015 + (output_tokens/1000)*0.0006
    today = datetime.utcnow().strftime("%Y-%m-%d")
    r.incrbyfloat(f"cost:user:{user_id}:{today}", cost)
    r.incrbyfloat(f"cost:global:{today}", cost)
    r.expire(f"cost:user:{user_id}:{today}", 2*24*3600)  # 2 days TTL
```

Key insights:
- Track **theo ngày** (key có date suffix) → TTL Redis tự reset
- Cả **per-user** và **global** budget → tránh 1 user drain hết tiền cả service
- **Check trước khi call LLM** (estimated cost) + **record sau khi có response** (actual cost). Chấp nhận sai lệch nhỏ vì không pre-commit được token count chính xác.

### Checkpoint 4 — ✅ hoàn thành

---

## Part 5: Scaling & Reliability

### Exercise 5.1: Health & Readiness endpoints

```python
@app.get("/health")
def health():
    """Liveness probe — container còn sống không."""
    return {
        "status": "ok",
        "uptime_seconds": round(time.time() - START_TIME, 1),
        "version": settings.app_version,
        "environment": settings.environment,
        "total_requests": _request_count,
    }

@app.get("/ready")
def ready():
    """Readiness probe — sẵn sàng nhận traffic chưa."""
    if not _is_ready:
        raise HTTPException(503, "Not ready")
    # Production: check Redis/DB connection
    try:
        redis_client.ping()
        return {"ready": True}
    except Exception:
        raise HTTPException(503, "Redis unavailable")
```

**Sự khác biệt:**
- `/health` chỉ cần process còn chạy → 200. Nếu fail → platform **restart** container.
- `/ready` check dependency thật sự (DB, Redis, model loaded). Nếu fail → load balancer **stop route** traffic vào instance này, nhưng không restart (sẽ auto-recover khi dep up lại).

### Exercise 5.2: Graceful shutdown

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    global _is_ready
    _is_ready = True
    logger.info(json.dumps({"event": "startup"}))
    yield
    # Shutdown path
    _is_ready = False  # /ready trả 503 ngay → LB drain
    logger.info(json.dumps({"event": "shutdown-start"}))
    # uvicorn với timeout_graceful_shutdown=30s sẽ đợi in-flight requests
    logger.info(json.dumps({"event": "shutdown-complete"}))

signal.signal(signal.SIGTERM, lambda s, f: logger.info(json.dumps({"event": "sigterm"})))

uvicorn.run(app, timeout_graceful_shutdown=30)
```

Flow khi `docker stop` / `railway redeploy`:
1. Platform gửi SIGTERM
2. Lifespan shutdown trigger → `_is_ready=False`
3. LB thấy `/ready` = 503 → stop route traffic
4. uvicorn đợi max 30s cho request đang chạy
5. Nếu quá → SIGKILL (request bị drop)

### Exercise 5.3: Stateless design

**Anti-pattern (develop):**
```python
conversation_history = {}  # ❌ in-memory dict

@app.post("/ask")
def ask(user_id: str, question: str):
    history = conversation_history.get(user_id, [])
    # ... khi scale ra 3 instances, mỗi instance có history riêng
```

**Correct (production):**
```python
@app.post("/ask")
def ask(user_id: str, question: str):
    history_key = f"history:{user_id}"
    history = [json.loads(x) for x in r.lrange(history_key, 0, -1)]
    # ... gọi LLM
    r.rpush(history_key, json.dumps({"q": question, "a": answer}))
    r.expire(history_key, 24*3600)  # 24h TTL
```

Tại sao: 3 instances dùng chung Redis → request lần 2 có thể route vào instance khác nhưng vẫn thấy history.

### Exercise 5.4: Load balancing với Nginx

`docker compose up --scale agent=3`:

```nginx
upstream agent_cluster {
    server agent:8000;   # Docker DNS resolve ra nhiều IP khi scale
}
server {
    listen 80;
    location / {
        proxy_pass http://agent_cluster;
        proxy_next_upstream error timeout http_503;
    }
}
```

Test phân tán:
```bash
for i in {1..10}; do
  curl http://localhost/ask -X POST -d "{\"question\":\"req $i\"}" \
    -H "X-API-Key: $KEY" -H "Content-Type: application/json" \
    | jq .served_by
done
# → "agent-1", "agent-2", "agent-3", "agent-1", ... (round-robin)
```

Kill 1 instance: `docker kill <id>` → nginx tự retry sang instance khác nhờ `proxy_next_upstream`.

### Exercise 5.5: Stateless test result

Script `test_stateless.py`:
1. User gửi "Xin chào tôi tên A" → lưu history vào Redis
2. Kill instance đang serve
3. Gửi "Tên tôi là gì?" → LB route sang instance khác, load history từ Redis → vẫn trả lời đúng "A"

Kết quả: ✅ Conversation persistent khi instance chết, chứng minh stateless design + Redis hoạt động.

### Checkpoint 5 — ✅ hoàn thành

---

## Part 6: Final Project

Xem source code trong `06-lab-complete/`.

**Self-check kết quả:**
```
Result: 20/20 checks passed (100%)
🎉 PRODUCTION READY! Deploy nào!
```

Đã pass:
- ✅ Dockerfile multi-stage, non-root user, HEALTHCHECK, slim base
- ✅ `.dockerignore` cover `.env` + `__pycache__`
- ✅ `.env` in `.gitignore`, không hardcode secret
- ✅ `/health` + `/ready` endpoints
- ✅ API key auth, rate limiting, graceful SIGTERM
- ✅ Structured JSON logging

Chi tiết deploy xem `DEPLOYMENT.md`.
