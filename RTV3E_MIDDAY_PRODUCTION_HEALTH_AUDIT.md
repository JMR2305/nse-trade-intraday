# RTV-3E — Read-Only Midday Production Health Audit

**Audit date:** 2026-08-25  
**Observation window:** approximately 13:57–13:59 IST  
**Production URL:** `https://nse-trade-intraday.replit.app`  
**Audit mode:** Production GET requests only; no mutation endpoint was called.

## Final verdict

**G. UNEXPECTED SCHEDULER ACTIVITY**

Production identity, core service health, authoritative custom-universe
membership, portfolio/ledger parity, paper-trading safety, and Kite
connectivity all passed their required checks. The baseline cannot be certified
as fully preserved because durable history contains one successful
`MANUAL_SCAN` after the RTV-3D deployment.

This audit did **not** start that scan. Its production requests were all
read-only `GET` requests, and no scan-trigger endpoint was called.

## 1. Production identity — PASS

Source: `GET /api/health/details`

| Field | Observed |
|---|---|
| Environment | `production` |
| Git commit | `9f83f6764e3861e351e6334070d4031a85818876` |
| Build ID | `apexquant-9f83f6764e38` |
| Deployment ID | `0d018179-abe0-42c2-a554-dbb19d11341f` |
| Runtime response timestamp | `2026-08-25T08:27:44.211Z` |

The live deployment exactly matches the approved RTV-3D commit and build.

## 2. Service health — PASS, with observability anomaly

Sources: `GET /api/health/details`, `/api/health/ready`, and
`/api/phase20/scheduler/health`.

| Check | Observed | Result |
|---|---|---|
| API reachability | HTTP 200 responses | PASS |
| Service health | `ok`; no `live_data_error` | PASS |
| `service_ready` | `true` | PASS |
| `data_ready` | `true` | PASS |
| Python runtime | `true` | PASS |
| Scan cache readable | `true` | PASS |
| Portfolio config loaded | `true` | PASS |
| Scheduler health | `HEALTHY`, `FRESH`, zero missed runs | PASS |
| Latest scheduler heartbeat | `2026-08-25T08:28:47Z` | PASS |
| Database-facing portfolio services | canonical responses available | PASS |

### Readiness anomaly

`trading_data_ready` was `false`, while the configured custom universe had a
fresh, complete 23/23 live scan. The canonical coverage probe similarly
reported:

```text
coverage = 23
symbols_requested = 23
min_symbols_expected = 50
ok = false
warning = Scanner coverage 23/50 during market hours
```

This is a legacy 50-symbol threshold mismatch, not evidence of missing data
for the active 23-symbol universe. It is documented separately as follow-up
task **#928**.

## 3. Universe authority — PASS

Sources: `GET /api/universe/custom/status` and
`/api/universe/custom/symbols`.

| Check | Observed | Result |
|---|---:|---|
| Active universe | `CUSTOM_LOW_PRICE_SECTOR` | PASS |
| Active symbols | 23 | PASS |
| Inactive candidates | 3 | PASS |
| Duplicate active symbols | 0 | PASS |
| Missing expected active symbols | 0 | PASS |
| Unexpected active symbols | 0 | PASS |

Exact active set:

```text
BANKBARODA BANKINDIA CANBK COALINDIA FEDERALBNK GAIL HUDCO IDFCFIRSTB
IRCON IRFC KTKBANK MAHABANK MRPL NBCC NMDC NTPC PFC PNB RECLTD RVNL SAIL
UNIONBANK WIPRO
```

No universe membership was changed.

## 4. Kite token and mapping health — PASS

Sources: `GET /api/kite/status`, `/api/kite/diagnostics`, and
`/api/universe/custom/symbols`.

| Check | Observed | Result |
|---|---|---|
| Credentials present | `true` | PASS |
| Token stored | `true` | PASS |
| Token status | `VALID` | PASS |
| Token expired | `false` | PASS |
| Connected/authenticated | `true` / `CONNECTED` | PASS |
| Daily login required | `false` | PASS |
| Mock mode | `false` | PASS |
| Active valid mappings | 23/23 | PASS |
| Missing Kite symbol/token/trading symbol/exchange/cache date | 0 | PASS |
| Duplicate active instrument tokens | 0 | PASS |

The diagnostic payload’s global instrument-cache metadata reports an older
cache date and `is_fresh=false`; however, the authoritative 23 active mapping
rows are complete and unique. No instrument refresh was performed. Credentials,
masked values, and personal identity fields are deliberately omitted.

## 5. Current market-data health and provenance — PASS for paper/research use

Sources: `GET /api/health/details`, `/api/live-data/health`,
`/api/live-data/health-v2`, and `/api/live-data/coverage`.

| Check | Observed |
|---|---|
| Market state | `OPEN` |
| Active symbols requested/succeeded | 23/23 |
| Coverage | 100% |
| Quality | 23 `LIVE`, 0 stale, 0 near-live, 0 unavailable |
| Fallback symbols | 0 |
| Synthetic symbols | 0 |
| Latest quote timestamp | `2026-08-25T08:27:02Z` |
| Quote age at audit | about 42 seconds |
| Latest scan timestamp | `2026-08-25T08:26:35Z` |
| Scan age at audit | about 69 seconds |
| Quote source | Yahoo Finance / yfinance |
| Scan provider label | Zerodha Kite Connect (Live) + Yahoo Finance (History) |

The current scan is fresh and complete for the configured paper/research
universe. Yahoo Finance market data is being used for the current scan and
historical OHLCV/research context. The audit did not find an enabled broker
execution path or a basis to treat these values as permission for live order
execution. Kite remains a read-only authenticated integration; live broker
orders remain disabled.

## 6. Phase 20 safety settings — PASS

Sources: `GET /api/phase20/settings`, `/api/phase20/bootstrap-status`,
`/api/controlled-paper-entry/status`, and `/api/broker/status`.

| Requirement | Observed | Result |
|---|---|---|
| Automatic paper entries | `false` | PASS |
| Entry confirmation timestamp | `null` | PASS |
| Bootstrap paper mode | `false` | PASS |
| Automatic paper exits | `true` | PASS |
| Controlled execution status | `DISABLED` | PASS |
| Controlled execution allowed | `false` | PASS |
| Controlled execution dry run | `true` | PASS |
| Execution mode | `PAPER_TRADING` | PASS |
| Live broker order placement | `false` | PASS |
| Paper/research label | Present | PASS |

The controlled-entry status endpoint intentionally returns HTTP 404 together
with its explicit `DISABLED` payload; this is the designed disabled-by-default
contract, not a missing safety control.

## 7. Portfolio and ledger parity — PASS

Sources: `GET /api/portfolio`, `/api/portfolio/snapshot`,
`/api/phase20/ledger`, and `/api/phase20/positions`.

| Check | Portfolio | Snapshot | Result |
|---|---:|---:|---|
| Source | `phase20_ledger` | `phase20_ledger` | PASS |
| Contract | `phase20-ledger-v1` | `phase20-ledger-v1` | PASS |
| Initial capital | ₹100,000.00 | ₹100,000.00 | PASS |
| Cash | ₹99,721.26 | ₹99,721.26 | PASS |
| Equity | ₹99,721.26 | ₹99,721.26 | PASS |
| Realized P&L | −₹278.74 | −₹278.74 | PASS |
| Unrealized P&L | ₹0.00 | ₹0.00 | PASS |
| Open positions | 0 | 0 | PASS |

The two portfolio representations agree exactly. The canonical ledger contains
six historical closed round-trip rows, the six-row baseline is preserved, and
there are no open or `EXIT_PENDING` positions. `closed_positions_today` is 0;
no new paper trade, position, or ledger row was observed for 2026-08-25.

## 8. Broker order check — PASS

Source: `GET /api/broker/status`

```text
daily_orders_today = 0
execution_mode = PAPER_TRADING
live_order_placement_enabled = false
```

No broker order was reported. Nothing was cancelled, modified, or placed.

## 9. Scheduler and job audit — EXCEPTION

Sources: `GET /api/phase20/scheduler/health`,
`/api/phase20/scan-history?limit=200`, and
`/api/phase20/notifications?limit=300`.

Current scheduler health is `HEALTHY` and `FRESH`; it reports no missed runs,
no last error, and its latest trigger as `SCHEDULED`.

Since the RTV-3D deployment observation at approximately 10:06 IST, durable
scan history contains:

```text
10 successful SCHEDULED MARKET_SCAN runs
 1 successful MANUAL_SCAN run
```

The unexpected run was:

| Field | Value |
|---|---|
| Started | `2026-08-25T08:26:35Z` / 13:56:35 IST |
| Completed | `2026-08-25T08:27:03Z` |
| Origin | `MANUAL` |
| Job type | `MANUAL_SCAN` |
| Status | `SUCCESS` |
| Scan ID | `e1ded4dfba2e` |
| Symbol coverage | 23 requested, 23 received |
| Entry/execution eligible | `false` / `false` |

This audit made no scan request and did not create this manual history row.
The record is therefore classified as unexpected external activity and is the
reason for the final verdict. Follow-up task **#929** was proposed so future
manual scans have safe operator/approval provenance.

The notification history also contains an open-of-session Phase 26C validation
failure at 10:06:52 IST, followed by a `LIVE_VALIDATION_RECOVERED` notification
at 10:10:29 IST. It is recorded as historical/recovered; the current scheduler
and core service health are healthy.

It also contains informational `symbol_rejected` notices that describe active
custom-universe symbols as outside the approved NIFTY 50 research universe.
The canonical scans nevertheless completed 23/23 for
`CUSTOM_LOW_PRICE_SECTOR`; these stale-baseline notices are treated as part of
the legacy coverage/authority observability mismatch, not as evidence that an
active symbol was excluded from the current scan.

## 10. Preserved RTV-3 failure evidence — PASS for immutable local evidence

The live pre-open status still identifies:

```text
session = preopen-2026-08-25-9b8340
```

The public status surface now displays a later 10-symbol frozen batch for that
historical session. It does not expose the original failed batch directly.
The original immutable evidence files remain byte-identical:

| Evidence | SHA-256 |
|---|---|
| `RTV3_NATURAL_SESSION_CERTIFICATION.md` | `8339f6a48a4f2eac2f172868e35759511ed66f060ddd956dfff931019999f7cf` |
| `RTV3_PREOPEN_BATCH_EVIDENCE.csv` | `c7e06a59cacd17b0b552365e753948db0b2bdecbab6df4d5fbccfb29fb699270` |

The preserved original batch identifier remains:

```text
collection-6073abbd096c44e7b4e4b51a205696ba
```

No historical session, batch, or evidence file was replayed or modified by
this audit.

## 11. Task #920 protection — PASS for this audit

This audit:

- did not call a Phase 5A, 5B, or 5C trigger;
- did not retry or replay pre-open;
- did not generate simulated market data;
- did not create a new Phase 5A certification batch;
- did not modify portfolio, ledger, capital, settings, universe membership,
  credentials, or broker state; and
- did not create evidence that can be mistaken for a Task #920 validation.

Task #920 remains reserved for the next naturally scheduled NSE pre-open
session. The externally recorded `MANUAL_SCAN` was a market scan, not a new
Phase 5A certification, and it is not accepted as Task #920 evidence.

## 12. API-visible observability and anomalies

API-visible identity, universe count, Kite status, market freshness, safety
mode, portfolio parity, and scheduler health are available and consistent with
paper/research operation.

Outstanding anomalies:

1. **Legacy coverage threshold:** readiness/coverage compares the healthy
   23-symbol custom universe to a 50-symbol threshold. See task #928.
2. **Unexpected manual scan:** a manually sourced scan was recorded after
   deployment without audit-visible actor or approval provenance. See task
   #929.
3. **Legacy universe notices:** informational rejection notifications still
   reference the NIFTY 50 baseline for active custom-universe symbols, despite
   complete 23/23 canonical scans. This is included in the #928 scope.
4. **Historical pre-open status:** the original failed session remains a
   10-symbol historical record and must not be used as next-session
   certification.

No UI/runtime code was changed by this audit.