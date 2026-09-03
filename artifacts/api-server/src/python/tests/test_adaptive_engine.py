"""
Automated tests — Version 2.0 Adaptive Self-Evaluation Engine (spec §14).

Covers:
  - Prediction snapshot storage + trade evaluation math
  - learn_eligible gating (mock data can NEVER feed learning)
  - Evidence-based failure/success analysis
  - Model versioning: ±3 step / ±15 total caps, rollback, modifier lookup
  - Learning cycle: sample-size guards (≥30 group / ≥15 symbol), analysis
    mode applies nothing
  - Out-of-sample validation + approve/reject flow
  - Decision safety: a learning adjustment can never create a BUY on its own
"""

import json
import os
import sqlite3
import sys
from datetime import datetime, timedelta

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import trade_evaluator
import failure_analyzer
import model_versioning
import adaptive_adjustments
import decision_service
import market_data_engine


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture()
def tmp_db(tmp_path, monkeypatch):
    """Isolated sqlite DB for every learning module + stubbed externals."""
    db = str(tmp_path / "test_intel.db")
    monkeypatch.setattr(trade_evaluator, "DB_PATH", db)
    monkeypatch.setattr(model_versioning, "DB_PATH", db)
    monkeypatch.setattr(adaptive_adjustments, "DB_PATH", db)

    # No network: excursions come back empty unless a test overrides them.
    monkeypatch.setattr(trade_evaluator, "_excursions",
                        lambda *a, **k: (None, None, None, "yfinance"))
    # Deterministic, no real-DB lookups inside the analyzer.
    monkeypatch.setattr(failure_analyzer, "_regime_at", lambda d: "")
    monkeypatch.setattr(failure_analyzer, "_kb_strategy_stats",
                        lambda *a, **k: None)

    monkeypatch.setattr(market_data_engine, "get_last_source",
                        lambda sym: "yfinance")
    return db


def _buy(trade_id="b1", symbol="TCS", price=100.0, stop=95.0, target=110.0,
         conf=82.0, days_ago=10, strategy="teststrat", regime="Bullish"):
    ts = (datetime.now() - timedelta(days=days_ago)).isoformat()
    return {
        "id": trade_id, "symbol": symbol, "action": "BUY", "price": price,
        "timestamp": ts, "signal_confidence": conf, "stop_loss": stop,
        "target": target, "rr_ratio": round((target - price) / (price - stop), 1),
        "strategy_id": strategy, "strategy_name": strategy,
        "ai_decision": "BUY", "market_regime_at_entry": regime,
        "volatility_at_entry": 14.0,
        "indicators_at_entry": {"rsi": 58, "adx": 28, "ema9": 101, "ema20": 100,
                                "ema50": 98, "macd": 1.2, "macd_signal": 0.8,
                                "volume_ratio": 1.4, "atr": 2.0},
    }


def _sell(trade_id="s1", symbol="TCS", price=108.0, days_ago=2,
          exit_type="SIGNAL_EXIT", qty=1):
    ts = (datetime.now() - timedelta(days=days_ago)).isoformat()
    return {"id": trade_id, "symbol": symbol, "action": "SELL", "price": price,
            "timestamp": ts, "exit_type": exit_type, "quantity": qty}


def _round_trip(i, ret_pct, symbol="TCS", conf=82.0, strategy="teststrat",
                sector="IT", regime="Bullish"):
    """Store snapshot + evaluation for one synthetic completed trade."""
    buy = _buy(trade_id=f"b{i}", symbol=symbol, conf=conf, strategy=strategy,
               regime=regime, days_ago=15)
    trade_evaluator.store_prediction_snapshot(buy, sector=sector, scan_item={})
    sell = _sell(trade_id=f"s{i}", symbol=symbol,
                 price=round(100.0 * (1 + ret_pct / 100.0), 2), days_ago=3)
    return trade_evaluator.evaluate_closed_trade(buy, sell, sector=sector)


# ── 1. Snapshot + evaluation math ─────────────────────────────────────────────

def test_snapshot_stored_and_retrievable(tmp_db):
    buy = _buy()
    snap = trade_evaluator.store_prediction_snapshot(buy, sector="IT", scan_item={})
    assert snap["data_source"] == "yfinance"
    assert snap["expected_return"] == 10.0          # (110-100)/100
    stored = trade_evaluator.get_snapshot("b1")
    assert stored is not None
    assert stored["symbol"] == "TCS"
    assert stored["final_confidence"] == 82.0
    assert stored["model_version"] == 0


def test_evaluation_math(tmp_db):
    ev = _round_trip(1, ret_pct=8.0)
    assert ev["actual_return"] == 8.0
    assert ev["expected_return"] == 10.0
    assert ev["prediction_error"] == -2.0           # actual - expected
    assert ev["direction_correct"] == 1
    assert ev["calibration_error"] == -18.0         # 82 - 100
    assert ev["learn_eligible"] == 1
    assert ev["outcome_class"]                      # classified
    assert ev["actual_holding_days"] > 0


def test_stop_and_target_detection(tmp_db):
    buy = _buy(trade_id="b_st", stop=95.0, target=110.0)
    trade_evaluator.store_prediction_snapshot(buy, sector="IT", scan_item={})
    ev = trade_evaluator.evaluate_closed_trade(
        buy, _sell(trade_id="s_st", price=94.9), sector="IT")
    assert ev["stop_hit"] == 1 and ev["target_hit"] == 0
    buy2 = _buy(trade_id="b_tg")
    trade_evaluator.store_prediction_snapshot(buy2, sector="IT", scan_item={})
    ev2 = trade_evaluator.evaluate_closed_trade(
        buy2, _sell(trade_id="s_tg", price=110.5), sector="IT")
    assert ev2["target_hit"] == 1 and ev2["stop_hit"] == 0


def test_mock_data_never_learn_eligible(tmp_db, monkeypatch):
    import market_data_engine
    monkeypatch.setattr(market_data_engine, "get_last_source", lambda s: "mock")
    buy = _buy(trade_id="b_mock")
    trade_evaluator.store_prediction_snapshot(buy, sector="IT", scan_item={})
    ev = trade_evaluator.evaluate_closed_trade(
        buy, _sell(trade_id="s_mock"), sector="IT")
    assert ev["learn_eligible"] == 0
    assert ev["data_source"] == "mock"
    # And the learning layer must not see it:
    assert adaptive_adjustments._eligible_evaluations() == []


def test_live_buy_mock_sell_not_learn_eligible(tmp_db, monkeypatch):
    """Mixed-source round trip: BUY on live data, SELL on mock → excluded."""
    import market_data_engine
    buy = _buy(trade_id="b_mix")            # snapshot stored while yfinance
    trade_evaluator.store_prediction_snapshot(buy, sector="IT", scan_item={})
    assert trade_evaluator.get_snapshot("b_mix")["data_source"] == "yfinance"
    # Data source degrades to mock by SELL time:
    monkeypatch.setattr(market_data_engine, "get_last_source", lambda s: "mock")
    ev = trade_evaluator.evaluate_closed_trade(
        buy, _sell(trade_id="s_mix"), sector="IT")
    assert ev["learn_eligible"] == 0
    assert ev["data_source"] == "mock"
    assert adaptive_adjustments._eligible_evaluations() == []


def test_unverified_excursion_source_not_learn_eligible(tmp_db, monkeypatch):
    """Evaluation-time verification fetch not live → conservatively excluded."""
    monkeypatch.setattr(trade_evaluator, "_excursions",
                        lambda *a, **k: (None, None, None, "unknown"))
    buy = _buy(trade_id="b_unv")
    trade_evaluator.store_prediction_snapshot(buy, sector="IT", scan_item={})
    ev = trade_evaluator.evaluate_closed_trade(
        buy, _sell(trade_id="s_unv"), sector="IT")
    assert ev["learn_eligible"] == 0
    assert ev["data_source"] == "unknown"
    assert adaptive_adjustments._eligible_evaluations() == []


# ── 2. Failure / success analysis is evidence-based ──────────────────────────

def test_failure_causes_have_evidence(tmp_db):
    snap = {"indicators": {"ema9": 90, "ema20": 95, "ema50": 98,
                           "volume_ratio": 0.5, "atr": 2.0, "rsi": 45},
            "stop_loss": 95.0, "target": 110.0, "market_regime": "Bullish",
            "data_source": "yfinance", "historical_matches": 40}
    ev = {"actual_return": -4.0, "expected_return": 8.0, "entry_price": 100.0,
          "prediction_error": -12.0, "mfe": 0.5, "mae": -4.5,
          "exit_time": "", "actual_holding_days": 5, "exit_type": "STOP_HIT",
          "stop_hit": 1}
    causes, factors, lesson = failure_analyzer.analyze_trade(snap, ev)
    names = {c["cause"] for c in causes}
    assert "Entered against broader trend" in names
    assert "Volume confirmation was weak" in names
    assert "Momentum reversed" in names
    for c in causes:                              # every cause carries evidence
        assert c["evidence"] and c["severity"] in ("High", "Medium", "Low")
        assert 0 <= c["diagnosis_confidence"] <= 100
    assert factors == []
    assert "cause" in lesson.lower() or "Loss" in lesson


def test_success_factors_for_winner(tmp_db):
    snap = {"indicators": {"ema9": 105, "ema20": 103, "ema50": 100, "adx": 30,
                           "volume_ratio": 1.5, "rsi": 60, "macd": 1.0,
                           "macd_signal": 0.5},
            "expected_rr": 2.5, "market_regime": "Bullish",
            "historical_matches": 50, "historical_expectancy": 1.2}
    ev = {"actual_return": 6.0, "expected_return": 7.0, "target_hit": 1,
          "exit_price": 106.0, "actual_holding_days": 4}
    causes, factors, lesson = failure_analyzer.analyze_trade(snap, ev)
    names = {f["factor"] for f in factors}
    assert "Strong trend alignment" in names
    assert "High-quality historical pattern" in names
    assert causes == []
    assert lesson.startswith("Winner")


def test_no_evidence_no_cause(tmp_db):
    # Loss but with no data at all → no invented causes.
    causes, factors, lesson = failure_analyzer.analyze_trade(
        {"indicators": {}, "data_source": "yfinance", "historical_matches": 40},
        {"actual_return": -1.0, "exit_time": ""})
    assert causes == [] or all(c["evidence"] for c in causes)


# ── 3. Model versioning: caps + rollback ─────────────────────────────────────

def test_apply_update_clamps_step_to_3(tmp_db):
    r = model_versioning.apply_update({"strategy|x": 10.0}, "test", 30, "test")
    assert r["applied"] and r["weights"]["strategy|x"] == 3.0


def test_total_weight_capped_at_15(tmp_db):
    for _ in range(7):
        r = model_versioning.apply_update({"strategy|x": 3.0}, "t", 30, "t")
    assert model_versioning.get_active_version()["weights"]["strategy|x"] == 15.0
    r = model_versioning.apply_update({"strategy|x": 3.0}, "t", 30, "t")
    assert r["applied"] is False                  # cap reached → no new version


def test_rollback_restores_previous(tmp_db):
    model_versioning.apply_update({"sector|IT": 2.0}, "v1", 30, "t")
    model_versioning.apply_update({"sector|IT": 2.0}, "v2", 30, "t")
    assert model_versioning.get_active_version()["weights"]["sector|IT"] == 4.0
    rb = model_versioning.rollback(2)
    assert rb["success"]
    assert model_versioning.get_active_version()["weights"]["sector|IT"] == 2.0
    rb0 = model_versioning.rollback(1)
    assert model_versioning.get_active_version()["version"] == 0


def test_modifier_for_sums_and_clamps(tmp_db):
    w = {"symbol|TCS": 5.0, "sector|IT": -2.0, "strategy|zz": 9.0}
    pts, applied = model_versioning.modifier_for(
        {"symbol": "TCS", "sector": "IT"}, w)
    assert pts == 3.0 and len(applied) == 2
    big = {"symbol|TCS": 15.0, "sector|IT": 15.0}
    pts2, _ = model_versioning.modifier_for({"symbol": "TCS", "sector": "IT"}, big)
    assert pts2 == 15.0                           # clamped to ±15 overall


def test_confidence_band():
    assert model_versioning.confidence_band(55) == "50-59"
    assert model_versioning.confidence_band(82) == "80-89"
    assert model_versioning.confidence_band(93) == "90-95"


# ── 4. Learning cycle: sample guards + analysis mode ─────────────────────────

def test_no_proposals_below_sample_minimum(tmp_db, monkeypatch):
    monkeypatch.setattr(trade_evaluator, "backfill_evaluations",
                        lambda: {"evaluated": 0})
    for i in range(10):                           # only 10 trades (< 15 / < 30)
        _round_trip(i, ret_pct=5.0, symbol=f"SYM{i}")
    out = adaptive_adjustments.run_learning_cycle()
    assert out["mode"] == "analysis"
    assert out["proposals_created"] == 0
    assert any("sample size" in n for n in out["notes"])
    assert model_versioning.get_active_version()["version"] == 0


def test_proposals_created_with_sufficient_sample(tmp_db, monkeypatch):
    monkeypatch.setattr(trade_evaluator, "backfill_evaluations",
                        lambda: {"evaluated": 0})
    # 35 profitable trades, same strategy/sector/regime, spread across symbols
    for i in range(35):
        _round_trip(i, ret_pct=6.0 if i % 4 else -2.0, symbol=f"SYM{i % 7}")
    out = adaptive_adjustments.run_learning_cycle()
    assert out["proposals_created"] > 0
    scopes = {(p["scope_type"], p["scope_key"]) for p in out["proposals"]}
    assert ("strategy", "teststrat") in scopes
    for p in out["proposals"]:
        assert abs(p["points"]) <= 3.0            # per-cycle cap
        assert p["sample_size"] >= 15
        assert p["reason"] and p["evidence"]
    # Analysis mode NEVER applies anything:
    assert model_versioning.get_active_version()["version"] == 0
    rows = adaptive_adjustments.get_adjustments()
    assert all(r["status"] == "PROPOSED" for r in rows)


def test_calibration_bands_structure(tmp_db):
    for i in range(20):
        _round_trip(i, ret_pct=5.0 if i % 2 else -3.0, conf=82.0,
                    symbol=f"S{i}")
    bands = adaptive_adjustments.calibration_bands()
    b = next(x for x in bands if x["band"] == "80-89")
    assert b["trades"] == 20
    assert b["actual_success_rate"] == 50.0
    assert b["gap"] == 34.5                       # 84.5 - 50
    assert b["conclusion"] == "Model is overconfident"
    assert b["recommended_correction"] < 0
    score = adaptive_adjustments.calibration_score(bands)
    assert score is not None and 0 <= score <= 100


# ── 5. Out-of-sample validation + approve/reject ─────────────────────────────

def _seed_kb(db, n=200, bad_strategy="losestrat"):
    conn = sqlite3.connect(db)
    conn.execute("""CREATE TABLE IF NOT EXISTS historical_knowledge_trades (
        symbol TEXT, sector TEXT, strategy TEXT, market_regime TEXT,
        exit_date TEXT, holding_days REAL, return_percent REAL, confidence REAL)""")
    base = datetime(2024, 1, 1)
    rows = []
    for i in range(n):
        is_bad = i % 4 == 0                       # 25% of trades: bad strategy
        rows.append((
            f"K{i % 10}", "IT", bad_strategy if is_bad else "goodstrat",
            "Bullish", (base + timedelta(days=i)).strftime("%Y-%m-%d"),
            5.0, -2.5 if is_bad else 1.5, 75.0))
    conn.executemany(
        "INSERT INTO historical_knowledge_trades VALUES (?,?,?,?,?,?,?,?)", rows)
    conn.commit()
    conn.close()


def test_validation_requires_kb(tmp_db):
    v = adaptive_adjustments.validate_proposal(
        {"scope_type": "strategy", "scope_key": "x", "points": -2.0})
    assert v["passed"] is False
    assert "Insufficient historical data" in v["reason"]


def test_validation_passes_for_penalizing_bad_strategy(tmp_db):
    _seed_kb(tmp_db)
    v = adaptive_adjustments.validate_proposal(
        {"scope_type": "strategy", "scope_key": "losestrat", "points": -3.0})
    assert v["passed"] is True
    assert v["proposed_model"]["expectancy"] > v["old_model"]["expectancy"]


def test_validation_rejects_boosting_bad_strategy(tmp_db):
    _seed_kb(tmp_db)
    v = adaptive_adjustments.validate_proposal(
        {"scope_type": "strategy", "scope_key": "losestrat", "points": 3.0})
    assert v["passed"] is False
    assert "worsens" in v["reason"]


def test_approve_flow_creates_version_and_reject_flow(tmp_db):
    _seed_kb(tmp_db)
    conn = adaptive_adjustments._connect()
    conn.execute(
        "INSERT INTO proposed_adjustments (created_at, scope_type, scope_key, "
        "points, size_multiplier, reason, evidence, sample_size, status) "
        "VALUES (?, 'strategy', 'losestrat', -3.0, 0.75, 'test', '{}', 40, "
        "'PROPOSED')", (datetime.now().isoformat(),))
    conn.execute(
        "INSERT INTO proposed_adjustments (created_at, scope_type, scope_key, "
        "points, size_multiplier, reason, evidence, sample_size, status) "
        "VALUES (?, 'strategy', 'goodstrat', 2.0, 1.1, 'test', '{}', 40, "
        "'PROPOSED')", (datetime.now().isoformat(),))
    conn.commit()
    conn.close()
    rows = adaptive_adjustments.get_adjustments()
    ids = {r["scope_key"]: r["id"] for r in rows}

    ok = adaptive_adjustments.approve_adjustment(ids["losestrat"])
    assert ok["success"] and ok["status"] == "APPLIED"
    active = model_versioning.get_active_version()
    assert active["version"] == ok["model_version"]
    assert active["weights"]["strategy|losestrat"] == -3.0

    rj = adaptive_adjustments.reject_adjustment(ids["goodstrat"])
    assert rj["success"] and rj["status"] == "REJECTED"
    assert "strategy|goodstrat" not in model_versioning.get_active_version()["weights"]

    # Double-decide is blocked
    again = adaptive_adjustments.approve_adjustment(ids["losestrat"])
    assert again["success"] is False


# ── 6. Decision safety: adjustment can never create a BUY ────────────────────

def _item(fc=72.0):
    return {"stock": "TCS", "sector": "IT", "error": None,
            "final_confidence": fc, "base_confidence": fc,
            "learning_adjustment": 0.0, "historical_expectancy": 1.5,
            "historical_profit_factor": 1.8, "historical_win_rate": 62.0,
            "historical_trades": 40, "rr_ratio": 2.5, "price": 100.0,
            "filter_passed": True, "live_signal": True,
            "best_strategy_id": "teststrat", "best_strategy_name": "teststrat",
            "best_regime": "Bullish", "entry_price": 100.0,
            "stop_loss": 95.0, "target": 110.0}


@pytest.fixture()
def _decision_env(monkeypatch):
    import market_data_engine, adaptive_learning
    monkeypatch.setattr(market_data_engine, "get_last_source",
                        lambda s: "yfinance")
    monkeypatch.setattr(adaptive_learning, "current_market_regime",
                        lambda: "Bullish")


def test_positive_adjustment_cannot_create_buy(tmp_db, _decision_env):
    # Unadjusted confidence 72 < 75 (BUY bar). +10 boost → 82, still NOT a BUY.
    weights = {"symbol|TCS": 10.0}
    d = decision_service._decide(_item(72.0), {}, [], 50.0,
                                 model_weights=weights, model_version=1)
    assert d["model_adjustment"] == 10.0
    assert d["final_confidence"] == 82.0
    assert d["recommendation"] not in ("BUY", "STRONG_BUY")


def test_unadjusted_buy_still_allowed(tmp_db, _decision_env):
    d = decision_service._decide(_item(78.0), {}, [], 50.0,
                                 model_weights={}, model_version=0)
    assert d["recommendation"] == "BUY"
    assert d["model_adjustment"] == 0.0


def test_negative_adjustment_can_demote_buy(tmp_db, _decision_env):
    weights = {"strategy|teststrat": -10.0}
    d = decision_service._decide(_item(78.0), {}, [], 50.0,
                                 model_weights=weights, model_version=1)
    assert d["model_adjustment"] == -10.0
    assert d["final_confidence"] == 68.0
    assert d["recommendation"] != "BUY"


@pytest.mark.parametrize("reasons,expected", [
    (["Volatility above limit"], "WATCH"),
    (["Volatility above limit", "Volume below minimum"], "AVOID"),
])
def test_risk_filters_remain_non_actionable_with_positive_adjustment(
    tmp_db, _decision_env, reasons, expected,
):
    # Task387: one high-confidence failure is WATCH; two still force AVOID.
    # Neither policy branch may become BUY due to a positive model adjustment.
    item = _item(90.0)
    item["filter_passed"] = False
    item["filter_reasons"] = reasons
    d = decision_service._decide(item, {}, [], 50.0,
                                 model_weights={"symbol|TCS": 15.0},
                                 model_version=1)
    assert d["recommendation"] == expected
