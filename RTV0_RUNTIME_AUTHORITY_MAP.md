# RTV-0 Runtime Authority Map

Audit mode: read-only runtime and database inspection on 2026-08-23 around 03:35 to 03:40 IST. Market state was WEEKEND / CLOSED. No state-changing request or service operation occurred. Production database was not queried.

## Authority matrix

| Business value | Observed authority | Competing path | Runtime conclusion | Confidence |
|---|---|---|---|---|
| Active universe | Phase20 settings endpoint and settings row | CUSTOM_LOW_PRICE_SECTOR candidate universe | NIFTY_50 is active at 50 symbols; custom 23-symbol universe is not active | Confirmed |
| Quote and execution price | local yfinance cache and Yahoo Finance history fallback | Kite LTP overlay | Kite session missing, therefore yfinance fallback is active | Confirmed |
| OHLCV | daily_ohlcv_cache | on-demand provider fetch | 50 symbols warm, Friday bars, valid historical cache only | Confirmed but stale for current session |
| Canonical scan | scan_state plus phase7 scan cache | manual scan routes | Friday scan 8ea114ecb962 is the observed canonical snapshot | Confirmed but stale |
| Scheduler | Node scan scheduler to Python scheduled_scan_tick | manual UI scan run endpoints | weekend system-heartbeat rows are current; no market scan run while closed | Confirmed |
| Signals | phase7 recommendations and signals cache | advisory copilot views | 21 WATCH and 29 IGNORE cached; no fresh-session signal evidence | Confirmed stale |
| AI and Copilot | derived advisory cache | direct scan and portfolio readers | cache exists but no auditable embedded freshness timestamp | Partial / UNKNOWN freshness |
| Position sizing and risk approval | Phase20 executor admission | Phase8 assisted-execution config | live execution path disabled, so actual sizing cannot be exercised | Static proof only; live session required |
| Paper entry and positions | Phase20 executor and phase20_paper_trades | disabled controlled-entry dry-run and legacy trader | auto entries false, bootstrap false, no OPEN rows | Confirmed disabled |
| Main cash and PnL | /api/portfolio source phase20_ledger | legacy paper_portfolio | canonical main API reconciles at 100000 INR | Confirmed |
| Portfolio snapshot UI | /api/portfolio/snapshot portfolio service | /api/portfolio main canonical API | snapshot is divergent at 50000 INR | Confirmed divergent |
| Preopen | preopen_sessions and provider-health | cache/report artifacts | provider health says 50 symbols but latest persisted Friday session has zero | Confirmed inconsistency |
| Preopen validation 5B | preopen_validation_sessions | report artifact | Friday COMPLETE, 10 of 10 valid | Confirmed historical |
| Signal validation 5C | signal_validation_sessions | paper execution | Friday ACTIVE with zero signals approvals trades | Confirmed historical |
| Health and readiness | readiness and health endpoints | portfolio health endpoint | ready/ok status coexists with explicit stale session freshness false | Confirmed semantic distinction |

## Order-value and concurrency classification

- Runtime capital is 100000 INR; auto paper entries false; bootstrap false; auto exits true.
- Static Phase20 BUY admission takes a PostgreSQL transaction advisory lock, rereads settings under that lock, checks open exposure and realized PnL, and has one-OPEN-per-symbol protection. Capital rebase shares the admission lock.
- Static bootstrap ceiling is 15000 INR but bootstrap is disabled. Separate Phase8 assisted-execution configuration has order_value_max 1500 INR; this audit did not prove it controls the Phase20 automatic path.
- Classification: B. Admission protected by static evidence; live concurrent behavior was not exercised. REQUIRES LIVE SESSION VERIFICATION.

## Runtime topology

- API server Node workflow is running. Python is spawned by the API subprocess bridge; no long-lived Python scanner was visible in the point-in-time process listing.
- Published application metadata: https://nse-trade-intraday.replit.app, public Autoscale deployment, successful build. This report does not assert production state equals development state.
