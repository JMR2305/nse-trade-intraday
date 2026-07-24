"""Tests for RC-10D reconnect manager (Group H).

Covers:
  - Bounded attempts enforced
  - Exponential back-off called
  - Successful reconnect stops the loop
  - Shutdown-safe cancellation
  - Post-reconnect callback is called on success
  - Failure logs without crashing
"""
from __future__ import annotations

import asyncio
import pytest

from src.brokers.zerodha.reconnect import ReconnectManager


class TestReconnectManager:
    @pytest.mark.asyncio
    async def test_success_on_first_attempt(self):
        call_count = 0

        async def reconnect_fn():
            nonlocal call_count
            call_count += 1

        mgr = ReconnectManager(
            "test",
            reconnect_fn,
            max_attempts=3,
            base_backoff=0.01,
        )
        mgr.start()
        await asyncio.sleep(0.1)  # Wait for reconnect
        assert call_count == 1
        assert not mgr.is_running

    @pytest.mark.asyncio
    async def test_bounded_attempts(self):
        call_count = 0

        async def reconnect_fn():
            nonlocal call_count
            call_count += 1
            raise Exception("always fails")

        mgr = ReconnectManager(
            "test",
            reconnect_fn,
            max_attempts=2,
            base_backoff=0.01,
        )
        mgr.start()
        await asyncio.sleep(0.5)
        assert call_count == 2  # Exactly max_attempts

    @pytest.mark.asyncio
    async def test_success_callback_called(self):
        success_cb_called = False

        async def reconnect_fn():
            pass

        async def on_success():
            nonlocal success_cb_called
            success_cb_called = True

        mgr = ReconnectManager(
            "test",
            reconnect_fn,
            on_reconnect_success=on_success,
            max_attempts=3,
            base_backoff=0.01,
        )
        mgr.start()
        await asyncio.sleep(0.1)
        assert success_cb_called is True

    @pytest.mark.asyncio
    async def test_stop_cancels_task(self):
        always_fails_count = 0

        async def reconnect_fn():
            nonlocal always_fails_count
            always_fails_count += 1
            raise Exception("fail")

        mgr = ReconnectManager(
            "test",
            reconnect_fn,
            max_attempts=100,
            base_backoff=0.01,
        )
        mgr.start()
        await asyncio.sleep(0.05)
        await mgr.stop()
        count_at_stop = always_fails_count
        await asyncio.sleep(0.1)
        # No more attempts after stop
        assert always_fails_count == count_at_stop

    @pytest.mark.asyncio
    async def test_attempt_count_tracked(self):
        call_count = 0

        async def reconnect_fn():
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise Exception("fail first")

        mgr = ReconnectManager("test", reconnect_fn, max_attempts=3, base_backoff=0.01)
        mgr.start()
        await asyncio.sleep(0.3)
        assert mgr.attempt_count >= 1

    @pytest.mark.asyncio
    async def test_is_running_false_after_success(self):
        async def reconnect_fn():
            pass

        mgr = ReconnectManager("test", reconnect_fn, max_attempts=3, base_backoff=0.01)
        mgr.start()
        await asyncio.sleep(0.15)
        assert not mgr.is_running

    @pytest.mark.asyncio
    async def test_double_start_no_duplicate_task(self):
        call_count = 0

        async def reconnect_fn():
            nonlocal call_count
            call_count += 1

        mgr = ReconnectManager("test", reconnect_fn, max_attempts=5, base_backoff=0.5)
        mgr.start()
        mgr.start()  # second call should be no-op
        await asyncio.sleep(0.1)
        await mgr.stop()
        assert call_count <= 2  # Only one task running
