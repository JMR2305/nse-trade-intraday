---
name: Phase 9 copilot design
description: AI Copilot / alerts / explainability engine invariants
---

- copilot_engine.py is strictly read-only over trading state: it only writes its own artifacts (phase9_alerts.json max 500, phase9_confidence_history.json, exports/). Never mutate scan cache, state.json, or broker config from Phase 9 code.
- Alerts are deduplicated by (type, symbol, scan_id) — regenerating on the same scan adds 0 new alerts by design.
- Confidence snapshots are idempotent per scan_id (append-only, one per scan) to preserve the no-look-ahead guarantee; all analysis is bound to the cached scan's scan_id + snapshot_ts.
- Every user-facing output carries voice-ready `voice_text` and the "PAPER / LIVE DATA VALIDATION" label; keep both when extending.
- Tests: `python3 test_phase9.py` in artifacts/api-server/src/python/ (isolates alert/history files to a tempdir).
