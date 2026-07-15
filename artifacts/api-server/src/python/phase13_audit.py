"""
phase13_audit.py — Phase 13 Model Comparison Audit Report

Compares Phase 13 vs Phase 12 (current) engine on out-of-sample completed paper trades.

Metrics:
  expectancy_after_costs, profit_factor, max_drawdown, sharpe_approx,
  win_rate, trade_count, turnover, regime_stability, sector_concentration,
  calibration_quality, benchmark_comparison

PAPER TRADING / RESEARCH ONLY — no live broker orders.
"""

from __future__ import annotations

import json
import math
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

_DIR = os.path.dirname(os.path.abspath(__file__))
AUDIT_FILE = os.path.join(_DIR, "phase13_audit_report.json")
BROKERAGE_PCT = 0.001  # 0.1% per leg (approximate NSE brokerage)
BENCHMARK_NIFTY_ANNUAL_PCT = 14.0  # approximate NIFTY 50 annual return

RESEARCH_ENGINE_VERSION = "Research Engine v1.0 · Phase 13"


def _now_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _load_json(path: str, default: Any = None) -> Any:
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return default


def _completed_paper_trades() -> List[Dict[str, Any]]:
    """Strict no-lookahead: only SELL rows with close timestamps."""
    try:
        from paper_trader import get_trades
        trades = list(get_trades())
    except Exception:
        return []
    return [
        t for t in trades
        if isinstance(t, dict)
        and t.get("action", "").upper() == "SELL"
        and bool(t.get("timestamp") or t.get("close_ts") or t.get("trade_date"))
    ]


def _brokerage(trade: Dict[str, Any]) -> float:
    """Estimate brokerage for a completed trade."""
    qty = float(trade.get("quantity", 0) or 0)
    buy_p = float(trade.get("avg_buy_price") or trade.get("entry_price") or 0)
    sell_p = float(trade.get("price") or trade.get("exit_price") or 0)
    return round(qty * (buy_p + sell_p) * BROKERAGE_PCT, 4)


def _compute_metrics(trades: List[Dict[str, Any]], engine_label: str) -> Dict[str, Any]:
    if not trades:
        return {
            "engine": engine_label, "trade_count": 0,
            "insufficient_data": True,
            "note": "No completed paper trades available for analysis.",
        }

    pnls_gross = []
    pnls_net = []
    sectors: List[str] = []
    regimes: List[str] = []
    turnover = 0.0

    for t in trades:
        qty = float(t.get("quantity", 0) or 0)
        buy_p = float(t.get("avg_buy_price") or t.get("entry_price") or 0)
        sell_p = float(t.get("price") or t.get("exit_price") or 0)
        gross = float(t.get("pnl") or t.get("realized_pnl") or 0)
        if not gross and qty and buy_p and sell_p:
            gross = (sell_p - buy_p) * qty
        cost = _brokerage(t)
        net = gross - cost
        pnls_gross.append(gross)
        pnls_net.append(net)
        if buy_p and qty:
            turnover += qty * buy_p
        sec = t.get("sector") or t.get("stock_sector")
        if sec:
            sectors.append(str(sec))
        reg = t.get("regime") or t.get("market_regime")
        if reg:
            regimes.append(str(reg))

    n = len(pnls_net)
    wins = [p for p in pnls_net if p > 0]
    losses = [p for p in pnls_net if p <= 0]
    wr = len(wins) / n if n else 0.0
    avg_win = sum(wins) / len(wins) if wins else 0.0
    avg_loss = abs(sum(losses) / len(losses)) if losses else 0.0
    expectancy_after_costs = wr * avg_win - (1 - wr) * avg_loss
    gp = sum(wins); gl = abs(sum(losses))
    pf = gp / gl if gl > 0 else (1.5 if gp > 0 else 1.0)

    # Drawdown
    equity, peak, max_dd = 0.0, 0.0, 0.0
    for p in pnls_net:
        equity += p
        if equity > peak:
            peak = equity
        dd = (peak - equity) / max(1.0, abs(peak)) if peak > 0 else 0
        if dd > max_dd:
            max_dd = dd

    # Sharpe
    mean_p = sum(pnls_net) / n
    var = sum((p - mean_p) ** 2 for p in pnls_net) / max(1, n - 1)
    std = math.sqrt(var) if var > 0 else 1.0
    sharpe = (mean_p / std) * math.sqrt(252 / max(1, n)) if std > 0 else 0.0

    # Sector concentration (top-1 sector share)
    sector_count: Dict[str, int] = {}
    for s in sectors:
        sector_count[s] = sector_count.get(s, 0) + 1
    top_sector_share = max(sector_count.values()) / len(sectors) if sectors else 0.0
    top_sector = max(sector_count, key=sector_count.__getitem__) if sector_count else None

    # Regime stability (% of trades in dominant regime)
    regime_count: Dict[str, int] = {}
    for r in regimes:
        regime_count[r] = regime_count.get(r, 0) + 1
    dom_regime_share = max(regime_count.values()) / len(regimes) if regimes else 0.0
    dominant_regime = max(regime_count, key=regime_count.__getitem__) if regime_count else None

    # Benchmark comparison (simple: total PnL vs hypothetical NIFTY hold)
    # Assumes average holding period ~5 days
    avg_hold_days = 5
    benchmark_pnl_pct = BENCHMARK_NIFTY_ANNUAL_PCT / 365 * avg_hold_days * n
    total_pnl_pct = sum(pnls_net) / 5000 * 100  # as % of ₹5000 capital
    alpha = round(total_pnl_pct - benchmark_pnl_pct, 2)

    return {
        "engine": engine_label,
        "trade_count": n,
        "win_rate": round(wr, 4),
        "expectancy_after_costs": round(expectancy_after_costs, 2),
        "profit_factor": round(min(pf, 9.99), 2),
        "avg_win": round(avg_win, 2),
        "avg_loss": round(avg_loss, 2),
        "gross_profit": round(gp, 2),
        "gross_loss": round(gl, 2),
        "total_net_pnl": round(sum(pnls_net), 2),
        "total_gross_pnl": round(sum(pnls_gross), 2),
        "total_brokerage": round(sum(pnls_gross) - sum(pnls_net), 2),
        "max_drawdown_pct": round(max_dd * 100, 2),
        "sharpe_approx": round(sharpe, 2),
        "turnover": round(turnover, 2),
        "sector_concentration": {
            "top_sector": top_sector,
            "top_sector_share_pct": round(top_sector_share * 100, 1),
            "sector_breakdown": {k: round(v / n * 100, 1) for k, v in sorted(sector_count.items(), key=lambda x: -x[1])},
        },
        "regime_stability": {
            "dominant_regime": dominant_regime,
            "dominant_regime_share_pct": round(dom_regime_share * 100, 1),
            "regime_breakdown": {k: round(v / len(regimes) * 100, 1) for k, v in sorted(regime_count.items(), key=lambda x: -x[1])} if regimes else {},
        },
        "benchmark": {
            "name": "NIFTY 50 (approx)",
            "annual_return_pct": BENCHMARK_NIFTY_ANNUAL_PCT,
            "strategy_total_pnl_pct": round(total_pnl_pct, 2),
            "benchmark_pnl_pct": round(benchmark_pnl_pct, 2),
            "alpha_pct": alpha,
        },
        "insufficient_data": False,
    }


def build_audit_report() -> Dict[str, Any]:
    """
    Build comparison of Phase 13 vs Phase 12 on the same set of completed trades.
    Both use the SAME trade history — the difference is the attribution metadata
    (which engine scored the trade).
    """
    completed = _completed_paper_trades()

    # Split by which engine tagged the trade (phase field or engine_version)
    p13_trades = [t for t in completed if "13" in str(t.get("engine_version") or t.get("phase") or "")]
    p12_trades = [t for t in completed if "12" in str(t.get("engine_version") or t.get("phase") or "")]
    all_trades = completed  # fallback: all trades for overall stats

    # If no engine tagging, use all trades for both (same dataset, demonstrates comparison framework)
    if not p13_trades and not p12_trades:
        p13_trades = all_trades
        p12_trades = all_trades
        note = "No engine-tagged trades yet — both columns show the same completed paper trades. Engine attribution will differentiate as trades accumulate."
    else:
        note = f"P13: {len(p13_trades)} trades | P12: {len(p12_trades)} trades"

    p13_metrics = _compute_metrics(p13_trades, "Phase 13 (current)")
    p12_metrics = _compute_metrics(p12_trades, "Phase 12 (baseline)")

    # Delta comparison
    delta: Dict[str, Any] = {}
    numeric_keys = [
        "win_rate", "expectancy_after_costs", "profit_factor",
        "max_drawdown_pct", "sharpe_approx",
    ]
    for k in numeric_keys:
        v13 = p13_metrics.get(k)
        v12 = p12_metrics.get(k)
        if isinstance(v13, (int, float)) and isinstance(v12, (int, float)):
            d = round(v13 - v12, 4)
            delta[k] = {"delta": d, "direction": "better" if (d > 0 and k != "max_drawdown_pct") or (d < 0 and k == "max_drawdown_pct") else "worse" if d != 0 else "same"}

    # Calibration quality
    p12_cache = _load_json(os.path.join(_DIR, "phase12_cache.json"), {})
    p13_cache = _load_json(os.path.join(_DIR, "phase13_cache.json"), {})
    p12_analysis = p12_cache.get("full_analysis") or {}
    p13_analysis = p13_cache.get("full_analysis") or {}

    def _avg_calib(analysis: Dict[str, Any]) -> Optional[float]:
        results = analysis.get("fused_results") or []
        scores = [r.get("factor_scores", {}).get("calibration_quality") for r in results if r.get("factor_scores")]
        valid = [s for s in scores if s is not None]
        return round(sum(valid) / len(valid), 1) if valid else None

    report = {
        "phase": 13,
        "engine_version": RESEARCH_ENGINE_VERSION,
        "generated_at": _now_str(),
        "label": "PAPER / RESEARCH ONLY",
        "mode": "out_of_sample_paper_trade_comparison",
        "note": note,
        "phase13": p13_metrics,
        "phase12": p12_metrics,
        "delta": delta,
        "calibration_comparison": {
            "phase13_avg_calib_score": _avg_calib(p13_analysis),
            "phase12_avg_calib_score": _avg_calib(p12_analysis),
        },
        "total_completed_trades": len(completed),
        "interpretation": _interpret_delta(delta, len(completed)),
        "caveats": [
            f"Based on {len(completed)} completed paper trades — live performance may differ.",
            "No live broker orders placed. All analysis is research-only.",
            "Small sample sizes reduce statistical reliability.",
            "Regime and sector conditions during backtesting may not repeat.",
        ],
    }

    try:
        with open(AUDIT_FILE, "w") as f:
            json.dump(report, f, indent=2, default=str)
    except Exception:
        pass

    return report


def _interpret_delta(delta: Dict[str, Any], n: int) -> str:
    if n < 20:
        return f"Insufficient evidence ({n} trades). Minimum 20 OOS trades needed for reliable comparison."
    improvements = sum(1 for v in delta.values() if isinstance(v, dict) and v.get("direction") == "better")
    regressions  = sum(1 for v in delta.values() if isinstance(v, dict) and v.get("direction") == "worse")
    if improvements > regressions:
        return f"Phase 13 shows improvement in {improvements}/{len(delta)} tracked metrics vs Phase 12."
    elif regressions > improvements:
        return f"Phase 12 outperforms Phase 13 in {regressions}/{len(delta)} metrics. Further tuning needed."
    else:
        return "Phase 13 and Phase 12 show comparable performance across tracked metrics."
