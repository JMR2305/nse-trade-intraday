"""
learning_agent — Phase 10D
READ-ONLY · ADVISORY-ONLY Learning Agent package.
"""
from .agent import LearningAgent
from .shared_services import (
    get_learning_snapshot,
    get_learning_metrics,
    get_learning_insights,
    get_learning_status,
)

__all__ = [
    "LearningAgent",
    "get_learning_snapshot",
    "get_learning_metrics",
    "get_learning_insights",
    "get_learning_status",
]
