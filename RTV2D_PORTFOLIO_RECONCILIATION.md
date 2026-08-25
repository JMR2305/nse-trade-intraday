# RTV-2D — Portfolio Reconciliation

**Date:** 2026-08-25 (IST)  
**Result:** **RECONCILED — canonical endpoints agree**

## Canonical endpoint parity

Both read-only production endpoints use the Phase 20 ledger financial contract.

| Canonical field | `/api/portfolio` | `/api/portfolio/snapshot` |
| --- | ---: | ---: |
| Initial capital | ₹100,000.00 | ₹100,000.00 |
| Cash | ₹99,721.26 | ₹99,721.26 |
| Available cash / buying power | ₹99,721.26 | ₹99,721.26 |
| Equity | ₹99,721.26 | ₹99,721.26 |
| Realised / realized P&L | −₹278.74 | −₹278.74 |
| Unrealised / unrealized P&L | ₹0.00 | ₹0.00 |
| Total P&L | −₹278.74 | −₹278.74 |
| Open-position cost | ₹0.00 | ₹0.00 |
| Open positions | 0 | 0 |

The snapshot’s `buying_power` is the available-cash alias. With no open
positions, cash, available cash, buying power, and equity are identical.

## Independent closed-ledger recomputation

The authoritative Phase 20 ledger contains exactly six closed rows:

| Symbol | Quantity | Entry | Exit | Realised P&L |
| --- | ---: | ---: | ---: | ---: |
| DRREDDY | 1 | ₹1,186.98 | ₹1,186.98 | ₹0.00 |
| GRASIM | 3 | ₹3,274.20 | ₹3,270.00 | −₹12.60 |
| DRREDDY | 20 | ₹1,193.79 | ₹1,180.10 | −₹273.80 |
| DIVISLAB | 1 | ₹8,570.34 | ₹8,578.00 | ₹7.66 |
| DRREDDY | 20 | ₹1,181.87 | ₹1,181.87 | ₹0.00 |
| TRENT | 5 | ₹2,971.45 | ₹2,971.45 | ₹0.00 |
| **Total** |  |  |  | **−₹278.74** |

There are zero `OPEN` rows, zero `EXIT_PENDING` rows, and zero open-position
cost. Therefore the ledger-derived result is:

```text
₹100,000.00 + (−₹278.74) = ₹99,721.26
```

## Explanation of the apparent ₹100,000 discrepancy

The `paper_portfolio` table contains a legacy reset-state row with
`cash = ₹100,000` and empty positions. That row is not the financial authority
for either production portfolio endpoint.

The Phase 20 canonical ledger is the authority. Its derived cash/equity is
₹99,721.26 and both endpoint contracts return that same value. The discrepancy
was therefore a comparison between a legacy reset-state cache and the canonical
ledger, not a cash loss, capital adjustment, or endpoint-parity defect.

No portfolio was reset and no historical ledger record was changed during this
reconciliation.
