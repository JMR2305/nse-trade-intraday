"""
supervisor_agent — Phase 10A
Monitors all registered agents, detects problems, generates advisory alerts.

READ-ONLY · ADVISORY-ONLY
NEVER auto-restarts agents. Recommendations only.
"""
from .shared_services import (
    get_supervisor_snapshot,
    get_agent_list,
    get_agent_detail,
    get_supervisor_alerts,
    get_scalability_estimate,
)

__all__ = [
    "get_supervisor_snapshot",
    "get_agent_list",
    "get_agent_detail",
    "get_supervisor_alerts",
    "get_scalability_estimate",
]
