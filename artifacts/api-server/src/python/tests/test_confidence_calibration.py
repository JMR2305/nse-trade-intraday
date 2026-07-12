"""Unit tests for the Phase 1 confidence calibration engine."""
import os
import sys
import json
import math
import random
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import confidence_calibration as cc


def _synthetic_samples(n=400, seed=7):
    """Overconfident model: true win prob = conf/200 (half the stated one)."""
    rng = random.Random(seed)
    out = []
    for _ in range(n):
        conf = rng.uniform(5, 95)
        p_true = conf / 200.0
        out.append((conf, 1 if rng.random() < p_true else 0))
    return out


def test_fit_auto_method_selection():
    big = _synthetic_samples(150)
    assert cc.fit_calibrator(big)["method"] == "isotonic"
    small = _synthetic_samples(40)
    assert cc.fit_calibrator(small)["method"] == "platt"
    tiny = _synthetic_samples(10)
    assert cc.fit_calibrator(tiny)["method"] == "identity"
    empty = cc.fit_calibrator([])
    assert empty["method"] == "identity"
    assert empty["n_samples"] == 0


def test_apply_calibration_always_in_unit_interval():
    for method in ("auto", "platt", "isotonic"):
        cal = cc.fit_calibrator(_synthetic_samples(200), method=method)
        for conf in (-50, 0, 1, 33.3, 50, 77, 95, 100, 150):
            p = cc.apply_calibration(cal, conf)
            assert 0.0 <= p <= 1.0, f"{method} conf={conf} -> {p}"
    # identity / missing calibrator
    assert cc.apply_calibration(None, 55) == 0.55
    assert cc.apply_calibration(None, 250) == 1.0
    assert cc.apply_calibration(None, -10) == 0.0


def test_isotonic_is_monotone():
    cal = cc.fit_calibrator(_synthetic_samples(300), method="isotonic")
    prev = -1.0
    for conf in range(0, 101, 2):
        p = cc.apply_calibration(cal, conf)
        assert p >= prev - 1e-9, f"not monotone at conf={conf}"
        prev = p


def test_calibration_improves_overconfident_model():
    train = _synthetic_samples(600, seed=1)
    test = _synthetic_samples(400, seed=2)
    cal = cc.fit_calibrator(train)
    raw_probs = [c / 100.0 for c, _ in test]
    cal_probs = [cc.apply_calibration(cal, c) for c, _ in test]
    ys = [y for _, y in test]
    assert cc.brier_score(cal_probs, ys) < cc.brier_score(raw_probs, ys)
    assert cc.expected_calibration_error(cal_probs, ys) < \
        cc.expected_calibration_error(raw_probs, ys)


def test_metrics_known_values():
    # Perfect predictions
    assert cc.brier_score([1.0, 0.0], [1, 0]) == 0.0
    # 50/50 predictions
    assert abs(cc.brier_score([0.5, 0.5], [1, 0]) - 0.25) < 1e-9
    # log loss of 0.5 predictions = ln(2)
    assert abs(cc.log_loss([0.5, 0.5], [1, 0]) - math.log(2)) < 1e-6
    # ECE 0 for perfectly calibrated single bin
    probs = [0.75] * 4
    ys = [1, 1, 1, 0]
    assert cc.expected_calibration_error(probs, ys) == 0.0
    # empty inputs
    assert cc.brier_score([], []) == 0.0
    assert cc.log_loss([], []) == 0.0
    assert cc.expected_calibration_error([], []) == 0.0


def test_reliability_diagram_bins():
    probs = [0.05, 0.15, 0.95, 1.0]
    ys = [0, 1, 1, 1]
    diag = cc.reliability_diagram(probs, ys, bins=10)
    assert len(diag) == 10
    assert diag[0]["count"] == 1          # 0.05
    assert diag[1]["count"] == 1          # 0.15
    assert diag[9]["count"] == 2          # 0.95 and 1.0 (last bin inclusive)
    assert sum(b["count"] for b in diag) == 4


def test_calibrate_prediction_record_shape():
    cal = cc.fit_calibrator(_synthetic_samples(200))
    cal["version"] = 3
    rec = cc.calibrate_prediction(cal, 72.4)
    assert rec["raw_confidence"] == 72.4
    assert 0.0 <= rec["calibrated_probability"] <= 1.0
    assert rec["calibrated_confidence"] == round(rec["calibrated_probability"] * 100, 1)
    assert rec["calibration_method"] == cal["method"]
    assert rec["calibration_version"] == 3
    # No calibrator -> identity fallback
    rec2 = cc.calibrate_prediction(None, 60)
    assert rec2["calibration_method"] == "identity"
    assert rec2["calibrated_probability"] == 0.6


def test_persistence_and_versioning(tmp_path=None):
    tmp = tempfile.mkdtemp()
    old_path = cc.STATE_PATH
    cc.STATE_PATH = os.path.join(tmp, "calibration_state.json")
    try:
        cal = cc.fit_calibrator(_synthetic_samples(200))
        saved1 = cc.save_calibrator(cal)
        assert saved1["version"] == 1
        saved2 = cc.save_calibrator(cal)
        assert saved2["version"] == 2
        loaded = cc.load_active_calibrator()
        assert loaded["version"] == 2
        assert loaded["method"] == cal["method"]
        with open(cc.STATE_PATH) as f:
            state = json.load(f)
        assert state["active"]["version"] == 2
    finally:
        cc.STATE_PATH = old_path


def test_training_samples_no_lookahead():
    samples_all = cc.training_samples_from_knowledge()
    if not samples_all:  # DB may be empty in some environments
        return
    cutoff = "2026-01-01"
    samples_cut = cc.training_samples_from_knowledge(as_of=cutoff)
    assert len(samples_cut) < len(samples_all)
    # verify directly against the DB
    import sqlite3
    conn = sqlite3.connect(cc.DB_PATH)
    n_expected = conn.execute(
        "SELECT COUNT(*) FROM historical_knowledge_trades WHERE confidence "
        "IS NOT NULL AND exit_date IS NOT NULL AND exit_date != '' AND "
        "substr(exit_date, 1, 10) < ?", (cutoff,)).fetchone()[0]
    conn.close()
    assert len(samples_cut) == n_expected


def test_calibration_report_shapes():
    train = _synthetic_samples(300)
    cal = cc.fit_calibrator(train)
    confs = [c for c, _ in train]
    ys = [y for _, y in train]
    rep = cc.calibration_report(confs, ys, cal)
    assert rep["samples"] == len(train)
    assert set(rep["before"].keys()) == {"brier_score", "ece", "log_loss"}
    assert set(rep["after"].keys()) == {"brier_score", "ece", "log_loss"}
    assert len(rep["reliability_raw"]) == 10
    assert len(rep["reliability_calibrated"]) == 10
    assert rep["safety"]

    rep2 = cc.calibration_report_from_pairs(
        confs, [cc.apply_calibration(cal, c) for c in confs], ys,
        method=cal["method"], version=9)
    assert rep2["calibration_version"] == 9
    assert rep2["after"]["brier_score"] == rep["after"]["brier_score"]


def test_decision_service_calibration_fields():
    from decision_service import _calibration_fields
    f = _calibration_fields(70.0)
    for k in ("raw_confidence", "calibrated_probability", "calibrated_confidence",
              "calibration_method", "calibration_version"):
        assert k in f, f"missing {k}"
    assert f["raw_confidence"] == 70.0
    assert 0.0 <= f["calibrated_probability"] <= 1.0


def test_portfolio_manager_uses_calibrated_confidence():
    from portfolio_manager import _effective_confidence, target_fraction
    d_raw = {"final_confidence": 90.0, "historical_kelly": 10.0}
    d_cal = {"final_confidence": 90.0, "calibrated_confidence": 45.0,
             "historical_kelly": 10.0}
    assert _effective_confidence(d_raw) == 90.0
    assert _effective_confidence(d_cal) == 45.0
    # calibrated (lower) confidence must shrink the position size
    assert target_fraction(d_cal) < target_fraction(d_raw)


def test_signal_quality_calibrated_floor():
    from signal_quality import strict_filter_check
    base = dict(opportunity_score=60, confidence=60, rr_ratio=2.5,
                sector_rank=1, regime="Bullish", above_ema20=True,
                above_ema50=True, volume_ratio=1.2, perf_score=70,
                total_trades=40)
    ok, reasons = strict_filter_check(**base, calibrated_probability=0.5)
    assert ok, reasons
    bad, reasons = strict_filter_check(**base, calibrated_probability=0.1)
    assert not bad
    assert any("Calibrated win probability" in r for r in reasons)
    # None (no calibrator) -> floor not applied
    ok2, _ = strict_filter_check(**base, calibrated_probability=None)
    assert ok2


def test_walk_forward_entry_gate_uses_calibrated_floor():
    from walk_forward_validator import _passes_entry_gate

    class Cfg:
        min_confidence_execute = 55.0
        min_calibrated_prob = 0.30

    cfg = Cfg()
    # Variant C: calibrated probability below the floor blocks the trade
    assert not _passes_entry_gate("C", 80.0, 0.10, cfg)
    # ... and at/above the floor it passes
    assert _passes_entry_gate("C", 80.0, 0.30, cfg)
    assert _passes_entry_gate("C", 80.0, 0.75, cfg)
    # Raw-confidence floor still applies even with a good calibrated prob
    assert not _passes_entry_gate("C", 40.0, 0.75, cfg)
    # Variant B (no calibrator -> cal_p None): behavior unchanged, raw floor only
    assert _passes_entry_gate("B", 60.0, None, cfg)
    assert not _passes_entry_gate("B", 40.0, None, cfg)
    # Variant A: no confidence gate at all
    assert _passes_entry_gate("A", 5.0, None, cfg)


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for fn in fns:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"FAIL {fn.__name__}: {e}")
        except Exception as e:
            failed += 1
            print(f"ERROR {fn.__name__}: {e}")
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    sys.exit(1 if failed else 0)
