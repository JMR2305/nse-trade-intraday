"""
decision_engine.py — Phase 10C
Decision Engine for the AI Decision Agent.

For every candidate symbol:
  - Computes 7 component scores (market, strategy, risk, research,
    liquidity, volatility, portfolio_impact)
  - Derives overall score + confidence
  - Assigns one of 7 Decision Types
  - Ranks candidates by 6 ranking criteria

Decision Types: WATCH | ACCUMULATE | BUY_CANDIDATE | SELL_CANDIDATE |
                REDUCE_EXPOSURE | AVOID | NO_ACTION

ADVISORY-ONLY — never places orders.
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Tuple

# ── Weights ────────────────────────────────────────────────────────────────────

SCORE_WEIGHTS = {
    "market":          0.20,
    "strategy":        0.25,
    "risk":            0.20,
    "research":        0.10,
    "liquidity":       0.10,
    "volatility":      0.10,
    "portfolio_impact":0.05,
}

# ── Helpers ────────────────────────────────────────────────────────────────────

def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

def _clamp(v: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, float(v) if v is not None else lo))

def _f(v) -> Optional[float]:
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


# ── Component score calculators ────────────────────────────────────────────────

def _market_score(mi: Dict[str, Any]) -> float:
    """Score based on market regime, trend, breadth, and momentum."""
    regime = mi.get("market_regime", "SIDEWAYS")
    trend  = _f(mi.get("trend_strength")) or 50.0
    breadth= _f(mi.get("breadth_score")) or 50.0
    momentum = mi.get("momentum_state", "NEUTRAL")

    base = {
        "BULL":             75.0, "TRENDING":         70.0, "BREAKOUT":         72.0,
        "SIDEWAYS":         50.0, "NORMAL":           50.0, "CHOPPY":           35.0,
        "HIGH_VOLATILITY":  30.0, "BEAR":             20.0, "UNKNOWN":          45.0,
    }.get(regime, 50.0)

    mom_adj = {
        "STRONG_BULLISH":   10.0, "BULLISH":          5.0, "IMPROVING":         3.0,
        "NEUTRAL":          0.0,  "DETERIORATING":   -5.0, "BEARISH":          -8.0,
        "STRONG_BEARISH":  -12.0,
    }.get(momentum, 0.0)

    trend_adj = (trend - 50.0) * 0.2
    breadth_adj = (breadth - 50.0) * 0.1
    return _clamp(base + mom_adj + trend_adj + breadth_adj)


def _strategy_score_for(symbol: str, strategy_snap: Dict[str, Any]) -> Tuple[float, str]:
    """Extract the best strategy score for a specific symbol."""
    top_setups = strategy_snap.get("top_setups") or []
    for setup in top_setups:
        if setup.get("symbol") == symbol:
            return _f(setup.get("best_score")) or 0.0, setup.get("best_strategy") or "Unknown"
    return _f(strategy_snap.get("highest_score")) or 0.0, strategy_snap.get("top_strategy") or "Unknown"


def _risk_score(risk_snap: Dict[str, Any]) -> float:
    """Inverse risk score — low portfolio risk → high score."""
    level = risk_snap.get("risk_level", "UNKNOWN")
    return {
        "LOW":      85.0, "MODERATE": 62.0,
        "HIGH":     35.0, "CRITICAL": 10.0, "UNKNOWN": 50.0,
    }.get(level, 50.0)


def _research_score(research_snap: Dict[str, Any]) -> float:
    """Score from macro/research context."""
    macro = research_snap.get("macro_regime", "NEUTRAL")
    global_risk = _f(research_snap.get("global_risk_score")) or 50.0
    base = {
        "EXPANSIONARY": 75.0, "NEUTRAL": 55.0, "TIGHTENING": 35.0,
        "CONTRACTIONARY": 20.0, "UNKNOWN": 50.0,
    }.get(macro, 50.0)
    risk_adj = (50.0 - global_risk) * 0.3
    return _clamp(base + risk_adj)


def _liquidity_score(mi: Dict[str, Any]) -> float:
    """Liquidity score from market intelligence."""
    return _clamp(_f(mi.get("liquidity_score")) or 55.0)


def _volatility_score(mi: Dict[str, Any]) -> float:
    """Inverse volatility score — lower volatility → higher score for entries."""
    v_regime = mi.get("volatility_regime", "NORMAL_VOLATILITY")
    vix = _f(mi.get("vix_value")) or 18.0
    base = {
        "LOW_VOLATILITY":    80.0, "NORMAL_VOLATILITY": 60.0,
        "ELEVATED":          40.0, "HIGH_VOLATILITY":   25.0, "UNKNOWN": 50.0,
    }.get(v_regime, 50.0)
    vix_adj = max(0.0, (20.0 - vix) * 1.5)
    return _clamp(base + vix_adj)


def _portfolio_impact_score(portfolio: Dict[str, Any], risk_snap: Dict[str, Any]) -> float:
    """Score based on remaining capital and utilisation."""
    util = _f((risk_snap.get("capital_utilisation") or {}).get("utilisation_pct")) or 0.0
    positions = portfolio.get("positions") or []
    n_pos = len(positions)
    util_score = _clamp(100.0 - util)   # less utilised = higher score
    pos_score  = _clamp(100.0 - n_pos * 8.0)  # fewer positions = more room
    return _clamp((util_score * 0.6 + pos_score * 0.4))


# ── Overall score + confidence ─────────────────────────────────────────────────

def compute_scores(
    symbol: str,
    mi: Dict, strategy: Dict, risk: Dict, research: Dict, portfolio: Dict
) -> Dict[str, float]:
    strat_score, best_strat = _strategy_score_for(symbol, strategy)
    components = {
        "market":           _market_score(mi),
        "strategy":         strat_score,
        "risk":             _risk_score(risk),
        "research":         _research_score(research),
        "liquidity":        _liquidity_score(mi),
        "volatility":       _volatility_score(mi),
        "portfolio_impact": _portfolio_impact_score(portfolio, risk),
    }
    overall = sum(components[k] * SCORE_WEIGHTS[k] for k in components)
    return {**components, "overall": round(overall, 1), "_best_strategy": best_strat}


def compute_confidence(scores: Dict[str, float], conflicting: bool) -> float:
    """Confidence = normalised overall × penalty for conflict."""
    base = scores["overall"] / 100.0
    conflict_penalty = 0.15 if conflicting else 0.0
    # Strategy + market agreement bonus
    strat_market_diff = abs(scores["strategy"] - scores["market"])
    divergence_penalty = (strat_market_diff / 100.0) * 0.10
    return round(_clamp(base - conflict_penalty - divergence_penalty, 0.0, 1.0), 3)


# ── Decision type assignment ───────────────────────────────────────────────────

def assign_decision_type(
    symbol: str,
    scores: Dict[str, float],
    risk_snap: Dict,
    portfolio: Dict,
    monitoring_snap: Dict,
) -> str:
    overall  = scores["overall"]
    risk_lv  = risk_snap.get("risk_level", "UNKNOWN")
    strategy = scores["strategy"]
    market   = scores["market"]

    # Check if symbol is an open position
    positions = portfolio.get("positions") or {}
    if isinstance(positions, dict):
        has_position = symbol in positions
    elif isinstance(positions, list):
        has_position = any(p.get("symbol") == symbol for p in positions)
    else:
        has_position = False

    # Check for breakdown events
    breakdowns = monitoring_snap.get("breakdowns") or []
    has_breakdown = any(b.get("symbol") == symbol for b in breakdowns)

    # Decision logic (priority order)
    if risk_lv == "CRITICAL" or overall < 25:
        return "AVOID"
    if has_position and (risk_lv == "HIGH" or overall < 35):
        return "REDUCE_EXPOSURE"
    if has_breakdown and has_position:
        return "SELL_CANDIDATE"
    if overall < 42:
        return "NO_ACTION"
    if 42 <= overall < 52:
        return "WATCH"
    if 52 <= overall < 62 and risk_lv not in ("HIGH", "CRITICAL"):
        return "ACCUMULATE"
    if overall >= 62 and risk_lv in ("LOW", "MODERATE") and strategy >= 55 and market >= 50:
        return "BUY_CANDIDATE"
    if has_position and strategy < 35:
        return "SELL_CANDIDATE"
    return "WATCH"


# ── Recommendation expiry ──────────────────────────────────────────────────────

def compute_expiry(decision_type: str, session_info: Dict) -> Tuple[str, str]:
    """Return (expiry_iso, expiry_reason)."""
    now = datetime.now(timezone.utc)
    durations = {
        "BUY_CANDIDATE":    timedelta(hours=2),
        "SELL_CANDIDATE":   timedelta(hours=1),
        "ACCUMULATE":       timedelta(hours=4),
        "WATCH":            timedelta(hours=6),
        "REDUCE_EXPOSURE":  timedelta(minutes=30),
        "AVOID":            timedelta(hours=8),
        "NO_ACTION":        timedelta(hours=1),
    }
    delta = durations.get(decision_type, timedelta(hours=2))
    reasons = {
        "BUY_CANDIDATE":    "Market conditions change rapidly; reassess after 2 hours",
        "SELL_CANDIDATE":   "Exit window is time-sensitive; expires in 1 hour",
        "ACCUMULATE":       "Accumulation window — expires if regime shifts",
        "WATCH":            "Monitor for 6 hours; re-evaluate on next scan",
        "REDUCE_EXPOSURE":  "Urgent — reduce within 30 minutes or risk worsens",
        "AVOID":            "Risk conditions persist; refresh after 8 hours",
        "NO_ACTION":        "No signal; refresh on next scan cycle",
    }
    expiry = now + delta
    return (
        expiry.strftime("%Y-%m-%dT%H:%M:%SZ"),
        reasons.get(decision_type, "Expires with next scan cycle"),
    )


# ── Priority ───────────────────────────────────────────────────────────────────

def assign_priority(decision_type: str, overall_score: float, confidence: float) -> int:
    """Priority 1 (highest) to 5 (lowest)."""
    urgency = {
        "REDUCE_EXPOSURE": 1, "SELL_CANDIDATE": 1, "AVOID": 2,
        "BUY_CANDIDATE":   2, "ACCUMULATE":     3, "WATCH": 4, "NO_ACTION": 5,
    }.get(decision_type, 5)
    score_boost = -1 if overall_score > 75 and confidence > 0.7 else 0
    return max(1, min(5, urgency + score_boost))


# ── Ranking ────────────────────────────────────────────────────────────────────

def rank_recommendations(recs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Rank by 6 criteria:
      1. Highest confidence
      2. Highest quality (overall score)
      3. Lowest risk (risk_score proxy)
      4. Best reward/risk
      5. Highest liquidity
      6. Best market alignment
    """
    def _rank_key(r: Dict) -> tuple:
        s = r.get("scores") or {}
        conf = -(r.get("confidence") or 0.0)       # 1. highest first
        qual = -(r.get("overall_score") or 0.0)    # 2. highest first
        risk = (s.get("risk") or 50.0)             # 3. highest risk score = lower risk (invert risk level)
        rr   = -(r.get("reward_risk_ratio") or 0.0)  # 4. highest first
        liq  = -(s.get("liquidity") or 50.0)       # 5. highest first
        mkt  = -(s.get("market") or 50.0)          # 6. highest first
        return (conf, qual, -risk, rr, liq, mkt)

    return sorted(recs, key=_rank_key)
