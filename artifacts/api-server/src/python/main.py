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


def cmd_market_replay(scan_date: str, holding_period: int, interval: str) -> dict:
    """Historical Market Scanner / Market Replay (paper trading, no real orders)."""
    from market_replay import run_market_replay
    state = _load_state()
    cash = state.get("cash", 5000.0)
    result = run_market_replay(
        scan_date=scan_date, holding_period=holding_period, interval=interval, capital=cash,
    )
    return dict(result)


def cmd_learning_summary() -> dict:
    """Strategy Learning Engine summary (v0.9) — recommendation only, no auto-trading."""
    from learning_engine import compute_learning_summary
    result = compute_learning_summary()
    return dict(result)


def cmd_paper_basket(
    selection_date: str,
    holding_period: int = 5,
    num_stocks: int = 10,
    quantity: int = 10,
    method: str = "opportunity_score",
    min_score: float = 50.0,
    min_confidence: float = 50.0,
    min_rr: float = 2.0,
    include_watch: bool = False,
) -> dict:
    """Paper Basket Testing Layer (v1.0) — paper trading only, no real orders."""
    from paper_basket import run_paper_basket
    state = _load_state()
    cash = state.get("cash", 5000.0)
    result = run_paper_basket(
        selection_date=selection_date,
        holding_period=holding_period,
        num_stocks=num_stocks,
        quantity=quantity,
        method=method,
        capital=cash,
        min_score=min_score,
        min_confidence=min_confidence,
        min_rr=min_rr,
        include_watch=include_watch,
    )
    return dict(result)


def cmd_trade_intelligence(limit: int = 200) -> dict:
    """Trade Intelligence Database (Sprint 3) — historical completed paper trades."""
    from trade_intelligence import get_intelligence
    return get_intelligence(limit=limit)


def cmd_trade_intelligence_import() -> dict:
    """Backfill Trade Intelligence from existing paper portfolio history."""
    from trade_intelligence import import_existing
    return import_existing()


def cmd_predictive_intelligence(symbol: str) -> dict:
    """Historical evidence for a live candidate built from current data."""
    from predictive_intelligence import evaluate_symbol
    return evaluate_symbol(symbol)


def cmd_predictive_evaluate(candidate_json: str) -> dict:
    """Historical evidence for an explicit candidate payload (JSON string)."""
    from predictive_intelligence import evaluate_candidate
    candidate = json.loads(candidate_json)
    if not isinstance(candidate, dict) or not candidate.get("symbol"):
        return {"error": "candidate must be an object with a 'symbol' field"}
    return evaluate_candidate(candidate)


def cmd_historical_knowledge_build(years: str) -> dict:
    """Run the full Historical Knowledge Base build (long-running)."""
    from historical_knowledge_builder import build_knowledge_base
    try:
        y = int(years)
    except ValueError:
        y = 5
    if y not in (1, 3, 5):
        y = 5
    return build_knowledge_base(y)


def cmd_historical_knowledge_summary() -> dict:
    from historical_knowledge_builder import knowledge_summary
    return knowledge_summary()


def cmd_learning_insights() -> dict:
    from adaptive_learning import learning_insights
    return learning_insights()


def cmd_pattern_quality() -> dict:
    from adaptive_learning import pattern_quality
    return pattern_quality()


def cmd_trade_decisions() -> dict:
    from decision_service import get_trade_decisions
    return get_trade_decisions()


def cmd_historical_knowledge_trades(opts_json: str) -> dict:
    from historical_knowledge_builder import knowledge_trades
    try:
        opts = json.loads(opts_json) if opts_json else {}
    except Exception:
        opts = {}
    return knowledge_trades(
        limit=int(opts.get("limit", 100)),
        offset=int(opts.get("offset", 0)),
        symbol=opts.get("symbol"),
        strategy=opts.get("strategy"),
    )


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
        elif command == "market_replay" and len(args) >= 2:
            result = cmd_market_replay(
                scan_date      = args[1],
                holding_period = int(args[2]) if len(args) > 2 else 5,
                interval       = args[3] if len(args) > 3 else "daily",
            )
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
        elif command == "learning_summary":
            result = cmd_learning_summary()
        elif command == "paper_basket" and len(args) >= 2:
            result = cmd_paper_basket(
                selection_date = args[1],
                holding_period = int(args[2]) if len(args) > 2 else 5,
                num_stocks     = int(args[3]) if len(args) > 3 else 10,
                quantity       = int(args[4]) if len(args) > 4 else 10,
                method         = args[5] if len(args) > 5 else "opportunity_score",
                min_score      = float(args[6]) if len(args) > 6 else 50.0,
                min_confidence = float(args[7]) if len(args) > 7 else 50.0,
                min_rr         = float(args[8]) if len(args) > 8 else 2.0,
                include_watch  = (args[9].lower() in ("1", "true", "yes")) if len(args) > 9 else False,
            )
        elif command == "trade_intelligence":
            result = cmd_trade_intelligence(
                limit = int(args[1]) if len(args) > 1 else 200,
            )
        elif command == "trade_intelligence_import":
            result = cmd_trade_intelligence_import()
        elif command == "predictive_intelligence" and len(args) >= 2:
            result = cmd_predictive_intelligence(args[1])
        elif command == "historical_knowledge_build":
            result = cmd_historical_knowledge_build(args[1] if len(args) >= 2 else "5")
        elif command == "historical_knowledge_summary":
            result = cmd_historical_knowledge_summary()
        elif command == "historical_knowledge_trades":
            result = cmd_historical_knowledge_trades(args[1] if len(args) >= 2 else "{}")
        elif command == "learning_insights":
            result = cmd_learning_insights()
        elif command == "pattern_quality":
            result = cmd_pattern_quality()
        elif command == "trade_decisions":
            result = cmd_trade_decisions()
        elif command == "predictive_evaluate" and len(args) >= 2:
            result = cmd_predictive_evaluate(args[1])
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
