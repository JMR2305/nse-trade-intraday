"""Strict contracts for the Phase 2B advisory-only analysis layer."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Iterable, Mapping


ADVISORY_DECISIONS = (
    "WATCH",
    "CANDIDATE",
    "REJECTED",
    "BLOCKED_DATA_QUALITY",
    "INSUFFICIENT_CONTEXT",
    "SUPERVISOR_BLOCKED",
)

# These are checked at the supervisor boundary.  The analysis layer never
# emits them as actions or decisions.
FORBIDDEN_ACTION_TERMS = ("BUY", "SELL", "EXECUTE")
PROHIBITED_OUTPUT_KEYS = frozenset(
    {
        "order",
        "order_id",
        "order_payload",
        "order_quantity",
        "quantity",
        "broker_instruction",
        "broker_order",
        "auto_enable",
        "phase20_entry_command",
        "executable_order",
        "execute",
        "action",
        "broker",
        "broker_api",
        "kite",
        "kite_instruction",
    }
)


def advisory_output(
    *,
    symbol: str,
    bot_name: str,
    strategy_name: str,
    score: float,
    decision: str,
    reason: str,
    data_quality: Any = "UNKNOWN",
    risk_flags: Iterable[str] = (),
    scan_id: str | None = None,
    build_id: str = "phase2b-dev",
    config_hash: str = "phase2b-default",
    **extra: Any,
) -> Dict[str, Any]:
    """Build one serialisable output with mandatory safety flags."""
    if decision not in ADVISORY_DECISIONS:
        raise ValueError(f"unsupported advisory decision: {decision}")
    if not symbol or not bot_name or not strategy_name:
        raise ValueError("symbol, bot_name, and strategy_name are required")
    if not isinstance(reason, str) or not reason.strip():
        raise ValueError("reason is required")
    if any(key in PROHIBITED_OUTPUT_KEYS for key in extra):
        raise ValueError("executable output fields are prohibited")
    return {
        "timestamp": extra.pop(
            "timestamp",
            datetime.now(timezone.utc).isoformat(),
        ),
        "scan_id": scan_id,
        "symbol": symbol,
        "bot_name": bot_name,
        "strategy_name": strategy_name,
        "score": round(max(0.0, min(100.0, float(score))), 2),
        "decision": decision,
        "reason": reason,
        "data_quality": data_quality,
        "risk_flags": list(risk_flags),
        "build_id": build_id,
        "config_hash": config_hash,
        "advisory_only": True,
        "paper_only": True,
        **extra,
    }


def assert_advisory_output(output: Mapping[str, Any]) -> None:
    """Raise when an output violates the public advisory contract."""
    if output.get("advisory_only") is not True:
        raise ValueError("advisory_only=true is required")
    if output.get("paper_only") is not True:
        raise ValueError("paper_only=true is required")
    if output.get("decision") not in ADVISORY_DECISIONS:
        raise ValueError("invalid advisory decision")
    bad_keys = PROHIBITED_OUTPUT_KEYS.intersection(output.keys())
    if bad_keys:
        raise ValueError(f"prohibited output keys: {sorted(bad_keys)}")
    violations = _find_forbidden_values(output)
    if violations:
        raise ValueError(f"forbidden executable values: {violations}")


def _find_forbidden_values(value: Any, path: str = "") -> list[str]:
    found: list[str] = []
    if isinstance(value, Mapping):
        for key, child in value.items():
            key_path = f"{path}.{key}" if path else str(key)
            if str(key).lower() in {k.lower() for k in PROHIBITED_OUTPUT_KEYS}:
                found.append(key_path)
            found.extend(_find_forbidden_values(child, key_path))
    elif isinstance(value, (list, tuple, set)):
        for index, child in enumerate(value):
            found.extend(_find_forbidden_values(child, f"{path}[{index}]"))
    elif isinstance(value, str):
        upper = value.upper()
        for term in FORBIDDEN_ACTION_TERMS:
            if upper == term or f" {term} " in f" {upper} ":
                found.append(path or "<value>")
                break
    return found