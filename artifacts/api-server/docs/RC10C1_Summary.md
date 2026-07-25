# RC-10C1 Portfolio Core — Implementation Summary

> **Status:** MERGED  
> **Test count:** 612 unit tests passing (265 new + 347 pre-existing)  
> **Module location:** `artifacts/api-server/src/python/src/portfolio/`

---

## Objective

Implement a production-grade portfolio state, capital allocation, position sizing,
exposure control, P&L accounting, persistence, and reconciliation layer for the
NSE Intraday Trading Platform.

**Hard boundaries:**
- RC-8 remains the final risk authority; RC-7 remains the execution authority.
- RC-10D is the only broker adapter layer.
- No portfolio component calls Zerodha, places, modifies, or cancels orders.
- `paper_mode = True` is enforced in `PortfolioConfig` via `model_validator` and
  cannot be overridden at runtime.

---

## Modules Implemented

| Module | Class | Responsibility |
|--------|-------|----------------|
| `contracts.py` | _(models)_ | All frozen Pydantic v2 models — enums, `CashBalance`, `MarginState`, `BuyingPower`, `PortfolioLot`, `PortfolioPosition`, `InstrumentExposure`, `SectorExposure`, `StrategyExposure`, `ExposureSnapshot`, `PositionPnL`, `PortfolioPnL`, `CapitalAllocation`, `AllocationDecision`, `PositionSizeRequest`, `PositionSizeDecision`, `LimitCheckResult`, `LimitCheckReport`, `PortfolioSnapshot`, `PortfolioEvent`, `PortfolioDiscrepancy`, `PortfolioReconciliationReport`, `PortfolioHealth` |
| `config.py` | `PortfolioConfig` | 20+ frozen config fields; paper_mode locked in validator |
| `state_manager.py` | `PortfolioStateManager` | In-memory state — cash, margin, positions; `initialise()`, `restore_from_snapshot()`, `reserve_order_capital()`, `release_order_capital()`, `apply_fill()`, `update_market_price()`, `get_snapshot()`, `halt()`, `resume()`, `is_stale()` |
| `position_manager.py` | `PositionManager` | FIFO lot tracking — `open_position()`, `increase_position()`, `reduce_position()`, `close_position()`, `update_unrealised_pnl()`, `is_fill_duplicate()`, `restore_position()` |
| `ledger.py` | `PortfolioEventLedger` | Append-only in-memory event log with sequence numbers; idempotent `replay()` for recovery |
| `pnl.py` | `PnLEngine` | NSE charge estimation; `build_position_pnl()`, `build_portfolio_pnl()` |
| `capital_allocator.py` | `CapitalAllocator` | 7-step constraint check — daily loss, drawdown, per-trade value, sector/strategy caps; `evaluate_allocation()`, `is_daily_loss_breached()`, `is_drawdown_breached()` |
| `position_sizer.py` | `PositionSizer` | Fixed-risk sizing with lot rounding and AI confidence scaling; `calculate_size()` |
| `exposure.py` | `ExposureEngine` | Instrument, sector, and strategy exposure tracking; `calculate_exposure()`, `check_instrument_exposure()`, `check_sector_exposure()`, `check_strategy_exposure()` |
| `limits.py` | `PortfolioLimitEngine` | 9 limit types with CRITICAL / WARNING severity evaluated in priority order; `check_all_limits()` |
| `health.py` | `PortfolioHealthMonitor` | Readiness / liveness / degraded logic; `compute_health()` |
| `reconciliation.py` | `PortfolioReconciliationEngine` | Broker-neutral dict reconciliation — 13 discrepancy types, staleness detection via `snapshot_at` or `as_of` keys |
| `service.py` | `PortfolioService` | Façade over all subsystems — 14 public methods, dependency injection, no direct broker calls |
| `repositories/` | 4 async repos | `PortfolioSnapshotRepository`, `PortfolioEventRepository`, `CapitalAllocationRepository`, `ReconciliationRepository` — SQLAlchemy async via `asyncio.to_thread` |

**ORM models** added to `src/database/models/portfolio_models.py`:
`PortfolioSnapshotModel`, `PortfolioEventModel`, `CapitalAllocationModel`,
`ExposureSnapshotModel`, `ReconciliationRunModel`, `ReconciliationDiscrepancyModel`,
`PortfolioHealthEventModel`.

---

## Correctness Bugs Found and Fixed by Code Review

The automated code reviewer ran four rejection rounds, each catching a real functional
defect before merge.

### 1 — `recover()` discarded all open positions
**Bug:** `PortfolioService.recover()` called `initialise(snapshot.cash.total)`, which
resets the position manager to empty. After recovery, cash reflected post-trade state
but positions were gone — an inconsistent portfolio.

**Fix:** Added `PortfolioStateManager.restore_from_snapshot(snapshot)` which rebuilds
`_cash`, `_margin`, `_version`, `_last_updated`, `_peak_equity`, `_daily_pnl`, and all
positions (via new `PositionManager.restore_position()`). `recover()` now calls this
instead of `initialise()`.

---

### 2 — `ledger.replay()` three-way breakage
**Bug (a):** Referenced `state_manager._applied_idempotency_keys` — field does not
exist. Correct name: `_seen_idempotency_keys`.

**Bug (b):** Called `apply_fill(fill_data_dict)` passing a plain dict instead of
keyword arguments.

**Bug (c):** Fill event payloads did not store `instrument_symbol`, making replay
unable to reconstruct positions.

**Fix:** Corrected field name, switched to keyword-arg call, added
`"instrument_symbol"` (and `"order_id"`, `"sector"`) to the fill event payload in
`service.apply_fill()`.

---

### 3 — Cash invariant broken for reserved orders
**Bug:** In the BUY-with-reservation branch of `state_manager.apply_fill()`:
```python
new_available = self._cash.available  # unchanged
new_total = self._cash.total - order_value
```
When `reserved_amount ≠ fill_value` (partial fill or slippage),
`available + blocked ≠ total`, causing a `CashBalance` `ValidationError` at runtime.

**Fix:** Derive `new_available` from `new_total − new_blocked` so the invariant holds
exactly under all fill scenarios:

| Scenario | Effect |
|----------|--------|
| `reserved == fill_value` | `available` unchanged; all from blocked |
| `reserved > fill_value` (partial fill) | Excess reservation returned to available |
| `reserved < fill_value` (slippage) | Extra taken from available |

---

### 4 — `Decimal` not imported in `ledger.py`
**Bug:** `ledger.replay()` constructs fill kwargs using `Decimal(...)` but `Decimal`
was not imported, raising `NameError` at runtime for any recovery replay containing a
fill event.

**Fix:** Added `from decimal import Decimal` to `ledger.py`.

---

### 5 — Idempotency key ≠ fill_id mismatch aborts recovery
**Bug:** `restore_from_snapshot()` seeds `_seen_idempotency_keys` from lot `fill_id`
values. The event `idempotency_key` is a separate identifier and may differ. When they
differ, `replay()` bypassed the fast-path dedup, re-called `apply_fill()`, and
`PositionManager.increase_position()` raised `InvalidPositionTransitionError` (seeing
a duplicate `fill_id` in lots). `replay()` did not catch this exception — recovery
aborted.

**Fix (primary):** `state_manager.apply_fill()` now checks for a duplicate `fill_id`
in the position's lot list *before* registering the `idempotency_key`, and returns a
no-op snapshot instead of proceeding.

**Fix (belt-and-suspenders):** `ledger.replay()` now catches
`InvalidPositionTransitionError` in addition to `DuplicateEventError`, treating both
as safe no-ops so recovery cannot fail on already-applied fills.

---

### 6 — Cold-start recovery used zero cash
**Bug:** `recover(snapshot=None)` called `initialise(Decimal("0"))`, leaving the
portfolio with no capital. All allocation checks would then fail, silently blocking
trading on first deployment or after snapshot loss.

**Fix:** Cold-start now calls `initialise(self.config.initial_capital)`.

---

### 7 — Reconciliation staleness missed RC-10D schema key
**Bug:** Staleness detection read only `broker_snapshot["as_of"]`. The documented
RC-10D broker-neutral schema uses `"snapshot_at"`. A stale snapshot arriving with
`"snapshot_at"` produced no `STALE_BROKER_SNAPSHOT` discrepancy — the stale-broker
protection gate was bypassed.

**Fix:** Staleness check now reads
`broker_snapshot.get("snapshot_at") or broker_snapshot.get("as_of")`,
with `snapshot_at` taking precedence when both are present.

---

## Test Coverage

| File | Tests |
|------|-------|
| `test_contracts.py` | Frozen model validation, Decimal rejection |
| `test_config.py` | paper_mode lock, field defaults |
| `test_position_manager.py` | Open/increase/reduce/close, FIFO P&L, duplicate fill |
| `test_pnl.py` | NSE charge estimation, portfolio P&L aggregation |
| `test_capital_allocator.py` | 7 allocation constraints, breached limit scenarios |
| `test_position_sizer.py` | Fixed-risk sizing, lot rounding, confidence scaling |
| `test_exposure.py` | Instrument / sector / strategy exposure limits |
| `test_limits.py` | 9 limit types, CRITICAL / WARNING severity ordering |
| `test_state_manager.py` | State transitions, reservation accounting (exact / partial / slippage), idempotency |
| `test_reconciliation.py` | 13 discrepancy types, staleness (both key formats), legacy alias |
| `test_service.py` | Full integration — recovery preserving positions, replay with key mismatch, cold-start capital, cash/P&L consistency |

**Total: 612 tests passing** (265 new portfolio + 347 pre-existing platform tests).

---

## Related Documentation

| File | Contents |
|------|----------|
| `RC10C1_Portfolio_Architecture.md` | Module dependency graph, data flow, design decisions |
| `RC10C1_Position_Accounting.md` | FIFO lot model, P&L calculation, NSE charges |
| `RC10C1_Capital_Allocation.md` | 7-step constraint check walkthrough |
| `RC10C1_Reconciliation_Runbook.md` | How to run reconciliation, interpret discrepancy types |
| `RC10C1_Recovery_Runbook.md` | Startup recovery procedure, snapshot restore, replay |
| `RC10C1_Production_Audit.md` | Checklist for live deployment readiness |
| `RC10C1_Freeze_Readiness.md` | Freeze criteria, what is and is not complete |
| `RC10C1_Preimplementation_Verification.md` | Pre-build invariant checks and design sign-off |
