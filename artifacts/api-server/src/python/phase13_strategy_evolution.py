"""
phase13_strategy_evolution.py — Strategy Evolution Module

Proposes candidate strategy mutations based on out-of-sample completed paper-trade evidence.

Rules:
  1. Reads ONLY completed paper trades (SELL rows with close_ts — no-lookahead)
  2. Requires minimum 20 completed trades per strategy before any mutation proposal
  3. Never auto-promotes a mutation — all proposals require explicit human approval
  4. Each proposal is isolated: changing one strategy cannot affect others
  5. No live broker order path — PAPER TRADING / RESEARCH ONLY
  6. Mutations are parameter tweaks only (thresholds, weights) — no structural changes

PAPER TRADING / RESEARCH ONLY
"""

from __future__ import annotations

import json
import os
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

_DIR = os.path.dirname(os.path.abspath(__file__))
PROPOSALS_FILE = os.path.join(_DIR, "phase13_proposals.json")
MIN_TRADES_FOR_PROPOSAL = 20    # minimum OOS trades before proposing mutations
MAX_OPEN_PROPOSALS = 5          # max unreviewed proposals per strategy

RESEARCH_ENGINE_VERSION = "Research Engine v1.0 · Phase 13"


def _now_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _load_proposals() -> Dict[str, Any]:
    try:
        with open(PROPOSALS_FILE) as f:
            return json.load(f)
    except Exception:
        return {"proposals": [], "version": 1}


def _save_proposals(data: Dict[str, Any]) -> None:
    tmp = PROPOSALS_FILE + f".tmp.{os.getpid()}"
    try:
        with open(tmp, "w") as f:
            json.dump(data, f, indent=2, default=str)
        os.replace(tmp, PROPOSALS_FILE)
    except Exception:
        try:
            os.unlink(tmp)
        except Exception:
            pass


def _completed_paper_trades() -> List[Dict[str, Any]]:
    """Strict no-lookahead: only SELL rows with close timestamps."""
    try:
        from paper_trader import get_trades
        trades = list(get_trades())
    except Exception:
        return []
    return [
        t for t in trades
        if isinstance(t, dict)
        and t.get("action", "").upper() == "SELL"
        and bool(t.get("timestamp") or t.get("close_ts") or t.get("trade_date"))
    ]


def _group_by_strategy(trades: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for t in trades:
        sid = str(t.get("strategy_id") or t.get("strategy") or "unknown")
        grouped.setdefault(sid, []).append(t)
    return grouped


def _compute_stats(trades: List[Dict[str, Any]]) -> Dict[str, Any]:
    pnls = []
    for t in trades:
        pnl = None
        try:
            pnl = float(t.get("pnl") or t.get("realized_pnl") or 0)
        except (TypeError, ValueError):
            pass
        if pnl is None:
            qty = float(t.get("quantity", 0) or 0)
            buy_p = float(t.get("avg_buy_price") or t.get("entry_price") or 0)
            sell_p = float(t.get("price") or t.get("exit_price") or 0)
            if qty and buy_p and sell_p:
                pnl = (sell_p - buy_p) * qty
        if pnl is not None:
            pnls.append(pnl)

    if not pnls:
        return {"count": 0}

    n = len(pnls)
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    wr = len(wins) / n
    avg_win = sum(wins) / len(wins) if wins else 0.0
    avg_loss = abs(sum(losses) / len(losses)) if losses else 0.0
    exp = wr * avg_win - (1 - wr) * avg_loss
    gp = sum(wins); gl = abs(sum(losses))
    pf = gp / gl if gl > 0 else (1.5 if gp > 0 else 1.0)

    # Drawdown
    equity = 0.0
    peak = 0.0
    max_dd = 0.0
    for p in pnls:
        equity += p
        if equity > peak:
            peak = equity
        dd = (peak - equity) / max(1, abs(peak)) if peak > 0 else 0
        if dd > max_dd:
            max_dd = dd

    # Sharpe approximation (daily PnL std)
    import math
    mean_pnl = sum(pnls) / n
    variance = sum((p - mean_pnl) ** 2 for p in pnls) / max(1, n - 1)
    std_pnl = math.sqrt(variance) if variance > 0 else 1.0
    sharpe = (mean_pnl / std_pnl) * math.sqrt(252 / max(1, n)) if std_pnl > 0 else 0.0

    return {
        "count": n,
        "win_rate": round(wr, 4),
        "expectancy": round(exp, 2),
        "profit_factor": round(min(pf, 9.99), 2),
        "avg_win": round(avg_win, 2),
        "avg_loss": round(avg_loss, 2),
        "gross_profit": round(gp, 2),
        "gross_loss": round(gl, 2),
        "max_drawdown_pct": round(max_dd * 100, 2),
        "sharpe_approx": round(sharpe, 2),
        "total_pnl": round(sum(pnls), 2),
    }


def _propose_mutations(strategy_id: str, stats: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Suggest parameter mutations based on the strategy's OOS performance.
    All suggestions are hypothesis-only; none are applied automatically.
    """
    proposals = []
    wr = stats.get("win_rate", 0)
    pf = stats.get("profit_factor", 1.0)
    exp = stats.get("expectancy", 0)
    avg_win = stats.get("avg_win", 0)
    avg_loss = stats.get("avg_loss", 0)

    # Low win-rate but positive expectancy: tighten entry filter
    if wr < 0.45 and exp > 0:
        proposals.append({
            "mutation": "tighten_entry",
            "description": "Increase minimum RSI/confidence threshold by 5 points to reduce false entries",
            "expected_effect": "Higher win-rate at cost of fewer trades",
            "parameter": "entry_threshold",
            "suggested_change": "+5 points",
            "basis": f"WR={wr:.0%} below 45% with positive expectancy suggests too many marginal entries",
        })

    # Wide stops causing large average loss
    if avg_loss > avg_win * 0.8 and pf < 1.5:
        proposals.append({
            "mutation": "tighten_stops",
            "description": "Reduce ATR multiplier for stop-loss from 2× to 1.5× ATR",
            "expected_effect": "Smaller average losses, better profit factor",
            "parameter": "stop_atr_multiplier",
            "suggested_change": "2.0 → 1.5",
            "basis": f"avg_loss=₹{avg_loss:.0f} near avg_win=₹{avg_win:.0f}; PF={pf:.2f}",
        })

    # Good PF but low expectancy: increase target
    if pf >= 2.0 and exp < 50:
        proposals.append({
            "mutation": "extend_target",
            "description": "Extend profit target from 2× to 2.5× ATR when trend is strong",
            "expected_effect": "Higher expectancy per trade",
            "parameter": "target_atr_multiplier",
            "suggested_change": "2.0 → 2.5",
            "basis": f"Good PF={pf:.2f} but low expectancy=₹{exp:.0f} suggests premature exits",
        })

    # Very low win rate with negative expectancy: more confirmation
    if wr < 0.35 and exp < 0:
        proposals.append({
            "mutation": "add_volume_confirmation",
            "description": "Require volume ≥ 1.5× 20-day average before entry",
            "expected_effect": "Filter low-conviction breakouts",
            "parameter": "volume_confirmation_multiplier",
            "suggested_change": "none → 1.5×",
            "basis": f"WR={wr:.0%} with negative exp=₹{exp:.0f} — needs stronger participation confirmation",
        })

    return proposals


def generate_evolution_proposals(force: bool = False) -> Dict[str, Any]:
    """
    Analyse completed paper trades per strategy and generate mutation proposals.
    Requires ≥20 OOS trades per strategy. Never auto-promotes.
    """
    completed = _completed_paper_trades()
    grouped = _group_by_strategy(completed)

    stored = _load_proposals()
    existing_ids = {p["proposal_id"] for p in stored.get("proposals", [])}

    new_proposals = []
    strategy_summaries = []

    for sid, trades in grouped.items():
        stats = _compute_stats(trades)
        n = stats.get("count", 0)
        ev = (
            "validated" if n >= 100 else "strong" if n >= 50 else
            "moderate" if n >= 20 else "low" if n >= 10 else
            "very_low" if n >= 3 else "insufficient"
        )
        strategy_summaries.append({
            "strategy_id": sid,
            "completed_trades": n,
            "evidence": ev,
            "stats": stats,
            "eligible_for_proposals": n >= MIN_TRADES_FOR_PROPOSAL,
        })

        if n < MIN_TRADES_FOR_PROPOSAL:
            continue

        # Check how many open proposals this strategy already has
        open_count = sum(
            1 for p in stored.get("proposals", [])
            if p.get("strategy_id") == sid and p.get("status") == "PENDING_APPROVAL"
        )
        if open_count >= MAX_OPEN_PROPOSALS:
            continue

        mutations = _propose_mutations(sid, stats)
        for mut in mutations:
            pid = str(uuid.uuid4())[:8]
            proposal = {
                "proposal_id": pid,
                "strategy_id": sid,
                "status": "PENDING_APPROVAL",
                "created_at": _now_str(),
                "evidence": ev,
                "oos_trade_count": n,
                "stats_snapshot": stats,
                "mutation": mut,
                "approval_required": True,
                "auto_promoted": False,
                "approved_at": None,
                "rejected_at": None,
                "approved_by": None,
                "notes": "Proposal only — requires explicit human review and approval before any use.",
            }
            new_proposals.append(proposal)

    stored.setdefault("proposals", []).extend(new_proposals)
    stored["last_generated"] = _now_str()
    stored["generator_version"] = RESEARCH_ENGINE_VERSION
    _save_proposals(stored)

    return {
        "success": True,
        "phase": 13,
        "label": "PAPER / RESEARCH ONLY",
        "generated_at": _now_str(),
        "completed_trade_count": len(completed),
        "strategy_summaries": strategy_summaries,
        "new_proposals_generated": len(new_proposals),
        "total_proposals": len(stored["proposals"]),
        "pending_approval": sum(1 for p in stored["proposals"] if p.get("status") == "PENDING_APPROVAL"),
        "proposals": new_proposals,
        "note": "All proposals require explicit human approval. No mutations are applied automatically.",
    }


def list_proposals(status: Optional[str] = None) -> Dict[str, Any]:
    stored = _load_proposals()
    proposals = stored.get("proposals", [])
    if status:
        proposals = [p for p in proposals if p.get("status") == status]
    return {
        "success": True,
        "proposals": proposals,
        "total": len(proposals),
        "pending": sum(1 for p in stored.get("proposals", []) if p.get("status") == "PENDING_APPROVAL"),
        "label": "PAPER / RESEARCH ONLY",
        "note": "No proposal is auto-applied. Approval by human required.",
    }


def review_proposal(proposal_id: str, action: str, notes: str = "") -> Dict[str, Any]:
    """
    action: APPROVE | REJECT
    Note: Even APPROVE only marks the proposal as approved for FUTURE use;
    it never auto-executes trades or modifies the running strategy.
    """
    if action not in ("APPROVE", "REJECT"):
        return {"success": False, "error": "action must be APPROVE or REJECT"}

    stored = _load_proposals()
    for p in stored.get("proposals", []):
        if p.get("proposal_id") == proposal_id:
            if p.get("status") != "PENDING_APPROVAL":
                return {"success": False, "error": f"Proposal already {p.get('status')}"}
            p["status"] = "APPROVED" if action == "APPROVE" else "REJECTED"
            p["approved_at" if action == "APPROVE" else "rejected_at"] = _now_str()
            p["approved_by"] = "human_operator"
            p["notes"] = notes or p.get("notes", "")
            p["auto_promoted"] = False  # always false
            _save_proposals(stored)
            return {
                "success": True,
                "proposal_id": proposal_id,
                "new_status": p["status"],
                "warning": (
                    "Approval recorded for future consideration only. "
                    "No live trading order or strategy change was applied. "
                    "PAPER TRADING ONLY."
                ) if action == "APPROVE" else None,
            }
    return {"success": False, "error": f"Proposal {proposal_id} not found"}
