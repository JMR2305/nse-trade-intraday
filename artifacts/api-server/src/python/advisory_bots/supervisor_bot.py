"""Final fail-closed advisory boundary."""

from __future__ import annotations

from typing import Any, Iterable, Mapping

from .contracts import assert_advisory_output, advisory_output


def supervise(
    outputs: Iterable[Mapping[str, Any]],
    settings: Mapping[str, Any] | None,
    *,
    universe_health: Mapping[str, Any] | None = None,
    scan_id: str | None = None,
    build_id: str = "phase2b-dev",
    config_hash: str = "phase2b-default",
) -> dict[str, Any]:
    """Approve advisory recording only; every unsafe condition blocks."""
    outputs = [dict(output) for output in outputs]
    settings = dict(settings or {})
    violations: list[str] = []
    for index, output in enumerate(outputs):
        try:
            assert_advisory_output(output)
        except ValueError as exc:
            violations.append(f"output[{index}]: {exc}")
    if settings.get("auto_paper_entries") is not False:
        violations.append("auto_paper_entries is not false")
    if settings.get("bootstrap_paper_enabled") is not False:
        violations.append("bootstrap_paper_enabled is not false")
    if settings.get("initial_capital") != 100000:
        violations.append("initial_capital is not 100000")
    if settings.get("active_intraday_universe") != "CUSTOM_LOW_PRICE_SECTOR":
        violations.append("active universe is not CUSTOM_LOW_PRICE_SECTOR")
    if universe_health is not None:
        if universe_health.get("healthy") is not True:
            violations.append("universe health is not healthy")
        if universe_health.get("active_count") != 23:
            violations.append("universe active count is not 23")
        if universe_health.get("nifty_fallback_detected") is not False:
            violations.append("NIFTY_50 fallback detected")

    blocked = bool(violations)
    return advisory_output(
        symbol="__RUN__",
        bot_name="supervisor-bot",
        strategy_name="ADVISORY_SUPERVISOR",
        score=0 if blocked else 100,
        decision="SUPERVISOR_BLOCKED" if blocked else "WATCH",
        reason="; ".join(violations) if blocked else "all outputs are advisory-only and settings safety state is confirmed",
        data_quality="SUPERVISOR_BLOCKED" if blocked else "PASS",
        risk_flags=["SUPERVISOR_BLOCK"] if blocked else [],
        scan_id=scan_id,
        build_id=build_id,
        config_hash=config_hash,
        supervisor_verdict="SUPERVISOR_BLOCKED" if blocked else "APPROVED_FOR_ADVISORY_RECORD",
        violations=violations,
        auto_paper_entries_confirmed=settings.get("auto_paper_entries") is False,
        bootstrap_paper_enabled_confirmed=settings.get("bootstrap_paper_enabled") is False,
        output_count=len(outputs),
    )