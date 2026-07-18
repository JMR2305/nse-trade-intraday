"""Order management endpoints."""

from decimal import Decimal
from typing import Dict, Any, Optional

from fastapi import APIRouter, Depends, HTTPException, status, Header
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies import get_db, get_current_user
from src.services.execution_service import ExecutionService
from src.services.order_service import OrderService
from src.services.session_service import SessionService
from src.core.exceptions import KillSwitchError, OrderValidationError, IdempotencyError, LiveModeBlockedError

router = APIRouter(prefix="/trading", tags=["trading"])


@router.post("/place_order")
async def place_order(symbol: str, side: str, quantity: int, order_type: str = "MARKET",
                      price: Optional[float] = None, trigger_price: Optional[float] = None,
                      stop_loss: Optional[float] = None, target: Optional[float] = None,
                      x_idempotency_key: str = Header(..., alias="X-Idempotency-Key"),
                      db: AsyncSession = Depends(get_db), user_id: str = Depends(get_current_user)) -> Dict[str, Any]:
    """Place a paper order. Requires idempotency key. Live execution structurally unavailable."""
    session_service = SessionService(db)
    session = await session_service.get_active_session()
    if not session:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No active session. Start a session first.")
    execution = ExecutionService(db)
    try:
        result = await execution.execute_order(
            session_id=session.session_id, instrument_token=0, symbol=symbol, side=side, quantity=quantity,
            order_type=order_type, price=Decimal(str(price)) if price else None,
            trigger_price=Decimal(str(trigger_price)) if trigger_price else None,
            stop_loss=Decimal(str(stop_loss)) if stop_loss else None,
            target=Decimal(str(target)) if target else None, idempotency_key=x_idempotency_key, created_by=user_id)
        return {"status": "success", "mode": "PAPER", **result, "idempotency_key": x_idempotency_key}
    except KillSwitchError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))
    except OrderValidationError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except IdempotencyError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    except LiveModeBlockedError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))


@router.post("/cancel_order")
async def cancel_order(order_id: int, db: AsyncSession = Depends(get_db), user_id: str = Depends(get_current_user)) -> Dict[str, str]:
    """Cancel an order."""
    execution = ExecutionService(db)
    result = await execution.cancel_order(order_id)
    if result:
        return {"status": "cancelled", "order_id": str(order_id)}
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found or cannot be cancelled")


@router.get("/orders")
async def get_orders(db: AsyncSession = Depends(get_db), user_id: str = Depends(get_current_user)) -> Dict[str, Any]:
    """Get all orders for active session."""
    session_service = SessionService(db)
    session = await session_service.get_active_session()
    if not session:
        return {"orders": []}
    order_service = OrderService(db)
    orders = await order_service.get_session_orders(session.session_id)
    return {"orders": [{"id": o.id, "order_id": o.order_id, "symbol": o.instrument_token, "side": o.side, "quantity": o.quantity,
                        "status": o.status, "price": float(o.price) if o.price else None,
                        "stop_loss": float(o.stop_loss) if o.stop_loss else None,
                        "target": float(o.target) if o.target else None} for o in orders]}
