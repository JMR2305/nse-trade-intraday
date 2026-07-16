"""
phase21_thresholds.py — Phase 21: Decision-threshold optimization (advisory).

PAPER / RESEARCH ONLY. ADVISORY ONLY.
- Walk-forward, time-ordered validation: optimize on earlier folds, test on
  later unseen folds. Never optimizes and tests on the same period.
- Candidates are compared against the frozen baseline thresholds.
- Rejects candidates that win only by taking very few trades, or that
  materially worsen drawdown.
- Never auto-applies: stores recommendations for human approval.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone

from phase14_learning import learning_rows, _max_drawdown
from phase21_baseline import load_baseline

_DIR = os.path.dirname(os.path.abspath(__file__))
THRESHOLDS_FILE = os.path.join(_DIR, "phase21_thresholds.json")

MIN_TRAIN_SAMPLE = 30
MIN_TEST_SAMPLE = 15
MIN_TRADE_FREQ_RATIO = 0.30   # candidate must keep >= 30% of baseline trades
MAX_DD_WORSEN_RATIO = 1.25    # candidate DD must not exceed 125% of baseline DD

# Candidate BUY-confidence thresholds evaluated (baseline value is included).
CANDIDATE_BUY_THRESHOLDS = [60.0, 65.0, 70.0, 75.0, 80.0, 85.0]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sorted_rows() -> list[dict]:
    rows = [r for r in learning_rows() if r.get("raw_confidence") is not None]
    return sorted(rows, key=lambda r: str(r.get("entry_ts") or ""))


def _eval_threshold(rows: list[dict], threshold: float) -> dict:
    """Simulate 'take the trade iff raw confidence >= threshold'."""
    taken = [r for r in rows if float(r["raw_confidence"]) >= threshold]
    n = len(taken)
    pnls = [float(r.get("net_pnl") or 0) for r in taken]
    rets = [float(r.get("return_pct") or 0) for r in taken]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    gross_win, gross_loss = sum(wins), abs(sum(losses))
    return {
        "trades": n,
        "win_rate": round(len(wins) / n, 4) if n else None,
        "profit_factor": (round(gross_win / gross_loss, 3)
                          if gross_loss else None),
        "expectancy": round(sum(pnls) / n, 2) if n else None,
        "avg_return_pct": round(sum(rets) / n, 3) if n else None,
        "max_drawdown": round(_max_drawdown(pnls), 2),
        "total_pnl": round(sum(pnls), 2),
    }


def run_threshold_optimization(force: bool = False) -> dict:
    if not force and os.path.exists(THRESHOLDS_FILE):
        with open(THRESHOLDS_FILE) as f:
            cached = json.load(f)
        if cached.get("generated_at", "")[:10] == _now()[:10]:
            return cached

    baseline = load_baseline() or {}
    base_buy = (baseline.get("rules", {})
                .get("decision_thresholds", {}).get("buy", 75.0))

    rows = _sorted_rows()
    n = len(rows)
    result: dict = {
        "generated_at": _now(),
        "baseline_buy_threshold": base_buy,
        "total_completed_trades": n,
        "min_train_sample": MIN_TRAIN_SAMPLE,
        "min_test_sample": MIN_TEST_SAMPLE,
        "candidates": [],
        "recommended": None,
        "auto_applied": False,
        "requires_human_approval": True,
        "label": "PAPER / RESEARCH ONLY",
    }

    if n < MIN_TRAIN_SAMPLE + MIN_TEST_SAMPLE:
        result["status"] = "INSUFFICIENT_EVIDENCE"
        result["note"] = (f"Need at least {MIN_TRAIN_SAMPLE + MIN_TEST_SAMPLE} "
                          f"completed trades for walk-forward optimization; have {n}.")
        _save(result)
        return result

    # Time-ordered split: first 70% train (optimize), last 30% test (validate).
    split = int(n * 0.7)
    train, test = rows[:split], rows[split:]
    result["walk_forward"] = {
        "train_trades": len(train), "test_trades": len(test),
        "train_period": [str(train[0].get("entry_ts"))[:10],
                         str(train[-1].get("entry_ts"))[:10]],
        "test_period": [str(test[0].get("entry_ts"))[:10],
                        str(test[-1].get("entry_ts"))[:10]],
        "separation": "Optimization uses only the train period; evaluation "
                      "uses only the later unseen test period.",
    }

    base_train = _eval_threshold(train, base_buy)
    base_test = _eval_threshold(test, base_buy)
    result["baseline_performance"] = {"train": base_train, "test": base_test}

    candidates = []
    for th in CANDIDATE_BUY_THRESHOLDS:
        tr = _eval_threshold(train, th)
        te = _eval_threshold(test, th)
        overfit_risk = "LOW"
        rejected_reasons = []
        if te["trades"] < MIN_TEST_SAMPLE:
            rejected_reasons.append("insufficient test-period trades")
            overfit_risk = "HIGH"
        if base_test["trades"] and te["trades"] < base_test["trades"] * MIN_TRADE_FREQ_RATIO:
            rejected_reasons.append("improves only by taking very few trades")
            overfit_risk = "HIGH"
        base_dd = abs(base_test["max_drawdown"]) or 0.01
        if abs(te["max_drawdown"]) > base_dd * MAX_DD_WORSEN_RATIO:
            rejected_reasons.append("materially worse drawdown than baseline")
        # Train/test divergence signals overfitting.
        if (tr.get("expectancy") is not None and te.get("expectancy") is not None
                and tr["expectancy"] > 0 and te["expectancy"] < 0):
            rejected_reasons.append("positive in train but negative in test")
            overfit_risk = "HIGH"
        elif overfit_risk == "LOW" and tr.get("win_rate") and te.get("win_rate") \
                and abs(tr["win_rate"] - te["win_rate"]) > 0.25:
            overfit_risk = "MEDIUM"

        improves = (te.get("expectancy") is not None
                    and base_test.get("expectancy") is not None
                    and te["expectancy"] > base_test["expectancy"])
        candidates.append({
            "threshold_set": {"buy": th},
            "sample_size": tr["trades"] + te["trades"],
            "train": tr,
            "test": te,
            "trades": te["trades"],
            "win_rate": te["win_rate"],
            "profit_factor": te["profit_factor"],
            "expectancy": te["expectancy"],
            "max_drawdown": te["max_drawdown"],
            "avg_return": te["avg_return_pct"],
            "trade_frequency": (round(te["trades"] / len(test), 3)
                                if test else None),
            "overfit_risk": overfit_risk,
            "improves_expectancy_vs_baseline": improves,
            "rejected_reasons": rejected_reasons,
            "recommended": bool(improves and not rejected_reasons
                                and th != base_buy),
        })

    result["candidates"] = candidates
    recs = [c for c in candidates if c["recommended"]]
    if recs:
        best = max(recs, key=lambda c: c["expectancy"] or -1e9)
        result["recommended"] = best["threshold_set"]
        result["status"] = "CANDIDATE_READY_FOR_REVIEW"
        result["note"] = ("Recommended threshold change is ADVISORY and stored "
                          "for human approval. Nothing is auto-applied.")
    else:
        result["status"] = "NO_CHANGE_RECOMMENDED"
        result["note"] = ("No candidate beat the frozen baseline on unseen "
                          "time-ordered data under the safety constraints.")
    _save(result)
    return result


def _save(result: dict) -> None:
    tmp = THRESHOLDS_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(result, f, indent=1, default=str)
    os.replace(tmp, THRESHOLDS_FILE)


def load_thresholds() -> dict:
    if os.path.exists(THRESHOLDS_FILE):
        with open(THRESHOLDS_FILE) as f:
            return json.load(f)
    return run_threshold_optimization()
