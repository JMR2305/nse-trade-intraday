"""
collaboration_engine — Phase 10E
Agent Collaboration Engine for ApexQuant AI.

READ-ONLY · ADVISORY-ONLY
"""
from .agent import CollaborationEngine
from .collaboration_graph import build_collaboration_graph
from .decision_lineage import build_decision_lineage
from .shared_services import (
    get_collaboration_snapshot,
    get_collaboration_graph,
    get_collaboration_lineage,
    get_collaboration_alerts,
    get_collaboration_health,
    get_comm_monitor,
    get_collaboration_dependencies,
)

__all__ = [
    "CollaborationEngine",
    "build_collaboration_graph",
    "build_decision_lineage",
    "get_collaboration_snapshot",
    "get_collaboration_graph",
    "get_collaboration_lineage",
    "get_collaboration_alerts",
    "get_collaboration_health",
    "get_comm_monitor",
    "get_collaboration_dependencies",
]
