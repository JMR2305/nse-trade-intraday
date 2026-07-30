"""
strategy_intelligence/shared_services.py — Stable shared service interface.

THIS IS THE CANONICAL ENTRY POINT for Phase 5D.4 and Phase 5D.5.

Phase 5D.4 (AI Performance Intelligence) and Phase 5D.5 (Executive Dashboard)
MUST import from this module instead of recalculating metrics themselves.

Stable public API (do not rename without versioning):

  get_all_strategy_profiles()  → List[StrategyProfile]
  get_strategy_stats(name)     → dict   (single strategy)
  get_regime_matrix()          → dict
  get_sector_matrix()          → dict
  get_time_matrix()            → dict
  get_strategy_rankings()      → List[dict]   (leaderboard rows)
  get_recommendations()        → List[dict]
  get_criterion_rankings()     → dict   (best by each criterion)
  get_summary_snapshot()       → dict   (top-level KPIs for dashboards)

All functions check is_enabled() and return disabled_response() when off.
All functions are read-only and advisory-only.
"""
from __future__ import annotations

from typing import List, Dict, Any, Optional

from .strategy_models import StrategyProfile, is_enabled, disabled_response, _LABEL


def _load_all() -> Dict[str, Any]:
    """
    Single authoritative data pipeline:
      load raw trades → match closed → build profiles → rank → recommend
    Returns all derived objects in one dict.
    """
    from .strategy_engine    import load_all_data
    from .strategy_statistics import build_all_profiles
    from .strategy_rankings   import compute_rank_scores, get_leaderboard, get_criterion_rankings
    from .recommendations     import apply_recommendations, get_recommendation_matrix
    from .market_regime_analysis import compute_regime_matrix
    from .sector_analysis        import compute_sector_matrix
    from .time_analysis          import compute_time_analysis

    data    = load_all_data()
    closed  = data["closed_trades"]
    opens   = data["open_counts"]

    profiles = build_all_profiles(closed, opens)
    profiles = apply_recommendations(profiles)
    profiles = compute_rank_scores(profiles)

    regime_data  = compute_regime_matrix(closed)
    sector_data  = compute_sector_matrix(closed)
    time_data    = compute_time_analysis(closed)

    return {
        "profiles":     profiles,
        "closed":       closed,
        "regime_data":  regime_data,
        "sector_data":  sector_data,
        "time_data":    time_data,
        "leaderboard":  get_leaderboard(profiles),
        "crit_ranks":   get_criterion_rankings(profiles),
        "rec_matrix":   get_recommendation_matrix(profiles),
    }


# ── Stable public API ─────────────────────────────────────────────────────────

def get_all_strategy_profiles() -> List[StrategyProfile]:
    """
    Return the fully enriched StrategyProfile list (ranked + recommended).
    Used by 5D.4 and 5D.5 as the primary data source.
    """
    if not is_enabled():
        return []
    try:
        return _load_all()["profiles"]
    except Exception:
        return []


def get_strategy_stats(strategy_name: str) -> dict:
    """Return the StrategyProfile dict for a single strategy by name."""
    if not is_enabled():
        return disabled_response()
    try:
        profiles = get_all_strategy_profiles()
        match = next((p for p in profiles if p.strategy_name == strategy_name), None)
        if match is None:
            return {"error": f"Strategy '{strategy_name}' not found.", "label": _LABEL}
        return {"status": "ENABLED", "label": _LABEL, "profile": match.to_dict()}
    except Exception as exc:
        return {"error": str(exc), "label": _LABEL}


def get_regime_matrix() -> dict:
    """Return the full regime performance matrix."""
    if not is_enabled():
        return disabled_response()
    try:
        from .strategy_engine import load_all_data
        from .market_regime_analysis import compute_regime_matrix, get_regime_summary
        data = load_all_data()
        rd   = compute_regime_matrix(data["closed_trades"])
        return {
            "status":          "ENABLED",
            "label":           _LABEL,
            "matrix":          rd["matrix"],
            "best_per_regime": rd["best_per_regime"],
            "summary":         get_regime_summary(rd),
            "regimes_seen":    rd["regimes_seen"],
        }
    except Exception as exc:
        return {"error": str(exc), "label": _LABEL}


def get_sector_matrix() -> dict:
    """Return the full sector performance matrix."""
    if not is_enabled():
        return disabled_response()
    try:
        from .strategy_engine import load_all_data
        from .sector_analysis import compute_sector_matrix, get_sector_summary
        data = load_all_data()
        sd   = compute_sector_matrix(data["closed_trades"])
        return {
            "status":          "ENABLED",
            "label":           _LABEL,
            "matrix":          sd["matrix"],
            "best_sector":     sd["best_sector"],
            "worst_sector":    sd["worst_sector"],
            "highest_win_rate_sector": sd["highest_win_rate_sector"],
            "summary":         get_sector_summary(sd),
        }
    except Exception as exc:
        return {"error": str(exc), "label": _LABEL}


def get_time_matrix() -> dict:
    """Return time-of-day and day-of-week performance matrices."""
    if not is_enabled():
        return disabled_response()
    try:
        from .strategy_engine import load_all_data
        from .time_analysis import compute_time_analysis
        data = load_all_data()
        td   = compute_time_analysis(data["closed_trades"])
        return {"status": "ENABLED", "label": _LABEL, **td}
    except Exception as exc:
        return {"error": str(exc), "label": _LABEL}


def get_strategy_rankings() -> List[dict]:
    """Return the ranked leaderboard rows."""
    if not is_enabled():
        return []
    try:
        return _load_all()["leaderboard"]
    except Exception:
        return []


def get_recommendations() -> List[dict]:
    """Return the advisory recommendation matrix."""
    if not is_enabled():
        return []
    try:
        return _load_all()["rec_matrix"]
    except Exception:
        return []


def get_criterion_rankings() -> dict:
    """Return best strategy per criterion (highest PF, win rate, etc.)."""
    if not is_enabled():
        return {}
    try:
        return _load_all()["crit_ranks"]
    except Exception:
        return {}


def _best_regime_str(rd: dict) -> str:
    """
    Return the regime NAME with the highest net P&L as a plain string.

    ``rd`` is the dict returned by ``compute_regime_matrix()``; its ``matrix``
    key maps regime names to per-regime stats.  We pick the regime name with
    the best ``net_pnl``.  Returns ``"N/A"`` when there are no regimes (e.g.
    no closed trades yet).
    """
    matrix = rd.get("matrix", {})
    if not matrix:
        return "N/A"
    return max(matrix, key=lambda k: matrix[k].get("net_pnl", 0))


def get_summary_snapshot() -> dict:
    """
    Top-level KPI snapshot for embedding in Phase 5D.5 Executive Dashboard.
    Returns the single most important fact per category without re-loading data.
    """
    if not is_enabled():
        return disabled_response()
    try:
        all_data  = _load_all()
        profiles  = all_data["profiles"]
        leaderboard = all_data["leaderboard"]
        crit      = all_data["crit_ranks"]
        rd        = all_data["regime_data"]
        sd        = all_data["sector_data"]
        td        = all_data["time_data"]

        with_trades = [p for p in profiles if p.total_trades > 0]
        best    = with_trades[0] if with_trades else None   # already sorted by rank
        worst   = with_trades[-1] if with_trades else None

        total_closed = sum(p.total_trades for p in profiles)
        total_pnl    = sum(p.net_pnl for p in profiles)
        overall_wr   = (
            sum(p.winning_trades for p in profiles) / total_closed * 100
            if total_closed > 0 else 0.0
        )

        return {
            "status":            "ENABLED",
            "label":             _LABEL,
            "total_strategies":  len(with_trades),
            "total_closed_trades": total_closed,
            "total_net_pnl":     round(total_pnl, 2),
            "overall_win_rate":  round(overall_wr, 2),
            "best_strategy":     best.strategy_name if best else None,
            "best_strategy_pnl": round(best.net_pnl, 2) if best else 0.0,
            "worst_strategy":    worst.strategy_name if worst else None,
            "best_regime":       _best_regime_str(rd),
            "best_sector":       sd.get("best_sector"),
            "worst_sector":      sd.get("worst_sector"),
            "best_time_slot":    td.get("best_slot"),
            "best_day":          td.get("best_day"),
            "criterion_rankings": crit,
        }
    except Exception as exc:
        return {"error": str(exc), "label": _LABEL}
