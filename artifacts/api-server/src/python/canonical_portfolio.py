"""canonical_portfolio.py — THE single canonical paper-portfolio snapshot.

All portfolio-facing endpoints must derive positions, cash, and equity from
this module so every page shows identical numbers.

Sources (in accordance with the platform's single-source-of-truth rules):
  • positions       — phase20 paper trade ledger (OPEN / EXIT_PENDING rows)
  • realized P&L    — phase20 ledger CLOSED rows (realized_pnl)
  • initial capital — portfolio_store.INITIAL_CAPITAL (never hardcoded)
  • marks           — live Kite quotes when a verified broker session exists,
                      otherwise last canonical scan prices (mark_source flags)

Cash accounting (identical to the Phase 4A dashboard):
  cash   = INITIAL_CAPITAL − Σ(open cost) + Σ(realized_pnl of CLOSED rows)
  equity = INITIAL_CAPITAL + Σ(realized) + Σ(unrealized MTM where marks known)

READ-ONLY: this module never mutates any store.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

OPEN_STATUSES = ("OPEN", "EXIT_PENDING")

_AGE_TS_KEYS = ("fill_ts", "signal_ts", "snapshot_ts", "created_at")


def _parse_ts_utc(raw: object) -> "datetime | None":
    """Parse any ISO-8601 string into an *aware* UTC datetime.

    Handles Z-suffix, explicit UTC offset, and naive local strings (treated
    as UTC so subtraction from utcnow() never raises TypeError).
    Returns None on any parse failure or empty input.
    """
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, TypeError):
        return None


def _pick_age_ts(row: Dict[str, Any]) -> Dict[str, Any]:
    """Return {"opened_at": <str|None>, "age_ts_source": <str|None>}.

    Iterates the fallback chain in priority order and returns the first
    timestamp value that is both non-empty AND parses without error (including
    naive strings treated as UTC). A malformed or unparseable value is skipped.
    """
    for key in _AGE_TS_KEYS:
        raw = row.get(key)
        if raw and _parse_ts_utc(raw) is not None:
            return {"opened_at": str(raw), "age_ts_source": key}
    return {"opened_at": None, "age_ts_source": None}


def _ledger_rows() -> List[Dict[str, Any]]:
    import phase20_executor as p20
    return p20.get_ledger(limit=10_000)


def _scan_marks() -> tuple[Dict[str, float], Dict[str, str], Optional[str]]:
    """Return ({symbol: last-scan price}, {symbol: sector}, scan_id)."""
    marks: Dict[str, float] = {}
    sectors: Dict[str, str] = {}
    scan_id: Optional[str] = None
    try:
        import scan_state_store
        snap = scan_state_store.load_latest_snapshot() or {}
        scan_id = snap.get("scan_id")
        for r in snap.get("recommendations") or []:
            sym = r.get("symbol")
            if sym and isinstance(r.get("entry_price"), (int, float)):
                marks[sym] = float(r["entry_price"])
            if sym and r.get("sector"):
                sectors[sym] = r["sector"]
    except Exception:
        pass
    return marks, sectors, scan_id


def _live_marks(symbols: List[str]) -> Dict[str, float]:
    """Live Kite LTPs for symbols, only when a broker session is verified."""
    out: Dict[str, float] = {}
    if not symbols:
        return out
    try:
        import kite_quote_provider as kqp
        if not kqp.kite_session_verified():
            return out
        for s, q in (kqp.get_quotes(sorted(set(symbols))) or {}).items():
            if q.get("data_source") == "kite_live" and isinstance(q.get("ltp"), (int, float)):
                out[s] = float(q["ltp"])
    except Exception:
        pass
    return out


def build_canonical_portfolio() -> Dict[str, Any]:
    """Canonical portfolio snapshot derived exclusively from the ledger."""
    import portfolio_store
    cap = float(portfolio_store.INITIAL_CAPITAL)

    rows = _ledger_rows()
    open_rows = [r for r in rows if r.get("status") in OPEN_STATUSES]
    closed = [r for r in rows if r.get("status") == "CLOSED"]
    realized = round(sum(float(r.get("realized_pnl") or 0.0) for r in closed), 2)

    scan_marks, scan_sectors, scan_id = _scan_marks()
    live = _live_marks([r.get("symbol") for r in open_rows if r.get("symbol")])

    positions: List[Dict[str, Any]] = []
    invested = 0.0
    unreal = 0.0
    unreal_known = True
    sector_exp: Dict[str, float] = defaultdict(float)
    for r in open_rows:
        sym = r.get("symbol")
        qty = int(r.get("quantity") or 0)
        fp = float(r.get("fill_price") or 0.0)
        cost = round(qty * fp, 2)
        invested += cost
        sector = r.get("sector") or scan_sectors.get(sym) or "UNKNOWN"
        sector_exp[sector] += cost
        if sym in live:
            m: Optional[float] = live[sym]
            m_src: Optional[str] = "live"
        elif sym in scan_marks:
            m, m_src = scan_marks[sym], "scan"
        else:
            m, m_src = None, None
        u = round((m - fp) * qty, 2) if m is not None else None
        if u is None:
            unreal_known = False
        else:
            unreal += u
        positions.append({
            "trade_id": r.get("trade_id"),
            "symbol": sym,
            "quantity": qty,
            "avg_price": fp,
            "cost": cost,
            "mark_price": m,
            "mark_source": m_src,
            "market_value": round((m if m is not None else fp) * qty, 2),
            "unrealized_pnl": u,
            "status": r.get("status"),
            "sector": sector,
            "strategy_id": r.get("strategy_id"),
            # Fallback chain for holding-age computation.
            # Priority: fill_ts → signal_ts → snapshot_ts → created_at.
            # Each candidate is parse-validated so a non-empty but malformed
            # value (e.g. "N/A", legacy placeholder) does not block a later
            # valid fallback. age_ts_source records which field was actually used.
            **_pick_age_ts(r),
            "stop_loss": r.get("stop_loss"),
            "target": r.get("target"),
            "scan_id": r.get("scan_id"),
        })

    cash = round(cap - invested + realized, 2)
    unreal_out = round(unreal, 2) if unreal_known else None
    # When a mark is missing, equity is computed with the KNOWN MTM only and
    # equity_complete=false is set — never silently pretend it is exact.
    equity = round(cap + realized + unreal, 2)

    # Portfolio version: deterministic over the ledger content that matters.
    latest_update = max((str(r.get("updated_at") or r.get("exit_ts") or r.get("fill_ts") or "")
                         for r in rows), default="")
    portfolio_version = f"{len(rows)}:{latest_update}"

    return {
        "source": "phase20_ledger",
        "scan_id": scan_id,
        "portfolio_version": portfolio_version,
        "initial_capital": cap,
        "cash": cash,
        "invested_value": round(invested, 2),
        "equity": equity,
        "equity_complete": unreal_known,
        "realized_pnl": realized,
        "unrealized_pnl": unreal_out,
        "unrealized_note": (None if unreal_known
                            else "mark price missing for some symbols in latest scan"),
        "open_position_count": len(open_rows),
        "closed_trade_count": len(closed),
        "positions": positions,
        "sector_exposure": {k: round(v, 2)
                            for k, v in sorted(sector_exp.items(), key=lambda x: -x[1])},
        "mark_basis": ("live" if live and len(live) == len(open_rows)
                       else "mixed" if live else "scan"),
    }


def canonical_trades(scope: str = "session") -> List[Dict[str, Any]]:
    """Trade history rows derived exclusively from the phase20 ledger.

    Emits one row per fill event (BUY on entry, SELL on exit of CLOSED rows)
    in the same shape legacy /api/trades consumers expect.
    scope="all" returns everything; default returns today's IST fills only.
    """
    from datetime import datetime, timezone, timedelta
    IST = timezone(timedelta(hours=5, minutes=30))

    def _ist_date(ts: Any) -> Optional[str]:
        try:
            dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
            return dt.astimezone(IST).date().isoformat()
        except Exception:
            return None

    today = datetime.now(IST).date().isoformat()
    out: List[Dict[str, Any]] = []
    try:
        rows = _ledger_rows()
    except Exception:
        return []
    for r in rows:
        qty = int(r.get("quantity") or 0)
        base = {
            "trade_id": r.get("trade_id"),
            "id": r.get("trade_id"),               # legacy consumers
            "symbol": r.get("symbol"),
            "quantity": qty,
            "strategy": r.get("strategy_name") or r.get("strategy_id"),
            "strategy_id": r.get("strategy_id"),
            "strategy_name": r.get("strategy_name") or r.get("strategy_id"),
            "confidence": r.get("confidence"),
            "scan_id": r.get("scan_id"),
            "status": r.get("status"),
            "stop_loss": r.get("stop_loss"),
            "target": r.get("target"),
            "sector": r.get("sector"),
            "source": "phase20_ledger",
        }
        fp = r.get("fill_price")
        if r.get("fill_ts") and isinstance(fp, (int, float)):
            out.append({**base, "action": "BUY", "price": float(fp),
                        "total": round(float(fp) * qty, 2),
                        "timestamp": r.get("fill_ts"),
                        "reason": r.get("trigger_source") or "entry"})
        ep = r.get("exit_price")
        if r.get("status") == "CLOSED" and r.get("exit_ts") and isinstance(ep, (int, float)):
            out.append({**base, "action": "SELL", "price": float(ep),
                        "total": round(float(ep) * qty, 2),
                        "timestamp": r.get("exit_ts"),
                        "reason": r.get("exit_rule") or "exit",
                        "exit_type": r.get("exit_rule") or "SIGNAL_EXIT",
                        "pnl": r.get("realized_pnl"),   # legacy consumers
                        "realized_pnl": r.get("realized_pnl")})
    out.sort(key=lambda t: str(t.get("timestamp") or ""), reverse=True)
    if scope != "all":
        out = [t for t in out if _ist_date(t.get("timestamp")) == today]
    return out
