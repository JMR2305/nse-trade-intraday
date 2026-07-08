"""
paper_trader.py
Simulates paper trading for NSE stocks.
Maintains portfolio state (cash, positions, trade history, P&L history)
in a local JSON file. No real orders are ever placed.

Initial capital: ₹5,000
"""

import json
import os
from datetime import datetime
from typing import TypedDict, Optional
import uuid

INITIAL_CAPITAL = 5000.0

STATE_DIR = os.path.dirname(os.path.abspath(__file__))
STATE_FILE = os.path.join(STATE_DIR, "state.json")


# ── Type definitions ──────────────────────────────────────────────────────────

class Position(TypedDict):
    symbol: str
    quantity: int
    avg_price: float
    current_price: float
    pnl: float
    pnl_pct: float


class Trade(TypedDict):
    id: str
    symbol: str
    action: str          # "BUY" | "SELL"
    quantity: int
    price: float
    total: float
    timestamp: str
    reason: str


class PnlPoint(TypedDict):
    timestamp: str
    value: float


class PortfolioState(TypedDict):
    cash: float
    total_value: float
    invested_value: float
    total_pnl: float
    total_pnl_pct: float
    positions: list[Position]
    pnl_history: list[PnlPoint]


# ── State persistence ─────────────────────────────────────────────────────────

def _default_state() -> dict:
    return {
        "cash": INITIAL_CAPITAL,
        "positions": {},        # symbol -> {quantity, avg_price}
        "trades": [],
        "pnl_history": [
            {"timestamp": datetime.now().isoformat(), "value": INITIAL_CAPITAL}
        ],
    }


def _load_state() -> dict:
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return _default_state()


def _save_state(state: dict) -> None:
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


# ── Portfolio calculations ─────────────────────────────────────────────────────

def _compute_portfolio(state: dict, current_prices: dict[str, float]) -> PortfolioState:
    cash = state["cash"]
    positions: list[Position] = []
    invested_value = 0.0

    for symbol, pos in state.get("positions", {}).items():
        qty = pos["quantity"]
        avg = pos["avg_price"]
        ltp = current_prices.get(symbol, avg)
        mkt_value = qty * ltp
        invested_value += mkt_value
        pnl = mkt_value - (qty * avg)
        pnl_pct = (pnl / (qty * avg)) * 100 if avg > 0 else 0.0
        positions.append(
            Position(
                symbol=symbol,
                quantity=qty,
                avg_price=round(avg, 2),
                current_price=round(ltp, 2),
                pnl=round(pnl, 2),
                pnl_pct=round(pnl_pct, 2),
            )
        )

    total_value = cash + invested_value
    total_pnl = total_value - INITIAL_CAPITAL
    total_pnl_pct = (total_pnl / INITIAL_CAPITAL) * 100

    return PortfolioState(
        cash=round(cash, 2),
        total_value=round(total_value, 2),
        invested_value=round(invested_value, 2),
        total_pnl=round(total_pnl, 2),
        total_pnl_pct=round(total_pnl_pct, 2),
        positions=positions,
        pnl_history=state.get("pnl_history", []),
    )


# ── Trade execution ────────────────────────────────────────────────────────────

def execute_buy(symbol: str, quantity: int, price: float, reason: str = "") -> tuple[bool, str]:
    """
    Execute a paper buy order.

    Returns:
        (success, message)
    """
    if quantity <= 0:
        return False, "Quantity must be positive"

    state = _load_state()
    total_cost = quantity * price

    if state["cash"] < total_cost:
        return False, f"Insufficient cash: need ₹{total_cost:.2f}, have ₹{state['cash']:.2f}"

    # Deduct cash
    state["cash"] -= total_cost

    # Update position (average down / up)
    sym = symbol.upper()
    if sym in state["positions"]:
        existing = state["positions"][sym]
        total_qty = existing["quantity"] + quantity
        total_cost_basis = existing["quantity"] * existing["avg_price"] + total_cost
        state["positions"][sym] = {
            "quantity": total_qty,
            "avg_price": total_cost_basis / total_qty,
        }
    else:
        state["positions"][sym] = {
            "quantity": quantity,
            "avg_price": price,
        }

    # Record trade
    trade = Trade(
        id=str(uuid.uuid4())[:8],
        symbol=sym,
        action="BUY",
        quantity=quantity,
        price=round(price, 2),
        total=round(total_cost, 2),
        timestamp=datetime.now().isoformat(),
        reason=reason,
    )
    state["trades"].append(trade)

    # Update P&L snapshot
    _append_pnl_snapshot(state, price, sym)

    _save_state(state)
    return True, f"Bought {quantity} × {sym} @ ₹{price:.2f} = ₹{total_cost:.2f}"


def execute_sell(symbol: str, quantity: int, price: float, reason: str = "") -> tuple[bool, str]:
    """
    Execute a paper sell order.

    Returns:
        (success, message)
    """
    if quantity <= 0:
        return False, "Quantity must be positive"

    state = _load_state()
    sym = symbol.upper()

    if sym not in state["positions"]:
        return False, f"No position in {sym}"

    existing = state["positions"][sym]
    if existing["quantity"] < quantity:
        return False, f"Only {existing['quantity']} shares available, tried to sell {quantity}"

    total_proceeds = quantity * price
    state["cash"] += total_proceeds

    # Reduce / close position
    remaining = existing["quantity"] - quantity
    if remaining == 0:
        del state["positions"][sym]
    else:
        state["positions"][sym]["quantity"] = remaining

    # Record trade
    trade = Trade(
        id=str(uuid.uuid4())[:8],
        symbol=sym,
        action="SELL",
        quantity=quantity,
        price=round(price, 2),
        total=round(total_proceeds, 2),
        timestamp=datetime.now().isoformat(),
        reason=reason,
    )
    state["trades"].append(trade)

    # Update P&L snapshot
    _append_pnl_snapshot(state, price, sym)

    _save_state(state)
    return True, f"Sold {quantity} × {sym} @ ₹{price:.2f} = ₹{total_proceeds:.2f}"


def _append_pnl_snapshot(state: dict, latest_price: float, latest_symbol: str) -> None:
    """Append a portfolio value snapshot to pnl_history."""
    invested = 0.0
    for sym, pos in state.get("positions", {}).items():
        # Use latest price for the symbol just traded, otherwise use avg_price as proxy
        ltp = latest_price if sym == latest_symbol else pos["avg_price"]
        invested += pos["quantity"] * ltp

    total = state["cash"] + invested
    state["pnl_history"].append({
        "timestamp": datetime.now().isoformat(),
        "value": round(total, 2),
    })

    # Keep last 500 snapshots
    if len(state["pnl_history"]) > 500:
        state["pnl_history"] = state["pnl_history"][-500:]


# ── Public query helpers ───────────────────────────────────────────────────────

def get_trades() -> list[Trade]:
    """Return all recorded trades, newest first."""
    state = _load_state()
    return list(reversed(state.get("trades", [])))


def get_portfolio(current_prices: Optional[dict[str, float]] = None) -> PortfolioState:
    """
    Return current portfolio state.

    Args:
        current_prices: optional dict of {symbol: ltp}. If None, avg_price is used as proxy.
    """
    state = _load_state()
    prices = current_prices or {}
    # Fill missing prices with avg_price as proxy
    for sym, pos in state.get("positions", {}).items():
        if sym not in prices:
            prices[sym] = pos["avg_price"]
    return _compute_portfolio(state, prices)


def reset_portfolio() -> None:
    """Reset the portfolio to initial state (₹5,000 cash, no positions)."""
    _save_state(_default_state())
