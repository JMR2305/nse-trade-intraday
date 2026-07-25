"""RC-10C1 Portfolio Core — Exposure Engine.

Derives a full ExposureSnapshot from open positions and pending order
reservations, then provides per-instrument / sector / strategy limit checks.

No broker calls, no order placement.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from .config import PortfolioConfig
from .contracts import (
    ExposureSnapshot,
    InstrumentExposure,
    LimitCheckResult,
    LimitSeverity,
    PortfolioPosition,
    PositionSide,
    SectorExposure,
    StrategyExposure,
)

logger = logging.getLogger(__name__)

# Fraction of the limit that triggers a WARNING (not yet breached but close).
_WARNING_THRESHOLD_PCT = Decimal("0.80")


# ---------------------------------------------------------------------------
# Primary calculation
# ---------------------------------------------------------------------------

def calculate_exposure(
    positions: list[PortfolioPosition],
    pending_reservations: dict[str, dict[str, Any]],
    portfolio_equity: Decimal,
    config: PortfolioConfig,
    stale_price_threshold_s: float,
) -> ExposureSnapshot:
    """Derive a full ExposureSnapshot from positions and pending reservations.

    Args:
        positions: All currently open (or reducing) positions.
        pending_reservations: Mapping of reservation_id to dict with at least
            ``instrument_token`` and ``estimated_value`` keys.
        portfolio_equity: Total portfolio equity used to compute percentages.
        config: Validated portfolio configuration.
        stale_price_threshold_s: Market price older than this many seconds is
            considered stale.

    Returns:
        ExposureSnapshot capturing gross/net exposure, per-instrument,
        per-sector, and per-strategy breakdowns, and a staleness flag.
    """
    now = datetime.now(timezone.utc)

    long_exposure = Decimal("0")
    short_exposure = Decimal("0")
    stale_prices = False

    # instrument_token -> {symbol, absolute_value, pending_value}
    instrument_map: dict[int, dict[str, Any]] = {}
    # sector -> {absolute_value, position_count}
    sector_map: dict[str, dict[str, Any]] = {}
    # strategy_id -> {absolute_value, position_count}
    strategy_map: dict[str, dict[str, Any]] = {}

    for pos in positions:
        price = (
            pos.last_market_price
            if pos.last_market_price is not None
            else pos.average_entry_price
        )
        position_exposure = Decimal(str(pos.open_quantity)) * price

        if pos.side == PositionSide.LONG:
            long_exposure += position_exposure
        else:
            short_exposure += position_exposure

        # Check price staleness.
        if pos.last_price_as_of is not None:
            age_s = (now - pos.last_price_as_of).total_seconds()
            if age_s > stale_price_threshold_s:
                stale_prices = True
        else:
            stale_prices = True

        # Instrument accumulation.
        token = pos.instrument_token
        if token not in instrument_map:
            instrument_map[token] = {
                "symbol": pos.instrument_symbol,
                "absolute_value": Decimal("0"),
                "pending_value": Decimal("0"),
            }
        instrument_map[token]["absolute_value"] += position_exposure

        # Sector accumulation.
        sector = pos.sector or "UNKNOWN"
        if sector not in sector_map:
            sector_map[sector] = {"absolute_value": Decimal("0"), "position_count": 0}
        sector_map[sector]["absolute_value"] += position_exposure
        sector_map[sector]["position_count"] += 1

        # Strategy accumulation.
        strategy_id = pos.strategy_id or "UNKNOWN"
        if strategy_id not in strategy_map:
            strategy_map[strategy_id] = {
                "absolute_value": Decimal("0"),
                "position_count": 0,
            }
        strategy_map[strategy_id]["absolute_value"] += position_exposure
        strategy_map[strategy_id]["position_count"] += 1

    # Pending order exposure.
    pending_order_exposure = Decimal("0")
    for reservation in pending_reservations.values():
        est_value = Decimal(str(reservation.get("estimated_value", "0")))
        pending_order_exposure += est_value
        res_token = reservation.get("instrument_token")
        if res_token is not None:
            res_token = int(res_token)
            if res_token not in instrument_map:
                instrument_map[res_token] = {
                    "symbol": reservation.get("instrument_symbol", str(res_token)),
                    "absolute_value": Decimal("0"),
                    "pending_value": Decimal("0"),
                }
            instrument_map[res_token]["pending_value"] += est_value

    # Build sub-models.
    equity_safe = portfolio_equity if portfolio_equity > Decimal("0") else Decimal("1")

    instrument_exposures = tuple(
        InstrumentExposure(
            instrument_token=token,
            instrument_symbol=data["symbol"],
            absolute_value=data["absolute_value"],
            portfolio_pct=(data["absolute_value"] / equity_safe).quantize(
                Decimal("0.0001")
            ),
            pending_value=data["pending_value"],
            as_of=now,
        )
        for token, data in instrument_map.items()
    )

    sector_exposures = tuple(
        SectorExposure(
            sector=sector,
            absolute_value=data["absolute_value"],
            portfolio_pct=(data["absolute_value"] / equity_safe).quantize(
                Decimal("0.0001")
            ),
            position_count=data["position_count"],
            as_of=now,
        )
        for sector, data in sector_map.items()
    )

    strategy_exposures = tuple(
        StrategyExposure(
            strategy_id=strategy_id,
            absolute_value=data["absolute_value"],
            portfolio_pct=(data["absolute_value"] / equity_safe).quantize(
                Decimal("0.0001")
            ),
            position_count=data["position_count"],
            as_of=now,
        )
        for strategy_id, data in strategy_map.items()
    )

    gross_exposure = long_exposure + short_exposure
    net_exposure = long_exposure - short_exposure

    logger.debug(
        "exposure_calculated|long=%s|short=%s|gross=%s|net=%s|pending=%s|stale=%s",
        long_exposure, short_exposure, gross_exposure,
        net_exposure, pending_order_exposure, stale_prices,
    )

    return ExposureSnapshot(
        gross_exposure=gross_exposure,
        net_exposure=net_exposure,
        long_exposure=long_exposure,
        short_exposure=short_exposure,
        pending_order_exposure=pending_order_exposure,
        reserved_capital_exposure=pending_order_exposure,
        instrument_exposures=instrument_exposures,
        sector_exposures=sector_exposures,
        strategy_exposures=strategy_exposures,
        portfolio_equity=portfolio_equity,
        stale_prices=stale_prices,
        as_of=now,
    )


# ---------------------------------------------------------------------------
# Individual limit checks
# ---------------------------------------------------------------------------

def check_instrument_exposure(
    instrument_token: int,
    proposed_value: Decimal,
    snapshot: ExposureSnapshot,
    config: PortfolioConfig,
    equity: Decimal,
) -> LimitCheckResult:
    """Check whether a proposed order would breach instrument exposure limits.

    Args:
        instrument_token: The instrument to check.
        proposed_value: Gross notional value of the proposed order.
        snapshot: Current exposure snapshot.
        config: Portfolio configuration.
        equity: Current portfolio equity for limit computation.

    Returns:
        LimitCheckResult indicating whether the limit is respected.
    """
    limit = config.max_instrument_value(equity)
    current = _instrument_current(snapshot, instrument_token)
    projected = current + proposed_value
    allowed = projected <= limit
    severity = _exposure_severity(projected, limit)
    return LimitCheckResult(
        limit_name="max_instrument_exposure",
        allowed=allowed,
        current_value=current,
        proposed_value=proposed_value,
        configured_limit=limit,
        severity=severity,
        reason=(
            ""
            if allowed
            else (
                f"Instrument {instrument_token} projected exposure {projected} "
                f"exceeds limit {limit}"
            )
        ),
    )


def check_sector_exposure(
    sector: str,
    proposed_value: Decimal,
    snapshot: ExposureSnapshot,
    config: PortfolioConfig,
    equity: Decimal,
) -> LimitCheckResult:
    """Check whether a proposed order would breach sector exposure limits.

    Args:
        sector: Sector name to check.
        proposed_value: Gross notional value of the proposed order.
        snapshot: Current exposure snapshot.
        config: Portfolio configuration.
        equity: Current portfolio equity for limit computation.

    Returns:
        LimitCheckResult indicating whether the limit is respected.
    """
    limit = config.max_sector_value(equity)
    current = _sector_current(snapshot, sector)
    projected = current + proposed_value
    allowed = projected <= limit
    severity = _exposure_severity(projected, limit)
    return LimitCheckResult(
        limit_name="max_sector_exposure",
        allowed=allowed,
        current_value=current,
        proposed_value=proposed_value,
        configured_limit=limit,
        severity=severity,
        reason=(
            ""
            if allowed
            else (
                f"Sector '{sector}' projected exposure {projected} "
                f"exceeds limit {limit}"
            )
        ),
    )


def check_strategy_exposure(
    strategy_id: str,
    proposed_value: Decimal,
    snapshot: ExposureSnapshot,
    config: PortfolioConfig,
    equity: Decimal,
) -> LimitCheckResult:
    """Check whether a proposed order would breach strategy exposure limits.

    Args:
        strategy_id: Strategy identifier to check.
        proposed_value: Gross notional value of the proposed order.
        snapshot: Current exposure snapshot.
        config: Portfolio configuration.
        equity: Current portfolio equity for limit computation.

    Returns:
        LimitCheckResult indicating whether the limit is respected.
    """
    limit = config.max_strategy_value(equity)
    current = _strategy_current(snapshot, strategy_id)
    projected = current + proposed_value
    allowed = projected <= limit
    severity = _exposure_severity(projected, limit)
    return LimitCheckResult(
        limit_name="max_strategy_exposure",
        allowed=allowed,
        current_value=current,
        proposed_value=proposed_value,
        configured_limit=limit,
        severity=severity,
        reason=(
            ""
            if allowed
            else (
                f"Strategy '{strategy_id}' projected exposure {projected} "
                f"exceeds limit {limit}"
            )
        ),
    )


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _instrument_current(snapshot: ExposureSnapshot, instrument_token: int) -> Decimal:
    for ie in snapshot.instrument_exposures:
        if ie.instrument_token == instrument_token:
            return ie.absolute_value + ie.pending_value
    return Decimal("0")


def _sector_current(snapshot: ExposureSnapshot, sector: str) -> Decimal:
    for se in snapshot.sector_exposures:
        if se.sector == sector:
            return se.absolute_value
    return Decimal("0")


def _strategy_current(snapshot: ExposureSnapshot, strategy_id: str) -> Decimal:
    for ste in snapshot.strategy_exposures:
        if ste.strategy_id == strategy_id:
            return ste.absolute_value
    return Decimal("0")


def _exposure_severity(projected: Decimal, limit: Decimal) -> LimitSeverity:
    """Return CRITICAL if limit is breached, WARNING if near it, INFO otherwise."""
    if limit <= Decimal("0"):
        return LimitSeverity.INFO
    if projected > limit:
        return LimitSeverity.CRITICAL
    if projected >= limit * _WARNING_THRESHOLD_PCT:
        return LimitSeverity.WARNING
    return LimitSeverity.INFO


# ---------------------------------------------------------------------------
# ExposureEngine class — injectable façade for PortfolioService
# ---------------------------------------------------------------------------

from .contracts import PortfolioSnapshot  # noqa: E402 (local import to avoid circular)


class ExposureEngine:
    """Object-oriented façade around the module-level calculate_exposure function.

    Wraps the functional exposure logic so that PortfolioService can use
    dependency injection for testing and composition.
    """

    def __init__(self, config: PortfolioConfig | None = None) -> None:
        from .config import DEFAULT_CONFIG as _DEFAULT_CONFIG
        self.config: PortfolioConfig = config or _DEFAULT_CONFIG

    async def calculate_exposure(
        self,
        snapshot: "PortfolioSnapshot",
        instrument_token: int | None = None,
        proposed_value: Decimal = Decimal("0"),
        strategy_id: str | None = None,
        sector: str | None = None,
    ) -> ExposureSnapshot:
        """Compute the current portfolio exposure, optionally including a proposal.

        Parameters
        ----------
        snapshot:
            Current portfolio state.
        instrument_token:
            Specific instrument to analyse (optional).
        proposed_value:
            Estimated value of a proposed new trade.
        strategy_id:
            Filter context (optional).
        sector:
            Sector context (optional).

        Returns
        -------
        ExposureSnapshot
        """
        positions = list(snapshot.open_positions)
        portfolio_equity = (
            snapshot.pnl.current_equity
            if snapshot.pnl.current_equity and snapshot.pnl.current_equity > Decimal("0")
            else snapshot.cash.total or Decimal("1")
        )

        # Build pending_reservations from blocked cash (simplified)
        pending_reservations: dict[str, dict[str, Any]] = {}
        if snapshot.cash.blocked > Decimal("0") and instrument_token is not None:
            pending_reservations["_proposed"] = {
                "instrument_token": instrument_token,
                "estimated_value": proposed_value,
            }

        return calculate_exposure(
            positions=positions,
            pending_reservations=pending_reservations,
            portfolio_equity=portfolio_equity,
            config=self.config,
            stale_price_threshold_s=self.config.stale_price_threshold_s,
        )
