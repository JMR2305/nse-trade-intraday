# AI Investigation Centre — V5.0 Summary
**Task #418 · Merged**

---

## What Was Built

Four new React components added to the **Trading Day Replay** mode of `/ai-investigation`, all under `artifacts/trading-dashboard/src/components/replay/`:

---

### 1. `TradingDaySelector.tsx`
Replaces the old plain dropdown with a rich session picker card rendered above the Replay Control Panel.

| Feature | Detail |
|---|---|
| Prev / Next arrows | Navigate across all 21 replay sessions chronologically |
| Session dropdown | Shows scan date, BUY count, symbol count; `(Latest)` tag on the most recent |
| Latest Session button | One-click jump to the newest scan |
| Refresh button | Calls `refetchSessions()` to pull new sessions without reloading the page |
| Metadata grid | 6 cells: Trading Date · Market · Replay Duration · Universe Size · Trades · Status badge |
| Counter | `1 / 21 sessions` — correctly handles the backend `"latest"` alias |

---

### 2. `StockFlowViz.tsx`
Animated chip visualisation inserted into the left column of Tab 0, below the Funnel Statistics bar.

| Feature | Detail |
|---|---|
| Stage zones | One labelled zone per pipeline stage (teal for reached stages, slate for future) |
| Animated chips | Teal chips = BUY candidates · Red chips = rejected symbols flowing through active stage |
| CSS keyframes | `@keyframes chipFlow` injected via `<style>` tag — no two-phase React render needed |
| Replay-aware | Chips only animate inside the zone matching `activeStageIdx`; past zones show a faded count |

---

### 3. `BottomTimeline.tsx`
Full-width horizontal event timeline rendered at the bottom of the Trading Day Replay view (above the End-of-Session Report).

| Feature | Detail |
|---|---|
| Two-zone scale | **Zone A (0–35 % of track):** scan pipeline stages (0–120 s pre-market) — no pin compression |
| | **Zone B (35–100 % of track):** intraday trade events by real market time (09:15–15:30) |
| Zone shading | Teal background for scan zone · "← Scan Pipeline →" and "← Intraday →" zone labels |
| Pin types | Teal = scan stage · Emerald = BUY entry · Red = SELL/exit · Slate = Market Open/Close |
| Clickable pins | Each pin calls `onJumpToStage(idx)` to teleport the replay to that stage |
| Progress cursor | Animated teal cursor + fill bar tracks `activeStageIdx` across the track |
| Auto-scroll | `scrollRef` centers the cursor in view as replay advances |
| Min width | 1100 px — 10 scan stages across 35 % = ~38 px apart, fully readable |

---

### 4. `LivePositions.tsx`
Per-position P&L table in the Tab 0 right column, rendered after the Symbol List.

| Feature | Detail |
|---|---|
| **Progressive visibility** | Stage 8 (Execution): only OPEN/PENDING entries shown — buys just placed |
| | Stage 9 (Portfolio Mgmt): WIN/LOSS exits also revealed — positions closed |
| Pre-execution placeholder | "Live positions appear when replay reaches the Execution stage" |
| Amber badge | "Exits visible at Portfolio stage" shown at stage 8 to set expectations |
| Table columns | Symbol · Qty · Entry ₹ · Current ₹ · P&L ₹ · P&L % · Capital Used · Status · Exit Reason |
| Running totals | Capital Used + Net P&L in header, colour-coded |
| Data join | Enriches `portfolioTrades` with `current_price` from `comparisonData` for live P&L |

---

## Wiring Changes in `AIInvestigationCentre.tsx`

| Change | Location |
|---|---|
| `import` for all 4 components | Top of file, after lucide imports |
| `refetch: refetchSessions` | Destructured from the `inv-sessions` useQuery |
| `<TradingDaySelector>` card | Inserted between `<ModeSelectorBar>` and the Replay Control Panel |
| `<StockFlowViz>` | Inside Tab 0 left column, after Funnel Statistics |
| `<LivePositions>` | Inside Tab 0 right column, after Symbol List |
| `<BottomTimeline>` | At end of `pageMode === "trading_day"` block, before End-of-Session Report |

---

## No New Backend Endpoints
All four components consume the existing four replay endpoints:

```
GET  /replay/sessions
GET  /replay/sessions/{id}
GET  /replay/sessions/{id}/comparison
GET  /replay/sessions/{id}/symbol/{symbol}
```

---

## Key Design Decisions

- **Two-zone scale in BottomTimeline** — scan stages run for ~60 s within a 22 500 s trading window; a linear scale compresses all 10 pins into 2 px. The piecewise scale dedicates 35 % of track width to the scan zone regardless of wall-clock proportion.
- **Stage-gated visibility in LivePositions** — positions are revealed at the replay stage that semantically produces them: entries at Execution (8), exits at Portfolio Management (9). This avoids the original all-at-once reveal.
- **No circular imports** — `EXECUTION_STAGE_IDX = 8` and `PORTFOLIO_STAGE_IDX = 9` are hardcoded in `LivePositions.tsx` rather than imported from the main page file.
- **CSS keyframes via `<style>` tag** in `StockFlowViz.tsx` — avoids two-phase React state needed for dynamic Tailwind class generation.
