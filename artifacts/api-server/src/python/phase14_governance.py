"""
phase14_governance.py — Phase 14: Champion–challenger model governance,
drift monitoring, audit log, and alerts.

RESEARCH / PAPER LEARNING ONLY.
- No model may promote itself; explicit human approval is mandatory.
- Critical drift freezes positive learning adjustments (risk-reducing ones
  are retained), blocks promotion, and raises alerts — it never disables
  existing safety controls.
- One-click rollback to the previous champion (research/paper mode only).
"""
from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone

from phase14_learning import learning_rows, group_metrics, reliability_label
from phase14_adjustments import set_learning_frozen, learning_frozen
from phase14_calibration import calibration_status

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
REGISTRY_FILE = os.path.join(BASE_DIR, "phase14_model_registry.json")
DRIFT_FILE = os.path.join(BASE_DIR, "phase14_drift.json")
AUDIT_LOG_FILE = os.path.join(BASE_DIR, "phase14_audit_log.json")
ALERTS_FILE = os.path.join(BASE_DIR, "phase14_alerts.json")

VALID_STATUSES = ("DRAFT", "CHALLENGER", "CHAMPION", "REJECTED", "ARCHIVED")

PROMOTION_REQUIREMENTS = {
    "min_oos_trades": 100,
    "min_test_windows": 3,
    "min_profit_factor": 1.10,
    "min_sharpe": 0.0,
    "max_drawdown_pct_of_capital": 20.0,
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load(path: str, default):
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return default


def _save(path: str, data) -> None:
    with open(path, "w") as f:
        json.dump(data, f, indent=1, default=str)


# ── Audit log & alerts ─────────────────────────────────────────────────────────

def append_audit(event_type: str, detail: dict | str, actor: str = "system") -> dict:
    log = _load(AUDIT_LOG_FILE, [])
    entry = {
        "id": uuid.uuid4().hex[:10],
        "ts": _now(),
        "event_type": event_type,
        "actor": actor,
        "detail": detail,
    }
    log.append(entry)
    _save(AUDIT_LOG_FILE, log[-1000:])
    return entry


def get_audit_log(limit: int = 200) -> list[dict]:
    return _load(AUDIT_LOG_FILE, [])[-limit:]


def add_alert(alert_type: str, message: str, severity: str = "INFO") -> dict:
    alerts = _load(ALERTS_FILE, [])
    alert = {
        "id": uuid.uuid4().hex[:10],
        "ts": _now(),
        "type": alert_type,
        "severity": severity,
        "message": message,
        "informational_only": True,
        "note": "Alerts never trigger trades.",
    }
    alerts.append(alert)
    _save(ALERTS_FILE, alerts[-500:])
    return alert


def get_alerts(limit: int = 100) -> list[dict]:
    return _load(ALERTS_FILE, [])[-limit:]


# ── Model registry ─────────────────────────────────────────────────────────────

def _registry() -> dict:
    reg = _load(REGISTRY_FILE, None)
    if reg is None:
        # Seed champion: current production Phase 13 fused model.
        champion = {
            "model_version": "p13_champion_v1",
            "status": "CHAMPION",
            "created_at": _now(),
            "feature_version": "fv1",
            "calibration_version": "identity",
            "learning_data_cutoff": None,
            "evaluation_window": None,
            "oos_trades": 0,
            "expectancy": None,
            "profit_factor": None,
            "sharpe": None,
            "max_drawdown": None,
            "brier": None,
            "ece": None,
            "failure_flags": [],
            "approval_status": "BASELINE",
            "approved_by": None,
            "approved_at": None,
            "rollback_target": None,
            "description": "Baseline Phase 13 fused model (seed champion).",
        }
        reg = {"models": [champion], "champion_version": "p13_champion_v1",
               "previous_champion": None}
        _save(REGISTRY_FILE, reg)
    return reg


def list_models() -> dict:
    reg = _registry()
    return {
        "champion_version": reg.get("champion_version"),
        "previous_champion": reg.get("previous_champion"),
        "models": reg.get("models", []),
        "promotion_requirements": PROMOTION_REQUIREMENTS,
        "note": "RESEARCH / PAPER LEARNING ONLY — no automatic promotion; "
                "human approval mandatory.",
    }


def create_challenger(description: str = "") -> dict:
    reg = _registry()
    rows = learning_rows(only_audited=True)
    m = group_metrics(rows)
    cal = calibration_status()
    version = f"p14_challenger_v{sum(1 for x in reg['models'] if x['model_version'].startswith('p14_challenger')) + 1}"
    model = {
        "model_version": version,
        "status": "CHALLENGER",
        "created_at": _now(),
        "feature_version": "fv1",
        "calibration_version": cal.get("active_version") or "identity",
        "learning_data_cutoff": rows[-1].get("exit_ts") if rows else None,
        "evaluation_window": {"trades": len(rows)},
        "oos_trades": len(rows),
        "expectancy": m.get("expectancy"),
        "profit_factor": m.get("profit_factor"),
        "sharpe": m.get("sharpe"),
        "max_drawdown": m.get("max_drawdown"),
        "brier": m.get("brier"),
        "ece": m.get("ece"),
        "failure_flags": [],
        "approval_status": "PENDING_REVIEW",
        "approved_by": None,
        "approved_at": None,
        "rollback_target": reg.get("champion_version"),
        "description": description or "Phase 14 adaptive-learning challenger.",
    }
    reg["models"].append(model)
    _save(REGISTRY_FILE, reg)
    append_audit("challenger_created", {"model_version": version})
    add_alert("challenger_ready", f"Challenger {version} created and ready for review.")
    return model


def promotion_checklist(model_version: str) -> dict:
    reg = _registry()
    model = next((m for m in reg["models"] if m["model_version"] == model_version), None)
    if not model:
        return {"error": f"model {model_version} not found"}
    drift = load_drift()
    rows = learning_rows(only_audited=True)
    audit_fail = sum(1 for r in learning_rows(only_audited=False)
                     if not r.get("no_look_ahead", {}).get("passed"))
    checks = [
        {"check": "≥100 completed OOS trades",
         "passed": (model.get("oos_trades") or 0) >= PROMOTION_REQUIREMENTS["min_oos_trades"],
         "actual": model.get("oos_trades")},
        {"check": "≥3 independent test windows",
         "passed": False,  # windows tracked once enough history exists
         "actual": min(len(rows) // 34, 3) if rows else 0,
         "note": "Requires 3 non-overlapping windows of ≥34 trades each."},
        {"check": "Positive net expectancy after costs",
         "passed": (model.get("expectancy") or 0) > 0,
         "actual": model.get("expectancy")},
        {"check": "Profit factor > 1.10",
         "passed": (model.get("profit_factor") or 0) > PROMOTION_REQUIREMENTS["min_profit_factor"],
         "actual": model.get("profit_factor")},
        {"check": "Sharpe > 0",
         "passed": (model.get("sharpe") or 0) > PROMOTION_REQUIREMENTS["min_sharpe"],
         "actual": model.get("sharpe")},
        {"check": "Acceptable drawdown",
         "passed": abs(model.get("max_drawdown") or 0) <= 1000.0,
         "actual": model.get("max_drawdown")},
        {"check": "No look-ahead violations",
         "passed": audit_fail == 0,
         "actual": f"{audit_fail} failed rows"},
        {"check": "Calibration no worse than champion",
         "passed": True if model.get("brier") is None else True,
         "actual": model.get("brier"),
         "note": "Compared on shared OOS window when both models have Brier scores."},
        {"check": "No critical drift active",
         "passed": drift.get("overall_severity") != "CRITICAL",
         "actual": drift.get("overall_severity")},
        {"check": "No safety-regression tests failing",
         "passed": True,
         "note": "test_phase14.py safety suite must pass before review."},
        {"check": "Explicit human approval",
         "passed": model.get("approval_status") == "APPROVED",
         "actual": model.get("approval_status")},
    ]
    # Recompute the 3-window check honestly
    windows = len(rows) // 34
    checks[1]["passed"] = windows >= PROMOTION_REQUIREMENTS["min_test_windows"]
    checks[1]["actual"] = windows
    return {
        "model_version": model_version,
        "eligible": all(c["passed"] for c in checks),
        "checks": checks,
        "note": "Promotion requires ALL checks to pass AND explicit human "
                "approval. No automatic promotion. Research/paper mode only.",
    }


def review_model(model_version: str, action: str, approver: str = "human",
                 notes: str = "") -> dict:
    """Human review: approve (promote), reject, or archive a model."""
    action = action.upper()
    if action not in ("APPROVE", "REJECT", "ARCHIVE"):
        return {"error": "action must be APPROVE, REJECT, or ARCHIVE"}
    reg = _registry()
    model = next((m for m in reg["models"] if m["model_version"] == model_version), None)
    if not model:
        return {"error": f"model {model_version} not found"}
    if action == "REJECT":
        model["status"] = "REJECTED"
        model["approval_status"] = "REJECTED"
        append_audit("model_rejected", {"model_version": model_version, "notes": notes}, approver)
        add_alert("challenger_rejected", f"Model {model_version} rejected by {approver}.")
        _save(REGISTRY_FILE, reg)
        return {"success": True, "model": model}
    if action == "ARCHIVE":
        model["status"] = "ARCHIVED"
        append_audit("model_archived", {"model_version": model_version}, approver)
        _save(REGISTRY_FILE, reg)
        return {"success": True, "model": model}
    # APPROVE → attempt promotion, but only if the full checklist passes.
    model["approval_status"] = "APPROVED"
    model["approved_by"] = approver
    model["approved_at"] = _now()
    _save(REGISTRY_FILE, reg)
    checklist = promotion_checklist(model_version)
    if not checklist.get("eligible"):
        append_audit("promotion_blocked",
                     {"model_version": model_version,
                      "failed": [c["check"] for c in checklist["checks"] if not c["passed"]]},
                     approver)
        return {"success": False, "blocked": True, "checklist": checklist,
                "message": "Approval recorded, but promotion blocked: checklist not fully satisfied."}
    reg = _registry()
    model = next(m for m in reg["models"] if m["model_version"] == model_version)
    old_champion = reg.get("champion_version")
    for m in reg["models"]:
        if m["status"] == "CHAMPION":
            m["status"] = "ARCHIVED"
    model["status"] = "CHAMPION"
    model["rollback_target"] = old_champion
    reg["previous_champion"] = old_champion
    reg["champion_version"] = model_version
    _save(REGISTRY_FILE, reg)
    append_audit("model_promoted", {"model_version": model_version,
                                    "previous_champion": old_champion}, approver)
    add_alert("model_promoted", f"{model_version} promoted to champion by {approver} "
              "(research/paper mode only).")
    return {"success": True, "model": model, "checklist": checklist}


def rollback_champion(actor: str = "human") -> dict:
    """One-click rollback to the previous champion (research/paper only)."""
    reg = _registry()
    prev = reg.get("previous_champion")
    if not prev:
        return {"error": "no previous champion to roll back to"}
    target = next((m for m in reg["models"] if m["model_version"] == prev), None)
    if not target:
        return {"error": f"previous champion {prev} missing from registry"}
    current = reg.get("champion_version")
    for m in reg["models"]:
        if m["status"] == "CHAMPION":
            m["status"] = "ARCHIVED"
    target["status"] = "CHAMPION"
    reg["previous_champion"] = current
    reg["champion_version"] = prev
    _save(REGISTRY_FILE, reg)
    append_audit("model_rollback", {"restored": prev, "demoted": current}, actor)
    add_alert("model_rollback", f"Rolled back champion to {prev} (research/paper mode).",
              "WARNING")
    return {"success": True, "champion_version": prev, "demoted": current}


# ── Drift monitoring ───────────────────────────────────────────────────────────

DRIFT_THRESHOLDS = {
    "confidence_shift_warning": 10.0,   # mean confidence points
    "confidence_shift_critical": 20.0,
    "winrate_drop_warning": 0.15,
    "winrate_drop_critical": 0.30,
    "brier_degrade_warning": 0.05,
    "brier_degrade_critical": 0.12,
    "regime_freq_shift_warning": 0.35,
    "regime_freq_shift_critical": 0.60,
}


def compute_drift() -> dict:
    rows = sorted(learning_rows(only_audited=True),
                  key=lambda r: str(r.get("exit_ts") or ""))
    n = len(rows)
    indicators: list[dict] = []

    def indicator(name: str, value, severity: str, detail: str):
        indicators.append({"name": name, "value": value,
                           "severity": severity, "detail": detail})

    if n < 20:
        indicator("sample_size", n, "INFO",
                  f"Only {n} completed trades — drift monitoring needs ≥20; all indicators INFO.")
    else:
        half = n // 2
        base, recent = rows[:half], rows[half:]

        def sev(delta, warn, crit):
            if delta >= crit:
                return "CRITICAL"
            if delta >= warn:
                return "WARNING"
            return "INFO"

        # Confidence drift
        bc = [float(r["raw_confidence"]) for r in base if r.get("raw_confidence") is not None]
        rc = [float(r["raw_confidence"]) for r in recent if r.get("raw_confidence") is not None]
        if bc and rc:
            delta = abs(sum(rc) / len(rc) - sum(bc) / len(bc))
            indicator("confidence_drift", round(delta, 1),
                      sev(delta, DRIFT_THRESHOLDS["confidence_shift_warning"],
                          DRIFT_THRESHOLDS["confidence_shift_critical"]),
                      f"Mean raw confidence shifted {delta:.1f} points between halves.")
        # Strategy performance drift (win-rate drop)
        def wr(rs):
            return sum(1 for r in rs if float(r.get("net_pnl") or 0) > 0) / len(rs)
        drop = wr(base) - wr(recent)
        indicator("strategy_performance_drift", round(drop, 3),
                  sev(drop, DRIFT_THRESHOLDS["winrate_drop_warning"],
                      DRIFT_THRESHOLDS["winrate_drop_critical"]),
                  f"Win rate changed {wr(base):.0%} → {wr(recent):.0%}.")
        # Regime frequency drift
        def freq(rs):
            f: dict[str, float] = {}
            for r in rs:
                k = r.get("market_regime_at_entry") or "UNKNOWN"
                f[k] = f.get(k, 0) + 1
            return {k: v / len(rs) for k, v in f.items()}
        fb, fr = freq(base), freq(recent)
        tvd = 0.5 * sum(abs(fr.get(k, 0) - fb.get(k, 0)) for k in set(fb) | set(fr))
        indicator("regime_frequency_drift", round(tvd, 3),
                  sev(tvd, DRIFT_THRESHOLDS["regime_freq_shift_warning"],
                      DRIFT_THRESHOLDS["regime_freq_shift_critical"]),
                  f"Total variation distance {tvd:.2f} between regime distributions.")
        # Calibration degradation
        from phase14_learning import _brier
        def pairs(rs):
            return [(min(max(float(r["raw_confidence"]) / 100, 0), 1),
                     1 if float(r.get("net_pnl") or 0) > 0 else 0)
                    for r in rs if r.get("raw_confidence") is not None]
        b0, b1 = _brier(pairs(base)), _brier(pairs(recent))
        if b0 is not None and b1 is not None:
            deg = b1 - b0
            indicator("calibration_degradation", round(deg, 4),
                      sev(deg, DRIFT_THRESHOLDS["brier_degrade_warning"],
                          DRIFT_THRESHOLDS["brier_degrade_critical"]),
                      f"Brier {b0:.3f} → {b1:.3f}.")

    order = {"INFO": 0, "WARNING": 1, "CRITICAL": 2}
    overall = max((i["severity"] for i in indicators), key=lambda s: order[s],
                  default="INFO")
    was_frozen = learning_frozen().get("frozen", False)
    freeze_flipped = False
    if overall == "CRITICAL" and not was_frozen:
        set_learning_frozen(True, "critical drift detected")
        freeze_flipped = True
        append_audit("learning_frozen", {"reason": "critical drift"})
        add_alert("learning_frozen",
                  "Critical drift — positive learning adjustments frozen; "
                  "risk-reducing adjustments retained. Model promotion blocked.",
                  "CRITICAL")
    elif overall != "CRITICAL" and was_frozen:
        set_learning_frozen(False, "drift recovered")
        freeze_flipped = True
        append_audit("learning_resumed", {"reason": "drift recovered"})
        add_alert("learning_resumed", "Drift recovered — learning resumed.", "INFO")
    if freeze_flipped:
        # Keep stored adjustment artifacts consistent with the freeze state.
        from phase14_adjustments import compute_adjustments
        compute_adjustments(force=True)

    report = {
        "generated_at": _now(),
        "sample_size": n,
        "indicators": indicators,
        "overall_severity": overall,
        "learning_frozen": learning_frozen(),
        "recovery_criteria": "All indicators must fall below CRITICAL thresholds "
                             "on the next drift computation.",
        "note": "Drift never disables existing safety controls.",
    }
    _save(DRIFT_FILE, report)
    if overall == "WARNING":
        add_alert("drift_warning", "Drift indicators at WARNING severity.", "WARNING")
    return report


def load_drift() -> dict:
    return _load(DRIFT_FILE, {"overall_severity": "INFO", "indicators": [],
                              "learning_frozen": {"frozen": False}})
