"""
phase21_baseline.py — Phase 21: Frozen baseline model snapshot + baseline report.

PAPER / RESEARCH ONLY.
- Freezes the current production rules as phase21_baseline_v1 (immutable).
- Never overwrites an existing baseline of the same version.
- Baseline report is computed from completed trades only; historical
  decisions are never rewritten.
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone

import config
from phase14_learning import learning_rows, group_metrics

_DIR = os.path.dirname(os.path.abspath(__file__))
BASELINE_FILE = os.path.join(_DIR, "phase21_baseline_v1.json")
BASELINE_REPORT_FILE = os.path.join(_DIR, "phase21_baseline_report.json")

BASELINE_VERSION = "phase21_baseline_v1"
MODEL_VERSION = "p13_champion_v1"   # current production champion
RULE_VERSION = "rv1"

CONFIDENCE_BUCKETS = [(0, 19), (20, 39), (40, 59), (60, 74), (75, 89), (90, 100)]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _current_rules() -> dict:
    """Snapshot of every rule that governs decisions today (from config.py)."""
    return {
        "confidence_rules": {
            "market_conf_mod_bullish": config.MARKET_CONF_MOD_BULLISH,
            "market_conf_mod_bearish": config.MARKET_CONF_MOD_BEARISH,
            "market_conf_mod_neutral": config.MARKET_CONF_MOD_NEUTRAL,
            "high_vol_conf_threshold": config.AI_HIGH_VOL_CONF_THRESHOLD,
            "sideways_conf_threshold": config.AI_SIDEWAYS_CONF_THRESHOLD,
        },
        "scoring_weights": {
            "trade_quality": config.TRADE_QUALITY_WEIGHTS,
            "opportunity": config.OPP_WEIGHTS,
        },
        "decision_thresholds": {
            "strong_buy": config.SIGNAL_STRONG_THRESHOLD,
            "buy": config.SIGNAL_BUY_THRESHOLD,
            "watch": config.SIGNAL_WATCH_THRESHOLD,
            "min": config.SIGNAL_MIN_THRESHOLD,
            "opp_hot_buy": config.OPP_HOT_BUY_THRESHOLD,
            "opp_buy": config.OPP_BUY_THRESHOLD,
            "opp_watch": config.OPP_WATCH_THRESHOLD,
        },
        "stop_loss_rules": {
            "min_stop_distance_pct": config.AI_MIN_STOP_DISTANCE_PCT,
        },
        "target_rules": {
            "min_rr_ratio": config.AI_MIN_RR_RATIO,
        },
        "position_sizing_rules": {
            "initial_capital": config.INITIAL_CAPITAL,
            "max_risk_pct": config.MAX_RISK_PCT,
            "max_capital_per_trade_pct": config.MAX_CAPITAL_PER_TRADE_PCT,
        },
        "regime_strategy_eligibility": {
            "min_tf_alignment": config.AI_MIN_TF_ALIGNMENT,
            "high_volatility_downgrade_below": config.AI_HIGH_VOL_CONF_THRESHOLD,
            "sideways_downgrade_below": config.AI_SIDEWAYS_CONF_THRESHOLD,
            "note": "All strategies eligible unless regime-specific confidence "
                    "downgrade applies; no strategy hard-disabled in baseline.",
        },
    }


def _config_hash(rules: dict) -> str:
    payload = json.dumps(rules, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def freeze_baseline() -> dict:
    """Create the immutable baseline snapshot. Refuses to overwrite."""
    if os.path.exists(BASELINE_FILE):
        with open(BASELINE_FILE) as f:
            existing = json.load(f)
        return {"created": False, "already_frozen": True, "baseline": existing}

    rules = _current_rules()
    baseline = {
        "baseline_version": BASELINE_VERSION,
        "model_version": MODEL_VERSION,
        "rule_version": RULE_VERSION,
        "frozen_at": _now(),
        "config_hash": _config_hash(rules),
        "rules": rules,
        "immutable": True,
        "label": "PAPER / RESEARCH ONLY",
    }
    tmp = BASELINE_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(baseline, f, indent=1, default=str)
    os.replace(tmp, BASELINE_FILE)
    try:
        os.chmod(BASELINE_FILE, 0o444)  # read-only on disk
    except OSError:
        pass
    return {"created": True, "already_frozen": False, "baseline": baseline}


def load_baseline() -> dict | None:
    if os.path.exists(BASELINE_FILE):
        with open(BASELINE_FILE) as f:
            return json.load(f)
    return None


def verify_baseline_integrity() -> dict:
    """Recompute the config hash of the stored rules — detects tampering."""
    b = load_baseline()
    if not b:
        return {"available": False, "reason": "baseline not frozen yet"}
    recomputed = _config_hash(b.get("rules", {}))
    ok = recomputed == b.get("config_hash")
    return {"available": True, "intact": ok,
            "stored_hash": b.get("config_hash"), "recomputed_hash": recomputed}


def confidence_bucket(conf: float | None) -> str | None:
    if conf is None:
        return None
    for lo, hi in CONFIDENCE_BUCKETS:
        if lo <= conf <= hi:
            return f"{lo}-{hi}"
    return "90-100" if conf > 100 else "0-19"


def _group_report(rows: list[dict], keyfn) -> list[dict]:
    groups: dict[str, list[dict]] = {}
    for r in rows:
        k = keyfn(r) or "UNKNOWN"
        groups.setdefault(str(k), []).append(r)
    out = []
    for k in sorted(groups):
        m = group_metrics(groups[k])
        m["group"] = k
        out.append(m)
    return out


def baseline_report(force: bool = False) -> dict:
    """Performance report of the frozen baseline over completed trades."""
    if not force and os.path.exists(BASELINE_REPORT_FILE):
        with open(BASELINE_REPORT_FILE) as f:
            return json.load(f)

    b = load_baseline()
    rows = learning_rows()
    overall = group_metrics(rows)
    avg_rr = None
    rrs = [float(r["risk_reward"]) for r in rows if r.get("risk_reward")]
    if rrs:
        avg_rr = round(sum(rrs) / len(rrs), 2)
    avg_return = None
    rets = [float(r.get("return_pct") or 0) for r in rows]
    if rets:
        avg_return = round(sum(rets) / len(rets), 3)

    report = {
        "generated_at": _now(),
        "baseline_version": b.get("baseline_version") if b else None,
        "model_version": b.get("model_version") if b else None,
        "config_hash": b.get("config_hash") if b else None,
        "completed_trades": len(rows),
        "overall": overall,
        "avg_return_pct": avg_return,
        "avg_rr": avg_rr,
        "by_strategy": _group_report(rows, lambda r: r.get("strategy")),
        "by_sector": _group_report(rows, lambda r: r.get("sector")),
        "by_regime": _group_report(rows, lambda r: r.get("market_regime_at_entry")),
        "by_confidence_bucket": _group_report(
            rows, lambda r: confidence_bucket(r.get("raw_confidence"))),
        "note": "Baseline evidence from completed paper/historical trades only. "
                "Historical decisions are never rewritten.",
        "label": "PAPER / RESEARCH ONLY",
    }
    tmp = BASELINE_REPORT_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(report, f, indent=1, default=str)
    os.replace(tmp, BASELINE_REPORT_FILE)
    return report
