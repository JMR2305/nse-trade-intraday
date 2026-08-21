"""Read-only market and sector regime classification."""

from __future__ import annotations

from typing import Any, Mapping

from .contracts import advisory_output


def classify_regime(
    context: Mapping[str, Any] | None,
    *,
    scan_id: str | None = None,
    build_id: str = "phase2b-dev",
    config_hash: str = "phase2b-default",
) -> dict[str, Any]:
    context = dict(context or {})
    vix = _number(context.get("vix", context.get("india_vix")))
    trend_strength = _number(context.get("trend_strength"))
    breadth = _number(context.get("breadth_pct", context.get("market_breadth_pct")))
    index_change = _number(context.get("index_change_pct", context.get("nifty_change_pct")))
    index_trend = str(context.get("index_trend") or "").upper()
    volatility = str(context.get("volatility") or context.get("volatility_regime") or "").upper()

    if not context:
        regime = "INSUFFICIENT_CONTEXT"
        reason = "index and sector context unavailable"
        score = 0
        decision = "INSUFFICIENT_CONTEXT"
    elif volatility in {"HIGH", "HIGH_VOLATILITY", "VOLATILE"} or vix >= 25:
        regime = "VOLATILE"
        reason = "volatility context indicates elevated movement risk"
        score = 30
        decision = "WATCH"
    elif index_trend in {"WEAK", "BEAR", "DOWN"} or breadth < 35 or index_change <= -1.0:
        regime = "WEAK"
        reason = "index/breadth context is weak"
        score = 30
        decision = "WATCH"
    elif index_trend in {"TRENDING", "BULL", "UP"} or trend_strength >= 0.6 or breadth >= 60:
        regime = "TRENDING"
        reason = "trend strength or breadth supports directional movement"
        score = 80
        decision = "WATCH"
    else:
        regime = "RANGE_BOUND"
        reason = "context is available but lacks directional confirmation"
        score = 50
        decision = "WATCH"

    return advisory_output(
        symbol="__RUN__",
        bot_name="market-regime-bot",
        strategy_name="MARKET_REGIME",
        score=score,
        decision=decision,
        reason=reason,
        data_quality="PASS" if context else "INSUFFICIENT",
        risk_flags=["REGIME_CONTEXT_LIMITED"] if not context else [],
        scan_id=scan_id,
        build_id=build_id,
        config_hash=config_hash,
        regime=regime,
        vix=vix if context else None,
        trend_strength=trend_strength if context else None,
        breadth_pct=breadth if context else None,
    )


def _number(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0