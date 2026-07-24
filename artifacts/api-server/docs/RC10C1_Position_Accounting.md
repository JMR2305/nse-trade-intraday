# RC-10C1 Position Accounting

**Document status:** Baseline  
**Phase:** RC-10C1 Portfolio Core  
**Applicable module:** `src/portfolio/position_manager.py`, `src/portfolio/pnl.py`

---

## 1. FIFO Lot Matching Algorithm

Each position maintains an ordered list of `PortfolioLot` records. Lots are appended in fill-received order (by `filled_at` timestamp, then by event sequence number for ties).

### 1.1 Opening a Position

A new `PortfolioPosition` is created. The fill becomes `lot[0]`.

```
Position opened:
  lots = [Lot(fill_id=F1, quantity=Q1, entry_price=P1)]
  open_quantity = Q1
  average_entry_price = P1
```

### 1.2 Increasing a Position (Additional Fill)

The new fill is appended to the lots list. The weighted average entry price is recalculated.

```
Before: lots = [L1(qty=Q1, price=P1), L2(qty=Q2, price=P2)]
After adding fill F3(qty=Q3, price=P3):
  lots = [L1, L2, L3(qty=Q3, price=P3)]
  open_quantity = Q1 + Q2 + Q3
  average_entry_price = (Q1*P1 + Q2*P2 + Q3*P3) / (Q1+Q2+Q3)
```

### 1.3 Reducing / Closing a Position

Lots are consumed from the front (FIFO order). Each lot consumed generates a realised P&L component.

**Algorithm (partial close of `reduce_qty` units):**

```
remaining = reduce_qty
for lot in lots (oldest first):
    if lot.quantity <= remaining:
        consume entire lot
        realised_pnl += lot.quantity * (exit_price - lot.entry_price) * direction
        remaining -= lot.quantity
        remove lot from list
    else:
        consume remaining from this lot
        realised_pnl += remaining * (exit_price - lot.entry_price) * direction
        lot.quantity -= remaining
        remaining = 0
        break

open_quantity -= reduce_qty
```

Where `direction = +1` for LONG, `direction = -1` for SHORT.

### 1.4 Idempotency

Every fill carries a `fill_id` (idempotency key). Before applying a fill to a position:

1. Check if `fill_id` already exists in any lot in the position.
2. If found, raise `DuplicateEventError` — the caller treats this as a no-op.
3. If not found, apply the fill as a new lot.

Out-of-order fills are safe: they are inserted with their correct `filled_at` timestamp, and lot ordering is maintained.

---

## 2. Weighted Average Entry Price Formula

When a position has lots `L1 … Ln` with quantities `q_i` and entry prices `p_i`:

```
average_entry_price = Σ(q_i * p_i) / Σ(q_i)
```

All arithmetic uses `Decimal` with at least 8 significant digits. Division result is not rounded until presentation. Rounding for order submission uses `ROUND_DOWN` to the instrument's `tick_size`.

**Example (INR):**

| Lot | Qty | Price | Value |
|-----|-----|-------|-------|
| L1  | 100 | 1500.00 | 150,000.00 |
| L2  | 50  | 1520.00 | 76,000.00 |
| **Total** | **150** | **avg = 1506.67** | **226,000.00** |

```
average_entry_price = 226000 / 150 = 1506.666...
```

---

## 3. Realised P&L Formula

### 3.1 LONG Position

```
realised_pnl = Σ [ lot_qty_consumed_i * (exit_price - lot_entry_price_i) ] - fees
```

**Gross realised P&L** (before fees):
```
gross_realised = Σ [ qty_i * (exit_price - entry_price_i) ]
```

**Net realised P&L**:
```
net_realised = gross_realised - total_charges
```

### 3.2 SHORT Position

```
realised_pnl = Σ [ lot_qty_consumed_i * (lot_entry_price_i - exit_price) ] - fees
```

Sign convention: Positive value = profit. Negative value = loss.

### 3.3 Example

Entry: 100 shares LONG at ₹1500. Exit: 100 shares at ₹1550.

```
gross_realised = 100 * (1550 - 1500) = ₹5,000
estimated_charges = ₹127.50  (see Section 5)
net_realised = ₹5,000 - ₹127.50 = ₹4,872.50
```

---

## 4. Unrealised P&L Formula

```
unrealised_pnl = open_quantity * (last_market_price - average_entry_price) * direction
```

Where `direction = +1` for LONG, `direction = -1` for SHORT.

If `last_market_price` is `None` or stale (age > `stale_price_threshold_s`):
- `unrealised_pnl = Decimal("0")`
- `ExposureSnapshot.stale_prices = True`
- `PortfolioHealth` reports degraded market-price freshness

Unrealised P&L is **never** used to approve new allocations when prices are stale — the system fails closed.

---

## 5. NSE India Charge Breakdown

All charge calculations use `Decimal` arithmetic. Values shown are representative; exact rates must be kept current with SEBI/exchange circulars.

### 5.1 Charge Components

| Charge | Rate | Applied On | Notes |
|--------|------|-----------|-------|
| **Brokerage** | Flat ₹20 per order or 0.03% (whichever lower) | Turnover | Varies by broker plan |
| **STT (Securities Transaction Tax)** | 0.1% on sell side (equity delivery); 0.025% on sell (intraday) | Sell-side turnover | SEBI mandated |
| **Exchange Transaction Charges** | ~0.00335% (NSE) | Turnover | Per NSE circular |
| **GST** | 18% | On brokerage + exchange charges | Inclusive of CGST + SGST |
| **SEBI Charges** | ₹10 per crore (0.0001%) | Turnover | Currently ₹10/crore |
| **Stamp Duty** | 0.015% on buy side | Buy-side value | State-level, varies |

### 5.2 Total Estimated Charge Formula

```
brokerage = min(flat_rate, turnover * brokerage_pct)
stt = turnover * stt_rate  (sell side only for intraday)
exchange_charge = turnover * exchange_rate
gst = (brokerage + exchange_charge) * 0.18
sebi = turnover * 0.000001
stamp = buy_value * 0.00015

total_estimated_charges = brokerage + stt + exchange_charge + gst + sebi + stamp
```

### 5.3 Intraday vs Delivery Distinction

| Mode | STT | Delivery |
|------|-----|---------|
| Intraday | 0.025% sell side only | No |
| Delivery | 0.1% both sides | Yes |

RC-10C1 defaults to intraday for all positions (consistent with NSE intraday platform scope).

---

## 6. Estimated vs Confirmed Charges Policy

| State | `fees_are_estimated` | Source |
|-------|---------------------|--------|
| Order placed, fill pending | `True` | Local calculation |
| Fill received (no broker confirmation yet) | `True` | Local calculation |
| Broker trade confirmation with ledger charges received | `False` | Broker-confirmed |

**Rules:**

1. All charges are initially estimated using the formula in Section 5.
2. `PositionPnL.fees_are_estimated = True` flags estimated values in all outputs.
3. When the broker snapshot includes confirmed charges, the system **recalculates** `PositionPnL` with `confirmed_fees` and sets `fees_are_estimated = False`.
4. Corrections are recorded as new `FEE_RECORDED` ledger events — the original estimated event is never deleted.
5. All P&L figures presented to RC-8 or strategies are clearly tagged with their estimation status.
6. Audit trail preserves both the original estimate and the confirmed value with timestamps.

---

## 7. Daily P&L Rollover (IST Midnight)

### 7.1 Trading Date Definition

- Trading date uses **IST (UTC+5:30)** midnight as the boundary.
- `PortfolioPnL.trading_date` is a `YYYY-MM-DD` string in IST.
- UTC timestamps are converted to IST for date assignment.

### 7.2 Rollover Procedure

At IST midnight (or at first event of the new trading day, whichever comes first):

1. Record an `END_OF_DAY_SNAPSHOT` event in the ledger with the current `daily_pnl`.
2. Reset `PortfolioPnL.daily_pnl = Decimal("0")`.
3. Update `trading_date` to the new calendar date in IST.
4. Persist the end-of-day snapshot to the repository for audit.
5. Carry forward `peak_equity`, `current_equity`, and `drawdown` — these are **not** reset daily.
6. Carry forward all open position lots — FIFO matching spans multiple days if positions are held overnight (not applicable for intraday close, but supported structurally).

### 7.3 NSE Session Boundaries

NSE normal market session: 09:15 to 15:30 IST. All intraday positions are expected to close before 15:20 IST (platform-enforced exit). Daily P&L rollover occurs at 00:00 IST.

---

## 8. Drawdown Calculation

### 8.1 Peak Equity Tracking

`peak_equity` is the highest `current_equity` value ever recorded since portfolio initialisation (or since last reset). It is updated whenever `current_equity` exceeds it.

```
current_equity = initial_capital + total_realised_pnl + total_unrealised_pnl - total_fees
peak_equity = max(peak_equity, current_equity)
```

### 8.2 Drawdown Formula

```
drawdown = (peak_equity - current_equity) / peak_equity
```

- Result is a `Decimal` in `[0, 1]`.
- `PortfolioPnL` model validator enforces `0 ≤ drawdown ≤ 1`.
- `drawdown_amount = peak_equity - current_equity` (INR absolute value).

### 8.3 Drawdown Limit Enforcement

| Threshold | Action |
|-----------|--------|
| `drawdown >= max_drawdown_pct * 0.80` | `WARNING` limit breach recorded |
| `drawdown >= max_drawdown_pct` | `CRITICAL` breach; new allocations blocked; kill-switch requested |

`PortfolioConfig.max_drawdown_pct` default: `0.10` (10% from peak equity).

### 8.4 Example

```
initial_capital  = ₹100,000
peak_equity      = ₹105,000   (after early profits)
current_equity   = ₹98,000    (after losses)

drawdown = (105,000 - 98,000) / 105,000 = 0.0667 (6.67%)
drawdown_amount  = ₹7,000
```

If `max_drawdown_pct = 0.10`, this drawdown (6.67%) is below the halt threshold but above the warning level (8%).
