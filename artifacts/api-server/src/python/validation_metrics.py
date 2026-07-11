"""
validation_metrics.py — v2.4 Walk-Forward Validation metrics.

Pure, deterministic aggregation functions over lists of simulated trade
records (produced by execution_simulator.build_trade_record) and equity
curves. No network, no database, no randomness.

Provides:
  - compute_performance_metrics: ~25 headline metrics net of costs
  - compute_calibration: confidence-band calibration with flags
  - compute_recommendation_outcomes: per-recommendation forward analysis
    (uses forward returns supplied by the validator; WATCH/AVOID loss
    prevention included)
  - compute_stability: results sliced by year / regime / sector / strategy /
    confidence band / holding period / bull-bear, plus concentration flags
  - evaluate_verdict: configurable PASSED / PASSED WITH CAUTION / FAILED /
    INSUFFICIENT DATA

PAPER TRADING AND RESEARCH ONLY.
"""

from __future__ import annotations

import math
from typing import Any

TRADING_DAYS_PER_YEAR = 252

CONFIDENCE_BANDS: list[tuple[int, int]] = [(50, 59), (60, 69), (70, 79), (80, 89), (90, 95)]

CALIBRATION_MIN_SAMPLE = 20      # below this → "Insufficient sample"
CALIBRATION_GAP_TOLERANCE = 7.5  # |predicted - actual| within this → well calibrated


# ── Default verdict criteria (configurable, never hardcoded downstream) ──────

DEFAULT_VERDICT_CRITERIA: dict[str, float | int] = {
    "min_expectancy": 0.0,            # positive out-of-sample expectancy (₹/trade)
    "min_profit_factor": 1.15,        # after costs
    "max_drawdown_pct": 20.0,         # configured limit
    "require_full_beats_base": 1,     # full model must outperform base (net return)
    "max_single_stock_profit_share": 60.0,   # % of net profit from one stock
    "max_single_window_profit_share": 60.0,  # % of net profit from one test window
    "min_trades": 100,                # completed out-of-sample trades
    "min_windows": 2,                 # minimum test windows evaluated
}


# ── Small helpers ────────────────────────────────────────────────────────────

def _safe_div(a: float, b: float, default: float = 0.0) -> float:
    return a / b if b not in (0, 0.0) else default


def _std(values: list[float]) -> float:
    n = len(values)
    if n < 2:
        return 0.0
    mean = sum(values) / n
    return math.sqrt(sum((v - mean) ** 2 for v in values) / (n - 1))


def max_drawdown_from_curve(curve: list[float]) -> float:
    """Max peak-to-trough drawdown in % from an equity curve."""
    peak = -float("inf")
    max_dd = 0.0
    for v in curve:
        peak = max(peak, v)
        if peak > 0:
            dd = (peak - v) / peak * 100.0
            max_dd = max(max_dd, dd)
    return round(max_dd, 2)


def drawdown_series(curve: list[float]) -> list[float]:
    peak = -float("inf")
    out = []
    for v in curve:
        peak = max(peak, v)
        out.append(round((peak - v) / peak * 100.0, 2) if peak > 0 else 0.0)
    return out


def _consecutive(trades: list[dict], want_win: bool) -> int:
    best = cur = 0
    for t in trades:
        if bool(t.get("win")) == want_win:
            cur += 1
            best = max(best, cur)
        else:
            cur = 0
    return best


# ── 1. Performance metrics ───────────────────────────────────────────────────

def compute_performance_metrics(
    trades: list[dict],
    initial_capital: float,
    equity_curve: list[float] | None = None,
    trading_days: int = 0,
) -> dict:
    """
    ~25 headline performance metrics, net of all simulated costs.
    `trades` must be completed round-trips sorted by exit_date.
    `equity_curve` is the daily portfolio value curve (₹) if available.
    `trading_days` = number of trading days in the tested period (for
    annualization and exposure).
    """
    total = len(trades)
    wins = [t for t in trades if t.get("win")]
    losses = [t for t in trades if not t.get("win")]

    gross_profit = sum(float(t.get("net_pnl", 0.0)) for t in wins)
    gross_loss = sum(float(t.get("net_pnl", 0.0)) for t in losses)  # negative
    net_profit = gross_profit + gross_loss
    total_costs = sum(float(t.get("total_costs", 0.0)) for t in trades)

    win_rate = round(_safe_div(len(wins), total) * 100.0, 1)
    avg_win = _safe_div(gross_profit, len(wins))
    avg_loss = _safe_div(abs(gross_loss), len(losses))
    expectancy = _safe_div(net_profit, total)
    profit_factor = round(_safe_div(gross_profit, abs(gross_loss), default=(999.0 if gross_profit > 0 else 0.0)), 2)

    total_return_pct = round(_safe_div(net_profit, initial_capital) * 100.0, 2)
    years = trading_days / TRADING_DAYS_PER_YEAR if trading_days > 0 else 0.0
    if years > 0 and initial_capital > 0 and (1 + net_profit / initial_capital) > 0:
        annualized = ((1 + net_profit / initial_capital) ** (1 / years) - 1) * 100.0
    else:
        annualized = 0.0

    returns = [float(t.get("return_pct", 0.0)) for t in trades]
    avg_return = round(_safe_div(sum(returns), total), 2)
    std_ret = _std(returns)
    downside = [r for r in returns if r < 0]
    std_down = _std(downside) if len(downside) >= 2 else 0.0
    trades_per_year = _safe_div(total, years) if years > 0 else float(total)
    ann_factor = math.sqrt(trades_per_year) if trades_per_year > 0 else 0.0
    sharpe = round(_safe_div(avg_return, std_ret) * ann_factor, 2) if std_ret > 0 else 0.0
    sortino = round(_safe_div(avg_return, std_down) * ann_factor, 2) if std_down > 0 else 0.0

    curve = equity_curve or []
    max_dd = max_drawdown_from_curve(curve) if curve else 0.0
    max_dd_rupees = 0.0
    if curve:
        peak = -float("inf")
        for v in curve:
            peak = max(peak, v)
            max_dd_rupees = max(max_dd_rupees, peak - v)
    recovery_factor = round(_safe_div(net_profit, max_dd_rupees), 2) if max_dd_rupees > 0 else 0.0
    calmar = round(_safe_div(annualized, max_dd), 2) if max_dd > 0 else 0.0

    holding = [int(t.get("holding_days", 0)) for t in trades]
    avg_holding = round(_safe_div(sum(holding), total), 1)

    # Exposure: fraction of trading days with at least one open position.
    exposure_days = 0
    if trading_days > 0 and trades:
        # approximate: sum of holding days capped by the period length
        exposure_days = min(trading_days, sum(holding))
    exposure_pct = round(_safe_div(exposure_days, trading_days) * 100.0, 1) if trading_days > 0 else 0.0

    turnover_value = sum(float(t.get("invested", 0.0)) for t in trades)
    turnover_ratio = round(_safe_div(turnover_value, initial_capital), 2)

    largest_winner = round(max((float(t.get("net_pnl", 0.0)) for t in wins), default=0.0), 2)
    largest_loser = round(min((float(t.get("net_pnl", 0.0)) for t in losses), default=0.0), 2)

    return {
        "total_trades": total,
        "winning_trades": len(wins),
        "losing_trades": len(losses),
        "win_rate": win_rate,
        "gross_profit": round(gross_profit, 2),
        "gross_loss": round(gross_loss, 2),
        "net_profit": round(net_profit, 2),
        "total_return_pct": total_return_pct,
        "annualized_return_pct": round(annualized, 2),
        "avg_return_per_trade_pct": avg_return,
        "expectancy": round(expectancy, 2),
        "profit_factor": profit_factor,
        "sharpe_ratio": sharpe,
        "sortino_ratio": sortino,
        "max_drawdown_pct": max_dd,
        "recovery_factor": recovery_factor,
        "calmar_ratio": calmar,
        "avg_holding_days": avg_holding,
        "exposure_pct": exposure_pct,
        "turnover": turnover_ratio,
        "total_costs": round(total_costs, 2),
        "avg_win": round(avg_win, 2),
        "avg_loss": round(avg_loss, 2),
        "largest_winner": largest_winner,
        "largest_loser": largest_loser,
        "max_consecutive_wins": _consecutive(trades, True),
        "max_consecutive_losses": _consecutive(trades, False),
    }


# ── 2. Confidence calibration ────────────────────────────────────────────────

def compute_calibration(trades: list[dict]) -> list[dict]:
    """
    For each confidence band, compare the band's predicted success rate
    (midpoint of the band, i.e. what the confidence number claims) with the
    actual win rate of trades taken in that band.
    """
    out = []
    for lo, hi in CONFIDENCE_BANDS:
        band_trades = [
            t for t in trades
            if lo <= float(t.get("confidence", 0.0)) <= hi
        ]
        n = len(band_trades)
        predicted = (lo + hi) / 2.0
        wins = sum(1 for t in band_trades if t.get("win"))
        actual = round(_safe_div(wins, n) * 100.0, 1)
        gap = round(actual - predicted, 1)
        returns = [float(t.get("return_pct", 0.0)) for t in band_trades]
        gp = sum(float(t.get("net_pnl", 0.0)) for t in band_trades if t.get("win"))
        gl = sum(float(t.get("net_pnl", 0.0)) for t in band_trades if not t.get("win"))
        pf = round(_safe_div(gp, abs(gl), default=(999.0 if gp > 0 else 0.0)), 2)

        if n < CALIBRATION_MIN_SAMPLE:
            flag = "Insufficient sample"
        elif gap < -CALIBRATION_GAP_TOLERANCE:
            flag = "Overconfident"
        elif gap > CALIBRATION_GAP_TOLERANCE:
            flag = "Underconfident"
        else:
            flag = "Well calibrated"

        out.append({
            "band": f"{lo}-{hi}",
            "trades": n,
            "predicted_success_rate": predicted,
            "actual_success_rate": actual if n > 0 else 0.0,
            "calibration_gap": gap if n > 0 else 0.0,
            "avg_return_pct": round(_safe_div(sum(returns), n), 2),
            "profit_factor": pf if n > 0 else 0.0,
            "flag": flag,
        })
    return out


# ── 3. Recommendation outcome analysis ───────────────────────────────────────

REC_TYPES = ["STRONG BUY", "BUY", "WATCH", "AVOID", "EXIT"]


def compute_recommendation_outcomes(recommendations: list[dict]) -> list[dict]:
    """
    `recommendations` — one entry per issued recommendation (all types, not
    just executed trades), each carrying:
      recommendation, forward_returns {"1","3","5","10","20"} (% or None),
      mae_pct, mfe_pct  (over the 20-day forward window)
    WATCH / AVOID loss-prevention: a WATCH/AVOID call "prevented a loss"
    when the 5-day forward return was negative (the model kept you out).
    """
    out = []
    for rec_type in REC_TYPES:
        recs = [r for r in recommendations if str(r.get("recommendation", "")).upper() == rec_type]
        n = len(recs)
        row: dict[str, Any] = {"recommendation": rec_type, "issued": n}

        for horizon in ("1", "3", "5", "10", "20"):
            vals = [
                float(r["forward_returns"][horizon])
                for r in recs
                if r.get("forward_returns") and r["forward_returns"].get(horizon) is not None
            ]
            row[f"fwd_return_{horizon}d"] = round(_safe_div(sum(vals), len(vals)), 2) if vals else None

        f5 = [
            float(r["forward_returns"]["5"])
            for r in recs
            if r.get("forward_returns") and r["forward_returns"].get("5") is not None
        ]
        if rec_type in ("STRONG BUY", "BUY"):
            wins = sum(1 for v in f5 if v > 0)
            row["win_rate"] = round(_safe_div(wins, len(f5)) * 100.0, 1) if f5 else 0.0
            row["expectancy_pct"] = round(_safe_div(sum(f5), len(f5)), 2) if f5 else 0.0
            row["losses_prevented"] = None
            row["loss_prevention_rate"] = None
        else:
            # For WATCH/AVOID/EXIT the "win" is the stock NOT rising after
            # we declined it (or exited): forward return <= 0.
            correct = sum(1 for v in f5 if v <= 0)
            row["win_rate"] = round(_safe_div(correct, len(f5)) * 100.0, 1) if f5 else 0.0
            row["expectancy_pct"] = round(_safe_div(sum(f5), len(f5)), 2) if f5 else 0.0
            row["losses_prevented"] = sum(1 for v in f5 if v < 0)
            row["loss_prevention_rate"] = round(_safe_div(row["losses_prevented"], len(f5)) * 100.0, 1) if f5 else 0.0

        maes = [float(r.get("mae_pct", 0.0)) for r in recs if r.get("mae_pct") is not None]
        mfes = [float(r.get("mfe_pct", 0.0)) for r in recs if r.get("mfe_pct") is not None]
        row["avg_mae_pct"] = round(_safe_div(sum(maes), len(maes)), 2) if maes else 0.0
        row["avg_mfe_pct"] = round(_safe_div(sum(mfes), len(mfes)), 2) if mfes else 0.0
        out.append(row)
    return out


# ── 4. Stability analysis ────────────────────────────────────────────────────

def _group_metrics(trades: list[dict], key_fn) -> list[dict]:
    groups: dict[str, list[dict]] = {}
    for t in trades:
        k = key_fn(t) or "Unknown"
        groups.setdefault(str(k), []).append(t)
    out = []
    for k in sorted(groups):
        g = groups[k]
        net = sum(float(t.get("net_pnl", 0.0)) for t in g)
        wins = sum(1 for t in g if t.get("win"))
        out.append({
            "group": k,
            "trades": len(g),
            "net_pnl": round(net, 2),
            "win_rate": round(_safe_div(wins, len(g)) * 100.0, 1),
            "avg_return_pct": round(
                _safe_div(sum(float(t.get("return_pct", 0.0)) for t in g), len(g)), 2),
        })
    return out


def _holding_bucket(days: int) -> str:
    if days <= 3:
        return "0-3 days"
    if days <= 7:
        return "4-7 days"
    if days <= 15:
        return "8-15 days"
    return "16+ days"


def _confidence_band_of(conf: float) -> str:
    for lo, hi in CONFIDENCE_BANDS:
        if lo <= conf <= hi:
            return f"{lo}-{hi}"
    return "<50" if conf < 50 else ">95"


def compute_stability(trades: list[dict], concentration_threshold_pct: float = 50.0) -> dict:
    """
    Slice results by year / regime / sector / strategy / confidence band /
    holding period / bull-bear, and flag profit concentration.
    """
    by_year = _group_metrics(trades, lambda t: str(t.get("exit_date", ""))[:4])
    by_regime = _group_metrics(trades, lambda t: t.get("market_regime", "Unknown"))
    by_sector = _group_metrics(trades, lambda t: t.get("sector", "Unknown"))
    by_strategy = _group_metrics(trades, lambda t: t.get("strategy_name") or t.get("strategy_id", "Unknown"))
    by_band = _group_metrics(trades, lambda t: _confidence_band_of(float(t.get("confidence", 0.0))))
    by_holding = _group_metrics(trades, lambda t: _holding_bucket(int(t.get("holding_days", 0))))
    by_month = _group_metrics(trades, lambda t: str(t.get("exit_date", ""))[:7])
    by_stock = _group_metrics(trades, lambda t: t.get("symbol", "Unknown"))

    bull_bear = _group_metrics(
        trades,
        lambda t: ("Bullish period" if "bull" in str(t.get("market_regime", "")).lower()
                   else "Bearish period" if "bear" in str(t.get("market_regime", "")).lower()
                   else "Neutral period"),
    )

    net_profit = sum(float(t.get("net_pnl", 0.0)) for t in trades)
    flags: list[str] = []

    def _check_concentration(groups: list[dict], label: str) -> None:
        if net_profit <= 0 or not groups:
            return
        top = max(groups, key=lambda g: g["net_pnl"])
        if top["net_pnl"] > 0:
            share = top["net_pnl"] / net_profit * 100.0
            if share > concentration_threshold_pct:
                flags.append(
                    f"{share:.0f}% of net profit came from one {label}: {top['group']}"
                )

    _check_concentration(by_stock, "stock")
    _check_concentration(by_sector, "sector")
    _check_concentration(by_month, "month")
    _check_concentration(by_strategy, "strategy")

    # Small number of trades driving profits
    if net_profit > 0 and trades:
        sorted_pnl = sorted((float(t.get("net_pnl", 0.0)) for t in trades), reverse=True)
        top5 = sum(sorted_pnl[:5])
        if len(trades) > 10 and top5 / net_profit * 100.0 > 80.0:
            flags.append(
                f"Top 5 trades account for {top5 / net_profit * 100.0:.0f}% of net profit "
                f"— results depend on a small number of trades"
            )

    return {
        "by_year": by_year,
        "by_regime": by_regime,
        "by_sector": by_sector,
        "by_strategy": by_strategy,
        "by_confidence_band": by_band,
        "by_holding_period": by_holding,
        "by_month": by_month,
        "by_stock": by_stock,
        "bull_bear": bull_bear,
        "concentration_flags": flags,
    }


# ── 5. Verdict ───────────────────────────────────────────────────────────────

def evaluate_verdict(
    full_metrics: dict,
    base_metrics: dict,
    stability: dict,
    window_results: list[dict],
    criteria: dict | None = None,
) -> dict:
    """
    Configurable verdict. Every criterion is evaluated and reported with its
    threshold, observed value and pass/fail so nothing is hidden.
    """
    crit = dict(DEFAULT_VERDICT_CRITERIA)
    if criteria:
        for k, v in criteria.items():
            if k in crit and v is not None:
                crit[k] = v

    total_trades = int(full_metrics.get("total_trades", 0))
    n_windows = len(window_results)

    checks: list[dict] = []

    def _add(name: str, observed, threshold, passed: bool, direction: str) -> None:
        checks.append({
            "name": name, "observed": observed, "threshold": threshold,
            "direction": direction, "passed": bool(passed),
        })

    if total_trades < int(crit["min_trades"]) or n_windows < int(crit["min_windows"]):
        _add("Completed out-of-sample trades", total_trades, int(crit["min_trades"]),
             total_trades >= int(crit["min_trades"]), ">=")
        _add("Test windows evaluated", n_windows, int(crit["min_windows"]),
             n_windows >= int(crit["min_windows"]), ">=")
        return {
            "verdict": "INSUFFICIENT DATA",
            "criteria": crit,
            "checks": checks,
            "summary": (
                f"Only {total_trades} completed out-of-sample trades across {n_windows} "
                f"test window(s) — at least {int(crit['min_trades'])} trades and "
                f"{int(crit['min_windows'])} windows are required for a reliable verdict."
            ),
        }

    _add("Completed out-of-sample trades", total_trades, int(crit["min_trades"]), True, ">=")
    _add("Test windows evaluated", n_windows, int(crit["min_windows"]), True, ">=")

    exp = float(full_metrics.get("expectancy", 0.0))
    _add("Out-of-sample expectancy (₹/trade)", exp, float(crit["min_expectancy"]),
         exp > float(crit["min_expectancy"]), ">")

    pf = float(full_metrics.get("profit_factor", 0.0))
    _add("Profit factor after costs", pf, float(crit["min_profit_factor"]),
         pf > float(crit["min_profit_factor"]), ">")

    dd = float(full_metrics.get("max_drawdown_pct", 0.0))
    _add("Maximum drawdown (%)", dd, float(crit["max_drawdown_pct"]),
         dd <= float(crit["max_drawdown_pct"]), "<=")

    full_ret = float(full_metrics.get("total_return_pct", 0.0))
    base_ret = float(base_metrics.get("total_return_pct", 0.0))
    beats = full_ret > base_ret
    if int(crit["require_full_beats_base"]):
        _add("Full model beats base model (net return %)",
             round(full_ret - base_ret, 2), 0.0, beats, ">")

    conc_flags = list(stability.get("concentration_flags", []))
    _add("No excessive profit concentration", len(conc_flags), 0, len(conc_flags) == 0, "==")

    # Window robustness: share of profitable windows
    profitable_windows = sum(
        1 for w in window_results
        if float(w.get("full_metrics", {}).get("net_profit", 0.0)) > 0
    )
    window_share = _safe_div(profitable_windows, n_windows) * 100.0
    _add("Profitable test windows (%)", round(window_share, 1), 50.0,
         window_share >= 50.0, ">=")

    hard_fails = [c for c in checks if not c["passed"] and c["name"] in (
        "Out-of-sample expectancy (₹/trade)",
        "Profit factor after costs",
        "Maximum drawdown (%)",
    )]
    soft_fails = [c for c in checks if not c["passed"] and c not in hard_fails]

    if hard_fails:
        verdict = "FAILED"
        summary = "Failed core requirement(s): " + "; ".join(c["name"] for c in hard_fails) + "."
    elif soft_fails:
        verdict = "PASSED WITH CAUTION"
        summary = ("Core requirements met, but with caution: "
                   + "; ".join(c["name"] for c in soft_fails) + ".")
        if conc_flags:
            summary += " " + " ".join(conc_flags)
    else:
        verdict = "PASSED"
        summary = "All configured requirements met on unseen out-of-sample data."

    return {"verdict": verdict, "criteria": crit, "checks": checks, "summary": summary}
