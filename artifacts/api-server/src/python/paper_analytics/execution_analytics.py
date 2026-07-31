"""
paper_analytics/execution_analytics.py — Phase 8.2
Execution quality analytics derived from execution_quality module.

Measures: entry/exit quality, slippage, execution delay,
missed opportunity, average capture %.

KEY CONTRACT — every field the dashboard reads:
  available, advisory_only
  total_records       ← compute_summary "total_trades"
  completed_records   ← compute_summary "completed_trades"
  avg_quality_score   ← compute_summary "avg_execution_score"
  overall_grade       ← grade computed from avg_quality_score
  avg_entry_slippage_pct, avg_exit_slippage_pct
  avg_execution_delay_seconds ← compute_summary "avg_fill_delay_seconds"
  avg_capture_pct     ← computed from completed records
  best_execution      ← compute_summary "best_trade" renamed
  worst_execution     ← compute_summary "worst_trade" renamed
  grade_distribution  ← keyed by quality_grade per record
  strategy_quality    ← list of {strategy, count, avg_score, avg_slippage_pct}

READ-ONLY. ADVISORY-ONLY.
"""
from __future__ import annotations

from typing import Any, Dict, List


def _overall_grade(score: float | None) -> str:
    """Map avg quality score (0–100) to A+/A/B/C/D."""
    if score is None:
        return "N/A"
    if score >= 90: return "A+"
    if score >= 78: return "A"
    if score >= 65: return "B"
    if score >= 50: return "C"
    return "D"


def get_execution_analytics() -> Dict[str, Any]:
    """
    Execution quality analytics reusing execution_quality sub-modules.
    Gracefully disables when execution_quality module is unavailable.

    All key names are chosen to match what PaperAnalytics.tsx reads.
    """
    try:
        from execution_quality.metrics import build_execution_records, compute_summary
    except ImportError:
        return {
            "available":     False,
            "advisory_only": True,
            "message":       "execution_quality module not available.",
        }

    try:
        records = build_execution_records()
        summary = compute_summary(records)

        # ── Aliased core counts/scores ─────────────────────────────────────
        total_records     = summary.get("total_trades",        0)
        completed_records = summary.get("completed_trades",    0)
        avg_quality_score = summary.get("avg_execution_score", None)

        overall_grade     = _overall_grade(avg_quality_score)

        # ── Slippage fields (shared key names) ────────────────────────────
        avg_entry_slippage_pct = summary.get("avg_entry_slippage_pct")
        avg_exit_slippage_pct  = summary.get("avg_exit_slippage_pct")

        # Dashboard reads "avg_execution_delay_seconds"
        avg_execution_delay_seconds = summary.get("avg_fill_delay_seconds")

        # ── Best / worst execution (renamed from best_trade/worst_trade) ──
        best_execution  = summary.get("best_trade")
        worst_execution = summary.get("worst_trade")

        completed = [r for r in records if r.is_complete]

        # ── Per-strategy quality ──────────────────────────────────────────
        by_strat: Dict[str, list] = {}
        for r in records:
            by_strat.setdefault(r.strategy_name or "Unknown", []).append(r)

        strat_quality = [
            {
                "strategy":         name,
                "count":            len(recs),
                "avg_score":        round(sum(r.quality_score for r in recs) / len(recs), 1),
                "avg_slippage_pct": round(
                    sum(r.entry_slippage_pct for r in recs) / len(recs), 4
                ) if recs else 0.0,
            }
            for name, recs in by_strat.items()
        ]
        strat_quality.sort(key=lambda r: -r["avg_score"])

        # ── Average capture % ─────────────────────────────────────────────
        capture_pcts = []
        for r in completed:
            if getattr(r, "target", 0) > 0 and getattr(r, "actual_entry_price", 0) > 0:
                potential = abs(r.target - r.actual_entry_price) * getattr(r, "quantity", 0)
                if potential > 0 and getattr(r, "pnl", None) is not None:
                    capture_pcts.append(r.pnl / potential * 100)

        import statistics as _s
        avg_capture_pct = round(_s.mean(capture_pcts), 2) if capture_pcts else None

        # ── Grade distribution ────────────────────────────────────────────
        grade_distribution: Dict[str, int] = {}
        for r in records:
            key = r.quality_grade or "N/A"
            grade_distribution[key] = grade_distribution.get(key, 0) + 1

        return {
            "available":                True,
            "advisory_only":            True,
            # Counts (dashboard contract names)
            "total_records":            total_records,
            "completed_records":        completed_records,
            # Scores (dashboard contract names)
            "avg_quality_score":        avg_quality_score,
            "overall_grade":            overall_grade,
            # Slippage
            "avg_entry_slippage_pct":   avg_entry_slippage_pct,
            "avg_exit_slippage_pct":    avg_exit_slippage_pct,
            "avg_entry_slippage_rs":    summary.get("avg_entry_slippage_rs"),
            "avg_exit_slippage_rs":     summary.get("avg_exit_slippage_rs"),
            # Delay (dashboard contract name)
            "avg_execution_delay_seconds": avg_execution_delay_seconds,
            # Capture
            "avg_capture_pct":          avg_capture_pct,
            # Best / worst (dashboard contract names)
            "best_execution":           best_execution,
            "worst_execution":          worst_execution,
            # Supplementary
            "most_efficient_strategy":  summary.get("most_efficient_strategy"),
            "highest_slippage_symbol":  summary.get("highest_slippage_symbol"),
            "grade_distribution":       grade_distribution,
            "strategy_quality":         strat_quality,
        }

    except Exception as exc:
        import traceback
        return {
            "available":     False,
            "advisory_only": True,
            "error":         str(exc),
            "trace":         traceback.format_exc(),
        }
