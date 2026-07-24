"""RC-10C1 Portfolio Core — Position Sizer.

Converts a PositionSizeRequest (entry/stop price, signal confidence, etc.)
into a PositionSizeDecision holding the approved quantity after all portfolio
constraints are applied.

No broker calls, no order placement.  RC-8 uses the approved_quantity from
this module as an advisory input — it may still override or reject.
"""
from __future__ import annotations

import logging
import math
from datetime import datetime, timezone
from decimal import Decimal

from .config import PortfolioConfig
from .contracts import (
    PositionSizeDecision,
    PositionSizeRequest,
    PortfolioSnapshot,
)
from .exceptions import StalePortfolioStateError

logger = logging.getLogger(__name__)

# Default stop distance as a fraction of entry price when no stop is given.
_DEFAULT_STOP_PCT = Decimal("0.02")


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------

def round_to_lot(qty: int, lot_size: int) -> int:
    """Floor *qty* to the nearest multiple of *lot_size*.

    Args:
        qty: Raw (unconstrained) quantity.
        lot_size: Minimum tradeable lot multiple (>= 1).

    Returns:
        Largest multiple of lot_size that does not exceed qty.

    Examples:
        >>> round_to_lot(153, 50)
        150
        >>> round_to_lot(50, 50)
        50
        >>> round_to_lot(49, 50)
        0
    """
    if lot_size <= 0:
        raise ValueError(f"lot_size must be >= 1, got {lot_size}")
    if qty <= 0:
        return 0
    return (qty // lot_size) * lot_size


def estimate_order_value(qty: int, price: Decimal) -> Decimal:
    """Estimate the gross notional value of an order.

    Args:
        qty: Number of units.
        price: Per-unit price.

    Returns:
        qty * price, rounded to 2 decimal places.
    """
    if qty <= 0 or price <= Decimal("0"):
        return Decimal("0")
    return (Decimal(str(qty)) * price).quantize(Decimal("0.01"))


# ---------------------------------------------------------------------------
# Core sizer
# ---------------------------------------------------------------------------

def calculate_size(
    request: PositionSizeRequest,
    snapshot: PortfolioSnapshot,
    config: PortfolioConfig,
) -> PositionSizeDecision:
    """Calculate position size subject to risk and portfolio constraints.

    Steps:
      1. Staleness guard.
      2. Determine available capital (request override or portfolio net buying power).
      3. Compute risk amount = config.risk_amount(available_capital).
      4. Derive risk_per_share from stop distance or default 2% of entry.
      5. raw_qty = floor(risk_amount / risk_per_share); round down to lot_size.
      6. Apply constraints:
         a. max_order_value cap.
         b. min_order_value floor (reject if below).
         c. instrument exposure cap.
         d. AI confidence scaling (optional).
      7. Return PositionSizeDecision.

    Args:
        request: Sizing inputs including instrument, price, and stop.
        snapshot: Current portfolio snapshot.
        config: Validated portfolio configuration.

    Returns:
        PositionSizeDecision with approved_quantity and constraint metadata.

    Raises:
        StalePortfolioStateError: Snapshot exceeds stale threshold.
    """
    now = datetime.now(timezone.utc)
    applied_constraints: list[str] = []

    # ── Step 1: Staleness guard ────────────────────────────────────────────
    state_age_s = (now - snapshot.snapshotted_at).total_seconds()
    if state_age_s > config.stale_state_threshold_s:
        raise StalePortfolioStateError(
            f"Portfolio snapshot is {state_age_s:.1f}s old "
            f"(threshold {config.stale_state_threshold_s}s); cannot size position"
        )

    equity = snapshot.pnl.current_equity

    # ── Step 2: Available capital ──────────────────────────────────────────
    if request.available_capital is not None:
        available_capital = request.available_capital
    else:
        available_capital = snapshot.buying_power.net

    # ── Step 3: Risk amount — always based on portfolio equity, not available
    #           capital (risk per trade is a % of total equity).
    risk_amount = config.risk_amount(equity)

    # ── Step 4: Risk per share ─────────────────────────────────────────────
    entry = request.entry_price
    if request.stop_price is not None:
        risk_per_share = abs(entry - request.stop_price)
    else:
        risk_per_share = entry * _DEFAULT_STOP_PCT

    if risk_per_share <= Decimal("0"):
        logger.warning(
            "position_sizer|instrument=%s|risk_per_share=%s|forcing_reject",
            request.instrument_symbol, risk_per_share,
        )
        return _reject(
            request=request,
            raw_qty=0,
            rejection_reason="ZERO_RISK_PER_SHARE",
            applied_constraints=applied_constraints,
        )

    # ── Step 5: Raw quantity + lot rounding ───────────────────────────────
    raw_qty_decimal = risk_amount / risk_per_share
    raw_qty = int(math.floor(raw_qty_decimal))
    approved_qty = round_to_lot(raw_qty, request.lot_size)

    logger.debug(
        "position_sizer|instrument=%s|risk_amount=%s|rps=%s|raw=%d|lot_qty=%d",
        request.instrument_symbol, risk_amount, risk_per_share, raw_qty, approved_qty,
    )

    # ── Step 6a: max_order_value cap ──────────────────────────────────────
    order_value = estimate_order_value(approved_qty, entry)
    if approved_qty > 0 and order_value > config.max_order_value:
        capped_raw = int(math.floor(config.max_order_value / entry))
        capped_qty = round_to_lot(capped_raw, request.lot_size)
        if capped_qty < approved_qty:
            approved_qty = capped_qty
            applied_constraints.append("MAX_ORDER_VALUE")

    # ── Step 6b: min_order_value floor ────────────────────────────────────
    order_value = estimate_order_value(approved_qty, entry)
    if order_value < config.min_order_value:
        applied_constraints.append("MIN_ORDER_VALUE")
        return _reject(
            request=request,
            raw_qty=raw_qty,
            rejection_reason="BELOW_MIN_ORDER_VALUE",
            applied_constraints=applied_constraints,
        )

    # ── Step 6c: Instrument exposure cap ──────────────────────────────────
    max_instrument = config.max_instrument_value(equity)
    existing_instrument_exposure = _existing_instrument_exposure(
        snapshot, request.instrument_token
    )
    instrument_headroom = max(Decimal("0"), max_instrument - existing_instrument_exposure)
    order_value = estimate_order_value(approved_qty, entry)
    if order_value > instrument_headroom:
        if instrument_headroom <= Decimal("0"):
            applied_constraints.append("INSTRUMENT_EXPOSURE_CAP")
            return _reject(
                request=request,
                raw_qty=raw_qty,
                rejection_reason="INSTRUMENT_EXPOSURE_LIMIT_REACHED",
                applied_constraints=applied_constraints,
            )
        capped_raw = int(math.floor(instrument_headroom / entry))
        capped_qty = round_to_lot(capped_raw, request.lot_size)
        if capped_qty < approved_qty:
            approved_qty = capped_qty
            applied_constraints.append("INSTRUMENT_EXPOSURE_CAP")

    # Re-check min after instrument cap.
    order_value = estimate_order_value(approved_qty, entry)
    if order_value < config.min_order_value:
        applied_constraints.append("MIN_ORDER_VALUE_POST_INSTRUMENT_CAP")
        return _reject(
            request=request,
            raw_qty=raw_qty,
            rejection_reason="BELOW_MIN_ORDER_VALUE",
            applied_constraints=applied_constraints,
        )

    # ── Step 6d: AI confidence scaling (optional) ─────────────────────────
    if (
        config.use_ai_confidence_sizing
        and request.signal_confidence >= config.ai_confidence_min
    ):
        confidence = request.signal_confidence
        scaled_raw = int(math.floor(int(approved_qty) * float(confidence)))
        scaled_qty = round_to_lot(scaled_raw, request.lot_size)
        if scaled_qty != approved_qty:
            approved_qty = scaled_qty
            applied_constraints.append("AI_CONFIDENCE_SCALING")
        # Re-check min after confidence scaling.
        order_value = estimate_order_value(approved_qty, entry)
        if order_value < config.min_order_value:
            applied_constraints.append("MIN_ORDER_VALUE_POST_CONFIDENCE")
            return _reject(
                request=request,
                raw_qty=raw_qty,
                rejection_reason="BELOW_MIN_ORDER_VALUE",
                applied_constraints=applied_constraints,
            )

    # ── Guard: zero quantity ───────────────────────────────────────────────
    if approved_qty == 0:
        return _reject(
            request=request,
            raw_qty=raw_qty,
            rejection_reason="ZERO_QUANTITY_AFTER_CONSTRAINTS",
            applied_constraints=applied_constraints,
        )

    # ── Build approved decision ────────────────────────────────────────────
    final_order_value = estimate_order_value(approved_qty, entry)
    pct_of_portfolio = (
        (final_order_value / equity).quantize(Decimal("0.0001"))
        if equity > Decimal("0")
        else Decimal("0")
    )
    risk_per_share_safe = risk_per_share if risk_per_share > Decimal("0") else Decimal("1")
    estimated_risk = (Decimal(str(approved_qty)) * risk_per_share_safe).quantize(
        Decimal("0.01")
    )

    logger.info(
        "position_sizer|approved|instrument=%s|qty=%d|value=%s|pct=%.2f%%",
        request.instrument_symbol,
        approved_qty,
        final_order_value,
        float(pct_of_portfolio) * 100,
    )

    return PositionSizeDecision(
        request_id=request.request_id,
        instrument_token=request.instrument_token,
        side=request.side,
        raw_quantity=raw_qty,
        approved_quantity=approved_qty,
        estimated_order_value=final_order_value,
        estimated_risk=estimated_risk,
        pct_of_portfolio=pct_of_portfolio,
        applied_constraints=tuple(applied_constraints),
        approved=True,
        rejection_reason=None,
        state_version=snapshot.version,
    )


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _existing_instrument_exposure(
    snapshot: PortfolioSnapshot, instrument_token: int
) -> Decimal:
    """Sum gross exposure of existing open positions for *instrument_token*."""
    total = Decimal("0")
    for pos in snapshot.open_positions:
        if pos.instrument_token == instrument_token:
            total += pos.gross_exposure
    return total


def _reject(
    *,
    request: PositionSizeRequest,
    raw_qty: int,
    rejection_reason: str,
    applied_constraints: list[str],
) -> PositionSizeDecision:
    """Build a rejected PositionSizeDecision."""
    return PositionSizeDecision(
        request_id=request.request_id,
        instrument_token=request.instrument_token,
        side=request.side,
        raw_quantity=raw_qty,
        approved_quantity=0,
        estimated_order_value=Decimal("0"),
        estimated_risk=Decimal("0"),
        pct_of_portfolio=Decimal("0"),
        applied_constraints=tuple(applied_constraints),
        approved=False,
        rejection_reason=rejection_reason,
    )


# ---------------------------------------------------------------------------
# PositionSizer class — injectable façade for PortfolioService
# ---------------------------------------------------------------------------

class PositionSizer:
    """Object-oriented façade around the module-level calculate_size function.

    Wraps the functional position-sizing logic so that PortfolioService
    can use dependency injection for testing and composition.
    """

    def __init__(self, config: PortfolioConfig | None = None) -> None:
        from .config import DEFAULT_CONFIG as _DEFAULT_CONFIG
        self.config: PortfolioConfig = config or _DEFAULT_CONFIG

    async def calculate_size(
        self,
        request: PositionSizeRequest,
        snapshot: PortfolioSnapshot,
    ) -> PositionSizeDecision:
        """Calculate position size by delegating to the module-level function.

        Parameters
        ----------
        request:
            Position size request parameters.
        snapshot:
            Current portfolio state.

        Returns
        -------
        PositionSizeDecision
        """
        return calculate_size(request=request, snapshot=snapshot, config=self.config)
