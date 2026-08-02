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

# Phase 19A: load the backend-stored Kite access token (if any) into the
# environment so every env-based reader picks it up transparently.
try:
    from kite_token_store import apply_to_env as _kite_apply_to_env
    _kite_apply_to_env()
except Exception:
    pass

from paper_trader import (
    get_portfolio, get_trades, execute_buy, execute_sell, reset_portfolio,
    get_trade_replay, get_strategy_performance, _load_state,
)
import config
from config import DEFAULT_WATCHLIST

WATCHLIST_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "watchlist.json")


def _load_watchlist() -> list[str]:
    """Load watchlist: Postgres (signals_store) → watchlist.json → defaults.

    An empty list is a valid persisted watchlist and is returned as-is.
    """
    try:
        import signals_store
        wl = signals_store.load_watchlist()
        if wl is not None:
            return wl
    except Exception:
        pass  # DB unreachable — fall through to the local file
    if os.path.exists(WATCHLIST_FILE):
        try:
            with open(WATCHLIST_FILE, "r") as f:
                data = json.load(f)
            if isinstance(data, dict):
                data = data.get("symbols", [])
            if isinstance(data, list):
                return [str(s) for s in data]
        except Exception:
            pass
    return list(DEFAULT_WATCHLIST)


def _save_watchlist(watchlist: list[str]) -> None:
    """Persist watchlist to Postgres (authoritative); signals_store also
    refreshes the local watchlist.json warm cache after a successful write."""
    import signals_store
    signals_store.save_watchlist(watchlist)


def _load_portfolio_with_live_prices() -> dict:
    state = _load_state()
    symbols = list(state.get("positions", {}).keys())
    if symbols:
        from market_data import get_multiple_ltp
        prices = get_multiple_ltp(symbols)
    else:
        prices = {}
    return dict(get_portfolio(prices))


# ── Commands ──────────────────────────────────────────────────────────────────

def cmd_portfolio() -> dict:
    return _load_portfolio_with_live_prices()


def cmd_signals() -> list:
    from intelligence import get_cached_enriched_signals
    data = get_cached_enriched_signals()
    if data:
        return data
    import signals_store as _sig_store
    return _sig_store.load_signals() or []


def cmd_ai_decisions() -> list:
    import signals_store as _sig_store
    return _sig_store.load_ai_decisions() or _read_json_cache("ai_decisions_cache.json")


def cmd_opportunity_scan() -> list:
    from intelligence import get_cached_opportunity_scan
    return get_cached_opportunity_scan()


def cmd_market_context() -> dict:
    from intelligence import get_cached_market_context
    return get_cached_market_context()


def cmd_trades() -> list:
    return list(get_trades())


def cmd_trades_all() -> list:
    from paper_trader import get_all_trades
    return list(get_all_trades())


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


def cmd_symbols() -> dict:
    """Return the known NSE symbol universe (NIFTY 50) with sector labels."""
    symbols = []
    for sector, syms in config.SECTOR_MAP.items():
        for sym in syms:
            symbols.append({"symbol": sym, "sector": sector})
    symbols.sort(key=lambda s: s["symbol"])
    return {"symbols": symbols}


def cmd_watchlist_add(symbol: str) -> dict:
    # Priority 3 (#26): central symbol validation (normalize, instrument
    # master check, duplicates, clear rejection reasons, audit tracking).
    import symbol_validation
    wl = _load_watchlist()
    r = symbol_validation.validate_symbol(symbol, context="watchlist", existing=wl)
    if not r["valid"]:
        out = {"error": r["reason"]}
        if r.get("suggestions"):
            out["suggestions"] = r["suggestions"]
        return out
    wl.append(r["symbol"])
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


def cmd_reset(reason: str = "Manual portfolio reset") -> dict:
    # Priority 2 (#21): archive the full session before wiping paper state.
    # A failed archive blocks the reset — no session may vanish unrecorded.
    import session_archive
    from config import INITIAL_CAPITAL
    archive = session_archive.archive_current_session(reason)
    reset_portfolio()
    return {"success": True,
            "message": f"Portfolio reset to ₹{INITIAL_CAPITAL:,.0f}",
            "archive_id": archive["id"]}


def cmd_update_stop(symbol: str, new_stop: float) -> dict:
    from paper_trader import update_stop_loss
    success, message = update_stop_loss(symbol, new_stop)
    return {"success": success, "message": message}


def cmd_session_archives() -> dict:
    import session_archive
    return {"archives": session_archive.list_archives()}


def cmd_session_archive_get(archive_id: str) -> dict:
    import session_archive
    rec = session_archive.get_archive(archive_id)
    if not rec:
        return {"success": False, "error": f"Archive {archive_id} not found"}
    return {"success": True, "archive": rec}


def cmd_session_restore_request(archive_id: str, confirmation: str) -> dict:
    import session_archive
    return session_archive.request_restore(archive_id, confirmation)


def cmd_session_restore_confirm(archive_id: str, confirmation: str,
                                restore_token: str) -> dict:
    import session_archive
    return session_archive.confirm_restore(archive_id, confirmation, restore_token)


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


def cmd_walk_forward_run(config_json: str) -> dict:
    """Run a full walk-forward validation (long-running, detached)."""
    from walk_forward_validator import run_validation
    try:
        cfg = json.loads(config_json) if config_json else {}
    except Exception:
        cfg = {}
    result = run_validation(cfg)
    # The full result is persisted to wf_result.json; return a light summary.
    if "error" in result:
        return result
    return {
        "completed": True,
        "run_seconds": result.get("run_seconds"),
        "verdict": (result.get("verdict") or {}).get("verdict"),
        "windows": len(result.get("windows", [])),
    }


def cmd_walk_forward_status() -> dict:
    from walk_forward_validator import read_status
    return read_status()


def cmd_walk_forward_result() -> dict:
    from walk_forward_validator import read_result
    return read_result()


def cmd_walk_forward_export(kind: str) -> dict:
    from walk_forward_validator import export_csv_path
    p = export_csv_path(kind)
    if not p:
        return {"error": f"No export available for '{kind}' — run a validation first."}
    return {"path": p}


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


def cmd_learning_review() -> dict:
    """v2.0 Adaptive Self-Evaluation — full Learning Review page payload."""
    from adaptive_adjustments import learning_review
    return learning_review()


def cmd_learning_cycle() -> dict:
    """v2.0 — run a learning cycle in Analysis Mode (proposes, applies nothing)."""
    from adaptive_adjustments import run_learning_cycle
    return run_learning_cycle()


def cmd_learning_approve(adj_id: str) -> dict:
    """v2.0 — approve a proposed adjustment (validated out-of-sample first)."""
    from adaptive_adjustments import approve_adjustment
    return approve_adjustment(int(adj_id))


def cmd_learning_reject(adj_id: str) -> dict:
    from adaptive_adjustments import reject_adjustment
    return reject_adjustment(int(adj_id))


def cmd_learning_rollback(version: str) -> dict:
    from model_versioning import rollback
    return rollback(int(version))


def cmd_hypothesis_approve(hyp_id: str) -> dict:
    """v2.1 — approve a hypothesis (validated out-of-sample first)."""
    from hypothesis_engine import approve_hypothesis
    return approve_hypothesis(int(hyp_id))


def cmd_hypothesis_reject(hyp_id: str) -> dict:
    from hypothesis_engine import reject_hypothesis
    return reject_hypothesis(int(hyp_id))


def cmd_portfolio_manager() -> dict:
    """v3.0 Portfolio Manager — ONE portfolio decision per refresh."""
    from portfolio_manager import get_portfolio_manager
    return get_portfolio_manager()


def cmd_evidence_research() -> dict:
    """v2.1 Evidence-Based Research — similarity evidence for every stock."""
    from similarity_engine import get_evidence_research
    return get_evidence_research()


def cmd_feature_importance() -> dict:
    """v2.2 Root Cause Intelligence — rolling feature-importance report and
    dynamic similarity-weight status (paper trading & research only)."""
    from root_cause_engine import get_feature_importance_report
    return get_feature_importance_report()


def cmd_trade_evaluations(limit: int = 200) -> list:
    from trade_evaluator import backfill_evaluations, get_evaluation_with_snapshot
    backfill_evaluations()
    return get_evaluation_with_snapshot(limit=limit)


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
        elif command == "signal_history":
            import signals_store as _ss
            limit = int(args[1]) if len(args) > 1 and args[1] not in ("", "-") else 30
            start = args[2] if len(args) > 2 and args[2] not in ("", "-") else None
            end   = args[3] if len(args) > 3 and args[3] not in ("", "-") else None
            result = _ss.load_signal_snapshots(limit=limit, start=start, end=end)
        elif command == "trades":
            result = cmd_trades()
        elif command == "trades_all":
            result = cmd_trades_all()
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
        elif command == "symbols":
            result = cmd_symbols()
        elif command == "symbol_search" and len(args) >= 2:
            import symbol_validation
            result = symbol_validation.search_symbols(args[1])
        elif command == "watchlist_add" and len(args) >= 2:
            result = cmd_watchlist_add(args[1])
        elif command == "watchlist_remove" and len(args) >= 2:
            result = cmd_watchlist_remove(args[1])
        elif command == "symbol_validate" and len(args) >= 2:
            import symbol_validation
            result = symbol_validation.validate_symbol(args[1], context="cli")
        elif command == "symbol_validation_log":
            import symbol_validation
            result = {"log": symbol_validation.get_validation_log(
                int(args[1]) if len(args) > 1 else 100)}
        elif command == "alert_queue_process":
            import alert_queue
            result = alert_queue.process_email_queue()
        elif command == "alert_queue_stats":
            import alert_queue
            result = alert_queue.queue_stats()
        elif command == "alert_deliveries":
            import alert_queue
            result = alert_queue.list_deliveries(
                channel=args[1] if len(args) > 1 and args[1] != "all" else None,
                status=args[2] if len(args) > 2 and args[2] != "all" else None,
                limit=int(args[3]) if len(args) > 3 else 100)
        elif command == "update_stop" and len(args) >= 3:
            result = cmd_update_stop(args[1], float(args[2]))
        elif command == "buy" and len(args) >= 4:
            result = cmd_buy(args[1], int(args[2]), float(args[3]),
                             args[4] if len(args) > 4 else "")
        elif command == "sell" and len(args) >= 4:
            result = cmd_sell(args[1], int(args[2]), float(args[3]),
                              args[4] if len(args) > 4 else "")
        elif command == "reset":
            result = cmd_reset(args[1] if len(args) > 1 else "Manual portfolio reset")
        elif command == "session_archives":
            result = cmd_session_archives()
        elif command == "session_archive_get" and len(args) >= 2:
            result = cmd_session_archive_get(args[1])
        elif command == "session_restore_request" and len(args) >= 3:
            result = cmd_session_restore_request(args[1], args[2])
        elif command == "session_restore_confirm" and len(args) >= 4:
            result = cmd_session_restore_confirm(args[1], args[2], args[3])
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
        elif command == "learning_review":
            result = cmd_learning_review()
        elif command == "learning_cycle":
            result = cmd_learning_cycle()
        elif command == "learning_approve" and len(args) >= 2:
            result = cmd_learning_approve(args[1])
        elif command == "learning_reject" and len(args) >= 2:
            result = cmd_learning_reject(args[1])
        elif command == "learning_rollback" and len(args) >= 2:
            result = cmd_learning_rollback(args[1])
        elif command == "hypothesis_approve" and len(args) >= 2:
            result = cmd_hypothesis_approve(args[1])
        elif command == "hypothesis_reject" and len(args) >= 2:
            result = cmd_hypothesis_reject(args[1])
        elif command == "portfolio_manager":
            result = cmd_portfolio_manager()
        elif command == "evidence_research":
            result = cmd_evidence_research()
        elif command == "feature_importance":
            result = cmd_feature_importance()
        elif command == "trade_evaluations":
            result = cmd_trade_evaluations(
                int(args[1]) if len(args) > 1 else 200)
        elif command == "walk_forward_run":
            result = cmd_walk_forward_run(args[1] if len(args) >= 2 else "{}")
        elif command == "walk_forward_status":
            result = cmd_walk_forward_status()
        elif command == "walk_forward_result":
            result = cmd_walk_forward_result()
        elif command == "walk_forward_export" and len(args) >= 2:
            result = cmd_walk_forward_export(args[1])
        elif command == "research_package_generate":
            from research_package_builder import generate_research_package
            result = generate_research_package()
        elif command == "chatgpt_report_generate":
            from research_package_builder import generate_chatgpt_report
            result = generate_chatgpt_report()
        elif command == "experiment_submit" and len(args) >= 2:
            from experiment_manager import submit_experiment
            result = submit_experiment(json.loads(args[1]))
        elif command == "experiment_list":
            from experiment_manager import list_experiments
            result = list_experiments()
        elif command == "experiment_run" and len(args) >= 2:
            from experiment_manager import run_experiment
            result = run_experiment(args[1])
        elif command == "experiment_get" and len(args) >= 2:
            from experiment_manager import get_experiment
            result = get_experiment(args[1])
        elif command == "experiment_leaderboard":
            from experiment_manager import get_leaderboard
            result = get_leaderboard()
        elif command == "experiment_delete" and len(args) >= 2:
            from experiment_manager import delete_experiment
            result = delete_experiment(args[1])
        elif command == "experiment_analyze" and len(args) >= 2:
            # Phase 4.2 — Strategy Improvement Framework (analysis only)
            import os as _os
            import re as _re
            from experiment_manager import EXPERIMENTS_DIR as _EXP_DIR
            if not _re.fullmatch(r"[A-Za-z0-9_-]{1,64}", args[1]):
                result = {"error": "Invalid experiment id"}
            else:
                from strategy_analyzer import analyze_experiment
                result = analyze_experiment(_os.path.join(_EXP_DIR, args[1]))
        elif command == "experiment_analysis_get" and len(args) >= 2:
            import os as _os
            import re as _re
            from experiment_manager import EXPERIMENTS_DIR as _EXP_DIR
            if not _re.fullmatch(r"[A-Za-z0-9_-]{1,64}", args[1]):
                result = {"error": "Invalid experiment id"}
            else:
                _ap = _os.path.join(_EXP_DIR, args[1], "analysis.json")
                if _os.path.exists(_ap):
                    with open(_ap) as _f:
                        result = json.load(_f)
                else:
                    result = {"error": "No analysis found for this experiment. "
                                       "Run it (or POST /analyze) to generate one."}
        elif command in ("report_get", "report_status", "report_generate",
                         "report_export_html", "report_export_csv") and len(args) >= 2:
            # Phase 4.3 — Research report engine (analysis only)
            import os as _os
            import re as _re
            from experiment_manager import EXPERIMENTS_DIR as _EXP_DIR
            if not _re.fullmatch(r"[A-Za-z0-9_-]{1,64}", args[1]):
                result = {"success": False,
                          "error": {"code": "INVALID_ID",
                                    "message": "Invalid experiment id.",
                                    "details": "id must match [A-Za-z0-9_-]{1,64}"}}
            else:
                _dir = _os.path.join(_EXP_DIR, args[1])
                if command == "report_get":
                    from report_engine import get_report
                    _v = None
                    if len(args) >= 3 and args[2].isdigit():
                        _v = int(args[2])
                    result = get_report(_dir, version=_v)
                elif command == "report_status":
                    from report_engine import report_status
                    result = report_status(_dir)
                elif command == "report_generate":
                    from report_engine import generate_report
                    _force = len(args) >= 3 and args[2] == "force"
                    result = generate_report(_dir, force=_force)
                    if result.get("success") and not result.get("skipped"):
                        try:
                            from report_exports import export_html
                            export_html(_dir)
                        except Exception:
                            pass
                elif command == "report_export_html":
                    from report_exports import export_html
                    result = export_html(_dir)
                elif command == "report_export_csv":
                    from report_exports import export_csv_zip
                    result = export_csv_zip(_dir)
        elif command == "research_intelligence":
            # Phase 5 — cross-experiment research intelligence (analysis only)
            from research_intelligence import build_intelligence
            result = build_intelligence()
        elif command == "experiment_compare" and len(args) >= 2:
            import re as _re
            from research_intelligence import compare_experiments
            _ids = [i for i in args[1].split(",") if _re.fullmatch(r"[A-Za-z0-9_-]{1,64}", i)]
            result = compare_experiments(_ids[:12])
        elif command == "trade_diagnostics" and len(args) >= 2:
            import os as _os
            import re as _re
            from experiment_manager import EXPERIMENTS_DIR as _EXP_DIR
            if not _re.fullmatch(r"[A-Za-z0-9_-]{1,64}", args[1]):
                result = {"success": False,
                          "error": {"code": "INVALID_ID",
                                    "message": "Invalid experiment id.",
                                    "details": "id must match [A-Za-z0-9_-]{1,64}"}}
            else:
                from research_intelligence import trade_diagnostics
                result = trade_diagnostics(_os.path.join(_EXP_DIR, args[1]))
        elif command == "phase7_health":
            # Quick provider probe — fetches 3 probe symbols only (fast, ~2-3s).
            # If a cached full scan exists, merges its summary in.
            from live_data_provider import LiveDataProvider
            from live_scan_engine import load_cached_scan, SCAN_CACHE_FILE
            import uuid as _uuid, datetime as _dt
            _probe_syms = ["RELIANCE", "INFY", "TCS"]
            _provider = LiveDataProvider()
            _snap_id  = _uuid.uuid4().hex[:8]
            _snap_ts  = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            _fresults = {s.upper(): _provider.fetch_symbol(s) for s in _probe_syms}
            _health   = _provider.build_health_report(_fresults, _snap_id, _snap_ts)
            from dataclasses import asdict as _asdict
            _cached = load_cached_scan()
            result  = {
                "success": True,
                "provider_health": _asdict(_health),
                "scan_audit": _cached.get("scan_audit") if _cached else None,
                "summary": _cached.get("summary") if _cached else None,
                "cache_exists": _cached is not None,
                "cache_scan_id": _cached.get("scan_id") if _cached else None,
                "cache_snapshot_ts": _cached.get("snapshot_ts") if _cached else None,
                "label": "PAPER / LIVE DATA VALIDATION",
                "note": "Provider health probed with 3 symbols. Run /api/live-data/scan for full NIFTY 50 scan.",
            }
        # ── Phase 11 — Live Data Foundation ──────────────────────────────────
        elif command == "market_status":
            from market_hours import market_status
            result = {"success": True, **market_status()}
        elif command == "quotes":
            from live_quote_service import get_quotes
            _syms = args[1].split(",") if len(args) > 1 and args[1] else ["NIFTY", "BANKNIFTY", "INDIAVIX"]
            _force = len(args) > 2 and args[2] == "force"
            result = {"success": True, **get_quotes(_syms, force=_force)}
        elif command == "live_health_v2":
            from market_hours import market_status
            from live_quote_service import provider_status
            from live_scan_engine import load_cached_scan
            _cached = load_cached_scan()
            result = {
                "success": True,
                "market": market_status(),
                "quote_provider": provider_status(),
                "scan_provider_health": _cached.get("provider_health") if _cached else None,
                "scan_id": _cached.get("scan_id") if _cached else None,
                "snapshot_ts": _cached.get("snapshot_ts") if _cached else None,
                "label": "PAPER / LIVE DATA VALIDATION",
            }
        elif command == "diagnostic_bundle":
            from phase11_diagnostics import build_diagnostic_bundle
            result = {"success": True, "bundle": build_diagnostic_bundle()}
        elif command == "system_event" and len(args) >= 2:
            from copilot_engine import record_system_event
            _payload = json.loads(args[2]) if len(args) > 2 else {}
            result = record_system_event(
                args[1],
                symbol=_payload.get("symbol"),
                reason=_payload.get("reason", ""),
                severity=_payload.get("severity"),
            )
        elif command == "phase7_scan":
            from live_scan_engine import get_or_run_scan
            import time as _time
            force = len(args) > 1 and args[1] == "force"
            _scan_t0 = _time.time()
            result = get_or_run_scan(max_age_s=600, force=force)
            result["success"] = True
            # Phase 20: record MANUAL scan runs in the durable history.
            if not result.get("_from_cache"):
                try:
                    from phase20_scheduler import record_manual_scan
                    record_manual_scan(result, _time.time() - _scan_t0)
                except Exception:
                    pass
                # Phase 22: manual scans get the same post-scan regeneration
                # pipeline + atomic bundle publish as scheduled scans.
                try:
                    from scan_pipeline import run_post_scan_pipeline
                    result["pipeline"] = run_post_scan_pipeline(
                        result, trigger="MANUAL")
                except Exception as _pexc:
                    result["pipeline"] = {"status": "FAILED",
                                          "error": str(_pexc)[:300]}
            # Phase 19B: compact scan-run metadata for the UI/route response.
            try:
                _audit = result.get("scan_audit") or {}
                _health = result.get("provider_health") or {}
                _safety = result.get("safety") or {}
                result["scan_run"] = {
                    "scan_id": result.get("scan_id"),
                    "status": "SUCCESS",
                    "started_at": result.get("snapshot_ts"),
                    "completed_at": _audit.get("scan_completed_ts") or result.get("snapshot_ts"),
                    "snapshot_ts": result.get("snapshot_ts"),
                    "provider": _safety.get("data_provider") or _health.get("provider"),
                    "from_cache": bool(result.get("_from_cache")),
                    "symbols_requested": _health.get("symbols_requested"),
                    "symbols_received": _health.get("symbols_succeeded"),
                    "symbols_stale": _health.get("symbols_stale"),
                    "symbols_unavailable": _health.get("symbols_unavailable"),
                    "missing_symbols": _health.get("unavailable_symbols") or [],
                    "stale_symbols": _health.get("stale_symbols") or [],
                }
            except Exception:
                pass
        elif command == "scan_status":
            from scan_state_store import load_latest_meta
            result = {"success": True, "latest_scan": load_latest_meta()}
        elif command == "scheduled_scan_tick":
            # Phase 20: market-hours auto-scan tick with durable settings,
            # scheduler health, scan-run history, and paper management.
            # Safe under Autoscale — freshness check + distributed lease
            # prevent duplicate scans.
            from phase20_scheduler import run_tick
            result = run_tick()

        # ── Phase 20 — settings / scheduler health / history / paper engine ──
        elif command == "phase20_settings":
            from phase20_store import get_settings
            result = {"success": True, "settings": get_settings()}
        elif command == "phase20_settings_update":
            from phase20_store import update_settings
            _payload = json.loads(args[1]) if len(args) > 1 else {}
            try:
                _updated = update_settings(
                    _payload.get("patch") or {},
                    confirmation_text=_payload.get("confirmation_text"),
                )
                result = {"success": True, "settings": _updated}
            except ValueError as _ve:
                result = {"success": False, "error": str(_ve)}
        elif command == "phase20_email_test":
            from email_alerts import send_test_email, provider_status
            _addr = args[1] if len(args) > 1 and args[1] else None
            result = {**send_test_email(_addr), "status": provider_status()}
        elif command == "phase20_email_send_daily_summary":
            # Manual, on-demand send of today's daily summary email.
            # Bypasses the opt-in toggle (explicit user action) but still
            # requires a valid configured address and provider.
            from email_alerts import maybe_send_daily_summary_email, provider_status
            import phase20_store as _p20store
            _settings = dict(_p20store.get_settings())
            _settings["daily_summary_email_enabled"] = True
            _report = None
            try:
                from phase22_report import build_daily_report
                _report = build_daily_report()
            except Exception as _exc:  # noqa: BLE001 — send with fallback body
                _report = None
            _send = maybe_send_daily_summary_email(_report, settings=_settings)
            result = {"success": bool(_send.get("sent")), **_send,
                      "status": provider_status()}
        elif command == "phase20_email_preview_daily_summary":
            # Compose today's daily summary email without delivering it.
            from email_alerts import _compose_daily_summary
            _report = None
            try:
                from phase22_report import build_daily_report
                _report = build_daily_report()
            except Exception:  # noqa: BLE001 — preview with fallback body
                _report = None
            _parts = _compose_daily_summary(_report)
            result = {"success": True, "subject": _parts["subject"],
                      "text": _parts["text"],
                      "html": _parts.get("html", ""),
                      "report_available": _report is not None}
        elif command == "phase20_email_preview_alert":
            # Compose a sample critical-alert email (the new formatted HTML
            # style shared by performance / circuit-breaker alerts) without
            # delivering it.
            from email_alerts import _compose
            _parts = _compose(
                "TEST", "Test alert email",
                "This is a test of your losing-streak / circuit-breaker email "
                "alerts. If you received this, email delivery is working.",
                "INFO",
            )
            result = {"success": True, "subject": _parts["subject"],
                      "text": _parts["text"],
                      "html": _parts.get("html", "")}
        elif command == "phase20_email_status":
            from email_alerts import provider_status, get_last_send
            result = {"success": True, **provider_status(),
                      "last_send": get_last_send()}
        elif command == "phase20_scheduler_health":
            from phase20_store import get_scheduler_health, kv_get
            _activity = {
                "scan_progress": kv_get("scan_progress"),
                "skipped_active_count": int(kv_get("scan_skipped_active_count") or 0),
            }
            try:
                from kite_quote_provider import (
                    kite_available, kite_configured, provider_label,
                )
                import kite_token_store as _kts
                _activity["kite"] = {
                    # Honest, cheap status: creds present AND no recent auth
                    # failure recorded by the verified session probe.
                    "session_active": kite_available() and not _kts.recent_auth_failure(),
                    "configured": kite_configured(),
                    "provider_label": provider_label(),
                }
            except Exception:
                _activity["kite"] = None
            result = {"success": True, "scheduler": get_scheduler_health(),
                      "activity": _activity}
        elif command == "phase20_scan_history":
            from phase20_store import list_scan_runs
            _limit = int(args[1]) if len(args) > 1 else 50
            result = {"success": True, "runs": list_scan_runs(_limit)}
        elif command == "phase20_notifications":
            from phase20_store import list_notifications
            _limit = int(args[1]) if len(args) > 1 else 100
            result = {"success": True, "notifications": list_notifications(_limit)}
        elif command == "phase20_notifications_read":
            from phase20_store import mark_notifications_read
            _ids = json.loads(args[1]) if len(args) > 1 else None
            result = {"success": True, "marked": mark_notifications_read(_ids)}
        elif command == "phase20_evaluate":
            from phase20_gates import evaluate_entries
            result = evaluate_entries()
            result["success"] = True
        elif command == "phase20_ledger":
            from phase20_executor import get_ledger
            _limit = int(args[1]) if len(args) > 1 else 200
            result = {"success": True, "ledger": get_ledger(_limit)}
        elif command == "phase20_positions":
            from phase20_executor import get_open_positions_view
            result = {"success": True, "positions": get_open_positions_view()}
        elif command == "phase20_exit_tick":
            from phase20_store import get_settings as _p20gs
            from phase20_exits import manage_open_positions
            result = manage_open_positions(_p20gs())
            result["success"] = True
        elif command == "phase20_entry_tick":
            from phase20_store import get_settings as _p20gs
            from phase20_executor import run_auto_entries
            result = run_auto_entries(_p20gs())
            result["success"] = True
        elif command == "phase20_replay":
            from phase20_executor import replay_trade
            result = replay_trade(args[1] if len(args) > 1 else "")
            result["success"] = True
        elif command == "phase20_circuit_breaker":
            from phase20_store import get_settings as _p20gs
            from phase20_circuit_breaker import (
                evaluate_and_maybe_trip, get_audit_log, RESUME_CONFIRMATION_TEXT,
            )
            _state = evaluate_and_maybe_trip(_p20gs())
            result = {"success": True, "circuit_breaker": _state,
                      "audit": get_audit_log(20),
                      "resume_confirmation_text": RESUME_CONFIRMATION_TEXT}
        elif command == "phase20_circuit_breaker_resume":
            from phase20_circuit_breaker import resume as _cb_resume
            _payload = json.loads(args[1]) if len(args) > 1 else {}
            try:
                _state = _cb_resume(
                    _payload.get("confirmation_text") or "",
                    reviewed_by=str(_payload.get("reviewed_by") or "user"))
                result = {"success": True, "circuit_breaker": _state}
            except ValueError as _ve:
                result = {"success": False, "error": str(_ve)}
        elif command == "phase20_validation":
            from phase20_validation import get_validation_status
            result = get_validation_status()
            result["success"] = True
        elif command == "phase7_recommendations":
            from live_scan_engine import get_or_run_scan
            full = get_or_run_scan(max_age_s=600)
            result = {"success": True, "recommendations": full.get("recommendations", []),
                      "scan_id": full.get("scan_id"), "snapshot_ts": full.get("snapshot_ts"),
                      "summary": full.get("summary"), "label": "PAPER / LIVE DATA VALIDATION"}
        elif command == "phase7_report":
            from live_scan_engine import get_or_run_scan
            from phase7_report import generate_report
            scan = get_or_run_scan(max_age_s=600)
            result = generate_report(scan)
            result["success"] = True

        # ── Phase 8 — Broker Integration & Live Execution Readiness ──────────
        elif command == "phase8_status":
            from broker_client import get_broker_client, masked_creds
            from execution_engine import (get_execution_mode, get_safety_controls,
                                          get_daily_order_count)
            from live_scan_engine import load_cached_scan
            from dataclasses import asdict as _dc_asdict
            _client = get_broker_client()
            _conn   = _client.test_connection()
            _scan   = load_cached_scan()
            _dq     = "UNKNOWN"
            _scan_ts = None
            if _scan:
                _ph = _scan.get("provider_health", {})
                _dq = "LIVE" if _ph.get("quality_summary", {}).get("LIVE", 0) > 0 else \
                      "NEAR_LIVE" if _ph.get("quality_summary", {}).get("NEAR_LIVE", 0) > 0 else \
                      "STALE"
                _scan_ts = _scan.get("snapshot_ts")
            _sc = get_safety_controls()
            result = {
                "success": True,
                "execution_mode": get_execution_mode(),
                "broker": _dc_asdict(_conn),
                "safety_controls": _dc_asdict(_sc),
                "daily_orders_today": get_daily_order_count(),
                "data_quality": _dq,
                "last_scan_ts": _scan_ts,
                "credentials": masked_creds(),
                "label": "PAPER / LIVE DATA VALIDATION",
                "warning": ("Research and assisted-execution tool only. "
                            "User is responsible for every live order."),
            }
        elif command == "phase8_health":
            from broker_client import get_broker_client, masked_creds
            from dataclasses import asdict as _dc_asdict
            _client = get_broker_client()
            _conn   = _client.test_connection()
            result  = {"success": True, "broker": _dc_asdict(_conn),
                       "credentials": masked_creds(),
                       "is_mock": _conn.is_mock,
                       "label": "PAPER / LIVE DATA VALIDATION"}
        elif command == "phase8_account":
            from broker_client import get_broker_client
            from dataclasses import asdict as _dc_asdict
            _client = get_broker_client()
            try:
                _profile  = _dc_asdict(_client.get_profile())
                _margins  = _dc_asdict(_client.get_margins())
                _holdings = [_dc_asdict(h) for h in _client.get_holdings()]
                _positions = [_dc_asdict(p) for p in _client.get_positions()]
                _orders   = [_dc_asdict(o) for o in _client.get_orders(limit=20)]
                result = {"success": True, "profile": _profile, "margins": _margins,
                          "holdings": _holdings, "positions": _positions,
                          "orders": _orders, "is_mock": _client.is_mock}
            except Exception as e:
                result = {"success": False, "error": str(e)}
        elif command == "phase8_mode_get":
            from execution_engine import get_execution_mode
            result = {"success": True, "execution_mode": get_execution_mode()}
        elif command == "phase8_mode_set":
            if len(args) < 2:
                result = {"success": False, "error": "Usage: phase8_mode_set <mode>"}
            else:
                from execution_engine import set_execution_mode
                _mode = args[1].upper()
                set_execution_mode(_mode)
                result = {"success": True, "execution_mode": _mode,
                          "warning": "LIVE_ASSISTED requires explicit per-order confirmation. No auto-execution."
                                     if _mode == "LIVE_ASSISTED" else ""}
        elif command == "phase8_readiness":
            from broker_client import get_broker_client
            from execution_engine import get_execution_mode
            from live_scan_engine import load_cached_scan
            from readiness_checker import LiveReadinessChecker
            from dataclasses import asdict as _dc_asdict
            import json as _json
            _client = get_broker_client()
            _conn   = _client.test_connection()
            _margins = _client.get_margins()
            _scan   = load_cached_scan()
            _dq     = "UNKNOWN"; _scan_ts = None
            if _scan:
                _ph = _scan.get("provider_health", {})
                _dq = next((q for q in ["LIVE","NEAR_LIVE","STALE","UNAVAILABLE"]
                             if _ph.get("quality_summary",{}).get(q,0) > 0), "UNKNOWN")
                _scan_ts = _scan.get("snapshot_ts")
            from paper_trader import STATE_FILE
            _paper_count = 0
            try:
                _state = _json.load(open(STATE_FILE))
                _paper_count = len([t for t in _state.get("trades", []) if t.get("action") == "BUY"])
            except Exception:
                pass
            _checker = LiveReadinessChecker(
                broker_connection_status=_dc_asdict(_conn),
                available_cash=_margins.available_cash,
                data_quality=_dq, last_scan_ts=_scan_ts,
                paper_trade_count=_paper_count,
            )
            _r = _checker.check()
            result = {"success": True, **_dc_asdict(_r)}
        elif command == "phase8_preview":
            if len(args) < 4:
                result = {"success": False, "error": "Usage: phase8_preview <symbol> <side> <qty> [entry] [sl] [target]"}
            else:
                import json as _json
                from broker_client import get_broker_client
                from execution_engine import get_engine, get_execution_mode
                from live_scan_engine import load_cached_scan
                from dataclasses import asdict as _dc_asdict
                _sym   = args[1].upper()
                _side  = args[2].upper()
                _qty   = int(args[3])
                _entry = float(args[4]) if len(args) > 4 else 0.0
                _sl    = float(args[5]) if len(args) > 5 else 0.0
                _tgt   = float(args[6]) if len(args) > 6 else 0.0
                _client = get_broker_client()
                _conn   = _client.test_connection()
                _margins = _client.get_margins()
                _scan   = load_cached_scan()
                _dq     = "UNKNOWN"
                if _scan and _entry == 0.0:
                    for _rec in _scan.get("recommendations", []):
                        if _rec.get("symbol") == _sym:
                            _entry = _rec.get("entry_price", 0.0)
                            _sl    = _sl or _rec.get("stop_loss", 0.0)
                            _tgt   = _tgt or _rec.get("target_price", 0.0)
                            _dq    = _rec.get("data_quality", "UNKNOWN")
                            break
                _engine = get_engine(_client)
                _preview = _engine.build_preview(
                    symbol=_sym, side=_side, quantity=_qty,
                    entry_price=_entry, stop_loss=_sl, target=_tgt,
                    data_quality=_dq, available_cash=_margins.available_cash,
                    broker_connected=_conn.connected,
                )
                result = {"success": True, **_dc_asdict(_preview)}
        elif command == "phase8_confirm1":
            if len(args) < 3:
                result = {"success": False, "error": "Usage: phase8_confirm1 <preview_id> <token>"}
            else:
                from execution_engine import get_engine
                result = get_engine().step1_confirm(args[1], args[2])
        elif command == "phase8_confirm2":
            if len(args) < 3:
                result = {"success": False, "error": "Usage: phase8_confirm2 <preview_id> <token>"}
            else:
                from broker_client import get_broker_client
                from execution_engine import get_engine
                _client = get_broker_client()
                result = get_engine(_client).step2_submit(args[1], args[2])
        elif command == "phase8_kill_switch":
            if len(args) < 2:
                result = {"success": False, "error": "Usage: phase8_kill_switch <on|off>"}
            else:
                from execution_engine import toggle_kill_switch
                from dataclasses import asdict as _dc_asdict
                _activate = args[1].lower() == "on"
                _sc = toggle_kill_switch(_activate)
                result = {"success": True, "kill_switch": _activate,
                          "safety_controls": _dc_asdict(_sc),
                          "message": f"Kill switch {'ACTIVATED — all orders blocked' if _activate else 'DEACTIVATED'}"}
        elif command == "phase8_audit":
            from execution_engine import get_audit_log
            _limit = int(args[1]) if len(args) > 1 else 100
            result = {"success": True, "audit_log": get_audit_log(_limit),
                      "total_returned": min(_limit, 500)}
        elif command == "phase8_export":
            import json as _j
            from broker_client import get_broker_client, masked_creds
            from execution_engine import (get_execution_mode, get_safety_controls,
                                          get_audit_log)
            from live_scan_engine import load_cached_scan
            from readiness_checker import LiveReadinessChecker
            from dataclasses import asdict as _dc_asdict
            import csv as _csv
            _kind = args[1].lower() if len(args) > 1 else "json"
            _client  = get_broker_client()
            _conn    = _client.test_connection()
            _margins = _client.get_margins()
            _scan    = load_cached_scan()
            _dq = "UNKNOWN"; _scan_ts = None
            if _scan:
                _ph = _scan.get("provider_health", {})
                _dq = next((q for q in ["LIVE","NEAR_LIVE","STALE","UNAVAILABLE"]
                             if _ph.get("quality_summary",{}).get(q,0)>0), "UNKNOWN")
                _scan_ts = _scan.get("snapshot_ts")
            _checker = LiveReadinessChecker(
                broker_connection_status=_dc_asdict(_conn),
                available_cash=_margins.available_cash,
                data_quality=_dq, last_scan_ts=_scan_ts)
            _ready = _checker.check()
            _audit = get_audit_log(500)
            _bundle = {
                "generated_at": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "phase": "8", "label": "PAPER / LIVE DATA VALIDATION",
                "execution_mode": get_execution_mode(),
                "credentials": masked_creds(),
                "broker_health": _dc_asdict(_conn),
                "margins": _dc_asdict(_margins),
                "readiness": _dc_asdict(_ready),
                "safety_controls": _dc_asdict(get_safety_controls()),
                "audit_log": _audit,
            }
            import os as _os2
            _export_dir = _os.path.join(_os.path.dirname(__file__), "exports")
            _os2.makedirs(_export_dir, exist_ok=True)
            if _kind == "json":
                _fpath = _os.path.join(_export_dir, "phase8_export.json")
                with open(_fpath, "w") as _f:
                    _j.dump(_bundle, _f, indent=1, default=str)
            else:
                _fpath = _os.path.join(_export_dir, "phase8_export.csv")
                with open(_fpath, "w", newline="") as _f:
                    _w = _csv.writer(_f)
                    _w.writerow(["## Phase 8 Broker & Execution Export", _bundle["generated_at"]])
                    _w.writerow(["execution_mode", _bundle["execution_mode"]])
                    _w.writerow(["broker_connected", _bundle["broker_health"].get("connected")])
                    _w.writerow(["readiness_status", _bundle["readiness"]["status"]])
                    _w.writerow(["readiness_score", _bundle["readiness"]["score"]])
                    _w.writerow([]); _w.writerow(["## Audit Log"])
                    if _audit:
                        _cols = sorted({k for e in _audit for k in e.keys()})
                        _w.writerow(_cols)
                        for _e in _audit:
                            _w.writerow([_e.get(_c, "") for _c in _cols])
            result = {"success": True, "file": _fpath, "kind": _kind}

        # ── Phase 9 — AI Copilot, Alerts & Explainability ─────────────────────
        elif command == "phase9_copilot":
            from copilot_engine import copilot_summary, record_confidence_snapshot
            record_confidence_snapshot()  # idempotent per scan_id
            result = copilot_summary()
        elif command == "phase9_alerts_generate":
            from copilot_engine import generate_alerts, record_confidence_snapshot
            record_confidence_snapshot()
            result = generate_alerts()
        elif command == "phase9_alerts":
            from copilot_engine import list_alerts
            _limit = int(args[1]) if len(args) > 1 else 100
            result = list_alerts(_limit)
        elif command == "phase9_alerts_read":
            from copilot_engine import mark_alerts_read
            result = mark_alerts_read(args[1] if len(args) > 1 else "all")
        elif command == "phase9_briefing":
            from copilot_engine import daily_briefing
            result = daily_briefing()
        elif command == "phase9_explanations":
            from copilot_engine import trade_explanations
            _limit = int(args[1]) if len(args) > 1 else 20
            result = trade_explanations(_limit)
        elif command == "phase9_explain":
            if len(args) < 2:
                result = {"success": False, "error": "Usage: phase9_explain <symbol>"}
            else:
                from copilot_engine import trade_explanation
                result = trade_explanation(args[1])
        elif command == "phase9_why_not":
            if len(args) < 2:
                result = {"success": False, "error": "Usage: phase9_why_not <symbol>"}
            else:
                from copilot_engine import why_not
                result = why_not(args[1])
        elif command == "phase9_watchlist_insights":
            from copilot_engine import watchlist_insights
            result = watchlist_insights()
        elif command == "phase9_confidence_history":
            from copilot_engine import confidence_history, record_confidence_snapshot
            record_confidence_snapshot()
            result = confidence_history(args[1] if len(args) > 1 else None)
        elif command == "phase9_export":
            from copilot_engine import export_phase9
            result = export_phase9(args[1].lower() if len(args) > 1 else "json")

        # ── Phase 10.1 — Performance Analytics ───────────────────────────────
        elif command == "phase10_analytics":
            from phase10_analytics import performance_analytics
            result = performance_analytics()
        elif command == "phase10_export":
            from phase10_analytics import export_analytics
            result = export_analytics(args[1].lower() if len(args) > 1 else "json")
        elif command == "review_package":
            from review_package import build_package
            result = build_package(args[1] if len(args) > 1 else None)

        # ── Phase 11 — Institutional Risk Engine ────────────────────────────
        elif command == "risk_dashboard":
            from phase11_risk import portfolio_risk
            result = portfolio_risk()
        elif command == "risk_assess":
            from phase11_risk import assess_trade
            if len(args) < 4:
                result = {"success": False, "error": "Usage: risk_assess <symbol> <quantity> <price> [stop_loss] [confidence]"}
            else:
                def _optf(v):
                    return None if v is None or str(v).lower() in ("null", "none", "") else float(v)
                result = assess_trade(
                    args[1], int(args[2]), float(args[3]),
                    _optf(args[4]) if len(args) > 4 else None,
                    _optf(args[5]) if len(args) > 5 else None,
                )
        elif command == "risk_position_size":
            from phase11_risk import position_size
            if len(args) < 3:
                result = {"success": False, "error": "Usage: risk_position_size <symbol> <price> [stop_loss] [confidence]"}
            else:
                def _optf(v):
                    return None if v is None or str(v).lower() in ("null", "none", "") else float(v)
                result = position_size(
                    args[1], float(args[2]),
                    _optf(args[3]) if len(args) > 3 else None,
                    _optf(args[4]) if len(args) > 4 else None,
                )
        elif command == "risk_analytics":
            from phase11_risk import risk_analytics
            result = risk_analytics()
        elif command == "risk_approval_cards":
            from phase11_risk import approval_cards
            result = approval_cards()
        elif command == "risk_alerts":
            from phase11_risk import risk_alerts
            result = risk_alerts()
        elif command == "risk_kill_switch":
            from phase11_risk import kill_switch_status, trigger_kill_switch, resume_trading
            sub = args[1] if len(args) > 1 else "status"
            if sub == "trigger":
                result = trigger_kill_switch(args[2] if len(args) > 2 else "Manual trigger", source="manual")
            elif sub == "resume":
                result = resume_trading(acknowledge=(len(args) > 2 and args[2].lower() == "acknowledge"))
            else:
                result = {"success": True, "kill_switch": kill_switch_status()}
        elif command == "risk_report":
            from phase11_risk import risk_report
            result = risk_report(args[1] if len(args) > 1 else "risk_summary")
        elif command == "risk_config":
            from phase11_risk import get_config, update_config
            if len(args) > 1:
                result = update_config(json.loads(args[1]))
            else:
                result = {"success": True, "config": get_config()}

        elif command == "meta_health":
            from meta_learning import cmd_health
            result = cmd_health()
        elif command == "meta_failures":
            from meta_learning import cmd_failures
            result = cmd_failures()
        elif command == "meta_eligibility":
            from meta_learning import cmd_eligibility
            result = cmd_eligibility()
        elif command == "meta_improvements":
            from meta_learning import cmd_improvements
            result = cmd_improvements()
        elif command == "meta_contradictions":
            from meta_learning import cmd_contradictions
            result = cmd_contradictions()
        elif command == "meta_compare" and len(args) >= 3:
            from meta_learning import cmd_compare
            result = cmd_compare(args[1], args[2])
        elif command == "meta_create_mutation" and len(args) >= 4:
            from meta_learning import cmd_create_mutation
            result = cmd_create_mutation(args[1], args[2], args[3],
                                         args[4] if len(args) >= 5 else "")
        elif command == "meta_export":
            from meta_learning import cmd_export
            result = cmd_export()
        elif command == "evolution_registry":
            from strategy_evolution import cmd_registry
            result = cmd_registry()
        elif command == "evolution_mutate" and len(args) >= 2:
            from strategy_evolution import cmd_mutate
            _params = json.loads(args[2]) if len(args) >= 3 else None
            result = cmd_mutate(args[1], _params)
        elif command == "evolution_set_status" and len(args) >= 3:
            from strategy_evolution import cmd_set_status
            result = cmd_set_status(args[1], args[2], args[3] if len(args) >= 4 else "")
        elif command == "evolution_ab_test" and len(args) >= 5:
            from strategy_evolution import cmd_ab_test
            result = cmd_ab_test(args[1], args[2], args[3], args[4])
        elif command == "evolution_ab_list":
            from strategy_evolution import cmd_ab_list
            result = cmd_ab_list()
        elif command == "evolution_robustness" and len(args) >= 2:
            from strategy_evolution import cmd_robustness
            result = cmd_robustness(args[1])
        elif command == "evolution_evaluate" and len(args) >= 4:
            from strategy_evolution import cmd_evaluate
            result = cmd_evaluate(args[1], args[2], args[3])
        elif command == "evolution_tree":
            from strategy_evolution import cmd_tree
            result = cmd_tree()
        elif command == "evolution_leaderboard":
            from strategy_evolution import cmd_leaderboard
            result = cmd_leaderboard()
        elif command == "evolution_knowledge":
            from strategy_evolution import cmd_knowledge
            result = cmd_knowledge()
        elif command == "evolution_export":
            from strategy_evolution import cmd_export
            result = cmd_export()
        elif command == "phase5_export":
            # Phase 5 review CSV export — read-only reporting, no trading impact
            from phase5_export import cmd_phase5_export
            from experiment_manager import (
                list_experiments as _p5_list, list_batches as _p5_batches,
                get_leaderboard as _p5_lb,
            )
            result = cmd_phase5_export(
                args[1] if len(args) > 1 else "generate",
                {
                    "experiment_list": _p5_list,
                    "experiment_batch_list": _p5_batches,
                    "experiment_leaderboard": _p5_lb,
                    "learning_insights": cmd_learning_insights,
                    "learning_review": cmd_learning_review,
                    "pattern_quality": cmd_pattern_quality,
                    "feature_importance": cmd_feature_importance,
                    "trade_replay": cmd_trade_replay,
                    "ai_decisions": cmd_ai_decisions,
                },
            )
        elif command == "experiment_check_running":
            from experiment_manager import check_any_running
            result = check_any_running()
        elif command == "experiment_batch_list":
            from experiment_manager import list_batches
            result = list_batches()
        elif command == "experiment_batch_get" and len(args) >= 2:
            from experiment_manager import get_batch
            result = get_batch(args[1])
        elif command == "experiment_check_duplicate" and len(args) >= 2:
            from experiment_manager import check_duplicate
            result = check_duplicate(json.loads(args[1]))
        elif command == "experiment_export_csv":
            from experiment_manager import export_experiments_csv
            result = export_experiments_csv(args[1] if len(args) >= 2 else None)
        elif command == "experiment_export_json":
            from experiment_manager import export_experiments_json
            result = export_experiments_json(args[1] if len(args) >= 2 else None)

        # ── Phase 12 — Advanced Institutional Intelligence Layer ──────────────
        elif command == "phase12_analysis":
            from phase12_intelligence import run_phase12_analysis
            from paper_trader import _load_state as _p12_load_state
            _p12_state = _p12_load_state()
            _p12_cash = _p12_state.get("cash", 5000.0)
            _p12_syms = args[1].split(",") if len(args) > 1 and args[1] else None
            _p12_force = len(args) > 2 and args[2] == "force"
            result = {"success": True,
                      **run_phase12_analysis(symbols=_p12_syms, force=_p12_force,
                                             available_cash=_p12_cash)}
        elif command == "phase12_regime":
            from phase12_intelligence import detect_market_regime
            import os as _os
            import json as _json
            _mc_path = _os.path.join(_os.path.dirname(__file__), "market_context_cache.json")
            try:
                with open(_mc_path) as _f:
                    _mc = _json.load(_f)
            except Exception:
                _mc = {}
            result = {"success": True, **detect_market_regime(_mc)}
        elif command == "phase12_sector_rotation":
            from phase12_intelligence import run_phase12_analysis
            from paper_trader import _load_state as _p12_sr_state
            _p12_sr_cash = _p12_sr_state().get("cash", 5000.0)
            _p12_data = run_phase12_analysis(available_cash=_p12_sr_cash)
            result = {"success": True,
                      "sector_rotation": _p12_data.get("sector_rotation", []),
                      "regime": _p12_data.get("regime"),
                      "generated_at": _p12_data.get("generated_at"),
                      "label": "PAPER / RESEARCH ONLY"}
        elif command == "phase12_bundle":
            from phase12_diagnostics import build_phase12_bundle
            result = {"success": True, "bundle": build_phase12_bundle()}

        # ── Phase 13 — Institutional AI & Strategy Evolution ──────────────────
        elif command == "phase13_analysis":
            from phase13_intelligence import run_phase13_analysis
            from paper_trader import _load_state as _p13_state
            _p13_cash = _p13_state().get("cash", 5000.0)
            _p13_syms = args[1].split(",") if len(args) > 1 and args[1] else None
            _p13_force = len(args) > 2 and args[2] == "force"
            result = {"success": True,
                      **run_phase13_analysis(symbols=_p13_syms, force=_p13_force,
                                             available_cash=_p13_cash)}
        elif command == "phase13_regime":
            from phase13_intelligence import detect_market_regime
            import os as _os13; import json as _j13
            _mc13 = _j13.load(open(_os13.path.join(_os13.path.dirname(__file__), "market_context_cache.json"))) if _os13.path.exists(_os13.path.join(_os13.path.dirname(__file__), "market_context_cache.json")) else {}
            result = {"success": True, **detect_market_regime(_mc13)}
        elif command == "phase13_sector_rotation":
            from phase13_intelligence import run_phase13_analysis
            from paper_trader import _load_state as _p13_sr
            _d = run_phase13_analysis(available_cash=_p13_sr().get("cash", 5000.0))
            result = {"success": True, "sector_rotation": _d.get("sector_rotation", []),
                      "regime": _d.get("regime"), "generated_at": _d.get("generated_at"),
                      "label": "PAPER / RESEARCH ONLY"}
        elif command == "phase13_bundle":
            from phase13_diagnostics import build_phase13_bundle
            result = {"success": True, "bundle": build_phase13_bundle()}
        elif command == "phase13_evolution":
            from phase13_strategy_evolution import generate_evolution_proposals
            _p13_force_ev = len(args) > 1 and args[1] == "force"
            result = generate_evolution_proposals(force=_p13_force_ev)
        elif command == "phase13_evolution_list":
            from phase13_strategy_evolution import list_proposals
            _ev_status = args[1] if len(args) > 1 else None
            result = list_proposals(status=_ev_status)
        elif command == "phase13_evolution_review" and len(args) >= 3:
            from phase13_strategy_evolution import review_proposal
            _notes = args[3] if len(args) > 3 else ""
            result = review_proposal(args[1], args[2], _notes)
        elif command == "phase13_audit":
            from phase13_audit import build_audit_report
            result = {"success": True, "report": build_audit_report()}
        elif command == "phase14_dataset":
            from phase14_learning import build_learning_dataset
            _ds = build_learning_dataset(force=True)
            result = {"success": True, **{k: v for k, v in _ds.items() if k != "rows"},
                      "rows": _ds["rows"][:200]}
        elif command == "phase14_evaluation":
            from phase14_learning import run_evaluation
            result = {"success": True, "report": run_evaluation(force=True)}
        elif command == "phase14_adjustments":
            from phase14_adjustments import compute_adjustments
            result = {"success": True, **compute_adjustments(force=True)}
        elif command == "phase14_calibration_train":
            from phase14_calibration import train_calibrator
            result = {"success": True, "calibrator": train_calibrator(force=True)}
        elif command == "phase14_calibration_status":
            from phase14_calibration import calibration_status
            result = {"success": True, **calibration_status()}
        elif command == "phase14_registry":
            from phase14_governance import list_models
            result = {"success": True, **list_models()}
        elif command == "phase14_challenger_create":
            from phase14_governance import create_challenger
            _desc = args[1] if len(args) > 1 else ""
            result = {"success": True, "model": create_challenger(_desc)}
        elif command == "phase14_promotion_checklist" and len(args) >= 2:
            from phase14_governance import promotion_checklist
            result = {"success": True, **promotion_checklist(args[1])}
        elif command == "phase14_model_review" and len(args) >= 3:
            from phase14_governance import review_model
            _approver = args[3] if len(args) > 3 else "human"
            result = review_model(args[1], args[2], _approver)
        elif command == "phase14_rollback":
            from phase14_governance import rollback_champion
            result = rollback_champion()
        elif command == "phase14_drift":
            from phase14_governance import compute_drift
            result = {"success": True, **compute_drift()}
        elif command == "phase14_alerts":
            from phase14_governance import get_alerts
            result = {"success": True, "alerts": get_alerts()}
        elif command == "phase14_audit_log":
            from phase14_governance import get_audit_log
            result = {"success": True, "log": get_audit_log()}
        elif command == "phase14_verification":
            from phase14_diagnostics import verification_report
            result = {"success": True, "verification": verification_report()}
        elif command == "phase14_bundle":
            from phase14_diagnostics import build_bundle
            result = build_bundle()
        elif command == "phase14_export" and len(args) >= 2:
            from phase14_diagnostics import export_artifact
            result = {"success": True, "artifact": args[1], **export_artifact(args[1])}
        elif command == "phase14_qa" and len(args) >= 2:
            from phase14_copilot import answer_question
            result = {"success": True, **answer_question(args[1])}
        elif command == "phase14_decision_batch" and len(args) >= 2:
            from phase14_calibration import calibrate_confidence
            from phase14_adjustments import adaptive_adjustment_for
            from phase14_governance import list_models
            import json as _json
            _items = _json.loads(args[1])
            _champ = list_models().get("champion_version")
            _out = []
            for _ctx in _items[:60]:
                _raw = float(_ctx.get("raw_confidence") or 0)
                _cal = calibrate_confidence(_raw)
                _adj = adaptive_adjustment_for(
                    strategy=_ctx.get("strategy"), regime=_ctx.get("regime"),
                    sector=_ctx.get("sector"), raw_confidence=_raw,
                    opportunity_score=_ctx.get("opportunity_score"),
                    holding_days=_ctx.get("holding_days"),
                    trade_quality=_ctx.get("trade_quality"),
                    recommendation=_ctx.get("recommendation"))
                _out.append({
                    "symbol": _ctx.get("symbol"),
                    "raw_confidence": _raw,
                    "calibrated_probability": _cal["calibrated_probability"],
                    "calibrator_version": _cal["calibrator_version"],
                    "adaptive_adjustment": _adj["adjustment"],
                    "final_confidence": round(max(0.0, min(100.0, _raw + _adj["adjustment"])), 1),
                    "explanation": _adj["explanation"],
                    "model_version": _champ})
            result = {"success": True, "items": _out}
        elif command == "phase14_decision_context" and len(args) >= 2:
            from phase14_calibration import calibrate_confidence
            from phase14_adjustments import adaptive_adjustment_for
            from phase14_governance import list_models
            import json as _json
            _ctx = _json.loads(args[1])
            _raw = float(_ctx.get("raw_confidence") or 0)
            _cal = calibrate_confidence(_raw)
            _adj = adaptive_adjustment_for(
                strategy=_ctx.get("strategy"), regime=_ctx.get("regime"),
                sector=_ctx.get("sector"), raw_confidence=_raw,
                opportunity_score=_ctx.get("opportunity_score"),
                holding_days=_ctx.get("holding_days"),
                trade_quality=_ctx.get("trade_quality"),
                recommendation=_ctx.get("recommendation"))
            _final = max(0.0, min(100.0, _raw + _adj["adjustment"]))
            result = {"success": True, "raw_confidence": _raw,
                      "calibrated_probability": _cal["calibrated_probability"],
                      "calibrator_version": _cal["calibrator_version"],
                      "adaptive_adjustment": _adj["adjustment"],
                      "final_confidence": round(_final, 1),
                      "explanation": _adj["explanation"],
                      "contributions": _adj["contributions"],
                      "learning_frozen": _adj["learning_frozen"],
                      "model_version": list_models().get("champion_version")}
        # ── Phase 15 — Production Hardening & Stabilization ────────────────
        elif command == "phase15_context":
            from phase15_scan_context import build_scan_context
            result = {"success": True, **build_scan_context()}
        elif command == "phase15_symbol" and len(args) >= 2:
            from phase15_scan_context import symbol_context
            result = {"success": True, **symbol_context(args[1])}
        elif command == "phase15_quality":
            from phase15_quality import quality_report
            result = {"success": True, **quality_report()}
        elif command == "phase15_staleness":
            from phase15_quality import staleness_report
            result = {"success": True, **staleness_report()}
        elif command == "phase15_consistency":
            from phase15_consistency import run_consistency_check
            result = {"success": True, **run_consistency_check()}
        elif command == "phase15_explain" and len(args) >= 2:
            from phase15_explain import explain_symbol
            result = {"success": True, **explain_symbol(args[1])}
        elif command == "phase15_explain_all":
            from phase15_explain import explain_all
            result = {"success": True, **explain_all()}
        elif command == "phase15_risk_gate" and len(args) >= 2:
            from phase15_risk_gate import risk_gate
            result = {"success": True, **risk_gate(args[1])}
        elif command == "phase15_audit_record":
            from phase15_audit import record_scan_audit
            result = record_scan_audit()
        elif command == "phase15_audit_list":
            from phase15_audit import list_scan_audits
            result = list_scan_audits(int(args[1]) if len(args) > 1 else 20)
        elif command == "phase15_diagnostics":
            from phase15_diagnostics import system_diagnostics
            result = system_diagnostics()
        elif command == "phase15_readiness":
            from phase15_diagnostics import readiness_report
            result = readiness_report()
        elif command == "phase16_overview":
            from phase16_validation import validation_overview
            result = validation_overview()
        elif command == "phase16_scorecard":
            from phase16_validation import strategy_scorecard
            result = strategy_scorecard()
        elif command == "phase16_confidence":
            from phase16_validation import confidence_validation
            result = confidence_validation()
        elif command == "phase16_regimes":
            from phase16_validation import regime_validation
            result = regime_validation()
        elif command == "phase16_sectors":
            from phase16_validation import sector_validation
            result = sector_validation()
        elif command == "phase16_ai":
            from phase16_validation import ai_decision_validation
            result = ai_decision_validation()
        elif command == "phase16_trades":
            from phase16_validation import trade_review
            result = trade_review()
        elif command == "phase16_weekly":
            from phase16_validation import weekly_report
            result = {"success": True, **weekly_report()}
        elif command == "phase16_monthly":
            from phase16_validation import monthly_report
            result = {"success": True, **monthly_report()}
        elif command == "phase16_recommendations":
            from phase16_validation import improvement_recommendations
            result = improvement_recommendations()
        elif command == "phase16_failures":
            from phase16_validation import failure_analysis
            result = failure_analysis()
        elif command == "phase16_successes":
            from phase16_validation import success_analysis
            result = success_analysis()
        elif command == "phase16_timeline":
            from phase16_validation import validation_timeline
            result = validation_timeline()
        elif command == "phase16_bugs":
            from phase16_validation import bug_detection
            result = bug_detection()
        elif command == "phase16_all":
            from phase16_validation import run_all
            result = run_all()
        elif command == "phase16_export":
            from phase16_exports import build_exports
            result = build_exports()

        # ── Phase 21: Strategy Calibration & Signal Quality ──────────────
        elif command == "phase21_baseline_freeze":
            from phase21_baseline import freeze_baseline
            result = freeze_baseline()
        elif command == "phase21_baseline":
            from phase21_baseline import load_baseline, verify_baseline_integrity
            result = {"baseline": load_baseline(),
                      "integrity": verify_baseline_integrity()}
        elif command == "phase21_baseline_report":
            from phase21_baseline import baseline_report
            result = baseline_report(force=len(args) > 1 and args[1] == "force")
        elif command == "phase21_calibration":
            from phase21_calibration import run_calibration
            result = run_calibration(force=len(args) > 1 and args[1] == "force")
        elif command == "phase21_thresholds":
            from phase21_thresholds import run_threshold_optimization
            result = run_threshold_optimization(force=len(args) > 1 and args[1] == "force")
        elif command == "phase21_regime_matrix":
            from phase21_regime import run_regime_matrix
            result = run_regime_matrix(force=len(args) > 1 and args[1] == "force")
        elif command == "phase21_stoptarget":
            from phase21_stoptarget import run_stoptarget_analysis
            result = run_stoptarget_analysis(force=len(args) > 1 and args[1] == "force")
        elif command == "phase21_ranking":
            from phase21_ranking import run_ranking
            result = run_ranking()
        elif command == "phase21_explain":
            from phase21_explain import explain_trade
            result = explain_trade(args[1]) if len(args) > 1 else {"error": "symbol required"}
        elif command == "phase21_explain_all":
            from phase21_explain import explain_all
            result = explain_all()
        elif command == "phase21_challengers_build":
            from phase21_challenger import build_challengers
            result = build_challengers(force=True)
        elif command == "phase21_registry":
            from phase21_challenger import get_registry
            result = get_registry()
        elif command == "phase21_promotion_checklist":
            from phase21_challenger import promotion_checklist
            result = promotion_checklist(args[1]) if len(args) > 1 else {"error": "challenger_id required"}
        elif command == "phase21_review_challenger":
            from phase21_challenger import review_challenger
            result = (review_challenger(args[1], args[2],
                                        args[3] if len(args) > 3 else "human")
                      if len(args) > 2 else {"error": "challenger_id and action required"})
        elif command == "phase21_scorecard":
            from phase21_scorecard import build_scorecard
            result = build_scorecard()
        elif command == "phase21_export":
            from phase21_exports import build_phase21_exports
            result = build_phase21_exports()

        # ── Phase 22: Controlled Auto Paper Trading & Evidence ────────────
        elif command == "phase22_readiness":
            from phase22_readiness import run_readiness_checklist
            result = run_readiness_checklist()
        elif command == "phase22_activation_status":
            from phase22_activation import get_activation_status
            result = get_activation_status()
        elif command == "phase22_enable":
            from phase22_activation import enable_paper_automation
            payload = json.loads(sys.argv[2]) if len(sys.argv) > 2 else {}
            result = enable_paper_automation(
                str(payload.get("confirmation_text") or ""),
                user=payload.get("user"))
        elif command == "phase22_disable":
            from phase22_activation import disable_paper_automation
            payload = json.loads(sys.argv[2]) if len(sys.argv) > 2 else {}
            result = disable_paper_automation(user=payload.get("user"))
        elif command == "phase22_evidence":
            from phase22_evidence import list_evidence, evidence_summary
            limit = int(sys.argv[2]) if len(sys.argv) > 2 else 100
            result = {"summary": evidence_summary(),
                      "rows": list_evidence(limit=limit),
                      "label": "PAPER / RESEARCH ONLY"}
        elif command == "phase22_bundle":
            from scan_pipeline import bundle_status
            result = bundle_status()
        elif command == "phase22_run_pipeline":
            from live_scan_engine import load_cached_scan
            from scan_pipeline import run_post_scan_pipeline
            snap = load_cached_scan() or {}
            result = run_post_scan_pipeline(snap, trigger="MANUAL")
        elif command == "phase22_evidence_update":
            from phase22_evidence import update_outcomes
            result = update_outcomes()
        elif command == "phase22_progress":
            from phase22_progress import get_progress
            result = get_progress()
        elif command == "phase22_daily_report":
            from phase22_report import build_daily_report
            day = sys.argv[2] if len(sys.argv) > 2 else None
            result = build_daily_report(day)
        elif command == "phase22_export":
            from phase22_report import export_daily_report
            day = sys.argv[2] if len(sys.argv) > 2 else None
            result = export_daily_report(day)

        # ── Phase 17: Automated QA & Release Validation ──────────────────
        elif command == "phase17_build_info":
            from phase17_qa import build_info
            result = build_info()
        elif command == "phase17_dashboard":
            from phase17_qa import release_dashboard
            result = release_dashboard()
        elif command == "phase17_history":
            from phase17_qa import validation_history
            result = validation_history()
        elif command == "phase17_last":
            from phase17_qa import last_run
            result = last_run()
        elif command == "phase17_run":
            from phase17_qa import run_complete_validation
            notes = sys.argv[2] if len(sys.argv) > 2 else ""
            result = run_complete_validation(notes)
        elif command == "phase17_reports":
            from phase17_reports import build_reports
            result = build_reports()

        # ── Phase 18: Research Notebook & Evidence Accumulation ──────────
        elif command == "phase18_ensure":
            from phase18_notebook import ensure_today_entry
            result = ensure_today_entry()
        elif command == "phase18_entry":
            from phase18_notebook import get_entry
            result = get_entry(sys.argv[2] if len(sys.argv) > 2 else None)
        elif command == "phase18_list":
            from phase18_notebook import list_entries
            result = list_entries()
        elif command == "phase18_notes":
            from phase18_notebook import save_notes
            payload = json.loads(sys.argv[2])
            result = save_notes(**payload)
        elif command == "phase18_decision":
            from phase18_notebook import record_user_decision
            payload = json.loads(sys.argv[2])
            result = record_user_decision(**payload)
        elif command == "phase18_finalize":
            from phase18_notebook import finalize_day
            result = finalize_day(sys.argv[2] if len(sys.argv) > 2 else None)
        elif command == "phase18_reopen":
            from phase18_notebook import reopen_day
            result = reopen_day(sys.argv[2])
        elif command == "phase18_search":
            from phase18_notebook import search
            payload = json.loads(sys.argv[2]) if len(sys.argv) > 2 else {}
            result = search(**payload)
        elif command == "phase18_issue_add":
            from phase18_notebook import add_issue
            result = add_issue(**json.loads(sys.argv[2]))
        elif command == "phase18_issue_update":
            from phase18_notebook import update_issue
            result = update_issue(**json.loads(sys.argv[2]))
        elif command == "phase18_issues":
            from phase18_notebook import list_issues
            payload = json.loads(sys.argv[2]) if len(sys.argv) > 2 else {}
            result = list_issues(**payload)
        elif command == "phase18_targets":
            from phase18_notebook import get_targets
            result = {"success": True, "targets": get_targets()}
        elif command == "phase18_targets_update":
            from phase18_notebook import update_targets
            result = update_targets(json.loads(sys.argv[2]))
        elif command == "phase18_daily_review":
            from phase18_reviews import daily_review
            result = daily_review(sys.argv[2] if len(sys.argv) > 2 else None)
        elif command == "phase18_weekly_review":
            from phase18_reviews import weekly_review
            result = weekly_review(sys.argv[2] if len(sys.argv) > 2 else None)
        elif command == "phase18_monthly_review":
            from phase18_reviews import monthly_review
            result = monthly_review(sys.argv[2] if len(sys.argv) > 2 else None)
        elif command == "phase18_evidence":
            from phase18_reviews import evidence_tracker
            result = evidence_tracker()
        elif command == "phase18_export_daily":
            from phase18_exports import export_daily
            result = export_daily(sys.argv[2] if len(sys.argv) > 2 else None)
        elif command == "phase18_export_all":
            from phase18_exports import export_all
            result = export_all()
        elif command == "phase18_archive":
            from phase18_exports import build_archive
            result = build_archive()

        # ── Phase 19: Zerodha Kite Connect live-data integration ─────────────
        elif command == "kite_status":
            from kite_session_manager import get_status
            force = "--force" in sys.argv
            result = get_status(force_probe=force)
        elif command == "kite_exchange":
            from kite_session_manager import exchange_request_token
            # request_token is passed via env (never argv) so it can't leak
            # through process listings or shell history.
            result = exchange_request_token(os.environ.get("KITE_REQUEST_TOKEN"))
        elif command == "kite_disconnect":
            from kite_session_manager import disconnect_session
            result = disconnect_session()
        elif command == "kite_invalidate":
            from kite_session_manager import invalidate_cache
            from kite_quote_provider import invalidate_cache as inv_q
            invalidate_cache()
            inv_q()
            result = {"success": True, "message": "Kite probe and quote caches cleared"}
        elif command == "kite_quote":
            from kite_quote_provider import get_quotes, provider_label
            symbols = [s.strip() for s in (sys.argv[2] if len(sys.argv) > 2 else "").split(",") if s.strip()]
            if not symbols:
                result = {"success": False, "error": "No symbols provided"}
            else:
                quotes = get_quotes(symbols)
                result = {"success": True, "quotes": quotes,
                          "count": len(quotes), "provider": provider_label()}
        elif command == "kite_ltp":
            from kite_quote_provider import get_ltp, provider_label
            symbols = [s.strip() for s in (sys.argv[2] if len(sys.argv) > 2 else "").split(",") if s.strip()]
            ltp = get_ltp(symbols)
            result = {"success": True, "ltp": ltp, "provider": provider_label()}
        elif command == "kite_holdings":
            from broker_client import get_broker_client
            from dataclasses import asdict
            client = get_broker_client()
            holdings = client.get_holdings()
            result = {"success": True, "holdings": [asdict(h) for h in holdings],
                      "count": len(holdings), "is_mock": client.is_mock,
                      "note": "Read-only. Paper trading mode active."}
        elif command == "kite_positions":
            from broker_client import get_broker_client
            from dataclasses import asdict
            client = get_broker_client()
            positions = client.get_positions()
            result = {"success": True, "positions": [asdict(p) for p in positions],
                      "count": len(positions), "is_mock": client.is_mock,
                      "note": "Read-only. Paper trading mode active."}
        elif command == "kite_margins":
            from broker_client import get_broker_client
            from dataclasses import asdict
            client = get_broker_client()
            margins = client.get_margins()
            result = {"success": True, "margins": asdict(margins),
                      "is_mock": client.is_mock,
                      "note": "Read-only. Paper trading mode active."}
        elif command == "kite_orders":
            from broker_client import get_broker_client
            from dataclasses import asdict
            limit = int(sys.argv[2]) if len(sys.argv) > 2 else 50
            client = get_broker_client()
            orders = client.get_orders(limit=limit)
            result = {"success": True, "orders": [asdict(o) for o in orders],
                      "count": len(orders), "is_mock": client.is_mock,
                      "note": "Read-only sync. Paper trading mode active. No real orders placed here."}
        elif command == "kite_instrument_search":
            from kite_instrument_cache import search, cache_status
            q = sys.argv[2] if len(sys.argv) > 2 else ""
            limit = int(sys.argv[3]) if len(sys.argv) > 3 else 20
            hits = search(q, limit=limit)
            cs = cache_status()
            result = {"success": True, "results": hits, "count": len(hits),
                      "query": q, "cache_date": cs.get("date"),
                      "cache_count": cs.get("count")}
        elif command == "kite_instrument_refresh":
            from kite_instrument_cache import refresh
            force = "--force" in sys.argv
            result = refresh(force=force)
        elif command == "kite_instrument_cache_status":
            from kite_instrument_cache import cache_status
            result = {"success": True, **cache_status()}
        elif command == "kite_diagnostics":
            from kite_session_manager import get_status
            from kite_quote_provider import kite_available, provider_label
            from kite_instrument_cache import cache_status
            from broker_client import get_broker_client, creds_present
            from dataclasses import asdict
            sess = get_status()
            client = get_broker_client()
            conn = client.test_connection()
            result = {
                "success": True,
                "session": sess,
                "connection": asdict(conn),
                "kite_available": kite_available(),
                "provider_label": provider_label(),
                "instrument_cache": cache_status(),
                "paper_trading_active": True,
                "live_order_placement_enabled": False,
                "note": "Phase 19: Read-only live data integration. Paper trading remains default.",
            }

        # ── EOD Reconciliation ─────────────────────────────────────────────
        elif command == "reconcil_status":
            from eod_reconciliation import get_reconciliation_status
            result = get_reconciliation_status()
        elif command == "reconcil_trigger":
            from eod_reconciliation import run_eod_reconciliation
            force = "--force" in args
            result = run_eod_reconciliation(trigger="manual", force=force)
        elif command == "reconcil_resolve" and len(args) > 1:
            from eod_reconciliation import resolve_discrepancy
            note_arg = args[2] if len(args) > 2 else None
            result = resolve_discrepancy(int(args[1]), note=note_arg)
        elif command == "reconcil_reopen" and len(args) > 1:
            from eod_reconciliation import reopen_discrepancy
            result = reopen_discrepancy(int(args[1]))
        elif command == "reconcil_probe":
            from eod_reconciliation import check_reconciliation_probe
            result = check_reconciliation_probe()

        elif command == "portfolio_snapshot":
            from portfolio_snapshot import get_portfolio_snapshot
            result = get_portfolio_snapshot()
        elif command == "portfolio_health":
            from portfolio_snapshot import get_portfolio_health
            result = get_portfolio_health()
        elif command == "portfolio_config":
            from portfolio_snapshot import get_portfolio_config
            result = get_portfolio_config()

        elif command == "preopen_intelligence_tick":
            from preopen_intelligence_tick import run_tick as _pi_tick
            result = _pi_tick()

        elif command == "preopen_intelligence_tick_status":
            from preopen_intelligence_tick import get_tick_status as _pi_ts
            result = _pi_ts()

        elif command == "preopen_status":
            from preopen_engine import get_status
            result = get_status()

        elif command == "preopen_health":
            from preopen_engine import get_health
            result = get_health()

        elif command == "preopen_snapshot":
            from preopen_engine import get_snapshot
            result = get_snapshot()

        elif command == "preopen_symbol" and len(args) > 1:
            from preopen_engine import get_symbol_snapshot
            result = get_symbol_snapshot(args[1])

        elif command == "preopen_rankings":
            from preopen_engine import get_rankings
            result = get_rankings()

        elif command == "preopen_watchlist":
            from preopen_engine import get_watchlists
            result = get_watchlists()

        elif command == "preopen_sectors":
            from preopen_engine import get_sectors
            result = get_sectors()

        elif command == "preopen_report":
            from preopen_engine import get_report
            result = get_report()

        elif command == "preopen_refresh":
            from preopen_engine import refresh
            result = refresh()

        elif command == "preopen_signal_hints":
            from preopen_engine import get_signal_hints
            result = get_signal_hints()

        elif command == "preopen_accuracy":
            from preopen_accuracy import get_accuracy
            date_arg = args[1] if len(args) > 1 else None
            result = get_accuracy(date_arg)

        elif command == "preopen_accuracy_history":
            from preopen_accuracy import get_accuracy_history
            result = get_accuracy_history()

        elif command == "preopen_validation_tick":
            from preopen_validation_tick import run_tick
            result = run_tick()

        elif command == "preopen_validation_tick_status":
            from preopen_validation_tick import get_tick_status
            result = get_tick_status()

        # ── Phase 5C: Signal Validation ──────────────────────────────────────

        elif command == "signal_validation_tick":
            from signal_validation_tick import run_tick as _sv_tick
            result = _sv_tick()

        elif command == "signal_validation_tick_status":
            from signal_validation_tick import get_tick_status as _sv_ts
            result = _sv_ts()

        elif command == "signal_validation_status":
            from signal_validation_engine import get_status as _sv_status
            result = _sv_status()

        elif command == "signal_validation_summary":
            from signal_validation_engine import get_summary as _sv_summary
            date = args[1] if len(args) > 1 else None
            result = _sv_summary(date)

        elif command == "signal_validation_signals":
            from signal_validation_engine import get_signals as _sv_signals
            date   = args[1] if len(args) > 1 else None
            limit  = int(args[2]) if len(args) > 2 else 100
            offset = int(args[3]) if len(args) > 3 else 0
            result = _sv_signals(trading_date=date, limit=limit, offset=offset)

        elif command == "signal_validation_detail" and len(args) > 1:
            from signal_validation_engine import get_signal_detail as _sv_detail
            signal_id = args[1]
            date = args[2] if len(args) > 2 else None
            result = _sv_detail(signal_id, date)

        elif command == "signal_validation_funnel":
            from signal_validation_engine import get_funnel as _sv_funnel
            date = args[1] if len(args) > 1 else None
            result = _sv_funnel(date)

        elif command == "signal_validation_strategies":
            from signal_validation_engine import get_strategies as _sv_strat
            date = args[1] if len(args) > 1 else None
            result = _sv_strat(date)

        elif command == "signal_validation_ai":
            from signal_validation_engine import get_ai_attribution as _sv_ai
            date = args[1] if len(args) > 1 else None
            result = _sv_ai(date)

        elif command == "signal_validation_preopen":
            from signal_validation_engine import get_preopen_attribution as _sv_po
            date = args[1] if len(args) > 1 else None
            result = _sv_po(date)

        elif command == "signal_validation_risk":
            from signal_validation_engine import get_risk_attribution as _sv_risk
            date = args[1] if len(args) > 1 else None
            result = _sv_risk(date)

        elif command == "signal_validation_regimes":
            from signal_validation_engine import get_regimes as _sv_reg
            date = args[1] if len(args) > 1 else None
            result = _sv_reg(date)

        elif command == "signal_validation_missed":
            from signal_validation_engine import get_missed_opportunities as _sv_mo
            date  = args[1] if len(args) > 1 else None
            limit = int(args[2]) if len(args) > 2 else 50
            result = _sv_mo(date, limit)

        elif command == "signal_validation_report":
            from signal_validation_engine import get_report as _sv_report
            date = args[1] if len(args) > 1 else None
            result = _sv_report(date)

        elif command == "signal_validation_run_now":
            from signal_validation_engine import run_now as _sv_run
            date = args[1] if len(args) > 1 else None
            result = _sv_run(date)

        elif command == "signal_validation_reconcile":
            from signal_validation_engine import reconcile_now as _sv_rec
            date = args[1] if len(args) > 1 else None
            result = _sv_rec(date)

        # ── Phase 5D.1: Execution Quality ─────────────────────────────────────
        elif command == "execution_quality_summary":
            from execution_quality.api import get_summary as _eq_summary
            date   = args[1] if len(args) > 1 else None
            result = _eq_summary(date)

        elif command == "execution_quality_trades":
            from execution_quality.api import get_trades as _eq_trades
            limit  = int(args[1]) if len(args) > 1 else 200
            offset = int(args[2]) if len(args) > 2 else 0
            date   = args[3] if len(args) > 3 else None
            result = _eq_trades(date, limit, offset)

        elif command == "execution_quality_slippage":
            from execution_quality.api import get_slippage as _eq_slippage
            date   = args[1] if len(args) > 1 else None
            result = _eq_slippage(date)

        elif command == "execution_quality_fills":
            from execution_quality.api import get_fills as _eq_fills
            date   = args[1] if len(args) > 1 else None
            result = _eq_fills(date)

        # ── Phase 5D.4: AI Performance Intelligence ──────────────────────────────
        elif command == "ai_summary":
            from ai_performance.api import get_summary as _ai_summary
            result = _ai_summary()

        elif command == "ai_confidence":
            from ai_performance.api import get_confidence as _ai_confidence
            result = _ai_confidence()

        elif command == "ai_calibration":
            from ai_performance.api import get_calibration as _ai_calibration
            result = _ai_calibration()

        elif command == "ai_predictions":
            from ai_performance.api import get_predictions as _ai_predictions
            result = _ai_predictions()

        elif command == "ai_recommendations":
            from ai_performance.api import get_recommendations as _ai_recommendations
            result = _ai_recommendations()

        elif command == "ai_learning":
            from ai_performance.api import get_learning as _ai_learning
            result = _ai_learning()

        # ── Phase 5D.5: Executive Dashboard ──────────────────────────────────────
        elif command == "executive_summary":
            from executive_dashboard.api import get_summary as _exec_summary
            result = _exec_summary()
        elif command == "executive_health":
            from executive_dashboard.api import get_health as _exec_health
            result = _exec_health()
        elif command == "executive_widgets":
            from executive_dashboard.api import get_widgets as _exec_widgets
            result = _exec_widgets()

        # ── Phase 5D.3: Strategy Intelligence ────────────────────────────────────
        elif command == "strategy_summary":
            from strategy_intelligence.api import get_summary as _si_summary
            result = _si_summary()

        elif command == "strategy_rankings":
            from strategy_intelligence.api import get_rankings as _si_rankings
            result = _si_rankings()

        elif command == "strategy_regimes":
            from strategy_intelligence.api import get_regimes as _si_regimes
            result = _si_regimes()

        elif command == "strategy_sectors":
            from strategy_intelligence.api import get_sectors as _si_sectors
            result = _si_sectors()

        elif command == "strategy_timing":
            from strategy_intelligence.api import get_timing as _si_timing
            result = _si_timing()

        elif command == "strategy_recommendations":
            from strategy_intelligence.api import get_recommendations_api as _si_recs
            result = _si_recs()

        # ── Phase 5D.2: Portfolio Performance Intelligence ─────────────────────
        elif command == "performance_summary":
            from portfolio_performance.api import get_summary as _pp_summary
            result = _pp_summary()

        elif command == "performance_equity":
            from portfolio_performance.api import get_equity as _pp_equity
            period = args[1] if len(args) > 1 else "daily"
            result = _pp_equity(period)

        elif command == "performance_drawdown":
            from portfolio_performance.api import get_drawdown as _pp_drawdown
            result = _pp_drawdown()

        elif command == "performance_statistics":
            from portfolio_performance.api import get_statistics as _pp_statistics
            result = _pp_statistics()

        elif command == "performance_portfolio":
            from portfolio_performance.api import get_portfolio as _pp_portfolio
            result = _pp_portfolio()

        elif command == "preopen_validation_status":
            from preopen_validation_engine import get_status
            result = get_status()

        elif command == "preopen_validation_daily":
            from preopen_validation_engine import get_daily
            date = args[1] if len(args) > 1 else None
            result = get_daily(date)

        elif command == "preopen_validation_candidates":
            from preopen_validation_engine import get_candidates
            date  = args[1] if len(args) > 1 else None
            limit = int(args[2]) if len(args) > 2 else 200
            result = get_candidates(date, limit)

        elif command == "preopen_validation_symbol" and len(args) > 1:
            from preopen_validation_engine import get_symbol
            symbol = args[1]
            date   = args[2] if len(args) > 2 else None
            result = get_symbol(symbol, date)

        elif command == "preopen_validation_score_bands":
            from preopen_validation_engine import get_score_bands
            date = args[1] if len(args) > 1 else None
            result = get_score_bands(date)

        elif command == "preopen_validation_factors":
            from preopen_validation_engine import get_factors
            date = args[1] if len(args) > 1 else None
            result = get_factors(date)

        elif command == "preopen_validation_sectors":
            from preopen_validation_engine import get_sectors
            date = args[1] if len(args) > 1 else None
            result = get_sectors(date)

        elif command == "preopen_validation_report":
            from preopen_validation_engine import get_report
            date = args[1] if len(args) > 1 else None
            result = get_report(date)

        elif command == "preopen_validation_run":
            from preopen_validation_engine import run_validation
            result = run_validation()

        elif command == "validation_session":
            from paper_trading_validation.api import cmd_session as _val_session
            result = _val_session()

        elif command == "validation_history":
            from paper_trading_validation.api import cmd_history as _val_history
            result = _val_history()

        elif command == "validation_quality":
            from paper_trading_validation.api import cmd_quality as _val_quality
            result = _val_quality()

        elif command == "validation_statistics":
            from paper_trading_validation.api import cmd_statistics as _val_statistics
            result = _val_statistics()

        elif command == "validation_export_csv":
            from paper_trading_validation.shared_services import export_records_csv as _val_csv
            result = {"csv": _val_csv()}

        elif command == "validation_export_json":
            from paper_trading_validation.shared_services import export_records_json as _val_json
            result = {"json": _val_json()}

        elif command == "optimisation_summary":
            from strategy_optimisation.api import cmd_summary as _opt_summary
            result = _opt_summary()

        elif command == "optimisation_strategies":
            from strategy_optimisation.api import cmd_strategies as _opt_strategies
            result = _opt_strategies()

        elif command == "optimisation_recommendations":
            from strategy_optimisation.api import cmd_recommendations as _opt_recs
            result = _opt_recs()

        elif command == "optimisation_patterns":
            from strategy_optimisation.api import cmd_patterns as _opt_patterns
            result = _opt_patterns()

        elif command == "optimisation_export_csv":
            from strategy_optimisation.shared_services import export_strategies_csv as _opt_csv
            result = {"csv": _opt_csv()}

        elif command == "optimisation_export_json":
            from strategy_optimisation.shared_services import export_recommendations_json as _opt_json
            result = {"json": _opt_json()}

        elif command == "ai_optimisation_summary":
            from ai_optimisation.api import cmd_summary as _aio_summary
            result = _aio_summary()

        elif command == "ai_optimisation_calibration":
            from ai_optimisation.api import cmd_calibration as _aio_cal
            result = _aio_cal()

        elif command == "ai_optimisation_drift":
            from ai_optimisation.api import cmd_drift as _aio_drift
            result = _aio_drift()

        elif command == "ai_optimisation_recommendations":
            from ai_optimisation.api import cmd_recommendations as _aio_recs
            result = _aio_recs()

        elif command == "ai_optimisation_history":
            from ai_optimisation.api import cmd_history as _aio_hist
            result = _aio_hist()

        elif command == "ai_optimisation_export_csv":
            from ai_optimisation.shared_services import export_summary_csv as _aio_csv
            result = {"csv": _aio_csv()}

        elif command == "ai_optimisation_export_json":
            from ai_optimisation.shared_services import export_full_json as _aio_json
            result = {"json": _aio_json()}

        elif command == "risk_optimisation_summary":
            from risk_optimisation.api import cmd_summary as _ro_summary
            result = _ro_summary()

        elif command == "risk_optimisation_capital":
            from risk_optimisation.api import cmd_capital as _ro_capital
            result = _ro_capital()

        elif command == "risk_optimisation_drawdown":
            from risk_optimisation.api import cmd_drawdown as _ro_drawdown
            result = _ro_drawdown()

        elif command == "risk_optimisation_stress":
            from risk_optimisation.api import cmd_stress as _ro_stress
            result = _ro_stress()

        elif command == "risk_optimisation_recommendations":
            from risk_optimisation.api import cmd_recommendations as _ro_recs
            result = _ro_recs()

        elif command == "risk_optimisation_export_csv":
            from risk_optimisation.shared_services import export_summary_csv as _ro_csv
            result = {"csv": _ro_csv()}

        elif command == "risk_optimisation_export_json":
            from risk_optimisation.shared_services import export_full_json as _ro_json
            result = {"json": _ro_json()}

        elif command == "readiness_summary":
            from live_readiness.api import cmd_summary as _rd_summary
            result = _rd_summary()

        elif command == "readiness_system":
            from live_readiness.api import cmd_system as _rd_system
            result = _rd_system()

        elif command == "readiness_data":
            from live_readiness.api import cmd_data as _rd_data
            result = _rd_data()

        elif command == "readiness_recovery":
            from live_readiness.api import cmd_recovery as _rd_recovery
            result = _rd_recovery()

        elif command == "readiness_security":
            from live_readiness.api import cmd_security as _rd_security
            result = _rd_security()

        elif command == "readiness_report":
            from live_readiness.api import cmd_report as _rd_report
            result = _rd_report()

        elif command == "readiness_export_csv":
            from live_readiness.shared_services import export_summary_csv as _rd_csv
            result = {"csv": _rd_csv()}

        elif command == "readiness_export_json":
            from live_readiness.shared_services import export_full_json as _rd_json
            result = {"json": _rd_json()}

        elif command == "market_intelligence_summary":
            from market_intelligence_hub.api import cmd_summary as _mi_summary
            result = _mi_summary()

        elif command == "market_intelligence_sectors":
            from market_intelligence_hub.api import cmd_sectors as _mi_sectors
            result = _mi_sectors()

        elif command == "market_intelligence_watchlist":
            from market_intelligence_hub.api import cmd_watchlist as _mi_watchlist
            result = _mi_watchlist()

        elif command == "market_intelligence_breadth":
            from market_intelligence_hub.api import cmd_breadth as _mi_breadth
            result = _mi_breadth()

        elif command == "market_intelligence_overview":
            from market_intelligence_hub.api import cmd_overview as _mi_overview
            result = _mi_overview()

        elif command == "market_intelligence_export_csv":
            from market_intelligence_hub.shared_services import export_summary_csv as _mi_csv
            result = {"csv": _mi_csv()}

        elif command == "market_intelligence_export_json":
            from market_intelligence_hub.shared_services import export_full_json as _mi_json
            result = {"json": _mi_json()}

        # ── Phase 7.2 — Event & Corporate Intelligence ────────────────────────
        elif command == "event_intelligence_summary":
            from event_intelligence.api import cmd_summary as _ei_summary
            result = _ei_summary()
        elif command == "event_intelligence_corporate":
            from event_intelligence.api import cmd_corporate as _ei_corporate
            result = _ei_corporate()
        elif command == "event_intelligence_regulatory":
            from event_intelligence.api import cmd_regulatory as _ei_regulatory
            result = _ei_regulatory()
        elif command == "event_intelligence_news":
            from event_intelligence.api import cmd_news as _ei_news
            result = _ei_news()
        elif command == "event_intelligence_timeline":
            from event_intelligence.api import cmd_timeline as _ei_timeline
            result = _ei_timeline()
        elif command == "event_intelligence_brief":
            from event_intelligence.api import cmd_brief as _ei_brief
            result = _ei_brief()
        elif command == "event_intelligence_export_csv":
            from event_intelligence.api import cmd_export_csv as _ei_csv
            result = _ei_csv()
        elif command == "event_intelligence_export_json":
            from event_intelligence.api import cmd_export_json as _ei_json
            result = _ei_json()

        # ── Phase 7.3 — Economic & Macro Intelligence ─────────────────────────
        elif command == "macro_intelligence_summary":
            from macro_intelligence.api import cmd_summary as _mac_summary
            result = _mac_summary()
        elif command == "macro_intelligence_calendar":
            from macro_intelligence.api import cmd_calendar as _mac_calendar
            result = _mac_calendar()
        elif command == "macro_intelligence_global":
            from macro_intelligence.api import cmd_global as _mac_global
            result = _mac_global()
        elif command == "macro_intelligence_flows":
            from macro_intelligence.api import cmd_flows as _mac_flows
            result = _mac_flows()
        elif command == "macro_intelligence_commodities":
            from macro_intelligence.api import cmd_commodities as _mac_commodities
            result = _mac_commodities()
        elif command == "macro_intelligence_brief":
            from macro_intelligence.api import cmd_brief as _mac_brief
            result = _mac_brief()
        elif command == "macro_intelligence_export_csv":
            from macro_intelligence.api import cmd_export_csv as _mac_csv
            result = _mac_csv()
        elif command == "macro_intelligence_export_json":
            from macro_intelligence.api import cmd_export_json as _mac_json
            result = _mac_json()

        # ── Phase 7.4 — Explainable AI & Decision Intelligence ────────────────
        elif command == "explainable_ai_summary":
            from explainable_ai.api import cmd_summary as _xai_summary
            result = _xai_summary()
        elif command == "explainable_ai_decision":
            from explainable_ai.api import cmd_decision as _xai_decision
            result = _xai_decision()
        elif command == "explainable_ai_contributions":
            from explainable_ai.api import cmd_contributions as _xai_contributions
            result = _xai_contributions()
        elif command == "explainable_ai_confidence":
            from explainable_ai.api import cmd_confidence as _xai_confidence
            result = _xai_confidence()
        elif command == "explainable_ai_scenarios":
            from explainable_ai.api import cmd_scenarios as _xai_scenarios
            result = _xai_scenarios()
        elif command == "explainable_ai_history":
            from explainable_ai.api import cmd_history as _xai_history
            result = _xai_history()
        elif command == "explainable_ai_snapshot":
            from explainable_ai.api import cmd_snapshot as _xai_snapshot
            result = _xai_snapshot()
        elif command == "explainable_ai_export":
            from explainable_ai.api import cmd_export as _xai_export
            result = _xai_export()

        # ── Phase 7.5 — Research, Simulation & Innovation Lab ─────────────────
        elif command == "research_lab_summary":
            from research_lab.api import cmd_summary as _rl_summary
            result = _rl_summary()
        elif command == "research_lab_strategies":
            from research_lab.api import cmd_strategies as _rl_strategies
            result = _rl_strategies()
        elif command == "research_lab_simulations":
            from research_lab.api import cmd_simulations as _rl_simulations
            result = _rl_simulations()
        elif command == "research_lab_replay":
            from research_lab.api import cmd_replay as _rl_replay
            result = _rl_replay()
        elif command == "research_lab_benchmark":
            from research_lab.api import cmd_benchmark as _rl_benchmark
            result = _rl_benchmark()
        elif command == "research_lab_reports":
            from research_lab.api import cmd_reports as _rl_reports
            result = _rl_reports()
        elif command == "research_lab_snapshot":
            from research_lab.api import cmd_snapshot as _rl_snapshot
            result = _rl_snapshot()
        elif command == "research_lab_export":
            from research_lab.api import cmd_export as _rl_export
            result = _rl_export()

        # ── Phase 8.1: Observability Center ──────────────────────────────────
        elif command == "observability_summary":
            from observability_center.api import cmd_summary as _f; result = _f()
        elif command == "observability_system":
            from observability_center.api import cmd_system as _f; result = _f()
        elif command == "observability_performance":
            from observability_center.api import cmd_performance as _f; result = _f()
        elif command == "observability_errors":
            from observability_center.api import cmd_errors as _f; result = _f()
        elif command == "observability_alerts":
            from observability_center.api import cmd_alerts as _f; result = _f()
        elif command == "observability_audit":
            from observability_center.api import cmd_audit as _f; result = _f()
        elif command == "observability_snapshot":
            from observability_center.api import cmd_snapshot as _f; result = _f()
        elif command == "observability_export_csv":
            from observability_center.api import cmd_export_csv as _f; result = _f()
        elif command == "observability_export_json":
            from observability_center.api import cmd_export_json as _f; result = _f()

        # ── Phase 8.2: Paper Analytics ────────────────────────────────────────
        elif command == "paper_analytics_summary":
            from paper_analytics.api import cmd_summary as _f; result = _f()
        elif command == "paper_analytics_trades":
            from paper_analytics.api import cmd_trades as _f; result = _f()
        elif command == "paper_analytics_strategies":
            from paper_analytics.api import cmd_strategies as _f; result = _f()
        elif command == "paper_analytics_risk":
            from paper_analytics.api import cmd_risk as _f; result = _f()
        elif command == "paper_analytics_preopen":
            from paper_analytics.api import cmd_preopen as _f; result = _f()
        elif command == "paper_analytics_portfolio":
            from paper_analytics.api import cmd_portfolio as _f; result = _f()
        elif command == "paper_analytics_learning":
            from paper_analytics.api import cmd_learning as _f; result = _f()
        elif command == "paper_analytics_snapshot":
            from paper_analytics.api import cmd_snapshot as _f; result = _f()
        elif command == "paper_analytics_export_json":
            from paper_analytics.api import cmd_export_json as _f; result = _f()
        elif command == "paper_analytics_export_csv":
            from paper_analytics.api import cmd_export_csv as _f; result = _f()

        # ── Phase 8.3: Data Quality & Validation Framework ────────────────────
        elif command == "data_quality_summary":
            from data_quality.api import cmd_summary as _f; result = _f()
        elif command == "data_quality_market":
            from data_quality.api import cmd_market as _f; result = _f()
        elif command == "data_quality_preopen":
            from data_quality.api import cmd_preopen as _f; result = _f()
        elif command == "data_quality_paper":
            from data_quality.api import cmd_paper as _f; result = _f()
        elif command == "data_quality_portfolio":
            from data_quality.api import cmd_portfolio as _f; result = _f()
        elif command == "data_quality_ai":
            from data_quality.api import cmd_ai as _f; result = _f()
        elif command == "data_quality_signals":
            from data_quality.api import cmd_signals as _f; result = _f()
        elif command == "data_quality_config":
            from data_quality.api import cmd_config as _f; result = _f()
        elif command == "data_quality_alerts":
            from data_quality.api import cmd_alerts as _f; result = _f()
        elif command == "data_quality_snapshot":
            from data_quality.api import cmd_snapshot as _f; result = _f()
        elif command == "data_quality_export_json":
            from data_quality.api import cmd_export_json as _f; result = _f()
        elif command == "data_quality_export_csv":
            from data_quality.api import cmd_export_csv as _f; result = _f()
        elif command == "data_quality_history":
            from data_quality.api import cmd_history as _f; result = _f()

        # ── Phase 8.4: Advanced Risk Validation Framework ─────────────────────
        elif command == "rv_summary":
            from risk_validation.api import cmd_summary      as _f; result = _f()
        elif command == "rv_portfolio":
            from risk_validation.api import cmd_portfolio     as _f; result = _f()
        elif command == "rv_sector":
            from risk_validation.api import cmd_sector        as _f; result = _f()
        elif command == "rv_correlation":
            from risk_validation.api import cmd_correlation   as _f; result = _f()
        elif command == "rv_stress":
            from risk_validation.api import cmd_stress        as _f; result = _f()
        elif command == "rv_tail":
            from risk_validation.api import cmd_tail          as _f; result = _f()
        elif command == "rv_execution":
            from risk_validation.api import cmd_execution     as _f; result = _f()
        elif command == "rv_market":
            from risk_validation.api import cmd_market        as _f; result = _f()
        elif command == "rv_drift":
            from risk_validation.api import cmd_drift         as _f; result = _f()
        elif command == "rv_alerts":
            from risk_validation.api import cmd_alerts        as _f; result = _f()
        elif command == "rv_snapshot":
            from risk_validation.api import cmd_snapshot      as _f; result = _f()
        elif command == "rv_export_json":
            from risk_validation.api import cmd_export_json   as _f; result = _f()
        elif command == "rv_export_csv":
            from risk_validation.api import cmd_export_csv    as _f; result = _f()

        # ── Phase 8.5: Operational Control Centre ─────────────────────────────
        elif command == "ops_summary":
            from operations_center.api import cmd_summary       as _f; result = _f()
        elif command == "ops_market":
            from operations_center.api import cmd_market        as _f; result = _f()
        elif command == "ops_paper":
            from operations_center.api import cmd_paper         as _f; result = _f()
        elif command == "ops_risk":
            from operations_center.api import cmd_risk          as _f; result = _f()
        elif command == "ops_data_quality":
            from operations_center.api import cmd_data_quality  as _f; result = _f()
        elif command == "ops_observability":
            from operations_center.api import cmd_observability as _f; result = _f()
        elif command == "ops_flags":
            from operations_center.api import cmd_flags         as _f; result = _f()
        elif command == "ops_jobs":
            from operations_center.api import cmd_jobs          as _f; result = _f()
        elif command == "ops_alerts":
            from operations_center.api import cmd_alerts        as _f; result = _f()
        elif command == "ops_checklist":
            from operations_center.api import cmd_checklist     as _f; result = _f()
        elif command == "ops_timeline":
            from operations_center.api import cmd_timeline      as _f; result = _f()
        elif command == "ops_snapshot":
            from operations_center.api import cmd_snapshot      as _f; result = _f()
        elif command == "ops_export_json":
            from operations_center.api import cmd_export_json   as _f; result = _f()
        elif command == "ops_export_csv":
            from operations_center.api import cmd_export_csv    as _f; result = _f()

        # ── Phase 8.6: Security & Compliance Centre ───────────────────────────
        elif command == "sec_summary":
            from security_center.api import cmd_summary      as _f; result = _f()
        elif command == "sec_auth":
            from security_center.api import cmd_auth         as _f; result = _f()
        elif command == "sec_sessions":
            from security_center.api import cmd_sessions     as _f; result = _f()
        elif command == "sec_secrets":
            from security_center.api import cmd_secrets      as _f; result = _f()
        elif command == "sec_config":
            from security_center.api import cmd_config       as _f; result = _f()
        elif command == "sec_api":
            from security_center.api import cmd_api          as _f; result = _f()
        elif command == "sec_dependencies":
            from security_center.api import cmd_dependencies as _f; result = _f()
        elif command == "sec_audit":
            from security_center.api import cmd_audit        as _f; result = _f()
        elif command == "sec_compliance":
            from security_center.api import cmd_compliance   as _f; result = _f()
        elif command == "sec_alerts":
            from security_center.api import cmd_alerts       as _f; result = _f()
        elif command == "sec_snapshot":
            from security_center.api import cmd_snapshot     as _f; result = _f()
        elif command == "sec_export_json":
            from security_center.api import cmd_export_json  as _f; result = _f()
        elif command == "sec_export_csv":
            from security_center.api import cmd_export_csv   as _f; result = _f()

        elif command == "perf_summary":
            from performance_center.api import cmd_summary        as _f; result = _f()
        elif command == "perf_api":
            from performance_center.api import cmd_api            as _f; result = _f()
        elif command == "perf_database":
            from performance_center.api import cmd_database       as _f; result = _f()
        elif command == "perf_cache":
            from performance_center.api import cmd_cache          as _f; result = _f()
        elif command == "perf_scheduler":
            from performance_center.api import cmd_scheduler      as _f; result = _f()
        elif command == "perf_resources":
            from performance_center.api import cmd_resources      as _f; result = _f()
        elif command == "perf_frontend":
            from performance_center.api import cmd_frontend       as _f; result = _f()
        elif command == "perf_scalability":
            from performance_center.api import cmd_scalability    as _f; result = _f()
        elif command == "perf_benchmark":
            from performance_center.api import cmd_benchmark      as _f; result = _f()
        elif command == "perf_recommendations":
            from performance_center.api import cmd_recommendations as _f; result = _f()
        elif command == "perf_snapshot":
            from performance_center.api import cmd_snapshot       as _f; result = _f()
        elif command == "perf_export_json":
            from performance_center.api import cmd_export_json    as _f; result = _f()
        elif command == "perf_export_csv":
            from performance_center.api import cmd_export_csv     as _f; result = _f()

        elif command == "deploy_summary":
            from deployment_center.api import cmd_summary         as _f; result = _f()
        elif command == "deploy_readiness":
            from deployment_center.api import cmd_readiness       as _f; result = _f()
        elif command == "deploy_config":
            from deployment_center.api import cmd_config          as _f; result = _f()
        elif command == "deploy_backups":
            from deployment_center.api import cmd_backups         as _f; result = _f()
        elif command == "deploy_restore":
            from deployment_center.api import cmd_restore         as _f; result = _f()
        elif command == "deploy_rollback":
            from deployment_center.api import cmd_rollback        as _f; result = _f()
        elif command == "deploy_infrastructure":
            from deployment_center.api import cmd_infrastructure  as _f; result = _f()
        elif command == "deploy_continuity":
            from deployment_center.api import cmd_continuity      as _f; result = _f()
        elif command == "deploy_recommendations":
            from deployment_center.api import cmd_recommendations as _f; result = _f()
        elif command == "deploy_snapshot":
            from deployment_center.api import cmd_snapshot        as _f; result = _f()
        elif command == "deploy_export_json":
            from deployment_center.api import cmd_export_json     as _f; result = _f()
        elif command == "deploy_export_csv":
            from deployment_center.api import cmd_export_csv      as _f; result = _f()

        elif command == "cmd_center_summary":
            from command_center.api import cmd_summary     as _f; result = _f()
        elif command == "cmd_center_briefing":
            from command_center.api import cmd_briefing    as _f; result = _f()
        elif command == "cmd_center_alerts":
            from command_center.api import cmd_alerts      as _f; result = _f()
        elif command == "cmd_center_timeline":
            from command_center.api import cmd_timeline    as _f; result = _f()
        elif command == "cmd_center_snapshot":
            from command_center.api import cmd_snapshot    as _f; result = _f()
        elif command == "cmd_center_export_json":
            from command_center.api import cmd_export_json as _f; result = _f()
        elif command == "cmd_center_export_csv":
            from command_center.api import cmd_export_csv  as _f; result = _f()

        # ── Phase 10A: Agent Framework ────────────────────────────────────────
        elif command == "agent_supervisor_snapshot":
            from supervisor_agent.shared_services import get_supervisor_snapshot as _f; result = _f()
        elif command == "agent_list":
            from supervisor_agent.shared_services import get_agent_list as _f; result = _f()
        elif command == "agent_detail":
            agent_id_arg = args[0] if args else ""
            from supervisor_agent.shared_services import get_agent_detail as _f; result = _f(agent_id_arg)
        elif command == "agent_supervisor_alerts":
            from supervisor_agent.shared_services import get_supervisor_alerts as _f; result = _f()
        elif command == "agent_market_data_snapshot":
            from market_data_agent.shared_services import get_market_data_snapshot as _f; result = _f()
        elif command == "agent_market_data_metrics":
            from market_data_agent.shared_services import get_market_data_metrics as _f; result = _f()
        elif command == "agent_research_snapshot":
            from research_agent.shared_services import get_research_snapshot as _f; result = _f()
        elif command == "agent_research_metrics":
            from research_agent.shared_services import get_research_metrics as _f; result = _f()
        elif command == "agent_scalability":
            from supervisor_agent.shared_services import get_scalability_estimate as _f; result = _f()

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
