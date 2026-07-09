"""
main.py
Entry point for the Python trading engine.
Called by the Express API server via child_process.

Usage:
  python3 main.py portfolio
  python3 main.py signals
  python3 main.py ai_decisions
  python3 main.py trades
  python3 main.py trade_replay
  python3 main.py strategy_performance
  python3 main.py scan                    ← full intelligence pipeline
  python3 main.py opportunity_scan        ← cached ranked opportunities
  python3 main.py market_context          ← cached market context
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
import io
import contextlib
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from paper_trader import (
    get_portfolio, get_trades, execute_buy, execute_sell, reset_portfolio,
    get_trade_replay, get_strategy_performance, _load_state,
)
from market_data import get_multiple_ltp
from config import DEFAULT_WATCHLIST

WATCHLIST_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "watchlist.json")


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
    state = _load_state()
    symbols = list(state.get("positions", {}).keys())
    prices = get_multiple_ltp(symbols) if symbols else {}
    return dict(get_portfolio(prices))


# ── Commands ──────────────────────────────────────────────────────────────────

def cmd_portfolio() -> dict:
    return _load_portfolio_with_live_prices()


def cmd_signals() -> list:
    from intelligence import get_cached_enriched_signals
    data = get_cached_enriched_signals()
    return data if data else _read_json_cache("signals_cache.json")


def cmd_ai_decisions() -> list:
    return _read_json_cache("ai_decisions_cache.json")


def cmd_opportunity_scan() -> list:
    from intelligence import get_cached_opportunity_scan
    return get_cached_opportunity_scan()


def cmd_market_context() -> dict:
    from intelligence import get_cached_market_context
    return get_cached_market_context()


def cmd_trades() -> list:
    return list(get_trades())


def cmd_trade_replay() -> list:
    return list(get_trade_replay())


def cmd_strategy_performance() -> dict:
    return dict(get_strategy_performance())


def cmd_market_overview() -> dict:
    from market_overview import get_market_overview
    state = _load_state()
    cash = state.get("cash", 5000.0)
    return dict(get_market_overview(available_cash=cash))


def cmd_scan() -> dict:
    """Full intelligence pipeline scan."""
    from intelligence import run_intelligence_scan
    state = _load_state()
    cash = state.get("cash", 5000.0)
    watchlist = _load_watchlist()
    result = run_intelligence_scan(watchlist, available_cash=cash, execute_trades=True)
    return dict(result)


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


def cmd_market_data(symbol: str, interval: str = "1d", period: str = "3mo") -> dict:
    from market_data_engine import fetch_candles
    return dict(fetch_candles(symbol, interval=interval, period=period))


def cmd_indicators(symbol: str, interval: str = "1d", period: str = "3mo") -> dict:
    from market_data_engine import fetch_candles_df
    from indicator_engine import compute_indicators
    df = fetch_candles_df(symbol, interval=interval, period=period)
    result = compute_indicators(df, symbol=symbol, interval=interval)
    # Omit full series by default for fast response; caller can request with ?series=true
    return dict(result)


def cmd_backtest(
    symbol: str,
    strategy: str,
    start_date: str,
    end_date: str,
    initial_capital: float = 5000.0,
    interval: str = "1d",
    debug: bool = False,
) -> dict:
    from backtesting_engine import run_backtest
    result = run_backtest(
        symbol=symbol,
        strategy_name=strategy,
        start_date=start_date,
        end_date=end_date,
        initial_capital=initial_capital,
        interval=interval,
        debug=debug,
    )
    return dict(result)


def cmd_strategies() -> list:
    from strategies import list_strategies
    return list_strategies()


def cmd_market_scan() -> dict:
    """Sprint 1.5 — full NIFTY 50 universe scan (paper trading, no real orders)."""
    from market_scanner import run_market_scan
    state = _load_state()
    cash = state.get("cash", 5000.0)
    result = run_market_scan(capital=cash)
    return dict(result)


def _read_json_cache(filename: str) -> list | dict:
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), filename)
    if os.path.exists(path):
        try:
            with open(path, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return []


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    args = sys.argv[1:]
    if not args:
        print(json.dumps({"error": "No command provided"}))
        sys.exit(1)

    command = args[0].lower()

    _stdout_buf = io.StringIO()
    result = None
    error_msg = None
    try:
      with contextlib.redirect_stdout(_stdout_buf):
        if command == "portfolio":
            result = cmd_portfolio()
        elif command == "signals":
            result = cmd_signals()
        elif command == "ai_decisions":
            result = cmd_ai_decisions()
        elif command == "opportunity_scan":
            result = cmd_opportunity_scan()
        elif command == "market_context":
            result = cmd_market_context()
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
            result = cmd_buy(args[1], int(args[2]), float(args[3]),
                             args[4] if len(args) > 4 else "")
        elif command == "sell" and len(args) >= 4:
            result = cmd_sell(args[1], int(args[2]), float(args[3]),
                              args[4] if len(args) > 4 else "")
        elif command == "reset":
            result = cmd_reset()
        elif command == "market_data" and len(args) >= 2:
            result = cmd_market_data(
                args[1],
                args[2] if len(args) > 2 else "1d",
                args[3] if len(args) > 3 else "3mo",
            )
        elif command == "indicators" and len(args) >= 2:
            result = cmd_indicators(
                args[1],
                args[2] if len(args) > 2 else "1d",
                args[3] if len(args) > 3 else "3mo",
            )
        elif command == "backtest" and len(args) >= 5:
            result = cmd_backtest(
                symbol          = args[1],
                strategy        = args[2],
                start_date      = args[3],
                end_date        = args[4],
                initial_capital = float(args[5]) if len(args) > 5 else 5000.0,
                interval        = args[6] if len(args) > 6 else "1d",
                debug           = (args[7].lower() == "true") if len(args) > 7 else False,
            )
        elif command == "strategies":
            result = cmd_strategies()
        elif command == "market_scan":
            result = cmd_market_scan()
        elif command == "optimizer" and len(args) >= 4:
            from strategy_optimizer import run_optimizer
            result = run_optimizer(
                symbol          = args[1],
                start_date      = args[2],
                end_date        = args[3],
                initial_capital = float(args[4]) if len(args) > 4 else 5000.0,
                interval        = args[5] if len(args) > 5 else "1d",
                top_n           = int(args[6]) if len(args) > 6 else 10,
            )
        elif command == "strategy_lab" and len(args) >= 4:
            from backtesting_engine import run_strategy_lab
            result = run_strategy_lab(
                symbol          = args[1],
                start_date      = args[2],
                end_date        = args[3],
                initial_capital = float(args[4]) if len(args) > 4 else 5000.0,
                interval        = args[5] if len(args) > 5 else "1d",
            )
        else:
            error_msg = f"Unknown command: {command}"

    except Exception as e:
        import traceback
        print(json.dumps({"error": str(e), "trace": traceback.format_exc()}))
        sys.exit(1)

    if error_msg is not None:
        print(json.dumps({"error": error_msg}))
        sys.exit(1)

    print(json.dumps(result, default=str))


if __name__ == "__main__":
    main()
