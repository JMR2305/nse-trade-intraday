"""Phase 6.5 — Meta-Learning, Failure Attribution & Strategy-Gating Intelligence.

STRICTLY RESEARCH ONLY. This module:
  * reads completed out-of-sample experiment results (never live/paper state),
  * never places orders, never modifies trading decisions or strategy selection,
  * never auto-promotes anything — all outputs are research candidates,
  * uses only data available before each out-of-sample decision (audited via
    max_data_timestamp <= entry_date per trade).

Dimensions NOT present in stored trade records (ADX band, ATR percentile,
volatility regime, volume ratio, EMA alignment, trend direction, RSI band,
MACD histogram state, entry subtype) are reported as NOT AVAILABLE — values
are never fabricated.
"""
import hashlib
import json
import os
import statistics
from datetime import datetime, timezone

import pandas as pd

from research_intelligence import _completed_experiments

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
EXPORT_DIR = os.path.join(BASE_DIR, "exports")

MODEL_VERSION = "meta-learning-1.0"

SAFETY = {
    "research_only": True,
    "affects_live_trading": False,
    "affects_paper_trading": False,
    "auto_promotion": False,
    "label": "RESEARCH CANDIDATE — HUMAN APPROVAL REQUIRED",
    "note": "Meta-learning findings are statistical associations from historical "
            "out-of-sample research trades. Nothing here modifies live or paper "
            "trading, and no rule or mutation is ever activated automatically.",
}

UNAVAILABLE_DIMENSIONS = [
    "entry_subtype", "adx_band", "atr_percentile", "volatility_regime",
    "volume_ratio", "ema_alignment", "trend_direction", "rsi_band",
    "macd_histogram_state",
]

# ── helpers ───────────────────────────────────────────────────────────────────

def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _r(v, nd=2):
    try:
        f = float(v)
        if f != f or f in (float("inf"), float("-inf")):
            return None
        return round(f, nd)
    except (TypeError, ValueError):
        return None


def evidence_label(n, windows=1, positive_windows=None):
    """Conservative evidence label. Small samples are never STRONG."""
    n = int(n or 0)
    if n < 10:
        return "INSUFFICIENT"
    if n < 20:
        return "VERY LOW"
    if n < 30:
        return "LOW"
    if n < 100 or windows < 2:
        return "MODERATE"
    if positive_windows is not None and positive_windows < 2:
        return "MODERATE"
    return "STRONG"


def _conf_band(c):
    try:
        c = float(c)
    except (TypeError, ValueError):
        return "NOT AVAILABLE"
    if c < 55:
        return "<55"
    if c < 65:
        return "55-64"
    if c < 75:
        return "65-74"
    if c < 85:
        return "75-84"
    return "85+"


def _hold_band(d):
    try:
        d = float(d)
    except (TypeError, ValueError):
        return "NOT AVAILABLE"
    if d <= 2:
        return "0-2d"
    if d <= 5:
        return "3-5d"
    if d <= 10:
        return "6-10d"
    if d <= 20:
        return "11-20d"
    return ">20d"


def _gap_band(g):
    try:
        g = float(g)
    except (TypeError, ValueError):
        return "NOT AVAILABLE"
    if g <= -2:
        return "gap<=-2%"
    if g < -0.5:
        return "-2%..-0.5%"
    if g <= 0.5:
        return "-0.5%..0.5%"
    if g <= 2:
        return "0.5%..2%"
    return "gap>2%"


DIMENSIONS = [
    ("market_regime", "Market regime", lambda t: t.get("market_regime") or "NOT AVAILABLE"),
    ("sector", "Sector", lambda t: t.get("sector") or "NOT AVAILABLE"),
    ("symbol", "Stock", lambda t: t.get("symbol") or "NOT AVAILABLE"),
    ("confidence_band", "Confidence band", lambda t: _conf_band(t.get("calibrated_confidence", t.get("confidence")))),
    ("holding_band", "Holding period", lambda t: _hold_band(t.get("holding_days"))),
    ("exit_reason", "Exit reason", lambda t: t.get("exit_reason") or "NOT AVAILABLE"),
    ("gap_band", "Opening gap", lambda t: _gap_band(t.get("gap_pct"))),
    ("month", "Time period (month)", lambda t: str(t.get("entry_date") or "")[:7] or "NOT AVAILABLE"),
    ("window", "Experiment window", lambda t: t.get("window") or "NOT AVAILABLE"),
]


# ── data loading + no-lookahead audit ────────────────────────────────────────

def _load_all_trades():
    """All OOS trades across completed experiments + no-lookahead audit."""
    frames = []
    exp_ids = []
    for exp_id, _d, _s, _c, df, _r2 in _completed_experiments():
        if df is None or df.empty:
            continue
        f = df.copy()
        f["__exp"] = exp_id
        frames.append(f)
        exp_ids.append(exp_id)
    if not frames:
        return pd.DataFrame(), [], {"status": "NOT APPLICABLE", "checked": 0, "violations": 0,
                                    "detail": "No completed experiments with trades."}
    allt = pd.concat(frames, ignore_index=True)
    for col in ("net_pnl", "gross_pnl", "total_costs", "return_pct", "holding_days",
                "gap_pct", "calibrated_confidence", "confidence", "mae_pct", "mfe_pct"):
        if col in allt.columns:
            allt[col] = pd.to_numeric(allt[col], errors="coerce")
    # Deduplicate exact duplicate trade records (same exp/symbol/entry/exit)
    dedupe_cols = [c for c in ("__exp", "symbol", "entry_date", "exit_date", "strategy_name") if c in allt.columns]
    before = len(allt)
    allt = allt.drop_duplicates(subset=dedupe_cols, keep="first").reset_index(drop=True)
    dupes_removed = before - len(allt)

    # No-lookahead audit: decision data must predate entry.
    checked = violations = 0
    if "max_data_timestamp" in allt.columns and "entry_date" in allt.columns:
        mdt = pd.to_datetime(allt["max_data_timestamp"], errors="coerce")
        ent = pd.to_datetime(allt["entry_date"], errors="coerce")
        mask = mdt.notna() & ent.notna()
        checked = int(mask.sum())
        violations = int((mdt[mask] > ent[mask]).sum())
    audit = {
        "status": ("NOT AVAILABLE" if checked == 0 else "PASS" if violations == 0 else "FAIL"),
        "checked": checked, "violations": violations,
        "duplicates_removed": dupes_removed,
        "detail": "Each trade's max_data_timestamp must be on or before its entry_date "
                  "(only pre-decision data used).",
    }
    return allt, sorted(exp_ids), audit


def _data_hash(df):
    if df is None or df.empty:
        return None
    key_cols = [c for c in ("__exp", "symbol", "entry_date", "net_pnl") if c in df.columns]
    payload = df[key_cols].astype(str).to_csv(index=False)
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def _grp_stats(g):
    n = len(g)
    pnl = g["net_pnl"].dropna()
    wins = int((pnl > 0).sum())
    gp = float(pnl[pnl > 0].sum())
    gl = abs(float(pnl[pnl < 0].sum()))
    return {
        "trades": n,
        "expectancy_rs": _r(pnl.mean()) if n else None,
        "win_rate": _r(wins / n * 100, 1) if n else None,
        "net_pnl": _r(pnl.sum()),
        "profit_factor": _r(gp / gl) if gl > 0 else None,
        "windows": int(g["window"].nunique()) if "window" in g.columns else 1,
    }


# ── 1. Condition analysis / uplift ───────────────────────────────────────────

def _condition_uplift(strat_df, min_n=5):
    """Per-dimension per-value expectancy vs the complement (identical population)."""
    rows = []
    total = len(strat_df)
    if total == 0:
        return rows
    base_exp = _r(strat_df["net_pnl"].mean())
    for dim_key, dim_label, fn in DIMENSIONS:
        vals = strat_df.apply(lambda t: fn(t), axis=1)
        for v, idx in vals.groupby(vals).groups.items():
            if v == "NOT AVAILABLE":
                continue
            sub = strat_df.loc[idx]
            rest = strat_df.drop(index=idx)
            if len(sub) < min_n:
                continue
            s_in, s_out = _grp_stats(sub), (_grp_stats(rest) if len(rest) else None)
            uplift = None
            if s_out and s_in["expectancy_rs"] is not None and s_out["expectancy_rs"] is not None:
                uplift = _r(s_in["expectancy_rs"] - s_out["expectancy_rs"])
            rows.append({
                "dimension": dim_key, "dimension_label": dim_label, "condition": str(v),
                "trades_with": s_in["trades"], "trades_without": (s_out or {}).get("trades", 0),
                "expectancy_with": s_in["expectancy_rs"],
                "expectancy_without": (s_out or {}).get("expectancy_rs"),
                "uplift_rs": uplift,
                "win_rate_with": s_in["win_rate"], "profit_factor_with": s_in["profit_factor"],
                "windows_with": s_in["windows"],
                "evidence": evidence_label(s_in["trades"], s_in["windows"]),
                "baseline_expectancy": base_exp,
                "wording": "associated with",  # not causal
            })
    rows.sort(key=lambda x: -(abs(x["uplift_rs"]) if x["uplift_rs"] is not None else 0))
    return rows


# ── robustness checks for an insight (strategy-level) ────────────────────────

def _robustness_checks(g):
    checks = []
    n = len(g)

    def chk(name, passed, detail):
        checks.append({"check": name, "passed": bool(passed), "detail": detail})

    chk("Minimum 30 OOS trades", n >= 30, f"{n} trades")
    wins = g.groupby("window")["net_pnl"].sum() if "window" in g.columns else pd.Series(dtype=float)
    nw = len(wins)
    posw = int((wins > 0).sum())
    chk("Minimum 2 test windows", nw >= 2, f"{nw} windows")
    chk("Positive expectancy in >1 window", posw >= 2, f"{posw}/{nw} windows positive")
    pnl = g["net_pnl"].dropna()
    eq = pnl.cumsum()
    dd = float((eq.cummax() - eq).max()) if len(eq) else 0.0
    invested = float(g["invested"].mean()) if "invested" in g.columns and g["invested"].notna().any() else None
    dd_ok = invested is None or dd <= invested * 0.5
    chk("Acceptable drawdown", dd_ok, f"peak-to-trough ₹{_r(dd)} on P&L curve")
    gross_pos = pnl[pnl > 0]
    for col, label in (("symbol", "stock"), ("sector", "sector")):
        if col in g.columns and len(gross_pos) > 0:
            share = g.loc[gross_pos.index].groupby(col)["net_pnl"].sum().max() / gross_pos.sum()
            chk(f"No severe {label} concentration", share < 0.6,
                f"top {label} = {_r(share * 100, 1)}% of winning P&L")
        else:
            chk(f"No severe {label} concentration", False, "NOT AVAILABLE")
    if "entry_date" in g.columns and len(gross_pos) > 0:
        months = g.loc[gross_pos.index, "entry_date"].astype(str).str[:7]
        mshare = g.loc[gross_pos.index].groupby(months)["net_pnl"].sum().max() / gross_pos.sum()
        chk("No single-month dependence", mshare < 0.6,
            f"top month = {_r(mshare * 100, 1)}% of winning P&L")
    if len(pnl) >= 5:
        top5 = pnl.nlargest(5).sum()
        net = pnl.sum()
        dep = net > 0 and (net - top5) <= 0
        chk("No top-5-trade dependence", not dep,
            f"net ₹{_r(net)} vs ₹{_r(net - top5)} without top 5 trades")
    # Cost/slippage stress: +50% costs
    if "total_costs" in g.columns and "gross_pnl" in g.columns:
        stressed = float((g["gross_pnl"] - g["total_costs"] * 1.5).sum())
        chk("Survives cost & slippage stress (+50% costs)", stressed > 0,
            f"net under stress ₹{_r(stressed)}")
    return checks


# ── 2. Failure attribution ────────────────────────────────────────────────────

def _attribute(g, name):
    n = len(g)
    s = _grp_stats(g)
    gross = float(g["gross_pnl"].sum()) if "gross_pnl" in g.columns else None
    net = float(g["net_pnl"].sum())
    costs = float(g["total_costs"].sum()) if "total_costs" in g.columns else None
    pnl = g["net_pnl"].dropna()
    eq = pnl.cumsum()
    max_dd = _r(float((eq.cummax() - eq).max())) if len(eq) else None

    # Calibration: |avg calibrated prob − actual win rate|
    calib_err = None
    if "calibrated_probability" in g.columns and g["calibrated_probability"].notna().any():
        cp = pd.to_numeric(g["calibrated_probability"], errors="coerce").dropna()
        if len(cp) >= 10:
            calib_err = _r(abs(float(cp.mean()) - (s["win_rate"] or 0) / 100), 3)

    reasons = []
    if n < 10:
        reasons.append(("INSUFFICIENT_EVIDENCE", f"Only {n} OOS trades — no reliable conclusions."))
    else:
        if gross is not None and gross <= 0:
            reasons.append(("NEGATIVE_GROSS_EDGE",
                            f"Gross P&L ₹{_r(gross)} ≤ 0 before costs — entries/exits lack edge."))
        elif gross is not None and gross > 0 and net <= 0:
            reasons.append(("COST_SENSITIVE",
                            f"Gross ₹{_r(gross)} positive but net ₹{_r(net)} ≤ 0 — costs (₹{_r(costs)}) consumed the edge."))
        # regime mismatch
        if "market_regime" in g.columns:
            by_reg = g.groupby("market_regime")["net_pnl"].agg(["mean", "count"])
            bad = by_reg[(by_reg["count"] >= 5) & (by_reg["mean"] < 0)]
            good = by_reg[(by_reg["count"] >= 5) & (by_reg["mean"] > 0)]
            if len(bad) and len(good):
                reasons.append(("REGIME_MISMATCH",
                                f"Positive expectancy in {', '.join(good.index)} but negative in "
                                f"{', '.join(bad.index)} — associated with regime, not universal."))
        # exits
        if "exit_reason" in g.columns:
            by_exit = g.groupby("exit_reason")["net_pnl"].agg(["mean", "count"])
            worst = by_exit[by_exit["count"] >= 5].sort_values("mean")
            if len(worst) and worst.iloc[0]["mean"] < 0 and str(worst.index[0]).lower().find("time") >= 0:
                reasons.append(("POOR_EXIT_LOGIC",
                                f"Time-based exits average ₹{_r(worst.iloc[0]['mean'])}/trade — "
                                "trades are being held to expiry rather than exited on signal."))
        # premature exits: MFE much larger than realized on losers
        if "mfe_pct" in g.columns and g["mfe_pct"].notna().any():
            losers = g[g["net_pnl"] < 0]
            if len(losers) >= 5 and float(losers["mfe_pct"].mean() or 0) > 2.0:
                reasons.append(("POOR_ENTRY_FILTER",
                                f"Losing trades averaged +{_r(losers['mfe_pct'].mean())}% open profit "
                                "before ending negative — associated with exit timing/entry quality."))
        if calib_err is not None and calib_err > 0.15:
            reasons.append(("OVERCONFIDENT",
                            f"Average calibrated probability differs from realized win rate by {calib_err} (>0.15)."))
        # concentration
        pos = pnl[pnl > 0]
        if len(pos) > 0:
            for col, code in (("symbol", "STOCK_CONCENTRATION"), ("sector", "SECTOR_CONCENTRATION")):
                if col in g.columns:
                    top = g.loc[pos.index].groupby(col)["net_pnl"].sum().sort_values(ascending=False)
                    share = float(top.iloc[0]) / float(pos.sum())
                    if share >= 0.6:
                        reasons.append((code, f"'{top.index[0]}' contributes {_r(share * 100, 1)}% of winning P&L."))
        if n >= 10:
            top5 = pnl.nlargest(min(5, len(pnl))).sum()
            if net > 0 and (net - float(top5)) <= 0:
                reasons.append(("FEW_TRADE_DEPENDENT",
                                f"Profit disappears without the top 5 trades (₹{_r(net)} → ₹{_r(net - float(top5))})."))
        if max_dd is not None and "invested" in g.columns and g["invested"].notna().any():
            if max_dd > float(g["invested"].mean()) * 0.5:
                reasons.append(("EXCESSIVE_DRAWDOWN",
                                f"P&L-curve drawdown ₹{max_dd} exceeds 50% of average position size."))
        wins = g.groupby("window")["net_pnl"].sum() if "window" in g.columns else pd.Series(dtype=float)
        if len(wins) >= 2 and int((wins > 0).sum()) < len(wins) / 2:
            reasons.append(("UNSTABLE_ACROSS_WINDOWS",
                            f"Only {int((wins > 0).sum())}/{len(wins)} walk-forward windows positive."))
        if not reasons and net > 0 and n < 30:
            reasons.append(("POSSIBLE_EDGE_REQUIRES_MORE_DATA",
                            f"Positive expectancy on {n} trades — below the 30-trade evidence threshold."))

    is_failure = net <= 0 or (s["profit_factor"] or 0) < 1.0
    checks = _robustness_checks(g)
    broad_or_concentrated = "NOT APPLICABLE"
    if is_failure and n >= 10:
        neg_by_reg = None
        if "market_regime" in g.columns:
            by_reg = g.groupby("market_regime")["net_pnl"].mean()
            neg_by_reg = int((by_reg < 0).sum()), len(by_reg)
        if neg_by_reg and neg_by_reg[1] > 0:
            broad_or_concentrated = ("BROAD" if neg_by_reg[0] >= max(2, neg_by_reg[1] - 1)
                                     else "CONCENTRATED")

    return {
        "strategy": name,
        "is_failure": bool(is_failure),
        "primary_reason": reasons[0][0] if reasons else ("NONE_DETECTED" if not is_failure else "INSUFFICIENT_EVIDENCE"),
        "primary_detail": reasons[0][1] if reasons else None,
        "secondary_reasons": [{"code": c, "detail": d} for c, d in reasons[1:6]],
        "sample_size": n,
        "evidence": evidence_label(n, s["windows"]),
        "expectancy_rs": s["expectancy_rs"], "profit_factor": s["profit_factor"],
        "win_rate": s["win_rate"], "max_drawdown_rs": max_dd,
        "calibration_error": calib_err,
        "gross_pnl": _r(gross), "net_pnl": _r(net), "total_costs": _r(costs),
        "costs_caused_failure": bool(gross is not None and gross > 0 and net <= 0),
        "negative_gross_edge": bool(gross is not None and gross <= 0),
        "failure_breadth": broad_or_concentrated,
        "robustness_checks": checks,
        "robustness_passed": sum(1 for c in checks if c["passed"]),
        "robustness_total": len(checks),
    }


# ── 3/5A. Strategy health + research action ─────────────────────────────────

def _research_action(attr, s):
    n = attr["sample_size"]
    if n < 10:
        return "REQUIRE MORE DATA"
    pr = attr["primary_reason"]
    if pr == "NEGATIVE_GROSS_EDGE" and attr["evidence"] in ("MODERATE", "STRONG"):
        return "REJECT"
    if pr == "COST_SENSITIVE":
        return "MODIFY EXIT LOGIC"
    if pr == "REGIME_MISMATCH":
        return "RESTRICT BY REGIME"
    if pr == "POOR_ENTRY_FILTER":
        return "MODIFY ENTRY FILTER"
    if pr == "POOR_EXIT_LOGIC":
        return "MODIFY EXIT LOGIC"
    if pr in ("FEW_TRADE_DEPENDENT", "UNSTABLE_ACROSS_WINDOWS"):
        return "KEEP RESEARCHING"
    if pr == "POSSIBLE_EDGE_REQUIRES_MORE_DATA":
        return "REQUIRE MORE DATA"
    if not attr["is_failure"] and (s.get("profit_factor") or 0) >= 1.1 and attr["evidence"] in ("MODERATE", "STRONG"):
        return "PROMISING — HUMAN REVIEW REQUIRED"
    if attr["is_failure"] and attr["evidence"] in ("MODERATE", "STRONG"):
        return "ARCHIVE"
    return "KEEP RESEARCHING"


def cmd_health():
    allt, exp_ids, audit = _load_all_trades()
    if allt.empty:
        return {"success": True, "strategies": [], "no_lookahead_audit": audit,
                "note": "INSUFFICIENT DATA — no completed experiments with trades.",
                "safety": SAFETY}
    out = []
    for name, g in allt.groupby("strategy_name"):
        s = _grp_stats(g)
        attr = _attribute(g, str(name))
        by_reg = (g.groupby("market_regime")["net_pnl"].agg(["mean", "count"])
                  if "market_regime" in g.columns else pd.DataFrame())
        by_reg = by_reg[by_reg["count"] >= 3] if len(by_reg) else by_reg
        best = worst = None
        if len(by_reg):
            best = {"regime": str(by_reg["mean"].idxmax()), "expectancy_rs": _r(by_reg["mean"].max()),
                    "trades": int(by_reg.loc[by_reg["mean"].idxmax(), "count"])}
            worst = {"regime": str(by_reg["mean"].idxmin()), "expectancy_rs": _r(by_reg["mean"].min()),
                     "trades": int(by_reg.loc[by_reg["mean"].idxmin(), "count"])}
        pnl = g["net_pnl"].dropna()
        eq = pnl.cumsum()
        out.append({
            "strategy": str(name),
            "status": ("FAILING" if attr["is_failure"] else "POSITIVE"),
            "oos_trades": s["trades"], "expectancy_rs": s["expectancy_rs"],
            "profit_factor": s["profit_factor"], "win_rate": s["win_rate"],
            "net_pnl": s["net_pnl"],
            "max_drawdown_rs": _r(float((eq.cummax() - eq).max())) if len(eq) else None,
            "evidence": attr["evidence"],
            "dominant_failure_reason": attr["primary_reason"] if attr["is_failure"] else None,
            "best_regime": best, "worst_regime": worst,
            "recommended_action": _research_action(attr, s),
            "windows": s["windows"],
        })
    out.sort(key=lambda x: -(x["net_pnl"] or 0))
    return {"success": True, "strategies": out, "no_lookahead_audit": audit,
            "source_experiments": exp_ids, "safety": SAFETY}


def cmd_failures():
    allt, exp_ids, audit = _load_all_trades()
    if allt.empty:
        return {"success": True, "reports": [], "no_lookahead_audit": audit, "safety": SAFETY}
    reports = []
    for name, g in allt.groupby("strategy_name"):
        attr = _attribute(g, str(name))
        uplift = _condition_uplift(g)
        attr["top_losing_conditions"] = [u for u in uplift if (u["expectancy_with"] or 0) < 0][:5]
        attr["top_profitable_conditions"] = [u for u in uplift if (u["expectancy_with"] or 0) > 0][:5]
        # confidence-band performance
        bands = []
        for b, sub in g.groupby(g.apply(lambda t: _conf_band(t.get("calibrated_confidence", t.get("confidence"))), axis=1)):
            st = _grp_stats(sub)
            bands.append({"band": b, **st, "evidence": evidence_label(st["trades"], st["windows"])})
        attr["confidence_band_performance"] = sorted(bands, key=lambda x: x["band"])
        # affected slices
        for col, key in (("market_regime", "affected_regimes"), ("sector", "affected_sectors")):
            if col in g.columns:
                by = g.groupby(col)["net_pnl"].agg(["mean", "count"])
                attr[key] = [{"value": str(i), "expectancy_rs": _r(r["mean"]), "trades": int(r["count"])}
                             for i, r in by[(by["count"] >= 3) & (by["mean"] < 0)].iterrows()]
        by_h = g.groupby(g.apply(lambda t: _hold_band(t.get("holding_days")), axis=1))["net_pnl"].agg(["mean", "count"])
        attr["affected_holding_periods"] = [
            {"band": str(i), "expectancy_rs": _r(r["mean"]), "trades": int(r["count"])}
            for i, r in by_h[(by_h["count"] >= 3) & (by_h["mean"] < 0)].iterrows()]
        reports.append(attr)
    reports.sort(key=lambda x: (not x["is_failure"], -(x["sample_size"] or 0)))
    return {"success": True, "reports": reports, "no_lookahead_audit": audit,
            "unavailable_dimensions": UNAVAILABLE_DIMENSIONS, "safety": SAFETY}


# ── eligibility policies + map ───────────────────────────────────────────────

REGIME_COLS = ["Bullish", "Bearish", "Neutral-Bullish", "Neutral-Bearish", "Sideways",
               "High Volatility", "Low Volatility"]


def cmd_eligibility():
    allt, exp_ids, audit = _load_all_trades()
    if allt.empty:
        return {"success": True, "policies": [], "matrix": [], "no_lookahead_audit": audit, "safety": SAFETY}
    policies, matrix = [], []
    for name, g in allt.groupby("strategy_name"):
        uplift = _condition_uplift(g)
        checks = _robustness_checks(g)
        robust_ok = sum(1 for c in checks if c["passed"]) >= max(1, len(checks) - 3)
        elig_rules, inelig_rules = [], []
        for u in uplift:
            if u["dimension"] in ("symbol", "month", "window"):
                continue  # too specific to gate on
            rule = {
                "condition": f"{u['dimension_label']} = {u['condition']}",
                "threshold": u["condition"],
                "source_metric": "net expectancy per trade (OOS)",
                "sample_size": u["trades_with"],
                "expectancy_with": u["expectancy_with"],
                "expectancy_without": u["expectancy_without"],
                "uplift_rs": u["uplift_rs"],
                "confidence": u["evidence"],
                "passed_robustness": bool(robust_ok and u["evidence"] not in ("INSUFFICIENT", "VERY LOW")),
                "wording": "associated with",
            }
            if (u["expectancy_with"] or 0) > 0 and (u["uplift_rs"] or 0) > 0:
                elig_rules.append(rule)
            elif (u["expectancy_with"] or 0) < 0:
                inelig_rules.append(rule)
        policies.append({
            "strategy": str(name),
            "label": SAFETY["label"],
            "eligible_when": elig_rules[:8],
            "ineligible_when": inelig_rules[:8],
            "minimum_sample_met": len(g) >= 30,
            "note": "Rules are research candidates derived from historical association — "
                    "not activated anywhere, human approval required.",
        })
        # matrix row
        cells = {}
        by_reg = g.groupby("market_regime") if "market_regime" in g.columns else []
        reg_stats = {str(k): _grp_stats(v) for k, v in by_reg} if len(g) else {}
        for col in REGIME_COLS:
            st = reg_stats.get(col)
            if not st:
                cells[col] = {"state": "insufficient evidence", "trades": 0,
                              "expectancy_rs": None, "profit_factor": None}
                continue
            n = st["trades"]
            if n < 10:
                state = "insufficient evidence"
            elif (st["expectancy_rs"] or 0) > 0 and (st["profit_factor"] or 0) >= 1.0:
                state = "research-only" if n < 30 else "eligible (research)"
            else:
                state = "ineligible"
            cells[col] = {"state": state, "trades": n,
                          "expectancy_rs": st["expectancy_rs"], "profit_factor": st["profit_factor"]}
        matrix.append({"strategy": str(name), "cells": cells})
    return {"success": True, "policies": policies, "matrix": matrix,
            "regimes": REGIME_COLS, "no_lookahead_audit": audit,
            "note": "'High/Low Volatility' columns show insufficient evidence — volatility regime "
                    "is not recorded in stored trade data (NOT AVAILABLE, not fabricated).",
            "safety": SAFETY}


# ── improvements + recommended mutations (top 3, evidence-backed) ────────────

def cmd_improvements():
    allt, exp_ids, audit = _load_all_trades()
    if allt.empty:
        return {"success": True, "suggestions": [], "no_lookahead_audit": audit, "safety": SAFETY}
    out = []
    for name, g in allt.groupby("strategy_name"):
        uplift = _condition_uplift(g)
        sugg = []
        for u in uplift:
            if u["evidence"] in ("INSUFFICIENT",):
                continue
            imp = None
            if u["dimension"] == "gap_band" and (u["expectancy_with"] or 0) < 0:
                imp = f"Avoid entries when opening gap is {u['condition']}"
                mut_param, mut_val = "gap_filter", f"exclude {u['condition']}"
            elif u["dimension"] == "market_regime" and (u["expectancy_with"] or 0) < 0:
                imp = f"Avoid {u['condition']} regime"
                mut_param, mut_val = "regime_restriction", f"exclude {u['condition']}"
            elif u["dimension"] == "market_regime" and (u["uplift_rs"] or 0) > 0:
                imp = f"Restrict to {u['condition']} regime"
                mut_param, mut_val = "regime_restriction", f"only {u['condition']}"
            elif u["dimension"] == "confidence_band" and (u["uplift_rs"] or 0) > 0 and u["condition"] in ("65-74", "75-84", "85+"):
                imp = f"Require calibrated confidence in band {u['condition']}"
                mut_param, mut_val = "confidence_threshold", u["condition"]
            elif u["dimension"] == "holding_band" and (u["uplift_rs"] or 0) > 0:
                imp = f"Target holding period {u['condition']}"
                mut_param, mut_val = "holding_period", u["condition"]
            elif u["dimension"] == "exit_reason" and (u["expectancy_with"] or 0) < 0:
                imp = f"Re-examine exits of type '{u['condition']}' (negative expectancy)"
                mut_param, mut_val = "exit_rule_adjustment", f"review {u['condition']}"
            elif u["dimension"] == "sector" and (u["expectancy_with"] or 0) < 0 and u["evidence"] not in ("VERY LOW",):
                imp = f"Avoid sector {u['condition']}"
                mut_param, mut_val = "sector_restriction", f"exclude {u['condition']}"
            if not imp:
                continue
            sugg.append({
                "suggestion": imp,
                "historical_uplift_rs": u["uplift_rs"],
                "expectancy_with": u["expectancy_with"], "expectancy_without": u["expectancy_without"],
                "sample_size": u["trades_with"], "evidence": u["evidence"],
                "mutation_parameter": mut_param, "mutation_value": mut_val,
                "known_risk": "Restricting conditions reduces trade count and may overfit to "
                              "historical periods; association is not causation.",
                "hypothesis": f"If '{imp}', OOS expectancy should improve by roughly "
                              f"₹{u['uplift_rs']}/trade based on {u['trades_with']} historical trades.",
            })
        # dedupe by (parameter,value), keep top 3 by |uplift|*evidence
        seen = set()
        deduped = []
        for s2 in sorted(sugg, key=lambda x: -abs(x["historical_uplift_rs"] or 0)):
            k = (s2["mutation_parameter"], s2["mutation_value"])
            if k in seen:
                continue
            seen.add(k)
            deduped.append(s2)
        out.append({"strategy": str(name), "suggestions": deduped[:3],
                    "note": "Top 3 evidence-supported changes only. Draft research proposals — "
                            "human approval required."})
    return {"success": True, "suggestions": out, "no_lookahead_audit": audit, "safety": SAFETY}


def cmd_create_mutation(strategy_name, parameter, value, evidence_note=""):
    """Create a DRAFT research mutation in the Strategy Evolution registry from a
    meta-learning finding. Never activates anything."""
    import fcntl
    import strategy_evolution as se
    lock_path = se.REGISTRY_PATH + ".lock"
    lock_f = open(lock_path, "w")
    try:
        fcntl.flock(lock_f, fcntl.LOCK_EX)
        return _create_mutation_locked(se, strategy_name, parameter, value, evidence_note)
    finally:
        fcntl.flock(lock_f, fcntl.LOCK_UN)
        lock_f.close()


def _create_mutation_locked(se, strategy_name, parameter, value, evidence_note):
    reg = se._load_registry()
    label_to_root = {}
    for e in reg["strategies"]:
        if e["parent_id"] is None:
            label_to_root[e["name"].lower()] = e
    parent = label_to_root.get(str(strategy_name).lower())
    if not parent:
        return {"success": False, "error": f"Strategy '{strategy_name}' not found among baseline strategies."}
    # Idempotency: same (parent, parameter, value) → return the existing entry.
    for e in reg["strategies"]:
        if (e.get("parent_id") == parent["strategy_id"]
                and (e.get("mutation") or {}).get("parameter") == str(parameter)
                and (e.get("mutation") or {}).get("to") == str(value)
                and e.get("status") != "Archived"):
            return {"success": True, "variant": e, "already_exists": True,
                    "note": "An identical draft mutation already exists — returning it instead of duplicating.",
                    "safety": SAFETY}
    import uuid as _uuid
    vid = _uuid.uuid4().hex[:12]
    entry = {
        "strategy_id": vid,
        "name": f"{parent['name']} — {parameter}={value}",
        "base_strategy": parent["base_strategy"],
        "parent_id": parent["strategy_id"],
        "version": max([e["version"] for e in reg["strategies"]
                        if e.get("base_strategy") == parent["base_strategy"]] or [1]) + 1,
        "created_at": _now(),
        "status": "Draft",
        "author": "meta-learning (research)",
        "notes": f"Draft mutation proposed by Meta-Learning. Evidence: {evidence_note or 'see meta-learning report'}. "
                 "Human approval required before any testing or use.",
        "change_summary": f"{parameter}: {value} (meta-learning proposal)",
        "mutation": {
            "parameter": str(parameter), "from": "current", "to": str(value),
            "unit": "meta-learning gate",
            "expected_benefit": evidence_note or "See meta-learning condition uplift analysis.",
            "observed_benefit": None, "observed_drawback": None,
            "confidence_in_recommendation": None,
            "evidence_for": evidence_note or None, "evidence_against": None,
        },
        "config_level": False, "proposed_config": None, "testable_now": False,
        "testing_note": "Meta-learning gating proposal — requires a dedicated research experiment; "
                        "never applied automatically.",
        "linked_experiment_ids": [], "evaluation": None,
    }
    reg["strategies"].append(entry)
    se._save_json(se.REGISTRY_PATH, reg)
    return {"success": True, "variant": entry,
            "note": "Draft created in the research registry only. Archive it any time via evolution status.",
            "safety": SAFETY}


# ── contradictions ────────────────────────────────────────────────────────────

def cmd_contradictions():
    allt, exp_ids, audit = _load_all_trades()
    if allt.empty:
        return {"success": True, "contradictions": [], "no_lookahead_audit": audit, "safety": SAFETY}
    found = []
    latest_regime = None
    if "entry_date" in allt.columns and "market_regime" in allt.columns:
        latest = allt.sort_values("entry_date").iloc[-1]
        latest_regime = str(latest.get("market_regime"))
    for name, g in allt.groupby("strategy_name"):
        s = _grp_stats(g)
        # high confidence but negative expectancy
        conf_col = "calibrated_confidence" if "calibrated_confidence" in g.columns else "confidence"
        hi = g[pd.to_numeric(g[conf_col], errors="coerce") >= 75]
        if len(hi) >= 5 and float(hi["net_pnl"].mean()) < 0:
            found.append({"type": "HIGH_CONFIDENCE_NEGATIVE_EXPECTANCY", "strategy": str(name),
                          "detail": f"{len(hi)} trades with confidence ≥75 average ₹{_r(hi['net_pnl'].mean())}/trade.",
                          "evidence": evidence_label(len(hi))})
        # per-window disagreement (overall positive, majority windows negative)
        wins = g.groupby("window")["net_pnl"].sum() if "window" in g.columns else pd.Series(dtype=float)
        if len(wins) >= 2 and (s["net_pnl"] or 0) > 0 and int((wins > 0).sum()) < len(wins) / 2:
            found.append({"type": "OVERALL_POSITIVE_BUT_WINDOWS_NEGATIVE", "strategy": str(name),
                          "detail": f"Net ₹{s['net_pnl']} positive overall but only "
                                    f"{int((wins > 0).sum())}/{len(wins)} windows positive.",
                          "evidence": evidence_label(s["trades"], len(wins))})
        # few-trade dependence behind a positive headline
        pnl = g["net_pnl"].dropna()
        if (s["net_pnl"] or 0) > 0 and len(pnl) >= 10:
            top5 = float(pnl.nlargest(5).sum())
            if (float(pnl.sum()) - top5) <= 0:
                found.append({"type": "POSITIVE_RETURN_FROM_FEW_TRADES", "strategy": str(name),
                              "detail": f"Reported net ₹{s['net_pnl']} becomes "
                                        f"₹{_r(float(pnl.sum()) - top5)} without the top 5 trades.",
                              "evidence": evidence_label(s["trades"])})
        # good overall but fails in most recent regime
        if latest_regime and "market_regime" in g.columns and (s["expectancy_rs"] or 0) > 0:
            cur = g[g["market_regime"] == latest_regime]
            if len(cur) >= 5 and float(cur["net_pnl"].mean()) < 0:
                found.append({"type": "FAILS_IN_CURRENT_REGIME", "strategy": str(name),
                              "detail": f"Positive overall but ₹{_r(cur['net_pnl'].mean())}/trade in the most "
                                        f"recent observed regime ({latest_regime}).",
                              "evidence": evidence_label(len(cur))})
    # child worse than parent (from evolution A/B tests)
    try:
        import strategy_evolution as se
        for t in se._load_json(se.AB_PATH, []):
            if t.get("winner") == "parent":
                found.append({"type": "CHILD_WORSE_THAN_PARENT",
                              "strategy": t["candidate_strategy"]["name"],
                              "detail": f"A/B test {t['id']}: parent beat candidate "
                                        f"({t.get('confidence')} confidence).",
                              "evidence": t.get("confidence", "LOW")})
    except Exception:
        pass
    return {"success": True, "contradictions": found, "no_lookahead_audit": audit, "safety": SAFETY}


# ── parent/child comparison on identical OOS data ────────────────────────────

def cmd_compare(exp_a, exp_b):
    """Compare two experiments on identical axes (delegates to evolution helpers)."""
    import strategy_evolution as se
    ba, bb = se._exp_bundle(exp_a), se._exp_bundle(exp_b)
    if not ba or not bb:
        return {"success": False, "error": "One or both experiments not found."}
    ma, mb = se._exp_metrics(ba), se._exp_metrics(bb)
    same, diff = se._matched_axes(ba["config"], bb["config"])
    rows = []
    for k, label in [("net_return_pct", "Net return %"), ("expectancy", "Expectancy ₹"),
                     ("profit_factor", "Profit factor"), ("sharpe", "Sharpe"),
                     ("sortino", "Sortino"), ("max_drawdown_pct", "Max drawdown %"),
                     ("win_rate", "Win rate %"), ("trades", "Trade count"),
                     ("total_costs", "Costs ₹"), ("calibration_ece", "Calibration ECE")]:
        rows.append({"metric": label, "a": ma.get(k), "b": mb.get(k)})
    wa, wb = ma.get("window_returns_pct") or [], mb.get("window_returns_pct") or []
    rows.append({"metric": "Positive windows",
                 "a": f"{ma.get('positive_windows')}/{len(wa)}",
                 "b": f"{mb.get('positive_windows')}/{len(wb)}"})
    improved = None
    if ma.get("profit_factor") is not None and mb.get("profit_factor") is not None:
        improved = mb["profit_factor"] > ma["profit_factor"]
    return {"success": True, "experiment_a": exp_a, "experiment_b": exp_b,
            "identical_test_period": len(diff) == 0, "matched_axes": same, "differing_axes": diff,
            "comparison": rows,
            "verdict": ("NOT COMPARABLE — differing axes: " + ", ".join(diff)) if diff else
                       ("B improved on A (profit factor)" if improved else
                        "B did not improve on A (profit factor)" if improved is not None else
                        "INSUFFICIENT DATA"),
            "safety": SAFETY}


# ── exports ───────────────────────────────────────────────────────────────────

def _flatten_tables():
    allt, exp_ids, audit = _load_all_trades()
    health = cmd_health()
    failures = cmd_failures()
    elig = cmd_eligibility()
    impr = cmd_improvements()
    contra = cmd_contradictions()
    uplift_rows = []
    conf_rows, hold_rows, exit_rows, cost_rows, conc_rows, rob_rows = [], [], [], [], [], []
    if not allt.empty:
        for name, g in allt.groupby("strategy_name"):
            for u in _condition_uplift(g):
                uplift_rows.append({"strategy": str(name), **u})
            for band_fn, dest, key in ((lambda t: _conf_band(t.get("calibrated_confidence", t.get("confidence"))), conf_rows, "confidence_band"),
                                       (lambda t: _hold_band(t.get("holding_days")), hold_rows, "holding_band")):
                for b, sub in g.groupby(g.apply(band_fn, axis=1)):
                    st = _grp_stats(sub)
                    dest.append({"strategy": str(name), key: b, **st,
                                 "evidence": evidence_label(st["trades"], st["windows"])})
            if "exit_reason" in g.columns:
                for er, sub in g.groupby("exit_reason"):
                    st = _grp_stats(sub)
                    exit_rows.append({"strategy": str(name), "exit_reason": str(er), **st,
                                      "evidence": evidence_label(st["trades"], st["windows"])})
            gross = float(g["gross_pnl"].sum()) if "gross_pnl" in g.columns else None
            net = float(g["net_pnl"].sum())
            costs = float(g["total_costs"].sum()) if "total_costs" in g.columns else None
            stressed = (float((g["gross_pnl"] - g["total_costs"] * 1.5).sum())
                        if "gross_pnl" in g.columns and "total_costs" in g.columns else None)
            cost_rows.append({"strategy": str(name), "gross_pnl": _r(gross), "net_pnl": _r(net),
                              "total_costs": _r(costs),
                              "net_under_cost_stress_150pct": _r(stressed),
                              "cost_sensitive": bool(gross is not None and gross > 0 and net <= 0)})
            pnl = g["net_pnl"].dropna()
            pos = pnl[pnl > 0]
            for col in ("symbol", "sector", "market_regime"):
                if col in g.columns and len(pos):
                    top = g.loc[pos.index].groupby(col)["net_pnl"].sum().sort_values(ascending=False)
                    conc_rows.append({"strategy": str(name), "dimension": col,
                                      "top_value": str(top.index[0]),
                                      "share_of_winning_pnl_pct": _r(float(top.iloc[0]) / float(pos.sum()) * 100, 1)})
            for c in _robustness_checks(g):
                rob_rows.append({"strategy": str(name), **c})
    mut_rows = []
    for s in impr["suggestions"]:
        for m in s["suggestions"]:
            mut_rows.append({"strategy": s["strategy"], **{k: v for k, v in m.items()}})
    evidence_rows = [{"strategy": h["strategy"], "oos_trades": h["oos_trades"],
                      "windows": h["windows"], "evidence": h["evidence"]}
                     for h in health["strategies"]]
    return {
        "strategy_health": health["strategies"],
        "failure_attribution": [{k: v for k, v in r.items() if k not in ("robustness_checks",)}
                                for r in failures["reports"]],
        "regime_eligibility": elig["matrix"],
        "sector_eligibility": [u for u in uplift_rows if u["dimension"] == "sector"],
        "condition_uplift": uplift_rows,
        "confidence_analysis": conf_rows,
        "holding_period_analysis": hold_rows,
        "exit_reason_analysis": exit_rows,
        "cost_sensitivity": cost_rows,
        "concentration_risk": conc_rows,
        "robustness_checks": rob_rows,
        "contradictions": contra["contradictions"],
        "recommended_mutations": mut_rows,
        "parent_child_comparison": _parent_child_rows(),
        "evidence_summary": evidence_rows,
    }, allt, exp_ids, audit


def _parent_child_rows():
    try:
        import strategy_evolution as se
        rows = []
        for t in se._load_json(se.AB_PATH, []):
            rows.append({"ab_test_id": t["id"], "parent": t["parent_strategy"]["name"],
                         "child": t["candidate_strategy"]["name"], "winner": t["winner"],
                         "confidence": t["confidence"], "controlled": t["controlled"],
                         "identical_test_period": t["controlled"],
                         "parent_pf": (t.get("parent_metrics") or {}).get("profit_factor"),
                         "child_pf": (t.get("candidate_metrics") or {}).get("profit_factor")})
        return rows
    except Exception:
        return []


def cmd_export():
    import csv
    os.makedirs(EXPORT_DIR, exist_ok=True)
    tables, allt, exp_ids, audit = _flatten_tables()
    meta = {
        "generated_at": _now(),
        "source_experiment_ids": exp_ids,
        "source_data_hash": _data_hash(allt),
        "model_version": MODEL_VERSION,
        "no_lookahead_audit": audit,
        "sample_counts": {"total_oos_trades": int(len(allt)),
                          "strategies": int(allt["strategy_name"].nunique()) if not allt.empty else 0},
        "warnings": ([] if not allt.empty else ["No completed experiments — all tables empty."])
                    + [f"Dimension not recorded in trade data: {d}" for d in UNAVAILABLE_DIMENSIONS],
        "research_only_disclaimer": SAFETY["note"],
    }
    bundle = {"meta": meta, "tables": tables, "safety": SAFETY}
    json_path = os.path.join(EXPORT_DIR, "phase65_meta_learning_export.json")
    with open(json_path, "w") as f:
        json.dump(bundle, f, indent=1, default=str)

    csv_path = os.path.join(EXPORT_DIR, "phase65_meta_learning_export.csv")
    n_rows = 0
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["# Phase 6.5 Meta-Learning export", meta["generated_at"],
                    "hash:" + str(meta["source_data_hash"]), meta["model_version"],
                    "no_lookahead:" + audit["status"], "RESEARCH ONLY"])
        for tname, rows in tables.items():
            w.writerow([])
            w.writerow([f"## table: {tname}", f"rows: {len(rows)}"])
            if not rows:
                w.writerow(["(INSUFFICIENT DATA)"])
                continue
            cols = sorted({k for r2 in rows for k in r2.keys()})
            w.writerow(cols)
            for r2 in rows:
                w.writerow([json.dumps(r2.get(c), default=str) if isinstance(r2.get(c), (dict, list))
                            else ("" if r2.get(c) is None else r2.get(c)) for c in cols])
                n_rows += 1

    def esc(s):
        return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    sections = []
    for tname, rows in tables.items():
        if not rows:
            sections.append(f"<h2>{esc(tname)}</h2><p><i>INSUFFICIENT DATA</i></p>")
            continue
        cols = sorted({k for r2 in rows for k in r2.keys()})
        body = "".join("<tr>" + "".join(
            f"<td>{esc(json.dumps(r2.get(c), default=str) if isinstance(r2.get(c), (dict, list)) else ('N/A' if r2.get(c) is None else r2.get(c)))}</td>"
            for c in cols) + "</tr>" for r2 in rows)
        sections.append(f"<h2>{esc(tname)} ({len(rows)})</h2><table><tr>"
                        + "".join(f"<th>{esc(c)}</th>" for c in cols) + f"</tr>{body}</table>")
    html = f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<title>Phase 6.5 — Complete Meta-Learning Report</title>
<style>body{{font-family:Georgia,serif;margin:40px;color:#111}}h1{{border-bottom:3px solid #111}}
h2{{margin-top:28px;border-bottom:1px solid #999}}table{{border-collapse:collapse;width:100%;font-size:11px;margin:10px 0}}
th,td{{border:1px solid #bbb;padding:3px 6px;text-align:left;vertical-align:top}}th{{background:#eee}}
.safety{{background:#fff8e1;border:1px solid #e0c060;padding:12px;font-size:13px}}
@media print{{body{{margin:10mm}}}}</style></head><body>
<h1>Phase 6.5 — Complete Meta-Learning Report</h1>
<p>Generated {esc(meta['generated_at'])} · model {esc(MODEL_VERSION)} · data hash {esc(meta['source_data_hash'])}
· no-lookahead audit: <b>{esc(audit['status'])}</b> ({audit['checked']} trades checked, {audit['violations']} violations)</p>
<div class="safety"><b>Research only.</b> {esc(SAFETY['note'])}</div>
<p>Source experiments: {esc(', '.join(exp_ids) or 'none')}</p>
<p>Unavailable dimensions (not recorded, never fabricated): {esc(', '.join(UNAVAILABLE_DIMENSIONS))}</p>
{''.join(sections)}
</body></html>"""
    html_path = os.path.join(EXPORT_DIR, "phase65_meta_learning_report.html")
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html)
    return {"success": True, "csv_file": csv_path, "json_file": json_path, "html_file": html_path,
            "csv_rows": n_rows, "tables": {k: len(v) for k, v in tables.items()},
            "meta": meta, "safety": SAFETY}
