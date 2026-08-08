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
    # Canonical positions (phase20 ledger incl. EXIT_PENDING, canonical marks)
    # adapted to this endpoint's legacy row shape.
    open_positions: List[Dict[str, Any]] = []
    try:
        from canonical_portfolio import build_canonical_portfolio
        for p in build_canonical_portfolio()["positions"]:
            qty = int(p.get("quantity") or 0)
            fill_price = _safe_float(p.get("avg_price"))           # avg entry
            mark = p.get("mark_price")
            cur_price = _safe_float(mark) if mark is not None else fill_price
            market_val = _safe_float(p.get("market_value") or cur_price * qty)
            upnl = _safe_float(p.get("unrealized_pnl", 0))
            upnl_pct = ((upnl / (fill_price * qty)) * 100
                        if fill_price > 0 and qty > 0 else 0.0)
            open_positions.append({
                "symbol":             str(p.get("symbol") or ""),
                "quantity":           qty,
                "avg_entry_price":    fill_price,
                "last_price":         cur_price,
                "market_value":       round(market_val, 2),
                "unrealised_pnl":     round(upnl, 2),
                "unrealised_pnl_pct": round(upnl_pct, 2),
                "side":               "LONG",
                "strategy_id":        p.get("strategy_id"),
                "sector":             p.get("sector"),
                "opened_at":          p.get("opened_at"),
                "mark_source":        p.get("mark_source"),
                "status":             p.get("status"),
            })
    except Exception as exc:
        logger.debug("canonical positions unavailable: %s", exc)

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

    # Canonical cash/equity accounting (phase20 ledger — single source of truth):
    #   cash = INITIAL_CAPITAL − Σ(open cost) + Σ(realized)
    # Never mix legacy paper_trader cash with ledger positions (that double-counts).
    try:
        from canonical_portfolio import build_canonical_portfolio
        _canon = build_canonical_portfolio()
        cash = _canon["cash"]
        total_invested = _canon["invested_value"]
        unrealised_pnl = _safe_float(_canon["unrealized_pnl"])
        _INITIAL_CAPITAL_local = _canon["initial_capital"] or _INITIAL_CAPITAL_local
    except Exception:
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

    # equity = capital + realized + unrealized MTM (canonical accounting);
    # cash + cost-basis invested would silently drop unrealized P&L.
    equity = cash + total_invested + unrealised_pnl
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
    limits_from_config = False
    try:
        from src.portfolio.config import PortfolioConfig
        _cfg = PortfolioConfig()
        instrument_limit_pct = float(_cfg.max_instrument_exposure_pct) * 100.0
        sector_limit_pct = float(_cfg.max_sector_exposure_pct) * 100.0
        limits_from_config = True
    except Exception as exc:
        logger.debug("PortfolioConfig unavailable; using hardcoded defaults: %s", exc)

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
        "limits_from_config": limits_from_config,
        "sector_exposures": sector_exposures,
        "exposure_warnings": exposure_warnings,
    }


def get_portfolio_config() -> Dict[str, Any]:
    """Return a JSON-serialisable snapshot of the active PortfolioConfig values."""
    loaded = False
    cfg_data: Dict[str, Any] = {}
    error: str | None = None
    try:
        from src.portfolio.config import PortfolioConfig
        cfg = PortfolioConfig()
        loaded = True
        cfg_data = {
            # ── Identity ─────────────────────────────────────────────
            "portfolio_id":                    cfg.portfolio_id,
            "enabled":                         cfg.enabled,
            "base_currency":                   cfg.base_currency,
            "paper_mode":                      cfg.paper_mode,
            # ── Capital ──────────────────────────────────────────────
            "initial_capital":                 float(cfg.initial_capital),
            "cash_reserve_pct":                float(cfg.cash_reserve_pct),
            # ── Exposure limits (stored as fractions 0–1) ─────────────
            "max_portfolio_exposure_pct":      float(cfg.max_portfolio_exposure_pct),
            "max_instrument_exposure_pct":     float(cfg.max_instrument_exposure_pct),
            "max_sector_exposure_pct":         float(cfg.max_sector_exposure_pct),
            "max_strategy_exposure_pct":       float(cfg.max_strategy_exposure_pct),
            # ── Position / order counts ───────────────────────────────
            "max_open_positions":              cfg.max_open_positions,
            "max_pending_orders":              cfg.max_pending_orders,
            # ── Loss / drawdown caps ──────────────────────────────────
            "max_daily_loss_pct":              float(cfg.max_daily_loss_pct),
            "max_drawdown_pct":                float(cfg.max_drawdown_pct),
            "max_capital_per_strategy_pct":    float(cfg.max_capital_per_strategy_pct),
            # ── Position sizing ───────────────────────────────────────
            "min_order_value":                 float(cfg.min_order_value),
            "max_order_value":                 float(cfg.max_order_value),
            "default_risk_per_trade_pct":      float(cfg.default_risk_per_trade_pct),
            "use_ai_confidence_sizing":        cfg.use_ai_confidence_sizing,
            "ai_confidence_min":               float(cfg.ai_confidence_min),
            # ── Staleness thresholds (seconds) ────────────────────────
            "stale_state_threshold_s":         cfg.stale_state_threshold_s,
            "stale_broker_threshold_s":        cfg.stale_broker_threshold_s,
            "stale_price_threshold_s":         cfg.stale_price_threshold_s,
            # ── Intervals (seconds) ───────────────────────────────────
            "reconciliation_interval_s":       cfg.reconciliation_interval_s,
            "snapshot_interval_s":             cfg.snapshot_interval_s,
            "allocation_ttl_s":                cfg.allocation_ttl_s,
        }
    except Exception as exc:
        error = str(exc)
        logger.debug("PortfolioConfig unavailable in get_portfolio_config: %s", exc)

    return {
        "loaded": loaded,
        "limits_from_config": loaded,
        "config": cfg_data,
        "error": error,
        "fetched_at": _now_iso(),
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

    # Check whether PortfolioConfig loaded successfully
    limits_from_config = False
    try:
        from src.portfolio.config import PortfolioConfig
        PortfolioConfig()
        limits_from_config = True
    except Exception as exc:
        logger.debug("PortfolioConfig unavailable in health check: %s", exc)

    # Check whether an email transport is configured (no secrets exposed).
    email_transport_configured = False
    try:
        from email_alerts import provider_status
        email_transport_configured = bool(provider_status().get("configured", False))
    except Exception as exc:
        logger.debug("email_alerts provider_status unavailable: %s", exc)

    # Emit a notification the first time per UTC day that limits fall back to
    # defaults.  Uses kv_get/kv_set for durable deduplication so the alert
    # fires at most once per day even when the health endpoint is polled
    # repeatedly throughout the session.
    if not limits_from_config:
        _ALERT_KIND = "PERFORMANCE_ALERT"
        _ALERT_TITLE = "Portfolio config missing — exposure limits using defaults"
        _ALERT_BODY = (
            "Exposure limits using hardcoded defaults — check PortfolioConfig import"
        )
        _ALERT_DEDUP_KEY = "portfolio_config_alert_day"
        try:
            today_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            import phase20_store as _store
            last_sent = _store.kv_get(_ALERT_DEDUP_KEY, default=None)
            if last_sent != today_utc:
                _store.add_notification(
                    kind=_ALERT_KIND,
                    title=_ALERT_TITLE,
                    body=_ALERT_BODY,
                    severity="WARNING",
                )
                _store.kv_set(_ALERT_DEDUP_KEY, today_utc)
                logger.info(
                    "portfolio_snapshot: emitted config-defaults notification "
                    "(first occurrence today %s)",
                    today_utc,
                )
        except Exception as _alert_exc:
            # Best-effort — a broken notification store must not break the
            # health endpoint or any caller.
            logger.debug("Failed to emit config-defaults notification: %s", _alert_exc)

    # Collect all degraded reasons
    degraded_reasons: List[str] = []
    if unresolved > 0:
        degraded_reasons.append(
            f"{unresolved} unresolved reconciliation discrepanc"
            f"{'y' if unresolved == 1 else 'ies'}"
        )
    if not limits_from_config:
        degraded_reasons.append(
            "Exposure limits using hardcoded defaults — check PortfolioConfig import"
        )

    # Derive overall status
    if not initialized:
        status = "UNKNOWN"
    elif degraded_reasons:
        status = "DEGRADED"
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
        "limits_from_config": limits_from_config,
        "degraded_reasons": degraded_reasons,
        "liveness": initialized,
        "readiness": initialized,
        "degraded": bool(degraded_reasons),
        "failure_reason": degraded_reasons[0] if degraded_reasons else None,
        # True when at least one email transport (Resend or SMTP) is configured.
        # When False and limits_from_config is also False, the config-defaults
        # PERFORMANCE_ALERT was stored in-app but email delivery was silently
        # skipped — surface this to the operator.
        "email_transport_configured": email_transport_configured,
        "checked_at": now,
    }
