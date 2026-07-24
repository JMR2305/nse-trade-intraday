"""RC-10D: Zerodha market gateway.

Provides instrument listings and quotes, normalised to broker contracts.
All operations are read-only.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional

from src.brokers.contracts import BrokerInstrument
from src.brokers.zerodha.config import ZerodhaBrokerConfig
from src.brokers.zerodha.health import BrokerHealthTracker
from src.core.logging import logger


def _dec(value: Any, default: str = "0") -> Decimal:
    try:
        if value is None or value == "":
            return Decimal(default)
        return Decimal(str(value))
    except InvalidOperation:
        return Decimal(default)


class ZerodhaMarketGateway:
    """Market data from Zerodha (read-only).

    In paper mode, delegates to PaperBroker (which returns empty/mock data).
    """

    def __init__(
        self,
        config: ZerodhaBrokerConfig,
        health_tracker: BrokerHealthTracker,
        paper_broker,
        client=None,
    ) -> None:
        self._config = config
        self._health = health_tracker
        self._paper_broker = paper_broker
        self._client = client

    async def get_instruments(self, exchange: str = "NSE") -> List[BrokerInstrument]:
        """Fetch instrument master for an exchange.

        Returns normalised BrokerInstrument list.
        In paper mode, returns an empty list.
        """
        if self._config.paper_trading or self._client is None:
            return []

        try:
            raw = await self._client.get_instruments(exchange=exchange)
            instruments = []
            for row in (raw or []):
                instruments.append(BrokerInstrument(
                    instrument_token=str(row.get("instrument_token", "")),
                    exchange_token=str(row.get("exchange_token", "")),
                    trading_symbol=str(row.get("tradingsymbol", "")),
                    name=str(row.get("name", "")),
                    last_price=_dec(row.get("last_price")),
                    expiry=str(row.get("expiry", "")) or None,
                    strike=_dec(row.get("strike")) if row.get("strike") else None,
                    tick_size=_dec(row.get("tick_size", "0.05")),
                    lot_size=_dec(row.get("lot_size", "1")),
                    instrument_type=str(row.get("instrument_type", "EQ")),
                    segment=str(row.get("segment", exchange)),
                    exchange=str(row.get("exchange", exchange)),
                ))
            await self._health.mark_rest_success()
            logger.info(
                f"Fetched {len(instruments)} instruments from {exchange}",
                extra={"event_type": "BROKER_INSTRUMENTS_FETCHED", "exchange": exchange},
            )
            return instruments
        except Exception as exc:
            await self._health.mark_rest_failure(str(type(exc).__name__))
            logger.error(
                f"Failed to fetch instruments: {type(exc).__name__}",
                extra={"event_type": "BROKER_INSTRUMENTS_ERROR", "exchange": exchange},
            )
            raise

    async def get_quotes(self, symbols: List[str]) -> Dict[str, Any]:
        """Fetch quotes for a list of symbols.

        Returns {symbol: {last_price, volume, oi, ...}} dict.
        In paper mode, delegates to PaperBroker mock.
        """
        if self._config.paper_trading or self._client is None:
            return await self._paper_broker.get_quote(symbols)

        # Quote API is not directly exposed through ZerodhaHttpClient;
        # quote data comes via WebSocket tick feed in production.
        # This is a placeholder for REST-based quote fetching.
        logger.debug(
            f"Quote fetch for {len(symbols)} symbols",
            extra={"event_type": "BROKER_QUOTE_REQUEST"},
        )
        return {sym: {"last_price": Decimal("0"), "volume": 0, "oi": 0} for sym in symbols}
