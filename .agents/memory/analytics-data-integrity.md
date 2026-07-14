---
name: Analytics data integrity
description: How historical trade analytics must source metadata to stay immutable
---

Rule: Historical trade analytics must read trade-time snapshots from the trade records themselves, never from mutable caches (e.g. latest scan cache), and BUY↔SELL pairs must be FIFO lot-matched.

**Why:** Scan caches are overwritten on every scan, so enriching old trades from them silently rewrites history (strategy, confidence, opportunity score drift). An architect review failed Phase 10 for exactly this. BUY records in state.json already carry immutable trade-time metadata (strategy_name, signal_confidence, opportunity_score, indicators_at_entry) — use those.

**How to apply:** Any new analytics/reporting over closed trades should FIFO-match SELLs to prior BUY lots per symbol and pull metadata from the matched BUY. Sector should come from the static SECTOR_MAP in config.py. Also: `analytics_engine.py` is a pre-existing shared backtest/replay module — Phase 10 analytics lives in `phase10_analytics.py`; don't collide with the shared name.
