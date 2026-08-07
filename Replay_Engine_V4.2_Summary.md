# Replay Engine V4.2 — Summary
**ApexQuant AI · Data Integrity + Portfolio Flow**

---

## Overview

V4.2 was a backend data-integrity and replay-engine enhancement — not a UI redesign. The goal was to eliminate count inconsistencies, connect real paper-trade data to the portfolio view, and give operators a single coherent audit trail from market scan through trade exit.

---

## What Was Fixed & Built

### Part 1 — Pipeline Count Conservation

**Problem:** The Execution stage was reporting more outputs than inputs (e.g. 6 in → 7 out, Rejected = −1), which is mathematically impossible.

**Fix (`replay_engine.py → _build_stages_from_snapshot`):**
- `rejected` is now always `max(0, stocks_in − stocks_out)` — negative values are clamped to zero
- Post-build integrity warnings are logged whenever a stage's counts are inconsistent
- No stage can ever report more outputs than inputs

---

### Part 2 — Single Source of Truth

**Problem:** Different pages computed stage counts independently, leading to drift.

**Fix:** All replay pages read from one `build_replay()` response keyed by `scan_id`. Counts are not recalculated anywhere in the UI — the frontend simply renders what the backend returns.

---

### Part 3 & 4 — Execution Connected to Portfolio

**Problem:** Execution showed paper orders; Portfolio showed zero positions because it read from the wrong table.

**Fix (`_get_execution_trades`):**
- Now queries `phase20_paper_trades WHERE scan_id = %s` — strictly session-scoped
- Returns `[]` safely when no concrete `scan_id` is available (no cross-session contamination)
- Fields returned: `symbol`, `side` (→ `action`), `fill_price`, `quantity`, `stop_loss`, `target`, `confidence`, `strategy_name`, `trade_quality_score`, `fill_ts`, `exit_ts`, `exit_price`, `exit_rule`, `realized_pnl`

**`build_replay()` now returns** an `execution_trades` list alongside stages and symbols.

---

### Part 5 — Side-Aware Portfolio Accounting (`LivePositions.tsx`)

**`computePortfolioSnapshots` now branches on `action`:**

| Trade Side | Effect |
|---|---|
| BUY | Debit cash, credit invested; if exit is already on the same row, close it out |
| SELL (exit-only row) | Return cost basis + realized P&L to cash; clamp to prevent negative balances |

Cash and invested balances are always `Math.max(0, …)` — negative equity is impossible in the UI.

---

### Part 6 — Bottom Timeline (`BottomTimeline.tsx`)

Replaced the old overlapping event strip with a **7-section zoomable chronological timeline**:

```
PRE MARKET → SCAN → DECISION → BUY → MONITOR → SELL → POST MARKET
```

- **Action-aware:** BUY chips filtered to `action !== "SELL"` rows; SELL chips from closed-BUY rows **and** explicit SELL-side ledger rows
- **De-overlapping:** simultaneous events stagger into sub-rows
- **Zoom:** Ctrl+wheel or pinch scales the time axis
- **Horizontal scroll:** native overflow scroll on the track
- **Fallback:** when no real trades exist, renders comparison-data chips from the Decision Comparison endpoint

---

### Part 7 — Trade Event Cards (`TradeEventCard.tsx`)

Every BUY event card shows:
> Symbol · Buy Time · Buy Price · Quantity · Capital Used · Stop Loss · Target · Confidence · Strategy · Risk Score · Portfolio after BUY

Every SELL event is represented by the same card when the BUY row has an exit recorded:
> Sell Time · Sell Price · Exit Reason · Holding Time · P&L ₹ · P&L % · Portfolio after SELL

Cards are expandable/collapsible; each manages its own state independently.

---

### Part 10 — Replay Integrity Panel (`ReplayIntegrityPanel.tsx`)

Eight automated checks run on every replay session:

| # | Check | Trigger |
|---|---|---|
| 1 | No negative rejected counts | ERROR if any stage has rejected < 0 |
| 2 | No stage creates symbols | ERROR if stocks_out > stocks_in |
| 3 | Input = Passed + Rejected | ERROR if over-counted; WARNING if >20% unaccounted |
| 4 | No duplicate symbols in any stage | WARNING |
| 5 | Execution input ≤ Decision output | ERROR |
| 6 | Cash never negative | WARNING |
| 7 | Position sizing valid (≤ starting capital) | ERROR |
| 8 | Portfolio positions consistent | WARNING if stage expected count mismatches actual DB trades (>25% delta) |

**Overall badge:** PASS / WARNING / ERROR  
**Error response shape:** all failure paths return `overall`, `snapshot_ts`, `stages_count`, `trades_count` so the frontend never crashes on a missing scan.

---

## New Files

| File | Purpose |
|---|---|
| `src/components/replay/ReplayIntegrityPanel.tsx` | 8-check audit table, self-fetching |
| `src/components/replay/TradeEventCard.tsx` | Expandable BUY/SELL detail card + `ExecutionTrade` type export |
| `src/components/replay/BottomTimeline.tsx` | 7-section zoomable timeline (full rewrite) |
| `src/components/replay/LivePositions.tsx` | Side-aware portfolio accounting (full rewrite) |

---

## Modified Files

| File | Key Change |
|---|---|
| `artifacts/api-server/src/python/replay_engine.py` | Count conservation fix; `_get_execution_trades` queries `phase20_paper_trades` by scan_id; bidirectional conservation check; normalized error shape for integrity endpoint |
| `artifacts/api-server/src/python/main.py` | Added `replay_integrity` command dispatch |
| `artifacts/api-server/src/routes/replay.ts` | Added `GET /api/replay/sessions/:scanId/integrity` |
| `artifacts/trading-dashboard/src/pages/AIInvestigationCentre.tsx` | Removed redundant `inv-integrity` query; wired `executionTrades` to all child components |

---

## What Was Not Done (Deferred)

| Part | Description | Status |
|---|---|---|
| Part 8 | Live portfolio animation (cash/equity count-up transitions as stages advance) | Deferred |
| Part 11 | End-of-day summary panel (win rate, profit factor, drawdown, AI accuracy) | Deferred |

---

## Key Invariants Established

1. **Session isolation:** `phase20_paper_trades` is always queried with `WHERE scan_id = %s` — trades from other sessions never appear in a replay.
2. **Conservation law:** No stage may report `stocks_out > stocks_in`. The rejection count absorbs all slack: `rejected = max(0, stocks_in − stocks_out)`.
3. **Portfolio integrity:** Portfolio math always branches on `action`; cash never goes below zero through clamping.
4. **Integrity response contract:** The `/integrity` endpoint always returns `{ overall, snapshot_ts, stages_count, trades_count, checks }` — even on error — so the panel never renders undefined values.
