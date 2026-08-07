---
name: Replay pipeline conservation & capital source of truth
description: Invariants for the trading-day replay system — stage accounting, ledger-only portfolio, configured capital.
---

# Replay integrity invariants

**Rule 1 — chained subsets:** every replay stage's symbol set must be derived by filtering the *previous* stage's set, never independently from all recommendations. Independently derived sets caused Execution 6-in/7-out.

**Rule 2 — exact accounting:** every stage must satisfy `stocks_in = stocks_out + rejected + pending + cancelled` exactly. The integrity check must compare all four buckets with zero tolerance and ERROR with stage attribution — a 20% "slack" band previously let leaks pass.

**Rule 3 — canonicalize input:** dedupe recommendation symbols (first wins) and clamp provider counts (received ≤ requested, requested ≥ record count) *before* stage assembly; surface inconsistencies as stage `anomalies`, never as negative rejected counts or duplicated downstream orders.

**Rule 4 — ledger-only portfolio:** replay trade cards/positions render exclusively from `phase20_paper_trades` scoped by scan_id. No synthesized fallback from comparison data — empty ledger shows an explicit empty state. A later scan can legitimately show eligible-but-unexecuted symbols (one-OPEN-trade-per-symbol rule); the integrity WARNING for that mismatch is correct behavior.

**Rule 5 — capital single source:** paper capital comes from `portfolio_store.INITIAL_CAPITAL` (₹50,000). Any fallback literal must go through a `_default_capital()`-style helper importing it (fallback 50_000), never a hardcoded 100_000. Cleaned from replay_engine, validation_v2_engine, portfolio config, risk_agent/agent.py, execution_agent/execution_planner.py, and the dashboard replay components (backend serves `starting_capital` in the replay payload).

**Rule 6 — reliability denominator:** sample-size dampening reaches full weight at 4 trades (`/4`), matching market_scanner; a lingering `/8` in signal_quality.reliability_score suppressed composite scores for young strategies.

**How to apply:** any change to replay stage construction must keep tests in `tests/test_replay_conservation.py` green, including duplicate/inconsistent-snapshot cases. React snapshot maps for per-trade balances must be keyed by trade object/unique key, not symbol.
