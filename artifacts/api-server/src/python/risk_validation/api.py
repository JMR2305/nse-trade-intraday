"""
risk_validation/api.py — Phase 8.4
Thin command-handler wrappers called from main.py dispatch.
READ-ONLY · ADVISORY-ONLY.
"""
from .shared_services import (
    get_summary, get_portfolio_data, get_sector_data, get_correlation_data,
    get_stress_data, get_tail_risk_data, get_execution_data,
    get_market_risk_data, get_drift_data, get_alerts_data,
    get_export_json, get_export_csv, get_risk_validation_snapshot,
)
from .models import is_enabled, disabled_response

def cmd_summary()     -> dict: return get_summary()
def cmd_portfolio()   -> dict: return get_portfolio_data()
def cmd_sector()      -> dict: return get_sector_data()
def cmd_correlation() -> dict: return get_correlation_data()
def cmd_stress()      -> dict: return get_stress_data()
def cmd_tail()        -> dict: return get_tail_risk_data()
def cmd_execution()   -> dict: return get_execution_data()
def cmd_market()      -> dict: return get_market_risk_data()
def cmd_drift()       -> dict: return get_drift_data()
def cmd_alerts()      -> dict: return get_alerts_data()
def cmd_snapshot()    -> dict: return get_risk_validation_snapshot()
def cmd_export_json() -> dict: return get_export_json()

def cmd_export_csv() -> dict:
    if not is_enabled():
        return disabled_response()
    return {
        "status":       "ENABLED",
        "advisory_only": True,
        "csv":           get_export_csv(),
    }


def cmd_pre_trade_log() -> dict:
    """Return the last 20 pre-trade risk validation outcomes from trade evidence."""
    from datetime import datetime, timezone

    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    try:
        from phase20_executor import get_ledger
        trades = get_ledger(100)
    except Exception as exc:
        return {"status": "ENABLED", "available": False,
                "advisory_only": True, "error": str(exc)[:200],
                "approvals": []}

    approvals = []
    for t in trades:
        ev = t.get("evidence") or {}
        rv = ev.get("risk_validation") or {}
        if not rv:
            continue
        approvals.append({
            "trade_id":    t.get("trade_id"),
            "symbol":      t.get("symbol"),
            "side":        t.get("side", "BUY"),
            "status":      t.get("status"),
            "decision_ts": t.get("decision_ts"),
            "fill_price":  t.get("fill_price"),
            "quantity":    t.get("quantity"),
            "verdict":     rv.get("verdict", "APPROVED"),
            "approved":    rv.get("approved", True),
            "reason":      rv.get("reason", ""),
            "critical_count": rv.get("critical_count", 0),
            "warning_count":  rv.get("warning_count", 0),
            "issues":      rv.get("issues", []),
            "metrics":     rv.get("metrics", {}),
            "summary":     rv.get("summary", {}),
        })

    # Most recent first
    approvals.sort(key=lambda x: x.get("decision_ts") or "", reverse=True)

    return {
        "status":        "ENABLED",
        "available":     True,
        "advisory_only": True,
        "generated_at":  _now(),
        "total":         len(approvals),
        "approvals":     approvals[:20],
    }
