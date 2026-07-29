"""
ai_performance/confidence_analysis.py — Confidence vs outcome analysis.

Buckets signals by confidence level and computes win rate, P&L, and
cross-correlations with regime and sector per bucket.

READ-ONLY. PAPER TRADING / ADVISORY ONLY.
"""
from __future__ import annotations

import statistics as _stats
from typing import List, Dict, Any

from .ai_models import AISignalRecord, ConfidenceBucketStats, CONFIDENCE_BUCKETS


def compute_confidence_distribution(signals: List[AISignalRecord]) -> Dict[str, Any]:
    """
    Compute per-bucket statistics and aggregate confidence metrics.
    Returns bucket stats + overall distribution summary.
    """
    if not signals:
        return {
            "buckets":            [],
            "total_signals":      0,
            "avg_confidence":     0.0,
            "median_confidence":  0.0,
            "high_confidence_pct": 0.0,
        }

    # Group by bucket
    bucket_groups: Dict[str, List[AISignalRecord]] = {b[0]: [] for b in CONFIDENCE_BUCKETS}
    for s in signals:
        bucket_groups.setdefault(s.confidence_bucket, []).append(s)

    bucket_stats: List[ConfidenceBucketStats] = []
    for label, lo, hi in CONFIDENCE_BUCKETS:
        group = bucket_groups.get(label, [])
        if not group:
            bucket_stats.append(ConfidenceBucketStats(bucket=label, count=0))
            continue
        winners = [g for g in group if g.is_winner]
        pnls    = [g.pnl for g in group]
        confs   = [g.signal_confidence for g in group]
        bs = ConfidenceBucketStats(
            bucket          = label,
            count           = len(group),
            winners         = len(winners),
            losers          = len(group) - len(winners),
            win_rate        = len(winners) / len(group) * 100,
            avg_pnl         = _stats.mean(pnls),
            net_pnl         = sum(pnls),
            avg_confidence  = _stats.mean(confs),
        )
        bucket_stats.append(bs)

    confs_all = [s.signal_confidence for s in signals]
    high_conf = sum(1 for s in signals if s.is_high_confidence)

    return {
        "buckets":             [b.to_dict() for b in bucket_stats],
        "total_signals":       len(signals),
        "avg_confidence":      round(_stats.mean(confs_all), 4),
        "median_confidence":   round(_stats.median(confs_all), 4),
        "high_confidence_pct": round(high_conf / len(signals) * 100, 2),
    }


def compute_confidence_vs_regime(signals: List[AISignalRecord]) -> List[Dict[str, Any]]:
    """Win rate and avg confidence broken down by market regime."""
    by_regime: Dict[str, List[AISignalRecord]] = {}
    for s in signals:
        r = s.market_regime or "Unknown"
        by_regime.setdefault(r, []).append(s)

    rows = []
    for regime, group in by_regime.items():
        winners = [g for g in group if g.is_winner]
        confs   = [g.signal_confidence for g in group]
        rows.append({
            "regime":          regime,
            "count":           len(group),
            "win_rate":        round(len(winners) / len(group) * 100, 2),
            "avg_confidence":  round(_stats.mean(confs), 4),
            "net_pnl":         round(sum(g.pnl for g in group), 2),
        })
    return sorted(rows, key=lambda r: -r["net_pnl"])


def compute_confidence_vs_sector(signals: List[AISignalRecord]) -> List[Dict[str, Any]]:
    """Win rate and avg confidence broken down by sector."""
    by_sector: Dict[str, List[AISignalRecord]] = {}
    for s in signals:
        sec = s.sector or "Unknown"
        by_sector.setdefault(sec, []).append(s)

    rows = []
    for sector, group in by_sector.items():
        winners = [g for g in group if g.is_winner]
        confs   = [g.signal_confidence for g in group]
        rows.append({
            "sector":          sector,
            "count":           len(group),
            "win_rate":        round(len(winners) / len(group) * 100, 2),
            "avg_confidence":  round(_stats.mean(confs), 4),
            "net_pnl":         round(sum(g.pnl for g in group), 2),
        })
    return sorted(rows, key=lambda r: -r["net_pnl"])
