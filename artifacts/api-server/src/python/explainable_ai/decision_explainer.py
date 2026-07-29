"""
decision_explainer.py — Phase 7.4
Core decision explanation engine.

Reads signal data from signals_store (cached) and upstream snapshots,
builds a structured ExplainableDecision. Never re-runs expensive analytics.

READ-ONLY. ADVISORY-ONLY.
"""
from __future__ import annotations
from typing import Optional
from .models import (
    ExplainableDecision, DecisionTreeNode,
    BUY_SIGNALS, SELL_SIGNALS,
    explainability_grade, RISK_LOW, RISK_MEDIUM, RISK_HIGH,
)


def _load_signal(symbol: str) -> Optional[dict]:
    """Find the most recent signal for a symbol from cached signals. Never raises."""
    try:
        import signals_store
        signals = signals_store.load_signals() or []
        sym_upper = symbol.upper().strip()
        for sig in signals:
            if isinstance(sig, dict) and sig.get("stock", "").upper() == sym_upper:
                return sig
    except Exception:
        pass
    return None


def _load_all_signals() -> list:
    """Load all cached signals. Never raises."""
    try:
        import signals_store
        return signals_store.load_signals() or []
    except Exception:
        return []


def _build_decision_tree(signal: dict, market_snap: dict, macro_snap: dict, risk_snap: dict) -> dict:
    """Build a nested decision tree dict."""
    sig_type = signal.get("signal", "NO_TRADE")
    confidence = float(signal.get("confidence", 50.0))
    expl = signal.get("explanation", {}) or {}

    # Determine overall direction
    if sig_type in BUY_SIGNALS:
        direction = "BULLISH"
    elif sig_type in SELL_SIGNALS:
        direction = "BEARISH"
    else:
        direction = "NEUTRAL"

    # Root node
    root = DecisionTreeNode(
        label=f"Signal: {sig_type}",
        contribution_score=confidence,
        direction=direction,
        evidence=f"Overall confidence: {confidence:.0f}/100",
    )

    # Technical branch
    trend_desc    = expl.get("trend", "")
    momentum_desc = expl.get("momentum", "")
    volume_desc   = expl.get("volume", "")
    tech_score    = min(100.0, confidence * 0.5 + 10)
    tech_branch   = DecisionTreeNode(
        label="Technical Analysis",
        contribution_score=round(tech_score, 1),
        direction=direction,
        evidence=expl.get("indicator_summary", ""),
        children=[
            DecisionTreeNode("Trend",    round(tech_score * 0.40, 1), direction, evidence=trend_desc),
            DecisionTreeNode("Momentum", round(tech_score * 0.35, 1), direction, evidence=momentum_desc),
            DecisionTreeNode("Volume",   round(tech_score * 0.25, 1), direction, evidence=volume_desc),
        ]
    )

    # Market context branch
    mkt_score = float(market_snap.get("market_health_score", 50.0))
    mkt_direction = (
        "BULLISH" if mkt_score >= 60 else
        "BEARISH" if mkt_score < 40 else "NEUTRAL"
    )
    mkt_branch = DecisionTreeNode(
        label="Market Context",
        contribution_score=round(mkt_score * 0.25, 1),
        direction=mkt_direction,
        evidence=f"Market health: {mkt_score:.0f}/100 ({market_snap.get('grade', 'D')})",
    )

    # Macro branch
    macro_score = float(macro_snap.get("macro_score", 50.0))
    macro_direction = "BULLISH" if macro_score >= 60 else "BEARISH" if macro_score < 40 else "NEUTRAL"
    macro_branch = DecisionTreeNode(
        label="Macro Environment",
        contribution_score=round(macro_score * 0.15, 1),
        direction=macro_direction,
        evidence=f"Macro score: {macro_score:.0f}/100. VIX: {macro_snap.get('india_vix', 18.0):.1f}. "
                 f"FII: {macro_snap.get('fii_posture', 'NEUTRAL')}",
    )

    # Risk branch
    risk_score = float(risk_snap.get("risk_optimisation_score", 50.0))
    risk_direction = "BULLISH" if risk_score >= 60 else "NEUTRAL"
    risk_branch = DecisionTreeNode(
        label="Risk Assessment",
        contribution_score=round(risk_score * 0.10, 1),
        direction=risk_direction,
        evidence=f"Risk score: {risk_score:.0f}/100. Max drawdown: {risk_snap.get('max_drawdown', 0):.1%}",
    )

    root.children = [tech_branch, mkt_branch, macro_branch, risk_branch]
    return root.to_dict()


def explain_decision(symbol: str,
                     market_snap: dict,
                     event_snap: dict,
                     macro_snap: dict,
                     risk_snap: dict) -> ExplainableDecision:
    """
    Build a full ExplainableDecision for a given symbol.
    All data comes from cached signals + upstream snapshots — no recomputation.
    """
    signal = _load_signal(symbol)

    if signal is None:
        # Return a minimal explanation when no signal is available
        return ExplainableDecision(
            symbol=symbol,
            signal_type="NO_TRADE",
            primary_reason="No active signal found for this symbol in the latest scan.",
            secondary_reasons=["Symbol may not have been included in the last scan.",
                               "Run a fresh scan to generate a signal."],
            supporting_indicators=[],
            supporting_market_conditions=[],
            supporting_events=[],
            supporting_macro_conditions=[],
            ai_score=0.0,
            strategy_score=0.0,
            risk_score=risk_snap.get("risk_optimisation_score", 0.0),
            final_confidence=0.0,
            explainability_score=0.0,
            grade="D",
            decision_tree={},
            plain_english_summary=f"No signal exists for {symbol}. Run a fresh scan to generate one.",
        )

    sig_type   = signal.get("signal", "NO_TRADE")
    confidence = float(signal.get("confidence", 50.0))
    reasons    = signal.get("reasons", []) or []
    expl       = signal.get("explanation", {}) or {}
    risk_level = signal.get("risk_level", RISK_MEDIUM)

    # Primary reason
    primary_reason = (
        expl.get("plain_english") or
        (reasons[0] if reasons else f"{sig_type} signal generated with confidence {confidence:.0f}/100")
    )

    # Secondary reasons
    secondary_reasons = []
    for r in (reasons or [])[:5]:
        if r and r != primary_reason:
            secondary_reasons.append(r)
    if expl.get("trend"):
        secondary_reasons.append(expl["trend"])
    if expl.get("momentum"):
        secondary_reasons.append(expl["momentum"])
    secondary_reasons = list(dict.fromkeys(secondary_reasons))[:6]  # dedup

    # Supporting indicators
    supporting_indicators = []
    ind_summary = expl.get("indicator_summary", "")
    if ind_summary:
        supporting_indicators.append(ind_summary)
    regime_impact = expl.get("regime_impact", "")
    if regime_impact:
        supporting_indicators.append(regime_impact)
    if expl.get("volume"):
        supporting_indicators.append(expl["volume"])

    # Market conditions
    mkt_health = float(market_snap.get("market_health_score", 50.0))
    market_conditions = [
        f"Market health: {mkt_health:.0f}/100 ({market_snap.get('grade', 'D')})",
        f"Market outlook: {market_snap.get('overall_outlook', 'Unknown')}",
    ]
    if market_snap.get("top_opportunity"):
        market_conditions.append(f"Top opportunity: {market_snap['top_opportunity']}")

    # Event conditions
    event_conditions = [
        f"Event intelligence score: {event_snap.get('intelligence_score', 0):.0f}/100",
        f"Active events: {event_snap.get('total_events', 0)} "
        f"({event_snap.get('high_priority_count', 0)} high priority)",
    ]
    if event_snap.get("bullish_count", 0) > event_snap.get("bearish_count", 0):
        event_conditions.append("More bullish events than bearish events in play.")
    elif event_snap.get("bearish_count", 0) > event_snap.get("bullish_count", 0):
        event_conditions.append("More bearish events than bullish events — watch for headwinds.")

    # Macro conditions
    macro_conds = [
        f"Macro score: {macro_snap.get('macro_score', 0):.0f}/100 ({macro_snap.get('grade', 'D')})",
        f"India VIX: {macro_snap.get('india_vix', 18.0):.1f} ({macro_snap.get('vix_risk_level', 'MEDIUM')} risk)",
        f"FII posture: {macro_snap.get('fii_posture', 'NEUTRAL')}",
        f"Global sentiment: {macro_snap.get('sentiment_label', 'NEUTRAL')} "
        f"({macro_snap.get('global_sentiment_score', 50):.0f}/100)",
    ]
    if macro_snap.get("inflation_risk") == "HIGH":
        macro_conds.append("High inflation risk — monitor commodity-sensitive positions.")

    # Scores
    ai_score       = confidence
    strategy_score = min(100.0, confidence * 0.9 + mkt_health * 0.1)
    risk_score_val = float(risk_snap.get("risk_optimisation_score", 50.0))

    # Explainability score: how well-supported is this explanation?
    data_coverage = min(100.0,
        20  # base
        + (10 if signal else 0)
        + (15 if market_snap.get("available") else 0)
        + (15 if event_snap.get("available") else 0)
        + (15 if macro_snap.get("available") else 0)
        + (15 if risk_snap.get("risk_optimisation_score", 0) > 0 else 0)
        + (10 if reasons else 0)
    )

    grade = explainability_grade(data_coverage)

    # Decision tree
    tree = _build_decision_tree(signal, market_snap, macro_snap, risk_snap)

    # Normalised confidence (0-1)
    conf_norm = confidence / 100.0 if confidence > 1.0 else confidence

    return ExplainableDecision(
        symbol=symbol,
        signal_type=sig_type,
        primary_reason=primary_reason,
        secondary_reasons=secondary_reasons,
        supporting_indicators=supporting_indicators,
        supporting_market_conditions=market_conditions,
        supporting_events=event_conditions,
        supporting_macro_conditions=macro_conds,
        ai_score=round(ai_score, 1),
        strategy_score=round(strategy_score, 1),
        risk_score=round(risk_score_val, 1),
        final_confidence=round(confidence, 1),
        explainability_score=round(data_coverage, 1),
        grade=grade,
        decision_tree=tree,
        plain_english_summary=primary_reason,
        confidence=round(conf_norm, 4),
        risk_level=risk_level,
        price=float(signal.get("price", 0) or 0) or None,
        target=float(signal.get("target", 0) or 0) or None,
        stop_loss=float(signal.get("stop_loss", 0) or 0) or None,
        regime=signal.get("regime", "NEUTRAL") or "NEUTRAL",
    )


def get_all_explainable_decisions(market_snap: dict, event_snap: dict,
                                  macro_snap: dict, risk_snap: dict) -> list:
    """Return explanation objects for all signals in the latest scan."""
    signals = _load_all_signals()
    results = []
    for sig in signals:
        sym = sig.get("stock", "")
        if not sym:
            continue
        try:
            dec = explain_decision(sym, market_snap, event_snap, macro_snap, risk_snap)
            results.append(dec.to_dict())
        except Exception:
            continue
    return results
