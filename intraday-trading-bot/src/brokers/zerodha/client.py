"""RC-10D: Zerodha HTTP client with retry policy.

ZerodhaHttpClient wraps KiteConnect with:
  - asyncio-safe synchronous-to-thread execution (KiteConnect uses requests)
  - Exponential back-off + jitter for read-only (GET) operations
  - NO blind retry for order placement — timeouts enter reconciliation
  - Rate limiter integration
  - Raw kiteconnect exceptions translated to domain exceptions

Safety:
  - Order placement exceptions are never automatically retried
  - BrokerTimeoutError on placement signals the correlation to be UNCERTAIN
  - Credentials are never included in logged exception messages
"""
from __future__ import annotations

import asyncio
import random
import time
from typing import Any, Callable, Optional

from src.brokers.exceptions import (
    BrokerAuthenticationError,
    BrokerConnectionError,
    BrokerError,
    BrokerProtocolError,
    BrokerRateLimitError,
    BrokerSessionExpiredError,
    BrokerTimeoutError,
    BrokerUnavailableError,
    BrokerValidationError,
)
from src.brokers.zerodha.rate_limiter import BrokerRateLimiter
from src.core.logging import logger


class ZerodhaHttpClient:
    """Async wrapper around the synchronous KiteConnect client.

    KiteConnect is built on the requests library (synchronous).  All calls
    are delegated to asyncio.get_event_loop().run_in_executor() to avoid
    blocking the event loop.

    Parameters
    ----------
    kite:
        A configured KiteConnect instance (access token already set).
    rate_limiter:
        BrokerRateLimiter to enforce per-category rate limits.
    timeout_seconds:
        Per-request timeout in seconds.
    maximum_retries:
        Maximum retry attempts for read-only operations.
    retry_backoff_seconds:
        Base back-off interval between retries (exponential with jitter).
    """

    def __init__(
        self,
        kite: Any,
        rate_limiter: BrokerRateLimiter,
        *,
        timeout_seconds: float = 10.0,
        maximum_retries: int = 3,
        retry_backoff_seconds: float = 1.0,
    ) -> None:
        self._kite = kite
        self._rate_limiter = rate_limiter
        self._timeout = timeout_seconds
        self._max_retries = maximum_retries
        self._backoff = retry_backoff_seconds

    # ── Order API (NO retry on placement) ─────────────────────────────────

    async def place_order(self, **params: Any) -> str:
        """Place a single order. Returns broker_order_id.

        NOT retried on timeout — caller must mark correlation as UNCERTAIN.
        Raises immediately on failure.
        """
        await self._rate_limiter.acquire_order()
        try:
            order_id = await self._run(self._kite.place_order, **params)
            return str(order_id)
        except BrokerError:
            raise
        except Exception as exc:
            raise self._translate(exc, operation="place_order") from exc

    async def modify_order(self, **params: Any) -> str:
        """Modify an existing order. Returns broker_order_id."""
        await self._rate_limiter.acquire_order()
        try:
            order_id = await self._run(self._kite.modify_order, **params)
            return str(order_id)
        except BrokerError:
            raise
        except Exception as exc:
            raise self._translate(exc, operation="modify_order") from exc

    async def cancel_order(self, variety: str, order_id: str) -> str:
        """Cancel an order. Returns broker_order_id."""
        await self._rate_limiter.acquire_order()
        try:
            result = await self._run(self._kite.cancel_order, variety=variety, order_id=order_id)
            return str(result)
        except BrokerError:
            raise
        except Exception as exc:
            raise self._translate(exc, operation="cancel_order") from exc

    # ── Order book / trades (retried on transient failure) ─────────────────

    async def get_orders(self) -> list:
        """Fetch today's order book (retried)."""
        return await self._retried_account_call(self._kite.orders)

    async def get_trades(self) -> list:
        """Fetch today's trade book (retried)."""
        return await self._retried_account_call(self._kite.trades)

    async def get_order_history(self, order_id: str) -> list:
        """Fetch history for a specific order (retried)."""
        return await self._retried_account_call(
            self._kite.order_history, order_id=order_id
        )

    async def get_order_trades(self, order_id: str) -> list:
        """Fetch trades for a specific order (retried)."""
        return await self._retried_account_call(
            self._kite.order_trades, order_id=order_id
        )

    # ── Account / position data (retried) ─────────────────────────────────

    async def get_positions(self) -> dict:
        """Fetch current positions (retried)."""
        return await self._retried_account_call(self._kite.positions)

    async def get_holdings(self) -> list:
        """Fetch delivery holdings (retried)."""
        return await self._retried_account_call(self._kite.holdings)

    async def get_margins(self, segment: Optional[str] = None) -> dict:
        """Fetch margins (retried)."""
        if segment:
            return await self._retried_account_call(self._kite.margins, segment=segment)
        return await self._retried_account_call(self._kite.margins)

    async def get_profile(self) -> dict:
        """Fetch user profile (retried) — used for session validation."""
        return await self._retried_account_call(self._kite.profile)

    # ── Market data (retried) ──────────────────────────────────────────────

    async def get_instruments(self, exchange: Optional[str] = None) -> list:
        """Fetch instrument master (retried, slow — rate limited)."""
        await self._rate_limiter.acquire_historical()
        if exchange:
            raw = await self._run(self._kite.instruments, exchange=exchange)
        else:
            raw = await self._run(self._kite.instruments)
        return raw

    # ── Internal helpers ───────────────────────────────────────────────────

    async def _retried_account_call(self, fn: Callable, **kwargs: Any) -> Any:
        """Execute fn with retries for transient errors (account/read-only ops)."""
        await self._rate_limiter.acquire_account()
        last_exc: Optional[Exception] = None
        for attempt in range(1, self._max_retries + 2):
            try:
                return await self._run(fn, **kwargs)
            except (BrokerRateLimitError,) as exc:
                raise  # Never retry rate-limit errors
            except (BrokerSessionExpiredError, BrokerAuthenticationError) as exc:
                raise  # Never retry auth errors
            except (BrokerConnectionError, BrokerTimeoutError, BrokerUnavailableError) as exc:
                last_exc = exc
                if attempt <= self._max_retries:
                    wait = self._backoff * (2 ** (attempt - 1)) + random.uniform(0, 0.5)
                    logger.warning(
                        f"Retrying {fn.__name__} (attempt {attempt}/{self._max_retries})",
                        extra={
                            "event_type": "BROKER_RETRY",
                            "attempt": attempt,
                            "wait_seconds": round(wait, 2),
                            "error": type(exc).__name__,
                        },
                    )
                    await asyncio.sleep(wait)
            except BrokerError as exc:
                raise  # Other broker errors not retried
        raise last_exc  # type: ignore[misc]

    async def _run(self, fn: Callable, **kwargs: Any) -> Any:
        """Run a synchronous kiteconnect function in a thread pool."""
        loop = asyncio.get_event_loop()
        try:
            result = await asyncio.wait_for(
                loop.run_in_executor(None, lambda: fn(**kwargs)),
                timeout=self._timeout,
            )
            return result
        except asyncio.TimeoutError as exc:
            raise BrokerTimeoutError(
                f"Request to {fn.__name__!r} timed out after {self._timeout}s"
            ) from exc

    @staticmethod
    def _translate(exc: Exception, *, operation: str) -> BrokerError:
        """Convert a kiteconnect exception to a domain exception.

        Credential values are NEVER included in the translated message.
        """
        exc_type = type(exc).__name__
        msg_raw = str(exc)

        # Never echo tokens/secrets in error messages
        for redacted_word in ("api_secret", "access_token", "request_token", "password"):
            if redacted_word in msg_raw.lower():
                msg_raw = "[REDACTED]"
                break

        try:
            # kiteconnect raises specific exception types
            from kiteconnect import exceptions as ke
            if isinstance(exc, ke.TokenException):
                return BrokerSessionExpiredError(f"Session expired during {operation}")
            if isinstance(exc, ke.PermissionException):
                return BrokerAuthenticationError(f"Permission denied during {operation}")
            if isinstance(exc, ke.NetworkException):
                return BrokerConnectionError(f"Network error during {operation}: {exc_type}")
            if isinstance(exc, ke.DataException):
                return BrokerProtocolError(f"Malformed response during {operation}: {exc_type}")
            if isinstance(exc, ke.InputException):
                return BrokerValidationError(f"Invalid input during {operation}: {msg_raw}")
            if isinstance(exc, ke.OrderException):
                from src.brokers.exceptions import BrokerOrderRejectedError
                return BrokerOrderRejectedError(f"Order rejected during {operation}: {msg_raw}")
            if isinstance(exc, ke.GeneralException):
                return BrokerUnavailableError(f"Broker unavailable during {operation}")
        except ImportError:
            pass

        return BrokerProtocolError(f"Broker error during {operation}: {exc_type}")
