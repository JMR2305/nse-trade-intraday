"""RC-10C1 Portfolio Core — Portfolio Limit Engine.

Runs all configured portfolio limits against a proposed action and returns a
LimitCheckReport aggregating every individual result.

No broker calls, no order placement.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from decimal import Decimal

from .config import PortfolioConfig
from .contracts import (
    LimitCheckReport,
    LimitCheckResult,
    LimitSeverity,
    PortfolioSnapshot,
)
from .exposure import (
    check_instrument_exposure,
    check_sector_exposure,
    check_strategy_exposure,
)

logger = logging.getLogger(__name__)

# Fraction of limit that triggers WARNING severity.
_WARNING_THRESHOLD_PCT = Decimal("0.80")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def check_all_limits(
    snapshot: PortfolioSnapshot,
    proposed_instrument_token: int | None,
    proposed_value: Decimal,
    proposed_strategy_id: str | None,
    proposed_sector: str | None,
    config: PortfolioConfig,
) -> LimitCheckReport:
    """Run every configured portfolio limit and return a consolidated report.

    Limits are evaluated in a fixed order so that the first blocking limit
    is always deterministic.

    Args:
        snapshot: Current authoritative portfolio snapshot.
        proposed_instrument_token: Instrument for the proposed order (optional).
        proposed_value: Gross notional value of the proposed order.
        proposed_strategy_id: Strategy submitting the order (optional).
        proposed_sector: Sector of the instrument (optional).
        config: Validated portfolio configuration.

    Returns:
        LimitCheckReport with overall_allowed, all individual results, and
        the first blocking limit name.
    """
    equity = snapshot.pnl.current_equity
    results: list[LimitCheckResult] = []

    # 1. Max gross exposure.
    results.append(_check_gross_exposure(snapshot, proposed_value, config, equity))

    # 2. Max instrument exposure (if instrument provided).
    if proposed_instrument_token is not None:
        results.append(
            check_instrument_exposure(
                instrument_token=proposed_instrument_token,
                proposed_value=proposed_value,
                snapshot=snapshot.exposure,
                config=config,
                equity=equity,
            )
        )

    # 3. Max sector exposure (if sector provided).
    if proposed_sector is not None:
        results.append(
            check_sector_exposure(
                sector=proposed_sector,
                proposed_value=proposed_value,
                snapshot=snapshot.exposure,
                config=config,
                equity=equity,
            )
        )

    # 4. Max strategy exposure (if strategy provided).
    if proposed_strategy_id is not None:
        results.append(
            check_strategy_exposure(
                strategy_id=proposed_strategy_id,
                proposed_value=proposed_value,
                snapshot=snapshot.exposure,
                config=config,
                equity=equity,
            )
        )

    # 5. Max open positions.
    results.append(_check_open_positions(snapshot, config))

    # 6. Max pending orders.
    results.append(_check_pending_orders(snapshot, config))

    # 7. Max daily loss.
    results.append(_check_daily_loss(snapshot, config, equity))

    # 8. Max drawdown.
    results.append(_check_drawdown(snapshot, config))

    # 9. Cash reserve.
    results.append(_check_cash_reserve(snapshot, proposed_value, config, equity))

    # Aggregate.
    overall_allowed = all(r.allowed for r in results)
    blocking_limit: str | None = None
    for r in results:
        if not r.allowed:
            blocking_limit = r.limit_name
            break

    critical_count = sum(1 for r in results if r.severity == LimitSeverity.CRITICAL)
    warning_count = sum(1 for r in results if r.severity == LimitSeverity.WARNING)
    now = datetime.now(timezone.utc)

    logger.debug(
        "limit_check|overall_allowed=%s|blocking=%s|critical=%d|warning=%d",
        overall_allowed, blocking_limit, critical_count, warning_count,
    )

    return LimitCheckReport(
        overall_allowed=overall_allowed,
        results=tuple(results),
        blocking_limit=blocking_limit,
        critical_count=critical_count,
        warning_count=warning_count,
        checked_at=now,
        state_version=snapshot.version,
    )


# ---------------------------------------------------------------------------
# Individual limit helpers
# ---------------------------------------------------------------------------

def _check_gross_exposure(
    snapshot: PortfolioSnapshot,
    proposed_value: Decimal,
    config: PortfolioConfig,
    equity: Decimal,
) -> LimitCheckResult:
    """Check max gross portfolio exposure."""
    limit = config.max_deployable(equity)
    current = snapshot.exposure.gross_exposure
    projected = current + proposed_value
    allowed = projected <= limit
    severity = _severity(projected, limit)
    return LimitCheckResult(
        limit_name="max_gross_exposure",
        allowed=allowed,
        current_value=current,
        proposed_value=proposed_value,
        configured_limit=limit,
        severity=severity,
        reason="" if allowed else f"Gross exposure {projected} would exceed limit {limit}",
        state_version=snapshot.version,
    )


def _check_open_positions(
    snapshot: PortfolioSnapshot,
    config: PortfolioConfig,
) -> LimitCheckResult:
    """Check max open positions count (CRITICAL if at limit)."""
    current_count = len(snapshot.open_positions)
    limit = config.max_open_positions
    allowed = current_count < limit
    severity: LimitSeverity
    if not allowed:
        severity = LimitSeverity.WARNING
    elif current_count >= int(limit * float(_WARNING_THRESHOLD_PCT)):
        severity = LimitSeverity.WARNING
    else:
        severity = LimitSeverity.INFO
    return LimitCheckResult(
        limit_name="max_open_positions",
        allowed=allowed,
        current_value=Decimal(str(current_count)),
        proposed_value=Decimal("1"),
        configured_limit=Decimal(str(limit)),
        severity=severity,
        reason=(
            "" if allowed
            else f"Open positions {current_count} already at limit {limit}"
        ),
        state_version=snapshot.version,
    )


def _check_pending_orders(
    snapshot: PortfolioSnapshot,
    config: PortfolioConfig,
) -> LimitCheckResult:
    """Check max pending orders count."""
    current_count = snapshot.pending_order_count
    limit = config.max_pending_orders
    allowed = current_count < limit
    severity: LimitSeverity
    if not allowed:
        severity = LimitSeverity.WARNING
    elif current_count >= int(limit * float(_WARNING_THRESHOLD_PCT)):
        severity = LimitSeverity.WARNING
    else:
        severity = LimitSeverity.INFO
    return LimitCheckResult(
        limit_name="max_pending_orders",
        allowed=allowed,
        current_value=Decimal(str(current_count)),
        proposed_value=Decimal("1"),
        configured_limit=Decimal(str(limit)),
        severity=severity,
        reason=(
            "" if allowed
            else f"Pending orders {current_count} already at limit {limit}"
        ),
        state_version=snapshot.version,
    )


def _check_daily_loss(
    snapshot: PortfolioSnapshot,
    config: PortfolioConfig,
    equity: Decimal,
) -> LimitCheckResult:
    """Check max daily loss limit. CRITICAL if breached."""
    limit_amount = config.max_daily_loss_amount(equity)
    daily_pnl = snapshot.pnl.daily_pnl
    # Breach when daily_pnl < -limit_amount (negative = loss).
    allowed = daily_pnl >= -limit_amount
    severity: LimitSeverity
    if not allowed:
        severity = LimitSeverity.CRITICAL
    elif daily_pnl < -(limit_amount * _WARNING_THRESHOLD_PCT):
        severity = LimitSeverity.WARNING
    else:
        severity = LimitSeverity.INFO
    return LimitCheckResult(
        limit_name="max_daily_loss",
        allowed=allowed,
        current_value=daily_pnl,
        proposed_value=Decimal("0"),
        configured_limit=-limit_amount,
        severity=severity,
        reason=(
            "" if allowed
            else f"Daily P&L {daily_pnl} has breached max daily loss limit -{limit_amount}"
        ),
        state_version=snapshot.version,
    )


def _check_drawdown(
    snapshot: PortfolioSnapshot,
    config: PortfolioConfig,
) -> LimitCheckResult:
    """Check max drawdown limit. CRITICAL if breached."""
    drawdown = snapshot.pnl.drawdown
    limit = config.max_drawdown_pct
    allowed = drawdown <= limit
    severity: LimitSeverity
    if not allowed:
        severity = LimitSeverity.CRITICAL
    elif drawdown >= limit * _WARNING_THRESHOLD_PCT:
        severity = LimitSeverity.WARNING
    else:
        severity = LimitSeverity.INFO
    return LimitCheckResult(
        limit_name="max_drawdown",
        allowed=allowed,
        current_value=drawdown,
        proposed_value=Decimal("0"),
        configured_limit=limit,
        severity=severity,
        reason=(
            "" if allowed
            else f"Drawdown {float(drawdown):.2%} exceeds max {float(limit):.2%}"
        ),
        state_version=snapshot.version,
    )


def _check_cash_reserve(
    snapshot: PortfolioSnapshot,
    proposed_value: Decimal,
    config: PortfolioConfig,
    equity: Decimal,
) -> LimitCheckResult:
    """Check that cash reserve floor is maintained after the proposed order.

    Rule: available_cash >= reserve_amount + proposed_value.
    CRITICAL if breached.
    """
    reserve = config.reserve_amount(equity)
    available = snapshot.cash.available
    required = reserve + proposed_value
    allowed = available >= required
    severity: LimitSeverity
    if not allowed:
        severity = LimitSeverity.CRITICAL
    elif available < required + (reserve * _WARNING_THRESHOLD_PCT):
        severity = LimitSeverity.WARNING
    else:
        severity = LimitSeverity.INFO
    return LimitCheckResult(
        limit_name="cash_reserve",
        allowed=allowed,
        current_value=available,
        proposed_value=proposed_value,
        configured_limit=reserve,
        severity=severity,
        reason=(
            "" if allowed
            else (
                f"Available cash {available} is below required reserve {reserve} "
                f"+ proposed {proposed_value} = {required}"
            )
        ),
        state_version=snapshot.version,
    )


def _severity(projected: Decimal, limit: Decimal) -> LimitSeverity:
    """Generic severity for exposure-style limits."""
    if limit <= Decimal("0"):
        return LimitSeverity.INFO
    if projected > limit:
        return LimitSeverity.CRITICAL
    if projected >= limit * _WARNING_THRESHOLD_PCT:
        return LimitSeverity.WARNING
    return LimitSeverity.INFO


# ---------------------------------------------------------------------------
# PortfolioLimitEngine class — injectable façade for PortfolioService
# ---------------------------------------------------------------------------

from .contracts import ExposureSnapshot  # noqa: E402


class PortfolioLimitEngine:
    """Object-oriented façade around the module-level check_all_limits function.

    Wraps the functional limit-checking logic so that PortfolioService can use
    dependency injection for testing and composition.
    """

    def __init__(self, config: PortfolioConfig | None = None) -> None:
        from .config import DEFAULT_CONFIG as _DEFAULT_CONFIG
        self.config: PortfolioConfig = config or _DEFAULT_CONFIG

    async def check_all_limits(
        self,
        snapshot: "PortfolioSnapshot",
        exposure: "ExposureSnapshot",
        proposed_instrument_token: int | None = None,
        proposed_value: Decimal = Decimal("0"),
        proposed_strategy_id: str | None = None,
        proposed_sector: str | None = None,
    ) -> LimitCheckReport:
        """Check all portfolio limits for a proposed action.

        Parameters
        ----------
        snapshot:
            Current portfolio state.
        exposure:
            Current exposure snapshot (pre-computed, may include proposed value).
        proposed_instrument_token:
            Target instrument for the proposed trade.
        proposed_value:
            Estimated monetary value of the proposed trade.
        proposed_strategy_id:
            Strategy initiating the trade.
        proposed_sector:
            Sector of the proposed trade.

        Returns
        -------
        LimitCheckReport
        """
        return check_all_limits(
            snapshot=snapshot,
            proposed_instrument_token=proposed_instrument_token,
            proposed_value=proposed_value,
            proposed_strategy_id=proposed_strategy_id,
            proposed_sector=proposed_sector,
            config=self.config,
        )
