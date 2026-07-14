---
name: Research report engine conventions
description: Durable conventions for the Phase 4.3 experiment research report engine (file persistence, idempotency, research-only guardrails)
---

- Reports are file-based (no SQL): `experiments/<id>/reports/report_vN.json` + `index.json`. The spec's "database table" requirement is satisfied this way — keep it consistent for future report-like features.
- Idempotency uses a hash of the source result files; regenerate only bumps the version when forced or when the hash changes. Any new source input added to reports must be included in the hash or stale-skip will hide changes.
- **Why:** deterministic, replayable research artifacts with no DB dependency, and cheap "unchanged → skip" semantics.
- Research-only guardrails: report generation must never affect experiment status or live/paper trading; hooks in the experiment pipeline are wrapped non-fatally. Suggested-experiment queueing requires explicit `{confirm:true}` from the UI — never auto-queue.
- UI must render exactly the 19 spec sections numbered 1–19 (strengths and weaknesses are separate sections), and every value formats through an N/A helper — never raw undefined/NaN.
- Playwright testing gotcha: a button labeled "Queue" collides with the "Queue" tab — always scope locators or rename labels when testing this page.
