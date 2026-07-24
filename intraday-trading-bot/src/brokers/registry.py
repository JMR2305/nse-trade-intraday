"""Broker singleton registry.

Holds the process-level authenticated broker adapter.  The FastAPI lifespan
in main.py calls ``set_live_broker()`` once at startup after the adapter is
fully initialised (session restored, REST probe confirmed, health ready).

All request handlers call ``get_broker()`` to obtain the adapter; they never
construct it themselves.

Paper mode: the registry is never populated, so ``get_broker()`` returns a
fresh ``PaperBroker()`` on every call — stateless, no auth needed.
"""
from __future__ import annotations

from typing import Optional

_live_broker: Optional[object] = None  # ZerodhaAdapter at runtime


def set_live_broker(adapter: object) -> None:
    """Register the authenticated live adapter (called once from lifespan)."""
    global _live_broker
    _live_broker = adapter


def get_broker() -> object:
    """Return the live adapter if initialised, otherwise a fresh PaperBroker."""
    if _live_broker is not None:
        return _live_broker
    from src.brokers.paper_broker import PaperBroker
    return PaperBroker()


def clear_live_broker() -> None:
    """Release the live adapter (called from lifespan shutdown)."""
    global _live_broker
    _live_broker = None


def is_live_mode() -> bool:
    """True when a live-authenticated adapter is registered."""
    return _live_broker is not None
