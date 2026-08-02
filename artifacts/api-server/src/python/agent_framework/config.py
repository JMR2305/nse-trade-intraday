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
