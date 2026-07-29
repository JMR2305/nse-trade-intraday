"""Phase 7.5 – Strategy comparison engine (read-only, advisory-only)."""
from __future__ import annotations
from typing import Any, Dict, List

from .models import (
    StrategyProfile, ALL_STRATEGIES,
    STRATEGY_TREND_FOLLOWING, STRATEGY_MEAN_REVERSION, STRATEGY_MOMENTUM,
    STRATEGY_BREAKOUT, STRATEGY_RANGE_TRADING, STRATEGY_VOLATILITY_BASED,
    STRATEGY_SECTOR_ROTATION, research_grade,
)

_STRATEGY_META: Dict[str, Dict[str, Any]] = {
    STRATEGY_TREND_FOLLOWING: {
        "label": "Trend Following",
        "description": "Follows established price trends using EMA crossovers and Supertrend.",
        "regime_keywords": ["TRENDING_UP", "MOMENTUM"],
        "best_regime": "TRENDING_UP",
        "worst_regime": "RANGE",
        "risk_baseline": 0.35,
    },
    STRATEGY_MEAN_REVERSION: {
        "label": "Mean Reversion",
        "description": "Exploits price deviations from moving averages expecting reversion.",
        "regime_keywords": ["MEAN_REVERSION", "RANGE"],
        "best_regime": "RANGE",
        "worst_regime": "TRENDING_UP",
        "risk_baseline": 0.40,
    },
    STRATEGY_MOMENTUM: {
        "label": "Momentum",
        "description": "Captures accelerating price and volume momentum signals.",
        "regime_keywords": ["MOMENTUM", "TRENDING_UP"],
        "best_regime": "MOMENTUM",
        "worst_regime": "HIGH_VOLATILITY",
        "risk_baseline": 0.45,
    },
    STRATEGY_BREAKOUT: {
        "label": "Breakout",
        "description": "Enters on breakouts above resistance or below support levels.",
        "regime_keywords": ["TRENDING_UP", "HIGH_VOLATILITY"],
        "best_regime": "TRENDING_UP",
        "worst_regime": "RANGE",
        "risk_baseline": 0.50,
    },
    STRATEGY_RANGE_TRADING: {
        "label": "Range Trading",
        "description": "Buys support and sells resistance in a defined price range.",
        "regime_keywords": ["RANGE", "MEAN_REVERSION"],
        "best_regime": "RANGE",
        "worst_regime": "TRENDING_UP",
        "risk_baseline": 0.30,
    },
    STRATEGY_VOLATILITY_BASED: {
        "label": "Volatility Based",
        "description": "Adjusts position sizing and entries based on ATR and VIX regime.",
        "regime_keywords": ["HIGH_VOLATILITY", "TRENDING_DOWN"],
        "best_regime": "HIGH_VOLATILITY",
        "worst_regime": "LOW_VOLATILITY",
        "risk_baseline": 0.55,
    },
    STRATEGY_SECTOR_ROTATION: {
        "label": "Sector Rotation",
        "description": "Rotates capital into outperforming sectors using breadth signals.",
        "regime_keywords": ["TRENDING_UP", "MOMENTUM", "MEAN_REVERSION"],
        "best_regime": "TRANSITION",
        "worst_regime": "BEAR",
        "risk_baseline": 0.38,
    },
}


def _classify_regime(signal: Dict[str, Any]) -> str:
    regime = (signal.get("regime") or "NEUTRAL").upper()
    if regime in ("TRENDING_UP", "MOMENTUM"): return "TRENDING_UP"
    if regime in ("TRENDING_DOWN", "BEAR"):   return "TRENDING_DOWN"
    if regime in ("MEAN_REVERSION", "RANGE"): return "RANGE"
    if regime == "HIGH_VOLATILITY":            return "HIGH_VOLATILITY"
    if regime == "LOW_VOLATILITY":             return "LOW_VOLATILITY"
    return "NEUTRAL"


def _strategy_matches(signal: Dict[str, Any], meta: Dict[str, Any]) -> bool:
    regime = _classify_regime(signal)
    return any(k in regime for k in meta["regime_keywords"])


def build_strategy_profiles(
    signals: List[Dict[str, Any]],
    risk_snap: Dict[str, Any],
) -> List[StrategyProfile]:
    """Build comparative profiles for all 7 strategy types."""
    max_dd    = float(risk_snap.get("max_drawdown", 0.08) or 0.08)
    max_dd    = max_dd * 100 if max_dd < 1.0 else max_dd

    profiles: List[StrategyProfile] = []

    for stype in ALL_STRATEGIES:
        meta    = _STRATEGY_META[stype]
        matched = [s for s in signals if _strategy_matches(s, meta)]
        total   = max(len(matched), 1)

        # Win rate proxy: fraction of BUY/SELL signals (not HOLD/NO_TRADE)
        actionable = [s for s in matched if s.get("signal") in ("BUY", "STRONG_BUY", "SELL", "STRONG_SELL")]
        win_rate   = len(actionable) / total

        # Average confidence
        conf_vals = []
        for s in matched:
            c = float(s.get("confidence", 0.5) or 0.5)
            conf_vals.append(c * 100 if c <= 1.0 else c)
        avg_conf = sum(conf_vals) / len(conf_vals) if conf_vals else 50.0

        # Drawdown estimate: base + risk baseline adjustment
        dd_est = max_dd * meta["risk_baseline"] / 0.40

        # Consistency: how many of the matched signals were actionable
        consistency = min(100.0, win_rate * 100 * 1.2)

        # Risk score: inverse of drawdown and risk baseline
        risk_score  = max(0.0, 100.0 - (dd_est * 5) - (meta["risk_baseline"] * 100 * 0.3))

        # Performance score: blend of win_rate + confidence + consistency
        perf_score  = min(100.0, win_rate * 40 + avg_conf * 0.4 + consistency * 0.2)

        grade = research_grade(perf_score)

        # Recommendation
        if perf_score >= 70:
            rec = f"{meta['label']} shows strong signals in the current environment."
        elif perf_score >= 50:
            rec = f"{meta['label']} shows moderate promise; consider with caution."
        else:
            rec = f"{meta['label']} is not well-suited to the current market regime."

        profiles.append(StrategyProfile(
            strategy_type=stype,
            label=meta["label"],
            description=meta["description"],
            signal_count=len(matched),
            win_rate=round(win_rate, 3),
            avg_confidence=round(avg_conf, 1),
            avg_drawdown=round(dd_est, 2),
            consistency=round(consistency, 1),
            risk_score=round(risk_score, 1),
            performance_score=round(perf_score, 1),
            grade=grade,
            best_regime=meta["best_regime"],
            worst_regime=meta["worst_regime"],
            recommendation=rec,
        ))

    # Sort by performance score descending
    profiles.sort(key=lambda p: p.performance_score, reverse=True)
    return profiles
