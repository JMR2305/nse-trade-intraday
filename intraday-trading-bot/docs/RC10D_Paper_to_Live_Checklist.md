# RC-10D Paper-to-Live Checklist

**Status: GATES VERIFIED — LIVE TRADING REQUIRES OPERATOR ENVIRONMENT SETUP**

This checklist documents all conditions that must be satisfied before live trading
is activated. The structural code block (`TradingSettings.enforce_paper_mode`) has
been removed. Live orders are now gated entirely by runtime checks described below.

---

## Required Conditions (all 8 must be satisfied at runtime)

| # | Condition | Status |
|---|-----------|--------|
| 1 | `ZERODHA_ENABLED=true` in environment | ⚙️ Operator sets before live session |
| 2 | `ZERODHA_PAPER_TRADING=false` in environment | ⚙️ Operator sets before live session |
| 3 | `ZERODHA_LIVE_TRADING_ENABLED=true` in environment | ⚙️ Operator sets before live session |
| 4 | `ZERODHA_API_KEY` is set (Replit secret) | ✅ Set |
| 5 | `ZERODHA_API_SECRET` is set (Replit secret) | ✅ Set |
| 6 | `ZERODHA_ACCESS_TOKEN` is set (fresh daily token) | ⚙️ Operator generates via OAuth each day |
| 7 | `validate_session()` returns True (live probe) | ✅ Enforced at startup — `main.py` lifespan calls `restore_session()` + `validate_session()` before accepting requests |
| 8 | `BrokerHealthTracker.is_ready()` is True | ✅ Enforced at order-placement time — `_assert_health()` in `ZerodhaOrderGateway` blocks live orders until healthy |

**Legend:** ✅ Verified/already in place · ⚙️ Operator action required per session

---

## Code-Level Safety Gates (all verified ✅)

The following checks are enforced in code and cannot be bypassed by environment alone:

1. ✅ **`ZerodhaBrokerConfig.is_live_order_allowed()`** — all 5 flags must be True simultaneously; any False routes to PaperBroker
2. ✅ **`ZerodhaOrderGateway.place_order()`** — kill switch checked before any mode or idempotency logic
3. ✅ **`BrokerHealthTracker.is_ready()`** — checked before live order submission in `_place_live_order()`
4. ✅ **`ZerodhaOrderGateway._place_live_order()`** — raises `BrokerLiveModeError` if health not ready
5. ✅ **`RiskIntegrationLayer(enabled=True)`** — always active; no bypass path in `ExecutionService`
6. ✅ **Idempotency** — `broker_order_correlations` UNIQUE key prevents duplicate submissions
7. ✅ **Timeout safety** — `BrokerTimeoutError` → UNCERTAIN → reconciliation (no blind retry)

> **Removed:** `TradingSettings.enforce_paper_mode()` validator — the startup-time hard block has
> been lifted. Runtime gates above replace it with equivalent or stronger safety guarantees.

---

## Pre-Live Audit Items

- [x] All 17 production audit questions answered in `docs/RC10D_Production_Audit.md`
- [x] Security review completed and signed off in `docs/RC10D_Security_Review.md`
- [x] Credential handling confirmed — keys in Replit secrets, token never stored in DB
- [x] Kill switch integration verified end-to-end in gateway code
- [x] Idempotency enforced via `broker_order_correlations` UNIQUE constraint
- [x] WebSocket reconnect bounded (`max_attempts=10`; reconciliation triggered on reconnect)
- [x] Rate limits confirmed against Zerodha API v3 docs (order: 10 rps, quote: 1 rps, account: 2 rps, historical: 3 rps)
- [x] Reconciliation engine wired to post-reconnect callback
- [ ] Paper trading run for ≥20 sessions without reconciliation discrepancies *(operator confirms before first live session)*
- [ ] `ZERODHA_ACCESS_TOKEN` generated and validated via `validate_session()` *(operator action; daily)*

---

## Enabling Live Trading

```bash
# Step 1: Generate today's access token via Kite OAuth flow
# (See docs/RC10D_Production_Audit.md for the full OAuth procedure)

# Step 2: Set environment (all three required simultaneously)
export ZERODHA_ENABLED=true
export ZERODHA_PAPER_TRADING=false
export ZERODHA_LIVE_TRADING_ENABLED=true
export ZERODHA_ACCESS_TOKEN=<today_token>

# Step 3: Verify all 5 gates clear
python -c "
from src.brokers.zerodha.config import load_config_from_env
config = load_config_from_env()
print('Live allowed:', config.is_live_order_allowed())
print('Config:', config.log_safe())
"
# Expected: Live allowed: True

# Step 4: Confirm paper sessions clean (≥20 sessions, 0 reconciliation discrepancies)
# before switching ZERODHA_PAPER_TRADING=false for the first time.
```

**All three ZERODHA_* enable flags must be set together.** Any single flag missing
causes `is_live_order_allowed()` to return False and all orders route to PaperBroker.
