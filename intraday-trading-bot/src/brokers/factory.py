"""RC-10D: Broker adapter factory.

Usage
-----
    from src.brokers.factory import create_broker_adapter

    adapter = create_broker_adapter()   # → PaperBroker (default)

PaperBroker is always the default.  ZerodhaAdapter is only returned when:
  - ZERODHA_ENABLED=true
  - ZERODHA_PAPER_TRADING=false  (explicit opt-out of paper)
  - ZERODHA_LIVE_TRADING_ENABLED=true

These conditions are evaluated at factory call time, not import time, so
tests can set env vars before calling create_broker_adapter().
"""
from __future__ import annotations

import os
from typing import Optional

from src.core.logging import logger


def create_broker_adapter(force_paper: bool = True):
    """Create and return the appropriate broker adapter.

    Parameters
    ----------
    force_paper:
        When True (the default), always return PaperBroker regardless of env.
        Set to False only in production-ready deployments that have passed all
        live-mode safety gates.

    Returns
    -------
    BrokerInterface or BrokerAdapter
        PaperBroker in all paper/default cases.
        ZerodhaAdapter when all live-mode conditions are explicitly satisfied.
    """
    from src.brokers.paper_broker import PaperBroker

    if force_paper:
        logger.info(
            "BrokerFactory: force_paper=True → PaperBroker",
            extra={"event_type": "BROKER_FACTORY_PAPER"},
        )
        return PaperBroker()

    # Evaluate live-mode conditions
    enabled = os.environ.get("ZERODHA_ENABLED", "false").lower() in ("1", "true", "yes")
    paper = os.environ.get("ZERODHA_PAPER_TRADING", "true").lower() in ("1", "true", "yes")
    live_enabled = os.environ.get("ZERODHA_LIVE_TRADING_ENABLED", "false").lower() in (
        "1", "true", "yes"
    )
    has_key = bool(os.environ.get("ZERODHA_API_KEY", ""))
    has_secret = bool(os.environ.get("ZERODHA_API_SECRET", ""))

    if not (enabled and not paper and live_enabled and has_key and has_secret):
        # Conditions not satisfied — fall back to PaperBroker
        logger.info(
            "BrokerFactory: live-mode conditions not met → PaperBroker",
            extra={
                "event_type": "BROKER_FACTORY_PAPER_FALLBACK",
                "enabled": enabled,
                "paper_trading": paper,
                "live_enabled": live_enabled,
                "has_key": has_key,
                "has_secret": has_secret,
            },
        )
        return PaperBroker()

    # All live-mode conditions are satisfied — return ZerodhaAdapter
    # (This path is NOT reachable in RC-10D because live trading is not enabled)
    from src.brokers.zerodha.config import load_config_from_env
    from src.brokers.zerodha.adapter import ZerodhaAdapter

    config = load_config_from_env()
    logger.warning(
        "BrokerFactory: creating ZerodhaAdapter (live mode requested)",
        extra={
            "event_type": "BROKER_FACTORY_ZERODHA",
            **config.log_safe(),
        },
    )
    return ZerodhaAdapter(config)
