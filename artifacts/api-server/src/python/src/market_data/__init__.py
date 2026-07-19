"""Market data foundation package."""
from src.market_data.contracts import (
    CompletedBar,
    DataGap,
    DataQualityEvent,
    DataQualityState,
    DataQualityStatus,
    MarketDepthLevel,
    Quote,
    SubscriptionRequest,
    Tick,
)
from src.market_data.provider import MarketDataProvider
from src.market_data.subscription_manager import SubscriptionManager
from src.market_data.bar_builder import BarBuilder
from src.market_data.quality import DataQualityTracker, DataQualitySettings
from src.market_data.backfill import BackfillCoordinator, BackfillSettings, BackfillResult
from src.market_data.instrument_sync import InstrumentSync, InstrumentSyncResult
from src.market_data.service import MarketDataService

__all__ = [
    "CompletedBar",
    "DataGap",
    "DataQualityEvent",
    "DataQualityState",
    "DataQualityStatus",
    "MarketDepthLevel",
    "Quote",
    "SubscriptionRequest",
    "Tick",
    "MarketDataProvider",
    "SubscriptionManager",
    "BarBuilder",
    "DataQualityTracker",
    "DataQualitySettings",
    "BackfillCoordinator",
    "BackfillSettings",
    "BackfillResult",
    "InstrumentSync",
    "InstrumentSyncResult",
    "MarketDataService",
]
