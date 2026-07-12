"""
Confidence Calibration Engine (Phase 1)
=======================================

Maps raw model confidence (0-100) to a calibrated win PROBABILITY (0-1)
learned from completed historical trades, so that "70% confidence" actually
wins ~70% of the time.

Methods (pure python — no external ML dependencies):
  • isotonic  — Pool-Adjacent-Violators (PAV) monotonic regression.
                Used when >= ISOTONIC_MIN_SAMPLES samples are available.
  • platt     — logistic (sigmoid) scaling fit with Newton-Raphson.
                Used when >= PLATT_MIN_SAMPLES samples are available.
  • identity  — raw/100 fallback when there is not enough data. The method
                name is always reported so downstream consumers know whether
                the probability is actually calibrated.

Every prediction produced through this module carries:
  raw_confidence          (0-100, unchanged)
  calibrated_probability  (0-1)
  calibrated_confidence   (0-100 — probability × 100, for legacy consumers)
  calibration_method      ("isotonic" | "platt" | "identity")
  calibration_version     (integer, bumped on every refit)

Quality metrics: Brier score, Expected Calibration Error (ECE), log loss and
reliability-diagram bins — with before (raw/100) vs after (calibrated)
comparison.

The fitted calibrator is persisted to calibration_state.json (versioned).
NO trading/strategy logic lives here; this module only rescales confidence.
"""

from __future__ import annotations

import json
import math
import os
import sqlite3
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATE_PATH = os.path.join(BASE_DIR, "calibration_state.json")
DB_PATH = os.path.join(BASE_DIR, "trade_intelligence.db")

ISOTONIC_MIN_SAMPLES = 100
PLATT_MIN_SAMPLES = 30
DEFAULT_BINS = 10
_EPS = 1e-6  # probability clamp for log loss

SAFETY_MESSAGE = ("Calibrated probabilities are estimated from historical "
                  "paper trades and do not guarantee future results. "
                  "Paper trading and research only.")


# ── Fitting ──────────────────────────────────────────────────────────────────

def _fit_platt(samples: list[tuple[float, int]]) -> dict:
    """Fit p = sigmoid(a * (conf/100) + b) by Newton-Raphson on log loss."""
    xs = [max(0.0, min(100.0, float(c))) / 100.0 for c, _ in samples]
    ys = [1.0 if y else 0.0 for _, y in samples]
    a, b = 1.0, 0.0
    for _ in range(100):
        ga = gb = 0.0
        haa = hab = hbb = 0.0
        for x, y in zip(xs, ys):
            z = a * x + b
            p = 1.0 / (1.0 + math.exp(-max(-30.0, min(30.0, z))))
            w = p * (1.0 - p)
            ga += (p - y) * x
            gb += (p - y)
            haa += w * x * x
            hab += w * x
            hbb += w
        # Regularize the Hessian slightly for stability
        haa += 1e-6
        hbb += 1e-6
        det = haa * hbb - hab * hab
        if abs(det) < 1e-12:
            break
        da = (hbb * ga - hab * gb) / det
        db = (haa * gb - hab * ga) / det
        a -= da
        b -= db
        if abs(da) < 1e-8 and abs(db) < 1e-8:
            break
    return {"a": round(a, 6), "b": round(b, 6)}


def _fit_isotonic(samples: list[tuple[float, int]]) -> dict:
    """Pool-Adjacent-Violators. Returns breakpoints (conf, prob) sorted by
    confidence; application interpolates linearly between breakpoints."""
    pts = sorted(
        (max(0.0, min(100.0, float(c))), 1.0 if y else 0.0) for c, y in samples
    )
    # PAV: blocks of (weight, mean, x_first, x_last)
    blocks: list[list[float]] = []
    for x, y in pts:
        blocks.append([1.0, y, x, x])
        while len(blocks) >= 2 and blocks[-2][1] >= blocks[-1][1]:
            w2, m2, x2f, _x2l = blocks.pop()
            w1, m1, x1f, _x1l = blocks.pop()
            w = w1 + w2
            blocks.append([w, (w1 * m1 + w2 * m2) / w, x1f, x])
    knots = [
        {"conf": round((blk[2] + blk[3]) / 2.0, 4), "prob": round(blk[1], 6)}
        for blk in blocks
    ]
    # Deduplicate identical conf values (keep last)
    dedup: dict[float, dict] = {}
    for k in knots:
        dedup[k["conf"]] = k
    return {"knots": sorted(dedup.values(), key=lambda k: k["conf"])}


def fit_calibrator(samples: list[tuple[float, int]], method: str = "auto") -> dict:
    """Fit a calibrator from (raw_confidence 0-100, won 0/1) samples.

    Returns a serializable spec:
      {method, params, n_samples, base_rate, fitted_at}
    """
    clean = [
        (float(c), 1 if y else 0) for c, y in samples
        if c is not None and 0.0 <= float(c) <= 100.0
    ]
    n = len(clean)
    base_rate = (sum(y for _, y in clean) / n) if n else 0.0
    if method == "auto":
        if n >= ISOTONIC_MIN_SAMPLES:
            method = "isotonic"
        elif n >= PLATT_MIN_SAMPLES:
            method = "platt"
        else:
            method = "identity"
    if method == "isotonic" and n >= 2:
        params = _fit_isotonic(clean)
    elif method == "platt" and n >= 2:
        params = _fit_platt(clean)
    else:
        method, params = "identity", {}
    return {
        "method": method,
        "params": params,
        "n_samples": n,
        "base_rate": round(base_rate, 4),
        "fitted_at": datetime.now().isoformat(timespec="seconds"),
    }


# ── Application ──────────────────────────────────────────────────────────────

def apply_calibration(calibrator: dict | None, raw_confidence: float) -> float:
    """Map raw confidence (0-100) → calibrated probability, ALWAYS in [0, 1]."""
    c = max(0.0, min(100.0, float(raw_confidence or 0.0)))
    if not calibrator or calibrator.get("method") in (None, "", "identity"):
        return round(c / 100.0, 6)
    method = calibrator["method"]
    params = calibrator.get("params") or {}
    if method == "platt":
        z = params.get("a", 1.0) * (c / 100.0) + params.get("b", 0.0)
        p = 1.0 / (1.0 + math.exp(-max(-30.0, min(30.0, z))))
    elif method == "isotonic":
        knots = params.get("knots") or []
        if not knots:
            p = c / 100.0
        elif c <= knots[0]["conf"]:
            p = knots[0]["prob"]
        elif c >= knots[-1]["conf"]:
            p = knots[-1]["prob"]
        else:
            p = knots[-1]["prob"]
            for i in range(1, len(knots)):
                lo, hi = knots[i - 1], knots[i]
                if c <= hi["conf"]:
                    span = hi["conf"] - lo["conf"]
                    t = (c - lo["conf"]) / span if span > 0 else 0.0
                    p = lo["prob"] + t * (hi["prob"] - lo["prob"])
                    break
    else:
        p = c / 100.0
    return round(max(0.0, min(1.0, p)), 6)


def calibrate_prediction(calibrator: dict | None, raw_confidence: float) -> dict:
    """Full calibration record for ONE prediction."""
    prob = apply_calibration(calibrator, raw_confidence)
    return {
        "raw_confidence": round(float(raw_confidence or 0.0), 1),
        "calibrated_probability": prob,
        "calibrated_confidence": round(prob * 100.0, 1),
        "calibration_method": (calibrator or {}).get("method", "identity"),
        "calibration_version": int((calibrator or {}).get("version", 0) or 0),
    }


# ── Quality metrics ──────────────────────────────────────────────────────────

def brier_score(probs: list[float], outcomes: list[int]) -> float:
    """Mean squared error between predicted probability and outcome (0=perfect)."""
    if not probs or len(probs) != len(outcomes):
        return 0.0
    return round(
        sum((p - (1.0 if y else 0.0)) ** 2 for p, y in zip(probs, outcomes))
        / len(probs), 6)


def log_loss(probs: list[float], outcomes: list[int]) -> float:
    """Negative mean log-likelihood; probabilities clamped to avoid log(0)."""
    if not probs or len(probs) != len(outcomes):
        return 0.0
    total = 0.0
    for p, y in zip(probs, outcomes):
        p = max(_EPS, min(1.0 - _EPS, p))
        total += -(math.log(p) if y else math.log(1.0 - p))
    return round(total / len(probs), 6)


def reliability_diagram(probs: list[float], outcomes: list[int],
                        bins: int = DEFAULT_BINS) -> list[dict]:
    """Equal-width probability bins with avg predicted vs observed win rate."""
    out = []
    n = len(probs)
    for i in range(bins):
        lo = i / bins
        hi = (i + 1) / bins
        idx = [j for j in range(n)
               if (probs[j] >= lo and (probs[j] < hi or (i == bins - 1 and probs[j] <= hi)))]
        cnt = len(idx)
        avg_p = sum(probs[j] for j in idx) / cnt if cnt else 0.0
        obs = sum(1 for j in idx if outcomes[j]) / cnt if cnt else 0.0
        out.append({
            "bin_low": round(lo, 2),
            "bin_high": round(hi, 2),
            "count": cnt,
            "avg_predicted": round(avg_p, 4),
            "observed_rate": round(obs, 4),
            "gap": round(obs - avg_p, 4) if cnt else 0.0,
        })
    return out


def expected_calibration_error(probs: list[float], outcomes: list[int],
                               bins: int = DEFAULT_BINS) -> float:
    """Weighted average |observed − predicted| across reliability bins (0=perfect)."""
    n = len(probs)
    if n == 0:
        return 0.0
    diag = reliability_diagram(probs, outcomes, bins)
    return round(
        sum(b["count"] / n * abs(b["observed_rate"] - b["avg_predicted"])
            for b in diag if b["count"] > 0), 6)


def calibration_report_from_pairs(raw_confidences: list[float],
                                  calibrated_probs: list[float],
                                  outcomes: list[int],
                                  method: str = "",
                                  version: int = 0,
                                  bins: int = DEFAULT_BINS) -> dict:
    """Before/after quality report when calibrated probabilities were already
    RECORDED at prediction time (e.g. walk-forward trades that carried their
    own per-window calibrated probability)."""
    outcomes = [1 if y else 0 for y in outcomes]
    raw_probs = [max(0.0, min(1.0, float(c or 0.0) / 100.0)) for c in raw_confidences]
    cal_probs = [max(0.0, min(1.0, float(p or 0.0))) for p in calibrated_probs]
    return {
        "samples": len(outcomes),
        "calibration_method": method or "identity",
        "calibration_version": int(version or 0),
        "before": {
            "brier_score": brier_score(raw_probs, outcomes),
            "ece": expected_calibration_error(raw_probs, outcomes, bins),
            "log_loss": log_loss(raw_probs, outcomes),
        },
        "after": {
            "brier_score": brier_score(cal_probs, outcomes),
            "ece": expected_calibration_error(cal_probs, outcomes, bins),
            "log_loss": log_loss(cal_probs, outcomes),
        },
        "reliability_raw": reliability_diagram(raw_probs, outcomes, bins),
        "reliability_calibrated": reliability_diagram(cal_probs, outcomes, bins),
        "safety": SAFETY_MESSAGE,
    }


def calibration_report(raw_confidences: list[float], outcomes: list[int],
                       calibrator: dict | None,
                       bins: int = DEFAULT_BINS) -> dict:
    """Before (raw/100) vs after (calibrated) quality report for a set of
    completed predictions."""
    outcomes = [1 if y else 0 for y in outcomes]
    raw_probs = [max(0.0, min(1.0, float(c or 0.0) / 100.0)) for c in raw_confidences]
    cal_probs = [apply_calibration(calibrator, c) for c in raw_confidences]
    return {
        "samples": len(outcomes),
        "calibration_method": (calibrator or {}).get("method", "identity"),
        "calibration_version": int((calibrator or {}).get("version", 0) or 0),
        "fitted_at": (calibrator or {}).get("fitted_at", ""),
        "training_samples": int((calibrator or {}).get("n_samples", 0) or 0),
        "before": {
            "brier_score": brier_score(raw_probs, outcomes),
            "ece": expected_calibration_error(raw_probs, outcomes, bins),
            "log_loss": log_loss(raw_probs, outcomes),
        },
        "after": {
            "brier_score": brier_score(cal_probs, outcomes),
            "ece": expected_calibration_error(cal_probs, outcomes, bins),
            "log_loss": log_loss(cal_probs, outcomes),
        },
        "reliability_raw": reliability_diagram(raw_probs, outcomes, bins),
        "reliability_calibrated": reliability_diagram(cal_probs, outcomes, bins),
        "safety": SAFETY_MESSAGE,
    }


# ── Persistence / versioning ─────────────────────────────────────────────────

def load_active_calibrator() -> dict | None:
    """Load the persisted calibrator ({method, params, version, ...}) or None."""
    try:
        with open(STATE_PATH) as f:
            state = json.load(f)
        cal = state.get("active")
        if cal and cal.get("method"):
            return cal
    except Exception:
        pass
    return None


def save_calibrator(calibrator: dict) -> dict:
    """Persist as the active calibrator, bumping the version."""
    prev = 0
    try:
        with open(STATE_PATH) as f:
            prev = int(json.load(f).get("active", {}).get("version", 0) or 0)
    except Exception:
        pass
    calibrator = dict(calibrator)
    calibrator["version"] = prev + 1
    with open(STATE_PATH, "w") as f:
        json.dump({"active": calibrator,
                   "updated_at": datetime.now().isoformat(timespec="seconds")},
                  f, indent=2)
    return calibrator


def training_samples_from_knowledge(as_of: str | None = None) -> list[tuple[float, int]]:
    """(confidence, winning) pairs from completed historical knowledge trades.
    When `as_of` (YYYY-MM-DD) is given, ONLY trades fully exited BEFORE that
    day are used (no lookahead)."""
    try:
        conn = sqlite3.connect(DB_PATH)
        try:
            q = ("SELECT confidence, winning, exit_date FROM "
                 "historical_knowledge_trades WHERE confidence IS NOT NULL "
                 "AND winning IS NOT NULL "
                 "AND exit_date IS NOT NULL AND exit_date != ''")
            rows = conn.execute(q).fetchall()
        finally:
            conn.close()
    except Exception:
        return []
    out = []
    for conf, won, exit_date in rows:
        d = str(exit_date)[:10]
        if as_of and (not d or d >= as_of):
            continue
        out.append((float(conf), 1 if won else 0))
    return out


def refit_from_knowledge() -> dict:
    """Refit the ACTIVE calibrator from all completed knowledge trades and
    persist it with a bumped version. Returns the saved calibrator."""
    samples = training_samples_from_knowledge()
    return save_calibrator(fit_calibrator(samples))


def get_or_fit_calibrator() -> dict:
    """Active calibrator, fitting one from knowledge on first use."""
    cal = load_active_calibrator()
    if cal is not None:
        return cal
    return refit_from_knowledge()
