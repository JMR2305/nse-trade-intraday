"""Phase 7.5 – Research report generator (advisory-only, read-only)."""
from __future__ import annotations
import uuid
from typing import Any, Dict, List

from .models import ResearchReport, research_grade, trend_label


def generate_research_report(
    strategies:   List[Any],         # StrategyProfile list
    scenarios:    List[Any],         # ScenarioResult list
    risk_sim:     Any,               # RiskSimulation
    benchmark:    Any,               # BenchmarkComparison
    experiments:  List[Any],         # Experiment list
    market_snap:  Dict[str, Any],
    macro_snap:   Dict[str, Any],
    explainable_snap: Dict[str, Any],
) -> ResearchReport:
    """Auto-generate a comprehensive research report from all module outputs."""

    # ── Research score ─────────────────────────────────────────────────────────
    top_strategy = strategies[0] if strategies else None
    strat_score  = top_strategy.performance_score if top_strategy else 50.0
    xai_score    = float(explainable_snap.get("explainable_ai_score", 50.0) or 50.0)
    risk_opt     = float(explainable_snap.get("avg_confidence", 0.5) or 0.5)
    risk_opt_pct = risk_opt * 100 if risk_opt <= 1.0 else risk_opt
    bench_score  = benchmark.research_score if benchmark else 50.0

    research_score = round(
        strat_score * 0.30 + xai_score * 0.30 + risk_opt_pct * 0.20 + bench_score * 0.20,
        1
    )
    grade = research_grade(research_score)
    trend = trend_label(research_score, 55.0)

    # ── Executive summary ─────────────────────────────────────────────────────
    mkt_outlook = market_snap.get("overall_outlook", "NEUTRAL")
    vix         = macro_snap.get("india_vix", 16.0)
    fii         = macro_snap.get("fii_posture", "NEUTRAL")
    macro_trend = macro_snap.get("trend", "NEUTRAL")

    exec_summary = (
        f"ApexQuant AI Research Lab scores {research_score:.0f}/100 (grade {grade}, {trend.lower()}). "
        f"The current market outlook is {mkt_outlook} with India VIX at {vix:.1f}. "
        f"FII posture is {fii} and macro trend is {macro_trend}. "
        f"The leading strategy type in the current environment is "
        f"{top_strategy.label if top_strategy else 'undetermined'}. "
        f"All findings are advisory only and must not be actioned without operator review."
    )

    # ── Objectives ────────────────────────────────────────────────────────────
    objectives = [
        "Validate signal quality across 7 strategy archetypes",
        "Simulate performance under 8 market scenarios",
        "Assess risk distribution and expected drawdown",
        "Benchmark research score vs NIFTY baseline and paper trading",
        "Maintain experiment registry with version history",
    ]

    # ── Methodology ──────────────────────────────────────────────────────────
    methodology = (
        "This report aggregates read-only outputs from Phase 7.1 (Market Intelligence), "
        "7.2 (Event Intelligence), 7.3 (Macro Intelligence), 7.4 (Explainable AI), "
        "6.4 (Risk Optimisation), and the paper portfolio store. "
        "No re-computation is performed; all data is sourced from cached snapshots. "
        "Strategy profiles are derived from the current signal distribution. "
        "Scenario outcomes are heuristic-based advisory estimates. "
        "Risk simulation uses deterministic heuristics scaled by live VIX."
    )

    # ── Key findings ──────────────────────────────────────────────────────────
    findings = []
    if top_strategy:
        findings.append(
            f"Best-performing strategy: {top_strategy.label} "
            f"(score {top_strategy.performance_score:.0f}/100, grade {top_strategy.grade})"
        )
    if scenarios:
        top_scenario = max(scenarios, key=lambda s: s.opportunity_score)
        findings.append(
            f"Highest-opportunity scenario: {top_scenario.label} "
            f"(opportunity score {top_scenario.opportunity_score:.0f}/100)"
        )
    if risk_sim:
        findings.append(
            f"Expected drawdown: {risk_sim.expected_drawdown:.1f}%, "
            f"max estimate: {risk_sim.max_drawdown_estimate:.1f}%"
        )
    if benchmark:
        findings.append(
            f"Relative alpha vs NIFTY: {benchmark.relative_alpha:+.1f} points"
        )
    if explainable_snap.get("total_decisions", 0) > 0:
        findings.append(
            f"Active explainable decisions: {explainable_snap['total_decisions']} "
            f"(avg confidence {explainable_snap.get('avg_confidence', 0)*100:.0f}%)"
        )

    # ── Performance summary ───────────────────────────────────────────────────
    perf_summary = benchmark.narrative if benchmark else "No benchmark data available."

    # ── Risk analysis ─────────────────────────────────────────────────────────
    risk_analysis = (
        f"Expected drawdown: {risk_sim.expected_drawdown:.1f}%. "
        f"Capital usage: {risk_sim.capital_usage_pct:.0f}%. "
        f"Volatility exposure index: {risk_sim.volatility_exposure:.0f}/100. "
        f"{risk_sim.monte_carlo_note}"
    ) if risk_sim else "Risk simulation data not available."

    # ── Limitations ───────────────────────────────────────────────────────────
    limitations = [
        "Strategy profiles are derived from current signal snapshot only — not from backtested P&L data.",
        "Scenario outcomes are advisory estimates, not Monte Carlo simulations.",
        "Historical replay requires signal snapshot history; sparse in new environments.",
        "Parameter experiments use deterministic heuristics, not live signal re-evaluation.",
        "Research score does not reflect intraday execution slippage or transaction costs.",
        "All outputs are advisory only — no production impact.",
    ]

    # ── Recommendations ───────────────────────────────────────────────────────
    recs = []
    if top_strategy and top_strategy.performance_score >= 65:
        recs.append(
            f"Focus signal analysis on {top_strategy.label} conditions "
            f"(best regime: {top_strategy.best_regime})"
        )
    if risk_sim and risk_sim.expected_drawdown > 10:
        recs.append("Consider tightening stop-losses — expected drawdown is elevated")
    if benchmark and benchmark.relative_alpha < 0:
        recs.append("Review parameter thresholds — research score lags NIFTY baseline")
    if experiments:
        draft_count = sum(1 for e in experiments if e.status == "DRAFT")
        if draft_count > 0:
            recs.append(f"Progress {draft_count} draft experiment(s) to improve research coverage")
    recs.append("Run a fresh scan to keep signal data current before acting on research findings")

    return ResearchReport(
        report_id=str(uuid.uuid4())[:8],
        generated_at="now",
        research_score=research_score,
        grade=grade,
        trend=trend,
        executive_summary=exec_summary,
        objectives=objectives,
        methodology=methodology,
        key_findings=findings,
        performance_summary=perf_summary,
        risk_analysis=risk_analysis,
        limitations=limitations,
        recommendations=recs,
    )
