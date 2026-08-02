"""
autonomous_operations — Phase 10E
Autonomous Operations Engine for ApexQuant AI.

READ-ONLY · ADVISORY-ONLY
No autonomous execution. No automatic strategy tuning.
No automatic AI retraining. No automatic portfolio changes.
"""
from .agent import AutonomousOpsAgent
from .operations_engine import (
    compute_system_health,
    compute_scalability_dashboard,
    compute_ops_snapshot,
)
from .supervisor_extensions import build_supervisor_extended
from .shared_services import (
    get_autonomous_ops_snapshot,
    get_system_health,
    get_scalability_dashboard,
    get_supervisor_extended,
    get_capacity_forecast,
)

__all__ = [
    "AutonomousOpsAgent",
    "compute_system_health",
    "compute_scalability_dashboard",
    "compute_ops_snapshot",
    "build_supervisor_extended",
    "get_autonomous_ops_snapshot",
    "get_system_health",
    "get_scalability_dashboard",
    "get_supervisor_extended",
    "get_capacity_forecast",
]
