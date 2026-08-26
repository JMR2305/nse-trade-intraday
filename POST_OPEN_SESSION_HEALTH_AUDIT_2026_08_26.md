# Post-Open Session Health Audit — 2026-08-26

**Scope:** Production, paper trading only, after NSE open.  
**Audit method:** Read-only production `GET` requests, production read-replica
`SELECT` queries, and a no-click production browser inspection.  
**No actions taken:** No scan, Phase 5A/B/C retry, replay, backfill, broker
order, paper trade, portfolio/ledger reset, universe refresh, setting change,
model action, or evidence mutation.

## A. Production identity — PASS

| Field | Value |
| --- | --- |
| Environment | `production` |
| Git commit | `fa612a219c2ca2aa682e5af58b051e2da4425c16` |
| Build ID | `apexquant-fa612a219c2c` |
| Deployment ID | `0d018179-abe0-42c2-a554-dbb19d11341f` |
| Runtime timestamp | `2026-08-26T04:13:52.508Z` |
| UI/API identity | `MATCH` |

The production Mission Control page rendered the same UI and API build ID.

## B. Kite session health — PASS

- Connected to Zerodha Kite Connect: **true**
- Credentials present and stored token reported: **true**
- Token status: **VALID**
- Token expiry warning: **false**; approximately **1,216 minutes** remained at
  the audit snapshot.
- Mock mode: **false**
- Last successful read-only broker call: `2026-08-26T04:13:52Z`
- Broker error / redirect / login failure: **none**
- Daily-login-required is not exposed as a separate field; the valid token and
  successful authenticated call show that no login was required at audit time.

No broker order endpoint was called.

## C. Market state — PASS

- NSE state: **OPEN**
- Audit-time market clock: `2026-08-26T09:52:09+05:30`
- Holiday: **none**
- Next transition: market close at `15:30 IST`

## D. Post-open readiness — PASS, with Task #930 certification warning

| Gate | Result | Evidence |
| --- | --- | --- |
| Scheduler | PASS | `HEALTHY`, `FRESH`, no active lock, no missed runs, no last error |
| Python/runtime and scan cache | PASS | `/api/health/ready` returned `ready` |
| Database / durable session store | PASS | Pre-open initialization recorded `db_ready=true`; production read-replica queries succeeded |
| Quote path | PASS | 23/23 current-session quotes are `LIVE` |
| Kite mapping | PASS | 23/23 valid active mappings |
| Active universe | PASS | `CUSTOM_LOW_PRICE_SECTOR`, 23 active symbols |
| Data freshness | PASS | Current quote freshness is `LIVE`; no stale, fallback, synthetic, or unavailable symbols |
| Circuit breaker | PASS | Not tripped; no reasons; zero consecutive losses |
| Open / stuck exits | PASS | No `OPEN` or `EXIT_PENDING` durable trade row |
| Ledger / portfolio health | PASS | Ledger readable, portfolio `HEALTHY`, zero unresolved discrepancies |
| Natural pre-open coverage | WARN / NOT CERTIFIED | The naturally scheduled Phase 5A collection persisted 3 of 23 expected symbols |

The early `PREMARKET_READINESS_CHECK` at 08:46 IST was naturally scheduled and
blocked while Kite had not yet been verified. That condition is no longer
current: Kite is valid and the post-open scheduled scans are healthy.

## E. Active universe and mappings — PASS

- Active universe: `CUSTOM_LOW_PRICE_SECTOR`
- Active symbols: **23**
- Complete active mappings: **23/23**
- Missing active mappings: **0**
- Duplicate active symbols: **0**
- Duplicate active instrument tokens: **0**
- Invalid active mappings: **0**
- Unexpected symbols in the current scheduled scan: **0**

**Mapping-cache age:** 3 days (`2026-08-23`). The metadata reports
`refresh_required=true`; this audit did not refresh mappings, as required.

## F. Current quote provenance — PASS

Authoritative source: `GET /api/live-data/health-v2` under
`market_data_readiness`.

| Field | Value |
| --- | --- |
| Current quote provider | `ZERODHA_KITE` |
| Current quote timestamp | `2026-08-26T04:17:39Z` |
| Current quote freshness | `LIVE` |
| Historical OHLCV provider | `YFINANCE` |
| Scan provenance | `SCHEDULED` |
| Current quote coverage | 23/23 |
| Stale / fallback / synthetic / unavailable | 0 / 0 / 0 / 0 |

The current-price provider is recorded separately from historical OHLCV. The
separate membership-refresh price evidence is not treated as a live quote.

## G. Pre-open data and volume — PARTIAL; Task #930 not certified today

The pre-open module is enabled and its provider reported `LIVE`, but the
durable scheduled collection was incomplete:

| Durable field | Value |
| --- | --- |
| Session | `preopen-2026-08-26-ccb21a` |
| Origin | `SCHEDULED` |
| Expected active universe | 23 |
| Provider collected | 3 |
| Persisted | 3 |
| Normalized | 3 |
| Missing / failed | 20 / 20 |
| Duplicate / malformed / unexpected | 0 / 0 / 0 |
| Persistence status | `COVERAGE_INCOMPLETE` |
| Verified batch / frozen batch | none / none |

The three durable records are `COALINDIA`, `NTPC`, and `WIPRO`; they include
pre-open price indications, gap and available volume fields. The remaining 20
active symbols were not covered. Index/regime evidence is therefore not
treated as complete for the active universe, and no data was fabricated.

**TASK #930 NOT CERTIFIED TODAY.** No corrective collection, replay, or
backfill was attempted.

## H. Natural scheduled scans and scheduler — PASS

Latest current-session canonical scan:

| Field | Value |
| --- | --- |
| Scan ID | `4354dd7cf3d3` |
| Started / completed | `09:47:35` / `09:47:39` IST |
| Origin | `SCHEDULED` |
| Status | `SUCCESS` |
| Requested / received | 23 / 23 |
| Quote provenance / freshness | `ZERODHA_KITE` / `LIVE` |

Natural jobs observed since market open:

1. `09:02:06 IST` — `SYSTEM_HEARTBEAT`, `SCHEDULER`, success.
2. `09:17:17–09:21:40 IST` — canonical `MARKET_SCAN`, `SCHEDULED`, success,
   23/23.
3. `09:39:31–09:39:38 IST` — canonical `MARKET_SCAN`, `SCHEDULED`, success,
   23/23.
4. `09:47:35–09:47:39 IST` — canonical `MARKET_SCAN`, `SCHEDULED`, success,
   23/23.

No `MANUAL` or `API_TRIGGERED` current-day scan row was found. The scheduler
reports a five-minute cadence, no active scan lock, no stuck progress, no
missed runs, and no current error.

## I. Paper portfolio and ledger — PASS

| Field | Value |
| --- | --- |
| Source | Canonical Phase 20 ledger |
| Initial capital | ₹100,000.00 |
| Cash / available buying power | ₹99,721.26 |
| Invested / reserved | ₹0.00 / ₹0.00 |
| Equity | ₹99,721.26 |
| Realized P&L | -₹278.74 |
| Unrealized P&L | ₹0.00 |
| Open positions / EXIT_PENDING | 0 / 0 |
| Closed trades | 6 |
| Current drawdown | ₹278.74 (0.28%) |
| Daily loss / risk-pause state | ₹0.00 / not paused |

`/api/portfolio` and `/api/portfolio/snapshot` agree on cash, equity,
positions, and P&L. The current ₹100,000 capital differs from the earlier
₹500,000 preserved baseline; the current durable capital status says the
₹100,000 paper-capital migration was already applied. This audit made no
capital change.

## J. Signals, orders, and trade activity today — PASS

- Structured signal-validation records today: **0**
- Structured paper orders / fills / closes today: **0 / 0 / 0**
- Durable Phase 20 paper trades created today: **0**
- Current `OPEN` or `EXIT_PENDING` trade rows: **0**
- Live broker orders today: **0**
- Current-day auto-paper buy-audit records: **0**

The legacy advisory signal endpoint returned recommendations only; they are not
paper orders or broker orders. No actual paper or live trade was found.

## K. Risk gates — PASS

| Gate | Current state |
| --- | --- |
| Per-trade risk | 1% default risk-per-trade cap |
| Daily loss | 3% / ₹3,000 Phase 20 limit; current-day realized P&L ₹0 |
| Weekly loss | Not exposed as a separate current policy field |
| Max drawdown pause | 10% portfolio threshold; current drawdown 0.28% |
| Maximum positions | 10 portfolio-level; 5 Phase 20 concurrent-position limit |
| Total exposure | 0%; caps are 90% portfolio-level and 80% Phase 20 |
| Sector exposure | 0%; caps are 35% portfolio-level and 40% Phase 20 |
| Minimum cash reserve | 5%; cash is 99.72% of initial capital |
| Circuit breaker | Not tripped; no reasons |
| Data-quality gate | `LIVE`, 23/23 coverage |
| Losing-streak pause | 0 consecutive losses; limit is 3 |

The policy values are reported from their respective portfolio and Phase 20
control layers. With no open exposure, neither layer is breached.

## L. Automatic paper-entry state — PASS

- Automatic paper entries: **OFF**
- Entry confirmation timestamp: **null**
- Bootstrap: **OFF**
- Automatic exits: **ON**
- Controlled paper entry: `DISABLED`, dry-run only
- Controlled entry `execution_allowed`: **false**

The market-hours gate is open, but it does not override the explicit
automatic-entry setting of `false`. Nothing was enabled in this audit.

## M. Live-order safety — PASS

- Execution mode: `PAPER_TRADING`
- Production validation: `ZERODHA_ENABLED=false`,
  `PAPER_TRADING_MODE=true`
- Live-order writes: disabled
- Controlled execution: disabled
- Broker orders today: 0
- This workflow made only GET and SELECT requests; no place, modify, or cancel
  order endpoint was invoked.

The controlled-paper-entry status endpoint returned its disabled safety payload
(`execution_allowed=false`) and no execution path was exercised.

## Task #939 provenance display — PASS

A production Chromium inspection of
`/trading-dashboard/mission-control` waited until the health requests
settled. The rendered card matched the production health-v2 payload:

| Rendered field | Value |
| --- | --- |
| Current quote provider | `ZERODHA_KITE` |
| Last quote | `2026-08-26T04:17:39Z` |
| Quote freshness | `LIVE` |
| Historical OHLCV | `YFINANCE` |
| Scan provenance | `SCHEDULED` |

The page showed matching UI/API build IDs and no application console errors.
The initial loading label was correctly present while the read-only health
request was pending; it resolved to the values above after the responses
returned HTTP 200.

## Read-only safety confirmation

The audit performed no mutation. It used production GET endpoints, production
read-replica SELECT queries, and a no-click browser load only. The legacy
manual scan `e1ded4dfba2e` remains a successful 23/23 record, and no Task #930
evidence was changed.

## Final verdict

A. LIVE SESSION HEALTHY — TASK #930 STILL AWAITS NEXT NATURAL PRE-OPEN