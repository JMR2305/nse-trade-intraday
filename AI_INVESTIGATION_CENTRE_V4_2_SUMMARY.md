# AI Investigation Centre — Version 4.2 Summary

**Date:** 6 August 2026  
**File:** `artifacts/trading-dashboard/src/pages/AIInvestigationCentre.tsx`

---

## What Was Built

Version 4.2 adds three investigation modes and a full suite of new sub-components to the AI Investigation Centre page (`/ai-investigation`). The existing Trading Day Replay is untouched — all new functionality is additive.

---

## New: Mode Selector Bar

A three-button switcher appears at the very top of the page, above the Replay Control Panel:

| Mode | Description |
|---|---|
| **Trading Day Replay** | Full market session pipeline (existing functionality, unchanged) |
| **Single Stock Investigation** | Deep-dive into one symbol through every AI pipeline stage |
| **Compare Two Stocks** | Side-by-side decision path analysis for any two symbols |

The PageHeader subtitle updates dynamically to match the active mode.

---

## New: Single Stock Investigation Mode

### Stock Search Panel (left column)
- Search by **Symbol** or **Sector**
- Each result shows the symbol, final action badge (BUY / WATCH / AVOID), and confidence %
- Clicking a symbol loads its full journey from the existing `/replay/sessions/{id}/symbol/{symbol}` endpoint

### Animated Pipeline (right column)
- Vertical timeline of all 10 stages (9 real + Portfolio Management)
- Each node pulses blue while active, turns green/red/amber after evaluation
- Simulated timestamps shown per stage using `STAGE_OFFSETS_S` offsets from `snapshot_ts`
- **Time Machine controls** inline: Play, Pause, Step Back ‹, Step Forward ›, Reset, speed (0.5×/1×/2×/4×), Jump-to-agent dropdown

### Agent Explanation Panel (click any stage node)
Shows for that stage:
- Decision (Accepted / Rejected) + Score + Threshold
- Plain-English Reason
- **Gate Results** table — each gate passed ✓ or failed ✗
- **Suggested Improvement** for rejected stages (dynamically generated from the rejection reason)
- AI Thinking key-value data
- Static Inputs / Outputs / Dependencies from `STAGE_META`
- Estimated processing time

### BUY / SELL Timeline
When a paper trade exists for the symbol: Entry price, Entry time, Quantity, Capital used, Stop loss, Target, Exit time, Exit reason, Net P&L.

### End-of-Replay Report (shown when replay reaches the last stage)
- AI Verdict (BUY / AVOID / WATCH)
- Decision quality, Risk quality, Stages Passed / Total
- Pipeline Bottleneck, Best Agent, Worst Agent
- Overall AI Rating (confidence %)

---

## New: Compare Two Stocks Mode

- Two independent symbol pickers (Stock A / Stock B), each with a live search field
- Side-by-side table of all pipeline agents with result badge, score, and truncated reason for each symbol
- Final comparison row: action, confidence, strategy
- Second symbol triggers its own `journeyDataB` query (enabled only in compare mode)

---

## Enhancement: Trading Day Replay — Step Buttons

Two new buttons added to the existing Replay Control Panel controls:

- **‹ Step Back** — moves one stage backward, sets state to Paused
- **› Step Forward** — moves one stage forward, sets state to Paused

These work alongside the existing Play / Pause / Stop / Restart / Speed / Jump controls.

---

## Enhancement: Trading Day End-of-Session Report

When the trading day replay **completes**, a `TradingDayEndReport` card appears below the tabs:

- AI Verdict (Positive / Mixed), Decision Quality %, Missed Opportunities count
- False Positives (losing trades), False Negatives (missed opps with >1% move)
- Pipeline Bottleneck (stage with highest rejection ratio)
- Win Rate, Overall AI Rating

---

## New Constants & Types

| Name | Purpose |
|---|---|
| `PageMode` | Union type `"trading_day" \| "single_stock" \| "compare"` |
| `STAGE_OFFSETS_S` | Per-stage simulated seconds-after-open (10 stages) |
| `STAGE_META` | Static inputs / outputs / dependencies / data-used per agent (10 stages) |

---

## New Sub-Components

| Component | Role |
|---|---|
| `ModeSelectorBar` | Top-of-page 3-mode switcher |
| `SingleStockReplayView` | Full single-stock animated pipeline with controls and BUY/SELL timeline |
| `AgentExplanationPanel` | Per-stage detail: score, gates, reason, AI thinking, static meta |
| `SingleStockEndReport` | End-of-replay verdict card for single stock mode |
| `ComparePanel` | Two-column A vs B agent score comparison |
| `TradingDayEndReport` | End-of-session report for trading day replay |
| `stockStageColor()` | Status-to-colour mapping for single-stock stage nodes |
| `stageTimestamp()` | Derives simulated IST timestamp for each pipeline stage |

---

## New State Variables

| Variable | Type | Purpose |
|---|---|---|
| `pageMode` | `PageMode` | Active mode (trading_day / single_stock / compare) |
| `symbolB` | `string \| null` | Second symbol for compare mode |

## New Query

| Query key | Endpoint | Enabled when |
|---|---|---|
| `inv-journey-b` | `replay/sessions/{id}/symbol/{symbolB}` | `symbolB` set + `pageMode === "compare"` |

---

## Files Changed

| File | Change |
|---|---|
| `artifacts/trading-dashboard/src/pages/AIInvestigationCentre.tsx` | All v4.2 additions (~900 lines added, zero existing features removed) |

TypeScript: **0 errors**  
Runtime: **0 errors** (confirmed via HMR logs + screenshot)
