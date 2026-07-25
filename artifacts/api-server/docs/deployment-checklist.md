# ApexQuant AI — Production Deployment Checklist

**System:** NSE Paper Trading Platform  
**Mode:** PAPER TRADING / RESEARCH ONLY — live broker order execution is disabled by design  
**Last updated:** 2026-07-25

---

## Pre-Deploy Checklist

### 1. Python Dependencies

Run the startup dependency validator before deploying:

```bash
cd /home/runner/workspace
uv run python artifacts/api-server/src/python/check_startup_deps.py
```

Expected output: `"success": true` with all packages listed.

If any packages are missing:
```bash
uv sync   # installs all deps declared in pyproject.toml
```

**Required packages in `pyproject.toml`:**

| Package | Version | Purpose |
|---------|---------|---------|
| `yfinance` | `>=1.5.1` | NSE market data via Yahoo Finance |
| `pandas` | `>=3.0.3` | DataFrame manipulation |
| `numpy` | `>=2.4.6` | Numerical calculations |
| `sqlalchemy[asyncio]` | `>=2.0` | Async ORM for PostgreSQL |
| `asyncpg` | `>=0.29` | PostgreSQL async driver |
| `psycopg2-binary` | `>=2.9.12` | Sync PostgreSQL driver |
| `kiteconnect` | `>=5.2.0` | Zerodha Kite broker client |
| `reportlab` | `>=4.0` | PDF report generation |
| `openpyxl` | `>=3.1` | Excel export |

---

### 2. Required Secrets (Replit Secrets)

Set these via **Tools → Secrets** in the Replit workspace. **Never commit values to source control.**

| Secret | Required | Where to get it |
|--------|----------|-----------------|
| `DATABASE_URL` | ✅ Always | Replit PostgreSQL — auto-set when DB is attached |
| `SESSION_SECRET` | ✅ Always | Generate: `openssl rand -hex 32` |
| `ZERODHA_API_KEY` | ✅ Always | Zerodha developer console |
| `ZERODHA_API_SECRET` | ✅ Always | Zerodha developer console |

---

### 3. Required Environment Variables (Frontend)

Set these via Replit Secrets for the deployed environment.

#### Dashboard (`artifacts/trading-dashboard`)

| Variable | Required | Value |
|----------|----------|-------|
| `VITE_API_BASE_URL` | ✅ Production | `https://<your-domain>/api-server/api` |
| `VITE_WS_BASE_URL` | No | Same as API unless SSE on different origin |

#### Mobile (`artifacts/trading-mobile`)

| Variable | Required | Value |
|----------|----------|-------|
| `EXPO_PUBLIC_API_BASE_URL` | ✅ EAS builds | `https://<your-domain>/api-server/api` |
| `EXPO_PUBLIC_DOMAIN` | Auto | Set by dev script via `$REPLIT_DEV_DOMAIN` |

---

### 4. CORS Configuration

| Variable | Required | Value |
|----------|----------|-------|
| `ALLOWED_ORIGINS` | Recommended | Comma-separated extra origins beyond `*.replit.dev` / `*.repl.co` |

Default behaviour: any `*.replit.dev` or `*.repl.co` origin is automatically allowed.

For custom domains, set:
```
ALLOWED_ORIGINS=https://yourdomain.com,https://app.yourdomain.com
```

---

### 5. Database

- PostgreSQL 16 is provisioned by Replit automatically.
- `DATABASE_URL` is auto-set when the DB is attached to the Replit project.
- Schema is auto-created by SQLAlchemy at startup (no manual migration needed for paper trading).

---

### 6. Pre-Deploy Validation Commands

Run these locally before every deploy:

```bash
# TypeScript typecheck — all packages must pass
pnpm exec tsc -b lib/api-client-react lib/api-zod lib/db artifacts/api-server
pnpm --filter trading-dashboard exec tsc --noEmit
pnpm --filter @workspace/trading-mobile exec tsc --noEmit

# Dashboard tests
cd artifacts/trading-dashboard && PORT=3000 BASE_PATH=/trading-dashboard pnpm exec vitest run

# Mobile tests
cd artifacts/trading-mobile && pnpm exec vitest run

# API server tests
cd artifacts/api-server && pnpm exec vitest run

# Python dependency check
uv run python artifacts/api-server/src/python/check_startup_deps.py
```

---

### 7. Post-Deploy Verification

After deploying, verify:

1. **Liveness probe:** `curl https://<domain>/api-server/api/health/live`
   - Expected: `{"status":"ok","uptime_s":N}`

2. **Readiness probe:** `curl https://<domain>/api-server/api/healthz`
   - Expected: `{"status":"ok"}`

3. **Python deps in prod:** `curl https://<domain>/api-server/api/live-data/health-v2`
   - Expected: `200` with `market.state` field
   - If `yfinance` missing: response will contain error mentioning `ModuleNotFoundError`

4. **CORS check:** Open browser DevTools on dashboard, confirm no CORS errors in console.

5. **SSE stream:** `curl -N https://<domain>/api-server/api/stream`
   - Expected: `data: {"type":"snapshot",...}` within 5 seconds

---

### 8. Known Production Blockers

| Blocker | Task | Resolution |
|---------|------|-----------|
| `yfinance` not installed in deployed env if `uv sync` not run | #100 | Run `uv sync` pre-deploy; verify with dep check script |
| `VITE_API_BASE_URL` not set | #114 | Set via Replit Secrets before deploy |
| `ALLOWED_ORIGINS` empty for custom domains | #114 | Set via Replit Secrets |
| Mobile `computeFreshness()` doesn't emit MARKET_CLOSED | #115 | Implemented in Task #115 |

---

### 9. Safety Guarantees (Do Not Remove)

These are hard-coded safety properties maintained by design:

- **No live trading:** `paper_mode: true` is enforced at the portfolio config level. Live broker order submission is gated by RC-8 controls requiring explicit enable + confirmation token.
- **AI advisory only:** AI signals are flagged `advisory_only: true`. No autonomous order placement.
- **RC-7/RC-8 controls:** Kill switch, position limits, and daily loss limits are enforced in Python. Do not disable.
- **Credential masking:** API keys are never returned in any API response. The `GET /api/broker/credentials` route returns only the key prefix.
