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
        elif command == "phase7_scan":
            from live_scan_engine import get_or_run_scan
            force = len(args) > 1 and args[1] == "force"
            result = get_or_run_scan(max_age_s=600, force=force)
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
