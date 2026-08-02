"""
agent_framework — Phase 10A
Foundational multi-agent infrastructure for ApexQuant AI.

READ-ONLY · ADVISORY-ONLY
All agents observe and report; none modify trading state, orders,
portfolio, strategy logic, AI models, or execution.
"""
from .models import AgentState, AgentRecord, HealthStatus, SnapshotEnvelope
from .agent_registry import AgentRegistry
from .snapshot_bus import SnapshotBus
from .heartbeat_service import HeartbeatService
from .metrics import AgentMetrics
from .config import (
    SUPERVISOR_AGENT_ENABLED,
    MARKET_DATA_AGENT_ENABLED,
    RESEARCH_AGENT_ENABLED,
    is_supervisor_enabled,
    is_market_data_enabled,
    is_research_enabled,
    disabled_response,
)

__all__ = [
    "AgentState", "AgentRecord", "HealthStatus", "SnapshotEnvelope",
    "AgentRegistry", "SnapshotBus", "HeartbeatService", "AgentMetrics",
    "SUPERVISOR_AGENT_ENABLED", "MARKET_DATA_AGENT_ENABLED", "RESEARCH_AGENT_ENABLED",
    "is_supervisor_enabled", "is_market_data_enabled", "is_research_enabled",
    "disabled_response",
]
