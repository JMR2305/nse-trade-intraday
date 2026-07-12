"""
Phase 4 – MACD Cross Robustness Analysis (ANALYSIS ONLY)

Measures whether MACD Cross results are structurally sound or dependent on
lucky concentration.  Tests eight performance breakdowns and five stress
scenarios, then issues a conservative KEEP / RESTRICT / REJECT verdict.

No changes are made to the live pipeline (requirement 9).
"""

from __future__ import annotations

import math
from collections import defaultdict

from strategy_audit import audit_window_pass
from macd_optimizer import MACD_ID, STRATEGY_REGISTRY
from execution_simulator import CostModel

SAFETY_MSG = (
    "ANALYSIS ONLY — this robustness report has no effect on live paper-"
    "trading decisions. The MACD Cross strategy runs unchanged."
)

# ── Verdict thresholds (spec §Stability verdict) ─────────────────────────────
V_MIN_EXPECTANCY_PCT   = 0.0     # must be strictly positive after costs
V_MIN_PROFIT_FACTOR    = 1.10
V_MIN_WINDOW_PASS_RATE = 0.50    # fraction of WF windows with exp > 0
V_MAX_STOCK_CONC       = 0.35    # one stock ≤ 35% of total profit
V_MAX_SECTOR_CONC      = 0.35    # one sector ≤ 35% of total profit
V_MAX_TOP5_CONC        = 0.50    # top-5 trades ≤ 50% of total profit
V_MAX_DRAWDOWN_PCT     = 40.0    # max drawdown < 40%

# Minimum OOS trades in a regime before making a recommendation
REGIME_MIN_SAMPLE = 10

VERDICT_KEEP     = "KEEP"
VERDICT_RESTRICT = "RESTRICT"
VERDICT_REJECT   = "REJECT"

_f = lambda v: round(float(v), 6) if v is not None else 0.0


# ── Helpers ──────────────────────────────────────────────────────────────────

def _safe_div(a: float, b: float, default: float = 0.0) -> float:
    return a / b if b != 0 else default


def _group_key_volatility(snap: dict | None) -> str:
    if snap is None:
        return "Unknown"
    atr_pct = _f(snap.get("atr_pct", 0.0))
    if atr_pct < 1.5:
        return "Low (<1.5%)"
    if atr_pct < 3.0:
        return "Medium (1.5–3%)"
    return "High (>3%)"


def _group_key_adx(snap: dict | None) -> str:
    if snap is None:
        return "Unknown"
    adx = _f(snap.get("adx", 0.0))
    if adx < 20:
        return "Weak (<20)"
    if adx < 30:
        return "Moderate (20–30)"
    return "Strong (>30)"


def _group_key_holding(days: int) -> str:
    if days <= 3:
        return "Short (1–3 days)"
    if days <= 10:
        return "Medium (4–10 days)"
    return "Long (11+ days)"


def _group_key_month(trade: dict) -> str:
    return str(trade.get("exit_date", ""))[:7] or "Unknown"


def _metrics(trades: list[dict], capital: float = 5000.0) -> dict:
    """Trade-level aggregate metrics — no equity curve required.
    Uses return_pct (return as % of invested) as the primary metric so that
    expectancy_pct and net_return_pct are consistent with Phase 3 figures."""
    if not trades:
        return {"trades": 0, "net_return_pct": 0.0, "expectancy_pct": 0.0,
                "profit_factor": 0.0, "win_rate": 0.0, "sharpe_ratio": 0.0,
                "max_drawdown_pct": 0.0, "total_costs": 0.0}

    # Win/loss defined by return_pct sign (matches build_trade_record convention)
    rets = [_f(t.get("return_pct")) for t in trades]
    wins_idx = [i for i, r in enumerate(rets) if r > 0]
    loss_idx = [i for i, r in enumerate(rets) if r <= 0]
    gross_p_pct = sum(rets[i] for i in wins_idx)
    gross_l_pct = sum(rets[i] for i in loss_idx)   # negative

    # Rupee figures for cost and PF denominator
    wins_pnl = [_f(trades[i].get("net_pnl")) for i in wins_idx]
    loss_pnl = [_f(trades[i].get("net_pnl")) for i in loss_idx]
    gross_profit = sum(wins_pnl)
    gross_loss = sum(loss_pnl)
    total_costs = sum(_f(t.get("total_costs")) for t in trades)
    n = len(trades)

    win_rate = round(_safe_div(len(wins_idx), n) * 100, 1)
    pf = round(_safe_div(gross_profit, abs(gross_loss),
                         default=(999.0 if gross_profit > 0 else 0.0)), 2)

    # net_return_pct = sum of per-trade return_pct (consistent with Phase 2B scorecard)
    net_ret = round(sum(rets), 2)
    exp_pct = round(_safe_div(sum(rets), n), 3)

    avg_ret = _safe_div(sum(rets), n)
    if n > 1:
        std_ret = math.sqrt(sum((r - avg_ret) ** 2 for r in rets) / (n - 1))
    else:
        std_ret = 0.0
    sharpe = round(_safe_div(avg_ret, std_ret) * math.sqrt(n), 2) if std_ret > 0 else 0.0

    # Drawdown from sequential equity curve, clamped at ruin (equity floor = 0).
    # Clipping at 0 ensures drawdown ≤ 100% and models "stop trading when broke."
    sorted_trades = sorted(trades, key=lambda t: str(t.get("exit_date", "")))
    equity = capital
    peak_eq = capital
    max_dd_abs = 0.0
    for t in sorted_trades:
        equity = max(0.0, equity + _f(t.get("net_pnl")))
        if equity > peak_eq:
            peak_eq = equity
        dd = peak_eq - equity
        if dd > max_dd_abs:
            max_dd_abs = dd
    ref = max(capital, peak_eq)
    max_dd_pct = round(max_dd_abs / ref * 100.0, 2) if ref > 0 else 0.0

    return {
        "trades": n,
        "net_return_pct": net_ret,
        "expectancy_pct": exp_pct,
        "profit_factor": pf,
        "win_rate": win_rate,
        "sharpe_ratio": sharpe,
        "max_drawdown_pct": max_dd_pct,
        "total_costs": round(total_costs, 2),
    }


def _breakdown(trades: list[dict], key_fn, capital: float = 5000.0) -> list[dict]:
    """Aggregate metrics by group, sorted descending by net PnL."""
    groups: dict[str, list] = defaultdict(list)
    for t in trades:
        groups[key_fn(t)].append(t)
    rows = []
    total_profit = sum(_f(t.get("net_pnl")) for t in trades if _f(t.get("net_pnl")) > 0)
    for grp, grp_trades in sorted(groups.items()):
        m = _metrics(grp_trades, capital)
        grp_pnl = sum(_f(t.get("net_pnl")) for t in grp_trades if _f(t.get("net_pnl")) > 0)
        m["group"] = grp
        m["profit_contribution_pct"] = round(
            _safe_div(grp_pnl, total_profit) * 100, 1) if total_profit > 0 else 0.0
        rows.append(m)
    rows.sort(key=lambda r: r.get("profit_contribution_pct", 0), reverse=True)
    return rows


# ── Stress tests ─────────────────────────────────────────────────────────────

def _stress_table(base: dict, variant: dict, label: str, description: str,
                  trades_removed: int, removed_label: str) -> dict:
    """Format one stress-test row."""
    return {
        "label": label,
        "description": description,
        "trades_removed": trades_removed,
        "removed_what": removed_label,
        "trades": variant["trades"],
        "net_return_pct": variant["net_return_pct"],
        "expectancy_pct": variant["expectancy_pct"],
        "profit_factor": variant["profit_factor"],
        "win_rate": variant["win_rate"],
        "sharpe_ratio": variant["sharpe_ratio"],
        "max_drawdown_pct": variant["max_drawdown_pct"],
        "total_costs": variant["total_costs"],
        "vs_base_expectancy": round(
            variant["expectancy_pct"] - base["expectancy_pct"], 3),
        "vs_base_net_return": round(
            variant["net_return_pct"] - base["net_return_pct"], 2),
        "still_profitable": variant["expectancy_pct"] > 0,
    }


def _stress_leave_one_stock_out(trades: list[dict],
                                capital: float) -> list[dict]:
    """For each stock, compute metrics over all other trades."""
    stocks = sorted({t.get("symbol", "?") for t in trades})
    rows = []
    base = _metrics(trades, capital)
    for sym in stocks:
        rest = [t for t in trades if t.get("symbol") != sym]
        m = _metrics(rest, capital)
        sym_pnl = sum(_f(t.get("net_pnl")) for t in trades if t.get("symbol") == sym)
        rows.append(_stress_table(
            base, m,
            label=f"Remove {sym}",
            description=f"All trades except {sym}",
            trades_removed=len(trades) - len(rest),
            removed_label=sym,
        ) | {"removed_pnl": round(sym_pnl, 2)})
    rows.sort(key=lambda r: r.get("vs_base_expectancy", 0))
    return rows


def _stress_leave_one_sector_out(trades: list[dict],
                                  capital: float) -> list[dict]:
    sectors = sorted({str(t.get("sector", "Unknown")) for t in trades})
    rows = []
    base = _metrics(trades, capital)
    for sec in sectors:
        rest = [t for t in trades if str(t.get("sector", "Unknown")) != sec]
        m = _metrics(rest, capital)
        sec_pnl = sum(_f(t.get("net_pnl")) for t in trades
                      if str(t.get("sector", "Unknown")) == sec)
        rows.append(_stress_table(
            base, m,
            label=f"Remove {sec}",
            description=f"All trades except sector {sec}",
            trades_removed=len(trades) - len(rest),
            removed_label=sec,
        ) | {"removed_pnl": round(sec_pnl, 2)})
    rows.sort(key=lambda r: r.get("vs_base_expectancy", 0))
    return rows


def _stress_leave_one_month_out(trades: list[dict],
                                 capital: float) -> list[dict]:
    months = sorted({_group_key_month(t) for t in trades})
    rows = []
    base = _metrics(trades, capital)
    for month in months:
        if month == "Unknown":
            continue
        rest = [t for t in trades if _group_key_month(t) != month]
        m = _metrics(rest, capital)
        month_pnl = sum(_f(t.get("net_pnl")) for t in trades
                        if _group_key_month(t) == month)
        rows.append(_stress_table(
            base, m,
            label=f"Remove {month}",
            description=f"All trades except {month}",
            trades_removed=len(trades) - len(rest),
            removed_label=month,
        ) | {"removed_pnl": round(month_pnl, 2)})
    rows.sort(key=lambda r: r.get("vs_base_expectancy", 0))
    return rows


def _stress_top5_removed(trades: list[dict], capital: float) -> dict:
    """Remove the top-5 trades by net_pnl and measure the impact.
    Concentration share is expressed as % of GROSS profit (sum of winning
    trades) so the value is always ≤ 100% and consistent with
    _concentration_summary."""
    sorted_by_pnl = sorted(trades, key=lambda t: _f(t.get("net_pnl")), reverse=True)
    top5 = sorted_by_pnl[:5]
    rest = sorted_by_pnl[5:]
    base = _metrics(trades, capital)
    m = _metrics(rest, capital)
    top5_pnl = sum(_f(t.get("net_pnl")) for t in top5)
    gross_profit = sum(_f(t.get("net_pnl")) for t in trades
                       if _f(t.get("net_pnl")) > 0)
    top5_share = round(_safe_div(top5_pnl, gross_profit) * 100, 1) if gross_profit > 0 else 0.0
    return _stress_table(
        base, m,
        label="Top-5 trades removed",
        description="All trades except the 5 largest winners by net P&L",
        trades_removed=len(top5),
        removed_label=(", ".join(t.get("symbol", "?") + " " +
                                  str(t.get("exit_date", ""))[:10]
                                  for t in top5[:3]) + (
                           " ..." if len(top5) > 3 else "")),
    ) | {"top5_pnl": round(top5_pnl, 2), "top5_share_of_profit_pct": top5_share}


def _stress_winsorized(trades: list[dict], capital: float,
                       sigma: float = 2.0) -> dict:
    """Cap return_pct and net_pnl at mean ± sigma × std."""
    rets = [_f(t.get("return_pct")) for t in trades]
    if len(rets) < 4:
        return _stress_table(_metrics(trades, capital), _metrics(trades, capital),
                             "Winsorized returns", "No winsorization applied",
                             0, "N/A")
    avg = sum(rets) / len(rets)
    std = math.sqrt(sum((r - avg) ** 2 for r in rets) / (len(rets) - 1))
    lo, hi = avg - sigma * std, avg + sigma * std

    winsorized = []
    capped = 0
    for t in trades:
        r = _f(t.get("return_pct"))
        if r < lo or r > hi:
            r_cap = max(lo, min(hi, r))
            invested = _f(t.get("invested", capital))
            pnl_cap = r_cap / 100.0 * invested
            winsorized.append(dict(t, return_pct=r_cap, net_pnl=pnl_cap))
            capped += 1
        else:
            winsorized.append(t)

    base = _metrics(trades, capital)
    m = _metrics(winsorized, capital)
    return _stress_table(
        base, m,
        label=f"Winsorized returns (±{sigma:.0f}σ)",
        description=(f"Return outliers capped at mean ± {sigma:.0f} std dev "
                     f"({lo:.2f}% to {hi:.2f}%). {capped} trades affected."),
        trades_removed=0,
        removed_label=f"{capped} returns capped",
    ) | {"trades_capped": capped, "cap_range_pct": [round(lo, 2), round(hi, 2)]}


# ── Verdict ──────────────────────────────────────────────────────────────────

def _compute_verdict(base: dict, window_perf: list[dict],
                     by_stock: list[dict], by_sector: list[dict],
                     stress_top5: dict) -> dict:
    """Evaluate each stability criterion and issue a final verdict."""
    total_pnl = sum(_f(t.get("net_pnl")) for t in _ALL_TRADES_SENTINEL)  # patched by caller
    checks = []

    def _check(name: str, description: str, threshold: str,
                observed: str, passed: bool, critical: bool = False) -> None:
        checks.append({"name": name, "description": description,
                        "threshold": threshold, "observed": observed,
                        "passed": passed, "critical": critical})

    exp = base.get("expectancy_pct", 0.0)
    _check("Positive net expectancy",
           "Net expectancy per trade must be positive after all costs",
           "> 0%/trade",
           f"{exp:+.3f}%/trade",
           exp > V_MIN_EXPECTANCY_PCT, critical=True)

    pf = base.get("profit_factor", 0.0)
    _check("Profit factor ≥ 1.10",
           "Profit factor (gross profit / gross loss) must reach 1.10",
           "≥ 1.10",
           f"{pf:.2f}",
           pf >= V_MIN_PROFIT_FACTOR, critical=True)

    n_pos = sum(1 for w in window_perf if w.get("expectancy_pct", 0) > 0)
    n_win = len(window_perf)
    pass_rate = _safe_div(n_pos, n_win)
    _check("Positive in ≥50% of walk-forward windows",
           "More than half of all test windows must have positive expectancy",
           "≥ 50% of windows",
           f"{n_pos}/{n_win} windows ({pass_rate * 100:.0f}%)",
           pass_rate >= V_MIN_WINDOW_PASS_RATE)

    top_stock = max(by_stock, key=lambda r: r.get("profit_contribution_pct", 0),
                    default=None)
    stock_conc = (top_stock["profit_contribution_pct"] / 100
                  if top_stock else 0.0)
    _check("No single stock > 35% of total profit",
           "Profit must not depend on one stock",
           "≤ 35%",
           f"{top_stock['group'] if top_stock else '—'}: "
           f"{stock_conc * 100:.1f}%",
           stock_conc <= V_MAX_STOCK_CONC)

    top_sector = max(by_sector, key=lambda r: r.get("profit_contribution_pct", 0),
                     default=None)
    sector_conc = (top_sector["profit_contribution_pct"] / 100
                   if top_sector else 0.0)
    _check("No single sector > 35% of total profit",
           "Profit must not be dominated by one sector",
           "≤ 35%",
           f"{top_sector['group'] if top_sector else '—'}: "
           f"{sector_conc * 100:.1f}%",
           sector_conc <= V_MAX_SECTOR_CONC)

    top5_share = stress_top5.get("top5_share_of_profit_pct", 0.0)
    _check("Top-5 trades ≤ 50% of total profit",
           "A handful of lucky trades must not drive all profits",
           "≤ 50%",
           f"{top5_share:.1f}%",
           top5_share <= V_MAX_TOP5_CONC * 100)

    dd = base.get("max_drawdown_pct", 0.0)
    _check("Drawdown < 40%",
           "Maximum drawdown must stay below 40% of capital",
           "< 40%",
           f"{dd:.1f}%",
           dd < V_MAX_DRAWDOWN_PCT, critical=True)

    passed = [c for c in checks if c["passed"]]
    failed = [c for c in checks if not c["passed"]]
    n_crit_failed = sum(1 for c in failed if c.get("critical"))
    n_failed = len(failed)

    if n_crit_failed >= 2 or n_failed >= 4:
        verdict = VERDICT_REJECT
        rationale = (f"REJECT — {n_failed} check(s) failed including {n_crit_failed} "
                     f"critical. MACD Cross does not currently meet minimum "
                     f"robustness standards for continued paper trading.")
    elif n_crit_failed == 1 or n_failed >= 2:
        verdict = VERDICT_RESTRICT
        rationale = (f"RESTRICT — {n_failed} check(s) failed. MACD Cross shows some "
                     f"edge but has structural weaknesses that should be addressed "
                     f"before scaling up. Continue monitoring and apply the "
                     f"concentration reduction steps below.")
    else:
        verdict = VERDICT_KEEP
        rationale = (f"KEEP — {len(passed)}/{len(checks)} checks passed. MACD Cross "
                     f"demonstrates structurally sound out-of-sample performance. "
                     f"Continue paper trading while monitoring concentration metrics.")

    return {
        "verdict": verdict,
        "rationale": rationale,
        "checks": checks,
        "passed_count": len(passed),
        "failed_count": n_failed,
        "critical_failed_count": n_crit_failed,
        "passed": [c["name"] for c in passed],
        "failed": [c["name"] for c in failed],
    }


_ALL_TRADES_SENTINEL: list = []   # filled by run_macd_robustness before _compute_verdict


# ── Regime recommendations ──────────────────────────────────────────────────

def _regime_recommendations(by_regime: list[dict]) -> list[dict]:
    recs = []
    for row in by_regime:
        n = row.get("trades", 0)
        exp = row.get("expectancy_pct", 0.0)
        pf = row.get("profit_factor", 0.0)
        wr = row.get("win_rate", 0.0)
        if n < REGIME_MIN_SAMPLE:
            action = "INSUFFICIENT DATA"
            reason = (f"Only {n} OOS trades in this regime — "
                      f"need ≥{REGIME_MIN_SAMPLE} before enabling/disabling.")
        elif exp > 0 and pf >= 1.05:
            action = "ENABLE"
            reason = (f"Positive expectancy ({exp:+.3f}%/trade), "
                      f"PF {pf:.2f}, win rate {wr:.1f}% across {n} OOS trades.")
        elif exp <= 0:
            action = "DISABLE"
            reason = (f"Negative expectancy ({exp:+.3f}%/trade) across {n} OOS "
                      f"trades — not profitable in this regime after costs.")
        else:
            action = "MONITOR"
            reason = (f"Marginally positive expectancy ({exp:+.3f}%/trade) "
                      f"but PF {pf:.2f} is below 1.05 — watch closely.")
        recs.append({
            "regime": row["group"],
            "trades": n,
            "expectancy_pct": exp,
            "profit_factor": pf,
            "win_rate": wr,
            "max_drawdown_pct": row.get("max_drawdown_pct", 0.0),
            "action": action,
            "reason": reason,
        })
    return sorted(recs, key=lambda r: (
        0 if r["action"] == "ENABLE" else 1 if r["action"] == "MONITOR"
        else 2 if r["action"] == "DISABLE" else 3))


# ── Concentration summary ────────────────────────────────────────────────────

def _concentration_summary(trades: list[dict]) -> dict:
    total_pnl = sum(_f(t.get("net_pnl")) for t in trades if _f(t.get("net_pnl")) > 0)
    if total_pnl <= 0 or not trades:
        return {}
    sorted_pnl = sorted((_f(t.get("net_pnl")) for t in trades), reverse=True)
    top1 = sorted_pnl[0]
    top5 = sum(sorted_pnl[:5])
    top10 = sum(sorted_pnl[:10])
    by_sym: dict[str, float] = defaultdict(float)
    by_sec: dict[str, float] = defaultdict(float)
    by_mon: dict[str, float] = defaultdict(float)
    for t in trades:
        p = _f(t.get("net_pnl"))
        if p > 0:
            by_sym[str(t.get("symbol", "?"))] += p
            by_sec[str(t.get("sector", "Unknown"))] += p
            by_mon[_group_key_month(t)] += p
    top_sym = max(by_sym, key=by_sym.get, default="—")
    top_sec = max(by_sec, key=by_sec.get, default="—")
    top_mon = max(by_mon, key=by_mon.get, default="—")
    return {
        "total_profit": round(total_pnl, 2),
        "top1_trade_share_pct": round(top1 / total_pnl * 100, 1),
        "top5_trade_share_pct": round(top5 / total_pnl * 100, 1),
        "top10_trade_share_pct": round(top10 / total_pnl * 100, 1),
        "top_stock": top_sym,
        "top_stock_share_pct": round(by_sym.get(top_sym, 0) / total_pnl * 100, 1),
        "top_sector": top_sec,
        "top_sector_share_pct": round(by_sec.get(top_sec, 0) / total_pnl * 100, 1),
        "top_month": top_mon,
        "top_month_share_pct": round(by_mon.get(top_mon, 0) / total_pnl * 100, 1),
    }


# ── Main entry point ─────────────────────────────────────────────────────────

def run_macd_robustness(
    sym_rows,                           # dict[str, pd.DataFrame]
    windows: list[dict],
    regime_by_date: dict[str, str],
    test_dates_by_window: dict[str, list[str]],
    cfg,
    cost_model: CostModel,
    progress_cb=None,
) -> dict:
    """
    Phase 4: Robustness analysis for MACD Cross.
    Returns a JSON-safe report — never alters the live pipeline.
    """
    import pandas as pd
    strat = STRATEGY_REGISTRY[MACD_ID]
    sym_recs = {sym: df.to_dict("records") for sym, df in sym_rows.items()}

    def _span(t0, t1):
        out = {}
        for sym, df in sym_rows.items():
            dates = df["date"]
            idx = [i for i, d in enumerate(dates) if t0 <= d <= t1]
            if len(idx) >= 5:
                out[sym] = (idx[0], idx[-1])
        return out

    valid_windows = [w for w in windows if not w.get("failed")]
    all_oos_trades: list[dict] = []
    window_perf: list[dict] = []

    if progress_cb:
        progress_cb("Phase 4 MACD robustness — collecting OOS trades")

    for wi, window in enumerate(valid_windows):
        label = window.get("label", f"W{wi + 1}")
        if progress_cb:
            progress_cb(f"Phase 4 MACD robustness — window {label}")
        test_span = _span(pd.Timestamp(window["test_start"]),
                          pd.Timestamp(window["test_end"]))
        test_out = audit_window_pass(strat, sym_recs, test_span,
                                     regime_by_date, cost_model, cfg, label,
                                     collect_alternatives=False)
        win_trades = test_out["baseline"]
        all_oos_trades.extend(win_trades)
        wm = _metrics(win_trades, cfg.initial_capital)
        wm["label"] = label
        wm["test_start"] = window["test_start"]
        wm["test_end"] = window["test_end"]
        window_perf.append(wm)

    capital = cfg.initial_capital

    if not all_oos_trades:
        return {
            "safety": SAFETY_MSG,
            "verdict": {"verdict": VERDICT_REJECT,
                        "rationale": "No OOS trades found — cannot assess robustness.",
                        "checks": [], "passed_count": 0, "failed_count": 0,
                        "critical_failed_count": 0, "passed": [], "failed": []},
            "error": "No out-of-sample MACD Cross trades available for robustness analysis.",
        }

    # ── Baseline metrics (all OOS trades) ──────────────────────────────────
    base = _metrics(all_oos_trades, capital)

    # ── Breakdowns ─────────────────────────────────────────────────────────
    by_stock = _breakdown(all_oos_trades,
                          lambda t: str(t.get("symbol", "?")), capital)
    by_sector = _breakdown(all_oos_trades,
                           lambda t: str(t.get("sector", "Unknown")), capital)
    by_month = _breakdown(all_oos_trades, _group_key_month, capital)
    by_regime = _breakdown(all_oos_trades,
                           lambda t: str(t.get("market_regime", "Unknown")), capital)
    by_holding = _breakdown(all_oos_trades,
                            lambda t: _group_key_holding(
                                int(_f(t.get("holding_days")))), capital)
    by_vol = _breakdown(all_oos_trades,
                        lambda t: _group_key_volatility(t.get("snapshot")), capital)
    by_adx = _breakdown(all_oos_trades,
                        lambda t: _group_key_adx(t.get("snapshot")), capital)
    by_subtype = _breakdown(all_oos_trades,
                            lambda t: str(t.get("entry_subtype") or "Unknown"),
                            capital)

    # ── Stress tests ───────────────────────────────────────────────────────
    if progress_cb:
        progress_cb("Phase 4 MACD robustness — stress tests")

    stress_stock = _stress_leave_one_stock_out(all_oos_trades, capital)
    stress_sector = _stress_leave_one_sector_out(all_oos_trades, capital)
    stress_month = _stress_leave_one_month_out(all_oos_trades, capital)
    stress_top5 = _stress_top5_removed(all_oos_trades, capital)
    stress_winsor = _stress_winsorized(all_oos_trades, capital)

    # ── Concentration summary ───────────────────────────────────────────────
    concentration = _concentration_summary(all_oos_trades)

    # ── Verdict ────────────────────────────────────────────────────────────
    global _ALL_TRADES_SENTINEL
    _ALL_TRADES_SENTINEL = all_oos_trades
    verdict = _compute_verdict(base, window_perf, by_stock, by_sector, stress_top5)
    _ALL_TRADES_SENTINEL = []

    # ── Regime recommendations ─────────────────────────────────────────────
    regime_recs = _regime_recommendations(by_regime)

    # ── Improvement roadmap ────────────────────────────────────────────────
    roadmap = _build_roadmap(verdict, concentration, by_stock, by_sector, stress_top5)

    # ── Strip internal fields before serialization ─────────────────────────
    def _clean(t: dict) -> dict:
        return {k: v for k, v in t.items() if k not in ("snapshot", "_spec")}

    # ── Final report ───────────────────────────────────────────────────────
    return {
        "safety": SAFETY_MSG,
        "strategy_id": MACD_ID,
        "strategy_name": "MACD Cross",
        "total_oos_trades": len(all_oos_trades),
        "windows_evaluated": len(valid_windows),
        "baseline": base,
        "window_performance": window_perf,
        "breakdowns": {
            "by_stock": by_stock,
            "by_sector": by_sector,
            "by_month": by_month,
            "by_regime": by_regime,
            "by_holding_period": by_holding,
            "by_volatility_band": by_vol,
            "by_adx_band": by_adx,
            "by_entry_subtype": by_subtype,
        },
        "concentration": concentration,
        "stress_tests": {
            "leave_one_stock_out": stress_stock,
            "leave_one_sector_out": stress_sector,
            "leave_one_month_out": stress_month,
            "top5_trades_removed": stress_top5,
            "winsorized_returns": stress_winsor,
        },
        "verdict": verdict,
        "regime_recommendations": regime_recs,
        "roadmap": roadmap,
    }


def _build_roadmap(verdict: dict, concentration: dict,
                   by_stock: list[dict], by_sector: list[dict],
                   stress_top5: dict) -> list[dict]:
    """Prioritised list of concrete improvement suggestions."""
    items = []
    failed = {c["name"] for c in verdict["checks"] if not c["passed"]}

    if "No single stock > 35% of total profit" in failed:
        top = concentration.get("top_stock", "?")
        share = concentration.get("top_stock_share_pct", 0)
        items.append({
            "priority": 1,
            "area": "Concentration — stock",
            "action": f"Reduce allocation to {top} or add a position cap per stock "
                      f"(currently {share:.0f}% of total profit).",
            "target": "≤ 35% profit from any single stock",
        })

    if "No single sector > 35% of total profit" in failed:
        top = concentration.get("top_sector", "?")
        share = concentration.get("top_sector_share_pct", 0)
        items.append({
            "priority": 1,
            "area": "Concentration — sector",
            "action": f"Cap positions per sector to max 2 simultaneous trades. "
                      f"{top} currently drives {share:.0f}% of total profit.",
            "target": "≤ 35% profit from any single sector",
        })

    if "Top-5 trades ≤ 50% of total profit" in failed:
        share = stress_top5.get("top5_share_of_profit_pct", 0)
        items.append({
            "priority": 2,
            "area": "Outlier dependence",
            "action": f"Top-5 trades contribute {share:.0f}% of profit. "
                      f"Consider partial profit booking (half at +1.5×ATR) to "
                      f"lock in gains and reduce dependence on outlier winners.",
            "target": "≤ 50% of profit from any 5 trades",
        })

    if "Drawdown < 40%" in failed:
        items.append({
            "priority": 1,
            "area": "Drawdown",
            "action": "Apply the Phase 3 risk rules: volatility-adjusted sizing + "
                      "sector cap. Target: drawdown below 40%.",
            "target": "Max drawdown < 40%",
        })

    if "Profit factor ≥ 1.10" in failed:
        items.append({
            "priority": 2,
            "area": "Profit factor",
            "action": "Apply the Phase 3 entry filters (ADX ≥ 25) to reject weak "
                      "crossovers. Fewer but better-quality trades.",
            "target": "Profit factor ≥ 1.10",
        })

    if not items:
        items.append({
            "priority": 3,
            "area": "Maintenance",
            "action": "All robustness checks pass. Continue paper trading. "
                      "Re-run this analysis after every new walk-forward run to "
                      "ensure no drift in concentration or drawdown.",
            "target": "All checks green",
        })

    return sorted(items, key=lambda x: x["priority"])
