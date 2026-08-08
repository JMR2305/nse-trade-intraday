---
name: Canonical portfolio module
description: Single source of truth for portfolio math — every portfolio endpoint must go through canonical_portfolio.py
---

- Rule: all positions/cash/equity/trade-history figures must come from `canonical_portfolio.py` (phase20 ledger). Never read legacy paper_trader/portfolio_store state for positions or cash — legacy daily resets archive positions that remain OPEN in the ledger, and mixing stores double-counts (one bug produced equity ₹77k from ₹50k capital by summing ledger positions on top of legacy cash).
- **Why:** three portfolio stores existed (paper_trader state, portfolio_store state, phase20 ledger); pages diverged (1 vs 4 open positions) until all endpoints were repointed.
- **How to apply:** any new endpoint or page showing positions, cash, equity, or trade history must call `build_canonical_portfolio()` / `canonical_trades()` and adapt shape, not re-derive. Accounting: cash = INITIAL_CAPITAL − open cost + realized; equity = cap + realized + known unrealized MTM with `equity_complete=false` when marks are missing. Legacy state is only allowed for pnl_history charting.
- Scan confidences may be stored as percent already — never blindly `*100` (ops-centre showed 5304.5); normalise with a `<=1.5` threshold.
- Execution Quality + Portfolio Performance are canonical too. EQ fallback rule: legacy portfolio_store allowed ONLY when `_ledger_rows()` import/retrieval fails; per-row errors log-and-skip, never wholesale fallback (tests assert legacy mock not called). PP keeps a legacy `load_state()` read solely for the pnl_history equity curve (ledger has no per-interval equity yet) — compat-only, documented in code.
