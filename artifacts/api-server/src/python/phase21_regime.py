"""
phase21_regime.py — Phase 21: Strategy performance by market regime (advisory).

PAPER / RESEARCH ONLY. ADVISORY ONLY.
- Per strategy × regime metrics from completed trades.
- Classifies each pair as ELIGIBLE / CONDITIONAL / WATCHLIST / DISABLED /
  INSUFFICIENT_DATA — recommendations only; nothing is enabled or disabled
  automatically.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone

from phase14_learning import learning_rows, group_metrics, reliability_label

_DIR = os.path.dirname(os.path.abspath(__file__))
REGIME_FILE = os.path.join(_DIR, "phase21_regime_matrix.json")

REGIMES = ["BULLISH", "BEARISH", "RANGE_BOUND", "HIGH_VOLATILITY",
           "LOW_VOLATILITY", "TREND_CONTINUATION", "REVERSAL"]

REGIME_ALIASES = {
    "BULL": "BULLISH", "UPTREND": "BULLISH", "TRENDING_UP": "BULLISH",
    "BEAR": "BEARISH", "DOWNTREND": "BEARISH", "TRENDING_DOWN": "BEARISH",
    "SIDEWAYS": "RANGE_BOUND", "RANGE": "RANGE_BOUND", "RANGING": "RANGE_BOUND",
    "NEUTRAL": "RANGE_BOUND",
    "VOLATILE": "HIGH_VOLATILITY", "HIGH_VOL": "HIGH_VOLATILITY",
    "LOW_VOL": "LOW_VOLATILITY", "QUIET": "LOW_VOLATILITY",
    "TREND": "TREND_CONTINUATION", "CONTINUATION": "TREND_CONTINUATION",
    "REVERSAL_ENVIRONMENT": "REVERSAL", "MEAN_REVERSION": "REVERSAL",
}

MIN_SAMPLE = 10


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_regime(raw: str | None) -> str:
    if not raw:
        return "UNKNOWN"
    key = str(raw).upper().replace(" ", "_").replace("-", "_")
    if key in REGIMES:
        return key
    return REGIME_ALIASES.get(key, key)


def _classify(m: dict) -> tuple[str, str]:
    """Advisory classification of a strategy/regime metric block."""
    n = m.get("sample_size", 0)
    if n < MIN_SAMPLE:
        return "INSUFFICIENT_DATA", f"only {n} completed trades (need {MIN_SAMPLE})"
    pf = m.get("profit_factor")
    exp = m.get("expectancy") or 0
    wr = m.get("win_rate") or 0
    if pf is not None and pf >= 1.5 and exp > 0 and wr >= 0.5:
        return "ELIGIBLE", "profitable with strong profit factor and win rate"
    if pf is not None and pf >= 1.1 and exp > 0:
        return "CONDITIONAL", "marginally profitable — allow with reduced size/extra confirmation"
    if exp > 0:
        return "WATCHLIST", "positive expectancy but weak profit factor — monitor"
    if pf is not None and pf < 0.8 and n >= 30:
        return "DISABLED", "consistently unprofitable with adequate sample — recommend disable"
    return "WATCHLIST", "negative expectancy but sample not yet conclusive"


def run_regime_matrix(force: bool = False) -> dict:
    if not force and os.path.exists(REGIME_FILE):
        with open(REGIME_FILE) as f:
            cached = json.load(f)
        if cached.get("generated_at", "")[:10] == _now()[:10]:
            return cached

    rows = learning_rows()
    pairs: dict[tuple[str, str], list[dict]] = {}
    for r in rows:
        strat = str(r.get("strategy") or "UNKNOWN")
        reg = normalize_regime(r.get("market_regime_at_entry"))
        pairs.setdefault((strat, reg), []).append(r)

    matrix = []
    for (strat, reg), prs in sorted(pairs.items()):
        m = group_metrics(prs)
        holding = [float(r["holding_period_days"]) for r in prs
                   if r.get("holding_period_days") is not None]
        rrs = [float(r["risk_reward"]) for r in prs if r.get("risk_reward")]
        status, reason = _classify(m)
        matrix.append({
            "strategy": strat,
            "regime": reg,
            **m,
            "wins": round((m.get("win_rate") or 0) * m.get("sample_size", 0)),
            "losses": m.get("sample_size", 0)
                      - round((m.get("win_rate") or 0) * m.get("sample_size", 0)),
            "avg_holding_days": (round(sum(holding) / len(holding), 2)
                                 if holding else None),
            "avg_rr": round(sum(rrs) / len(rrs), 2) if rrs else None,
            "reliability_status": reliability_label(m.get("sample_size", 0)),
            "classification": status,
            "classification_reason": reason,
            "advisory_only": True,
        })

    result = {
        "generated_at": _now(),
        "regimes": REGIMES,
        "min_sample": MIN_SAMPLE,
        "pairs": matrix,
        "auto_applied": False,
        "note": "Classifications are RECOMMENDATIONS for human review. "
                "No strategy is enabled or disabled automatically.",
        "label": "PAPER / RESEARCH ONLY",
    }
    tmp = REGIME_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(result, f, indent=1, default=str)
    os.replace(tmp, REGIME_FILE)
    return result


def load_regime_matrix() -> dict:
    if os.path.exists(REGIME_FILE):
        with open(REGIME_FILE) as f:
            return json.load(f)
    return run_regime_matrix()
