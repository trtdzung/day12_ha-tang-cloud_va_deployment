# Deployment 1 — `06-lab-complete/` (Python/FastAPI sample)

> **Student:** Ngô Hải Văn (2A202600386)
> **Date:** 2026-04-17
> **Code:** [`./06-lab-complete/`](./06-lab-complete)

Dự án Python FastAPI mẫu đi kèm bài giảng Lab 12 — reference implementation
tuân thủ đầy đủ 11 items trong production readiness checklist.

---

## Tổng quan

Agent FastAPI đơn giản dùng **mock LLM** (không cần OpenAI API key), chạy
standalone bằng `docker compose up`. 
**Stack:**
- Python 3.11 + FastAPI + uvicorn
- **Redis-backed state** (sliding-window rate limit, INCRBYFLOAT cost guard, conversation history per user)
- Dockerfile multi-stage → image 272 MB
- Config options sẵn sàng deploy Railway hoặc Render

---

## Live deploy (Railway)

- **Public URL:** https://day12-agent-production-a0dc.up.railway.app
- **Swagger UI:** https://day12-agent-production-a0dc.up.railway.app/docs
- **Redis:** Railway-managed instance, linked vào `day12-agent` service qua `REDIS_URL=${{Redis.REDIS_URL}}`
- **CI/CD:** GitHub Actions `.github/workflows/deploy-railway.yml` — push `main` → auto deploy + smoke test (1m24s)
- **API key:** lấy bằng `railway variables --service day12-agent --kv | grep AGENT_API_KEY`

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
BASE=https://day12-agent-production-a0dc.up.railway.app
API_KEY=<AGENT_API_KEY-từ-railway-variables>

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

Result: **20/20 checks passed (100%) 🎉 PRODUCTION READY**

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

URL public: https://day12-agent-production-a0dc.up.railway.app (kèm Swagger `/docs`).
CI/CD qua GitHub Actions auto deploy mỗi lần push `main`. Xem run:
https://github.com/hvan128/2A202600386_NgoHaiVan_LAB12/actions

Dự án chính (**Vinmec AI Agent** — UI + Postgres + streaming LLM thật) xem tiếp `DEPLOYMENT2.md`.
