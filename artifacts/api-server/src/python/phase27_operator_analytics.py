"""
phase27_operator_analytics.py — Phase 27E: Operator Analytics (READ-ONLY).

Explains how the platform has been behaving over time — pipeline funnel,
stage timing, rejections, decisions, risk interventions — built STRICTLY on
canonical sources:

  • Pipeline Event Store (pipeline_events)  — rejections/decisions/timings,
  • unified replay snapshot (replay_engine.build_replay) — the ONLY source
    of per-stage in/out/rejected/pending counts,
  • canonical scan snapshot — symbol/sector/regime splits,
  • replay session list — session summary + cross-scan trends
    (synthetic "demo" sessions are excluded — never treated as evidence).

Performance/time-of-day breakdowns are served by the existing
paper_analytics endpoints — this module NEVER recomputes them.

Honesty rules
  • Every canonical source reports its own availability/error state in the
    response `sources` map — a read failure is surfaced as UNAVAILABLE,
    never silently rendered as "no data".
  • Bounded event fetches report `truncated=True` when the limit was hit,
    so counts are labelled partial instead of definitive.
  • Stage timing needs >= MIN_TIMING_SAMPLES gap samples, otherwise the
    stage explicitly reports insufficient_telemetry — never inferred.
  • Rejection accounting separates rejected EVENTS from reason-code
    OCCURRENCES (one event can fail several gates); percentages are
    explicitly shares of reason occurrences.
  • Aggregations are scan-scoped (bounded event fetches per scan) — no
    full-event-history scans.

ADVISORY-ONLY · READ-ONLY · never touches trading state.
"""
from __future__ import annotations

import statistics
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

MIN_TIMING_SAMPLES = 3
TREND_SCAN_WINDOW = 5          # scans (incl. current) used for trends
EVENTS_PER_SCAN_LIMIT = 2000   # bounded per-scan event fetch
TREND_EVENTS_LIMIT = 1000

ADVISORY = ("Phase 27E Operator Analytics — read-only aggregation of "
            "canonical stores. PAPER TRADING / RESEARCH ONLY.")

# Rejection display groups keyed by canonical event_type. The raw reason
# code from the event payload is ALWAYS preserved next to the group.
REJECTION_STAGE_GROUPS = {
    "SYMBOL_REJECTED": "Scanner / market data",
    "STRATEGY_REJECTED": "Strategy selection",
    "PRECHECK_REJECTED": "Portfolio pre-check",
    "RISK_REJECTED": "Risk gates",
    "ORDER_REJECTED": "Execution",
    "ORDER_CANCELLED": "Execution",
    "SCAN_FAILED": "Scan lifecycle",
}

DECISION_EVENT_TYPES = {
    "BUY_GENERATED": "BUY",
    "SELL_GENERATED": "SELL",
    "WATCH_GENERATED": "WATCH",
    "IGNORE_GENERATED": "IGNORE",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_ts(ts: Any) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except Exception:
        return None


# ── Canonical source access — every reader reports availability ─────────────
# Each returns (data, source_state) where source_state is
# {"available": bool, "error": str|None, ...extras}.

def _replay(scan_id: str) -> Dict[str, Any]:
    from replay_engine import build_replay
    return build_replay(scan_id) or {}


def _sessions(limit: int = 20) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Replay sessions, EXCLUDING synthetic demo sessions."""
    try:
        from replay_engine import get_replay_sessions
        raw = list((get_replay_sessions() or {}).get("sessions") or [])
        real = [s for s in raw
                if s.get("source") != "demo" and s.get("scan_id") != "demo"]
        state = {"available": True, "error": None,
                 "demo_excluded": len(raw) - len(real)}
        return real[:limit], state
    except Exception as exc:
        return [], {"available": False, "error": str(exc)[:200],
                    "demo_excluded": 0}


def _scan_events(scan_id: Optional[str],
                 limit: int = EVENTS_PER_SCAN_LIMIT
                 ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """One bounded event fetch for a single scan (canonical event store).

    `truncated` means the fetch hit the limit — downstream counts are then
    partial, never definitive.
    """
    if not scan_id:
        return [], {"available": False, "error": "no scan_id",
                    "truncated": False, "limit": limit}
    try:
        import pipeline_events
        events = pipeline_events.query_events(scan_id=scan_id, limit=limit)
        return events, {"available": True, "error": None,
                        "truncated": len(events) >= limit, "limit": limit}
    except Exception as exc:
        return [], {"available": False, "error": str(exc)[:200],
                    "truncated": False, "limit": limit}


def _snapshot_rows() -> Tuple[List[Dict[str, Any]], Any, Any, Dict[str, Any]]:
    try:
        from scan_state_store import load_latest_snapshot
        snap = load_latest_snapshot() or {}
        return (list(snap.get("recommendations") or []), snap.get("scan_id"),
                snap.get("snapshot_ts"), {"available": True, "error": None})
    except Exception as exc:
        return [], None, None, {"available": False, "error": str(exc)[:200]}


# ── Rejection reason extraction (canonical payload keys only) ────────────────

def _rejection_reasons(ev: Dict[str, Any]) -> List[str]:
    """Raw canonical reason codes for one rejection event.

    SYMBOL_REJECTED  → payload.error
    RISK_REJECTED    → payload.failed_gates (dict keys or list)
    PRECHECK_REJECTED→ payload.reasons (list) [+ blocking_limit]
    others           → payload.reason/error if present, else the event_type.
    """
    p = ev.get("payload") or {}
    et = ev.get("event_type")
    if et == "RISK_REJECTED":
        fg = p.get("failed_gates")
        if isinstance(fg, dict) and fg:
            return [str(k) for k in fg.keys()]
        if isinstance(fg, list) and fg:
            return [str(g) for g in fg]
    if et == "PRECHECK_REJECTED":
        rs = p.get("reasons")
        if isinstance(rs, list) and rs:
            return [str(r) for r in rs]
        if p.get("blocking_limit"):
            return [str(p["blocking_limit"])]
    for key in ("error", "reason"):
        if p.get(key):
            return [str(p[key])]
    return [str(et or "UNKNOWN")]


def _aggregate_rejections(events: List[Dict[str, Any]],
                          events_state: Optional[Dict[str, Any]] = None
                          ) -> Dict[str, Any]:
    """Rejected EVENTS and reason-code OCCURRENCES are counted separately:
    one event may carry several failed gates. `pct` is explicitly the share
    of reason occurrences, never of events."""
    try:
        from pipeline_events import REJECTED_EVENT_TYPES
    except Exception:
        REJECTED_EVENT_TYPES = frozenset(REJECTION_STAGE_GROUPS)
    agg: Dict[tuple, Dict[str, Any]] = {}
    rejected_events = 0
    occurrences = 0
    for ev in events:
        et = ev.get("event_type")
        if et not in REJECTED_EVENT_TYPES:
            continue
        rejected_events += 1
        for code in _rejection_reasons(ev):
            occurrences += 1
            k = (et, code)
            row = agg.setdefault(k, {
                "event_type": et,
                "group": REJECTION_STAGE_GROUPS.get(et, et),
                "reason_code": code,          # raw canonical code, verbatim
                "count": 0, "symbols": set(), "event_ids": [],
            })
            row["count"] += 1
            if ev.get("symbol"):
                row["symbols"].add(ev["symbol"])
            if len(row["event_ids"]) < 50:
                row["event_ids"].append(ev.get("id"))
    rows = []
    for row in agg.values():
        rows.append({
            **row,
            "symbols": sorted(row["symbols"]),
            "event_ids": sorted(row["event_ids"], key=lambda i: (i is None, i)),
            "pct_of_occurrences": round(row["count"] / occurrences * 100, 1)
            if occurrences else 0.0,
        })
    rows.sort(key=lambda r: (-r["count"], r["reason_code"]))
    st = events_state or {"available": True, "truncated": False}
    return {
        "rejected_events": rejected_events,
        "reason_occurrences": occurrences,
        "reasons": rows,
        "evidence": _evidence_state(st, rejected_events > 0),
        "source": "pipeline_events (canonical reason codes; pct = share of "
                  "reason occurrences)",
    }


def _evidence_state(events_state: Dict[str, Any], has_rows: bool) -> str:
    """UNAVAILABLE (source failed) / PARTIAL (fetch truncated) /
    VERIFIED_EMPTY (source read OK, nothing there) / OK."""
    if not events_state.get("available", False):
        return "SOURCE_UNAVAILABLE"
    if events_state.get("truncated"):
        return "PARTIAL"
    return "OK" if has_rows else "VERIFIED_EMPTY"


# ── Decision distribution ────────────────────────────────────────────────────

def _normalise_action(action: Any) -> str:
    return str(action or "UNKNOWN").upper().replace("_", " ").strip()


def _decision_distribution(events: List[Dict[str, Any]],
                           snap_rows: List[Dict[str, Any]],
                           snap_scan_id: Any,
                           scan_id: Any,
                           events_state: Optional[Dict[str, Any]] = None
                           ) -> Dict[str, Any]:
    counts: Dict[str, int] = defaultdict(int)
    for ev in events:
        label = DECISION_EVENT_TYPES.get(str(ev.get("event_type")))
        if label:
            counts[label] += 1
    ev_total = sum(counts.values())

    # symbol/sector/regime splits come from the canonical snapshot — only
    # when it belongs to the same scan (never mixed silently).
    splits_available = bool(snap_rows) and snap_scan_id == scan_id
    by_action: Dict[str, int] = defaultdict(int)
    by_sector: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
    regime = None
    if splits_available:
        for r in snap_rows:
            act = _normalise_action(r.get("final_action"))
            by_action[act] += 1
            sector = str(r.get("sector") or "Unknown")
            by_sector[sector][act] += 1
            regime = regime or r.get("market_regime") or r.get("regime")
    total_snap = sum(by_action.values())
    st = events_state or {"available": True, "truncated": False}
    return {
        "source": "pipeline_events decision events + canonical snapshot",
        "event_decisions": {
            "counts": dict(counts), "total": ev_total,
            "evidence": _evidence_state(st, ev_total > 0),
            "pct": {k: round(v / ev_total * 100, 1)
                    for k, v in counts.items()} if ev_total else {},
        },
        "snapshot_distribution": {
            "available": splits_available,
            "note": None if splits_available else
            "canonical snapshot is from a different scan — splits omitted",
            "actions": [{"action": a, "count": c,
                         "pct": round(c / total_snap * 100, 1)}
                        for a, c in sorted(by_action.items(),
                                           key=lambda x: -x[1])],
            "by_sector": [{"sector": s, "actions": dict(acts)}
                          for s, acts in sorted(by_sector.items())],
            "regime": regime,
        },
    }


# ── Risk intervention ────────────────────────────────────────────────────────

def _risk_interventions(events: List[Dict[str, Any]],
                        events_state: Optional[Dict[str, Any]] = None
                        ) -> Dict[str, Any]:
    st = events_state or {"available": True, "truncated": False}
    out: Dict[str, Any] = {}
    for stage, appr, rej in (
            ("risk", "RISK_APPROVED", "RISK_REJECTED"),
            ("portfolio_precheck", "PRECHECK_APPROVED", "PRECHECK_REJECTED")):
        approved, blocked = 0, 0
        reasons: Dict[str, Dict[str, Any]] = defaultdict(lambda: {
            "count": 0, "symbols": set(), "event_ids": []})
        for ev in events:
            et = ev.get("event_type")
            if et == appr:
                approved += 1
            elif et == rej:
                blocked += 1
                for code in _rejection_reasons(ev):
                    row = reasons[code]
                    row["count"] += 1
                    if ev.get("symbol"):
                        row["symbols"].add(ev["symbol"])
                    if len(row["event_ids"]) < 50:
                        row["event_ids"].append(ev.get("id"))
        candidates = approved + blocked
        out[stage] = {
            "candidates": candidates,
            "approved": approved,
            "blocked": blocked,
            "block_rate_pct": round(blocked / candidates * 100, 1)
            if candidates else None,
            "reasons": sorted(
                [{"reason_code": c, "count": r["count"],
                  "symbols": sorted(r["symbols"]),
                  "event_ids": r["event_ids"]}
                 for c, r in reasons.items()],
                key=lambda r: -r["count"]),
            "evidence": _evidence_state(st, candidates > 0),
        }
    out["source"] = "pipeline_events PRECHECK_*/RISK_* (canonical reasons)"
    return out


# ── Funnel + stage timing ────────────────────────────────────────────────────

def _stage_timing(events: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """avg/median/p95 per-symbol gap per stage, from the SAME gap definition
    stage_summary uses (symbol's event vs its previous event in the scan).
    p95 is nearest-rank on the sorted sample (index round(0.95*(n-1)))."""
    per_symbol: Dict[str, List[tuple]] = defaultdict(list)
    for ev in events:
        if ev.get("symbol") and ev.get("ts"):
            per_symbol[ev["symbol"]].append(
                (str(ev["ts"]), int(ev.get("id") or 0), str(ev.get("stage"))))
    gaps: Dict[str, List[float]] = defaultdict(list)
    for seq in per_symbol.values():
        seq.sort(key=lambda p: (p[0], p[1]))
        for (prev_ts, _i, _s), (ts, _j, stage) in zip(seq, seq[1:]):
            a, b = _parse_ts(prev_ts), _parse_ts(ts)
            if a and b:
                gaps[stage].append((b - a).total_seconds() * 1000)
    out: Dict[str, Dict[str, Any]] = {}
    for stage, vals in gaps.items():
        if len(vals) < MIN_TIMING_SAMPLES:
            out[stage] = {"insufficient_telemetry": True,
                          "samples": len(vals)}
            continue
        vals.sort()
        p95_idx = max(0, int(round(0.95 * (len(vals) - 1))))
        out[stage] = {
            "insufficient_telemetry": False,
            "samples": len(vals),
            "avg_ms": round(sum(vals) / len(vals), 1),
            "median_ms": round(statistics.median(vals), 1),
            "p95_ms": round(vals[p95_idx], 1),
        }
    return out


# Map replay stage ids → pipeline_events stage names for the timing overlay.
REPLAY_TO_EVENT_STAGE = {
    "supervisor": "SUPERVISOR", "market_data": "SCANNER",
    "research": "RESEARCH", "market_intelligence": "MARKET_INTELLIGENCE",
    "monitoring": "MONITORING", "strategy": "STRATEGY",
    "portfolio_precheck": "PORTFOLIO_PRECHECK", "risk": "RISK",
    "ai_decision": "AI_DECISION", "execution": "EXECUTION",
}


def _funnel(replay: Dict[str, Any],
            events: List[Dict[str, Any]]) -> Dict[str, Any]:
    timing = _stage_timing(events)
    stages_out = []
    for s in (replay.get("stages") or []):
        sin = int(s.get("stocks_in") or 0)
        sout = int(s.get("stocks_out") or 0)
        ev_stage = REPLAY_TO_EVENT_STAGE.get(str(s.get("id")))
        t = timing.get(ev_stage or "", None)
        stages_out.append({
            "id": s.get("id"), "label": s.get("label"),
            "order": s.get("order"),
            "stocks_in": sin, "stocks_out": sout,
            "rejected": s.get("rejected"), "pending": s.get("pending"),
            "cancelled": s.get("cancelled"),
            "conversion_pct": round(sout / sin * 100, 1) if sin else None,
            "timing": t if t is not None else
            {"insufficient_telemetry": True, "samples": 0},
        })
    return {
        "source": "unified replay snapshot (counts) + pipeline_events (timing)",
        "stages": stages_out,
    }


# ── Cross-scan trends ────────────────────────────────────────────────────────

def _trends(current_scan_id: Any,
            sessions: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Per-scan rejection/decision totals over the last TREND_SCAN_WINDOW
    real replay sessions (bounded per-scan event fetches — never full
    history; demo sessions already excluded upstream)."""
    points = []
    for sess in sessions[:TREND_SCAN_WINDOW]:
        sid = sess.get("scan_id")
        evs, st = _scan_events(sid, limit=TREND_EVENTS_LIMIT)
        rej = _aggregate_rejections(evs, st)
        dec: Dict[str, int] = defaultdict(int)
        for ev in evs:
            label = DECISION_EVENT_TYPES.get(str(ev.get("event_type")))
            if label:
                dec[label] += 1
        by_reason: Dict[str, int] = defaultdict(int)
        for r in rej["reasons"]:
            by_reason[r["reason_code"]] += r["count"]
        points.append({
            "scan_id": sid,
            "snapshot_ts": sess.get("snapshot_ts"),
            "is_current": sid == current_scan_id,
            "rejected_events": rej["rejected_events"],
            "rejections_by_reason": dict(by_reason),
            "decisions": dict(dec),
            "evidence": _evidence_state(st, bool(evs)),
        })
    return {"window_scans": TREND_SCAN_WINDOW, "points": points,
            "source": "replay sessions + per-scan pipeline_events",
            "note": "INSUFFICIENT DATA" if len(points) < 2 else None}


# ── Entry point ──────────────────────────────────────────────────────────────

def operator_analytics_report(scan_id: Optional[str] = None) -> Dict[str, Any]:
    snap_rows, snap_scan_id, snap_ts, snap_state = _snapshot_rows()
    target = scan_id or snap_scan_id
    replay_state: Dict[str, Any] = {"available": True, "error": None}
    try:
        replay = _replay(str(target) if target else "latest")
        if replay.get("error"):
            replay_state = {"available": False,
                            "error": str(replay["error"])[:200]}
    except Exception as exc:
        replay, replay_state = {}, {"available": False,
                                    "error": str(exc)[:200]}
    replay_scan_id = replay.get("scan_id") \
        or (replay.get("session") or {}).get("scan_id") or target
    events, events_state = _scan_events(replay_scan_id)
    sessions, sessions_state = _sessions()

    return {
        "ok": True,
        "advisory_only": True,
        "read_only": True,
        "generated_at": _now(),
        "note": ADVISORY,
        "scan_id": replay_scan_id,
        "snapshot_ts": snap_ts if snap_scan_id == replay_scan_id else None,
        "event_count": len(events),
        # Per-source availability — the UI must distinguish "source down"
        # from "verified empty" and flag truncated (partial) fetches.
        "sources": {
            "replay": replay_state,
            "pipeline_events": events_state,
            "snapshot": snap_state,
            "sessions": sessions_state,
        },
        "session_summary": {
            "source": "replay sessions (canonical; demo sessions excluded)",
            "available": sessions_state["available"],
            "error": sessions_state["error"],
            "sessions": sessions,
        },
        "funnel": _funnel(replay, events),
        "rejections": _aggregate_rejections(events, events_state),
        "decisions": _decision_distribution(events, snap_rows, snap_scan_id,
                                            replay_scan_id, events_state),
        "risk_interventions": _risk_interventions(events, events_state),
        "trends": _trends(replay_scan_id, sessions),
        "performance_note": ("Performance and time-of-day breakdowns are "
                             "served by the paper-analytics endpoints "
                             "(paper trades only — never mixed with "
                             "backtests)."),
    }
