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
    """Evaluate all open Phase 20 paper positions for exits.

    Always runs the EXIT_PENDING timeout cleanup even when there are no OPEN
    trades — EXIT_PENDING positions live in the ledger, not in open_trades,
    so they would be silently skipped by an early-return guard.
    """
    open_trades = get_open_trades()

    from phase15_scan_context import build_scan_context
    ctx = build_scan_context()
    scan_ok = bool(ctx.get("available"))
    stale = bool(ctx.get("stale", True))
    symbols_ctx: Dict[str, Any] = ctx.get("symbols") or {}
    exit_scan_id = ctx.get("scan_id")

    # Force-close EXIT_PENDING positions that have exceeded max_holding_days.
    # Runs unconditionally because EXIT_PENDING rows are not in open_trades.
    timeout_closed = _resolve_timeout_exit_pending(settings, symbols_ctx, exit_scan_id)

    if not open_trades:
        return {"evaluated": 0, "exits": [] + timeout_closed,
                "pending": [], "timeout_closed": timeout_closed}

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

        quote = float(rec.get("entry_price") or 0)  # yfinance daily close (baseline)
        dq = str(rec.get("data_quality") or "").upper()
        quote_reliable = (scan_ok and not stale and quote > 0
                          and dq in ("LIVE", "NEAR_LIVE") and not rec.get("error"))

        # ── Task 4: Kite LTP overlay — use live LTP for exit price ───────────
        # When the scan engine ran with KITE_LTP_OVERLAY_ENABLED=true and
        # Kite LTP is available in the snapshot, use it as the exit quote.
        # quote_reliable becomes True since LTP is a live verified price.
        _kite_ltp_for_exit = float(rec.get("kite_ltp") or 0)
        if (rec.get("kite_ltp_available")
                and _kite_ltp_for_exit > 0
                and rec.get("quote_reliable")):
            quote = _kite_ltp_for_exit
            quote_reliable = True

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

        if rule is None:
            # Mandatory intraday square-off: close all OPEN paper positions at
            # or after 15:20 IST (10 minutes before NSE close).  This rule is
            # unconditional — it does NOT require square_off_before_close=True
            # in settings.  Paper positions must never carry overnight unless
            # the operator has explicitly disabled auto_paper_exits.
            if mstate == "OPEN":
                try:
                    from market_hours import now_ist, MARKET_CLOSE
                    ist = now_ist()
                    close_dt = ist.replace(hour=MARKET_CLOSE.hour,
                                           minute=MARKET_CLOSE.minute,
                                           second=0, microsecond=0)
                    if (close_dt - ist).total_seconds() <= 10 * 60:
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
            # ── Task 791: prefer immediate yfinance close over EXIT_PENDING ──
            # When exit_on_stale_after_days > 0, a trade that has been held
            # long enough (>= N days from fill_ts) may be closed immediately
            # using the yfinance daily close — even on a stale scan — rather
            # than accumulating EXIT_PENDING entries that won't resolve until
            # Kite LTP comes back online.
            _stale_exit_days = int(settings.get("exit_on_stale_after_days", 5))
            if _stale_exit_days > 0:
                _entry_dt = _parse_ts(trade.get("fill_ts"))
                _held_days = (_now() - _entry_dt).days if _entry_dt else 0
                _yf_quote = float(rec.get("entry_price") or 0)
                if (_held_days >= _stale_exit_days
                        and _yf_quote > 0
                        and not rec.get("error")):
                    # Use yfinance daily close for an immediate CLOSED exit.
                    _ok, _msg = execute_sell(
                        sym, qty, _yf_quote,
                        ledger_trade_id=trade_id,
                        reason=(
                            f"Phase 20 exit {rule} "
                            f"(stale scan, yfinance daily close, "
                            f"held {_held_days}d >= exit_on_stale_after_days="
                            f"{_stale_exit_days}d, trade {trade_id})"
                        ),
                        exit_type=("STOP_HIT" if rule == "STOP_LOSS_HIT"
                                   else "TARGET_HIT" if rule == "TARGET_HIT"
                                   else "SIGNAL_EXIT"),
                    )
                    if _ok:
                        record_exit(trade_id, _yf_quote, rule, exit_scan_id,
                                    status="CLOSED")
                        exits.append({
                            "trade_id": trade_id, "symbol": sym, "rule": rule,
                            "exit_price": _yf_quote,
                            "price_source": "yfinance_daily_close_stale",
                        })
                        store.add_notification(
                            "EXIT_COMPLETED",
                            f"Paper exit {sym} @ ₹{_yf_quote} ({rule}, "
                            f"yfinance close on stale scan)",
                            f"Trade {trade_id} closed by {rule} using yfinance "
                            f"daily close on a stale scan (held {_held_days}d >= "
                            f"exit_on_stale_after_days={_stale_exit_days}d). "
                            f"Kite LTP was offline. Scan: {exit_scan_id}.",
                            severity="INFO",
                            context={
                                "trade_id": trade_id, "symbol": sym,
                                "rule": rule, "scan_id": exit_scan_id,
                                "price_source": "yfinance_daily_close_stale",
                                "held_days": _held_days,
                            })
                        continue
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
            # Emit a mandatory terminal event so the SELL failure is
            # visible in the pipeline and never disappears silently.
            # The most common cause is portfolio-state divergence: the
            # Phase 20 ledger shows the trade as OPEN, but the paper
            # portfolio no longer holds the position (e.g. after a
            # manual reset or a failed prior SELL).
            try:
                from pipeline_events import emit as _pe
                _pe("EXECUTION_SKIPPED_WITH_REASON", "EXECUTION",
                    scan_id=exit_scan_id, symbol=sym,
                    payload={
                        "reason": msg,
                        "note": (
                            "SELL skipped — no open paper position; "
                            "portfolio state diverged from Phase 20 ledger"
                        ),
                        "exit_rule": rule,
                        "position_count": len(portfolio.get("positions", [])),
                        "source": "paper_mode_sell_validation",
                        "trade_id": trade_id,
                    })
            except Exception:
                pass
            store.add_notification(
                "SELL_SKIPPED_NO_POSITION",
                f"SELL skipped — no open paper position for {sym}",
                f"execute_sell returned: {msg}. Exit rule: {rule}. "
                f"The Phase 20 ledger trade {trade_id} is still OPEN but "
                f"the paper portfolio no longer holds {sym}.",
                severity="WARN",
                context={"symbol": sym, "trade_id": trade_id,
                         "rule": rule, "scan_id": exit_scan_id},
            )
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

    return {"evaluated": len(open_trades), "exits": exits + retried + timeout_closed,
            "pending": pending, "timeout_closed": timeout_closed}


# ── EOD post-close force-exit ──────────────────────────────────────────────────

def eod_force_close_open_positions(settings: Dict[str, Any]) -> Dict[str, Any]:
    """Force-close any OPEN paper positions after market has closed.

    Called from the scheduler's CLOSED / POST_CLOSE state handler.  This is
    the safety net for positions that survived the 15:20 IST intraday square-off
    window (e.g. because the final pre-close tick was missed or the server
    restarted at an inconvenient moment).

    Exit rule: POST_CLOSE_FORCE_EXIT.

    Price resolution (in order):
      1. Kite LTP from the most-recent scan snapshot (live verified price).
      2. yfinance daily close from the scan snapshot (LIVE / NEAR_LIVE quality).
      3. Fill price (entry price) — recorded honestly so the position is closed;
         an INFO notification marks the fallback.

    When no price is available at all the position is left open and a
    MARKET_CLOSE_EXIT_BLOCKED pipeline event is emitted so the dashboard can
    surface a visible warning.  The position is NOT silently carried overnight
    without this explicit signal.

    Returns a dict with keys: evaluated, force_closed, blocked.
    Never raises — errors are swallowed per-trade.

    Respects the ``auto_paper_exits`` operator setting: when the setting is
    False this function returns immediately without touching any positions.
    This keeps EOD force-close consistent with the normal exit gate so that
    disabling automatic exits prevents *all* automated sells, including the
    post-close safety net.

    Price provenance is recorded in the ``PAPER_TRADE_FORCE_CLOSED`` pipeline
    event payload (exit_price_source, quote_reliable, fallback_used).  The
    ``record_exit()`` ledger row stores only the canonical fields it already
    supports (exit_price, exit_rule, exit_scan_id, realized_pnl).
    """
    if not settings.get("auto_paper_exits", True):
        store.add_notification(
            "EOD_SQUAREOFF_SKIPPED",
            "EOD force-close suppressed — auto_paper_exits is OFF",
            "Operator has disabled automatic paper exits. "
            "POST_CLOSE_FORCE_EXIT will not run. "
            "Open positions may carry overnight; review manually.",
            severity="INFO",
        )
        return {"evaluated": 0, "force_closed": [], "blocked": [],
                "skipped_reason": "auto_paper_exits_disabled"}

    from paper_trader import execute_sell
    from phase20_executor import get_open_trades, record_exit

    open_trades = get_open_trades()
    if not open_trades:
        return {"evaluated": 0, "force_closed": [], "blocked": []}

    from phase15_scan_context import build_scan_context
    ctx = build_scan_context()
    scan_ok = bool(ctx.get("available"))
    ctx_stale = bool(ctx.get("stale", True))
    ctx_today = bool(ctx.get("is_today_session", False))
    symbols_ctx: Dict[str, Any] = ctx.get("symbols") or {}
    exit_scan_id: Optional[str] = ctx.get("scan_id")

    # yfinance prices are only accepted when the scan is fresh *and* from
    # today's IST session.  A stale or prior-session snapshot would close
    # a position at yesterday's close, which is misleading and harmful.
    yf_data_usable: bool = scan_ok and not ctx_stale and ctx_today

    force_closed: List[Dict[str, Any]] = []
    blocked: List[Dict[str, Any]] = []

    for trade in open_trades:
        sym = str(trade.get("symbol") or "").upper()
        trade_id = str(trade.get("trade_id"))
        qty = int(trade.get("quantity") or 0)
        fill_price = float(trade.get("fill_price") or 0)
        rec = symbols_ctx.get(sym) or {}

        # ── Price resolution ─────────────────────────────────────────────────
        # Canonical scan context (build_scan_context) exposes data_quality and
        # entry_price per symbol, but not Kite LTP (which is overlaid by
        # kite_ltp_overlay.py only when KITE_LTP_OVERLAY_ENABLED is set and is
        # not part of the base context contract).  Resolution order:
        #
        #   1. yfinance daily close — only when scan is fresh AND from today's
        #      IST session AND data_quality is LIVE or NEAR_LIVE.
        #   2. Fill price (entry price) — always available; marks the exit as
        #      a fallback with INFO-level notification so operators can audit.
        #
        # If neither source is available (fill price also 0) the position is
        # left OPEN and a MARKET_CLOSE_EXIT_BLOCKED event is emitted.

        quote: float = 0.0
        exit_price_source: str = "unavailable"
        quote_reliable: bool = False
        fallback_used: bool = False

        # 1. yfinance daily close (fresh, today's session, LIVE / NEAR_LIVE)
        yf_price = float(rec.get("entry_price") or 0)
        dq = str(rec.get("data_quality") or "").upper()
        if yf_data_usable and yf_price > 0 and dq in ("LIVE", "NEAR_LIVE") and not rec.get("error"):
            quote = yf_price
            exit_price_source = "yfinance_daily_close"
            quote_reliable = True

        # 2. Fill price fallback — honest but marked
        if not quote_reliable and fill_price > 0:
            quote = fill_price
            exit_price_source = "fill_price_fallback"
            quote_reliable = False
            fallback_used = True

        # No price at all — emit blocked event and skip
        if quote <= 0:
            blocked.append({"trade_id": trade_id, "symbol": sym,
                            "reason": "no_price_available"})
            try:
                from pipeline_events import emit as _pe
                _pe("MARKET_CLOSE_EXIT_BLOCKED", "PORTFOLIO",
                    scan_id=exit_scan_id, symbol=sym,
                    payload={
                        "trade_id": trade_id,
                        "reason": "No price available for POST_CLOSE_FORCE_EXIT",
                        "exit_price_source": "unavailable",
                        "quote_reliable": False,
                    })
            except Exception:
                pass
            store.add_notification(
                "MARKET_CLOSE_EXIT_BLOCKED",
                f"{sym} overnight carry — no price for EOD close",
                f"Trade {trade_id} could not be closed at market end: "
                f"no Kite LTP, yfinance, or fill-price fallback available. "
                f"Position is carrying overnight. Manual review required.",
                severity="WARN",
                context={"trade_id": trade_id, "symbol": sym,
                         "scan_id": exit_scan_id})
            continue

        # ── Execute paper sell ───────────────────────────────────────────────
        try:
            ok, msg = execute_sell(
                sym, qty, quote,
                ledger_trade_id=trade_id,
                reason=(
                    f"POST_CLOSE_FORCE_EXIT (trade {trade_id}, "
                    f"source={exit_price_source}, "
                    f"fallback={fallback_used})"
                ),
                exit_type="SIGNAL_EXIT",
            )
        except Exception as exc:
            ok, msg = False, str(exc)[:200]

        if not ok:
            # execute_sell failed — leave the ledger row OPEN so a retry is
            # possible and the ledger remains consistent with the paper
            # portfolio.  Recording CLOSED here would create a desync where
            # the portfolio still holds the position but the ledger shows it
            # closed, silently corrupting cash/equity/P&L accounting.
            # Emit MARKET_CLOSE_EXIT_BLOCKED so the operator can see the
            # failure and take manual action on the next tick.
            blocked.append({"trade_id": trade_id, "symbol": sym,
                            "reason": f"execute_sell failed: {msg}"})
            try:
                from pipeline_events import emit as _pe
                _pe("MARKET_CLOSE_EXIT_BLOCKED", "PORTFOLIO",
                    scan_id=exit_scan_id, symbol=sym,
                    payload={
                        "trade_id": trade_id,
                        "reason": f"POST_CLOSE_FORCE_EXIT: execute_sell rejected — {msg}",
                        "exit_price_source": exit_price_source,
                        "quote_reliable": quote_reliable,
                        "sell_ok": False,
                        "sell_msg": msg,
                    })
            except Exception:
                pass
            store.add_notification(
                "MARKET_CLOSE_EXIT_BLOCKED",
                f"{sym} EOD force-close failed — sell rejected",
                f"Trade {trade_id} could not be closed at market end: "
                f"execute_sell returned failure ({msg}). "
                f"Position is carrying overnight. Manual review required.",
                severity="WARN",
                context={"trade_id": trade_id, "symbol": sym,
                         "scan_id": exit_scan_id, "sell_msg": msg})
            continue

        rule = "POST_CLOSE_FORCE_EXIT"
        record_exit(trade_id, quote, rule, exit_scan_id, status="CLOSED")

        # Emit a rich pipeline event with provenance metadata
        try:
            from pipeline_events import emit as _pe
            pnl = round((quote - fill_price) * qty, 2)
            _pe("PAPER_TRADE_FORCE_CLOSED", "PORTFOLIO",
                scan_id=exit_scan_id, symbol=sym,
                payload={
                    "trade_id": trade_id,
                    "exit_price": quote,
                    "exit_rule": rule,
                    "realized_pnl": pnl,
                    "exit_price_source": exit_price_source,
                    "quote_reliable": quote_reliable,
                    "fallback_used": fallback_used,
                    "sell_ok": ok,
                    "sell_msg": msg if not ok else None,
                })
        except Exception:
            pass

        severity = "INFO" if quote_reliable else "WARN"
        store.add_notification(
            "EXIT_COMPLETED",
            f"EOD force-close {sym} @ ₹{quote} (POST_CLOSE_FORCE_EXIT)",
            f"Trade {trade_id} force-closed after market close. "
            f"Price source: {exit_price_source}. "
            f"Fallback used: {fallback_used}. Reliable: {quote_reliable}.",
            severity=severity,
            context={
                "trade_id": trade_id, "symbol": sym, "rule": rule,
                "exit_price": quote, "exit_price_source": exit_price_source,
                "quote_reliable": quote_reliable, "fallback_used": fallback_used,
                "scan_id": exit_scan_id,
            })

        force_closed.append({
            "trade_id": trade_id, "symbol": sym,
            "exit_price": quote, "exit_price_source": exit_price_source,
            "quote_reliable": quote_reliable, "fallback_used": fallback_used,
        })

    return {
        "evaluated": len(open_trades),
        "force_closed": force_closed,
        "blocked": blocked,
    }


def _resolve_timeout_exit_pending(
    settings: Dict[str, Any],
    symbols_ctx: Dict[str, Any],
    exit_scan_id: Optional[str],
) -> List[Dict[str, Any]]:
    """Force-close EXIT_PENDING positions that have exceeded max_holding_days.

    When Kite LTP is offline for an extended period the normal pending-retry
    path never fires (it waits for a reliable quote).  A position that has
    been in EXIT_PENDING long enough that even the original TIME_EXIT
    threshold would have triggered is force-closed using whichever price
    source is available:

        1. Live yfinance daily close from the current scan snapshot.
        2. Fill price (entry price) — never fabricates a loss, but records an
           honest TIMEOUT exit so the position is no longer stuck.

    Calls execute_sell so the paper portfolio is also reconciled; if the
    portfolio no longer holds the position (desync) the ledger entry is still
    closed so the UI reflects reality.

    This function is advisory-safe: errors are swallowed per-trade so one
    bad row never blocks the rest.
    """
    from phase20_executor import get_exit_pending_trades, record_exit
    from paper_trader import execute_sell
    out: List[Dict[str, Any]] = []
    max_days = float(settings.get("max_holding_days", 10))

    # Use get_exit_pending_trades() — no row-count limit, EXIT_PENDING only.
    # get_ledger(500) would miss trades older than the 500-row window.
    for trade in get_exit_pending_trades():
        if trade.get("status") != "EXIT_PENDING":
            continue
        try:
            sym = str(trade.get("symbol") or "").upper()
            trade_id = str(trade.get("trade_id") or "")
            qty = int(trade.get("quantity") or 0)
            fill_price = float(trade.get("fill_price") or 0)

            # Measure time spent in EXIT_PENDING state using exit_ts (the
            # timestamp recorded when the trade transitioned to EXIT_PENDING).
            # Fallback chain: exit_ts → fill_ts → created_at.
            # created_at is always present (DB DEFAULT NOW()) so this chain
            # guarantees that no EXIT_PENDING trade can be permanently stranded
            # even when exit_ts and fill_ts are both NULL (legacy rows).
            pending_dt = _parse_ts(trade.get("exit_ts"))
            _ts_source = "exit_ts"
            if pending_dt is None:
                pending_dt = _parse_ts(trade.get("fill_ts"))
                _ts_source = "fill_ts_legacy_fallback"
            if pending_dt is None:
                pending_dt = _parse_ts(trade.get("created_at"))
                _ts_source = "created_at_legacy_fallback"
            if not (pending_dt and (_now() - pending_dt).days >= max_days):
                continue

            # Price source: prefer live scan quote, fall back to fill price.
            rec = symbols_ctx.get(sym) or {}
            quote = float(rec.get("entry_price") or 0)
            _price_source = "yfinance_daily_close"
            # Kite LTP overlay when available
            _kite_ltp = float(rec.get("kite_ltp") or 0)
            if (rec.get("kite_ltp_available") and _kite_ltp > 0
                    and rec.get("quote_reliable")):
                quote = _kite_ltp
                _price_source = "kite_ltp"
            if not (quote > 0 and not rec.get("error")):
                # No scan data at all — use fill price to un-stuck the position.
                quote = fill_price
                _price_source = "fill_price_fallback"

            # Try to reconcile the paper portfolio; if it's already desync'd,
            # still close the ledger so the dashboard is accurate.
            ok, _msg = execute_sell(
                sym, qty, quote,
                ledger_trade_id=trade_id,
                reason=(f"Phase 20 TIMEOUT_EXIT_PENDING "
                        f"(pending >{max_days:.0f}d via {_ts_source}, "
                        f"Kite LTP offline)"),
                exit_type="SIGNAL_EXIT",
            )
            if not ok:
                # Portfolio desync — close ledger only. The sell was never
                # pending in paper_trader so this is safe to do directly.
                try:
                    from pipeline_events import emit as _pe
                    _pe("EXECUTION_SKIPPED_WITH_REASON", "EXECUTION",
                        scan_id=exit_scan_id, symbol=sym,
                        payload={
                            "reason": _msg,
                            "note": "TIMEOUT_EXIT_PENDING sell skipped — portfolio position gone; closing ledger",
                            "exit_rule": "TIMEOUT_EXIT_PENDING",
                            "trade_id": trade_id,
                        })
                except Exception:
                    pass

            record_exit(trade_id, quote, "TIMEOUT_EXIT_PENDING", exit_scan_id,
                        status="CLOSED")
            days_stuck = (_now() - pending_dt).days
            store.add_notification(
                "EXIT_COMPLETED",
                f"Force-closed {sym} after {days_stuck}d in EXIT_PENDING "
                f"(Kite LTP offline — {_price_source})",
                f"Trade {trade_id} has been stuck in EXIT_PENDING for {days_stuck} days "
                f"(since {pending_dt.date().isoformat()}, measured via {_ts_source}). "
                f"Force-closed at ₹{quote:.2f} using {_price_source}. "
                f"Exit rule: TIMEOUT_EXIT_PENDING.",
                severity="WARN",
                context={
                    "trade_id": trade_id, "symbol": sym,
                    "days_stuck": days_stuck, "exit_price": quote,
                    "price_source": _price_source,
                    "ts_source": _ts_source,
                    "scan_id": exit_scan_id,
                },
            )
            out.append({
                "trade_id": trade_id, "symbol": sym,
                "exit_price": quote, "price_source": _price_source,
                "days_stuck": days_stuck,
                "exit_rule": "TIMEOUT_EXIT_PENDING",
            })
        except Exception:
            pass  # never let one bad trade block the rest
    return out


def _retry_pending(symbols_ctx: Dict[str, Any], scan_ok: bool, stale: bool,
                   exit_scan_id: Optional[str]) -> List[Dict[str, Any]]:
    """Complete EXIT_PENDING trades once a reliable quote is available.

    Two resolution tiers:
      1. LIVE / NEAR_LIVE (or Kite LTP) — preferred; standard resolution.
      2. yfinance daily close fallback — accepted when Kite LTP has been
         offline for days and the only quote is a fresh daily-bar close.
         The exit price is still a real market price, just not intraday.
    """
    from phase20_executor import get_exit_pending_trades
    from paper_trader import execute_sell
    out: List[Dict[str, Any]] = []
    if not scan_ok or stale:
        return out
    # Use get_exit_pending_trades() — no 500-row limit, fetches all EXIT_PENDING.
    for trade in get_exit_pending_trades():
        if trade.get("status") != "EXIT_PENDING":
            continue
        sym = str(trade.get("symbol") or "").upper()
        rec = symbols_ctx.get(sym) or {}
        quote = float(rec.get("entry_price") or 0)  # yfinance daily close (baseline)
        dq = str(rec.get("data_quality") or "").upper()
        _price_source = "yfinance_daily_close"
        # Task 4: Kite LTP overlay — use live LTP for pending exit resolution
        _kite_ltp_retry = float(rec.get("kite_ltp") or 0)
        if (rec.get("kite_ltp_available")
                and _kite_ltp_retry > 0
                and rec.get("quote_reliable")):
            quote = _kite_ltp_retry
            dq = "LIVE"   # treat as LIVE for the eligibility check below
            _price_source = "kite_ltp"

        # How long has this trade been in EXIT_PENDING?  Use exit_ts (the
        # transition timestamp), falling back to fill_ts then created_at for
        # legacy rows where both may be NULL.  Without this chain a trade
        # with NULL exit_ts + fill_ts gets _ep_pending_hours=0 and tier-2
        # never fires, leaving the position permanently stuck.
        _ep_ts_str = (trade.get("exit_ts")
                      or trade.get("fill_ts")
                      or trade.get("created_at"))
        _ep_pending_hours = 0.0
        if _ep_ts_str:
            try:
                from datetime import datetime as _epdt
                _ep_dt_obj = _epdt.fromisoformat(
                    str(_ep_ts_str).replace("Z", "+00:00"))
                _ep_pending_hours = (_now() - _ep_dt_obj).total_seconds() / 3600.0
            except Exception:
                pass

        # Tier 1: live / near-live data quality (or Kite LTP) — no age gate.
        # Tier 2: yfinance daily close fallback — only accepted when the trade
        #   has been stuck in EXIT_PENDING for at least 24 hours.  This gate
        #   ensures newly-pending trades still wait for a reliable quote and do
        #   not get immediately resolved on low-quality data, while positions
        #   stuck for days (Kite LTP offline) are eventually unblocked.
        _MIN_PENDING_HOURS_FOR_FALLBACK = 24.0
        tier1_ok = (dq in ("LIVE", "NEAR_LIVE") and quote > 0
                    and not rec.get("error"))
        tier2_ok = (dq not in ("", "UNAVAILABLE", "ERROR")
                    and quote > 0 and not rec.get("error")
                    and _ep_pending_hours >= _MIN_PENDING_HOURS_FOR_FALLBACK)
        if not (tier1_ok or tier2_ok):
            continue
        qty = int(trade.get("quantity") or 0)
        rule = str(trade.get("exit_rule") or "PENDING_DATA_RESOLVED")
        ok, _msg = execute_sell(sym, qty, quote,
                                reason=f"Phase 20 pending exit resolved ({rule})",
                                exit_type="SIGNAL_EXIT",
                                ledger_trade_id=str(trade.get("trade_id") or ""))
        if not ok:
            # Pending retry also failed — emit terminal event so the gap
            # is visible in the pipeline rather than silently dropped.
            try:
                from pipeline_events import emit as _pe
                _pe("EXECUTION_SKIPPED_WITH_REASON", "EXECUTION",
                    scan_id=exit_scan_id, symbol=sym,
                    payload={
                        "reason": _msg,
                        "note": (
                            "SELL skipped — no open paper position; "
                            "pending exit retry could not be resolved"
                        ),
                        "exit_rule": rule,
                        "source": "paper_mode_sell_validation",
                        "trade_id": str(trade.get("trade_id") or ""),
                    })
            except Exception:
                pass
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
