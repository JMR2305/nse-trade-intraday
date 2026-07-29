"""Phase 7.4 – Public interface for Explainable AI module."""
from __future__ import annotations
import csv
import io
import json
from typing import Any, Dict, List, Optional

from .models import is_enabled, disabled_response
from .decision_explainer import explain_decision, get_all_explainable_decisions
from .indicator_contributions import compute_contributions
from .confidence_analyzer import compute_confidence
from .scenario_generator import generate_scenarios
from .historical_similarity import find_historical_matches
from .market_context_explainer import explain_market_context
from .event_context_explainer import explain_event_context
from .macro_context_explainer import explain_macro_context
from .risk_explainer import explain_risk
from .operator_summary import build_operator_summary

# ── upstream snapshot imports (zero re-computation) ─────────────────────────
try:
    from market_intelligence_hub.shared_services import get_market_intelligence_snapshot
except Exception:
    def get_market_intelligence_snapshot() -> Dict[str, Any]:  # type: ignore
        return {"available": False}

try:
    from event_intelligence.shared_services import get_event_intelligence_snapshot
except Exception:
    def get_event_intelligence_snapshot() -> Dict[str, Any]:  # type: ignore
        return {"available": False}

try:
    from macro_intelligence.shared_services import get_macro_intelligence_snapshot
except Exception:
    def get_macro_intelligence_snapshot() -> Dict[str, Any]:  # type: ignore
        return {"available": False}

try:
    from risk_optimisation.shared_services import get_risk_optimisation_snapshot
except Exception:
    def get_risk_optimisation_snapshot() -> Dict[str, Any]:  # type: ignore
        return {"available": False}

try:
    import signals_store
    _has_store = True
except Exception:
    _has_store = False

try:
    import signals_cache
    _has_cache = True
except Exception:
    _has_cache = False


# ── helpers ──────────────────────────────────────────────────────────────────

def _load_signal(symbol: str) -> Optional[Dict[str, Any]]:
    if not _has_store:
        return None
    try:
        signals = signals_store.load_signals()
        for s in (signals or []):
            if s.get("stock") == symbol or s.get("symbol") == symbol:
                return s
    except Exception:
        pass
    return None


def _load_all_signals() -> List[Dict[str, Any]]:
    if not _has_store:
        return []
    try:
        return signals_store.load_signals() or []
    except Exception:
        return []


def _load_signal_snapshots() -> List[Dict[str, Any]]:
    if not _has_store:
        return []
    try:
        fn = getattr(signals_store, "load_signal_snapshots", None)
        if fn:
            return fn() or []
    except Exception:
        pass
    return []


# ── public API ───────────────────────────────────────────────────────────────

def get_summary() -> Dict[str, Any]:
    """High-level summary: list of explainable decisions + KPIs."""
    if not is_enabled():
        return disabled_response("get_summary")

    market_snap = get_market_intelligence_snapshot()
    event_snap  = get_event_intelligence_snapshot()
    macro_snap  = get_macro_intelligence_snapshot()
    risk_snap   = get_risk_optimisation_snapshot()

    # get_all_explainable_decisions returns a list of dicts (already serialised)
    decisions = get_all_explainable_decisions(market_snap, event_snap, macro_snap, risk_snap)

    buy_count  = sum(1 for d in decisions if d.get("signal_type") in ("BUY", "STRONG_BUY"))
    sell_count = sum(1 for d in decisions if d.get("signal_type") in ("SELL", "STRONG_SELL"))
    hold_count = sum(1 for d in decisions if d.get("signal_type") not in
                     ("BUY", "STRONG_BUY", "SELL", "STRONG_SELL"))
    avg_conf   = (
        sum(_conf_from_dict(d) for d in decisions) / len(decisions) if decisions else 0.0
    )

    return {
        "status":          "ENABLED",
        "total_decisions": len(decisions),
        "buy_count":       buy_count,
        "sell_count":      sell_count,
        "hold_count":      hold_count,
        "avg_confidence":  round(avg_conf, 3),
        "decisions":       decisions,
    }


def get_decision(symbol: str) -> Dict[str, Any]:
    """Full explainable decision for a single symbol."""
    if not is_enabled():
        return disabled_response("get_decision")

    market_snap = get_market_intelligence_snapshot()
    event_snap  = get_event_intelligence_snapshot()
    macro_snap  = get_macro_intelligence_snapshot()
    risk_snap   = get_risk_optimisation_snapshot()

    decision = explain_decision(symbol, market_snap, event_snap, macro_snap, risk_snap)
    if decision is None:
        return {"status": "ENABLED", "symbol": symbol, "decision": None, "message": "No signal found"}

    summary  = build_operator_summary(decision)
    dec_dict = decision.to_dict() if hasattr(decision, "to_dict") else decision

    # Enrich the decision dict with structured context objects so the
    # dashboard Market/Event/Macro/Risk tabs have live data to display.
    market_ctx = explain_market_context(market_snap)
    event_ctx  = explain_event_context(event_snap)
    macro_ctx  = explain_macro_context(macro_snap)
    risk_ctx   = explain_risk(risk_snap)

    dec_dict["market_context"] = market_ctx
    dec_dict["event_context"]  = event_ctx
    dec_dict["macro_context"]  = macro_ctx
    dec_dict["risk_context"]   = risk_ctx

    return {
        "status":   "ENABLED",
        "symbol":   symbol,
        "decision": dec_dict,
        "summary":  summary,
    }


def get_contributions(symbol: str) -> Dict[str, Any]:
    """12-indicator contribution breakdown for a symbol."""
    if not is_enabled():
        return disabled_response("get_contributions")

    signal = _load_signal(symbol)
    if signal is None:
        return {"status": "ENABLED", "symbol": symbol, "contributions": [], "message": "No signal found"}

    market_snap = get_market_intelligence_snapshot()
    contribs = compute_contributions(symbol, signal, market_snap)
    return {
        "status":        "ENABLED",
        "symbol":        symbol,
        "contributions": [c.to_dict() if hasattr(c, "to_dict") else c.__dict__ for c in contribs],
    }


def get_confidence(symbol: str) -> Dict[str, Any]:
    """8-dimension confidence decomposition for a symbol."""
    if not is_enabled():
        return disabled_response("get_confidence")

    signal = _load_signal(symbol)
    if signal is None:
        return {"status": "ENABLED", "symbol": symbol, "confidence": None, "message": "No signal found"}

    market_snap = get_market_intelligence_snapshot()
    macro_snap  = get_macro_intelligence_snapshot()
    risk_snap   = get_risk_optimisation_snapshot()

    decomp = compute_confidence(symbol, signal, market_snap, macro_snap, risk_snap)
    return {
        "status":     "ENABLED",
        "symbol":     symbol,
        "confidence": decomp.to_dict() if hasattr(decomp, "to_dict") else decomp.__dict__,
    }


def get_scenarios(symbol: str) -> Dict[str, Any]:
    """Bullish / Neutral / Bearish scenario analysis for a symbol."""
    if not is_enabled():
        return disabled_response("get_scenarios")

    signal = _load_signal(symbol)
    if signal is None:
        return {"status": "ENABLED", "symbol": symbol, "scenarios": [], "message": "No signal found"}

    market_snap = get_market_intelligence_snapshot()
    macro_snap  = get_macro_intelligence_snapshot()

    scenarios = generate_scenarios(symbol, signal, market_snap, macro_snap)
    return {
        "status":    "ENABLED",
        "symbol":    symbol,
        "scenarios": [s.to_dict() if hasattr(s, "to_dict") else s.__dict__ for s in scenarios],
    }


def get_history(symbol: str) -> Dict[str, Any]:
    """Up to 5 historical pattern matches for a symbol."""
    if not is_enabled():
        return disabled_response("get_history")

    signal = _load_signal(symbol)
    if signal is None:
        return {"status": "ENABLED", "symbol": symbol, "matches": [], "message": "No signal found"}

    snapshots = _load_signal_snapshots()
    matches   = find_historical_matches(symbol, signal, snapshots)
    return {
        "status":  "ENABLED",
        "symbol":  symbol,
        "matches": [m.to_dict() if hasattr(m, "to_dict") else m.__dict__ for m in matches],
    }


def get_explainable_ai_snapshot() -> Dict[str, Any]:
    """Flat KPI dict for Phase 7.5 Research Lab aggregation."""
    if not is_enabled():
        return {
            "available":       False,
            "explainable_ai_score": 0,
            "grade":           "N/A",
            "total_decisions": 0,
            "avg_confidence":  0,
            "buy_count":       0,
            "sell_count":      0,
            "hold_count":      0,
        }

    try:
        summary = get_summary()
        total   = summary.get("total_decisions", 0)
        avg_c   = summary.get("avg_confidence", 0.0)
        # Score: blend of coverage and confidence
        score   = round(min(100.0, avg_c * 100 * 0.7 + min(total, 20) / 20 * 100 * 0.3), 1)

        if score >= 80:
            grade = "A"
        elif score >= 65:
            grade = "B"
        elif score >= 50:
            grade = "C"
        elif score >= 35:
            grade = "D"
        else:
            grade = "F"

        return {
            "available":            True,
            "explainable_ai_score": score,
            "grade":                grade,
            "total_decisions":      total,
            "avg_confidence":       avg_c,
            "buy_count":            summary.get("buy_count", 0),
            "sell_count":           summary.get("sell_count", 0),
            "hold_count":           summary.get("hold_count", 0),
        }
    except Exception as exc:
        return {
            "available":            False,
            "explainable_ai_score": 0,
            "grade":                "N/A",
            "error":                str(exc),
        }


def export_csv() -> str:
    """Export all explainable decisions as CSV text."""
    if not is_enabled():
        return "status\nDISABLED\n"

    market_snap = get_market_intelligence_snapshot()
    event_snap  = get_event_intelligence_snapshot()
    macro_snap  = get_macro_intelligence_snapshot()
    risk_snap   = get_risk_optimisation_snapshot()

    # returns list of dicts
    decisions = get_all_explainable_decisions(market_snap, event_snap, macro_snap, risk_snap)

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([
        "symbol", "signal", "confidence", "grade",
        "risk_level", "price", "target", "stop_loss",
        "primary_reason", "regime",
    ])
    for d in decisions:
        writer.writerow([
            d.get("symbol"), d.get("signal_type"), _conf_from_dict(d),
            d.get("grade"), d.get("risk_level"),
            d.get("price"), d.get("target"), d.get("stop_loss"),
            d.get("primary_reason", ""), d.get("regime", ""),
        ])
    return buf.getvalue()


def export_json() -> str:
    """Export all explainable decisions as JSON text."""
    if not is_enabled():
        return json.dumps({"status": "DISABLED"})

    market_snap = get_market_intelligence_snapshot()
    event_snap  = get_event_intelligence_snapshot()
    macro_snap  = get_macro_intelligence_snapshot()
    risk_snap   = get_risk_optimisation_snapshot()

    decisions = get_all_explainable_decisions(market_snap, event_snap, macro_snap, risk_snap)
    return json.dumps(
        {"status": "ENABLED", "decisions": decisions},
        indent=2,
    )


# ── internal helpers ─────────────────────────────────────────────────────────

def _conf_from_dict(d: Dict[str, Any]) -> float:
    """Extract a 0–1 confidence value from a decision dict."""
    c = d.get("confidence", 0.0)
    if c is None:
        c = 0.0
    if c > 1.0:
        c = c / 100.0
    fc = d.get("final_confidence", 0.0) or 0.0
    if c == 0.0 and fc > 0.0:
        c = fc / 100.0 if fc > 1.0 else fc
    return float(c)
