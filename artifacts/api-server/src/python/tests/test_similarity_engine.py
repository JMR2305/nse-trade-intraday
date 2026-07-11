"""Tests for the v2.1 Evidence-Based Research Engine (similarity_engine.py).

Covers: similarity scoring accuracy (identical / different / partial),
missing-value handling, weight budget, match retrieval (threshold, top-N,
lookahead, dedupe), evidence statistics, reliability tiers + downgrades,
bounded adjustment rules (positive gates, negative gates, low-reliability
never increases), decision-service integration guards (no BUY creation,
5-95 clamp), and determinism.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

import similarity_engine as se


# ── Fixtures ──────────────────────────────────────────────────────────────────

def make_item(**over) -> dict:
    base = {
        "stock": "TCS", "sector": "IT", "best_strategy_id": "strat_a",
        "price": 100.0, "rsi": 55.0, "adx": 30.0,
        "macd_line": 1.2, "macd_signal": 1.0, "macd_hist": 0.2,
        "ema9": 101.0, "ema20": 100.0, "ema50": 99.0, "ema200": 95.0,
        "vwap": 99.5, "atr": 1.5, "supertrend": 97.0,
        "volume_ratio": 1.2, "rr_ratio": 2.0, "expected_holding_days": 10.0,
        "base_confidence": 70.0, "confidence": 70.0,
        "opportunity_score": 60.0, "trade_quality": 55.0,
        "entry_price": 100.0, "stop_loss": 96.0, "target": 108.0,
    }
    base.update(over)
    return base


def make_hist(**over) -> dict:
    base = {
        "id": 1, "symbol": "INFY", "sector": "IT", "strategy": "strat_a",
        "market_regime": "Bullish", "volatility_regime": "NORMAL",
        "holding_days": 12, "rsi": 55.0, "adx": 30.0,
        "macd": 1.2, "macd_signal": 1.0,
        "ema9": 202.0, "ema20": 200.0, "ema50": 198.0, "ema200": 190.0,
        "vwap": 199.0, "atr": 3.0, "supertrend": 194.0,
        "volume_ratio": 1.2, "entry_date": "2025-01-05",
        "exit_date": "2025-01-20", "return_percent": 4.0, "winning": 1,
        "exit_reason": "Target hit", "entry_price": 200.0,
    }
    base.update(over)
    return base


def cur_features(**over):
    return se.extract_current_features(make_item(**over), regime_now="Bullish")


def hist_features(**over):
    return se.extract_historical_features(make_hist(**over))


# ── 1. Similarity scoring ─────────────────────────────────────────────────────

def test_weights_sum_to_100():
    assert abs(sum(se.WEIGHTS.values()) - 100.0) < 1e-9


def test_identical_setup_scores_100():
    # Historical row constructed to mirror the current setup exactly
    # (same ratios: atr% = 1.5%, same EMA ordering, price above vwap/ST).
    c = cur_features()
    h = hist_features(rsi=55.0, adx=30.0, volume_ratio=1.2,
                      atr=3.0, entry_price=200.0)
    score, missing = se.similarity_score(c, h)
    assert missing == []
    assert score == pytest.approx(100.0, abs=0.01)


def test_completely_different_setup_scores_low():
    c = cur_features()
    h = hist_features(
        strategy="strat_z", sector="PHARMA", market_regime="Bearish",
        volatility_regime="HIGH", rsi=5.0, adx=70.0,
        macd=-1.0, macd_signal=1.0,             # bearish MACD state
        ema9=180.0, ema20=190.0, ema50=195.0, ema200=205.0,  # bearish stack
        vwap=250.0, supertrend=260.0,            # price below both
        atr=30.0, volume_ratio=5.0, entry_price=200.0)
    score, _ = se.similarity_score(c, h)
    assert score < 10.0


def test_missing_values_contribute_zero():
    c = cur_features(rsi=None)  # RSI missing on the current setup
    h = hist_features()
    score_missing, missing = se.similarity_score(c, h)
    assert "rsi" in missing
    c_full = cur_features()
    score_full, _ = se.similarity_score(c_full, h)
    assert score_full - score_missing == pytest.approx(se.WEIGHTS["rsi"], abs=0.01)


def test_numeric_similarity_partial_credit():
    # RSI 25 points away on a 50-point scale => half the RSI weight.
    c = cur_features(rsi=55.0)
    h_same = hist_features(rsi=55.0)
    h_off = hist_features(rsi=80.0)
    s_same, _ = se.similarity_score(c, h_same)
    s_off, _ = se.similarity_score(c, h_off)
    assert s_same - s_off == pytest.approx(se.WEIGHTS["rsi"] * 0.5, abs=0.01)


def test_related_regime_gets_partial_credit():
    c = cur_features()  # regime Bullish
    h_exact = hist_features(market_regime="Bullish")
    h_related = hist_features(market_regime="Strong Bullish")
    h_opposite = hist_features(market_regime="Bearish")
    s_exact, _ = se.similarity_score(c, h_exact)
    s_related, _ = se.similarity_score(c, h_related)
    s_opp, _ = se.similarity_score(c, h_opposite)
    assert s_exact > s_related > s_opp
    assert s_exact - s_related == pytest.approx(se.WEIGHTS["regime"] * 0.5, abs=0.01)


def test_determinism_same_inputs_same_output():
    c, h = cur_features(), hist_features()
    assert se.similarity_score(c, h) == se.similarity_score(c, h)


# ── 2. Match retrieval ────────────────────────────────────────────────────────

def test_threshold_and_top_n():
    c = cur_features()
    good = [hist_features(id=i, entry_date=f"2025-0{1 + i % 5}-01",
                          exit_date=f"2025-0{1 + i % 5}-15")
            for i in range(60)]
    bad = [hist_features(id=100 + i, strategy="zzz", sector="PHARMA",
                         market_regime="Bearish", rsi=5.0, adx=80.0,
                         macd=-2.0, macd_signal=2.0, vwap=300.0,
                         supertrend=310.0, atr=40.0, volume_ratio=6.0)
           for i in range(5)]
    matches, _ = se.find_matches(c, good + bad, as_of="2026-07-11")
    assert len(matches) == se.MAX_MATCHES
    assert all(m["similarity"] >= se.MIN_SIMILARITY for m in matches)


def test_lookahead_prevention():
    c = cur_features()
    past = hist_features(id=1, exit_date="2026-07-10")
    today = hist_features(id=2, exit_date="2026-07-11")
    future = hist_features(id=3, exit_date="2026-08-01")
    matches, _ = se.find_matches(c, [past, today, future], as_of="2026-07-11")
    assert [m["id"] for m in matches] == [1]


def test_holding_period_mismatch_is_partial():
    c = cur_features(expected_holding_days=10.0)
    h_ok = hist_features(id=1, holding_days=12)
    h_long = hist_features(id=2, holding_days=60)
    matches, _ = se.find_matches(c, [h_ok, h_long], as_of="2026-07-11")
    by_id = {m["id"]: m for m in matches}
    assert by_id[1]["partial_match"] is False
    assert by_id[2]["partial_match"] is True


# ── 3. Evidence statistics ────────────────────────────────────────────────────

def test_evidence_stats_math():
    matches = [dict(hist_features(id=i), similarity=80.0) for i in range(4)]
    matches[0]["return_percent"] = 10.0
    matches[1]["return_percent"] = 6.0
    matches[2]["return_percent"] = -4.0
    matches[3]["return_percent"] = -2.0
    st = se.evidence_stats(matches)
    assert st["matches"] == 4
    assert st["wins"] == 2 and st["losses"] == 2
    assert st["win_rate"] == 50.0
    assert st["avg_return"] == pytest.approx(2.5)
    assert st["profit_factor"] == pytest.approx(16.0 / 6.0, abs=0.01)
    assert st["expectancy"] == pytest.approx(0.5 * 8.0 + 0.5 * -3.0, abs=0.01)
    assert st["max_favourable_excursion"] == 10.0
    assert st["max_adverse_excursion"] == -4.0


def test_evidence_stats_empty():
    st = se.evidence_stats([])
    assert st["matches"] == 0 and st["profit_factor"] == 0.0


# ── 4. Reliability tiers ──────────────────────────────────────────────────────

def _diverse_matches(n, ret=4.0, sim=85.0):
    out = []
    for i in range(n):
        m = dict(hist_features(
            id=i, symbol=f"SYM{i % 12}",
            entry_date=f"{2024 + i % 2}-{1 + i % 12:02d}-05",
            exit_date=f"{2024 + i % 2}-{1 + i % 12:02d}-20",
            return_percent=ret if i % 4 else -1.0), similarity=sim)
        out.append(m)
    return out


@pytest.mark.parametrize("n,expected", [
    (5, "VERY_LOW"), (12, "LOW"), (25, "MEDIUM"), (60, "HIGH")])
def test_reliability_tiers(n, expected):
    matches = _diverse_matches(n)
    st = se.evidence_stats(matches)
    # Tiering uses the FULL eligible match set, not the top-20 stats sample,
    # so HIGH is reachable with 50+ matches.
    level, _ = se.classify_reliability(st, matches, [])
    assert level == expected


def test_reliability_downgrade_on_concentration():
    matches = [dict(hist_features(id=i, symbol="INFY",
                                  entry_date=f"2024-{1 + i % 12:02d}-05",
                                  return_percent=3.0), similarity=85.0)
               for i in range(25)]
    st = se.evidence_stats(matches)
    level, reasons = se.classify_reliability(st, matches, [])
    assert level == "LOW"
    assert any("concentrated" in r for r in reasons)


def test_reliability_downgrade_on_missing_features():
    matches = _diverse_matches(25)
    st = se.evidence_stats(matches)
    level, reasons = se.classify_reliability(st, matches, ["rsi"])
    assert level == "LOW"
    assert any("missing" in r.lower() for r in reasons)


# ── 5. Confidence adjustment rules ────────────────────────────────────────────

def _stats(matches=25, sim=80.0, exp=1.5, pf=2.0, wr=70.0):
    return {"matches": matches, "avg_similarity": sim, "expectancy": exp,
            "profit_factor": pf, "win_rate": wr}


def test_positive_adjustment_within_bounds():
    adj, expl = se.confidence_adjustment(_stats(), "MEDIUM")
    assert se.MIN_POS_ADJ <= adj <= se.MAX_POS_ADJ
    assert "increased" in expl


def test_positive_adjustment_never_exceeds_cap():
    adj, _ = se.confidence_adjustment(
        _stats(matches=50, sim=100.0, exp=10.0, pf=10.0), "HIGH")
    assert adj == se.MAX_POS_ADJ


def test_low_reliability_never_increases():
    for level in ("LOW", "VERY_LOW"):
        adj, expl = se.confidence_adjustment(_stats(), level)
        assert adj == 0.0
        assert "No confidence increase" in expl


def test_no_positive_below_gates():
    # expectancy below +0.75 gate
    adj, _ = se.confidence_adjustment(_stats(exp=0.5), "HIGH")
    assert adj == 0.0
    # avg similarity below 75 gate
    adj, _ = se.confidence_adjustment(_stats(sim=70.0), "HIGH")
    assert adj == 0.0
    # PF below 1.5 gate
    adj, _ = se.confidence_adjustment(_stats(pf=1.3), "HIGH")
    assert adj == 0.0


def test_negative_adjustment_within_bounds():
    adj, expl = se.confidence_adjustment(
        _stats(exp=-1.0, pf=0.7, wr=30.0), "MEDIUM")
    assert se.MAX_NEG_ADJ <= adj <= se.MIN_NEG_ADJ
    assert "decreased" in expl


def test_negative_adjustment_never_exceeds_cap():
    adj, _ = se.confidence_adjustment(
        _stats(matches=50, sim=95.0, exp=-10.0, pf=0.0, wr=5.0), "HIGH")
    assert adj == se.MAX_NEG_ADJ


def test_insufficient_matches_no_boost_small_penalty_allowed():
    adj, _ = se.confidence_adjustment(
        _stats(matches=6, exp=-1.0, pf=0.5, wr=20.0), "VERY_LOW")
    assert adj == se.SMALL_NEG_ADJ
    adj, _ = se.confidence_adjustment(
        _stats(matches=6, exp=2.0, pf=3.0, wr=80.0), "VERY_LOW")
    assert adj == 0.0


# ── 6. Historical vector cache & dedupe ───────────────────────────────────────

def test_load_historical_vectors_dedupes_and_filters(tmp_path, monkeypatch):
    import sqlite3
    db = str(tmp_path / "test.db")
    monkeypatch.setattr(se, "DB_PATH", db)
    import historical_knowledge_builder as hkb
    monkeypatch.setattr(hkb, "DB_PATH", db, raising=False)
    conn = sqlite3.connect(db)
    conn.execute("""CREATE TABLE historical_knowledge_trades (
        id INTEGER PRIMARY KEY AUTOINCREMENT, symbol TEXT, sector TEXT,
        strategy TEXT, entry_date TEXT, exit_date TEXT, holding_days INTEGER,
        entry_price REAL, exit_price REAL, quantity INTEGER, profit_loss REAL,
        return_percent REAL, winning INTEGER, exit_reason TEXT,
        market_regime TEXT, nifty_trend TEXT, banknifty_trend TEXT,
        volatility_regime TEXT, ema9 REAL, ema20 REAL, ema50 REAL,
        ema200 REAL, rsi REAL, macd REAL, macd_signal REAL, vwap REAL,
        atr REAL, adx REAL, supertrend REAL, volume_ratio REAL,
        opportunity_score REAL, trade_quality REAL, confidence REAL,
        risk_reward REAL, created_at TEXT)""")
    row = ("TCS", "IT", "s1", "2025-01-01", "2025-01-10", 9, 100.0, 104.0,
           1, 4.0, 4.0, 1, "Target", "Bullish", "UP", "UP", "NORMAL",
           101.0, 100.0, 99.0, 95.0, 55.0, 1.0, 0.8, 99.0, 1.5, 30.0,
           97.0, 1.2, 60.0, 55.0, 70.0, 2.0, "2025-01-10")
    cols = ("symbol,sector,strategy,entry_date,exit_date,holding_days,"
            "entry_price,exit_price,quantity,profit_loss,return_percent,"
            "winning,exit_reason,market_regime,nifty_trend,banknifty_trend,"
            "volatility_regime,ema9,ema20,ema50,ema200,rsi,macd,macd_signal,"
            "vwap,atr,adx,supertrend,volume_ratio,opportunity_score,"
            "trade_quality,confidence,risk_reward,created_at")
    ph = ",".join("?" * 34)
    conn.execute(f"INSERT INTO historical_knowledge_trades ({cols}) VALUES ({ph})", row)
    conn.execute(f"INSERT INTO historical_knowledge_trades ({cols}) VALUES ({ph})", row)  # duplicate
    # invalid rows: zero entry price / NULL return
    bad = list(row); bad[6] = 0.0
    conn.execute(f"INSERT INTO historical_knowledge_trades ({cols}) VALUES ({ph})", tuple(bad))
    bad2 = list(row); bad2[10] = None; bad2[3] = "2025-02-01"
    conn.execute(f"INSERT INTO historical_knowledge_trades ({cols}) VALUES ({ph})", tuple(bad2))
    conn.commit(); conn.close()

    se._HIST_CACHE["key"] = None
    vectors = se.load_historical_vectors(force=True)
    assert len(vectors) == 1
    assert vectors[0]["symbol"] == "TCS"
    # cache hit path returns the same object without reloading
    assert se.load_historical_vectors() is vectors


# ── 7. Decision integration guards ────────────────────────────────────────────

def _decision_item(**over):
    item = make_item(
        error=None, final_confidence=72.0, base_confidence=70.0,
        learning_adjustment=2.0, historical_expectancy=1.5,
        historical_profit_factor=1.8, historical_win_rate=60.0,
        historical_trades=30, filter_passed=True, live_signal=True,
        volume_ratio=1.2, similarity_adjustment=8.0,
        evidence_reliability="MEDIUM",
        similarity_evidence={"match_count": 25},
        similarity_explanation="test evidence")
    item.update(over)
    return item


def _run_decide(item):
    import decision_service as ds
    from unittest.mock import patch
    with patch("market_data_engine.get_last_source", return_value="yfinance"), \
         patch("adaptive_learning.current_market_regime", return_value="Bullish"):
        return ds._decide(item, positions={}, trades=[])


def test_similarity_cannot_create_buy_alone():
    # Raw confidence 70 (< BUY 75); +8 similarity pushes it to 78, but the
    # fc_raw guard must keep this at WATCH.
    d = _run_decide(_decision_item(final_confidence=70.0,
                                   similarity_adjustment=8.0))
    assert d["recommendation"] != "BUY" and d["recommendation"] != "STRONG_BUY"
    assert d["similarity_adjustment"] == 8.0


def test_similarity_applies_to_confidence_and_clamps():
    d = _run_decide(_decision_item(final_confidence=92.0,
                                   similarity_adjustment=8.0))
    assert d["final_confidence"] == 95.0  # clamped at 95
    d = _run_decide(_decision_item(final_confidence=10.0,
                                   similarity_adjustment=-15.0))
    assert d["final_confidence"] == 5.0   # clamped at 5


def test_negative_similarity_lowers_confidence():
    d = _run_decide(_decision_item(final_confidence=80.0,
                                   similarity_adjustment=-10.0))
    assert d["final_confidence"] == 70.0
    assert d["evidence_reliability"] == "MEDIUM"
    assert d["similarity_evidence"] == {"match_count": 25}


def test_zero_adjustment_leaves_confidence_untouched():
    d = _run_decide(_decision_item(final_confidence=72.0,
                                   similarity_adjustment=0.0))
    assert d["final_confidence"] == 72.0


# ── 8. Full per-item evidence pipeline ────────────────────────────────────────

def test_evidence_for_item_end_to_end():
    vectors = [hist_features(id=i, symbol=f"SYM{i % 8}",
                             entry_date=f"2024-{1 + i % 12:02d}-05",
                             exit_date=f"2024-{1 + i % 12:02d}-20",
                             return_percent=3.0 if i % 3 else -1.0)
               for i in range(40)]
    ev = se.evidence_for_item(make_item(), vectors,
                              regime_now="Bullish", as_of="2026-07-11")
    # match_count reflects the FULL eligible match set (up to MAX_MATCHES),
    # while performance stats are computed over the top-20 primary sample.
    assert se.PRIMARY_MATCHES <= ev["match_count"] <= se.MAX_MATCHES
    assert ev["stats"]["matches"] <= se.PRIMARY_MATCHES
    assert len(ev["top_matches"]) == se.DISPLAY_MATCHES
    assert ev["reliability"] in ("VERY_LOW", "LOW", "MEDIUM", "HIGH")
    assert ev["safety"] == se.SAFETY_MESSAGE
    # determinism
    ev2 = se.evidence_for_item(make_item(), vectors,
                               regime_now="Bullish", as_of="2026-07-11")
    assert ev == ev2


def test_annotate_items_with_evidence_handles_errors():
    items = [make_item(error="fetch failed"), make_item(error=None)]
    se._HIST_CACHE["key"] = ("test",)
    se._HIST_CACHE["vectors"] = [hist_features(id=i) for i in range(5)]
    try:
        import unittest.mock as um
        with um.patch.object(se, "load_historical_vectors",
                             return_value=se._HIST_CACHE["vectors"]):
            meta = se.annotate_items_with_evidence(items, regime_now="Bullish")
    finally:
        se._HIST_CACHE["key"] = None
        se._HIST_CACHE["vectors"] = []
    assert items[0]["similarity_adjustment"] == 0.0
    assert items[0]["similarity_evidence"] is None
    assert "similarity_evidence" in items[1]
    assert meta["stocks_processed"] == 2
