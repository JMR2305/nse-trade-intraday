"""
exports_retention.py — workspace-root exports/ folder retention policy.

Deletes files in the workspace-root ``exports/`` directory that are older
than RETENTION_DAYS days.  Runs automatically after market close each trading
day (wired into the phase20 scheduler CLOSED tick, guarded by kv_claim_once
so it fires exactly once per calendar day across all Autoscale processes).

Rules:
  * Read-only probe: never modifies trading or portfolio state.
  * Never raises out of ``maybe_run_exports_cleanup`` — failures are returned
    as a status dict so the scheduler tick is never broken.
  * Only files are removed; sub-directories inside exports/ are left as-is so
    any sub-directory structure used by specific phases is preserved.
  * The kv claim key includes the IST calendar date so a retry on the same
    day after a transient error re-runs without waiting until tomorrow.
"""
from __future__ import annotations

import os
import time
from datetime import datetime, timezone
from typing import Any, Dict

RETENTION_DAYS: int = 7          # files older than this are deleted
_CLAIM_PREFIX = "exports_cleanup"


def _exports_dir() -> str:
    """Return the absolute path to the workspace-root exports/ folder."""
    # This module lives at artifacts/api-server/src/python/; walk up 4 levels
    # to reach the workspace root.
    here = os.path.dirname(os.path.abspath(__file__))
    workspace = os.path.abspath(os.path.join(here, "..", "..", "..", ".."))
    return os.path.join(workspace, "exports")


def prune_exports(retention_days: int = RETENTION_DAYS) -> Dict[str, Any]:
    """Delete files in exports/ older than *retention_days* days.

    Returns a summary dict with ``deleted``, ``kept``, ``errors``, and
    ``exports_dir`` keys.
    """
    exports_dir = _exports_dir()
    cutoff = time.time() - retention_days * 86400
    deleted: list[str] = []
    kept: list[str] = []
    errors: list[str] = []

    if not os.path.isdir(exports_dir):
        return {
            "deleted": 0, "kept": 0, "errors": [],
            "exports_dir": exports_dir, "skipped": "directory_not_found",
        }

    for entry in os.scandir(exports_dir):
        if not entry.is_file(follow_symlinks=False):
            continue
        try:
            mtime = entry.stat(follow_symlinks=False).st_mtime
            if mtime < cutoff:
                os.remove(entry.path)
                deleted.append(entry.name)
            else:
                kept.append(entry.name)
        except Exception as exc:
            errors.append(f"{entry.name}: {exc!s}"[:200])

    return {
        "deleted": len(deleted),
        "kept": len(kept),
        "errors": errors,
        "exports_dir": exports_dir,
        "retention_days": retention_days,
        "deleted_files": deleted,
    }


def maybe_run_exports_cleanup() -> Dict[str, Any]:
    """Run exports cleanup exactly once per IST calendar day.

    Uses kv_claim_once so multiple Autoscale ticks on the same day do not
    each delete files.  Returns a summary dict; never raises.
    """
    try:
        from zoneinfo import ZoneInfo
        today_ist = datetime.now(ZoneInfo("Asia/Kolkata")).strftime("%Y-%m-%d")
        claim_key = f"{_CLAIM_PREFIX}:{today_ist}"

        import phase20_store as store  # type: ignore[import]
        if not store.kv_claim_once(claim_key):
            return {"ran": False, "reason": "already_ran_today", "date": today_ist}

        result = prune_exports()
        result["ran"] = True
        result["date"] = today_ist
        return result
    except Exception as exc:
        return {"ran": False, "error": str(exc)[:300]}
