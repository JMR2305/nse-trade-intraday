"""
phase21_calibration.py — Phase 21: Confidence calibration by fixed buckets.

PAPER / RESEARCH ONLY. ADVISORY ONLY.
- Uses only completed trades closed before the evaluation date (no look-ahead).
- Raw confidence is never modified; calibrated confidence is stored separately.
- Sample-size shrinkage (Bayesian toward the global win rate) prevents tiny
  samples from producing extreme calibration changes.
- Buckets below the minimum sample size are marked INSUFFICIENT.
- Calibration output is advisory until explicitly approved via governance.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone

from phase14_learning import learning_rows
from phase21_baseline import CONFIDENCE_BUCKETS, confidence_bucket

_DIR = os.path.dirname(os.path.abspath(__file__))
CALIBRATION_FILE = os.path.join(_DIR, "phase21_calibration.json")

MIN_BUCKET_SAMPLE = 10        # below this → INSUFFICIENT
SHRINKAGE_PRIOR_WEIGHT = 20.0  # pseudo-observations pulled toward global rate


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _completed_before(rows: list[dict], eval_date: str | None) -> list[dict]:
    """Only trades whose exit timestamp precedes the evaluation date."""
    if not eval_date:
        return rows
    out = []
    for r in rows:
        exit_ts = str(r.get("exit_ts") or "")
        if exit_ts and exit_ts[:10] < eval_date[:10]:
            out.append(r)
    return out


def run_calibration(eval_date: str | None = None, force: bool = False) -> dict:
    """Bucketed calibration over completed trades prior to eval_date."""
    if not force and eval_date is None and os.path.exists(CALIBRATION_FILE):
        with open(CALIBRATION_FILE) as f:
            cached = json.load(f)
        if cached.get("generated_at", "")[:10] == _now()[:10]:
            return cached

    eval_date = eval_date or _now()
    rows = [r for r in learning_rows() if r.get("raw_confidence") is not None]
    rows = _completed_before(rows, eval_date)

    global_n = len(rows)
    global_wins = sum(1 for r in rows if float(r.get("net_pnl") or 0) > 0)
    global_rate = (global_wins / global_n) if global_n else 0.5

    buckets = []
    curve = []
    weighted_err = 0.0
    weighted_n = 0
    for lo, hi in CONFIDENCE_BUCKETS:
        label = f"{lo}-{hi}"
        brows = [r for r in rows
                 if confidence_bucket(float(r["raw_confidence"])) == label]
        n = len(brows)
        pnls = [float(r.get("net_pnl") or 0) for r in brows]
        rets = [float(r.get("return_pct") or 0) for r in brows]
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p < 0]
        win_rate = (len(wins) / n) if n else None
        gross_win, gross_loss = sum(wins), abs(sum(losses))
        pf = (gross_win / gross_loss) if gross_loss else None
        expectancy = (sum(pnls) / n) if n else None
        avg_return = (sum(rets) / n) if n else None
        maes = [float(r["mae"]) for r in brows if r.get("mae") is not None]
        mfes = [float(r["mfe"]) for r in brows if r.get("mfe") is not None]
        predicted = (lo + hi) / 2.0 / 100.0

        insufficient = n < MIN_BUCKET_SAMPLE
        # Shrinkage: observed rate pulled toward global rate by prior weight.
        shrunk = None
        if n:
            shrunk = ((len(wins) + SHRINKAGE_PRIOR_WEIGHT * global_rate)
                      / (n + SHRINKAGE_PRIOR_WEIGHT))
        calibration_error = (abs(predicted - win_rate)
                             if win_rate is not None else None)
        if win_rate is not None:
            weighted_err += n * abs(predicted - win_rate)
            weighted_n += n

        buckets.append({
            "bucket": label,
            "predicted_confidence": round(predicted * 100, 1),
            "trades": n,
            "win_rate": round(win_rate, 4) if win_rate is not None else None,
            "avg_return_pct": round(avg_return, 3) if avg_return is not None else None,
            "profit_factor": round(pf, 3) if pf is not None else None,
            "expectancy": round(expectancy, 2) if expectancy is not None else None,
            "max_adverse_excursion": round(max(maes), 3) if maes else None,
            "max_favorable_excursion": round(max(mfes), 3) if mfes else None,
            "calibration_error": (round(calibration_error, 4)
                                  if calibration_error is not None else None),
            "shrunk_observed_rate": round(shrunk, 4) if shrunk is not None else None,
            "calibrated_confidence_advisory": (round(shrunk * 100, 1)
                                               if shrunk is not None and not insufficient
                                               else None),
            "status": "INSUFFICIENT" if insufficient else "OK",
        })
        curve.append({
            "bucket": label,
            "predicted": round(predicted * 100, 1),
            "observed": round(win_rate * 100, 1) if win_rate is not None else None,
            "shrunk_observed": round(shrunk * 100, 1) if shrunk is not None else None,
            "trades": n,
        })

    result = {
        "generated_at": _now(),
        "evaluation_date": eval_date,
        "no_look_ahead": "Only trades closed before evaluation_date are used.",
        "total_trades": global_n,
        "global_win_rate": round(global_rate, 4),
        "min_bucket_sample": MIN_BUCKET_SAMPLE,
        "shrinkage_prior_weight": SHRINKAGE_PRIOR_WEIGHT,
        "buckets": buckets,
        "calibration_curve": curve,
        "overall_calibration_error": (round(weighted_err / weighted_n, 4)
                                      if weighted_n else None),
        "advisory_only": True,
        "raw_confidence_untouched": True,
        "note": "Calibrated confidence is ADVISORY until explicitly approved. "
                "Raw confidence is preserved unchanged.",
        "label": "PAPER / RESEARCH ONLY",
    }
    tmp = CALIBRATION_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(result, f, indent=1, default=str)
    os.replace(tmp, CALIBRATION_FILE)
    return result


def load_calibration() -> dict:
    if os.path.exists(CALIBRATION_FILE):
        with open(CALIBRATION_FILE) as f:
            return json.load(f)
    return run_calibration()


def calibrate_confidence_advisory(raw_conf: float | None) -> dict:
    """Advisory calibrated value for a raw confidence (never applied automatically)."""
    if raw_conf is None:
        return {"raw": None, "calibrated_advisory": None, "status": "NO_CONFIDENCE"}
    cal = load_calibration()
    label = confidence_bucket(float(raw_conf))
    for b in cal.get("buckets", []):
        if b["bucket"] == label:
            return {
                "raw": raw_conf,
                "bucket": label,
                "calibrated_advisory": b.get("calibrated_confidence_advisory"),
                "status": b.get("status"),
                "advisory_only": True,
            }
    return {"raw": raw_conf, "bucket": label, "calibrated_advisory": None,
            "status": "INSUFFICIENT", "advisory_only": True}
