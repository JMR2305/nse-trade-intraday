"""
Kill Switch mechanism for emergency trading halt.

The Kill Switch is an independently operable safety mechanism that can be
activated manually or automatically by risk rules. When active, it prevents
all new order submissions while optionally allowing risk-reducing orders.

Activation and deactivation are audited. The kill switch is per-account.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Optional, Dict, Any, List
from datetime import datetime
from pydantic import BaseModel, Field

from .contracts import RiskAction, RiskSeverity, RiskViolation, RiskCheckType
from .exceptions import KillSwitchAlreadyActiveError, KillSwitchNotActiveError


class KillSwitchEvent(BaseModel, frozen=True):
    """Immutable record of a kill switch activation or deactivation."""

    account_id: str = Field(..., description="Account affected")
    action: str = Field(..., description="ACTIVATED or DEACTIVATED")
    reason: str = Field(..., description="Reason for the action")
    actor: str = Field(default="system", description="Who triggered the action")
    event_timestamp: datetime = Field(..., description="When the event occurred")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Additional context")


class KillSwitch:
    """Emergency trading halt mechanism.

    When active, the kill switch:
    - Blocks all new orders (returns BLOCK action)
    - Optionally allows risk-reducing orders (closing positions)
    - Maintains an audit trail of all activations/deactivations

    The kill switch is per-account and operates independently of the
    RiskEngine's normal rule evaluation.
    """

    def __init__(self, account_id: str, allow_risk_reducing: bool = False):
        self.account_id: str = account_id
        self._active: bool = False
        self._reason: Optional[str] = None
        self._allow_risk_reducing: bool = allow_risk_reducing
        self._history: List[KillSwitchEvent] = []

    @property
    def is_active(self) -> bool:
        """Whether the kill switch is currently active."""
        return self._active

    @property
    def reason(self) -> Optional[str]:
        """Reason for current activation, if active."""
        return self._reason

    def activate(self, reason: str, actor: str = "system", timestamp: Optional[datetime] = None) -> KillSwitchEvent:
        """Activate the kill switch.

        Raises:
            KillSwitchAlreadyActiveError: If the kill switch is already active.
        """
        if self._active:
            raise KillSwitchAlreadyActiveError(
                f"Kill switch for account {self.account_id} is already active: {self._reason}"
            )

        if timestamp is None:
            timestamp = datetime.utcnow()

        self._active = True
        self._reason = reason

        event = KillSwitchEvent(
            account_id=self.account_id,
            action="ACTIVATED",
            reason=reason,
            actor=actor,
            event_timestamp=timestamp,
        )
        self._history.append(event)
        return event

    def deactivate(self, reason: str, actor: str = "system", timestamp: Optional[datetime] = None) -> KillSwitchEvent:
        """Deactivate the kill switch.

        Raises:
            KillSwitchNotActiveError: If the kill switch is not currently active.
        """
        if not self._active:
            raise KillSwitchNotActiveError(
                f"Kill switch for account {self.account_id} is not active"
            )

        if timestamp is None:
            timestamp = datetime.utcnow()

        self._active = False
        self._reason = None

        event = KillSwitchEvent(
            account_id=self.account_id,
            action="DEACTIVATED",
            reason=reason,
            actor=actor,
            event_timestamp=timestamp,
        )
        self._history.append(event)
        return event

    def evaluate_order(self, order_side: str, current_position_direction: str) -> Optional[RiskViolation]:
        """Evaluate whether an order is allowed under kill switch.

        Returns:
            RiskViolation if order is blocked, None if allowed.
        """
        if not self._active:
            return None

        if self._allow_risk_reducing:
            is_risk_reducing = self._is_risk_reducing(order_side, current_position_direction)
            if is_risk_reducing:
                return None

        return RiskViolation(
            check_type=RiskCheckType.KILL_SWITCH,
            severity=RiskSeverity.FATAL,
            message=f"Kill switch active: {self._reason}. All new orders blocked.",
            rule_id="kill_switch",
            metadata={"reason": self._reason, "allow_risk_reducing": self._allow_risk_reducing},
        )

    @staticmethod
    def _is_risk_reducing(order_side: str, current_position_direction: str) -> bool:
        """Determine if an order reduces risk (closes or reduces position)."""
        side = order_side.upper()
        direction = current_position_direction.upper()

        if direction == "FLAT":
            return False
        elif direction == "LONG":
            return side == "SELL"
        elif direction == "SHORT":
            return side == "BUY"
        return False

    def get_history(self) -> List[KillSwitchEvent]:
        """Return the full kill switch activation history."""
        return list(self._history)

    def reset(self) -> None:
        """Reset kill switch state — used for deterministic replay."""
        self._active = False
        self._reason = None
        self._history.clear()
