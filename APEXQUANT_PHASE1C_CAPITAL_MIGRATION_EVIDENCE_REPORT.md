# APEXQUANT PHASE 1C — CAPITAL MIGRATION EVIDENCE REPORT

**Date:** 2026-08-21  
**Environment:** Production (`nse-trade-intraday.replit.app`)  
**Operation:** Paper capital rebase ₹5,00,000 → ₹1,00,000  
**Outcome:** ✅ APPLIED — all 11 verification steps passed  
**Controlling plan:** APEXQUANT_PHASE1_REVISED_CAPITAL_UNIVERSE_EXECUTION_PLAN.md  

---

## Migration Timeline

| Event | Timestamp (UTC) |
|---|---|
| Pre-migration verification captured | 2026-08-21T12:19:40Z |
| Migration executed (`POST /api/phase20/capital-migration`) | 2026-08-21T12:20:38Z |
| Post-migration status verified (`ALREADY_APPLIED`) | 2026-08-21T12:20:52Z |
| Total elapsed | ~72 seconds |

---

## 1. PRE-MIGRATION SETTINGS (Baseline)

Captured via `GET /api/phase20/settings` at 2026-08-21T12:19:40Z.

| Field | Value |
|---|---|
| `initial_capital` | 500000 |
| `active_intraday_universe` | NIFTY_50 |
| `auto_paper_entries` | false |
| `auto_paper_entries_confirmed_at` | null |
| `auto_paper_exits` | true |
| `bootstrap_paper_enabled` | false |
| `config_hash` | `81df262bfdbdaaf5` |
| `per_stock_exposure_cap_pct` | 25 |
| `risk_per_trade_pct` | 1 |
| `daily_loss_limit_pct` | 3 |
| `circuit_breaker_loss_threshold` | 3 |

Pre-migration risk limits (absolute) at ₹5,00,000:

| Limit | Pre-migration (₹5,00,000) |
|---|---|
| per_stock_exposure_cap | ₹1,25,000 |
| sector_exposure_cap | ₹2,00,000 |
| portfolio_deployed_cap | ₹4,00,000 |
| risk_per_trade | ₹5,000 |
| daily_loss_limit | ₹15,000 |
| circuit_breaker_daily_loss_limit | ₹15,000 |
| bootstrap_max_order_value | ₹15,000 |

Pre-migration position state:
- `open_count = 0`
- `exit_pending_count = 0`
- `positions = []`

Pre-migration capital migration status:
- `status = CONFIRMATION_REQUIRED`
- `current_capital = 500000`
- `closed_trade_count = 6`
- `realized_pnl = −278.74`
- `preserved = true`

---

## 2. MIGRATION RESPONSE

`POST /api/phase20/capital-migration` executed at 2026-08-21T12:20:38Z.  
Payload: `{ "confirmation_text": "I confirm there are no open or exit-pending paper positions and approve rebasing paper capital to ₹100,000.", "reviewed_by": "operator" }`

```json
{
    "success": true,
    "paper_only": true,
    "broker_orders_called": false,
    "status": "APPLIED",
    "message": "Paper capital was rebased to ₹100,000. Closed trade history and realized P&L were preserved; automatic paper entries remain paused.",
    "target_capital": 100000,
    "current_capital": 100000,
    "auto_paper_entries": false,
    "open_count": 0,
    "exit_pending_count": 0,
    "active_positions": [],
    "closed_history": {
        "closed_trade_count": 6,
        "realized_pnl": -278.74,
        "preserved": true
    },
    "derived_limits": {
        "initial_capital": 100000,
        "per_stock_exposure_cap": 25000,
        "sector_exposure_cap": 40000,
        "portfolio_deployed_cap": 80000,
        "risk_per_trade": 1000,
        "daily_loss_limit": 3000,
        "circuit_breaker_daily_loss_limit": 3000,
        "bootstrap_max_order_value": 15000
    },
    "previous_capital": 500000,
    "reviewed_by": "operator",
    "legacy_cash_before": 500000,
    "cash_after_rebase": 99721.26,
    "deployed_capital_after": 0,
    "legacy_positions_cleared": true,
    "legacy_pnl_history_preserved": true,
    "previous_phase11_starting_capital": null,
    "previous_phase11_topup_target": null,
    "phase11_starting_capital": 100000,
    "phase11_topup_target": 100000
}
```

---

## 3. POST-MIGRATION SETTINGS

Captured via `GET /api/phase20/settings` immediately after migration.

| Field | Pre-migration | Post-migration | Changed? |
|---|---|---|---|
| `initial_capital` | 500000 | **100000** | ✅ Changed |
| `active_intraday_universe` | NIFTY_50 | NIFTY_50 | No change |
| `auto_paper_entries` | false | false | No change |
| `auto_paper_entries_confirmed_at` | null | null | No change |
| `auto_paper_exits` | true | true | No change |
| `bootstrap_paper_enabled` | false | false | No change |
| `config_hash` | `81df262bfdbdaaf5` | **`fad093c2b1a194dd`** | ✅ Changed (expected — capital is part of hash) |
| All other fields | (unchanged) | (unchanged) | No change |

> **config_hash change is expected.** The hash is computed from all settings including `initial_capital`. The only setting that changed is `initial_capital`; all operational settings (thresholds, fills, charges, universe, entries, bootstrap) are unchanged.

---

## 4. CAPITAL MIGRATION STATUS (Post)

Captured via `GET /api/phase20/capital-migration/status` at 2026-08-21T12:20:52Z.

| Field | Value |
|---|---|
| `status` | **ALREADY_APPLIED** ✅ |
| `current_capital` | **100000** ✅ |
| `auto_paper_entries` | false ✅ |
| `open_count` | 0 ✅ |
| `exit_pending_count` | 0 ✅ |
| `closed_history.closed_trade_count` | 6 ✅ |
| `closed_history.realized_pnl` | −278.74 ✅ |
| `closed_history.preserved` | true ✅ |
| `legacy_paper_cash` | 99721.26 |
| `paper_only` | true ✅ |
| `broker_orders_called` | false ✅ |
| `confirmation_required` | false ✅ |

---

## 5. RISK LIMIT COMPARISON BEFORE / AFTER

| Limit | Pre-migration (₹5,00,000) | Post-migration (₹1,00,000) | Change |
|---|---|---|---|
| `initial_capital` | ₹5,00,000 | **₹1,00,000** | −80% |
| `per_stock_exposure_cap` (25%) | ₹1,25,000 | **₹25,000** | −80% |
| `sector_exposure_cap` (40%) | ₹2,00,000 | **₹40,000** | −80% |
| `portfolio_deployed_cap` (80%) | ₹4,00,000 | **₹80,000** | −80% |
| `risk_per_trade` (1%) | ₹5,000 | **₹1,000** | −80% |
| `daily_loss_limit` (3%) | ₹15,000 | **₹3,000** | −80% |
| `circuit_breaker_daily_loss_limit` (3%) | ₹15,000 | **₹3,000** | −80% |
| `bootstrap_max_order_value` (fixed) | ₹15,000 | ₹15,000 | No change |

All percentage-based limits scaled proportionally. The `bootstrap_max_order_value` is a fixed constant (not percentage-based) and is intentionally unchanged.

---

## 6. CLOSED TRADE PRESERVATION PROOF

| Metric | Pre-migration | Post-migration | Match? |
|---|---|---|---|
| `closed_trade_count` | 6 | 6 | ✅ Identical |
| `realized_pnl` | −278.74 | −278.74 | ✅ Identical |
| `preserved` | true | true | ✅ |

The migration response explicitly confirmed:
- `"legacy_pnl_history_preserved": true`
- `"legacy_positions_cleared": true` (no open positions existed — nothing to clear)
- `"closed_history.preserved": true`

**Cash reconciliation:**  
`cash_after_rebase = 99,721.26 = 1,00,000 − 278.74`  
The post-rebase cash balance correctly deducts the cumulative realized loss (₹278.74) from the new starting capital (₹1,00,000). This is the expected behaviour: the migration preserves P&L history by adjusting the cash balance accordingly.

No trade row was modified. Closed trade records retain their original entry/exit prices, timestamps, and P&L.

---

## 7. CONFIRMATION: AUTO ENTRIES AND BOOTSTRAP REMAIN DISABLED

| Setting | Pre-migration | Post-migration |
|---|---|---|
| `auto_paper_entries` | false | **false** ✅ |
| `auto_paper_entries_confirmed_at` | null | **null** ✅ |
| `bootstrap_paper_enabled` | false | **false** ✅ |
| `auto_paper_exits` | true | **true** ✅ (exits-only continues) |

The migration module explicitly pauses entries during execution (`_pause_entries_best_effort()`) and does not re-enable them. The migration response message states: *"automatic paper entries remain paused."*

---

## 8. CONFIRMATION: ACTIVE UNIVERSE UNCHANGED

| Setting | Pre-migration | Post-migration |
|---|---|---|
| `active_intraday_universe` | NIFTY_50 | **NIFTY_50** ✅ |

Universe switch (Phase 1D/1E) has not been performed. The NIFTY_50 universe remains active.

---

## 9. CONFIRMATION: NO TRADES OR POSITIONS CHANGED

| Check | Result |
|---|---|
| `positions` post-migration | `[]` ✅ |
| `open_count` | 0 ✅ |
| `exit_pending_count` | 0 ✅ |
| `closed_trade_count` pre | 6 |
| `closed_trade_count` post | 6 ✅ (unchanged) |
| `realized_pnl` pre | −278.74 |
| `realized_pnl` post | −278.74 ✅ (unchanged) |
| Any trade row modified | No — migration only writes `phase20_settings`, `paper_capital_migration_status`, and KV keys |
| Phase 20 safety files touched | No — `phase20_executor.py`, `phase20_scheduler.py`, `phase20_exits.py`, `phase20_eod_outcomes.py` unchanged |

---

## 10. CONFIRMATION: NO LIVE ORDERS

| Check | Value |
|---|---|
| `paper_only` | true |
| `broker_orders_called` | false |
| Broker API calls made | None |
| Real money at risk | None — paper simulation only |

The migration is a DB write operation. It calls no broker APIs. It emits a `CAPITAL_REBASE` pipeline event (internal only). No orders of any kind were placed.

---

## PHASE 1C OUTCOME SUMMARY

| Step | Check | Result |
|---|---|---|
| 1 | `auto_paper_entries = false` (pre) | ✅ PASS |
| 2 | `bootstrap_paper_enabled = false` (pre) | ✅ PASS |
| 3 | `positions = []` (pre) | ✅ PASS |
| 4 | `exit_pending_count = 0` (pre) | ✅ PASS |
| 5 | Baseline captured | ✅ DONE |
| 6 | Migration executed, `status = APPLIED` | ✅ PASS |
| 7 | `initial_capital = 100000` (post) | ✅ PASS |
| 8 | `per_stock_exposure_cap = 25000` | ✅ PASS |
| 9 | `risk_per_trade = 1000` | ✅ PASS |
| 10 | `daily_loss_limit = 3000` | ✅ PASS |
| 11 | `circuit_breaker_daily_loss_limit = 3000` | ✅ PASS |
| 12 | `migration status = ALREADY_APPLIED` (post) | ✅ PASS |
| 13 | Closed trade count unchanged (6) | ✅ PASS |
| 14 | Realized P&L unchanged (−278.74) | ✅ PASS |
| 15 | `positions = []` (post) | ✅ PASS |
| 16 | `auto_paper_entries = false` (post) | ✅ PASS |
| 17 | `bootstrap_paper_enabled = false` (post) | ✅ PASS |
| 18 | `active_intraday_universe = NIFTY_50` (post) | ✅ PASS |
| 19 | No broker orders called | ✅ PASS |
| 20 | Phase 0C/0D files untouched | ✅ PASS |

**All 20 checks passed. Phase 1C is complete.**

---

## WHAT CHANGED

| Component | Before | After |
|---|---|---|
| `phase20_settings.initial_capital` | 500000 | **100000** |
| `phase20_settings.config_hash` | `81df262bfdbdaaf5` | **`fad093c2b1a194dd`** |
| `phase20_kv_store.phase11_starting_capital` | null | **100000** |
| `phase20_kv_store.phase11_topup_target` | null | **100000** |
| `paper_capital_migration_status` | CONFIRMATION_REQUIRED | **ALREADY_APPLIED** |
| Legacy paper cash | 500000 | **99,721.26** |

## WHAT DID NOT CHANGE

- All execution settings (thresholds, fill model, charges, cooldown)
- All operational settings (universe, scan interval, circuit breaker thresholds)
- `auto_paper_entries` (remains false)
- `bootstrap_paper_enabled` (remains false)
- `auto_paper_exits` (remains true)
- Closed trade records (6 trades, P&L −₹278.74)
- Active open positions (0)
- Phase 20 executor, scheduler, exits, and EOD safety code
- Phase 0C/0D safety guards
