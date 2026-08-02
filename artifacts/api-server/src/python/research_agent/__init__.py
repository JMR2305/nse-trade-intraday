"""
research_agent — Phase 10A
Collects and normalises research feeds; publishes ResearchSnapshot.

READ-ONLY · ADVISORY-ONLY
No recommendations. No order placement.
"""
from .shared_services import (
    get_research_snapshot,
    get_research_metrics,
    get_research_status,
)

__all__ = [
    "get_research_snapshot",
    "get_research_metrics",
    "get_research_status",
]
