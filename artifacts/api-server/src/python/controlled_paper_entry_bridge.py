"""Disabled advisory-to-paper bridge.

This boundary intentionally stops at a dry-run estimate.  There is no import
or call path to execution, paper trading, broker, settings, or scheduling.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from controlled_paper_entry_dry_run import DRY_RUN_MARKER, simulate_dry_run
from controlled_paper_entry_flags import (
    ControlledPaperEntryFlags,
    get_controlled_paper_entry_flags,
)


def preview_advisory_candidate(
    advisory_candidate: Mapping[str, Any] | object,
    *,
    flags: ControlledPaperEntryFlags | None = None,
) -> dict[str, Any]:
    """Return a non-executable preview and never produce an entry request."""
    controls = flags or get_controlled_paper_entry_flags()
    if not controls.framework_enabled:
        return {
            "status": "BRIDGE_DISABLED",
            "dry_run_only": True,
            "marker": DRY_RUN_MARKER,
            "execution_allowed": False,
            "simulation": None,
        }
    if not controls.review_gate_safe:
        return {
            "status": "BLOCKED",
            "dry_run_only": controls.dry_run_only,
            "marker": DRY_RUN_MARKER,
            "execution_allowed": False,
            "simulation": None,
            "rejection_reason": "controlled-entry safety controls are not in review-only mode",
        }
    return {
        "status": "DRY_RUN_ONLY",
        "dry_run_only": True,
        "marker": DRY_RUN_MARKER,
        "execution_allowed": False,
        "simulation": simulate_dry_run(advisory_candidate),
    }