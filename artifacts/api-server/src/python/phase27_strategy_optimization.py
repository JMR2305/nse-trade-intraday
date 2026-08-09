"""
phase27_strategy_optimization.py — Phase 27D: Strategy Optimization (READ-ONLY).

Historical optimization report built ONLY from canonical sources:
  • closed paper trades — paper_trading_validation.validation_collector
    .collect_all_trade_records() (FIFO over the phase20 ledger),
  • the canonical scan snapshot (gate flags per symbol),
  • phase24 missed-opportunity analysis (reused, never recomputed),
  • existing advisory recommendation engines (5D.3 strategy intelligence,
    phase24 learning) — aggregated, not duplicated.

Honesty rules
  • MIN_EVIDENCE = 5 closed trades per strategy; below that a row is marked
    low_evidence and classifications become INSUFFICIENT_EVIDENCE.
  • Recommendations are ADVISORY-ONLY; nothing here mutates thresholds.

ADVISORY-ONLY · READ-ONLY · never touches trading state.
"""
from __future__ import annotations

import math
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

MIN_EVIDENCE = 5
GATES = {
    "gate_price": "Price gate",
    "gate_rr": "Risk/Reward gate",
    "gate_volume": "Volume gate",
    "gate_data_quality": "Data-quality gate",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _records() -> List[Dict[str, Any]]:
    try:
        from paper_trading_validation.validation_collector import collect_all_trade_records
        return [r.to_dict() for r in collect_all_trade_records()]
    except Exception:
        return []


def _initial_capital() -> float:
    try:
        from portfolio_store import INITIAL_CAPITAL
        return float(INITIAL_CAPITAL)
    except Exception:
        return 0.0


# ── Per-strategy metric contract ─────────────────────────────────────────────

def _strategy_metrics(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    cap = _initial_capital()
    by: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for r in rows:
        by[r.get("strategy") or "unknown"].append(r)

    out = []
    for strat, rs in sorted(by.items()):
        rs = sorted(rs, key=lambda r: str(r.get("timestamp") or ""))
        pnls = [float(r.get("pnl") or 0) for r in rs]
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p < 0]
        gross_win, gross_loss = sum(wins), -sum(losses)
        # max drawdown on the cumulative per-strategy PnL curve
        cum = peak = mdd = 0.0
        for p in pnls:
            cum += p
            peak = max(peak, cum)
            mdd = max(mdd, peak - cum)
        pcts = [float(r.get("pnl_pct") or 0) for r in rs]
        mean = sum(pcts) / len(pcts) if pcts else 0.0
        std = math.sqrt(sum((x - mean) ** 2 for x in pcts) / len(pcts)) if pcts else 0.0
        holds = [float(r.get("holding_time_minutes") or 0) for r in rs]
        deploys = [float(r.get("entry_price") or 0) * int(r.get("quantity") or 0)
                   for r in rs]
        out.append({
            "strategy": strat,
            "trades": len(rs),
            "wins": len(wins),
            "losses": len(losses),
            "win_pct": round(len(wins) / len(rs) * 100, 1) if rs else 0.0,
            "avg_profit": round(sum(wins) / len(wins), 2) if wins else None,
            "avg_loss": round(sum(losses) / len(losses), 2) if losses else None,
            "profit_factor": round(gross_win / gross_loss, 2) if gross_loss > 0 else None,
            "max_drawdown": round(mdd, 2),
            "sharpe": round(mean / std, 2) if std > 0 else None,
            "avg_hold_minutes": round(sum(holds) / len(holds), 1) if holds else None,
            "capital_utilisation_pct":
                round(sum(deploys) / len(deploys) / cap * 100, 1)
                if deploys and cap > 0 else None,
            "net_pnl": round(sum(pnls), 2),
            "low_evidence": len(rs) < MIN_EVIDENCE,
        })
    return out


# ── Filter / gate analysis ───────────────────────────────────────────────────

def _scan_snapshot() -> tuple[List[Dict[str, Any]], Any]:
    try:
        from scan_state_store import load_latest_snapshot
        snap = load_latest_snapshot() or {}
        return list(snap.get("recommendations") or []), snap.get("scan_id")
    except Exception:
        return [], None


def _missed_opps() -> List[Dict[str, Any]]:
    """Reuse phase24's stored missed-opportunity analyses (never recompute).

    phase24_store rows wrap the analysis in `record`:
      record.rejected_by_gates: [gate names], record.rejection_correct: bool,
      record.should_have_allowed: bool.
    """
    try:
        from phase24_store import list_missed_opps
        rows = list(list_missed_opps() or [])
        return [dict(r.get("record") or {}, symbol=r.get("symbol"))
                for r in rows]
    except Exception:
        return []


def _gate_failed(rec: Dict[str, Any], key: str) -> bool:
    """Canonical gate shape is {"passed": bool, "reason": str}."""
    gate = rec.get(key)
    if isinstance(gate, dict):
        return gate.get("passed") is False
    return gate is False


# phase24 missed-opp records name the phase20 ENTRY gates that fired
# (e.g. "min_risk_reward"), not the 4 scan-gate keys. Only defensible
# mappings are aliased; unmapped entry gates surface honestly in the
# separate entry_gate_outcomes breakdown instead of being force-fitted.
GATE_ALIASES: Dict[str, frozenset] = {
    "gate_price": frozenset({"valid_stop_loss"}),
    "gate_rr": frozenset({"min_risk_reward"}),
    "gate_volume": frozenset({"min_liquidity"}),
    "gate_data_quality": frozenset({
        "no_fallback_data", "quote_available", "scan_fresh",
        "snapshot_consistency", "research_available"}),
}


def _filter_analysis(scan_rows: List[Dict[str, Any]],
                     current_scan_id: Any = None) -> Dict[str, Any]:
    missed = _missed_opps()
    missed_by_gate: Dict[str, int] = defaultdict(int)
    good_by_gate: Dict[str, int] = defaultdict(int)
    # Honest per-entry-gate outcome breakdown (raw phase20 gate names),
    # over the WHOLE evidence store — clearly labelled as historical.
    entry_gates: Dict[str, Dict[str, int]] = defaultdict(
        lambda: {"rejections": 0, "good_rejections": 0, "bad_rejections": 0})
    # Symbols each scan gate rejects on the CURRENT snapshot (for the join).
    current_reject: Dict[str, set] = {
        key: {str(r.get("symbol")) for r in scan_rows if _gate_failed(r, key)}
        for key in GATES
    }
    for m in missed:
        gates = m.get("rejected_by_gates") or []
        gates_l = [str(g).lower() for g in gates]
        good = m.get("rejection_correct") is True
        bad = m.get("should_have_allowed") is True
        for g in gates_l:
            eg = entry_gates[g]
            eg["rejections"] += 1
            if bad:
                eg["bad_rejections"] += 1
            elif good:
                eg["good_rejections"] += 1
        # The 4 scan-filter columns only count evidence that provably belongs
        # to the current snapshot: same scan_id AND the symbol actually fails
        # that scan gate on the current rows. Everything else stays visible
        # in entry_gate_outcomes instead of being force-fitted.
        if current_scan_id is None or m.get("scan_id") != current_scan_id:
            continue
        sym = str(m.get("symbol"))
        for key, label in GATES.items():
            aliases = GATE_ALIASES.get(key, frozenset())
            hit = any(g in aliases or key == g or key.replace("gate_", "") == g
                      or label.lower() == g for g in gates_l)
            if not hit or sym not in current_reject[key]:
                continue
            if bad:
                missed_by_gate[key] += 1
            elif good:
                good_by_gate[key] += 1

    # Symbols whose data fetch failed trip every gate at once; attributing
    # those to individual filters would make all gates look identical
    # (false "duplicate" classification). Report them separately.
    data_error_symbols = [str(r.get("symbol")) for r in scan_rows if r.get("error")]
    clean_rows = [r for r in scan_rows if not r.get("error")]

    filters, reject_sets = [], {}
    n = len(clean_rows)
    for key, label in GATES.items():
        rejected = [str(r.get("symbol")) for r in clean_rows if _gate_failed(r, key)]
        reject_sets[key] = frozenset(rejected)
        good, bad = good_by_gate.get(key, 0), missed_by_gate.get(key, 0)
        has_outcomes = (good + bad) > 0
        filters.append({
            "filter": label,
            "times_triggered": len(rejected),
            "symbols_rejected": rejected,
            "good_rejections": good if has_outcomes else None,
            "bad_rejections": bad if has_outcomes else None,
            "missed_opportunities": bad if has_outcomes else None,
            "outcome_evidence": "phase24 missed-opportunity store"
                if has_outcomes else "INSUFFICIENT_EVIDENCE",
        })

    # taxonomy — conservative / aggressive / duplicate / unused
    for f in filters:
        key = next(k for k, v in GATES.items() if v == f["filter"])
        trig = f["times_triggered"]
        if trig == 0:
            cls = "UNUSED_ON_LATEST_SCAN"
        elif n and trig / n > 0.5 and (f["bad_rejections"] or 0) > (f["good_rejections"] or 0):
            cls = "OVERLY_CONSERVATIVE"
        elif n and trig / n > 0.5:
            cls = "OVERLY_CONSERVATIVE" if f["outcome_evidence"] != "INSUFFICIENT_EVIDENCE" \
                else "HIGH_REJECTION_RATE_INSUFFICIENT_EVIDENCE"
        elif (f["good_rejections"] is None):
            cls = "INSUFFICIENT_EVIDENCE"
        elif (f["bad_rejections"] or 0) == 0 and (f["good_rejections"] or 0) > 0:
            cls = "EFFECTIVE"
        else:
            cls = "MIXED"
        dup_of = [GATES[k2] for k2, s2 in reject_sets.items()
                  if k2 != key and s2 and s2 == reject_sets[key]]
        if dup_of:
            f["duplicate_of"] = dup_of
            cls = "DUPLICATE_REJECTION_SET"
        f["classification"] = cls

    return {
        "scan_universe": len(scan_rows),
        "data_error_symbols": data_error_symbols,
        "filters": filters,
        "entry_gate_outcomes": dict(sorted(entry_gates.items())),
        "threshold_domains": {
            "confidence_thresholds": "see recommendations (phase21/phase24 advisory engines)",
            "risk_thresholds": "risk gate + heat, canonical scan",
            "sector_exposure": "portfolio sector_exposures (canonical snapshot)",
            "liquidity_filters": "volume gate (volume_ratio)",
            "news_filters": "not implemented in pipeline — honestly N/A",
            "volatility_filters": "regime gating (canonical scan regime)",
        },
    }


# ── Recommendations aggregation (advisory-only) ──────────────────────────────

def _recommendations() -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    try:
        from strategy_intelligence.api import get_recommendations_api
        for r in (get_recommendations_api() or {}).get("recommendations") or []:
            out.append({"source": "strategy_intelligence (5D.3)", **r})
    except Exception:
        pass
    try:
        from phase24_store import list_recommendations
        for r in list_recommendations() or []:
            out.append({"source": "phase24 learning engine", **r})
    except Exception:
        pass
    for r in out:
        r["advisory_only"] = True
    return out


# ── Dashboards: periods, heatmaps, distributions ─────────────────────────────

def _period_perf(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    def bucket(fmt: str) -> List[Dict[str, Any]]:
        agg: Dict[str, List[float]] = defaultdict(list)
        for r in rows:
            ts = str(r.get("timestamp") or "")[:10]
            try:
                d = datetime.fromisoformat(ts)
            except Exception:
                continue
            if fmt == "daily":
                k = ts
            elif fmt == "weekly":
                iso = d.isocalendar()
                k = f"{iso[0]}-W{iso[1]:02d}"
            else:
                k = ts[:7]
            agg[k].append(float(r.get("pnl") or 0))
        return [{"period": k, "trades": len(v), "pnl": round(sum(v), 2),
                 "win_pct": round(sum(1 for x in v if x > 0) / len(v) * 100, 1)}
                for k, v in sorted(agg.items())]
    return {"daily": bucket("daily"), "weekly": bucket("weekly"),
            "monthly": bucket("monthly")}


def _heatmaps(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    def matrix(kx, ky) -> List[Dict[str, Any]]:
        agg: Dict[tuple, List[float]] = defaultdict(list)
        for r in rows:
            agg[(str(r.get(kx) or "unknown"), str(r.get(ky) or "unknown"))] \
                .append(float(r.get("pnl") or 0))
        return [{"x": x, "y": y, "trades": len(v), "pnl": round(sum(v), 2)}
                for (x, y), v in sorted(agg.items())]

    weekday: Dict[tuple, List[float]] = defaultdict(list)
    for r in rows:
        try:
            d = datetime.fromisoformat(str(r.get("timestamp"))[:19])
            weekday[(d.strftime("%a"), str(r.get("strategy") or "unknown"))] \
                .append(float(r.get("pnl") or 0))
        except Exception:
            continue
    return {
        "sector_x_regime": matrix("sector", "market_regime"),
        "strategy_x_regime": matrix("strategy", "market_regime"),
        "weekday_x_strategy": [
            {"x": x, "y": y, "trades": len(v), "pnl": round(sum(v), 2)}
            for (x, y), v in sorted(weekday.items())],
    }


def _distributions(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    def hist(key: str, edges: List[float]) -> List[Dict[str, Any]]:
        buckets = [{"range": f"{edges[i]}–{edges[i+1]}", "trades": 0,
                    "wins": 0, "pnl": 0.0} for i in range(len(edges) - 1)]
        n_valued = 0
        for r in rows:
            v = r.get(key)
            if v is None:
                continue
            v = float(v)
            n_valued += 1
            for i in range(len(edges) - 1):
                if edges[i] <= v < edges[i + 1] or (i == len(edges) - 2 and v == edges[-1]):
                    b = buckets[i]
                    b["trades"] += 1
                    b["pnl"] = round(b["pnl"] + float(r.get("pnl") or 0), 2)
                    if float(r.get("pnl") or 0) > 0:
                        b["wins"] += 1
                    break
        return buckets if n_valued else []
    return {
        "confidence": hist("ai_confidence", [0, 40, 50, 60, 70, 80, 90, 100]),
        "risk_score": hist("risk_score", [0, 2, 4, 6, 8, 10]),
    }


# ── Entry point ──────────────────────────────────────────────────────────────

def strategy_optimization_report() -> Dict[str, Any]:
    rows = _records()
    scan_rows, scan_id = _scan_snapshot()
    return {
        "ok": True,
        "advisory_only": True,
        "read_only": True,
        "generated_at": _now(),
        "evidence": {
            "closed_trades": len(rows),
            "min_evidence_per_strategy": MIN_EVIDENCE,
            "sufficient": len(rows) >= MIN_EVIDENCE,
        },
        "strategies": _strategy_metrics(rows),
        "filter_analysis": _filter_analysis(scan_rows, scan_id),
        "recommendations": _recommendations(),
        "period_performance": _period_perf(rows),
        "heatmaps": _heatmaps(rows),
        "distributions": _distributions(rows),
        "note": "Advisory-only. No threshold is ever modified automatically.",
    }
