"""RC-10C1 Portfolio Core — Capital Allocator.

Evaluates whether a strategy can be granted the requested capital at this
moment, given the current portfolio snapshot and configured limits.

RC-8 remains the final authority on order execution.  A APPROVED decision
here is necessary but NOT sufficient — RC-8 must still perform its own
pre-flight checks and may reject the order for reasons outside the
portfolio's jurisdiction.

No broker calls, no order placement.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from .config import PortfolioConfig
from .contracts import (
    AllocationDecision,
    AllocationStatus,
    PortfolioPnL,
    PortfolioSnapshot,
    PortfolioStatus,
)
from .exceptions import (
    NegativeQuantityError,
    PortfolioNotReadyError,
    StalePortfolioStateError,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------

def is_daily_loss_breached(pnl: PortfolioPnL, config: PortfolioConfig) -> bool:
    """Return True if today's P&L loss exceeds the configured daily loss cap.

    Args:
        pnl: Current portfolio P&L snapshot.
        config: Validated portfolio configuration.

    Returns:
        True if the daily loss cap has been breached.
    """
    equity = pnl.current_equity
    if equity <= Decimal("0"):
        return False
    max_loss = config.max_daily_loss_amount(equity)
    return pnl.daily_pnl < -max_loss


def is_drawdown_breached(pnl: PortfolioPnL, config: PortfolioConfig) -> bool:
    """Return True if peak-to-trough drawdown exceeds the configured cap.

    Args:
        pnl: Current portfolio P&L snapshot.
        config: Validated portfolio configuration.

    Returns:
        True if the drawdown cap has been breached.
    """
    return pnl.drawdown > config.max_drawdown_pct


# ---------------------------------------------------------------------------
# Core evaluator
# ---------------------------------------------------------------------------

async def evaluate_allocation(
    strategy_id: str,
    instrument_token: int | None,
    requested_capital: Decimal,
    snapshot: PortfolioSnapshot,
    config: PortfolioConfig,
    correlation_id: str | None = None,
) -> AllocationDecision:
    """Evaluate a capital-allocation request and return an AllocationDecision.

    Gates (in order):
      1. Snapshot staleness guard.
      2. Portfolio status must be READY.
      3. Daily loss limit must not be breached.
      4. Drawdown limit must not be breached.
      5. Cap approved <= net buying power (cash reserve floor).
      6. Cap approved <= max_capital_per_strategy.
      7. Cap approved <= max_portfolio_exposure headroom.
      8. Reject if approved < min_order_value.

    Args:
        strategy_id: Identifier of the requesting strategy.
        instrument_token: Optional instrument token for the intended order.
        requested_capital: Gross capital the strategy wants to deploy.
        snapshot: Current authoritative portfolio snapshot.
        config: Validated portfolio configuration.
        correlation_id: Optional trace identifier propagated from the caller.

    Returns:
        AllocationDecision with status APPROVED or REJECTED.

    Raises:
        StalePortfolioStateError: Snapshot is older than the stale threshold.
        PortfolioNotReadyError: Portfolio status is not READY.
        NegativeQuantityError: Approved capital is below min_order_value.
    """
    now = datetime.now(timezone.utc)
    reason_codes: list[str] = []
    binding_limit: str | None = None

    # ── Gate 1: Staleness ──────────────────────────────────────────────────
    state_age_s = (now - snapshot.snapshotted_at).total_seconds()
    if state_age_s > config.stale_state_threshold_s:
        logger.warning(
            "allocation_rejected|strategy=%s|reason=stale_state|age_s=%.1f",
            strategy_id, state_age_s,
        )
        raise StalePortfolioStateError(
            f"Portfolio snapshot is {state_age_s:.1f}s old "
            f"(threshold {config.stale_state_threshold_s}s)"
        )

    # ── Gate 2: Portfolio readiness ────────────────────────────────────────
    if snapshot.status != PortfolioStatus.READY:
        logger.warning(
            "allocation_rejected|strategy=%s|reason=not_ready|status=%s",
            strategy_id, snapshot.status,
        )
        raise PortfolioNotReadyError(
            f"Portfolio status is {snapshot.status.value}; READY required for allocation"
        )

    equity = snapshot.pnl.current_equity
    approved_capital = requested_capital

    # ── Gate 3: Daily loss limit ───────────────────────────────────────────
    if is_daily_loss_breached(snapshot.pnl, config):
        max_loss = config.max_daily_loss_amount(equity)
        logger.warning(
            "allocation_rejected|strategy=%s|reason=daily_loss|daily_pnl=%s|limit=%s",
            strategy_id, snapshot.pnl.daily_pnl, max_loss,
        )
        return _build_decision(
            strategy_id=strategy_id,
            instrument_token=instrument_token,
            requested_capital=requested_capital,
            approved_capital=Decimal("0"),
            status=AllocationStatus.REJECTED,
            reason_codes=["DAILY_LOSS_LIMIT_BREACHED"],
            binding_limit="max_daily_loss",
            snapshot=snapshot,
            expires_at=None,
            correlation_id=correlation_id,
        )

    # ── Gate 4: Drawdown limit ─────────────────────────────────────────────
    if is_drawdown_breached(snapshot.pnl, config):
        logger.warning(
            "allocation_rejected|strategy=%s|reason=drawdown|drawdown=%s|limit=%s",
            strategy_id, snapshot.pnl.drawdown, config.max_drawdown_pct,
        )
        return _build_decision(
            strategy_id=strategy_id,
            instrument_token=instrument_token,
            requested_capital=requested_capital,
            approved_capital=Decimal("0"),
            status=AllocationStatus.REJECTED,
            reason_codes=["DRAWDOWN_LIMIT_BREACHED"],
            binding_limit="max_drawdown",
            snapshot=snapshot,
            expires_at=None,
            correlation_id=correlation_id,
        )

    # ── Gate 5: Cash-reserve floor — cap to net buying power ──────────────
    net_buying_power = snapshot.buying_power.net
    if approved_capital > net_buying_power:
        logger.info(
            "allocation_capped|strategy=%s|reason=buying_power|requested=%s|cap=%s",
            strategy_id, approved_capital, net_buying_power,
        )
        approved_capital = net_buying_power
        reason_codes.append("CAPPED_BY_BUYING_POWER")
        if binding_limit is None:
            binding_limit = "net_buying_power"

    # ── Gate 6: Max capital per strategy ──────────────────────────────────
    max_strategy = config.max_strategy_value(equity)
    strategy_deployed = _strategy_deployed(snapshot, strategy_id)
    strategy_headroom = max(Decimal("0"), max_strategy - strategy_deployed)
    if approved_capital > strategy_headroom:
        logger.info(
            "allocation_capped|strategy=%s|reason=max_strategy|approved=%s|headroom=%s",
            strategy_id, approved_capital, strategy_headroom,
        )
        approved_capital = strategy_headroom
        reason_codes.append("CAPPED_BY_STRATEGY_LIMIT")
        if binding_limit is None:
            binding_limit = "max_capital_per_strategy"

    # ── Gate 7: Max portfolio exposure ─────────────────────────────────────
    max_deployable = config.max_deployable(equity)
    current_gross = snapshot.exposure.gross_exposure
    portfolio_headroom = max(Decimal("0"), max_deployable - current_gross)
    if approved_capital > portfolio_headroom:
        logger.info(
            "allocation_capped|strategy=%s|reason=portfolio_exposure|approved=%s|headroom=%s",
            strategy_id, approved_capital, portfolio_headroom,
        )
        approved_capital = portfolio_headroom
        reason_codes.append("CAPPED_BY_PORTFOLIO_EXPOSURE")
        if binding_limit is None:
            binding_limit = "max_portfolio_exposure"

    # ── Gate 8: Min order value threshold ─────────────────────────────────
    if approved_capital < config.min_order_value:
        logger.warning(
            "allocation_rejected|strategy=%s|reason=below_min_order_value|approved=%s|min=%s",
            strategy_id, approved_capital, config.min_order_value,
        )
        reason_codes.append("BELOW_MIN_ORDER_VALUE")
        raise NegativeQuantityError(
            f"Approved capital {approved_capital} is below minimum order value "
            f"{config.min_order_value}; strategy={strategy_id} reason_codes={reason_codes}"
        )

    # ── All gates passed — APPROVED ────────────────────────────────────────
    expires_at = now + timedelta(seconds=config.allocation_ttl_s)
    logger.info(
        "allocation_approved|strategy=%s|requested=%s|approved=%s|expires_at=%s",
        strategy_id, requested_capital, approved_capital, expires_at.isoformat(),
    )
    return _build_decision(
        strategy_id=strategy_id,
        instrument_token=instrument_token,
        requested_capital=requested_capital,
        approved_capital=approved_capital,
        status=AllocationStatus.APPROVED,
        reason_codes=reason_codes,
        binding_limit=binding_limit,
        snapshot=snapshot,
        expires_at=expires_at,
        correlation_id=correlation_id,
    )


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _strategy_deployed(snapshot: PortfolioSnapshot, strategy_id: str) -> Decimal:
    """Return gross capital currently deployed for *strategy_id*.

    Prefers the pre-computed ``StrategyExposure`` from the snapshot's
    ``ExposureSnapshot`` (populated by the exposure engine), falling back to
    a manual sum over open positions when not available.
    """
    # Fast path: use pre-computed strategy exposure breakdown
    for se in snapshot.exposure.strategy_exposures:
        if se.strategy_id == strategy_id:
            return se.absolute_value

    # Fallback: derive from open positions
    total = Decimal("0")
    for pos in snapshot.open_positions:
        if pos.strategy_id == strategy_id:
            total += pos.gross_exposure
    return total


def _build_decision(
    *,
    strategy_id: str,
    instrument_token: int | None,
    requested_capital: Decimal,
    approved_capital: Decimal,
    status: AllocationStatus,
    reason_codes: list[str],
    binding_limit: str | None,
    snapshot: PortfolioSnapshot,
    expires_at: datetime | None,
    correlation_id: str | None,
) -> AllocationDecision:
    """Construct an AllocationDecision value object."""
    rejected_capital = max(Decimal("0"), requested_capital - approved_capital)
    return AllocationDecision(
        strategy_id=strategy_id,
        instrument_token=instrument_token,
        requested_capital=requested_capital,
        approved_capital=approved_capital,
        rejected_capital=rejected_capital,
        status=status,
        reason_codes=tuple(reason_codes),
        binding_limit=binding_limit,
        portfolio_state_version=snapshot.version,
        expires_at=expires_at,
        correlation_id=correlation_id,
    )


# ---------------------------------------------------------------------------
# CapitalAllocator class — injectable façade for PortfolioService
# ---------------------------------------------------------------------------

class CapitalAllocator:
    """Object-oriented façade around the module-level evaluate_allocation function.

    Wraps the functional capital-allocation logic so that PortfolioService
    can use dependency injection for testing and composition.
    """

    def __init__(self, config: PortfolioConfig | None = None) -> None:
        from .config import DEFAULT_CONFIG as _DEFAULT_CONFIG
        self.config: PortfolioConfig = config or _DEFAULT_CONFIG

    async def evaluate_allocation(
        self,
        snapshot: PortfolioSnapshot,
        strategy_id: str,
        instrument_token: int | None,
        requested_capital: Decimal,
        correlation_id: str | None = None,
    ) -> AllocationDecision:
        """Delegate to the module-level evaluate_allocation function.

        Parameters
        ----------
        snapshot:
            Current portfolio state.
        strategy_id:
            Requesting strategy identifier.
        instrument_token:
            Optional target instrument.
        requested_capital:
            Amount of capital requested.
        correlation_id:
            Optional tracing identifier.

        Returns
        -------
        AllocationDecision
        """
        return await evaluate_allocation(
            strategy_id=strategy_id,
            instrument_token=instrument_token,
            requested_capital=requested_capital,
            snapshot=snapshot,
            config=self.config,
            correlation_id=correlation_id,
        )
