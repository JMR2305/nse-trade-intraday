# RTV-1H Production Readiness Completion

## Scope and safety boundary

This completion records the authorized production actions only: one stale Kite instrument-reference refresh, metadata-only hydration of existing custom-universe rows, and read-only quote/readiness/portfolio/ledger verification. No membership, strategy, threshold, capital, historical ledger, broker order, or live execution state was changed. No manual market scan or pre-open flow was triggered.

## Task 1 — identity

- environment: `production`
- git_commit: `4392f278ae25562f168f970e2b694f8c3d249d5c`
- build_id: `apexquant-4392f278ae25`
- deployment_id: `0d018179-abe0-42c2-a554-dbb19d11341f`
- runtime_timestamp: `2026-08-23T22:08:44.728Z`
- Result: **PASS** — exact approved identity.

## Task 2 — pre-hydration baseline

- total rows: 26
- active rows: 23
- inactive rows: 3
- active sectors: BANK 9 / INFRA 13 / IT 1
- active symbols: `BANKBARODA,BANKINDIA,CANBK,FEDERALBNK,IDFCFIRSTB,KTKBANK,MAHABANK,PNB,UNIONBANK,COALINDIA,GAIL,HUDCO,IRCON,IRFC,MRPL,NBCC,NMDC,NTPC,PFC,RECLTD,RVNL,SAIL,WIPRO`
- each of the five instrument metadata fields: 0/23 non-null before hydration

## Task 3 — Kite instrument master

The pre-check found a stale cache dated `2026-08-09` with one row. The explicitly approved metadata-only refresh completed successfully:

- success: `true`
- refreshed: `true`
- new cache date: `2026-08-23`
- fetched_at: `2026-08-23T22:07:52Z`
- total rows: `10222`
- fresh: `true`

## Tasks 4–6 — mapping and membership

- hydration result: success, 23 active rows processed, 23 mapped
- valid NSE mappings: 23/23
- missing mappings: 0
- duplicate instrument tokens: 0
- active membership unchanged: 23
- inactive historical rows unchanged: 3
- sector split unchanged: BANK 9 / INFRA 13 / IT 1
- WIPRO remains IT
- active symbol list unchanged: **PASS**

See `RTV1H_CUSTOM_UNIVERSE_TOKEN_MAP.csv` for every row.

## Tasks 7–8 — Kite quote provenance

The read-only quote request covered all 23 active symbols:

- Kite quote success: 23/23
- LTP returned: 23/23
- source: `kite_live` for all 23
- reliable LIVE quotes: 23/23
- fallback: 0
- synthetic: 0
- quote timestamp: supplied as `fetched_at` per quote

See `RTV1H_KITE_QUOTE_PROVENANCE.csv` for every symbol. No order endpoint was called.

## Tasks 9–11 — readiness semantics

The readiness contract now uses the current active universe:

- active_universe: `CUSTOM_LOW_PRICE_SECTOR`
- active_universe_count: 23
- valid_token_count: 23
- missing_token_count: 0
- token_coverage_pct: 100
- symbols_synthetic: 0

The separate latest scan remains historical metadata: scan ID `76e307f291e7`, timestamp `2026-08-21T10:02:20Z`, 50 symbols, and `scan_fresh_for_session=false`. It was not rewritten and was not used as the current token denominator. `trading_data_ready=false` remains fail-closed because the existing scan/data-freshness gates are not an open-session certification.

## Tasks 12–15 — portfolio, ledger, auth, and safety

Portfolio parity is exact across `/api/portfolio` and `/api/portfolio/snapshot`:

- initial capital: ₹100,000
- cash/equity: ₹99,721.26
- realized P&L: ₹-278.74
- unrealized P&L: ₹0
- total P&L: ₹-278.74
- open positions: 0

Ledger verification: 6 CLOSED Phase20 rows, matching the prior RTV-1C evidence IDs/symbols/quantities/fills/statuses; stored realized P&L sums to ₹-278.74. No ledger mutation occurred.

Kite authentication: `token_status=VALID`, `token_stored=true`, `connected=true`, `token_expired=false`, `daily_login_required=false`, live probe non-mock.

Safety remains unchanged: paper mode enabled, automatic entries disabled, bootstrap disabled, automatic exits enabled, live broker order placement disabled.

## Task 16 — tests

Focused mapping/readiness/provenance/portfolio/safety regression suite:
**109 passed**. One pre-existing `datetime.utcnow()` deprecation warning was
reported. No tests were weakened.

## Final readiness snapshot

| Area | Result |
|---|---|
| Runtime identity | PASS |
| Kite auth | VALID / connected / stored |
| Universe | CUSTOM_LOW_PRICE_SECTOR, 23 active |
| Mappings | 23/23, zero missing, zero duplicates |
| Quote provenance | 23 Kite live, zero fallback, zero synthetic |
| Current token coverage | 100% |
| Service readiness | true |
| Data readiness | current direct quote plumbing verified; historical scan retained separately |
| Trading readiness | false, fail-closed pending open-session/current-scan gates |
| Portfolio | ₹99,721.26 cash/equity; ₹-278.74 realized; flat |
| Safety | entries off; bootstrap off; exits on; live orders disabled |

## Final verdict

**A. RTV-1H PASS — OPEN-SESSION VERIFICATION PENDING**

Do not claim open-session validation from this off-hours run. The only remaining checks are listed in `RTV1H_NEXT_OPEN_SESSION_GATE.md`. Automatic paper entries must remain disabled.
