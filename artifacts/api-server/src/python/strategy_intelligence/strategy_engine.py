"""
strategy_intelligence/strategy_engine.py — Core data loader and profile builder.

Reads from portfolio_store (paper_trades) and execution_quality (quality scores).
FIFO BUY→SELL matching — same pattern as portfolio_performance/performance_engine.py.
READ-ONLY. PAPER TRADING / ADVISORY ONLY.
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import List, Dict, Optional, Any

from .strategy_models import ClosedTrade, StrategyProfile, TIME_SLOTS, DAYS_OF_WEEK

_IST = timezone(timedelta(hours=5, minutes=30))


# ── Helpers ───────────────────────────────────────────────────────────────────

def _sector_of(symbol: str) -> str:
    try:
        from market_scanner import _sector_of as _ms
        return _ms(symbol) or "Unknown"
    except Exception:
        return "Unknown"


def _parse_ts(ts: Optional[str]) -> Optional[datetime]:
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(ts)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


def _to_ist(dt: datetime) -> datetime:
    return dt.astimezone(_IST)


def _time_slot(hour: int, minute: int) -> str:
    total = hour * 60 + minute
    if total < 10 * 60:
        return "09:15–10:00"
    elif total < 11 * 60:
        return "10:00–11:00"
    elif total < 12 * 60:
        return "11:00–12:00"
    elif total < 13 * 60:
        return "12:00–13:00"
    elif total < 14 * 60:
        return "13:00–14:00"
    else:
        return "14:00–15:30"


def _holding_seconds(entry_ts: Optional[str], exit_ts: Optional[str]) -> float:
    a = _parse_ts(entry_ts)
    b = _parse_ts(exit_ts)
    if a is None or b is None:
        return 0.0
    if a.tzinfo is None:
        a = a.replace(tzinfo=timezone.utc)
    if b.tzinfo is None:
        b = b.replace(tzinfo=timezone.utc)
    return max(0.0, (b - a).total_seconds())


# ── Execution quality score lookup (best-effort) ─────────────────────────────

def _build_eq_index() -> Dict[str, tuple]:
    """Return {trade_id: (quality_score, quality_grade)} from execution quality."""
    try:
        from execution_quality.metrics import build_execution_records
        recs = build_execution_records()
        return {r.trade_id: (r.quality_score, r.quality_grade) for r in recs}
    except Exception:
        return {}


# ── FIFO BUY→SELL matching ───────────────────────────────────────────────────

def build_closed_trades(raw_trades: List[Dict[str, Any]]) -> List[ClosedTrade]:
    """
    Match each BUY to the chronologically-next SELL for the same symbol (FIFO).
    Returns only completed round-trips.
    """
    eq_index = _build_eq_index()

    buys  = [t for t in raw_trades if t.get("action") == "BUY"]
    sells = [t for t in raw_trades if t.get("action") == "SELL"]

    sell_idx: Dict[str, List[Dict[str, Any]]] = {}
    for s in sorted(sells, key=lambda x: x.get("timestamp", "")):
        sell_idx.setdefault(s.get("symbol", ""), []).append(s)

    sell_ptr: Dict[str, int] = {}
    closed: List[ClosedTrade] = []

    for buy in sorted(buys, key=lambda x: x.get("timestamp", "")):
        sym      = buy.get("symbol", "")
        buy_ts   = buy.get("timestamp", "")
        qty      = int(buy.get("quantity", 0))
        ep       = float(buy.get("price", 0.0))
        et       = float(buy.get("total", 0.0))
        tid      = buy.get("id", "")

        # Enrich with IST time fields from entry timestamp
        entry_dt = _parse_ts(buy_ts)
        ist_dt   = _to_ist(entry_dt) if entry_dt else None
        slot     = _time_slot(ist_dt.hour, ist_dt.minute) if ist_dt else ""
        dow      = DAYS_OF_WEEK[ist_dt.weekday()] if ist_dt and ist_dt.weekday() < 5 else ""
        hour_ist = ist_dt.hour if ist_dt else 9

        qs, qg = eq_index.get(tid, (0, ""))

        ct = ClosedTrade(
            trade_id          = tid,
            symbol            = sym,
            sector            = _sector_of(sym),
            strategy_id       = buy.get("strategy_id", "ai_scan"),
            strategy_name     = buy.get("strategy_name", "AI Scan"),
            entry_ts          = buy_ts,
            entry_price       = ep,
            quantity          = qty,
            entry_total       = et,
            stop_loss         = float(buy.get("stop_loss", 0.0)),
            target            = float(buy.get("target", 0.0)),
            market_regime     = buy.get("market_regime_at_entry") or buy.get("regime", "Unknown"),
            signal_confidence = float(buy.get("signal_confidence", 0.0)),
            quality_score     = qs,
            quality_grade     = qg,
            time_slot         = slot,
            day_of_week       = dow,
            hour_ist          = hour_ist,
        )

        sym_sells = sell_idx.get(sym, [])
        ptr       = sell_ptr.get(sym, 0)

        while ptr < len(sym_sells):
            sell = sym_sells[ptr]
            if sell.get("timestamp", "") >= buy_ts:
                xp = float(sell.get("price", 0.0))
                xt = float(sell.get("total", 0.0))
                ct.exit_ts        = sell.get("timestamp")
                ct.exit_price     = xp
                ct.pnl            = float(sell.get("pnl", xt - et))
                ct.pnl_pct        = float(sell.get("pnl_pct", (ct.pnl / et * 100) if et else 0.0))
                ct.exit_type      = sell.get("exit_type", "SIGNAL_EXIT")
                ct.holding_seconds = _holding_seconds(buy_ts, ct.exit_ts)
                sell_ptr[sym] = ptr + 1
                break
            ptr += 1
        else:
            sell_ptr[sym] = ptr

        if ct.exit_ts:
            closed.append(ct)

    return closed


# ── Open trade count per strategy ─────────────────────────────────────────────

def count_open_trades(raw_trades: List[Dict[str, Any]]) -> Dict[str, int]:
    """Count open (unmatched BUY) trades per strategy_name."""
    from collections import Counter
    buys  = [t for t in raw_trades if t.get("action") == "BUY"]
    sells = [t for t in raw_trades if t.get("action") == "SELL"]

    sell_idx: Dict[str, int] = {}
    for s in sorted(sells, key=lambda x: x.get("timestamp", "")):
        sym = s.get("symbol", "")
        sell_idx[sym] = sell_idx.get(sym, 0) + 1

    buy_counts: Dict[str, int] = {}
    open_by_strategy: Counter = Counter()

    for buy in sorted(buys, key=lambda x: x.get("timestamp", "")):
        sym  = buy.get("symbol", "")
        name = buy.get("strategy_name", "AI Scan")
        buy_counts[sym] = buy_counts.get(sym, 0) + 1
        if buy_counts[sym] > sell_idx.get(sym, 0):
            open_by_strategy[name] += 1

    return dict(open_by_strategy)


# ── Load all data from portfolio_store ────────────────────────────────────────

def load_all_data() -> Dict[str, Any]:
    """
    Single authoritative data load for all strategy_intelligence sub-modules.
    Returns {"closed_trades": [...], "open_counts": {...}, "raw_trades": [...]}.
    """
    from portfolio_store import load_all_trades_any
    raw = load_all_trades_any()
    closed = build_closed_trades(raw)
    open_counts = count_open_trades(raw)
    return {
        "closed_trades": closed,
        "open_counts":   open_counts,
        "raw_trades":    raw,
    }
