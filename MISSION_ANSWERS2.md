# Day 12 Lab — Mission Answers (2)

> **Project:** Vinmec AI Agent — production chatbot Next.js 14 + Postgres
> **Deployment doc:** [`DEPLOYMENT2.md`](./DEPLOYMENT2.md)
> **Live URL:** https://lab12.hvan.it.com
> **Repo:** https://github.com/hvan128/Lab12_Vinmec_2A202600386
>
> **Student:** Ngô Hải Văn
> **Student ID:** 2A202600386
> **Date:** 2026-04-17

Các câu trả lời exercise Part 1-5 phân tích code trong lab materials
(`01-localhost-vs-production/` → `05-scaling-reliability/`) — giống như
`MISSION_ANSWERS1.md`, chỉ khác Part 3 (URL thật) + Part 6 (Vinmec thay vì
Python sample).

---

## Part 1: Localhost vs Production

### Exercise 1.1: Anti-patterns trong `01-localhost-vs-production/develop/app.py`

1. **Hardcode secrets** — `OPENAI_API_KEY = "sk-..."`, `DATABASE_URL = "postgresql://admin:password123@..."`. Push lên GitHub công khai → bot scan và abuse trong vài phút.
2. **Config không từ env** — `DEBUG = True`, `MAX_TOKENS = 500` hardcode, không thể đổi giữa dev/staging/prod.
3. **`print()` làm logging** — không level, không structured, log cả secret.
4. **Thiếu health check** — platform không biết khi nào restart.
5. **Port + host cố định** — `host="localhost"` không nhận request từ ngoài container; port không đọc từ `$PORT`.
6. **`reload=True` trong production** — tốn CPU, memory leak.
7. **Không xử lý SIGTERM** — rolling deploy drop request đang chạy.
8. **Không CORS / security headers** — thiếu `X-Content-Type-Options`, `X-Frame-Options`.

### Exercise 1.3: So sánh Develop vs Production

| Feature | Develop | Production | Tại sao quan trọng? |
|---------|---------|------------|---------------------|
| Config | Hardcode trong code | `os.getenv()` + dataclass Settings | Đổi env không cần build lại image (12-factor) |
| Secrets | `OPENAI_API_KEY="sk-..."` | `os.getenv("OPENAI_API_KEY")`, fail-fast nếu thiếu | Không lộ trên GitHub, rotate dễ |
| Host | `localhost` | `0.0.0.0` từ env `HOST` | `localhost` không nhận từ ngoài container |
| Port | Cố định `8000` | `int(os.getenv("PORT", "8000"))` | Cloud platform inject động |
| Logging | `print()` | JSON structured theo `DEBUG` env | Parse được Loki/Datadog |
| Health check | Không có | `/health` (liveness) + `/ready` (readiness) | Restart / drain traffic |
| Shutdown | Kill đột ngột | Lifespan + SIGTERM handler, timeout 30s | Không drop in-flight request |
| CORS | Không có | `CORSMiddleware` allowlist | Chặn cross-origin |
| State | In-process | Redis (khi scale) | Stateless horizontal scale |

**Áp dụng vào Vinmec:** Next.js app đọc mọi config qua `process.env.*`, có `.env.example` mẫu, `.env` trong `.gitignore`. Production secret set qua GitHub Secrets + docker-compose `env_file: .env`.

### Checkpoint 1 — ✅

---

## Part 2: Docker

### Exercise 2.1: Dockerfile basic questions

1. **Base image:** `python:3.11` full distribution, ~1 GB.
2. **Working directory:** `/app` (`WORKDIR /app`).
3. **COPY requirements.txt trước code:** Layer caching — nếu requirements không đổi, Docker reuse layer pip install. Build nhanh 10-50x khi chỉ sửa code.
4. **CMD vs ENTRYPOINT:**
   - `CMD` — default command, override được khi `docker run`.
   - `ENTRYPOINT` — cố định, arg sau `docker run` append vào.
   - Best practice: `ENTRYPOINT` cho binary + `CMD` cho default args.

### Exercise 2.3: Image size comparison

| Image | Size | Ghi chú |
|-------|------|---------|
| `06-lab-complete` single-stage python:3.11 | 1.67 GB | Full Python + build tools |
| `06-lab-complete` multi-stage python:3.11-slim | 262 MB | Slim + selective copy |
| **Vinmec app runtime (node:20-alpine multi-stage)** | **345 MB** | Next.js standalone + Prisma runtime |
| Vinmec migrate (full node_modules) | 1.05 GB | Tách image riêng, chỉ chạy migrate |

**Vinmec multi-stage:**
- Stage 1 `deps`: install full node_modules
- Stage 2 `builder`: run `npm run build` (Next.js standalone)
- Stage 3 `runtime`: chỉ copy `.next/standalone` + public + prisma runtime → 345 MB
- Stage 4 `migrate`: copy FULL node_modules (prisma CLI, tsx, effect, ...) cho `migrate deploy && db seed` → không bloat runtime image

### Exercise 2.4: Docker Compose architecture (Vinmec)

```
Cloudflare Tunnel (HTTPS)
         │
         ▼
    VPS :3003 → container :3000 (Next.js)
                    │
                    ├─► migrate (service_completed_successfully)
                    └─► db (Postgres 16, persistent volume)
```

Services liên lạc qua Docker internal DNS (`db:5432`). `depends_on.service_healthy` + `service_completed_successfully` đảm bảo start theo thứ tự: db healthy → migrate chạy + seed → app start.

### Checkpoint 2 — ✅

---

## Part 3: Cloud Deployment

### Exercise 3.1: Deployment (VPS + Cloudflare Tunnel thay Railway)

Dự án Vinmec chọn VPS + GitHub Actions CI/CD thay Railway vì:
- Có sẵn VPS CentOS (`root@157.66.100.59`)
- Tunnel miễn phí HTTPS, không mở port
- Học pipeline CI/CD thật (build image → push GHCR → SSH deploy → smoke test)
- Không giới hạn free tier

**LIVE:** https://lab12.hvan.it.com

**Stack deploy:**
```
Push main (GitHub)
   ↓ GitHub Actions
   ├── Build runtime image (345 MB) → push GHCR :latest + :sha
   ├── Build migrate image (1.05 GB) → push GHCR -migrate:latest
   ├── SSH root@157.66.100.59
   │     ↓ scp docker-compose.yml
   │     ↓ write .env atomically
   │     ↓ docker compose --profile tunnel pull
   │     ↓ docker compose --profile tunnel up -d
   │          (migrate auto-run trước app nhờ depends_on)
   └── Smoke test: curl /api/health → 200, /api/chat → 401
```

**Env vars inject runtime (từ GitHub Secrets):**
```
DATABASE_URL              postgresql://postgres:***@db:5432/vinmec_ai?schema=public
OPENAI_API_KEY            sk-proj-...
AGENT_API_KEY             <64-byte hex>
ADMIN_KEY                 vinmec-demo-2026
CLOUDFLARE_TUNNEL_TOKEN   eyJ...
RATE_LIMIT_PER_MINUTE     10
MONTHLY_BUDGET_USD        0.5
```

### Exercise 3.2: VPS + CF Tunnel vs Railway/Render

| | Railway/Render | VPS + CF Tunnel |
|---|---|---|
| Tự quản OS/Docker | ❌ Managed | ✅ Có kiểm soát hoàn toàn |
| HTTPS | ✅ Tự động | ✅ Qua Cloudflare Tunnel |
| Scale tự động | ✅ | ❌ Manual (tốt cho lab) |
| Chi phí | Free tier có giới hạn | VPS flat ~$5/tháng |
| Độ khó setup | ⭐ | ⭐⭐⭐ (SSH, firewall, Cloudflare) |
| Học được CI/CD thực tế | Partial | ✅ Full pipeline |

### Checkpoint 3 — ✅

---

## Part 4: API Security

### Exercise 4.1: API Key authentication (áp dụng vào Vinmec `lib/auth.ts`)

- **Kiểm tra ở đâu?** Middleware `verifyApiKey(req)` được gọi đầu `POST /api/chat`, `POST /api/metrics`. So sánh header `X-API-Key` với env `AGENT_API_KEY`.
- **Sai key?** `401 {"error":"Invalid API key."}`. Không key → `401 {"error":"Missing API key..."}`.
- **Rotate:** `gh secret set AGENT_API_KEY` → trigger GHA deploy lại (~5 phút).
- **Đặc biệt: Same-origin bypass** — nếu `Origin` header trùng `NEXT_PUBLIC_APP_URL` → bypass (UI hoạt động không cần key), nhưng rate-limit bucket = `ui-<IP>`.

Test (xem `DEPLOYMENT2.md` §3-4):
```bash
# No key → 401
curl -X POST https://lab12.hvan.it.com/api/chat -H "Content-Type: application/json" -d '{"messages":[],"userId":"t"}'

# Valid key → 200 streaming
curl -X POST https://lab12.hvan.it.com/api/chat \
  -H "X-API-Key: 1e93a43b..." -H "Content-Type: application/json" \
  -d '{"messages":[{"role":"user","content":"Xin chào"}],"userId":"user-an"}'
```

### Exercise 4.2: JWT flow (học từ `04-api-gateway/production/auth.py`)

Vinmec chưa dùng JWT (API key đủ cho scope lab), nhưng concept từ mẫu:

1. `POST /auth/token` — body `{username, password}` → server verify → `create_token()`:
   - Payload: `{sub, role, iat, exp: now+60min}`
   - Sign HS256 + `JWT_SECRET`
2. Client gắn `Authorization: Bearer <token>` mỗi request.
3. `verify_token()` decode + verify signature/expiry:
   - `ExpiredSignatureError` → 401
   - `InvalidTokenError` → 403

**Lợi thế JWT:** stateless (không query DB), chứa claims (role, tenant_id), expiry tự động. Dùng khi cần multi-tenant hoặc role-based access.

### Exercise 4.3: Rate limiting (Vinmec `lib/rateLimit.ts`)

- **Algorithm:** Sliding Window Counter — `Map<keyId, number[]>` chứa timestamp. Khi có request: pop timestamps > 60s, check `len < 10`.
- **Limit:** **10 req/min/bucket** (env `RATE_LIMIT_PER_MINUTE`).
- **Bucket key:**
  - External: 8 ký tự đầu API key
  - UI: `ui-<CF-Connecting-IP>` (tách user qua Cloudflare IP)
- **Response:** `429 Too Many Requests` + `Retry-After: 60`.

Test (verified LIVE):
```bash
for i in {1..12}; do curl ... ; done
# req 1-10: 200
# req 11-12: 429 (Retry-After: 60) ✅
```

### Exercise 4.4: Cost guard (Vinmec `lib/costGuard.ts`)

```typescript
const MONTHLY_BUDGET = parseFloat(process.env.MONTHLY_BUDGET_USD || "10");  // $0.5 ở prod
const INPUT_PRICE_PER_1K = 0.00015;   // gpt-4o-mini
const OUTPUT_PRICE_PER_1K = 0.0006;

function checkBudget(keyId: string, estTokens = 500): BudgetResult {
  const month = currentMonth();  // "YYYY-MM"
  const current = spend.get(keyId)?.spentUsd ?? 0;
  const estCost = (estTokens / 1000) * INPUT_PRICE_PER_1K;
  if (current + estCost > MONTHLY_BUDGET) return { ok: false, status: 402 };
  return { ok: true, spentUsd: current, remainingUsd: MONTHLY_BUDGET - current };
}

function recordUsage(keyId: string, input: number, output: number) {
  const cost = (input / 1000) * INPUT_PRICE_PER_1K + (output / 1000) * OUTPUT_PRICE_PER_1K;
  spend.get(keyId).spentUsd += cost;
}
```

**Flow trong `/api/chat`:**
1. Before stream: `checkBudget(keyId)` → 402 nếu vượt
2. After stream complete (fire-and-forget): `recordUsage(keyId, usage.inputTokens, usage.outputTokens)`

**Key insights:**
- Bucket theo **tháng** (key `YYYY-MM`) → reset đầu tháng
- Per-bucket budget (mỗi API key / mỗi IP UI)
- Check trước LLM (estimated) + record sau (actual) — chấp nhận sai lệch nhỏ
- `/api/metrics` (protected) cho audit: `{"month":"2026-04","monthlyBudget":0.5,"keys":[...]}`

### Checkpoint 4 — ✅

---

## Part 5: Scaling & Reliability

### Exercise 5.1: Health & Readiness endpoints (Vinmec `app/api/health|ready/route.ts`)

```typescript
// /api/health — liveness
export async function GET() {
  return NextResponse.json({
    status: "ok",
    version: VERSION,
    environment: ENVIRONMENT,
    uptime_seconds: Math.round((Date.now() - START_TIME) / 1000),
    timestamp: new Date().toISOString(),
  });
}

// /api/ready — readiness: check DB + OpenAI config
export async function GET() {
  const checks = {};
  let ok = true;
  try {
    await prisma.$queryRaw`SELECT 1`;
    checks.database = "ok";
  } catch (err) {
    ok = false;
    checks.database = String(err);
  }
  checks.openai_key = process.env.OPENAI_API_KEY ? "ok" : "missing";
  if (!process.env.OPENAI_API_KEY) ok = false;
  return NextResponse.json({ ready: ok, checks, timestamp: ... }, { status: ok ? 200 : 503 });
}
```

**Khác biệt:**
- `/health` — chỉ process còn chạy → 200. Fail → platform **restart**.
- `/ready` — check dep thật (DB, key). Fail → LB **drain traffic** (không restart).

### Exercise 5.2: Graceful shutdown (Vinmec Dockerfile)

```dockerfile
# tini làm PID 1 → forward SIGTERM → Node → Next.js
RUN apk add --no-cache tini
ENTRYPOINT ["/sbin/tini", "--"]
CMD ["node", "server.js"]
```

```yaml
# docker-compose.yml
app:
  stop_grace_period: 30s   # đợi 30s cho in-flight request hoàn thành
```

**Flow SIGTERM:**
1. Platform gửi SIGTERM
2. `tini` forward tới Node
3. Next.js standalone đóng HTTP server, drain connections
4. Prisma pool đóng (trả connection về Postgres)
5. Process exit
6. Nếu > 30s → SIGKILL

### Exercise 5.3: Stateless design (Vinmec dùng Postgres thay Redis)

**Anti-pattern:**
```typescript
const conversationHistory = new Map();  // ❌ in-memory
```

**Vinmec production:**
```typescript
// Lưu message vào Postgres qua Prisma
await prisma.feedback.create({ data: { userId, messageId, ... } });
await prisma.qualityScore.create({ data: { userId, query, answer, ... } });
```

Mỗi instance app đọc/ghi vào cùng Postgres → stateless. Kill instance bất kỳ, user vẫn tiếp tục session với instance khác (nếu scale). Demo hiện tại single instance nhưng design stateless sẵn sàng.

### Exercise 5.4: Load balancing

Vinmec hiện tại chạy **1 instance** trên VPS (đủ cho demo + tiết kiệm resource). Để scale:

```yaml
# docker-compose.yml
app:
  deploy:
    replicas: 3
# + add nginx upstream
```

Hoặc dùng cloud orchestrator (Kubernetes, ECS) tự scale theo load.

### Exercise 5.5: Stateless test

Manual test: gửi message qua user `user-an`, kiểm tra `prisma.feedback.findMany({where:{userId:"user-an"}})` → thấy lịch sử. Restart container → data vẫn còn (persistent Postgres volume). ✅

### Checkpoint 5 — ✅

---

## Part 6: Final Project (Vinmec AI Agent)

**Source:** https://github.com/hvan128/Lab12_Vinmec_2A202600386
**Báo cáo chi tiết:** `BAO_CAO_LAB12_VINMEC.md` trong repo

### 9/9 checklist Lab 12 — verified LIVE tại https://lab12.hvan.it.com

| # | Yêu cầu | Vinmec implementation | Evidence |
|---|---------|----------------------|----------|
| 1 | Dockerfile multi-stage < 500 MB | 3-stage runtime (345 MB) + 1 stage migrate riêng | `Dockerfile` |
| 2 | API key auth | `X-API-Key` middleware + same-origin UI bypass | `lib/auth.ts` |
| 3 | Rate limit 10 req/min | Sliding window per-key | `lib/rateLimit.ts` — verified req 11+ = 429 |
| 4 | Cost guard $/tháng | $0.5 monthly budget, 402 khi vượt | `lib/costGuard.ts` |
| 5 | `/health` + `/ready` | Liveness + readiness (DB + OpenAI check) | `app/api/health/`, `app/api/ready/` |
| 6 | Graceful shutdown SIGTERM | `tini` PID 1 + `stop_grace_period: 30s` | `Dockerfile`, `docker-compose.yml` |
| 7 | Stateless | Conversation/feedback trong Postgres | `prisma/schema.prisma` |
| 8 | Config env vars, không hardcode | `process.env.*` + GitHub Secrets + `.env.example` | `lib/config.*`, `.gitignore` |
| 9 | Public URL | https://lab12.hvan.it.com via Cloudflare Tunnel | Live |

### Extras vượt chuẩn

- ✅ **CI/CD tự động** — GitHub Actions build 2 images → push GHCR → SSH VPS → smoke test
- ✅ **Auto seed DB** — `prisma migrate deploy && db seed` mỗi deploy (idempotent upsert)
- ✅ **Separate migrate image** — full node_modules cho Prisma CLI, không bloat runtime image
- ✅ **Protected `/api/metrics`** — cost snapshot cho audit
- ✅ **Same-origin UI bypass** — UX + security balance (UI không cần key, external vẫn bắt buộc)
- ✅ **Post-deploy smoke test** — tự động verify 200 + 401 enforcement
- ✅ **Out-of-the-box `docker compose up --build`** — người clone chạy được ngay với 1 lệnh
- ✅ **HTTP/2 fallback cho Cloudflared** — khi VPS firewall block UDP/QUIC

### Thời gian deploy

Từ `git push main` đến production: **~5 phút**
- Build 2 Docker images: 3-4 phút (có GHA cache)
- SSH deploy + migrate + seed + app start: ~1 phút
- Smoke test: 10-60 giây

### Demo data

3 user giả lập (`user-an`, `user-binh`, `user-cuong`) + 30 doctor + 10 department + 7 branch + 30 FAQ + 10 preparation guide.

---

Xem thêm [`MISSION_ANSWERS1.md`](./MISSION_ANSWERS1.md) cho sample Python deploy Railway.
