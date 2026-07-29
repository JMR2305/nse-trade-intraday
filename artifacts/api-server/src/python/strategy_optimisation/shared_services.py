"""
shared_services.py — Phase 6.2
Stable public interface for strategy_optimisation.
All future phases call these functions — never the sub-modules directly.

READ-ONLY. ADVISORY-ONLY.
No trading parameters, strategies, orders, portfolio, signals, or risk engine
are ever modified by this module.
"""
from __future__ import annotations
import sys, os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from .optimisation_models import is_enabled, disabled_response


def _get_records() -> list:
    """Collect all validated trade records via Phase 6.1 (FIFO-matched)."""
    try:
        from paper_trading_validation.validation_collector import collect_all_trade_records
        return collect_all_trade_records()
    except Exception:
        return []


# ---------------------------------------------------------------------------
# GET /api/optimisation/summary
# ---------------------------------------------------------------------------

def get_summary() -> dict:
    """
    Full optimisation summary:
    • Top 3 strategies ranked by health score
    • Best regime, best sector, best time window
    • Overall advisory: Continue / Observe / Retune / Pause
    • Adaptive learning overview
    """
    if not is_enabled():
        return disabled_response()
    try:
        from .strategy_analyser import analyse_strategies
        from .regime_analyser import analyse_regimes
        from .sector_analyser import analyse_sectors
        from .time_analyser import analyse_time_windows
        from .adaptive_learning import compute_adaptive_learning

        records = _get_records()

        strategies = analyse_strategies(records)
        regimes = analyse_regimes(records)
        sectors = analyse_sectors(records)
        time_windows = analyse_time_windows(records)
        adaptive = compute_adaptive_learning(records)

        underperforming = [s for s in strategies if s.is_underperforming]
        top_strategies = strategies[:3]

        return {
            "status": "ENABLED",
            "total_trades": len(records),
            "total_strategies": len(strategies),
            "top_strategies": [s.to_dict() for s in top_strategies],
            "underperforming_strategies": [s.to_dict() for s in underperforming],
            "best_regime": regimes[0].to_dict() if regimes else None,
            "best_sector": sectors[0].to_dict() if sectors else None,
            "best_time_window": next((w.to_dict() for w in time_windows if w.trades > 0), None),
            "overall_trend": adaptive.get("overall_trend"),
            "advisory_only": True,
            "available": True,
        }
    except Exception as e:
        import traceback
        return {"status": "ERROR", "error": str(e), "trace": traceback.format_exc(), "available": False}


# ---------------------------------------------------------------------------
# GET /api/optimisation/strategies
# ---------------------------------------------------------------------------

def get_strategies() -> dict:
    """
    Full strategy ranking with per-strategy profiles, parameter recommendations,
    regime/sector breakdown per strategy, and lifecycle states.
    """
    if not is_enabled():
        return disabled_response()
    try:
        from .strategy_analyser import analyse_strategies
        from .parameter_optimiser import generate_recommendations
        from .regime_analyser import analyse_regimes
        from collections import defaultdict

        records = _get_records()
        profiles = analyse_strategies(records)

        by_strategy: dict = defaultdict(list)
        for r in records:
            by_strategy[r.strategy].append(r)

        strategies_out = []
        for profile in profiles:
            strat_records = by_strategy.get(profile.strategy, [])
            param_recs = generate_recommendations(profile, strat_records)

            # Per-strategy regime breakdown
            strat_regimes: dict = defaultdict(list)
            for r in strat_records:
                strat_regimes[r.market_regime].append(r)
            regime_breakdown = []
            for regime, recs in strat_regimes.items():
                wr = sum(1 for r in recs if r.pnl > 0) / len(recs)
                regime_breakdown.append({
                    "regime": regime, "trades": len(recs),
                    "win_rate": round(wr, 4),
                    "net_pnl": round(sum(r.pnl for r in recs), 2),
                })
            regime_breakdown.sort(key=lambda x: x["win_rate"], reverse=True)

            strategies_out.append({
                **profile.to_dict(),
                "parameter_recommendations": [r.to_dict() for r in param_recs],
                "regime_breakdown": regime_breakdown,
            })

        return {
            "status": "ENABLED",
            "strategies": strategies_out,
            "total_strategies": len(strategies_out),
            "advisory_only": True,
            "available": True,
        }
    except Exception as e:
        import traceback
        return {"status": "ERROR", "error": str(e), "trace": traceback.format_exc(), "available": False}


# ---------------------------------------------------------------------------
# GET /api/optimisation/recommendations
# ---------------------------------------------------------------------------

def get_recommendations() -> dict:
    """
    All advisory recommendations: regime, sector, time window, parameter,
    underperforming actions, and adaptive learning signals.
    All carry advisory_only=True.
    """
    if not is_enabled():
        return disabled_response()
    try:
        from .strategy_analyser import analyse_strategies
        from .parameter_optimiser import generate_recommendations
        from .regime_analyser import analyse_regimes
        from .sector_analyser import analyse_sectors
        from .time_analyser import analyse_time_windows
        from .adaptive_learning import compute_adaptive_learning
        from collections import defaultdict

        records = _get_records()
        profiles = analyse_strategies(records)
        regimes = analyse_regimes(records)
        sectors = analyse_sectors(records)
        time_windows = analyse_time_windows(records)
        adaptive = compute_adaptive_learning(records)

        by_strategy: dict = defaultdict(list)
        for r in records:
            by_strategy[r.strategy].append(r)

        # Collect all parameter recommendations
        all_param_recs = []
        for profile in profiles:
            strat_recs = by_strategy.get(profile.strategy, [])
            all_param_recs.extend(generate_recommendations(profile, strat_recs))

        # Underperforming actions
        underperform_actions = [
            {
                "strategy": p.strategy,
                "action": p.action,
                "reasons": p.underperform_reasons,
                "health_score": p.health_score,
                "grade": p.grade,
                "advisory_only": True,
            }
            for p in profiles if p.is_underperforming
        ]

        # Best regime to trade in
        best_regime_rec = None
        if regimes:
            best = regimes[0]
            best_regime_rec = {
                "recommendation": f"Focus on {best.regime} regime",
                "rationale": f"{best.win_rate * 100:.0f}% win rate across {best.trades} trades",
                "advisory_only": True,
            }

        # Best time window
        best_time_rec = None
        non_empty_windows = [w for w in time_windows if w.trades > 0]
        if non_empty_windows:
            best_w = non_empty_windows[0]
            best_time_rec = {
                "recommendation": f"Prefer {best_w.window} ({best_w.start_time}–{best_w.end_time})",
                "rationale": f"{best_w.win_rate * 100:.0f}% win rate across {best_w.trades} trades",
                "advisory_only": True,
            }

        return {
            "status": "ENABLED",
            "parameter_recommendations": [r.to_dict() for r in all_param_recs],
            "underperforming_actions": underperform_actions,
            "regime_recommendation": best_regime_rec,
            "time_window_recommendation": best_time_rec,
            "adaptive_learning": adaptive,
            "advisory_only": True,
            "available": True,
        }
    except Exception as e:
        import traceback
        return {"status": "ERROR", "error": str(e), "trace": traceback.format_exc(), "available": False}


# ---------------------------------------------------------------------------
# GET /api/optimisation/patterns
# ---------------------------------------------------------------------------

def get_patterns() -> dict:
    """Pattern discovery: winning/losing conditions, high/low confidence, combinations."""
    if not is_enabled():
        return disabled_response()
    try:
        from .pattern_discovery import discover_patterns
        from .sector_analyser import analyse_sectors
        from .regime_analyser import analyse_regimes

        records = _get_records()
        patterns = discover_patterns(records)
        sectors = analyse_sectors(records)
        regimes = analyse_regimes(records)

        winning = [p.to_dict() for p in patterns if p.pattern_type == "WINNING"]
        losing = [p.to_dict() for p in patterns if p.pattern_type == "LOSING"]
        high_conf = [p.to_dict() for p in patterns if p.pattern_type == "HIGH_CONF"]
        low_conf = [p.to_dict() for p in patterns if p.pattern_type == "LOW_CONF"]

        return {
            "status": "ENABLED",
            "total_patterns": len(patterns),
            "winning_patterns": winning,
            "losing_patterns": losing,
            "high_confidence_patterns": high_conf,
            "low_confidence_patterns": low_conf,
            "sector_ranking": [s.to_dict() for s in sectors],
            "regime_ranking": [r.to_dict() for r in regimes],
            "advisory_only": True,
            "available": True,
        }
    except Exception as e:
        import traceback
        return {"status": "ERROR", "error": str(e), "trace": traceback.format_exc(), "available": False}


# ---------------------------------------------------------------------------
# Export helpers
# ---------------------------------------------------------------------------

def export_strategies_csv() -> str:
    if not is_enabled():
        return ""
    try:
        import csv, io
        from .strategy_analyser import analyse_strategies
        profiles = analyse_strategies(_get_records())
        output = io.StringIO()
        if not profiles:
            return ""
        writer = csv.DictWriter(output, fieldnames=list(profiles[0].to_dict().keys()), extrasaction="ignore")
        writer.writeheader()
        for p in profiles:
            writer.writerow(p.to_dict())
        return output.getvalue()
    except Exception:
        return ""


def export_recommendations_json() -> str:
    if not is_enabled():
        return ""
    try:
        import json
        return json.dumps(get_recommendations(), indent=2, default=str)
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# Flat snapshot for Executive Dashboard / super-aggregators
# ---------------------------------------------------------------------------

def get_optimisation_snapshot() -> dict:
    """Flat KPI dict for future phases — never raises."""
    try:
        records = _get_records()
        from .strategy_analyser import analyse_strategies
        profiles = analyse_strategies(records)
        best = profiles[0] if profiles else None
        underperforming = sum(1 for p in profiles if p.is_underperforming)
        return {
            "total_strategies": len(profiles),
            "best_strategy": best.strategy if best else None,
            "best_strategy_health": best.health_score if best else 0.0,
            "best_strategy_grade": best.grade if best else "D",
            "underperforming_count": underperforming,
        }
    except Exception:
        return {
            "total_strategies": 0,
            "best_strategy": None,
            "best_strategy_health": 0.0,
            "best_strategy_grade": "D",
            "underperforming_count": 0,
        }
