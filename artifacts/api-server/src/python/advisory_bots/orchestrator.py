"""Manual, read-input-only Phase 2B advisory multi-bot orchestration."""

from __future__ import annotations

from typing import Any, Dict, Iterable, Mapping

from .audit_bot import persist_advisory_run
from .data_quality_bot import check_symbol_quality
from .decision_bot import combine_scores
from .regime_bot import classify_regime
from .risk_gate_bot import evaluate_risk
from .strategies import evaluate_strategies
from .supervisor_bot import supervise
from .universe_bot import CUSTOM_UNIVERSE, validate_universe


def run_advisory_analysis(
    *,
    scan_id: str,
    universe_rows: Iterable[Mapping[str, Any]],
    scan_items: Iterable[Mapping[str, Any]],
    settings: Mapping[str, Any],
    market_context: Mapping[str, Any] | None = None,
    risk_inputs: Mapping[str, Mapping[str, Any]] | None = None,
    build_id: str = "phase2b-dev",
    config_hash: str = "phase2b-default",
    persist: bool = False,
) -> Dict[str, Any]:
    """Run one manually invoked advisory analysis over supplied read-only data.

    It intentionally accepts all inputs from the caller rather than pulling
    from scheduler, execution, broker, or settings-write code.  `persist` is
    false by default and only writes append-only advisory audit evidence after
    the supervisor passes.
    """
    if not scan_id:
        raise ValueError("scan_id is required for advisory analysis")

    rows = [dict(row) for row in universe_rows if isinstance(row, Mapping)]
    items_by_symbol = {
        str(item.get("symbol") or item.get("Symbol") or "").strip().upper(): dict(item)
        for item in scan_items
        if isinstance(item, Mapping)
    }
    universe_health = validate_universe(
        rows,
        scan_id=scan_id,
        build_id=build_id,
        config_hash=config_hash,
    )
    regime = classify_regime(
        market_context,
        scan_id=scan_id,
        build_id=build_id,
        config_hash=config_hash,
    )
    active_rows = [
        row for row in rows
        if row.get("is_active") is True and row.get("allowed_universe") == CUSTOM_UNIVERSE
    ]

    quality_outputs = []
    strategy_outputs = []
    risk_outputs = []
    decisions = []
    risk_inputs = risk_inputs or {}

    if universe_health["healthy"]:
        for master_row in active_rows:
            symbol = str(master_row["symbol"]).strip().upper()
            item = items_by_symbol.get(symbol)
            quality = check_symbol_quality(
                symbol,
                item,
                master_row=master_row,
                scan_id=scan_id,
                build_id=build_id,
                config_hash=config_hash,
            )
            quality_outputs.append(quality)
            if quality["decision"] != "WATCH":
                decisions.append(
                    combine_scores(
                        symbol,
                        [],
                        {"decision": "REJECTED", "risk_flags": ["DATA_QUALITY_BLOCK"]},
                        quality,
                        regime,
                        scan_id=scan_id,
                        build_id=build_id,
                        config_hash=config_hash,
                    )
                )
                continue

            strategies = evaluate_strategies(symbol, item or {}, regime)
            for strategy in strategies:
                strategy["scan_id"] = scan_id
                strategy["build_id"] = build_id
                strategy["config_hash"] = config_hash
            strategy_outputs.extend(strategies)

            risk_input = dict(risk_inputs.get(symbol) or {})
            risk_input.setdefault("score", max(float(output["score"]) for output in strategies))
            risk = evaluate_risk(
                symbol,
                risk_input,
                settings,
                scan_id=scan_id,
                build_id=build_id,
                config_hash=config_hash,
            )
            risk_outputs.append(risk)
            decisions.append(
                combine_scores(
                    symbol,
                    strategies,
                    risk,
                    quality,
                    regime,
                    scan_id=scan_id,
                    build_id=build_id,
                    config_hash=config_hash,
                )
            )

    all_outputs = [universe_health, regime, *quality_outputs, *strategy_outputs, *risk_outputs, *decisions]
    supervisor = supervise(
        all_outputs,
        settings,
        universe_health=universe_health,
        scan_id=scan_id,
        build_id=build_id,
        config_hash=config_hash,
    )
    run = {
        "scan_id": scan_id,
        "universe_health": universe_health,
        "regime": regime,
        "quality_outputs": quality_outputs,
        "strategy_outputs": strategy_outputs,
        "risk_outputs": risk_outputs,
        "decisions": _rank(decisions),
        "supervisor": supervisor,
        "advisory_only": True,
        "paper_only": True,
        "manual_invocation_only": True,
        "scheduler_integration": False,
    }
    if persist:
        run["audit"] = persist_advisory_run(run, settings=settings)
    return run


def _rank(decisions: list[Dict[str, Any]]) -> list[Dict[str, Any]]:
    ranked = sorted(decisions, key=lambda item: float(item.get("score") or 0), reverse=True)
    for index, decision in enumerate(ranked, start=1):
        decision["final_rank"] = index
    return ranked