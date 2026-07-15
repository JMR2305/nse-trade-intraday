"""
paper_trader.py
Simulates paper trading for NSE stocks.
Maintains portfolio state (cash, positions, trade history, P&L history)
in a local JSON file. No real orders are ever placed.

Initial capital: ₹5,000

v0.4: Enhanced trade storage for Trade Replay.
Each BUY record stores AI decision metadata (confidence, regime, rr_ratio,
stop_loss, target, plain_english) so the Trade Replay page can show full context.
Each SELL record stores realized P&L and exit type.
"""

import json
import os
from datetime import datetime
from typing import TypedDict, Optional
import uuid

from analytics_engine import classify_outcome

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


class TradeReplayItem(TypedDict):
    id: str
    symbol: str
    entry_time: str
    exit_time: str
    entry_price: float
    exit_price: float
    quantity: int
    pnl: float
    pnl_pct: float
    signal_confidence: float
    regime: str
    ai_decision: str
    rr_ratio: float
    target: float
    stop_loss: float
    exit_type: str           # TARGET_HIT | STOP_HIT | SIGNAL_EXIT | MANUAL
    reason_entry: str
    reason_exit: str
    plain_english: str
    # ── Trade Journal enrichment (v0.9) ─────────────────────────────────
    strategy_id:            str
    strategy_name:          str
    outcome_classification: str   # Excellent | Good | Weak | Small Loss | Failed


class StrategyPerformance(TypedDict):
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: float
    avg_profit: float
    avg_loss: float
    profit_factor: float
    total_pnl: float
    best_stock: str
    worst_stock: str
    best_regime: str
    computed_at: str


# ── State persistence ────────────────────────────────────────────────────────

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


# ── Portfolio calculations ────────────────────────────────────────────────────

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


# ── Trade execution ───────────────────────────────────────────────────────────

def execute_buy(
    symbol: str,
    quantity: int,
    price: float,
    reason: str = "",
    # AI Decision metadata (stored for Trade Replay)
    signal_confidence: float = 0.0,
    regime: str = "UNKNOWN",
    ai_decision: str = "",
    rr_ratio: float = 0.0,
    target: float = 0.0,
    stop_loss_price: float = 0.0,
    plain_english: str = "",
    strategy_id: str = "",
    strategy_name: str = "",
    opportunity_score: float = 0.0,
    trade_quality: float = 0.0,
    bypass_risk: bool = False,
) -> tuple[bool, str]:
    """
    Execute a paper buy order.

    Additional metadata params are stored in the trade record
    for Trade Replay and Strategy Performance analysis.

    Returns:
        (success, message)
    """
    if quantity <= 0:
        return False, "Quantity must be positive"

    # ── Phase 11: pre-trade risk enforcement (paper trading only) ────────
    risk_note = ""
    if not bypass_risk:
        try:
            from phase11_risk import pre_trade_check
            allowed, risk_msg = pre_trade_check(
                symbol, quantity, price,
                stop_loss_price if stop_loss_price > 0 else None,
                signal_confidence if signal_confidence > 0 else None,
            )
            if not allowed:
                return False, f"RISK BLOCKED: {risk_msg}"
            if risk_msg and "Risk note" in risk_msg:
                risk_note = f" [{risk_msg}]"
        except ImportError:
            pass  # risk engine not present — legacy behavior

    state = _load_state()
    total_cost = quantity * price

    if state["cash"] < total_cost:
        return False, f"Insufficient cash: need ₹{total_cost:.2f}, have ₹{state['cash']:.2f}"

    # Deduct cash
    state["cash"] -= total_cost

    # Update position (average up/down)
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

    # Record trade with full metadata
    trade: dict = {
        "id": str(uuid.uuid4())[:8],
        "symbol": sym,
        "action": "BUY",
        "quantity": quantity,
        "price": round(price, 2),
        "total": round(total_cost, 2),
        "timestamp": datetime.now().isoformat(),
        "reason": reason,
        # AI Decision metadata
        "signal_confidence": round(signal_confidence, 1),
        "regime": regime,
        "ai_decision": ai_decision or "BUY",
        "rr_ratio": round(rr_ratio, 2),
        "target": round(target, 2),
        "stop_loss": round(stop_loss_price, 2),
        "plain_english": plain_english,
        "strategy_id": strategy_id or "ai_scan",
        "strategy_name": strategy_name or "AI Scan",
        "opportunity_score": round(opportunity_score, 2) if opportunity_score else None,
        "trade_quality": round(trade_quality, 2) if trade_quality else None,
    }

    # ── Trade Intelligence: freeze the entry snapshot (indicators + regime).
    # These values are stored on the BUY record and never change afterwards.
    try:
        from market_data import fetch_ohlcv
        from indicator_engine import compute_indicators_df

        df = fetch_ohlcv(sym, period="1y", interval="1d")
        last = compute_indicators_df(df).iloc[-1]

        def _v(col, nd=4):
            try:
                v = float(last.get(col))
                return None if v != v else round(v, nd)  # NaN check
            except (TypeError, ValueError):
                return None

        trade["indicators_at_entry"] = {
            "ema9": _v("ema9", 2), "ema20": _v("ema20", 2),
            "ema50": _v("ema50", 2), "ema200": _v("ema200", 2),
            "rsi": _v("rsi", 2), "macd": _v("macd_line"),
            "macd_signal": _v("macd_signal"), "vwap": _v("vwap", 2),
            "atr": _v("atr", 2), "adx": _v("adx", 2),
            "supertrend": _v("supertrend", 2), "volume_ratio": _v("volume_ratio", 2),
        }
    except Exception:
        pass  # snapshot must never block a buy order

    try:
        from trade_intelligence import classify_regime

        regime_info = classify_regime()
        trade["market_regime_at_entry"] = regime_info.get("regime", "")
        trade["volatility_at_entry"] = regime_info.get("volatility")
    except Exception:
        pass

    state["trades"].append(trade)

    _append_pnl_snapshot(state, price, sym)
    _save_state(state)

    # ── v2.0 Self-Evaluation: permanently store the prediction snapshot ──
    try:
        from trade_evaluator import store_prediction_snapshot
        store_prediction_snapshot(trade)
    except Exception:
        pass  # snapshot must never block a buy order

    return True, f"Bought {quantity} × {sym} @ ₹{price:.2f} = ₹{total_cost:.2f}{risk_note}"


def execute_sell(
    symbol: str,
    quantity: int,
    price: float,
    reason: str = "",
    exit_type: str = "SIGNAL_EXIT",
) -> tuple[bool, str]:
    """
    Execute a paper sell order.

    exit_type: TARGET_HIT | STOP_HIT | SIGNAL_EXIT | MANUAL

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

    avg_price = existing["avg_price"]
    total_proceeds = quantity * price
    realized_pnl = (price - avg_price) * quantity
    realized_pnl_pct = (realized_pnl / (avg_price * quantity)) * 100 if avg_price > 0 else 0.0

    state["cash"] += total_proceeds

    # Reduce / close position
    remaining = existing["quantity"] - quantity
    if remaining == 0:
        del state["positions"][sym]
    else:
        state["positions"][sym]["quantity"] = remaining

    # Record trade with P&L
    trade: dict = {
        "id": str(uuid.uuid4())[:8],
        "symbol": sym,
        "action": "SELL",
        "quantity": quantity,
        "price": round(price, 2),
        "total": round(total_proceeds, 2),
        "timestamp": datetime.now().isoformat(),
        "reason": reason,
        # Sell-specific fields
        "entry_price": round(avg_price, 2),
        "pnl": round(realized_pnl, 2),
        "pnl_pct": round(realized_pnl_pct, 2),
        "exit_type": exit_type,
    }
    state["trades"].append(trade)

    _append_pnl_snapshot(state, price, sym)
    _save_state(state)

    # ── Trade Intelligence (Sprint 3): store the completed paper trade ───
    try:
        from trade_intelligence import record_paper_trade, find_buy_trade
        from market_scanner import _sector_of
        buy_trade = find_buy_trade(state, sym, trade["timestamp"])
        record_paper_trade(trade, sector=_sector_of(sym), buy_trade=buy_trade)
    except Exception:
        buy_trade = None  # recording must never break a sell order

    # ── v2.0 Self-Evaluation: evaluate the completed round trip ──────────
    try:
        from trade_evaluator import evaluate_closed_trade
        if buy_trade:
            evaluate_closed_trade(buy_trade, trade)
    except Exception:
        pass  # evaluation must never break a sell order

    return True, f"Sold {quantity} × {sym} @ ₹{price:.2f} | P&L: ₹{realized_pnl:.2f}"


def _append_pnl_snapshot(state: dict, latest_price: float, latest_symbol: str) -> None:
    """Append a portfolio value snapshot to pnl_history."""
    invested = 0.0
    for sym, pos in state.get("positions", {}).items():
        ltp = latest_price if sym == latest_symbol else pos["avg_price"]
        invested += pos["quantity"] * ltp

    total = state["cash"] + invested
    state["pnl_history"].append({
        "timestamp": datetime.now().isoformat(),
        "value": round(total, 2),
    })

    if len(state["pnl_history"]) > 500:
        state["pnl_history"] = state["pnl_history"][-500:]


# ── Trade Replay ──────────────────────────────────────────────────────────────

def get_trade_replay() -> list[TradeReplayItem]:
    """
    Match BUY→SELL pairs and return enriched round-trip records.
    FIFO matching per symbol. Only completed round trips are returned.
    """
    state = _load_state()
    trades = state.get("trades", [])

    # Stack of open BUY trades per symbol (FIFO)
    open_buys: dict[str, list[dict]] = {}
    replay_items: list[TradeReplayItem] = []

    for trade in trades:
        sym = trade.get("symbol", "")
        action = trade.get("action", "")

        if action == "BUY":
            open_buys.setdefault(sym, []).append(trade)

        elif action == "SELL" and sym in open_buys and open_buys[sym]:
            buy_trade = open_buys[sym].pop(0)

            entry_price = buy_trade.get("price", 0.0)
            exit_price = trade.get("price", 0.0)
            qty = trade.get("quantity", 0)
            pnl = round((exit_price - entry_price) * qty, 2)
            pnl_pct = round((pnl / (entry_price * qty)) * 100, 2) if entry_price > 0 else 0.0

            # Determine exit type from stored metadata or price comparison
            exit_type = trade.get("exit_type", "SIGNAL_EXIT")
            target = buy_trade.get("target", 0.0)
            stop_loss = buy_trade.get("stop_loss", 0.0)
            if exit_type == "SIGNAL_EXIT":
                if target > 0 and exit_price >= target * 0.99:
                    exit_type = "TARGET_HIT"
                elif stop_loss > 0 and exit_price <= stop_loss * 1.01:
                    exit_type = "STOP_HIT"

            replay_items.append(TradeReplayItem(
                id=trade.get("id", ""),
                symbol=sym,
                entry_time=buy_trade.get("timestamp", ""),
                exit_time=trade.get("timestamp", ""),
                entry_price=entry_price,
                exit_price=exit_price,
                quantity=qty,
                pnl=pnl,
                pnl_pct=pnl_pct,
                signal_confidence=buy_trade.get("signal_confidence", 0.0),
                regime=buy_trade.get("regime", "UNKNOWN"),
                ai_decision=buy_trade.get("ai_decision", "UNKNOWN"),
                rr_ratio=buy_trade.get("rr_ratio", 0.0),
                target=target,
                stop_loss=stop_loss,
                exit_type=exit_type,
                reason_entry=buy_trade.get("reason", ""),
                reason_exit=trade.get("reason", ""),
                plain_english=buy_trade.get("plain_english", ""),
                strategy_id=buy_trade.get("strategy_id", "ai_scan"),
                strategy_name=buy_trade.get("strategy_name", "AI Scan"),
                outcome_classification=classify_outcome(pnl_pct),
            ))

    return sorted(replay_items, key=lambda x: x["exit_time"], reverse=True)


def get_strategy_performance() -> StrategyPerformance:
    """
    Compute strategy performance metrics from all completed trade pairs.
    """
    replay = get_trade_replay()

    if not replay:
        return StrategyPerformance(
            total_trades=0, winning_trades=0, losing_trades=0,
            win_rate=0.0, avg_profit=0.0, avg_loss=0.0,
            profit_factor=0.0, total_pnl=0.0,
            best_stock="—", worst_stock="—", best_regime="—",
            computed_at=datetime.now().isoformat(),
        )

    winners = [t for t in replay if t["pnl"] > 0]
    losers  = [t for t in replay if t["pnl"] < 0]

    total = len(replay)
    win_count = len(winners)
    loss_count = len(losers)
    win_rate = (win_count / total * 100) if total > 0 else 0.0

    avg_profit = sum(t["pnl"] for t in winners) / win_count if winners else 0.0
    avg_loss   = sum(t["pnl"] for t in losers)  / loss_count if losers  else 0.0

    total_profits = sum(t["pnl"] for t in winners)
    total_losses  = abs(sum(t["pnl"] for t in losers))
    profit_factor = (total_profits / total_losses) if total_losses > 0 else 999.0

    # Per-stock P&L
    stock_pnl: dict[str, float] = {}
    for t in replay:
        stock_pnl[t["symbol"]] = stock_pnl.get(t["symbol"], 0.0) + t["pnl"]

    best_stock  = max(stock_pnl, key=lambda k: stock_pnl[k]) if stock_pnl else "—"
    worst_stock = min(stock_pnl, key=lambda k: stock_pnl[k]) if stock_pnl else "—"

    # Best regime by win rate
    regime_wins:  dict[str, int] = {}
    regime_total: dict[str, int] = {}
    for t in replay:
        reg = t.get("regime", "UNKNOWN")
        regime_total[reg] = regime_total.get(reg, 0) + 1
        if t["pnl"] > 0:
            regime_wins[reg] = regime_wins.get(reg, 0) + 1

    if regime_total:
        best_regime = max(
            regime_total,
            key=lambda r: (regime_wins.get(r, 0) / regime_total[r])
        )
    else:
        best_regime = "—"

    return StrategyPerformance(
        total_trades=total,
        winning_trades=win_count,
        losing_trades=loss_count,
        win_rate=round(win_rate, 1),
        avg_profit=round(avg_profit, 2),
        avg_loss=round(avg_loss, 2),
        profit_factor=round(profit_factor, 2),
        total_pnl=round(sum(t["pnl"] for t in replay), 2),
        best_stock=best_stock,
        worst_stock=worst_stock,
        best_regime=best_regime,
        computed_at=datetime.now().isoformat(),
    )


# ── Public query helpers ──────────────────────────────────────────────────────

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
    for sym, pos in state.get("positions", {}).items():
        if sym not in prices:
            prices[sym] = pos["avg_price"]
    return _compute_portfolio(state, prices)


def reset_portfolio() -> None:
    """Reset the portfolio to initial state (₹5,000 cash, no positions)."""
    _save_state(_default_state())
