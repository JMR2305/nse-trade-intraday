"""
heartbeat_service.py — Phase 10A
Tracks per-agent heartbeat timestamps and detects missed beats.

READ-ONLY · ADVISORY-ONLY — never restarts agents automatically.
"""
from __future__ import annotations

import threading
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _parse_iso(ts: Optional[str]) -> Optional[datetime]:
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


class HeartbeatService:
    """
    Tracks the last heartbeat for each registered agent.
    Detects missed beats by comparing elapsed time against the agent's
    declared heartbeat_interval_s with a configurable grace multiplier.

    NEVER auto-restarts agents — advisory alerts only.
    """

    DEFAULT_GRACE_MULTIPLIER: float = 3.0  # missed if > interval × grace
    DEFAULT_STALL_MULTIPLIER: float = 6.0  # stalled if > interval × stall

    def __init__(
        self,
        grace_multiplier: float = DEFAULT_GRACE_MULTIPLIER,
        stall_multiplier: float = DEFAULT_STALL_MULTIPLIER,
    ) -> None:
        self._grace = grace_multiplier
        self._stall = stall_multiplier
        self._mu    = threading.Lock()

    # ── Record heartbeat ───────────────────────────────────────────────────────

    def record(self, agent_id: str, record: "AgentRecord") -> None:  # type: ignore[name-defined]
        """Update the last_heartbeat on the AgentRecord (called by the agent)."""
        record.beat()

    # ── Check health ──────────────────────────────────────────────────────────

    def check(
        self,
        agent_id: str,
        last_heartbeat: Optional[str],
        heartbeat_interval_s: float,
    ) -> Tuple[str, float]:
        """
        Returns (status, elapsed_seconds).
        status: "OK" | "LATE" | "MISSED" | "STALLED" | "NEVER"
        """
        if not last_heartbeat:
            return "NEVER", -1.0

        last = _parse_iso(last_heartbeat)
        if last is None:
            return "NEVER", -1.0

        elapsed = (_now_utc() - last).total_seconds()
        interval = max(1.0, heartbeat_interval_s)

        if elapsed <= interval:
            return "OK", elapsed
        if elapsed <= interval * self._grace:
            return "LATE", elapsed
        if elapsed <= interval * self._stall:
            return "MISSED", elapsed
        return "STALLED", elapsed

    def check_all(
        self,
        agents: List["AgentRecord"],  # type: ignore[name-defined]
    ) -> List[Dict]:
        """Return heartbeat status for a list of AgentRecords."""
        results = []
        for a in agents:
            status, elapsed = self.check(
                a.agent_id, a.last_heartbeat, a.heartbeat_interval_s
            )
            results.append({
                "agent_id":           a.agent_id,
                "name":               a.name,
                "heartbeat_status":   status,
                "elapsed_s":          round(elapsed, 1) if elapsed >= 0 else None,
                "last_heartbeat":     a.last_heartbeat,
                "interval_s":         a.heartbeat_interval_s,
            })
        return results

    # ── Summary ───────────────────────────────────────────────────────────────

    def summary(self, agents: List["AgentRecord"]) -> Dict:  # type: ignore[name-defined]
        checks = self.check_all(agents)
        ok      = sum(1 for c in checks if c["heartbeat_status"] == "OK")
        late    = sum(1 for c in checks if c["heartbeat_status"] == "LATE")
        missed  = sum(1 for c in checks if c["heartbeat_status"] in ("MISSED", "STALLED"))
        never   = sum(1 for c in checks if c["heartbeat_status"] == "NEVER")
        return {
            "total":  len(checks),
            "ok":     ok,
            "late":   late,
            "missed": missed,
            "never":  never,
            "checks": checks,
        }
