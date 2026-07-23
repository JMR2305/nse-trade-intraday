"""AnnouncementPoller — background asyncio task that drives AnnouncementIntelligenceService.

Lifecycle:
  await poller.start(interval_seconds=60)  # starts background task
  await poller.stop()                       # cancels task, waits for cleanup

Error handling: any exception in poll_and_classify() is caught, logged as
WARNING, and the poller continues to the next interval.  The asyncio event
loop is never blocked.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Optional

from market_intelligence.announcements import AnnouncementIntelligenceService

logger = logging.getLogger(__name__)


class AnnouncementPoller:
    """Background asyncio task wrapper for AnnouncementIntelligenceService.

    Not thread-safe — must run within a single event loop.
    """

    def __init__(
        self,
        service: AnnouncementIntelligenceService,
        engine: Optional[object] = None,
    ) -> None:
        self._service = service
        self._engine = engine
        self._task: Optional[asyncio.Task] = None  # type: ignore[type-arg]
        self._running = False

    async def start(self, interval_seconds: int = 60) -> None:
        """Start the background polling task."""
        if self._running:
            logger.debug("AnnouncementPoller already running")
            return
        self._running = True
        self._task = asyncio.create_task(
            self._poll_loop(interval_seconds), name="announcement_poller"
        )
        logger.info("AnnouncementPoller started (interval=%ds)", interval_seconds)

    async def stop(self) -> None:
        """Cancel the background task and wait for it to finish."""
        self._running = False
        if self._task is not None and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("AnnouncementPoller stopped")

    async def _poll_loop(self, interval_seconds: int) -> None:
        while self._running:
            try:
                count = await self._service.poll_and_classify(None)
                if count:
                    logger.debug("Polled %d new announcements", count)
                self._service.clear_expired()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.warning("AnnouncementPoller poll error: %s", exc)
            await asyncio.sleep(interval_seconds)
