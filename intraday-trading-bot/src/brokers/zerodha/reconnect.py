"""RC-10D: Reconnect manager for WebSocket and REST session recovery.

ReconnectManager owns the reconnect task and enforces:
  - Bounded attempts (configurable max)
  - Exponential back-off with jitter
  - Shutdown-safe cancellation (asyncio.CancelledError is propagated)
  - Post-reconnect reconciliation trigger
"""
from __future__ import annotations

import asyncio
import random
from datetime import datetime, timezone
from typing import Awaitable, Callable, Optional

from src.core.logging import logger


class ReconnectManager:
    """Manages bounded reconnect attempts with exponential back-off.

    Parameters
    ----------
    name:
        Descriptive name for logging (e.g. "zerodha_websocket").
    reconnect_fn:
        Async function to call on each reconnect attempt.
        Should raise an exception on failure, return on success.
    on_reconnect_success:
        Optional async callback invoked after a successful reconnect.
        Typically triggers reconciliation.
    max_attempts:
        Maximum reconnect attempts before giving up.
    base_backoff:
        Base wait interval in seconds (doubles each attempt, with jitter).
    """

    def __init__(
        self,
        name: str,
        reconnect_fn: Callable[[], Awaitable[None]],
        *,
        on_reconnect_success: Optional[Callable[[], Awaitable[None]]] = None,
        max_attempts: int = 10,
        base_backoff: float = 2.0,
    ) -> None:
        self._name = name
        self._reconnect_fn = reconnect_fn
        self._on_success = on_reconnect_success
        self._max_attempts = max_attempts
        self._base_backoff = base_backoff

        self._attempt_count: int = 0
        self._last_reconnect: Optional[datetime] = None
        self._task: Optional[asyncio.Task] = None
        self._running = False

    # ── Public API ─────────────────────────────────────────────────────────

    def start(self) -> None:
        """Launch the reconnect loop as a background task."""
        if self._task and not self._task.done():
            return  # Already running
        self._running = True
        self._task = asyncio.create_task(
            self._reconnect_loop(), name=f"reconnect_{self._name}"
        )

    async def stop(self) -> None:
        """Cancel the reconnect task and wait for it to finish."""
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
        self._task = None

    @property
    def attempt_count(self) -> int:
        return self._attempt_count

    @property
    def is_running(self) -> bool:
        return self._task is not None and not self._task.done()

    # ── Internal ───────────────────────────────────────────────────────────

    async def _reconnect_loop(self) -> None:
        self._attempt_count = 0

        while self._running and self._attempt_count < self._max_attempts:
            self._attempt_count += 1
            backoff = self._base_backoff * (2 ** (self._attempt_count - 1))
            jitter = random.uniform(0, backoff * 0.2)
            wait = min(backoff + jitter, 60.0)  # cap at 60s

            logger.info(
                f"Reconnect attempt {self._attempt_count}/{self._max_attempts} "
                f"for {self._name!r} in {wait:.1f}s",
                extra={
                    "event_type": "BROKER_RECONNECT_ATTEMPT",
                    "component_name": self._name,
                    "attempt": self._attempt_count,
                    "wait_seconds": round(wait, 2),
                },
            )
            await asyncio.sleep(wait)

            try:
                await self._reconnect_fn()
                self._last_reconnect = datetime.now(timezone.utc)
                logger.info(
                    f"Reconnect succeeded for {self._name!r} "
                    f"(attempt {self._attempt_count})",
                    extra={
                        "event_type": "BROKER_RECONNECT_SUCCESS",
                        "component_name": self._name,
                        "attempt": self._attempt_count,
                    },
                )
                # Trigger post-reconnect reconciliation
                if self._on_success:
                    try:
                        await self._on_success()
                    except Exception as exc:
                        logger.warning(
                            f"Post-reconnect callback failed: {exc}",
                            extra={"event_type": "BROKER_RECONNECT_CALLBACK_ERROR"},
                        )
                self._running = False
                return

            except asyncio.CancelledError:
                logger.info(f"Reconnect task cancelled for {self._name!r}")
                raise
            except Exception as exc:
                logger.warning(
                    f"Reconnect attempt {self._attempt_count} failed for "
                    f"{self._name!r}: {type(exc).__name__}",
                    extra={
                        "event_type": "BROKER_RECONNECT_FAILURE",
                        "component_name": self._name,
                        "attempt": self._attempt_count,
                        "error": type(exc).__name__,
                    },
                )

        if self._attempt_count >= self._max_attempts:
            logger.error(
                f"Reconnect exhausted for {self._name!r} after "
                f"{self._attempt_count} attempts",
                extra={
                    "event_type": "BROKER_RECONNECT_EXHAUSTED",
                    "component_name": self._name,
                    "attempts": self._attempt_count,
                },
            )
