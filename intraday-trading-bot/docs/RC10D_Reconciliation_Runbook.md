# RC-10D Reconciliation Runbook

## Overview

The `ReconciliationEngine` compares local DB orders against the Zerodha broker order book and trade book. It classifies discrepancies into 9 types and records them in `broker_reconciliation_runs` and `broker_reconciliation_discrepancies`.

**No destructive corrections are made without an explicit policy.**

---

## When Reconciliation Runs

| Trigger | When |
|---------|------|
| `startup` | System start-up |
| `post_reconnect` | After WebSocket reconnect |
| `uncertain_submission` | After a placement timeout |
| `periodic` | During market hours on a schedule |
| `eod` | End-of-day check |
| `manual` | Operator-triggered |

---

## 9 Discrepancy Types

| Type | Description | `requires_manual_review` |
|------|-------------|--------------------------|
| `LOCAL_ONLY` | Local order exists, not in broker book (non-terminal) | ✅ Yes |
| `BROKER_ONLY` | Broker order exists, no local counterpart (non-terminal) | ✅ Yes |
| `STATE_MISMATCH` | Terminal state differs between local and broker | ✅ Yes |
| `FILL_MISMATCH` | Order COMPLETE but no trade records | ✅ Yes |
| `QUANTITY_MISMATCH` | Filled quantity differs | ✅ Yes |
| `PRICE_MISMATCH` | Average price differs beyond tolerance | ✅ Yes |
| `MISSING_EXCHANGE_ORDER_ID` | Filled order missing exchange ID | ❌ No |
| `DUPLICATE_ORDER` | Same order submitted twice at broker | ✅ Yes |
| `UNRESOLVED_BROKER_EVENT` | Unknown status in event inbox | ❌ No |

---

## Reading Reconciliation Results

```sql
-- Latest reconciliation run
SELECT * FROM broker_reconciliation_runs ORDER BY started_at DESC LIMIT 1;

-- Discrepancies requiring manual review
SELECT * FROM broker_reconciliation_discrepancies
WHERE requires_manual_review = true AND resolved = false
ORDER BY created_at DESC;
```

---

## Resolving a Discrepancy

After manual investigation, mark as resolved:

```sql
UPDATE broker_reconciliation_discrepancies
SET resolved = true,
    resolved_at = NOW(),
    resolution_notes = 'Confirmed as Zerodha race condition — order settled correctly'
WHERE id = <id>;
```

---

## Paper Mode Behaviour

In paper mode, reconciliation always reports **CLEAN** with `orders_checked = 0`. No broker API calls are made.

---

## Operator Checklist After UNCERTAIN Submission

1. Wait 5 minutes for the order to settle
2. Trigger manual reconciliation
3. Check `broker_reconciliation_discrepancies` for the affected `internal_order_id`
4. If `STATE_MISMATCH` or `LOCAL_ONLY`: check Zerodha Kite portal directly
5. Mark discrepancy as resolved after confirming actual order state
6. Update local order status via admin endpoint if needed
