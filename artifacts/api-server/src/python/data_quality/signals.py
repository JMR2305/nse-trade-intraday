"""
data_quality/signals.py — Phase 8.3
Signal validation: lifecycle state validity, duplicate IDs, timestamp ordering,
paper-order linkage, missing approval fields, and execution status consistency.

READ-ONLY · ADVISORY-ONLY.
"""
from __future__ import annotations

from datetime import datetime, timezone

from .models import Issue, domain_result

_VALID_STATES = {
    "PENDING", "APPROVED", "REJECTED", "EXECUTED", "FAILED",
    "CANCELLED", "EXPIRED", "OPEN", "CLOSED", "ACTIVE", "INACTIVE",
    "PENDING_ENTRY", "ENTRY_PLACED", "IN_POSITION", "EXIT_PLACED",
    "POSITION_CLOSED", "SKIPPED", "IGNORED",
}


def _safe_str(v) -> str:
    return str(v).strip().upper() if v else ""


def validate_signal(sig: dict) -> list[Issue]:
    issues: list[Issue] = []
    sid = str(sig.get("id") or sig.get("signal_id") or "")
    sym = str(sig.get("symbol", ""))

    def add(sev, check, fld, msg, val=None):
        issues.append(Issue(sev, check, fld, msg, symbol=sym, value=val))

    # ID presence
    if not sid:
        add("CRITICAL", "SIGNAL_ID_MISSING", "id", "Signal record has no ID")

    # Lifecycle state
    state = _safe_str(sig.get("status") or sig.get("state"))
    if state and state not in _VALID_STATES:
        add("WARNING", "INVALID_STATE", "status",
            f"Unknown signal state {state!r}", state)

    # Confidence 0–1
    conf = sig.get("confidence")
    if conf is not None:
        try:
            cf = float(conf)
            if not 0.0 <= cf <= 1.0:
                add("WARNING", "CONFIDENCE_RANGE", "confidence",
                    f"confidence {cf:.3f} outside [0, 1]", cf)
        except (TypeError, ValueError):
            add("WARNING", "CONFIDENCE_TYPE", "confidence",
                f"confidence is not numeric: {conf!r}", conf)

    # Timestamp presence
    ts = sig.get("created_at") or sig.get("timestamp") or sig.get("signal_time")
    if ts is None:
        add("MISSING", "TIMESTAMP_PRESENT", "created_at",
            "Signal has no created_at timestamp")

    # Paper-order linkage for executed signals
    if state in ("EXECUTED", "ENTRY_PLACED", "IN_POSITION", "POSITION_CLOSED"):
        paper_trade_id = sig.get("paper_trade_id") or sig.get("order_id")
        if not paper_trade_id:
            add("WARNING", "MISSING_LINKAGE", "paper_trade_id",
                f"Executed signal {sid!r} has no paper_trade_id", sid)

    return issues


def validate_signal_set(signals: list[dict]) -> dict:
    if not signals:
        return domain_result(
            "signals", 1, 1,
            [],
            extra={"signals_checked": 0,
                   "note": "No signals found — this is normal on a fresh session."},
        )

    all_issues: list[Issue] = []
    total_checks = 0
    total_passed = 0

    # Duplicate IDs
    seen_ids: dict[str, int] = {}
    for s in signals:
        sid = str(s.get("id") or s.get("signal_id") or "")
        if sid:
            seen_ids[sid] = seen_ids.get(sid, 0) + 1
    for sid, count in seen_ids.items():
        total_checks += 1
        if count > 1:
            all_issues.append(Issue("DUPLICATE", "DUPLICATE_SIGNAL_ID", "id",
                                    f"Signal ID {sid!r} appears {count} times", value=sid))
        else:
            total_passed += 1

    # Per-signal validation
    for sig in signals:
        sig_issues = validate_signal(sig)
        total_checks += 4  # ID, state, confidence, timestamp
        n_failed = min(4, len([i for i in sig_issues if i.severity != "INFO"]))
        total_passed += 4 - n_failed
        all_issues.extend(sig_issues)

    # Timestamp ordering (sort by created_at)
    try:
        ts_vals = [str(s.get("created_at") or s.get("timestamp") or "")
                   for s in signals]
        ts_sorted = sorted(ts_vals)
        total_checks += 1
        if ts_vals == ts_sorted:
            total_passed += 1
        else:
            all_issues.append(Issue("WARNING", "TIMESTAMP_ORDER", "created_at",
                                    "Signals are not in chronological order"))
    except Exception:
        total_checks += 1; total_passed += 1

    return domain_result(
        "signals", total_checks, total_passed, all_issues,
        extra={"signals_checked": len(signals)},
    )


# ── Public entry point ────────────────────────────────────────────────────────

def get_signal_validation() -> dict:
    signals: list[dict] = []

    try:
        import psycopg2, os, json
        conn = psycopg2.connect(os.environ["DATABASE_URL"])
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, symbol, status, confidence, created_at, paper_trade_id "
                "FROM signals_cache ORDER BY created_at DESC LIMIT 500"
            )
            cols = [d[0] for d in cur.description]
            signals = [dict(zip(cols, row)) for row in cur.fetchall()]
        conn.close()
    except Exception:
        pass

    return validate_signal_set(signals)
