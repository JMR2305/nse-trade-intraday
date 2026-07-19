"""Read-only Zerodha market-data adapter.

Uses official Kite Connect / KiteTicker concepts only.
No trading or order operations.  Credentials injected at construction.
External library imports are isolated inside methods.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from src.market_data.contracts import CompletedBar, MarketDepthLevel, Tick
from src.market_data.provider import MarketDataProvider, TickHandler


class ZerodhaMarketDataProvider(MarketDataProvider):
    """Read-only adapter for Zerodha Kite Connect market data.

    Args:
        api_key: Kite Connect API key
        access_token: valid access token
    """

    def __init__(self, api_key: str, access_token: str) -> None:
        self._api_key = api_key
        self._access_token = access_token
        self._kite: Any | None = None
        self._ticker: Any | None = None
        self._tick_handler: TickHandler | None = None
        self._loop = None
        self._connected = False

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------
    async def connect(self) -> None:
        """Initialise KiteTicker connection (lazy import)."""
        # Isolate external import
        try:
            from kiteconnect import KiteTicker
        except ImportError as exc:
            raise RuntimeError(
                "kiteconnect library is required for ZerodhaMarketDataProvider"
            ) from exc

        self._ticker = KiteTicker(self._api_key, self._access_token)
        self._ticker.on_ticks = self._on_ticks_wrapper
        self._ticker.on_connect = self._on_connect_wrapper
        self._ticker.on_close = self._on_close_wrapper
        self._ticker.on_error = self._on_error_wrapper
        import asyncio
        self._loop = asyncio.get_running_loop()
        self._ticker.connect(threaded=True)
        self._connected = True

    async def disconnect(self) -> None:
        """Close the WebSocket connection."""
        if self._ticker is not None:
            self._ticker.close()
        self._connected = False
        self._ticker = None
        self._loop = None

    # ------------------------------------------------------------------
    # Subscription
    # ------------------------------------------------------------------
    async def subscribe(self, tokens: list[int]) -> None:
        if not self._connected or self._ticker is None:
            raise RuntimeError("not connected")
        self._ticker.subscribe(tokens)

    async def unsubscribe(self, tokens: list[int]) -> None:
        if not self._connected or self._ticker is None:
            raise RuntimeError("not connected")
        self._ticker.unsubscribe(tokens)

    def set_tick_handler(self, callback: TickHandler) -> None:
        self._tick_handler = callback

    # ------------------------------------------------------------------
    # Historical data
    # ------------------------------------------------------------------
    async def get_historical_bars(
        self,
        token: int,
        from_dt: datetime,
        to_dt: datetime,
        interval: str = "minute",
    ) -> list[CompletedBar]:
        """Fetch historical bars via Kite Connect REST API.

        Converts KiteConnect response into internal CompletedBar contracts.
        """
        self._ensure_kite_connect()
        # Kite Connect expects strings: "YYYY-MM-DD HH:MM:SS"
        from_str = from_dt.strftime("%Y-%m-%d %H:%M:%S")
        to_str = to_dt.strftime("%Y-%m-%d %H:%M:%S")

        raw = self._kite.historical_data(token, from_str, to_str, interval)
        bars: list[CompletedBar] = []
        for row in raw:
            # Kite returns: date, open, high, low, close, volume
            ts = row["date"]
            if isinstance(ts, str):
                ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            if ts.tzinfo is None:
                # Kite historical data is in IST; attach Asia/Kolkata
                from zoneinfo import ZoneInfo
                ts = ts.replace(tzinfo=ZoneInfo("Asia/Kolkata"))
            bars.append(
                CompletedBar(
                    instrument_token=token,
                    timestamp=ts,
                    open=Decimal(str(row["open"])),
                    high=Decimal(str(row["high"])),
                    low=Decimal(str(row["low"])),
                    close=Decimal(str(row["close"])),
                    volume=int(row["volume"]),
                    oi=None,
                    is_backfilled=True,
                    source="backfill",
                )
            )
        return bars

    # ------------------------------------------------------------------
    # Instruments
    # ------------------------------------------------------------------
    async def get_instruments(self, exchange: str = "NSE") -> list[dict[str, Any]]:
        """Fetch instrument master for an exchange."""
        self._ensure_kite_connect()
        return self._kite.instruments(exchange)

    # ------------------------------------------------------------------
    # Health
    # ------------------------------------------------------------------
    async def health(self) -> dict[str, Any]:
        """Check provider health via Kite Connect profile endpoint.

        Returns degraded/unhealthy status on any exception.
        """
        if not self._connected:
            return {
                "status": "unhealthy",
                "details": "WebSocket not connected",
                "provider": "zerodha",
            }
        try:
            self._ensure_kite_connect()
            profile = self._kite.profile()
            return {
                "status": "healthy",
                "details": f"user={profile.get('user_name', 'unknown')}",
                "provider": "zerodha",
            }
        except Exception as exc:
            return {
                "status": "degraded",
                "details": str(exc),
                "provider": "zerodha",
            }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _ensure_kite_connect(self) -> None:
        """Lazy initialise the KiteConnect REST client."""
        if self._kite is not None:
            return
        try:
            from kiteconnect import KiteConnect
        except ImportError as exc:
            raise RuntimeError(
                "kiteconnect library is required for ZerodhaMarketDataProvider"
            ) from exc
        self._kite = KiteConnect(api_key=self._api_key)
        self._kite.set_access_token(self._access_token)

    def _on_ticks_wrapper(self, ws, ticks: list[dict[str, Any]]) -> None:
        """Callback bridge from KiteTicker to internal Tick contract.

        Runs in KiteTicker's background OS thread.  Uses call_soon_threadsafe
        to schedule the handler on the main event loop.
        """
        if self._tick_handler is None or self._loop is None:
            return
        for raw in ticks:
            tick = self._convert_tick(raw)
            if tick is not None:
                try:
                    self._loop.call_soon_threadsafe(self._tick_handler, tick)
                except Exception:
                    pass

    def _on_connect_wrapper(self, ws, response) -> None:
        self._connected = True

    def _on_close_wrapper(self, ws, code, reason) -> None:
        self._connected = False

    def _on_error_wrapper(self, ws, code, reason) -> None:
        self._connected = False

    def _convert_tick(self, raw: dict[str, Any]) -> Tick | None:
        """Map a KiteTicker tick payload to our internal Tick contract."""
        try:
            from zoneinfo import ZoneInfo
            ist = ZoneInfo("Asia/Kolkata")
            utc = ZoneInfo("UTC")

            # Kite ticker timestamp is usually missing; use received_at as UTC
            received_at = datetime.now(utc)
            # Attempt to parse exchange timestamp if present
            exchange_ts = raw.get("timestamp")
            if exchange_ts is not None:
                if isinstance(exchange_ts, str):
                    exchange_ts = datetime.fromisoformat(
                        exchange_ts.replace("Z", "+00:00")
                    )
                if exchange_ts.tzinfo is None:
                    exchange_ts = exchange_ts.replace(tzinfo=ist)
            else:
                exchange_ts = received_at.astimezone(ist)

            depth_raw = raw.get("depth", {})
            depth: list[MarketDepthLevel] | None = None
            if depth_raw:
                depth = []
                for side in ("buy", "sell"):
                    for level in depth_raw.get(side, []):
                        depth.append(
                            MarketDepthLevel(
                                price=Decimal(str(level["price"])),
                                quantity=int(level["quantity"]),
                                orders=level.get("orders"),
                            )
                        )

            return Tick(
                instrument_token=int(raw["instrument_token"]),
                exchange_timestamp=exchange_ts,
                received_at=received_at,
                last_price=Decimal(str(raw["last_price"])),
                last_quantity=int(raw.get("last_quantity", 0)),
                cumulative_volume=int(raw.get("volume", 0)),
                average_price=Decimal(str(raw["average_price"]))
                if raw.get("average_price") is not None
                else None,
                open=Decimal(str(raw["ohlc"]["open"])),
                high=Decimal(str(raw["ohlc"]["high"])),
                low=Decimal(str(raw["ohlc"]["low"])),
                close=Decimal(str(raw["ohlc"]["close"])),
                change=Decimal(str(raw["change"])) if "change" in raw else None,
                open_interest=int(raw["oi"]) if raw.get("oi") is not None else None,
                buy_quantity=int(raw["buy_quantity"]) if "buy_quantity" in raw else None,
                sell_quantity=int(raw["sell_quantity"]) if "sell_quantity" in raw else None,
                market_depth=depth,
            )
        except (KeyError, ValueError, TypeError):
            return None
