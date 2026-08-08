---
name: Phase 23 Parts 6/7 Strategy Lab
description: Optimization Lab + Institutional Analytics — derived-only what-if sims, lab_verify byte-compare, INSUFFICIENT_EVIDENCE rules
---
- What-if/config-comparison results are **derived simulations recomputed on demand, never persisted** — this is what makes the module trivially read-only. Keep it that way; do not add a "save variant" store without revisiting immutability guarantees.
- **Why:** backtest runs have no parameter overrides (thresholds come from the settings store at scan time), so variants can only exist as replays over the recorded ledger + candle cache.
- `lab_verify` proves read-only by byte-comparing the run record + trade ledger before/after running what-if, walk-forward and recommendations, plus replay_verify and settings-hash checks. Any new lab feature must stay inside that proof.
- Exit re-simulation walks the same cached candles the runner used, stop-beats-target priority, END_OF_BACKTEST close; MIN_EVIDENCE=5 → INSUFFICIENT_EVIDENCE verdict, never extrapolation.
- Monte Carlo is deterministic-seeded bootstrap (seed from run_id) so repeated calls are identical — tests rely on this.
- Metric math delegates to expectancy.compute_metrics (field is `max_drawdown`, not `max_drawdown_pct`, in summary); paper calibration embeds phase21_calibration verbatim.
- Routes: `routes/lab.ts` inline runPython (never shared import), 30s coalescing cache on heavy GETs, 120–300s timeouts; export endpoint streams file content with Content-Disposition, frontend uses plain `<a href="/api/lab/export?...">` (apiJson would mangle downloads).
- Two sources everywhere: source=backtest (run_id) or paper (phase20 ledger BUY rows).
