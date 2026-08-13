# Morning Stale Data Reset Fix Report

**Task:** Fix morning stale data showing as active  
**Date:** 2026-08-13  
**Scope:** Advisory / display only — no trade logic, thresholds, or live order paths changed.

---

## What Stale Data Was Displayed

Before this fix, when the latest scan was 14+ hours old (from the previous
IST trading day), the following displayed incorrectly as if active:

| Surface | Stale data shown |
|---------|-----------------|
| **AI Paper Trader — Execution Pipeline** | Yesterday's `top_buy_candidates` table (BUY cards with scores, confidence, action badges) |
| **AI Paper Trader — Execution Pipeline** | Yesterday's `candidate_gate_details` (blocked-candidate rows with gate pills) |
| **AI Investigation Centre — Symbol grid** | `Paper ✓` badge on symbols from yesterday's scan |
| **AI Investigation Centre — Symbol grid** | Full active-candidate grid with today-implying action badges |
| **Phase 11 Recommendation Queue** | Yesterday's AI-decision BUY recommendations returned as current |
| **Replay Engine — Symbol Journey** | "Paper order placed" label / `PAPER BUY` result for `paper_eligible=true` records with no `paper_order_id` |
| **Ops Centre — Execution card** | "Not placed" label (ambiguous) when `paper_eligible=false` and no `paper_order_id` |

Operators saw a contradictory state: a stale-data warning banner at the top and
live-looking BUY cards below it — a safety and clarity problem.

---

## What Active State Is Now Session-Gated

Every component now checks `is_today_session` — a field computed by comparing
the scan snapshot's IST date against today's IST date.

### Backend

**`phase15_scan_context.py`**
- Added `_today_ist()` and `_snapshot_date_ist()` helpers (same pattern as `daily_session_manager.py`).
- `build_scan_context()` now returns:
  - `is_today_session: bool` — `True` only when the snapshot's IST date equals today's IST date.
  - `snapshot_date_ist: str | None` — the IST date of the snapshot as `YYYY-MM-DD`.
  - `buy_recommendations_disabled` is now `True` when stale **or** not today's session.

**`pipeline_stats.py`**
- After building `top_buy_candidates` and `candidate_gate_details`, checks `is_today_session`.
- When `False` (previous-day scan): both lists are set to `[]` and the response includes:
  - `session_mismatch: true`
  - `session_message: "Waiting for today's first fresh scan"`
- `gate_summary`, `funnel`, and `first_blocker` continue to reflect the real stale-scan state for operator diagnostics.

**`phase11_autonomous.py` — `get_recommendation_queue()`**
- After building items, checks `is_today_session` from scan context.
- When `False`: returns `items=[]`, `count=0`, `session_mismatch: true`.
- `advisory_only` / `paper_only` flags preserved.

**`replay_engine.py`**
- `get_replay_sessions()` now adds `is_today_session` and `snapshot_date_ist` to each session dict, letting the UI gate display per session without client-side date arithmetic.
- `_build_symbol_journey()` execution label fix:
  - `paper_eligible=true` + no execution event → `result="ELIGIBLE"`, `reason="Paper eligible"` (was `"PENDING"` / misleading).
  - `paper_eligible=true` + `ORDER_SUBMITTED`/`ORDER_EXECUTED` → `result="PAPER BUY"`, `reason="Paper order placed and recorded"` (unchanged).
  - `paper_eligible=false` → `SKIPPED` / `REJECTED` (unchanged).

**`ops_centre.py`**
- Execution card fallthrough fix:
  - `paper_eligible=false` + no `paper_order_id` + BUY decision → `"Not executed"` (was the ambiguous `"Not placed"`).
  - `paper_eligible=true` + no order → `"Paper Eligible"` (unchanged, correct).

### Frontend

**`AIInvestigationCentre.tsx`**
- `Session` type extended with `is_today_session?: boolean` and `snapshot_date_ist?: string`.
- `isTodaySession` derived from `selectedSession?.is_today_session` (with IST date fallback).
- `showStaleGuard = isLatestSession && !isTodaySession`.
- When `showStaleGuard=true`: the active candidate card grid is **replaced** with a "Waiting for today's first fresh scan" neutral empty state showing the previous session date.
- A collapsed `<details>` "Previous session snapshot — historical / not actionable" accordion gives access to yesterday's symbols without implying they are actionable.
- `Paper ✓` badge is now gated on `sym.paper_eligible && isTodaySession` — suppressed when viewing a previous-session snapshot as latest.

**`AIPaperTraderPage.tsx`**
- `PipelineStats` type extended with `session_mismatch?: boolean` and `session_message?: string`.
- When `session_mismatch=true`:
  - The "BUY Candidates This Scan" table is **replaced** with a "Waiting for today's first fresh scan" neutral empty state.
  - The "Blocked Candidates" / `candidate_gate_details` section is suppressed.
  - The existing stale-warning banner, disabled-BUY notice, and funnel diagnostic remain visible.

---

## What Historical Data Is Preserved

The following are **completely untouched**:

| Data | Status |
|------|--------|
| `pipeline_events` table | Untouched — no reads or writes |
| `phase20_paper_trades` table | Untouched |
| `scan_state` / `signal_snapshots` | Read-only, no schema changes |
| Audit logs | Untouched |
| Learning records | Untouched |
| Backtest data | Untouched |
| Previous-session snapshot rows | Accessible via the "Previous session snapshot" accordion |

The fix only changes **what is displayed as active** — it adds a session-date
check on top of existing staleness detection; it does not delete or alter
any persisted records.

---

## UI Behaviour Before and After the First Fresh Scan

### Morning / Pre-Scan (scan is previous trading day's)

| Component | Before fix | After fix |
|-----------|-----------|-----------|
| AI Paper Trader BUY candidates | Yesterday's BUY table visible | "Waiting for today's first fresh scan" neutral state |
| AI Paper Trader blocked candidates | Yesterday's gate failures visible | Suppressed |
| Phase 11 recommendation queue | Yesterday's BUY recs returned | `items=[]`, `session_mismatch=true` |
| AI Investigation Centre symbol grid | Yesterday's cards with `Paper ✓` | "Waiting for today's first fresh scan" + collapsed accordion |
| `Paper ✓` badge | Always shown when `paper_eligible=true` | Suppressed for previous-session snapshot |
| Funnel diagnostic / stale banner | Shown | Still shown (unchanged) |

### After First Fresh Scan of the Day

Once the scan runs and `snapshot_ts` falls within the current IST trading
day, `is_today_session=true`:

- All candidate cards, Paper ✓ badges, agent journey steps, and execution labels reappear normally.
- The "Waiting" state is replaced by the live candidate grid.
- No operator action is required — the transition is automatic.

---

## Trading Logic and Threshold Confirmation

- **No trade logic changed.** Strategy evaluation, entry gates, risk thresholds, position sizing, R:R computation, and kill-switch logic are all untouched.
- **No live orders are placed.** All changes are advisory / display only (`advisory_only=true`, `paper_only=true` flags preserved throughout).
- **Stale detection threshold (90 min) unchanged.** `STALE_AFTER_S = 90 * 60` in `phase15_scan_context.py` is unchanged. Session-date awareness is additive — a scan can be within the 90-min freshness window but still be yesterday's session (e.g. a late-night run); `is_today_session=false` now correctly covers that case.
- **No schema changes.** `phase20_paper_trades`, `pipeline_events`, `scan_state`, and all other tables retain their existing schemas.

---

## Test Coverage

`test_morning_stale_reset.py` verifies the morning stale scenario end-to-end with
four test classes:

1. **`TestPhase15SessionDate`** — `build_scan_context()` returns `is_today_session=False` for a 25-hour-old scan and `True` for a 30-minute-old scan.
2. **`TestPipelineStatsSessionMismatch`** — `get_pipeline_stats()` returns `top_buy_candidates=[]` and `session_mismatch=True` for a previous-day scan, and shows candidates for today's scan.
3. **`TestPhase11RecommendationQueue`** — `get_recommendation_queue()` returns `items=[]` and `session_mismatch=True` for a previous-day scan.
4. **`TestReplayEngineExecutionLabel`** — `_build_symbol_journey()` labels `paper_eligible=True` (no execution event) as `ELIGIBLE` / `"Paper eligible"`, and only uses `PAPER BUY` / `"Paper order placed"` for confirmed `ORDER_SUBMITTED` events.

All tests use mocked/in-memory stores — no production DB writes, no network calls.
