"""Base strategy with thesis invalidation."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Dict, Any, List, Optional
from datetime import datetime


class SignalType:
    BUY = "BUY"
    SELL = "SELL"
    NO_TRADE = "NO_TRADE"


@dataclass
class Signal:
    """Trading signal with quality and thesis tracking."""
    signal_type: str
    symbol: str
    instrument_token: int
    price: Decimal
    timestamp: datetime
    signal_quality: str
    regime: str = "UNKNOWN"
    thesis_valid: bool = True
    invalidation_conditions: Dict[str, Any] = field(default_factory=dict)
    strategy_name: str = ""
    strategy_version: str = ""


class BaseStrategy(ABC):
    """Abstract base strategy with thesis invalidation support."""

    def __init__(self, name: str, version: str = "1.0.0") -> None:
        self.name = name
        self.version = version
        self._config: Dict[str, Any] = {}

    @abstractmethod
    def generate_signal(self, symbol: str, instrument_token: int, price: Decimal) -> Signal:
        """Generate a trading signal."""
        pass

    @abstractmethod
    def check_thesis_invalidated(self, signal: Signal, current_price: Decimal) -> bool:
        """Check if a signal's thesis has been invalidated."""
        pass

    def get_config(self) -> Dict[str, Any]:
        """Get strategy-specific configuration."""
        return self._config.copy()

    def set_config(self, **kwargs) -> None:
        """Update strategy configuration."""
        self._config.update(kwargs)
