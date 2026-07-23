"""ContextBuilder — constructs immutable StrategyContext snapshots.

Uses only documented public APIs from RC-6, RC-7, and RC-8.

RC-10A additions (all backward-compatible):
  - Optional intelligence injection via keyword-only constructor parameters.
  - New sync `build()` method used by the market intelligence test suite.
  - The existing async `build_context()` method is UNCHANGED.
"""
from __future__ import annotations

import logging
from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, Optional

from strategy.contracts import StrategyConfig, StrategyContext, StrategyStateSnapshot, StrategyLifecycleState
from strategy.exceptions import StrategyError
from execution.portfolio import PortfolioSnapshot, PositionSnapshot
from market_data.service import MarketDataService
from market_data.contracts import CompletedBar
from risk.contracts import RiskStateSnapshot
from risk.engine import RiskEngine

logger = logging.getLogger(__name__)


class ContextBuilder:
    """Builds StrategyContext snapshots from live system state.

    Existing five-arg constructor form is preserved:
        ContextBuilder(market_data_service, risk_engine=None)

    RC-10A intelligence injection (all optional keyword args):
        ContextBuilder(
            indicator_engine=...,
            regime_detector=...,
            announcement_service=...,
            watchlist_ranker=...,
        )

    Mixing both forms is supported.
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
    ) -> None:
        self._market_data = market_data_service
        self._risk_engine = risk_engine
        # RC-10A
        self._indicator_engine = indicator_engine
        self._regime_detector = regime_detector
        self._announcement_service = announcement_service
        self._watchlist_ranker = watchlist_ranker

    # ------------------------------------------------------------------
    # RC-10A: sync build() used by new market intelligence tests
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
        """
        market_snapshots: Dict[str, Any] = {}

        if self._indicator_engine is not None:
            for token in config.instrument_tokens:
                mtf_data: Dict[str, Any] = {}

                try:
                    all_tf = self._indicator_engine.get_all_timeframes(token)
                    if all_tf:
                        mtf_data["timeframes"] = all_tf
                except Exception as exc:
                    logger.debug("IndicatorEngine failed for %s: %s", token, exc)

                if self._regime_detector is not None and "timeframes" in mtf_data:
                    try:
                        indicators: Dict[str, Any] = {}
                        for tf in ("15m", "1h", "5m", "1m"):
                            if tf in mtf_data["timeframes"]:
                                indicators = mtf_data["timeframes"][tf]
                                break
                        if indicators:
                            regime = self._regime_detector.detect(token, indicators)
                            mtf_data["regime"] = regime
                    except Exception as exc:
                        logger.debug("Regime detection failed for %s: %s", token, exc)

                if self._announcement_service is not None:
                    try:
                        announcements = self._announcement_service.get_active_announcements_sync(token)
                        mtf_data["active_announcements"] = announcements
                    except Exception as exc:
                        logger.debug("Announcement service failed for %s: %s", token, exc)

                if mtf_data:
                    market_snapshots[token] = mtf_data

        return StrategyContext(
            strategy_id=config.strategy_id,
            timestamp=datetime.utcnow(),
            market_snapshots=market_snapshots,
        )

    # ------------------------------------------------------------------
    # Existing async build_context() — UNCHANGED from pre-RC-10A
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
        # Gather market snapshots for all watched instruments
        market_snapshots: Dict[str, Any] = {}
        if self._market_data is not None:
            for token in config.instrument_tokens:
                snapshot = self._market_data.get_snapshot(token)
                if snapshot is not None:
                    market_snapshots[token] = snapshot

        # RC-10A: overlay intelligence data when injected
        if self._indicator_engine is not None:
            for token in config.instrument_tokens:
                mtf_data: Dict[str, Any] = market_snapshots.get(token, {})
                try:
                    all_tf = self._indicator_engine.get_all_timeframes(token)
                    if all_tf:
                        mtf_data["timeframes"] = all_tf
                except Exception as exc:
                    logger.debug("IndicatorEngine failed for %s: %s", token, exc)

                if self._regime_detector is not None and "timeframes" in mtf_data:
                    try:
                        indicators: Dict[str, Any] = {}
                        for tf in ("15m", "1h", "5m", "1m"):
                            if tf in mtf_data["timeframes"]:
                                indicators = mtf_data["timeframes"][tf]
                                break
                        if indicators:
                            regime = self._regime_detector.detect(token, indicators)
                            mtf_data["regime"] = regime
                    except Exception as exc:
                        logger.debug("Regime detection failed for %s: %s", token, exc)

                if mtf_data:
                    market_snapshots[token] = mtf_data

        if portfolio is None:
            portfolio = PortfolioSnapshot()
        if strategy_positions is None:
            strategy_positions = {}

        risk_state: RiskStateSnapshot
        if self._risk_engine is not None:
            snapshot_r = self._risk_engine.snapshot(config.strategy_id)
            risk_state = snapshot_r if snapshot_r is not None else self._default_risk_state(config.strategy_id)
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
