"""Non-executing advisory risk feasibility checks."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Mapping

from .contracts import advisory_output


@dataclass(frozen=True)
class AdvisoryRiskLimits:
    capital: float = 100_000.0
    per_stock_cap: float = 25_000.0
    risk_per_idea: float = 1_000.0
    daily_loss_limit: float = 3_000.0


_FIXED_LIMITS = AdvisoryRiskLimits()


def evaluate_risk(
    symbol: str,
    idea: Mapping[str, Any],
    settings: Mapping[str, Any] | None,
    *,
    scan_id: str | None = None,
    build_id: str = "phase2b-dev",
    config_hash: str = "phase2b-default",
) -> dict[str, Any]:
    """Return advisory feasibility without quantity, order, or portfolio writes."""
    limits = _FIXED_LIMITS
    settings = dict(settings or {})
    mismatches = []
    if _number(settings.get("initial_capital")) != limits.capital:
        mismatches.append("initial_capital")
    if settings.get("active_intraday_universe") != "CUSTOM_LOW_PRICE_SECTOR":
        mismatches.append("active_intraday_universe")
    if settings.get("auto_paper_entries") is not False:
        mismatches.append("auto_paper_entries")
    if settings.get("bootstrap_paper_enabled") is not False:
        mismatches.append("bootstrap_paper_enabled")
    if mismatches:
        return _risk_result(
            symbol,
            0,
            "REJECTED",
            "CONFIG_MISMATCH: " + ", ".join(mismatches),
            ["CONFIG_MISMATCH"],
            limits,
            scan_id=scan_id,
            build_id=build_id,
            config_hash=config_hash,
        )

    notional = _finite_number(idea.get("notional_value", idea.get("proposed_notional")))
    risk_amount = _finite_number(idea.get("risk_amount"))
    daily_loss_raw = _finite_number(idea.get("daily_loss_to_date", idea.get("daily_loss")))
    if notional is None or risk_amount is None or daily_loss_raw is None:
        return _risk_result(
            symbol,
            0,
            "REJECTED",
            "RISK_EVIDENCE_MISSING",
            ["RISK_EVIDENCE_MISSING"],
            limits,
            risk_verdict="REJECTED_ADVISORY",
            scan_id=scan_id,
            build_id=build_id,
            config_hash=config_hash,
        )
    daily_loss = abs(daily_loss_raw)
    flags = []
    if notional < 0:
        flags.append("INVALID_NOTIONAL_VALUE")
    if risk_amount < 0:
        flags.append("INVALID_RISK_AMOUNT")
    if notional > limits.per_stock_cap:
        flags.append("PER_STOCK_CAP_EXCEEDED")
    if risk_amount > limits.risk_per_idea:
        flags.append("RISK_PER_IDEA_EXCEEDED")
    if daily_loss > limits.daily_loss_limit:
        flags.append("DAILY_LOSS_LIMIT_EXCEEDED")
    if _number(idea.get("score")) <= 0:
        flags.append("NO_SCORABLE_IDEA")
    allowed = not flags
    return _risk_result(
        symbol,
        100 if allowed else 0,
        "CANDIDATE" if allowed else "REJECTED",
        "advisory risk limits pass; no order or reservation created"
        if allowed
        else "; ".join(flags),
        flags,
        limits,
        notional_value=notional,
        risk_amount=risk_amount,
        daily_loss_to_date=daily_loss,
        risk_verdict="ALLOWED_ADVISORY" if allowed else "REJECTED_ADVISORY",
        scan_id=scan_id,
        build_id=build_id,
        config_hash=config_hash,
    )


def _risk_result(symbol: str, score: float, decision: str, reason: str, flags: list[str], limits: AdvisoryRiskLimits, **extra: Any) -> dict[str, Any]:
    return advisory_output(
        symbol=symbol,
        bot_name="risk-gate-bot",
        strategy_name="ADVISORY_RISK_GATE",
        score=score,
        decision=decision,
        reason=reason,
        data_quality="PASS" if "CONFIG_MISMATCH" not in flags else "CONFIG_BLOCKED",
        risk_flags=flags,
        capital_basis=limits.capital,
        per_stock_cap=limits.per_stock_cap,
        risk_per_idea=limits.risk_per_idea,
        daily_loss_limit=limits.daily_loss_limit,
        **extra,
    )


def _number(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _finite_number(value: Any) -> float | None:
    try:
        parsed = float(value)
        return parsed if math.isfinite(parsed) else None
    except (TypeError, ValueError):
        return None