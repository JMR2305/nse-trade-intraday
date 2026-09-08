"""
phase20_eod_status.py — EOD square-off status for the Mission Control panel.

Returns a lightweight payload that lets the dashboard show:
  • A countdown to 15:20 IST while the market is still open.
  • An "active" message during the 15:20–15:30 IST window.
  • The result of today's force-close (symbol, exit_price, realized_pnl).
  • A MARKET_CLOSE_EXIT_BLOCKED warning when a position couldn't be closed.

Design note — two data sources for force_close_results:
  1. The phase20 ledger (phase20_paper_trades, queried by exit_rule).
     This is the canonical, authoritative source.  MARKET_CLOSE_EXIT (the
     intraday 15:20 IST path) writes to the ledger via record_exit() but
     does NOT emit a pipeline event, so event-only queries miss it.
  2. Pipeline events — used only for MARKET_CLOSE_EXIT_BLOCKED, which IS
     emitted explicitly by eod_force_close_open_positions().

The function is read-only and never raises.  All expensive work is gated
behind today's IST date so stale results can never be returned.

PAPER TRADING / RESEARCH ONLY.
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Tuple

# ── Constants ─────────────────────────────────────────────────────────────────

_IST_OFFSET = timedelta(hours=5, minutes=30)

# 15:20 IST — intraday MARKET_CLOSE_EXIT trigger
_SQUAREOFF_HOUR = 15
_SQUAREOFF_MIN = 20

# 15:30 IST — POST_CLOSE begins; EOD force-exit fires here too
_POST_CLOSE_HOUR = 15
_POST_CLOSE_MIN = 30

# Only show countdown within this many seconds of 15:20 IST
_SHOW_COUNTDOWN_WITHIN_SEC = 30 * 60  # 30 minutes

# EOD exit rules that should appear in force_close_results
EOD_EXIT_RULES = ("MARKET_CLOSE_EXIT", "POST_CLOSE_FORCE_EXIT")

# Pipeline event type for blocked EOD closes
_BLOCKED_TYPE = "MARKET_CLOSE_EXIT_BLOCKED"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _now_ist() -> datetime:
    """Current time in IST.  Falls back to UTC+5:30 if zoneinfo is absent."""
    try:
        from zoneinfo import ZoneInfo  # Python 3.9+
        return datetime.now(ZoneInfo("Asia/Kolkata"))
    except Exception:
        return datetime.now(timezone.utc).astimezone(
            timezone(timedelta(hours=5, minutes=30))
        )


def _today_ist_str(now_ist: datetime) -> str:
    return now_ist.strftime("%Y-%m-%d")


def _ist_midnight_utc_lower(now_ist: datetime) -> str:
    """UTC timestamp for today's IST midnight (00:00:00 IST = 18:30 UTC prev day).

    Used as a WHERE lower-bound when querying UTC-stored timestamps so that
    early-morning IST events (00:00–05:30 IST, where UTC date differs from IST
    date) are still included correctly.
    """
    # IST midnight = today at 00:00 IST = (today - 5h30m) UTC
    ist_midnight = now_ist.replace(hour=0, minute=0, second=0, microsecond=0)
    utc_midnight = ist_midnight.astimezone(timezone.utc)
    return utc_midnight.strftime("%Y-%m-%dT%H:%M:%SZ")


def _eod_ran_today(today_str: str) -> bool:
    """True when the eod_squareoff KV claim for today has been set."""
    try:
        from phase20_store import kv_get
        return kv_get(f"eod_squareoff:{today_str}") is not None
    except Exception:
        return False


# ── Ledger query — primary source for force_close_results ────────────────────

def _fetch_ledger_eod_rows(
    ist_midnight_utc: str,
) -> List[Dict[str, Any]]:
    """Query phase20_paper_trades for today's CLOSED EOD-exit rows.

    MARKET_CLOSE_EXIT (intraday 15:20 path) writes to the ledger but does NOT
    emit a pipeline event.  Querying the ledger here is the only reliable way
    to surface those closures in the status panel.

    Returns rows sorted newest exit_ts first.  Never raises.
    """
    rules_placeholder = ", ".join(["%s"] * len(EOD_EXIT_RULES))
    sql = (
        "SELECT symbol, exit_price, realized_pnl, exit_rule, exit_ts, "
        "       fill_price, quantity "
        "FROM phase20_paper_trades "
        f"WHERE status = 'CLOSED' "
        f"  AND exit_rule IN ({rules_placeholder}) "
        "  AND exit_ts >= %s "
        "ORDER BY exit_ts DESC "
        "LIMIT 50"
    )
    params = list(EOD_EXIT_RULES) + [ist_midnight_utc]

    try:
        from scan_state_store import db_available, _connect
        if not db_available():
            return []
        conn = _connect()
        try:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                rows = cur.fetchall()
        finally:
            conn.close()

        results = []
        for r in rows:
            sym, exit_price, realized_pnl, exit_rule, exit_ts, fill_price, qty = r
            results.append({
                "symbol": sym,
                "exit_rule": exit_rule or "UNKNOWN",
                "exit_price": float(exit_price) if exit_price is not None else None,
                "realized_pnl": float(realized_pnl) if realized_pnl is not None else None,
                "exit_price_source": None,   # enriched by caller from phase20_eod_outcomes
                "fallback_used": False,
                "exit_ts": exit_ts,
            })
        return results

    except Exception:
        return []


# ── Pipeline event query — MARKET_CLOSE_EXIT_BLOCKED only ────────────────────

def _fetch_blocked_events(
    ist_midnight_utc: str,
) -> List[Dict[str, Any]]:
    """Query pipeline_events for MARKET_CLOSE_EXIT_BLOCKED events today.

    Uses the UTC lower-bound derived from IST midnight so early-morning events
    are not missed.  Returns entries deduplicated by symbol (newest first).
    Never raises.
    """
    blocked: List[Dict[str, Any]] = []
    try:
        from pipeline_events import query_events
        evts = query_events(event_type=_BLOCKED_TYPE, limit=50, newest_first=True)
        for e in evts:
            ts_str: str = str(e.get("ts") or "")
            # Filter: event ts must be >= today's IST midnight in UTC
            if ts_str < ist_midnight_utc:
                continue
            payload: Dict[str, Any] = e.get("payload") or {}
            sym = e.get("symbol") or payload.get("symbol") or None
            blocked.append({
                "symbol": sym,
                "trade_id": payload.get("trade_id"),
                "reason": payload.get("reason"),
                "ts": ts_str,
            })
    except Exception:
        pass

    # Deduplicate by symbol (list already newest-first from query)
    seen: set[str] = set()
    dedup = []
    for r in blocked:
        key = str(r.get("symbol") or r.get("trade_id") or id(r))
        if key not in seen:
            seen.add(key)
            dedup.append(r)
    return dedup


# ── Public API ────────────────────────────────────────────────────────────────

def build_eod_status_payload() -> Dict[str, Any]:
    """Compute the EOD square-off status payload.  Never raises."""
    try:
        now_ist = _now_ist()
        today_str = _today_ist_str(now_ist)
        ist_midnight_utc = _ist_midnight_utc_lower(now_ist)

        # Squareoff and post-close anchor times for today
        squareoff_ts = now_ist.replace(
            hour=_SQUAREOFF_HOUR, minute=_SQUAREOFF_MIN, second=0, microsecond=0
        )
        post_close_ts = now_ist.replace(
            hour=_POST_CLOSE_HOUR, minute=_POST_CLOSE_MIN, second=0, microsecond=0
        )

        time_to_squareoff_sec = int((squareoff_ts - now_ist).total_seconds())
        in_squareoff_window = squareoff_ts <= now_ist < post_close_ts
        past_post_close = now_ist >= post_close_ts

        # Only expose the countdown within the configurable look-ahead window
        show_countdown = (
            not in_squareoff_window
            and not past_post_close
            and 0 < time_to_squareoff_sec <= _SHOW_COUNTDOWN_WITHIN_SEC
        )

        eod_ran = _eod_ran_today(today_str)

        # Force-close results come from the ledger (authoritative; covers both
        # MARKET_CLOSE_EXIT from the intraday path and POST_CLOSE_FORCE_EXIT).
        force_close_results = _fetch_ledger_eod_rows(ist_midnight_utc)

        # Enrich exit_price_source from durable outcome records (TASK 7).
        # phase20_eod_outcomes stores price-source provenance that the ledger
        # table does not. Enrichment is advisory — never let it kill the payload.
        try:
            from phase20_eod_outcomes import get_eod_outcomes as _geo
            _outcomes = _geo(session_date=today_str, limit=200)
            _src_map: Dict[str, str] = {}
            for _o in _outcomes:
                _sym_o = str(_o.get("symbol") or "").upper()
                _src = _o.get("exit_price_source")
                if _sym_o and _src:
                    _src_map[_sym_o] = str(_src)
            for _row in force_close_results:
                _s = str(_row.get("symbol") or "").upper()
                if _s in _src_map and _row.get("exit_price_source") is None:
                    _row["exit_price_source"] = _src_map[_s]
                    _row["fallback_used"] = _src_map[_s] in (
                        "fill_price_fallback",
                        "ohlcv_cache_prev_session_close",
                    )
        except Exception:
            pass

        # Blocked events come from pipeline events (the only place they're recorded).
        blocked_events = _fetch_blocked_events(ist_midnight_utc)

        return {
            "success": True,
            "time_to_squareoff_sec": time_to_squareoff_sec,
            "squareoff_time_ist": f"{_SQUAREOFF_HOUR:02d}:{_SQUAREOFF_MIN:02d} IST",
            "in_squareoff_window": in_squareoff_window,
            "past_post_close": past_post_close,
            "show_countdown": show_countdown,
            "eod_ran_today": eod_ran,
            "force_close_results": force_close_results,
            "blocked_events": blocked_events,
            "now_ist": now_ist.strftime("%H:%M:%S"),
            "today_ist": today_str,
        }
    except Exception as exc:
        return {"success": False, "error": str(exc)[:200]}
