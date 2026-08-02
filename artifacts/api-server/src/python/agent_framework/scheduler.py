"""
scheduler.py — Phase 10A
Simple interval-based task scheduler for agents.

Supports:
  - one-shot tasks (run_once)
  - periodic tasks (every N seconds)
  - manual tick (for synchronous testing)

All tasks are advisory-only work (data collection, snapshot publishing).
NEVER schedules order placement or portfolio modification.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional


@dataclass
class ScheduledTask:
    task_id:      str
    fn:           Callable[[], Any]
    interval_s:   float          # 0 = one-shot
    last_run_at:  float = 0.0
    run_count:    int   = 0
    error_count:  int   = 0
    last_error:   str   = ""
    enabled:      bool  = True

    def is_due(self, now: float) -> bool:
        if not self.enabled:
            return False
        if self.interval_s <= 0 and self.run_count > 0:
            return False  # one-shot already ran
        return (now - self.last_run_at) >= self.interval_s


class AgentScheduler:
    """
    Lightweight cooperative scheduler.

    In production the agent calls tick() from its own loop.
    In tests, call tick() directly to advance time manually.

    No background threads are created — the caller owns the loop.
    """

    def __init__(self) -> None:
        self._tasks: Dict[str, ScheduledTask] = {}
        self._mu = threading.Lock()

    # ── Registration ──────────────────────────────────────────────────────────

    def schedule(
        self,
        task_id: str,
        fn: Callable[[], Any],
        interval_s: float,
    ) -> ScheduledTask:
        """Register a periodic task. Returns the ScheduledTask."""
        task = ScheduledTask(task_id=task_id, fn=fn, interval_s=interval_s)
        with self._mu:
            self._tasks[task_id] = task
        return task

    def run_once(
        self,
        task_id: str,
        fn: Callable[[], Any],
    ) -> ScheduledTask:
        """Register a one-shot task (runs on next tick)."""
        return self.schedule(task_id, fn, interval_s=0)

    def cancel(self, task_id: str) -> bool:
        with self._mu:
            t = self._tasks.get(task_id)
            if t:
                t.enabled = False
                return True
            return False

    def remove(self, task_id: str) -> bool:
        with self._mu:
            return self._tasks.pop(task_id, None) is not None

    # ── Execution ─────────────────────────────────────────────────────────────

    def tick(self, now: Optional[float] = None) -> List[str]:
        """
        Run all due tasks. Returns list of task_ids that ran.
        Errors are caught and recorded on the task; never propagated.
        """
        now = now if now is not None else time.monotonic()
        ran = []
        with self._mu:
            due = [t for t in self._tasks.values() if t.is_due(now)]

        for task in due:
            try:
                task.fn()
                task.run_count += 1
                task.last_error = ""
            except Exception as exc:
                task.error_count += 1
                task.last_error = str(exc)[:200]
            finally:
                task.last_run_at = now
            ran.append(task.task_id)

        return ran

    # ── Status ────────────────────────────────────────────────────────────────

    def status(self) -> List[Dict]:
        with self._mu:
            return [
                {
                    "task_id":    t.task_id,
                    "interval_s": t.interval_s,
                    "run_count":  t.run_count,
                    "error_count":t.error_count,
                    "last_error": t.last_error,
                    "enabled":    t.enabled,
                }
                for t in self._tasks.values()
            ]
