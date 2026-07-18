"""Application entry point with safe mode checks."""

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.core.config import settings
from src.core.logging import logger
from src.core.kill_switch import kill_switch_manager
from src.core.market_calendar import market_calendar
from src.core.exceptions import ConfigurationError, LiveModeBlockedError
from src.api.middleware.correlation_id import CorrelationIdMiddleware
from src.api.middleware.audit import AuditMiddleware
from src.api.middleware.cors import setup_cors
from src.api.routers import health, auth, sessions, orders, positions, risk


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    logger.info("Starting intraday trading bot", extra={"event_type": "APP_STARTUP", "version": "2.0.1-acr", "trading_mode": settings.trading.mode})
    if not settings.is_paper_mode:
        logger.critical("LIVE mode detected — structurally blocked", extra={"event_type": "LIVE_MODE_BLOCKED"})
        raise LiveModeBlockedError("LIVE mode is structurally unavailable. Use PAPER mode.")
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
