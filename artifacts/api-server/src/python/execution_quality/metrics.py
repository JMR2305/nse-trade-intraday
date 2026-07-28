"""
execution_quality/metrics.py — Build ExecutionRecord list from paper trades.

Read-only: reads portfolio_store and signal_validation_db.
Never writes to any table or file.

PAPER TRADING / ADVISORY ONLY.
"""
from __future__ import annotations

import statistics
from datetime import datetime, timezone
from typing import List, Optional, Dict, Any

from .models import ExecutionRecord
from .report import score_trade


# ── Sector lookup (best-effort, never blocks) ────────────────────────────────

def _sector_of(symbol: str) -> str:
    try:
        from market_scanner import _sector_of as _ms_sector
        return _ms_sector(symbol) or "Unknown"
    except Exception:
        return "Unknown"


# ── Signal-validation fill-delay lookup ─────────────────────────────────────

def _sv_fill_delay(trade_id: str) -> Optional[float]:
    """
    Return fill delay in seconds by joining signal_validation_records
    on paper_order_id = trade_id.  Returns None if not found.
    """
    try:
        from signal_validation_db import _get_conn, _db_available
        if not _db_available():
            return None
        conn = _get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT signal_ts, paper_fill_ts
                    FROM   signal_validation_records
                    WHERE  paper_order_id = %s
                    LIMIT  1
                    """,
                    (trade_id,),
                )
                row = cur.fetchone()
            if row is None:
                return None
            sig_ts, fill_ts = row
            if sig_ts is None or fill_ts is None:
                return None
            def _to_aware(dt):
                if dt.tzinfo is None:
                    return dt.replace(tzinfo=timezone.utc)
                return dt
            delta = _to_aware(fill_ts) - _to_aware(sig_ts)
            return max(0.0, delta.total_seconds())
        finally:
            conn.close()
    except Exception:
        return None


# ── Record builder ────────────────────────────────────────────────────────────

def _parse_ts(ts_str: Optional[str]) -> Optional[datetime]:
    if not ts_str:
        return None
    try:
        return datetime.fromisoformat(ts_str)
    except (ValueError, TypeError):
        return None


def _build_record_from_buy(buy: Dict[str, Any]) -> ExecutionRecord:
    price     = float(buy.get("price", 0.0))
    total     = float(buy.get("total", 0.0))
    slip_rs   = float(buy.get("est_slippage", 0.0))
    slip_pct  = (slip_rs / total * 100) if total > 0 else 0.0
    stop_loss = float(buy.get("stop_loss", 0.0))
    target    = float(buy.get("target", 0.0))

    rec = ExecutionRecord(
        trade_id      = buy.get("id", ""),
        symbol        = buy.get("symbol", ""),
        strategy_id   = buy.get("strategy_id", "ai_scan"),
        strategy_name = buy.get("strategy_name", "AI Scan"),
        sector        = _sector_of(buy.get("symbol", "")),
        regime        = buy.get("market_regime_at_entry") or buy.get("regime", ""),
        signal_ts     = None,   # filled later from signal validation
        entry_ts      = buy.get("timestamp"),
        intended_entry_price = price,
        actual_entry_price   = price,
        entry_slippage_rs    = slip_rs,
        entry_slippage_pct   = slip_pct,
        fill_delay_seconds   = 0.0,
        quantity    = int(buy.get("quantity", 0)),
        entry_total = total,
        stop_loss_set = stop_loss > 0,
        target_set    = target > 0,
        stop_loss     = stop_loss,
        target        = target,
    )
    return rec


def _apply_exit(rec: ExecutionRecord, sell: Dict[str, Any]) -> None:
    """Enrich an ExecutionRecord with exit data from a matching SELL trade."""
    exit_price  = float(sell.get("price", 0.0))
    exit_total  = float(sell.get("total", 0.0))
    exit_slip   = float(sell.get("est_slippage", 0.0))
    exit_slip_pct = (exit_slip / exit_total * 100) if exit_total > 0 else 0.0

    rec.exit_ts            = sell.get("timestamp")
    rec.actual_exit_price  = exit_price
    rec.intended_exit_price = exit_price   # paper trades fill at signal price
    rec.exit_slippage_rs   = exit_slip
    rec.exit_slippage_pct  = exit_slip_pct
    rec.exit_type          = sell.get("exit_type", "SIGNAL_EXIT")
    rec.pnl                = float(sell.get("pnl", 0.0))
    rec.pnl_pct            = float(sell.get("pnl_pct", 0.0))
    rec.is_complete        = True

    # Exit delay: time from entry fill to exit fill
    entry_dt = _parse_ts(rec.entry_ts)
    exit_dt  = _parse_ts(rec.exit_ts)
    if entry_dt and exit_dt:
        def _aw(dt: datetime) -> datetime:
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        rec.exit_delay_seconds = max(0.0, (_aw(exit_dt) - _aw(entry_dt)).total_seconds())


def build_execution_records() -> List[ExecutionRecord]:
    """
    Build one ExecutionRecord per BUY trade.
    Matches each BUY to the next SELL for the same symbol (FIFO).
    Reads from portfolio_store only.
    """
    from portfolio_store import load_all_trades_any
    trades = load_all_trades_any()

    buys  = [t for t in trades if t.get("action") == "BUY"]
    sells = [t for t in trades if t.get("action") == "SELL"]

    # Group SELLs by symbol, sorted chronologically
    sell_idx: Dict[str, List[Dict[str, Any]]] = {}
    for s in sorted(sells, key=lambda x: x.get("timestamp", "")):
        sell_idx.setdefault(s.get("symbol", ""), []).append(s)

    # Track which SELLs have been consumed
    sell_ptr: Dict[str, int] = {}

    records: List[ExecutionRecord] = []
    for buy in sorted(buys, key=lambda x: x.get("timestamp", "")):
        rec = _build_record_from_buy(buy)
        sym = buy.get("symbol", "")
        buy_ts = buy.get("timestamp", "")

        # FIFO match: first unused SELL for this symbol after the BUY
        sym_sells = sell_idx.get(sym, [])
        ptr       = sell_ptr.get(sym, 0)
        while ptr < len(sym_sells):
            sell = sym_sells[ptr]
            if sell.get("timestamp", "") >= buy_ts:
                _apply_exit(rec, sell)
                sell_ptr[sym] = ptr + 1
                break
            ptr += 1
        else:
            sell_ptr[sym] = ptr  # exhausted, update pointer

        # Enrich with signal-validation fill delay
        sv_delay = _sv_fill_delay(rec.trade_id)
        if sv_delay is not None:
            rec.fill_delay_seconds = sv_delay

        rec.quality_score, rec.quality_grade = score_trade(rec)
        records.append(rec)

    return records


# ── Summary stats ─────────────────────────────────────────────────────────────

def compute_summary(records: List[ExecutionRecord]) -> dict:
    if not records:
        return {
            "total_trades":        0,
            "completed_trades":    0,
            "avg_execution_score": None,
            "avg_entry_slippage_rs":  None,
            "avg_entry_slippage_pct": None,
            "avg_exit_slippage_rs":   None,
            "avg_exit_slippage_pct":  None,
            "avg_fill_delay_seconds": None,
            "best_trade":  None,
            "worst_trade": None,
            "most_efficient_strategy": None,
            "highest_slippage_symbol": None,
        }

    scores    = [r.quality_score for r in records]
    completed = [r for r in records if r.is_complete]

    entry_slips_rs  = [r.entry_slippage_rs  for r in records]
    entry_slips_pct = [r.entry_slippage_pct for r in records]
    exit_slips_rs   = [r.exit_slippage_rs   for r in completed]
    exit_slips_pct  = [r.exit_slippage_pct  for r in completed]
    delays          = [r.fill_delay_seconds for r in records]

    best  = max(records, key=lambda r: r.quality_score)
    worst = min(records, key=lambda r: r.quality_score)

    # Most efficient strategy (highest avg score)
    strat_scores: Dict[str, List[int]] = {}
    for r in records:
        strat_scores.setdefault(r.strategy_name or "Unknown", []).append(r.quality_score)
    most_efficient = max(strat_scores, key=lambda k: statistics.mean(strat_scores[k])) if strat_scores else None

    # Highest slippage symbol
    sym_slips: Dict[str, List[float]] = {}
    for r in records:
        sym_slips.setdefault(r.symbol, []).append(r.entry_slippage_rs)
    highest_slip_sym = max(sym_slips, key=lambda k: statistics.mean(sym_slips[k])) if sym_slips else None

    def _safe_mean(lst):
        return round(statistics.mean(lst), 4) if lst else None

    return {
        "total_trades":        len(records),
        "completed_trades":    len(completed),
        "avg_execution_score": round(statistics.mean(scores), 1),
        "avg_entry_slippage_rs":  _safe_mean(entry_slips_rs),
        "avg_entry_slippage_pct": _safe_mean(entry_slips_pct),
        "avg_exit_slippage_rs":   _safe_mean(exit_slips_rs),
        "avg_exit_slippage_pct":  _safe_mean(exit_slips_pct),
        "avg_fill_delay_seconds": _safe_mean(delays),
        "best_trade": {
            "trade_id": best.trade_id,
            "symbol":   best.symbol,
            "score":    best.quality_score,
            "grade":    best.quality_grade,
        },
        "worst_trade": {
            "trade_id": worst.trade_id,
            "symbol":   worst.symbol,
            "score":    worst.quality_score,
            "grade":    worst.quality_grade,
        },
        "most_efficient_strategy": most_efficient,
        "highest_slippage_symbol": highest_slip_sym,
    }
