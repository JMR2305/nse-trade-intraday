"""portfolio_bridge.py — wire the RC-10C1 Portfolio Core into the live signal flow.

Spec flow:  Strategy → SignalRouter → **Portfolio Pre-Check** → RC-8 → RC-7 → RC-10D

In this codebase the live signal path is:

    intelligence.run_intelligence_scan()  (signals)
        → paper_trader.execute_buy/sell   (order commit — RC-8-style gates live
          in phase11_risk + execution_engine.PreTradeValidator)

This bridge exposes a small synchronous API over the async PortfolioService
so the per-process CLI/scan world can call it:

    startup()            — instantiate + initialise + seed from the canonical
                           paper ledger + reconcile (startup reconciliation).
    pre_check(...)       — evaluate_allocation() + evaluate_limits() for a
                           proposed BUY; MUST be called before RC-8 checks.
    on_fill(...)         — forward a paper fill to portfolio_service.apply_fill().
    update_price(...)    — forward a mark to update_market_price().
    update_prices(...)   — bulk mark update from a scan snapshot.
    reconcile_now()      — reconcile against the canonical paper snapshot
                           (called on startup and by the phase20 scheduler).

Fail-safe policy
----------------
* pre_check fails CLOSED: any internal error blocks the order with a clear
  reason code (PORTFOLIO_PRECHECK_ERROR) — limits must never be silently
  skipped.
* on_fill / update_price / reconcile_now fail OPEN (log + continue): state
  mirroring must never lose an already-committed fill or break a scan.
* If PORTFOLIO_ENABLED=false the pre-check is a no-op pass-through so the
  bridge can be disabled operationally without code changes.
"""
from __future__ import annotations

import asyncio
import logging
import os
import zlib
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ── Event loop + service singletons (per process) ─────────────────────────────

_loop: Optional[asyncio.AbstractEventLoop] = None
_service = None          # PortfolioService
_started = False
_startup_error: Optional[str] = None


def _get_loop() -> asyncio.AbstractEventLoop:
    global _loop
    if _loop is None or _loop.is_closed():
        _loop = asyncio.new_event_loop()
    return _loop


def _run(coro):
    """Run *coro* on the bridge's dedicated event loop."""
    return _get_loop().run_until_complete(coro)


def instrument_token_for(symbol: str) -> int:
    """Deterministic stable pseudo-token for an NSE symbol (paper flow)."""
    return zlib.crc32(symbol.upper().strip().encode()) & 0x7FFFFFFF


def sector_for(symbol: str) -> str:
    try:
        import config
        sym = symbol.upper().strip()
        for sector, syms in config.SECTOR_MAP.items():
            if sym in syms:
                return sector
    except Exception:
        pass
    return "OTHER"


def _build_service():
    from src.portfolio.config import PortfolioConfig
    from src.portfolio.service import PortfolioService
    from src.portfolio.repositories.portfolio_event import PortfolioEventRepository
    from src.portfolio.repositories.portfolio_snapshot import PortfolioSnapshotRepository
    from src.portfolio.repositories.reconciliation import ReconciliationRepository

    try:
        import portfolio_store
        initial_capital = str(portfolio_store.INITIAL_CAPITAL)
    except Exception:
        initial_capital = "50000"

    cfg = PortfolioConfig(
        initial_capital=Decimal(os.environ.get(
            "PORTFOLIO_INITIAL_CAPITAL", initial_capital)),
        # Paper orders on a ₹50k book are small; the library default of ₹5,000
        # min order value would silently strangle the pipeline (see the
        # pipeline-gate calibration incident). Keep the floor tiny unless an
        # operator explicitly raises it via env.
        min_order_value=Decimal(os.environ.get("PORTFOLIO_MIN_ORDER_VALUE", "50")),
    )
    return PortfolioService(
        config=cfg,
        snapshot_repo=PortfolioSnapshotRepository(),
        event_repo=PortfolioEventRepository(),
        reconciliation_repo=ReconciliationRepository(),
    )


def _canonical_state() -> Dict[str, Any]:
    """Canonical paper positions + cash (phase20 ledger)."""
    from canonical_portfolio import build_canonical_portfolio
    return build_canonical_portfolio()


def _broker_like_snapshot(canon: Dict[str, Any]) -> Dict[str, Any]:
    """Map the canonical paper portfolio to the broker-neutral reconcile dict."""
    positions = []
    for p in canon.get("positions", []):
        positions.append({
            "instrument_token": instrument_token_for(p["symbol"]),
            "quantity": int(p.get("quantity") or 0),
            "average_price": float(p.get("avg_price") or 0.0),
            "realised_pnl": 0.0,
            "product": "CNC",
        })
    return {
        "positions": positions,
        "orders": [],
        "funds": {
            "available_cash": float(canon.get("cash") or 0.0),
            "used_margin": 0.0,
            "total": float(canon.get("cash") or 0.0),
        },
        "trades": [],
        "as_of": datetime.now(timezone.utc).isoformat(),
    }


def get_service():
    """Return the process-level PortfolioService, starting it if needed."""
    startup()
    return _service


def startup(force: bool = False) -> bool:
    """Instantiate + initialise the PortfolioService and run the startup
    reconciliation. Idempotent per process. Returns True when the service
    is ready."""
    global _service, _started, _startup_error
    if _started and not force:
        return _service is not None
    _started = True
    try:
        _service = _build_service()
        canon = _canonical_state()
        _run(_service.initialise(Decimal(str(canon.get("initial_capital")
                                             or _service.config.initial_capital))))

        # Seed open canonical positions as synthetic fills so exposure and
        # limit checks see the true current book, not an empty portfolio.
        from src.portfolio.contracts import PositionSide
        for p in canon.get("positions", []):
            qty = int(p.get("quantity") or 0)
            if qty <= 0:
                continue
            sym = str(p.get("symbol") or "")
            trade_id = str(p.get("trade_id") or f"{sym}-{qty}")
            try:
                _run(_service.apply_fill(
                    idempotency_key=f"seed-{trade_id}",
                    instrument_token=instrument_token_for(sym),
                    instrument_symbol=sym,
                    side=PositionSide.LONG,
                    quantity=qty,
                    price=Decimal(str(p.get("avg_price") or 0.0)),
                    fill_id=f"seed-{trade_id}",
                    filled_at=datetime.now(timezone.utc),
                    order_id=trade_id,
                    strategy_id=p.get("strategy_id"),
                    sector=p.get("sector") or sector_for(sym),
                ))
                mark = p.get("mark_price")
                if mark:
                    _run(_service.update_market_price(
                        instrument_token_for(sym), Decimal(str(mark)),
                        datetime.now(timezone.utc)))
            except Exception as exc:
                logger.warning("portfolio seed fill failed for %s: %s", sym, exc)

        # Startup reconciliation (dry-run analysis against the paper ledger).
        try:
            _run(_service.reconcile(_broker_like_snapshot(canon), dry_run=True))
        except Exception as exc:
            logger.warning("startup reconciliation failed: %s", exc)

        _startup_error = None
        logger.info("portfolio_bridge started (portfolio pre-check active)")
        return True
    except Exception as exc:
        _service = None
        _startup_error = str(exc)
        logger.error("portfolio_bridge startup failed: %s", exc)
        return False


def is_enabled() -> bool:
    v = os.environ.get("PORTFOLIO_ENABLED", "true").strip().lower()
    return v in {"1", "true", "yes"}


# ── Pre-check (called BEFORE RC-8-style order validation) ─────────────────────

def pre_check(
    symbol: str,
    quantity: int,
    price: float,
    strategy_id: str = "ai_scan",
    sector: Optional[str] = None,
) -> Dict[str, Any]:
    """Portfolio pre-check for a proposed BUY.

    Runs evaluate_allocation() + evaluate_limits(). Fails CLOSED on internal
    errors. Returns {approved, reasons, allocation_status, limits_allowed}.
    """
    if not is_enabled():
        return {"approved": True, "reasons": ["PORTFOLIO_DISABLED"],
                "allocation_status": "SKIPPED", "limits_allowed": True}
    try:
        if not startup():
            return {"approved": False,
                    "reasons": [f"PORTFOLIO_PRECHECK_ERROR: startup failed: {_startup_error}"],
                    "allocation_status": "ERROR", "limits_allowed": False}

        value = Decimal(str(price)) * Decimal(int(quantity))
        token = instrument_token_for(symbol)
        sec = sector or sector_for(symbol)

        # Keep the mark fresh so staleness guards see a current price.
        try:
            _run(_service.update_market_price(
                token, Decimal(str(price)), datetime.now(timezone.utc)))
        except Exception:
            pass

        alloc = _run(_service.evaluate_allocation(
            strategy_id=strategy_id or "ai_scan",
            requested_capital=value,
            instrument_token=token,
        ))
        limits = _run(_service.evaluate_limits(
            proposed_instrument_token=token,
            proposed_value=value,
            proposed_strategy_id=strategy_id or "ai_scan",
            proposed_sector=sec,
        ))

        reasons: List[str] = list(alloc.reason_codes or ())
        alloc_ok = alloc.status.value == "APPROVED"
        limits_ok = bool(limits.overall_allowed)
        if not limits_ok and limits.blocking_limit:
            reasons.append(f"LIMIT_BREACH:{limits.blocking_limit}")
        approved = alloc_ok and limits_ok
        return {
            "approved": approved,
            "reasons": reasons if not approved else reasons,
            "allocation_status": alloc.status.value,
            "approved_capital": float(alloc.approved_capital),
            "limits_allowed": limits_ok,
            "blocking_limit": limits.blocking_limit,
        }
    except Exception as exc:
        logger.error("portfolio pre_check error for %s: %s", symbol, exc)
        return {"approved": False,
                "reasons": [f"PORTFOLIO_PRECHECK_ERROR: {exc}"],
                "allocation_status": "ERROR", "limits_allowed": False}


# ── Fill + price forwarding (fail-open) ───────────────────────────────────────

def on_fill(
    symbol: str,
    side: str,
    quantity: int,
    price: float,
    trade_id: str,
    strategy_id: Optional[str] = None,
    fees: float = 0.0,
) -> None:
    """Forward a committed paper fill to portfolio_service.apply_fill()."""
    if not is_enabled():
        return
    try:
        if not startup():
            return
        from src.portfolio.contracts import PositionSide
        _run(_service.apply_fill(
            idempotency_key=f"fill-{trade_id}",
            instrument_token=instrument_token_for(symbol),
            instrument_symbol=symbol.upper(),
            side=PositionSide.LONG if str(side).upper() == "BUY" else PositionSide.SHORT,
            quantity=int(quantity),
            price=Decimal(str(price)),
            fill_id=str(trade_id),
            filled_at=datetime.now(timezone.utc),
            order_id=str(trade_id),
            fees=Decimal(str(fees)),
            strategy_id=strategy_id,
            sector=sector_for(symbol),
        ))
    except Exception as exc:
        logger.warning("portfolio on_fill failed for %s %s: %s", side, symbol, exc)


def update_price(symbol: str, price: float) -> None:
    """Forward a single mark to portfolio_service.update_market_price()."""
    if not is_enabled():
        return
    try:
        if not startup():
            return
        _run(_service.update_market_price(
            instrument_token_for(symbol), Decimal(str(price)),
            datetime.now(timezone.utc)))
    except Exception as exc:
        logger.debug("portfolio update_price failed for %s: %s", symbol, exc)


def update_prices(prices: Dict[str, float]) -> None:
    """Bulk mark update from a scan snapshot ({symbol: last_price})."""
    if not is_enabled():
        return
    if not startup():
        return
    for sym, px in (prices or {}).items():
        try:
            if px and float(px) > 0:
                update_price(sym, float(px))
        except Exception:
            continue


def reconcile_now() -> Dict[str, Any]:
    """Reconcile the portfolio service against the canonical paper snapshot.

    Called on startup (inside startup()) and on a schedule by the phase20
    scheduler tick. Fail-open: returns an error dict instead of raising.
    """
    if not is_enabled():
        return {"skipped": True, "reason": "PORTFOLIO_DISABLED"}
    try:
        if not startup():
            return {"error": f"startup failed: {_startup_error}"}
        report = _run(_service.reconcile(
            _broker_like_snapshot(_canonical_state()), dry_run=True))
        return {
            "run_id": str(report.run_id),
            "critical_count": report.critical_count,
            "warning_count": report.warning_count,
            "portfolio_ready": report.portfolio_ready,
        }
    except Exception as exc:
        logger.warning("portfolio reconcile_now failed: %s", exc)
        return {"error": str(exc)}
