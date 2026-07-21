"""
Kill Switch — emergency safety mechanism.

KillSwitch manages the activation and deactivation of an emergency trading halt.
It maintains an audit trail of all activation/deactivation events.
"""

from __future__ import annotations

from typing import Optional, List
from datetime import datetime, timezone
from dataclasses import dataclass, field
import asyncio
import logging

from .contracts import RiskSeverity

logger = logging.getLogger(__name__)


@dataclass
class KillSwitchEvent:
    """Record of a kill switch state change."""

    event_type: str          # "ACTIVATED" | "DEACTIVATED"
    timestamp: datetime
    reason: Optional[str] = None
    triggered_by: Optional[str] = None

    def __repr__(self) -> str:
        return (
            f"KillSwitchEvent(type={self.event_type!r}, "
            f"ts={self.timestamp.isoformat()!r}, reason={self.reason!r})"
        )


class KillSwitch:
    """Emergency kill switch that halts all new order submissions.

    When active, the RiskEngine rejects all incoming orders with a FATAL violation.
    The kill switch maintains a full audit trail of all state changes.

    Thread-safe via asyncio.Lock.
    """

    def __init__(self) -> None:
        self._active: bool = False
        self._reason: Optional[str] = None
        self._triggered_by: Optional[str] = None
        self._events: List[KillSwitchEvent] = []
        self._lock: asyncio.Lock = asyncio.Lock()

    @property
    def active(self) -> bool:
        """Whether the kill switch is currently engaged."""
        return self._active

    @property
    def reason(self) -> Optional[str]:
        """Reason for current kill switch activation, or None if inactive."""
        return self._reason

    @property
    def triggered_by(self) -> Optional[str]:
        """Who triggered the kill switch, or None if inactive."""
        return self._triggered_by

    @property
    def events(self) -> List[KillSwitchEvent]:
        """Read-only copy of the audit trail."""
        return list(self._events)

    async def activate(
        self,
        reason: str,
        triggered_by: Optional[str] = None,
    ) -> None:
        """Engage the kill switch.

        Args:
            reason: Human-readable reason for activation.
            triggered_by: Who or what triggered the activation.
        """
        async with self._lock:
            if not self._active:
                self._active = True
                self._reason = reason
                self._triggered_by = triggered_by
                event = KillSwitchEvent(
                    event_type="ACTIVATED",
                    timestamp=datetime.now(timezone.utc),
                    reason=reason,
                    triggered_by=triggered_by,
                )
                self._events.append(event)
                logger.critical(
                    f"Kill switch ACTIVATED: reason={reason!r}, triggered_by={triggered_by!r}"
                )

    async def deactivate(
        self,
        triggered_by: Optional[str] = None,
    ) -> None:
        """Disengage the kill switch, allowing new orders.

        Args:
            triggered_by: Who authorised the deactivation.
        """
        async with self._lock:
            if self._active:
                self._active = False
                old_reason = self._reason
                self._reason = None
                self._triggered_by = None
                event = KillSwitchEvent(
                    event_type="DEACTIVATED",
                    timestamp=datetime.now(timezone.utc),
                    reason=old_reason,
                    triggered_by=triggered_by,
                )
                self._events.append(event)
                logger.info(
                    f"Kill switch DEACTIVATED by {triggered_by!r}; "
                    f"was active with reason={old_reason!r}"
                )

    def is_active(self) -> bool:
        """Synchronous check — safe for non-critical reads."""
        return self._active

    def reset_events(self) -> None:
        """Clear the audit trail (for testing only)."""
        self._events.clear()
