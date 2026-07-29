"""
false_signal_analyser.py — Phase 6.3
Identify and categorise false signals from paper trade records.

Types: FALSE_BUY, FALSE_SELL, LATE, EARLY, HIGH_CONF_LOSS, LOW_CONF_WIN.

READ-ONLY. ADVISORY-ONLY.
"""
from __future__ import annotations
from typing import List
from .optimisation_models import FalseSignal


_HIGH_CONF = 0.75
_LOW_CONF  = 0.50


def analyse_false_signals(records: list) -> dict:
    if not records:
        return {
            "total_trades": 0,
            "false_signals": [],
            "false_signal_rate": 0.0,
            "advisory_insights": [],
            "advisory_only": True,
        }

    total = len(records)
    avg_hold = sum(r.holding_time_minutes or 0 for r in records) / total

    false_buy     = _collect(records, "FALSE_BUY",      lambda r: (r.ai_recommendation or "").upper() == "BUY"  and (r.pnl or 0) < 0)
    false_sell    = _collect(records, "FALSE_SELL",     lambda r: (r.ai_recommendation or "").upper() == "SELL" and (r.pnl or 0) < 0)
    late          = _collect(records, "LATE",           lambda r: (r.holding_time_minutes or 0) > avg_hold * 1.5 and (r.pnl or 0) < 0)
    early         = _collect(records, "EARLY",          lambda r: avg_hold > 0 and (r.holding_time_minutes or 0) < avg_hold * 0.3 and (r.pnl or 0) < 0)
    high_conf_loss= _collect(records, "HIGH_CONF_LOSS", lambda r: (r.ai_confidence or 0) >= _HIGH_CONF and (r.pnl or 0) < 0)
    low_conf_win  = _collect(records, "LOW_CONF_WIN",   lambda r: (r.ai_confidence or 0) < _LOW_CONF  and (r.pnl or 0) > 0)

    signals = [false_buy, false_sell, late, early, high_conf_loss, low_conf_win]
    signals = [_annotate(s, total) for s in signals]

    # false signal rate = proportion of trades with a meaningful false pattern
    problematic = set()
    for r in records:
        rec = (r.ai_recommendation or "").upper()
        conf = r.ai_confidence or 0.0
        pnl = r.pnl or 0
        if rec == "BUY"  and pnl < 0: problematic.add(r.trade_id)
        if rec == "SELL" and pnl < 0: problematic.add(r.trade_id)
        if conf >= _HIGH_CONF and pnl < 0: problematic.add(r.trade_id)
    false_rate = len(problematic) / total if total > 0 else 0.0

    insights = _generate_insights(signals, false_rate)

    return {
        "total_trades": total,
        "false_signals": [s.to_dict() for s in signals],
        "false_signal_rate": round(false_rate, 4),
        "advisory_insights": insights,
        "advisory_only": True,
    }


def _collect(records: list, signal_type: str, predicate) -> FalseSignal:
    matched = [r for r in records if predicate(r)]
    avg_loss = (sum(r.pnl_pct or 0.0 for r in matched) / len(matched)
                if matched else 0.0)
    descriptions = {
        "FALSE_BUY":       "AI recommended BUY but trade resulted in a loss",
        "FALSE_SELL":      "AI recommended SELL but trade resulted in a loss",
        "LATE":            "Entry signal was delayed — trade held longer than average and lost",
        "EARLY":           "Exit signal was premature — trade closed well before average holding time and lost",
        "HIGH_CONF_LOSS":  f"High-confidence signal (≥{int(_HIGH_CONF*100)}%) led to a losing trade",
        "LOW_CONF_WIN":    f"Low-confidence signal (<{int(_LOW_CONF*100)}%) led to a winning trade — potential missed optimisation",
    }
    return FalseSignal(
        signal_type=signal_type,
        count=len(matched),
        pct_of_total=0.0,  # filled by _annotate
        avg_loss_pct=round(avg_loss, 4),
        description=descriptions.get(signal_type, signal_type),
        examples=[r.trade_id for r in matched[:3]],
    )


def _annotate(s: FalseSignal, total: int) -> FalseSignal:
    s.pct_of_total = round(s.count / total, 4) if total > 0 else 0.0
    return s


def _generate_insights(signals: List[FalseSignal], false_rate: float) -> List[str]:
    insights = []
    by_type = {s.signal_type: s for s in signals}

    fb = by_type.get("FALSE_BUY")
    if fb and fb.count > 0:
        insights.append(
            f"{fb.count} false BUY signal(s) detected ({fb.pct_of_total*100:.1f}% of trades). "
            "Consider raising the confidence threshold for BUY recommendations."
        )

    hcl = by_type.get("HIGH_CONF_LOSS")
    if hcl and hcl.count > 0:
        insights.append(
            f"{hcl.count} high-confidence signal(s) led to losses. "
            "Confidence calibration may need review — the model may be overconfident."
        )

    lcw = by_type.get("LOW_CONF_WIN")
    if lcw and lcw.count > 0:
        insights.append(
            f"{lcw.count} low-confidence signal(s) resulted in wins. "
            "Some valuable opportunities may be filtered out by current confidence thresholds."
        )

    if false_rate > 0.3:
        insights.append(
            f"Overall false signal rate is {false_rate*100:.1f}% — above the 30% advisory threshold. "
            "Review signal generation quality."
        )
    elif false_rate == 0.0 and sum(s.count for s in signals) == 0:
        insights.append("No trades recorded yet. Insights will appear as paper trades accumulate.")

    return insights
