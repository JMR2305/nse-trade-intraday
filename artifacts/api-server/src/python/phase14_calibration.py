"""
phase14_calibration.py — Phase 14: Rolling, versioned confidence calibration.

RESEARCH / PAPER LEARNING ONLY.
- Fits only on trades completed BEFORE the evaluation split (chronological).
- Isotonic (PAV) when >= 100 train samples, Platt when >= 30, else identity.
- Every calibrator is versioned and preserved; a new calibrator that performs
  worse out-of-sample than the active one is rejected automatically and the
  previous stable calibrator stays active.
- Never fits and evaluates on the same observations.
"""
from __future__ import annotations

import json
import math
import os
from datetime import datetime, timezone

from phase14_learning import learning_rows, _brier, _ece, _log_loss

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CALIBRATORS_FILE = os.path.join(BASE_DIR, "phase14_calibrators.json")

MIN_ISOTONIC = 100
MIN_PLATT = 30
LOW_SAMPLE_WARNING = 100


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_store() -> dict:
    if os.path.exists(CALIBRATORS_FILE):
        with open(CALIBRATORS_FILE) as f:
            return json.load(f)
    return {"active_version": None, "calibrators": []}


def _save_store(store: dict) -> None:
    with open(CALIBRATORS_FILE, "w") as f:
        json.dump(store, f, indent=1, default=str)


# ── Fitting primitives ─────────────────────────────────────────────────────────

def _fit_isotonic(samples: list[tuple[float, int]]) -> dict:
    """Pool-adjacent-violators on (raw_prob, outcome)."""
    pts = sorted(samples)
    blocks = [[p, float(y), 1.0] for p, y in pts]  # x, mean, weight
    merged: list[list[float]] = []
    for b in blocks:
        merged.append(b)
        while len(merged) >= 2 and merged[-2][1] > merged[-1][1]:
            x2, m2, w2 = merged.pop()
            x1, m1, w1 = merged.pop()
            w = w1 + w2
            merged.append([x2, (m1 * w1 + m2 * w2) / w, w])
    xs, ys = [], []
    for x, m, _ in merged:
        xs.append(x)
        ys.append(m)
    return {"method": "isotonic", "xs": xs, "ys": ys}


def _fit_platt(samples: list[tuple[float, int]]) -> dict:
    """Simple logistic fit p' = sigmoid(a*logit-ish(p) + b) via gradient descent."""
    a, b = 1.0, 0.0
    lr = 0.1
    for _ in range(500):
        ga = gb = 0.0
        for p, y in samples:
            z = a * (p - 0.5) * 4 + b
            s = 1 / (1 + math.exp(-z))
            d = s - y
            ga += d * (p - 0.5) * 4
            gb += d
        n = len(samples)
        a -= lr * ga / n
        b -= lr * gb / n
    return {"method": "platt", "a": a, "b": b}


def _apply(cal: dict | None, raw_prob: float) -> float:
    p = min(max(raw_prob, 0.0), 1.0)
    if not cal or cal.get("method") == "identity":
        return p
    if cal["method"] == "isotonic":
        xs, ys = cal["xs"], cal["ys"]
        if not xs:
            return p
        if p <= xs[0]:
            return ys[0]
        if p >= xs[-1]:
            return ys[-1]
        for i in range(1, len(xs)):
            if p <= xs[i]:
                x0, x1, y0, y1 = xs[i - 1], xs[i], ys[i - 1], ys[i]
                if x1 == x0:
                    return y1
                t = (p - x0) / (x1 - x0)
                return y0 + t * (y1 - y0)
        return ys[-1]
    if cal["method"] == "platt":
        z = cal["a"] * (p - 0.5) * 4 + cal["b"]
        return 1 / (1 + math.exp(-z))
    return p


def _metrics(cal: dict | None, pairs: list[tuple[float, int]]) -> dict:
    mapped = [(_apply(cal, p), y) for p, y in pairs]
    return {
        "brier": round(_brier(mapped), 4) if mapped else None,
        "ece": round(_ece(mapped), 4) if mapped else None,
        "log_loss": round(_log_loss(mapped), 4) if mapped else None,
        "n": len(mapped),
    }


# ── Training ───────────────────────────────────────────────────────────────────

def train_calibrator(force: bool = False) -> dict:
    """Train a new calibrator on a chronological train/test split."""
    rows = sorted(learning_rows(only_audited=True),
                  key=lambda r: str(r.get("exit_ts") or ""))
    pairs = [
        (min(max(float(r["raw_confidence"]) / 100.0, 0.0), 1.0),
         1 if float(r.get("net_pnl") or 0) > 0 else 0)
        for r in rows if r.get("raw_confidence") is not None
    ]
    n = len(pairs)
    store = _load_store()
    version = f"cal_v{len(store['calibrators']) + 1}"
    warning = (f"Only {n} completed trades — calibration unreliable below "
               f"{LOW_SAMPLE_WARNING}.") if n < LOW_SAMPLE_WARNING else None

    if n < MIN_PLATT:
        cal = {"method": "identity"}
        train_pairs, test_pairs = [], pairs
        note = f"identity calibration — insufficient evidence ({n} < {MIN_PLATT})"
    else:
        split = max(int(n * 0.7), n - 200)
        train_pairs, test_pairs = pairs[:split], pairs[split:]
        if len(train_pairs) >= MIN_ISOTONIC:
            cal = _fit_isotonic(train_pairs)
            note = f"isotonic fitted on {len(train_pairs)} chronological train samples"
        else:
            cal = _fit_platt(train_pairs)
            note = f"platt fitted on {len(train_pairs)} chronological train samples"

    before = _metrics(None, test_pairs)
    after = _metrics(cal, test_pairs)

    # Compare against the currently active calibrator on the same OOS window.
    active = get_active_calibrator()
    rejected = False
    reject_reason = None
    if active and test_pairs:
        active_metrics = _metrics(active["calibrator"], test_pairs)
        if (after["brier"] is not None and active_metrics["brier"] is not None
                and after["brier"] > active_metrics["brier"]):
            rejected = True
            reject_reason = (f"new OOS Brier {after['brier']} worse than active "
                             f"calibrator {active['version']} ({active_metrics['brier']}) "
                             "— falling back to previous stable calibrator")

    record = {
        "version": version,
        "created_at": _now(),
        "method": cal["method"],
        "calibrator": cal,
        "train_samples": len(train_pairs),
        "test_samples": len(test_pairs),
        "data_cutoff": rows[-1].get("exit_ts") if rows else None,
        "metrics_before": before,
        "metrics_after": after,
        "status": "REJECTED" if rejected else "ACTIVE",
        "reject_reason": reject_reason,
        "note": note,
        "warning": warning,
    }
    # Preserve history; demote previous active if promoting this one.
    if not rejected:
        for c in store["calibrators"]:
            if c.get("status") == "ACTIVE":
                c["status"] = "ARCHIVED"
        store["active_version"] = version
    store["calibrators"].append(record)
    _save_store(store)
    return record


def get_active_calibrator() -> dict | None:
    store = _load_store()
    av = store.get("active_version")
    for c in store.get("calibrators", []):
        if c["version"] == av:
            return c
    return None


def calibration_status() -> dict:
    store = _load_store()
    active = get_active_calibrator()
    rows = learning_rows(only_audited=True)
    return {
        "active_version": store.get("active_version"),
        "active_method": active["method"] if active else "identity",
        "calibrator_count": len(store.get("calibrators", [])),
        "completed_trades": len(rows),
        "warning": (f"Only {len(rows)} completed trades — calibration unreliable "
                    f"below {LOW_SAMPLE_WARNING}.") if len(rows) < LOW_SAMPLE_WARNING else None,
        "history": [
            {k: c.get(k) for k in ("version", "created_at", "method", "status",
                                   "train_samples", "test_samples",
                                   "metrics_before", "metrics_after",
                                   "reject_reason", "warning")}
            for c in store.get("calibrators", [])
        ],
        "note": "RESEARCH / PAPER LEARNING ONLY.",
    }


def calibrate_confidence(raw_confidence: float) -> dict:
    """Map a 0-100 raw confidence to a calibrated win probability."""
    active = get_active_calibrator()
    raw_p = min(max(raw_confidence / 100.0, 0.0), 1.0)
    cal_p = _apply(active["calibrator"] if active else None, raw_p)
    return {
        "raw_confidence": raw_confidence,
        "raw_probability": round(raw_p, 4),
        "calibrated_probability": round(cal_p, 4),
        "calibrator_version": active["version"] if active else "identity",
        "calibrator_method": active["method"] if active else "identity",
    }
