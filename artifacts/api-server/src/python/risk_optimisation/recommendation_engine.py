"""
recommendation_engine.py — Phase 6.4
Explainable advisory recommendations for risk optimisation.

Every recommendation:
  - Includes reason, supporting metrics, historical evidence, confidence,
    expected benefit, risk reduction, and priority.
  - Is advisory_only=True. Never auto-applied.

READ-ONLY. ADVISORY-ONLY.
"""
from __future__ import annotations
from typing import List
from .risk_models import RiskRecommendation

DEFAULT_CAPITAL = 500_000.0


def generate_risk_recommendations(
    capital: dict,
    position: dict,
    concentration: dict,
    drawdown: dict,
    stop_loss: dict,
    targets: dict,
) -> List[RiskRecommendation]:
    """
    Generate advisory recommendations from aggregated analytics dicts.
    Returns a list of RiskRecommendation objects (advisory_only=True always).
    """
    recs: List[RiskRecommendation] = []

    _add_capital_recs(recs, capital)
    _add_position_recs(recs, position, capital)
    _add_concentration_recs(recs, concentration)
    _add_drawdown_recs(recs, drawdown)
    _add_stop_loss_recs(recs, stop_loss)
    _add_target_recs(recs, targets)
    _add_risk_budget_recs(recs, capital, drawdown, concentration)
    _add_diversification_recs(recs, concentration)

    # Sort: HIGH priority first, then MEDIUM, then LOW
    order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
    recs.sort(key=lambda r: order.get(r.priority, 2))

    return recs


# ---------------------------------------------------------------------------
# Internal generators
# ---------------------------------------------------------------------------

def _add_capital_recs(recs: list, cap: dict) -> None:
    util = cap.get("capital_utilisation_rate", 0.0)
    kelly = cap.get("kelly_fraction", 0.0)
    rec_alloc = cap.get("recommended_allocation", 0.0)
    avg_cap = cap.get("avg_capital_usage", 0.0)
    n = cap.get("total_trades", 0)
    if n == 0:
        return

    if util < 0.30:
        recs.append(RiskRecommendation(
            category="CapitalAllocation",
            recommendation="Increase capital deployment — current utilisation is very low.",
            rationale=f"Average capital utilisation is {util:.1%}, leaving significant idle capital.",
            current_value=f"{util:.1%} utilisation",
            suggested_value="Target 40–60% utilisation",
            confidence="MEDIUM",
            expected_benefit="Higher returns from capital put to work.",
            risk_reduction="Low — higher deployment increases exposure.",
            priority="MEDIUM",
        ))
    elif util > 0.80:
        recs.append(RiskRecommendation(
            category="CapitalAllocation",
            recommendation="Reduce capital deployment — over-utilisation increases drawdown risk.",
            rationale=f"Capital utilisation at {util:.1%} leaves insufficient buffer for adverse moves.",
            current_value=f"{util:.1%} utilisation",
            suggested_value="Target 50–70% utilisation",
            confidence="HIGH",
            expected_benefit="Lower drawdown risk and improved recovery speed.",
            risk_reduction="Significant — maintains cash buffer for recovery.",
            priority="HIGH",
        ))

    if kelly > 0 and abs(avg_cap - rec_alloc) / DEFAULT_CAPITAL > 0.05:
        recs.append(RiskRecommendation(
            category="CapitalAllocation",
            recommendation=f"Align position sizing with Kelly-based recommended allocation (₹{rec_alloc:,.0f}).",
            rationale="Kelly criterion optimises long-run capital growth based on your historical win rate and reward/risk ratio.",
            current_value=f"Avg ₹{avg_cap:,.0f}",
            suggested_value=f"₹{rec_alloc:,.0f} per trade",
            confidence="MEDIUM",
            expected_benefit="Optimal long-run capital growth.",
            risk_reduction="Moderate — prevents over-sizing on individual trades.",
            priority="MEDIUM",
        ))


def _add_position_recs(recs: list, pos: dict, cap: dict) -> None:
    n = pos.get("total_trades", 0)
    if n == 0:
        return
    largest_pct = pos.get("largest_position_pct_of_capital", 0.0)
    risk_per_trade = pos.get("avg_risk_per_trade_pct", 0.0)
    max_safe = pos.get("max_safe_position", 0.0)
    avg_win_pos = pos.get("avg_winning_position", 0.0)
    avg_loss_pos = pos.get("avg_losing_position", 0.0)

    if largest_pct > 0.25:
        recs.append(RiskRecommendation(
            category="PositionSizing",
            recommendation="Reduce maximum single position size to ≤20% of capital.",
            rationale=f"Largest position is {largest_pct:.1%} of capital — concentration risk is elevated.",
            current_value=f"{largest_pct:.1%} of capital",
            suggested_value="≤20% of capital",
            confidence="HIGH",
            expected_benefit="Limits catastrophic loss from any single trade.",
            risk_reduction="High — protects against concentrated position reversal.",
            priority="HIGH",
        ))

    if risk_per_trade > 0.02:
        recs.append(RiskRecommendation(
            category="PositionSizing",
            recommendation="Apply 2% rule — risk no more than 2% of capital per trade.",
            rationale=f"Average risk per trade is {risk_per_trade:.1%} — exceeding 2% accelerates drawdown.",
            current_value=f"{risk_per_trade:.1%} avg risk per trade",
            suggested_value="≤2% risk per trade",
            confidence="HIGH",
            expected_benefit="Preserves capital during losing streaks.",
            risk_reduction="High — mathematical protection against ruin.",
            priority="HIGH",
        ))

    if avg_win_pos > avg_loss_pos * 1.5 and avg_loss_pos > 0:
        recs.append(RiskRecommendation(
            category="PositionSizing",
            recommendation="Consider increasing position size on high-confidence setups.",
            rationale="Winning positions are significantly larger than losing ones — sizing up on wins could improve returns.",
            current_value=f"Win pos: ₹{avg_win_pos:,.0f} vs Loss pos: ₹{avg_loss_pos:,.0f}",
            suggested_value="Scale up 20–30% on highest-confidence signals",
            confidence="LOW",
            expected_benefit="Improved return on winning trades.",
            risk_reduction="Neutral — maintain strict max position limits.",
            priority="LOW",
        ))


def _add_concentration_recs(recs: list, conc: dict) -> None:
    n = conc.get("total_trades", 0)
    if n == 0:
        return
    corr_risk = conc.get("correlation_risk", "LOW")
    max_sec = conc.get("max_sector_concentration_pct", 0.0)
    single_pos = conc.get("single_position_max_pct", 0.0)
    hhi_sec = conc.get("hhi_sector", 0.0)

    if corr_risk == "HIGH":
        recs.append(RiskRecommendation(
            category="Concentration",
            recommendation="Diversify across more sectors — correlation risk is HIGH.",
            rationale=f"Dominant sector accounts for {max_sec:.1%} of trades — highly correlated portfolio.",
            current_value=f"{max_sec:.1%} in top sector",
            suggested_value="No sector > 30% of portfolio",
            confidence="HIGH",
            expected_benefit="Reduces correlated drawdown in sector-specific events.",
            risk_reduction="High — sector events won't devastate the whole portfolio.",
            priority="HIGH",
        ))
    elif corr_risk == "MEDIUM":
        recs.append(RiskRecommendation(
            category="Concentration",
            recommendation="Improve sector diversification to reduce correlation risk.",
            rationale=f"Sector HHI of {hhi_sec:.2f} indicates moderate concentration.",
            current_value=f"HHI sector: {hhi_sec:.2f}",
            suggested_value="Target HHI < 0.20",
            confidence="MEDIUM",
            expected_benefit="More stable returns across different market conditions.",
            risk_reduction="Moderate.",
            priority="MEDIUM",
        ))


def _add_drawdown_recs(recs: list, dd: dict) -> None:
    max_dd = dd.get("max_drawdown", 0.0)
    avg_dd = dd.get("avg_drawdown", 0.0)
    freq = dd.get("drawdown_frequency_per_10", 0.0)
    rec_eff = dd.get("recovery_efficiency", 1.0)

    if max_dd > 0.20:
        recs.append(RiskRecommendation(
            category="Drawdown",
            recommendation="Implement a daily loss limit to prevent drawdowns exceeding 20%.",
            rationale=f"Maximum drawdown of {max_dd:.1%} indicates insufficient loss controls.",
            current_value=f"Max DD: {max_dd:.1%}",
            suggested_value="Stop trading for the day after 5% drawdown",
            confidence="HIGH",
            expected_benefit="Prevents catastrophic equity destruction.",
            risk_reduction="Critical — preserves capital for recovery.",
            priority="HIGH",
        ))
    elif max_dd > 0.10:
        recs.append(RiskRecommendation(
            category="Drawdown",
            recommendation="Consider a 10% daily drawdown circuit breaker.",
            rationale=f"Maximum drawdown of {max_dd:.1%} is above the 10% comfort threshold.",
            current_value=f"Max DD: {max_dd:.1%}",
            suggested_value="Pause and review after 10% drawdown",
            confidence="MEDIUM",
            expected_benefit="Prevents emotional trading during losing periods.",
            risk_reduction="Moderate.",
            priority="MEDIUM",
        ))

    if rec_eff < 0.60:
        recs.append(RiskRecommendation(
            category="Drawdown",
            recommendation="Improve recovery strategy — fewer than 60% of drawdowns fully recover.",
            rationale=f"Recovery efficiency is {rec_eff:.1%} — many drawdown periods remain unresolved.",
            current_value=f"Recovery rate: {rec_eff:.1%}",
            suggested_value="Review strategy behaviour during drawdown periods",
            confidence="MEDIUM",
            expected_benefit="Faster return to equity peak.",
            risk_reduction="Moderate.",
            priority="MEDIUM",
        ))


def _add_stop_loss_recs(recs: list, sl: dict) -> None:
    sl_rate = sl.get("stop_loss_rate", 0.0)
    avg_loss_pct = sl.get("avg_loss_pct_on_sl", 0.0)
    premature = sl.get("premature_exits", 0)
    late = sl.get("late_exits", 0)
    sl_qual = sl.get("stop_loss_quality_score", 0.5)

    if sl_qual < 0.40:
        recs.append(RiskRecommendation(
            category="StopLoss",
            recommendation="Review and optimise stop loss placement — quality score is below threshold.",
            rationale=sl.get("advisory", ""),
            current_value=f"SL rate: {sl_rate:.1%}, avg loss: {avg_loss_pct:.2%}",
            suggested_value="Use ATR-based stops or 1.5× average range",
            confidence="MEDIUM",
            expected_benefit="Reduces average loss per stopped trade.",
            risk_reduction="Significant — properly placed stops limit downside.",
            priority="HIGH",
        ))

    if premature > late and sl.get("total_trades", 0) > 10:
        recs.append(RiskRecommendation(
            category="StopLoss",
            recommendation="Widen stop loss distance — premature exits outnumber late exits.",
            rationale="Stops triggered before the trade had time to work suggest stops are too tight.",
            current_value=f"{premature} premature vs {late} late exits",
            suggested_value="Increase stop distance by 20–30%",
            confidence="MEDIUM",
            expected_benefit="Fewer false exits; more trades reach their targets.",
            risk_reduction="Low — slightly more per-trade risk, better overall efficiency.",
            priority="MEDIUM",
        ))


def _add_target_recs(recs: list, tgt: dict) -> None:
    rr = tgt.get("reward_risk_ratio", 0.0)
    early = tgt.get("early_profit_booking", 0)
    n = tgt.get("total_trades", 0)
    if n == 0:
        return

    if rr < 1.5:
        recs.append(RiskRecommendation(
            category="Target",
            recommendation="Improve reward/risk ratio — target at least 1.5× per trade.",
            rationale=f"Current R:R of {rr:.2f} is below the 1.5 benchmark for sustainable trading.",
            current_value=f"R:R: {rr:.2f}",
            suggested_value="Set minimum target at 1.5× stop distance",
            confidence="HIGH",
            expected_benefit="Positive expectancy even with a 40% win rate.",
            risk_reduction="High — positive R:R is the mathematical foundation of profitability.",
            priority="HIGH" if rr < 1.0 else "MEDIUM",
        ))

    if early > n * 0.30:
        recs.append(RiskRecommendation(
            category="Target",
            recommendation="Reduce early profit booking — >30% of wins exit too early.",
            rationale="Early exits cap profits on winning trades, undermining the reward/risk ratio.",
            current_value=f"{early} early exits ({early/n:.1%} of trades)",
            suggested_value="Use trailing stops instead of fixed targets",
            confidence="MEDIUM",
            expected_benefit="Allows winners to run further.",
            risk_reduction="Neutral — trailing stops maintain downside protection.",
            priority="MEDIUM",
        ))


def _add_risk_budget_recs(recs: list, cap: dict, dd: dict, conc: dict) -> None:
    n = cap.get("total_trades", 0)
    if n == 0:
        return
    max_dd = dd.get("max_drawdown", 0.0)
    hhi_strat = conc.get("hhi_strategy", 0.0)

    if hhi_strat > 0.60:
        recs.append(RiskRecommendation(
            category="RiskBudget",
            recommendation="Diversify across more strategies to reduce strategy-level concentration.",
            rationale=f"Strategy HHI of {hhi_strat:.2f} — over-reliance on a single strategy.",
            current_value=f"HHI strategy: {hhi_strat:.2f}",
            suggested_value="Target HHI < 0.33 (at least 3 active strategies)",
            confidence="MEDIUM",
            expected_benefit="Reduces strategy-specific underperformance risk.",
            risk_reduction="Moderate.",
            priority="MEDIUM",
        ))

    if max_dd > 0.05:
        recs.append(RiskRecommendation(
            category="RiskBudget",
            recommendation="Set a maximum portfolio risk budget of 2% per day.",
            rationale=f"With a max drawdown of {max_dd:.1%}, daily risk must be explicitly bounded.",
            current_value="No explicit daily risk budget",
            suggested_value="Maximum 2% portfolio risk per day; maximum 20% open exposure",
            confidence="HIGH",
            expected_benefit="Systematic loss prevention across all strategies.",
            risk_reduction="High — prevents compounding losses.",
            priority="HIGH" if max_dd > 0.15 else "MEDIUM",
        ))


def _add_diversification_recs(recs: list, conc: dict) -> None:
    div_score = conc.get("diversification_score", 0.0)
    n = conc.get("total_trades", 0)
    if n == 0:
        return
    unique_syms = conc.get("unique_symbols", 0)

    if div_score < 0.40:
        recs.append(RiskRecommendation(
            category="Diversification",
            recommendation="Significantly improve portfolio diversification.",
            rationale=f"Diversification score of {div_score:.2f}/1.0 indicates high concentration risk.",
            current_value=f"Div score: {div_score:.2f}, {unique_syms} symbols",
            suggested_value="Target ≥ 5 symbols across ≥ 3 sectors",
            confidence="HIGH",
            expected_benefit="Reduces idiosyncratic risk from single stocks/sectors.",
            risk_reduction="High.",
            priority="HIGH",
        ))
    elif div_score < 0.65:
        recs.append(RiskRecommendation(
            category="Diversification",
            recommendation="Moderately improve diversification across sectors and strategies.",
            rationale=f"Diversification score of {div_score:.2f}/1.0 has room for improvement.",
            current_value=f"Div score: {div_score:.2f}",
            suggested_value="Target diversification score ≥ 0.65",
            confidence="MEDIUM",
            expected_benefit="More consistent returns across market conditions.",
            risk_reduction="Moderate.",
            priority="LOW",
        ))
