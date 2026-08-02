"""
learning_engine.py — Phase 10D Learning Agent
Computes learning metrics, insights, and pattern observations.

READ-ONLY · ADVISORY-ONLY
No model retraining. No parameter tuning. No automatic optimisation.
All outputs require operator review before adoption.
"""
from __future__ import annotations
import math
from datetime import datetime, timezone
from typing import Any

# ── helpers ───────────────────────────────────────────────────────────────────

def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _safe(fn, default=None):
    try:
        return fn()
    except Exception:
        return default


def _pct(n: int, d: int) -> float:
    return round(100.0 * n / d, 1) if d > 0 else 0.0


def _avg(values: list) -> float:
    clean = [v for v in values if v is not None and not math.isnan(v)]
    return round(sum(clean) / len(clean), 3) if clean else 0.0


# ── learning metrics ──────────────────────────────────────────────────────────

def compute_learning_metrics(
    trades: list[dict],
    recommendations: list[dict],
    risk_snapshot: dict,
    strategy_snapshot: dict,
) -> dict:
    """
    Compute the 9 core learning metrics from completed trade/recommendation data.
    Pure computation — no side-effects.
    """
    closed = [t for t in trades if t.get("status") in ("CLOSED", "COMPLETED", "SOLD")]
    winners = [t for t in closed if _safe(lambda t=t: float(t.get("pnl_pct", 0)) > 0, False)]
    losers  = [t for t in closed if _safe(lambda t=t: float(t.get("pnl_pct", 0)) <= 0, False)]

    total_closed = len(closed)
    win_count    = len(winners)

    # 1. Recommendation accuracy — fraction of recs that reached target
    rec_total   = len(recommendations)
    rec_success = sum(1 for r in recommendations if r.get("outcome") in ("TARGET_HIT", "PROFITABLE", "SUCCESS"))
    rec_accuracy = _pct(rec_success, rec_total)

    # 2. Strategy win rate
    strategy_win_rate = _pct(win_count, total_closed)

    # 3. Confidence calibration — avg(abs(confidence - binary_outcome))
    calibration_errors = []
    for r in recommendations:
        conf = _safe(lambda r=r: float(r.get("confidence", 0.5)), 0.5)
        outcome_val = 1.0 if r.get("outcome") in ("TARGET_HIT", "PROFITABLE", "SUCCESS") else 0.0
        calibration_errors.append(abs(conf - outcome_val))
    calibration_error = _avg(calibration_errors)
    calibration_score = round(1.0 - calibration_error, 3)  # 1.0 = perfect

    # 4. Average holding time (minutes)
    holding_times = []
    for t in closed:
        entry = _safe(lambda t=t: t.get("entry_time") or t.get("created_at"), None)
        exit_ = _safe(lambda t=t: t.get("exit_time")  or t.get("updated_at"), None)
        if entry and exit_:
            try:
                for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d %H:%M:%S"):
                    try:
                        e = datetime.strptime(str(entry), fmt)
                        x = datetime.strptime(str(exit_), fmt)
                        holding_times.append((x - e).total_seconds() / 60)
                        break
                    except ValueError:
                        pass
            except Exception:
                pass
    avg_holding_minutes = round(_avg(holding_times), 1)

    # 5. Average reward/risk ratio
    rr_ratios = []
    for t in closed:
        gain = _safe(lambda t=t: float(t.get("pnl_pct", 0)), 0.0)
        risk = _safe(lambda t=t: float(t.get("risk_pct", 1.0)), 1.0)
        if risk > 0:
            rr_ratios.append(gain / risk)
    avg_rr = _avg(rr_ratios)

    # 6. Sector performance
    sector_stats: dict[str, dict] = {}
    for t in closed:
        sector = t.get("sector", "UNKNOWN")
        pnl    = _safe(lambda t=t: float(t.get("pnl_pct", 0)), 0.0)
        if sector not in sector_stats:
            sector_stats[sector] = {"count": 0, "wins": 0, "total_pnl": 0.0}
        sector_stats[sector]["count"]    += 1
        sector_stats[sector]["total_pnl"] += pnl
        if pnl > 0:
            sector_stats[sector]["wins"] += 1
    sector_performance = {
        s: {
            "count": d["count"],
            "win_rate": _pct(d["wins"], d["count"]),
            "avg_pnl_pct": round(d["total_pnl"] / d["count"], 2) if d["count"] > 0 else 0.0,
        }
        for s, d in sector_stats.items()
    }

    # 7. Market regime performance
    regime = _safe(lambda: str(risk_snapshot.get("regime", "UNKNOWN")), "UNKNOWN")
    regime_pnl  = _avg([_safe(lambda t=t: float(t.get("pnl_pct", 0)), 0.0) for t in closed])
    regime_win  = _pct(win_count, total_closed)
    regime_perf = {
        regime: {"trades": total_closed, "win_rate": regime_win, "avg_pnl_pct": regime_pnl}
    }

    # 8. Risk prediction accuracy — how often risk agent warnings materialized
    risk_warnings_issued  = _safe(lambda: int(risk_snapshot.get("total_warnings", 0)), 0)
    risk_events_confirmed = _safe(lambda: int(risk_snapshot.get("confirmed_risk_events", 0)), risk_warnings_issued // 3 if risk_warnings_issued else 0)
    risk_prediction_accuracy = _pct(risk_events_confirmed, risk_warnings_issued)

    # 9. Execution validation accuracy
    exec_total   = _safe(lambda: int(risk_snapshot.get("execution_checks_total", 0)), total_closed)
    exec_correct = _safe(lambda: int(risk_snapshot.get("execution_checks_passed", 0)), int(exec_total * 0.85))
    execution_validation_accuracy = _pct(exec_correct, exec_total)

    return {
        "recommendation_accuracy": rec_accuracy,
        "strategy_win_rate": strategy_win_rate,
        "confidence_calibration": round(calibration_score, 3),
        "avg_holding_minutes": avg_holding_minutes,
        "avg_reward_risk": round(avg_rr, 3),
        "sector_performance": sector_performance,
        "regime_performance": regime_perf,
        "risk_prediction_accuracy": risk_prediction_accuracy,
        "execution_validation_accuracy": execution_validation_accuracy,
        # summary
        "trades_analysed": total_closed,
        "winners": win_count,
        "losers": len(losers),
        "recommendations_analysed": rec_total,
    }


# ── learning insights ─────────────────────────────────────────────────────────

def compute_learning_insights(
    metrics: dict,
    trades: list[dict],
    recommendations: list[dict],
    risk_snapshot: dict,
) -> dict:
    """
    Automatically identify the 8 learning insights from computed metrics.
    Advisory observations only — never modify any model or strategy.
    """
    sector_perf = metrics.get("sector_performance", {})

    # Best / worst strategy
    strategy_counts: dict[str, dict] = {}
    for t in trades:
        if t.get("status") not in ("CLOSED", "COMPLETED", "SOLD"):
            continue
        strat = t.get("strategy", "UNKNOWN")
        pnl   = _safe(lambda t=t: float(t.get("pnl_pct", 0)), 0.0)
        if strat not in strategy_counts:
            strategy_counts[strat] = {"wins": 0, "total": 0, "pnl_sum": 0.0}
        strategy_counts[strat]["total"] += 1
        strategy_counts[strat]["pnl_sum"] += pnl
        if pnl > 0:
            strategy_counts[strat]["wins"] += 1

    best_strategy   = "N/A"
    worst_strategy  = "N/A"
    best_win_rate   = -1.0
    worst_win_rate  = 101.0

    for strat, d in strategy_counts.items():
        wr = _pct(d["wins"], d["total"])
        if wr > best_win_rate:
            best_win_rate = wr
            best_strategy = strat
        if wr < worst_win_rate:
            worst_win_rate = wr
            worst_strategy = strat

    # Most profitable / weakest sector
    best_sector_name   = "N/A"
    worst_sector_name  = "N/A"
    best_sector_pnl    = float("-inf")
    worst_sector_pnl   = float("inf")
    for s, d in sector_perf.items():
        avg = d.get("avg_pnl_pct", 0.0)
        if avg > best_sector_pnl:
            best_sector_pnl  = avg
            best_sector_name = s
        if avg < worst_sector_pnl:
            worst_sector_pnl  = avg
            worst_sector_name = s

    # Most reliable recommendation type
    type_stats: dict[str, dict] = {}
    for r in recommendations:
        rtype = r.get("decision_type", r.get("type", "UNKNOWN"))
        outcome = r.get("outcome", "UNKNOWN")
        if rtype not in type_stats:
            type_stats[rtype] = {"total": 0, "success": 0}
        type_stats[rtype]["total"] += 1
        if outcome in ("TARGET_HIT", "PROFITABLE", "SUCCESS"):
            type_stats[rtype]["success"] += 1

    best_rec_type = max(
        type_stats.items(),
        key=lambda kv: _pct(kv[1]["success"], kv[1]["total"]) if kv[1]["total"] > 0 else 0,
        default=("N/A", {}),
    )[0] if type_stats else "N/A"

    # Common rejection reasons
    rejection_reasons: dict[str, int] = {}
    for r in recommendations:
        for reason in r.get("rejection_reasons", []):
            rejection_reasons[reason] = rejection_reasons.get(reason, 0) + 1
    top_rejections = sorted(rejection_reasons.items(), key=lambda x: -x[1])[:5]

    # Most frequent risk warnings
    risk_warnings: dict[str, int] = {}
    for warning in _safe(lambda: risk_snapshot.get("recent_warnings", []), []):
        msg = str(warning.get("message", warning)) if isinstance(warning, dict) else str(warning)
        risk_warnings[msg] = risk_warnings.get(msg, 0) + 1
    top_risk_warnings = sorted(risk_warnings.items(), key=lambda x: -x[1])[:5]

    # Recurring market patterns (advisory observations from trade data)
    patterns_observed: list[str] = []
    gap_up_count   = sum(1 for t in trades if _safe(lambda t=t: float(t.get("gap_pct", 0)) > 1.5, False))
    momentum_count = sum(1 for t in trades if t.get("strategy", "").upper().startswith("MOMENTUM"))
    if gap_up_count >= 2:
        patterns_observed.append(f"Gap-up detected in {gap_up_count} sessions — watch for breakout follow-through")
    if momentum_count > 0 and metrics.get("avg_holding_minutes", 120) < 60:
        patterns_observed.append("Momentum strategies are showing early exit — check morning fade risk")
    if metrics.get("strategy_win_rate", 50) < 40:
        patterns_observed.append("Win rate below 40% — review entry criteria for current regime")
    if not patterns_observed:
        patterns_observed.append("No recurring patterns detected in current session — continue monitoring")

    return {
        "best_strategy_today": best_strategy,
        "worst_strategy_today": worst_strategy,
        "most_profitable_sector": best_sector_name,
        "weakest_sector": worst_sector_name,
        "most_reliable_rec_type": best_rec_type,
        "common_rejection_reasons": [{"reason": r, "count": c} for r, c in top_rejections],
        "most_frequent_risk_warnings": [{"warning": w, "count": c} for w, c in top_risk_warnings],
        "recurring_patterns": patterns_observed,
    }


# ── pattern discovery ─────────────────────────────────────────────────────────

def discover_patterns(trades: list[dict], scan_snapshot: dict | None = None) -> list[dict]:
    """
    Identify recurring advisory patterns from trade history.
    Returns pattern observations — never triggers any automated action.
    """
    patterns: list[dict] = []

    # Pattern 1: Gap-up followed by breakout
    gap_wins = [
        t for t in trades
        if _safe(lambda t=t: float(t.get("gap_pct", 0)) > 1.5 and float(t.get("pnl_pct", 0)) > 0, False)
    ]
    if len(gap_wins) >= 2:
        patterns.append({
            "pattern_id": "GAP_BREAKOUT",
            "name": "Gap-Up Breakout",
            "description": "Gap-up open followed by sustained breakout continuation.",
            "occurrences": len(gap_wins),
            "advisory": "Consider monitoring gap-ups above 1.5% for breakout confirmation signal.",
            "confidence": min(0.90, 0.50 + len(gap_wins) * 0.08),
            "category": "PRICE_ACTION",
        })

    # Pattern 2: High VIX with false breakouts
    high_vix_losses = [
        t for t in trades
        if _safe(lambda t=t: float(t.get("vix_at_entry", 0)) > 18 and float(t.get("pnl_pct", 0)) < 0, False)
    ]
    if len(high_vix_losses) >= 2:
        patterns.append({
            "pattern_id": "HIGH_VIX_FALSE_BREAKOUT",
            "name": "High VIX False Breakout",
            "description": "Breakout signals during VIX > 18 more likely to reverse.",
            "occurrences": len(high_vix_losses),
            "advisory": "Apply tighter stops or avoid breakout entries when VIX exceeds 18.",
            "confidence": min(0.85, 0.45 + len(high_vix_losses) * 0.10),
            "category": "VOLATILITY",
        })

    # Pattern 3: Morning momentum fading (trades closed < 60 min with loss)
    morning_fades = [
        t for t in trades
        if _safe(lambda t=t: float(t.get("holding_minutes", 120)) < 60
                              and float(t.get("pnl_pct", 0)) < 0, False)
    ]
    if len(morning_fades) >= 2:
        patterns.append({
            "pattern_id": "MORNING_MOMENTUM_FADE",
            "name": "Morning Momentum Fade",
            "description": "Short-duration trades under 60 minutes tending to result in losses.",
            "occurrences": len(morning_fades),
            "advisory": "Monitor intraday momentum decay — extend target window or reduce position size.",
            "confidence": min(0.80, 0.40 + len(morning_fades) * 0.09),
            "category": "TIME_BASED",
        })

    # Pattern 4: Sector rotation
    sector_seq: list[str] = []
    for t in sorted(trades, key=lambda x: x.get("entry_time", "")):
        s = t.get("sector", "UNKNOWN")
        if sector_seq and sector_seq[-1] != s:
            sector_seq.append(s)
        elif not sector_seq:
            sector_seq.append(s)
    if len(set(sector_seq)) >= 3:
        patterns.append({
            "pattern_id": "SECTOR_ROTATION",
            "name": "Sector Rotation",
            "description": f"Activity rotating across {len(set(sector_seq))} sectors: {', '.join(list(set(sector_seq))[:4])}.",
            "occurrences": len(sector_seq),
            "advisory": "Track sector rotation flow for early rally identification.",
            "confidence": 0.65,
            "category": "SECTOR",
        })

    # Pattern 5: Repeated risk failures
    risk_fails = [
        t for t in trades
        if t.get("rejected_by_risk") or t.get("risk_failure")
    ]
    if len(risk_fails) >= 2:
        patterns.append({
            "pattern_id": "REPEATED_RISK_FAILURES",
            "name": "Repeated Risk Rejections",
            "description": "Multiple trades failed pre-execution risk checks.",
            "occurrences": len(risk_fails),
            "advisory": "Review risk limit calibration — frequent rejections may indicate overly tight limits.",
            "confidence": 0.70,
            "category": "RISK",
        })

    # Always include baseline if no patterns found
    if not patterns:
        patterns.append({
            "pattern_id": "BASELINE_OBSERVATION",
            "name": "Baseline — Insufficient History",
            "description": "Not enough completed trades to identify statistically reliable patterns.",
            "occurrences": len(trades),
            "advisory": "Continue paper trading to build sufficient history for pattern detection.",
            "confidence": 0.0,
            "category": "META",
        })

    return patterns
