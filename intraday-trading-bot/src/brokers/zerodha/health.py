"""RC-10D: Broker health tracker.

BrokerHealthTracker maintains a mutable health snapshot updated by other
components as they receive successes, failures, reconnects, rate limits, etc.

Components call the update_* methods; callers read get_health() for a
frozen snapshot.  is_ready() is checked by ExecutionService before any order.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Optional

from src.brokers.contracts import BrokerHealth, BrokerHealthStatus
from src.core.logging import logger


class BrokerHealthTracker:
    """Thread-safe (asyncio-lock-protected) broker health state.

    Usage
    -----
        tracker = BrokerHealthTracker(paper_mode=True)
        tracker.mark_authenticated()
        tracker.mark_rest_success()
        health = tracker.get_health()
        if not health.is_ready:
            raise ...
    """

    def __init__(self, *, paper_mode: bool = True) -> None:
        self._lock = asyncio.Lock()
        self._paper_mode = paper_mode

        # Mutable state
        self._authenticated: bool = False
        self._session_valid: bool = False
        self._rest_reachable: bool = False
        self._websocket_connected: bool = False
        self._last_successful_request: Optional[datetime] = None
        self._last_broker_event: Optional[datetime] = None
        self._reconnect_count: int = 0
        self._rate_limited: bool = False
        self._unresolved_orders: int = 0
        self._reconciliation_status: Optional[str] = None
        self._failure_reason: Optional[str] = None
        # Token expiry tracking
        self._token_expiry_minutes: Optional[float] = None
        self._token_expiry_warning: bool = False

    # ── Update methods (called by gateways / websocket / session manager) ──

    async def mark_authenticated(self) -> None:
        async with self._lock:
            self._authenticated = True
            self._session_valid = True
            self._failure_reason = None

    async def mark_session_invalid(self, reason: Optional[str] = None) -> None:
        async with self._lock:
            self._authenticated = False
            self._session_valid = False
            self._failure_reason = reason

    async def mark_rest_success(self) -> None:
        async with self._lock:
            self._rest_reachable = True
            self._last_successful_request = datetime.now(timezone.utc)
            self._rate_limited = False

    async def mark_rest_failure(self, reason: Optional[str] = None) -> None:
        async with self._lock:
            self._rest_reachable = False
            self._failure_reason = reason

    async def mark_websocket_connected(self) -> None:
        async with self._lock:
            self._websocket_connected = True
            self._last_broker_event = datetime.now(timezone.utc)

    async def mark_websocket_disconnected(self) -> None:
        async with self._lock:
            self._websocket_connected = False
            self._reconnect_count += 1

    async def mark_rate_limited(self) -> None:
        async with self._lock:
            self._rate_limited = True

    async def mark_broker_event(self) -> None:
        async with self._lock:
            self._last_broker_event = datetime.now(timezone.utc)

    async def set_unresolved_orders(self, count: int) -> None:
        async with self._lock:
            self._unresolved_orders = count

    async def set_reconciliation_status(self, status: str) -> None:
        async with self._lock:
            self._reconciliation_status = status

    async def update_token_expiry_minutes(self, minutes_remaining: float) -> None:
        """Update the expiry countdown for a healthy (non-warning) session.

        Only updates the minutes field; does NOT set the warning flag.
        Call this on every healthy poll iteration so the UI countdown stays fresh.
        """
        async with self._lock:
            self._token_expiry_minutes = minutes_remaining

    async def mark_token_expiry_warning(
        self,
        minutes_remaining: float,
        *,
        is_expired: bool = False,
    ) -> None:
        """Record that the session token is approaching or past expiry.

        Sets ``token_expiry_warning=True``.  Call only when the token is within
        the configured warning window or already expired.  For healthy sessions
        (outside the warning window) use ``update_token_expiry_minutes()``
        instead so the warning flag is not set spuriously.

        Parameters
        ----------
        minutes_remaining:
            Minutes until the token expires (negative = already expired).
        is_expired:
            True when the token has already crossed the expiry boundary.
        """
        async with self._lock:
            self._token_expiry_minutes = minutes_remaining
            self._token_expiry_warning = True
            if is_expired:
                # Treat an expired token the same as an invalid session so
                # health.is_ready and order-gateway._assert_health() both block
                # new live orders immediately.
                self._authenticated = False
                self._session_valid = False
                self._failure_reason = "Token expired — re-authenticate via daily OAuth flow"

    async def clear_token_expiry_warning(self) -> None:
        """Clear the expiry warning after a fresh token is installed."""
        async with self._lock:
            self._token_expiry_minutes = None
            self._token_expiry_warning = False

    # ── Read methods ───────────────────────────────────────────────────────

    def get_health(self) -> BrokerHealth:
        """Return a frozen snapshot of current health.  Non-blocking."""
        status = self._compute_status()
        return BrokerHealth(
            status=status,
            authenticated=self._authenticated,
            session_valid=self._session_valid,
            rest_reachable=self._rest_reachable,
            websocket_connected=self._websocket_connected,
            paper_mode=self._paper_mode,
            last_successful_request=self._last_successful_request,
            last_broker_event=self._last_broker_event,
            reconnect_count=self._reconnect_count,
            rate_limited=self._rate_limited,
            unresolved_orders=self._unresolved_orders,
            reconciliation_status=self._reconciliation_status,
            failure_reason=self._failure_reason,
            token_expiry_minutes=self._token_expiry_minutes,
            token_expiry_warning=self._token_expiry_warning,
            checked_at=datetime.now(timezone.utc),
        )

    def is_ready(self) -> bool:
        """True when the broker can accept new orders.

        In paper mode: always True (no live checks needed).
        In live mode: session must be valid and REST must be reachable.
        """
        if self._paper_mode:
            return True
        return (
            self._authenticated
            and self._session_valid
            and self._rest_reachable
        )

    def is_live(self) -> bool:
        """True when running in live (non-paper) mode."""
        return not self._paper_mode

    # ── Internal ───────────────────────────────────────────────────────────

    def _compute_status(self) -> BrokerHealthStatus:
        if self._paper_mode:
            return BrokerHealthStatus.HEALTHY
        if not self._authenticated or not self._session_valid:
            return BrokerHealthStatus.DOWN
        if not self._rest_reachable:
            return BrokerHealthStatus.DOWN
        if self._rate_limited or not self._websocket_connected:
            return BrokerHealthStatus.DEGRADED
        if self._unresolved_orders > 0:
            return BrokerHealthStatus.DEGRADED
        return BrokerHealthStatus.HEALTHY
