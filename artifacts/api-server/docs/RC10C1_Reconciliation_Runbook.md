# RC-10C1 Reconciliation Runbook

**Document status:** Operational  
**Phase:** RC-10C1 Portfolio Core  
**Applicable module:** `src/portfolio/reconciliation.py`, `src/portfolio/repositories/reconciliation.py`

---

## 1. Reconciliation Trigger Conditions

Reconciliation compares local portfolio state against the broker-neutral snapshot from RC-10D. It is triggered in the following situations:

| Trigger | Type | Frequency |
|---------|------|-----------|
| Periodic schedule | Automatic | Every `reconciliation_interval_s` seconds (default: 300s) |
| Startup recovery | Automatic | Once, during portfolio recovery sequence |
| Fill received | Automatic | Immediately after applying a fill event |
| Manual operator request | Manual | On demand via `PortfolioService.reconcile()` |
| Critical discrepancy detected | Automatic | Re-triggered after applying corrections |
| Stale broker snapshot detected | Automatic | When broker snapshot age exceeds `stale_broker_threshold_s` |
| Portfolio status changes to DEGRADED | Automatic | To verify whether degradation is resolved |

**Reconciliation never triggers broker API calls directly.** It consumes only the broker-neutral snapshot already fetched by RC-10D.

---

## 2. Broker Snapshot Format (Dict Schema)

RC-10C1 consumes broker snapshots in RC-10D's broker-neutral dict format:

```python
{
    "source": "zerodha_paper",          # str: broker adapter identifier
    "snapshot_at": "2024-01-15T09:30:00+05:30",  # ISO-8601 with timezone

    "positions": [
        {
            "instrument_token": 738561,     # int: NSE token
            "instrument_symbol": "RELIANCE",# str
            "quantity": 100,                # int: net open quantity
            "average_price": "1506.67",     # str: Decimal-safe
            "last_price": "1510.00",        # str: last known market price
            "realised_pnl": "0.00",         # str: broker-reported realised P&L
            "unrealised_pnl": "333.00",     # str: broker-reported unrealised P&L
            "product": "MIS",               # str: MIS=intraday, CNC=delivery
            "side": "LONG"                  # str: LONG or SHORT
        }
    ],

    "orders": [
        {
            "order_id": "231015000012345",  # str: broker order ID
            "internal_order_id": "uuid...", # str: RC-7 internal ID (if mapped)
            "instrument_token": 738561,
            "status": "OPEN",               # str: OPEN, COMPLETE, CANCELLED, etc.
            "quantity": 100,
            "filled_quantity": 0,
            "price": "1505.00",
            "side": "BUY",
            "product": "MIS"
        }
    ],

    "trades": [
        {
            "trade_id": "T001",
            "order_id": "231015000012345",
            "instrument_token": 738561,
            "quantity": 100,
            "price": "1506.50",
            "side": "BUY",
            "timestamp": "2024-01-15T09:32:10+05:30",
            "charges": {
                "brokerage": "20.00",
                "stt": "3.77",
                "exchange_charges": "0.51",
                "gst": "3.69",
                "sebi_charges": "0.02",
                "stamp_duty": "2.26",
                "total": "30.25"
            }
        }
    ],

    "funds": {
        "available_cash": "45000.00",       # str: free cash
        "used_margin": "55000.00",          # str: margin consumed
        "available_margin": "20000.00",     # str: margin still available
        "total_balance": "100000.00",       # str: total account value
        "currency": "INR"
    }
}
```

All monetary values are strings to preserve Decimal precision across JSON serialisation.

---

## 3. Discrepancy Classification Table

| Type | Severity | Description | Default Action |
|------|----------|-------------|----------------|
| `LOCAL_ONLY_POSITION` | CRITICAL | Portfolio has a position; broker has none | Block new orders; require manual review |
| `BROKER_ONLY_POSITION` | CRITICAL | Broker has a position; portfolio has none | Block new orders; alert operator |
| `QUANTITY_MISMATCH` | CRITICAL | Open quantity differs by more than rounding tolerance | Block new orders; log details |
| `AVG_PRICE_MISMATCH` | WARNING | Average price differs beyond tolerance (0.01%) | Log; continue with caution |
| `REALISED_PNL_MISMATCH` | WARNING | Realised P&L differs (common with charge estimation) | Log; flag as estimated until confirmed |
| `MARGIN_MISMATCH` | WARNING | Used margin differs beyond 1% tolerance | Log; refresh margin state |
| `CASH_MISMATCH` | WARNING | Available cash differs beyond tolerance | Log; use broker value as authoritative |
| `MISSING_FILL` | CRITICAL | Local fill not found in broker trades | Block affected position's orders |
| `DUPLICATE_FILL` | CRITICAL | Same trade appears twice locally | Halt and investigate immediately |
| `STALE_BROKER_SNAPSHOT` | WARNING | Snapshot age > `stale_broker_threshold_s` | Refuse to reconcile; fetch fresh snapshot |
| `STALE_LOCAL_STATE` | WARNING | Local state age > `stale_state_threshold_s` | Mark portfolio degraded |
| `UNKNOWN_INSTRUMENT` | WARNING | Instrument in broker snapshot not in local state | Log; investigate if quantity > 0 |
| `UNRESOLVED_ORDER` | WARNING | Order in broker book not tracked locally | Reconcile order; create reservation if needed |

### 3.1 Severity Escalation Rules

- Any **CRITICAL** discrepancy → `portfolio_ready = False`
- Three or more **WARNING** discrepancies → `PortfolioStatus = DEGRADED`
- `DUPLICATE_FILL` always escalates to maximum severity and triggers immediate halt request

---

## 4. Dry-Run vs Live Reconciliation

| Aspect | Dry-Run (`dry_run=True`) | Live (`dry_run=False`) |
|--------|--------------------------|------------------------|
| Discrepancy detection | Full comparison run | Full comparison run |
| State mutations | **None** | Corrections applied if policy permits |
| Portfolio status change | No | Yes (may degrade or restore readiness) |
| Ledger events | None | `RECONCILIATION_COMPLETED`, `DISCREPANCY_DETECTED` |
| Report persistence | Saved as dry-run report | Saved as live reconciliation report |
| Audit trail | No | Full audit trail for every correction |
| Default mode | `True` | Must explicitly pass `dry_run=False` |

**Dry-run is the default.** This prevents accidental state corruption during investigation or development. All automated periodic reconciliations run in dry-run mode by default; corrections require operator confirmation or explicit configuration.

No **blind destructive corrections** are ever applied. Each correction:
1. Is classified by type and severity
2. Requires explicit correction policy approval
3. Is recorded in the ledger before being applied
4. Is persisted to the reconciliation repository

---

## 5. When Portfolio Readiness Is Degraded

`PortfolioHealth.readiness = False` blocks all new order approvals. Readiness is degraded when:

| Condition | Status set |
|-----------|-----------|
| Any CRITICAL discrepancy in last reconciliation | `DEGRADED` |
| `DUPLICATE_FILL` detected | `HALTED` |
| `LOCAL_ONLY_POSITION` unresolved | `DEGRADED` |
| `BROKER_ONLY_POSITION` unresolved | `DEGRADED` |
| `QUANTITY_MISMATCH` unresolved | `DEGRADED` |
| Recovery not yet complete | `RECOVERING` |
| Reconciliation not yet run post-recovery | `RECONCILING` |
| Stale local state | `DEGRADED` |
| Critical limit breach | `HALTED` |

**Readiness is restored** only after:
1. A successful reconciliation with `critical_count == 0`
2. All previously blocking discrepancies resolved or acknowledged
3. Portfolio state is within staleness thresholds

---

## 6. Manual Resolution Steps for Critical Discrepancy Types

### 6.1 `LOCAL_ONLY_POSITION` — Portfolio has position; broker has none

```
Symptom: Portfolio shows 100 RELIANCE LONG; broker shows zero.

Steps:
1. Pull fresh broker snapshot via RC-10D
2. Re-run dry-run reconciliation to confirm discrepancy persists
3. Check broker order book for any pending close orders
4. Review execution audit trail in RC-7 for any close fills missed
5. If broker truly has zero:
   a. If position was closed at broker (fill missed locally):
      - Reconstruct fill from broker trade history
      - Apply fill via PortfolioService.apply_fill() with correct fill_id
   b. If position was never opened at broker (order rejected):
      - Release reservation via PortfolioService.release_order_reservation()
      - Record resolution in reconciliation note
6. Re-run live reconciliation to verify resolution
7. Restore readiness if critical_count == 0
```

### 6.2 `BROKER_ONLY_POSITION` — Broker has position; portfolio has none

```
Symptom: Broker shows 50 INFY LONG; portfolio has no record.

Steps:
1. Search RC-7 execution records for INFY orders
2. Search portfolio event ledger for any POSITION_OPENED events for INFY
3. If found in RC-7 but not portfolio:
   - Replay the fill event via PortfolioService.apply_fill()
   - Verify position is created with correct quantities and prices
4. If not found in RC-7 either:
   - This is an unknown trade — escalate to operations team
   - Do NOT create a synthetic position without full audit documentation
5. If position originated from a different system (not this platform):
   - Document as out-of-scope; do not reconcile
6. Verify readiness after resolution
```

### 6.3 `QUANTITY_MISMATCH` — Quantities differ

```
Symptom: Local shows 100 shares; broker shows 80 shares.

Steps:
1. Check pending orders: is there an outstanding sell order for 20 shares?
2. Check recent fills: was a partial close fill received but not applied?
3. If partial fill was missed:
   - Retrieve fill from broker trade history
   - Apply via PortfolioService.apply_fill()
4. If quantities still differ after fill reconciliation:
   - Document discrepancy with before/after values
   - Adjust local quantity to match broker (with full audit entry)
   - Record the adjustment as a RECONCILIATION_COMPLETED event
5. Check P&L impact of the adjustment and record any correction
```

### 6.4 `MISSING_FILL` — Local fill not found in broker trades

```
Symptom: Portfolio applied fill F001 for 100 SBIN; broker trade list has no matching trade.

Steps:
1. Search broker trade history by order_id and timestamp
2. If found under different trade_id:
   - Update mapping; apply idempotency key fix
3. If broker confirms trade was cancelled/rejected:
   - Reverse the fill via InvalidPositionTransitionError path
   - Restore reserved capital
   - Record correction with full audit trail
4. If broker cannot explain the discrepancy:
   - Halt portfolio immediately
   - Escalate to operations team
   - Do not accept new orders until resolved
```

---

## 7. Audit Trail Requirements

Every reconciliation run must produce:

| Record | Required Fields | Retention |
|--------|----------------|-----------|
| `PortfolioReconciliationReport` | `run_id`, `started_at`, `completed_at`, `dry_run`, `critical_count`, `warning_count`, `portfolio_ready`, `state_version` | Permanent |
| `PortfolioDiscrepancy` (per discrepancy) | `discrepancy_id`, `discrepancy_type`, `severity`, `local_value`, `broker_value`, `detected_at` | Permanent |
| Correction events | `PortfolioEvent` with `idempotency_key`, `payload` including before/after values, `occurred_at` | Permanent |
| Operator acknowledgements | Timestamp, operator ID, resolution note | Permanent |

**Never log:**
- Raw broker API credentials
- Account passwords or tokens
- Full private account details (mask account numbers)

**Always log:**
- Discrepancy type and severity
- Instrument token and symbol
- Local vs broker values (quantities, prices — not credentials)
- Correction action taken
- Resolution timestamp and operator ID
