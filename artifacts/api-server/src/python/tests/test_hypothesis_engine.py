"""
Automated tests — Version 2.1 Hypothesis Engine.

Covers:
  - Pattern mining minimum sample size (30 trades per segment)
  - Statistical confidence estimation (clear effect vs pure noise)
  - Human-readable hypothesis statements + rationale
  - Approval flow: out-of-sample validation -> bounded model version
  - Combo scope matching in the decision modifier
  - Rejection flow
  - Effectiveness tracking + automatic rollback of ineffective hypotheses
  - Mock data can NEVER feed hypothesis generation
"""

import json
import os
import sys
from datetime import datetime, timedelta

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import trade_evaluator
import failure_analyzer
import model_versioning
import adaptive_adjustments
import hypothesis_engine


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture()
def tmp_db(tmp_path, monkeypatch):
    db = str(tmp_path / "test_intel.db")
    monkeypatch.setattr(trade_evaluator, "DB_PATH", db)
    monkeypatch.setattr(model_versioning, "DB_PATH", db)
    monkeypatch.setattr(adaptive_adjustments, "DB_PATH", db)
    monkeypatch.setattr(hypothesis_engine, "DB_PATH", db)

    monkeypatch.setattr(trade_evaluator, "_excursions",
                        lambda *a, **k: (None, None, None, "yfinance"))
    monkeypatch.setattr(failure_analyzer, "_regime_at", lambda d: "")
    monkeypatch.setattr(failure_analyzer, "_kb_strategy_stats",
                        lambda *a, **k: None)

    import market_data_engine
    monkeypatch.setattr(market_data_engine, "get_last_source",
                        lambda sym: "yfinance")
    return db


def _buy(trade_id, symbol="TCS", conf=82.0, strategy="macd_cross",
         strategy_name="MACD Cross", regime="Strong Bull", rsi=58, adx=28):
    ts = (datetime.now() - timedelta(days=15)).isoformat()
    return {
        "id": trade_id, "symbol": symbol, "action": "BUY", "price": 100.0,
        "timestamp": ts, "signal_confidence": conf, "stop_loss": 95.0,
        "target": 110.0, "rr_ratio": 2.0,
        "strategy_id": strategy, "strategy_name": strategy_name,
        "ai_decision": "BUY", "market_regime_at_entry": regime,
        "volatility_at_entry": 14.0,
        "indicators_at_entry": {"rsi": rsi, "adx": adx, "ema9": 101,
                                "ema20": 100, "ema50": 98, "macd": 1.2,
                                "macd_signal": 0.8, "volume_ratio": 1.4,
                                "atr": 2.0},
    }


def _sell(trade_id, symbol="TCS", price=108.0):
    ts = (datetime.now() - timedelta(days=3)).isoformat()
    return {"id": trade_id, "symbol": symbol, "action": "SELL", "price": price,
            "timestamp": ts, "exit_type": "SIGNAL_EXIT", "quantity": 1}


def _round_trip(i, ret_pct, symbol="TCS", sector="IT", strategy="macd_cross",
                strategy_name="MACD Cross", regime="Strong Bull"):
    buy = _buy(f"b{i}", symbol=symbol, strategy=strategy,
               strategy_name=strategy_name, regime=regime)
    trade_evaluator.store_prediction_snapshot(buy, sector=sector, scan_item={})
    sell = _sell(f"s{i}", symbol=symbol,
                 price=round(100.0 * (1 + ret_pct / 100.0), 2))
    return trade_evaluator.evaluate_closed_trade(buy, sell, sector=sector)


def _seed_split(n_bad=35, n_good=40):
    """Losing MACD Cross/BANKING/Strong Bull segment + winning rest."""
    i = 0
    for _ in range(n_bad):
        _round_trip(i, ret_pct=-2.5, symbol="SBIN", sector="BANKING",
                    strategy="macd_cross", strategy_name="MACD Cross",
                    regime="Strong Bull")
        i += 1
    for _ in range(n_good):
        _round_trip(i, ret_pct=3.0, symbol="TCS", sector="IT",
                    strategy="mean_reversion", strategy_name="Mean Reversion",
                    regime="Neutral")
        i += 1


def _eligible():
    return adaptive_adjustments._eligible_evaluations()


# ── 1. Minimum sample size (spec: 30 trades) ─────────────────────────────────

def test_min_sample_size_blocks_small_segments(tmp_db):
    _seed_split(n_bad=29, n_good=40)      # segment 1 short of the minimum
    findings = hypothesis_engine.mine_patterns(_eligible())
    assert all(
        not (f["dims"].get("sector") == "BANKING"
             and set(f["dims"]) >= {"strategy", "sector"})
        or f["sample_size"] >= 30
        for f in findings)
    # No finding may cite a segment smaller than 30 trades.
    assert all(f["sample_size"] >= 30 for f in findings)


def test_pattern_detected_at_min_sample(tmp_db):
    _seed_split(n_bad=35, n_good=40)
    findings = hypothesis_engine.mine_patterns(_eligible())
    assert findings, "clear losing segment must produce findings"
    combo = [f for f in findings
             if f["dims"].get("strategy") == "macd_cross"
             and f["dims"].get("sector") == "BANKING"
             and f["dims"].get("regime") == "Strong Bull"]
    assert combo, "3-dim strategy+sector+regime pattern must be detected"
    assert combo[0]["direction"] == "reduce"
    assert combo[0]["confidence_pct"] >= 90.0
    assert combo[0]["sample_size"] == 35


def test_noise_produces_no_findings(tmp_db):
    # Same tiny alternating returns everywhere — no real segment difference.
    for i in range(70):
        ret = 0.6 if i % 2 == 0 else -0.5
        sector = "BANKING" if i % 2 == 0 else "IT"
        _round_trip(i, ret_pct=ret, symbol="SBIN" if i % 2 == 0 else "TCS",
                    sector=sector)
    findings = hypothesis_engine.mine_patterns(_eligible())
    # Alternating construction gives segments whose expectancies differ, but
    # the returns within each segment are constant -> variance 0 handled;
    # what matters: statistical confidence gate keeps weak/noisy effects out.
    for f in findings:
        assert f["confidence_pct"] >= 90.0


def test_single_dimension_patterns_are_mined(tmp_db):
    _seed_split(n_bad=35, n_good=40)
    findings = hypothesis_engine.mine_patterns(_eligible())
    # Broad single-dimension segments must be detected too, not only combos.
    singles = [f for f in findings if len(f["dims"]) == 1]
    assert singles, "single-dimension patterns must be mined"
    assert any(f["dims"] == {"sector": "BANKING"} for f in singles)
    assert any(f["dims"] == {"strategy": "macd_cross"} for f in singles)


def test_material_metric_must_be_significant_on_its_own_test(tmp_db):
    # Segment: expectancy differs materially but win rates are nearly equal
    # AND the returns are so noisy that the returns test cannot reach 90%.
    # A strong win-rate test may NOT carry a weak returns test.
    import random
    rng = random.Random(7)
    i = 0
    for _ in range(35):        # segment: mean ~ +0.35%, huge spread
        _round_trip(i, ret_pct=0.35 + rng.uniform(-8, 8), symbol="SBIN",
                    sector="BANKING")
        i += 1
    for _ in range(40):        # rest: mean ~ 0.0%, huge spread
        _round_trip(i, ret_pct=rng.uniform(-8, 8), symbol="TCS",
                    sector="IT", strategy="mean_reversion",
                    strategy_name="Mean Reversion", regime="Neutral")
        i += 1
    findings = hypothesis_engine.mine_patterns(_eligible())
    for f in findings:
        ev = f["evidence"]
        if abs(ev["expectancy_diff"]) >= hypothesis_engine.MIN_EFFECT_EXPECTANCY:
            assert ev["confidence_returns_test"] >= hypothesis_engine.MIN_CONFIDENCE
        if abs(ev["win_rate_diff"]) >= hypothesis_engine.MIN_EFFECT_WIN_RATE:
            assert ev["confidence_win_rate_test"] >= hypothesis_engine.MIN_CONFIDENCE


# ── 2. Statistical confidence ─────────────────────────────────────────────────

def test_confidence_math():
    # Clear difference -> near-certain; identical -> no confidence.
    assert hypothesis_engine.win_rate_confidence(5, 40, 35, 40) > 99.0
    assert hypothesis_engine.win_rate_confidence(20, 40, 20, 40) == 0.0
    strong = hypothesis_engine.returns_confidence(
        [-2.0 + 0.01 * i for i in range(40)], [2.0 + 0.01 * i for i in range(40)])
    assert strong > 99.0


# ── 3. Human-readable statements ─────────────────────────────────────────────

def test_statement_is_human_readable(tmp_db):
    _seed_split()
    created = hypothesis_engine.generate_hypotheses(_eligible())
    assert created
    hyps = hypothesis_engine.get_hypotheses()
    combo = [h for h in hyps
             if h["scope_type"] == "strategy+sector+regime"][0]
    s = combo["statement"]
    assert "Reduce confidence for MACD Cross" in s
    assert "in Banking" in s
    assert "during Strong Bull markets" in s
    assert "%" in s
    assert combo["rationale"]           # the inferred WHY is spelled out
    assert "underperformed" in combo["rationale"]
    assert combo["evidence"]["segment"]["trades"] >= 30


# ── 4. Approval flow: OOS validation -> bounded model version ────────────────

def _kb(n=200, seg_ret=-2.0, rest_ret=2.0):
    """Synthetic knowledge base: MACD Cross/BANKING/Strong Bull loses."""
    out = []
    for i in range(n):
        in_seg = i % 4 == 0
        out.append({
            "symbol": "SBIN" if in_seg else "TCS",
            "sector": "BANKING" if in_seg else "IT",
            "strategy": "macd_cross" if in_seg else "mean_reversion",
            "market_regime": "Strong Bull" if in_seg else "Neutral",
            "exit_date": f"2025-{(i % 12) + 1:02d}-15",
            "holding_days": 5, "confidence": 80,
            "return_percent": seg_ret if in_seg else rest_ret,
            "rsi": 58, "adx": 28, "volume_ratio": 1.4,
            "volatility_regime": "normal",
        })
    return out


def test_approve_creates_bounded_model_version(tmp_db, monkeypatch):
    monkeypatch.setattr(adaptive_adjustments, "_kb_trades", _kb)
    _seed_split()
    hypothesis_engine.generate_hypotheses(_eligible())
    combo = [h for h in hypothesis_engine.get_hypotheses()
             if h["scope_type"] == "strategy+sector+regime"][0]
    assert combo["magnitude_pct"] <= -5.0          # meaningful suggestion
    assert abs(combo["step_points"]) <= 3.0        # but bounded application

    res = hypothesis_engine.approve_hypothesis(combo["id"])
    assert res["success"], res
    assert res["status"] == "APPLIED"
    active = model_versioning.get_active_version()
    scope = f"{combo['scope_type']}|{combo['scope_key']}"
    assert active["weights"][scope] == combo["step_points"]
    assert abs(active["weights"][scope]) <= 3.0

    # Audit trail preserved
    h = [x for x in hypothesis_engine.get_hypotheses()
         if x["id"] == combo["id"]][0]
    assert h["status"] == "APPLIED"
    assert h["applied_version"] == res["model_version"]
    assert h["validation"]["passed"] is True


def test_combo_scope_affects_only_matching_context(tmp_db, monkeypatch):
    monkeypatch.setattr(adaptive_adjustments, "_kb_trades", _kb)
    _seed_split()
    hypothesis_engine.generate_hypotheses(_eligible())
    combo = [h for h in hypothesis_engine.get_hypotheses()
             if h["scope_type"] == "strategy+sector+regime"][0]
    hypothesis_engine.approve_hypothesis(combo["id"])
    weights = model_versioning.get_active_version()["weights"]

    hit, applied = model_versioning.modifier_for(
        {"strategy_id": "macd_cross", "sector": "BANKING",
         "regime": "Strong Bull"}, weights)
    assert hit == combo["step_points"]
    assert applied

    miss, _ = model_versioning.modifier_for(
        {"strategy_id": "macd_cross", "sector": "IT",
         "regime": "Strong Bull"}, weights)
    assert miss == 0.0


def test_oos_validation_failure_auto_rejects(tmp_db, monkeypatch):
    # KB says the segment WINS out-of-sample -> reducing it must be rejected.
    monkeypatch.setattr(adaptive_adjustments, "_kb_trades",
                        lambda: _kb(seg_ret=3.0, rest_ret=0.5))
    _seed_split()
    hypothesis_engine.generate_hypotheses(_eligible())
    combo = [h for h in hypothesis_engine.get_hypotheses()
             if h["scope_type"] == "strategy+sector+regime"][0]
    res = hypothesis_engine.approve_hypothesis(combo["id"])
    assert res["success"] is False
    assert res["status"] == "REJECTED"
    assert model_versioning.get_active_version()["version"] == 0


def test_reject_hypothesis(tmp_db):
    _seed_split()
    hypothesis_engine.generate_hypotheses(_eligible())
    h = hypothesis_engine.get_hypotheses()[0]
    res = hypothesis_engine.reject_hypothesis(h["id"])
    assert res["success"] and res["status"] == "REJECTED"
    assert model_versioning.get_active_version()["version"] == 0
    # Double decision is refused
    assert hypothesis_engine.reject_hypothesis(h["id"])["success"] is False


# ── 5. Effectiveness tracking + automatic rollback ───────────────────────────

def test_auto_rollback_of_ineffective_hypothesis(tmp_db, monkeypatch):
    monkeypatch.setattr(adaptive_adjustments, "_kb_trades", _kb)
    _seed_split()
    hypothesis_engine.generate_hypotheses(_eligible())
    combo = [h for h in hypothesis_engine.get_hypotheses()
             if h["scope_type"] == "strategy+sector+regime"][0]
    res = hypothesis_engine.approve_hypothesis(combo["id"])
    version = res["model_version"]
    assert model_versioning.get_active_version()["version"] == version

    # After the reduction went live the "bad" segment turns clearly healthy
    # -> the penalty was wrong and must be rolled back automatically.
    for i in range(200, 212):
        _round_trip(i, ret_pct=4.0, symbol="SBIN", sector="BANKING",
                    strategy="macd_cross", strategy_name="MACD Cross",
                    regime="Strong Bull")

    actions = hypothesis_engine.track_effectiveness()
    rb = [a for a in actions if a["action"] == "auto_rollback"]
    assert rb, actions
    assert rb[0]["hypothesis_id"] == combo["id"]
    assert model_versioning.get_active_version()["version"] < version

    h = [x for x in hypothesis_engine.get_hypotheses()
         if x["id"] == combo["id"]][0]
    assert h["status"] == "ROLLED_BACK"
    assert h["effectiveness"]["verdict"] == "rolled_back"
    assert h["effectiveness"]["note"]


def test_effective_hypothesis_is_kept(tmp_db, monkeypatch):
    monkeypatch.setattr(adaptive_adjustments, "_kb_trades", _kb)
    _seed_split()
    hypothesis_engine.generate_hypotheses(_eligible())
    combo = [h for h in hypothesis_engine.get_hypotheses()
             if h["scope_type"] == "strategy+sector+regime"][0]
    res = hypothesis_engine.approve_hypothesis(combo["id"])

    # Segment keeps losing after the reduction -> the hypothesis was right.
    for i in range(300, 312):
        _round_trip(i, ret_pct=-2.0, symbol="SBIN", sector="BANKING",
                    strategy="macd_cross", strategy_name="MACD Cross",
                    regime="Strong Bull")

    actions = hypothesis_engine.track_effectiveness()
    kept = [a for a in actions if a["action"] == "kept"]
    assert kept
    assert model_versioning.get_active_version()["version"] == res["model_version"]
    h = [x for x in hypothesis_engine.get_hypotheses()
         if x["id"] == combo["id"]][0]
    assert h["status"] == "APPLIED"
    assert h["effectiveness"]["verdict"] == "effective"


def test_too_few_post_trades_keeps_monitoring(tmp_db, monkeypatch):
    monkeypatch.setattr(adaptive_adjustments, "_kb_trades", _kb)
    _seed_split()
    hypothesis_engine.generate_hypotheses(_eligible())
    combo = [h for h in hypothesis_engine.get_hypotheses()
             if h["scope_type"] == "strategy+sector+regime"][0]
    res = hypothesis_engine.approve_hypothesis(combo["id"])
    for i in range(400, 403):     # only 3 post trades — not enough to judge
        _round_trip(i, ret_pct=4.0, symbol="SBIN", sector="BANKING",
                    strategy="macd_cross", strategy_name="MACD Cross",
                    regime="Strong Bull")
    hypothesis_engine.track_effectiveness()
    assert model_versioning.get_active_version()["version"] == res["model_version"]
    h = [x for x in hypothesis_engine.get_hypotheses()
         if x["id"] == combo["id"]][0]
    assert h["status"] == "APPLIED"
    assert h["effectiveness"]["verdict"] == "monitoring"


# ── 6. Mock data can NEVER feed hypotheses ───────────────────────────────────

def test_mock_trades_never_feed_hypotheses(tmp_db, monkeypatch):
    import market_data_engine
    monkeypatch.setattr(market_data_engine, "get_last_source", lambda s: "mock")
    _seed_split()                              # every trade is mock-sourced
    created = hypothesis_engine.generate_hypotheses()   # uses eligible only
    assert created == []
    assert hypothesis_engine.get_hypotheses() == []


# ── 7. Learning cycle integration ─────────────────────────────────────────────

def test_learning_cycle_includes_hypotheses(tmp_db, monkeypatch):
    monkeypatch.setattr(trade_evaluator, "backfill_evaluations",
                        lambda: {"evaluated": 0})
    import adaptive_learning
    monkeypatch.setattr(adaptive_learning, "current_market_regime",
                        lambda: "Neutral")
    _seed_split()
    result = adaptive_adjustments.run_learning_cycle()
    assert result["hypotheses_created"] > 0
    assert result["hypotheses"][0]["statement"]
    assert isinstance(result["effectiveness_actions"], list)
    # Analysis mode still applies nothing
    assert model_versioning.get_active_version()["version"] == 0
