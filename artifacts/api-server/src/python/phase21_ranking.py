"""
phase21_ranking.py — Phase 21: Deterministic opportunity ranking with full
score breakdown and penalty terms.

PAPER / RESEARCH ONLY.
- Deterministic: same scan snapshot + same configuration → same ranking.
- Full score breakdown is stored per symbol.
- Geometric blending prevents a single strong factor from dominating.
- Penalties for low reliability, stale/fallback data, poor liquidity,
  regime mismatch, and weak historical expectancy.
- Existing BUY safety gates are untouched — ranking never unblocks a BUY.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone

from phase15_scan_context import build_scan_context
from phase21_calibration import calibrate_confidence_advisory
from phase21_regime import load_regime_matrix, normalize_regime

_DIR = os.path.dirname(os.path.abspath(__file__))
RANKING_FILE = os.path.join(_DIR, "phase21_ranking.json")

RANKING_CONFIG_VERSION = "rank_v1"

# Component weights (sum to 1.0) — applied to normalized 0..1 factors.
WEIGHTS = {
    "confidence": 0.25,
    "opportunity_score": 0.25,
    "rr_ratio": 0.20,
    "regime_compatibility": 0.15,
    "historical_expectancy": 0.15,
}
# A single factor can contribute at most this share of the raw score,
# preventing one strong factor from carrying a weak setup.
FACTOR_CAP = 0.35


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clamp01(v: float) -> float:
    return max(0.0, min(1.0, v))


def _regime_reliability(strategy: str | None, regime: str | None) -> dict:
    matrix = load_regime_matrix()
    reg = normalize_regime(regime)
    for p in matrix.get("pairs", []):
        if p.get("strategy") == (strategy or "UNKNOWN") and p.get("regime") == reg:
            return p
    return {"classification": "INSUFFICIENT_DATA", "expectancy": None,
            "reliability_status": "INSUFFICIENT", "sample_size": 0}


def _score_symbol(item: dict) -> dict:
    conf = item.get("confidence")
    opp = item.get("opportunity_score")
    rr = item.get("rr_ratio")
    strat = item.get("strategy_name") or item.get("strategy_id")
    pair = _regime_reliability(strat, item.get("regime"))

    factors = {
        "confidence": _clamp01(float(conf or 0) / 100.0),
        "opportunity_score": _clamp01(float(opp or 0) / 100.0),
        "rr_ratio": _clamp01(float(rr or 0) / 4.0),
        "regime_compatibility": {
            "ELIGIBLE": 1.0, "CONDITIONAL": 0.7, "WATCHLIST": 0.4,
            "INSUFFICIENT_DATA": 0.5, "DISABLED": 0.0,
        }.get(pair.get("classification"), 0.5),
        "historical_expectancy": _clamp01(
            0.5 + (float(pair.get("expectancy") or 0) / 100.0)),
    }

    # Weighted sum with a per-factor contribution cap.
    contributions = {}
    raw = 0.0
    for k, w in WEIGHTS.items():
        c = min(w * factors[k], FACTOR_CAP)
        contributions[k] = round(c, 4)
        raw += c

    penalties = {}
    quality = str(item.get("data_quality") or "").upper()
    if quality in ("STALE", "FALLBACK", "UNAVAILABLE"):
        penalties["stale_or_fallback_data"] = 0.30
    if pair.get("reliability_status") in ("INSUFFICIENT", "LOW"):
        penalties["low_sample_reliability"] = 0.15
    vol_ratio = (item.get("indicators") or {}).get("volume_ratio")
    if vol_ratio is not None and float(vol_ratio) < 0.5:
        penalties["poor_liquidity"] = 0.15
    if pair.get("classification") == "DISABLED":
        penalties["regime_mismatch"] = 0.30
    if pair.get("expectancy") is not None and float(pair["expectancy"]) < 0:
        penalties["weak_historical_expectancy"] = 0.20
    if item.get("error"):
        penalties["data_error"] = 0.50

    penalty_total = min(sum(penalties.values()), 0.9)
    final = round(raw * (1.0 - penalty_total) * 100, 2)

    cal = calibrate_confidence_advisory(conf)
    return {
        "symbol": item["symbol"],
        "final_action": item.get("final_action"),
        "effective_action": item.get("effective_action"),
        "all_gates_passed": item.get("all_gates_passed"),
        "rank_score": final,
        "raw_score": round(raw * 100, 2),
        "factors": {k: round(v, 4) for k, v in factors.items()},
        "weights": WEIGHTS,
        "factor_cap": FACTOR_CAP,
        "contributions": contributions,
        "penalties": penalties,
        "penalty_total": round(penalty_total, 3),
        "raw_confidence": conf,
        "calibrated_confidence_advisory": cal.get("calibrated_advisory"),
        "strategy": strat,
        "regime": item.get("regime"),
        "regime_classification": pair.get("classification"),
        "regime_reliability": pair.get("reliability_status"),
        "buy_gates_untouched": True,
    }


def run_ranking() -> dict:
    """Deterministic ranking for the current canonical scan snapshot."""
    ctx = build_scan_context()
    if not ctx.get("available"):
        return {"available": False, "reason": ctx.get("reason"),
                "label": "PAPER / RESEARCH ONLY"}

    scored = [_score_symbol(item) for item in ctx["symbols"].values()
              if not item.get("error")]
    # Deterministic ordering: score desc, then symbol asc as tiebreak.
    scored.sort(key=lambda s: (-s["rank_score"], s["symbol"]))
    for i, s in enumerate(scored):
        s["rank"] = i + 1

    result = {
        "available": True,
        "generated_at": _now(),
        "scan_id": ctx["scan_id"],
        "snapshot_ts": ctx["snapshot_ts"],
        "ranking_config_version": RANKING_CONFIG_VERSION,
        "deterministic": True,
        "items": scored,
        "note": "Ranking is deterministic for the same scan snapshot and "
                "configuration. BUY remains blocked whenever safety gates fail.",
        "label": "PAPER / RESEARCH ONLY",
    }
    tmp = RANKING_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(result, f, indent=1, default=str)
    os.replace(tmp, RANKING_FILE)
    return result
