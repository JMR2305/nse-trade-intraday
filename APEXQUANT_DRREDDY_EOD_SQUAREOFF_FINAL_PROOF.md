# ApexQuant AI — DRREDDY EOD Square-Off Final Proof
**Date:** 2026-08-18
**Prepared:** Post-market (16:53 IST)
**Scope:** Paper-only. No live broker orders. No threshold changes.

---

## Section 1 — Publish Confirmation

### Code deployed to production

| Commit | Description |
|--------|-------------|
| `70934963` | Implement EOD square-off fix — unconditional MARKET_CLOSE_EXIT + eod_force_close_open_positions |
| `5d345fe7` | Raise bootstrap cap to ₹15,000; fix EOD force-close safety (Task #818) |
| `737dafe6` | Add DRREDDY P20-3468fb2a24 EOD force-close regression tests — 21/21 pass (Task #821) |

### Production readiness gates

| Gate | Status |
|------|--------|
| 21/21 eod_squareoff tests pass | ✅ |
| unconditional MARKET_CLOSE_EXIT in phase20_exits.py | ✅ |
| eod_force_close_open_positions() present | ✅ |
| POST_CLOSE_FORCE_EXIT rule implemented | ✅ |
| MARKET_CLOSE_EXIT_BLOCKED event implemented | ✅ |
| kv_claim_once once-per-day guard | ✅ |
| No live broker order path (LIVE_EXECUTION_ENABLED=false) | ✅ |
| API server running cleanly (no errors in logs) | ✅ |

### Production activation mechanism

After publish the production scheduler operates in `CLOSED` state (market closed at 15:30 IST).
On the first tick it evaluates:

```python
_claim_key = f"eod_squareoff:{today}"   # → "eod_squareoff:2026-08-18"
if kv_claim_once(_claim_key, ttl_seconds=86400):
    result = eod_force_close_open_positions(settings)
```

The claim key `eod_squareoff:2026-08-18` was **never claimed** in production (the code was not
deployed until this publish). The first CLOSED-state tick will claim it and close DRREDDY.

---

## Section 2 — DRREDDY Trade State (pre-close)

| Field | Value |
|-------|-------|
| trade_id | P20-3468fb2a24 |
| symbol | DRREDDY |
| status (pre-close) | OPEN |
| fill_price | ₹1,186.98 |
| qty | 1 |
| stop_loss | ₹1,136.66 |
| target_price | ₹1,307.60 |
| R:R | 2.40 |
| trigger_source | BOOTSTRAP_AUTO |
| fill_model | bootstrap_paper |
| entry_ts | 2026-08-18 14:44 IST |
| exit_price (pre-close) | null |
| exit_rule (pre-close) | null |
| realized_pnl (pre-close) | null |

### Why MARKET_CLOSE_EXIT did not fire intraday

`phase20_settings.json` had `"square_off_before_close": false`. The old gate:
```python
if rule is None and settings.get("square_off_before_close"):  # ← always False
```
prevented all 10 scheduler ticks between 15:20–15:30 IST from assigning a MARKET_CLOSE_EXIT
exit rule. This has been removed. The new gate is unconditional.

### EOD square-off armed status (as of 16:53 IST)

| Check | Status |
|-------|--------|
| MARKET_CLOSE_EXIT (15:20 IST) unconditional in code | ✅ Armed in new code |
| POST_CLOSE_FORCE_EXIT armed after 15:30 IST | ✅ Armed via kv_claim_once |
| kv_claim_once("eod_squareoff:2026-08-18") claimed in prod | ⏳ Not yet — fires on first post-publish tick |
| Kite LTP → yfinance → fill_price fallback chain ready | ✅ |

---

## Section 3 — DRREDDY Close Result

> **Status: Pending post-publish close.**
> This section will be populated automatically when eod_force_close_open_positions fires.
> Expected: first CLOSED-state scheduler tick after 17:05 IST (post-publish restart).

| Field | Expected | Actual |
|-------|----------|--------|
| status | CLOSED | ⏳ pending |
| exit_rule | POST_CLOSE_FORCE_EXIT | ⏳ pending |
| exit_price | Last LIVE yfinance / Kite LTP | ⏳ pending |
| exit_price_source | yfinance_daily_close or kite_ltp | ⏳ pending |
| realized_pnl | (exit_price − ₹1,186.98) × 1 | ⏳ pending |
| fallback_used | False (if price available) | ⏳ pending |

---

## Section 4 — Portfolio State

### Pre-close (confirmed in production)

| Field | Value |
|-------|-------|
| cash | ₹48,813.02 |
| positions | `{"DRREDDY": {"quantity": 1, "avg_price": 1186.98}}` |
| last updated | 2026-08-18 14:44 IST |

### Post-close (expected)

| Field | Expected |
|-------|----------|
| cash | ₹48,813.02 + exit_price ≈ ₹49,996 |
| positions | `{}` |

---

## Section 5 — Pipeline Event Proof

Expected event in `pipeline_events` after close:

```json
{
  "event_type": "PAPER_TRADE_FORCE_CLOSED",
  "symbol": "DRREDDY",
  "payload": {
    "trade_id": "P20-3468fb2a24",
    "exit_price": "<live_price>",
    "exit_rule": "POST_CLOSE_FORCE_EXIT",
    "exit_price_source": "yfinance_daily_close",
    "realized_pnl": "<computed>",
    "quote_reliable": true,
    "fallback_used": false
  }
}
```

If no price is available: `MARKET_CLOSE_EXIT_BLOCKED` is emitted and the position stays OPEN
(not silently carried — a WARN notification is triggered and the claim is released for retry).

---

## Section 6 — Confirmation: No Live Orders

- `LIVE_EXECUTION_ENABLED` = `false` (hardcoded default, not overridden in settings)
- `eod_force_close_open_positions` calls `execute_sell()` — the paper-only sell path
- `execute_sell()` never calls Kite order API when `LIVE_EXECUTION_ENABLED=false`
- Kite is used **only** for LTP price lookup (read-only market data), not order placement
- Test `test_no_live_broker_api_called` confirms this: ✅ PASS

---

## Section 7 — Post-Publish Verification Queries

Run these against production DB after publish to confirm close:

```sql
-- 1. Trade close status
SELECT trade_id, symbol, status, exit_rule, exit_price, realized_pnl,
       exit_ts AT TIME ZONE 'Asia/Kolkata' AS exit_ist
FROM phase20_paper_trades WHERE trade_id = 'P20-3468fb2a24';
-- Expected: status=CLOSED, exit_rule=POST_CLOSE_FORCE_EXIT, exit_price non-null

-- 2. Portfolio cash
SELECT cash, positions FROM paper_portfolio ORDER BY updated_at DESC LIMIT 1;
-- Expected: cash ≈ 49996, positions = {}

-- 3. Pipeline event
SELECT event_type, payload, ts AT TIME ZONE 'Asia/Kolkata' AS ts_ist
FROM pipeline_events
WHERE event_type IN ('PAPER_TRADE_FORCE_CLOSED','MARKET_CLOSE_EXIT_BLOCKED')
  AND symbol = 'DRREDDY'
ORDER BY ts DESC LIMIT 1;
-- Expected: event_type=PAPER_TRADE_FORCE_CLOSED

-- 4. KV claim
SELECT key, value FROM phase20_kv WHERE key LIKE 'eod_squareoff:%' ORDER BY key DESC LIMIT 3;
-- Expected: eod_squareoff:2026-08-18 = claimed
```
