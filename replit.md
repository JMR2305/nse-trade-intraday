# NSE Algo Paper Trader

A paper-trading algorithmic system for Indian NSE stocks with a React web dashboard. Generates buy/sell signals using technical indicators (RSI, MACD, Moving Averages) on yfinance data, and simulates trades with ₹5,000 initial capital. No real orders are ever placed.

## Run & Operate

- `pnpm --filter @workspace/api-server run dev` — run the API server (port 8080)
- `pnpm --filter @workspace/trading-dashboard run dev` — run the React dashboard (port 24210)
- `pnpm run typecheck` — full typecheck across all packages
- `pnpm run build` — typecheck + build all packages
- `pnpm --filter @workspace/api-spec run codegen` — regenerate API hooks and Zod schemas from the OpenAPI spec
- `pip install yfinance pandas numpy` — install Python trading dependencies

## Stack

- pnpm workspaces, Node.js 24, TypeScript 5.9
- API: Express 5 (TypeScript) + Python 3 child_process for trading engine
- Trading engine: Python (yfinance, pandas, numpy) — pure JSON file state
- DB: Not yet provisioned (state is in JSON files under `artifacts/api-server/src/python/`)
- Validation: Zod (`zod/v4`), `drizzle-zod`
- API codegen: Orval (from OpenAPI spec)
- Frontend: React + Vite, Recharts, wouter, Tailwind, shadcn/ui

## Where things live

- `artifacts/api-server/src/python/` — Python trading engine (main.py, market_data.py, signal_engine.py, paper_trader.py)
- `artifacts/api-server/src/routes/trading.ts` — Express routes that spawn Python via child_process
- `artifacts/trading-dashboard/src/` — React frontend (dark terminal theme, teal accents)
- `lib/api-spec/openapi.yaml` — single source of truth for all API contracts
- `lib/api-client-react/src/generated/` — generated React Query hooks (do not edit)
- Python state files (auto-created): `state.json`, `watchlist.json`, `signals_cache.json` in `src/python/`

## Architecture decisions

- **Python via child_process**: The trading engine runs as Python subprocesses spawned by Express. Each API call spawns `python3 main.py <command>` and reads JSON from stdout. Simple and swap-friendly — replacing yfinance with Kite Connect only requires changes to `market_data.py`.
- **JSON file state**: Portfolio, trades, watchlist, and signal cache are stored as JSON files next to the Python scripts. This is intentional for the first version — persistent DB migration is a planned follow-up.
- **Signals are cached**: `GET /api/signals` returns cached results from the last scan. `POST /api/run-scan` triggers a fresh scan (can take 30–60 seconds for 10 stocks).
- **₹5,000 initial capital**: Hard-coded in `paper_trader.py`. Position sizing allocates 20% of available cash per trade.
- **Paper trading only**: No broker integration. `execute_buy` and `execute_sell` in `paper_trader.py` only update JSON state.

## Product

- Dashboard: live portfolio value, cash, P&L, open positions, P&L history chart
- Signals page: Stock | Time | Signal (BUY/SELL/HOLD) | Quantity | Price (₹) | Confidence | Reason
- Trades page: full paper trade history
- Watchlist: manage NSE symbols (default: RELIANCE, TCS, INFY, HDFCBANK, ICICIBANK, SBIN, WIPRO, LT, BAJFINANCE, MARUTI)

## User preferences

- Paper trading only — no real order placement ever
- NSE symbols (Yahoo Finance .NS suffix applied automatically)
- yfinance for now; Zerodha Kite Connect planned as a future swap
- Initial capital: ₹5,000
- Do not add automated real order placement
- Every change/prompt executed must also be reflected in the review package generator (`review_package.py`: implementation summary, feature matrix, tests, data exports) so "Generate Review Package" always includes the latest changes
- At the end of every phase, write a summary `.md` to `docs/phase<ID>-summary.md` covering: what was built (files created/modified, API endpoints, algorithm details), test results, an **Issues & known gaps** table (area, description, severity, resolution path), a "What to enable" checklist, and downstream phase dependencies.

## Gotchas

- Running a full scan (`POST /api/run-scan`) fetches 3 months of daily data for each watchlist symbol via yfinance. This can take 30–90 seconds for 10 stocks.
- State files (`state.json`, `watchlist.json`, `signals_cache.json`) are created in `artifacts/api-server/src/python/` on first run. They are not committed to git.
- The api-server has `@workspace/db` in dependencies but does NOT import it — the trading routes use only Python child_process. DATABASE_URL is not required for the trading system to work.
- After adding new OpenAPI endpoints, always run `pnpm --filter @workspace/api-spec run codegen` before using the generated hooks.

## Publish image size guard

The publish image has an 8 GiB limit (a 2026-08-09 publish failed on it).
Run `./scripts/check-workspace-size.sh` (also registered as the
`image-size` validation step) before publishing — it fails at ≥7 GiB and
prints the safe cleanup recipe: clear `.cache/{uv,pip,pnpm}`, `pnpm store
prune`, `git lfs prune`, `git gc --prune=now`. After cleanup, verify the
dashboard and API server still respond.

## Pointers

- See the `pnpm-workspace` skill for workspace structure, TypeScript setup, and package details
- Python engine entry point: `artifacts/api-server/src/python/main.py`
- To swap market data source: replace `fetch_ohlcv()` and `get_ltp()` in `artifacts/api-server/src/python/market_data.py`
