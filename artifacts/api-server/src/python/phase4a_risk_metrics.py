"""
phase4a_risk_metrics.py — Phase 4A Section 4: Risk Validation.

Computes all 15 risk metrics from closed-trade history and live portfolio:

  1.  win_rate_pct               — wins / total trades × 100
  2.  loss_rate_pct              — losses / total trades × 100
  3.  avg_reward_risk_ratio      — avg winner / avg loser (absolute)
  4.  profit_factor              — gross profit / gross loss
  5.  expectancy                 — avg ₹ P&L per trade
  6.  max_drawdown_pct           — peak-to-trough drawdown %
  7.  largest_win                — largest single winning trade ₹
  8.  largest_loss               — largest single losing trade ₹
  9.  daily_risk_pct             — today's realised loss % of portfolio
  10. capital_usage_pct          — invested / total_equity × 100
  11. position_exposure_pct      — open position value / total_equity × 100
  12. sector_exposure            — dict: sector → exposure_pct
  13. kill_switch_events         — number of kill switch activations (ever)
  14. circuit_breaker_events     — number of CB trips (ever)
  15. open_position_limit_usage  — open positions / max_open_positions limit

Usage:
    uv run python phase4a_risk_metrics.py --compute [--date YYYY-MM-DD]

PAPER TRADING / RESEARCH ONLY.
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
from typing import Any, Optional

_DIR = os.path.dirname(os.path.abspath(__file__))
_DOCS = os.path.join(_DIR, "..", "..", "docs")
os.makedirs(_DOCS, exist_ok=True)

LABEL = "PAPER TRADING / RESEARCH ONLY"


def _now_ist() -> str:
    try:
        import zoneinfo
        return datetime.datetime.now(zoneinfo.ZoneInfo("Asia/Kolkata")).isoformat()
    except Exception:
        return datetime.datetime.utcnow().isoformat() + "Z"


def _sector_of(symbol: str) -> str:
    try:
        import config
        for sector, syms in config.SECTOR_MAP.items():
            if symbol.upper() in syms:
                return sector
    except Exception:
        pass
    return "Unknown"


def compute_risk_metrics(date_str: Optional[str] = None) -> dict:
    """
    Compute all 15 Phase 4A risk metrics.
    Returns a flat dict suitable for JSON serialisation.
    """
    target_date = date_str or datetime.date.today().isoformat()

    # ── Load closed trades ────────────────────────────────────────────────────
    closed_trades: list[dict] = []
    try:
        from phase20_executor import get_ledger
        all_trades = get_ledger(500)
        closed_trades = [t for t in all_trades if t.get("status") == "CLOSED"
                         and t.get("realized_pnl") is not None]
    except Exception:
        pass

    # ── Also load paper_trader trades for daily P&L ───────────────────────────
    paper_trades: list[dict] = []
    try:
        import portfolio_store as _store
        state = _store.load_state()
        paper_trades = [t for t in state.get("trades", [])
                        if t.get("action") == "SELL"]
    except Exception:
        pass

    # ── Portfolio snapshot ────────────────────────────────────────────────────
    portfolio: dict = {}
    try:
        import urllib.request
        with urllib.request.urlopen("http://localhost:8080/api/portfolio/snapshot", timeout=6) as r:
            portfolio = json.loads(r.read())
    except Exception:
        pass

    # ── PortfolioConfig for limits ────────────────────────────────────────────
    max_open_positions = 5
    try:
        import urllib.request
        with urllib.request.urlopen("http://localhost:8080/api/portfolio/config", timeout=6) as r:
            cfg_data = json.loads(r.read())
            max_open_positions = int(cfg_data.get("max_open_positions", 5))
    except Exception:
        pass

    # ── analytics_engine core metrics ────────────────────────────────────────
    from analytics_engine import compute_trade_analytics
    pnl_list = [{"pnl": float(t.get("realized_pnl") or 0)} for t in closed_trades]
    starting_capital = float(portfolio.get("cash", 0)) + float(portfolio.get("invested_value", 0)) \
        if portfolio else 5000.0
    analytics = compute_trade_analytics(pnl_list, starting_capital)

    # ── 1–5: Win/loss/R-R/profit_factor/expectancy (from analytics_engine) ───
    win_rate_pct = analytics.get("win_rate", 0.0)
    loss_rate_pct = round(100.0 - win_rate_pct, 1) if closed_trades else 0.0
    avg_win = analytics.get("avg_win", 0.0)
    avg_loss = abs(analytics.get("avg_loss", 0.0))
    avg_rr = round(avg_win / avg_loss, 2) if avg_loss > 0 else None
    profit_factor = analytics.get("profit_factor", 0.0)
    expectancy = analytics.get("expectancy", 0.0)

    # ── 6: Max drawdown ───────────────────────────────────────────────────────
    max_drawdown_pct = analytics.get("max_drawdown_pct", 0.0)

    # ── 7 & 8: Largest win / loss ─────────────────────────────────────────────
    pnls = [float(t.get("realized_pnl") or 0) for t in closed_trades]
    largest_win = max(pnls) if pnls else 0.0
    largest_loss = min(pnls) if pnls else 0.0

    # ── 9: Daily risk % ───────────────────────────────────────────────────────
    total_equity = float(portfolio.get("total_equity", starting_capital)) or 1.0
    today_iso = target_date
    daily_pnl = sum(
        float(t.get("pnl", 0))
        for t in paper_trades
        if str(t.get("timestamp", "")).startswith(today_iso)
    )
    daily_risk_pct = round((-daily_pnl / total_equity * 100.0) if daily_pnl < 0 else 0.0, 4)

    # ── 10: Capital usage % ───────────────────────────────────────────────────
    invested = float(portfolio.get("invested_value", 0))
    capital_usage_pct = round(invested / total_equity * 100.0, 2) if total_equity > 0 else 0.0

    # ── 11: Position exposure % ───────────────────────────────────────────────
    position_exposure_pct = capital_usage_pct  # same as capital usage for paper trading

    # ── 12: Sector exposure map ───────────────────────────────────────────────
    sector_exposure: dict[str, float] = {}
    positions = portfolio.get("positions", [])
    for pos in positions:
        sym = str(pos.get("symbol") or "").upper()
        qty = float(pos.get("quantity") or 0)
        price = float(pos.get("current_price") or pos.get("avg_price") or 0)
        val = qty * price
        sector = _sector_of(sym)
        sector_exposure[sector] = round(sector_exposure.get(sector, 0) + (val / total_equity * 100), 2)

    # ── 13: Kill switch events ───────────────────────────────────────────────
    kill_switch_events = 0
    try:
        import phase11_risk as rk
        ks = rk.kill_switch_status()
        kill_switch_events = len(ks.get("events", []))
    except Exception:
        pass

    # ── 14: Circuit breaker events ────────────────────────────────────────────
    circuit_breaker_events = 0
    try:
        from phase20_circuit_breaker import get_audit_log
        log = get_audit_log(limit=200)
        circuit_breaker_events = sum(1 for e in log
                                     if e.get("event") == "CIRCUIT_BREAKER_TRIPPED")
    except Exception:
        pass

    # ── 15: Open position limit usage ─────────────────────────────────────────
    open_count = len([p for p in positions]) if positions else 0
    open_position_limit_usage = round(open_count / max_open_positions * 100.0, 1) \
        if max_open_positions > 0 else 0.0

    metrics = {
        "label": LABEL,
        "computed_at": _now_ist(),
        "date": target_date,
        "closed_trades": len(closed_trades),
        # 15 required metrics
        "win_rate_pct": win_rate_pct,
        "loss_rate_pct": loss_rate_pct,
        "avg_reward_risk_ratio": avg_rr,
        "profit_factor": profit_factor,
        "expectancy": expectancy,
        "max_drawdown_pct": max_drawdown_pct,
        "largest_win": round(largest_win, 2),
        "largest_loss": round(largest_loss, 2),
        "daily_risk_pct": daily_risk_pct,
        "capital_usage_pct": capital_usage_pct,
        "position_exposure_pct": position_exposure_pct,
        "sector_exposure": sector_exposure,
        "kill_switch_events": kill_switch_events,
        "circuit_breaker_events": circuit_breaker_events,
        "open_position_limit_usage_pct": open_position_limit_usage,
        # Supporting data
        "total_equity": round(total_equity, 2),
        "open_positions": open_count,
        "max_open_positions": max_open_positions,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "max_consecutive_wins": analytics.get("max_consecutive_wins", 0),
        "max_consecutive_losses": analytics.get("max_consecutive_losses", 0),
        "total_return_pct": analytics.get("total_return_pct", 0.0),
    }
    return metrics


def print_metrics(m: dict) -> None:
    print(f"\n{'=' * 60}")
    print(f"  Phase 4A Risk Metrics — {m['date']}")
    print(f"  {m['label']}")
    print(f"{'=' * 60}")
    print(f"  Closed trades:        {m['closed_trades']}")
    print(f"  Win rate:             {m['win_rate_pct']:.1f}%  |  Loss rate: {m['loss_rate_pct']:.1f}%")
    print(f"  Avg R/R:              {m['avg_reward_risk_ratio']}")
    print(f"  Profit factor:        {m['profit_factor']}")
    print(f"  Expectancy:           ₹{m['expectancy']:.2f} / trade")
    print(f"  Max drawdown:         {m['max_drawdown_pct']:.2f}%")
    print(f"  Largest win:          ₹{m['largest_win']:.2f}")
    print(f"  Largest loss:         ₹{m['largest_loss']:.2f}")
    print(f"  Daily risk:           {m['daily_risk_pct']:.4f}%")
    print(f"  Capital usage:        {m['capital_usage_pct']:.2f}%")
    print(f"  Position exposure:    {m['position_exposure_pct']:.2f}%")
    print(f"  Kill switch events:   {m['kill_switch_events']}")
    print(f"  Circuit breaker trips:{m['circuit_breaker_events']}")
    print(f"  Open pos limit usage: {m['open_position_limit_usage_pct']:.1f}%")
    print(f"  Sector exposure:      {m['sector_exposure']}")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Phase 4A risk metrics")
    parser.add_argument("--compute", action="store_true", help="Compute and print metrics")
    parser.add_argument("--date", type=str, default=None, help="Date YYYY-MM-DD")
    args = parser.parse_args()

    metrics = compute_risk_metrics(args.date)
    print_metrics(metrics)

    # Save JSON
    date_compact = metrics["date"].replace("-", "")
    out_path = os.path.join(_DOCS, f"risk_metrics_{date_compact}.json")
    with open(out_path, "w") as f:
        json.dump(metrics, f, indent=2, default=str)
    print(f"\n  Saved: {out_path}")
