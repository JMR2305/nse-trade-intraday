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