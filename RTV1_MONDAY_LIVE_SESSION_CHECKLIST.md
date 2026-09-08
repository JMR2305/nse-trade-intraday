# RTV-1 Monday Live-Session Checklist

**Operating rule:** paper-only. Do not enable automatic entries, bootstrap, live order placement, manual trades, or broker orders.

## Before 09:00 IST

- [ ] Confirm `/api/kite/status` reports an authenticated, unexpired session. If not: **MANUAL SECRET / LOGIN ACTION REQUIRED**.
- [ ] Confirm the read-only market-data health payload reports 50 active symbols, 50 valid instrument tokens, 0 missing tokens, and 100% token coverage.
- [ ] Confirm no active symbol is classified as synthetic.
- [ ] Confirm `service_ready`, `data_ready`, `session_fresh`, and `trading_data_ready` are separately visible; do not treat service health as trade readiness.
- [ ] Confirm `/api/portfolio` and `/api/portfolio/snapshot` both show canonical `phase20_ledger` source, ₹100,000 initial capital/cash/equity, zero positions, and no false drawdown.
- [ ] Confirm auto paper entries remains disabled, bootstrap remains disabled, auto paper exits remains enabled, and live orders remain disabled.

## 09:00–09:15 IST pre-open

- [ ] Capture Phase 5A provider collected count.
- [ ] Capture persisted snapshot count for the same session/date.
- [ ] Require `persistence_status=MATCH`; stop and investigate any `MISMATCH` or error status.
- [ ] Verify provider/source/timestamp age is visible for the pre-open records.
- [ ] Confirm the watchlist freeze preserves the collected counts rather than replacing them with zero.

## After 09:15 IST

- [ ] Obtain the first fresh canonical scan.
- [ ] Confirm scan timestamp and every Kite-live quote timestamp are valid, non-future, and within the configured freshness window.
- [ ] Confirm all 50 symbols show explicit source, source timestamp, received/freshness status, fallback flag/reason, and token presence.
- [ ] Confirm no fallback or synthetic price is marked execution-grade Kite/live.
- [ ] Require `trading_data_ready=true` only if the strict contract is genuinely satisfied; otherwise retain the fail-closed state.
- [ ] Confirm configured scan cadence and no duplicate legacy scheduled scan.
- [ ] Confirm Dashboard and Signals timestamps align with the canonical scan.
- [ ] Reconfirm PortfolioLive equals the canonical portfolio response.

## Close / post-session

- [ ] Confirm 5B reaches an explicit terminal outcome (`COMPLETE` or `NO_CANDIDATES` as applicable).
- [ ] Confirm 5C is `COMPLETE` only when all records are terminal; otherwise require explicit retry/incomplete state.
- [ ] Record any backtest queue watchdog timeout with elapsed/log context; do not redesign the queue during the session.

## Acceptance

Mark live-session validation complete only after the Kite session, instrument hydration, fresh source provenance, pre-open persistence parity, and canonical portfolio parity checks have all passed without changing the paper-only safety controls.

## Runtime evidence — 2026-08-23 (Sunday, NO-GO)

This was a read-only validation run. It must **not** be treated as a completed
Monday live-session validation or as authorization to enable paper entries.

| Check | Observed evidence | Result |
| --- | --- | --- |
| Market gate | `market.state=WEEKEND`; automatic paper entry was blocked because NSE was not confirmed open. | PASS — safety gate remained closed |
| Kite session | `/api/kite/status` reported `connection_state=LOGIN_REQUIRED`, `connected=false`, `token_stored=false`, and no prior authenticated success. | BLOCKED — daily Kite login is required |
| Instrument hydration | `/api/live-data/health-v2` reported 50 active symbols, 1 valid cached token, 49 missing tokens, and 2% coverage. The cache itself was dated 2026-08-09 and not fresh. | BLOCKED — refresh after authenticated Kite login |
| Fresh execution provenance | The canonical scan timestamp was 2026-08-21T09:55:44Z (stale). There were 0 Kite-live rows, 50 Yahoo fallback rows, 0 synthetic rows, and no Kite quote timestamp to validate. | BLOCKED — run a fresh live scan in the NSE session |
| Strict readiness | Health kept `service_ready=true` and `data_ready=true` separate from `session_fresh=false` and `trading_data_ready=false`. | PASS — fail-closed contract held |
| Phase 5A persistence parity | The provider health probe exposed 50 available NSE symbols, but 2026-08-23 had no active pre-open session or persisted snapshots. The latest persisted session was 2026-08-21 with 0 records and `provider_status=UNAVAILABLE`. | NOT VERIFIED — do not infer a count match from the provider probe |
| Portfolio parity | `/api/portfolio` and `/api/portfolio/snapshot` both used `phase20_ledger` and reported ₹100,000 cash/equity, zero positions, and zero drawdown. | PASS |
| Safety controls and side effects | Auto paper entries were off, bootstrap was off, auto paper exits remained on, live orders remained disabled, the broker was mock-only with 0 orders, and the ledger had 4 closed / 0 open-or-pending trades. | PASS — no order or paper entry was created |

### Required next verification window

On the next NSE trading day, before 09:00 IST, complete the daily Kite login
through the operator flow and refresh the instrument cache. During the
09:00–09:15 IST collection window, record a same-session provider-collected
count and persisted snapshot count, requiring `persistence_status=MATCH`.
After the first fresh canonical scan, proceed only if all 50 rows are
execution-grade Kite-live, all source timestamps are fresh and parseable, and
`trading_data_ready=true`. Leave auto paper entries disabled unless that full
checklist is subsequently satisfied.

### Runtime recheck — 2026-08-23 19:24 IST (Sunday, NO-GO)

This was another read-only check after the operator requested an immediate
status refresh. No login, instrument refresh, scan, order, paper entry, or
safety-setting mutation was attempted.

| Check | Current evidence | Result |
| --- | --- | --- |
| Market gate | `market.state=WEEKEND`, `is_open=false`, and automatic paper entry was blocked because NSE was not confirmed open. | PASS — safety gate remained closed |
| Kite session | `/api/kite/status` reported `connection_state=LOGIN_REQUIRED`, `connected=false`, `token_stored=false`, and no authenticated success. | BLOCKED — operator login required |
| Instrument hydration | `/api/kite/instruments/status` reported cache date 2026-08-09, `count=1`, and `is_fresh=false`; health reported 50 active symbols, 1 valid token, 49 missing, and 2% coverage. | BLOCKED — authenticated refresh required |
| Fresh execution provenance | Health reported scan `8ea114ecb962` at `2026-08-21T09:55:44Z`, 0 Kite-live rows, 50 Yahoo fallback rows, `session_fresh=false`, and `trading_data_ready=false`. | BLOCKED — no fresh execution-grade scan |
| Phase 5A persistence parity | `/api/preopen/health` exposed a 50-symbol NSE provider probe, but `/api/preopen/snapshot` returned 0 snapshots and the latest persisted session remained 2026-08-21 with `symbol_count=0` and `provider_status=UNAVAILABLE`. | NOT VERIFIED — no current session exists |
| Portfolio parity | `/api/portfolio` and `/api/portfolio/snapshot` both reported `phase20_ledger`, ₹100,000 initial capital/cash/equity, zero positions, and zero drawdown. | PASS |
| Side effects and controls | Broker mode was `PAPER_TRADING`; activation status showed paper automation false, auto exits true, and live orders disabled. Mock order history was empty; paper summary showed 4 filled historical trades, 0 open positions, and 0 trades today. | PASS — no order or paper entry created |

The current result remains **NO-GO**. The pre-open provider probe and mock broker
health are not substitutes for authenticated Kite session proof, complete
instrument coverage, fresh Kite quote provenance, or same-session persistence
parity.