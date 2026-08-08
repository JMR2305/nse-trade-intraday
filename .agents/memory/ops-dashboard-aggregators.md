---
name: Aggregated ops dashboards
description: Rules for the Phase 4A / Paper Trading Validation aggregate dashboard endpoints and metric windowing
---

- Both dashboards are fed by ONE Python aggregator (`phase4a_dashboard.py`, commands `phase4a_dashboard` / `validation_dashboard`) that only reads canonical stores: phase20 ledger, portfolio_store.INITIAL_CAPITAL, replay pipeline_counts, latest scan snapshot, cached market context, ai_decisions_cache. **Why:** the spec forbids duplicated calculations and hardcoded values; every metric must trace to a store.
- Time bucketing: today/previous-session/rolling windows must use IST *calendar dates* of fill_ts/exit_ts, never UTC `now - timedelta` instants; CLOSED rows without exit_ts are excluded from windows (they're flagged in data quality instead of being counted as "now").
- "Trades today" = distinct trade_ids with activity today (a same-day round trip is 1 trade, not 2).
- Unrealized P&L / portfolio value marks come from latest scan prices — always label `mark_source`; when a mark is missing, return null + note, never partial sums presented as complete.
- Route pattern: 30s TTL cache + single-flight promise per endpoint, with a bounded spawn timeout — replay rebuild per poll is too expensive otherwise.
- No fabricated statuses: absent provider fields report "NOT REPORTED", not "OK"; genuinely missing data renders as "—" and is listed in the gaps section of reports.
