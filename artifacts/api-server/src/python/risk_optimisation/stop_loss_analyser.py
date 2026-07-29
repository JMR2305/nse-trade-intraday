"""
stop_loss_analyser.py — Phase 6.4
Stop loss hits, average loss, stop distance, trailing stop performance,
premature/late exits, and improvement recommendations.

READ-ONLY. ADVISORY-ONLY.
"""
from __future__ import annotations


def analyse_stop_loss(records: list) -> dict:
    """
    Analyse stop loss behaviour from FIFO-matched trade records.

    Stop loss exits are identified by exit_reason containing:
    'stop', 'sl', 'stoploss', 'stop_loss', 'trailing'

    Target exits: 'target', 'tgt', 'profit_target', 'take_profit'
    """
    if not records:
        return _empty_stop_loss()

    n = len(records)
    sl_exits = []
    target_exits = []
    time_exits = []

    for r in records:
        reason = (r.get("exit_reason") or "").lower()
        pnl = r.get("pnl") or 0.0
        pnl_pct = r.get("pnl_pct") or 0.0
        entry = float(r.get("entry_price") or 0.0)
        exit_p = float(r.get("exit_price") or 0.0)
        stop_dist = abs(exit_p - entry) / entry if entry > 0 else 0.0

        rec = {"pnl": pnl, "pnl_pct": pnl_pct, "stop_dist": stop_dist, "reason": reason}

        if any(kw in reason for kw in ("stop", "sl", "stoploss", "stop_loss", "trailing")):
            sl_exits.append(rec)
        elif any(kw in reason for kw in ("target", "tgt", "profit", "take_profit")):
            target_exits.append(rec)
        else:
            time_exits.append(rec)

    sl_count = len(sl_exits)
    sl_rate = sl_count / n if n > 0 else 0.0
    avg_loss_on_sl = (sum(r["pnl"] for r in sl_exits) / sl_count) if sl_count > 0 else 0.0
    avg_loss_pct_on_sl = (sum(r["pnl_pct"] for r in sl_exits) / sl_count) if sl_count > 0 else 0.0
    avg_stop_distance = (sum(r["stop_dist"] for r in sl_exits) / sl_count) if sl_count > 0 else 0.0

    # Trailing stop: exits where 'trailing' in reason
    trailing = [r for r in sl_exits if "trailing" in r["reason"]]
    trailing_count = len(trailing)
    trailing_avg_pnl = sum(r["pnl"] for r in trailing) / trailing_count if trailing_count > 0 else 0.0

    # Premature exits: SL hit but price later would have recovered (heuristic: loss < 0.5%)
    premature = [r for r in sl_exits if abs(r["pnl_pct"]) < 0.005]
    late_exits = [r for r in sl_exits if abs(r["pnl_pct"]) > 0.03]  # loss > 3%

    # Stop loss quality score: penalise high SL rate and large average loss
    sl_quality = max(0.0, min(1.0, 1.0 - sl_rate * 0.5 - min(abs(avg_loss_pct_on_sl), 0.10) * 5.0))

    return {
        "total_trades": n,
        "stop_loss_hits": sl_count,
        "stop_loss_rate": round(sl_rate, 4),
        "avg_loss_on_sl": round(avg_loss_on_sl, 2),
        "avg_loss_pct_on_sl": round(avg_loss_pct_on_sl, 4),
        "avg_stop_distance_pct": round(avg_stop_distance, 4),
        "trailing_stop_count": trailing_count,
        "trailing_stop_avg_pnl": round(trailing_avg_pnl, 2),
        "premature_exits": len(premature),
        "late_exits": len(late_exits),
        "target_exits": len(target_exits),
        "time_exits": len(time_exits),
        "stop_loss_quality_score": round(sl_quality, 4),
        "advisory": _sl_advisory(sl_rate, avg_loss_pct_on_sl, premature, late_exits),
    }


def _sl_advisory(sl_rate: float, avg_loss_pct: float, premature: list, late: list) -> str:
    if sl_rate > 0.50:
        return "High stop-loss rate (>50%): consider widening stop distance or adjusting entry criteria."
    if abs(avg_loss_pct) > 0.03:
        return "Average loss on stop hits exceeds 3%: consider tighter stops to limit capital erosion."
    if len(premature) > len(late):
        return "More premature exits than late exits: stops may be too tight — widen slightly."
    if len(late) > len(premature) * 2:
        return "Frequent late exits: tighten stops or use trailing stops to protect profits."
    return "Stop loss behaviour is within acceptable parameters."


def _empty_stop_loss() -> dict:
    return {
        "total_trades": 0,
        "stop_loss_hits": 0,
        "stop_loss_rate": 0.0,
        "avg_loss_on_sl": 0.0,
        "avg_loss_pct_on_sl": 0.0,
        "avg_stop_distance_pct": 0.0,
        "trailing_stop_count": 0,
        "trailing_stop_avg_pnl": 0.0,
        "premature_exits": 0,
        "late_exits": 0,
        "target_exits": 0,
        "time_exits": 0,
        "stop_loss_quality_score": 0.5,
        "advisory": "No trades recorded yet.",
    }
