"""
phase22_activation.py — Phase 22 explicit user activation of auto paper entries.

Rules (spec Parts 1–2):
- Auto paper entries stay OFF by default after every deployment.
- Activation requires ALL readiness checks to pass AND the user to type the
  exact confirmation text: ENABLE PAPER ONLY
- On activation: record user, timestamp, configuration hash, audit event.
- Immediate Disable is always available and requires no confirmation.
- This confirmation must NEVER be reused for live trading.

PAPER TRADING / RESEARCH ONLY. No live orders anywhere.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional

import phase20_store as store

PHASE22_CONFIRMATION_TEXT = "ENABLE PAPER ONLY"
ACK_STATEMENT = (
    "I understand this enables automatic simulated paper trades only. "
    "No real Zerodha orders will be placed. "
    "Paper trades can gain or lose simulated capital."
)
_ACTIVATION_KEY = "phase22_activation"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_activation_status() -> Dict[str, Any]:
    settings = store.get_settings()
    record = store.kv_get(_ACTIVATION_KEY, {}) or {}
    active = bool(settings.get("auto_paper_entries")
                  and settings.get("auto_paper_entries_confirmed_at"))
    return {
        "paper_automation_active": active,
        "default_state": "OFF (after every deployment)",
        "required_confirmation_text": PHASE22_CONFIRMATION_TEXT,
        "acknowledgement_statement": ACK_STATEMENT,
        "activation_record": record if active else None,
        "last_activation_record": record or None,
        "auto_paper_exits": bool(settings.get("auto_paper_exits")),
        "live_orders": "DISABLED",
        "label": "PAPER / RESEARCH ONLY",
        "note": ("PAPER AUTOMATION ACTIVE — simulated entries only. "
                 "Disable is available immediately." if active else
                 "Auto paper entries are OFF. Activation requires the readiness "
                 "checklist to pass and typing the exact confirmation text."),
    }


def enable_paper_automation(confirmation_text: str,
                            user: Optional[str] = None) -> Dict[str, Any]:
    """Enable automatic paper entries after readiness + typed confirmation."""
    typed = (confirmation_text or "").strip()
    if typed != PHASE22_CONFIRMATION_TEXT:
        return {"success": False,
                "error": f"Confirmation text must be exactly "
                         f"'{PHASE22_CONFIRMATION_TEXT}'. Nothing was changed.",
                "paper_automation_active": False}

    from phase22_readiness import run_readiness_checklist
    readiness = run_readiness_checklist()
    if not readiness.get("all_passed"):
        return {"success": False,
                "error": "Readiness checklist failed — activation blocked. "
                         "No control was weakened.",
                "failed_checks": readiness.get("failed_checks"),
                "readiness": readiness,
                "paper_automation_active": False}

    cfg_hash = store.config_hash()
    now = _now_iso()
    actor = str(user or "dashboard_user")

    # Flip the underlying Phase 20 flag through its own guarded path.
    store.update_settings({"auto_paper_entries": True},
                          confirmation_text=store.CONFIRMATION_TEXT)

    record = {
        "activated_at": now,
        "activated_by": actor,
        "config_hash": cfg_hash,
        "confirmation_text_typed": PHASE22_CONFIRMATION_TEXT,
        "acknowledgement": ACK_STATEMENT,
        "scope": "PAPER_ONLY",
        "not_valid_for_live_trading": True,
    }
    store.kv_set(_ACTIVATION_KEY, record)

    try:
        from phase14_governance import append_audit
        append_audit("phase22_paper_automation_enabled", record, actor=actor)
    except Exception:
        pass
    store.add_notification(
        "PAPER_AUTOMATION_ENABLED", "Paper automation ACTIVE",
        f"Automatic simulated paper entries enabled by {actor} at {now} "
        f"(config {cfg_hash}). PAPER ONLY — no real orders.",
        severity="WARN", context=record)

    return {"success": True, "paper_automation_active": True,
            "activation_record": record,
            "banner": "PAPER AUTOMATION ACTIVE — simulated trades only",
            "label": "PAPER / RESEARCH ONLY"}


def disable_paper_automation(user: Optional[str] = None,
                             reason: str = "user_disable") -> Dict[str, Any]:
    """Immediate disable — never requires confirmation."""
    store.update_settings({"auto_paper_entries": False})
    now = _now_iso()
    actor = str(user or "dashboard_user")
    record = store.kv_get(_ACTIVATION_KEY, {}) or {}
    record.update({"disabled_at": now, "disabled_by": actor,
                   "disable_reason": reason})
    store.kv_set(_ACTIVATION_KEY, record)
    try:
        from phase14_governance import append_audit
        append_audit("phase22_paper_automation_disabled",
                     {"disabled_at": now, "by": actor, "reason": reason},
                     actor=actor)
    except Exception:
        pass
    store.add_notification(
        "PAPER_AUTOMATION_DISABLED", "Paper automation disabled",
        f"Automatic paper entries disabled by {actor} at {now}.",
        severity="INFO")
    return {"success": True, "paper_automation_active": False,
            "disabled_at": now, "label": "PAPER / RESEARCH ONLY"}
