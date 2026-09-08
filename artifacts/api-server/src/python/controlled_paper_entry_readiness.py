"""Pure, read-only readiness checks for the Phase 4A review gate."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from controlled_paper_entry_flags import (
    ControlledPaperEntryFlags,
    get_controlled_paper_entry_flags,
)


GO_FOR_OPERATOR_REVIEW = "GO_FOR_OPERATOR_REVIEW"
NO_GO = "NO_GO"
BLOCKED = "BLOCKED"
ALLOWED_VERDICTS = frozenset({GO_FOR_OPERATOR_REVIEW, NO_GO, BLOCKED})
REQUIRED_SECTOR_COUNTS = {"BANK": 9, "INFRA": 13, "IT": 1}


def _mapping(value: object) -> Mapping[str, Any] | None:
    return value if isinstance(value, Mapping) else None


def _section(
    evidence: Mapping[str, Any],
    *names: str,
) -> Mapping[str, Any] | None:
    for name in names:
        value = _mapping(evidence.get(name))
        if value is not None:
            return value
    return None


def _exact_bool(section: Mapping[str, Any] | None, key: str) -> bool:
    return section is not None and section.get(key) is True


def _exact_number(section: Mapping[str, Any] | None, key: str, expected: int) -> bool:
    value = section.get(key) if section is not None else None
    return isinstance(value, (int, float)) and not isinstance(value, bool) and value == expected


def _phase1h_passed(evidence: Mapping[str, Any]) -> bool:
    phase1h = _section(evidence, "phase1h_watch", "phase1h")
    if phase1h is None:
        return False
    status = str(phase1h.get("status") or phase1h.get("verdict") or "").strip().upper()
    return phase1h.get("report_exists") is True and status == "PASS"


def _universe_passed(evidence: Mapping[str, Any]) -> bool:
    universe = _section(evidence, "universe")
    custom_status = _section(evidence, "custom_universe_status", "custom_status")
    if universe is None or custom_status is None:
        return False
    if universe.get("universe_mode") != "CUSTOM_LOW_PRICE_SECTOR":
        return False
    if not _exact_number(universe, "symbols_analysed", 23):
        return False
    if not _exact_number(universe, "symbols_with_errors", 0):
        return False
    if universe.get("nifty_50_fallback") is not False:
        return False
    if custom_status.get("sector_counts") != REQUIRED_SECTOR_COUNTS:
        return False
    return _exact_number(custom_status, "active_count", 23)


def _settings_passed(evidence: Mapping[str, Any]) -> bool:
    settings = _section(evidence, "settings")
    if settings is None:
        return False
    active_universe = settings.get("active_intraday_universe")
    if active_universe != "CUSTOM_LOW_PRICE_SECTOR":
        return False
    return (
        _exact_number(settings, "initial_capital", 100000)
        and settings.get("auto_paper_entries") is False
        and settings.get("bootstrap_paper_enabled") is False
    )


def _positions_passed(evidence: Mapping[str, Any]) -> bool:
    return evidence.get("positions") == []


def _trade_audit_passed(evidence: Mapping[str, Any]) -> bool:
    trades = evidence.get("trades_during_watch")
    if not isinstance(trades, list):
        return False
    forbidden = {"AUTO", "BOOTSTRAP_AUTO"}
    for trade in trades:
        if not isinstance(trade, Mapping):
            return False
        source = str(
            trade.get("trade_type")
            or trade.get("source")
            or trade.get("origin")
            or trade.get("action")
            or ""
        ).strip().upper()
        if source in forbidden:
            return False
    return True


def _eod_passed(evidence: Mapping[str, Any]) -> bool:
    eod = _section(evidence, "eod")
    if eod is None:
        return False
    status_passed = eod.get("status_passed") is True
    outcomes_passed = eod.get("outcomes_passed") is True
    return status_passed and outcomes_passed


def _reviews_passed(evidence: Mapping[str, Any]) -> bool:
    reviews = _section(evidence, "reviews")
    if reviews is None:
        return False
    return (
        reviews.get("advisory_core_reviewed") is True
        and reviews.get("advisory_integration_reviewed") is True
    )


def _operator_approval_passed(evidence: Mapping[str, Any]) -> bool:
    approval = evidence.get("operator_approval")
    if approval is True:
        return True
    approval_section = _mapping(approval)
    return approval_section is not None and approval_section.get("approved") is True


def readiness_evidence_passes(evidence: Mapping[str, Any]) -> bool:
    """Return whether every required evidence item is present and exact."""
    return (
        _phase1h_passed(evidence)
        and _universe_passed(evidence)
        and _settings_passed(evidence)
        and _positions_passed(evidence)
        and _trade_audit_passed(evidence)
        and _eod_passed(evidence)
        and _reviews_passed(evidence)
        and _operator_approval_passed(evidence)
    )


def check_readiness(
    evidence: Mapping[str, Any] | object,
    *,
    flags: ControlledPaperEntryFlags | None = None,
) -> str:
    """Return only the documented verdict strings; never mutate supplied state."""
    controls = flags or get_controlled_paper_entry_flags()
    if not isinstance(evidence, Mapping):
        return BLOCKED
    if not controls.review_gate_safe:
        return BLOCKED
    if not readiness_evidence_passes(evidence):
        return NO_GO
    return GO_FOR_OPERATOR_REVIEW