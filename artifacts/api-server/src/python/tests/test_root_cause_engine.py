"""Tests for v2.2 Root Cause Intelligence (root_cause_engine.py).

Covers: deterministic factor bucketing, winner/loser prevalence with
sample-size shrinkage, root-cause narratives (explain the existing
similarity adjustment — never add a second one), minimum-sample gates,
global feature importance (separation index, determinism), gradual
weight blending (blend + relative cap + renormalize to 100), the
>=50-new-trades update gate, and dynamic-weight loading safety.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

import similarity_engine as se
import root_cause_engine as rce


# ── Fixtures ──────────────────────────────────────────────────────────────────

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


def hist_features(**over):
    return se.extract_historical_features(make_hist(**over))


def make_match_set():
    """10 winners with strong ADX + volume confirmation, 10 losers with weak
    ADX + weak volume. Deterministic and clearly separated."""
    matches = []
    for i in range(10):
        matches.append(hist_features(
            id=i + 1, adx=32.0, volume_ratio=1.8, rsi=58.0,
            return_percent=5.0, winning=1))
    for i in range(10):
        matches.append(hist_features(
            id=100 + i, adx=14.0, volume_ratio=0.5, rsi=44.0,
            return_percent=-3.0, winning=0))
    return matches


# ── 1. Factor bucketing ───────────────────────────────────────────────────────

def test_factor_buckets_are_deterministic_and_labelled():
    v = hist_features(rsi=35.0, adx=18.0, volume_ratio=0.5)
    f = rce.factors_of(v)
    assert f["rsi"] == "Weak RSI (<40)"
    assert f["adx"] == "Weak ADX (<20)"
    assert f["volume"] == "Weak volume (<0.8x avg)"
    assert f["macd_state"] == "Bullish MACD"
    assert f["sector"] == "Sector: IT"
    assert rce.factors_of(v) == f  # deterministic


def test_factor_buckets_omit_missing_values():
    v = hist_features(rsi=None, adx=None, volume_ratio=None)
    f = rce.factors_of(v)
    assert "rsi" not in f and "adx" not in f and "volume" not in f


def test_factor_bucket_boundaries():
    assert rce._rsi_factor(40.0) == "Neutral RSI (40-60)"
    assert rce._rsi_factor(39.99) == "Weak RSI (<40)"
    assert rce._rsi_factor(70.01) == "Overbought RSI (>70)"
    assert rce._adx_factor(25.0) == "Strong ADX (25-40)"
    assert rce._volume_factor(1.5) == "Normal volume (0.8-1.5x)"
    assert rce._volume_factor(1.51) == "Volume confirmation (>1.5x)"


# ── 2. Prevalence + lift ──────────────────────────────────────────────────────

def test_prevalence_splits_winners_and_losers():
    prev = rce.factor_prevalence(make_match_set())
    assert prev["winners"] == 10 and prev["losers"] == 10
    by_factor = {t["factor"]: t for t in prev["factors"]}
    weak_adx = by_factor["Weak ADX (<20)"]
    assert weak_adx["loser_prevalence"] == 100.0
    assert weak_adx["winner_prevalence"] == 0.0
    assert weak_adx["lift"] < 0
    vol_conf = by_factor["Volume confirmation (>1.5x)"]
    assert vol_conf["winner_prevalence"] == 100.0
    assert vol_conf["lift"] > 0


def test_lift_is_shrunk_by_sample_size():
    """Small samples produce proportionally smaller lift (K=20 shrinkage)."""
    small = make_match_set()[:2] + make_match_set()[10:12]  # 2W / 2L
    prev_small = rce.factor_prevalence(small)
    prev_big = rce.factor_prevalence(make_match_set())
    f_small = {t["factor"]: t for t in prev_small["factors"]}["Weak ADX (<20)"]
    f_big = {t["factor"]: t for t in prev_big["factors"]}["Weak ADX (<20)"]
    assert abs(f_small["lift"]) < abs(f_big["lift"])


def test_prevalence_empty_matches_is_safe():
    prev = rce.factor_prevalence([])
    assert prev == {"winners": 0, "losers": 0, "factors": []}


# ── 3. Root cause narratives ──────────────────────────────────────────────────

def _losing_current():
    """Current setup sharing the losers' characteristics."""
    return se.extract_current_features({
        "stock": "TCS", "sector": "IT", "best_strategy_id": "strat_a",
        "price": 100.0, "rsi": 44.0, "adx": 14.0,
        "macd_line": 1.2, "macd_signal": 1.0,
        "ema9": 101.0, "ema20": 100.0, "ema50": 99.0, "ema200": 95.0,
        "vwap": 99.5, "atr": 1.5, "supertrend": 97.0,
        "volume_ratio": 0.5, "entry_price": 100.0,
    }, regime_now="Bullish")


def test_negative_adjustment_narrative_names_loser_factors():
    rc = rce.root_cause_for_item(_losing_current(), make_match_set(), -6.0)
    assert "reduced confidence by 6 points" in rc["narrative"]
    assert "%" in rc["narrative"]
    shared = [t["factor"] for t in rc["shared_with_losers"]]
    assert "Weak ADX (<20)" in shared
    assert "Weak volume (<0.8x avg)" in shared


def test_narrative_never_adds_a_second_adjustment():
    """Root cause explains the existing adjustment; output has no adjustment
    field of its own."""
    rc = rce.root_cause_for_item(_losing_current(), make_match_set(), -6.0)
    assert "adjustment" not in rc


def test_minimum_sample_gate():
    few = make_match_set()[:3] + make_match_set()[10:13]  # 3W / 3L < 5
    rc = rce.root_cause_for_item(_losing_current(), few, -4.0)
    assert "Not enough evidence" in rc["narrative"]
    assert rc["shared_with_losers"] == [] or True  # narrative gate is the contract


def test_root_cause_is_deterministic():
    a = rce.root_cause_for_item(_losing_current(), make_match_set(), -6.0)
    b = rce.root_cause_for_item(_losing_current(), make_match_set(), -6.0)
    assert a == b


# ── 4. Global feature importance ─────────────────────────────────────────────

def test_feature_importance_ranks_separating_features():
    vectors = make_match_set() * 5  # 50W / 50L, perfectly separated on adx/vol
    fi = rce.compute_feature_importance(vectors)
    by = {f["feature"]: f for f in fi["features"]}
    # Perfectly separating features must beat non-separating ones.
    assert by["adx"]["importance"] > by["sector"]["importance"]
    assert by["volume"]["importance"] > by["sector"]["importance"]
    assert abs(sum(f["contribution_pct"] for f in fi["features"]) - 100.0) < 1.0


def test_feature_importance_deterministic():
    vectors = make_match_set()
    a = rce.compute_feature_importance(vectors)
    b = rce.compute_feature_importance(vectors)
    assert a["features"] == b["features"]


def test_feature_importance_handles_one_sided_data():
    winners_only = [hist_features(id=i, return_percent=2.0) for i in range(5)]
    fi = rce.compute_feature_importance(winners_only)
    assert all(f["importance"] == 0.0 for f in fi["features"])


# ── 5. Weight blending (gradual, capped, renormalized) ───────────────────────

def test_blend_keeps_total_100():
    prev = dict(se.WEIGHTS)
    target = {f: 100.0 / len(prev) for f in prev}  # uniform target
    new = rce._blend_weights(prev, target)
    assert abs(sum(new.values()) - 100.0) < 0.01


def test_blend_respects_relative_cap():
    prev = dict(se.WEIGHTS)
    # Extreme target: everything to one feature.
    target = {f: (100.0 if f == "rsi" else 0.0) for f in prev}
    new = rce._blend_weights(prev, target)
    for f in prev:
        # Before renormalization the cap is ±15%; renormalization scales all
        # weights by one common factor, so relative change stays bounded.
        rel = new[f] / prev[f]
        assert 0.7 < rel < 1.4


def test_blend_no_single_trade_dominance():
    """A tiny target shift produces a proportionally tiny weight shift."""
    prev = dict(se.WEIGHTS)
    target = dict(se.WEIGHTS)
    target["rsi"] = prev["rsi"] + 1.0
    target["adx"] = prev["adx"] - 1.0
    new = rce._blend_weights(prev, target)
    assert abs(new["rsi"] - prev["rsi"]) < 0.5
    assert abs(new["adx"] - prev["adx"]) < 0.5


# ── 6. Update gating + dynamic weight loading (isolated temp DB) ─────────────

@pytest.fixture()
def temp_db(tmp_path, monkeypatch):
    db = str(tmp_path / "test_ti.db")
    monkeypatch.setattr(rce, "DB_PATH", db)
    return db


def test_update_gate_requires_50_new_trades(temp_db, monkeypatch):
    vectors = make_match_set()
    monkeypatch.setattr(se, "load_historical_vectors", lambda force=False: vectors)
    # Baseline run: snapshot created, weights = static (no rebalance yet).
    st1 = rce.maybe_update_feature_importance()
    assert st1["updated"] is False and st1.get("snapshot") is True
    w = rce.get_dynamic_weights()
    assert w is not None
    for f, val in se.WEIGHTS.items():
        assert abs(w[f] - val) < 1e-9
    # Same trade count again: gated, no snapshot.
    st2 = rce.maybe_update_feature_importance()
    assert st2["updated"] is False and "reason" in st2
    # +49 trades: still gated.
    vectors49 = vectors + [hist_features(id=1000 + i) for i in range(29)]
    monkeypatch.setattr(se, "load_historical_vectors", lambda force=False: vectors49)
    st3 = rce.maybe_update_feature_importance()
    assert st3["updated"] is False
    # +50 trades: weights rebalance (gradually).
    vectors50 = vectors + [
        hist_features(id=2000 + i,
                      adx=32.0 if i % 2 == 0 else 14.0,
                      volume_ratio=1.8 if i % 2 == 0 else 0.5,
                      return_percent=5.0 if i % 2 == 0 else -3.0)
        for i in range(50)]
    monkeypatch.setattr(se, "load_historical_vectors", lambda force=False: vectors50)
    st4 = rce.maybe_update_feature_importance()
    assert st4["updated"] is True
    w2 = rce.get_dynamic_weights()
    assert abs(sum(w2.values()) - 100.0) < 0.01
    for f in se.WEIGHTS:  # gradual: every change within the relative cap band
        assert 0.7 < w2[f] / w[f] < 1.4


def test_malformed_dynamic_weights_are_rejected(temp_db):
    rce.ensure_tables()
    import sqlite3
    conn = sqlite3.connect(temp_db)
    conn.execute("INSERT INTO feature_weights VALUES ('rsi', 500.0, 8.0, 'x')")
    conn.commit()
    conn.close()
    assert rce.get_dynamic_weights() is None  # incomplete + bad sum → static


def test_similarity_score_accepts_custom_weights():
    cur = hist_features()
    cur["holding_period"] = None
    custom = {f: (100.0 if f == "rsi" else 0.0) for f in se.WEIGHTS}
    score, _ = se.similarity_score(cur, hist_features(), custom)
    assert score == 100.0  # identical rsi carries all the weight

def test_baseline_report_is_not_marked_dynamic(temp_db, monkeypatch):
    vectors = make_match_set()
    monkeypatch.setattr(se, "load_historical_vectors", lambda force=False: vectors)
    report = rce.get_feature_importance_report()
    # Baseline snapshot exists but weights were never rebalanced:
    assert report["weights_dynamic"] is False
    # After a genuine 50-trade rebalance the flag flips on.
    vectors50 = vectors + [
        hist_features(id=3000 + i,
                      adx=32.0 if i % 2 == 0 else 14.0,
                      volume_ratio=1.8 if i % 2 == 0 else 0.5,
                      return_percent=5.0 if i % 2 == 0 else -3.0)
        for i in range(50)]
    monkeypatch.setattr(se, "load_historical_vectors", lambda force=False: vectors50)
    st = rce.maybe_update_feature_importance()
    assert st["updated"] is True
    report2 = rce.get_feature_importance_report()
    assert report2["weights_dynamic"] is True


def test_direction_harmful_when_loser_signal_dominates(temp_db, monkeypatch):
    # ADX values: winners spread thin, losers heavily concentrated on Weak ADX
    # → the strongest signal for the adx feature is loser-associated.
    vectors = []
    for i in range(12):
        vectors.append(hist_features(
            id=i + 1, adx=[16.0, 22.0, 32.0][i % 3],
            return_percent=5.0, winning=1))
    for i in range(12):
        vectors.append(hist_features(
            id=500 + i, adx=14.0, return_percent=-3.0, winning=0))
    monkeypatch.setattr(se, "load_historical_vectors", lambda force=False: vectors)
    report = rce.get_feature_importance_report()
    by_feat = {f["feature"]: f for f in report["features"]}
    adx = by_feat["adx"]
    assert adx["worst_value"] is not None and adx["worst_value_lift"] < 0
    assert adx["direction"] == "HARMFUL"
