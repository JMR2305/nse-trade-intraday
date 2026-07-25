"""portfolio_snapshot.py — Live portfolio snapshot and health for the dashboard.

Builds a normalised snapshot from the paper trader state + live market prices,
and exposes a health summary.  This is a READ-ONLY module; it never modifies
portfolio state.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

_INITIAL_CAPITAL = 5_000.0  # default; overridden if paper_trader exposes it

# Default exposure limits (fractions of equity, matching PortfolioConfig defaults).
# Overridden at runtime if PortfolioConfig is importable.
_DEFAULT_INSTRUMENT_LIMIT_PCT = 20.0   # 20 % per single stock
_DEFAULT_SECTOR_LIMIT_PCT = 35.0       # 35 % per sector
_WARNING_RATIO = 0.80                  # ≥ 80 % of limit → WARNING


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_float(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def get_portfolio_snapshot() -> Dict[str, Any]:
    """Return a normalised portfolio snapshot suitable for the dashboard."""
    # ── 1. Try Phase-20 durable open positions first ──────────────────────
    # get_open_positions_view() returns rows with keys:
    #   fill_price, current_price, unrealized_pnl (American spelling), quantity,
    #   symbol, sector, strategy_id, side, fill_ts, stop_loss, target, …
    open_positions: List[Dict[str, Any]] = []
    try:
        from phase20_executor import get_open_positions_view
        raw_positions = get_open_positions_view() or []
        for p in raw_positions:
            qty = int(p.get("quantity") or 0)
            fill_price = _safe_float(p.get("fill_price"))          # avg entry
            cur_price = _safe_float(p.get("current_price") or fill_price)
            market_val = round(cur_price * qty, 2)
            upnl = _safe_float(p.get("unrealized_pnl", 0))        # American spelling
            upnl_pct = ((upnl / (fill_price * qty)) * 100
                        if fill_price > 0 and qty > 0 else 0.0)
            open_positions.append({
                "symbol":             str(p.get("symbol") or ""),
                "quantity":           qty,
                "avg_entry_price":    fill_price,
                "last_price":         cur_price,
                "market_value":       market_val,
                "unrealised_pnl":     round(upnl, 2),
                "unrealised_pnl_pct": round(upnl_pct, 2),
                "side":               p.get("side", "LONG"),
                "strategy_id":        p.get("strategy_id"),
                "sector":             p.get("sector"),
                "opened_at":          p.get("fill_ts") or p.get("signal_ts"),
            })
    except Exception as exc:
        logger.debug("phase20 positions unavailable: %s", exc)

    # ── 2. Fall back to legacy paper_trader state ──────────────────────────
    legacy_state: Dict[str, Any] = {}
    try:
        from paper_trader import _load_state, get_portfolio, INITIAL_CAPITAL as IC
        legacy_state = _load_state() or {}
        _INITIAL_CAPITAL_local = float(IC)
    except Exception:
        _INITIAL_CAPITAL_local = _INITIAL_CAPITAL

    # If phase20 gave us nothing, build from legacy positions
    if not open_positions:
        raw_positions_legacy = legacy_state.get("positions", {})
        if raw_positions_legacy:
            try:
                from market_data import get_multiple_ltp
                symbols = list(raw_positions_legacy.keys())
                prices = get_multiple_ltp(symbols)
            except Exception:
                prices = {}
            for sym, pos in raw_positions_legacy.items():
                qty = int(pos.get("quantity", 0))
                avg = _safe_float(pos.get("avg_price"))
                ltp = _safe_float(prices.get(sym, avg))
                market_val = qty * ltp
                upnl = market_val - (qty * avg)
                upnl_pct = (upnl / (qty * avg) * 100) if avg > 0 else 0.0
                open_positions.append({
                    "symbol":             sym,
                    "quantity":           qty,
                    "avg_entry_price":    avg,
                    "last_price":         ltp,
                    "market_value":       round(market_val, 2),
                    "unrealised_pnl":     round(upnl, 2),
                    "unrealised_pnl_pct": round(upnl_pct, 2),
                    "side":               "LONG",
                    "strategy_id":        pos.get("strategy_id"),
                    "sector":             None,
                    "opened_at":          pos.get("opened_at"),
                })

    # ── 3. Derive aggregate metrics ────────────────────────────────────────
    try:
        from paper_trader import _load_state as _ls
        state = _ls() or {}
    except Exception:
        state = legacy_state

    cash = _safe_float(state.get("cash", _INITIAL_CAPITAL_local))
    total_invested = sum(p["market_value"] for p in open_positions)
    unrealised_pnl = sum(p["unrealised_pnl"] for p in open_positions)

    # Realised P&L: sum of completed trades recorded today
    realised_pnl_today = 0.0
    closed_count_today = 0
    try:
        from paper_trader import get_trades as _get_trades
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        trades = _get_trades() or []
        for t in trades:
            ts = str(t.get("timestamp", t.get("exit_time", "")) or "")
            if ts.startswith(today):
                realised_pnl_today += _safe_float(t.get("pnl", t.get("realised_pnl", 0)))
                closed_count_today += 1
    except Exception:
        pass

    # Also check phase22 evidence for daily P&L
    if realised_pnl_today == 0.0:
        try:
            from phase22_auto_paper import get_daily_pnl_today
            realised_pnl_today = _safe_float(get_daily_pnl_today())
        except Exception:
            pass

    equity = cash + total_invested
    initial_capital = _safe_float(state.get("initial_capital", _INITIAL_CAPITAL_local))
    if initial_capital <= 0:
        initial_capital = _INITIAL_CAPITAL_local

    # Peak equity: use the maximum from pnl_history if available
    pnl_history = state.get("pnl_history", [])
    if pnl_history:
        peak_equity = max(
            (_safe_float(p.get("value", p.get("equity", equity))) for p in pnl_history),
            default=equity,
        )
    else:
        peak_equity = max(initial_capital, equity)

    drawdown_amount = max(0.0, peak_equity - equity)
    drawdown_pct = (drawdown_amount / peak_equity * 100) if peak_equity > 0 else 0.0

    # Buying power = cash (paper mode — no margin)
    buying_power = cash

    # Status — derived from phase22 activation (paper_automation_active)
    status = "READY"
    try:
        from phase22_activation import get_activation_status as _get_act
        act = _get_act() or {}
        if not act.get("paper_automation_active", False):
            status = "DISABLED"
    except Exception:
        pass

    # ── 4. Exposure limits (try to load from PortfolioConfig) ─────────────
    instrument_limit_pct = _DEFAULT_INSTRUMENT_LIMIT_PCT
    sector_limit_pct = _DEFAULT_SECTOR_LIMIT_PCT
    try:
        from src.portfolio.config import PortfolioConfig
        _cfg = PortfolioConfig()
        instrument_limit_pct = float(_cfg.max_instrument_exposure_pct) * 100.0
        sector_limit_pct = float(_cfg.max_sector_exposure_pct) * 100.0
    except Exception:
        pass

    # ── 5. Per-position exposure_pct and sector rollup ─────────────────────
    equity_safe = equity if equity > 0 else 1.0
    sector_map: Dict[str, Dict[str, Any]] = {}

    for pos in open_positions:
        pos["exposure_pct"] = round(pos["market_value"] / equity_safe * 100.0, 2)
        sector = pos.get("sector") or "UNKNOWN"
        if sector not in sector_map:
            sector_map[sector] = {"total_value": 0.0, "position_count": 0}
        sector_map[sector]["total_value"] += pos["market_value"]
        sector_map[sector]["position_count"] += 1

    sector_exposures: List[Dict[str, Any]] = []
    for sector, data in sector_map.items():
        exp_pct = round(data["total_value"] / equity_safe * 100.0, 2)
        sector_exposures.append({
            "sector": sector,
            "total_value": round(data["total_value"], 2),
            "exposure_pct": exp_pct,
            "limit_pct": sector_limit_pct,
            "ratio": round(exp_pct / sector_limit_pct, 4) if sector_limit_pct > 0 else 0.0,
            "position_count": data["position_count"],
        })
    sector_exposures.sort(key=lambda s: s["exposure_pct"], reverse=True)

    # ── 6. Exposure warnings ───────────────────────────────────────────────
    exposure_warnings: List[Dict[str, Any]] = []

    for pos in open_positions:
        ratio = pos["exposure_pct"] / instrument_limit_pct if instrument_limit_pct > 0 else 0.0
        if ratio >= _WARNING_RATIO:
            exposure_warnings.append({
                "kind": "instrument",
                "name": pos["symbol"],
                "exposure_pct": pos["exposure_pct"],
                "limit_pct": instrument_limit_pct,
                "ratio": round(ratio, 4),
                "severity": "CRITICAL" if ratio >= 1.0 else "WARNING",
            })

    for se in sector_exposures:
        if se["ratio"] >= _WARNING_RATIO:
            exposure_warnings.append({
                "kind": "sector",
                "name": se["sector"],
                "exposure_pct": se["exposure_pct"],
                "limit_pct": sector_limit_pct,
                "ratio": se["ratio"],
                "severity": "CRITICAL" if se["ratio"] >= 1.0 else "WARNING",
            })

    return {
        "status": status,
        "paper_mode": True,
        "snapshotted_at": _now_iso(),
        "equity": round(equity, 2),
        "cash": round(cash, 2),
        "buying_power": round(buying_power, 2),
        "invested_value": round(total_invested, 2),
        "initial_capital": round(initial_capital, 2),
        "unrealised_pnl": round(unrealised_pnl, 2),
        "realised_pnl_today": round(realised_pnl_today, 2),
        "total_pnl": round(unrealised_pnl + realised_pnl_today, 2),
        "peak_equity": round(peak_equity, 2),
        "drawdown_amount": round(drawdown_amount, 2),
        "drawdown_pct": round(drawdown_pct, 2),
        "open_positions": open_positions,
        "open_position_count": len(open_positions),
        "closed_positions_today": closed_count_today,
        # Exposure data
        "instrument_limit_pct": instrument_limit_pct,
        "sector_limit_pct": sector_limit_pct,
        "sector_exposures": sector_exposures,
        "exposure_warnings": exposure_warnings,
    }


def get_portfolio_health() -> Dict[str, Any]:
    """Return a health/readiness summary for the portfolio service."""
    now = _now_iso()

    # Check auto-paper activation via phase22_activation (paper_automation_active)
    enabled = False
    activation_ok = False
    try:
        from phase22_activation import get_activation_status as _get_act
        act = _get_act() or {}
        enabled = bool(act.get("paper_automation_active", False))
        activation_ok = True
    except Exception:
        pass

    # Check if portfolio has been initialised (has any state)
    initialized = False
    state_fresh = None
    try:
        from paper_trader import _load_state
        state = _load_state() or {}
        initialized = bool(state)
        ts_str = state.get("last_updated") or state.get("updated_at")
        if ts_str:
            try:
                ts = datetime.fromisoformat(str(ts_str).replace("Z", "+00:00"))
                state_fresh = (datetime.now(timezone.utc) - ts).total_seconds()
            except Exception:
                pass
    except Exception:
        pass

    # Check for unresolved reconciliation discrepancies
    unresolved = 0
    try:
        from eod_reconciliation import get_reconciliation_status
        rec = get_reconciliation_status() or {}
        unresolved = int(rec.get("unresolved_count", rec.get("open_discrepancies", 0)) or 0)
    except Exception:
        pass

    # Derive overall status
    if not initialized:
        status = "UNKNOWN"
    elif unresolved > 0:
        status = "DEGRADED"
    elif enabled:
        status = "HEALTHY"
    else:
        status = "HEALTHY"

    return {
        "status": status,
        "initialized": initialized,
        "paper_mode": True,
        "auto_paper_enabled": enabled,
        "activation_check_ok": activation_ok,
        "state_freshness_s": state_fresh,
        "unresolved_discrepancies": unresolved,
        "liveness": initialized,
        "readiness": initialized,
        "degraded": unresolved > 0,
        "failure_reason": None,
        "checked_at": now,
    }
