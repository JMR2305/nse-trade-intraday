"""
knowledge_engine.py — Phase 10D Knowledge Agent
Indexing, search, trade memory, and lessons library.

READ-ONLY · ADVISORY-ONLY
No model retraining. No parameter tuning. No automatic optimisation.
All outputs require operator review before adoption.
"""
from __future__ import annotations
import hashlib
import re
from datetime import datetime, timezone
from typing import Any

# ── helpers ───────────────────────────────────────────────────────────────────

def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _safe(fn, default=None):
    try:
        return fn()
    except Exception:
        return default


def _entry_id(*parts: str) -> str:
    """Deterministic short ID for a knowledge entry."""
    raw = "|".join(parts)
    return hashlib.md5(raw.encode()).hexdigest()[:10]


def _tokenise(text: str) -> list[str]:
    """Simple lowercase tokeniser for keyword matching."""
    return re.findall(r"[a-zA-Z0-9]+", text.lower())


def _score_relevance(query_tokens: list[str], entry_text: str) -> float:
    """Return 0.0–1.0 relevance score for a knowledge entry against a query."""
    entry_tokens = set(_tokenise(entry_text))
    if not query_tokens:
        return 0.0
    hits = sum(1 for t in query_tokens if t in entry_tokens)
    return round(hits / len(query_tokens), 3)


# ── knowledge indexing ────────────────────────────────────────────────────────

def build_knowledge_index(
    trades: list[dict],
    recommendations: list[dict],
    research_snapshot: dict,
    timeline_events: list[dict],
    decision_snapshot: dict,
    annotations: list[dict],
) -> list[dict]:
    """
    Index all knowledge sources into a unified, searchable entry list.
    Returns knowledge entries with type, content, tags, and metadata.
    """
    entries: list[dict] = []

    # Index completed trades
    for t in trades:
        if t.get("status") not in ("CLOSED", "COMPLETED", "SOLD"):
            continue
        pnl = _safe(lambda t=t: float(t.get("pnl_pct", 0.0)), 0.0)
        label = "WIN" if pnl > 0 else "LOSS"
        text = (
            f"{label} trade in {t.get('symbol','?')} sector {t.get('sector','?')} "
            f"strategy {t.get('strategy','?')} pnl {pnl:.1f}%"
        )
        entries.append({
            "entry_id": _entry_id("trade", str(t.get("id", t.get("symbol", "")))),
            "type": "TRADE",
            "label": label,
            "title": f"{label}: {t.get('symbol','?')} via {t.get('strategy','?')}",
            "content": text,
            "symbol": t.get("symbol"),
            "sector": t.get("sector", "UNKNOWN"),
            "strategy": t.get("strategy", "UNKNOWN"),
            "pnl_pct": pnl,
            "tags": [t.get("sector", "UNKNOWN"), t.get("strategy", "UNKNOWN"), label, "TRADE"],
            "timestamp": t.get("exit_time") or t.get("updated_at") or _now_iso(),
        })

    # Index recommendations
    for r in recommendations:
        outcome = r.get("outcome", "PENDING")
        confidence = _safe(lambda r=r: float(r.get("confidence", 0.5)), 0.5)
        text = (
            f"recommendation {r.get('decision_type','?')} for {r.get('symbol','?')} "
            f"confidence {confidence:.0%} outcome {outcome}"
        )
        entries.append({
            "entry_id": _entry_id("rec", str(r.get("recommendation_id", r.get("symbol", "")))),
            "type": "RECOMMENDATION",
            "label": outcome,
            "title": f"Rec: {r.get('decision_type','?')} {r.get('symbol','?')} ({confidence:.0%})",
            "content": text,
            "symbol": r.get("symbol"),
            "decision_type": r.get("decision_type"),
            "confidence": confidence,
            "tags": [r.get("decision_type", "REC"), outcome, "RECOMMENDATION"],
            "timestamp": r.get("generated_at") or r.get("timestamp") or _now_iso(),
        })

    # Index research items
    for item in _safe(lambda: research_snapshot.get("research_items", []), []):
        text = f"research {item.get('topic','?')} {item.get('summary','')}"
        entries.append({
            "entry_id": _entry_id("research", str(item.get("id", item.get("topic", "")))),
            "type": "RESEARCH",
            "label": "INSIGHT",
            "title": f"Research: {item.get('topic','?')}",
            "content": text,
            "tags": ["RESEARCH", item.get("category", "GENERAL")],
            "timestamp": item.get("timestamp") or _now_iso(),
        })

    # Index timeline events
    for ev in timeline_events[:100]:  # cap to avoid index bloat
        etype = ev.get("event_type", ev.get("type", "EVENT"))
        text = f"event {etype} {ev.get('title','')} {ev.get('description','')}"
        entries.append({
            "entry_id": _entry_id("event", str(ev.get("event_id", ev.get("title", "")))),
            "type": "TIMELINE_EVENT",
            "label": etype,
            "title": ev.get("title", etype),
            "content": text,
            "tags": [etype, "TIMELINE"],
            "timestamp": ev.get("timestamp") or _now_iso(),
        })

    # Index decision explanations
    for rec in _safe(lambda: decision_snapshot.get("recommendations", []), []):
        explain = rec.get("explanation", {})
        summary = explain.get("summary", "")
        if not summary:
            continue
        text = f"decision explanation {rec.get('symbol','?')} {summary}"
        entries.append({
            "entry_id": _entry_id("explain", str(rec.get("recommendation_id", rec.get("symbol", "")))),
            "type": "DECISION_EXPLANATION",
            "label": rec.get("decision_type", "DECISION"),
            "title": f"AI Explanation: {rec.get('symbol','?')} {rec.get('decision_type','')}",
            "content": text,
            "symbol": rec.get("symbol"),
            "tags": ["DECISION", "EXPLANATION", rec.get("decision_type", "")],
            "timestamp": rec.get("generated_at") or _now_iso(),
        })

    # Index operator annotations
    for ann in annotations:
        text = f"annotation {ann.get('note','')} {ann.get('symbol','')}"
        entries.append({
            "entry_id": _entry_id("ann", str(ann.get("id", ann.get("note", ""))[:20])),
            "type": "ANNOTATION",
            "label": "OPERATOR_NOTE",
            "title": f"Note: {str(ann.get('note',''))[:60]}",
            "content": text,
            "tags": ["ANNOTATION", "OPERATOR_NOTE"],
            "timestamp": ann.get("timestamp") or _now_iso(),
        })

    return entries


# ── natural-language search ───────────────────────────────────────────────────

_INTENT_MAP = {
    "banking":     ["BANKING", "FINANCIALS", "BANK"],
    "breakout":    ["BREAKOUT", "MOMENTUM", "TREND"],
    "confidence":  ["RECOMMENDATION"],
    "rbi":         ["MACRO", "RESEARCH", "EVENT"],
    "volatility":  ["VOLATILITY", "HIGH_VOL", "VIX"],
    "momentum":    ["MOMENTUM"],
    "sector":      ["SECTOR"],
    "risk":        ["RISK", "RISK_AGENT"],
}

def search_knowledge(query: str, entries: list[dict], limit: int = 20) -> list[dict]:
    """
    Natural-language keyword search over indexed knowledge entries.
    Returns entries ranked by relevance (highest first).
    """
    q_lower = query.lower().strip()
    q_tokens = _tokenise(q_lower)

    # Expand intent tokens
    extra_tokens: list[str] = []
    for keyword, expansions in _INTENT_MAP.items():
        if keyword in q_tokens:
            extra_tokens.extend([t.lower() for t in expansions])
    all_tokens = list(set(q_tokens + extra_tokens))

    # Confidence filter (e.g. "above 80%")
    confidence_threshold = 0.0
    m = re.search(r"(\d{2,3})\s*%", q_lower)
    if m:
        confidence_threshold = int(m.group(1)) / 100.0

    scored: list[dict] = []
    for entry in entries:
        text = entry.get("content", "") + " " + " ".join(entry.get("tags", []))
        score = _score_relevance(all_tokens, text)

        # Apply confidence filter if requested
        if confidence_threshold > 0:
            conf = entry.get("confidence", 1.0)
            if conf < confidence_threshold:
                continue

        # Boost exact label / symbol matches
        if any(t in entry.get("symbol", "").lower() for t in q_tokens):
            score = min(1.0, score + 0.3)
        if any(t in entry.get("label", "").lower() for t in q_tokens):
            score = min(1.0, score + 0.2)

        if score > 0:
            scored.append({**entry, "relevance_score": round(score, 3)})

    # Sort by relevance then timestamp (newest first)
    scored.sort(key=lambda x: (-x["relevance_score"], x.get("timestamp", "")), reverse=False)
    scored.sort(key=lambda x: -x["relevance_score"])
    return scored[:limit]


# ── trade memory ──────────────────────────────────────────────────────────────

def build_trade_memory(
    trades: list[dict],
    recommendations: list[dict],
    decision_snapshot: dict,
) -> list[dict]:
    """
    For every completed paper trade, store the full learning record:
    decision, execution plan, outcome, timeline, AI explanation,
    strategy, risk, lessons learned, related research.
    """
    rec_map = {r.get("symbol"): r for r in recommendations}
    dec_recs = {
        r.get("symbol"): r
        for r in _safe(lambda: decision_snapshot.get("recommendations", []), [])
    }

    memory: list[dict] = []
    for t in trades:
        if t.get("status") not in ("CLOSED", "COMPLETED", "SOLD"):
            continue

        symbol = t.get("symbol", "?")
        pnl    = _safe(lambda t=t: float(t.get("pnl_pct", 0.0)), 0.0)
        rec    = rec_map.get(symbol, {})
        dec    = dec_recs.get(symbol, {})
        explain = dec.get("explanation", {})

        outcome = "WIN" if pnl > 0 else "LOSS"

        # Lessons learned (advisory)
        lessons: list[str] = []
        if pnl > 2.0:
            lessons.append(f"{symbol} breakout trade returned {pnl:.1f}% — strategy and timing aligned well.")
        elif pnl > 0:
            lessons.append(f"{symbol} closed positive at {pnl:.1f}% — monitor for stronger confirmation signals.")
        elif pnl > -1.0:
            lessons.append(f"{symbol} small loss {pnl:.1f}% — within acceptable stop range, no action required.")
        else:
            lessons.append(f"{symbol} loss {pnl:.1f}% — review entry signal quality and regime suitability.")

        if t.get("rejected_by_risk"):
            lessons.append("Trade was flagged by risk pre-checks — review calibration if rejections are frequent.")

        memory.append({
            "memory_id": _entry_id("mem", symbol, t.get("exit_time", _now_iso())),
            "symbol": symbol,
            "sector": t.get("sector", "UNKNOWN"),
            "strategy": t.get("strategy", "UNKNOWN"),
            "outcome": outcome,
            "pnl_pct": pnl,
            # Decision context
            "decision_type": dec.get("decision_type") or rec.get("decision_type", "UNKNOWN"),
            "decision_confidence": _safe(lambda: float(dec.get("confidence", rec.get("confidence", 0.5))), 0.5),
            "ai_explanation_summary": explain.get("summary", "No AI explanation available."),
            "supporting_signals": explain.get("supporting_signals", []),
            # Execution context
            "entry_price": t.get("entry_price"),
            "exit_price":  t.get("exit_price"),
            "quantity":    t.get("quantity"),
            "entry_time":  t.get("entry_time") or t.get("created_at"),
            "exit_time":   t.get("exit_time")  or t.get("updated_at"),
            # Risk context
            "risk_pct":          t.get("risk_pct"),
            "stop_loss":         t.get("stop_loss"),
            "rejected_by_risk":  t.get("rejected_by_risk", False),
            # Learning output
            "lessons_learned": lessons,
            "related_research": rec.get("supporting_strategies", []),
            "timestamp": t.get("exit_time") or _now_iso(),
        })

    return memory


# ── lessons library ───────────────────────────────────────────────────────────

def generate_lessons_library(
    trade_memory: list[dict],
    metrics: dict,
    insights: dict,
) -> dict:
    """
    Automatically generate the five lesson categories:
    what worked, what failed, what should be reviewed,
    what should be monitored, and open research questions.
    Advisory only.
    """
    wins  = [m for m in trade_memory if m["outcome"] == "WIN"]
    loss  = [m for m in trade_memory if m["outcome"] == "LOSS"]

    # What worked
    what_worked: list[str] = []
    if wins:
        top_strats = {}
        for w in wins:
            s = w.get("strategy", "UNKNOWN")
            top_strats[s] = top_strats.get(s, 0) + 1
        best = max(top_strats, key=top_strats.get)
        what_worked.append(f"Strategy '{best}' contributed to {top_strats[best]} winning trade(s).")
    best_sec = insights.get("most_profitable_sector", "N/A")
    if best_sec != "N/A":
        what_worked.append(f"Sector '{best_sec}' showed the best average P&L today.")
    if metrics.get("avg_reward_risk", 0) > 1.5:
        what_worked.append(f"Average reward/risk of {metrics['avg_reward_risk']:.2f} — disciplined exits are working.")
    if not what_worked:
        what_worked.append("Insufficient closed trades to identify what worked — continue monitoring.")

    # What failed
    what_failed: list[str] = []
    if loss:
        fail_strats = {}
        for lo in loss:
            s = lo.get("strategy", "UNKNOWN")
            fail_strats[s] = fail_strats.get(s, 0) + 1
        worst = max(fail_strats, key=fail_strats.get)
        what_failed.append(f"Strategy '{worst}' contributed to {fail_strats[worst]} losing trade(s).")
    weak_sec = insights.get("weakest_sector", "N/A")
    if weak_sec != "N/A" and weak_sec != best_sec:
        what_failed.append(f"Sector '{weak_sec}' showed the weakest average P&L today.")
    if metrics.get("strategy_win_rate", 100) < 40:
        what_failed.append(f"Win rate {metrics['strategy_win_rate']:.0f}% below 40% — entry criteria need review.")
    if not what_failed:
        what_failed.append("No significant failure patterns identified in current session.")

    # What should be reviewed
    what_to_review: list[str] = []
    if metrics.get("strategy_win_rate", 100) < 40:
        what_to_review.append(
            f"Win rate {metrics['strategy_win_rate']:.0f}% below 40% — entry criteria need review."
        )
    if metrics.get("confidence_calibration", 1.0) < 0.6:
        what_to_review.append(
            f"Confidence calibration score is {metrics['confidence_calibration']:.2f} — "
            "AI confidence estimates diverging from actual outcomes."
        )
    for r in insights.get("common_rejection_reasons", [])[:2]:
        what_to_review.append(f"Rejection reason '{r['reason']}' appeared {r['count']} time(s) — worth investigating.")
    if not what_to_review:
        what_to_review.append("No urgent review items identified — system operating within expected parameters.")

    # What should be monitored
    what_to_monitor: list[str] = []
    for p in insights.get("recurring_patterns", [])[:3]:
        what_to_monitor.append(p)
    for w in insights.get("most_frequent_risk_warnings", [])[:2]:
        what_to_monitor.append(f"Risk warning '{w['warning']}' recurring {w['count']} time(s).")
    if not what_to_monitor:
        what_to_monitor.append("No monitoring alerts raised — continue standard session review cadence.")

    # Open research questions
    open_questions: list[str] = []
    if metrics.get("avg_holding_minutes", 120) < 30:
        open_questions.append("Why are trades closing so quickly? Investigate stop tightness vs volatility expansion.")
    if metrics.get("risk_prediction_accuracy", 50) < 50:
        open_questions.append("Risk prediction accuracy below 50% — is the risk model calibrated for current regime?")
    open_questions.append("Which market microstructure signals best precede successful breakouts in the current regime?")
    open_questions.append("How does the intraday regime transition affect recommendation accuracy across strategy types?")

    return {
        "what_worked":     what_worked,
        "what_failed":     what_failed,
        "what_to_review":  what_to_review,
        "what_to_monitor": what_to_monitor,
        "open_questions":  open_questions,
        "generated_at":    _now_iso(),
        "trades_analysed": len(trade_memory),
    }
