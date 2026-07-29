"""
recommendation_engine.py — Phase 6.3
Generate advisory optimisation recommendations across 8 dimensions.

NEVER applied automatically. ADVISORY-ONLY.

READ-ONLY. ADVISORY-ONLY.
"""
from __future__ import annotations
from collections import defaultdict
from typing import List
from .optimisation_models import OptimisationRecommendation

_INTRADAY_WINDOWS = [
    ("Opening Hour", "09:15", "10:15"),
    ("Morning",      "10:15", "11:30"),
    ("Mid Session",  "11:30", "13:00"),
    ("Afternoon",    "13:00", "14:30"),
    ("Closing Hour", "14:30", "15:30"),
]


def generate_recommendations(records: list, calibration: dict) -> List[OptimisationRecommendation]:
    recs: List[OptimisationRecommendation] = []

    if not records:
        return [_no_data_rec()]

    recs.append(_confidence_threshold_rec(records, calibration))
    recs.extend(_signal_filter_recs(records))
    recs.append(_regime_selection_rec(records))
    recs.append(_sector_selection_rec(records))
    recs.append(_time_window_rec(records))
    recs.append(_risk_threshold_rec(records))
    recs.append(_execution_threshold_rec(records))
    recs.append(_strategy_selection_rec(records))

    return [r for r in recs if r is not None]


def _no_data_rec() -> OptimisationRecommendation:
    return OptimisationRecommendation(
        category="General",
        recommendation="No trades recorded yet",
        rationale="Complete paper trades to generate advisory recommendations.",
        current_value="N/A", suggested_value="N/A", confidence="LOW",
        expected_benefit="Advisory optimisation recommendations will appear as data accumulates.",
    )


def _confidence_threshold_rec(records: list, calibration: dict) -> OptimisationRecommendation:
    threshold = calibration.get("recommended_threshold", 0.60)
    expected_wr = calibration.get("threshold_expected_win_rate", 0.0)
    rationale = calibration.get("threshold_rationale", "Based on calibration analysis.")
    current = "0.60 (default)"

    return OptimisationRecommendation(
        category="ConfidenceThreshold",
        recommendation=f"Set minimum confidence threshold to {threshold:.0%}",
        rationale=rationale,
        current_value=current,
        suggested_value=f"{threshold:.0%}",
        confidence="MEDIUM" if expected_wr < 0.55 else "HIGH",
        expected_benefit=f"Expected win rate in qualifying trades: {expected_wr*100:.1f}%",
    )


def _signal_filter_recs(records: list) -> List[OptimisationRecommendation]:
    recs = []
    # Identify regimes with consistently negative return
    regime_pnl: dict = defaultdict(list)
    for r in records:
        regime_pnl[r.market_regime].append(r.pnl_pct or 0.0)

    for regime, returns in regime_pnl.items():
        avg_ret = sum(returns) / len(returns)
        if avg_ret < -0.5 and len(returns) >= 5:
            recs.append(OptimisationRecommendation(
                category="SignalFilter",
                recommendation=f"Reduce signal generation during '{regime}' regime",
                rationale=f"Average return of {avg_ret:.2f}% across {len(returns)} trades in this regime.",
                current_value="All regimes active",
                suggested_value=f"Skip '{regime}' regime signals",
                confidence="MEDIUM",
                expected_benefit="Reduce losing trades in underperforming market conditions.",
            ))
    return recs[:2]  # cap at 2 signal filter recs


def _best_by_win_rate(records: list, key_fn) -> tuple:
    """Return (best_key, win_rate, trade_count)."""
    groups: dict = defaultdict(list)
    for r in records:
        groups[key_fn(r)].append((r.pnl or 0))

    best_key, best_wr, best_count = None, 0.0, 0
    for k, pnls in groups.items():
        if len(pnls) < 3:
            continue
        wr = sum(1 for p in pnls if p > 0) / len(pnls)
        if wr > best_wr:
            best_wr, best_key, best_count = wr, k, len(pnls)
    return best_key, best_wr, best_count


def _regime_selection_rec(records: list) -> OptimisationRecommendation:
    key, wr, cnt = _best_by_win_rate(records, lambda r: r.market_regime)
    if key is None:
        return OptimisationRecommendation(
            category="RegimeSelection",
            recommendation="Insufficient data for regime recommendation",
            rationale="Need ≥3 trades per regime.",
            current_value="All regimes", suggested_value="N/A",
            confidence="LOW", expected_benefit="N/A",
        )
    return OptimisationRecommendation(
        category="RegimeSelection",
        recommendation=f"Prioritise trading in '{key}' market regime",
        rationale=f"{wr*100:.0f}% win rate across {cnt} trades in this regime.",
        current_value="All regimes equally weighted",
        suggested_value=f"Prioritise '{key}' regime",
        confidence="HIGH" if wr >= 0.65 else "MEDIUM",
        expected_benefit=f"Expected win rate improvement by focusing on best-performing regime.",
    )


def _sector_selection_rec(records: list) -> OptimisationRecommendation:
    key, wr, cnt = _best_by_win_rate(records, lambda r: r.sector)
    if key is None:
        return OptimisationRecommendation(
            category="SectorSelection",
            recommendation="Insufficient data for sector recommendation",
            rationale="Need ≥3 trades per sector.",
            current_value="All sectors", suggested_value="N/A",
            confidence="LOW", expected_benefit="N/A",
        )
    return OptimisationRecommendation(
        category="SectorSelection",
        recommendation=f"Increase allocation to '{key}' sector",
        rationale=f"{wr*100:.0f}% win rate across {cnt} trades in this sector.",
        current_value="All sectors equally weighted",
        suggested_value=f"Overweight '{key}' sector",
        confidence="HIGH" if wr >= 0.65 else "MEDIUM",
        expected_benefit="Improve portfolio win rate by concentrating on best-performing sector.",
    )


def _time_window_rec(records: list) -> OptimisationRecommendation:
    """Map trades to intraday time buckets by approximate entry time."""
    import datetime

    def _bucket(ts_str: str) -> str:
        try:
            t = datetime.datetime.fromisoformat(ts_str)
            hm = t.hour * 60 + t.minute
            for name, start, end in _INTRADAY_WINDOWS:
                sh, sm = int(start.split(":")[0]), int(start.split(":")[1])
                eh, em = int(end.split(":")[0]),   int(end.split(":")[1])
                if sh * 60 + sm <= hm < eh * 60 + em:
                    return name
        except Exception:
            pass
        return "Unknown"

    bucket_pnl: dict = defaultdict(list)
    for r in records:
        b = _bucket(r.timestamp)
        bucket_pnl[b].append(r.pnl or 0.0)

    best_bucket, best_wr, best_cnt = None, 0.0, 0
    for b, pnls in bucket_pnl.items():
        if b == "Unknown" or len(pnls) < 3:
            continue
        wr = sum(1 for p in pnls if p > 0) / len(pnls)
        if wr > best_wr:
            best_wr, best_bucket, best_cnt = wr, b, len(pnls)

    if best_bucket is None:
        return OptimisationRecommendation(
            category="TimeWindow",
            recommendation="Insufficient data for time window recommendation",
            rationale="Need ≥3 trades per time window.",
            current_value="All windows", suggested_value="N/A",
            confidence="LOW", expected_benefit="N/A",
        )
    return OptimisationRecommendation(
        category="TimeWindow",
        recommendation=f"Focus entries during '{best_bucket}' session",
        rationale=f"{best_wr*100:.0f}% win rate across {best_cnt} trades in this window.",
        current_value="All intraday windows active",
        suggested_value=f"Prioritise '{best_bucket}'",
        confidence="HIGH" if best_wr >= 0.65 else "MEDIUM",
        expected_benefit="Align entries with the highest-performing intraday window.",
    )


def _risk_threshold_rec(records: list) -> OptimisationRecommendation:
    if not records:
        return OptimisationRecommendation(
            category="RiskThreshold", recommendation="No data",
            rationale="N/A", current_value="N/A", suggested_value="N/A",
            confidence="LOW", expected_benefit="N/A",
        )
    winners = [r for r in records if (r.pnl or 0) > 0]
    losers  = [r for r in records if (r.pnl or 0) < 0]
    avg_win_risk  = sum(r.risk_score or 0 for r in winners) / len(winners) if winners else 0.0
    avg_lose_risk = sum(r.risk_score or 0 for r in losers)  / len(losers)  if losers  else 0.0
    suggested = round((avg_win_risk + avg_lose_risk) / 2, 2) if losers and winners else 0.5

    return OptimisationRecommendation(
        category="RiskThreshold",
        recommendation=f"Set maximum risk score threshold to {suggested:.2f}",
        rationale=(
            f"Winning trades averaged risk score {avg_win_risk:.3f}; "
            f"losing trades averaged {avg_lose_risk:.3f}."
        ),
        current_value="No explicit risk filter",
        suggested_value=f"Max risk score ≤ {suggested:.2f}",
        confidence="MEDIUM",
        expected_benefit="Filter out high-risk signals that historically underperform.",
    )


def _execution_threshold_rec(records: list) -> OptimisationRecommendation:
    if not records:
        return OptimisationRecommendation(
            category="ExecutionThreshold", recommendation="No data",
            rationale="N/A", current_value="N/A", suggested_value="N/A",
            confidence="LOW", expected_benefit="N/A",
        )
    winners = [r for r in records if (r.pnl or 0) > 0]
    losers  = [r for r in records if (r.pnl or 0) < 0]
    avg_win_eq  = sum(r.execution_quality_score or 0 for r in winners) / len(winners) if winners else 0.0
    avg_lose_eq = sum(r.execution_quality_score or 0 for r in losers)  / len(losers)  if losers  else 0.0
    suggested   = max(50, round((avg_win_eq + avg_lose_eq) / 2))

    return OptimisationRecommendation(
        category="ExecutionThreshold",
        recommendation=f"Set minimum execution quality threshold to {suggested}",
        rationale=(
            f"Winning trades had avg EQ score {avg_win_eq:.1f}; "
            f"losing trades {avg_lose_eq:.1f}."
        ),
        current_value="No explicit execution filter",
        suggested_value=f"Min EQ score ≥ {suggested}",
        confidence="MEDIUM",
        expected_benefit="Avoid entering trades with poor execution quality.",
    )


def _strategy_selection_rec(records: list) -> OptimisationRecommendation:
    key, wr, cnt = _best_by_win_rate(records, lambda r: r.strategy)
    if key is None:
        return OptimisationRecommendation(
            category="StrategySelection",
            recommendation="Insufficient data for strategy recommendation",
            rationale="Need ≥3 trades per strategy.",
            current_value="All strategies", suggested_value="N/A",
            confidence="LOW", expected_benefit="N/A",
        )
    return OptimisationRecommendation(
        category="StrategySelection",
        recommendation=f"Increase weighting for '{key}' strategy",
        rationale=f"{wr*100:.0f}% win rate across {cnt} trades.",
        current_value="All strategies equally weighted",
        suggested_value=f"Prioritise '{key}'",
        confidence="HIGH" if wr >= 0.65 else "MEDIUM",
        expected_benefit="Concentrate on the highest-performing strategy for improved returns.",
    )
