# Deployment 1 — `06-lab-complete/` (Python/FastAPI sample)

> **Student:** Trần Tiến Dũng -2A202600314
> **Date:** 2026-04-17
> **Code:** [`./06-lab-complete/`](./06-lab-complete)

---

## Tổng quan

Agent FastAPI đơn giản dùng mock LLM (không cần OpenAI API key), chạy
standalone bằng `docker compose up`. 
**Stack:**
- Python 3.11 + FastAPI + uvicorn
- Redis-backed state (sliding-window rate limit, INCRBYFLOAT cost guard, conversation history per user)
- Dockerfile multi-stage → image 272 MB
- Config options sẵn sàng deploy Railway hoặc Render

---

## Live deploy (Railway)

- **Public URL:** https://your-agent.railway.app
- **Swagger UI:** https://your-agent.railway.app/docs
- **Redis:** Railway-managed instance, linked vào `day12-agent` service qua `REDIS_URL=${{Redis.REDIS_URL}}`
- **LLM:** OpenAI `gpt-4o-mini` thật (không còn mock) — `OPENAI_API_KEY` set server-side, grader không cần
- **CI/CD:** GitHub Actions `.github/workflows/deploy-railway.yml` — push `main` → auto deploy + smoke test (~1m)

---

## Demo API Key (dùng cho grader chấm Lab 12)

Key dưới đây để test `/ask`, `/metrics`, `/history/{user_id}` qua curl/Postman/Swagger.
Các endpoint public (`/health`, `/ready`, `/docs`) không cần key.

```
AGENT_API_KEY=your-api-key-here
```

Cách dùng với Swagger UI:
1. Mở https://your-agent.railway.app/docs
2. Click nút **Authorize** ở góc phải
3. Paste key vào ô `ApiKeyHeader (X-API-Key)` → **Authorize** → **Close**
4. Click "Try it out" trên `POST /ask` hoặc `GET /metrics` → điền body → **Execute**

Bảo vệ khỏi abuse:
- **Rate limit** — 20 req/min/user (Redis sorted set sliding window, consistent qua mọi instance)
- **Cost guard** — $10/day global (gpt-4o-mini ~$0.0002/req → đủ ~50k req/ngày)
- **Key rotate** — sau deadline 17/4/2026:
  ```bash
  railway variables --service day12-agent --set "AGENT_API_KEY=$(openssl rand -hex 32)"
  ```

---

## Chạy local

```bash
cd 06-lab-complete
cp .env.example .env.local   # điền các giá trị nếu cần
docker compose up            # agent + redis
```

Test:
```bash
curl http://localhost:8000/health
# → {"status":"ok","version":"1.0.0","uptime_seconds":...}

API_KEY=$(grep AGENT_API_KEY .env.local | cut -d= -f2)
curl -X POST http://localhost:8000/ask \
  -H "X-API-Key: $API_KEY" -H "Content-Type: application/json" \
  -d '{"question":"What is production deployment?"}'
```

---

## Deploy — 3 options có sẵn

### Option A — Railway (nhanh nhất, < 5 phút)

```bash
cd 06-lab-complete
npm i -g @railway/cli
railway login
railway init
railway variables set AGENT_API_KEY=$(openssl rand -hex 32)
railway variables set JWT_SECRET=$(openssl rand -hex 32)
railway variables set ENVIRONMENT=production
railway variables set RATE_LIMIT_PER_MINUTE=20
railway variables set DAILY_BUDGET_USD=10
railway up
railway domain  # → public URL
```

Config file: [`railway.toml`](./06-lab-complete/railway.toml)

### Option B — Render (Blueprint YAML)

1. Push repo lên GitHub
2. Render Dashboard → **New** → **Blueprint** → connect repo
3. Render đọc `render.yaml` tự động
4. Set `OPENAI_API_KEY` trong dashboard (optional — không set thì dùng mock LLM)
5. `AGENT_API_KEY` + `JWT_SECRET` auto-sinh (`generateValue: true`)

Config file: [`render.yaml`](./06-lab-complete/render.yaml)

### Option C — GCP Cloud Run (production-grade)

Tham khảo `03-cloud-deployment/production-cloud-run/` để biết
`cloudbuild.yaml` + `service.yaml` CI/CD pipeline.

---

## Test commands

```bash
BASE=https://your-agent.railway.app
API_KEY=your-secret-key-here

# 1. Health — phải thấy storage=redis, redis_connected=true
curl $BASE/health

# 2. Ready — 200 + {"ready":true}
curl $BASE/ready

# 3. Auth required — 401
curl -X POST $BASE/ask -H "Content-Type: application/json" -d '{"question":"Hello"}'

# 4. Conversation history — cùng user_id nhiều turn
curl -X POST $BASE/ask -H "X-API-Key: $API_KEY" -H "Content-Type: application/json" \
  -d '{"question":"Tôi tên Alice","user_id":"alice"}'
curl -X POST $BASE/ask -H "X-API-Key: $API_KEY" -H "Content-Type: application/json" \
  -d '{"question":"Docker là gì?","user_id":"alice"}'

# Xem lịch sử
curl -H "X-API-Key: $API_KEY" $BASE/history/alice
# → {"user_id":"alice","messages":[{role,content,ts},...],"count":4,"storage":"redis"}

# Xóa lịch sử
curl -X DELETE -H "X-API-Key: $API_KEY" $BASE/history/alice

# 5. Rate limit — 20 req/min/user (Redis-backed, consistent qua nhiều instance)
for i in {1..25}; do
  curl -s -o /dev/null -w "req $i: %{http_code}\n" \
    -X POST $BASE/ask \
    -H "X-API-Key: $API_KEY" -H "Content-Type: application/json" \
    -d "{\"question\":\"test $i\",\"user_id\":\"ratetest\"}"
done
# Expected: req 1-20 = 200, req 21-25 = 429

# 6. Metrics — tổng request + cost từ Redis
curl -H "X-API-Key: $API_KEY" $BASE/metrics
# → {"storage":"redis","total_requests":...,"daily_cost_usd":...,"budget_used_pct":...}
```

---

## Environment Variables

| Variable | Default | Notes |
|----------|---------|-------|
| `PORT` | `8000` (Railway/Render inject tự động) | |
| `HOST` | `0.0.0.0` | Bind all interfaces |
| `ENVIRONMENT` | `development` | Set `production` để disable `/docs` |
| `APP_VERSION` | `1.0.0` | |
| `AGENT_API_KEY` | — | Sinh bằng `openssl rand -hex 32` |
| `JWT_SECRET` | — | Sinh bằng `openssl rand -hex 32` |
| `RATE_LIMIT_PER_MINUTE` | `20` | |
| `DAILY_BUDGET_USD` | `5.0` | Cost guard threshold |
| `OPENAI_API_KEY` | *(empty → mock LLM)* | Optional |
| `ALLOWED_ORIGINS` | `*` | CORS — siết lại trong prod |
| `REDIS_URL` | — | Enable Redis-backed state; Railway auto-inject qua `${{Redis.REDIS_URL}}` |
| `EXPOSE_DOCS` | `false` | Set `true` ở production để bật Swagger UI `/docs` |

---

## Production Readiness — 20/20

```bash
cd 06-lab-complete
python3 check_production_ready.py
```

Result: **20/20 checks passed**

- ✅ Dockerfile multi-stage + non-root + `HEALTHCHECK` + slim base
- ✅ `.dockerignore` covers `.env`, `__pycache__`
- ✅ `/health` + `/ready` endpoints
- ✅ API key authentication (`X-API-Key` header)
- ✅ Rate limiting (sliding window, 20 req/min/user — **Redis sorted set**, consistent qua mọi instance)
- ✅ Cost guard ($5/day budget — **Redis INCRBYFLOAT** với daily TTL)
- ✅ Conversation history per user — **Redis list**, TTL 24h, giữ 20 msg gần nhất
- ✅ Graceful shutdown (SIGTERM + `timeout_graceful_shutdown=30s`)
- ✅ Structured JSON logging
- ✅ No hardcoded secrets
- ✅ `railway.toml` + `render.yaml` deploy configs sẵn

---

## Sample này đã deploy thật

URL public: https://your-agent.railway.app (kèm Swagger `/docs`).
