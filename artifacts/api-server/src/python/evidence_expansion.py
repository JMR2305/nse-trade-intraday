"""
evidence_expansion.py — Phase 3A.5 Evidence Expansion (ANALYSIS ONLY).
v1.0

Analyses all completed out-of-sample trades across all walk-forward windows
to assess evidence quantity, quality, regime coverage, and statistical
robustness before any further model tuning or deployment decisions.

Key outputs:
  - Sample adequacy verdict: PASS / INCONCLUSIVE / FAIL / INSUFFICIENT_EVIDENCE
  - Regime coverage: trades by all 7 canonical regimes with under-coverage warnings
  - Trade distributions: by strategy, year, sector, holding period
  - Stability checks: median return, median PF, profitable-window %, worst/best,
    dispersion, concentration
  - Calibration comparison: raw vs calibrated Brier score, ECE, log loss
  - CSV exports: wf_evidence_report.csv, wf_evidence_trades.csv

ANALYSIS ONLY — never changes live decisions, thresholds, strategy rankings,
or paper-trading recommendations.  No lookahead (all analysis uses completed
out-of-sample trades only — each window's test data was never seen during
training, and calibration was re-fitted per window using only prior trades).

PAPER TRADING AND RESEARCH ONLY — no real orders are ever placed.
"""
from __future__ import annotations

import csv as _csv
import math
import os
import statistics
from collections import defaultdict
from datetime import datetime

SAFETY_MESSAGE = (
    "Out-of-sample historical performance does not guarantee future results. "
    "Paper trading and research only."
)

VALIDATION_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "validation_runs"
)

EVIDENCE_CSV_FILES = {
    "evidence_report": "wf_evidence_report.csv",
    "evidence_trades": "wf_evidence_trades.csv",
}

# ── Sample adequacy thresholds ────────────────────────────────────────────────
MIN_TRADES_INSUFFICIENT = 100     # below this: INSUFFICIENT_EVIDENCE
MIN_TRADES_PASS = 300             # preferred research target
MIN_WINDOWS_INSUFFICIENT = 4      # below this: INSUFFICIENT_EVIDENCE
MIN_WINDOWS_PASS = 8              # preferred for PASS
MIN_REGIMES_INCONCLUSIVE = 3      # minimum distinct regimes for any conclusion
MIN_REGIMES_PASS = 4              # for PASS verdict
MIN_PROFITABLE_WINDOWS_PCT = 50.0 # profitable-window threshold for PASS

# All 7 canonical regimes (same as classify_regime output)
ALL_REGIMES = [
    "Bullish", "Neutral-Bullish", "Neutral-Bearish", "Bearish",
    "Sideways", "High-Volatility", "Low-Volatility",
]
UNDERREPRESENTED_THRESHOLD = 10   # fewer than this in a regime → warning

TRADE_COLS = [
    "window", "variant", "symbol", "sector", "recommendation",
    "confidence", "raw_confidence", "calibrated_probability",
    "calibrated_confidence", "calibration_method", "calibration_version",
    "strategy_name", "entry_date", "entry_price", "quantity",
    "requested_quantity", "partial_fill", "gap_pct", "invested",
    "exit_date", "exit_price", "exit_reason", "holding_days",
    "gross_pnl", "net_pnl", "return_pct", "total_costs",
    "mae_pct", "mfe_pct", "intrabar_rule", "market_regime",
    "max_data_timestamp",
]


# ── Helpers ───────────────────────────────────────────────────────────────────

def _f(v, default: float = 0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _holding_bucket(days: float) -> str:
    d = int(days)
    if d <= 5:
        return "Short (1-5d)"
    if d <= 15:
        return "Medium (6-15d)"
    return "Long (16+d)"


def _by_group(
    trades: list[dict],
    key_fn,
    sort_by: str = "trades",
) -> list[dict]:
    """Aggregate trades into groups returning trades, net_pnl, win_rate, expectancy."""
    groups: dict[str, dict] = defaultdict(lambda: {
        "count": 0, "net_pnl": 0.0, "wins": 0, "returns": []
    })
    for t in trades:
        k = key_fn(t) or "Unknown"
        g = groups[k]
        g["count"] += 1
        pnl = _f(t.get("net_pnl"))
        g["net_pnl"] += pnl
        g["wins"] += 1 if pnl > 0 else 0
        g["returns"].append(_f(t.get("return_pct")))

    result = []
    for k, g in groups.items():
        n = g["count"]
        result.append({
            "group": k,
            "trades": n,
            "net_pnl": round(g["net_pnl"], 2),
            "win_rate": round(g["wins"] / n * 100.0, 1) if n else 0.0,
            "expectancy": round(g["net_pnl"] / n, 2) if n else 0.0,
            "median_return_pct": round(statistics.median(g["returns"]), 2)
                                 if g["returns"] else 0.0,
        })
    if sort_by == "group":
        result.sort(key=lambda x: x["group"])
    else:
        result.sort(key=lambda x: -x["trades"])
    return result


# ── Regime coverage ───────────────────────────────────────────────────────────

def _regime_coverage(trades: list[dict]) -> dict:
    counts: dict[str, int] = defaultdict(int)
    for t in trades:
        r = str(t.get("market_regime") or "Unknown").strip()
        counts[r] += 1

    n_total = len(trades)
    rows = []
    for regime in ALL_REGIMES:
        n = counts.get(regime, 0)
        rows.append({
            "regime": regime,
            "trades": n,
            "pct_of_total": round(n / n_total * 100.0, 1) if n_total else 0.0,
            "underrepresented": n < UNDERREPRESENTED_THRESHOLD,
        })
    # any extra regimes not in canonical list
    for r, n in counts.items():
        if r not in ALL_REGIMES:
            rows.append({
                "regime": r,
                "trades": n,
                "pct_of_total": round(n / n_total * 100.0, 1) if n_total else 0.0,
                "underrepresented": n < UNDERREPRESENTED_THRESHOLD,
            })

    regimes_covered = sum(1 for r in rows
                          if r["trades"] > 0 and r["regime"] in ALL_REGIMES)
    warnings = []
    for r in rows:
        if r["regime"] in ALL_REGIMES and r["underrepresented"]:
            warnings.append(
                f"Regime '{r['regime']}' has only {r['trades']} trade(s) — "
                "under-represented; conclusions may not generalise"
            )
    missing = [r for r in ALL_REGIMES if counts.get(r, 0) == 0]
    if missing:
        warnings.append(
            f"No trades in regime(s): {', '.join(missing)} — "
            "extend the date range to cover more market conditions"
        )

    return {
        "by_regime": rows,
        "regimes_covered": regimes_covered,
        "regimes_total_canonical": len(ALL_REGIMES),
        "warnings": warnings,
    }


# ── Stability checks ──────────────────────────────────────────────────────────

def _stability_checks(trades: list[dict], window_results: list[dict]) -> dict:
    win_metrics = []
    for w in window_results:
        if w.get("failed"):
            continue
        fm = w.get("full_metrics") or {}
        n = int(_f(fm.get("total_trades")))
        if n == 0:
            continue
        ret = _f(fm.get("total_return_pct"))
        pf = _f(fm.get("profit_factor"))
        win_metrics.append({
            "label": w.get("label", ""),
            "train_start": w.get("train_start", ""),
            "train_end": w.get("train_end", ""),
            "test_start": w.get("test_start", ""),
            "test_end": w.get("test_end", ""),
            "trades": n,
            "return_pct": ret,
            "profit_factor": pf,
            "net_pnl": _f(fm.get("net_profit")),
            "win_rate": _f(fm.get("win_rate")),
            "profitable": pf > 1.0,
        })

    if not win_metrics:
        return {
            "window_count": 0,
            "profitable_windows": 0,
            "profitable_windows_pct": 0.0,
            "median_return_pct": None,
            "median_profit_factor": None,
            "best_window": None,
            "worst_window": None,
            "return_dispersion": None,
            "windows": [],
        }

    returns = [w["return_pct"] for w in win_metrics]
    pfs = [w["profit_factor"] for w in win_metrics]
    profitable = [w for w in win_metrics if w["profitable"]]

    best = max(win_metrics, key=lambda w: w["return_pct"])
    worst = min(win_metrics, key=lambda w: w["return_pct"])
    dispersion = round(statistics.stdev(returns), 2) if len(returns) > 1 else 0.0

    return {
        "window_count": len(win_metrics),
        "profitable_windows": len(profitable),
        "profitable_windows_pct": round(len(profitable) / len(win_metrics) * 100.0, 1),
        "median_return_pct": round(statistics.median(returns), 2),
        "median_profit_factor": round(statistics.median(pfs), 3),
        "best_window": {
            "label": best["label"],
            "test_start": best["test_start"],
            "test_end": best["test_end"],
            "return_pct": best["return_pct"],
            "profit_factor": best["profit_factor"],
            "trades": best["trades"],
        },
        "worst_window": {
            "label": worst["label"],
            "test_start": worst["test_start"],
            "test_end": worst["test_end"],
            "return_pct": worst["return_pct"],
            "profit_factor": worst["profit_factor"],
            "trades": worst["trades"],
        },
        "return_dispersion": dispersion,
        "windows": win_metrics,
    }


# ── Calibration comparison ────────────────────────────────────────────────────

def _brier(preds: list[float], outcomes: list[int]) -> float:
    return statistics.mean((p - o) ** 2 for p, o in zip(preds, outcomes))


def _log_loss(preds: list[float], outcomes: list[int]) -> float:
    eps = 1e-7
    return -statistics.mean(
        o * math.log(max(p, eps)) + (1 - o) * math.log(max(1 - p, eps))
        for p, o in zip(preds, outcomes)
    )


def _ece(preds: list[float], outcomes: list[int], n_bins: int = 10) -> float:
    bins = [{"sp": 0.0, "so": 0.0, "n": 0} for _ in range(n_bins)]
    for p, o in zip(preds, outcomes):
        idx = min(int(p * n_bins), n_bins - 1)
        bins[idx]["sp"] += p
        bins[idx]["so"] += o
        bins[idx]["n"] += 1
    n_total = len(preds)
    return sum(
        (b["n"] / n_total) * abs(b["sp"] / b["n"] - b["so"] / b["n"])
        for b in bins if b["n"] > 0
    )


def _calibration_comparison(trades: list[dict]) -> dict:
    raw_preds, cal_preds, outcomes = [], [], []
    skipped = 0
    for t in trades:
        rc = t.get("raw_confidence")
        cp = t.get("calibrated_probability")
        if rc is None or rc == "" or cp is None or cp == "":
            skipped += 1
            continue
        try:
            raw_p = max(0.001, min(0.999, _f(rc) / 100.0))
            cal_p = max(0.001, min(0.999, _f(cp)))
            outcome = 1 if _f(t.get("net_pnl")) > 0 else 0
        except (ValueError, TypeError):
            skipped += 1
            continue
        raw_preds.append(raw_p)
        cal_preds.append(cal_p)
        outcomes.append(outcome)

    n = len(raw_preds)
    if n < 10:
        return {
            "available": False,
            "reason": (
                f"Only {n} trade(s) have both raw and calibrated confidence "
                "(need ≥10). Run with more windows/trades."
            ),
        }

    rb = round(_brier(raw_preds, outcomes), 4)
    cb = round(_brier(cal_preds, outcomes), 4)
    re = round(_ece(raw_preds, outcomes), 4)
    ce = round(_ece(cal_preds, outcomes), 4)
    rl = round(_log_loss(raw_preds, outcomes), 4)
    cl = round(_log_loss(cal_preds, outcomes), 4)

    return {
        "available": True,
        "n_trades": n,
        "skipped_trades": skipped,
        "raw_brier_score": rb,
        "calibrated_brier_score": cb,
        "brier_improvement": round(rb - cb, 4),
        "raw_ece": re,
        "calibrated_ece": ce,
        "ece_improvement": round(re - ce, 4),
        "raw_log_loss": rl,
        "calibrated_log_loss": cl,
        "log_loss_improvement": round(rl - cl, 4),
        "calibration_helps": cb < rb,
        "note": (
            "Lower Brier / ECE / log-loss is better. "
            "Positive improvement means calibration reduced error."
        ),
    }


# ── Concentration checks ──────────────────────────────────────────────────────

def _concentration_checks(trades: list[dict]) -> list[str]:
    flags = []
    if not trades:
        return flags

    n = len(trades)
    threshold = 0.50

    # Positive P&L pool
    pos_by_sym: dict[str, float] = defaultdict(float)
    pos_by_sec: dict[str, float] = defaultdict(float)
    pos_by_strat: dict[str, float] = defaultdict(float)
    for t in trades:
        pnl = _f(t.get("net_pnl"))
        if pnl <= 0:
            continue
        pos_by_sym[str(t.get("symbol") or "?")] += pnl
        pos_by_sec[str(t.get("sector") or "Unknown")] += pnl
        pos_by_strat[str(t.get("strategy_name") or "Unknown")] += pnl

    total_pos = sum(pos_by_sym.values())

    if total_pos > 0:
        for label, pool in [("Stock", pos_by_sym), ("Sector", pos_by_sec),
                             ("Strategy", pos_by_strat)]:
            for name, pnl in pool.items():
                frac = pnl / total_pos
                if frac > threshold:
                    flags.append(
                        f"{label} concentration: '{name}' contributes "
                        f"{frac * 100:.0f}% of total profitable P&L"
                    )

    # Month concentration (by trade count)
    month_counts: dict[str, int] = defaultdict(int)
    for t in trades:
        m = str(t.get("entry_date") or "")[:7]
        if m:
            month_counts[m] += 1
    for month, cnt in month_counts.items():
        if cnt / n > threshold:
            flags.append(
                f"Month concentration: {cnt}/{n} trades ({cnt/n*100:.0f}%) "
                f"entered in {month}"
            )

    # Small-sample: top-5 trades > 50% of total positive P&L
    all_pnl = sorted([_f(t.get("net_pnl")) for t in trades], reverse=True)
    top5 = sum(all_pnl[:5])
    total_pnl = sum(all_pnl)
    if total_pnl > 0 and top5 / total_pnl > threshold:
        flags.append(
            f"Small-sample risk: top 5 trades contribute "
            f"{top5/total_pnl*100:.0f}% of total P&L"
        )

    return flags


# ── Date coverage ─────────────────────────────────────────────────────────────

def _date_coverage(window_results: list[dict]) -> dict:
    active = [w for w in window_results if not w.get("failed")]
    starts = [w.get("test_start", "") for w in active if w.get("test_start")]
    ends = [w.get("test_end", "") for w in active if w.get("test_end")]
    if not starts or not ends:
        return {"earliest_test_date": None, "latest_test_date": None,
                "years_covered": None}
    earliest = min(starts)
    latest = max(ends)
    try:
        yrs = round(
            (datetime.strptime(latest, "%Y-%m-%d")
             - datetime.strptime(earliest, "%Y-%m-%d")).days / 365.25, 1)
    except ValueError:
        yrs = None
    return {
        "earliest_test_date": earliest,
        "latest_test_date": latest,
        "years_covered": yrs,
    }


# ── Sample adequacy verdict ───────────────────────────────────────────────────

def _sample_verdict(
    n_trades: int,
    n_windows: int,
    n_regimes: int,
    profitable_pct: float,
    expectancy: float,
) -> dict:
    criteria = [
        {
            "name": "Minimum trades for any evidence",
            "threshold": MIN_TRADES_INSUFFICIENT,
            "preferred": MIN_TRADES_PASS,
            "observed": n_trades,
            "passed": n_trades >= MIN_TRADES_INSUFFICIENT,
        },
        {
            "name": "Preferred trades (300 = research target)",
            "threshold": MIN_TRADES_PASS,
            "preferred": MIN_TRADES_PASS,
            "observed": n_trades,
            "passed": n_trades >= MIN_TRADES_PASS,
        },
        {
            "name": "Minimum windows for any evidence",
            "threshold": MIN_WINDOWS_INSUFFICIENT,
            "preferred": MIN_WINDOWS_PASS,
            "observed": n_windows,
            "passed": n_windows >= MIN_WINDOWS_INSUFFICIENT,
        },
        {
            "name": "Preferred windows (8+)",
            "threshold": MIN_WINDOWS_PASS,
            "preferred": MIN_WINDOWS_PASS,
            "observed": n_windows,
            "passed": n_windows >= MIN_WINDOWS_PASS,
        },
        {
            "name": "Market regime diversity (3+ canonical regimes)",
            "threshold": MIN_REGIMES_INCONCLUSIVE,
            "preferred": MIN_REGIMES_PASS,
            "observed": n_regimes,
            "passed": n_regimes >= MIN_REGIMES_INCONCLUSIVE,
        },
        {
            "name": "Profitable windows ≥ 50%",
            "threshold": MIN_PROFITABLE_WINDOWS_PCT,
            "preferred": MIN_PROFITABLE_WINDOWS_PCT,
            "observed": round(profitable_pct, 1),
            "passed": profitable_pct >= MIN_PROFITABLE_WINDOWS_PCT,
        },
        {
            "name": "Positive expectancy after costs (₹/trade)",
            "threshold": 0.0,
            "preferred": 0.0,
            "observed": round(expectancy, 2),
            "passed": expectancy > 0.0,
        },
    ]

    insufficient = (n_trades < MIN_TRADES_INSUFFICIENT
                    or n_windows < MIN_WINDOWS_INSUFFICIENT)
    if insufficient:
        verdict = "INSUFFICIENT_EVIDENCE"
        summary = (
            f"Only {n_trades} completed OOS trades across {n_windows} window(s). "
            f"Need ≥{MIN_TRADES_INSUFFICIENT} trades and "
            f"≥{MIN_WINDOWS_INSUFFICIENT} windows for any evidence assessment. "
            "Recommended: train_years=2, test_months=3, step_months=3 "
            "going back ≥5 years (targets 10-12 windows and 300+ trades)."
        )
    elif (n_trades >= MIN_TRADES_PASS and n_windows >= MIN_WINDOWS_PASS
          and profitable_pct >= MIN_PROFITABLE_WINDOWS_PCT
          and expectancy > 0.0 and n_regimes >= MIN_REGIMES_PASS):
        verdict = "PASS"
        summary = (
            f"{n_trades} OOS trades across {n_windows} windows covering "
            f"{n_regimes} market regimes. Positive expectancy (₹{expectancy:.0f}/trade), "
            f"{profitable_pct:.0f}% profitable windows. "
            "Evidence meets research quality threshold."
        )
    elif (n_trades >= MIN_TRADES_PASS
          and (profitable_pct < MIN_PROFITABLE_WINDOWS_PCT or expectancy <= 0.0)):
        parts = []
        if profitable_pct < MIN_PROFITABLE_WINDOWS_PCT:
            parts.append(f"only {profitable_pct:.0f}% profitable windows (need ≥50%)")
        if expectancy <= 0.0:
            parts.append(f"negative expectancy (₹{expectancy:.0f}/trade)")
        verdict = "FAIL"
        summary = (
            f"{n_trades} OOS trades, but: {'; '.join(parts)}. "
            "Evidence does not support a net positive-expectancy edge. "
            "Do not claim edge without positive expectancy after costs."
        )
    else:
        parts = []
        if n_trades < MIN_TRADES_PASS:
            parts.append(f"{n_trades}/{MIN_TRADES_PASS} preferred trades")
        if n_windows < MIN_WINDOWS_PASS:
            parts.append(f"{n_windows}/{MIN_WINDOWS_PASS} preferred windows")
        if n_regimes < MIN_REGIMES_PASS:
            parts.append(f"{n_regimes}/{MIN_REGIMES_PASS} regimes")
        verdict = "INCONCLUSIVE"
        summary = (
            "Insufficient evidence to reach a firm conclusion: "
            + ", ".join(parts)
            + ". Extend the validation range to collect more evidence."
        )

    return {"verdict": verdict, "summary": summary, "criteria": criteria}


# ── CSV exports ───────────────────────────────────────────────────────────────

def export_evidence_csvs(report: dict, trades: list[dict]) -> None:
    """Write wf_evidence_report.csv and wf_evidence_trades.csv."""
    os.makedirs(VALIDATION_DIR, exist_ok=True)

    # 1. Evidence report summary CSV
    with open(
        os.path.join(VALIDATION_DIR, EVIDENCE_CSV_FILES["evidence_report"]),
        "w", newline="",
    ) as f:
        w = _csv.writer(f)
        w.writerow(["section", "metric", "value"])
        v = report["verdict"]
        w.writerow(["verdict", "verdict", v["verdict"]])
        w.writerow(["verdict", "summary", v["summary"]])
        for c in v["criteria"]:
            w.writerow(["verdict_criterion", c["name"],
                        f"observed={c['observed']} threshold={c['threshold']} "
                        f"passed={c['passed']}"])
        cov = report["date_coverage"]
        for k, val in cov.items():
            w.writerow(["coverage", k, val])
        w.writerow(["summary", "total_oos_trades", report["n_trades"]])
        w.writerow(["summary", "total_windows", report["n_windows"]])
        w.writerow(["summary", "expectancy_per_trade_inr", report["expectancy_per_trade"]])
        for r in report["regime_coverage"]["by_regime"]:
            w.writerow(["regime", r["regime"],
                        f"trades={r['trades']} pct={r['pct_of_total']}% "
                        f"underrepresented={r['underrepresented']}"])
        for warn in report["regime_coverage"]["warnings"]:
            w.writerow(["regime_warning", "warning", warn])
        for dim_key, dim_label in [
            ("by_strategy", "strategy"), ("by_year", "year"),
            ("by_sector", "sector"), ("by_holding_period", "holding_period"),
        ]:
            for row in report.get(dim_key, []):
                w.writerow([dim_label, row["group"],
                            f"trades={row['trades']} net_pnl={row['net_pnl']} "
                            f"win_rate={row['win_rate']}% expectancy={row['expectancy']}"])
        s = report["stability"]
        for k in ["window_count", "profitable_windows", "profitable_windows_pct",
                   "median_return_pct", "median_profit_factor", "return_dispersion"]:
            w.writerow(["stability", k, s.get(k, "")])
        if s.get("best_window"):
            bw = s["best_window"]
            w.writerow(["stability", "best_window",
                        f"{bw['label']} ({bw['test_start']}-{bw['test_end']}) "
                        f"return={bw['return_pct']}%"])
        if s.get("worst_window"):
            ww = s["worst_window"]
            w.writerow(["stability", "worst_window",
                        f"{ww['label']} ({ww['test_start']}-{ww['test_end']}) "
                        f"return={ww['return_pct']}%"])
        cal = report["calibration_comparison"]
        if cal.get("available"):
            for k in ["n_trades", "raw_brier_score", "calibrated_brier_score",
                       "brier_improvement", "raw_ece", "calibrated_ece",
                       "ece_improvement", "raw_log_loss", "calibrated_log_loss",
                       "log_loss_improvement", "calibration_helps"]:
                w.writerow(["calibration_comparison", k, cal.get(k, "")])
        for flag in report["concentration_flags"]:
            w.writerow(["concentration_flag", "warning", flag])
        w.writerow(["safety", "message", report["safety"]])

    # 2. All evidence trades (same schema as wf_trades.csv + phase tag)
    with open(
        os.path.join(VALIDATION_DIR, EVIDENCE_CSV_FILES["evidence_trades"]),
        "w", newline="",
    ) as f:
        w = _csv.writer(f)
        w.writerow(["phase"] + TRADE_COLS)
        for t in trades:
            w.writerow(["3A.5"] + [t.get(c, "") for c in TRADE_COLS])


def export_evidence_csv_path(kind: str) -> str | None:
    fn = EVIDENCE_CSV_FILES.get(kind)
    if not fn:
        return None
    p = os.path.join(VALIDATION_DIR, fn)
    return p if os.path.exists(p) else None


# ── Main entry point ──────────────────────────────────────────────────────────

def build_evidence_report(
    all_trades_c: list[dict],
    window_results: list[dict],
    calibration_report: dict,
    cfg,
    progress_cb=None,
) -> dict:
    """
    Phase 3A.5 — Evidence Expansion main entry point.

    Parameters
    ----------
    all_trades_c      : All Variant C out-of-sample trades (list of dicts).
    window_results    : Walk-forward window result dicts (from the main run loop).
    calibration_report: Existing calibration metrics dict (for context only).
    cfg               : ValidationConfig instance.
    progress_cb       : Optional callable(str) for progress logging.

    Returns
    -------
    JSON-serialisable dict with Phase 3A.5 analysis.
    """
    def _log(msg: str) -> None:
        if progress_cb:
            progress_cb(f"[Phase 3A.5] {msg}")

    _log("Starting evidence expansion analysis")

    trades = list(all_trades_c)
    n_trades = len(trades)
    active_windows = [w for w in window_results if not w.get("failed")]
    n_windows = len(active_windows)

    _log(f"{n_trades} OOS trades | {n_windows} active windows")

    # Overall expectancy (net, after costs)
    total_pnl = sum(_f(t.get("net_pnl")) for t in trades)
    expectancy = total_pnl / n_trades if n_trades else 0.0

    _log("Computing regime coverage")
    regime_cov = _regime_coverage(trades)
    n_regimes = regime_cov["regimes_covered"]

    _log("Running stability checks")
    stability = _stability_checks(trades, window_results)
    profitable_pct = stability.get("profitable_windows_pct", 0.0)

    _log("Assessing sample adequacy")
    verdict = _sample_verdict(n_trades, n_windows, n_regimes, profitable_pct, expectancy)

    _log("Computing trade distributions")
    by_strategy = _by_group(trades,
                            lambda t: str(t.get("strategy_name") or "Unknown"))
    by_year = _by_group(trades,
                        lambda t: str(t.get("entry_date") or "")[:4] or "Unknown",
                        sort_by="group")
    by_sector = _by_group(trades,
                          lambda t: str(t.get("sector") or "Unknown"))
    by_holding = _by_group(trades,
                           lambda t: _holding_bucket(_f(t.get("holding_days", 0))))

    _log("Comparing raw vs calibrated confidence")
    cal_comparison = _calibration_comparison(trades)

    _log("Checking concentration")
    concentration_flags = _concentration_checks(trades)

    # Per-window regime map
    win_regime_map = []
    for w in active_windows:
        label = w.get("label", "")
        win_trades = [t for t in trades if str(t.get("window") or "") == label]
        regime_counts: dict[str, int] = defaultdict(int)
        for t in win_trades:
            regime_counts[str(t.get("market_regime") or "Unknown")] += 1
        dominant = max(regime_counts, key=regime_counts.__getitem__) \
                   if regime_counts else "Unknown"
        fm = w.get("full_metrics") or {}
        win_regime_map.append({
            "label": label,
            "test_start": w.get("test_start", ""),
            "test_end": w.get("test_end", ""),
            "trades": int(_f(fm.get("total_trades"))),
            "dominant_regime": dominant,
            "return_pct": _f(fm.get("total_return_pct")),
        })

    coverage = _date_coverage(window_results)

    report = {
        "phase": "3A.5",
        "phase_label": "Evidence Expansion",
        "n_trades": n_trades,
        "n_windows": n_windows,
        "date_coverage": coverage,
        "total_pnl": round(total_pnl, 2),
        "expectancy_per_trade": round(expectancy, 2),
        "verdict": verdict,
        "regime_coverage": regime_cov,
        "stability": stability,
        "by_strategy": by_strategy,
        "by_year": by_year,
        "by_sector": by_sector,
        "by_holding_period": by_holding,
        "window_regime_map": win_regime_map,
        "calibration_comparison": cal_comparison,
        "concentration_flags": concentration_flags,
        "recommended_config_for_pass": {
            "train_years": 2,
            "test_months": 3,
            "step_months": 3,
            "guidance": (
                "Use train_years=2, test_months=3, step_months=3 and set "
                "start_date ≈5 years ago to obtain 10-12 windows and ≥300 trades."
            ),
        },
        "safety": SAFETY_MESSAGE,
    }

    _log("Exporting evidence CSVs")
    export_evidence_csvs(report, trades)

    _log("Phase 3A.5 complete")
    return report
