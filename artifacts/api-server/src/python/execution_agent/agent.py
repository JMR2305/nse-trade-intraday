"""
agent.py — Phase 10C
Execution Agent.

Consumes decision snapshots + portfolio state.
Produces execution plans with full pre-execution validation.

Execution Modes:
  Paper (default) — simulated, no real orders
  Semi-Auto       — operator approves each order
  Live            — requires LIVE_EXECUTION_ENABLED=true + operator confirmation

Safety Guarantees:
  - NO autonomous live order placement ever
  - Paper execution only by default
  - Every execution plan passes 10 pre-execution checks
  - Failed checks block plan generation

READ-ONLY (analysis) · ADVISORY-ONLY (recommendations)
PAPER EXECUTION available when PAPER_EXECUTION_ENABLED=true
LIVE EXECUTION requires explicit flag + operator confirmation
"""
from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from agent_framework.base_agent import BaseAgent
from execution_agent.execution_planner import (
    PreExecutionChecklist, OrderValidator, ExecutionPlan, determine_execution_mode,
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _safe(fn, default=None):
    try:
        return fn()
    except Exception:
        return default


def _f(v):
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


class ExecutionAgent(BaseAgent):
    """
    Validates recommendations and generates execution plans.
    Default: Paper execution only.
    Live execution: requires LIVE_EXECUTION_ENABLED=true + operator confirmation.

    NEVER places autonomous live orders.
    """

    HEARTBEAT_INTERVAL_S: float = 60.0

    def __init__(self) -> None:
        super().__init__(
            agent_id="execution-agent",
            name="Execution Agent",
            version="1.0.0",
            owner="ApexQuant AI",
            priority=5,
            dependencies=["ai-decision-agent"],
            capabilities=[
                "pre_execution_validation", "order_validation",
                "execution_planning", "paper_execution",
                "cost_estimation", "slippage_estimation",
            ],
        )
        self._checklist = PreExecutionChecklist()
        self._validator = OrderValidator()
        self._planner   = ExecutionPlan()
        self._last_snapshot: Optional[Dict[str, Any]] = None

    @property
    def default_topic(self) -> str:
        return "execution"

    def execute_task(self) -> Optional[Dict[str, Any]]:
        start_ms = time.monotonic() * 1000

        exec_mode = determine_execution_mode()
        decisions = _safe(self._load_decisions) or {}
        portfolio = _safe(self._load_portfolio) or {}
        risk_snap = _safe(self._load_risk)      or {}
        mi_snap   = _safe(self._load_mi)        or {}

        recommendations = decisions.get("recommendations") or []

        # Evaluate top-20 actionable recommendations
        actionable = [
            r for r in recommendations
            if r.get("decision_type") not in ("NO_ACTION", "AVOID")
        ][:20]

        execution_queue: List[Dict[str, Any]] = []
        paper_orders:    List[Dict[str, Any]] = []
        validation_failures: List[Dict[str, Any]] = []

        for rec in actionable:
            plan = _safe(lambda r=rec: self._plan_recommendation(
                r, portfolio, risk_snap, mi_snap, exec_mode
            ))
            if plan is None:
                continue

            if plan["validation_passed"]:
                execution_queue.append({
                    "symbol":          plan["symbol"],
                    "decision_type":   plan["decision_type"],
                    "execution_mode":  exec_mode,
                    "overall_score":   rec.get("overall_score", 0),
                    "confidence":      rec.get("confidence", 0),
                    "execution_plan":  plan["execution_plan"],
                    "status":          "PENDING_APPROVAL" if exec_mode != "PAPER" else "PAPER_READY",
                    "advisory_only":   True,
                })
                if exec_mode == "PAPER":
                    paper_orders.append(self._create_paper_order(plan, rec))
            else:
                validation_failures.append({
                    "symbol":   plan["symbol"],
                    "failures": [c for c in plan["checklist"] if not c["passed"]],
                })

        elapsed = round((time.monotonic() * 1000) - start_ms, 1)

        payload = {
            "agent_id":    "execution-agent",
            "agent_name":  "Execution Agent",
            "advisory_only":         True,
            "never_autonomous_live": True,
            "execution_mode":        exec_mode,
            "live_execution_enabled":exec_mode == "LIVE",
            "paper_execution_enabled": exec_mode in ("PAPER", "SEMI_AUTO"),

            # Queue
            "execution_queue":       execution_queue,
            "execution_queue_size":  len(execution_queue),
            "paper_orders":          paper_orders,
            "paper_orders_count":    len(paper_orders),
            "validation_failures":   validation_failures,
            "validation_failure_count": len(validation_failures),

            # Stats
            "recommendations_received": len(recommendations),
            "actionable_evaluated":     len(actionable),
            "plans_generated":          len(execution_queue) + len(validation_failures),

            # Context
            "market_regime":  mi_snap.get("market_regime", "UNKNOWN"),
            "risk_level":     risk_snap.get("risk_level", "UNKNOWN"),
            "session_phase":  (mi_snap.get("session_info") or {}).get("phase", "UNKNOWN"),

            "planning_latency_ms": elapsed,
            "generated_at": _now_iso(),
        }
        self._last_snapshot = payload
        return payload

    # ── Plan generation ───────────────────────────────────────────────────────

    def _plan_recommendation(
        self, rec: Dict, portfolio: Dict, risk_snap: Dict, mi_snap: Dict, mode: str
    ) -> Dict[str, Any]:
        symbol   = rec.get("symbol", "UNKNOWN")
        plan_raw = self._planner.generate(symbol, rec, portfolio)
        qty      = plan_raw["suggested_qty"]
        price    = plan_raw["suggested_entry"]

        # Pre-execution checklist
        all_passed, checklist = self._checklist.run(
            symbol, qty, price, portfolio, risk_snap, mi_snap
        )

        # Order validation
        order_valid, order_errors = self._validator.validate(symbol, qty, price)

        return {
            "symbol":            symbol,
            "decision_type":     rec.get("decision_type"),
            "validation_passed": all_passed and order_valid,
            "checklist":         checklist,
            "order_errors":      order_errors,
            "execution_plan":    plan_raw,
        }

    @staticmethod
    def _create_paper_order(plan: Dict, rec: Dict) -> Dict[str, Any]:
        ep = plan["execution_plan"]
        return {
            "order_id":      f"PAPER-{rec.get('symbol','X')}-{int(time.time())}",
            "symbol":        plan["symbol"],
            "qty":           ep["suggested_qty"],
            "price":         ep["suggested_entry"],
            "order_type":    "LIMIT",
            "side":          "BUY" if rec.get("decision_type") in (
                                 "BUY_CANDIDATE", "ACCUMULATE") else "SELL",
            "stop_loss":     ep["stop_loss"],
            "target":        ep["target_1"],
            "estimated_charges": ep["estimated_charges"]["total"],
            "status":        "PAPER_SIMULATED",
            "decision_type": rec.get("decision_type"),
            "confidence":    rec.get("confidence", 0),
            "advisory_only": True,
            "is_paper":      True,
            "created_at":    _now_iso(),
        }

    # ── Data loaders ──────────────────────────────────────────────────────────

    @staticmethod
    def _load_decisions() -> Dict[str, Any]:
        from ai_decision_agent.shared_services import get_ai_decision_snapshot
        return get_ai_decision_snapshot()

    @staticmethod
    def _load_portfolio() -> Dict[str, Any]:
        from portfolio_store import load_state
        return load_state() or {}

    @staticmethod
    def _load_risk() -> Dict[str, Any]:
        from risk_agent.shared_services import get_risk_snapshot
        return get_risk_snapshot()

    @staticmethod
    def _load_mi() -> Dict[str, Any]:
        from market_intelligence_agent.shared_services import get_market_intelligence_agent_snapshot
        return get_market_intelligence_agent_snapshot()

    def get_plan_for_symbol(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Generate execution plan for a specific symbol on demand."""
        decisions = _safe(self._load_decisions) or {}
        portfolio = _safe(self._load_portfolio) or {}
        risk_snap = _safe(self._load_risk) or {}
        mi_snap   = _safe(self._load_mi) or {}
        mode      = determine_execution_mode()

        recs = decisions.get("recommendations") or []
        rec  = next((r for r in recs if r.get("symbol") == symbol), None)
        if rec is None:
            # Generate a minimal recommendation context
            rec = {"symbol": symbol, "decision_type": "WATCH", "overall_score": 50, "confidence": 0.5}

        plan = _safe(lambda: self._plan_recommendation(rec, portfolio, risk_snap, mi_snap, mode))
        if plan is None:
            return None
        plan["available"]      = True
        plan["execution_mode"] = mode
        plan["advisory_only"]  = True
        return plan

    def last_snapshot(self) -> Optional[Dict[str, Any]]:
        return self._last_snapshot
