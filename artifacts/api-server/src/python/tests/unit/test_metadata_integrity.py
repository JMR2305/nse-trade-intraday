"""Guard: detect silently-lost trade metadata that zeroes AI confidence
analytics (task: wrong-shape writers nesting fields under "metadata")."""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..")))

from ai_performance.metadata_integrity import (  # noqa: E402
    check_metadata_integrity, ZERO_CONFIDENCE_PCT_THRESHOLD, MIN_SAMPLE,
)


def buy(tid, conf=0.72, **extra):
    t = {"id": tid, "symbol": "TCS", "action": "BUY", "quantity": 1,
         "price": 100.0, "total": 100.0, "timestamp": "2026-08-07T04:00:00+00:00",
         "reason": ""}
    if conf is not None:
        t["signal_confidence"] = conf
    t.update(extra)
    return t


def sell(tid):
    return {"id": tid, "symbol": "TCS", "action": "SELL", "quantity": 1,
            "price": 105.0, "total": 105.0,
            "timestamp": "2026-08-07T06:00:00+00:00"}


def test_healthy_trades_pass():
    trades = [buy(f"T{i}") for i in range(5)] + [sell("S1")]
    out = check_metadata_integrity(trades)
    assert out["ok"] is True and out["flagged"] is False
    assert out["zero_confidence_trades"] == 0
    assert out["warnings"] == []


def test_mass_zero_confidence_flagged():
    trades = [buy(f"T{i}", conf=0.0) for i in range(5)]
    out = check_metadata_integrity(trades)
    assert out["flagged"] is True and out["ok"] is False
    assert out["zero_confidence_pct"] == 100.0
    assert any("zeroed" in w for w in out["warnings"])


def test_missing_confidence_counts_as_zero():
    trades = [buy(f"T{i}", conf=None) for i in range(4)]
    out = check_metadata_integrity(trades)
    assert out["flagged"] is True
    assert out["zero_confidence_trades"] == 4


def test_nested_metadata_shape_flagged_even_when_sample_small():
    # One wrong-shape row is a definite writer bug regardless of sample size.
    trades = [buy("T1", conf=None,
                  metadata={"signal_confidence": 0.8, "strategy_id": "s"})]
    out = check_metadata_integrity(trades)
    assert out["flagged"] is True
    assert out["nested_metadata_trades"] == 1
    assert out["nested_metadata_trade_ids"] == ["T1"]
    assert any("NESTED" in w for w in out["warnings"])


def test_nested_regime_alone_flagged():
    # The production writer uses "regime"; nesting only that field must be
    # caught even though confidence stays healthy (no %-heuristic trigger).
    trades = [buy(f"T{i}", conf=0.75) for i in range(4)]
    trades.append(buy("BAD", conf=0.9, metadata={"regime": "BULLISH"}))
    out = check_metadata_integrity(trades)
    assert out["flagged"] is True
    assert out["nested_metadata_trades"] == 1
    assert out["nested_metadata_trade_ids"] == ["BAD"]
    assert out["zero_confidence_pct"] == 0.0  # confidence heuristic silent


def test_small_sample_zero_confidence_not_flagged():
    # 1-2 manual trades without metadata must not trip the alarm.
    trades = [buy(f"T{i}", conf=0.0) for i in range(MIN_SAMPLE - 1)]
    out = check_metadata_integrity(trades)
    assert out["flagged"] is False and out["ok"] is True


def test_mixed_below_threshold_not_flagged():
    # 50% zero — below the 80% threshold, healthy trades dominate signal.
    trades = [buy("A", conf=0.7), buy("B", conf=0.8),
              buy("C", conf=0.0), buy("D", conf=None)]
    out = check_metadata_integrity(trades)
    assert out["zero_confidence_pct"] == 50.0
    assert out["flagged"] is False
    assert ZERO_CONFIDENCE_PCT_THRESHOLD == 80.0


def test_sells_ignored():
    trades = [sell(f"S{i}") for i in range(10)] + [buy("T1")]
    out = check_metadata_integrity(trades)
    assert out["total_buy_trades"] == 1 and out["ok"] is True


def test_never_raises_on_bad_input():
    out = check_metadata_integrity([{"action": "BUY", "quantity": "x"},
                                    "not-a-dict", None])
    assert isinstance(out, dict) and "flagged" in out


def test_loader_error_returns_advisory_error(monkeypatch):
    import portfolio_store

    def boom():
        raise RuntimeError("db down")
    monkeypatch.setattr(portfolio_store, "load_all_trades_any", boom)
    out = check_metadata_integrity(None)
    assert out["flagged"] is False and "db down" in out.get("error", "")
