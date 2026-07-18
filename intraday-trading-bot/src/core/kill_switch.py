"""Three-level kill switch state machine."""

from enum import Enum
from dataclasses import dataclass, field
from typing import List, Callable, Optional, Dict, Any
from datetime import datetime, timezone

from src.core.config import settings
from src.core.logging import logger


class KillSwitchLevel(Enum):
    """Kill switch severity levels."""
    NORMAL = "NORMAL"
    PAUSE = "PAUSE"
    CANCEL_PENDING = "CANCEL_PENDING"
    FLATTEN_ALL = "FLATTEN_ALL"


@dataclass
class KillSwitchState:
    """Current kill switch state."""
    level: KillSwitchLevel = KillSwitchLevel.NORMAL
    triggered_at: Optional[datetime] = None
    triggered_by: str = "system"
    reason: str = ""

    def can_place_orders(self) -> bool:
        """Check if new orders can be placed."""
        return self.level == KillSwitchLevel.NORMAL

    def can_modify_orders(self) -> bool:
        """Check if existing orders can be modified."""
        return self.level in (KillSwitchLevel.NORMAL, KillSwitchLevel.PAUSE)

    def should_cancel_pending(self) -> bool:
        """Check if pending orders should be cancelled."""
        return self.level in (KillSwitchLevel.CANCEL_PENDING, KillSwitchLevel.FLATTEN_ALL)

    def should_flatten(self) -> bool:
        """Check if all positions should be flattened."""
        return self.level == KillSwitchLevel.FLATTEN_ALL


class KillSwitchManager:
    """Manages kill switch state with escalation and reset."""

    def __init__(self) -> None:
        self._state = KillSwitchState()
        self._listeners: List[Callable[[KillSwitchState], None]] = []
        self._history: List[KillSwitchState] = []

    @property
    def state(self) -> KillSwitchState:
        """Get current kill switch state."""
        return self._state

    def register_listener(self, callback: Callable[[KillSwitchState], None]) -> None:
        """Register a callback for state changes."""
        self._listeners.append(callback)

    def _notify(self) -> None:
        """Notify all listeners of state change."""
        for listener in self._listeners:
            try:
                listener(self._state)
            except Exception as e:
                logger.error(f"Kill switch listener failed: {e}")

    def escalate(
        self,
        level: KillSwitchLevel,
        reason: str,
        triggered_by: str = "system",
    ) -> None:
        """Escalate kill switch to a higher level."""
        if level == self._state.level:
            return

        current_priority = list(KillSwitchLevel).index(self._state.level)
        new_priority = list(KillSwitchLevel).index(level)

        # Prevent de-escalation through escalate (use reset instead)
        if new_priority <= current_priority and level != KillSwitchLevel.NORMAL:
            logger.warning(
                f"Kill switch already at {self._state.level.value}, "
                f"ignoring escalation to {level.value}"
            )
            return

        self._history.append(self._state)
        self._state = KillSwitchState(
            level=level,
            triggered_at=datetime.now(timezone.utc),
            triggered_by=triggered_by,
            reason=reason,
        )

        logger.critical(
            f"KILL SWITCH ESCALATED to {level.value}",
            extra={
                "kill_switch_level": level.value,
                "kill_switch_reason": reason,
                "kill_switch_triggered_by": triggered_by,
                "event_type": "KILL_SWITCH_ESCALATION",
            },
        )
        self._notify()

    def reset(self, reason: str, triggered_by: str = "system") -> None:
        """Reset kill switch to NORMAL."""
        if self._state.level == KillSwitchLevel.NORMAL:
            return

        self._history.append(self._state)
        self._state = KillSwitchState(
            level=KillSwitchLevel.NORMAL,
            triggered_at=datetime.now(timezone.utc),
            triggered_by=triggered_by,
            reason=f"Reset: {reason}",
        )

        logger.info(
            "KILL SWITCH RESET to NORMAL",
            extra={
                "kill_switch_level": "NORMAL",
                "kill_switch_reason": reason,
                "event_type": "KILL_SWITCH_RESET",
            },
        )
        self._notify()

    def check_risk_limits(self, daily_pnl: float, max_drawdown: float) -> None:
        """Check risk limits and escalate if breached."""
        risk = settings.risk

        # Level 3: Flatten all
        if daily_pnl <= -risk.daily_loss_limit_inr or max_drawdown >= risk.max_drawdown_inr:
            self.escalate(
                KillSwitchLevel.FLATTEN_ALL,
                f"Daily loss {daily_pnl} >= limit {-risk.daily_loss_limit_inr} "
                f"or drawdown {max_drawdown} >= max {risk.max_drawdown_inr}",
                "risk_manager",
            )
            return

        # Level 2: Cancel pending
        if daily_pnl <= -risk.daily_loss_limit_inr * 0.75:
            self.escalate(
                KillSwitchLevel.CANCEL_PENDING,
                f"Daily loss {daily_pnl} >= 75% of limit",
                "risk_manager",
            )
            return

        # Level 1: Pause
        if daily_pnl <= -risk.daily_loss_limit_inr * 0.5:
            self.escalate(
                KillSwitchLevel.PAUSE,
                f"Daily loss {daily_pnl} >= 50% of limit",
                "risk_manager",
            )

    def get_history(self) -> List[Dict[str, Any]]:
        """Get kill switch history as dicts."""
        return [
            {
                "level": h.level.value,
                "triggered_at": h.triggered_at.isoformat() if h.triggered_at else None,
                "triggered_by": h.triggered_by,
                "reason": h.reason,
            }
            for h in self._history
        ]


# Singleton instance
kill_switch_manager = KillSwitchManager()
