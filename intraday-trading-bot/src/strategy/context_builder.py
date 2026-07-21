"""ContextBuilder — constructs immutable StrategyContext snapshots.

Uses only documented public APIs from RC-6, RC-7, and RC-8.
"""
from __future__ import annotations

from typing import Optional, Dict, Any
from datetime import datetime

from strategy.contracts import StrategyContext, StrategyStateSnapshot, StrategyConfig
from strategy.exceptions import StrategyError
from execution.portfolio import PortfolioSnapshot, PositionSnapshot
from market_data.service import MarketDataService
from risk.contracts import RiskStateSnapshot
from risk.engine import RiskEngine


class ContextBuilder:
    """Builds StrategyContext snapshots from live system state.

    This is a stateless utility class. Each call produces a fresh
    immutable StrategyContext from the current market, portfolio,
    and risk state.
    """

    def __init__(
        self,
        market_data_service: MarketDataService,
        risk_engine: Optional[RiskEngine] = None,
    ):
        self._market_data = market_data_service
        self._risk_engine = risk_engine

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
        for token in config.instrument_tokens:
            snapshot = self._market_data.get_snapshot(token)
            if snapshot is not None:
                market_snapshots[token] = snapshot

        # Get portfolio (or default)
        if portfolio is None:
            portfolio = PortfolioSnapshot()

        # Get strategy-filtered positions (or default)
        if strategy_positions is None:
            strategy_positions = {}

        # Get risk state (or default)
        risk_state: RiskStateSnapshot
        if self._risk_engine is not None:
            snapshot = self._risk_engine.snapshot(config.strategy_id)
            risk_state = snapshot if snapshot is not None else self._default_risk_state(config.strategy_id)
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
        """Create a default empty risk state."""
        return RiskStateSnapshot(
            account_id=account_id,
            snapshot_timestamp=datetime.utcnow(),
        )
