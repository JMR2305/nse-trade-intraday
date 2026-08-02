"""
config.py — Phase 10A
Feature flags for the Agent Framework modules.

READ-ONLY · ADVISORY-ONLY
"""
from __future__ import annotations
import os

# ── Feature flag names ─────────────────────────────────────────────────────────

SUPERVISOR_AGENT_ENABLED          = "SUPERVISOR_AGENT_ENABLED"
MARKET_DATA_AGENT_ENABLED         = "MARKET_DATA_AGENT_ENABLED"
RESEARCH_AGENT_ENABLED            = "RESEARCH_AGENT_ENABLED"
AGENT_FRAMEWORK_ENABLED           = "AGENT_FRAMEWORK_ENABLED"

# Phase 10B — Analysis Layer
MARKET_INTELLIGENCE_AGENT_ENABLED = "MARKET_INTELLIGENCE_AGENT_ENABLED"
STOCK_MONITORING_AGENT_ENABLED    = "STOCK_MONITORING_AGENT_ENABLED"
STRATEGY_AGENT_ENABLED            = "STRATEGY_AGENT_ENABLED"
RISK_AGENT_ENABLED                = "RISK_AGENT_ENABLED"

# Phase 10C — Decision Layer
AI_DECISION_AGENT_ENABLED = "AI_DECISION_AGENT_ENABLED"
EXECUTION_AGENT_ENABLED   = "EXECUTION_AGENT_ENABLED"
LIVE_EXECUTION_ENABLED    = "LIVE_EXECUTION_ENABLED"    # default FALSE — safety
PAPER_EXECUTION_ENABLED   = "PAPER_EXECUTION_ENABLED"   # default TRUE

# Phase 10D — Learning Layer
LEARNING_AGENT_ENABLED  = "LEARNING_AGENT_ENABLED"
KNOWLEDGE_AGENT_ENABLED = "KNOWLEDGE_AGENT_ENABLED"
AUTO_MODEL_UPDATES      = "AUTO_MODEL_UPDATES"    # MUST remain false — safety
AUTO_STRATEGY_TUNING    = "AUTO_STRATEGY_TUNING"  # MUST remain false — safety

# Phase 10E — Collaborative Intelligence + Autonomous Operations
COLLABORATION_ENGINE_ENABLED  = "COLLABORATION_ENGINE_ENABLED"
AUTONOMOUS_OPERATIONS_ENABLED = "AUTONOMOUS_OPERATIONS_ENABLED"
SUPERVISOR_EXTENDED_ENABLED   = "SUPERVISOR_EXTENDED_ENABLED"
COLLABORATION_ALERTS_ENABLED  = "COLLABORATION_ALERTS_ENABLED"

_TRUE = ("1", "true", "yes")


def _flag(name: str, default: bool = True) -> bool:
    return os.environ.get(name, "true" if default else "false").lower() in _TRUE


def is_supervisor_enabled() -> bool:
    return _flag(SUPERVISOR_AGENT_ENABLED, default=True)


def is_market_data_enabled() -> bool:
    return _flag(MARKET_DATA_AGENT_ENABLED, default=True)


def is_research_enabled() -> bool:
    return _flag(RESEARCH_AGENT_ENABLED, default=True)


def is_framework_enabled() -> bool:
    return _flag(AGENT_FRAMEWORK_ENABLED, default=True)


def disabled_response(flag: str) -> dict:
    return {
        "status":        "DISABLED",
        "available":     False,
        "advisory_only": True,
        "read_only":     True,
        "message":       f"Set {flag}=true to enable this agent.",
    }
