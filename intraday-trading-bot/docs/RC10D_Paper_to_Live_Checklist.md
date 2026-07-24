# RC-10D Paper-to-Live Checklist

**Status: LIVE TRADING IS NOT ENABLED IN RC-10D**

This checklist documents the conditions that must ALL be satisfied before live trading can be activated in a future release.

---

## Required Conditions (all 8 must be satisfied)

| # | Condition | Status |
|---|-----------|--------|
| 1 | `ZERODHA_ENABLED=true` in environment | ❌ Not set |
| 2 | `ZERODHA_PAPER_TRADING=false` in environment | ❌ Not set |
| 3 | `ZERODHA_LIVE_TRADING_ENABLED=true` in environment | ❌ Not set |
| 4 | `ZERODHA_API_KEY` is set (Replit secret) | ✅ Set |
| 5 | `ZERODHA_API_SECRET` is set (Replit secret) | ✅ Set |
| 6 | `ZERODHA_ACCESS_TOKEN` is set (fresh daily token) | ❌ Not set |
| 7 | `validate_session()` returns True (live probe) | ❌ Not validated |
| 8 | `BrokerHealthTracker.is_ready()` is True | ❌ Not ready (paper mode) |

---

## Code-Level Safety Gates

The following checks are enforced in code and cannot be bypassed by environment alone:

1. **`TradingSettings.enforce_paper_mode()`** — `LIVE` mode raises `ValueError` at startup
2. **`ZerodhaBrokerConfig.is_live_order_allowed()`** — all 5 flags must be True simultaneously
3. **`ZerodhaOrderGateway.place_order()`** — kill switch checked before any mode logic
4. **`BrokerHealthTracker.is_ready()`** — checked before live order submission
5. **`ZerodhaOrderGateway._place_live_order()`** — raises `BrokerLiveModeError` if health not ready

---

## Pre-Live Audit Items

Before any attempt to enable live trading:

- [ ] All RC-10D tests pass (≥738 + new tests)
- [ ] Reconciliation engine tested against real Zerodha sandbox
- [ ] Rate limits confirmed against Zerodha API v3 docs
- [ ] WebSocket reconnect tested under market-hours load
- [ ] Kill switch integration verified end-to-end
- [ ] Credential rotation procedure documented and tested
- [ ] `docs/RC10D_Security_Review.md` reviewed and signed off
- [ ] `docs/RC10D_Production_Audit.md` all 17 questions answered
- [ ] Paper trading run for ≥20 sessions without reconciliation discrepancies

---

## Enabling Live Trading (Future Release Only)

```bash
# Step 1: Set environment
export ZERODHA_ENABLED=true
export ZERODHA_PAPER_TRADING=false
export ZERODHA_LIVE_TRADING_ENABLED=true
export ZERODHA_ACCESS_TOKEN=<today_token>

# Step 2: Verify
python -c "
from src.brokers.zerodha.config import load_config_from_env
config = load_config_from_env()
print('Live allowed:', config.is_live_order_allowed())
print('Config:', config.log_safe())
"

# Step 3: Also remove the structural block in TradingSettings.enforce_paper_mode()
# (requires code change in src/core/config.py)
```

**RC-10D does not remove the structural LIVE block in `TradingSettings`.**
