"""
pattern_discovery.py — Phase 6.2
Pattern clustering: winning/losing conditions, high/low confidence setups,
frequent exit reasons, best combinations.

GitHub-inspired: pattern clustering for winning/losing trades,
explainable recommendations with supporting metrics.
"""
from __future__ import annotations
import sys, os
from typing import List, Dict
from collections import defaultdict, Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from .optimisation_models import Pattern


def _avg(vals: list) -> float:
    v = [x for x in vals if x is not None]
    return sum(v) / len(v) if v else 0.0


def _cluster_by(records: list, key_fn) -> Dict[tuple, list]:
    clusters: Dict[tuple, list] = defaultdict(list)
    for r in records:
        k = key_fn(r)
        clusters[k].append(r)
    return clusters


def discover_patterns(records: list) -> List[Pattern]:
    """
    Identify patterns from trade history:
    1. Best strategy × regime combinations (winning conditions)
    2. Worst strategy × regime combinations (losing conditions)
    3. High-confidence setups
    4. Low-confidence setups
    5. Frequent losing exit reasons
    6. Best strategy × sector × time-of-day combinations
    """
    patterns: List[Pattern] = []
    if len(records) < 3:
        return patterns

    # -----------------------------------------------------------------------
    # 1. Strategy × Regime combinations — best winning
    # -----------------------------------------------------------------------
    strat_regime = _cluster_by(records, lambda r: (r.strategy, r.market_regime))
    combo_scores = []
    for (strat, regime), recs in strat_regime.items():
        if len(recs) < 2:
            continue
        wr = sum(1 for r in recs if r.pnl > 0) / len(recs)
        avg_ret = _avg([r.pnl_pct for r in recs])
        combo_scores.append(((strat, regime), recs, wr, avg_ret))

    combo_scores.sort(key=lambda x: x[2] * 0.6 + min(abs(x[3]) / 5, 1) * (0.4 if x[3] > 0 else -0.4), reverse=True)

    for i, ((strat, regime), recs, wr, avg_ret) in enumerate(combo_scores[:3]):
        if wr >= 0.6 and avg_ret > 0:
            patterns.append(Pattern(
                pattern_id=f"WIN_{strat}_{regime}".replace(" ", "_").upper(),
                pattern_type="WINNING",
                description=f"{strat} performs best in {regime} regime",
                conditions={"strategy": strat, "regime": regime, "min_trades": len(recs)},
                trade_count=len(recs),
                win_rate=round(wr, 4),
                avg_return_pct=round(avg_ret, 4),
                examples=[r.trade_id for r in recs[:3]],
            ))

    # -----------------------------------------------------------------------
    # 2. Worst strategy × regime combinations (losing)
    # -----------------------------------------------------------------------
    for (strat, regime), recs, wr, avg_ret in reversed(combo_scores[-3:]):
        if wr < 0.4 and len(recs) >= 2:
            patterns.append(Pattern(
                pattern_id=f"LOSE_{strat}_{regime}".replace(" ", "_").upper(),
                pattern_type="LOSING",
                description=f"{strat} struggles in {regime} regime ({wr * 100:.0f}% win rate)",
                conditions={"strategy": strat, "regime": regime, "trades": len(recs)},
                trade_count=len(recs),
                win_rate=round(wr, 4),
                avg_return_pct=round(avg_ret, 4),
                examples=[r.trade_id for r in recs[:3]],
            ))

    # -----------------------------------------------------------------------
    # 3. High-confidence setups
    # -----------------------------------------------------------------------
    high_conf = [r for r in records if r.ai_confidence is not None and r.ai_confidence >= 0.75]
    if len(high_conf) >= 3:
        wr_hc = sum(1 for r in high_conf if r.pnl > 0) / len(high_conf)
        patterns.append(Pattern(
            pattern_id="HIGH_CONFIDENCE_SETUP",
            pattern_type="HIGH_CONF",
            description=f"High-confidence (≥0.75) trades: {wr_hc * 100:.0f}% win rate",
            conditions={"ai_confidence_min": 0.75, "trade_count": len(high_conf)},
            trade_count=len(high_conf),
            win_rate=round(wr_hc, 4),
            avg_return_pct=round(_avg([r.pnl_pct for r in high_conf]), 4),
            examples=[r.trade_id for r in high_conf[:3]],
        ))

    # -----------------------------------------------------------------------
    # 4. Low-confidence setups
    # -----------------------------------------------------------------------
    low_conf = [r for r in records if r.ai_confidence is not None and r.ai_confidence < 0.5]
    if len(low_conf) >= 3:
        wr_lc = sum(1 for r in low_conf if r.pnl > 0) / len(low_conf)
        patterns.append(Pattern(
            pattern_id="LOW_CONFIDENCE_SETUP",
            pattern_type="LOW_CONF",
            description=f"Low-confidence (<0.5) trades: {wr_lc * 100:.0f}% win rate — consider filtering",
            conditions={"ai_confidence_max": 0.5, "trade_count": len(low_conf)},
            trade_count=len(low_conf),
            win_rate=round(wr_lc, 4),
            avg_return_pct=round(_avg([r.pnl_pct for r in low_conf]), 4),
            examples=[r.trade_id for r in low_conf[:3]],
        ))

    # -----------------------------------------------------------------------
    # 5. Frequent losing exit reasons
    # -----------------------------------------------------------------------
    losing = [r for r in records if r.pnl < 0]
    if losing:
        exit_counter = Counter(r.exit_reason for r in losing)
        for reason, count in exit_counter.most_common(2):
            if count >= 3:
                reason_recs = [r for r in losing if r.exit_reason == reason]
                patterns.append(Pattern(
                    pattern_id=f"FREQ_LOSS_EXIT_{reason}".replace(" ", "_").upper(),
                    pattern_type="LOSING",
                    description=f"'{reason}' is the most frequent losing exit ({count} times)",
                    conditions={"exit_reason": reason, "occurrences": count},
                    trade_count=count,
                    win_rate=0.0,
                    avg_return_pct=round(_avg([r.pnl_pct for r in reason_recs]), 4),
                    examples=[r.trade_id for r in reason_recs[:3]],
                ))

    # -----------------------------------------------------------------------
    # 6. Best strategy × sector combination
    # -----------------------------------------------------------------------
    strat_sector = _cluster_by(records, lambda r: (r.strategy, r.sector))
    best_combo = None
    best_score = -999.0
    for (strat, sector), recs in strat_sector.items():
        if len(recs) < 2:
            continue
        wr = sum(1 for r in recs if r.pnl > 0) / len(recs)
        avg_ret = _avg([r.pnl_pct for r in recs])
        score = wr * 0.6 + min(avg_ret / 5, 1.0) * 0.4
        if score > best_score:
            best_score = score
            best_combo = ((strat, sector), recs, wr, avg_ret)

    if best_combo and best_combo[2] >= 0.6:
        (strat, sector), recs, wr, avg_ret = best_combo
        patterns.append(Pattern(
            pattern_id=f"BEST_COMBO_{strat}_{sector}".replace(" ", "_").upper(),
            pattern_type="WINNING",
            description=f"Best combination: {strat} in {sector} sector ({wr * 100:.0f}% win rate)",
            conditions={"strategy": strat, "sector": sector, "trades": len(recs)},
            trade_count=len(recs),
            win_rate=round(wr, 4),
            avg_return_pct=round(avg_ret, 4),
            examples=[r.trade_id for r in recs[:3]],
        ))

    return patterns
