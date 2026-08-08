"""Application entry point with safe mode checks."""

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.core.config import settings
from src.core.logging import logger
from src.core.kill_switch import kill_switch_manager
from src.core.market_calendar import market_calendar
from src.core.exceptions import ConfigurationError
from src.api.middleware.correlation_id import CorrelationIdMiddleware
from src.api.middleware.audit import AuditMiddleware
from src.api.middleware.cors import setup_cors
from src.api.routers import health, auth, sessions, orders, positions, risk


async def _close_live_broker() -> None:
    """Close and deregister the live broker adapter (stops expiry monitor +
    websocket).  Best-effort: never raises.  Safe to call when not in live mode."""
    from src.brokers.registry import clear_live_broker, get_live_broker
    live_adapter = get_live_broker()
    if live_adapter is not None:
        try:
            await live_adapter.close()
        except Exception as exc:  # noqa: BLE001 — cleanup must not raise
            logger.warning(
                f"Live broker close failed during cleanup: {exc}",
                extra={"event_type": "LIVE_BROKER_CLOSE_FAILED"},
            )
    clear_live_broker()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    logger.info("Starting intraday trading bot", extra={"event_type": "APP_STARTUP", "version": "2.0.1-acr", "trading_mode": settings.trading.mode})

    # Live-mode startup gate: when not in paper mode, validate all 5 runtime
    # gates pass, restore + probe the Zerodha session, wire the health tracker,
    # and register a singleton authenticated adapter in the broker registry.
    # Any failure here prevents startup with a clear operator-facing message.
    if not settings.is_paper_mode:
        from src.brokers.zerodha.config import load_config_from_env
        from src.brokers.zerodha.adapter import ZerodhaAdapter
        from src.brokers.registry import set_live_broker, clear_live_broker
        zerodha_cfg = load_config_from_env()
        if not zerodha_cfg.is_live_order_allowed():
            missing = [
                k for k, v in {
                    "ZERODHA_ENABLED": zerodha_cfg.enabled,
                    "ZERODHA_PAPER_TRADING=false": not zerodha_cfg.paper_trading,
                    "ZERODHA_LIVE_TRADING_ENABLED": zerodha_cfg.live_trading_enabled,
                    "ZERODHA_API_KEY": bool(zerodha_cfg.api_key),
                    "ZERODHA_ACCESS_TOKEN": bool(zerodha_cfg.access_token),
                }.items() if not v
            ]
            raise ConfigurationError(
                f"LIVE mode requires all 5 gates to pass. Not satisfied: {missing}. "
                "Set the missing env vars or switch TRADING__MODE=PAPER."
            )
        adapter = ZerodhaAdapter(zerodha_cfg)
        try:
            await adapter.initialize_live_session()
        except Exception as exc:
            # Release any resources acquired before the failure (e.g. an
            # already-started expiry monitor) so nothing leaks on startup abort.
            try:
                await adapter.close()
            except Exception:  # noqa: BLE001 — best-effort cleanup
                pass
            raise ConfigurationError(
                f"LIVE mode startup failed: {exc}. "
                "Check ZERODHA_ACCESS_TOKEN and re-run the OAuth flow if expired."
            ) from exc
        set_live_broker(adapter)

    # Everything after live-broker registration runs under try/finally so a
    # failure in any later startup step (or normal shutdown) always closes the
    # adapter — cancelling the auto-started TokenExpiryMonitor and websocket.
    try:
        if not settings.database_url:
            raise ConfigurationError("DATABASE_URL not configured")
        if not settings.jwt_secret_key or len(settings.jwt_secret_key) < 32:
            raise ConfigurationError("JWT_SECRET_KEY must be at least 32 characters")
        now_ist = market_calendar.now_ist()
        logger.info(f"Market status: open={market_calendar.is_market_open()}, pre_open={market_calendar.is_pre_open()}, current_ist={now_ist.isoformat()}", extra={"event_type": "MARKET_STATUS_CHECK"})
        from src.services.operator_auth_service import operator_auth_service
        operator_auth_service.register_user("admin", "admin123", is_admin=True)
        logger.info("Default admin user registered (dev only)", extra={"event_type": "DEV_USER_REGISTERED"})
        yield
    finally:
        await _close_live_broker()
        logger.info("Shutting down intraday trading bot", extra={"event_type": "APP_SHUTDOWN"})


def create_app() -> FastAPI:
    """Create and configure FastAPI application."""
    app = FastAPI(title="Intraday Trading Bot", version="2.0.1-acr", description="Production-grade paper-first intraday trading platform",
                  docs_url="/docs" if settings.debug else None, redoc_url="/redoc" if settings.debug else None, lifespan=lifespan)
    app.add_middleware(CorrelationIdMiddleware)
    app.add_middleware(AuditMiddleware)
    setup_cors(app)
    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(sessions.router)
    app.include_router(orders.router)
    app.include_router(positions.router)
    app.include_router(risk.router)
    logger.info("FastAPI application configured", extra={"event_type": "APP_CONFIGURED"})
    return app


app = create_app()
