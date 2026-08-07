"""
Deterministic tests for the v2.4 Walk-Forward Validator (pure functions only:
window generation, config parsing, no-lookahead guards, recommendation
mapping, forward evaluation and cost aggregation — no data or network).
Run: python tests/test_walk_forward_validator.py  (from src/python)
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

from walk_forward_validator import (
    ValidationConfig, generate_windows, _add_months, _knowledge_before,
    _recommendation_for, forward_eval, regime_as_of, aggregate_costs,
    export_csv_path, _audit_decision,
)
from datetime import datetime
from config import INITIAL_CAPITAL


# ── Window generation ────────────────────────────────────────────────────────

def test_add_months():
    assert _add_months(datetime(2024, 1, 31), 1) == datetime(2024, 2, 29)  # leap
    assert _add_months(datetime(2023, 1, 31), 1) == datetime(2023, 2, 28)
    assert _add_months(datetime(2024, 11, 15), 3) == datetime(2025, 2, 15)


def test_windows_no_overlap_no_lookahead():
    ws = generate_windows("2022-01-01", "2024-12-31",
                          train_years=1, test_months=3, step_months=3)
    assert len(ws) >= 4
    for w in ws:
        # Test period starts strictly after the training period ends.
        assert w["train_end"] < w["test_start"]
        assert w["train_start"] < w["train_end"] < w["test_start"] < w["test_end"]
    # Rolling step: consecutive train starts are 3 months apart
    assert ws[0]["train_start"] == "2022-01-01"
    assert ws[1]["train_start"] == "2022-04-01"
    # First window: train exactly one year, test exactly 3 months
    assert ws[0]["train_end"] == "2022-12-31"
    assert ws[0]["test_start"] == "2023-01-01"
    assert ws[0]["test_end"] == "2023-03-31"
    # No window's test period extends past the requested end
    assert all(w["test_end"] <= "2024-12-31" for w in ws)


def test_windows_too_short_period():
    assert generate_windows("2024-01-01", "2024-06-30", 1, 3, 3) == []


# ── Config ───────────────────────────────────────────────────────────────────

def test_config_defaults_and_sanitization():
    cfg = ValidationConfig.from_dict(None)
    assert cfg.train_years == 1 and cfg.test_months == 3 and cfg.step_months == 3
    assert cfg.initial_capital == INITIAL_CAPITAL
    cfg2 = ValidationConfig.from_dict({
        "train_years": 7,               # invalid → fall back to 1
        "test_months": 6,
        "intrabar_rule": "bogus",       # invalid → conservative
        "max_holding_days": 0,          # clamped to >= 1
        "universe": ["reliance", "TCS"],
        "universe_size": 10,
    })
    assert cfg2.train_years == 1 and cfg2.test_months == 6
    assert cfg2.intrabar_rule == "conservative"
    assert cfg2.max_holding_days == 1
    assert cfg2.universe == ["RELIANCE", "TCS"]
    assert cfg2.universe_size == 10


# ── No-lookahead guards ──────────────────────────────────────────────────────

def test_knowledge_before_filters_future_trades():
    knowledge = [
        {"exit_date": "2024-01-10", "symbol": "A"},
        {"exit_date": "2024-06-15", "symbol": "B"},
        {"exit_date": "2024-06-16", "symbol": "C"},
        {"exit_date": "", "symbol": "D"},           # no exit date → excluded
    ]
    out = _knowledge_before(knowledge, "2024-06-16")
    syms = {k["symbol"] for k in out}
    assert syms == {"A", "B"}                       # strictly before the day


def test_forward_eval_never_used_for_decisions_shape():
    rows = pd.DataFrame({
        "close": [100.0 + i for i in range(30)],
        "high": [101.0 + i for i in range(30)],
        "low": [99.0 + i for i in range(30)],
    })
    fe = forward_eval(rows, 5)
    assert fe["forward_returns"]["1"] == round(1 / 105 * 100, 2)
    assert fe["forward_returns"]["20"] == round(20 / 105 * 100, 2)
    assert fe["mfe_pct"] > 0
    # Near the end of data, unavailable horizons are None, not fabricated.
    fe2 = forward_eval(rows, 27)
    assert fe2["forward_returns"]["1"] is not None
    assert fe2["forward_returns"]["5"] is None
    assert fe2["forward_returns"]["20"] is None


def test_regime_as_of_uses_only_past_data():
    idx = pd.date_range("2024-01-01", periods=100, freq="D")
    rising = pd.DataFrame({"close": [100 + i for i in range(100)]}, index=idx)
    assert regime_as_of(rising, idx[99]) == "Bullish"
    # With fewer than 55 candles of history the regime is Unknown
    assert regime_as_of(rising, idx[10]) == "Unknown"
    falling = pd.DataFrame({"close": [200 - i for i in range(100)]}, index=idx)
    assert regime_as_of(falling, idx[99]) == "Bearish"


# ── Recommendation mapping (adjustments can only downgrade) ─────────────────

def test_recommendation_mapping():
    buy = {"technical_action": "BUY"}
    strong = {"technical_action": "STRONG BUY"}
    watch = {"technical_action": "WATCH"}
    ignore = {"technical_action": "IGNORE"}
    # Variant A never downgrades on confidence
    assert _recommendation_for(buy, "A", 40.0) == "BUY"
    # Learning variants downgrade a BUY below the execution threshold
    assert _recommendation_for(buy, "B", 50.0) == "WATCH"
    assert _recommendation_for(buy, "C", 54.9) == "WATCH"
    assert _recommendation_for(buy, "C", 60.0) == "BUY"
    assert _recommendation_for(strong, "C", 80.0) == "STRONG BUY"
    # Learning can never create a BUY out of a WATCH/IGNORE
    assert _recommendation_for(watch, "C", 95.0) == "WATCH"
    assert _recommendation_for(ignore, "C", 95.0) == "AVOID"


# ── Cost aggregation ─────────────────────────────────────────────────────────

def test_aggregate_costs_reconciles():
    trades = [{
        "entry_price": 100.1, "raw_open": 100.0,
        "raw_exit_price": 110.0, "exit_price": 109.9,
        "quantity": 10, "gross_pnl": 100.0, "net_pnl": 90.0,
        "buy_costs": {"brokerage": 1.0, "stt": 1.0, "exchange": 0.1,
                      "sebi": 0.01, "stamp_duty": 0.15, "gst": 0.2},
        "sell_costs": {"brokerage": 1.0, "stt": 1.1, "exchange": 0.1,
                       "sebi": 0.01, "stamp_duty": 0.0, "gst": 0.2},
    }]
    agg = aggregate_costs(trades)
    assert agg["brokerage"] == 2.0
    assert agg["stt"] == 2.1
    assert agg["stamp_duty"] == 0.15
    assert agg["slippage_and_spread"] == 2.0        # (0.1 + 0.1) * 10
    assert agg["gross_pnl"] == 100.0 and agg["net_pnl"] == 90.0
    assert agg["cost_drag"] == 10.0


def test_export_csv_path_rejects_unknown_kind():
    assert export_csv_path("nonsense") is None


# ── Lookahead audit covers every data source ─────────────────────────────────

def test_audit_decision_flags_future_data_from_any_source():
    day = "2024-06-14"

    # Clean decision: same-day candle, knowledge/similarity strictly older.
    log = {}
    assert _audit_decision(log, day, "2024-06-14", "2024-06-10", "2024-06-01") is False
    assert log["decisions"] == 1 and log["violations"] == 0

    # Future candle (bar newer than the decision day) → violation.
    log = {}
    assert _audit_decision(log, day, "2024-06-17", "", "") is True
    assert log["violations"] == 1

    # Knowledge trade exiting ON the decision day (not fully exited BEFORE) → violation.
    log = {}
    assert _audit_decision(log, day, day, "2024-06-14", "") is True
    assert log["violations"] == 1

    # Knowledge trade exiting AFTER the decision day → violation.
    log = {}
    assert _audit_decision(log, day, day, "2024-07-01", "") is True
    assert log["violations"] == 1

    # Similarity match not exited before the decision day → violation.
    log = {}
    assert _audit_decision(log, day, day, "", "2024-06-20") is True
    assert log["violations"] == 1

    # Empty knowledge/similarity (variant A or no matches) is never a violation.
    log = {}
    assert _audit_decision(log, day, day, "", "") is False
    assert log["violations"] == 0

    # Max-seen timestamps are tracked per source across decisions.
    log = {}
    _audit_decision(log, day, "2024-06-13", "2024-06-10", "2024-06-05")
    _audit_decision(log, day, "2024-06-14", "2024-06-12", "2024-06-01")
    assert log["decisions"] == 2 and log["violations"] == 0
    assert log["max_timestamp"] == "2024-06-14"
    assert log["max_knowledge_timestamp"] == "2024-06-12"
    assert log["max_similarity_timestamp"] == "2024-06-05"


def test_similarity_adjustment_reports_newest_match_used():
    """The similarity path must report the newest exit_date among matches it
    actually used, so the audit can independently verify no-lookahead. With
    injected future-dated vectors the engine's as_of filter must exclude them,
    leaving no usable match (empty timestamp)."""
    from walk_forward_validator import _similarity_adjustment

    item = {
        "stock": "RELIANCE", "sector": "ENERGY", "best_strategy_id": "ema_cross",
        "rsi": 55.0, "adx": 25.0, "volume_ratio": 1.2, "rr_ratio": 2.0,
        "above_ema20": True, "above_ema50": True, "error": None,
    }
    future_vectors = [
        {"symbol": "RELIANCE", "strategy": "ema_cross", "sector": "ENERGY",
         "regime": "Bullish", "entry_date": "2024-06-20", "exit_date": "2024-06-28",
         "return_percent": 5.0, "holding_days": 8, "exit_reason": "TARGET", "id": 1},
    ]
    adj, used_max = _similarity_adjustment(item, future_vectors, "Bullish", "2024-06-14")
    # Future-dated vectors must be filtered out: no match may be used, and the
    # reported used-timestamp must be empty (nothing newer than the day leaked in).
    assert used_max == "" or used_max < "2024-06-14"
    assert isinstance(adj, float)


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"PASS {fn.__name__}")
    print(f"\n{len(fns)} test groups passed")
