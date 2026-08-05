# Risk Decision Report — Feature Summary

## What Was Built

A new **Risk Decision Report** page added to the ApexQuant AI trading dashboard under the **Risk Agent** section. It shows every candidate evaluated in the last Risk Agent entry eligibility run, with per-gate pass/fail results, exact thresholds, and a gate-pressure analysis.

---

## Files Changed

| File | Change |
|------|--------|
| `artifacts/api-server/src/python/phase20_gates.py` | Added `risk_decision_report()` function + gate metadata |
| `artifacts/api-server/src/python/main.py` | Added `phase15_risk_decision_report` command dispatcher |
| `artifacts/api-server/src/routes/phase15.ts` | Added `GET /api/phase15/risk-decision-report` route |
| `artifacts/trading-dashboard/src/pages/RiskDecisionReportPage.tsx` | New page (created) |
| `artifacts/trading-dashboard/src/App.tsx` | Import + route `/risk-decision-report` |
| `artifacts/trading-dashboard/src/components/layout/AgentConfig.ts` | Nav item under Risk Agent |

---

## Backend: `risk_decision_report()`

- Reads the last Risk Agent entry evaluation from the Postgres KV store (`last_entry_evaluation`) — **no scan triggered, read-only**
- Falls back to running `evaluate_entries()` fresh if no cached evaluation exists
- Enriches every gate with a human-readable label (e.g. `min_risk_reward` → `Minimum Risk / Reward`)
- Computes **gate pressure**: for each gate, how many candidates it blocked and what percentage of the pool that represents, sorted descending
- Returns `top_blockers` — the top-3 gate labels filtering the most opportunities

### Response shape (key fields)

```json
{
  "available": true,
  "evaluated_at": "2026-08-05T08:49:00Z",
  "scan_id": "254012707e17...",
  "market_state": "OPEN",
  "global_gates": [ { "gate": "scan_fresh", "label": "Scan Freshness", "passed": true, "reason": "..." } ],
  "global_pass": true,
  "candidates": [
    {
      "symbol": "HDFCLIFE",
      "sector": "FINANCE",
      "recommendation": "BUY",
      "eligible": false,
      "failed_gates": ["min_risk_reward", "per_stock_cap"],
      "gates": [ { "gate": "min_confidence", "label": "Minimum Confidence", "passed": true, "reason": "Confidence 73.9 vs minimum 60.0", "is_global": false } ],
      "sizing": { "quantity": 28, "entry_price": 542.25, "stop_loss": 524.0, "target_price": 569.0, "position_value": 15183.0, "risk_amount": 497.0, "rr_ratio": 1.5 },
      "confidence": 73.9,
      "opportunity_score": 64.2,
      "trade_quality_score": 71.9,
      "strategy_name": "Mean Reversion",
      "regime": "Ranging / sideways"
    }
  ],
  "total_count": 6,
  "eligible_count": 4,
  "blocked_count": 2,
  "gate_pressure": [
    { "gate_id": "per_stock_cap", "label": "Per-Stock Exposure Cap", "blocked": 2, "blocked_pct": 33.3 }
  ],
  "top_blockers": ["Per-Stock Exposure Cap", "Minimum Risk / Reward", "No Duplicate Open Trade"]
}
```

---

## Frontend Page

**Route:** `/risk-decision-report`  
**Navigation:** Risk Agent → Risk Decision Report (first item, amber accent)

### Sections

#### 1. Summary KPI Bar
| Metric | Description |
|--------|-------------|
| Candidates | Total symbols evaluated in the last run |
| Rejected | Count that failed one or more gates |
| Approved | Count that passed all gates |
| Global Gates Failed | Gates that block ALL candidates at once |

#### 2. Top Blockers Banner
Three amber pills showing the gates that filtered the most opportunities in the current evaluation.

#### 3. Global Gates Warning
If any global gate is failing (e.g. market closed, stale scan, circuit breaker tripped), an amber warning block lists those gates with their reasons — these block every candidate regardless of individual scores.

#### 4. Gate Pressure Chart
Horizontal progress bars, one per failed gate, showing:
- Gate name
- `X / N` candidates blocked
- Percentage of pool blocked
- Colour: red ≥ 80%, amber ≥ 50%, yellow ≥ 25%, teal < 25%

#### 5. Per-Symbol Cards
Default view shows **Rejected only** (toggle to All / Approved / search by symbol or strategy).

Each card shows:

**Header**
- Symbol + 3-letter avatar
- Strategy · Sector · Regime
- Gate fail count + REJECTED / APPROVED verdict badge

**KPI Row** (always visible)
| Field | Source |
|-------|--------|
| Confidence | `calibrated_confidence` from scan |
| Opportunity Score | `opportunity_score` from scan |
| Risk / Reward | `rr_ratio` from scan |
| Trade Quality | `technical_score` (phase20 evaluation) |

**Sizing Row** (always visible)
| Field | Source |
|-------|--------|
| Position Size | Computed qty from risk budget ÷ stop distance |
| Capital Required | `qty × entry_price` |
| Stop Loss | `stop_loss` from scan |
| Target | `target_price` from scan |

**Detail Row**
Sector · Entry Price · Risk Amount · Expected Hold

**Gate Results** (expandable, auto-open for rejected)

Each gate shows:
- ✅ PASS or ❌ FAIL icon
- Human-readable gate name
- For failed gates with threshold: `Actual: X · Required: Y` (parsed from reason string)
- For other gates: the raw reason text
- `global` badge on session-level gates

**Final Decision block**
- APPROVED (green) or REJECTED (red) with list of failed gate IDs

---

## Gates Covered

### Global Gates (apply to all candidates)
| Gate ID | Label |
|---------|-------|
| `scan_fresh` | Scan Freshness |
| `snapshot_consistency` | Snapshot Consistency |
| `provider_zerodha` | Data Provider |
| `no_fallback_data` | No Fallback/Mock Data |
| `market_open` | Market Open |
| `entry_circuit_breaker` | Circuit Breaker |

### Per-Symbol Gates
| Gate ID | Label |
|---------|-------|
| `quote_available` | Quote Available |
| `strategy_regime_eligible` | Strategy / Regime |
| `recommendation_buy` | BUY Recommendation |
| `min_confidence` | Minimum Confidence |
| `min_opportunity_score` | Minimum Opportunity Score |
| `min_trade_quality` | Minimum Trade Quality |
| `min_risk_reward` | Minimum Risk / Reward |
| `valid_stop_loss` | Valid Stop-Loss |
| `position_size` | Position Sizing |
| `sufficient_cash` | Sufficient Cash |
| `per_stock_cap` | Per-Stock Exposure Cap |
| `sector_cap` | Sector Exposure Cap |
| `portfolio_deployed_cap` | Portfolio Deployed Cap |
| `daily_loss_limit` | Daily Loss Limit |
| `daily_trade_limit` | Daily Trade Limit |
| `no_open_duplicate` | No Duplicate Open Trade |
| `cooldown` | Symbol Cooldown |

---

## Design Notes

- **Read-only / advisory-only** — never modifies positions, strategies, or orders
- **No extra scan triggered** — reads the KV-stored last evaluation; fresh `evaluate_entries()` only if none exists
- **Auto-expand rejected cards** — operators see failure details immediately without clicking
- **Threshold parsing** — reason strings like `"Confidence 73.9 vs minimum 60.0"` are parsed into `Actual / Required` pairs for the cleaner display the user requested
- **Colour coding** — red < thresholds, amber = borderline, emerald = strong; consistent with rest of dashboard
