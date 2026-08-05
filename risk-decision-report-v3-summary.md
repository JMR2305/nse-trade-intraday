# AI Risk Intelligence & Optimization Center — V3 Summary

**Page:** Risk Decision Report  
**Route:** `/risk-decision-report`  
**Agent:** Risk Agent (ApexQuant AI)  
**Status:** Advisory-only · Read-only · Paper trading only  
**Date completed:** 5 August 2026

---

## Overview

V3 extends the AI Risk Analysis Centre (V2) with a sixth **Intelligence** tab that surfaces 15 learning and analytics sections, turning the page from a passive rejection log into a self-improving risk advisor. No thresholds are changed automatically. No live execution. All output is advisory.

---

## Tab Structure (6 tabs)

| # | Tab | What it shows |
|---|-----|---------------|
| 1 | **Candidates** | All scanned symbols with composite risk scores, position sizing, sector tags, strategy signals, and ELIGIBLE / REJECTED verdicts |
| 2 | **Gate Analysis** | Gate pass/fail heatmap across all symbols, top blocker table, 7-day rejection history timeline, per-gate detail modal with recommendations |
| 3 | **Simulator** | Client-side slider simulator — adjust any gate threshold and instantly see how the candidate list would change (no server call) |
| 4 | **Compare** | Pipeline replay for rejected symbols + side-by-side stock comparison with radar chart |
| 5 | **Export** | Browser-native CSV / JSON / PDF export of the full report (no extra libraries) |
| 6 | **Intelligence** *(V3 new)* | Optimization dashboard + 7 analytics sub-tabs — see details below |

---

## Intelligence Tab — 15 Sections

### Always-visible: Optimization Dashboard (Section 15)
Top-line metrics: optimization score ring, false rejection rate, opportunity leakage estimate, learning maturity %, and system health status. Rendered at the top of the Intelligence tab regardless of which sub-tab is active.

### Sub-tab 1 — False Rejection Analysis
| Section | Description |
|---------|-------------|
| S1 | False rejection table — rejected candidates that subsequently gained ≥ 2 % within 5 days (sourced from yfinance outcome tracking) |
| S2 | Gate accuracy table — per-gate false-rejection rate and accuracy score |
| S9 | Threshold impact — estimated P&L impact of each gate's false rejections |

### Sub-tab 2 — Opportunity Leakage
| Section | Description |
|---------|-------------|
| S3 | Leakage periods — date ranges where rejection rate spiked vs. realized market gains |
| S13 | Confidence calibration — predicted vs. actual win rates across confidence buckets |

### Sub-tab 3 — AI Threshold Optimizer
| Section | Description |
|---------|-------------|
| S4 | Per-gate threshold optimizer — AI-suggested relaxation with estimated uplift (advisory, no auto-apply) |
| S5 | Regime-specific optimization — different suggested thresholds for trending, ranging, volatile, and low-volatility regimes |

### Sub-tab 4 — Strategy Effectiveness
| Section | Description |
|---------|-------------|
| S6 | Strategy effectiveness table — win rate, avg gain, risk-adjusted return, and regime fit per strategy |
| S7 | Outcome predictor — probability scores for win / breakeven / loss given current market conditions |

### Sub-tab 5 — Learning Feedback Loop
| Section | Description |
|---------|-------------|
| S8 | Visual pipeline — 5-stage learning cycle: completed trade → learning generated → knowledge updated → threshold impact → future recommendation |
| S10 | AI coach — natural-language advisory messages generated from accumulated learning |

### Sub-tab 6 — Reports
| Section | Description |
|---------|-------------|
| S11 | Weekly optimization report — 7-day rejection stats, false/correct counts, largest missed opportunity, largest avoided loss, review items |
| S12 | Monthly optimization report — 30-day trend, regime breakdown, top 3 recommendations, accuracy trend chart |

### Sub-tab 7 — Decision Sandbox
| Section | Description |
|---------|-------------|
| S14 | Enhanced sandbox — replay any rejected candidate with AI-suggested threshold presets and historical context panels |

---

## Backend (New in V3)

### New module: `phase20_v3_analytics.py`

| Function | Purpose |
|----------|---------|
| `record_rejections(candidates)` | Appends rejected candidates to the `rejection_tracker` KV store (max 300 entries, FIFO rotation) |
| `_update_outcomes()` | Fetches yfinance price data for up to 12 recent rejections to assess false rejections (max `MAX_OUTCOME_FETCH = 12`) |
| `get_v3_analytics()` | Assembles all 15 sections, returns full payload; 30-minute KV cache under `v3_analytics_cache` |

### New routes (in `phase15.ts`)

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/phase15/v3-analytics` | Fetch V3 analytics (uses 30-min cache) |
| `POST` | `/phase15/v3-analytics/refresh` | Force cache bust and regenerate |

### Changes to `phase20_gates.py`
- `evaluate_entries()` now calls `record_rejections()` after each evaluation cycle so the V3 tracker populates automatically as the Risk Agent runs scans
- `risk_decision_report()` return enriched with: `blocked_7d`, `blocked_30d`, `trend`, `history_timeline`, `history_days`, `history_entries`

---

## Frontend Components

### V3 components (`src/components/riskReport/v3/`)

| File | Sections rendered |
|------|-------------------|
| `types.ts` | All V3 TypeScript interfaces |
| `OptimizationDashboard.tsx` | S15 — score ring + top-line metrics |
| `RejectionAnalysis.tsx` | S1, S2, S9 |
| `LeakageSection.tsx` | S3, S13 |
| `OptimizerSection.tsx` | S4, S5 |
| `StrategiesSection.tsx` | S6, S7 |
| `LearningSection.tsx` | S8, S10 |
| `ReportsSection.tsx` | S11, S12 |
| `SandboxSection.tsx` | S14 |
| `IntelligenceTab.tsx` | Orchestrator — fetches `/phase15/v3-analytics`, renders S15 + 7 sub-tabs |

### Page (`RiskDecisionReportPage.tsx`)
- Added `"intelligence"` to the `Tab` union type
- Added 6th entry to `TABS` array with `Brain` icon from lucide-react
- Renders `<IntelligenceTab candidates={candidates} />` when Intelligence tab is active

---

## Performance

| Concern | Detail |
|---------|--------|
| Extra API calls | +1 (`GET /phase15/v3-analytics`) — only triggered when operator opens Intelligence tab |
| Cache duration | 30 minutes (KV store) — subsequent opens within the window are instant |
| yfinance fetches | Capped at **12 symbols per call** (`MAX_OUTCOME_FETCH = 12`) |
| New scans | None |
| New polling | None |
| Background workers | None |

---

## TypeScript

Typecheck passes at **0 errors** across the full dashboard workspace after two fixes applied during V3 wire-up:

| File | Issue | Fix |
|------|-------|-----|
| `LearningSection.tsx` | Circular `ReturnType<() => typeof s8>` | Replaced with explicit `type S8Data = Parameters<typeof LearningFeedbackSection>[0]["data"]` |
| `ReportsSection.tsx` | `unknown && JSX` in JSX position | Wrapped condition with `Boolean()` |

---

## First-Run Behaviour

`rejection_tracker` and `v3_analytics_cache` KV keys are empty on a fresh instance. All 15 Intelligence sections display a **"data accumulating"** empty state — this is correct and expected. Sections populate automatically as:
1. The Risk Agent runs scan evaluations (fills `rejection_tracker`)
2. 5 days pass and yfinance can assess outcomes (fills false-rejection data)
3. Paper trades complete (feeds learning sections)

No manual seed data is required. The system is fully self-populating.

---

## Version History

| Version | What was built |
|---------|----------------|
| V1 | Basic rejection log — why each trade was blocked by the Risk Agent |
| V2 | AI Risk Analysis Centre — 5 tabs, 15 enhanced sections, client-side simulator, export |
| V3 | AI Risk Intelligence & Optimization Center — 6th Intelligence tab, 15 learning/analytics sections, V3 backend analytics module, outcome tracking |
