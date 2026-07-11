"""Tests for the v2.3 Analyst Reasoning and Decision Invalidation Layer."""

import re
from datetime import datetime

import pytest

import analyst_reasoning as ar


# ── Fixtures ──────────────────────────────────────────────────────────────────

def make_item(**over) -> dict:
    item = {
        "stock": "TESTX",
        "sector": "IT",
        "price": 100.0,
        "rsi": 58.0,
        "macd_hist": 0.4,
        "volume_ratio": 1.3,
        "ema20": 96.0,
        "ema50": 92.0,
        "above_ema20": True,
        "above_ema50": True,
        "supertrend_dir": "up",
        "volatility": 14.0,
        "sector_rank": 2,
        "opportunity_score": 68.0,
        "error": None,
    }
    item.update(over)
    return item


def make_decision(**over) -> dict:
    d = {
        "stock": "TESTX",
        "sector": "IT",
        "recommendation": "BUY",
        "data_status": "OK",
        "low_reliability": False,
        "final_confidence": 78.0,
        "price": 100.0,
        "stop_loss": 94.0,
        "target": 115.0,
        "rr_ratio": 2.5,
        "position_open": False,
        "position_quantity": 0,
        "position_avg_price": 0.0,
        "position_pnl_pct": 0.0,
        "reason": "Confidence 78, expectancy +1.40%, PF 1.80, R:R 2.5:1",
        "evidence_reliability": "MEDIUM",
        "similarity_evidence": {
            "match_count": 24,
            "avg_similarity": 82.0,
            "stats": {
                "win_rate": 62.5,
                "expectancy": 1.4,
                "profit_factor": 1.8,
                "avg_return": 1.1,
                "max_adverse_excursion": -3.2,
                "avg_holding_days": 6.0,
            },
        },
        "explanation_sections": {
            "technical": {
                "technical_score": 70.0,
                "opportunity_score": 68.0,
                "risk_filters_passed": True,
                "risk_filter_notes": [],
                "trend": "Above EMA20, above EMA50, supertrend UP",
                "momentum": "RSI 58, MACD histogram +0.40",
                "volume": "1.3× 20-day average volume",
            },
            "similarity": {
                "match_count": 24,
                "avg_similarity": 82.0,
                "win_rate": 62.5,
                "expectancy": 1.4,
                "profit_factor": 1.8,
                "adjustment": 4.0,
                "reliability": "MEDIUM",
                "text": "",
            },
            "pattern": {
                "strategy": "Trend Rider",
                "sector": "IT",
                "regime": "Bullish",
                "expectancy": 1.2,
                "profit_factor": 1.6,
                "sample_size": 30,
                "note": "descriptive only",
            },
            "summary": {
                "technical_confidence": 70.0,
                "learning_adjustment": 2.0,
                "model_adjustment": 2.0,
                "similarity_adjustment": 4.0,
                "pattern_adjustment": 0.0,
                "final_confidence": 78.0,
                "recommendation": "BUY",
                "learning_note": None,
            },
        },
    }
    d.update(over)
    return d


NOW = datetime(2026, 7, 10, 11, 0, 0)  # Friday 11:00 IST


def build(decision=None, item=None, regime="Bullish", now=NOW):
    return ar.build_analyst_view(decision or make_decision(),
                                 item or make_item(), regime, now=now)


# ── Structure and determinism ────────────────────────────────────────────────

REQUIRED_KEYS = {
    "analyst_summary", "current_observation", "historical_assessment",
    "decision_reasoning", "invalidation_conditions", "upgrade_conditions",
    "invalidation_met", "upgrade_met", "decision_state",
    "decision_timestamp", "valid_until", "validity_note",
    "conflict_level", "conflict_explanation", "missing_data_fields",
}


def test_all_fields_present():
    view = build()
    assert REQUIRED_KEYS.issubset(view.keys())


def test_deterministic_same_inputs_same_output():
    assert build() == build()


def test_condition_shape():
    view = build()
    for c in view["invalidation_conditions"] + view["upgrade_conditions"]:
        assert set(c.keys()) == {"metric", "current_value", "trigger_value",
                                 "direction", "why", "met"}
        assert isinstance(c["met"], bool)
        assert c["why"]  # every condition explains why it matters


# ── Source attribution / no invented facts ───────────────────────────────────

def test_historical_assessment_uses_similarity_numbers_only():
    view = build()
    txt = view["historical_assessment"]
    assert "24" in txt and "82%" in txt
    assert "62%" in txt or "63%" in txt  # win rate
    assert "+1.40%" in txt
    # Pattern-knowledge numbers must NOT leak into section B
    assert "30 trades" not in txt


def test_historical_assessment_without_evidence():
    d = make_decision(similarity_evidence=None)
    view = build(decision=d)
    assert "No sufficiently similar" in view["historical_assessment"]


def test_decision_reasoning_names_sources():
    view = build()
    txt = view["decision_reasoning"]
    assert "historical similarity evidence" in txt
    assert "adaptive learning" in txt
    assert "did not affect the confidence" in txt  # pattern disclaimer
    assert "BUY" in txt


def test_no_unsupported_causal_claims():
    view = build()
    joined = " ".join([view["analyst_summary"], view["current_observation"],
                       view["historical_assessment"],
                       view["decision_reasoning"]])
    for banned in ("will rise", "will fall", "guaranteed", "proves that",
                   "caused the price"):
        assert banned not in joined.lower()


# ── Section A ─────────────────────────────────────────────────────────────────

def test_current_observation_content():
    view = build()
    txt = view["current_observation"]
    assert "TESTX" in txt
    assert "Above EMA20" in txt
    assert "Market regime: Bullish" in txt
    assert "2.5:1" in txt
    assert "verified live NSE data" in txt
    assert "No open position" in txt


# ── Section D + decision state ───────────────────────────────────────────────

def test_healthy_buy_is_valid():
    view = build()
    assert view["decision_state"] == "VALID"
    assert view["invalidation_met"] == 0


def test_stop_loss_breach_invalidates_buy():
    d = make_decision(price=93.0)
    it = make_item(price=93.0)
    view = build(decision=d, item=it)
    assert view["decision_state"] == "INVALIDATED"
    stop_cond = next(c for c in view["invalidation_conditions"]
                     if c["metric"] == "Price vs stop-loss")
    assert stop_cond["met"] is True


def test_partial_deterioration_weakens_buy():
    it = make_item(macd_hist=-0.2)  # single downside trigger met
    view = build(item=it)
    assert view["decision_state"] == "WEAKENING"
    assert view["invalidation_met"] == 1


def test_watch_with_most_upgrades_met_is_improving():
    d = make_decision(recommendation="WATCH", final_confidence=76.0)
    view = build(decision=d)
    # Fixture setup already meets nearly all upgrade conditions
    assert view["decision_state"] == "IMPROVING"
    assert view["upgrade_met"] >= 3


def test_weak_watch_stays_valid():
    d = make_decision(recommendation="WATCH", final_confidence=58.0)
    it = make_item(rsi=35.0, macd_hist=-0.5, volume_ratio=0.5,
                   above_ema20=False, above_ema50=False,
                   opportunity_score=30.0)
    view = build(decision=d, item=it, regime="Bearish")
    assert view["decision_state"] == "VALID"


def test_upgrade_conditions_have_numeric_triggers():
    d = make_decision(recommendation="WATCH")
    it = make_item(above_ema20=False, above_ema50=False, rsi=38.0)
    view = build(decision=d, item=it)
    metrics = {c["metric"] for c in view["upgrade_conditions"]}
    assert "Price vs EMA20" in metrics and "RSI" in metrics
    ema = next(c for c in view["upgrade_conditions"]
               if c["metric"] == "Price vs EMA20")
    assert "₹96.00" in ema["trigger_value"]
    assert ema["met"] is False


def test_exit_gets_reversal_conditions():
    d = make_decision(recommendation="EXIT", position_open=True,
                      position_quantity=5, position_avg_price=98.0,
                      final_confidence=40.0,
                      reason="Stop-loss hit")
    it = make_item(macd_hist=-0.3, above_ema20=False)
    view = build(decision=d, item=it)
    assert view["valid_until"] is None
    assert "position is closed" in view["validity_note"]
    metrics = {c["metric"] for c in view["upgrade_conditions"]}
    assert "Final confidence" in metrics


# ── Validity window / expiry ─────────────────────────────────────────────────

def test_valid_until_is_next_close_same_day_before_close():
    view = build(now=datetime(2026, 7, 10, 11, 0, 0))  # Friday morning
    assert view["valid_until"] == "2026-07-10T15:30:00"
    assert view["validity_note"] == "Valid until next daily close"


def test_valid_until_skips_weekend_after_close():
    view = build(now=datetime(2026, 7, 10, 16, 0, 0))  # Friday after close
    assert view["valid_until"] == "2026-07-13T15:30:00"  # Monday


def test_next_daily_close_weekend():
    sat = datetime(2026, 7, 11, 10, 0, 0)
    assert ar.next_daily_close(sat) == datetime(2026, 7, 13, 15, 30, 0)


# ── DATA_LIMITED ─────────────────────────────────────────────────────────────

def test_data_limited_state_and_missing_fields():
    d = make_decision(data_status="DATA_UNAVAILABLE", recommendation="WATCH",
                      final_confidence=40.0)
    it = make_item(error="fetch failed")
    view = build(decision=d, item=it)
    assert view["decision_state"] == "DATA_LIMITED"
    assert view["valid_until"] is None
    assert view["validity_note"] == "Re-evaluation required"
    assert "live price" in view["missing_data_fields"]
    assert any("fetch failed" in m for m in view["missing_data_fields"])
    assert "provisional" in view["current_observation"]


# ── Conflict detection ───────────────────────────────────────────────────────

def test_no_conflict_on_aligned_evidence():
    view = build()
    assert view["conflict_level"] == "NONE"
    assert view["conflict_explanation"] == ""


def test_conflict_technical_positive_similarity_negative():
    d = make_decision()
    d["explanation_sections"]["similarity"]["expectancy"] = -1.2
    d["explanation_sections"]["similarity"]["match_count"] = 25
    view = build(decision=d)
    assert view["conflict_level"] == "HIGH"  # MEDIUM reliability evidence
    assert "negative expectancy" in view["conflict_explanation"]


def test_conflict_pattern_positive_technicals_weak():
    d = make_decision(recommendation="AVOID", final_confidence=40.0)
    d["explanation_sections"]["technical"]["technical_score"] = 35.0
    d["explanation_sections"]["technical"]["risk_filters_passed"] = False
    d["explanation_sections"]["summary"]["technical_confidence"] = 35.0
    view = build(decision=d)
    assert view["conflict_level"] in ("LOW", "MEDIUM")
    assert "Pattern Knowledge" in view["conflict_explanation"]


def test_conflict_high_confidence_thin_history():
    d = make_decision(low_reliability=True, final_confidence=80.0)
    view = build(decision=d)
    assert view["conflict_level"] in ("MEDIUM", "HIGH")
    assert "thin" in view["conflict_explanation"] \
        or "limited evidence" in view["conflict_explanation"]


def test_conflict_expectancy_good_rr_bad():
    d = make_decision(rr_ratio=1.2)
    view = build(decision=d)
    assert view["conflict_level"] in ("MEDIUM", "HIGH")
    assert "risk/reward" in view["conflict_explanation"].lower()


def test_conflict_weak_sector():
    d = make_decision()
    it = make_item(sector_rank=7)
    view = build(decision=d, item=it)
    assert view["conflict_level"] != "NONE"
    assert "sector" in view["conflict_explanation"].lower()


# ── Analyst summary ──────────────────────────────────────────────────────────

def test_summary_word_cap_and_format():
    view = build()
    s = view["analyst_summary"]
    assert len(s.split()) <= 120
    for label in ("Recommendation:", "Confidence:", "Primary reason:",
                  "Historical evidence:", "Main risk:",
                  "What would change the decision:"):
        assert label in s


def test_summary_word_cap_extreme():
    d = make_decision(reason="x" * 5 + " word" * 200)
    view = build(decision=d)
    assert len(view["analyst_summary"].split()) <= 120


# ── No contradiction across sections ─────────────────────────────────────────

def test_sections_agree_on_recommendation_and_confidence():
    view = build()
    assert "BUY" in view["analyst_summary"]
    assert "78" in view["analyst_summary"]
    assert "78" in view["decision_reasoning"]
    # Section B expectancy sign must match what section C reports as support
    assert "+1.4" in view["historical_assessment"]
    assert "historical similarity evidence (+4.0)" in view["decision_reasoning"]
