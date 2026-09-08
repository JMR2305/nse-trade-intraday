"""Development-only, fixture-only runner for the advisory analysis layer.

This module deliberately has no production data loader and no access to broker,
Phase 20, scheduler, settings-write, trade, or position modules.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Mapping

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from advisory_bots.flags import get_advisory_flags
    from advisory_bots.orchestrator import run_advisory_analysis
else:
    from .flags import get_advisory_flags
    from .orchestrator import run_advisory_analysis


def _load_payload(fixture: str | None) -> Mapping[str, Any]:
    if fixture:
        payload = json.loads(Path(fixture).read_text())
    else:
        payload = json.load(sys.stdin)
    if not isinstance(payload, Mapping):
        raise ValueError("fixture must contain one JSON object")
    return payload


def _required_payload(payload: Mapping[str, Any], key: str) -> Any:
    value = payload.get(key)
    if value is None:
        raise ValueError(f"fixture field is required: {key}")
    return value


def run_fixture(fixture: str | None, *, persist: bool = False) -> dict[str, Any]:
    """Run one caller-supplied fixture, never persisting unless explicitly safe."""
    flags = get_advisory_flags()
    if not flags.bots_enabled:
        raise ValueError("manual runner requires ADVISORY_BOTS_ENABLED=true")
    if persist and (not flags.persist_enabled or not flags.persistence_environment_allowed):
        raise ValueError(
            "persistence requires ADVISORY_BOTS_PERSIST_ENABLED=true with NODE_ENV=development or test"
        )

    payload = _load_payload(fixture)
    result = run_advisory_analysis(
        scan_id=str(_required_payload(payload, "scan_id")),
        universe_rows=_required_payload(payload, "universe_rows"),
        scan_items=_required_payload(payload, "scan_items"),
        settings=_required_payload(payload, "settings"),
        market_context=payload.get("market_context"),
        risk_inputs=payload.get("risk_inputs"),
        build_id=str(payload.get("build_id") or "phase3a-dev"),
        config_hash=str(payload.get("config_hash") or "phase3a-fixture"),
        persist=persist,
    )
    return {
        "status": "OK",
        "advisory_only": True,
        "paper_only": True,
        "not_trade_instructions": True,
        "manual_invocation_only": True,
        "ranked_advisory_outputs": result.get("decisions", []),
        "result": result,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run advisory bots over a development JSON fixture only."
    )
    parser.add_argument(
        "--fixture",
        help="JSON fixture path; stdin is used when omitted",
    )
    parser.add_argument(
        "--stdin",
        action="store_true",
        help="read the fixture JSON from stdin (the default when --fixture is omitted)",
    )
    parser.add_argument(
        "--persist",
        action="store_true",
        help="explicitly persist advisory evidence; rejected unless safe flags allow it",
    )
    args = parser.parse_args(argv)
    try:
        if args.fixture and args.stdin:
            raise ValueError("use either --fixture or --stdin, not both")
        print(json.dumps(run_fixture(args.fixture, persist=args.persist), default=str))
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        print(
            json.dumps(
                {
                    "status": "ERROR",
                    "advisory_only": True,
                    "paper_only": True,
                    "not_trade_instructions": True,
                    "error": str(exc),
                }
            )
        )
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())