"""Append-only persistence for supervisor-approved advisory evidence."""

from __future__ import annotations

from typing import Any, Callable, Dict, Mapping

from phase24_store import ADVISORY_TABLES, insert_advisory_batch

from .contracts import assert_advisory_output
from .supervisor_bot import supervise

BatchWriter = Callable[[Dict[str, list[Dict[str, Any]]]], Dict[str, int]]


def persist_advisory_run(
    run: Mapping[str, Any],
    *,
    settings: Mapping[str, Any],
    batch_writer: BatchWriter = insert_advisory_batch,
) -> Dict[str, Any]:
    """Persist only an already supervisor-approved advisory run.

    The writer is injected for tests.  It can only receive one of the four
    approved advisory tables; this module has no access to trading storage.
    """
    subject_outputs = _subject_outputs(run)
    universe_health = run.get("universe_health")
    scan_id = run.get("scan_id")
    if not isinstance(universe_health, Mapping) or not scan_id:
        return {
            "persisted": False,
            "reason": "universe health and scan_id are required before advisory persistence",
            "inserted": {},
            "advisory_only": True,
            "paper_only": True,
        }
    # Never trust a caller-supplied verdict.  Recompute the supervisor result
    # over the actual batch and the supplied read-only settings immediately
    # before persistence, then persist that recomputed result as audit evidence.
    supervisor = supervise(
        subject_outputs,
        settings,
        universe_health=universe_health,
        scan_id=str(scan_id),
        build_id=str(run.get("build_id") or universe_health.get("build_id") or "phase2b-dev"),
        config_hash=str(run.get("config_hash") or universe_health.get("config_hash") or "phase2b-default"),
    )
    if supervisor.get("supervisor_verdict") != "APPROVED_FOR_ADVISORY_RECORD":
        return {
            "persisted": False,
            "reason": "recomputed supervisor blocked advisory persistence",
            "inserted": {},
            "supervisor": supervisor,
            "advisory_only": True,
            "paper_only": True,
        }

    outputs = [*subject_outputs, supervisor]
    if not subject_outputs:
        return {
            "persisted": False,
            "reason": "no advisory outputs to persist",
            "inserted": {},
            "advisory_only": True,
            "paper_only": True,
        }

    # Validate the complete batch before the first insert.  A malformed record
    # must produce zero writes rather than a partially persisted audit.
    for output in outputs:
        _require_persistable(output)

    records_by_table = {
        "advisory_bot_outputs": outputs,
        "advisory_strategy_scores": [dict(output) for output in run.get("strategy_outputs") or []],
        "advisory_decision_audit": [dict(output) for output in run.get("decisions") or []],
        "advisory_universe_health": [],
    }
    universe = run.get("universe_health")
    if universe:
        records_by_table["advisory_universe_health"].append(dict(universe))
    inserted = batch_writer(records_by_table)

    return {
        "persisted": True,
        "inserted": inserted,
        "advisory_only": True,
        "paper_only": True,
    }


def _subject_outputs(run: Mapping[str, Any]) -> list[Dict[str, Any]]:
    result: list[Dict[str, Any]] = []
    for output in (run.get("universe_health"), run.get("regime")):
        if isinstance(output, Mapping):
            result.append(dict(output))
    for key in ("quality_outputs", "strategy_outputs", "risk_outputs", "decisions"):
        result.extend(dict(output) for output in (run.get(key) or []) if isinstance(output, Mapping))
    return result


def _require_persistable(output: Mapping[str, Any]) -> None:
    assert_advisory_output(output)
    if output.get("advisory_only") is not True or output.get("paper_only") is not True:
        raise ValueError("only advisory paper-only outputs may be persisted")
    if not output.get("scan_id"):
        raise ValueError("scan_id is required before advisory persistence")
    if output.get("decision") not in {
        "WATCH", "CANDIDATE", "REJECTED", "BLOCKED_DATA_QUALITY",
        "INSUFFICIENT_CONTEXT", "SUPERVISOR_BLOCKED",
    }:
        raise ValueError("unapproved advisory decision")