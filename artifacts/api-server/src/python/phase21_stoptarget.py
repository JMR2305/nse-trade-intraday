"""
phase21_stoptarget.py — Phase 21: Stop-loss & target quality evaluation (advisory).

PAPER / RESEARCH ONLY. ADVISORY ONLY.
- Evaluates completed trades: initial risk, MAE/MFE (where recorded),
  stop-too-tight / too-loose flags, target realism, time-to-exit.
- Candidate stop/target models compared with time-ordered validation.
- Past trades are NEVER rewritten; counterfactuals are stored separately
  and labelled SIMULATED.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone

from phase14_learning import learning_rows, _max_drawdown

_DIR = os.path.dirname(os.path.abspath(__file__))
STOPTARGET_FILE = os.path.join(_DIR, "phase21_stoptarget.json")

CANDIDATE_MODELS = [
    {"id": "baseline", "name": "Current baseline",
     "description": "Existing stop/target logic as recorded on each trade."},
    {"id": "atr", "name": "ATR-based",
     "description": "Stop = entry - 1.5×ATR, target = entry + 3.0×ATR."},
    {"id": "structure", "name": "Structure-based",
     "description": "Stop below recent swing low, target at prior resistance."},
    {"id": "hybrid", "name": "Hybrid ATR + structure",
     "description": "Wider of ATR/structure stop; nearer of ATR/structure target."},
    {"id": "regime_adjusted", "name": "Regime-adjusted",
     "description": "ATR multiples widened in high volatility, tightened in low."},
]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _trade_quality_row(r: dict) -> dict:
    entry = float(r.get("entry_price") or 0)
    exitp = float(r.get("exit_price") or 0)
    stop = r.get("stop_loss")
    target = r.get("target")
    ret = float(r.get("return_pct") or 0)
    mae = r.get("mae")
    mfe = r.get("mfe")
    exit_reason = str(r.get("exit_reason") or "").upper()

    initial_risk_pct = None
    if entry and stop:
        initial_risk_pct = round((entry - float(stop)) / entry * 100, 2)

    stop_too_tight = None
    stop_too_loose = None
    if mae is not None and initial_risk_pct:
        # Stopped out but adverse move barely exceeded the stop → tight.
        stop_too_tight = ("STOP" in exit_reason
                          and abs(float(mae)) <= initial_risk_pct * 1.1
                          and (mfe is not None and float(mfe) > initial_risk_pct))
        stop_too_loose = abs(float(mae)) > initial_risk_pct * 2.0
    target_realistic = None
    if mfe is not None and entry and target:
        reward_pct = (float(target) - entry) / entry * 100
        target_realistic = float(mfe) >= reward_pct * 0.8

    return {
        "trade_id": r.get("trade_id"),
        "symbol": r.get("symbol"),
        "strategy": r.get("strategy"),
        "regime": r.get("market_regime_at_entry"),
        "entry_price": entry, "exit_price": exitp,
        "stop_loss": stop, "target": target,
        "initial_risk_pct": initial_risk_pct,
        "mae": mae, "mfe": mfe,
        "return_pct": ret,
        "exit_reason": r.get("exit_reason"),
        "stop_too_tight": stop_too_tight,
        "stop_too_loose": stop_too_loose,
        "target_realistic": target_realistic,
        "target_reached_after_early_exit": (
            None if mfe is None or not entry or not target
            else ("TARGET" not in exit_reason
                  and float(mfe) >= (float(target) - entry) / entry * 100)),
        "holding_days": r.get("holding_period_days"),
        "data_completeness": ("FULL" if mae is not None and mfe is not None
                              and stop and target else "PARTIAL"),
    }


def run_stoptarget_analysis(force: bool = False) -> dict:
    if not force and os.path.exists(STOPTARGET_FILE):
        with open(STOPTARGET_FILE) as f:
            cached = json.load(f)
        if cached.get("generated_at", "")[:10] == _now()[:10]:
            return cached

    rows = sorted(learning_rows(), key=lambda r: str(r.get("entry_ts") or ""))
    per_trade = [_trade_quality_row(r) for r in rows]

    full = [t for t in per_trade if t["data_completeness"] == "FULL"]
    partial = len(per_trade) - len(full)

    tight = [t for t in full if t["stop_too_tight"]]
    loose = [t for t in full if t["stop_too_loose"]]
    unrealistic = [t for t in full if t["target_realistic"] is False]

    # Candidate model comparison — only possible when MAE/MFE data exists.
    # Counterfactuals never modify recorded trades; clearly SIMULATED.
    n = len(rows)
    split = int(n * 0.7)
    test_rows = rows[split:]
    baseline_pnls = [float(r.get("net_pnl") or 0) for r in test_rows]
    model_comparison = []
    for m in CANDIDATE_MODELS:
        entry_avail = m["id"] == "baseline" or len(full) > 0
        model_comparison.append({
            **m,
            "labelled": "SIMULATED" if m["id"] != "baseline" else "ACTUAL",
            "evaluable": entry_avail and len(test_rows) >= 15,
            "test_trades": len(test_rows),
            "test_pnl": (round(sum(baseline_pnls), 2)
                         if m["id"] == "baseline" else None),
            "test_max_drawdown": (round(_max_drawdown(baseline_pnls), 2)
                                  if m["id"] == "baseline" else None),
            "status": ("EVALUATED" if m["id"] == "baseline" and len(test_rows) >= 15
                       else "INSUFFICIENT_DATA" if not entry_avail or len(test_rows) < 15
                       else "REQUIRES_MAE_MFE_HISTORY"),
            "note": ("Counterfactual simulation requires per-trade MAE/MFE and "
                     "intraday path data; recorded trades lack it, so alternate "
                     "models are registered but not yet scoreable."
                     if m["id"] != "baseline" else
                     "Actual recorded results on time-ordered test window."),
        })

    result = {
        "generated_at": _now(),
        "total_trades": len(per_trade),
        "trades_with_full_excursion_data": len(full),
        "trades_with_partial_data": partial,
        "per_trade": per_trade,
        "summary": {
            "stop_too_tight_count": len(tight),
            "stop_too_loose_count": len(loose),
            "unrealistic_target_count": len(unrealistic),
        },
        "candidate_models": model_comparison,
        "validation": "time-ordered (train 70% / test 30% split by entry time)",
        "historical_trades_rewritten": False,
        "counterfactual_label": "SIMULATED",
        "note": "Past trades are never rewritten. Alternate stop/target models "
                "are advisory; counterfactual results are labelled SIMULATED.",
        "label": "PAPER / RESEARCH ONLY",
    }
    tmp = STOPTARGET_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(result, f, indent=1, default=str)
    os.replace(tmp, STOPTARGET_FILE)
    return result


def load_stoptarget() -> dict:
    if os.path.exists(STOPTARGET_FILE):
        with open(STOPTARGET_FILE) as f:
            return json.load(f)
    return run_stoptarget_analysis()
