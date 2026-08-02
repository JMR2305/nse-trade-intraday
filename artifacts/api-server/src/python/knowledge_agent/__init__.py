"""
knowledge_agent — Phase 10D
READ-ONLY · ADVISORY-ONLY Knowledge Agent package.
"""
from .agent import KnowledgeAgent
from .shared_services import (
    get_knowledge_snapshot,
    get_knowledge_search,
    get_knowledge_patterns,
    get_knowledge_lessons,
    get_trade_memory,
    get_knowledge_status,
)

__all__ = [
    "KnowledgeAgent",
    "get_knowledge_snapshot",
    "get_knowledge_search",
    "get_knowledge_patterns",
    "get_knowledge_lessons",
    "get_trade_memory",
    "get_knowledge_status",
]
