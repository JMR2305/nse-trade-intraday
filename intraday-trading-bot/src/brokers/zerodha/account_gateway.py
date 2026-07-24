"""RC-10D: Zerodha account gateway (read-only).

Provides funds, margins, holdings, and positions — all normalised to
broker-neutral contracts.  All operations are read-only; write operations
belong in ZerodhaOrderGateway.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional

from src.brokers.contracts import (
    BrokerFunds,
    BrokerHolding,
    BrokerMargins,
    BrokerPosition,
    BrokerSide,
)
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


class ZerodhaAccountGateway:
    """Read-only account data from Zerodha.

    In paper mode, returns empty/zero values from PaperBroker.
    In live mode, fetches from Zerodha via ZerodhaHttpClient.
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

    async def get_margins(self) -> BrokerMargins:
        """Fetch account margin summary."""
        if self._config.paper_trading or self._client is None:
            legacy = await self._paper_broker.get_margins()
            return BrokerMargins(
                available_cash=legacy.available_cash,
                available_margin=legacy.available_margin,
                used_margin=legacy.used_margin,
            )

        try:
            raw = await self._client.get_margins()
            equity = raw.get("equity", {})
            available = equity.get("available", {})
            utilised = equity.get("utilised", {})

            margins = BrokerMargins(
                available_cash=_dec(available.get("cash")),
                available_margin=_dec(available.get("live_balance") or available.get("cash")),
                used_margin=_dec(utilised.get("debits") or utilised.get("span")),
                payin_amount=_dec(available.get("intraday_payin")),
                span_margin=_dec(utilised.get("span")),
                option_premium=_dec(utilised.get("option_premium")),
                net=_dec(equity.get("net")),
            )
            await self._health.mark_rest_success()
            return margins
        except Exception as exc:
            await self._health.mark_rest_failure(str(type(exc).__name__))
            logger.error(
                f"Failed to fetch margins: {type(exc).__name__}",
                extra={"event_type": "BROKER_MARGINS_ERROR"},
            )
            raise

    async def get_funds(self) -> BrokerFunds:
        """Fetch full funds breakdown."""
        if self._config.paper_trading or self._client is None:
            legacy = await self._paper_broker.get_margins()
            equity = BrokerMargins(
                available_cash=legacy.available_cash,
                available_margin=legacy.available_margin,
                used_margin=legacy.used_margin,
            )
            return BrokerFunds(equity=equity)

        try:
            raw = await self._client.get_margins()
            equity_raw = raw.get("equity", {})
            commodity_raw = raw.get("commodity", {})

            def _parse_segment(seg: Dict) -> BrokerMargins:
                available = seg.get("available", {})
                utilised = seg.get("utilised", {})
                return BrokerMargins(
                    available_cash=_dec(available.get("cash")),
                    available_margin=_dec(
                        available.get("live_balance") or available.get("cash")
                    ),
                    used_margin=_dec(utilised.get("debits")),
                    payin_amount=_dec(available.get("intraday_payin")),
                    span_margin=_dec(utilised.get("span")),
                    option_premium=_dec(utilised.get("option_premium")),
                    net=_dec(seg.get("net")),
                )

            funds = BrokerFunds(
                equity=_parse_segment(equity_raw),
                commodity=_parse_segment(commodity_raw) if commodity_raw else None,
            )
            await self._health.mark_rest_success()
            return funds
        except Exception as exc:
            await self._health.mark_rest_failure(str(type(exc).__name__))
            raise

    async def get_positions(self) -> List[BrokerPosition]:
        """Fetch current open positions."""
        if self._config.paper_trading or self._client is None:
            legacy_positions = await self._paper_broker.get_positions()
            result = []
            for p in legacy_positions:
                result.append(BrokerPosition(
                    trading_symbol=p.symbol,
                    exchange="NSE",
                    product=p.product,
                    quantity=Decimal(str(p.quantity)),
                    average_price=p.average_price,
                    last_price=p.last_price,
                    pnl=p.pnl,
                ))
            return result

        try:
            raw = await self._client.get_positions()
            positions = []
            for p in (raw.get("net", []) or []):
                side_raw = "BUY" if _dec(p.get("quantity", 0)) >= 0 else "SELL"
                positions.append(BrokerPosition(
                    trading_symbol=str(p.get("tradingsymbol", "")),
                    exchange=str(p.get("exchange", "NSE")),
                    instrument_token=str(p.get("instrument_token", "")),
                    product=str(p.get("product", "MIS")),
                    quantity=_dec(p.get("quantity")),
                    overnight_quantity=_dec(p.get("overnight_quantity")),
                    average_price=_dec(p.get("average_price")),
                    close_price=_dec(p.get("close_price")),
                    last_price=_dec(p.get("last_price")),
                    pnl=_dec(p.get("pnl")),
                    m2m=_dec(p.get("m2m")),
                    unrealised=_dec(p.get("unrealised")),
                    realised=_dec(p.get("realised")),
                    buy_quantity=_dec(p.get("buy_quantity")),
                    buy_price=_dec(p.get("buy_price")),
                    sell_quantity=_dec(p.get("sell_quantity")),
                    sell_price=_dec(p.get("sell_price")),
                ))
            await self._health.mark_rest_success()
            return positions
        except Exception as exc:
            await self._health.mark_rest_failure(str(type(exc).__name__))
            raise

    async def get_holdings(self) -> List[BrokerHolding]:
        """Fetch delivery holdings."""
        if self._config.paper_trading or self._client is None:
            return []

        try:
            raw_holdings = await self._client.get_holdings()
            holdings = []
            for h in (raw_holdings or []):
                holdings.append(BrokerHolding(
                    trading_symbol=str(h.get("tradingsymbol", "")),
                    exchange=str(h.get("exchange", "NSE")),
                    instrument_token=str(h.get("instrument_token", "")),
                    isin=h.get("isin"),
                    product=str(h.get("product", "CNC")),
                    quantity=_dec(h.get("quantity")),
                    average_price=_dec(h.get("average_price")),
                    last_price=_dec(h.get("last_price")),
                    close_price=_dec(h.get("close_price")),
                    pnl=_dec(h.get("pnl")),
                    day_change=_dec(h.get("day_change")),
                    day_change_percentage=_dec(h.get("day_change_percentage")),
                ))
            await self._health.mark_rest_success()
            return holdings
        except Exception as exc:
            await self._health.mark_rest_failure(str(type(exc).__name__))
            raise
