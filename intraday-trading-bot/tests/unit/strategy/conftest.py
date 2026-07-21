"""Shared fixtures for strategy tests."""
import asyncio
import pytest


@pytest.fixture(autouse=True)
async def cancel_stray_tasks():
    """Cancel any lingering background tasks after each test.

    StrategyRuntime creates a permanent background task via
    asyncio.create_task(self._run_loop()). If a test ends without
    calling runtime.stop(), the task keeps running and the event
    loop never closes. This fixture ensures clean test isolation.
    """
    yield
    tasks = [t for t in asyncio.all_tasks() if not t.done() and t != asyncio.current_task()]
    for t in tasks:
        t.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)
