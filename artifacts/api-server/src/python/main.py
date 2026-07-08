"""
main.py
Entry point for the Python trading engine.
Called by the Express API server via child_process.

Usage:
  python3 main.py portfolio
  python3 main.py signals
  python3 main.py trades
  python3 main.py scan
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

# Add the directory containing this file to sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from paper_trader import get_portfolio, get_trades, execute_buy, execute_sell, reset_portfolio
from signal_engine import scan_watchlist, generate_signal
from market_data import get_multiple_ltp
from market_regime import get_regime

WATCHLIST_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "watchlist.json")

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
    """Fetch live LTPs and compute real-time portfolio."""
    from paper_trader import _load_state
    state = _load_state()
    symbols = list(state.get("positions", {}).keys())
    prices = get_multiple_ltp(symbols) if symbols else {}
    portfolio = get_portfolio(prices)
    return dict(portfolio)


def cmd_portfolio() -> dict:
    return _load_portfolio_with_live_prices()


def cmd_signals() -> list:
    """Return latest cached signals (from last scan)."""
    signals_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "signals_cache.json")
    if os.path.exists(signals_file):
        try:
            with open(signals_file, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return []


def cmd_trades() -> list:
    return list(get_trades())


EXECUTABLE_BUY_SIGNALS = {"STRONG_BUY", "BUY"}
EXECUTABLE_SELL_SIGNALS = {"STRONG_SELL", "SELL"}


def cmd_market_overview() -> dict:
    """Generate market intelligence overview (NIFTY, BANKNIFTY, VIX, regime, top/weak stocks)."""
    from market_overview import get_market_overview
    from paper_trader import _load_state
    state = _load_state()
    cash = state.get("cash", 5000.0)
    return dict(get_market_overview(available_cash=cash))


def cmd_scan() -> list:
    """Run signal scan on watchlist, cache results, and auto-execute paper trades.

    Execution rules:
      - STRONG_BUY / BUY  → open a long paper position (if quantity > 0 and cash available)
      - STRONG_SELL / SELL → close existing long position (if held)
      - WATCH / NO_TRADE   → no execution
    """
    from paper_trader import _load_state
    state = _load_state()
    cash = state.get("cash", 5000.0)

    # Fetch regime once — reused across all stock signals
    regime = get_regime()

    watchlist = _load_watchlist()
    signals = scan_watchlist(watchlist, available_cash=cash, regime=regime)

    # Cache results
    signals_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "signals_cache.json")
    with open(signals_file, "w") as f:
        json.dump(signals, f, indent=2)

    # Auto-execute paper trades for actionable signals
    positions = state.get("positions", {})
    for sig in signals:
        symbol = sig.get("stock", "")
        signal_type = sig.get("signal", "NO_TRADE")
        quantity = sig.get("quantity", 0)
        price = sig.get("price", 0.0)
        reasons = sig.get("reasons", [])
        reason_str = "; ".join(reasons[:3]) if reasons else "Auto-executed from scan"

        if quantity <= 0 or price <= 0:
            continue

        if signal_type in EXECUTABLE_BUY_SIGNALS:
            execute_buy(symbol, quantity, price, reason_str)
        elif signal_type in EXECUTABLE_SELL_SIGNALS:
            sym_upper = symbol.upper()
            if sym_upper in positions:
                held_qty = positions[sym_upper].get("quantity", 0)
                sell_qty = min(quantity, held_qty)
                if sell_qty > 0:
                    execute_sell(symbol, sell_qty, price, reason_str)

    return signals


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
        elif command == "trades":
            result = cmd_trades()
        elif command == "scan":
            result = cmd_scan()
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
        elif command == "market_overview":
            result = cmd_market_overview()
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
