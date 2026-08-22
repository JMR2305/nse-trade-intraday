"""Non-persistent estimates for a future paper-entry review.

The output deliberately contains no quantity, order identifier, broker field,
or executable payload.  It is an estimate and not a trade instruction.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any


DRY_RUN_MARKER = "DRY RUN ONLY — NOT A TRADE — NOT AN ORDER"
_PROHIBITED_INPUT_FIELDS = frozenset(
    {
        "quantity",
        "order_quantity",
        "executable_quantity",
        "order_id",
        "broker",
        "broker_order_id",
        "instrument_token",
    }
)
_BUY_ACTIONS = frozenset({"BUY", "STRONG BUY", "STRONG_BUY"})


def _finite_number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _risk_flags(value: object) -> list[str] | None:
    if value is None:
        return []
    if not isinstance(value, (list, tuple)):
        return None
    if not all(isinstance(flag, str) and flag.strip() for flag in value):
        return None
    return [flag.strip() for flag in value]


def simulate_dry_run(
    advisory_candidate: Mapping[str, Any] | object,
    *,
    capital: float = 100000.0,
    notional_limit: float = 25000.0,
    risk_rate: float = 0.02,
) -> dict[str, Any]:
    """Estimate one advisory candidate without writing or calling anything."""
    candidate = advisory_candidate if isinstance(advisory_candidate, Mapping) else {}
    symbol_value = candidate.get("symbol") or candidate.get("candidate_symbol")
    symbol = str(symbol_value or "").strip().upper()
    strategy_source = str(
        candidate.get("strategy_source") or candidate.get("strategy") or ""
    ).strip()
    score_value = candidate.get("advisory_score", candidate.get("score"))
    score = _finite_number(score_value)
    flags = _risk_flags(candidate.get("risk_flags"))
    action = str(
        candidate.get("final_action")
        or candidate.get("decision")
        or candidate.get("action")
        or ""
    ).strip().upper()

    rejection_reasons: list[str] = []
    if not symbol:
        rejection_reasons.append("candidate symbol is required")
    if not strategy_source:
        rejection_reasons.append("strategy source is required")
    if score is None:
        rejection_reasons.append("advisory score must be finite")
    if flags is None:
        rejection_reasons.append("risk_flags must be a list of non-empty strings")
        flags = []
    elif flags:
        rejection_reasons.append("risk flags are present: " + ", ".join(flags))
    if action not in _BUY_ACTIONS:
        rejection_reasons.append("candidate is not an approved BUY advisory action")
    if _PROHIBITED_INPUT_FIELDS.intersection(candidate.keys()):
        rejection_reasons.append("executable fields are not accepted by dry-run")

    capital_value = _finite_number(capital)
    limit_value = _finite_number(notional_limit)
    risk_rate_value = _finite_number(risk_rate)
    if capital_value is None or capital_value <= 0:
        rejection_reasons.append("capital must be positive")
        capital_value = 100000.0
    if limit_value is None or limit_value <= 0:
        rejection_reasons.append("notional limit must be positive")
        limit_value = 25000.0
    if risk_rate_value is None or risk_rate_value < 0:
        rejection_reasons.append("risk rate must be non-negative")
        risk_rate_value = 0.02

    requested_notional = _finite_number(candidate.get("theoretical_notional"))
    if requested_notional is None:
        requested_notional = min(capital_value * 0.20, limit_value)
    theoretical_notional = round(max(0.0, min(requested_notional, limit_value)), 2)
    supplied_risk = _finite_number(candidate.get("theoretical_risk"))
    theoretical_risk = round(
        max(0.0, supplied_risk if supplied_risk is not None else theoretical_notional * risk_rate_value),
        2,
    )

    return {
        "status": "DRY_RUN_REJECTED" if rejection_reasons else "DRY_RUN_CANDIDATE",
        "dry_run_only": True,
        "marker": DRY_RUN_MARKER,
        "candidate_symbol": symbol or None,
        "strategy_source": strategy_source or None,
        "advisory_score": score,
        "risk_flags": flags,
        "theoretical_notional": theoretical_notional,
        "theoretical_risk": theoretical_risk,
        "rejection_reason": "; ".join(rejection_reasons) if rejection_reasons else None,
        "execution_allowed": False,
    }