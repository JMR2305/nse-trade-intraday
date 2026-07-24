# RC-10C1 Capital Allocation

**Document status:** Baseline  
**Phase:** RC-10C1 Portfolio Core  
**Applicable module:** `src/portfolio/capital_allocator.py`, `src/portfolio/contracts.py`

---

## 1. AllocationDecision Lifecycle

An `AllocationDecision` is produced by the `CapitalAllocator` in response to a capital request from the signal router. It follows a strict lifecycle:

```
                     ┌─────────┐
                     │ REQUEST │
                     └────┬────┘
                          │ evaluate()
               ┌──────────▼──────────┐
               │   Constraint Check   │
               └──────────┬──────────┘
                   Pass   │   Fail
          ┌───────────────┤
          ▼               ▼
     APPROVED         REJECTED ──── terminal (no further transitions)
          │
     (TTL running)
          │
     ┌────▼────────────────────────────────────┐
     │ commit() called before expires_at        ├──► COMMITTED (terminal)
     │ release() called (order cancelled)       ├──► RELEASED  (terminal)
     │ expires_at reached without commit/release├──► EXPIRED   (terminal)
     └─────────────────────────────────────────┘
```

### 1.1 Status Definitions

| Status | Meaning | Next Actions |
|--------|---------|-------------|
| `APPROVED` | Capital reserved; awaiting RC-8 evaluation | → COMMITTED, RELEASED, EXPIRED |
| `REJECTED` | Cannot allocate; reason codes set | Terminal — signal must be dropped |
| `COMMITTED` | Capital deployed; RC-7 has accepted the order | Terminal — release on fill or cancel |
| `EXPIRED` | TTL elapsed before commit; reservation void | Terminal — must re-request |
| `RELEASED` | Reservation explicitly cancelled | Terminal — capital returned to pool |

**COMMITTED decisions** are superseded by fill events: when a fill is received, the committed allocation transitions to position capital and is tracked via open position cost basis, not as a pending allocation.

---

## 2. Constraint Evaluation Order

The capital allocator evaluates constraints in a fixed priority order. The first failing constraint is the `binding_limit` reported in the `AllocationDecision`.

```
1. Portfolio readiness gate
   └─ Is PortfolioHealth.readiness == True?
   └─ Exception: PortfolioNotReadyError

2. Portfolio halted check
   └─ Is PortfolioStatus == HALTED?
   └─ Exception: PortfolioHaltedError

3. Daily loss limit
   └─ Would daily_pnl + proposed_loss > max_daily_loss_amount(equity)?
   └─ Reason code: DAILY_LOSS_LIMIT

4. Drawdown limit
   └─ Is current drawdown >= max_drawdown_pct?
   └─ Reason code: DRAWDOWN_LIMIT

5. Cash reserve protection
   └─ Would available_cash - requested < reserve_amount(equity)?
   └─ Reason code: CASH_RESERVE

6. Gross buying power
   └─ Is requested_capital > BuyingPower.net?
   └─ Reason code: INSUFFICIENT_BUYING_POWER

7. Portfolio gross exposure cap
   └─ Would (gross_exposure + requested) / equity > max_portfolio_exposure_pct?
   └─ Reason code: PORTFOLIO_EXPOSURE_CAP

8. Strategy capital cap
   └─ Would strategy_allocated + requested > max_capital_per_strategy(equity)?
   └─ Reason code: STRATEGY_CAP

9. Instrument exposure cap
   └─ Would instrument_exposure + requested > max_instrument_value(equity)?
   └─ Reason code: INSTRUMENT_EXPOSURE_CAP

10. Sector exposure cap
    └─ Would sector_exposure + requested > max_sector_value(equity)?
    └─ Reason code: SECTOR_EXPOSURE_CAP

11. Maximum open positions
    └─ Is open_position_count >= max_open_positions?
    └─ Reason code: MAX_OPEN_POSITIONS

12. Maximum pending orders
    └─ Is pending_order_count >= max_pending_orders?
    └─ Reason code: MAX_PENDING_ORDERS

13. Minimum order value
    └─ Is requested_capital < min_order_value?
    └─ Reason code: BELOW_MIN_ORDER

14. Maximum order value
    └─ Is requested_capital > max_order_value?
    └─ (Approved capital is capped at max_order_value; not rejected)
```

All passing constraints produce `approved_capital`. Failed constraints produce `rejected_capital = requested_capital - approved_capital` (which may equal `requested_capital` if fully rejected).

---

## 3. Cash Reserve Protection Rule

The cash reserve is the **highest priority financial constraint** (after readiness and halt checks).

```python
reserve_amount = equity * cash_reserve_pct  # e.g. 5% of ₹100,000 = ₹5,000

# Deployment is only allowed if:
available_cash - requested_capital >= reserve_amount
```

**Invariants:**

- Reserve amount is **never allocatable**, regardless of signal confidence or strategy priority.
- Even if available cash significantly exceeds the request, the reserve floor is maintained.
- `ReservedCapitalViolationError` is raised if any allocation attempt would breach the reserve.
- The reserve applies to cash; margin allocation is evaluated separately.
- `BuyingPower.reserved` reflects the current reserve amount at all times.

**Example:**

```
initial_capital   = ₹100,000
cash_reserve_pct  = 0.05  →  reserve = ₹5,000
available_cash    = ₹30,000
max_allocatable   = ₹30,000 - ₹5,000 = ₹25,000

Request: ₹28,000  →  REJECTED (CASH_RESERVE)
Request: ₹20,000  →  APPROVED (within ₹25,000 limit)
```

---

## 4. Strategy Capital Cap

Each strategy has a maximum capital allocation expressed as a percentage of portfolio equity.

```
max_strategy_allocation = equity * max_capital_per_strategy_pct
```

`PortfolioConfig.max_capital_per_strategy_pct` default: `0.40` (40% of equity).

This cap is evaluated against **currently committed + pending allocations** for the strategy, not just the current request. If Strategy A already has ₹35,000 committed and requests another ₹10,000 against a ₹100,000 portfolio (cap = ₹40,000), only ₹5,000 is approved.

Strategy exposure is tracked in `StrategyExposure.allocated_capital` within the `ExposureSnapshot`.

---

## 5. TTL and Staleness Enforcement

### 5.1 Allocation TTL

Every `AllocationDecision` carries an `expires_at` timestamp:

```
expires_at = decided_at + timedelta(seconds=allocation_ttl_s)
```

`PortfolioConfig.allocation_ttl_s` default: `30` seconds.

### 5.2 Staleness Check at Commit

When the signal router attempts to commit an allocation (forward to RC-8):

```python
if decision.is_expired(now=datetime.now(timezone.utc)):
    raise StaleAllocationError(f"Allocation {decision.decision_id} expired at {decision.expires_at}")
```

The decision is not re-evaluated — it is discarded. The caller must request a new allocation with current portfolio state.

### 5.3 Version Check at Commit

In addition to TTL, optimistic concurrency is enforced:

```python
if decision.portfolio_state_version != state_manager.version:
    raise PortfolioVersionConflictError(...)
```

This prevents a scenario where portfolio state changed significantly between allocation approval and commit (e.g., another fill arrived, reducing available capital).

### 5.4 Expired Decision Cleanup

Expired `APPROVED` decisions are treated as `RELEASED` at cleanup time. The reserved capital is returned to the pool. A `ORDER_RESERVATION_RELEASED` event is recorded in the ledger.

---

## 6. Why Portfolio Approval ≠ RC-8 Approval

Portfolio approval and RC-8 approval are **independent evaluations** serving different purposes:

| Dimension | Portfolio Pre-Check | RC-8 Risk Engine |
|-----------|--------------------|--------------------|
| **Authority** | Necessary condition | **Final authority** |
| **Scope** | Portfolio capacity, exposure limits, cash reserve | All risk rules, market-based checks, volatility, correlation |
| **Failure mode** | Reject before reaching RC-8 | May reject even portfolio-approved requests |
| **State used** | Portfolio state (local) | RC-8 internal risk state + portfolio context |
| **Broker calls** | None | None (paper mode) |
| **Result** | `AllocationDecision` | Order approval / rejection |

**A portfolio-approved allocation does not guarantee trade approval.** This is by design. RC-8 may reject an order that the portfolio has capacity for, based on:

- Market volatility conditions
- Correlation with existing risk positions
- Real-time price-based risk thresholds
- Kill-switch status
- Any RC-8-specific rule not represented in portfolio limits

**Stale portfolio state causes fail-closed behaviour:** If portfolio state is stale (`StalePortfolioStateError`), new orders are blocked before reaching RC-8. This protects RC-8 from receiving incorrect context. However, RC-8 must never be weakened by portfolio context — portfolio approval only permits the request to proceed; it cannot lower RC-8 thresholds.

---

## 7. Allocation and Capital Flow Summary

```
1. Signal arrives with strategy_id, instrument_token, requested_capital

2. CapitalAllocator.evaluate(request, state) → AllocationDecision
   - Checks all constraints in order (Section 2)
   - Reserves approved_capital in CashBalance.blocked
   - Records ORDER_RESERVED ledger event
   - Sets expires_at = now + allocation_ttl_s

3. AllocationDecision forwarded to RC-8

4a. RC-8 approves → RC-7 executes
    - On fill: apply_fill() called
    - COMMITTED → released into position cost basis
    - CashBalance.blocked decremented; position cost basis incremented

4b. RC-8 rejects → release_order_reservation() called
    - RELEASED
    - CashBalance.blocked decremented
    - ORDER_RESERVATION_RELEASED event recorded

5. Allocation expires without RC-8 response
    - Cleanup job detects expires_at < now
    - EXPIRED → treated as RELEASED
    - Blocked capital returned to available
```
