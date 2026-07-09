"""
signal_learning.py
Signal Quality Learning Weights (v1.0).

Adjusts the relative importance (weight) of each signal-quality factor by
learning from historical Market Replay and Paper Basket Test outcomes.

PAPER TRADING ONLY — this module never places real orders. It only tunes
the transparent factor weights used by signal_quality.py.

Learning rule (simple, transparent, bounded):
  - For each completed (resolved) paper trade, a factor "appeared" in the
    trade when its component score was >= FACTOR_PRESENT_THRESHOLD.
  - If the trade WON, every factor that appeared gains +LEARN_STEP.
  - If the trade LOST, every factor that appeared loses -LEARN_STEP.
  - Weights are always clamped to [MIN_WEIGHT, MAX_WEIGHT].

Weights are persisted to signal_weights.json next to this file so learning
accumulates across runs and stays fully inspectable.
"""

import json
import os
from datetime import datetime

STATE_DIR = os.path.dirname(os.path.abspath(__file__))
WEIGHTS_FILE = os.path.join(STATE_DIR, "signal_weights.json")

FACTORS = [
    "trend",
    "momentum",
    "volume",
    "sector",
    "regime",
    "risk_reward",
    "strategy_reliability",
]

DEFAULT_WEIGHTS: dict[str, float] = {
    "trend":                18.0,
    "momentum":             14.0,
    "volume":               12.0,
    "sector":               12.0,
    "regime":               14.0,
    "risk_reward":          15.0,
    "strategy_reliability": 15.0,
}

MIN_WEIGHT = 5.0
MAX_WEIGHT = 30.0
LEARN_STEP = 0.5
FACTOR_PRESENT_THRESHOLD = 60.0


def _clamp(w: float) -> float:
    return round(max(MIN_WEIGHT, min(MAX_WEIGHT, w)), 2)


def load_weights() -> dict:
    """Return {'weights': {factor: weight}, 'samples_learned': int, 'updated_at': str}."""
    if os.path.exists(WEIGHTS_FILE):
        try:
            with open(WEIGHTS_FILE, "r") as f:
                data = json.load(f)
            weights = {k: _clamp(float(data.get("weights", {}).get(k, DEFAULT_WEIGHTS[k])))
                       for k in FACTORS}
            return {
                "weights": weights,
                "samples_learned": int(data.get("samples_learned", 0)),
                "updated_at": data.get("updated_at", ""),
            }
        except Exception:
            pass
    return {"weights": dict(DEFAULT_WEIGHTS), "samples_learned": 0, "updated_at": ""}


def _save(state: dict) -> None:
    try:
        with open(WEIGHTS_FILE, "w") as f:
            json.dump(state, f, indent=2)
    except Exception:
        pass  # learning is best-effort; never break a paper test over persistence


def learn_from_outcomes(records: list[dict]) -> dict:
    """
    records: [{ 'factors': {factor: score 0-100}, 'win': bool }, ...]
    Adjusts weights per the learning rule and persists them.
    Returns the updated state plus a per-factor adjustment log.
    """
    state = load_weights()
    weights = state["weights"]
    adjustments: dict[str, float] = {k: 0.0 for k in FACTORS}

    used = 0
    for rec in records:
        factors = rec.get("factors") or {}
        win = bool(rec.get("win"))
        touched = False
        for name in FACTORS:
            score = factors.get(name)
            if score is None or score < FACTOR_PRESENT_THRESHOLD:
                continue
            delta = LEARN_STEP if win else -LEARN_STEP
            weights[name] = _clamp(weights[name] + delta)
            adjustments[name] = round(adjustments[name] + delta, 2)
            touched = True
        if touched:
            used += 1

    state["weights"] = weights
    state["samples_learned"] = state["samples_learned"] + used
    state["updated_at"] = datetime.now().isoformat()
    _save(state)

    return {
        "weights": weights,
        "samples_learned": state["samples_learned"],
        "updated_at": state["updated_at"],
        "adjustments": adjustments,
        "records_used": used,
        "bounds": {"min": MIN_WEIGHT, "max": MAX_WEIGHT},
    }
