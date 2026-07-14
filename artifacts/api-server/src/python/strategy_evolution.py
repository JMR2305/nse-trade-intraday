"""Phase 6 — Strategy Evolution Laboratory (RESEARCH ONLY).

Generates, compares, tests and ranks strategy variations using data already
produced by the Research Factory. Nothing in this module:
  * places live orders,
  * modifies Trade Decision / paper-trading / scanner / portfolio logic,
  * changes strategy parameters automatically,
  * promotes any strategy into production.

Everything is a research candidate requiring explicit human approval.
Persistent store: src/python/strategy_evolution_store/ (JSON files).
"""
import json
import os
import statistics
import uuid
from datetime import datetime, timezone

import pandas as pd

from strategies import STRATEGY_REGISTRY  # read-only import of built-in definitions

ALL_STRATEGIES = list(STRATEGY_REGISTRY.values())
from research_intelligence import _completed_experiments

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STORE_DIR = os.path.join(BASE_DIR, "strategy_evolution_store")
EXPORT_DIR = os.path.join(BASE_DIR, "exports")
REGISTRY_PATH = os.path.join(STORE_DIR, "registry.json")
AB_PATH = os.path.join(STORE_DIR, "ab_tests.json")

SAFETY = {
    "research_only": True,
    "affects_live_trading": False,
    "affects_paper_trading": False,
    "auto_promotion": False,
    "note": "Strategy Evolution Laboratory produces research candidates only. "
            "Human approval is required before any future deployment.",
}

VALID_STATUSES = ["Draft", "Research", "Candidate", "Archived", "Rejected"]

# ── Mutation parameter space — ONE major parameter changes per variant ────────
PARAM_SPACE = {
    "confidence_threshold": {
        "values": [55, 60, 65, 70, 75], "default": 55, "unit": "score",
        "config_key": "min_confidence_execute", "config_level": True,
        "benefit": "Higher thresholds trade less but may improve win rate; lower thresholds increase sample size.",
    },
    "holding_days": {
        "values": [5, 10, 15, 20, 30], "default": 20, "unit": "days",
        "config_key": "max_holding_days", "config_level": True,
        "benefit": "Shorter holds reduce time-based exits and exposure; longer holds let trends develop.",
    },
    "atr_multiplier": {
        "values": [0.8, 1.0, 1.2, 1.5], "default": 2.0, "unit": "x ATR",
        "config_key": None, "config_level": False,
        "benefit": "Tighter stops cut losers faster; wider stops reduce noise exits.",
    },
    "adx_threshold": {
        "values": [15, 20, 25, 30], "default": 20, "unit": "ADX",
        "config_key": None, "config_level": False,
        "benefit": "Higher ADX filters demand stronger trends before entry.",
    },
    "volume_filter": {
        "values": [0.5, 0.75, 1.0, 1.25], "default": 1.0, "unit": "x avg volume",
        "config_key": None, "config_level": False,
        "benefit": "Stricter volume confirmation avoids illiquid or unconvincing moves.",
    },
    "ema_combination": {
        "values": ["20/50", "20/100", "50/200"], "default": "9/20/50", "unit": "EMA pair",
        "config_key": None, "config_level": False,
        "benefit": "Slower EMA pairs reduce whipsaw at the cost of later entries.",
    },
    "rsi_threshold": {
        "values": [30, 35, 40], "default": 40, "unit": "RSI",
        "config_key": None, "config_level": False,
        "benefit": "Lower RSI floors allow earlier pullback entries; higher floors demand momentum.",
    },
    "supertrend_settings": {
        "values": ["7/2.0", "10/3.0", "14/3.5"], "default": "10/3.0", "unit": "period/multiplier",
        "config_key": None, "config_level": False,
        "benefit": "Faster supertrend reacts sooner; slower settings hold through pullbacks.",
    },
    "risk_reward_ratio": {
        "values": ["1.5:1", "2:1", "3:1"], "default": "2:1", "unit": "RR",
        "config_key": None, "config_level": False,
        "benefit": "Higher RR targets need lower win rates to break even but are hit less often.",
    },
    "stop_loss_logic": {
        "values": ["fixed_atr", "swing_low", "trailing_atr"], "default": "fixed_atr", "unit": "rule",
        "config_key": None, "config_level": False,
        "benefit": "Structural stops respect price levels; trailing stops lock in gains.",
    },
    "take_profit_logic": {
        "values": ["fixed_target", "scale_out", "trail_to_breakeven"], "default": "fixed_target", "unit": "rule",
        "config_key": None, "config_level": False,
        "benefit": "Scaling out banks partial profits; trailing captures extended moves.",
    },
    "exit_rules": {
        "values": ["ema_cross", "supertrend_flip", "time_stop_only"], "default": "ema_cross", "unit": "rule",
        "config_key": None, "config_level": False,
        "benefit": "Different exit triggers trade off responsiveness against staying in trends.",
    },
}


def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _load_json(path, default):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return default


def _save_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=1, default=str)
    os.replace(tmp, path)


def _num(v, nd=2):
    try:
        f = float(v)
        if f != f:
            return None
        return round(f, nd)
    except (TypeError, ValueError):
        return None


def _evidence_label(n):
    n = int(n or 0)
    if n >= 100:
        return "STRONG"
    if n >= 30:
        return "MODERATE"
    if n >= 10:
        return "WEAK"
    return "INSUFFICIENT"


# ── Registry ──────────────────────────────────────────────────────────────────

def _seed_registry():
    """Seed version-1 entries from the built-in strategies (read-only)."""
    entries = []
    for s in ALL_STRATEGIES:
        entries.append({
            "strategy_id": f"root_{s.id}",
            "name": s.name,
            "base_strategy": s.id,
            "parent_id": None,
            "version": 1,
            "created_at": _now(),
            "status": "Research",
            "author": "system (built-in)",
            "notes": s.description,
            "change_summary": "Baseline built-in strategy (version 1).",
            "mutation": None,
            "config_level": False,
            "proposed_config": None,
            "best_regime": getattr(s, "best_regime", ""),
            "linked_experiment_ids": [],
            "evaluation": None,
        })
    return {"strategies": entries, "created_at": _now(), "safety": SAFETY}


def _load_registry():
    reg = _load_json(REGISTRY_PATH, None)
    if not reg or not reg.get("strategies"):
        reg = _seed_registry()
        _save_json(REGISTRY_PATH, reg)
    return reg


def _perf_by_strategy():
    """Cross-experiment OOS performance per base strategy (research data only)."""
    frames = []
    exp_ids_by_strategy = {}
    for exp_id, _d, _status, _config, df, _report in _completed_experiments():
        if df is None or df.empty or "strategy_name" not in df.columns:
            continue
        f = df.copy()
        f["__exp"] = exp_id
        frames.append(f)
    if not frames:
        return {}, {}
    allt = pd.concat(frames, ignore_index=True)
    allt["net_pnl"] = pd.to_numeric(allt.get("net_pnl"), errors="coerce")
    allt["return_pct"] = pd.to_numeric(allt.get("return_pct"), errors="coerce")
    out = {}
    for name, g in allt.groupby("strategy_name"):
        n = len(g)
        wins = int((g["net_pnl"] > 0).sum())
        gp = float(g.loc[g["net_pnl"] > 0, "net_pnl"].sum())
        gl = abs(float(g.loc[g["net_pnl"] < 0, "net_pnl"].sum()))
        rets = g["return_pct"].dropna()
        sharpe_proxy = None
        if len(rets) >= 3 and rets.std(ddof=1) > 0:
            sharpe_proxy = round(float(rets.mean() / rets.std(ddof=1)), 3)
        out[str(name)] = {
            "trades": n, "win_rate": round(wins / n * 100.0, 1) if n else None,
            "net_pnl": round(float(g["net_pnl"].sum()), 2),
            "expectancy_rs": round(float(g["net_pnl"].mean()), 2) if n else None,
            "profit_factor": round(gp / gl, 2) if gl > 0 else None,
            "sharpe_proxy": sharpe_proxy,
            "evidence": _evidence_label(n),
        }
        exp_ids_by_strategy[str(name)] = sorted(set(g["__exp"].astype(str)))
    return out, exp_ids_by_strategy


_STRATEGY_LABELS = {s.id: s.name for s in ALL_STRATEGIES}


def _evidence_score(perf):
    """0–100 evidence score: sample size + consistency, honestly conservative."""
    if not perf:
        return 0
    n = perf.get("trades") or 0
    score = min(50, n / 2)  # up to 50 pts for sample size (100+ trades)
    pf = perf.get("profit_factor")
    if pf is not None:
        score += max(0, min(25, (pf - 0.8) * 25))
    sp = perf.get("sharpe_proxy")
    if sp is not None:
        score += max(0, min(25, (sp + 0.2) * 50))
    return int(round(min(100, score)))


def cmd_registry():
    reg = _load_registry()
    perf, exp_ids = _perf_by_strategy()
    for e in reg["strategies"]:
        base = e.get("base_strategy")
        label = _STRATEGY_LABELS.get(base, base)
        p = perf.get(label) or perf.get(base)
        e["current_performance"] = p
        e["evidence_score"] = _evidence_score(p) if e["parent_id"] is None else e.get("evidence_score")
        if e["parent_id"] is None:
            e["linked_experiment_ids"] = exp_ids.get(label) or exp_ids.get(base) or []
            if p is None:
                e["research_verdict"] = "NO_DATA"
            elif (p.get("expectancy_rs") or 0) > 0 and (p.get("profit_factor") or 0) >= 1.1:
                e["research_verdict"] = "PROMISING"
            elif (p.get("expectancy_rs") or 0) > 0:
                e["research_verdict"] = "MARGINAL"
            else:
                e["research_verdict"] = "UNDERPERFORMING"
    counts = {}
    for e in reg["strategies"]:
        counts[e["status"]] = counts.get(e["status"], 0) + 1
    return {"success": True, "strategies": reg["strategies"], "status_counts": counts,
            "parameter_space": PARAM_SPACE, **{"safety": SAFETY}}


# ── Mutation engine ───────────────────────────────────────────────────────────

def cmd_mutate(strategy_id, parameters=None, author="researcher"):
    """Generate Draft variants of one strategy. One major parameter per variant.
    Variants are NEVER activated automatically."""
    reg = _load_registry()
    parent = next((e for e in reg["strategies"] if e["strategy_id"] == strategy_id), None)
    if not parent:
        return {"success": False, "error": f"Strategy '{strategy_id}' not found in registry."}
    if parent["status"] in ("Rejected", "Archived"):
        return {"success": False,
                "error": f"Cannot mutate a {parent['status']} strategy — revive it to Research first."}

    params = [p for p in (parameters or list(PARAM_SPACE.keys())) if p in PARAM_SPACE]
    if not params:
        return {"success": False, "error": "No valid parameters requested.",
                "valid_parameters": list(PARAM_SPACE.keys())}

    existing = {(e.get("parent_id"), (e.get("mutation") or {}).get("parameter"),
                 str((e.get("mutation") or {}).get("to")))
                for e in reg["strategies"]}
    created = []
    child_version = max([e["version"] for e in reg["strategies"]
                         if e.get("base_strategy") == parent["base_strategy"]] or [1]) + 1
    for pname in params:
        spec = PARAM_SPACE[pname]
        for val in spec["values"]:
            if str(val) == str(spec["default"]):
                continue
            if (strategy_id, pname, str(val)) in existing:
                continue  # already generated — preserve every experiment, no dupes
            vid = uuid.uuid4().hex[:12]
            proposed_config = None
            if spec["config_level"] and spec["config_key"]:
                proposed_config = {spec["config_key"]: val}
            entry = {
                "strategy_id": vid,
                "name": f"{parent['name']} — {pname}={val}",
                "base_strategy": parent["base_strategy"],
                "parent_id": strategy_id,
                "version": child_version,
                "created_at": _now(),
                "status": "Draft",
                "author": author,
                "notes": f"Controlled mutation of {parent['name']}: only '{pname}' changed "
                         f"({spec['default']} → {val}). Requires human approval before any use.",
                "change_summary": f"{pname}: {spec['default']} → {val} ({spec['unit']})",
                "mutation": {
                    "parameter": pname,
                    "from": spec["default"],
                    "to": val,
                    "unit": spec["unit"],
                    "expected_benefit": spec["benefit"],
                    "observed_benefit": None,   # honest blank until tested
                    "observed_drawback": None,  # honest blank until tested
                    "confidence_in_recommendation": None,
                    "evidence_for": None,
                    "evidence_against": None,
                },
                "config_level": bool(spec["config_level"]),
                "proposed_config": proposed_config,
                "testable_now": bool(spec["config_level"]),
                "testing_note": (
                    "Config-level parameter — can be tested by submitting a Research Factory "
                    "experiment with the proposed config." if spec["config_level"] else
                    "Strategy-code-level parameter — recorded as a research proposal; testing "
                    "requires a code-level variant which is NOT created automatically."),
                "linked_experiment_ids": [],
                "evaluation": None,
            }
            reg["strategies"].append(entry)
            created.append(entry)
        child_version += 1
    _save_json(REGISTRY_PATH, reg)
    return {"success": True, "parent": parent["strategy_id"], "created": len(created),
            "variants": created,
            "note": "Variants are Draft research candidates only — nothing was activated.",
            "safety": SAFETY}


def cmd_set_status(strategy_id, status, note=""):
    """Explicit human action: change a variant's lifecycle status."""
    if status not in VALID_STATUSES:
        return {"success": False, "error": f"Invalid status. Valid: {VALID_STATUSES}"}
    reg = _load_registry()
    e = next((x for x in reg["strategies"] if x["strategy_id"] == strategy_id), None)
    if not e:
        return {"success": False, "error": f"Strategy '{strategy_id}' not found."}
    if e["parent_id"] is None and status in ("Rejected", "Archived"):
        return {"success": False, "error": "Baseline built-in strategies cannot be rejected or archived here."}
    old = e["status"]
    e["status"] = status
    e.setdefault("history", []).append({"at": _now(), "from": old, "to": status, "note": note})
    _save_json(REGISTRY_PATH, reg)
    return {"success": True, "strategy_id": strategy_id, "from": old, "to": status, "safety": SAFETY}


def cmd_link_experiment(strategy_id, exp_id):
    """Link a Research Factory experiment to a variant (evidence trail)."""
    reg = _load_registry()
    e = next((x for x in reg["strategies"] if x["strategy_id"] == strategy_id), None)
    if not e:
        return {"success": False, "error": f"Strategy '{strategy_id}' not found."}
    ids = set(e.get("linked_experiment_ids") or [])
    ids.add(exp_id)
    e["linked_experiment_ids"] = sorted(ids)
    _save_json(REGISTRY_PATH, reg)
    return {"success": True, "strategy_id": strategy_id, "linked_experiment_ids": e["linked_experiment_ids"]}


# ── Experiment metric extraction (for A/B + robustness) ──────────────────────

def _exp_bundle(exp_id):
    exp_dir = os.path.join(BASE_DIR, "experiments", exp_id)
    if not os.path.isdir(exp_dir):
        return None
    status = _load_json(os.path.join(exp_dir, "status.json"), {})
    config = _load_json(os.path.join(exp_dir, "config.json"), {})
    wf = _load_json(os.path.join(exp_dir, "wf_result.json"), {})
    return {"exp_id": exp_id, "status": status, "config": config, "wf": wf}


def _exp_metrics(b):
    wf = b["wf"] or {}
    overall = (wf.get("overall") or {}).get("full_metrics") or {}
    windows = wf.get("windows") or []
    win_rets = []
    for w in windows:
        m = w.get("full_metrics") or {}
        r = _num(m.get("total_return_pct"), 4)
        if r is not None:
            win_rets.append(r)
    cal = wf.get("calibration_report") or wf.get("calibration") or {}
    ece = None
    if isinstance(cal, dict):
        for k in ("ece_after", "ece", "after_ece"):
            if _num(cal.get(k)) is not None:
                ece = _num(cal.get(k), 4)
                break
    return {
        "trades": overall.get("total_trades"),
        "windows": len(windows),
        "window_returns_pct": win_rets,
        "positive_windows": sum(1 for r in win_rets if r > 0),
        "net_return_pct": _num(overall.get("total_return_pct")),
        "net_profit": _num(overall.get("net_profit")),
        "total_costs": _num(overall.get("total_costs")),
        "profit_factor": _num(overall.get("profit_factor")),
        "sharpe": _num(overall.get("sharpe_ratio"), 3),
        "sortino": _num(overall.get("sortino_ratio"), 3),
        "max_drawdown_pct": _num(overall.get("max_drawdown_pct")),
        "win_rate": _num(overall.get("win_rate"), 1),
        "expectancy": _num(overall.get("expectancy")),
        "calibration_ece": ece,
        "overfitting_flags": (b["status"] or {}).get("overfitting_flags") or [],
    }


_AXES = ["train_years", "test_months", "step_months", "start_date", "end_date",
         "universe_size", "intrabar_rule"]


def _matched_axes(ca, cb):
    same, diff = [], []
    for k in _AXES:
        (same if ca.get(k) == cb.get(k) else diff).append(k)
    return same, diff


def _welch_t(a, b):
    """Welch t statistic + rough significance label (no scipy dependency)."""
    if len(a) < 2 or len(b) < 2:
        return None, "INSUFFICIENT_WINDOWS"
    va, vb = statistics.variance(a), statistics.variance(b)
    denom = (va / len(a) + vb / len(b)) ** 0.5
    if denom == 0:
        return None, "NO_VARIANCE"
    t = (statistics.mean(a) - statistics.mean(b)) / denom
    label = ("LIKELY_MEANINGFUL" if abs(t) >= 2.0 else
             "POSSIBLY_MEANINGFUL" if abs(t) >= 1.0 else "NOT_DISTINGUISHABLE")
    return round(t, 3), label


# ── A/B testing ───────────────────────────────────────────────────────────────

def cmd_ab_test(parent_strategy_id, candidate_strategy_id, exp_a, exp_b):
    """Controlled A/B comparison of two experiments (parent vs candidate)."""
    reg = _load_registry()
    p = next((x for x in reg["strategies"] if x["strategy_id"] == parent_strategy_id), None)
    c = next((x for x in reg["strategies"] if x["strategy_id"] == candidate_strategy_id), None)
    if not p or not c:
        return {"success": False, "error": "Parent or candidate strategy not found in registry."}
    ba, bb = _exp_bundle(exp_a), _exp_bundle(exp_b)
    if not ba or not bb:
        return {"success": False, "error": "One or both experiments were not found."}
    ma, mb = _exp_metrics(ba), _exp_metrics(bb)
    same, diff = _matched_axes(ba["config"], bb["config"])
    controlled = len(diff) == 0

    # Winner determination — conservative, evidence-first
    score_a = score_b = 0
    checks = []
    for metric, higher_better in [("profit_factor", True), ("sharpe", True),
                                  ("net_return_pct", True), ("max_drawdown_pct", False),
                                  ("calibration_ece", False)]:
        va, vb = ma.get(metric), mb.get(metric)
        if va is None or vb is None:
            checks.append({"metric": metric, "parent": va, "candidate": vb, "winner": "NO_DATA"})
            continue
        better_b = (vb > va) if higher_better else (vb < va)
        if va == vb:
            w = "TIE"
        elif better_b:
            w = "candidate"
            score_b += 1
        else:
            w = "parent"
            score_a += 1
        checks.append({"metric": metric, "parent": va, "candidate": vb, "winner": w})

    t_stat, t_label = _welch_t(ma["window_returns_pct"], mb["window_returns_pct"])
    ev_a, ev_b = _evidence_label(ma["trades"]), _evidence_label(mb["trades"])
    min_ev = min(ma.get("trades") or 0, mb.get("trades") or 0)

    if score_a == score_b:
        winner = "INCONCLUSIVE"
    else:
        winner = "candidate" if score_b > score_a else "parent"
    confidence = "LOW"
    if winner != "INCONCLUSIVE" and controlled and min_ev >= 30 and t_label == "LIKELY_MEANINGFUL":
        confidence = "HIGH"
    elif winner != "INCONCLUSIVE" and min_ev >= 10 and t_label in ("LIKELY_MEANINGFUL", "POSSIBLY_MEANINGFUL"):
        confidence = "MEDIUM"

    if not controlled:
        recommendation = (f"Comparison is NOT fully controlled (differing: {', '.join(diff)}). "
                          "Re-run both experiments with identical settings before drawing conclusions.")
    elif winner == "INCONCLUSIVE":
        recommendation = "No clear winner — keep both under research; collect more evidence."
    elif min_ev < 30:
        recommendation = (f"{winner.capitalize()} leads on {max(score_a, score_b)}/5 metrics, but evidence is "
                          f"{_evidence_label(min_ev)} ({min_ev} trades) — do not act; extend testing.")
    else:
        recommendation = (f"{winner.capitalize()} wins {max(score_a, score_b)}/5 metric checks with "
                          f"{confidence} confidence. This remains a research finding only — "
                          "human approval is required for any change.")

    result = {
        "id": uuid.uuid4().hex[:12], "created_at": _now(),
        "parent_strategy": {"id": p["strategy_id"], "name": p["name"], "experiment_id": exp_a},
        "candidate_strategy": {"id": c["strategy_id"], "name": c["name"], "experiment_id": exp_b,
                               "change_summary": c.get("change_summary")},
        "controlled": controlled, "matched_axes": same, "differing_axes": diff,
        "metric_checks": checks,
        "winner": winner, "confidence": confidence,
        "evidence": {"parent_trades": ma["trades"], "candidate_trades": mb["trades"],
                     "parent_evidence": ev_a, "candidate_evidence": ev_b,
                     "evidence_difference": (mb.get("trades") or 0) - (ma.get("trades") or 0)},
        "statistical_difference": {"welch_t": t_stat, "interpretation": t_label,
                                   "basis": "per-window total returns"},
        "recommendation": recommendation,
        "parent_metrics": ma, "candidate_metrics": mb,
        "safety": SAFETY,
    }
    tests = _load_json(AB_PATH, [])
    tests.append(result)
    _save_json(AB_PATH, tests)
    # Record observed outcome on the candidate's mutation record (honest values)
    if c.get("mutation"):
        pfd = (mb.get("profit_factor") or 0) - (ma.get("profit_factor") or 0)
        ddd = (mb.get("max_drawdown_pct") or 0) - (ma.get("max_drawdown_pct") or 0)
        c["mutation"]["observed_benefit"] = (
            f"Profit factor {'+' if pfd >= 0 else ''}{round(pfd, 2)} vs parent" if pfd > 0 else None)
        c["mutation"]["observed_drawback"] = (
            f"Max drawdown {'+' if ddd >= 0 else ''}{round(ddd, 2)}pp vs parent" if ddd > 0 else None)
        c["mutation"]["confidence_in_recommendation"] = confidence
        c["mutation"]["evidence_for"] = f"{mb.get('trades')} candidate OOS trades ({ev_b})"
        c["mutation"]["evidence_against"] = (
            f"Uncontrolled axes: {', '.join(diff)}" if diff else
            (f"Only {min_ev} trades on the weaker side" if min_ev < 30 else None))
        _save_json(REGISTRY_PATH, reg)
    return {"success": True, "ab_test": result}


def cmd_ab_list():
    return {"success": True, "ab_tests": _load_json(AB_PATH, []), "safety": SAFETY}


# ── Robustness testing ────────────────────────────────────────────────────────

def cmd_robustness(exp_id):
    """Robustness score (0–100) for an experiment + automatic rejection reasons."""
    b = _exp_bundle(exp_id)
    if not b:
        return {"success": False, "error": f"Experiment '{exp_id}' not found."}
    m = _exp_metrics(b)
    wf = b["wf"] or {}

    # Trade-level concentration (regime / sector / stock)
    trades_df = None
    for exp_id2, _d, _s, _c, df, _r in _completed_experiments():
        if exp_id2 == exp_id:
            trades_df = df
            break
    reasons, warnings = [], []
    score = 100.0
    n = m.get("trades") or 0

    if n < 10:
        reasons.append(f"Depends on very few trades ({n} < 10).")
        score -= 35
    elif n < 30:
        warnings.append(f"Small sample ({n} trades) — evidence is {_evidence_label(n)}.")
        score -= 15

    def _concentration(col, label, threshold=0.70):
        nonlocal score
        if trades_df is None or trades_df.empty or col not in trades_df.columns:
            warnings.append(f"{label} concentration could not be evaluated (no trade data).")
            return None
        pnl = pd.to_numeric(trades_df["net_pnl"], errors="coerce").fillna(0)
        pos = pnl[pnl > 0]
        if pos.empty:
            return None
        by = trades_df.loc[pos.index].groupby(col)[
            "net_pnl"].apply(lambda s: pd.to_numeric(s, errors="coerce").sum())
        top = by.sort_values(ascending=False)
        share = float(top.iloc[0]) / float(pos.sum()) if float(pos.sum()) > 0 else 0
        if share >= threshold:
            reasons.append(f"Depends on one {label.lower()}: '{top.index[0]}' contributes "
                           f"{round(share * 100)}% of gross winning P&L.")
            score -= 15
        return {"top": str(top.index[0]), "share_pct": round(share * 100, 1)}

    conc = {
        "regime": _concentration("market_regime", "Market regime"),
        "sector": _concentration("sector", "Sector"),
        "stock": _concentration("symbol", "Stock"),
    }

    if (m.get("net_profit") or 0) <= 0:
        reasons.append("Loses after realistic costs (net profit ≤ 0 including commissions/slippage).")
        score -= 25

    wr = m.get("window_returns_pct") or []
    if len(wr) >= 2:
        pos_share = m["positive_windows"] / len(wr)
        if pos_share < 0.5:
            reasons.append(f"Unstable walk-forward results: only {m['positive_windows']}/{len(wr)} "
                           "windows were positive.")
            score -= 15
        if len(wr) >= 3 and statistics.pstdev(wr) > max(5.0, abs(statistics.mean(wr)) * 3):
            warnings.append("High variance across walk-forward windows.")
            score -= 5
    else:
        warnings.append("Too few windows to judge walk-forward stability.")

    flags = m.get("overfitting_flags") or []
    if flags:
        reasons.append(f"Probable overfitting flagged by validator: {', '.join(map(str, flags))[:200]}")
        score -= 15

    ece = m.get("calibration_ece")
    if ece is not None and ece > 0.15:
        reasons.append(f"Inconsistent calibration (ECE {ece} > 0.15).")
        score -= 10
    elif ece is None:
        warnings.append("Calibration ECE unavailable — not scored, not assumed.")

    score = max(0, min(100, round(score)))
    verdict = "REJECT" if reasons else ("CAUTION" if warnings else "ROBUST")
    return {"success": True, "experiment_id": exp_id, "robustness_score": score,
            "verdict": verdict, "rejection_reasons": reasons, "warnings": warnings,
            "concentration": conc, "metrics": m, "safety": SAFETY}


# ── Survival rules ────────────────────────────────────────────────────────────

def cmd_evaluate(candidate_strategy_id, exp_candidate, exp_parent):
    """Apply survival rules to a candidate vs its parent baseline.
    Survivors become 'Candidate'; failures are 'Archived'. Research only."""
    reg = _load_registry()
    c = next((x for x in reg["strategies"] if x["strategy_id"] == candidate_strategy_id), None)
    if not c:
        return {"success": False, "error": "Candidate not found in registry."}
    if c["parent_id"] is None:
        return {"success": False, "error": "Baselines are not evaluated by survival rules."}
    bc, bp = _exp_bundle(exp_candidate), _exp_bundle(exp_parent)
    if not bc or not bp:
        return {"success": False, "error": "Candidate or parent experiment not found."}
    mc, mp = _exp_metrics(bc), _exp_metrics(bp)
    rob = cmd_robustness(exp_candidate)
    rules = []

    def rule(name, passed, detail):
        rules.append({"rule": name, "passed": bool(passed), "detail": detail})

    pf_c, pf_p = mc.get("profit_factor"), mp.get("profit_factor")
    rule("Improves profit factor",
         pf_c is not None and pf_p is not None and pf_c > pf_p,
         f"candidate {pf_c} vs parent {pf_p}")
    sh_c, sh_p = mc.get("sharpe"), mp.get("sharpe")
    rule("Maintains or improves Sharpe",
         sh_c is not None and sh_p is not None and sh_c >= sh_p - 0.05,
         f"candidate {sh_c} vs parent {sh_p} (tolerance −0.05)")
    dd_c, dd_p = mc.get("max_drawdown_pct"), mp.get("max_drawdown_pct")
    rule("Does not materially increase drawdown",
         dd_c is not None and dd_p is not None and dd_c <= dd_p * 1.2 + 1.0,
         f"candidate {dd_c}% vs parent {dd_p}% (limit {round((dd_p or 0) * 1.2 + 1.0, 2)}%)")
    e_c, e_p = mc.get("calibration_ece"), mp.get("calibration_ece")
    if e_c is None or e_p is None:
        rule("Maintains calibration", False, "ECE unavailable — cannot verify, so rule fails honestly")
    else:
        rule("Maintains calibration", e_c <= e_p + 0.03, f"candidate ECE {e_c} vs parent {e_p} (+0.03 tolerance)")
    wr = mc.get("window_returns_pct") or []
    rule("Passes walk-forward validation",
         len(wr) >= 2 and mc["positive_windows"] / len(wr) >= 0.5,
         f"{mc.get('positive_windows')}/{len(wr)} positive windows (need ≥50%)")
    rule("Passes evidence thresholds",
         (mc.get("trades") or 0) >= 30,
         f"{mc.get('trades')} OOS trades (need ≥30)")
    rule("Passes robustness screen",
         rob.get("success") and rob.get("verdict") != "REJECT",
         f"robustness verdict: {rob.get('verdict')} (score {rob.get('robustness_score')})")

    survives = all(r["passed"] for r in rules)
    new_status = "Candidate" if survives else "Archived"
    old_status = c["status"]
    c["status"] = new_status
    c["evaluation"] = {
        "at": _now(), "exp_candidate": exp_candidate, "exp_parent": exp_parent,
        "rules": rules, "survives": survives,
        "robustness_score": rob.get("robustness_score"),
        "robustness_reasons": rob.get("rejection_reasons"),
    }
    c.setdefault("history", []).append({
        "at": _now(), "from": old_status, "to": new_status,
        "note": "Survival rules " + ("passed" if survives else
                f"failed: {sum(1 for r in rules if not r['passed'])} rule(s)")})
    ids = set(c.get("linked_experiment_ids") or [])
    ids.add(exp_candidate)
    c["linked_experiment_ids"] = sorted(ids)
    _save_json(REGISTRY_PATH, reg)
    return {"success": True, "strategy_id": candidate_strategy_id,
            "survives": survives, "new_status": new_status, "rules": rules,
            "robustness": {k: rob.get(k) for k in ("robustness_score", "verdict",
                                                   "rejection_reasons", "warnings")},
            "note": "Status change is within the research registry only — production is untouched.",
            "safety": SAFETY}


# ── Genealogy: family tree + evolution timeline ───────────────────────────────

def cmd_tree():
    reg = _load_registry()
    perf, _ = _perf_by_strategy()
    by_parent = {}
    for e in reg["strategies"]:
        by_parent.setdefault(e.get("parent_id"), []).append(e)

    def node(e):
        label = _STRATEGY_LABELS.get(e.get("base_strategy"), e.get("base_strategy"))
        return {
            "strategy_id": e["strategy_id"], "name": e["name"], "version": e["version"],
            "status": e["status"], "change_summary": e.get("change_summary"),
            "created_at": e.get("created_at"),
            "mutation": e.get("mutation"),
            "evaluation": (e.get("evaluation") or {}).get("survives") if e.get("evaluation") else None,
            "performance": perf.get(label) if e["parent_id"] is None else None,
            "children": sorted([node(cc) for cc in by_parent.get(e["strategy_id"], [])],
                               key=lambda x: x["created_at"]),
        }

    roots = sorted([node(e) for e in by_parent.get(None, [])], key=lambda x: x["name"])

    timeline = []
    for e in reg["strategies"]:
        timeline.append({"at": e["created_at"], "type": "created",
                         "strategy_id": e["strategy_id"], "name": e["name"],
                         "what_changed": e.get("change_summary"),
                         "why": (e.get("mutation") or {}).get("expected_benefit") if e.get("mutation")
                                else "Baseline strategy",
                         "status": e["status"]})
        for h in e.get("history", []) or []:
            timeline.append({"at": h["at"], "type": "status_change",
                             "strategy_id": e["strategy_id"], "name": e["name"],
                             "what_changed": f"{h['from']} → {h['to']}",
                             "why": h.get("note") or "", "status": h["to"]})
        ev = e.get("evaluation")
        if ev:
            timeline.append({"at": ev["at"], "type": "evaluation",
                             "strategy_id": e["strategy_id"], "name": e["name"],
                             "what_changed": "Survival rules applied",
                             "why": f"{sum(1 for r in ev['rules'] if r['passed'])}/{len(ev['rules'])} rules passed",
                             "status": e["status"]})
    timeline.sort(key=lambda x: x["at"])
    return {"success": True, "tree": roots, "timeline": timeline, "safety": SAFETY}


def cmd_leaderboard():
    """Rank tested variants: best performing, most stable, highest evidence."""
    reg = _load_registry()
    tests = _load_json(AB_PATH, [])
    latest_by_candidate = {}
    for t in tests:
        latest_by_candidate[t["candidate_strategy"]["id"]] = t
    entries = []
    for e in reg["strategies"]:
        if e["parent_id"] is None:
            continue
        t = latest_by_candidate.get(e["strategy_id"])
        m = (t or {}).get("candidate_metrics") or {}
        wr = m.get("window_returns_pct") or []
        stability = None
        if len(wr) >= 2:
            stability = round(m.get("positive_windows", 0) / len(wr) * 100, 1)
        entries.append({
            "strategy_id": e["strategy_id"], "name": e["name"], "status": e["status"],
            "change_summary": e.get("change_summary"),
            "tested": t is not None,
            "profit_factor": m.get("profit_factor"), "sharpe": m.get("sharpe"),
            "net_return_pct": m.get("net_return_pct"),
            "max_drawdown_pct": m.get("max_drawdown_pct"),
            "trades": m.get("trades"), "evidence": _evidence_label(m.get("trades")),
            "window_positive_pct": stability,
            "robustness_score": (e.get("evaluation") or {}).get("robustness_score"),
        })
    tested = [x for x in entries if x["tested"]]
    highlights = {
        "best_performing": max(tested, key=lambda x: (x["profit_factor"] or 0), default=None),
        "most_stable": max(tested, key=lambda x: (x["window_positive_pct"] or 0), default=None),
        "highest_evidence": max(tested, key=lambda x: (x["trades"] or 0), default=None),
    }
    return {"success": True, "variants": entries, "highlights": highlights,
            "note": "Untested variants show honest blanks — no metrics are invented.",
            "safety": SAFETY}


# ── Strategy knowledge base ───────────────────────────────────────────────────

def cmd_knowledge():
    """Lessons learned per base strategy from cross-experiment OOS trades."""
    frames = []
    for exp_id, _d, _s, _c, df, _r in _completed_experiments():
        if df is None or df.empty:
            continue
        f = df.copy()
        f["__exp"] = exp_id
        frames.append(f)
    if not frames:
        return {"success": True, "lessons": [],
                "note": "No completed experiments with trades yet — knowledge base is honestly empty.",
                "safety": SAFETY}
    allt = pd.concat(frames, ignore_index=True)
    allt["net_pnl"] = pd.to_numeric(allt.get("net_pnl"), errors="coerce")
    lessons = []
    for (strat,), g in allt.groupby(["strategy_name"]):
        works, fails = [], []
        for col, label in [("market_regime", "Market regime"), ("sector", "Sector")]:
            if col not in g.columns:
                continue
            for ctx, sub in g.groupby(col):
                n = len(sub)
                if n < 3:
                    continue  # too little evidence to call it a lesson
                exp_ids = sorted(set(sub["__exp"].astype(str)))
                item = {
                    "context": f"{label}: {ctx}",
                    "trades": n,
                    "expectancy_rs": round(float(sub["net_pnl"].mean()), 2),
                    "win_rate": round(float((sub["net_pnl"] > 0).mean() * 100), 1),
                    "net_pnl": round(float(sub["net_pnl"].sum()), 2),
                    "confidence": _evidence_label(n),
                    "evidence": f"{n} OOS trades across {len(exp_ids)} experiment(s)",
                    "experiment_ids": exp_ids,
                }
                (works if item["expectancy_rs"] > 0 else fails).append(item)
        works.sort(key=lambda x: -x["expectancy_rs"])
        fails.sort(key=lambda x: x["expectancy_rs"])
        lessons.append({"strategy": str(strat), "works_well": works[:8], "fails": fails[:8],
                        "total_trades": int(len(g))})
    lessons.sort(key=lambda x: -x["total_trades"])
    return {"success": True, "lessons": lessons,
            "note": "Lessons are statistical observations from simulated research trades — never certainty.",
            "safety": SAFETY}


# ── Exports (CSV / JSON / printable HTML) ─────────────────────────────────────

def _esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def cmd_export():
    import csv
    os.makedirs(EXPORT_DIR, exist_ok=True)
    reg = cmd_registry()
    tree = cmd_tree()
    lb = cmd_leaderboard()
    kb = cmd_knowledge()
    tests = _load_json(AB_PATH, [])

    bundle = {
        "generated_at": _now(), "phase": "Phase 6 — Strategy Evolution Laboratory",
        "safety": SAFETY,
        "strategy_registry": reg["strategies"],
        "family_tree": tree["tree"],
        "evolution_timeline": tree["timeline"],
        "mutation_history": [e for e in reg["strategies"] if e.get("mutation")],
        "ab_tests": tests,
        "robustness_reports": [e.get("evaluation") for e in reg["strategies"] if e.get("evaluation")],
        "knowledge_base": kb["lessons"],
        "candidate_leaderboard": lb["variants"],
        "rejected_candidates": [e for e in reg["strategies"] if e["status"] in ("Rejected", "Archived")],
    }
    json_path = os.path.join(EXPORT_DIR, "phase6_evolution_export.json")
    with open(json_path, "w") as f:
        json.dump(bundle, f, indent=1, default=str)

    csv_path = os.path.join(EXPORT_DIR, "phase6_evolution_export.csv")
    cols = ["record_type", "strategy_id", "name", "base_strategy", "parent_id", "version",
            "status", "change_summary", "mutation_parameter", "mutation_from", "mutation_to",
            "expected_benefit", "observed_benefit", "observed_drawback",
            "profit_factor", "sharpe", "net_return_pct", "max_drawdown_pct", "trades",
            "evidence", "robustness_score", "winner", "confidence", "recommendation",
            "context", "expectancy_rs", "win_rate", "experiment_ids", "created_at", "notes"]
    n_rows = 0
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for e in reg["strategies"]:
            mu = e.get("mutation") or {}
            perf = e.get("current_performance") or {}
            w.writerow({"record_type": "strategy", "strategy_id": e["strategy_id"],
                        "name": e["name"], "base_strategy": e.get("base_strategy"),
                        "parent_id": e.get("parent_id") or "", "version": e["version"],
                        "status": e["status"], "change_summary": e.get("change_summary"),
                        "mutation_parameter": mu.get("parameter", ""),
                        "mutation_from": mu.get("from", ""), "mutation_to": mu.get("to", ""),
                        "expected_benefit": mu.get("expected_benefit", ""),
                        "observed_benefit": mu.get("observed_benefit") or "",
                        "observed_drawback": mu.get("observed_drawback") or "",
                        "profit_factor": perf.get("profit_factor", ""),
                        "trades": perf.get("trades", ""),
                        "evidence": perf.get("evidence", ""),
                        "robustness_score": (e.get("evaluation") or {}).get("robustness_score", ""),
                        "experiment_ids": ";".join(e.get("linked_experiment_ids") or []),
                        "created_at": e.get("created_at"), "notes": e.get("notes", "")})
            n_rows += 1
        for t in tests:
            w.writerow({"record_type": "ab_test", "strategy_id": t["candidate_strategy"]["id"],
                        "name": f"{t['parent_strategy']['name']} vs {t['candidate_strategy']['name']}",
                        "winner": t["winner"], "confidence": t["confidence"],
                        "recommendation": t["recommendation"],
                        "profit_factor": (t.get("candidate_metrics") or {}).get("profit_factor", ""),
                        "sharpe": (t.get("candidate_metrics") or {}).get("sharpe", ""),
                        "trades": (t.get("candidate_metrics") or {}).get("trades", ""),
                        "experiment_ids": ";".join([t["parent_strategy"]["experiment_id"],
                                                    t["candidate_strategy"]["experiment_id"]]),
                        "created_at": t["created_at"]})
            n_rows += 1
        for les in kb["lessons"]:
            for kind, items in [("works_well", les["works_well"]), ("fails", les["fails"])]:
                for it in items:
                    w.writerow({"record_type": f"lesson_{kind}", "name": les["strategy"],
                                "context": it["context"], "trades": it["trades"],
                                "expectancy_rs": it["expectancy_rs"], "win_rate": it["win_rate"],
                                "evidence": it["confidence"],
                                "experiment_ids": ";".join(it["experiment_ids"])})
                    n_rows += 1

    # Printable HTML
    def rows_html(items, fields):
        out = []
        for it in items:
            out.append("<tr>" + "".join(f"<td>{_esc(it.get(f, '') if it.get(f) is not None else '')}</td>"
                                        for f in fields) + "</tr>")
        return "\n".join(out)

    strat_fields = ["name", "version", "status", "change_summary", "created_at"]
    html = f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<title>Phase 6 — Strategy Evolution Report</title>
<style>
body{{font-family:Georgia,serif;margin:40px;color:#111}}
h1{{border-bottom:3px solid #111}} h2{{margin-top:32px;border-bottom:1px solid #999}}
table{{border-collapse:collapse;width:100%;font-size:13px;margin:12px 0}}
th,td{{border:1px solid #bbb;padding:5px 8px;text-align:left;vertical-align:top}}
th{{background:#eee}} .safety{{background:#fff8e1;border:1px solid #e0c060;padding:12px;font-size:13px}}
@media print{{body{{margin:12mm}}}}
</style></head><body>
<h1>Phase 6 — Strategy Evolution Laboratory Report</h1>
<p>Generated {_esc(_now())} — research only.</p>
<div class="safety"><b>Safety:</b> {_esc(SAFETY['note'])} No live trading, paper trading,
trade-decision, scanner or portfolio logic was modified.</div>
<h2>Strategy Registry ({len(reg['strategies'])})</h2>
<table><tr>{"".join(f"<th>{_esc(h)}</th>" for h in strat_fields)}</tr>
{rows_html(reg['strategies'], strat_fields)}</table>
<h2>A/B Tests ({len(tests)})</h2>
<table><tr><th>Parent</th><th>Candidate</th><th>Winner</th><th>Confidence</th><th>Recommendation</th></tr>
{"".join(f"<tr><td>{_esc(t['parent_strategy']['name'])}</td><td>{_esc(t['candidate_strategy']['name'])}</td><td>{_esc(t['winner'])}</td><td>{_esc(t['confidence'])}</td><td>{_esc(t['recommendation'])}</td></tr>" for t in tests)}
</table>
<h2>Candidate Leaderboard ({len(lb['variants'])})</h2>
<table><tr><th>Name</th><th>Status</th><th>Change</th><th>PF</th><th>Sharpe</th><th>Trades</th><th>Evidence</th></tr>
{"".join(f"<tr><td>{_esc(x['name'])}</td><td>{_esc(x['status'])}</td><td>{_esc(x['change_summary'])}</td><td>{_esc(x['profit_factor'] if x['profit_factor'] is not None else '')}</td><td>{_esc(x['sharpe'] if x['sharpe'] is not None else '')}</td><td>{_esc(x['trades'] if x['trades'] is not None else '')}</td><td>{_esc(x['evidence'])}</td></tr>" for x in lb['variants'])}
</table>
<h2>Knowledge Base ({len(kb['lessons'])} strategies)</h2>
{"".join(f"<h3>{_esc(l['strategy'])} ({l['total_trades']} trades)</h3><table><tr><th>Type</th><th>Context</th><th>Trades</th><th>Expectancy ₹</th><th>Win rate %</th><th>Confidence</th></tr>" + "".join(f"<tr><td>Works well</td><td>{_esc(i['context'])}</td><td>{i['trades']}</td><td>{i['expectancy_rs']}</td><td>{i['win_rate']}</td><td>{_esc(i['confidence'])}</td></tr>" for i in l['works_well']) + "".join(f"<tr><td>Fails</td><td>{_esc(i['context'])}</td><td>{i['trades']}</td><td>{i['expectancy_rs']}</td><td>{i['win_rate']}</td><td>{_esc(i['confidence'])}</td></tr>" for i in l['fails']) + "</table>" for l in kb['lessons'])}
<h2>Evolution Timeline ({len(tree['timeline'])} events)</h2>
<table><tr><th>When</th><th>Event</th><th>Strategy</th><th>What changed</th><th>Why</th></tr>
{"".join(f"<tr><td>{_esc(ev['at'])}</td><td>{_esc(ev['type'])}</td><td>{_esc(ev['name'])}</td><td>{_esc(ev['what_changed'])}</td><td>{_esc(ev['why'])}</td></tr>" for ev in tree['timeline'])}
</table>
</body></html>"""
    html_path = os.path.join(EXPORT_DIR, "phase6_evolution_report.html")
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html)

    return {"success": True, "csv_file": csv_path, "json_file": json_path,
            "html_file": html_path, "csv_rows": n_rows,
            "strategies": len(reg["strategies"]), "ab_tests": len(tests),
            "safety": SAFETY}
