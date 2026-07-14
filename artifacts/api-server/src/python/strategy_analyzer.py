"""
Strategy Improvement Framework (Phase 4.2) — post-experiment analytics.

Reads an experiment output directory (research_ledger.csv, wf_trades.csv,
wf_result.json) and explains WHY the experiment performed the way it did:

  1. failure_diagnosis      — which verdict gates / score components failed
  2. opportunity_funnel     — evaluated → signal → gates → queued → entered
  3. threshold_sensitivity  — confidence / calibrated-prob / volume / hold-days sweeps
  4. feature_impact         — feature vs outcome correlations + win/loss deltas
  5. false_positives        — entered trades that lost, and what they looked like
  6. missed_opportunities   — rejected candidates that would likely have won
  7. research_summary       — plain-language findings + recommendations

ANALYSIS ONLY — reads finished experiment output; never touches live trading.
All "would-have" returns use a documented approximation: a rejected candidate
is assumed stopped out if forward MAE reached the stop distance, target-hit if
forward MFE reached the target distance, else the raw forward return at the
horizon. MAE/MFE are measured over a 20-day forward window.

Paper trading and research only. No real orders are placed.
"""

from __future__ import annotations

import csv
import json
import os
import sys
from datetime import datetime

import pandas as pd

REJECTED_STAGES = {
    "rejected_confidence", "rejected_confidence_similarity",
    "rejected_calibrated_prob", "rejected_strategy_gate",
    "rejected_no_slot", "rejected_position_limit",
    "rejected_allocation_caps", "rejected_fill", "rejected_no_trading_day",
}
BUY_STAGES = REJECTED_STAGES | {"queued", "entered", "candidate_pool"}

FUNNEL_ORDER = [
    "not_buy_signal", "already_in_position",
    "rejected_confidence", "rejected_confidence_similarity",
    "rejected_calibrated_prob", "rejected_strategy_gate",
    "rejected_no_slot", "rejected_position_limit",
    "rejected_allocation_caps", "rejected_fill", "rejected_no_trading_day",
    "queued", "entered",
]

FEATURES = ["final_confidence", "base_confidence", "calibrated_probability",
            "pattern_adjustment", "similarity_adjustment", "model_adjustment",
            "opportunity_score", "rr_ratio", "rsi", "adx",
            "volume_ratio", "atr_pct"]


# ── helpers ──────────────────────────────────────────────────────────────────

def _f(v, default=None):
    try:
        x = float(v)
        return default if pd.isna(x) else x
    except (TypeError, ValueError):
        return default


def _approx_outcome_return(row: pd.Series, horizon: int) -> float | None:
    """Approximate realized return had this candidate been entered and held
    up to `horizon` trading days with its proposed stop/target.

    Approximation (documented): if forward MAE breached the stop distance we
    assume the stop fired first (conservative); else if forward MFE reached
    the target distance we assume the target filled; else the raw forward
    close-to-close return at the horizon. MAE/MFE cover a 20-day window, so
    horizons > 20 only use them for stop/target detection within 20 days.
    """
    price = _f(row.get("price"), 0.0) or 0.0
    if price <= 0:
        return None
    fr = _f(row.get(f"fwd_{horizon}"))
    mae = _f(row.get("mae_pct"))
    mfe = _f(row.get("mfe_pct"))
    stop = _f(row.get("stop_loss"), 0.0) or 0.0
    target = _f(row.get("target"), 0.0) or 0.0
    stop_pct = (stop - price) / price * 100.0 if stop > 0 else None
    target_pct = (target - price) / price * 100.0 if target > 0 else None
    if stop_pct is not None and mae is not None and mae <= stop_pct:
        return round(stop_pct, 2)
    if target_pct is not None and mfe is not None and mfe >= target_pct:
        return round(target_pct, 2)
    return fr


def _bucket_stats(returns: list[float]) -> dict:
    n = len(returns)
    if n == 0:
        return {"n": 0, "win_rate": None, "avg_return_pct": None,
                "expectancy_pct": None, "profit_factor": None}
    wins = [r for r in returns if r > 0]
    losses = [r for r in returns if r <= 0]
    gross_w = sum(wins)
    gross_l = abs(sum(losses))
    return {
        "n": n,
        "win_rate": round(len(wins) / n * 100.0, 1),
        "avg_return_pct": round(sum(returns) / n, 2),
        "expectancy_pct": round(sum(returns) / n, 2),
        "profit_factor": round(gross_w / gross_l, 2) if gross_l > 0 else None,
    }


# ── 1. Failure diagnosis ─────────────────────────────────────────────────────

def failure_diagnosis(result: dict, status: dict) -> dict:
    verdict = result.get("verdict") or {}
    checks = verdict.get("checks") or []
    failed = [c for c in checks if not c.get("passed")]
    score = (status.get("score_breakdown") or {})
    max_pts = {"profit_factor": 25, "expectancy": 20, "sharpe": 20,
               "drawdown": 15, "calibration": 10, "evidence": 10}
    weak = sorted(
        ({"component": k, "points": _f(v, 0.0), "max_points": max_pts.get(k, 0),
          "pct_of_max": round(_f(v, 0.0) / max_pts[k] * 100.0, 0) if max_pts.get(k) else None}
         for k, v in score.items()), key=lambda d: (d["pct_of_max"] is None, d["pct_of_max"]))
    full = (result.get("overall") or {}).get("full_metrics") or {}
    return {
        "verdict": verdict.get("verdict"),
        "verdict_summary": verdict.get("summary"),
        "failed_checks": [
            {"name": c.get("name"), "observed": c.get("observed"),
             "threshold": f"{c.get('direction', '')}{c.get('threshold', '')}"}
            for c in failed],
        "score_total": status.get("score"),
        "weakest_score_components": weak[:3],
        "overfitting_flags": status.get("overfitting_flags") or [],
        "headline_metrics": {
            "total_trades": full.get("total_trades"),
            "win_rate": full.get("win_rate"),
            "profit_factor": full.get("profit_factor"),
            "expectancy": full.get("expectancy"),
            "sharpe_ratio": full.get("sharpe_ratio"),
            "max_drawdown_pct": full.get("max_drawdown_pct"),
            "total_return_pct": full.get("total_return_pct"),
        },
    }


# ── 2. Opportunity funnel ────────────────────────────────────────────────────

def opportunity_funnel(led: pd.DataFrame) -> dict:
    counts = led["stage"].value_counts().to_dict()
    total = int(len(led))
    stages = [{"stage": s, "count": int(counts.get(s, 0)),
               "pct_of_evaluated": round(counts.get(s, 0) / total * 100.0, 2) if total else 0.0}
              for s in FUNNEL_ORDER if counts.get(s, 0) > 0 or s in ("queued", "entered")]
    unknown = {s: int(c) for s, c in counts.items() if s not in FUNNEL_ORDER}
    buy_signals = int(led["stage"].isin(BUY_STAGES).sum())
    entered = int(counts.get("entered", 0))
    return {
        "total_evaluated": total,
        "buy_signals": buy_signals,
        "entered": entered,
        "conversion_pct": round(entered / buy_signals * 100.0, 1) if buy_signals else None,
        "stages": stages,
        "unknown_stages": unknown,
        "notes": [
            "The engine has NO explicit volatility or liquidity gates — no "
            "candidates are rejected on those criteria (reported as absent, "
            "not zero-by-measurement).",
            "'rejected_confidence_similarity' marks candidates that would "
            "have passed the confidence floor WITHOUT the negative "
            "similarity adjustment (counterfactual attribution).",
        ],
    }


# ── 3. Threshold sensitivity ─────────────────────────────────────────────────

def threshold_sensitivity(led: pd.DataFrame, cfg: dict) -> dict:
    buys = led[led["stage"].isin(BUY_STAGES)].copy()
    horizon = 10
    buys["approx_ret"] = buys.apply(lambda r: _approx_outcome_return(r, horizon), axis=1)
    buys = buys[buys["approx_ret"].notna()]

    def sweep(mask_fn, values, label):
        rows = []
        for v in values:
            sub = buys[mask_fn(buys, v)]
            st = _bucket_stats(sub["approx_ret"].tolist())
            rows.append({label: v, **st})
        return rows

    conf_sweep = sweep(lambda d, v: d["final_confidence"].astype(float) >= v,
                       [45, 50, 55, 60, 65, 70, 75], "min_confidence")
    calp = buys[buys["calibrated_probability"].notna()]
    cal_sweep = []
    for v in [0.20, 0.25, 0.30, 0.35, 0.40, 0.45, 0.50]:
        sub = calp[calp["calibrated_probability"].astype(float) >= v]
        cal_sweep.append({"min_calibrated_prob": v,
                          **_bucket_stats(sub["approx_ret"].tolist())})
    vol_sweep = sweep(lambda d, v: d["volume_ratio"].astype(float) >= v,
                      [0.0, 0.5, 0.75, 1.0, 1.25, 1.5], "min_volume_ratio")

    # Hold-days sweep on candidates that actually passed all gates (queued or
    # entered) — the closest observational proxy for "same trades, held N days".
    passed = led[led["stage"].isin(["queued", "entered"])].copy()
    hold_sweep = []
    for h in [5, 10, 15, 20, 30]:
        rets = passed.apply(lambda r: _approx_outcome_return(r, h), axis=1).dropna().tolist()
        hold_sweep.append({"hold_days": h, **_bucket_stats(rets)})

    return {
        "current_thresholds": {
            "min_confidence_execute": cfg.get("min_confidence_execute"),
            "min_calibrated_prob": cfg.get("min_calibrated_prob"),
            "volume_filter": "none (engine has no volume gate — sweep is hypothetical)",
        },
        "outcome_model": ("approx: stop assumed hit first if 20d MAE <= stop "
                          "distance; else target if 20d MFE >= target distance; "
                          f"else raw forward return at the horizon (default {horizon}d)"),
        "confidence_sweep": conf_sweep,
        "calibrated_prob_sweep": cal_sweep,
        "volume_ratio_sweep": vol_sweep,
        "hold_days_sweep": hold_sweep,
    }


# ── 4. Feature impact ────────────────────────────────────────────────────────

def feature_impact(led: pd.DataFrame, trades: pd.DataFrame) -> dict:
    buys = led[led["stage"].isin(BUY_STAGES)].copy()
    horizon_col = "fwd_10"
    correlations = []
    for feat in FEATURES:
        if feat not in buys.columns:
            continue
        sub = buys[[feat, horizon_col]].apply(pd.to_numeric, errors="coerce").dropna()
        if len(sub) < 30 or sub[feat].std() == 0:
            continue
        # Spearman = Pearson on ranks (avoids a scipy dependency)
        corr = sub[feat].rank().corr(sub[horizon_col].rank())
        correlations.append({"feature": feat, "spearman_ic_vs_fwd10": round(float(corr), 3),
                             "n": int(len(sub))})
    correlations.sort(key=lambda d: -abs(d["spearman_ic_vs_fwd10"]))

    # Win/loss feature deltas on REALIZED trades (joined ledger ↔ trades)
    joined = join_trades(led, trades)
    deltas = []
    if len(joined) >= 10:
        winners = joined[joined["net_pnl"] > 0]
        losers = joined[joined["net_pnl"] <= 0]
        for feat in FEATURES:
            if feat not in joined.columns:
                continue
            w = pd.to_numeric(winners[feat], errors="coerce").dropna()
            l = pd.to_numeric(losers[feat], errors="coerce").dropna()
            if len(w) < 5 or len(l) < 5:
                continue
            deltas.append({"feature": feat,
                           "winners_mean": round(float(w.mean()), 3),
                           "losers_mean": round(float(l.mean()), 3),
                           "delta": round(float(w.mean() - l.mean()), 3)})
        deltas.sort(key=lambda d: -abs(d["delta"]))
    return {
        "ic_note": ("Spearman rank correlation between each feature at decision "
                    "time and the 10-day forward return across ALL buy-signal "
                    "candidates (entered or not). |IC| > 0.05 is meaningful at "
                    "this sample size; sign shows direction."),
        "feature_ic": correlations,
        "winner_vs_loser_deltas": deltas,
        "realized_trades_joined": int(len(joined)),
    }


def join_trades(led: pd.DataFrame, trades: pd.DataFrame) -> pd.DataFrame:
    """Join ledger 'entered' rows to realized variant-C trades by
    (symbol, entry_date) — unique since one open position per symbol."""
    if trades.empty:
        return pd.DataFrame()
    entered = led[led["stage"] == "entered"].copy()
    if entered.empty:
        return pd.DataFrame()
    tr = trades[trades["variant"] == "C"].copy() if "variant" in trades.columns else trades.copy()
    # Join on window + symbol + entry_date: with overlapping walk-forward
    # windows (step < test length) the same (symbol, entry_date) can occur in
    # more than one window, so the window key prevents cross-window mixing.
    keys = ["symbol", "entry_date"]
    if "window" in tr.columns and "window" in entered.columns:
        keys = ["window", "symbol", "entry_date"]
    tr = tr[keys + ["exit_date", "exit_reason", "holding_days",
                    "net_pnl", "return_pct"]]
    return entered.merge(tr, on=keys, how="inner")


# ── 5. False positives ───────────────────────────────────────────────────────

def false_positives(led: pd.DataFrame, trades: pd.DataFrame) -> dict:
    joined = join_trades(led, trades)
    if joined.empty:
        return {"n_losing_trades": 0, "note": "no realized trades joined", "worst": []}
    losers = joined[pd.to_numeric(joined["net_pnl"], errors="coerce") <= 0].copy()
    losers["return_pct"] = pd.to_numeric(losers["return_pct"], errors="coerce")
    worst = losers.nsmallest(15, "return_pct")
    cols = ["window", "date", "symbol", "sector", "strategy_id", "regime",
            "final_confidence", "calibrated_probability",
            "similarity_adjustment", "pattern_adjustment", "rsi", "adx",
            "volume_ratio", "rr_ratio", "exit_reason", "holding_days", "return_pct"]
    by_exit = losers["exit_reason"].value_counts().to_dict() if "exit_reason" in losers else {}
    by_regime = losers["regime"].value_counts().to_dict()
    by_strategy = losers["strategy_id"].value_counts().to_dict()
    hi_conf = losers[pd.to_numeric(losers["final_confidence"], errors="coerce") >= 65]
    return {
        "n_trades": int(len(joined)),
        "n_losing_trades": int(len(losers)),
        "loss_rate_pct": round(len(losers) / len(joined) * 100.0, 1),
        "high_confidence_losers": int(len(hi_conf)),
        "losers_by_exit_reason": {k: int(v) for k, v in by_exit.items()},
        "losers_by_regime": {k: int(v) for k, v in by_regime.items()},
        "losers_by_strategy": {k: int(v) for k, v in by_strategy.items()},
        "worst": worst[[c for c in cols if c in worst.columns]].to_dict("records"),
    }


# ── 6. Missed opportunities ──────────────────────────────────────────────────

def missed_opportunities(led: pd.DataFrame) -> dict:
    rej = led[led["stage"].isin(REJECTED_STAGES)].copy()
    if rej.empty:
        return {"n_rejected": 0, "by_stage": {}, "best_missed": []}
    rej["approx_ret"] = rej.apply(lambda r: _approx_outcome_return(r, 10), axis=1)
    rej = rej[rej["approx_ret"].notna()]
    by_stage = {}
    for stage, grp in rej.groupby("stage"):
        st = _bucket_stats(grp["approx_ret"].tolist())
        by_stage[stage] = {**st,
                           "missed_winners": int((grp["approx_ret"] > 0).sum())}
    best = rej.nlargest(15, "approx_ret")
    cols = ["window", "date", "symbol", "sector", "strategy_id", "regime", "stage",
            "final_confidence", "calibrated_probability", "similarity_adjustment",
            "volume_ratio", "rr_ratio", "approx_ret", "fwd_10", "fwd_20", "mfe_pct"]
    return {
        "n_rejected": int(len(rej)),
        "outcome_model": "same stop/target-aware 10-day approximation as the threshold sweeps",
        "by_stage": by_stage,
        "best_missed": best[[c for c in cols if c in best.columns]].to_dict("records"),
    }


# ── 7. Research summary (rule-based, deterministic) ──────────────────────────

def research_summary(diag: dict, funnel: dict, sens: dict,
                     feats: dict, fps: dict, missed: dict) -> dict:
    findings: list[str] = []
    recs: list[str] = []

    hm = diag.get("headline_metrics") or {}
    if diag.get("failed_checks"):
        names = ", ".join(c["name"] for c in diag["failed_checks"])
        findings.append(f"Verdict '{diag.get('verdict')}' — failed gates: {names}.")
    for w in diag.get("weakest_score_components") or []:
        if w.get("pct_of_max") is not None and w["pct_of_max"] <= 40:
            findings.append(
                f"Score component '{w['component']}' earned {w['points']}/"
                f"{w['max_points']} points ({w['pct_of_max']:.0f}% of max) — a primary drag.")

    conv = funnel.get("conversion_pct")
    if conv is not None and conv < 30:
        findings.append(
            f"Only {conv}% of buy signals became trades "
            f"({funnel['entered']}/{funnel['buy_signals']}); the biggest "
            "chokepoints are visible in the funnel stages.")
    slot_lost = next((s["count"] for s in funnel.get("stages", [])
                      if s["stage"] == "rejected_no_slot"), 0)
    if slot_lost and funnel.get("buy_signals"):
        pct = slot_lost / funnel["buy_signals"] * 100.0
        if pct > 15:
            findings.append(
                f"{slot_lost} candidates ({pct:.0f}% of buy signals) were lost to "
                "the max-open-positions limit — capital, not signal quality, was binding.")
            recs.append("Consider testing a higher max_open_positions or "
                        "smaller per-trade allocation in a future experiment.")

    # Threshold sweeps: find the confidence floor with the best expectancy at n>=30
    best_conf = max((r for r in sens.get("confidence_sweep", []) if r["n"] >= 30),
                    key=lambda r: (r["expectancy_pct"] if r["expectancy_pct"] is not None else -99),
                    default=None)
    cur_conf = (sens.get("current_thresholds") or {}).get("min_confidence_execute")
    if best_conf and cur_conf is not None and best_conf["min_confidence"] != cur_conf:
        findings.append(
            f"The confidence sweep peaks at floor {best_conf['min_confidence']} "
            f"(expectancy {best_conf['expectancy_pct']}%/trade on n={best_conf['n']}) "
            f"vs the current {cur_conf}.")
        recs.append(f"Run an experiment with min_confidence_execute="
                    f"{best_conf['min_confidence']} to validate the sweep out-of-sample.")
    best_hold = max((r for r in sens.get("hold_days_sweep", []) if r["n"] >= 20),
                    key=lambda r: (r["expectancy_pct"] if r["expectancy_pct"] is not None else -99),
                    default=None)
    if best_hold:
        findings.append(
            f"Hold-days sweep (approximate, stop/target-aware): best expectancy at "
            f"{best_hold['hold_days']}d ({best_hold['expectancy_pct']}%/trade).")

    for ic in (feats.get("feature_ic") or [])[:3]:
        if abs(ic["spearman_ic_vs_fwd10"]) >= 0.05:
            direction = "higher" if ic["spearman_ic_vs_fwd10"] > 0 else "lower"
            findings.append(
                f"Feature '{ic['feature']}' shows the strongest link to 10-day "
                f"forward returns (IC {ic['spearman_ic_vs_fwd10']}, n={ic['n']}) — "
                f"{direction} values preceded better outcomes.")

    if fps.get("n_losing_trades"):
        top_exit = max((fps.get("losers_by_exit_reason") or {}).items(),
                       key=lambda kv: kv[1], default=None)
        if top_exit and top_exit[1] >= 3:
            findings.append(
                f"{fps['n_losing_trades']} losing trades "
                f"({fps['loss_rate_pct']}% of realized trades); most common losing "
                f"exit: '{top_exit[0]}' ({top_exit[1]} trades).")
        if fps.get("high_confidence_losers", 0) >= 3:
            findings.append(
                f"{fps['high_confidence_losers']} losers carried confidence >= 65 — "
                "high confidence did not protect against losses; calibration or "
                "feature quality is suspect.")
            recs.append("Inspect the 'worst' false-positive list for shared "
                        "characteristics (regime, strategy, sector) before "
                        "trusting confidence-weighted sizing.")

    conf_stage = (missed.get("by_stage") or {}).get("rejected_confidence")
    if conf_stage and conf_stage.get("missed_winners", 0) > 0 and \
            (conf_stage.get("expectancy_pct") or 0) > 0:
        findings.append(
            f"Candidates rejected on confidence had POSITIVE approximate expectancy "
            f"({conf_stage['expectancy_pct']}%/trade, n={conf_stage['n']}) — the "
            "confidence floor may be discarding real edge.")
        recs.append("Cross-check with the confidence sweep before lowering the "
                    "floor; both views must agree.")
    sim_stage = (missed.get("by_stage") or {}).get("rejected_confidence_similarity")
    if sim_stage and (sim_stage.get("expectancy_pct") or 0) > 0:
        findings.append(
            f"Similarity-driven rejections (would have passed without the negative "
            f"similarity adjustment) had positive approximate expectancy "
            f"({sim_stage['expectancy_pct']}%/trade, n={sim_stage['n']}) — the "
            "similarity layer may be over-penalizing in this configuration.")

    if not findings:
        findings.append("No dominant failure driver was detected by the rule-based "
                        "checks; inspect the detailed sections manually.")
    if not recs:
        recs.append("No specific parameter change is supported by this run's "
                    "evidence; gather more trades before tuning.")
    return {
        "method": ("Deterministic rule-based synthesis of sections 1-6 — no "
                   "LLM involved; every statement is traceable to the data above."),
        "findings": findings,
        "recommendations": recs,
        "caveats": [
            "All 'would-have' returns are approximations (stop/target inferred "
            "from 20-day MAE/MFE; no intraday ordering).",
            "This is research-only output; nothing here changes live trading.",
        ],
    }


# ── Orchestration ────────────────────────────────────────────────────────────

def analyze_experiment(exp_dir: str) -> dict:
    ledger_path = os.path.join(exp_dir, "research_ledger.csv")
    if not os.path.exists(ledger_path):
        return {"error": "research_ledger.csv not found — this experiment was "
                         "run before Phase 4.2; re-run it to generate the ledger."}
    led = pd.read_csv(ledger_path)
    trades_path = os.path.join(exp_dir, "wf_trades.csv")
    trades = pd.read_csv(trades_path) if os.path.exists(trades_path) else pd.DataFrame()
    result = {}
    rp = os.path.join(exp_dir, "wf_result.json")
    if os.path.exists(rp):
        with open(rp) as f:
            result = json.load(f)
    status = {}
    sp = os.path.join(exp_dir, "status.json")
    if os.path.exists(sp):
        with open(sp) as f:
            status = json.load(f)
    cfg = result.get("config") or {}

    diag = failure_diagnosis(result, status)
    funnel = opportunity_funnel(led)
    sens = threshold_sensitivity(led, cfg)
    feats = feature_impact(led, trades)
    fps = false_positives(led, trades)
    missed = missed_opportunities(led)
    summary = research_summary(diag, funnel, sens, feats, fps, missed)

    analysis = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "ledger_rows": int(len(led)),
        "safety": "Paper trading and research only. No real orders are placed.",
        "failure_diagnosis": diag,
        "opportunity_funnel": funnel,
        "threshold_sensitivity": sens,
        "feature_impact": feats,
        "false_positives": fps,
        "missed_opportunities": missed,
        "research_summary": summary,
    }

    with open(os.path.join(exp_dir, "analysis.json"), "w") as f:
        json.dump(analysis, f, indent=1, default=str)
    _export_csvs(exp_dir, sens, fps, missed)
    return analysis


def _export_csvs(exp_dir: str, sens: dict, fps: dict, missed: dict) -> None:
    def write(name: str, rows: list[dict]):
        if not rows:
            return
        cols = list(rows[0].keys())
        with open(os.path.join(exp_dir, name), "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
            w.writeheader()
            w.writerows(rows)

    sweep_rows = []
    for key in ("confidence_sweep", "calibrated_prob_sweep",
                "volume_ratio_sweep", "hold_days_sweep"):
        for r in sens.get(key, []):
            sweep_rows.append({"sweep": key, "parameter": list(r.items())[0][1],
                               **{k: v for k, v in r.items()}})
    normalized = []
    for r in sweep_rows:
        param_key = next(k for k in r if k not in
                         ("sweep", "parameter", "n", "win_rate",
                          "avg_return_pct", "expectancy_pct", "profit_factor"))
        normalized.append({"sweep": r["sweep"], "threshold": r[param_key],
                           "n": r["n"], "win_rate": r["win_rate"],
                           "expectancy_pct": r["expectancy_pct"],
                           "profit_factor": r["profit_factor"]})
    write("analysis_threshold_sensitivity.csv", normalized)
    write("analysis_false_positives.csv", fps.get("worst") or [])
    write("analysis_missed_opportunities.csv", missed.get("best_missed") or [])


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: strategy_analyzer.py <experiment_dir>", file=sys.stderr)
        sys.exit(1)
    out = analyze_experiment(sys.argv[1])
    if out.get("error"):
        print(json.dumps(out), file=sys.stderr)
        sys.exit(2)
    print(json.dumps({"ok": True, "ledger_rows": out["ledger_rows"]}))
