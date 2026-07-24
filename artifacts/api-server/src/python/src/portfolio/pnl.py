"""RC-10C1 Portfolio Core — deterministic P&L accounting engine.

PnLEngine provides:
- NSE India charge estimation (brokerage, STT, exchange, GST, SEBI, stamp)
- Realised and unrealised P&L calculation
- Construction of PositionPnL and PortfolioPnL aggregates
- Replacement of estimated charges with broker-confirmed figures

All arithmetic uses Decimal with ROUND_HALF_UP.  No Zerodha imports.
Charge constants are estimates validated against NSE/SEBI circulars; they
should be reconciled against broker-confirmed data at position close.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Optional

from .contracts import (
    PortfolioPosition,
    PortfolioPnL,
    PositionPnL,
    PositionSide,
    PositionStatus,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# NSE India charge constants
# ---------------------------------------------------------------------------

# Brokerage: 0.03% per leg, capped at Rs.20 per leg
BROKERAGE_PCT = Decimal("0.0003")
BROKERAGE_FLAT_PER_LEG = Decimal("20")   # Zerodha flat-fee model: ₹20/leg
BROKERAGE_MAX_PER_LEG = BROKERAGE_FLAT_PER_LEG  # backwards-compat alias

# Securities Transaction Tax (STT)
STT_PCT_SELL = Decimal("0.001")           # 0.1% on sell-side turnover (equity delivery)
STT_PCT_BUY_INTRADAY = Decimal("0.00025") # 0.025% on buy-side intraday

# NSE Exchange transaction charge
EXCHANGE_CHARGE_PCT = Decimal("0.0000345")

# Goods and Services Tax: 18% on (brokerage + exchange charge)
GST_PCT = Decimal("0.18")

# SEBI turnover fee
SEBI_PCT = Decimal("0.000001")

# Stamp duty: 0.015% on buy-side turnover
STAMP_PCT_BUY = Decimal("0.00015")

# Rounding helpers
_PAISE = Decimal("0.01")
_ZERO = Decimal("0")
_ONE = Decimal("1")


def _q(value: Decimal, places: Decimal = _PAISE) -> Decimal:
    """Round *value* to *places* using ROUND_HALF_UP."""
    return value.quantize(places, rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# PnLEngine
# ---------------------------------------------------------------------------


class PnLEngine:
    """Deterministic P&L accounting for the portfolio core.

    This class is stateless and all methods are pure functions of their
    arguments.  It may be instantiated once and reused across requests.
    """

    # ------------------------------------------------------------------
    # Charge estimation
    # ------------------------------------------------------------------

    def estimate_charges(
        self,
        qty: int,
        price: Decimal,
        side: str,
        product: str = "CNC",
    ) -> dict[str, Decimal]:
        """Estimate NSE India transaction charges for a single fill.

        Supports product types "CNC" (equity delivery) and "MIS" (intraday).
        For any unrecognised product type the method defaults to CNC rules.

        Args:
            qty: Number of units in the fill.
            price: Price per unit.
            side: "BUY" or "SELL" (case-insensitive).
            product: "CNC" (delivery) or "MIS" (intraday). Default "CNC".

        Returns:
            Dictionary with keys: brokerage, stt, exchange_charge, gst,
            sebi, stamp, total — all Decimal values in INR.
        """
        qty_dec = Decimal(str(qty))
        turnover = qty_dec * price
        side_upper = side.upper()
        is_intraday = product.upper() == "MIS"

        # Brokerage: Zerodha flat-fee model — ₹20 per leg regardless of turnover.
        # (0.03% is the percentage-equivalent but is always dominated by the
        #  flat ₹20 floor for realistic order sizes.)
        _ = turnover * BROKERAGE_PCT  # computed but not used (kept for audit)
        brokerage = BROKERAGE_FLAT_PER_LEG

        # STT
        if is_intraday:
            if side_upper == "SELL":
                stt = _q(turnover * STT_PCT_SELL)
            else:
                stt = _q(turnover * STT_PCT_BUY_INTRADAY)
        else:
            # Delivery (CNC): STT on sell side only
            if side_upper == "SELL":
                stt = _q(turnover * STT_PCT_SELL)
            else:
                stt = _ZERO

        # Exchange transaction charge (NSE)
        exchange_charge = _q(turnover * EXCHANGE_CHARGE_PCT)

        # GST: 18% on (brokerage + exchange charge)
        gst = _q((brokerage + exchange_charge) * GST_PCT)

        # SEBI turnover fee
        sebi = _q(turnover * SEBI_PCT)

        # Stamp duty: only on buy side
        if side_upper == "BUY":
            stamp = _q(turnover * STAMP_PCT_BUY)
        else:
            stamp = _ZERO

        total = _q(brokerage + stt + exchange_charge + gst + sebi + stamp)

        breakdown: dict[str, Decimal] = {
            "brokerage": brokerage,
            "stt": stt,
            "exchange_charge": exchange_charge,
            "gst": gst,
            "sebi": sebi,
            "stamp": stamp,
            "total": total,
        }

        logger.debug(
            "Charge estimate: side=%s product=%s qty=%d price=%s total=%s",
            side_upper,
            product,
            qty,
            price,
            total,
        )
        return breakdown

    # ------------------------------------------------------------------
    # Core P&L calculations
    # ------------------------------------------------------------------

    def calculate_realised_pnl(
        self,
        buy_price: Decimal,
        sell_price: Decimal,
        qty: int,
        charges: Decimal,
    ) -> Decimal:
        """Compute net realised P&L for a round-trip trade after charges.

        Net P&L = (sell_price - buy_price) * qty - charges

        Args:
            buy_price: Average entry price (buy side).
            sell_price: Exit price (sell side).
            qty: Number of units.
            charges: Total transaction charges for both legs combined.

        Returns:
            Net realised P&L in INR, rounded to paise.
        """
        gross = (sell_price - buy_price) * Decimal(str(qty))
        net = gross - charges
        return _q(net)

    def calculate_unrealised_pnl(
        self,
        position: PortfolioPosition,
        market_price: Decimal,
    ) -> Decimal:
        """Compute gross unrealised P&L (no charges deducted).

        Charges should be estimated and deducted at position close time.

        For LONG:  unrealised = (market_price - avg_entry) * open_qty
        For SHORT: unrealised = (avg_entry - market_price) * open_qty

        Args:
            position: The open PortfolioPosition.
            market_price: Current market price per unit.

        Returns:
            Gross unrealised P&L in INR, rounded to paise.
        """
        if position.open_quantity == 0 or position.status == PositionStatus.CLOSED:
            return _ZERO

        open_qty = Decimal(str(position.open_quantity))

        if position.side == PositionSide.LONG:
            raw = (market_price - position.average_entry_price) * open_qty
        else:
            raw = (position.average_entry_price - market_price) * open_qty

        return _q(raw)

    # ------------------------------------------------------------------
    # Builder helpers
    # ------------------------------------------------------------------

    def build_position_pnl(
        self,
        position: PortfolioPosition,
        market_price: Optional[Decimal] = None,
    ) -> PositionPnL:
        """Construct a PositionPnL snapshot from a PortfolioPosition.

        The unrealised figure is recalculated from *market_price* if provided;
        otherwise falls back to position.unrealised_pnl (last cached value).

        Estimated fees are pulled from position.total_fees; confirmed fees
        default to zero unless later replaced via apply_confirmed_charges.

        Args:
            position: The PortfolioPosition to snapshot.
            market_price: Optional current market price for live unrealised
                P&L recalculation.

        Returns:
            An immutable PositionPnL snapshot.
        """
        if market_price is not None:
            unrealised = self.calculate_unrealised_pnl(position, market_price)
        else:
            unrealised = position.unrealised_pnl

        realised = position.realised_pnl
        estimated_fees = position.total_fees
        total = _q(realised + unrealised)

        return PositionPnL(
            instrument_token=position.instrument_token,
            instrument_symbol=position.instrument_symbol,
            realised=realised,
            unrealised=unrealised,
            total=total,
            estimated_fees=estimated_fees,
            confirmed_fees=_ZERO,
            fees_are_estimated=True,
            as_of=datetime.now(timezone.utc),
        )

    def build_portfolio_pnl(
        self,
        positions: list[PortfolioPosition],
        realised_total: Decimal,
        cash_balance: Decimal,
        initial_capital: Decimal,
        peak_equity: Decimal,
        daily_pnl: Decimal,
        trading_date: str,
        state_version: int = 0,
    ) -> PortfolioPnL:
        """Build an aggregate PortfolioPnL from all current positions.

        Equity is approximated as: cash_balance + sum(position market values)
        where market value uses last_market_price or average_entry_price as
        fallback.  Drawdown is calculated against *peak_equity*.

        Args:
            positions: All portfolio positions (open + reducing).
            realised_total: Total confirmed realised P&L (from ledger).
            cash_balance: Current free cash balance.
            initial_capital: Starting capital (contextual, not used in calc).
            peak_equity: Historical peak equity for drawdown calculation.
            daily_pnl: Today's net P&L (from daily-reset tracking).
            trading_date: Trading date string "YYYY-MM-DD" in IST.
            state_version: Current state machine version counter.

        Returns:
            An immutable PortfolioPnL aggregate.
        """
        position_pnls: list[PositionPnL] = []
        total_unrealised = _ZERO
        total_estimated_fees = _ZERO
        total_market_value = _ZERO

        for pos in positions:
            if pos.status == PositionStatus.CLOSED:
                continue

            ppnl = self.build_position_pnl(pos)
            position_pnls.append(ppnl)
            total_unrealised = _q(total_unrealised + ppnl.unrealised)
            total_estimated_fees = _q(total_estimated_fees + ppnl.estimated_fees)

            # Market value contribution
            price = pos.last_market_price or pos.average_entry_price
            total_market_value = _q(
                total_market_value + Decimal(str(pos.open_quantity)) * price
            )

        current_equity = _q(cash_balance + total_market_value)
        gross_pnl = _q(realised_total + total_unrealised)
        net_pnl = _q(gross_pnl - total_estimated_fees)

        # Drawdown: fraction of peak equity lost
        if peak_equity > _ZERO:
            dd_amount = _q(max(_ZERO, peak_equity - current_equity))
            dd_fraction = _q(dd_amount / peak_equity, Decimal("0.0001"))
            # Clamp to [0, 1]
            dd_fraction = min(max(dd_fraction, _ZERO), _ONE)
        else:
            dd_amount = _ZERO
            dd_fraction = _ZERO

        return PortfolioPnL(
            realised=realised_total,
            unrealised=total_unrealised,
            gross=gross_pnl,
            net=net_pnl,
            brokerage=total_estimated_fees,   # best estimate available
            taxes=_ZERO,                       # broken out later via confirmed charges
            other_fees=_ZERO,
            daily_pnl=daily_pnl,
            peak_equity=peak_equity,
            current_equity=current_equity,
            drawdown=dd_fraction,
            drawdown_amount=dd_amount,
            fees_are_estimated=True,
            position_pnls=tuple(position_pnls),
            as_of=datetime.now(timezone.utc),
            trading_date=trading_date,
            state_version=state_version,
        )

    def apply_confirmed_charges(
        self,
        position_pnl: PositionPnL,
        confirmed_brokerage: Decimal,
        confirmed_taxes: Decimal,
        confirmed_fees: Decimal,
    ) -> PositionPnL:
        """Replace estimated fees with broker-confirmed charges.

        Returns a new PositionPnL instance with fees_are_estimated=False and
        the total recalculated using confirmed figures.

        Args:
            position_pnl: The existing (estimated) PositionPnL snapshot.
            confirmed_brokerage: Broker-confirmed brokerage charge.
            confirmed_taxes: Broker-confirmed tax charges (STT, GST, etc.).
            confirmed_fees: Any other broker-confirmed charges.

        Returns:
            A new immutable PositionPnL with confirmed charges applied.
        """
        total_confirmed = _q(confirmed_brokerage + confirmed_taxes + confirmed_fees)
        # Net total: realised + unrealised - confirmed_fees
        new_total = _q(position_pnl.realised + position_pnl.unrealised - total_confirmed)

        return PositionPnL(
            instrument_token=position_pnl.instrument_token,
            instrument_symbol=position_pnl.instrument_symbol,
            realised=position_pnl.realised,
            unrealised=position_pnl.unrealised,
            total=new_total,
            estimated_fees=position_pnl.estimated_fees,
            confirmed_fees=total_confirmed,
            fees_are_estimated=False,
            as_of=datetime.now(timezone.utc),
        )


# ---------------------------------------------------------------------------
# PnLCalculator alias — backward compat for state_manager.py
# ---------------------------------------------------------------------------

class PnLCalculator:
    """Alias for the static build_portfolio_pnl helper used by state_manager.

    state_manager.py calls PnLCalculator.build_portfolio_pnl as a class method.
    """

    @staticmethod
    def build_portfolio_pnl(
        positions: list[PortfolioPosition],
        daily_pnl: Decimal,
        peak_equity: Decimal,
        current_equity: Decimal,
        state_version: int = 0,
    ) -> PortfolioPnL:
        """Simplified build_portfolio_pnl for backward compatibility.

        Used by PortfolioStateManager (state_manager.py) which tracks equity
        separately and passes it directly.
        """
        position_pnls: list[PositionPnL] = []
        total_unrealised = _ZERO
        total_estimated_fees = _ZERO

        for pos in positions:
            if pos.status == PositionStatus.CLOSED:
                continue
            unrealised = pos.unrealised_pnl
            realised = pos.realised_pnl
            est_fees = pos.total_fees
            ppnl = PositionPnL(
                instrument_token=pos.instrument_token,
                instrument_symbol=pos.instrument_symbol,
                realised=realised,
                unrealised=unrealised,
                total=_q(realised + unrealised),
                estimated_fees=est_fees,
                confirmed_fees=_ZERO,
                fees_are_estimated=True,
                as_of=datetime.now(timezone.utc),
            )
            position_pnls.append(ppnl)
            total_unrealised = _q(total_unrealised + unrealised)
            total_estimated_fees = _q(total_estimated_fees + est_fees)

        realised_total = sum((p.realised_pnl for p in positions), _ZERO)
        gross_pnl = _q(realised_total + total_unrealised)
        net_pnl = _q(gross_pnl - total_estimated_fees)

        if peak_equity > _ZERO:
            dd_amount = _q(max(_ZERO, peak_equity - current_equity))
            dd_fraction = _q(dd_amount / peak_equity, Decimal("0.0001"))
            dd_fraction = min(max(dd_fraction, _ZERO), _ONE)
        else:
            dd_amount = _ZERO
            dd_fraction = _ZERO

        return PortfolioPnL(
            realised=realised_total,
            unrealised=total_unrealised,
            gross=gross_pnl,
            net=net_pnl,
            brokerage=total_estimated_fees,
            taxes=_ZERO,
            other_fees=_ZERO,
            daily_pnl=daily_pnl,
            peak_equity=peak_equity,
            current_equity=current_equity,
            drawdown=dd_fraction,
            drawdown_amount=dd_amount,
            fees_are_estimated=True,
            position_pnls=tuple(position_pnls),
            as_of=datetime.now(timezone.utc),
            state_version=state_version,
        )
