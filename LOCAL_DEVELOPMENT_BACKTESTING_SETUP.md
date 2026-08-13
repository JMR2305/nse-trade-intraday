# Local Development & Backtesting Setup Guide

> **ApexQuant AI — NSE Trading Platform**
>
> This guide lets operators run heavy backtests on their own hardware while leaving the Replit production deployment completely untouched. No application logic, thresholds, or database records are changed. This is a reference document only.

---

## Table of Contents

1. [Current App Architecture](#1-current-app-architecture)
2. [Exact Local Setup Steps](#2-exact-local-setup-steps)
3. [Database Options](#3-database-options-a-b-c)
4. [Safety Guarantees](#4-safety-guarantees)
5. [Backtest Usage](#5-backtest-usage)
6. [Sync Strategy](#6-sync-strategy)
7. [Recommended Hardware](#7-recommended-hardware)
8. [Quick Reference Card](#8-quick-reference-card)

---

## 1. Current App Architecture

### 1.1 Service Map

| Service | Location | Port | Notes |
|---------|----------|------|-------|
| **API Server** | `artifacts/api-server/` | `$PORT` (default 8080) | Express/TypeScript; builds via esbuild to `dist/index.mjs` |
| **Trading Dashboard** | `artifacts/trading-dashboard/` | `$PORT` (default 3000) | Vite + React |
| **Trade Hub** | `artifacts/trading-document-hub/` | `$PORT` | Next.js |
| **Mobile App** | `artifacts/trading-mobile/` | Expo dev server | Expo React Native |
| **Python Worker** | `artifacts/api-server/src/python/main.py` | — | No persistent server; spawned per request |
| **Backtest Scheduler** | `artifacts/api-server/src/lib/backtestScheduler.ts` | — | Ticks every 2 min via `bt_queue_tick_cmd.py` |

### 1.2 Frontend Services

- **Vite + React Dashboard** (`artifacts/trading-dashboard/`): Primary operator dashboard. `pnpm run dev` starts Vite's dev server. In production the build serves via the Express static middleware; locally you need a proxy configured for `/api → localhost:8080`.
- **Next.js Trade Hub** (`artifacts/trading-document-hub/`): Document-centric views. `pnpm run dev` starts the Next.js server.
- **Expo Mobile** (`artifacts/trading-mobile/`): React Native app. `pnpm run dev` starts the Expo development server; use Expo Go or a simulator.

### 1.3 API Server

The API server is an **Express/TypeScript** application located in `artifacts/api-server/`.

- **Port**: controlled by the `PORT` environment variable. The server will refuse to start without it.
- **Build**: esbuild bundles TypeScript to `dist/index.mjs` (`node build.mjs`).
- **Dev start**: `pnpm run dev` runs `build → start` in sequence. There is **no hot reload** — changes require a rebuild.
- **Start (after build)**: `node --enable-source-maps ./dist/index.mjs`

### 1.4 Python Worker

The Python layer has **no persistent server**. Every API call that needs Python logic spawns a child process:

```
Node.js (Express route)
  └── child_process.spawn(PYTHON_BIN, ["main.py", command, json_args])
        └── main.py dispatches on sys.argv[1]
              └── outputs JSON to stdout → Node.js parses it
```

The Python binary is resolved in order by `src/lib/python-env.ts`:

1. `.python-exe` (written by deploy-build.sh at production build time)
2. `.venv/bin/python3` (workspace virtual environment — preferred for local dev)
3. `.pythonlibs/bin/python3` (Replit's Nix-managed Python — fallback on Replit)
4. `.pythonlibs/../bin/python3` (alternate Replit path)
5. `python3` (system fallback)

The Python source directory (`PYTHON_DIR`) is resolved to whichever of `src/python/` or `artifacts/api-server/src/python/` contains `main.py`.

### 1.5 Backtest Scheduler

`src/lib/backtestScheduler.ts` runs automatically when the API server starts.

- Ticks every **2 minutes**.
- Each tick spawns `bt_queue_tick_cmd.py` (lightweight — imports only `psycopg2`, ~23 ms cold start). `main.py` is **not** used for scheduler ticks to avoid the 13–25 s pandas+yfinance import overhead on cold starts.
- The scheduler advances `QUEUED → PENDING → spawned worker` and marks stale `RUNNING` runs as `STALE`.
- **Disable with**: `DISABLE_BACKTEST_SCHEDULER=true` (set in your `.env`).

### 1.6 Database Architecture

One PostgreSQL instance, two schema managers:

| Manager | Tables Managed | How Tables Are Created |
|---------|---------------|----------------------|
| **Drizzle ORM** (`lib/db/`) | `paper_portfolio`, `paper_trades`, `signals_cache`, `signal_snapshots`, `push_subscriptions`, `alert_deliveries` | `pnpm --filter @workspace/db run push` |
| **Python / SQLAlchemy** | `phase20_*`, `phase23_*`, `backtest_runs`, `backtest_trades`, `backtest_ledger`, `pipeline_events`, and many others | `CREATE TABLE IF NOT EXISTS` on first use |

`lib/db/protected-tables.json` prevents Drizzle from touching Python-managed tables. Never run `drizzle-kit drop` or unguarded DDL against production.

### 1.7 Environment Variables Reference

| Variable | Required | Notes |
|----------|----------|-------|
| `PORT` | ✅ | API server listen port. Server refuses to start without it. |
| `DATABASE_URL` | ✅ | PostgreSQL connection string (asyncpg-compatible, e.g. `postgresql://...`). |
| `SESSION_SECRET` | ✅ | Express session secret. Generate with `openssl rand -hex 32`. |
| `ZERODHA_API_KEY` | ⚠️ Optional for paper/backtest | Zerodha developer console. Without it, `MockBrokerClient` is used. |
| `ZERODHA_API_SECRET` | ⚠️ Optional for paper/backtest | Same as above. |
| `INTRADAY_DATABASE_URL` | Optional | Async URL for the intraday-trading-bot's separate database. |
| `INTRADAY_DATABASE_URL_SYNC` | Optional | Sync URL (psycopg2) for Alembic migrations in the bot. |
| `JWT_SECRET_KEY` | Intraday bot only | JWT HS256 signing key. |
| `TRADING_MODE` | Optional | `PAPER` (default) or `LIVE`. Always keep `PAPER` locally. |
| `LIVE_EXECUTION_ENABLED` | 🚫 Must be `false` | Controls the ExecutionAgent gate. See [Section 4](#4-safety-guarantees). |
| `VITE_API_BASE_URL` | Dashboard (production) | Full base URL of the API. Leave unset for local dev with proxy. |
| `EXPO_PUBLIC_API_BASE_URL` | Mobile (EAS builds) | Full base URL including `/api`. |
| `DISABLE_BACKTEST_SCHEDULER` | Optional | Set `true` to stop the 2-min tick loop during debugging. |

### 1.8 Zerodha / Kite

`kiteconnect>=5.2.0` is installed as a root Python dependency (always available). The broker client (`broker_client.py`) auto-detects credentials:

- **With `ZERODHA_API_KEY` + `ZERODHA_ACCESS_TOKEN`**: uses the real Kite client (read-only by default).
- **Without credentials**: automatically uses `MockBrokerClient` — safe, no network calls.

Zerodha credentials are **not needed** for historical candle data or backtesting. Yahoo Finance provides all historical OHLCV data.

### 1.9 Market Data / yfinance

All historical candles are fetched from **Yahoo Finance** via `yfinance>=1.5.1` using the `.NS` suffix (e.g., `RELIANCE.NS`). No API key is needed.

**Fallback**: if yfinance fails (rate limit, network error), `market_data_engine.py` falls back to **deterministic synthetic candles** labelled `source='mock'`. These are clearly marked in every response. **Never use mock-source candle data for real analysis or production decisions.**

---

## 2. Exact Local Setup Steps

### 2.1 Prerequisites

#### Node.js

No specific version is pinned in this project (no `.nvmrc` or `engines` field). Use the latest LTS (22.x):

```bash
# Using nvm
curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.39.7/install.sh | bash
nvm install --lts
nvm use --lts

# Or using fnm (faster)
curl -fsSL https://fnm.vercel.app/install | bash
fnm install --lts
fnm use lts-latest
```

#### pnpm

The root `package.json` `preinstall` script rejects npm and yarn installs. The lockfile format is pnpm 9.0:

```bash
corepack enable
corepack prepare pnpm@latest --activate
```

Verify: `pnpm --version` (should be 9.x or later).

#### Python 3.12

The root `pyproject.toml` requires `>=3.11`; the intraday bot requires `>=3.12`. Use **Python 3.12** for both.

```bash
# macOS (Homebrew)
brew install python@3.12

# Ubuntu / Debian
sudo apt update && sudo apt install python3.12 python3.12-venv python3.12-dev

# Verify
python3.12 --version
```

#### uv (Python package manager)

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
# Restart shell or source the updated PATH
```

### 2.2 Clone and Install

```bash
# Clone the repository
git clone <your-repo-url> apexquant
cd apexquant

# Install all Node.js packages (workspace-wide)
pnpm install
```

### 2.3 Python Virtual Environment

Run these commands from the **workspace root** (where `pyproject.toml` lives):

```bash
# Create the virtual environment with Python 3.12
uv venv .venv --python python3.12

# Install all Python dependencies from uv.lock
uv sync

# Verify — should show Python 3.12.x
.venv/bin/python3 --version
```

The `python-env.ts` resolver automatically finds `.venv/bin/python3` as its second priority, so the API server will use this venv without any additional configuration.

### 2.4 Build Shared TypeScript Libraries

```bash
# From workspace root
pnpm run typecheck:libs
```

This builds the shared packages (`lib/api-zod`, `lib/api-client-react`, `lib/db`) via TypeScript project references. Must be run before starting any artifact.

### 2.5 Configure the API Server `.env`

Create `artifacts/api-server/.env`:

```bash
# ── Required ────────────────────────────────────────────────
PORT=8080
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/apexquant_local
SESSION_SECRET=<generate with: openssl rand -hex 32>

# ── Safety: must always be false locally ─────────────────────
LIVE_EXECUTION_ENABLED=false
TRADING_MODE=PAPER

# ── Optional: disable background scheduler during debugging ──
# DISABLE_BACKTEST_SCHEDULER=true

# ── Zerodha (not needed for paper/backtest mode) ─────────────
# ZERODHA_API_KEY=
# ZERODHA_API_SECRET=
```

> **Note**: `ZERODHA_API_KEY` and `ZERODHA_API_SECRET` are optional for paper trading and backtesting. Omitting them causes the system to use `MockBrokerClient` automatically.

### 2.6 Start the API Server

```bash
cd artifacts/api-server
PORT=8080 pnpm run dev
```

The `dev` script runs `build → start`. On subsequent restarts after code changes, run it again (no hot reload).

You should see log lines like:
```
[python-env] PYTHON_DIR=...  BIN=.../.venv/bin/python3
Server listening { port: 8080 }
Backtest queue scheduler started
```

### 2.7 Start the Trading Dashboard

```bash
cd artifacts/trading-dashboard
pnpm run dev
```

**Local Vite proxy for API calls**: The dashboard expects API calls to go through its own server. For local development, you need a proxy from `/api → localhost:8080`. Add this to `artifacts/trading-dashboard/vite.config.ts` temporarily (do **not** commit this change — it is local-only):

```typescript
// Local development only — do NOT commit
server: {
  port: 3000,
  proxy: {
    '/api': {
      target: 'http://localhost:8080',
      changeOrigin: true,
    },
  },
},
```

Alternatively, set `VITE_API_BASE_URL=http://localhost:8080/api` in `artifacts/trading-dashboard/.env.local`.

### 2.8 Run Python Workers Directly (Debugging)

You can invoke any Python command directly without the Node.js layer:

```bash
cd artifacts/api-server/src/python

# Activate the venv
source ../../../.venv/bin/activate   # from workspace root: source .venv/bin/activate

# Portfolio state
python main.py portfolio

# Signals / scan cache
python main.py signals

# List backtest runs
python main.py backtest_runs '{}'

# Start a backtest (returns run_id immediately)
python main.py backtest_start '{"symbols":["RELIANCE.NS","TCS.NS"],"interval":"15m","start":"2024-01-01","end":"2024-03-01","capital":100000}'

# Check run status
python main.py backtest_status '{"run_id":"<run_id>"}'
```

All commands output JSON to stdout. Errors output `{"error": "..."}` with exit code 1.

### 2.9 Optional: Intraday Trading Bot Setup

The `intraday-trading-bot/` is a separate FastAPI service with its own PostgreSQL database and virtual environment. It is **not required** for dashboard or backtest usage.

```bash
cd intraday-trading-bot
uv venv .venv --python python3.12
uv sync
cp .env.example .env
# Edit .env with your local DATABASE_URL and JWT_SECRET_KEY
```

---

## 3. Database Options (A, B, C)

### Option A — Same Remote Neon DB (Not Recommended for Backtesting)

Copy the `DATABASE_URL` from Replit's Secrets panel and paste it into your local `.env`.

| | |
|---|---|
| **Pros** | Zero setup; local UI reads live data immediately |
| **Cons** | Local backtests write to the **production database**; network latency adds to already-slow scans; no isolation; one crash can corrupt production paper trades |

**Do not use Option A for heavy backtesting.** Backtest tables grow quickly and you risk polluting the production `phase23_*` and `backtest_*` tables with local experiment runs.

---

### Option B — Local Postgres Copy ✅ RECOMMENDED

This is the recommended approach for all backtesting work.

#### Install PostgreSQL

```bash
# macOS
brew install postgresql@16
brew services start postgresql@16

# Ubuntu / Debian
sudo apt install postgresql-16
sudo systemctl start postgresql
```

#### Create the database

```bash
createdb apexquant_local
```

#### Apply Drizzle migrations (TypeScript-managed tables)

```bash
DATABASE_URL=postgresql://postgres@localhost:5432/apexquant_local \
  pnpm --filter @workspace/db run push
```

Python-managed tables (`phase20_*`, `phase23_*`, `backtest_*`, `pipeline_events`, etc.) are created automatically via `CREATE TABLE IF NOT EXISTS` the first time any Python command runs. No manual migration needed.

#### Update your `.env`

```bash
DATABASE_URL=postgresql://postgres@localhost:5432/apexquant_local
```

| | |
|---|---|
| **Pros** | Fully isolated; no network latency; free to wipe and restart; fast Postgres (no TLS round trips) |
| **Cons** | Starts with empty paper portfolio and no historical paper trades |

**Why Option B is recommended**: Backtests write hundreds of rows per run. Local Postgres is 5–10× faster than Neon for write-heavy workloads, the data is isolated from production, and you can `DROP DATABASE apexquant_local` to start fresh without any risk.

---

### Option C — Separate Local Research DB

For parallel experiments, use two local databases:

```bash
createdb apexquant_dev       # ongoing development, paper trading state
createdb apexquant_research  # isolated backtest experiments
```

Switch between them by changing `DATABASE_URL` in your shell:

```bash
# Development work
export DATABASE_URL=postgresql://postgres@localhost:5432/apexquant_dev

# Backtest research
export DATABASE_URL=postgresql://postgres@localhost:5432/apexquant_research
```

| | |
|---|---|
| **Pros** | Cleanest isolation; paper trading history stays pristine while backtest data grows freely |
| **Cons** | Two databases to maintain; must remember which is active |

Use Option C when running many independent backtest scenarios that you want to compare, or when you need to keep your dev paper trading history intact.

---

## 4. Safety Guarantees

### 4.1 `LIVE_EXECUTION_ENABLED=false` — The Primary Gate

**Always set `LIVE_EXECUTION_ENABLED=false` in your local `.env`.** This is the most critical safety control.

What it blocks:
- The `ExecutionAgent` gates every order attempt by reading this flag before calling any broker API.
- With `LIVE_EXECUTION_ENABLED=false`, the `ExecutionAgent` will never call `KiteConnect.place_order()` or any other real order API, regardless of what signals the pipeline generates.
- Even if you have valid Zerodha credentials set, no real order will reach the broker.

**Under no circumstance should you set `LIVE_EXECUTION_ENABLED=true` in a local development environment.** That flag is strictly for supervised production deployments with all safety checks independently verified.

### 4.2 MockBrokerClient — Automatic Fallback

If `ZERODHA_API_KEY` or `ZERODHA_ACCESS_TOKEN` is absent from the environment, `broker_client.py` instantiates `MockBrokerClient` automatically:

- Returns simulated account data (zero holdings, mock margins).
- Logs all "order" calls as dry-run events — nothing reaches any broker.
- No network connections to Zerodha are made.

This is the default behaviour locally when credentials are not configured.

### 4.3 Isolated Backtest Ledger

Backtest runs use a completely separate database ledger:

| Table | Purpose | Touched by backtests? |
|-------|---------|----------------------|
| `paper_portfolio` | Live paper trading portfolio | ❌ Never |
| `paper_trades` | Live paper trade history | ❌ Never |
| `phase20_paper_trades` | Phase 20 canonical paper ledger | ❌ Never |
| `backtest_trades` | Backtest trade records | ✅ Yes |
| `backtest_ledger` | Backtest P&L ledger | ✅ Yes |
| `backtest_runs` | Run metadata and status | ✅ Yes |

A backtest run has its own `run_id` and writes exclusively to the `backtest_*` tables. The live paper portfolio is never touched.

### 4.4 Mock Candle Data Warning

When yfinance fails (rate limit, network error), `market_data_engine.py` returns synthetic candles labelled `source='mock'`. These are:
- Deterministic (seeded by symbol + timestamp, so reproducible).
- Structurally valid OHLCV bars.
- **Not real market data.** They must never be used for analysis, model training, or production decisions.

Always check the `source` field in market data responses. Any result with `"source": "mock"` should be discarded.

### 4.5 Pre-flight Safety Check

Before starting any backtest session, verify the safety gate is active:

```bash
curl -s http://localhost:8080/api/settings | python3 -m json.tool | grep -i live_execution
```

Expected output should include `"live_execution_enabled": false` (or the field should be absent, meaning the default `false` applies).

---

## 5. Backtest Usage

### 5.1 Trigger a Backtest Run

**Via the API (recommended)**:

```bash
curl -s -X POST http://localhost:8080/api/backtest/run \
  -H "Content-Type: application/json" \
  -d '{
    "symbols": ["RELIANCE.NS", "TCS.NS", "INFY.NS", "HDFCBANK.NS", "ICICIBANK.NS"],
    "interval": "15m",
    "start": "2024-01-01",
    "end": "2024-03-01",
    "capital": 100000
  }' | python3 -m json.tool
```

The response includes a `run_id`. Backtest runs are **detached** — the API returns immediately and the worker runs in the background.

**Via universe alias**:

```bash
curl -s -X POST http://localhost:8080/api/backtest/run \
  -H "Content-Type: application/json" \
  -d '{
    "universe": "nifty50",
    "interval": "1d",
    "start": "2024-01-01",
    "end": "2024-12-31",
    "capital": 500000
  }' | python3 -m json.tool
```

**Via Python CLI** (no Node.js layer):

```bash
python main.py backtest_start '{"symbols":["RELIANCE.NS","TCS.NS","INFY.NS"],"interval":"15m","start":"2024-01-01","end":"2024-03-01","capital":100000}'
```

### 5.2 5-Symbol Quick Validation Run

Use this for quick end-to-end pipeline validation:

```json
{
  "symbols": ["RELIANCE.NS", "TCS.NS", "INFY.NS", "HDFCBANK.NS", "ICICIBANK.NS"],
  "interval": "15m",
  "start": "2024-01-01",
  "end": "2024-01-31",
  "capital": 100000
}
```

Expected time: ~6 minutes on warm cache (recommended hardware). See [Section 7](#7-recommended-hardware) for timing guidance.

### 5.3 20-Symbol Extended Run

```json
{
  "symbols": [
    "RELIANCE.NS", "TCS.NS", "INFY.NS", "HDFCBANK.NS", "ICICIBANK.NS",
    "HINDUNILVR.NS", "ITC.NS", "KOTAKBANK.NS", "LT.NS", "AXISBANK.NS",
    "SBIN.NS", "BAJFINANCE.NS", "WIPRO.NS", "HCLTECH.NS", "MARUTI.NS",
    "NESTLEIND.NS", "ULTRACEMCO.NS", "TITAN.NS", "ASIANPAINT.NS", "SUNPHARMA.NS"
  ],
  "interval": "15m",
  "start": "2024-01-01",
  "end": "2024-03-31",
  "capital": 500000
}
```

> ⚠️ **TATAMOTORS demerger note**: `TATAMOTORS.NS` was split into `TMPV.NS` (passenger vehicles) and `TMCV.NS` (commercial vehicles). Do not include `TATAMOTORS.NS` in backtests. The NIFTY 50 universe now has 51 constituents.

**Or use the universe alias**:
```json
{
  "universe": "nifty50",
  "interval": "15m",
  "start": "2024-01-01",
  "end": "2024-03-31",
  "capital": 500000
}
```

### 5.4 Interval Reference

| Interval | Use Case | yfinance Limit | Recommendation |
|----------|----------|---------------|----------------|
| `5m` | High-frequency intraday | 60 days lookback max | Limit to ≤5 symbols, ≤30 days |
| `10m` | Intraday with less noise | ~60 days lookback | ≤10 symbols recommended |
| `15m` | Standard intraday | ~60 days lookback | Primary backtest interval |
| `1d` | Daily / swing trading | Years of data | Full 20-symbol runs feasible |

> **yfinance rate limit**: Yahoo Finance throttles sub-daily requests. For 5m/10m runs, limit symbols or date range. The engine retries with backoff, but very large requests may see `source='mock'` fallback candles if the rate limit is hit.

### 5.5 Monitor a Running Backtest

```bash
RUN_ID="<run_id from backtest/run response>"

# Poll status (check progress, state, and metrics)
curl -s http://localhost:8080/api/backtest/run/$RUN_ID | python3 -m json.tool

# Watch continuously
watch -n 5 "curl -s http://localhost:8080/api/backtest/run/$RUN_ID | python3 -c 'import sys,json; r=json.load(sys.stdin); print(r.get(\"state\"),r.get(\"progress\"))'
```

**Run states**: `QUEUED → PENDING → RUNNING → COMPLETED | FAILED | STALE`

### 5.6 Retrieve Results

```bash
RUN_ID="<run_id>"

# Portfolio summary (equity curve, final P&L)
curl -s http://localhost:8080/api/backtest/run/$RUN_ID/portfolio | python3 -m json.tool

# Trade ledger (every BUY/SELL)
curl -s http://localhost:8080/api/backtest/run/$RUN_ID/trades | python3 -m json.tool

# Missed opportunities (signals that were rejected)
curl -s http://localhost:8080/api/backtest/run/$RUN_ID/missed | python3 -m json.tool

# Replay integrity validation (replay ≡ pipeline check)
curl -s http://localhost:8080/api/backtest/run/$RUN_ID/validate | python3 -m json.tool

# Decision tree for a specific symbol
curl -s http://localhost:8080/api/backtest/run/$RUN_ID/decision/RELIANCE.NS | python3 -m json.tool

# List all runs
curl -s http://localhost:8080/api/backtest/runs | python3 -m json.tool
```

### 5.7 Export Results to JSON

All backtest data lives in PostgreSQL (no flat-file writer). Export via curl:

```bash
RUN_ID="<run_id>"
OUT_DIR="./local_research/${RUN_ID}"
mkdir -p "$OUT_DIR"

curl -s http://localhost:8080/api/backtest/run/$RUN_ID/portfolio > "$OUT_DIR/portfolio.json"
curl -s http://localhost:8080/api/backtest/run/$RUN_ID/trades    > "$OUT_DIR/trades.json"
curl -s http://localhost:8080/api/backtest/run/$RUN_ID/missed    > "$OUT_DIR/missed.json"
curl -s http://localhost:8080/api/backtest/run/$RUN_ID/validate  > "$OUT_DIR/validate.json"

echo "Results saved to $OUT_DIR/"
```

> Add `local_research/` to your `.gitignore` to keep backtest exports out of git.

### 5.8 Comparing Local vs Replit Results

The backtest engine uses the exact same production pipeline (`live_scan_engine._scan_one()`) on both Replit and locally. Given the same parameters and the same yfinance data, results are deterministic.

```bash
# On Replit: export equity curve
curl -s https://<your-repl>.repl.co/api/backtest/run/<REPLIT_RUN_ID>/portfolio > replit_portfolio.json

# Locally: export equity curve
curl -s http://localhost:8080/api/backtest/run/<LOCAL_RUN_ID>/portfolio > local_portfolio.json

# Compare equity curves (if structure is identical)
diff <(python3 -c "import json,sys; r=json.load(open('replit_portfolio.json')); print(json.dumps(r.get('equity_curve',[]), indent=2))") \
     <(python3 -c "import json,sys; r=json.load(open('local_portfolio.json')); print(json.dumps(r.get('equity_curve',[]), indent=2))")
```

> Note: yfinance data can differ slightly between fetches (adjusted prices, corporate actions). For exact comparison, ensure both runs use the same data snapshot (check `candle_source` in the run metadata).

### 5.9 Universe Options

| Value | Resolves To |
|-------|-------------|
| `"universe": "nifty50"` | `config.NIFTY_50` (51 symbols as of Aug 2026 after TATAMOTORS demerger) |
| `"universe": "nifty_50"` | Same as `nifty50` |
| `"universe": "nifty"` | Same as `nifty50` |
| `"universe": "configured"` | Watchlist from DB, falling back to `config.DEFAULT_WATCHLIST` |
| `"symbols": [...]` | Exact list provided — overrides universe |

---

## 6. Sync Strategy

### 6.1 GitHub as the Bridge

GitHub is the canonical bridge between Replit and local development:

```
Replit Workspace  ←──── git pull ────  GitHub (main)
                  ──── git push ───→
Local Machine     ←──── git pull ────
                  ──── git push ───→
```

After Replit is connected to a GitHub repository, pushing to `main` automatically updates the Replit workspace.

### 6.2 Pulling Updates

After pulling code from GitHub, always update both Node.js and Python dependencies:

```bash
git pull origin main
pnpm install          # update Node.js packages if pnpm-lock.yaml changed
uv sync               # update Python packages if uv.lock changed
pnpm run typecheck:libs  # rebuild shared TypeScript libs
```

### 6.3 Feature Branch Workflow for Local Experiments

Use feature branches to keep backtest experiments isolated from production code:

```bash
# Create a branch for a local experiment
git checkout -b local/backtest-experiment-1

# Work on your experiment
# ...

# When done, merge or discard
git checkout main
git branch -D local/backtest-experiment-1
```

### 6.4 Rules

- **Never `git push --force` to `main`**. This can overwrite changes made on Replit.
- **Never edit `artifacts/api-server/src/python/main.py` locally** unless the change is ready for production — it is the dispatch entry point for all Python commands and changes affect every feature.
- **`.env` files must be in `.gitignore`**. Never commit API keys, database URLs, or session secrets.
- **Backtest result exports** belong in a `.gitignore`'d directory (e.g., `local_research/`).

### 6.5 `.gitignore` Additions for Local Dev

Add these to your `.gitignore` if not already present:

```
# Local environment files
artifacts/api-server/.env
.env.local
.env.*.local

# Local research and backtest exports
local_research/

# Python virtual environment
.venv/
.python-exe
.python-site
```

### 6.6 After Pushing to GitHub

Once you push a change to GitHub, Replit picks it up if the workspace is connected (git pull or automatic sync depending on workspace settings). Always:

1. Pull the latest code on Replit.
2. Run `pnpm install && uv sync` if dependency files changed.
3. Restart the API server workflow on Replit.

---

## 7. Recommended Hardware

### 7.1 Timing Baseline

The production backtest engine (`backtest_runner.py`) calls the **full decision pipeline** (`live_scan_engine._scan_one()`) for every symbol at every candle tick. This includes: indicator computation, research agents, market intelligence, monitoring, strategy evaluation, risk gates, and AI decision — the exact same path as a live scan.

**Baseline timing** (post-optimization, warm yfinance cache):
- 5-symbol, 15m interval, 30-day run: **~6 minutes**
- ~93% of time is spent in `_scan_one()` per candle
- Cold cache (first run, yfinance downloads required) adds 30–90 seconds of I/O on top

### 7.2 Minimum Specifications

| Component | Minimum |
|-----------|---------|
| CPU | 4-core / 8-thread (e.g., Intel i5-12th gen, AMD Ryzen 5 5600) |
| RAM | 8 GB |
| Storage | 20 GB SSD (for OS, code, and local Postgres) |
| Network | Stable broadband (yfinance downloads on cold cache) |

At minimum specs, expect **2–3× faster** than Replit for the same backtest parameters.

### 7.3 Recommended Specifications

| Component | Recommended |
|-----------|-------------|
| CPU | 8-core / 16-thread (Apple M2 Pro, AMD Ryzen 7 7700X, Intel i7-13700) |
| RAM | 16 GB |
| Storage | 50 GB NVMe SSD |
| Network | Broadband ≥ 50 Mbps (for yfinance bulk downloads) |

At recommended specs, expect **5–8× faster** than Replit.

### 7.4 Speed Comparison Table

| Environment | Relative Speed | 5-sym 15m 30d | Notes |
|-------------|---------------|--------------|-------|
| Replit (shared compute, autoscale) | 1× (baseline) | ~6 min | No parallelism; cold starts frequent |
| Local minimum specs | 2–3× | 2–3 min | I/O bound on cold cache |
| Local recommended specs | 5–8× | 45–75 sec | Warm cache; local Postgres |
| High-end workstation (12-core+, 32 GB) | 10–15× | 25–40 sec | Full warm cache |

### 7.5 Apple Silicon Notes

Python 3.12 runs natively on ARM64 on Apple Silicon (M1/M2/M3). All key packages have ARM64 wheels:

| Package | ARM64 Wheel |
|---------|------------|
| `pandas` | ✅ Native ARM64 |
| `numpy` | ✅ Native ARM64 |
| `yfinance` | ✅ Pure Python |
| `kiteconnect` | ✅ Pure Python |
| `sqlalchemy` | ✅ Native ARM64 |
| `asyncpg` | ✅ Native ARM64 |
| `psycopg2-binary` | ⚠️ May need `brew install libpq` first |

If `psycopg2-binary` installation fails on Apple Silicon:

```bash
brew install libpq
export LDFLAGS="-L/opt/homebrew/opt/libpq/lib"
export CPPFLAGS="-I/opt/homebrew/opt/libpq/include"
uv sync
```

### 7.6 Concrete Large-Run Example

**20-symbol, 15m interval, 90-day backtest**:

| Environment | Outcome |
|-------------|---------|
| Replit | Times out (backtest scheduler marks STALE after 30 min without heartbeat) |
| Local minimum specs | 15–30 min (feasible, may hit yfinance rate limits) |
| Local recommended specs | 15–25 min (warm cache; local Postgres; no rate limits if run over several minutes) |
| High-end workstation | 8–15 min |

### 7.7 Decision Guide

| Scenario | Use |
|----------|-----|
| Live paper trading | **Replit** (always-on, connected to production DB) |
| Quick 5-symbol validation (≤30 days) | Replit or local |
| Anything > 5 symbols | **Local** |
| Anything > 30 days | **Local** |
| 20-symbol full NIFTY 50 runs | **Local** (recommended hardware) |
| Parallel experiment comparison | **Local** (Option C: two databases) |

---

## 8. Quick Reference Card

```bash
# ════════════════════════════════════════════════════════════
#  APEXQUANT AI — LOCAL DEVELOPMENT QUICK REFERENCE
# ════════════════════════════════════════════════════════════

# ── ONE-TIME SETUP ──────────────────────────────────────────
git clone <repo-url> apexquant && cd apexquant
pnpm install
uv venv .venv --python python3.12 && uv sync
pnpm run typecheck:libs
createdb apexquant_local
DATABASE_URL=postgresql://postgres@localhost:5432/apexquant_local \
  pnpm --filter @workspace/db run push

# ── START API SERVER ────────────────────────────────────────
cd artifacts/api-server
# Edit .env: PORT=8080, DATABASE_URL=..., LIVE_EXECUTION_ENABLED=false
PORT=8080 pnpm run dev

# ── START DASHBOARD ─────────────────────────────────────────
cd artifacts/trading-dashboard
# Add Vite proxy to vite.config.ts (local only, do not commit):
#   server: { proxy: { '/api': 'http://localhost:8080' } }
pnpm run dev
# Open: http://localhost:3000

# ── SAFETY CHECK ────────────────────────────────────────────
curl -s http://localhost:8080/api/settings | python3 -m json.tool | grep -i live

# ── RUN A 5-SYMBOL BACKTEST ─────────────────────────────────
RUN=$(curl -s -X POST http://localhost:8080/api/backtest/run \
  -H "Content-Type: application/json" \
  -d '{
    "symbols": ["RELIANCE.NS","TCS.NS","INFY.NS","HDFCBANK.NS","ICICIBANK.NS"],
    "interval": "15m",
    "start": "2024-01-01",
    "end": "2024-01-31",
    "capital": 100000
  }' | python3 -c "import sys,json; print(json.load(sys.stdin)['run_id'])")
echo "Run ID: $RUN"

# ── MONITOR THE RUN ─────────────────────────────────────────
watch -n 5 "curl -s http://localhost:8080/api/backtest/run/$RUN \
  | python3 -c 'import sys,json; r=json.load(sys.stdin); \
    print(r.get(\"state\"), r.get(\"progress\",{}))'

# ── RETRIEVE RESULTS ────────────────────────────────────────
curl -s http://localhost:8080/api/backtest/run/$RUN/portfolio | python3 -m json.tool
curl -s http://localhost:8080/api/backtest/run/$RUN/trades    | python3 -m json.tool
curl -s http://localhost:8080/api/backtest/runs               | python3 -m json.tool

# ── EXPORT TO FILES ─────────────────────────────────────────
mkdir -p local_research/$RUN
curl -s http://localhost:8080/api/backtest/run/$RUN/portfolio > local_research/$RUN/portfolio.json
curl -s http://localhost:8080/api/backtest/run/$RUN/trades    > local_research/$RUN/trades.json

# ── SYNC CODE FROM GITHUB ───────────────────────────────────
git pull origin main && pnpm install && uv sync && pnpm run typecheck:libs

# ── PYTHON WORKER DEBUG (no Node.js layer) ──────────────────
cd artifacts/api-server/src/python
source ../../../.venv/bin/activate
python main.py portfolio
python main.py signals
python main.py backtest_runs '{}'

# ════════════════════════════════════════════════════════════
#  KEY RULES
#  1. LIVE_EXECUTION_ENABLED=false — always, no exceptions
#  2. Use Option B (local Postgres) for any backtest work
#  3. Never push --force to main
#  4. Never commit .env files
#  5. Mock candles (source='mock') are not real data
# ════════════════════════════════════════════════════════════
```
