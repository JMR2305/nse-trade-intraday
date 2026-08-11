# FRONTEND BACKTEST MONITOR — VERIFICATION REPORT

Date: 2026-08-11 · PAPER / RESEARCH ONLY — no live defaults changed, no live orders placed.

---

## 1. Long 20-symbol runs — health status

All five 20-symbol runs (2026-06-18 → 2026-08-11, 5m interval, ₹1,00,000) are **RUNNING and healthy** as of this report. None have stalled or failed.

| Run ID | Config | Done / Total | Progress |
|---|---|---|---|
| BT-19c7568aa7 | A Baseline | 416 / 2819 | 15% |
| BT-94bd1a3c5d | B Scale-in | 321 / 2819 | 11% |
| BT-27b0ca58b7 | C Vol-Normalized | 281 / 2819 | 10% |
| BT-cb2a4e5081 | D Recommended | 281 / 2819 | 10% |
| BT-bc6b55820d | E Higher Sizing | 281 / 2819 | 10% |

These are still running at the time of writing and were not cancelled. Estimated completion: 1–2 hours.

---

## 2. Small frontend smoke runs — status at report time

Five smoke runs (RELIANCE, TCS, INFY, HDFCBANK, ICICIBANK · 5m · 2026-06-18 → 2026-08-11 · ₹1,00,000) launched and **RUNNING** in parallel with the 20-symbol runs.

| Run ID | Config | Status | Done / Total |
|---|---|---|---|
| BT-5d2ba71f70 | A Baseline | RUNNING | 176 / 2819 |
| BT-c5e69f6674 | B Scale-in | RUNNING | 176 / 2819 |
| BT-536cc0f4bd | C Vol-Normalized | RUNNING | 151 / 2819 |
| BT-da5e7f9a58 | D Recommended | RUNNING | 151 / 2819 |
| BT-dcbfd63627 | E Higher Sizing | RUNNING | 146 / 2819 |

Smoke runs are visible in the frontend Investigation Center immediately (see §4/§5).

---

## 3. Run IDs — A/B/C/D/E

### Small smoke runs (5 symbols):
- **A Baseline**: `BT-5d2ba71f70`
- **B Scale-in**: `BT-c5e69f6674`
- **C Vol-Normalized**: `BT-536cc0f4bd`
- **D Recommended**: `BT-da5e7f9a58`
- **E Higher Sizing**: `BT-dcbfd63627`

### 20-symbol wide-universe runs:
- **A Baseline**: `BT-19c7568aa7`
- **B Scale-in**: `BT-94bd1a3c5d`
- **C Vol-Normalized**: `BT-27b0ca58b7`
- **D Recommended**: `BT-cb2a4e5081`
- **E Higher Sizing**: `BT-bc6b55820d`

---

## 4. Where to see them in the frontend

Navigate to **Investigation Center** (sidebar → Operations → Investigation Center, or `/investigation-center`).

The **Backtest Runs** card on the left shows all runs, newest first. The card now displays:

| Field | Shown as |
|---|---|
| Config name | Bold label: "A Baseline", "B Scale-in", "C Vol-Normalized", "D Recommended", "E Higher Sizing" |
| Run ID | Monospace subtitle |
| Status | Colour-coded badge: QUEUED (amber), RUNNING (blue), COMPLETED (green), FAILED (red) |
| Progress | `146/2819 ticks · 1/5 syms · 5%` with a live progress bar |
| Elapsed time | `4m 53s` (top-right of progress row) |
| ETA | `~108m 1s left` (blue, computed from tick rate) |
| Latest timestamp | `2026-06-19 09:35` (last processed tick) |
| Error text | Shown in red, first 120 chars |
| Completed summary | `₹4,094 (4.06%) · 2 trades · 100% WR · Xh Ym total` inline |

---

## 5. Investigation Center auto-refresh

**Yes — auto-refresh is active.** The Backtest Runs query has `refetchInterval: 5_000` (every 5 seconds). The card header shows "auto-refresh 5s". Progress bars, tick counts, ETAs, and status badges all update without page reload. All per-run detail queries (events, trades, portfolio) also poll every 5 seconds while the run is PENDING or RUNNING.

---

## 6. Run Comparison panel

A new **Run Comparison** card was added to the Investigation Center (above the Advanced Replay section). It appears automatically whenever any completed runs are present. Columns:

Config · Symbols · Trades · P&L · Return · Win% · Profit Factor · DD% (realized-equity only — no MTM, clearly labelled) · Cancelled (order vs. open position) · SI ✓/✗ (scale-in executions/rejections with exact counts) · Vol-rej (RISK_REJECTED events) · Missed opps · Avg hold time

Clicking a row selects that run and loads it in the replay panel below.

The panel is powered by a new `GET /api/backtest/run/:id/stats` endpoint that runs a fast aggregation SQL (no replay bundle required). Stats are cached for 5 minutes in TanStack Query and fetched for every completed run automatically. Stats fetch errors are caught silently — the cell shows `…` rather than crashing the page.

---

## 7. Best config in the small smoke run (5 symbols)

Results pending — smoke runs are still RUNNING at report time (all at ~5–6%). The comparison table will populate automatically once any run completes. The 1-symbol GLAND reference from the previous report (CAPITAL_DEPLOYMENT_FIX_VERIFICATION.md) showed C (Higher sizing 1.5%, no scale-in) delivering the best single-symbol P&L (+55% vs baseline), while D (combined scale-in + vol normalization) was close (+50%). For a 5-symbol mix, volume normalization and scale-in are expected to show clearer separation because the total-exposure cap actually engages.

---

## 8. Wait for 20-symbol results before enabling anything?

**Yes — wait for the full 20-symbol result.** The 1-symbol GLAND validation confirms the mechanics work correctly and defaults are preserved. The 5-symbol smoke run will confirm multi-symbol handling. But the authoritative answer on whether scale-in and volume normalization meaningfully improve capital deployment across a realistic NSE universe requires the 20-symbol result where the total-exposure cap, cross-symbol competition for capital, and the volume gate all engage meaningfully. The full results should be available within 1–2 hours.

Until then: **no live/paper default changes, scale-in remains OFF by default, no live orders.**

---

## Summary of changes in this session

| Item | Status |
|---|---|
| Enhanced Backtest Runs card (config label, progress bar, ETA, symbol count, elapsed, latest ts) | ✅ Done |
| Run Comparison table (all 12 metrics columns, auto-populates for completed runs) | ✅ Done |
| `GET /api/backtest/run/:id/stats` endpoint (event counts, profit factor, avg hold time) | ✅ Done |
| SQL fix (`fill_ts::timestamptz`, `exit_ts::timestamptz` for avg hold time calculation) | ✅ Done |
| Stats fetch errors caught silently (no Vite overlay, cell shows `…`) | ✅ Done |
| 20-symbol wide runs — not cancelled, still RUNNING | ✅ Confirmed |
| 5-symbol smoke runs A/B/C/D/E — launched and RUNNING | ✅ Confirmed |
| Live/paper defaults — unchanged | ✅ Confirmed |
| No live orders placed | ✅ Confirmed |
