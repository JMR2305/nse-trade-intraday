---
name: Portfolio pre-check wiring
description: How RC-10C1 PortfolioService is wired into the live paper signal flow via portfolio_bridge
---
The spec's SignalRouter/RC-8/RC-7 runtime does NOT exist in this checkout; the live signal path is intelligence scan → paper_trader.execute_buy/sell, with execution_engine.PreTradeValidator as the RC-8-style gate.

**Rule:** all portfolio-core enforcement enters through `portfolio_bridge.py` (sync façade over the async PortfolioService, per-process singleton + dedicated event loop). Order: portfolio pre-check runs BEFORE phase11 risk in execute_buy, and is prepended to build_preview checks (BUY only — never block exits). Fills/marks/reconcile mirror through on_fill/update_price(s)/reconcile_now; scheduled reconcile in phase20_scheduler after each scan tick.

**Why:** pre-check must fail CLOSED (blocked orders) but mirroring must fail OPEN (never lose a committed fill); repos are in-memory stubs, so each process seeds from the canonical phase20 ledger at startup.

**Gate calibration:** library default min_order_value ₹5,000 would silence all paper BUYs on a ₹50k book — bridge lowers it to ₹50 unless env overrides. Also fixed: state_manager drawdown used cash-only equity (`current_equity=cash.total`), making any deployed book look like a 70%+ drawdown and rejecting every allocation; equity must include open-position gross value.

**How to apply:** any new order entry point must call portfolio_bridge.pre_check before committing and on_fill after; symbols map to tokens via crc32 (instrument_token_for).
