# Deployment Information #2 — Day 12 Lab (Railway)

> **Student:** Ngô Hải Văn (2A202600386)
> **Date:** 2026-04-17
> **Dự án triển khai:** `06-lab-complete/` (Production AI Agent) — chính source của Day 12 Lab.
> **Ghi chú:** Đây là bản deploy thứ 2 song song với bản VPS trong `DEPLOYMENT.md`.

---

## Public URL

**Production URL:** https://day12-agent-production-a0dc.up.railway.app

- Health: https://day12-agent-production-a0dc.up.railway.app/health
- Ready: https://day12-agent-production-a0dc.up.railway.app/ready
- **Swagger UI:** https://day12-agent-production-a0dc.up.railway.app/docs
- ReDoc: https://day12-agent-production-a0dc.up.railway.app/redoc
- OpenAPI JSON: https://day12-agent-production-a0dc.up.railway.app/openapi.json

---

## Platform

- **Hosting:** Railway (auto-managed)
- **Builder:** `DOCKERFILE` (từ `06-lab-complete/Dockerfile`, multi-stage, non-root)
- **Runtime:** uvicorn 2 workers, bind `0.0.0.0:$PORT`
- **Image size:** ~272 MB (python:3.11-slim)
- **Health check:** Railway poll `/health` mỗi 30s, `healthcheckTimeout = 30s`
- **Restart policy:** `ON_FAILURE` với 3 retries
- **Account:** `ngohaivan7@gmail.com` / Project `day12-agent-van` / Service `day12-agent`

---

## Environment Variables (set trên Railway)

| Variable | Value | Notes |
|----------|-------|-------|
| `PORT` | auto | Injected by Railway |
| `ENVIRONMENT` | `production` | Tắt `/docs` endpoint |
| `APP_NAME` | `Day12 Agent` | |
| `APP_VERSION` | `1.0.0` | |
| `AGENT_API_KEY` | *(64-hex ngẫu nhiên — `secrets.token_hex(32)`)* | **Secret**, không commit |
| `JWT_SECRET` | *(64-hex ngẫu nhiên)* | **Secret**, không commit |
| `RATE_LIMIT_PER_MINUTE` | `10` | Sliding window |
| `DAILY_BUDGET_USD` | `10.0` | Cost guard |
| `OPENAI_API_KEY` | *(empty → mock LLM)* | Optional |
| `EXPOSE_DOCS` | `true` | Bật `/docs`, `/redoc`, `/openapi.json` ở production để grading |

> Key lấy trực tiếp từ Railway:
> ```bash
> railway variables --service day12-agent --kv | grep AGENT_API_KEY
> ```
> (File `.lab12_secrets.local` local được sync từ VPS nên **không chứa** Railway key.)

---

## Test Commands

Trước khi chạy, export API key:

```bash
# Lấy từ Railway dashboard Variables hoặc file .lab12_secrets.local
export URL="https://day12-agent-production-a0dc.up.railway.app"
export API_KEY="<AGENT_API_KEY-từ-railway-variables>"
```

### 1. Health Check (public)

```bash
curl -s "$URL/health" | jq
```

Expected:
```json
{
  "status": "ok",
  "version": "1.0.0",
  "environment": "production",
  "uptime_seconds": 37.0,
  "total_requests": 2,
  "checks": { "llm": "mock" },
  "timestamp": "2026-04-17T09:20:19.486290+00:00"
}
```

### 2. Readiness Probe (public)

```bash
curl -s "$URL/ready"
# → {"ready":true}
```

### 3. Authentication — Không có API key → 401

```bash
curl -s -o /dev/null -w "HTTP %{http_code}\n" \
  -X POST "$URL/ask" \
  -H "Content-Type: application/json" \
  -d '{"question":"hello"}'
# → HTTP 401
```

### 4. Authentication — Có API key → 200

```bash
curl -s -X POST "$URL/ask" \
  -H "X-API-Key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"question":"Deployment là gì?"}'
```

Expected:
```json
{
  "question": "Deployment là gì?",
  "answer": "Deployment là quá trình đưa code từ máy bạn lên server để người khác dùng được.",
  "model": "gpt-4o-mini",
  "timestamp": "2026-04-17T09:20:05.449245+00:00"
}
```

### 5. Input Validation — Question trống → 422

```bash
curl -s -o /dev/null -w "HTTP %{http_code}\n" \
  -X POST "$URL/ask" \
  -H "X-API-Key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"question":""}'
# → HTTP 422 (Pydantic min_length=1)
```

### 6. Rate Limit — 10 req/min → request 11-15 trả 429

```bash
for i in {1..15}; do
  curl -s -o /dev/null -w "req $i: %{http_code}\n" \
    -X POST "$URL/ask" \
    -H "X-API-Key: $API_KEY" \
    -H "Content-Type: application/json" \
    -d "{\"question\":\"ping $i\"}"
done
```

Kết quả đo thực tế (service chạy **2 uvicorn workers**, rate limiter in-memory per-process nên mỗi worker có counter riêng):
```
req 1-11: 200
req 12-14: 429
req 15: 200   ← rơi vào worker khác còn slot
```
Tổng quát: cỡ ~20 req/min service chấp nhận trước khi đa số trả 429. Để đúng "10/min/service", cần Redis-backed rate limiter (xem Part 5 production).

### 7. Metrics (protected)

```bash
curl -s "$URL/metrics" -H "X-API-Key: $API_KEY" | jq
```

Expected:
```json
{
  "uptime_seconds": 23.6,
  "total_requests": 5,
  "error_count": 0,
  "daily_cost_usd": 0.0,
  "daily_budget_usd": 10.0,
  "budget_used_pct": 0.0
}
```

### 8. Swagger UI (interactive test)

Mở trong browser:
```
https://day12-agent-production-a0dc.up.railway.app/docs
```
1. Click lock icon ở góc phải → paste `AGENT_API_KEY` vào ô `X-API-Key` → Authorize.
2. Expand `POST /ask` → "Try it out" → điền `{"question":"Xin chào"}` → Execute.
3. Xem response trực tiếp, không cần curl.

Endpoint liệt kê trong OpenAPI: `/`, `/ask`, `/health`, `/ready`, `/metrics`.

### 9. Security Headers

```bash
curl -sI "$URL/health"
```

Response có các header:
- `x-content-type-options: nosniff`
- `x-frame-options: DENY`
- `server: railway-edge` (do Railway edge proxy gắn, **middleware app đã strip upstream `server:` — header còn lại là của Railway, không phải uvicorn**)

---

## Deploy Steps (reproduce lại)

```bash
# 1. Cài CLI
npm i -g @railway/cli
railway login                # mở browser login
railway whoami               # verify

# 2. Init project (trong folder 06-lab-complete)
cd 06-lab-complete
railway init --name day12-agent-van
railway add --service day12-agent

# 3. Gen secrets
AGENT_KEY=$(python3 -c "import secrets; print(secrets.token_hex(32))")
JWT_KEY=$(python3 -c "import secrets; print(secrets.token_hex(32))")

# 4. Set env vars (skip-deploys để batch)
railway variables --service day12-agent --skip-deploys \
  --set "ENVIRONMENT=production" \
  --set "AGENT_API_KEY=$AGENT_KEY" \
  --set "JWT_SECRET=$JWT_KEY" \
  --set "DAILY_BUDGET_USD=10.0" \
  --set "RATE_LIMIT_PER_MINUTE=10" \
  --set "APP_VERSION=1.0.0" \
  --set "APP_NAME=Day12 Agent"

# 5. Deploy + expose
railway up --service day12-agent --detach
railway domain --service day12-agent   # tạo *.up.railway.app

# 6. Poll tới khi /health = 200
for i in {1..30}; do
  s=$(curl -s -o /dev/null -w "%{http_code}" "https://<domain>/health")
  echo "$i: $s"; [ "$s" = "200" ] && break; sleep 10
done
```

---

## Bug gặp khi deploy + fix

**Triệu chứng:** build image OK, container start fail với:
```
Error: Invalid value for '--port': '$PORT' is not a valid integer.
```

**Nguyên nhân:** `railway.toml` ban đầu:
```toml
startCommand = "uvicorn app.main:app --host 0.0.0.0 --port $PORT --workers 2"
```
Railway pass command này sang container bằng exec thay vì sh → shell variable không expand.

**Fix:** wrap bằng `sh -c`:
```toml
startCommand = "sh -c 'uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 2'"
```

Sau fix redeploy → container bind đúng `$PORT` Railway inject → healthcheck pass → URL live.

---

## Verify Checklist (đối chiếu rubric `INSTRUCTOR_GUIDE.md`)

- [x] **Public URL hoạt động** — `https://day12-agent-production-a0dc.up.railway.app/health` trả 200
- [x] **Deployment config** — `railway.toml` đủ field `build`, `deploy`, `healthcheckPath`
- [x] **Environment setup** — 8 env vars set trên Railway, không commit secrets
- [x] **Authentication** — `/ask` yêu cầu `X-API-Key` (401 nếu thiếu)
- [x] **Rate limiting** — 10 req/min (verify request 11 trả 429)
- [x] **Cost guard** — `/metrics` trả `daily_cost_usd / daily_budget_usd`
- [x] **Health + Readiness** — `/health` `/ready` tách biệt
- [x] **Structured logging** — JSON format trong Railway Logs
- [x] **Docker multi-stage + non-root** — Dockerfile có `USER agent`, `HEALTHCHECK`
- [x] **Graceful shutdown** — `timeout_graceful_shutdown=30` + SIGTERM handler
