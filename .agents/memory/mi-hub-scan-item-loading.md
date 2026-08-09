---
name: MI hub scan-item loading
description: Why market-intelligence breadth showed zeros — snapshot key and final_action format mismatches.
---

# Market-intelligence hub scan-item loading

The canonical Postgres scan snapshot stores per-symbol rows under **`recommendations`** (not `items`/`watchlist`). Any loader reading the snapshot must check that key or it silently gets an empty list and analytics render zeros/dashes.

`final_action` in canonical snapshots is **"STRONG BUY" (space-separated)**, while analysers historically matched `"STRONG_BUY"`. Normalise with `.upper().replace(" ", "_")` before classifying.

**Volume breadth** has a canonical source: each recommendation row carries `volume_ratio` (current vs average volume). Breadth analyser publishes `volume_breadth` (% of symbols with ratio ≥ 1), plus `volume_advancers/decliners/symbols`; `volume_breadth` is `None` when no rows have volume data — UI shows "no canonical source" dash.

**Why:** breadth endpoint returned all zeros during sessions despite a fresh 50-symbol scan; overview worked because it reads a different route.
**How to apply:** any new consumer of `scan_state_store.load_latest_snapshot()` must read `recommendations` and normalise `final_action` spacing.

Note: MI endpoints spawn a fresh Python process per request (~60–90s cold) — page screenshots rarely catch the Market Breadth widget populated; verify via curl + unit tests.
