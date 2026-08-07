---
name: Unified Replay Snapshot
description: Single-source-of-truth pattern for replay/ops/portfolio/timeline count parity
---
# Unified Replay Snapshot

Rule: `build_replay()` output is the ONLY source of pipeline counts, decisions, trades, portfolio state, timeline events, and integrity. No page or endpoint recomputes them.

**Why:** Replay, Ops Centre, Portfolio and Timeline each computed their own counts and drifted (e.g. Execution stage said "2 eligible" while the ledger had 0 rows for that scan because duplicate-open-position blocks create no row).

**How to apply:**
- Ops Centre `_pipeline_summary` overrides its legacy counts from the replay snapshot when scan_ids match (`counts_source: "replay_snapshot"`; legacy fallback is tagged).
- Execution stage `out` = actual phase20 ledger rows for the scan; eligible-but-blocked entries go to `cancelled` so conservation (in = out+rej+pend+canc) holds exactly. Ledger overage raises `in` and records an anomaly instead of impossible counts.
- Frontend integrity panel renders the snapshot's embedded `integrity` report (fetch is fallback only) — a second fetch can disagree if the ledger changed in between.
- `get_symbol_journey` must resolve the REQUESTED scan_id (scan_state only if current, else signal_snapshots) and read trades from phase20 ledger scoped by scan — never legacy `paper_trades` or the current scan unconditionally.
- Portfolio state is ledger-only and scan-scoped: a position opened by an earlier scan shows 0 open for the latest scan — by design, not a bug.
