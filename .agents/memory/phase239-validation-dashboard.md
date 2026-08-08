---
name: Phase 23.9 Validation Dashboard & Export
description: Export engine, validation dashboard page, and final acceptance audit conventions
---

# Phase 23.9 — Validation Dashboard, Export & Final Acceptance

- Export engine lives in `phase239_reports.py` (commands `p239_export`, `p239_acceptance`); route file `routes/phase239.ts` serves `GET /api/phase239/export/:report/:format` and `GET /api/phase239/acceptance`.
- Reports: certification | validation_logs | simulation | comparison | acceptance. Formats: json | csv | md | pdf. PDF is in-memory reportlab returned as `content_b64`; the route base64-decodes and streams it. "Validation logs" = append-only certification run history (the only persisted validation audit trail).
- `export_report(..., data=...)` and `acceptance_report(module_audits=..., runtime=...)` accept injected payloads so tests never touch the DB.
- **Acceptance audit rule:** `must_reference` markers must match what each module *actually* imports/queries — replay/mission-control read the `scan_state` table directly (not scan_state_store), validation engines read canonical_portfolio + pipeline_events, strategy_lab reads backtest_portfolio + phase20_executor. Don't assume every canonical consumer goes through scan_state_store.
- **Why:** presence of the wrong marker string turns a healthy module into a false FAIL; the audit is string-based, so markers are contracts with the source files.
- Dashboard page `/validation-dashboard` (ValidationDashboard.tsx, Operations nav). Component-test pitfalls (Vitest 4 + RQ): never `mockReset` the apiJson mock in beforeEach; "READY" text appears in the history table before the full report loads, so waitFor must target the domain cards, not the banner text.
- Run Certification button: server already single-flights POST /certification/run; client just needs 600s apiJson timeout + disabled/progress state.
