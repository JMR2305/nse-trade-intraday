"""
main.py
Entry point for the Python trading engine.
Called by the Express API server via child_process.

Usage:
  python3 main.py portfolio
  python3 main.py signals
  python3 main.py trades
  python3 main.py scan
  python3 main.py ai_decisions
  python3 main.py trade_replay
  python3 main.py strategy_performance
  python3 main.py market_overview
  python3 main.py watchlist
  python3 main.py watchlist_add RELIANCE
  python3 main.py watchlist_remove RELIANCE
  python3 main.py buy RELIANCE 2 500.00 "RSI oversold"
  python3 main.py sell RELIANCE 1 520.00 "RSI overbought"
  python3 main.py reset

All commands output JSON to stdout. Errors output {"error": "..."} with exit code 1.
"""

import sys
import json
import os
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from paper_trader import (
    get_portfolio, get_trades, execute_buy, execute_sell, reset_portfolio,
    get_trade_replay, get_strategy_performance,
)
from signal_engine import scan_watchlist, generate_signal
from market_data import get_multiple_ltp
from market_regime import get_regime

WATCHLIST_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "watchlist.json")
SIGNALS_CACHE  = os.path.join(os.path.dirname(os.path.abspath(__file__)), "signals_cache.json")
AI_CACHE       = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ai_decisions_cache.json")

DEFAULT_WATCHLIST = [
    "RELIANCE", "TCS", "INFY", "HDFCBANK", "ICICIBANK",
    "SBIN", "WIPRO", "LT", "BAJFINANCE", "MARUTI",
]


def _load_watchlist() -> list[str]:
    if os.path.exists(WATCHLIST_FILE):
        try:
            with open(WATCHLIST_FILE, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return list(DEFAULT_WATCHLIST)


def _save_watchlist(watchlist: list[str]) -> None:
    with open(WATCHLIST_FILE, "w") as f:
        json.dump(watchlist, f, indent=2)


def _load_portfolio_with_live_prices() -> dict:
    from paper_trader import _load_state
    state = _load_state()
    symbols = list(state.get("positions", {}).keys())
    prices = get_multiple_ltp(symbols) if symbols else {}
    return dict(get_portfolio(prices))


def cmd_portfolio() -> dict:
    return _load_portfolio_with_live_prices()


def cmd_signals() -> list:
    if os.path.exists(SIGNALS_CACHE):
        try:
            with open(SIGNALS_CACHE, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return []


def cmd_ai_decisions() -> list:
    if os.path.exists(AI_CACHE):
        try:
            with open(AI_CACHE, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return []


def cmd_trades() -> list:
    return list(get_trades())


def cmd_trade_replay() -> list:
    return list(get_trade_replay())


def cmd_strategy_performance() -> dict:
    return dict(get_strategy_performance())


EXECUTABLE_BUY_SIGNALS  = {"STRONG_BUY", "BUY"}
EXECUTABLE_SELL_SIGNALS = {"STRONG_SELL", "SELL"}


def cmd_market_overview() -> dict:
    from market_overview import get_market_overview
    from paper_trader import _load_state
    state = _load_state()
    cash = state.get("cash", 5000.0)
    return dict(get_market_overview(available_cash=cash))


def cmd_scan() -> dict:
    """
    Full scan: signal engine → AI Decision Engine → paper trade execution.

    Returns dict with signals, ai_decisions, and scanned_at.
    """
    from ai_decision import scan_ai_decisions
    from paper_trader import _load_state

    state = _load_state()
    cash = state.get("cash", 5000.0)

    # 1. Market regime (fetched once)
    regime = get_regime()

    # 2. Signal engine scan
    watchlist = _load_watchlist()
    signals = scan_watchlist(watchlist, available_cash=cash, regime=regime)

    # 3. AI Decision Engine
    ai_decisions = scan_ai_decisions(signals, available_cash=cash)

    # 4. Cache both
    with open(SIGNALS_CACHE, "w") as f:
        json.dump(signals, f, indent=2, default=str)
    with open(AI_CACHE, "w") as f:
        json.dump(ai_decisions, f, indent=2, default=str)

    # 5. Execute paper trades based on AI decisions (not raw signals)
    # Reload state to get current positions
    state = _load_state()
    positions = state.get("positions", {})
    current_cash = state.get("cash", 5000.0)

    for ai_dec in ai_decisions:
        symbol   = ai_dec.get("stock", "")
        decision = ai_dec.get("decision", "NO_TRADE")
        price    = ai_dec.get("entry_price", 0.0)
        qty_from_ai = int(current_cash * 0.20 / price) if price > 0 else 0

        if qty_from_ai <= 0 or price <= 0:
            continue

        plain_english = ai_dec.get("plain_english", "")
        regime_name   = ai_dec.get("regime", "UNKNOWN")
        confidence    = ai_dec.get("confidence", 0.0)
        rr_ratio      = ai_dec.get("rr_ratio", 0.0)
        target        = ai_dec.get("target", 0.0)
        stop          = ai_dec.get("stop_loss", 0.0)

        upgrade_rsns   = ai_dec.get("upgrade_reasons", [])
        downgrade_rsns = ai_dec.get("downgrade_reasons", [])
        all_rsns = upgrade_rsns + downgrade_rsns
        reason_str = "; ".join(all_rsns[:3]) if all_rsns else f"AI Decision: {decision}"

        if decision in EXECUTABLE_BUY_SIGNALS:
            execute_buy(
                symbol, qty_from_ai, price,
                reason=reason_str,
                signal_confidence=confidence,
                regime=regime_name,
                ai_decision=decision,
                rr_ratio=rr_ratio,
                target=target,
                stop_loss_price=stop,
                plain_english=plain_english,
            )
            # Reload cash after each buy
            state = _load_state()
            current_cash = state.get("cash", 5000.0)

        elif decision in EXECUTABLE_SELL_SIGNALS:
            sym_upper = symbol.upper()
            if sym_upper in positions:
                held_qty = positions[sym_upper].get("quantity", 0)
                sell_qty = min(qty_from_ai, held_qty)
                if sell_qty > 0:
                    # Determine exit type
                    if stop > 0 and price <= stop * 1.01:
                        exit_type = "STOP_HIT"
                    elif target > 0 and price >= target * 0.99:
                        exit_type = "TARGET_HIT"
                    else:
                        exit_type = "SIGNAL_EXIT"
                    execute_sell(symbol, sell_qty, price, reason=reason_str, exit_type=exit_type)

    scanned_at = datetime.now().isoformat()
    return {
        "signals": signals,
        "ai_decisions": ai_decisions,
        "scanned_at": scanned_at,
    }


def cmd_watchlist() -> list:
    return _load_watchlist()


def cmd_watchlist_add(symbol: str) -> dict:
    symbol = symbol.upper().strip()
    wl = _load_watchlist()
    if symbol not in wl:
        wl.append(symbol)
        _save_watchlist(wl)
    return {"watchlist": wl}


def cmd_watchlist_remove(symbol: str) -> dict:
    symbol = symbol.upper().strip()
    wl = _load_watchlist()
    wl = [s for s in wl if s != symbol]
    _save_watchlist(wl)
    return {"watchlist": wl}


def cmd_buy(symbol: str, quantity: int, price: float, reason: str = "") -> dict:
    success, message = execute_buy(symbol, quantity, price, reason)
    return {"success": success, "message": message}


def cmd_sell(symbol: str, quantity: int, price: float, reason: str = "") -> dict:
    success, message = execute_sell(symbol, quantity, price, reason)
    return {"success": success, "message": message}


def cmd_reset() -> dict:
    reset_portfolio()
    return {"success": True, "message": "Portfolio reset to ₹5,000"}


def main():
    args = sys.argv[1:]
    if not args:
        print(json.dumps({"error": "No command provided"}))
        sys.exit(1)

    command = args[0].lower()

    try:
        if command == "portfolio":
            result = cmd_portfolio()
        elif command == "signals":
            result = cmd_signals()
        elif command == "ai_decisions":
            result = cmd_ai_decisions()
        elif command == "trades":
            result = cmd_trades()
        elif command == "trade_replay":
            result = cmd_trade_replay()
        elif command == "strategy_performance":
            result = cmd_strategy_performance()
        elif command == "scan":
            result = cmd_scan()
        elif command == "market_overview":
            result = cmd_market_overview()
        elif command == "watchlist":
            result = cmd_watchlist()
        elif command == "watchlist_add" and len(args) >= 2:
            result = cmd_watchlist_add(args[1])
        elif command == "watchlist_remove" and len(args) >= 2:
            result = cmd_watchlist_remove(args[1])
        elif command == "buy" and len(args) >= 4:
            result = cmd_buy(args[1], int(args[2]), float(args[3]), args[4] if len(args) > 4 else "")
        elif command == "sell" and len(args) >= 4:
            result = cmd_sell(args[1], int(args[2]), float(args[3]), args[4] if len(args) > 4 else "")
        elif command == "reset":
            result = cmd_reset()
        else:
            print(json.dumps({"error": f"Unknown command: {command}"}))
            sys.exit(1)

        print(json.dumps(result, default=str))

    except Exception as e:
        print(json.dumps({"error": str(e)}))
        sys.exit(1)


if __name__ == "__main__":
    main()
