"""Phase 5 — AI Research Intelligence & Strategy Improvement Engine.

Research only. Deterministic, rule-based analysis of completed experiments:
  * trade_diagnostics(exp_dir)   — per-trade diagnosis (honest N/A for data
                                   that was never stored, e.g. indicator values)
  * build_intelligence()         — cross-experiment insights, learning summary,
                                   strategy health scores, recommendations,
                                   portfolio suggestions, learning timeline
  * compare_experiments(ids)     — side-by-side comparison of latest reports

Nothing here modifies live or paper-trading behavior. All outputs carry
research_only flags and disclaimers. No lookahead: only stored, completed
out-of-sample results are read.
"""
import os
import json

import pandas as pd

from report_engine import (
    _load, _variant_c, _sample_label, _num, _pf, _read_index, _latest,
    _now_iso,
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
EXPERIMENTS_DIR = os.path.join(BASE_DIR, "experiments")

DISCLAIMER = ("Research only — these are research suggestions based on historical "
              "out-of-sample results. They do not modify live or paper trading and "
              "do not guarantee future results.")

SAFETY = {"research_only": True, "live_orders_affected": False,
          "auto_applied": False, "disclaimer": DISCLAIMER}


# ── helpers ──────────────────────────────────────────────────────────────────

def _latest_report(exp_dir):
    idx = _read_index(exp_dir)
    latest = _latest(idx)
    if not latest:
        return None
    p = os.path.join(exp_dir, "reports", f"report_v{latest['version']}.json")
    if not os.path.exists(p):
        return None
    try:
        with open(p) as f:
            return json.load(f)
    except Exception:
        return None


def _completed_experiments():
    """Yield (exp_id, exp_dir, status, config, trades_variant_c, report|None)."""
    if not os.path.isdir(EXPERIMENTS_DIR):
        return []
    out = []
    for exp_id in sorted(os.listdir(EXPERIMENTS_DIR)):
        d = os.path.join(EXPERIMENTS_DIR, exp_id)
        if not os.path.isdir(d):
            continue
        status, config, result, analysis, trades, ledger = _load(d)
        if (status.get("status") or "").lower() not in ("completed", "rejected", "failed_evidence", "done"):
            continue
        df = _variant_c(trades)
        if df.empty:
            continue
        out.append((exp_id, d, status, config, df, _latest_report(d)))
    return out


def _f(v, nd=2):
    n = _num(v)
    return None if n is None else round(n, nd)


def _grp(df, key):
    """Aggregate trades by a column → list of dicts with core research metrics."""
    if df.empty or key not in df.columns:
        return []
    rows = []
    for g, sub in df.groupby(key):
        pnls = pd.to_numeric(sub["net_pnl"], errors="coerce").fillna(0.0)
        n = len(sub)
        wins = int((pnls > 0).sum())
        rows.append({
            "group": str(g), "trades": n, "wins": wins, "losses": n - wins,
            "win_rate": _f(100.0 * wins / n) if n else None,
            "net_pnl": _f(pnls.sum()),
            "expectancy_rs": _f(pnls.mean()),
            "profit_factor": _f(_pf(pnls)),
            "avg_return_pct": _f(pd.to_numeric(sub["return_pct"], errors="coerce").mean()) if "return_pct" in sub else None,
            "sample_label": _sample_label(n),
        })
    rows.sort(key=lambda r: -(r["net_pnl"] or 0))
    return rows


# ── 1. Trade Diagnostics Engine ──────────────────────────────────────────────

def trade_diagnostics(exp_dir):
    exp_id = os.path.basename(exp_dir.rstrip("/"))
    if not os.path.isdir(exp_dir):
        return {"success": False, "error": {"code": "NOT_FOUND",
                                            "message": "Experiment not found.", "details": exp_id}}
    status, config, result, analysis, trades_all, ledger = _load(exp_dir)
    df = _variant_c(trades_all)
    if df.empty:
        return {"success": True, "experiment_id": exp_id, "trades": [],
                "note": "No out-of-sample trades were recorded for this experiment.",
                **SAFETY}

    # cross-variant outcomes for the same symbol+entry (honest counterfactual)
    other = trades_all[trades_all.get("variant", "C") != "C"] if "variant" in trades_all.columns else pd.DataFrame()

    diagnoses = []
    for _, t in df.iterrows():
        pnl = _num(t.get("net_pnl")) or 0.0
        won = pnl > 0
        conf = _num(t.get("confidence"))
        cal = _num(t.get("calibrated_confidence"))
        mae = _num(t.get("mae_pct"))
        mfe = _num(t.get("mfe_pct"))
        gap = _num(t.get("gap_pct"))
        hold = _num(t.get("holding_days"))
        regime = str(t.get("market_regime") or "") or None
        exit_reason = str(t.get("exit_reason") or "") or None
        strat = str(t.get("strategy_name") or "") or None

        entry = (f"{strat or 'Strategy'} issued a {t.get('recommendation') or 'BUY'} signal on "
                 f"{t.get('symbol')} ({t.get('sector') or 'sector N/A'}) with "
                 f"{'N/A' if conf is None else f'{conf:.0f}%'} raw confidence"
                 f"{'' if cal is None else f' ({cal:.0f}% calibrated)'}"
                 f"{f' in a {regime} regime' if regime else ''}"
                 f"{'' if gap is None else f'; opening gap {gap:+.2f}%'}.")

        why = []
        if exit_reason:
            why.append(f"Exit: {exit_reason}.")
        if won:
            if mfe is not None:
                why.append(f"Price moved up to {mfe:+.2f}% in the trade's favour (MFE).")
            if mae is not None and mae <= -3:
                why.append(f"But it first drew down {mae:.2f}% (MAE) — the entry timing was early.")
        else:
            if mae is not None:
                why.append(f"Adverse move reached {mae:.2f}% (MAE) before exit.")
            if mfe is not None and mfe >= 2:
                why.append(f"The trade was profitable at one point (MFE {mfe:+.2f}%) but gave the gain back.")
            if exit_reason and "stop" in exit_reason.lower():
                why.append("The stop-loss rule ended the trade as designed.")
        if hold is not None:
            why.append(f"Held {hold:.0f} day(s).")

        filters = []
        if gap is not None:
            filters.append({"filter": "Opening-gap check", "value": f"{gap:+.2f}%",
                            "respected": abs(gap) <= 3,
                            "note": None if abs(gap) <= 3 else "Entry occurred after a >3% gap — gap trades were flagged as riskier in prior analysis."})
        pf_fill = str(t.get("partial_fill", "")).lower() == "true"
        filters.append({"filter": "Full fill", "value": "partial" if pf_fill else "full",
                        "respected": not pf_fill, "note": None})
        if conf is not None:
            filters.append({"filter": "Confidence floor (55%)", "value": f"{conf:.0f}%",
                            "respected": conf >= 55, "note": None})

        # honest cross-variant comparison (only if another variant traded the same setup)
        counterfactual = None
        if not other.empty and "symbol" in other.columns:
            m = other[(other["symbol"] == t.get("symbol")) &
                      (other["entry_date"] == t.get("entry_date")) &
                      (other.get("window") == t.get("window"))]
            if not m.empty:
                alt = [{"variant": str(r.get("variant")),
                        "net_pnl": _f(_num(r.get("net_pnl"))),
                        "exit_reason": str(r.get("exit_reason") or "") or None}
                       for _, r in m.iterrows()]
                counterfactual = {"available": True, "alternatives": alt}
        if counterfactual is None:
            counterfactual = {"available": False,
                              "note": "No other model variant traded this exact setup, so whether another strategy would have avoided or improved the result cannot be determined honestly from stored data."}

        diagnoses.append({
            "window": str(t.get("window") or ""),
            "symbol": str(t.get("symbol") or ""),
            "sector": str(t.get("sector") or "") or None,
            "strategy_name": strat,
            "entry_date": str(t.get("entry_date") or ""),
            "exit_date": str(t.get("exit_date") or ""),
            "holding_days": _f(hold, 0),
            "net_pnl": _f(pnl),
            "return_pct": _f(_num(t.get("return_pct"))),
            "outcome": "WIN" if won else "LOSS",
            "market_regime": regime,
            "confidence": _f(conf, 1),
            "calibrated_confidence": _f(cal, 1),
            "exit_reason": exit_reason,
            "mae_pct": _f(mae), "mfe_pct": _f(mfe), "gap_pct": _f(gap),
            "entry_rationale": entry,
            "outcome_explanation": " ".join(why) or "No additional outcome detail was recorded.",
            "filters": filters,
            "filters_respected": all(f["respected"] for f in filters),
            "indicator_values": None,
            "indicator_note": ("Indicator values at entry (MACD, RSI, EMA, ATR, trend/sector "
                               "strength) were not stored with this experiment's trades, so they "
                               "are shown as Not available rather than reconstructed."),
            "counterfactual": counterfactual,
        })

    return {"success": True, "experiment_id": exp_id,
            "experiment_name": status.get("name"),
            "trade_count": len(diagnoses), "trades": diagnoses, **SAFETY}


# ── 2/3/5/6/7/8. Cross-experiment intelligence ───────────────────────────────

def _conf_label(n):
    lab = _sample_label(n)
    return {"VERY LOW": "LOW", "LOW": "LOW", "LIMITED": "MEDIUM",
            "MODERATE": "MEDIUM", "STRONGER": "HIGH"}.get(lab, "LOW")


def build_intelligence():
    exps = _completed_experiments()
    if not exps:
        return {"success": True, "experiments_analyzed": 0,
                "note": "No completed experiments with trades were found yet.",
                "insights": [], "learning_summary": {}, "strategy_health": [],
                "recommendations": [], "portfolio_suggestions": [],
                "timeline": [], **SAFETY}

    frames = []
    for exp_id, d, status, config, df, report in exps:
        f = df.copy()
        f["experiment_id"] = exp_id
        f["experiment_name"] = status.get("name") or exp_id
        frames.append(f)
    allt = pd.concat(frames, ignore_index=True)
    allt["net_pnl"] = pd.to_numeric(allt["net_pnl"], errors="coerce").fillna(0.0)

    by_strategy = _grp(allt, "strategy_name")
    by_sector = _grp(allt, "sector")
    by_regime = _grp(allt, "market_regime")
    # confidence bands
    if "confidence" in allt.columns:
        allt["_band"] = pd.cut(pd.to_numeric(allt["confidence"], errors="coerce"),
                               [0, 55, 65, 75, 85, 101],
                               labels=["<55", "55-65", "65-75", "75-85", "85+"])
        by_band = _grp(allt.assign(_band=allt["_band"].astype(str)), "_band")
    else:
        by_band = []
    if "holding_days" in allt.columns:
        allt["_hold"] = pd.cut(pd.to_numeric(allt["holding_days"], errors="coerce"),
                               [-1, 2, 5, 10, 20, 10_000],
                               labels=["0-2d", "3-5d", "6-10d", "11-20d", "20d+"])
        by_hold = _grp(allt.assign(_hold=allt["_hold"].astype(str)), "_hold")
    else:
        by_hold = []

    # strategy × regime for pattern discovery
    strat_regime = []
    if {"strategy_name", "market_regime"}.issubset(allt.columns):
        for (s, r), sub in allt.groupby(["strategy_name", "market_regime"]):
            pnls = sub["net_pnl"]
            strat_regime.append({"strategy": str(s), "regime": str(r), "trades": len(sub),
                                 "expectancy_rs": _f(pnls.mean()), "net_pnl": _f(pnls.sum()),
                                 "sample_label": _sample_label(len(sub))})

    # ── insights (pattern discovery) — only evidence-backed statements ──
    insights = []

    def add(iid, category, title, detail, n, metric):
        insights.append({"id": iid, "category": category, "title": title, "detail": detail,
                         "evidence": {"trades": n, "metric": metric},
                         "sample_label": _sample_label(n), "confidence_level": _conf_label(n)})

    for sr in sorted(strat_regime, key=lambda x: -(x["net_pnl"] or 0))[:3]:
        if (sr["trades"] or 0) >= 3 and (sr["expectancy_rs"] or 0) > 0:
            add(f"pat_sr_{sr['strategy']}_{sr['regime']}".replace(" ", "_").lower(), "strategy_regime",
                f"{sr['strategy']} performed best in {sr['regime']} conditions",
                f"Across all experiments, {sr['strategy']} averaged ₹{sr['expectancy_rs']} per trade "
                f"over {sr['trades']} trades in {sr['regime']} regimes.",
                sr["trades"], f"expectancy ₹{sr['expectancy_rs']}")
    for sr in sorted(strat_regime, key=lambda x: (x["expectancy_rs"] or 0))[:3]:
        if (sr["trades"] or 0) >= 3 and (sr["expectancy_rs"] or 0) < 0:
            add(f"pat_srw_{sr['strategy']}_{sr['regime']}".replace(" ", "_").lower(), "strategy_regime",
                f"{sr['strategy']} struggled in {sr['regime']} conditions",
                f"{sr['strategy']} lost an average of ₹{abs(sr['expectancy_rs'])} per trade over "
                f"{sr['trades']} trades in {sr['regime']} regimes.",
                sr["trades"], f"expectancy ₹{sr['expectancy_rs']}")
    for s in by_sector:
        if s["trades"] >= 3 and (s["expectancy_rs"] or 0) < 0:
            add(f"pat_sector_{s['group']}".lower(), "sector",
                f"{s['group']} sector underperformed",
                f"{s['group']} produced ₹{s['net_pnl']} net across {s['trades']} trades "
                f"(win rate {s['win_rate']}%).", s["trades"], f"net ₹{s['net_pnl']}")
    # confidence quality
    hi = [b for b in by_band if b["group"] in ("75-85", "85+") and b["trades"] >= 3]
    lo = [b for b in by_band if b["group"] in ("55-65", "65-75") and b["trades"] >= 3]
    if hi and lo:
        hi_e = sum((b["expectancy_rs"] or 0) * b["trades"] for b in hi) / max(1, sum(b["trades"] for b in hi))
        lo_e = sum((b["expectancy_rs"] or 0) * b["trades"] for b in lo) / max(1, sum(b["trades"] for b in lo))
        if hi_e <= lo_e:
            add("pat_conf_quality", "confidence",
                "High-confidence trades were not higher quality",
                f"Trades above 75% confidence averaged ₹{hi_e:.2f} vs ₹{lo_e:.2f} for 55–75% "
                "confidence — raw confidence did not translate into better outcomes.",
                int(sum(b["trades"] for b in hi + lo)), f"₹{hi_e:.2f} vs ₹{lo_e:.2f}")
    for h in by_hold:
        if h["group"] in ("11-20d", "20d+") and h["trades"] >= 3 and (h["expectancy_rs"] or 0) < 0:
            add(f"pat_hold_{h['group']}", "holding_period",
                f"Long holding periods ({h['group']}) reduced expectancy",
                f"Trades held {h['group']} averaged ₹{h['expectancy_rs']} per trade "
                f"across {h['trades']} trades.", h["trades"], f"expectancy ₹{h['expectancy_rs']}")
    # gap behaviour
    if "gap_pct" in allt.columns:
        gp = allt[pd.to_numeric(allt["gap_pct"], errors="coerce").abs() > 2]
        if len(gp) >= 3:
            e = gp["net_pnl"].mean()
            if e < 0:
                add("pat_gap", "entry_quality", "Entries after >2% gaps underperformed",
                    f"{len(gp)} trades entered after a >2% opening gap averaged ₹{e:.2f} per trade.",
                    len(gp), f"expectancy ₹{e:.2f}")

    # ── 7. strategy health ──
    health = []
    for s in by_strategy:
        sub = allt[allt["strategy_name"] == s["group"]]
        rets = pd.to_numeric(sub["return_pct"], errors="coerce").dropna() if "return_pct" in sub else pd.Series(dtype=float)
        sharpe_proxy = None
        if len(rets) >= 3 and rets.std(ddof=0) > 0:
            sharpe_proxy = _f(rets.mean() / rets.std(ddof=0), 2)
        per_exp = sub.groupby("experiment_id")["net_pnl"].mean()
        consistency = _f(100.0 * (per_exp > 0).sum() / len(per_exp)) if len(per_exp) else None
        stability = _f(per_exp.std(ddof=0)) if len(per_exp) >= 2 else None
        score = 0
        pf = s["profit_factor"]
        score += 30 if (pf or 0) >= 1.5 else 20 if (pf or 0) >= 1.2 else 10 if (pf or 0) >= 1.0 else 0
        score += 20 if (s["expectancy_rs"] or 0) > 0 else 0
        score += 15 if (sharpe_proxy or 0) > 0.2 else 8 if (sharpe_proxy or 0) > 0 else 0
        score += 15 if (consistency or 0) >= 75 else 8 if (consistency or 0) >= 50 else 0
        score += {"STRONGER": 20, "MODERATE": 14, "LIMITED": 8, "LOW": 4}.get(s["sample_label"], 2)
        rating = ("Excellent" if score >= 80 else "Good" if score >= 60 else
                  "Average" if score >= 40 else "Weak" if score >= 25 else "Reject")
        explanation = (f"Profit factor {pf if pf is not None else 'N/A'}, expectancy "
                       f"₹{s['expectancy_rs']}, per-trade Sharpe proxy "
                       f"{sharpe_proxy if sharpe_proxy is not None else 'N/A'}, positive in "
                       f"{consistency if consistency is not None else 'N/A'}% of experiments, "
                       f"evidence {s['sample_label']} ({s['trades']} trades). "
                       "Drawdown and calibration are tracked at portfolio level, not per strategy.")
        health.append({"strategy": s["group"], "trades": s["trades"],
                       "profit_factor": pf, "expectancy_rs": s["expectancy_rs"],
                       "win_rate": s["win_rate"], "net_pnl": s["net_pnl"],
                       "sharpe_proxy": sharpe_proxy, "consistency_pct": consistency,
                       "stability_rs_std": stability, "evidence": s["sample_label"],
                       "health_score": score, "rating": rating, "explanation": explanation})
    health.sort(key=lambda h: -h["health_score"])

    # ── 5. learning summary ──
    def best(rows, key="expectancy_rs", positive=True, min_n=3):
        pool = [r for r in rows if r["trades"] >= min_n]
        if not pool:
            return None
        r = max(pool, key=lambda x: (x[key] or -1e9)) if positive else min(pool, key=lambda x: (x[key] or 1e9))
        return r

    bs, ws = best(by_strategy), best(by_strategy, positive=False)
    br, wr_ = best(by_regime), best(by_regime, positive=False)
    bb = best(by_band)
    bad_sectors = [s["group"] for s in by_sector if s["trades"] >= 3 and (s["expectancy_rs"] or 0) < 0]
    failing_params = []
    for exp_id, d, status, config, df, report in exps:
        v = ((report or {}).get("final_verdict") or {}).get("verdict") or (status.get("status") or "").upper()
        if "REJECT" in str(v).upper() or "FAIL" in str(v).upper():
            cfg = config or {}
            failing_params.append({"experiment": status.get("name") or exp_id,
                                   "verdict": str(v),
                                   "config_summary": {k: cfg.get(k) for k in
                                                      ("template", "train_years", "test_months", "step_months")
                                                      if cfg.get(k) is not None}})
    learning = {
        "experiments_analyzed": len(exps),
        "total_oos_trades": int(len(allt)),
        "most_consistent_strategy": (bs and {"strategy": bs["group"], "expectancy_rs": bs["expectancy_rs"],
                                             "trades": bs["trades"], "sample_label": bs["sample_label"]}),
        "weakest_strategy": (ws and {"strategy": ws["group"], "expectancy_rs": ws["expectancy_rs"],
                                     "trades": ws["trades"], "sample_label": ws["sample_label"]}),
        "safest_regime": (br and {"regime": br["group"], "expectancy_rs": br["expectancy_rs"],
                                  "trades": br["trades"], "sample_label": br["sample_label"]}),
        "riskiest_regime": (wr_ and {"regime": wr_["group"], "expectancy_rs": wr_["expectancy_rs"],
                                     "trades": wr_["trades"], "sample_label": wr_["sample_label"]}),
        "best_confidence_band": (bb and {"band": bb["group"], "expectancy_rs": bb["expectancy_rs"],
                                         "trades": bb["trades"], "sample_label": bb["sample_label"]}),
        "underperforming_sectors": bad_sectors,
        "repeatedly_failing_configs": failing_params,
        "filters_note": ("Which filters consistently improve performance cannot be stated yet — "
                         "controlled filter on/off experiments have not been run. Suggested as "
                         "follow-up research."),
        "tables": {"by_strategy": by_strategy, "by_sector": by_sector,
                   "by_regime": by_regime, "by_confidence_band": by_band,
                   "by_holding_period": by_hold, "strategy_regime": strat_regime},
    }

    # ── 3. recommendations ──
    recs = []

    def rec(rid, action, benefit, evidence, n, category):
        recs.append({"id": rid, "category": category, "action": action,
                     "expected_benefit": benefit, "supporting_evidence": evidence,
                     "evidence_trades": n, "confidence_level": _conf_label(n),
                     "auto_applied": False, "research_only": True})

    for b in by_band:
        if b["group"] in ("55-65",) and b["trades"] >= 3 and (b["expectancy_rs"] or 0) < 0:
            rec("rec_conf_threshold",
                "Test raising the confidence threshold above 65% in a controlled experiment",
                f"Removing the 55–65% band would have avoided ₹{abs(b['net_pnl'])} of net losses historically",
                f"55–65% confidence trades: {b['trades']} trades, expectancy ₹{b['expectancy_rs']}",
                b["trades"], "confidence")
    for h in by_hold:
        if h["group"] in ("11-20d", "20d+") and h["trades"] >= 3 and (h["expectancy_rs"] or 0) < 0:
            rec(f"rec_hold_{h['group']}",
                f"Test a shorter maximum holding period (current losses concentrate in {h['group']})",
                f"Avoiding {h['group']} holds would have saved ₹{abs(h['net_pnl'])} net historically",
                f"{h['group']} holds: {h['trades']} trades, expectancy ₹{h['expectancy_rs']}",
                h["trades"], "holding_period")
    for s in by_sector:
        if s["trades"] >= 3 and (s["expectancy_rs"] or 0) < 0:
            rec(f"rec_sector_{s['group'].lower()}",
                f"Test a sector-strength filter for {s['group']}",
                f"{s['group']} contributed ₹{s['net_pnl']} net loss",
                f"{s['group']}: {s['trades']} trades, win rate {s['win_rate']}%",
                s["trades"], "sector")
    for r in by_regime:
        if r["trades"] >= 3 and (r["expectancy_rs"] or 0) < 0:
            rec(f"rec_regime_{r['group'].lower().replace(' ', '_')}",
                f"Test skipping entries during {r['group']} regimes",
                f"{r['group']} trades produced ₹{r['net_pnl']} net loss",
                f"{r['group']}: {r['trades']} trades, expectancy ₹{r['expectancy_rs']}",
                r["trades"], "regime")
    for h in health:
        if h["rating"] in ("Weak", "Reject") and h["trades"] >= 3:
            rec(f"rec_strategy_{h['strategy'].lower().replace(' ', '_')}",
                f"Consider disabling or re-parameterising {h['strategy']} (health: {h['rating']})",
                f"Removing it would have avoided ₹{abs(h['net_pnl'])} net loss" if (h["net_pnl"] or 0) < 0
                else "Its evidence does not support continued allocation",
                h["explanation"], h["trades"], "strategy")

    # ── 6. portfolio suggestions (advisory) ──
    port = []
    total_pos = sum(max(0.0, h["expectancy_rs"] or 0) * h["trades"] for h in health)
    for h in health:
        w = (max(0.0, (h["expectancy_rs"] or 0)) * h["trades"] / total_pos * 100) if total_pos > 0 else None
        port.append({"strategy": h["strategy"], "rating": h["rating"],
                     "suggested_research_weight_pct": _f(w, 1),
                     "suggestion": (f"Increase research allocation toward {h['strategy']}"
                                    if h["rating"] in ("Excellent", "Good") else
                                    f"Hold {h['strategy']} at reduced/neutral weight pending more evidence"
                                    if h["rating"] == "Average" else
                                    f"Reduce or disable {h['strategy']} in future experiments"),
                     "advisory_only": True})
    if wr_ and (wr_["expectancy_rs"] or 0) < 0:
        port.append({"strategy": None, "rating": None, "suggested_research_weight_pct": None,
                     "suggestion": f"Consider higher cash allocation during {wr_['group']} regimes "
                                   f"(historical expectancy ₹{wr_['expectancy_rs']}/trade)",
                     "advisory_only": True})

    # ── 8. learning timeline ──
    timeline = []
    for exp_id, d, status, config, df, report in exps:
        when = status.get("completed_at") or status.get("created_at")
        es = (report or {}).get("executive_summary") or {}
        fv = ((report or {}).get("final_verdict") or {}).get("verdict")
        conf_sec = (report or {}).get("confidence_analysis") or {}
        ece_b = ((conf_sec.get("before_calibration") or {}).get("ece"))
        ece_a = ((conf_sec.get("after_calibration") or {}).get("ece"))
        timeline.append({"date": when, "type": "experiment_completed",
                         "title": f"Experiment completed: {status.get('name') or exp_id}",
                         "detail": {"verdict": fv, "oos_trades": es.get("oos_trades"),
                                    "net_return_pct": es.get("net_return_pct"),
                                    "score": es.get("score"),
                                    "ece_before": ece_b, "ece_after": ece_a,
                                    "report_version": (report or {}).get("report_version")}})
        idx = _read_index(d)
        for v in (idx.get("versions") or []):
            if v.get("status") == "COMPLETED":
                timeline.append({"date": v.get("generated_at"), "type": "report_generated",
                                 "title": f"Research report v{v['version']} — {status.get('name') or exp_id}",
                                 "detail": {"version": v["version"]}})
    for ins in insights[:5]:
        timeline.append({"date": _now_iso(), "type": "discovery",
                         "title": f"Discovery: {ins['title']}",
                         "detail": {"evidence": ins["evidence"], "confidence_level": ins["confidence_level"]}})
    timeline.sort(key=lambda e: str(e.get("date") or ""))

    return {"success": True, "generated_at": _now_iso(),
            "experiments_analyzed": len(exps), "total_oos_trades": int(len(allt)),
            "insights": insights, "learning_summary": learning,
            "strategy_health": health, "recommendations": recs,
            "portfolio_suggestions": port, "timeline": timeline, **SAFETY}


# ── 4. Experiment comparison ─────────────────────────────────────────────────

def compare_experiments(exp_ids):
    rows = []
    for exp_id in exp_ids:
        d = os.path.join(EXPERIMENTS_DIR, exp_id)
        if not os.path.isdir(d):
            rows.append({"experiment_id": exp_id, "available": False,
                         "note": "Experiment not found."})
            continue
        status, config, result, analysis, trades, ledger = _load(d)
        report = _latest_report(d)
        if not report:
            rows.append({"experiment_id": exp_id, "available": False,
                         "experiment_name": status.get("name") or exp_id,
                         "note": "No completed research report — generate one first."})
            continue
        es = report.get("executive_summary") or {}
        perf = report.get("performance_analysis") or {}
        risk = report.get("risk_analysis") or {}
        conf = report.get("confidence_analysis") or {}
        dist = ((report.get("trade_distribution") or {}).get("tables") or {})
        strat_rows = [r for r in (dist.get("by_strategy") or []) if r.get("trades")]
        best_s = max(strat_rows, key=lambda r: (r.get("net_pnl") or -1e18), default=None)
        worst_s = min(strat_rows, key=lambda r: (r.get("net_pnl") or 1e18), default=None)
        regimes = [r for r in (dist.get("by_regime") or []) if r.get("trades")]
        dom_regime = max(regimes, key=lambda r: r.get("trades") or 0, default=None)
        rows.append({
            "experiment_id": exp_id, "available": True,
            "experiment_name": es.get("experiment_name") or status.get("name") or exp_id,
            "template": es.get("template"),
            "report_version": report.get("report_version"),
            "verdict": ((report.get("final_verdict") or {}).get("verdict")),
            "score": es.get("score"),
            "evidence_verdict": es.get("evidence_verdict"),
            "oos_trades": es.get("oos_trades"), "windows": es.get("windows"),
            "net_return_pct": es.get("net_return_pct"), "net_pnl": es.get("net_pnl"),
            "profit_factor": es.get("profit_factor"), "expectancy_rs": es.get("expectancy_rs"),
            "win_rate": es.get("win_rate"), "sharpe": es.get("sharpe"),
            "max_drawdown_pct": es.get("max_drawdown_pct"),
            "recovery_factor": perf.get("recovery_factor"),
            "calibration_ece_after": ((conf.get("after_calibration") or {}).get("ece")),
            "dominant_regime": dom_regime and dom_regime.get("group"),
            "best_strategy": best_s and {"name": best_s.get("group"), "net_pnl": best_s.get("net_pnl")},
            "worst_strategy": worst_s and {"name": worst_s.get("group"), "net_pnl": worst_s.get("net_pnl")},
        })
    return {"success": True, "generated_at": _now_iso(), "experiments": rows, **SAFETY}
