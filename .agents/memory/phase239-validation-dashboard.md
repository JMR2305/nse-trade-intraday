---
name: Phase 23.9 validation dashboard & export + V2 empty-state
description: Validation dashboards/export pitfalls, and AI Validation Centre V2 schema-drift + first-run UX lessons.
---

# Export engine
- json/csv/md/pdf via reportlab b64; acceptance audit must_reference markers must match real imports.
- RQ test pitfalls: never mockReset an API mock in beforeEach or React Query rejections go unhandled.

# AI Validation Centre V2 (validation_v2_engine.py)
- **Legacy schema drift is silent.** `_ensure_tables` uses CREATE TABLE IF NOT EXISTS, so old tables keep missing columns; the run-insert wraps in `except Exception: pass`, so a failed INSERT returns a run_id that never exists ("Run X not found" downstream). Any new column added to the DDL MUST also be added to the ALTER TABLE migration block in `_ensure_tables`.
- Legacy `validation_v2_decisions` had a NOT NULL `stage` column with no default → whole flush transaction aborted for every symbol. Migration must set a default (guard with ADD COLUMN IF NOT EXISTS first, since ALTER COLUMN has no IF EXISTS).
- psycopg returns JSONB columns as native Python lists/dicts, not strings — never call `json.loads()` on them unconditionally (use an isinstance check).
- Background execute is spawned with `stdio: "ignore"` — it dies silently. Debug by running `main.py validation_v2_backtest_execute <run_id> <config_json>` in the foreground.
- run_ids are 12-char truncated UUIDs by design (not corruption).

# V2 first-run UX contract
- Page-level `["v2-runs"]` query gates the UI: first-run banner + CTA, auto-open Backtest Runner, RUN_DEPENDENT_TABS (indices 2-9) disabled while empty. `sessionRunCompleted` state clears the banner/unlocks tabs instantly on completion — do not rely on the refetch alone (staleTime race). Overview cards must navigate through the guarded `selectTab`, never raw `setActiveTab`.
- Dashboard vitest needs `pnpm run test` (sets PORT/BASE_PATH); bare vitest fails on vite.config PORT check. jsdom needs a ResizeObserver stub for chart-bearing tabs.
