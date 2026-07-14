"""
Phase 4.3 — Comprehensive Experiment Research Report Engine.

RESEARCH ONLY. This module reads stored experiment outputs (status.json,
config.json, wf_result.json, wf_trades.csv, research_ledger.csv,
analysis.json) and produces a deterministic, rule-based research report.

It NEVER modifies experiment results, live/paper trading logic, strategy
selection, or walk-forward methodology. All analysis uses only data that was
stored during the simulation (no lookahead beyond stored forward returns,
which were themselves computed inside valid window boundaries).

Persistence (file-based — this project has no SQL database):
  experiments/<id>/reports/report_v<N>.json   — full report versions
  experiments/<id>/reports/index.json         — version index + status
Idempotent: if the source result hash is unchanged and the latest report
completed, generation is skipped unless force=True. Old versions are kept.
"""

import hashlib
import json
import math
import os
import time
from datetime import datetime, timezone

import pandas as pd

DISCLAIMER = ("Research only — out-of-sample historical performance does not "
              "guarantee future results. This report does not affect live or "
              "paper-trading strategy selection.")

REPORT_SCHEMA_VERSION = 1

SAMPLE_LABELS = [(0, 9, "VERY LOW"), (10, 24, "LOW"), (25, 49, "LIMITED"),
                 (50, 99, "MODERATE"), (100, 10 ** 9, "STRONGER")]


# ── generic helpers ──────────────────────────────────────────────────────────

def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def _sample_label(n):
    for lo, hi, lab in SAMPLE_LABELS:
        if lo <= n <= hi:
            return lab
    return "VERY LOW"


def _num(x):
    """Return a JSON-safe number or None (rendered as N/A downstream)."""
    if x is None:
        return None
    try:
        f = float(x)
    except (TypeError, ValueError):
        return None
    if math.isnan(f) or math.isinf(f):
        return None
    return round(f, 4)


def _div(a, b):
    try:
        a = float(a); b = float(b)
    except (TypeError, ValueError):
        return None
    if b == 0 or math.isnan(b):
        return None
    return a / b


def _pf(pnls):
    wins = sum(p for p in pnls if p > 0)
    losses = -sum(p for p in pnls if p < 0)
    if losses <= 0:
        return None if wins <= 0 else None  # undefined without losses
    return wins / losses


def _breakdown(df, label):
    """Standard stats block for a group of trades (net-of-cost)."""
    n = len(df)
    if n == 0:
        return None
    pnls = df["net_pnl"].tolist()
    rets = df["return_pct"].tolist()
    wins = int((df["net_pnl"] > 0).sum())
    return {
        "group": label,
        "trades": n,
        "wins": wins,
        "losses": n - wins,
        "win_rate": _num(100.0 * wins / n),
        "gross_pnl": _num(df["gross_pnl"].sum()) if "gross_pnl" in df.columns else None,
        "net_pnl": _num(sum(pnls)),
        "avg_return_pct": _num(sum(rets) / n),
        "median_return_pct": _num(float(pd.Series(rets).median())),
        "expectancy_rs": _num(sum(pnls) / n),
        "profit_factor": _num(_pf(pnls)),
        "avg_holding_days": _num(df["holding_days"].mean()) if "holding_days" in df.columns else None,
        "total_costs": _num(df["total_costs"].sum()) if "total_costs" in df.columns else None,
        "sample_label": _sample_label(n),
    }


def _by(df, key, order=None):
    if key not in df.columns or df.empty:
        return []
    rows = []
    for g, sub in df.groupby(key, dropna=False, sort=True):
        b = _breakdown(sub, str(g))
        if b:
            rows.append(b)
    if order:
        pos = {v: i for i, v in enumerate(order)}
        rows.sort(key=lambda r: pos.get(r["group"], 999))
    else:
        rows.sort(key=lambda r: (-r["trades"], r["group"]))
    return rows


def _band(series, edges, labels):
    return pd.cut(series, bins=edges, labels=labels, include_lowest=True).astype(str)


# ── loading ──────────────────────────────────────────────────────────────────

def _load(exp_dir):
    def j(name):
        p = os.path.join(exp_dir, name)
        if os.path.exists(p):
            try:
                with open(p) as f:
                    return json.load(f)
            except Exception:
                return None
        return None

    def c(name):
        p = os.path.join(exp_dir, name)
        if os.path.exists(p):
            try:
                return pd.read_csv(p)
            except Exception:
                return pd.DataFrame()
        return pd.DataFrame()

    status = j("status.json") or {}
    result = j("wf_result.json") or {}
    config = j("config.json") or {}
    analysis = j("analysis.json")
    trades = c("wf_trades.csv")
    ledger = c("research_ledger.csv")
    return status, config, result, analysis, trades, ledger


def _result_hash(exp_dir):
    """Hash of the experiment's stored result artifacts (identity of source)."""
    h = hashlib.md5()
    for name in ("wf_result.json", "wf_trades.csv", "status.json"):
        p = os.path.join(exp_dir, name)
        if os.path.exists(p):
            st = os.stat(p)
            h.update(name.encode())
            h.update(str(st.st_size).encode())
            if name == "status.json":
                try:
                    with open(p) as f:
                        s = json.load(f)
                    h.update(json.dumps(s.get("metrics"), sort_keys=True).encode())
                    h.update(str(s.get("completed_at")).encode())
                except Exception:
                    pass
            else:
                h.update(str(int(st.st_mtime)).encode())
    return h.hexdigest()[:16]


def _variant_c(trades):
    if trades.empty:
        return trades
    df = trades[trades["variant"] == "C"].copy() if "variant" in trades.columns else trades.copy()
    before = len(df)
    keycols = [k for k in ("window", "symbol", "entry_date", "exit_date") if k in df.columns]
    if keycols:
        df = df.drop_duplicates(subset=keycols)
    df.attrs["duplicates_removed"] = before - len(df)
    return df


# ── sections ─────────────────────────────────────────────────────────────────

def _sec_executive(status, config, result, trades):
    m = status.get("metrics") or {}
    cfg = result.get("config") or config or {}
    windows = result.get("windows") or []
    n = int(m.get("total_trades") or len(trades))
    exp_rs = m.get("expectancy")
    pf = m.get("profit_factor")
    verdict = status.get("verdict") or "UNKNOWN"
    reasons = []
    if n > 0:
        if exp_rs is not None and exp_rs < 0:
            reasons.append(f"negative net expectancy of Rs {exp_rs:.2f} per trade after costs")
        if pf is not None and pf < 1:
            reasons.append(f"profit factor of {pf:.2f} (below 1)")
    ev = (m.get("ev_verdict") or "")
    if "INSUFFICIENT" in str(ev).upper() or "INSUFFICIENT" in str(verdict).upper():
        reasons.append("the result did not meet the minimum evidence requirement")
    if not reasons:
        reasons.append("see performance and verdict sections for the full breakdown")
    explanation = (f"The experiment produced {n} out-of-sample trades across "
                   f"{len(windows)} test window(s). "
                   + ("Key findings: " + "; ".join(reasons) + ". ")
                   + f"Final research verdict: {verdict}. "
                     "No live or paper-trading behavior is affected by this report.")
    return {
        "experiment_name": status.get("name"),
        "template": status.get("template_id"),
        "template_family": status.get("template_family"),
        "date_range": {"start": cfg.get("start_date"), "end": cfg.get("end_date")},
        "train_years": cfg.get("train_years"),
        "test_months": cfg.get("test_months"),
        "step_months": cfg.get("step_months"),
        "windows": len(windows),
        "oos_trades": n,
        "net_return_pct": _num(m.get("total_return_pct")),
        "net_pnl": _num(m.get("net_pnl")),
        "profit_factor": _num(pf),
        "expectancy_rs": _num(exp_rs),
        "win_rate": _num(m.get("win_rate")),
        "sharpe": _num(m.get("sharpe")),
        "max_drawdown_pct": _num(m.get("max_drawdown_pct")),
        "total_costs": _num((result.get("cost_breakdown") or {}).get("total")),
        "evidence_verdict": m.get("ev_verdict"),
        "overfitting_flags": status.get("overfitting_flags") or [],
        "final_verdict": verdict,
        "score": _num(status.get("score")),
        "explanation": explanation,
    }


def _sec_performance(status, result, trades):
    o = (result.get("overall") or {}).get("full_metrics") or {}
    cb = result.get("cost_breakdown") or {}
    bm = result.get("benchmarks") or {}
    windows = result.get("windows") or []
    wrows = []
    for w in windows:
        fm = w.get("full_metrics") or {}
        wrows.append({"window": w.get("label") or w.get("window"),
                      "trades": fm.get("total_trades"),
                      "net_return_pct": _num(fm.get("total_return_pct")),
                      "profit_factor": _num(fm.get("profit_factor")),
                      "win_rate": _num(fm.get("win_rate")),
                      "max_drawdown_pct": _num(fm.get("max_drawdown_pct"))})
    valid = [w for w in wrows if (w["trades"] or 0) > 0]
    profitable = [w for w in valid if (w["net_return_pct"] or 0) > 0]
    best_w = max(valid, key=lambda w: w["net_return_pct"] or 0) if valid else None
    worst_w = min(valid, key=lambda w: w["net_return_pct"] or 0) if valid else None

    monthly = []
    if not trades.empty and "exit_date" in trades.columns:
        t = trades.copy()
        t["month"] = t["exit_date"].astype(str).str[:7]
        for g, sub in t.groupby("month"):
            monthly.append({"month": g, "trades": len(sub),
                            "net_pnl": _num(sub["net_pnl"].sum())})
    best_m = max(monthly, key=lambda x: x["net_pnl"] or 0) if monthly else None
    worst_m = min(monthly, key=lambda x: x["net_pnl"] or 0) if monthly else None
    wins = trades[trades["net_pnl"] > 0] if not trades.empty else pd.DataFrame()
    losses = trades[trades["net_pnl"] <= 0] if not trades.empty else pd.DataFrame()
    gross_profit = o.get("gross_profit")
    return {
        "gross_pnl": _num(cb.get("gross_pnl")),
        "net_pnl": _num(cb.get("net_pnl")),
        "gross_return_note": "Gross figures are before configured transaction costs.",
        "net_return_pct": _num(o.get("total_return_pct")),
        "annualized_return_pct": _num(o.get("annualized_return_pct")),
        "total_costs": _num(cb.get("total")),
        "cost_drag_pct_of_gross_profit": _num(_div(100.0 * (cb.get("total") or 0), gross_profit)) if gross_profit else None,
        "profit_factor": _num(o.get("profit_factor")),
        "expectancy_rs": _num(o.get("expectancy")),
        "win_rate": _num(o.get("win_rate")),
        "avg_win": _num(o.get("avg_win")),
        "avg_loss": _num(o.get("avg_loss")),
        "median_win": _num(wins["net_pnl"].median()) if len(wins) else None,
        "median_loss": _num(losses["net_pnl"].median()) if len(losses) else None,
        "payoff_ratio": _num(_div(o.get("avg_win"), abs(o.get("avg_loss")) if o.get("avg_loss") else None)),
        "sharpe": _num(o.get("sharpe_ratio")),
        "sortino": _num(o.get("sortino_ratio")),
        "calmar": _num(o.get("calmar_ratio")),
        "recovery_factor": _num(o.get("recovery_factor")),
        "turnover": _num(o.get("turnover")),
        "exposure_pct": _num(o.get("exposure_pct")),
        "avg_holding_days": _num(o.get("avg_holding_days")),
        "median_holding_days": _num(trades["holding_days"].median()) if not trades.empty else None,
        "max_consecutive_wins": o.get("max_consecutive_wins"),
        "max_consecutive_losses": o.get("max_consecutive_losses"),
        "best_month": best_m, "worst_month": worst_m,
        "best_window": best_w, "worst_window": worst_w,
        "pct_profitable_windows": _num(_div(100.0 * len(profitable), len(valid))) if valid else None,
        "windows": wrows,
        "benchmarks": {
            "strategy_net_return_pct": _num(bm.get("full_model_pct")),
            "nifty_buy_hold_pct": _num(bm.get("nifty_buy_hold_pct")),
            "equal_weight_universe_pct": _num(bm.get("equal_weight_pct")),
            "cash_pct": _num(bm.get("cash_pct")),
            "base_model_pct": _num(((result.get("overall") or {}).get("base_metrics") or {}).get("total_return_pct")),
            "note": bm.get("note"),
        },
    }


def _drawdown_episodes(eq):
    """Episodes from stored full-model equity curve (no recomputation of trades)."""
    episodes = []
    peak = None; peak_date = None; trough = None; trough_date = None; in_dd = False
    for pt in eq:
        v = pt.get("full_model"); d = pt.get("date")
        if v is None:
            continue
        if peak is None or v >= peak:
            if in_dd and peak and trough is not None:
                episodes.append({"start_date": peak_date, "trough_date": trough_date,
                                 "recovery_date": d,
                                 "depth_pct": _num(100.0 * (peak - trough) / peak),
                                 "duration_days": None})
            peak, peak_date, in_dd, trough = v, d, False, None
        else:
            if not in_dd:
                in_dd, trough, trough_date = True, v, d
            elif v < trough:
                trough, trough_date = v, d
    if in_dd and peak and trough is not None:
        episodes.append({"start_date": peak_date, "trough_date": trough_date,
                         "recovery_date": None,
                         "depth_pct": _num(100.0 * (peak - trough) / peak),
                         "duration_days": None})
    for e in episodes:
        try:
            end = e["recovery_date"] or e["trough_date"]
            e["duration_days"] = (pd.Timestamp(end) - pd.Timestamp(e["start_date"])).days
        except Exception:
            pass
    episodes.sort(key=lambda e: -(e["depth_pct"] or 0))
    return episodes


def _sec_risk(result, trades):
    o = (result.get("overall") or {}).get("full_metrics") or {}
    n = len(trades)
    rets = trades["return_pct"] if n else pd.Series(dtype=float)
    pnls = trades["net_pnl"] if n else pd.Series(dtype=float)
    neg = rets[rets < 0]
    downside_dev = _num(neg.std()) if len(neg) > 1 else None
    total_profit = pnls[pnls > 0].sum() if n else 0
    total_loss = -pnls[pnls < 0].sum() if n else 0
    top5 = pnls.nlargest(5).sum() if n else 0
    bot5 = -pnls.nsmallest(5).sum() if n else 0
    eq = result.get("equity_curve") or []
    episodes = _drawdown_episodes(eq)
    material = [e for e in episodes if (e["depth_pct"] or 0) >= 3.0]
    dd_curve = result.get("drawdown_curve") or []
    underwater_days = sum(1 for p in dd_curve if (p.get("drawdown_pct") or 0) > 0)

    conc = {}
    warnings = []
    for key, name in (("symbol", "stock"), ("sector", "sector"),
                      ("strategy_name", "strategy"), ("market_regime", "regime")):
        if n and key in trades.columns:
            grp = trades.groupby(key)["net_pnl"].sum().sort_values(ascending=False)
            profit_grp = grp[grp > 0]
            top_share = _num(_div(100.0 * profit_grp.iloc[0], total_profit)) if len(profit_grp) and total_profit > 0 else None
            conc[name] = {"top_group": str(grp.index[0]) if len(grp) else None,
                          "top_profit_share_pct": top_share}
            if top_share is not None and top_share > 40:
                warnings.append(f"More than 40% of gross profit came from one {name} "
                                f"({grp.index[0]}: {top_share:.0f}%).")
    top5_share = _num(_div(100.0 * top5, total_profit)) if total_profit > 0 else None
    if top5_share is not None and top5_share > 70:
        warnings.append(f"Top five trades generated {top5_share:.0f}% of total profit — "
                        "results depend on a small number of trades.")
    if n and "market_regime" in trades.columns and total_loss > 0:
        loss_by_regime = trades[trades["net_pnl"] < 0].groupby("market_regime")["net_pnl"].sum()
        if len(loss_by_regime):
            worst = loss_by_regime.idxmin()
            share = -loss_by_regime.min() / total_loss * 100
            if share > 50:
                warnings.append(f"Most losses ({share:.0f}%) occurred in the {worst} regime.")
    # Risk-of-ruin estimate (labelled estimate; simple Gaussian approximation)
    ror = None
    if n >= 10:
        mu, sd = rets.mean(), rets.std()
        if sd and sd > 0:
            ror = _num(min(100.0, max(0.0, 100.0 * math.exp(-2 * mu * 25 / (sd * sd))))) if mu > 0 else 100.0
    return {
        "max_drawdown_pct": _num(o.get("max_drawdown_pct")),
        "drawdown_episodes_material": len(material),
        "avg_drawdown_pct": _num(pd.Series([e["depth_pct"] for e in episodes if e["depth_pct"]]).mean()) if episodes else None,
        "longest_drawdown_days": max((e["duration_days"] or 0) for e in episodes) if episodes else None,
        "time_underwater_pct": _num(_div(100.0 * underwater_days, len(dd_curve))) if dd_curve else None,
        "largest_single_trade_loss": _num(pnls.min()) if n else None,
        "p5_trade_return_pct": _num(rets.quantile(0.05)) if n >= 5 else None,
        "p95_trade_return_pct": _num(rets.quantile(0.95)) if n >= 5 else None,
        "downside_deviation_pct": downside_dev,
        "risk_of_ruin_estimate_pct": ror,
        "risk_of_ruin_note": "Rough Gaussian estimate over 25 sequential trades — an approximation, not a measured probability.",
        "concentration": conc,
        "top5_trades_profit_share_pct": top5_share,
        "top5_losses_share_pct": _num(_div(100.0 * bot5, total_loss)) if total_loss > 0 else None,
        "depends_on_few_trades": bool(top5_share and top5_share > 70),
        "warnings": warnings,
    }


def _sec_distribution(trades, ledger):
    if trades.empty:
        return {"note": "No out-of-sample trades were executed.", "tables": {}}
    t = trades.copy()
    tables = {
        "by_strategy": _by(t, "strategy_name"),
        "by_stock": _by(t, "symbol")[:20],
        "by_sector": _by(t, "sector"),
        "by_regime": _by(t, "market_regime"),
        "by_exit_reason": _by(t, "exit_reason"),
    }
    t["year"] = t["entry_date"].astype(str).str[:4]
    tables["by_year"] = _by(t, "year")
    t["month"] = t["entry_date"].astype(str).str[:7]
    tables["by_month"] = _by(t, "month")
    hold_order = ["0-1d", "2-3d", "4-7d", "8-15d", "16-20d", "21d+"]
    t["hold_band"] = _band(t["holding_days"], [-1, 1, 3, 7, 15, 20, 10 ** 4], hold_order)
    tables["by_holding_period"] = _by(t, "hold_band", hold_order)
    conf_order = ["<55", "55-60", "60-65", "65-70", "70-75", "75-80", "80+"]
    t["conf_band"] = _band(t["confidence"], [0, 55, 60, 65, 70, 75, 80, 101], conf_order)
    tables["by_confidence_band"] = _by(t, "conf_band", conf_order)
    if "gap_pct" in t.columns:
        gap_order = ["<-1%", "-1..0%", "0..1%", "1..2%", ">2%"]
        t["gap_band"] = _band(t["gap_pct"], [-100, -1, 0, 1, 2, 100], gap_order)
        tables["by_gap_pct"] = _by(t, "gap_band", gap_order)
    # feature bands need entry-time features from the ledger (entered rows)
    joined = _join_ledger(t, ledger)
    for col, edges, labels, name in (
            ("volume_ratio", [0, 0.8, 1.2, 2.0, 100], ["<0.8x", "0.8-1.2x", "1.2-2x", ">2x"], "by_volume_ratio"),
            ("adx", [0, 20, 25, 35, 100], ["<20", "20-25", "25-35", ">35"], "by_adx_band"),
            ("atr_pct", [0, 1.5, 2.5, 4, 100], ["<1.5%", "1.5-2.5%", "2.5-4%", ">4%"], "by_volatility_band"),
            ("opportunity_score", [0, 40, 55, 70, 101], ["<40", "40-55", "55-70", "70+"], "by_opportunity_score"),
            ("rr_ratio", [0, 1.5, 2, 3, 100], ["<1.5", "1.5-2", "2-3", ">3"], "by_risk_reward")):
        if joined is not None and col in joined.columns and joined[col].notna().any():
            jj = joined.copy()
            jj["band"] = _band(jj[col], edges, labels)
            tables[name] = _by(jj, "band", labels)
        else:
            tables[name] = []
    notes = ["All trades are long-only (no short side in this system).",
             "Groups labelled VERY LOW / LOW have too few trades to be reliable, regardless of profitability."]
    return {"tables": tables, "notes": notes}


def _join_ledger(trades, ledger):
    """Attach entry-time features from ledger 'entered' rows (window+symbol+entry_date)."""
    if ledger.empty or trades.empty or "stage" not in ledger.columns:
        return None
    ent = ledger[ledger["stage"] == "entered"].copy()
    if ent.empty:
        return None
    keys = [k for k in ("window", "symbol", "entry_date") if k in ent.columns and k in trades.columns]
    if len(keys) < 2:
        return None
    feat_cols = [c for c in ("rsi", "adx", "volume_ratio", "atr_pct", "opportunity_score",
                             "rr_ratio", "macd_state", "above_ema20", "above_ema50",
                             "base_confidence", "similarity_adjustment", "pattern_adjustment",
                             "model_adjustment", "calibrated_probability") if c in ent.columns]
    ent = ent[keys + feat_cols].drop_duplicates(subset=keys)
    return trades.merge(ent, on=keys, how="left", suffixes=("", "_ledger"))


def _sec_confidence(result, trades):
    cal = result.get("calibration_report") or {}
    n = cal.get("samples") or 0
    before, after = cal.get("before") or {}, cal.get("after") or {}
    buckets = []
    for b in (cal.get("reliability_calibrated") or cal.get("reliability_raw") or []):
        if (b.get("count") or 0) > 0:
            buckets.append({"range": f"{b.get('bin_low')}-{b.get('bin_high')}",
                            "count": b.get("count"),
                            "predicted_win_prob": _num(b.get("avg_predicted")),
                            "actual_win_rate": _num(b.get("observed_rate")),
                            "gap": _num(b.get("gap"))})
    warnings = []
    if n and n < 50:
        warnings.append(f"Calibration metrics are based on only {n} samples ({_sample_label(n)}) — treat with caution.")
    hi_losers = lo_winners = None
    neg_bands = []
    if not trades.empty and "confidence" in trades.columns:
        hi_losers = int(((trades["confidence"] >= 70) & (trades["net_pnl"] <= 0)).sum())
        lo_winners = int(((trades["confidence"] < 60) & (trades["net_pnl"] > 0)).sum())
        t = trades.copy()
        t["conf_band"] = _band(t["confidence"], [0, 55, 60, 65, 70, 75, 80, 101],
                               ["<55", "55-60", "60-65", "65-70", "70-75", "75-80", "80+"])
        hi = t[t["confidence"] >= 70]; lo = t[t["confidence"] < 70]
        if len(hi) >= 5 and len(lo) >= 5:
            if (hi["net_pnl"].mean() or 0) < (lo["net_pnl"].mean() or 0):
                warnings.append("Higher confidence did NOT correspond with better outcomes in this experiment.")
        for g, sub in t.groupby("conf_band"):
            if len(sub) >= 5 and sub["net_pnl"].mean() < 0:
                neg_bands.append({"band": str(g), "trades": len(sub),
                                  "expectancy_rs": _num(sub["net_pnl"].mean()),
                                  "sample_label": _sample_label(len(sub))})
        if neg_bands:
            warnings.append("Some confidence bands show negative expectancy — confidence should not be read as trade quality here.")
    for b in buckets:
        if b["count"] and b["count"] >= 10 and b["gap"] is not None and b["gap"] > 0.15:
            warnings.append(f"Confidence bucket {b['range']} is materially overconfident "
                            f"(predicted {b['predicted_win_prob']}, actual {b['actual_win_rate']}).")
    return {
        "samples": n or None,
        "method": cal.get("calibration_method"),
        "before_calibration": {"brier_score": _num(before.get("brier_score")),
                               "ece": _num(before.get("ece")),
                               "log_loss": _num(before.get("log_loss"))},
        "after_calibration": {"brier_score": _num(after.get("brier_score")),
                              "ece": _num(after.get("ece")),
                              "log_loss": _num(after.get("log_loss"))},
        "reliability_buckets": buckets,
        "high_confidence_losses": hi_losers,
        "low_confidence_winners": lo_winners,
        "negative_expectancy_bands": neg_bands,
        "warnings": warnings,
    }


def _sec_false_positives(analysis, trades, ledger):
    base = (analysis or {}).get("false_positives") or {}
    out = {"definition": ("BUY/STRONG BUY entries that lost money after costs, hit the "
                          "stop, or never achieved at least +1% favourable excursion."),
           "from_phase42_analysis": base or None}
    if trades.empty:
        out["note"] = "No executed trades — false-positive analysis unavailable."
        return out
    t = trades.copy()
    fp_mask = (t["net_pnl"] <= 0) | (t["exit_reason"].astype(str).str.contains("Stop", case=False)) | \
              (t["mfe_pct"].fillna(0) < 1.0 if "mfe_pct" in t.columns else False)
    fp = t[fp_mask]
    n, total = len(fp), len(t)
    base_rate = 100.0 * n / total if total else None
    out.update({
        "count": n, "total_trades": total,
        "rate_pct": _num(base_rate),
        "avg_mae_pct": _num(fp["mae_pct"].mean()) if "mae_pct" in fp.columns and len(fp) else None,
        "avg_mfe_pct": _num(fp["mfe_pct"].mean()) if "mfe_pct" in fp.columns and len(fp) else None,
        "avg_holding_days": _num(fp["holding_days"].mean()) if len(fp) else None,
        "exit_reasons": _by(fp, "exit_reason"),
    })
    subgroups = []
    joined = _join_ledger(t, ledger)
    src = joined if joined is not None else t
    src = src.copy(); src["_is_fp"] = fp_mask.values
    dims = [("strategy_name", None), ("market_regime", None), ("sector", None)]
    if "volume_ratio" in src.columns:
        src["vol_band"] = _band(src["volume_ratio"], [0, 0.8, 1.2, 2.0, 100], ["<0.8x", "0.8-1.2x", "1.2-2x", ">2x"])
        dims.append(("vol_band", "volume band"))
    src["conf_band"] = _band(src["confidence"], [0, 60, 70, 101], ["<60", "60-70", "70+"])
    dims.append(("conf_band", "confidence band"))
    for col, label in dims:
        if col not in src.columns:
            continue
        for g, sub in src.groupby(col, dropna=True):
            if len(sub) < 3:
                continue
            sub_rate = 100.0 * sub["_is_fp"].sum() / len(sub)
            subgroups.append({
                "dimension": label or col.replace("_name", "").replace("market_", ""),
                "group": str(g), "sample_count": len(sub),
                "baseline_rate_pct": _num(base_rate),
                "subgroup_rate_pct": _num(sub_rate),
                "abs_difference_pct": _num(sub_rate - base_rate) if base_rate is not None else None,
                "reliability": _sample_label(len(sub)),
            })
    subgroups.sort(key=lambda s: -(abs(s["abs_difference_pct"] or 0)))
    out["subgroup_rates"] = subgroups[:20]
    out["language_note"] = ("Associations only — no causal claims. Example: false-positive "
                            "trades were more frequently associated with the subgroups showing "
                            "the largest positive differences above, given sufficient samples.")
    return out


def _sec_missed(analysis, ledger):
    base = (analysis or {}).get("missed_opportunities") or {}
    if ledger.empty or "stage" not in ledger.columns:
        return {"available": False,
                "note": ("Missed-opportunity analysis unavailable because historical "
                         "rejected-candidate snapshots were not persisted for this experiment.")}
    cats = {
        "rejected_confidence": "Excluded by confidence floor",
        "rejected_confidence_similarity": "Excluded by similarity adjustment (counterfactual)",
        "rejected_calibrated_prob": "Excluded by calibrated-probability floor",
        "rejected_strategy_gate": "Excluded by strategy eligibility",
        "rejected_no_slot": "Excluded by position-slot limit",
        "rejected_fill": "Order not filled",
        "rejected_allocation_caps": "Excluded by allocation caps",
    }
    rows = []
    for stage, label in cats.items():
        sub = ledger[ledger["stage"] == stage]
        if sub.empty:
            continue
        row = {"category": label, "stage": stage, "cases": len(sub),
               "reliability": _sample_label(len(sub))}
        for h in (1, 3, 5, 10, 20):
            col = f"fwd_{h}"
            row[f"avg_fwd_{h}d_pct"] = _num(sub[col].mean()) if col in sub.columns else None
        row["avg_mfe_pct"] = _num(sub["mfe_pct"].mean()) if "mfe_pct" in sub.columns else None
        row["avg_mae_pct"] = _num(sub["mae_pct"].mean()) if "mae_pct" in sub.columns else None
        row["avg_confidence"] = _num(sub["final_confidence"].mean()) if "final_confidence" in sub.columns else None
        row["winners_10d_pct"] = _num(100.0 * (sub["fwd_10"] > 2).mean()) if "fwd_10" in sub.columns and sub["fwd_10"].notna().any() else None
        rows.append(row)
    watch = ledger[(ledger.get("recommendation") == "WATCH") & (ledger["stage"] == "not_buy_signal")] \
        if "recommendation" in ledger.columns else pd.DataFrame()
    watch_row = None
    if len(watch) and "fwd_10" in watch.columns:
        risers = watch[watch["fwd_10"] > 3]
        watch_row = {"watch_signals": len(watch),
                     "rose_over_3pct_in_10d": int(len(risers)),
                     "share_pct": _num(100.0 * len(risers) / len(watch))}
    return {"available": True, "categories": rows, "watch_that_rose": watch_row,
            "from_phase42_analysis": base or None,
            "note": ("Diagnostic only — this does not weaken or modify any safety gate. "
                     "Forward returns were computed inside each experiment window during "
                     "simulation; no new lookahead is introduced.")}


FEATURES = ["rsi", "adx", "volume_ratio", "atr_pct", "opportunity_score", "rr_ratio",
            "base_confidence", "calibrated_probability", "similarity_adjustment",
            "pattern_adjustment", "gap_pct", "confidence"]


def _sec_features(analysis, trades, ledger):
    out = {"from_phase42_analysis": (analysis or {}).get("feature_impact") or None,
           "features": []}
    joined = _join_ledger(trades, ledger)
    if joined is None or joined.empty:
        out["note"] = "Entry-time feature snapshots unavailable — feature analysis limited to Phase 4.2 output."
        return out
    windows = joined["window"].nunique() if "window" in joined.columns else 1
    for feat in FEATURES:
        if feat not in joined.columns or joined[feat].notna().sum() < 5:
            continue
        df = joined[joined[feat].notna()].copy()
        winners, losers = df[df["net_pnl"] > 0], df[df["net_pnl"] <= 0]
        w_mean = _num(winners[feat].mean()) if len(winners) else None
        l_mean = _num(losers[feat].mean()) if len(losers) else None
        try:
            q = pd.qcut(df[feat], min(3, df[feat].nunique()), duplicates="drop")
        except Exception:
            q = None
        bins = []
        consistent_windows = 0
        if q is not None:
            for g, sub in df.groupby(q, observed=True):
                if len(sub) == 0:
                    continue
                bins.append({"bin": str(g), "trades": len(sub),
                             "win_rate": _num(100.0 * (sub["net_pnl"] > 0).mean()),
                             "expectancy_rs": _num(sub["net_pnl"].mean()),
                             "profit_factor": _num(_pf(sub["net_pnl"].tolist())),
                             "avg_return_pct": _num(sub["return_pct"].mean()),
                             "sample_label": _sample_label(len(sub))})
        # window consistency: sign of (winner mean - loser mean) per window
        if "window" in df.columns and w_mean is not None and l_mean is not None:
            overall_sign = 1 if w_mean > l_mean else -1
            for _, wsub in df.groupby("window"):
                ww, wl = wsub[wsub["net_pnl"] > 0], wsub[wsub["net_pnl"] <= 0]
                if len(ww) >= 2 and len(wl) >= 2:
                    sign = 1 if ww[feat].mean() > wl[feat].mean() else -1
                    if sign == overall_sign:
                        consistent_windows += 1
        n = len(df)
        # rule-based assessment
        if n < 25:
            assess = "INCONCLUSIVE"
        elif w_mean is None or l_mean is None or abs((w_mean or 0) - (l_mean or 0)) < 1e-9:
            assess = "INCONCLUSIVE"
        elif consistent_windows >= 2 and n >= 50:
            assess = "SUPPORTED"
        elif consistent_windows >= 2:
            assess = "POSSIBLY USEFUL"
        else:
            assess = "INCONCLUSIVE"
        # HARMFUL/UNHELPFUL: monotone-negative bins
        if len(bins) >= 2 and n >= 25:
            exps = [b["expectancy_rs"] for b in bins if b["expectancy_rs"] is not None]
            if len(exps) >= 2 and all(e < 0 for e in exps):
                assess = "UNHELPFUL"
        out["features"].append({
            "feature": feat, "samples": n, "sample_label": _sample_label(n),
            "winner_mean": w_mean, "loser_mean": l_mean,
            "winner_loser_gap": _num((w_mean or 0) - (l_mean or 0)) if w_mean is not None and l_mean is not None else None,
            "bins": bins, "windows_consistent": consistent_windows,
            "windows_total": int(windows), "assessment": assess,
        })
    out["note"] = ("SUPPORTED requires 50+ samples and multi-window consistency. "
                   "A single profitable bucket does not make a feature important.")
    return out


def _sec_param_sensitivity(analysis, status, all_experiments=None):
    ts = (analysis or {}).get("threshold_sensitivity") or {}
    sweeps = {}
    for key in ("confidence_sweep", "calibrated_prob_sweep", "volume_sweep", "hold_days_sweep"):
        rows = ts.get(key)
        if not rows:
            continue
        vals = []
        for r in rows:
            n = r.get("trades") or r.get("n") or 0
            vals.append(dict(r, evidence=_sample_label(int(n))))
        sweeps[key] = vals
    highlights = []
    conf = sweeps.get("confidence_sweep") or []
    if len(conf) >= 3:
        exps = [(r.get("threshold"), r.get("expectancy") if r.get("expectancy") is not None else r.get("avg_return_pct")) for r in conf]
        exps = [(t, e) for t, e in exps if e is not None]
        if exps:
            best = max(exps, key=lambda x: x[1])
            rest = [e for t, e in exps if t != best[0]]
            if rest and best[1] > 0 and max(rest) < best[1] * 0.5:
                highlights.append({"type": "unstable_peak",
                                   "message": f"Confidence threshold {best[0]} is an isolated peak — likely overfit; prefer stable ranges."})
            elif len(exps) >= 3 and max(e for _, e in exps) - min(e for _, e in exps) < 5:
                highlights.append({"type": "flat_region",
                                   "message": "Confidence sweep is relatively flat — results not highly sensitive to this parameter."})
    return {"sweeps": sweeps, "highlights": highlights,
            "note": ("Sweeps use the stop/target-aware approximation documented in the "
                     "Phase 4.2 analysis. No single 'best' value is recommended from "
                     "maximum return alone — prefer stable parameter ranges. Values with "
                     "VERY LOW / LOW evidence should not drive decisions.")}


def _sec_regimes(trades, result):
    rows = _by(trades, "market_regime") if not trades.empty else []
    total_pnl = trades["net_pnl"].sum() if not trades.empty else 0
    total_n = len(trades)
    recs = []
    windows_by_regime = {}
    if not trades.empty and "window" in trades.columns:
        for g, sub in trades.groupby("market_regime"):
            pos_windows = sum(1 for _, w in sub.groupby("window") if w["net_pnl"].sum() > 0)
            windows_by_regime[str(g)] = {"windows": int(sub["window"].nunique()),
                                         "profitable_windows": pos_windows}
    for r in rows:
        r["pct_of_trades"] = _num(_div(100.0 * r["trades"], total_n))
        r["pct_of_net_pnl"] = _num(_div(100.0 * (r["net_pnl"] or 0), total_pnl)) if total_pnl else None
        r["window_consistency"] = windows_by_regime.get(r["group"])
        n = r["trades"]
        exp = r["expectancy_rs"] or 0
        if n < 10:
            rec = "INCONCLUSIVE"
        elif exp > 0 and (r["profit_factor"] or 0) > 1.1 and (r["window_consistency"] or {}).get("profitable_windows", 0) >= 2:
            rec = "ELIGIBLE"
        elif exp < 0 and n >= 25:
            rec = "DISABLE"
        elif exp < 0:
            rec = "RESTRICT"
        else:
            rec = "INCONCLUSIVE"
        recs.append({"regime": r["group"], "recommendation": rec, "trades": n,
                     "expectancy_rs": r["expectancy_rs"], "sample_label": r["sample_label"]})
    return {"tables": rows, "eligibility_recommendations": recs,
            "disclaimer": "Analysis-only regime recommendation — not used by live strategy selection."}


def _sec_holding(trades, ledger):
    if trades.empty:
        return {"note": "No trades to analyse."}
    t = trades.copy()
    order = ["0-1d", "2-3d", "4-7d", "8-15d", "16-20d", "21d+"]
    t["hold_band"] = _band(t["holding_days"], [-1, 1, 3, 7, 15, 20, 10 ** 4], order)
    tables = []
    for b in _by(t, "hold_band", order):
        sub = t[t["hold_band"] == b["group"]]
        b["avg_mae_pct"] = _num(sub["mae_pct"].mean()) if "mae_pct" in sub.columns else None
        b["avg_mfe_pct"] = _num(sub["mfe_pct"].mean()) if "mfe_pct" in sub.columns else None
        b["exit_reasons"] = sub["exit_reason"].value_counts().to_dict() if "exit_reason" in sub.columns else {}
        tables.append(b)
    # controlled alternative-exit analysis from stored forward returns
    alt = []
    joined = _join_ledger(t, ledger)
    if joined is not None:
        for h, col in ((1, "fwd_1"), (3, "fwd_3"), (5, "fwd_5"), (10, "fwd_10")):
            if col in joined.columns and joined[col].notna().sum() >= 5:
                sub = joined[joined[col].notna()]
                alt.append({"exit_after_days": h, "trades": len(sub),
                            "avg_return_pct": _num(sub[col].mean()),
                            "win_rate": _num(100.0 * (sub[col] > 0).mean()),
                            "sample_label": _sample_label(len(sub))})
        alt.append({"exit_after_days": "strategy exit (actual)", "trades": len(t),
                    "avg_return_pct": _num(t["return_pct"].mean()),
                    "win_rate": _num(100.0 * (t["net_pnl"] > 0).mean()),
                    "sample_label": _sample_label(len(t))})
    return {"tables": tables, "alternative_exits": alt,
            "alternative_exit_note": ("Controlled alternative-exit analysis using forward "
                                      "returns stored during simulation (gross of costs, "
                                      "close-to-close). Approximation only — actual "
                                      "stop/target behaviour is not replayed.")}


def _sec_drawdown(result, trades):
    eq = result.get("equity_curve") or []
    dd = result.get("drawdown_curve") or []
    episodes = _drawdown_episodes(eq)[:10]
    for e in episodes:
        if trades.empty:
            continue
        try:
            mask = (trades["exit_date"] >= e["start_date"]) & \
                   (trades["exit_date"] <= (e["recovery_date"] or e["trough_date"]))
            sub = trades[mask]
        except Exception:
            continue
        e["trades_during"] = len(sub)
        if len(sub):
            losses = sub[sub["net_pnl"] < 0]
            e["dominant_strategy"] = str(sub.groupby("strategy_name")["net_pnl"].sum().idxmin()) if "strategy_name" in sub.columns and len(losses) else None
            e["dominant_sector"] = str(sub.groupby("sector")["net_pnl"].sum().idxmin()) if "sector" in sub.columns and len(losses) else None
            e["dominant_regime"] = str(sub["market_regime"].mode().iloc[0]) if "market_regime" in sub.columns and len(sub) else None
            e["main_loss_contributors"] = [
                {"symbol": r["symbol"], "net_pnl": _num(r["net_pnl"]), "exit_date": r["exit_date"]}
                for _, r in losses.nsmallest(3, "net_pnl").iterrows()] if len(losses) else []
    explanation = None
    if episodes:
        big = episodes[0]
        parts = [f"The largest drawdown was {big['depth_pct']}% deep, starting {big['start_date']}"]
        if big.get("dominant_regime"):
            parts.append(f"occurring mainly during the {big['dominant_regime']} regime")
        if big.get("dominant_strategy"):
            parts.append(f"with the largest losses from {big['dominant_strategy']} trades")
        explanation = ", ".join(parts) + "."
    return {"equity_curve": eq, "drawdown_curve": dd,
            "episodes": episodes, "largest_drawdown_explanation": explanation}


def _trade_rows(df, ledger):
    joined = _join_ledger(df, ledger)
    src = joined if joined is not None else df
    cols = ["symbol", "strategy_name", "entry_date", "exit_date", "entry_price",
            "exit_price", "stop_loss", "target", "return_pct", "net_pnl", "total_costs",
            "confidence", "calibrated_probability", "opportunity_score", "market_regime",
            "sector", "exit_reason", "mae_pct", "mfe_pct", "holding_days", "window",
            "rsi", "adx", "volume_ratio", "atr_pct", "macd_state"]
    rows = []
    for _, r in src.iterrows():
        row = {}
        for c in cols:
            v = r.get(c)
            if isinstance(v, float):
                v = _num(v)
            elif pd.isna(v) if not isinstance(v, (list, dict)) else False:
                v = None
            row[c] = v
        rows.append(row)
    return rows


def _sec_examples(trades, ledger):
    if trades.empty:
        return {"note": "No trades."}
    t = trades
    out = {
        "top_winners": _trade_rows(t.nlargest(10, "net_pnl"), ledger),
        "top_losers": _trade_rows(t.nsmallest(10, "net_pnl"), ledger),
    }
    if "mae_pct" in t.columns:
        out["highest_mae"] = _trade_rows(t.nsmallest(10, "mae_pct"), ledger)
    if "confidence" in t.columns:
        out["high_confidence_losses"] = _trade_rows(
            t[t["net_pnl"] <= 0].nlargest(10, "confidence"), ledger)
        out["low_confidence_winners"] = _trade_rows(
            t[t["net_pnl"] > 0].nsmallest(10, "confidence"), ledger)
    out["note"] = "Row details use entry-time stored data only."
    return out


def _sec_strengths_weaknesses(exec_s, perf, risk, conf, regimes):
    strengths, weaknesses = [], []

    def item(title, expl, metric, n, src):
        return {"title": title, "explanation": expl, "supporting_metric": metric,
                "sample_count": n, "reliability": _sample_label(n or 0),
                "source_section": src}

    n = exec_s.get("oos_trades") or 0
    pf = exec_s.get("profit_factor")
    exp = exec_s.get("expectancy_rs")
    if exp is not None and exp < 0:
        weaknesses.append(item("Negative expectancy after costs",
                               f"Average trade lost Rs {abs(exp):.2f} net of costs.",
                               f"expectancy_rs={exp}", n, "performance"))
    if pf is not None and pf < 1:
        weaknesses.append(item("Profit factor below 1",
                               "Gross losses exceeded gross profits.",
                               f"profit_factor={pf}", n, "performance"))
    if n < 50:
        weaknesses.append(item("Low trade count",
                               f"Only {n} out-of-sample trades — evidence is {_sample_label(n)}.",
                               f"oos_trades={n}", n, "executive_summary"))
    if risk.get("depends_on_few_trades"):
        weaknesses.append(item("Performance depends on few trades",
                               f"Top five trades produced {risk.get('top5_trades_profit_share_pct')}% of profit.",
                               f"top5_share={risk.get('top5_trades_profit_share_pct')}%", n, "risk"))
    for w in risk.get("warnings") or []:
        weaknesses.append(item("Concentration warning", w, "see risk section", n, "risk"))
    for w in conf.get("warnings") or []:
        weaknesses.append(item("Calibration warning", w, "see confidence section",
                               conf.get("samples") or 0, "confidence_analysis"))
    pw = perf.get("pct_profitable_windows")
    if pw is not None and pw < 50:
        weaknesses.append(item("Majority of windows unprofitable",
                               f"Only {pw:.0f}% of test windows were profitable.",
                               f"pct_profitable_windows={pw}", n, "performance"))

    b, a = conf.get("before_calibration") or {}, conf.get("after_calibration") or {}
    if b.get("brier_score") and a.get("brier_score") and a["brier_score"] < b["brier_score"]:
        strengths.append(item("Calibration improved raw confidence",
                              f"Brier score improved from {b['brier_score']} to {a['brier_score']}.",
                              "brier_before_vs_after", conf.get("samples") or 0, "confidence_analysis"))
    cost_drag = perf.get("cost_drag_pct_of_gross_profit")
    if cost_drag is not None and 0 <= cost_drag < 15:
        strengths.append(item("Costs are a small share of gross profit",
                              f"Cost drag is {cost_drag:.1f}% of gross profit.",
                              f"cost_drag={cost_drag}", n, "performance"))
    for r in regimes.get("eligibility_recommendations") or []:
        if r["recommendation"] == "ELIGIBLE":
            strengths.append(item(f"Positive results in {r['regime']} regime",
                                  f"Expectancy Rs {r['expectancy_rs']} across {r['trades']} trades with multi-window support.",
                                  f"regime={r['regime']}", r["trades"], "regime_analysis"))
    if not strengths:
        strengths.append(item("No reliable strengths identified",
                              "No metric met the evidence requirements for a supported strength claim.",
                              "N/A", n, "executive_summary"))
    return strengths, weaknesses


def _sec_recommendations(exec_s, weaknesses, param_sens, conf, regimes):
    recs = []
    n = exec_s.get("oos_trades") or 0

    def rec(priority, category, action, reason, evidence, value, risk_note, experiment):
        recs.append({"priority": priority, "category": category, "action": action,
                     "reason": reason, "evidence": evidence,
                     "expected_research_value": value, "risk": risk_note,
                     "suggested_controlled_experiment": experiment,
                     "may_affect_live_logic": False})

    if n < 50:
        rec("HIGH", "Increase evidence period",
            "Extend the date range or widen windows to reach at least 100 out-of-sample trades.",
            f"Only {n} OOS trades — below the 100-trade evidence requirement.",
            f"oos_trades={n}", "High — verdicts are currently statistically weak.",
            "None — current results cannot be trusted either way.",
            "Same config with a longer start–end range (e.g. +2 years).")
    if (exec_s.get("profit_factor") or 1) < 0.8 and n >= 25:
        rec("HIGH", "Disable strategy from further testing",
            "Deprioritize this exact configuration in future batches.",
            f"Profit factor {exec_s.get('profit_factor')} is materially below 1 with {_sample_label(n)} evidence.",
            f"profit_factor={exec_s.get('profit_factor')}, trades={n}",
            "Medium — avoids wasting research budget.", "Low.",
            "Re-test only after a structural change (exit rules or regime restriction).")
    sweeps = (param_sens.get("sweeps") or {}).get("confidence_sweep") or []
    good = [r for r in sweeps if (r.get("trades") or 0) >= 10 and (r.get("expectancy") or r.get("avg_return_pct") or 0) > 0]
    if good:
        thr = good[0].get("threshold")
        rec("MEDIUM", "Test a confidence threshold",
            f"Run a controlled experiment with min confidence {thr}.",
            "Threshold sweep shows positive expectancy at this level (approximate, stop/target-aware).",
            f"sweep row: {good[0]}", "Medium.", "Sweep is an approximation — needs a real run.",
            f"Identical config except min_confidence_execute={thr}.")
    for w in conf.get("warnings") or []:
        if "overconfident" in w.lower():
            rec("MEDIUM", "Fix calibration",
                "Collect more calibration samples before trusting confidence-based gates.",
                w, f"calibration samples={conf.get('samples')}",
                "Medium.", "Low.", "Longer run to accumulate 100+ calibration samples.")
            break
    for r in regimes.get("eligibility_recommendations") or []:
        if r["recommendation"] == "DISABLE" and r["trades"] >= 25:
            rec("MEDIUM", "Restrict to a market regime",
                f"Test excluding the {r['regime']} regime.",
                f"Negative expectancy (Rs {r['expectancy_rs']}) in {r['regime']} across {r['trades']} trades.",
                f"regime table: {r}", "Medium.",
                "Regime filters can overfit — verify across windows.",
                f"Identical config with {r['regime']} entries disabled (research variant).")
    if not recs:
        rec("LOW", "Improve data coverage",
            "No specific evidence-backed recommendation; extend evidence before further changes.",
            "No section produced a supported recommendation.", "N/A", "Low.", "None.",
            "Longer date range, same config.")
    return recs


def _sec_next_experiments(exec_s, status, param_sens, regimes):
    cfg = status.get("canonical_config") or {}
    base = {k: cfg.get(k) for k in ("train_years", "test_months", "step_months",
                                    "start_date", "end_date", "max_holding_days",
                                    "min_confidence_execute", "intrabar_rule")}
    out = []

    def sug(sid, name, hypothesis, variable, treatment, priority, rationale):
        treat_cfg = dict(base); treat_cfg.update(treatment)
        out.append({"id": sid, "name": name, "hypothesis": hypothesis,
                    "primary_variable": variable,
                    "control_config": base, "treatment_config": treat_cfg,
                    "required_date_range": f"{base.get('start_date')} to {base.get('end_date')}",
                    "required_sample_target": 100,
                    "success_criteria": "Profit factor >= 1.15 and positive expectancy with >= 100 OOS trades and >= 2 profitable windows.",
                    "rejection_criteria": "Expectancy remains negative or evidence stays below 50 trades.",
                    "expected_runtime_estimate_min": 3,
                    "priority": priority, "rationale": rationale,
                    "queue_requires_confirmation": True})

    try:
        start_year = int(str(base.get("start_date"))[:4])
        extended = f"{start_year - 2}-01-01"
    except Exception:
        extended = None
    if extended:
        sug("ext_evidence", "Extended evidence period",
            "The current verdict is evidence-limited; more windows will produce a statistically usable sample.",
            "date range", {"start_date": extended}, "HIGH",
            f"Only {exec_s.get('oos_trades')} OOS trades; the 100-trade requirement was not met.")
    conf_now = base.get("min_confidence_execute")
    sweeps = (param_sens.get("sweeps") or {}).get("confidence_sweep") or []
    cands = [r for r in sweeps if (r.get("trades") or 0) >= 10 and r.get("threshold") not in (None, conf_now)]
    if cands:
        best = max(cands, key=lambda r: (r.get("expectancy") or r.get("avg_return_pct") or 0))
        sug("conf_thr", f"Confidence threshold {best.get('threshold')}",
            "A higher confidence floor removes negative-expectancy entries.",
            "min_confidence_execute",
            {"min_confidence_execute": best.get("threshold")}, "MEDIUM",
            "Sweep analysis (approximate) shows better expectancy at this threshold; a real run is required to confirm.")
    hold = base.get("max_holding_days") or 20
    sug("hold_short", f"Shorter max holding period ({max(5, int(hold) // 2)}d)",
        "Losses grow with holding time in this experiment; earlier exits may cut tail losses.",
        "max_holding_days", {"max_holding_days": max(5, int(hold) // 2)}, "MEDIUM",
        "Holding-period table shows deteriorating expectancy in longer bands (verify in report).")
    disables = [r for r in regimes.get("eligibility_recommendations") or [] if r["recommendation"] in ("DISABLE", "RESTRICT")]
    if disables:
        reg = disables[0]["regime"]
        sug("regime_excl", f"Exclude {reg} regime",
            f"Entries during {reg} contributed negative expectancy.",
            "regime eligibility (research-only gate)", {"exclude_regime": reg}, "LOW",
            "Regime table shows losses concentrated in this regime; controlled test needed.")
    sug("step_shift", "Shifted window phase",
        "Robust results should not depend on window phase alignment.",
        "start_date (+1 month phase shift)", {"start_date": _shift_month(base.get("start_date"))}, "LOW",
        "Window-phase robustness check — a genuinely robust result survives phase shifts.")
    return {"suggestions": out[:5],
            "note": ("Suggestions follow controlled-experiment principles: one variable at a "
                     "time, walk-forward evaluation, realistic costs. Queueing always requires "
                     "explicit user confirmation — nothing is auto-queued.")}


def _shift_month(d):
    try:
        ts = pd.Timestamp(d) + pd.DateOffset(months=1)
        return ts.strftime("%Y-%m-%d")
    except Exception:
        return d


def _sec_final_verdict(exec_s, status):
    n = exec_s.get("oos_trades") or 0
    windows = exec_s.get("windows") or 0
    pf = exec_s.get("profit_factor")
    exp = exec_s.get("expectancy_rs")
    flags = exec_s.get("overfitting_flags") or []
    crit = ((status.get("metrics") or {}).get("verdict") or status.get("verdict"))
    reasons, verdict = [], None
    thresholds = {"min_trades": 100, "min_windows": 2, "reject_pf_below": 0.8,
                  "promising_pf_above": 1.15, "max_drawdown_pct": 20.0}
    if n < thresholds["min_trades"] or windows < thresholds["min_windows"]:
        verdict = "INSUFFICIENT DATA"
        reasons.append(f"{n} OOS trades (< {thresholds['min_trades']}) across {windows} windows.")
    elif exp is not None and exp < 0 and pf is not None and pf < thresholds["reject_pf_below"]:
        verdict = "REJECT"
        reasons.append(f"Materially negative expectancy (Rs {exp}) and profit factor {pf} with sufficient evidence.")
    elif pf is not None and abs(pf - 1.0) < 0.1:
        verdict = "INCONCLUSIVE"
        reasons.append(f"Profit factor {pf} is close to breakeven.")
    elif (exp or 0) > 0 and (pf or 0) >= thresholds["promising_pf_above"] and \
            (exec_s.get("max_drawdown_pct") or 100) <= thresholds["max_drawdown_pct"] and not flags:
        verdict = "PROMISING — RESEARCH ONLY"
        reasons.append("Positive expectancy, profit factor above threshold, acceptable drawdown, no hard overfitting flags.")
    else:
        verdict = "CONTINUE RESEARCH"
        reasons.append("Some evidence is positive but robustness requirements are not fully met.")
    if flags:
        reasons.append("Overfitting flags: " + "; ".join(map(str, flags)))
    return {"verdict": verdict, "reasons": reasons, "thresholds": thresholds,
            "engine_verdict_reference": crit,
            "disclaimer": ("Even a PROMISING verdict is research-only and does not affect "
                           "the live system. Never deploy based on this report.")}


# ── orchestration ────────────────────────────────────────────────────────────

def build_report(exp_dir):
    t0 = time.time()
    status, config, result, analysis, trades_all, ledger = _load(exp_dir)
    trades = _variant_c(trades_all)
    dup_removed = trades.attrs.get("duplicates_removed", 0)
    invalid = 0
    if not trades.empty:
        before = len(trades)
        trades = trades[trades["net_pnl"].notna() & trades["return_pct"].notna()]
        invalid = before - len(trades)

    exec_s = _sec_executive(status, config, result, trades)
    perf = _sec_performance(status, result, trades)
    risk = _sec_risk(result, trades)
    dist = _sec_distribution(trades, ledger)
    conf = _sec_confidence(result, trades)
    fps = _sec_false_positives(analysis, trades, ledger)
    missed = _sec_missed(analysis, ledger)
    feats = _sec_features(analysis, trades, ledger)
    params = _sec_param_sensitivity(analysis, status)
    regimes = _sec_regimes(trades, result)
    holding = _sec_holding(trades, ledger)
    dd = _sec_drawdown(result, trades)
    examples = _sec_examples(trades, ledger)
    strengths, weaknesses = _sec_strengths_weaknesses(exec_s, perf, risk, conf, regimes)
    recommendations = _sec_recommendations(exec_s, weaknesses, params, conf, regimes)
    nexts = _sec_next_experiments(exec_s, status, params, regimes)
    final = _sec_final_verdict(exec_s, status)
    la = result.get("lookahead_audit") or {}
    cfg = result.get("config") or {}
    diagnostics = {
        "source_trade_count": int(len(trades_all)),
        "variant_c_trades_used": int(len(trades)),
        "duplicate_rows_removed": int(dup_removed),
        "invalid_rows_ignored": int(invalid),
        "ledger_rows": int(len(ledger)),
        "missing_sources": [name for name, present in
                            (("analysis.json", analysis is not None),
                             ("research_ledger.csv", not ledger.empty),
                             ("wf_trades.csv", not trades_all.empty),
                             ("wf_result.json", bool(result))) if not present],
        "windows_used": len(result.get("windows") or []),
        "date_boundaries": {"start": cfg.get("start_date"), "end": cfg.get("end_date")},
        "cost_model": cfg.get("cost_model"),
        "intrabar_rule": result.get("intrabar_rule_label") or cfg.get("intrabar_rule"),
        "lookahead_audit": {"decisions_logged": la.get("decisions_logged"),
                            "violations": la.get("violations"),
                            "status": ("CLEAN" if la.get("violations") == 0 else
                                       ("VIOLATIONS" if la.get("violations") else "UNKNOWN"))},
        "generation_seconds": round(time.time() - t0, 2),
    }
    return {
        "schema_version": REPORT_SCHEMA_VERSION,
        "experiment_id": status.get("id") or os.path.basename(exp_dir),
        "generated_at": _now_iso(),
        "disclaimer": DISCLAIMER,
        "research_only": True,
        "live_orders_affected": False,
        "safety": {"research_only": True, "affects_live_trading": False,
                   "affects_paper_trading": False, "auto_promotion": False},
        "executive_summary": exec_s,
        "performance_analysis": perf,
        "risk_analysis": risk,
        "trade_distribution": dist,
        "confidence_analysis": conf,
        "false_positive_analysis": fps,
        "missed_opportunity_analysis": missed,
        "feature_analysis": feats,
        "parameter_sensitivity": params,
        "regime_analysis": regimes,
        "holding_period_analysis": holding,
        "drawdown_analysis": dd,
        "trade_examples": examples,
        "strengths": strengths,
        "weaknesses": weaknesses,
        "recommendations": recommendations,
        "next_experiments": nexts,
        "final_verdict": final,
        "diagnostics": diagnostics,
    }


# ── persistence / lifecycle ──────────────────────────────────────────────────

def _reports_dir(exp_dir):
    return os.path.join(exp_dir, "reports")


def _read_index(exp_dir):
    p = os.path.join(_reports_dir(exp_dir), "index.json")
    if os.path.exists(p):
        try:
            with open(p) as f:
                return json.load(f)
        except Exception:
            pass
    return {"versions": []}


def _write_index(exp_dir, idx):
    os.makedirs(_reports_dir(exp_dir), exist_ok=True)
    p = os.path.join(_reports_dir(exp_dir), "index.json")
    tmp = p + ".tmp"
    with open(tmp, "w") as f:
        json.dump(idx, f, indent=1)
    os.replace(tmp, p)


def _latest(idx, completed_only=True):
    versions = idx.get("versions") or []
    pool = [v for v in versions if v.get("status") == "COMPLETED"] if completed_only else versions
    return pool[-1] if pool else None


def generate_report(exp_dir, force=False):
    """Generate (or skip if unchanged) a research report. Never raises to caller
    in a way that could affect experiment state — errors are recorded in the index."""
    exp_id = os.path.basename(exp_dir.rstrip("/"))
    if not os.path.isdir(exp_dir):
        return {"success": False, "error": {"code": "NOT_FOUND",
                                            "message": "Experiment not found.",
                                            "details": exp_id}}
    status_path = os.path.join(exp_dir, "status.json")
    exp_status = None
    if os.path.exists(status_path):
        try:
            with open(status_path) as f:
                exp_status = (json.load(f) or {}).get("status")
        except Exception:
            pass
    if exp_status in ("queued", "running"):
        return {"success": False, "error": {
            "code": "EXPERIMENT_NOT_FINISHED",
            "message": "Reports are only generated after an experiment finishes.",
            "details": f"status={exp_status}"}}
    src_hash = _result_hash(exp_dir)
    idx = _read_index(exp_dir)
    latest = _latest(idx)
    if latest and latest.get("source_result_hash") == src_hash and not force:
        return {"success": True, "skipped": True, "reason": "unchanged",
                "version": latest["version"], "source_result_hash": src_hash}
    version = (idx["versions"][-1]["version"] + 1) if idx.get("versions") else 1
    entry = {"version": version, "status": "GENERATING", "generated_at": _now_iso(),
             "source_result_hash": src_hash, "error": None}
    idx.setdefault("versions", []).append(entry)
    _write_index(exp_dir, idx)
    try:
        report = build_report(exp_dir)
        report["report_version"] = version
        report["source_result_hash"] = src_hash
        path = os.path.join(_reports_dir(exp_dir), f"report_v{version}.json")
        tmp = path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(report, f, indent=1, default=str)
        os.replace(tmp, path)
        entry["status"] = "COMPLETED"
        entry["generated_at"] = _now_iso()
        _write_index(exp_dir, idx)
        return {"success": True, "version": version, "source_result_hash": src_hash,
                "generation_seconds": report["diagnostics"]["generation_seconds"]}
    except Exception as exc:  # report failure never fails the experiment
        entry["status"] = "FAILED"
        entry["error"] = f"{type(exc).__name__}: {exc}"[:500]
        _write_index(exp_dir, idx)
        return {"success": False, "error": {
            "code": "REPORT_GENERATION_FAILED",
            "message": "Research report generation failed.",
            "details": entry["error"]}}


def get_report(exp_dir, version=None):
    idx = _read_index(exp_dir)
    if version is None:
        latest = _latest(idx)
        if not latest:
            failed = _latest(idx, completed_only=False)
            return {"success": False, "error": {
                "code": "REPORT_NOT_FOUND",
                "message": "No completed research report exists for this experiment.",
                "details": (failed or {}).get("error") or "Generate one first."}}
        version = latest["version"]
    p = os.path.join(_reports_dir(exp_dir), f"report_v{version}.json")
    if not os.path.exists(p):
        return {"success": False, "error": {"code": "REPORT_NOT_FOUND",
                                            "message": "Report version not found.",
                                            "details": f"v{version}"}}
    with open(p) as f:
        report = json.load(f)
    return {"success": True, "report": report}


def report_status(exp_dir):
    idx = _read_index(exp_dir)
    latest_any = _latest(idx, completed_only=False)
    latest_ok = _latest(idx)
    if not latest_any:
        return {"success": True, "status": "NONE", "versions": []}
    state = latest_any["status"]
    outdated = False
    if latest_ok:
        outdated = latest_ok.get("source_result_hash") != _result_hash(exp_dir)
    display = "OUTDATED" if (state == "COMPLETED" and outdated) else state
    return {"success": True, "status": display,
            "latest_version": latest_any.get("version"),
            "latest_completed_version": (latest_ok or {}).get("version"),
            "error": latest_any.get("error"),
            "generated_at": latest_any.get("generated_at"),
            "outdated": outdated,
            "versions": [{k: v.get(k) for k in ("version", "status", "generated_at", "error")}
                         for v in idx.get("versions") or []]}
