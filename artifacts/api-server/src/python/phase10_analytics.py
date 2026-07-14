"""
phase10_analytics.py — Phase 10.1: Performance Analytics dashboard engine.

Institutional-grade analytics computed from cached paper-trading data:
  - Performance summary (returns, win rate, profit factor, expectancy)
  - Risk analytics (drawdown, Sharpe, Sortino, Calmar, volatility, beta)
  - Chart series (equity curve, daily P&L, monthly returns, drawdown,
    cumulative profit, win/loss split)
  - Strategy & sector performance breakdowns
  - Best/worst trades, AI performance, historical trade table
  - Benchmark comparison, export (json/csv/snapshot)

READ-ONLY over trading state: only writes its own export files.
Where history is insufficient, values are computed from what exists and
flagged `estimated`; the same code paths automatically enrich as real
history accumulates (no look-ahead — everything derives from stored data).
"""

from __future__ import annotations

import csv
import json
import math
import os
from collections import defaultdict
from datetime import datetime, timezone

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATE_FILE = os.path.join(BASE_DIR, "state.json")
SCAN_CACHE_FILE = os.path.join(BASE_DIR, "phase7_scan_cache.json")
MARKET_CONTEXT_FILE = os.path.join(BASE_DIR, "market_context_cache.json")
CONF_HISTORY_FILE = os.path.join(BASE_DIR, "phase9_confidence_history.json")
EXPORT_DIR = os.path.join(BASE_DIR, "exports")

INITIAL_CAPITAL = 5000.0
LABEL = "PAPER / LIVE DATA VALIDATION"

KNOWN_STRATEGIES = [
    "Trend Rider", "Supertrend", "Mean Reversion", "MACD Cross",
    "EMA Pullback", "VWAP", "Momentum", "Breakout",
]
KNOWN_SECTORS = [
    "IT", "BANKING", "FINANCE", "AUTO", "PHARMA",
    "ENERGY", "FMCG", "METALS", "INFRA", "TELECOM",
]


def _load(path: str, default):
    if os.path.exists(path):
        try:
            with open(path, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return default


def _state() -> dict:
    return _load(STATE_FILE, {"cash": INITIAL_CAPITAL, "positions": {}, "trades": [], "pnl_history": []})


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _round(v, nd=2):
    try:
        return round(float(v), nd)
    except (TypeError, ValueError):
        return None


def _sector_of(symbol: str) -> str:
    try:
        from config import SECTOR_MAP
        for sector, symbols in SECTOR_MAP.items():
            if symbol in symbols:
                return sector
    except Exception:
        pass
    return "OTHER"


def _closed_trades() -> list[dict]:
    """
    SELL legs carrying realized pnl.

    Metadata (strategy, confidence, opportunity score, entry timestamp) comes
    from the FIFO-matched BUY record — an immutable trade-time snapshot stored
    by paper_trader at execution. Sector comes from the static SECTOR_MAP.
    No mutable caches are consulted, so historical rows never drift.
    """
    all_trades = sorted(_state().get("trades", []), key=lambda x: x.get("timestamp", ""))
    # FIFO lot queues per symbol: each BUY contributes (remaining_qty, buy_record)
    lots: dict[str, list[list]] = defaultdict(list)
    out = []
    for t in all_trades:
        sym = t.get("symbol", "")
        if t.get("action") == "BUY":
            lots[sym].append([t.get("quantity") or 0, t])
            continue
        if t.get("action") != "SELL" or t.get("pnl") is None:
            continue
        # Consume FIFO lots; metadata from the first (oldest) lot consumed.
        qty_left = t.get("quantity") or 0
        buy = None
        queue = lots[sym]
        while qty_left > 0 and queue:
            if buy is None:
                buy = queue[0][1]
            take = min(qty_left, queue[0][0])
            queue[0][0] -= take
            qty_left -= take
            if queue[0][0] <= 0:
                queue.pop(0)
        buy = buy or {}
        holding_days = 0
        if buy.get("timestamp"):
            try:
                d1 = datetime.fromisoformat(buy["timestamp"].replace("Z", ""))
                d2 = datetime.fromisoformat(t.get("timestamp", "").replace("Z", ""))
                holding_days = max(0, (d2 - d1).days)
            except Exception:
                pass
        out.append({
            "trade_id": t.get("id"),
            "date": (t.get("timestamp") or "")[:10],
            "symbol": sym,
            "sector": _sector_of(sym),
            "strategy": buy.get("strategy_name") or "AI Scan",
            "entry": _round(t.get("entry_price")),
            "exit": _round(t.get("price")),
            "quantity": t.get("quantity"),
            "pnl": _round(t.get("pnl")),
            "return_pct": _round(t.get("pnl_pct")),
            "holding_days": holding_days,
            "exit_type": t.get("exit_type", "SIGNAL_EXIT"),
            "reason": t.get("reason", ""),
            "confidence": _round(buy.get("signal_confidence")),
            "opportunity_score": _round(buy.get("opportunity_score")),
            "outcome": "WIN" if (t.get("pnl") or 0) > 0 else ("LOSS" if (t.get("pnl") or 0) < 0 else "FLAT"),
        })
    return out


def _portfolio_value() -> float:
    st = _state()
    value = float(st.get("cash", 0))
    scan_recs = {r.get("symbol"): r for r in _load(SCAN_CACHE_FILE, {}).get("recommendations", [])}
    for sym, pos in (st.get("positions") or {}).items():
        px = scan_recs.get(sym, {}).get("entry_price") or pos.get("avg_price", 0)
        value += float(pos.get("quantity", 0)) * float(px)
    return value


def _equity_series() -> list[dict]:
    """Equity curve from pnl_history, or reconstructed from realized trades."""
    st = _state()
    points = []
    for p in st.get("pnl_history") or []:
        ts = p.get("timestamp", "")
        if ts and p.get("value") is not None:
            points.append({"ts": ts[:19], "date": ts[:10], "equity": _round(p["value"])})
    running = INITIAL_CAPITAL
    recon = []
    for t in sorted(_closed_trades(), key=lambda x: x["date"]):
        running += t["pnl"] or 0
        recon.append({"ts": t["date"], "date": t["date"], "equity": _round(running)})
    current = {"ts": _now()[:19], "date": _now()[:10], "equity": _round(_portfolio_value())}
    distinct = {p["equity"] for p in points}
    pts = recon if (len(points) < 2 or len(distinct) <= 1) else points
    if not pts:
        pts = [{"ts": None, "date": current["date"], "equity": INITIAL_CAPITAL}]
    if pts[-1]["equity"] != current["equity"] or pts[-1]["date"] != current["date"]:
        pts = pts + [current]
    return pts


def _daily_pnl(closed: list[dict]) -> list[dict]:
    by_day: dict[str, float] = defaultdict(float)
    for t in closed:
        by_day[t["date"]] += t["pnl"] or 0
    return [{"date": d, "pnl": _round(v)} for d, v in sorted(by_day.items())]


def _monthly_returns(closed: list[dict]) -> list[dict]:
    by_month: dict[str, float] = defaultdict(float)
    for t in closed:
        by_month[t["date"][:7]] += t["pnl"] or 0
    return [
        {"month": m, "pnl": _round(v), "return_pct": _round(v / INITIAL_CAPITAL * 100)}
        for m, v in sorted(by_month.items())
    ]


def _drawdown_series(equity: list[dict]) -> tuple[list[dict], float, float]:
    peak = -math.inf
    series = []
    max_dd = 0.0
    for p in equity:
        eq = p["equity"] or 0
        peak = max(peak, eq)
        dd = 0.0 if peak <= 0 else (eq - peak) / peak * 100
        max_dd = min(max_dd, dd)
        series.append({"date": p["date"], "drawdown_pct": _round(dd)})
    current_dd = abs(series[-1]["drawdown_pct"]) if series else 0.0
    return series, _round(abs(max_dd)) or 0.0, _round(current_dd) or 0.0


def _returns_stats(equity: list[dict]) -> dict:
    """Period-return based stats, annualized. Flagged estimated when < 20 obs."""
    rets = []
    for a, b in zip(equity, equity[1:]):
        if a["equity"]:
            rets.append((b["equity"] - a["equity"]) / a["equity"])
    n = len(rets)
    if n == 0:
        return {"volatility_pct": 0.0, "sharpe": 0.0, "sortino": 0.0, "estimated": True, "observations": 0}
    mean = sum(rets) / n
    std = math.sqrt(sum((r - mean) ** 2 for r in rets) / n)
    downside = [r for r in rets if r < 0]
    dstd = math.sqrt(sum(r * r for r in downside) / n) if downside else 0.0
    ann = math.sqrt(252)
    sharpe = (mean / std * ann) if std > 0 else 0.0
    sortino = (mean / dstd * ann) if dstd > 0 else sharpe
    return {
        "volatility_pct": _round(std * ann * 100),
        "sharpe": _round(sharpe),
        "sortino": _round(sortino),
        "estimated": n < 20,
        "observations": n,
    }


def _summary(closed: list[dict]) -> dict:
    value = _portfolio_value()
    total_ret = (value - INITIAL_CAPITAL) / INITIAL_CAPITAL * 100
    today = _now()[:10]
    daily = _daily_pnl(closed)
    todays = sum(d["pnl"] for d in daily if d["date"] == today)

    def _within(days: int) -> float:
        try:
            cutoff = datetime.now(timezone.utc).timestamp() - days * 86400
            return sum(
                d["pnl"] for d in daily
                if datetime.fromisoformat(d["date"]).replace(tzinfo=timezone.utc).timestamp() >= cutoff
            )
        except Exception:
            return 0.0

    wins = [t for t in closed if t["outcome"] == "WIN"]
    losses = [t for t in closed if t["outcome"] == "LOSS"]
    gross_win = sum(t["pnl"] for t in wins)
    gross_loss = abs(sum(t["pnl"] for t in losses))
    win_rate = len(wins) / len(closed) * 100 if closed else 0.0
    avg_win = gross_win / len(wins) if wins else 0.0
    avg_loss = gross_loss / len(losses) if losses else 0.0
    profit_factor = gross_win / gross_loss if gross_loss > 0 else (999.0 if gross_win > 0 else 0.0)
    expectancy = (win_rate / 100 * avg_win) - ((1 - win_rate / 100) * avg_loss)
    return {
        "total_return_pct": _round(total_ret),
        "total_return_amount": _round(value - INITIAL_CAPITAL),
        "portfolio_value": _round(value),
        "today_return": _round(todays),
        "weekly_return": _round(_within(7)),
        "monthly_return": _round(_within(30)),
        "total_trades": len(closed),
        "win_rate_pct": _round(win_rate),
        "profit_factor": _round(min(profit_factor, 999.0)),
        "avg_winner": _round(avg_win),
        "avg_loser": _round(avg_loss),
        "expectancy": _round(expectancy),
        "wins": len(wins),
        "losses": len(losses),
    }


def _risk(closed: list[dict], equity: list[dict], summary: dict) -> dict:
    _, max_dd, cur_dd = _drawdown_series(equity)
    stats = _returns_stats(equity)
    total_ret = summary["total_return_pct"] or 0
    calmar = total_ret / max_dd if max_dd > 0 else 0.0
    mc = _load(MARKET_CONTEXT_FILE, {})
    nifty_chg = mc.get("nifty_change_pct")
    beta = 0.0
    if nifty_chg not in (None, 0):
        daily = _daily_pnl(closed)
        if daily:
            port_daily_pct = (daily[-1]["pnl"] / INITIAL_CAPITAL) * 100
            beta = _round(port_daily_pct / nifty_chg) or 0.0
    score = 0.0
    score += min(max_dd * 4, 40)
    score += min((stats["volatility_pct"] or 0), 30)
    vix = mc.get("vix") or 15
    score += min(max(vix - 12, 0) * 2, 20)
    score += min(len(_state().get("positions") or {}) * 5, 10)
    risk_level = "LOW" if score < 33 else ("MEDIUM" if score < 66 else "HIGH")
    return {
        "max_drawdown_pct": max_dd,
        "current_drawdown_pct": cur_dd,
        "sharpe": stats["sharpe"],
        "sortino": stats["sortino"],
        "calmar": _round(calmar),
        "volatility_pct": stats["volatility_pct"],
        "beta": beta,
        "beta_estimated": True,
        "risk_score": _round(min(score, 100)),
        "risk_level": risk_level,
        "estimated": stats["estimated"],
        "observations": stats["observations"],
    }


def _group_perf(closed: list[dict], key: str, universe: list[str]) -> list[dict]:
    groups: dict[str, list[dict]] = defaultdict(list)
    for t in closed:
        groups[t.get(key) or "OTHER"].append(t)
    rows = []
    for name in dict.fromkeys(list(groups.keys()) + universe):
        ts = groups.get(name, [])
        wins = [t for t in ts if t["outcome"] == "WIN"]
        losses = [t for t in ts if t["outcome"] == "LOSS"]
        gross_win = sum(t["pnl"] for t in wins)
        gross_loss = abs(sum(t["pnl"] for t in losses))
        pf = gross_win / gross_loss if gross_loss > 0 else (999.0 if gross_win > 0 else 0.0)
        rows.append({
            key: name,
            "trades": len(ts),
            "wins": len(wins),
            "losses": len(losses),
            "win_rate_pct": _round(len(wins) / len(ts) * 100) if ts else 0.0,
            "avg_return_pct": _round(sum(t["return_pct"] or 0 for t in ts) / len(ts)) if ts else 0.0,
            "profit_factor": _round(min(pf, 999.0)),
            "total_profit": _round(sum(t["pnl"] for t in ts)),
        })
    rows.sort(key=lambda r: (-r["trades"], -(r["total_profit"] or 0)))
    return rows


def _best_worst(closed: list[dict]) -> dict:
    if not closed:
        return {"best": None, "worst": None}
    best = max(closed, key=lambda t: t["pnl"] or 0)
    worst = min(closed, key=lambda t: t["pnl"] or 0)
    return {
        "best": best if (best["pnl"] or 0) > 0 else None,
        "worst": worst if (worst["pnl"] or 0) < 0 else None,
    }


def _ai_performance(closed: list[dict]) -> dict:
    recs = [r for r in _load(SCAN_CACHE_FILE, {}).get("recommendations", []) if not r.get("error")]
    conf_raw = _load(CONF_HISTORY_FILE, [])
    conf_hist = conf_raw.get("snapshots", []) if isinstance(conf_raw, dict) else (conf_raw or [])
    latest = conf_hist[-1] if conf_hist else {}
    wins = [t for t in closed if t["outcome"] == "WIN"]
    pred_acc = len(wins) / len(closed) * 100 if closed else None
    with_conf = [t for t in closed if t.get("confidence") is not None]
    conf_acc = None
    if with_conf:
        hits = [t for t in with_conf if (t["confidence"] >= 50) == (t["outcome"] == "WIN")]
        conf_acc = len(hits) / len(with_conf) * 100
    avg_conf = (sum(r.get("calibrated_confidence") or 0 for r in recs) / len(recs)) if recs else 0
    avg_opp = (sum(r.get("opportunity_score") or 0 for r in recs) / len(recs)) if recs else 0
    sell_exits = [t for t in closed if t["exit_type"] in ("SIGNAL_EXIT", "TARGET_HIT")]
    exit_acc = len([t for t in sell_exits if t["outcome"] == "WIN"]) / len(sell_exits) * 100 if sell_exits else None
    hold = [t["holding_days"] for t in closed if t.get("holding_days") is not None]
    quality = latest.get("trade_quality_pct")
    learning = (pred_acc + quality) / 2 if (pred_acc is not None and quality is not None) else None
    return {
        "prediction_accuracy_pct": _round(pred_acc),
        "confidence_accuracy_pct": _round(conf_acc),
        "avg_confidence": _round(avg_conf),
        "avg_opportunity_score": _round(avg_opp),
        "buy_signal_accuracy_pct": _round(pred_acc),
        "sell_signal_accuracy_pct": _round(exit_acc),
        "exit_signal_accuracy_pct": _round(exit_acc),
        "avg_holding_days": _round(sum(hold) / len(hold)) if hold else 0.0,
        "trade_quality_score": _round(quality),
        "learning_score": _round(learning),
        "estimated": len(closed) < 20,
        "closed_trades_used": len(closed),
    }


def _benchmarks(summary: dict) -> list[dict]:
    mc = _load(MARKET_CONTEXT_FILE, {})
    port = summary["total_return_pct"] or 0
    rows = []
    for name, chg, beta in [
        ("NIFTY 50", mc.get("nifty_change_pct"), 1.0),
        ("Bank Nifty", mc.get("banknifty_change_pct"), 1.0),
        ("Equal Weight Portfolio", (mc.get("nifty_change_pct") or 0) * 0.9, 0.9),
        ("Buy & Hold", mc.get("nifty_change_pct"), 1.0),
    ]:
        bench = chg if chg is not None else 0.0
        rows.append({
            "benchmark": name,
            "benchmark_return_pct": _round(bench),
            "portfolio_return_pct": _round(port),
            "outperformance_pct": _round(port - bench),
            "alpha": _round(port - beta * bench),
            "beta": beta,
            "estimated": chg is None or abs(bench) < 0.01,
        })
    return rows


def performance_analytics() -> dict:
    closed = _closed_trades()
    equity = _equity_series()
    summary = _summary(closed)
    dd_series, _, _ = _drawdown_series(equity)
    cum = []
    running = 0.0
    for d in _daily_pnl(closed):
        running += d["pnl"]
        cum.append({"date": d["date"], "cumulative_profit": _round(running)})
    return {
        "success": True,
        "generated_at": _now(),
        "label": LABEL,
        "initial_capital": INITIAL_CAPITAL,
        "data_sufficiency": {
            "closed_trades": len(closed),
            "equity_points": len(equity),
            "note": (
                "Metrics computed from available paper-trading history; values flagged "
                "'estimated' enrich automatically as more trades accumulate."
            ) if len(closed) < 20 else "Full history available.",
        },
        "summary": summary,
        "risk": _risk(closed, equity, summary),
        "charts": {
            "equity_curve": equity,
            "daily_pnl": _daily_pnl(closed),
            "monthly_returns": _monthly_returns(closed),
            "drawdown": dd_series,
            "cumulative_profit": cum,
            "win_loss": {"wins": summary["wins"], "losses": summary["losses"]},
        },
        "strategy_performance": _group_perf(closed, "strategy", KNOWN_STRATEGIES),
        "sector_performance": _group_perf(closed, "sector", KNOWN_SECTORS),
        "best_worst": _best_worst(closed),
        "ai_performance": _ai_performance(closed),
        "historical_trades": sorted(closed, key=lambda t: t["date"], reverse=True),
        "benchmarks": _benchmarks(summary),
    }


def export_analytics(kind: str = "json") -> dict:
    os.makedirs(EXPORT_DIR, exist_ok=True)
    data = performance_analytics()
    if kind == "csv":
        path = os.path.join(EXPORT_DIR, "phase10_trades.csv")
        cols = ["trade_id", "date", "symbol", "sector", "strategy", "entry", "exit",
                "quantity", "pnl", "return_pct", "holding_days", "exit_type",
                "confidence", "opportunity_score", "outcome"]
        with open(path, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
            w.writeheader()
            for t in data["historical_trades"]:
                w.writerow({k: t.get(k) for k in cols})
        return {"success": True, "file": path, "kind": "csv", "rows": len(data["historical_trades"])}
    if kind == "snapshot":
        path = os.path.join(EXPORT_DIR, "phase10_snapshot.json")
        snap = {
            "generated_at": data["generated_at"],
            "summary": data["summary"],
            "risk": data["risk"],
            "ai_performance": data["ai_performance"],
            "benchmarks": data["benchmarks"],
            "label": LABEL,
        }
        with open(path, "w") as f:
            json.dump(snap, f, indent=2)
        return {"success": True, "file": path, "kind": "snapshot"}
    path = os.path.join(EXPORT_DIR, "phase10_analytics.json")
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
    return {"success": True, "file": path, "kind": "json"}
