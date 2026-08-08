"""
phase20_exits.py — Phase 20 paper position management (exits).

On each successful scheduled scan (and on demand), every open Phase 20 paper
position is evaluated against the exit rules:

  STOP_LOSS_HIT, TARGET_HIT, RECOMMENDATION_EXIT, TRAILING_STOP,
  TIME_EXIT (max holding period), MARKET_CLOSE_EXIT (square-off setting),
  PORTFOLIO_RISK_REDUCTION (daily loss limit breached),
  SECTOR_CAP_BREACH, STALE_DATA_SAFETY

Safety rules:
- Stale data NEVER fabricates an exit fill. If a reliable quote is not
  available, the exit is marked EXIT_PENDING (PENDING_DATA) and the user is
  notified — no simulated fill happens until fresh data returns.
- The rule that triggered every exit is recorded on the trade row.

PAPER TRADING / RESEARCH ONLY. No live orders anywhere.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import phase20_store as store
from phase20_executor import get_open_trades, record_exit


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_ts(ts: Optional[str]) -> Optional[datetime]:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except Exception:
        return None


def _sector_of(symbol: str) -> str:
    try:
        from market_scanner import _sector_of as sec
        return sec(symbol) or "Other"
    except Exception:
        return "Other"


def manage_open_positions(settings: Dict[str, Any]) -> Dict[str, Any]:
    """Evaluate all open Phase 20 paper positions for exits."""
    open_trades = get_open_trades()
    if not open_trades:
        return {"evaluated": 0, "exits": [], "pending": []}

    from phase15_scan_context import build_scan_context
    ctx = build_scan_context()
    scan_ok = bool(ctx.get("available"))
    stale = bool(ctx.get("stale", True))
    symbols_ctx: Dict[str, Any] = ctx.get("symbols") or {}
    exit_scan_id = ctx.get("scan_id")

    from market_hours import market_status
    mstat = market_status()
    mstate = str(mstat.get("state") or mstat.get("market_state") or "").upper()

    from paper_trader import _load_state, get_portfolio, execute_sell
    portfolio = get_portfolio()
    total_value = float(portfolio["total_value"]) or 1.0
    state = _load_state()

    today = _now().date().isoformat()
    daily_pnl = sum(float(t.get("pnl") or 0) for t in state.get("trades", [])
                    if t.get("action") == "SELL"
                    and str(t.get("timestamp", "")).startswith(today))
    daily_loss_limit = total_value * float(settings["daily_loss_limit_pct"]) / 100.0
    loss_limit_breached = daily_pnl <= -daily_loss_limit

    exits: List[Dict[str, Any]] = []
    pending: List[Dict[str, Any]] = []

    for trade in open_trades:
        sym = str(trade.get("symbol") or "").upper()
        trade_id = str(trade.get("trade_id"))
        qty = int(trade.get("quantity") or 0)
        stop = float(trade.get("stop_loss") or 0)
        target = float(trade.get("target") or 0)
        rec = symbols_ctx.get(sym) or {}

        quote = float(rec.get("entry_price") or 0)  # latest scanned price
        dq = str(rec.get("data_quality") or "").upper()
        quote_reliable = (scan_ok and not stale and quote > 0
                          and dq in ("LIVE", "NEAR_LIVE") and not rec.get("error"))

        # Decide which rule (if any) wants an exit.
        rule: Optional[str] = None
        action = str(rec.get("final_action") or "").upper()

        if quote_reliable:
            if stop > 0 and quote <= stop:
                rule = "STOP_LOSS_HIT"
            elif target > 0 and quote >= target:
                rule = "TARGET_HIT"
            elif action in ("EXIT", "AVOID", "SELL"):
                rule = "RECOMMENDATION_EXIT"

        if rule is None:
            # Trailing stop: once the peak (high-water mark) has reached 2R
            # above fill, exit if the price falls back to <= fill + 1R,
            # locking in roughly 1R of profit. The peak is persisted per
            # trade so the rule survives restarts and stale gaps.
            if quote_reliable and stop > 0:
                fill = float(trade.get("fill_price") or 0)
                one_r = fill - stop
                if one_r > 0:
                    peak_key = f"trail_peak:{trade.get('trade_id')}"
                    try:
                        peak = float(store.kv_get(peak_key, 0) or 0)
                    except Exception:
                        peak = 0.0
                    if quote > peak:
                        peak = quote
                        try:
                            store.kv_set(peak_key, peak)
                        except Exception:
                            pass
                    if peak >= fill + 2 * one_r and quote <= fill + one_r:
                        rule = "TRAILING_STOP"

        if rule is None:
            entry_dt = _parse_ts(trade.get("fill_ts"))
            max_days = float(settings.get("max_holding_days", 10))
            if entry_dt and (_now() - entry_dt).days >= max_days:
                rule = "TIME_EXIT"

        if rule is None and settings.get("square_off_before_close"):
            # Square off in the last 15 minutes of the session.
            if mstate == "OPEN":
                try:
                    from market_hours import now_ist, MARKET_CLOSE
                    ist = now_ist()
                    close_dt = ist.replace(hour=MARKET_CLOSE.hour,
                                           minute=MARKET_CLOSE.minute,
                                           second=0, microsecond=0)
                    if (close_dt - ist).total_seconds() <= 15 * 60:
                        rule = "MARKET_CLOSE_EXIT"
                except Exception:
                    pass

        if rule is None and loss_limit_breached:
            rule = "PORTFOLIO_RISK_REDUCTION"

        if rule is None:
            sector = trade.get("sector") or _sector_of(sym)
            sector_value = sum(float(p["quantity"]) * float(p["current_price"])
                               for p in portfolio["positions"]
                               if _sector_of(str(p["symbol"])) == sector)
            sector_pct = sector_value / total_value * 100.0
            if sector_pct > float(settings["sector_exposure_cap_pct"]) * 1.25:
                rule = "SECTOR_CAP_BREACH"

        if rule is None:
            # Data unavailable for a prolonged period → safety exit advice.
            if scan_ok and not rec:
                rule = "STALE_DATA_SAFETY"

        if rule is None:
            continue  # position stays open

        if not quote_reliable:
            # NEVER fabricate a fill from stale/unavailable data.
            record_exit(trade_id, 0.0, rule, exit_scan_id, status="EXIT_PENDING")
            pend = {"trade_id": trade_id, "symbol": sym, "rule": rule,
                    "reason": "No reliable quote — exit is PENDING_DATA, "
                              "no simulated fill created"}
            pending.append(pend)
            store.add_notification(
                "EXIT_PENDING_DATA", f"{sym} exit pending data",
                f"Exit rule {rule} triggered for trade {trade_id} but no "
                f"reliable quote is available. No fill was fabricated.",
                severity="WARN",
                context={"trade_id": trade_id, "symbol": sym, "rule": rule})
            continue

        ok, msg = execute_sell(
            sym, qty, quote,
            ledger_trade_id=trade_id,
            reason=f"Phase 20 exit {rule} (trade {trade_id})",
            exit_type=("STOP_HIT" if rule == "STOP_LOSS_HIT"
                       else "TARGET_HIT" if rule == "TARGET_HIT"
                       else "SIGNAL_EXIT"),
        )
        if not ok:
            pending.append({"trade_id": trade_id, "symbol": sym,
                            "rule": rule, "reason": msg})
            continue
        record_exit(trade_id, quote, rule, exit_scan_id, status="CLOSED")
        exits.append({"trade_id": trade_id, "symbol": sym, "rule": rule,
                      "exit_price": quote})
        store.add_notification(
            "EXIT_COMPLETED", f"Paper exit {sym} @ ₹{quote} ({rule})",
            f"Trade {trade_id} closed by {rule} on scan {exit_scan_id}.",
            severity="INFO",
            context={"trade_id": trade_id, "symbol": sym, "rule": rule,
                     "scan_id": exit_scan_id})

    # Retry previously pending exits when data has recovered.
    retried = _retry_pending(symbols_ctx, scan_ok, stale, exit_scan_id)

    return {"evaluated": len(open_trades), "exits": exits + retried,
            "pending": pending}


def _retry_pending(symbols_ctx: Dict[str, Any], scan_ok: bool, stale: bool,
                   exit_scan_id: Optional[str]) -> List[Dict[str, Any]]:
    """Complete EXIT_PENDING trades once a reliable quote is available."""
    from phase20_executor import get_ledger
    from paper_trader import execute_sell
    out: List[Dict[str, Any]] = []
    if not scan_ok or stale:
        return out
    for trade in get_ledger(500):
        if trade.get("status") != "EXIT_PENDING":
            continue
        sym = str(trade.get("symbol") or "").upper()
        rec = symbols_ctx.get(sym) or {}
        quote = float(rec.get("entry_price") or 0)
        dq = str(rec.get("data_quality") or "").upper()
        if not (quote > 0 and dq in ("LIVE", "NEAR_LIVE") and not rec.get("error")):
            continue
        qty = int(trade.get("quantity") or 0)
        rule = str(trade.get("exit_rule") or "PENDING_DATA_RESOLVED")
        ok, _msg = execute_sell(sym, qty, quote,
                                reason=f"Phase 20 pending exit resolved ({rule})",
                                exit_type="SIGNAL_EXIT",
                                ledger_trade_id=str(trade.get("trade_id") or ""))
        if not ok:
            continue
        record_exit(str(trade.get("trade_id")), quote, rule, exit_scan_id,
                    status="CLOSED")
        out.append({"trade_id": trade.get("trade_id"), "symbol": sym,
                    "rule": rule, "exit_price": quote, "resolved_pending": True})
        store.add_notification(
            "EXIT_COMPLETED", f"Pending exit resolved: {sym} @ ₹{quote}",
            f"Trade {trade.get('trade_id')} closed after data recovered.",
            severity="INFO",
            context={"trade_id": trade.get("trade_id"), "symbol": sym})
    return out
