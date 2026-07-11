"""
Automated tests — v3.0 Portfolio Manager.

Covers:
  - Risk-adjusted ranking prefers better evidence
  - Single-stock cap (max 20% of capital)
  - Sector cap (max 30% of capital, including existing holdings)
  - Max 5 new positions; slots 6-7 only with exceptional confidence (>= 90)
  - Hold cash when nothing beats the quality bar
  - Mock / unavailable data can NEVER receive an allocation
  - Unaffordable prices are skipped with an explanation
  - Holding actions: EXIT / REDUCE / INCREASE / HOLD
  - Persistence + equal-weight benchmark math (portfolio-level learning)
"""

import json
import os
import sys
from datetime import datetime, timedelta

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import portfolio_manager as pm


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture()
def tmp_db(tmp_path, monkeypatch):
    db = str(tmp_path / "test_intel.db")
    monkeypatch.setattr(pm, "DB_PATH", db)
    return db


def make_decision(stock, sector="IT", rec="BUY", conf=80.0, exp=1.5,
                  sharpe=1.2, kelly=12.0, trades=40, price=100.0,
                  regime_match=True, data_status="OK", **extra):
    d = {
        "stock": stock, "sector": sector, "recommendation": rec,
        "data_status": data_status, "price": price,
        "final_confidence": conf, "historical_expectancy": exp,
        "historical_sharpe": sharpe, "historical_kelly": kelly,
        "historical_trades": trades, "historical_win_rate": 60.0,
        "regime_match": regime_match, "expected_drawdown": 3.0,
        "expected_holding_days": 5.0, "stop_loss": price * 0.95,
        "target": price * 1.10, "rr_ratio": 2.0, "model_adjustment": 0.0,
        "reason": "test", "position_open": False,
    }
    d.update(extra)
    return d


EMPTY_STATE = {"cash": 5000.0, "positions": {}}


def plan_of(decisions, state=None, regime="Strong Bull", strength=80.0):
    return pm.build_portfolio_plan(decisions, state or dict(EMPTY_STATE),
                                   regime=regime, regime_strength=strength)


# ── Ranking ───────────────────────────────────────────────────────────────────

def test_risk_adjusted_score_prefers_better_evidence():
    strong = pm.risk_adjusted_score(make_decision("A", conf=90, exp=2.5,
                                                  sharpe=2.0, kelly=20, trades=60))
    weak = pm.risk_adjusted_score(make_decision("B", conf=55, exp=0.2,
                                                sharpe=0.1, kelly=2, trades=5,
                                                regime_match=False))
    assert strong > weak
    assert 0.0 <= weak <= 100.0 and 0.0 <= strong <= 100.0


def test_top_ranked_candidate_gets_capital_first():
    decisions = [
        make_decision("WEAK", conf=62, exp=0.6, sharpe=0.4, kelly=4, trades=12),
        make_decision("BEST", conf=92, exp=2.5, sharpe=2.0, kelly=20, trades=60),
    ]
    plan = plan_of(decisions)
    assert plan["new_buys"], "expected at least one buy"
    assert plan["new_buys"][0]["symbol"] == "BEST"


# ── Hard caps ─────────────────────────────────────────────────────────────────

def test_single_stock_cap_20_percent():
    d = make_decision("A", conf=99, exp=3.0, sharpe=2.5, kelly=80.0, trades=100)
    plan = plan_of([d])
    buy = plan["new_buys"][0]
    assert buy["allocation"] <= 0.20 * plan["total_capital"] + 1e-6


def test_sector_cap_30_percent_including_holdings():
    # Existing IT holding worth 1000 of 5000 total (20%). New IT buys may only
    # add up to 10% more => <= 500.
    state = {"cash": 4000.0, "positions": {"HOLD1": {"quantity": 10, "avg_price": 100.0}}}
    decisions = [
        make_decision("HOLD1", sector="IT", rec="HOLD", price=100.0),
        make_decision("IT_A", sector="IT", conf=95, kelly=40, price=50.0),
        make_decision("IT_B", sector="IT", conf=94, kelly=40, price=50.0),
        make_decision("IT_C", sector="IT", conf=93, kelly=40, price=50.0),
    ]
    plan = plan_of(decisions, state)
    it_new = sum(b["allocation"] for b in plan["new_buys"] if b["sector"] == "IT")
    assert it_new <= 0.30 * plan["total_capital"] - 1000.0 + 1e-6
    # something must have been skipped for the sector cap once room ran out
    reasons = " ".join(s["reason"] for s in plan["skipped"])
    assert "sector" in reasons.lower()


def test_max_five_new_positions():
    decisions = [make_decision(f"S{i}", sector=f"SEC{i}", conf=85, price=30.0)
                 for i in range(8)]
    plan = plan_of(decisions)
    assert len(plan["new_buys"]) == 5
    reasons = " ".join(s["reason"] for s in plan["skipped"])
    assert "5 new positions" in reasons


def test_exceptional_confidence_unlocks_slots_6_and_7():
    decisions = [make_decision(f"S{i}", sector=f"SEC{i}", conf=95, exp=2.5,
                               sharpe=2.0, kelly=18, trades=60, price=20.0)
                 for i in range(8)]
    plan = plan_of(decisions)
    assert 5 < len(plan["new_buys"]) <= pm.MAX_NEW_EXCEPTIONAL


# ── Cash discipline ───────────────────────────────────────────────────────────

def test_hold_cash_when_nothing_qualifies():
    decisions = [
        make_decision("A", rec="WATCH"),
        make_decision("B", rec="AVOID"),
        make_decision("C", conf=40, exp=-0.5, sharpe=-0.5, kelly=0, trades=3,
                      regime_match=False),  # BUY but below quality bar
    ]
    plan = plan_of(decisions)
    assert plan["new_buys"] == []
    assert plan["stance"] == "HOLD_CASH"
    assert plan["cash_pct"] == 100.0
    low = [s for s in plan["skipped"] if s["symbol"] == "C"]
    assert low and "quality bar" in low[0]["reason"]


def test_mock_or_unavailable_data_never_bought():
    decisions = [
        make_decision("MOCKED", conf=99, exp=3.0, data_status="DATA_UNAVAILABLE"),
        make_decision("MOCK2", conf=99, exp=3.0, data_status="MOCK"),
    ]
    plan = plan_of(decisions)
    assert plan["new_buys"] == []
    assert plan["stance"] == "HOLD_CASH"


def test_unaffordable_price_skipped_with_reason():
    decisions = [make_decision("PRICEY", conf=92, exp=2.0, price=12000.0)]
    plan = plan_of(decisions)  # 20% of 5000 = 1000 < 12000/share
    assert plan["new_buys"] == []
    row = [s for s in plan["skipped"] if s["symbol"] == "PRICEY"][0]
    assert "Cannot size a position" in row["reason"]


# ── Holding actions ───────────────────────────────────────────────────────────

def test_holding_actions_exit_reduce_increase_hold():
    state = {"cash": 2000.0, "positions": {
        "EXITME": {"quantity": 5, "avg_price": 100.0},
        "BIG":    {"quantity": 12, "avg_price": 100.0},   # 1200/5000 = 24% > 20%
        "ADDME":  {"quantity": 3, "avg_price": 100.0},    # 6% < 10%, STRONG_BUY
        "KEEP":   {"quantity": 5, "avg_price": 100.0},
    }}
    decisions = [
        make_decision("EXITME", sector="AUTO", rec="EXIT", price=100.0,
                      exit_reason="Stop loss hit"),
        make_decision("BIG", sector="BANK", rec="HOLD", price=100.0),
        make_decision("ADDME", sector="PHARMA", rec="STRONG_BUY", conf=88, price=100.0),
        make_decision("KEEP", sector="FMCG", rec="HOLD", price=100.0),
    ]
    plan = plan_of(decisions, state)
    actions = {h["symbol"]: h["action"] for h in plan["holdings"]}
    assert actions["EXITME"] == "EXIT"
    assert actions["BIG"] == "REDUCE"
    assert actions["ADDME"] == "INCREASE"
    assert actions["KEEP"] == "HOLD"
    assert plan["exits"] and plan["exits"][0]["symbol"] == "EXITME"


def test_metrics_and_sector_exposure_present():
    plan = plan_of([make_decision("A", sector="IT"),
                    make_decision("B", sector="BANK")])
    m = plan["metrics"]
    for key in ("portfolio_confidence", "expected_monthly_return_pct",
                "expected_max_drawdown_pct", "diversification_score",
                "risk_score", "new_positions_count"):
        assert key in m
    assert plan["sector_exposure"]
    assert all(se["pct"] <= 30.0 + 1e-6 for se in plan["sector_exposure"]
               if se["sector"] not in ("CASH",))
    assert plan["summary"]
    assert all(b["rationale"] for b in plan["new_buys"])


# ── Persistence + equal-weight benchmark learning ────────────────────────────

def test_persist_and_benchmark_math(tmp_db, monkeypatch):
    decisions = [
        make_decision("AAA", sector="IT", conf=90, kelly=20, price=100.0),
        make_decision("BBB", sector="BANK", conf=60, exp=0.6, sharpe=0.3,
                      kelly=3, trades=8, price=100.0),
    ]
    plan = plan_of(decisions)
    plan_id = pm.persist_decision(plan)
    assert plan_id > 0

    # Make the row "old enough" to be evaluated.
    with pm._connect() as conn:
        old = (datetime.now() - timedelta(days=10)).isoformat()
        conn.execute("UPDATE portfolio_decisions SET created_at = ? WHERE id = ?",
                     (old, plan_id))
        conn.commit()

    # AAA +10%, BBB -2% — all from verified live data.
    fake = {"AAA": 10.0, "BBB": -2.0}
    monkeypatch.setattr(pm, "_symbol_return", lambda s, t: fake.get(s))

    results = pm.evaluate_matured_decisions()
    assert len(results) == 1
    ev = results[0]

    total = plan["total_capital"]
    expected_ai = sum((b["allocation"] / total) * fake[b["symbol"]]
                      for b in plan["new_buys"])
    candidates = {b["symbol"] for b in plan["new_buys"]} | {
        s["symbol"] for s in plan["skipped"]}
    expected_ew = sum(fake[s] for s in candidates) / len(candidates)

    assert ev["ai_return_pct"] == pytest.approx(expected_ai, abs=1e-3)
    assert ev["equal_weight_return_pct"] == pytest.approx(expected_ew, abs=1e-3)
    assert ev["alpha_pct"] == pytest.approx(expected_ai - expected_ew, abs=1e-3)

    perf = pm.allocation_performance()
    assert perf["evaluated_count"] == 1
    assert perf["verdict"]

    recent = pm.recent_decisions()
    assert recent and recent[0]["evaluated"] is True


def test_mock_data_defers_benchmark_evaluation(tmp_db, monkeypatch):
    plan = plan_of([make_decision("AAA", conf=90, price=100.0),
                    make_decision("BBB", sector="BANK", conf=88, price=100.0)])
    plan_id = pm.persist_decision(plan)
    with pm._connect() as conn:
        old = (datetime.now() - timedelta(days=10)).isoformat()
        conn.execute("UPDATE portfolio_decisions SET created_at = ? WHERE id = ?",
                     (old, plan_id))
        conn.commit()

    # Every symbol is on mock data -> _symbol_return returns None -> defer.
    monkeypatch.setattr(pm, "_symbol_return", lambda s, t: None)
    assert pm.evaluate_matured_decisions() == []
    with pm._connect() as conn:
        row = conn.execute("SELECT evaluated FROM portfolio_decisions WHERE id = ?",
                           (plan_id,)).fetchone()
    assert row["evaluated"] == 0  # still pending — never learned from mock
