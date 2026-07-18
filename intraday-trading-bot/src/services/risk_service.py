"""Risk service — per-trade and portfolio risk checks."""

from decimal import Decimal
from typing import Tuple, Optional, Dict, Any

from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import settings
from src.core.logging import logger
from src.core.kill_switch import kill_switch_manager
from src.database.repositories.positions import PositionRepository
from src.database.repositories.ledger import LedgerRepository


class RiskService:
    """Risk manager with per-trade and portfolio-level checks. Per-trade risk = abs(entry - stop_loss) * quantity + estimated costs."""

    def __init__(self, db_session: AsyncSession) -> None:
        self._db = db_session
        self._position_repo = PositionRepository(db_session)
        self._ledger_repo = LedgerRepository(db_session)

    async def check_trade_risk(self, entry_price: Decimal, stop_loss: Optional[Decimal], quantity: int,
                               symbol: str, session_id: Optional[str] = None) -> Tuple[bool, str]:
        if not kill_switch_manager.state.can_place_orders():
            return False, f"Kill switch active: {kill_switch_manager.state.level.value}"
        if stop_loss is None:
            return False, "Stop loss required for risk calculation"
        if stop_loss <= 0:
            return False, "Stop loss must be positive"
        price_risk = abs(entry_price - stop_loss) * quantity
        turnover = entry_price * quantity
        estimated_costs = min(Decimal(str(settings.broker.brokerage_per_order)), turnover * Decimal("0.0003")) + (turnover * Decimal("0.00025"))
        total_risk = price_risk + estimated_costs
        if session_id:
            balance = await self._ledger_repo.get_current_balance(session_id)
            if balance > 0:
                risk_pct = (total_risk / balance) * 100
                if risk_pct > settings.risk.risk_per_trade_pct:
                    return False, f"Trade risk {risk_pct:.2f}% exceeds limit {settings.risk.risk_per_trade_pct}%"
        if session_id:
            open_positions = await self._position_repo.get_open_positions(session_id)
            position_value = sum(p.quantity * p.average_price for p in open_positions)
            if balance > 0:
                heat = (position_value / balance) * 100
                new_heat = heat + (entry_price * quantity / balance * 100)
                if new_heat > settings.risk.portfolio_heat_pct:
                    return False, f"Portfolio heat {new_heat:.2f}% exceeds limit {settings.risk.portfolio_heat_pct}%"
        return True, "OK"

    async def check_portfolio_risk(self, session_id: str) -> Dict[str, Any]:
        open_positions = await self._position_repo.get_open_positions(session_id)
        balance = await self._ledger_repo.get_current_balance(session_id)
        total_exposure = sum(p.quantity * p.average_price for p in open_positions)
        heat = (total_exposure / balance * 100) if balance > 0 else 0
        return {
            "portfolio_heat_pct": float(heat),
            "open_positions": len(open_positions),
            "total_exposure": float(total_exposure),
            "available_balance": float(balance),
            "kill_switch_level": kill_switch_manager.state.level.value,
            "can_trade": kill_switch_manager.state.can_place_orders(),
        }
