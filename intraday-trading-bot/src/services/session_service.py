"""Session management with idempotency, recovery, and persistence."""

import uuid
from datetime import datetime, timezone
from typing import Optional, Dict, Any

from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import settings
from src.core.logging import logger
from src.core.market_calendar import market_calendar
from src.core.idempotency import IdempotencyManager
from src.core.exceptions import SessionError
from src.database.repositories.sessions import SessionRepository
from src.database.repositories.idempotency import IdempotencyRepository
from src.database.repositories.orders import OrderRepository
from src.database.repositories.positions import PositionRepository
from src.database.repositories.ledger import LedgerRepository
from src.database.models import TradingSession


class SessionService:
    """Manages trading sessions with idempotency and restart recovery."""

    def __init__(self, db_session: AsyncSession) -> None:
        self._db = db_session
        self._session_repo = SessionRepository(db_session)
        self._idempotency_repo = IdempotencyRepository(db_session)
        self._idempotency = IdempotencyManager(self._idempotency_repo)

    async def start_session(self, recovery_mode: str = "auto", created_by: str = "system") -> TradingSession:
        session_date = market_calendar.get_session_date()
        idem_key = self._idempotency.generate_key("SESSION_START", "session", session_date)

        existing = await self._session_repo.get_by_idempotency_key(idem_key)
        if existing:
            logger.info(f"Session already exists: {existing.session_id}", extra={"event_type": "SESSION_EXISTS", "session_id": existing.session_id})
            return existing

        active = await self._session_repo.get_active_session()
        if active and recovery_mode == "auto":
            logger.info(f"Recovering active session: {active.session_id}", extra={"event_type": "SESSION_RECOVER", "session_id": active.session_id})
            return active

        session_id = f"sess_{session_date}_{uuid.uuid4().hex[:8]}"
        previous_session = await self._session_repo.get_last_session()

        recovery_snapshot = None
        recovery_reason = None
        if recovery_mode == "auto" and previous_session:
            recovery_snapshot = {"previous_session_id": previous_session.session_id, "previous_status": previous_session.status}
            recovery_reason = f"Recovered from {previous_session.session_id}"

        await self._idempotency.check_and_store(idem_key, "SESSION_START")

        session = await self._session_repo.create(
            session_id=session_id,
            status="ACTIVE",
            trading_mode=settings.trading.mode,
            previous_session_id=previous_session.session_id if previous_session else None,
            recovery_reason=recovery_reason,
            recovery_snapshot=recovery_snapshot,
            idempotency_key=idem_key,
        )

        ledger_repo = LedgerRepository(self._db)
        await ledger_repo.create(
            session_id=session_id,
            transaction_type="DEPOSIT",
            amount=settings.paper.initial_capital,
            balance_after=settings.paper.initial_capital,
            description="Initial paper capital",
        )

        logger.info(f"Session started: {session_id}", extra={"event_type": "SESSION_START", "session_id": session_id, "recovery_mode": recovery_mode})
        return session

    async def get_active_session(self) -> Optional[TradingSession]:
        return await self._session_repo.get_active_session()

    async def end_session(self, session_id: str, mode: str = "graceful") -> Optional[TradingSession]:
        session = await self._session_repo.get_by_session_id(session_id)
        if not session:
            raise SessionError(f"Session not found: {session_id}")
        if mode == "emergency":
            logger.critical(f"Emergency shutdown for session {session_id}", extra={"event_type": "SESSION_EMERGENCY_SHUTDOWN", "session_id": session_id})
        ended = await self._session_repo.end_session(session_id)
        logger.info(f"Session ended: {session_id} (mode={mode})", extra={"event_type": "SESSION_END", "session_id": session_id, "shutdown_mode": mode})
        return ended

    async def get_session_state(self, session_id: str) -> Dict[str, Any]:
        session = await self._session_repo.get_by_session_id(session_id)
        if not session:
            raise SessionError(f"Session not found: {session_id}")
        order_repo = OrderRepository(self._db)
        position_repo = PositionRepository(self._db)
        ledger_repo = LedgerRepository(self._db)
        orders = await order_repo.get_by_session(session_id)
        positions = await position_repo.get_open_positions(session_id)
        balance = await ledger_repo.get_current_balance(session_id)
        return {
            "session_id": session_id,
            "status": session.status,
            "trading_mode": session.trading_mode,
            "started_at": session.started_at.isoformat() if session.started_at else None,
            "order_count": len(orders),
            "open_position_count": len(positions),
            "current_balance": float(balance),
            "orders": [{"id": o.id, "order_id": o.order_id, "symbol": o.instrument_token, "side": o.side, "quantity": o.quantity, "status": o.status} for o in orders],
            "positions": [{"id": p.id, "instrument_token": p.instrument_token, "side": p.side, "quantity": p.quantity, "average_price": float(p.average_price)} for p in positions],
        }
