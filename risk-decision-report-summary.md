# Risk Decision Report — V1 & V2 Summary

**Project:** ApexQuant AI — NSE Trading Dashboard  
**Page route:** `/risk-decision-report`  
**Agent:** Risk Agent (Agent 6, amber)  
**Mode:** Advisory-only · Read-only · Paper / Research only  

---

## Version 1 — Risk Decision Report

### What it does
A rejection log that shows every candidate the Risk Agent evaluated in the last scan, why each was rejected or approved, and which gates caused the most blocks.

### Backend
**File:** `artifacts/api-server/src/python/phase20_gates.py`

- Added `risk_decision_report()` — reads the last Risk Agent entry evaluation from KV (`last_entry_evaluation`); falls back to running a fresh `evaluate_entries()` if nothing is cached.
- Added `_GATE_META` dict — maps every gate ID to a human-readable label (e.g. `min_risk_reward` → "Minimum Risk / Reward").
- Added `_GLOBAL_GATES` frozenset — session-level gates that apply to all candidates (scan freshness, circuit breaker, market open, data provider).
- Computes `gate_pressure` — per-gate count and percentage of candidates blocked, sorted descending.
- Computes `top_blockers` — top-3 gate labels by block count.

**File:** `artifacts/api-server/src/python/main.py`
- Added `phase15_risk_decision_report` command dispatcher.

**File:** `artifacts/api-server/src/routes/phase15.ts`
- Added `GET /api/phase15/risk-decision-report` route with 60 s timeout.

### Frontend
**File:** `artifacts/trading-dashboard/src/pages/RiskDecisionReportPage.tsx` *(created)*

| UI element | Detail |
|-----------|--------|
| Summary KPIs | Total candidates · Eligible · Rejected · Pass rate |
| Top blockers banner | Red chips for the top-3 blocking gates |
| Global gates warning | Purple banner listing any session-level gate failures |
| Gate pressure chart | Horizontal bars, one per gate, showing blocked count and % |
| Filter / search | Toggle All / Eligible / Rejected; free-text search by symbol or sector |
| Per-symbol candidate cards | Auto-expanded for rejected candidates |
| Card header | Symbol · Sector · Strategy · Verdict chip (ELIGIBLE / REJECTED + fail count) |
| KPI row | Confidence · Opportunity Score · R:R · Trade Quality |
| Sizing row | Position Size · Capital Required · Stop Loss · Target |
| Info row | Sector · Entry Price · Risk Amount · Expected Hold |
| Gate results | Expandable list; failed gates first; each shows Actual · Required · ❌ FAIL marker |

**Files also modified:**
- `artifacts/trading-dashboard/src/App.tsx` — route `/risk-decision-report → RiskDecisionReportPage`
- `artifacts/trading-dashboard/src/components/layout/AgentConfig.ts` — "Risk Decision Report" as first page under Risk Agent

---

## Version 2 — AI Risk Analysis Centre

### What changed
The existing V1 page was enhanced in-place (not replaced). A 5-tab navigation was added around the existing content, and 15 new sections were implemented across 7 new component files. All V2 computation is client-side from the single existing API call — no new endpoints, no additional scans, no polling changes.

### Backend additions
**File:** `artifacts/api-server/src/python/phase20_gates.py`

| Addition | Detail |
|----------|--------|
| Evaluation history tracking | After every `evaluate_entries()` run, a lightweight summary is appended to `evaluation_history` KV list (dedup by `scan_id`, capped at 60 entries). Each entry records: `evaluated_at`, `scan_id`, `total_count`, `blocked_count`, `gate_blocked_counts` (per-gate dict). |
| 7-day / 30-day gate stats | `risk_decision_report()` reads history and computes `blocked_7d`, `blocked_30d`, and `trend` (increasing / stable / decreasing / insufficient_data) for every gate in `gate_pressure`. |
| History timeline | Builds `history_timeline` list (date, total, blocked, eligible, pass_rate) from history entries. |
| New response fields | `history_timeline`, `history_days`, `history_entries`, `label` added to the return dict. |

### Frontend — new files

| File | Sections |
|------|----------|
| `src/components/riskReport/types.ts` | All shared TypeScript interfaces: Gate, Sizing, Candidate, GatePressure, HistoryEntry, Report, SimSettings |
| `src/components/riskReport/helpers.ts` | Gate weights, risk score computation, severity classification, threshold parser, pass hints, decision explainer, simulator engine, gate descriptions, gate recommendations, formatting helpers |
| `src/components/riskReport/EnhancedCandidateCard.tsx` | Sections 1, 2, 3, 4, 12, 13 |
| `src/components/riskReport/GateAnalysisPanel.tsx` | Sections 5, 6, 10, 11 |
| `src/components/riskReport/SimulatorPanel.tsx` | Section 7 |
| `src/components/riskReport/ComparePanel.tsx` | Sections 8, 9 |
| `src/components/riskReport/ExportPanel.tsx` | Section 14 |

**Modified:** `src/pages/RiskDecisionReportPage.tsx` — rewritten to orchestrate tabs and pass gate-click callbacks that open the Gate Details modal on the Gate Analysis tab.

### Tab structure

```
Candidates | Gate Analysis | Simulator | Compare | Export
```

### All 15 sections

| # | Section | Tab | How it works |
|---|---------|-----|-------------|
| 1 | **What Would Make This Pass?** | Candidates | For each failed gate with a parseable threshold, shows Actual / Required / Gap and a plain-English hint: "If Minimum Risk / Reward increased by 0.50×, this gate would PASS." Rendered inline under each failed gate row. |
| 2 | **Expected Opportunity** | Candidates | Per rejected candidate, computes Expected Return %, Expected Profit ₹, Capital Required, Risk Amount from sizing data already in the API response. Advisory-only collapsible panel. |
| 3 | **Rejection Severity** | Candidates | Counts per-symbol failed gates (excluding global gates). NEAR PASS (≤1) · MODERATE (2–3) · POOR QUALITY (4+). Shown as a colour-coded badge in every rejected card header. |
| 4 | **AI Risk Recommendation** | Candidates | Per failed gate, surfaces a hardcoded advisory sentence from a gate → text map in `helpers.ts`. Collapsible "AI Risk Recommendations" panel inside each card. No AI API call. |
| 5 | **Top Blocker Analysis** | Gate Analysis | Table of all gates with Today / 7-day / 30-day blocked counts and an Increasing ↑ / Stable → / Decreasing ↓ trend arrow. Data comes from the enriched `gate_pressure` in the API response. |
| 6 | **Gate Heatmap** | Gate Analysis | Grid of tiles, one per gate, coloured by rejection rate: Green (0%) · Yellow (1–30%) · Orange (30–60%) · Red (60%+). Each tile shows gate label, blocked count, and rate. Click any tile → Gate Details modal. |
| 7 | **Pass Simulator** | Simulator | 6 sliders (Min Confidence, Min Opportunity Score, Min R:R, Min Trade Quality, Sector Cap, Per-Stock Cap), initialised by parsing current thresholds from gate reason strings. Re-evaluates all candidates in memory on every slider change. Shows approved / rejected counts, estimated exposure, and per-candidate ✓/✗ chips. "Simulation only" disclaimer. |
| 8 | **Pipeline Replay** | Compare | Visual waterfall: Supervisor → Market Data → Research → Market Intel → Monitoring → Strategy → **Risk Agent ❌** → Execution (BLOCKED). The Risk Agent node is highlighted red with a ✗ badge. Failed gates listed below as the stop reason. Select any candidate from chips at the top. |
| 9 | **Stock Comparison** | Compare | Multi-select up to 3 stocks. Side-by-side comparison table covering 17 fields (sector, strategy, regime, all score fields, sizing fields, risk score, severity) plus one row per gate showing ✅ / ❌. |
| 10 | **Gate Details Modal** | Any | Click any gate name anywhere on the page. Modal shows: purpose, impact, current threshold (parsed from reason), today / 7d / 30d blocked counts, trend, min / median / max actual values across candidates, global-vs-per-symbol classification. |
| 11 | **Historical Timeline** | Gate Analysis | Toggle Today / Yesterday / 7d / 30d. Horizontal bar chart of `history_timeline` entries: each bar shows blocked / total ratio. Pass rate percentage shown on the right. Shows "Insufficient history" message when fewer than 1 calendar day of data exists. |
| 12 | **Risk Score** | Candidates | Weighted sum of gate pass/fail. Gate weights: global safety gates = 3, core quality gates = 2–2.5, portfolio/position gates = 1. Score 0–100 mapped to Very Low (90+) · Low (75+) · Moderate (55+) · High (35+) · Very High (<35). Score ring shown in every candidate card header. Failed gate labels listed as risk factors. |
| 13 | **Decision Explainer** | Candidates | One plain-English paragraph per candidate, generated client-side. Adapts sentence structure to 1 / 2+ / global-only failure patterns. Includes failed gate count vs total. Always visible (not collapsible). |
| 14 | **Export** | Export | **CSV** — all candidates × all fields + one column per gate (PASS/FAIL) + reason columns; downloaded via `Blob` + `createObjectURL`. **JSON** — full report object. **PDF** — `window.print()` with `@media print` CSS. No extra libraries. |
| 15 | **Performance** | Architecture | One API call to `GET /api/phase15/risk-decision-report`, same as V1. No additional scans triggered. No polling changes. All V2 computation (simulator, risk score, decision explainer, comparison, export) runs client-side from the cached response. |

### TypeScript status
**0 errors** across all new and modified files.

### Performance
- API calls: **1** (same endpoint as V1)
- Extra scans triggered: **0**
- Polling frequency: **unchanged**
- All V2 logic: **client-side**

---

## File inventory

### Created
- `artifacts/api-server/src/python/phase20_gates.py` *(modified)*
- `artifacts/trading-dashboard/src/components/riskReport/types.ts`
- `artifacts/trading-dashboard/src/components/riskReport/helpers.ts`
- `artifacts/trading-dashboard/src/components/riskReport/EnhancedCandidateCard.tsx`
- `artifacts/trading-dashboard/src/components/riskReport/GateAnalysisPanel.tsx`
- `artifacts/trading-dashboard/src/components/riskReport/SimulatorPanel.tsx`
- `artifacts/trading-dashboard/src/components/riskReport/ComparePanel.tsx`
- `artifacts/trading-dashboard/src/components/riskReport/ExportPanel.tsx`

### Modified
- `artifacts/trading-dashboard/src/pages/RiskDecisionReportPage.tsx`
- `artifacts/api-server/src/python/main.py` (V1)
- `artifacts/api-server/src/routes/phase15.ts` (V1)
- `artifacts/trading-dashboard/src/App.tsx` (V1)
- `artifacts/trading-dashboard/src/components/layout/AgentConfig.ts` (V1)
