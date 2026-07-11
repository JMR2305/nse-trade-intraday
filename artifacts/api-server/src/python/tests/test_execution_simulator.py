"""
Deterministic tests for the v2.4 Realistic Execution Simulator.
Run: python tests/test_execution_simulator.py  (from src/python)
Pure arithmetic checks — no data or network required.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

from execution_simulator import (
    CostModel, side_costs, effective_buy_price, effective_sell_price,
    simulate_entry, simulate_exit, evaluate_exit_candle, build_trade_record,
    INTRABAR_CONSERVATIVE, INTRABAR_OPTIMISTIC,
    EXIT_STOP, EXIT_TARGET, EXIT_TIME, EXIT_SIGNAL, EXIT_FORCED,
)

ZERO_COSTS = CostModel(
    slippage_pct=0, spread_pct=0, brokerage_pct=0, brokerage_flat=0,
    brokerage_max=0, stt_pct=0, exchange_pct=0, sebi_pct=0, stamp_pct=0,
    gst_pct=0, allow_partial_fills=False, max_entry_gap_pct=0,
)


def _candle(date, o, h, low, c, v=1_000_000):
    return {"date": date, "open": o, "high": h, "low": low, "close": c, "volume": v}


def _df(candles):
    return pd.DataFrame(candles)


# ── CostModel ────────────────────────────────────────────────────────────────

def test_cost_model_from_dict_overrides_and_ignores_unknown():
    cm = CostModel.from_dict({"slippage_pct": 0.2, "brokerage_flat": 20,
                              "allow_partial_fills": False, "bogus_key": 1})
    assert cm.slippage_pct == 0.2
    assert cm.brokerage_flat == 20.0
    assert cm.allow_partial_fills is False
    assert cm.stt_pct == 0.1                       # default kept
    assert not hasattr(cm, "bogus_key")


def test_side_costs_buy_vs_sell_stamp_duty():
    cm = CostModel(brokerage_pct=0.03, brokerage_flat=0, brokerage_max=20,
                   stt_pct=0.1, exchange_pct=0.00297, sebi_pct=0.0001,
                   stamp_pct=0.015, gst_pct=18.0)
    buy = side_costs(cm, 10_000.0, "buy")
    sell = side_costs(cm, 10_000.0, "sell")
    assert buy["brokerage"] == 3.0                 # 0.03% of 10k, under ₹20 cap
    assert buy["stt"] == 10.0                      # 0.1%
    assert buy["stamp_duty"] == 1.5                # buy side only
    assert sell["stamp_duty"] == 0.0
    expected_gst = round((3.0 + 0.297 + 0.01) * 0.18, 4)
    assert buy["gst"] == expected_gst
    assert buy["total"] == round(3.0 + 10.0 + 0.297 + 0.01 + 1.5 + expected_gst, 4)


def test_brokerage_cap():
    cm = CostModel(brokerage_pct=0.5, brokerage_max=20, gst_pct=0,
                   stt_pct=0, exchange_pct=0, sebi_pct=0, stamp_pct=0)
    c = side_costs(cm, 100_000.0, "buy")
    assert c["brokerage"] == 20.0                  # capped (0.5% would be 500)


def test_effective_prices_symmetry():
    cm = CostModel(slippage_pct=0.1, spread_pct=0.1)
    # buy pays +0.15% (slippage + half spread), sell loses 0.15%
    assert round(effective_buy_price(cm, 100.0), 4) == 100.15
    assert round(effective_sell_price(cm, 100.0), 4) == 99.85


# ── Entry ────────────────────────────────────────────────────────────────────

def test_entry_basic_fill_zero_costs():
    e = simulate_entry(ZERO_COSTS, _candle("2025-01-02", 100, 105, 99, 104),
                       signal_close=100.0, available_cash=5000.0,
                       desired_allocation=1000.0)
    assert e["filled"] and e["quantity"] == 10     # 1000 // 100
    assert e["fill_price"] == 100.0 and e["gap_pct"] == 0.0
    assert e["cash_used"] == 1000.0


def test_entry_gap_skip():
    cm = CostModel.from_dict({**ZERO_COSTS.to_dict(), "max_entry_gap_pct": 3.0})
    e = simulate_entry(cm, _candle("2025-01-02", 104, 106, 103, 105),
                       signal_close=100.0, available_cash=5000.0,
                       desired_allocation=1000.0)
    assert not e["filled"] and "Gap" in e["skip_reason"]
    assert e["gap_pct"] == 4.0
    # Gap within limit fills at the real gapped open
    e2 = simulate_entry(cm, _candle("2025-01-02", 102, 106, 101, 105),
                        signal_close=100.0, available_cash=5000.0,
                        desired_allocation=1000.0)
    assert e2["filled"] and e2["raw_open"] == 102.0


def test_entry_insufficient_capital():
    e = simulate_entry(ZERO_COSTS, _candle("2025-01-02", 3000, 3100, 2990, 3050),
                       signal_close=3000.0, available_cash=2500.0,
                       desired_allocation=2500.0)
    assert not e["filled"] and "Insufficient capital" in e["skip_reason"]


def test_entry_sizing_leaves_room_for_costs():
    # 10 shares @100 = 1000 turnover, but flat ₹25 brokerage per side means
    # only 9 shares fit in exactly ₹1000 cash.
    cm = CostModel.from_dict({**ZERO_COSTS.to_dict(),
                              "brokerage_flat": 25.0, "brokerage_max": 0})
    e = simulate_entry(cm, _candle("2025-01-02", 100, 105, 99, 104),
                       signal_close=100.0, available_cash=1000.0,
                       desired_allocation=1000.0)
    assert e["filled"] and e["quantity"] == 9
    assert e["cash_used"] <= 1000.0


def test_entry_partial_fill_volume_limit():
    cm = CostModel.from_dict({**ZERO_COSTS.to_dict(),
                              "allow_partial_fills": True,
                              "volume_participation_pct": 5.0})
    # candle volume 100 → max 5 shares
    e = simulate_entry(cm, _candle("2025-01-02", 100, 105, 99, 104, v=100),
                       signal_close=100.0, available_cash=5000.0,
                       desired_allocation=1000.0)
    assert e["filled"] and e["quantity"] == 5 and e["partial_fill"]
    assert e["requested_quantity"] == 10
    assert "Partial fill" in e["fill_note"]


# ── Same-candle exit rule ────────────────────────────────────────────────────

def test_conservative_rule_stop_first():
    c = {"open": 100, "high": 112, "low": 94, "close": 105}
    exited, raw, why, both = evaluate_exit_candle(c, stop_loss=95, target=110,
                                                  intrabar_rule=INTRABAR_CONSERVATIVE)
    assert exited and both and why == EXIT_STOP and raw == 95


def test_optimistic_rule_target_first():
    c = {"open": 100, "high": 112, "low": 94, "close": 105}
    exited, raw, why, both = evaluate_exit_candle(c, stop_loss=95, target=110,
                                                  intrabar_rule=INTRABAR_OPTIMISTIC)
    assert exited and both and why == EXIT_TARGET and raw == 110


def test_gap_through_stop_fills_at_open():
    c = {"open": 90, "high": 96, "low": 88, "close": 92}
    exited, raw, why, _ = evaluate_exit_candle(c, stop_loss=95, target=110)
    assert exited and why == EXIT_STOP and raw == 90   # gapped below stop


def test_gap_above_target_fills_at_open():
    c = {"open": 115, "high": 118, "low": 113, "close": 116}
    exited, raw, why, _ = evaluate_exit_candle(c, stop_loss=95, target=110)
    assert exited and why == EXIT_TARGET and raw == 115


# ── simulate_exit ────────────────────────────────────────────────────────────

def test_exit_stop_hit_and_mae_mfe():
    df = _df([
        _candle("2025-01-02", 100, 103, 99, 102),
        _candle("2025-01-03", 102, 104, 100, 103),
        _candle("2025-01-06", 101, 102, 94, 95),   # stop 95 hit
    ])
    x = simulate_exit(ZERO_COSTS, df, entry_price=100.0, stop_loss=95.0,
                      target=120.0, quantity=10)
    assert x["exit_reason"] == EXIT_STOP and x["exit_date"] == "2025-01-06"
    assert x["raw_exit_price"] == 95.0 and x["holding_days"] == 2
    assert x["mae_pct"] == -6.0                    # low 94 vs entry 100
    assert x["mfe_pct"] == 4.0                     # high 104


def test_exit_time_and_forced():
    rows = [_candle(f"2025-01-{d:02d}", 100, 101, 99, 100) for d in range(2, 8)]
    x = simulate_exit(ZERO_COSTS, _df(rows), 100.0, 90.0, 120.0, 10,
                      max_holding_days=3)
    assert x["exit_reason"] == EXIT_TIME and x["holding_days"] == 3
    x2 = simulate_exit(ZERO_COSTS, _df(rows[:2]), 100.0, 90.0, 120.0, 10,
                       max_holding_days=30)
    assert x2["exit_reason"] == EXIT_FORCED and x2["exit_date"] == "2025-01-03"


def test_exit_signal_date():
    rows = [_candle("2025-01-02", 100, 101, 99, 100),
            _candle("2025-01-03", 100, 101, 99, 100.5)]
    x = simulate_exit(ZERO_COSTS, _df(rows), 100.0, 90.0, 120.0, 10,
                      signal_exit_dates={"2025-01-03"})
    assert x["exit_reason"] == EXIT_SIGNAL and x["raw_exit_price"] == 100.5


# ── Round trip ───────────────────────────────────────────────────────────────

def test_trade_record_net_pnl_reconciles():
    cm = CostModel(slippage_pct=0.05, spread_pct=0.05, stt_pct=0.1,
                   stamp_pct=0.015, exchange_pct=0.00297, sebi_pct=0.0001,
                   gst_pct=18.0, brokerage_pct=0, brokerage_flat=0,
                   allow_partial_fills=False, max_entry_gap_pct=0)
    e = simulate_entry(cm, _candle("2025-01-02", 100, 103, 99, 102),
                       signal_close=100.0, available_cash=5000.0,
                       desired_allocation=2000.0)
    df = _df([_candle("2025-01-02", 100, 103, 99, 102),
              _candle("2025-01-03", 108, 112, 107, 111)])
    x = simulate_exit(cm, df, e["fill_price"], 95.0, 110.0, e["quantity"])
    rec = build_trade_record("TEST", e, x, {"confidence": 70})
    assert rec["exit_reason"] == EXIT_TARGET
    # Net = effective prices minus explicit costs; must be below gross
    assert rec["net_pnl"] < rec["gross_pnl"]
    expected_net = round((x["sell_price"] - e["fill_price"]) * e["quantity"]
                         - e["buy_costs"]["total"] - x["sell_costs"]["total"], 2)
    assert rec["net_pnl"] == expected_net
    assert rec["total_costs"] > 0 and rec["win"] is (rec["net_pnl"] > 0)
    assert rec["confidence"] == 70                 # meta passthrough


def test_conservative_never_beats_optimistic():
    """On identical both-touched data the conservative P&L must be <= optimistic."""
    df = _df([_candle("2025-01-02", 100, 111, 94, 105)])
    con = simulate_exit(ZERO_COSTS, df, 100.0, 95.0, 110.0, 10,
                        intrabar_rule=INTRABAR_CONSERVATIVE)
    opt = simulate_exit(ZERO_COSTS, df, 100.0, 95.0, 110.0, 10,
                        intrabar_rule=INTRABAR_OPTIMISTIC)
    assert con["raw_exit_price"] <= opt["raw_exit_price"]
    assert con["both_touched_candles"] == 1 and opt["both_touched_candles"] == 1


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"PASS {fn.__name__}")
    print(f"\n{len(fns)} test groups passed")
