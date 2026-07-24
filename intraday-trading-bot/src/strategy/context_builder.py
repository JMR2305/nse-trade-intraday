"""ContextBuilder — constructs immutable StrategyContext snapshots.

Uses only documented public APIs from RC-6, RC-7, and RC-8.

RC-10A additions (all backward-compatible):
  - Optional intelligence injection via keyword-only constructor parameters.
  - New sync `build()` method used by the market intelligence test suite.
  - The existing async `build_context()` method is UNCHANGED from pre-RC-10A
    in its signature and external behaviour; it now uses the shared private
    helper `_inject_market_intelligence()` internally.

RC-10A FINAL PATCH:
  - `market_snapshots[token]` now contains typed `MultiTimeframeContext`
    objects (not raw dicts) when intelligence services are injected.
  - Shared injection logic extracted to `_inject_market_intelligence()`.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from strategy.contracts import StrategyConfig, StrategyContext, StrategyStateSnapshot
from execution.portfolio import PortfolioSnapshot, PositionSnapshot
from market_data.service import MarketDataService
from market_data.contracts import CompletedBar
from risk.contracts import RiskStateSnapshot
from risk.engine import RiskEngine
from market_intelligence.multi_timeframe_context import (
    AnnouncementRecord,
    MarketRegimeSnapshot,
    MultiTimeframeContext,
)

logger = logging.getLogger(__name__)


class ContextBuilder:
    """Builds StrategyContext snapshots from live system state.

    Existing two-arg constructor form is preserved:
        ContextBuilder(market_data_service, risk_engine=None)

    RC-10A intelligence injection (all optional keyword args):
        ContextBuilder(
            indicator_engine=...,
            regime_detector=...,
            announcement_service=...,
            watchlist_ranker=...,
        )

    Mixing both forms is supported.

    When intelligence services are injected, ``market_snapshots[token]``
    contains a typed ``MultiTimeframeContext`` instance.  When no intelligence
    is injected the value is whatever ``MarketDataService.get_snapshot()``
    returns (pre-RC-10A behaviour is fully preserved).
    """

    def __init__(
        self,
        market_data_service: Optional[MarketDataService] = None,
        risk_engine: Optional[RiskEngine] = None,
        *,
        indicator_engine: Optional[Any] = None,
        regime_detector: Optional[Any] = None,
        announcement_service: Optional[Any] = None,
        watchlist_ranker: Optional[Any] = None,
        # RC-10B: AI forecast services (all optional, fail-open)
        ai_forecast_adapter: Optional[Any] = None,
        confidence_gate: Optional[Any] = None,
        volatility_forecaster: Optional[Any] = None,
    ) -> None:
        self._market_data = market_data_service
        self._risk_engine = risk_engine
        # RC-10A
        self._indicator_engine = indicator_engine
        self._regime_detector = regime_detector
        self._announcement_service = announcement_service
        self._watchlist_ranker = watchlist_ranker
        # RC-10B (stored; enrichment via SignalRouter at signal time)
        self._ai_forecast_adapter = ai_forecast_adapter
        self._confidence_gate = confidence_gate
        self._volatility_forecaster = volatility_forecaster

    # ------------------------------------------------------------------
    # Private helper — shared intelligence injection logic
    # ------------------------------------------------------------------

    def _inject_market_intelligence(
        self,
        instrument_token: str,
        snapshot_ts: datetime,
    ) -> Optional[MultiTimeframeContext]:
        """Build a typed MultiTimeframeContext for one instrument.

        Queries each injected intelligence service independently; any
        individual service failure is caught and logged at DEBUG level so
        that intelligence errors never propagate to strategy callers.

        Returns None when no intelligence data is available for the token
        (e.g. the IndicatorEngine has not yet received bars for it).
        """
        timeframes: Dict[str, Any] = {}
        regime: Optional[MarketRegimeSnapshot] = None
        active_announcements: List[AnnouncementRecord] = []

        # --- indicator data ---
        if self._indicator_engine is not None:
            try:
                all_tf = self._indicator_engine.get_all_timeframes(instrument_token)
                if all_tf:
                    timeframes = all_tf
            except Exception as exc:
                logger.debug("IndicatorEngine failed for %s: %s", instrument_token, exc)

        # --- regime detection (requires indicators) ---
        if self._regime_detector is not None and timeframes:
            try:
                indicators: Dict[str, Any] = {}
                for tf in ("15m", "1h", "5m", "1m"):
                    if tf in timeframes:
                        indicators = timeframes[tf]
                        break
                if indicators:
                    regime = self._regime_detector.detect(instrument_token, indicators)
            except Exception as exc:
                logger.debug("Regime detection failed for %s: %s", instrument_token, exc)

        # --- announcement intelligence ---
        if self._announcement_service is not None:
            try:
                active_announcements = (
                    self._announcement_service.get_active_announcements_sync(
                        instrument_token
                    )
                )
            except Exception as exc:
                logger.debug(
                    "Announcement service failed for %s: %s", instrument_token, exc
                )

        # Return None when there is nothing to populate; avoids injecting
        # empty MultiTimeframeContext objects for unknown instruments.
        if not timeframes and regime is None and not active_announcements:
            return None

        return MultiTimeframeContext(
            instrument_token=instrument_token,
            snapshot_timestamp=snapshot_ts,
            timeframes=timeframes,
            regime=regime,
            active_announcements=active_announcements,
        )

    # ------------------------------------------------------------------
    # RC-10A: sync build() used by market intelligence tests
    # ------------------------------------------------------------------

    def build(
        self,
        config: StrategyConfig,
        state_snapshot: Dict[str, Any],
        bar: Optional[CompletedBar] = None,
    ) -> StrategyContext:
        """Build a StrategyContext synchronously.

        Preserves pre-RC-10A behaviour when no intelligence is injected
        (market_snapshots == {}).

        When intelligence services are injected, each populated token gets
        a typed MultiTimeframeContext in market_snapshots.
        """
        market_snapshots: Dict[str, Any] = {}

        if self._indicator_engine is not None:
            ts = datetime.utcnow()
            for token in config.instrument_tokens:
                mtf_ctx = self._inject_market_intelligence(token, ts)
                if mtf_ctx is not None:
                    market_snapshots[token] = mtf_ctx

        return StrategyContext(
            strategy_id=config.strategy_id,
            timestamp=datetime.utcnow(),
            market_snapshots=market_snapshots,
        )

    # ------------------------------------------------------------------
    # Existing async build_context() — signature UNCHANGED from pre-RC-10A
    # ------------------------------------------------------------------

    async def build_context(
        self,
        config: StrategyConfig,
        strategy_state: StrategyStateSnapshot,
        portfolio: Optional[PortfolioSnapshot] = None,
        strategy_positions: Optional[Dict[str, PositionSnapshot]] = None,
    ) -> StrategyContext:
        """Build a StrategyContext for the given strategy.

        Args:
            config: The strategy configuration.
            strategy_state: Current runtime state of the strategy.
            portfolio: Optional pre-fetched portfolio snapshot.
            strategy_positions: Optional pre-filtered position map.

        Returns:
            Immutable StrategyContext snapshot.
        """
        # Gather market snapshots for all watched instruments (pre-RC-10A path)
        market_snapshots: Dict[str, Any] = {}
        if self._market_data is not None:
            for token in config.instrument_tokens:
                snapshot = self._market_data.get_snapshot(token)
                if snapshot is not None:
                    market_snapshots[token] = snapshot

        # RC-10A: when intelligence services are injected, replace the raw
        # market-data snapshot with a typed MultiTimeframeContext object.
        if self._indicator_engine is not None:
            ts = datetime.utcnow()
            for token in config.instrument_tokens:
                mtf_ctx = self._inject_market_intelligence(token, ts)
                if mtf_ctx is not None:
                    market_snapshots[token] = mtf_ctx

        if portfolio is None:
            portfolio = PortfolioSnapshot()
        if strategy_positions is None:
            strategy_positions = {}

        risk_state: RiskStateSnapshot
        if self._risk_engine is not None:
            snapshot_r = self._risk_engine.snapshot(config.strategy_id)
            risk_state = (
                snapshot_r
                if snapshot_r is not None
                else self._default_risk_state(config.strategy_id)
            )
        else:
            risk_state = self._default_risk_state(config.strategy_id)

        return StrategyContext(
            strategy_id=config.strategy_id,
            timestamp=datetime.utcnow(),
            market_snapshots=market_snapshots,
            portfolio=portfolio,
            strategy_positions=strategy_positions,
            risk_state=risk_state,
            strategy_state=strategy_state,
        )

    def _default_risk_state(self, account_id: str) -> RiskStateSnapshot:
        return RiskStateSnapshot(
            account_id=account_id,
            snapshot_timestamp=datetime.utcnow(),
        )
