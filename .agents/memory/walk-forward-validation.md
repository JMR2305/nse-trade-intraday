---
name: Walk-forward validation design rules
description: Durable rules for the v2.4 walk-forward validator — lookahead audits and window semantics.
---

# Lookahead audit must cover every data source
The audit must record the newest timestamp from EACH decision input independently: candle bars (≤ decision day), knowledge trades and similarity matches (must have exited STRICTLY before the day). Auditing only the bar timestamp proves nothing about the learning paths.
**Why:** architect review flagged that a bar-only audit reported "0 violations" while leaving pattern/similarity paths unverified.
**How to apply:** any new decision input (new adjustment source) must feed its max source timestamp into the audit helper and be covered by a unit test that injects future-dated data.

# Zero-trade windows are valid, not failed
A test window where the model executed 0 trades is a legitimate outcome; only data failures (no candles / insufficient history) mark a window failed. Excluding zero-trade windows silently zeroes market benchmarks (NIFTY, equal-weight) and undercounts test windows in the verdict.
**Why:** small universes (3–5 stocks) routinely produce 0 BUYs under live scanner thresholds (BUY ≥ 62 opportunity score); treating that as failure made benchmarks show 0% and the verdict claim "0 test windows".
**How to apply:** keep "failed" reserved for data errors; benchmarks and verdict window counts include zero-trade windows.

# Benchmark aggregation is mixed-mode (known, labeled)
Non-model benchmarks are summed per-window returns (each window restarts at configured capital); the full-model headline is compounded. This is labeled in the result note; if ever normalized, make all series consistent.
