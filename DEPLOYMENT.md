# Deployment Information — Day 12 Lab

> **Student:** Ngô Hải Vân (2A202600386)
> **Date:** 2026-04-17

---

## Public URL

**Production URL:** https://lab12.hvan.it.com

> Deploy bằng **GitHub Actions + VPS + Cloudflare Tunnel** (thay Railway/Render).
> Dự án triển khai là **Vinmec AI Agent** — xem chi tiết tại
> `https://github.com/hvan128/Lab12_Vinmec_2A202600386` và file `BAO_CAO_LAB12_VINMEC.md`.

---

## Platform

- **Hosting:** VPS CentOS `root@157.66.100.59` + Docker Compose
- **Edge/HTTPS:** Cloudflare Tunnel (không mở port, HTTPS auto)
- **Registry:** GHCR (`ghcr.io/hvan128/lab12_vinmec_2a202600386`)
- **CI/CD:** GitHub Actions → build → push GHCR → SSH deploy → smoke test
- **Reference:** Python/FastAPI sample trong `06-lab-complete/` chạy được standalone với `docker compose up`

---

## Demo API Key (dùng cho grader chấm Lab 12)

UI `https://lab12.hvan.it.com` **không cần key** (same-origin tự bypass).
Chỉ external test tools (curl/Postman) cần key:

```
AGENT_API_KEY=1e93a43bffdd1906cd5828943dd79b5ef5e99350103bcde32b34011f75ee945b
```

Bảo vệ bởi:
- Rate-limit 10 req/min/bucket
- Cost guard **$0.5 / tháng / bucket** (dễ trigger 402 khi test)
- Key rotate tự động sau deadline (17/4/2026) bằng `gh secret set`

---

## Test Commands

### 1. Health Check

```bash
curl https://lab12.hvan.it.com/api/health
```

Expected:
```json
{
  "status": "ok",
  "version": "<git-sha>",
  "environment": "production",
  "uptime_seconds": 42,
  "timestamp": "2026-04-17T09:00:00.000Z"
}
```

### 2. Readiness Check

```bash
curl https://lab12.hvan.it.com/api/ready
# → {"ready":true,"checks":{"database":"ok","openai_key":"ok"}}
```

### 3. API Test — Authentication Required

```bash
# Không có API key → 401
curl -X POST https://lab12.hvan.it.com/api/chat \
  -H "Content-Type: application/json" \
  -d '{"messages":[],"userId":"test"}'
# → {"error":"Missing API key. Include header: X-API-Key: <key>"}
```

### 4. API Test — With Valid Key

```bash
export API_KEY="1e93a43bffdd1906cd5828943dd79b5ef5e99350103bcde32b34011f75ee945b"

curl -X POST https://lab12.hvan.it.com/api/chat \
  -H "X-API-Key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"messages":[{"role":"user","content":"Xin chào, tôi cần đặt lịch khám"}],"userId":"user-an"}'
# → Streaming response từ LLM

# userId có sẵn trong seed: user-an, user-binh, user-cuong
```

Expected:
```json
{
  "question": "What is production deployment?",
  "answer": "<mock LLM response>",
  "model": "gpt-4o-mini",
  "timestamp": "2026-04-17T09:00:00+00:00"
}
```

### 5. Rate Limit Test (10 req/min)

```bash
for i in {1..15}; do
  curl -s -o /dev/null -w "req $i: %{http_code}\n" \
    -X POST https://lab12.hvan.it.com/api/chat \
    -H "X-API-Key: $API_KEY" \
    -H "Content-Type: application/json" \
    -d "{\"messages\":[{\"role\":\"user\",\"content\":\"ping\"}],\"userId\":\"t\"}"
done
# req 1-10: 200
# req 11-15: 429, Retry-After: 60
```

### 6. Metrics (protected endpoint)

```bash
curl -H "X-API-Key: $API_KEY" https://lab12.hvan.it.com/api/metrics
# → {"month":"2026-04","monthlyBudget":0.5,"keys":[{"key":"1e93a43b","spentUsd":0.0034}]}
```

### 7. Cost Guard demo (spam → 402 Payment Required)

```bash
# Gửi ~600 requests (chờ rate-limit reset giữa batch) → tổng > $0.5
for batch in {1..60}; do
  for i in {1..10}; do
    curl -s -o /dev/null -w "batch $batch req $i: %{http_code}\n" \
      -X POST https://lab12.hvan.it.com/api/chat \
      -H "X-API-Key: $API_KEY" -H "Content-Type: application/json" \
      -d '{"messages":[{"role":"user","content":"ping"}],"userId":"stress"}'
  done
  sleep 61  # đợi rate-limit window reset
done
# Sau khi chi vượt $0.5: HTTP 402 {"error":"Monthly budget exceeded ($0.5)..."}
```

---

## Environment Variables Set

| Variable | Value | Notes |
|----------|-------|-------|
| `PORT` | auto | Injected by Railway |
| `HOST` | `0.0.0.0` | Bind all interfaces |
| `ENVIRONMENT` | `production` | Disables `/docs` endpoint |
| `APP_VERSION` | `1.0.0` | |
| `AGENT_API_KEY` | *(32-byte hex, gen by `openssl rand -hex 32`)* | Secret |
| `JWT_SECRET` | *(32-byte hex)* | Secret |
| `RATE_LIMIT_PER_MINUTE` | `10` | |
| `MONTHLY_BUDGET_USD` | `0.5` | Giảm xuống để grader có thể trigger 402 |
| `OPENAI_API_KEY` | *(empty → mock LLM)* | Optional |
| `ALLOWED_ORIGINS` | `https://<frontend-domain>` | CORS |

---

## Deployment Steps

### Option A — Railway (chính)

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

### Option B — VPS + GitHub Actions CI/CD

1. VPS cài Docker, Nginx, certbot.
2. Thêm secret `SSH_PRIVATE_KEY`, `VPS_HOST`, `VPS_USER`, `AGENT_API_KEY`, `JWT_SECRET` vào GitHub repo.
3. Workflow `.github/workflows/deploy.yml` build Docker image, push registry, SSH vào VPS, `docker compose pull && up -d`.
4. Nginx proxy `agent.<domain>` → `localhost:8000`, Let's Encrypt HTTPS.

### Option C — Render

Push repo → Render Dashboard → Blueprint → Connect repo → Render đọc `render.yaml` → Deploy.
`generateValue: true` tự sinh `AGENT_API_KEY` và `JWT_SECRET`.

---

## Screenshots

- `screenshots/dashboard.png` — Railway/Render dashboard khi deploy thành công
- `screenshots/running.png` — service đang chạy, logs OK
- `screenshots/health-check.png` — `curl /health` → 200
- `screenshots/rate-limit.png` — spam request → 429 sau request thứ 21
- `screenshots/auth-401.png` — no API key → 401

---

## Production Readiness Verification

```bash
cd 06-lab-complete
python3 check_production_ready.py
```

Result: **20/20 checks passed (100%) 🎉 PRODUCTION READY**

- ✅ Dockerfile multi-stage + non-root + HEALTHCHECK + slim base
- ✅ `.dockerignore` covers `.env`, `__pycache__`
- ✅ `/health` + `/ready` endpoints
- ✅ API key authentication (X-API-Key header)
- ✅ Rate limiting (sliding window, 20 req/min default)
- ✅ Cost guard ($10/day budget, 80% warning)
- ✅ Graceful shutdown (SIGTERM + `timeout_graceful_shutdown=30s`)
- ✅ Structured JSON logging
- ✅ No hardcoded secrets
- ✅ `railway.toml` + `render.yaml` deploy configs
