"""Explainable final ranking of advisory strategy outputs."""

from __future__ import annotations

from typing import Any, Iterable, Mapping

from .contracts import advisory_output


def combine_scores(
    symbol: str,
    strategy_outputs: Iterable[Mapping[str, Any]],
    risk_output: Mapping[str, Any],
    quality_output: Mapping[str, Any],
    regime_output: Mapping[str, Any],
    *,
    scan_id: str | None = None,
    build_id: str = "phase2b-dev",
    config_hash: str = "phase2b-default",
) -> dict[str, Any]:
    strategies = [dict(item) for item in strategy_outputs]
    if quality_output.get("decision") != "WATCH":
        return advisory_output(
            symbol=symbol,
            bot_name="ai-decision-bot",
            strategy_name="ADVISORY_DECISION",
            score=0,
            decision="BLOCKED_DATA_QUALITY",
            reason=quality_output.get("reason", "data quality blocked scoring"),
            data_quality=quality_output.get("data_quality", "BLOCKED"),
            risk_flags=["DATA_QUALITY_BLOCK"],
            scan_id=scan_id,
            build_id=build_id,
            config_hash=config_hash,
            strategy_scores=[],
            final_rank=None,
        )
    if not strategies:
        return advisory_output(
            symbol=symbol,
            bot_name="ai-decision-bot",
            strategy_name="ADVISORY_DECISION",
            score=0,
            decision="INSUFFICIENT_CONTEXT",
            reason="no strategy evidence was available",
            data_quality="MISSING",
            risk_flags=["NO_STRATEGY_EVIDENCE"],
            scan_id=scan_id,
            build_id=build_id,
            config_hash=config_hash,
            strategy_scores=[],
            final_rank=None,
        )

    ranked = sorted(strategies, key=lambda item: float(item.get("score") or 0), reverse=True)
    best = ranked[0]
    average = sum(float(item.get("score") or 0) for item in ranked) / len(ranked)
    regime_factor = 0.85 if regime_output.get("regime") in {"WEAK", "VOLATILE"} else 1.0
    risk_factor = 1.0 if risk_output.get("decision") == "CANDIDATE" else 0.0
    final_score = round(min(100.0, average * 0.45 + float(best.get("score") or 0) * 0.55) * regime_factor * risk_factor, 2)
    decision = "CANDIDATE" if final_score >= 60 and risk_factor else "WATCH"
    reasons = [
        f"best strategy={best.get('strategy_name')} score={best.get('score')}",
        f"combined score={final_score:.2f}",
    ]
    if risk_factor == 0:
        reasons.append("advisory risk gate rejected the idea")
    return advisory_output(
        symbol=symbol,
        bot_name="ai-decision-bot",
        strategy_name="ADVISORY_DECISION",
        score=final_score,
        decision=decision,
        reason="; ".join(reasons),
        data_quality=quality_output.get("data_quality", "PASS"),
        risk_flags=list(risk_output.get("risk_flags") or []),
        scan_id=scan_id,
        build_id=build_id,
        config_hash=config_hash,
        final_rank=None,
        best_strategy=best.get("strategy_name"),
        strategy_scores=[
            {"strategy_name": item.get("strategy_name"), "score": item.get("score"), "decision": item.get("decision")}
            for item in ranked
        ],
        regime=regime_output.get("regime"),
    )