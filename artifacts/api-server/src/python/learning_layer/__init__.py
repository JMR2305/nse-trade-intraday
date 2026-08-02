"""
learning_layer — Phase 10D
Aggregation layer for Learning Agent + Knowledge Agent.
READ-ONLY · ADVISORY-ONLY
"""
from .shared_services import (
    get_learning_summary,
    get_learning_timeline,
    get_learning_performance,
)

__all__ = [
    "get_learning_summary",
    "get_learning_timeline",
    "get_learning_performance",
]
