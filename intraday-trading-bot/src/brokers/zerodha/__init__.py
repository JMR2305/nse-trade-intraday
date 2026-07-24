"""RC-10D: Zerodha Kite broker adapter sub-package.

Public surface:
    ZerodhaAdapter      — full adapter implementing BrokerAdapter
    ZerodhaBrokerConfig — configuration model
    load_config_from_env — factory for ZerodhaBrokerConfig from env vars

All classes in this package depend on kiteconnect being available at runtime.
In paper mode (the default), kiteconnect is not required.
"""
from __future__ import annotations

# Lazy imports to avoid hard-coupling when kiteconnect is not installed
__all__ = ["ZerodhaAdapter", "ZerodhaBrokerConfig", "load_config_from_env"]


def __getattr__(name: str):
    if name == "ZerodhaAdapter":
        from src.brokers.zerodha.adapter import ZerodhaAdapter
        return ZerodhaAdapter
    if name == "ZerodhaBrokerConfig":
        from src.brokers.zerodha.config import ZerodhaBrokerConfig
        return ZerodhaBrokerConfig
    if name == "load_config_from_env":
        from src.brokers.zerodha.config import load_config_from_env
        return load_config_from_env
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
