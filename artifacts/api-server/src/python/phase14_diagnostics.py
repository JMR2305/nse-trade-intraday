"""
phase14_diagnostics.py — Phase 14: Exports, diagnostic bundle, verification report.

RESEARCH / PAPER LEARNING ONLY. Exports mask credentials and contain no secrets.
"""
from __future__ import annotations

import csv
import io
import json
import os
from datetime import datetime, timezone

from phase14_learning import (
    load_dataset, load_evaluation, run_evaluation, learning_rows,
    reliability_label,
)
from phase14_adjustments import load_adjustments, compute_adjustments, learning_frozen
from phase14_calibration import calibration_status, get_active_calibrator
from phase14_governance import (
    list_models, load_drift, get_audit_log, get_alerts, compute_drift,
    add_alert, append_audit,
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
BUNDLE_JSON = os.path.join(BASE_DIR, "phase14_diagnostic_bundle.json")
BUNDLE_CSV = os.path.join(BASE_DIR, "phase14_summary.csv")

SECRET_MARKERS = ("api_key", "secret", "token", "password", "credential",
                  "access_key", "private")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _mask_secrets(obj):
    """Recursively mask any key that looks like a credential."""
    if isinstance(obj, dict):
        return {
            k: ("***MASKED***" if any(m in k.lower() for m in SECRET_MARKERS)
                else _mask_secrets(v))
            for k, v in obj.items()
        }
    if isinstance(obj, list):
        return [_mask_secrets(x) for x in obj]
    return obj


def _rows_to_csv(rows: list[dict], fields: list[str]) -> str:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=fields, extrasaction="ignore")
    w.writeheader()
    for r in rows:
        w.writerow({f: r.get(f) for f in fields})
    return buf.getvalue()


DATASET_CSV_FIELDS = [
    "trade_id", "symbol", "sector", "strategy", "entry_ts", "exit_ts",
    "entry_price", "exit_price", "quantity", "holding_period_days", "net_pnl",
    "return_pct", "exit_reason", "raw_confidence", "opportunity_score",
    "trade_quality", "market_regime_at_entry", "risk_reward", "outcome",
    "model_version", "feature_version",
]

README = """PHASE 14 DIAGNOSTIC BUNDLE — README
RESEARCH / PAPER LEARNING ONLY. No real broker orders. No secrets included.

Files/sections:
- learning_dataset: canonical completed-trade learning rows. Each row carries
  a no_look_ahead audit block (passed + issues). Entry features are entry-time
  snapshots only.
- evaluation_report: overall and grouped performance metrics with sample sizes
  and reliability labels (INSUFFICIENT <30, LOW 30-49, MODERATE 50-99,
  STRONG 100-249, HIGH 250+).
- calibration_report: calibrator versions, methods, before/after Brier, ECE,
  and log loss on out-of-sample data.
- learning_adjustments: per-source bounded adjustments (±5/source, ±10 total),
  each with evidence, reliability, bounds, and reason.
- model_registry: champion/challenger models, statuses, promotion requirements.
- drift_report: drift indicators with severity and frozen-learning state.
- audit_log: calibrator training, evaluations, adjustment changes, model
  status changes, approvals, rollbacks, exports.
- verification: Phase 14 verification summary (acceptance criteria evidence).

Field conventions: pnl values in INR; confidences 0-100; probabilities 0-1.
"""


def export_artifact(name: str) -> dict:
    """Return one exportable artifact as {json, csv} strings."""
    if name == "dataset":
        ds = load_dataset()
        return {"json": ds, "csv": _rows_to_csv(ds.get("rows", []), DATASET_CSV_FIELDS)}
    if name == "evaluation":
        ev = load_evaluation()
        flat = [{"group": "overall", **{k: v for k, v in ev.get("overall", {}).items()}}]
        for section in ("by_strategy", "by_sector", "by_regime", "by_confidence_band"):
            for key, m in ev.get(section, {}).items():
                flat.append({"group": f"{section}:{key}", **m})
        fields = sorted({k for r in flat for k in r})
        return {"json": ev, "csv": _rows_to_csv(flat, fields)}
    if name == "calibration":
        cs = calibration_status()
        hist = cs.get("history", [])
        fields = ["version", "created_at", "method", "status", "train_samples",
                  "test_samples", "reject_reason"]
        return {"json": cs, "csv": _rows_to_csv(hist, fields)}
    if name == "adjustments":
        adj = load_adjustments()
        flat = []
        for source, entries in adj.get("sources", {}).items():
            for key, e in entries.items():
                flat.append({"source": source, "key": key, **{k: v for k, v in e.items()
                            if k not in ("bounds", "evidence_period")}})
        fields = sorted({k for r in flat for k in r}) if flat else ["source", "key"]
        return {"json": adj, "csv": _rows_to_csv(flat, fields)}
    if name == "registry":
        reg = list_models()
        fields = ["model_version", "status", "created_at", "oos_trades",
                  "expectancy", "profit_factor", "sharpe", "max_drawdown",
                  "brier", "approval_status", "approved_by"]
        return {"json": reg, "csv": _rows_to_csv(reg.get("models", []), fields)}
    if name == "drift":
        dr = load_drift()
        fields = ["name", "value", "severity", "detail"]
        return {"json": dr, "csv": _rows_to_csv(dr.get("indicators", []), fields)}
    if name == "audit_log":
        log = get_audit_log(1000)
        fields = ["id", "ts", "event_type", "actor", "detail"]
        rows = [{**e, "detail": json.dumps(e.get("detail"), default=str)} for e in log]
        return {"json": log, "csv": _rows_to_csv(rows, fields)}
    return {"error": f"unknown artifact {name}"}


def verification_report() -> dict:
    ds = load_dataset()
    ev = load_evaluation()
    adj = load_adjustments()
    cal = calibration_status()
    reg = list_models()
    drift = load_drift()
    active = get_active_calibrator()

    # Max total adjustment observable across all source combinations (capped)
    max_obs = 0.0
    for entries in adj.get("sources", {}).values():
        for e in entries.values():
            max_obs = max(max_obs, abs(e.get("adjustment") or 0))
    active_sources = sum(
        1 for entries in adj.get("sources", {}).values()
        for e in entries.values() if e.get("adjustment")
    )
    return {
        "generated_at": _now(),
        "banner": "RESEARCH / PAPER LEARNING ONLY",
        "message": ("Adaptive learning uses completed historical and paper trades. "
                    "Findings may be unreliable with limited samples. No model, "
                    "rule, or strategy is promoted automatically. Human approval "
                    "is required."),
        "completed_learning_rows": ds.get("total_rows", 0),
        "rows_passing_no_look_ahead": ds.get("audit_passed_rows", 0),
        "no_look_ahead_audit_status": ("PASS" if ds.get("audit_failed_rows", 0) == 0
                                        else f"{ds.get('audit_failed_rows')} FAILED"),
        "current_champion": reg.get("champion_version"),
        "active_calibrator": cal.get("active_version") or "identity",
        "calibrator_method": cal.get("active_method"),
        "adjustment_sources_active": active_sources,
        "max_adjustment_observed": max_obs,
        "adjustment_caps": adj.get("caps"),
        "calibration_metrics": {
            "before": active.get("metrics_before") if active else None,
            "after": active.get("metrics_after") if active else None,
        },
        "drift_status": drift.get("overall_severity", "INFO"),
        "learning_frozen": learning_frozen(),
        "challenger_count": sum(1 for m in reg.get("models", [])
                                if m.get("status") == "CHALLENGER"),
        "automatic_promotion_occurred": False,
        "evaluation_reliability": ev.get("reliability"),
        "sample_warning": ev.get("warning"),
    }


def build_bundle() -> dict:
    """Full Phase 14 diagnostic bundle with README, JSON + CSV files on disk."""
    run_evaluation(force=True)
    compute_adjustments(force=True)
    compute_drift()
    bundle = {
        "generated_at": _now(),
        "readme": README,
        "verification": verification_report(),
        "learning_dataset": load_dataset(),
        "evaluation_report": load_evaluation(),
        "calibration_report": calibration_status(),
        "learning_adjustments": load_adjustments(),
        "model_registry": list_models(),
        "drift_report": load_drift(),
        "audit_log": get_audit_log(500),
        "alerts": get_alerts(200),
    }
    bundle = _mask_secrets(bundle)
    with open(BUNDLE_JSON, "w") as f:
        json.dump(bundle, f, indent=1, default=str)
    with open(BUNDLE_CSV, "w") as f:
        f.write(export_artifact("dataset")["csv"])
    append_audit("bundle_exported", {"files": ["phase14_diagnostic_bundle.json",
                                               "phase14_summary.csv"]})
    return {"success": True, "files": [BUNDLE_JSON, BUNDLE_CSV],
            "verification": bundle["verification"]}
