"""RC-10D: Proactive Zerodha token expiry monitor.

TokenExpiryMonitor runs as a background asyncio task and calls
``ZerodhaAdapter.check_token_expiry()`` on a regular interval.  When expiry is
detected within the configured warning window it logs CRITICAL, sends an alert,
and signals the adapter to fall back to paper mode for any new order placement.

Design rules
------------
- Paper mode only when token is expired OR within warning window and degradation
  is requested.  The monitor never touches the broker session directly.
- The monitor stops cleanly when ``stop()`` is awaited (e.g. on server shutdown).
- All exceptions inside the poll loop are caught and logged; the monitor never
  crashes the event loop.
- Never raises from ``start()`` or ``stop()``.
"""
from __future__ import annotations

import asyncio
from typing import Optional

from src.core.logging import logger

# Default: poll every 60 seconds
_DEFAULT_POLL_INTERVAL_SECONDS: int = 60
# Default: warn when less than 30 minutes remain
_DEFAULT_WARNING_LEAD_MINUTES: int = 30


class TokenExpiryMonitor:
    """Background asyncio monitor for Zerodha token expiry.

    Parameters
    ----------
    adapter:
        ZerodhaAdapter instance to check and degrade on expiry.
    poll_interval_seconds:
        How often to probe the session expiry clock.  Default 60 s.
    warning_lead_minutes:
        How many minutes before midnight IST to trigger the warning alert and
        paper-mode fallback.  Default 30 min.
    """

    def __init__(
        self,
        adapter,  # ZerodhaAdapter (avoid circular import)
        *,
        poll_interval_seconds: int = _DEFAULT_POLL_INTERVAL_SECONDS,
        warning_lead_minutes: int = _DEFAULT_WARNING_LEAD_MINUTES,
    ) -> None:
        self._adapter = adapter
        self._poll_interval = poll_interval_seconds
        self._warning_lead = warning_lead_minutes
        self._task: Optional[asyncio.Task] = None
        self._running = False

    def start(self) -> None:
        """Schedule the background poll task.  Safe to call multiple times."""
        if self._task is not None and not self._task.done():
            return  # already running
        self._running = True
        self._task = asyncio.create_task(
            self._poll_loop(), name="zerodha_token_expiry_monitor"
        )
        logger.info(
            "TokenExpiryMonitor started",
            extra={
                "event_type": "TOKEN_EXPIRY_MONITOR_STARTED",
                "poll_interval_s": self._poll_interval,
                "warning_lead_min": self._warning_lead,
            },
        )

    async def stop(self) -> None:
        """Cancel the background poll task and wait for it to finish."""
        self._running = False
        if self._task is not None and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info(
            "TokenExpiryMonitor stopped",
            extra={"event_type": "TOKEN_EXPIRY_MONITOR_STOPPED"},
        )

    # ── Internal ───────────────────────────────────────────────────────────

    async def _poll_loop(self) -> None:
        while self._running:
            try:
                await self._adapter.check_token_expiry(
                    warning_lead_minutes=self._warning_lead
                )
            except Exception as exc:  # noqa: BLE001 — monitor must never crash
                logger.warning(
                    f"TokenExpiryMonitor: poll error ({type(exc).__name__}): {exc}",
                    extra={"event_type": "TOKEN_EXPIRY_MONITOR_POLL_ERROR"},
                )
            await asyncio.sleep(self._poll_interval)
