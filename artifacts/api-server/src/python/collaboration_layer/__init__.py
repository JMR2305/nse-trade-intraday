"""
collaboration_layer — Phase 10E
Aggregation layer for the Collaborative Intelligence + Autonomous Operations platform.

READ-ONLY · ADVISORY-ONLY
"""
from .shared_services import (
    get_collaboration_summary,
    get_collaboration_timeline,
    get_collaboration_performance,
)

__all__ = [
    "get_collaboration_summary",
    "get_collaboration_timeline",
    "get_collaboration_performance",
]
