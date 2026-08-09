"""
validation_collector.py — Phase 6.1
Reads paper_trades, FIFO-matches BUY→SELL pairs, enriches with full
decision context from existing modules.

READ-ONLY. Never touches trading engine, orders, strategies, signals, or portfolio.
"""
from __future__ import annotations
import sys, os
from typing import List, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from .validation_models import TradeRecord, SessionMetadata


# ---------------------------------------------------------------------------
# FIFO matching helpers
# ---------------------------------------------------------------------------

def _fifo_match(raw_trades: list) -> List[Tuple[dict, dict]]:
    """
    FIFO-match BUY and SELL records by symbol.
    Returns a list of (buy_record, sell_record) pairs.
    """
    from collections import defaultdict

    buy_queues: dict = defaultdict(list)
    completed: list = []

    sorted_trades = sorted(
        raw_trades,
        key=lambda t: t.get("timestamp", t.get("trade_ts", "")),
    )

    for trade in sorted_trades:
        action = (trade.get("action") or "").upper()
        symbol = trade.get("symbol", "")
        if action == "BUY":
            buy_queues[symbol].append(trade)
        elif action == "SELL" and buy_queues[symbol]:
            buy = buy_queues[symbol].pop(0)
            completed.append((buy, trade))

    return completed


def _holding_minutes(buy: dict, sell: dict) -> float:
    """Minutes between BUY timestamp and SELL timestamp."""
    from datetime import datetime, timezone

    def _parse(t: dict) -> Optional[datetime]:
        ts = t.get("timestamp") or t.get("trade_ts")
        if not ts:
            return None
        try:
            if isinstance(ts, datetime):
                return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
            dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except Exception:
            return None

    buy_ts = _parse(buy)
    sell_ts = _parse(sell)
    if buy_ts is None or sell_ts is None:
        return 0.0
    delta = sell_ts - buy_ts
    return max(0.0, delta.total_seconds() / 60.0)


# ---------------------------------------------------------------------------
# Aggregate module enrichment (current-session snapshots)
# ---------------------------------------------------------------------------

# Hard deadline for aggregate snapshot helpers.  The underlying dashboard
# modules can trigger live yfinance network calls that hang indefinitely;
# analytics collection must never block on them.
_SNAPSHOT_TIMEOUT_SECONDS = 2.0


def _call_with_timeout(fn, timeout: float = _SNAPSHOT_TIMEOUT_SECONDS):
    """
    Run fn() in a daemon worker thread and return its result, or None if it
    raises or does not complete within `timeout` seconds.

    The worker thread is a daemon, so a hung network call cannot keep the
    process alive; we simply abandon it and return None.
    """
    import threading

    result: list = [None]

    def _worker() -> None:
        try:
            result[0] = fn()
        except Exception:
            result[0] = None

    t = threading.Thread(target=_worker, daemon=True)
    t.start()
    t.join(timeout)
    if t.is_alive():
        return None
    return result[0]


def _get_exec_score_snapshot() -> Optional[float]:
    def _fetch():
        from execution_quality.api import get_summary
        s = get_summary()
        return s.get("avg_execution_score")

    return _call_with_timeout(_fetch)


def _get_executive_snapshot() -> Optional[float]:
    def _fetch():
        from executive_dashboard.shared_services import get_executive_snapshot
        snap = get_executive_snapshot()
        return snap.get("executive_score")

    return _call_with_timeout(_fetch)


def _get_portfolio_value() -> Optional[float]:
    def _fetch():
        from portfolio_performance.api import get_summary
        s = get_summary()
        return s.get("total_portfolio_value")

    return _call_with_timeout(_fetch)


# ---------------------------------------------------------------------------
# Build a single TradeRecord from a matched (buy, sell) pair
# ---------------------------------------------------------------------------

def _build_record(buy: dict, sell: dict, exec_score: Optional[float], exec_snap: Optional[float]) -> TradeRecord:
    buy_meta = buy.get("metadata") or {}
    sell_meta = sell.get("metadata") or {}

    symbol = buy.get("symbol", sell.get("symbol", "UNKNOWN"))
    entry_price = float(buy.get("price", 0.0))
    exit_price = float(sell.get("price", 0.0))
    quantity = int(buy.get("quantity", sell.get("quantity", 0)))

    pnl = (exit_price - entry_price) * quantity
    pnl_pct = ((exit_price - entry_price) / entry_price * 100.0) if entry_price > 0 else 0.0
    holding_mins = _holding_minutes(buy, sell)

    # AI fields from BUY metadata
    ai_conf = buy_meta.get("ai_confidence") or buy_meta.get("confidence")
    if ai_conf is not None:
        try:
            ai_conf = float(ai_conf)
        except (TypeError, ValueError):
            ai_conf = None

    ai_rec = buy_meta.get("ai_recommendation") or buy_meta.get("recommendation")
    signal_status = buy_meta.get("signal_validation_status") or buy_meta.get("signal_status")

    risk_score_raw = buy_meta.get("risk_score")
    risk_score = float(risk_score_raw) if risk_score_raw is not None else None

    # Execution quality: prefer per-trade score from SELL metadata, fall back to session avg
    eq_raw = sell_meta.get("execution_quality_score") or buy_meta.get("execution_quality_score")
    eq_score = float(eq_raw) if eq_raw is not None else exec_score

    portfolio_val = buy_meta.get("portfolio_value_at_entry")
    if portfolio_val is not None:
        try:
            portfolio_val = float(portfolio_val)
        except (TypeError, ValueError):
            portfolio_val = None

    # Exit reason: prefer sell reason field, then metadata
    exit_reason = (
        sell.get("reason")
        or sell_meta.get("exit_reason")
        or sell_meta.get("reason")
        or "Unknown"
    )

    return TradeRecord(
        trade_id=sell.get("id", f"{symbol}_{sell.get('timestamp', '')}"),
        timestamp=sell.get("timestamp") or sell.get("trade_ts") or "",
        symbol=symbol,
        strategy=buy_meta.get("strategy", "Unknown"),
        market_regime=buy_meta.get("market_regime") or buy_meta.get("regime", "Unknown"),
        sector=buy_meta.get("sector", "Unknown"),
        entry_price=entry_price,
        exit_price=exit_price,
        quantity=quantity,
        holding_time_minutes=holding_mins,
        pnl=pnl,
        pnl_pct=pnl_pct,
        execution_quality_score=eq_score,
        ai_confidence=ai_conf,
        ai_recommendation=ai_rec,
        signal_validation_status=signal_status,
        risk_score=risk_score,
        portfolio_value_at_entry=portfolio_val,
        executive_score_snapshot=exec_snap,
        exit_reason=exit_reason,
    )


# ---------------------------------------------------------------------------
# Public: collect all trade records
# ---------------------------------------------------------------------------

def collect_all_trade_records() -> List[TradeRecord]:
    """
    Read all paper trades from portfolio_store, FIFO-match BUY→SELL pairs,
    and enrich with context from existing modules.

    Background-safe: called only from shared_services, never from trading engine.
    """
    try:
        from portfolio_store import load_trades
        raw = load_trades()
    except Exception:
        return []

    if not raw:
        return []

    pairs = _fifo_match(raw)
    if not pairs:
        return []

    # Fetch aggregate snapshots once (not per-trade, to keep collection fast)
    exec_score = _get_exec_score_snapshot()
    exec_snap = _get_executive_snapshot()

    records: List[TradeRecord] = []
    for buy, sell in pairs:
        try:
            rec = _build_record(buy, sell, exec_score, exec_snap)
            records.append(rec)
        except Exception:
            continue

    return records


# ---------------------------------------------------------------------------
# Public: today's session metadata
# ---------------------------------------------------------------------------

def collect_session_metadata() -> SessionMetadata:
    from datetime import date

    today = date.today().isoformat()
    market_status = "UNKNOWN"
    pre_open_summary = "Unavailable"
    market_breadth = "Unavailable"
    nifty: Optional[float] = None
    bank_nifty: Optional[float] = None
    india_vix: Optional[float] = None
    leading_sector = "Unknown"
    top_gap = "Unavailable"
    session_start: Optional[str] = None
    session_end: Optional[str] = None

    try:
        from preopen_engine import get_status
        status = get_status()
        market_status = status.get("market_status", "UNKNOWN")
        pre_open_summary = status.get("summary", "Unavailable")
        sector_data = status.get("top_sector") or status.get("leading_sector")
        if sector_data:
            leading_sector = str(sector_data)
        gap = status.get("top_gap") or status.get("highest_gap")
        if gap:
            top_gap = str(gap)
        session_start = status.get("session_start")
        session_end = status.get("session_end")
    except Exception:
        pass

    try:
        from meta_health import get_meta_health
        health = get_meta_health()
        indices = health.get("indices") or {}
        nifty_data = indices.get("NIFTY 50") or indices.get("NIFTY50") or {}
        bank_nifty_data = indices.get("NIFTY BANK") or indices.get("BANKNIFTY") or {}
        vix_data = indices.get("INDIA VIX") or {}
        if isinstance(nifty_data, dict):
            nifty = nifty_data.get("last_price") or nifty_data.get("close")
        if isinstance(bank_nifty_data, dict):
            bank_nifty = bank_nifty_data.get("last_price") or bank_nifty_data.get("close")
        if isinstance(vix_data, dict):
            india_vix = vix_data.get("last_price") or vix_data.get("close")
        breadth = health.get("market_breadth")
        if breadth:
            market_breadth = str(breadth)
    except Exception:
        pass

    return SessionMetadata(
        trading_date=today,
        session_start=session_start,
        session_end=session_end,
        market_status=market_status,
        pre_open_summary=pre_open_summary,
        market_breadth=market_breadth,
        nifty=nifty,
        bank_nifty=bank_nifty,
        india_vix=india_vix,
        leading_sector=leading_sector,
        top_gap=top_gap,
    )
