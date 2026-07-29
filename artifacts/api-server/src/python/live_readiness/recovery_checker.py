"""
recovery_checker.py — Phase 6.5
Recovery validation: journal replay capability, session restoration,
state restoration, config file presence, recovery success rate.

READ-ONLY. ADVISORY-ONLY.
"""
from __future__ import annotations
import os, time
from typing import List
from .readiness_models import ReadinessCheck, PASS, WARN, FAIL


def check_recovery() -> dict:
    """
    Run recovery validation checks.
    """
    checks: List[ReadinessCheck] = []

    checks.append(_check_portfolio_store_recovery())
    checks.append(_check_config_accessible())
    checks.append(_check_watchlist_accessible())
    checks.append(_check_phase6x_snapshot_recovery())
    checks.append(_check_session_restoration())
    checks.append(_check_journal_replay())

    score = _category_score(checks)

    return {
        "checks": [c.to_dict() for c in checks],
        "score": score,
        "total_checks": len(checks),
        "passed": sum(1 for c in checks if c.status == PASS),
        "warnings": sum(1 for c in checks if c.status == WARN),
        "failures": sum(1 for c in checks if c.status == FAIL),
        "recovery_health": "STRONG" if score >= 80 else "ADEQUATE" if score >= 60 else "WEAK",
    }


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------

def _check_portfolio_store_recovery() -> ReadinessCheck:
    """Verify portfolio state can be loaded after a simulated restart."""
    t0 = time.monotonic()
    try:
        from portfolio_store import load_state
        state = load_state()
        ms = (time.monotonic() - t0) * 1000
        cash = state.get("cash", 0.0)
        return ReadinessCheck(
            name="portfolio_store_recovery",
            label="Portfolio State Recovery",
            status=PASS,
            required=True,
            detail=f"Portfolio store loaded in {ms:.0f}ms (cash: ₹{cash:,.0f}).",
            category="Recovery",
        )
    except Exception as e:
        return ReadinessCheck(
            name="portfolio_store_recovery",
            label="Portfolio State Recovery",
            status=FAIL,
            required=True,
            detail=f"Portfolio state load failed: {str(e)[:120]}",
            category="Recovery",
        )


def _check_config_accessible() -> ReadinessCheck:
    try:
        import config
        has_watchlist = hasattr(config, "DEFAULT_WATCHLIST")
        has_capital = hasattr(config, "PAPER_TRADING_CAPITAL") or hasattr(config, "STARTING_CAPITAL")
        if has_watchlist:
            return ReadinessCheck(
                name="config_accessible",
                label="Configuration Module",
                status=PASS,
                required=True,
                detail="Config module loaded — DEFAULT_WATCHLIST present.",
                category="Recovery",
            )
        return ReadinessCheck(
            name="config_accessible",
            label="Configuration Module",
            status=WARN,
            required=False,
            detail="Config module loaded but DEFAULT_WATCHLIST not found.",
            category="Recovery",
        )
    except Exception as e:
        return ReadinessCheck(
            name="config_accessible",
            label="Configuration Module",
            status=FAIL,
            required=True,
            detail=f"Config import failed: {str(e)[:120]}",
            category="Recovery",
        )


def _check_watchlist_accessible() -> ReadinessCheck:
    """Verify the symbol watchlist can be resolved."""
    try:
        import config
        watchlist = getattr(config, "DEFAULT_WATCHLIST", [])
        if not watchlist:
            # Try loading watchlist.json
            import json
            wl_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "watchlist.json")
            if os.path.exists(wl_path):
                with open(wl_path) as f:
                    data = json.load(f)
                    symbols = data if isinstance(data, list) else data.get("symbols", [])
                    if symbols:
                        return ReadinessCheck(
                            name="watchlist_accessible",
                            label="Symbol Watchlist",
                            status=PASS,
                            required=False,
                            detail=f"watchlist.json: {len(symbols)} symbols.",
                            category="Recovery",
                        )
            return ReadinessCheck(
                name="watchlist_accessible",
                label="Symbol Watchlist",
                status=WARN,
                required=False,
                detail="Watchlist is empty — no symbols configured for scanning.",
                category="Recovery",
            )
        return ReadinessCheck(
            name="watchlist_accessible",
            label="Symbol Watchlist",
            status=PASS,
            required=False,
            detail=f"DEFAULT_WATCHLIST: {len(watchlist)} symbol(s).",
            category="Recovery",
        )
    except Exception as e:
        return ReadinessCheck(
            name="watchlist_accessible",
            label="Symbol Watchlist",
            status=WARN,
            required=False,
            detail=f"Watchlist check failed: {str(e)[:80]}",
            category="Recovery",
        )


def _check_phase6x_snapshot_recovery() -> ReadinessCheck:
    """Verify all Phase 6.x snapshot functions can be called without error."""
    failed = []
    for label, importer in [
        ("6.1 Validation",       lambda: __import__("paper_trading_validation.shared_services", fromlist=["get_validation_snapshot"]).get_validation_snapshot()),
        ("6.2 Strategy Opt.",    lambda: __import__("strategy_optimisation.shared_services", fromlist=["get_optimisation_snapshot"]).get_optimisation_snapshot()),
        ("6.3 AI Opt.",          lambda: __import__("ai_optimisation.shared_services", fromlist=["get_ai_optimisation_snapshot"]).get_ai_optimisation_snapshot()),
        ("6.4 Risk Opt.",        lambda: __import__("risk_optimisation.shared_services", fromlist=["get_risk_optimisation_snapshot"]).get_risk_optimisation_snapshot()),
    ]:
        try:
            result = importer()
            if not isinstance(result, dict):
                failed.append(f"{label} (non-dict response)")
        except Exception as e:
            failed.append(f"{label}: {str(e)[:60]}")

    if not failed:
        return ReadinessCheck(
            name="phase6x_snapshot_recovery",
            label="Phase 6.x Analytics Recovery",
            status=PASS,
            required=False,
            detail="All Phase 6.x snapshot functions callable without error.",
            category="Recovery",
        )
    return ReadinessCheck(
        name="phase6x_snapshot_recovery",
        label="Phase 6.x Analytics Recovery",
        status=WARN,
        required=False,
        detail=f"Snapshot issues: {'; '.join(failed[:3])}",
        category="Recovery",
    )


def _check_session_restoration() -> ReadinessCheck:
    """Check session secret and session management are configured."""
    has_session_secret = bool(os.environ.get("SESSION_SECRET"))
    if has_session_secret:
        return ReadinessCheck(
            name="session_restoration",
            label="Session Secret Configured",
            status=PASS,
            required=True,
            detail="SESSION_SECRET is set — sessions can be restored securely.",
            category="Recovery",
        )
    return ReadinessCheck(
        name="session_restoration",
        label="Session Secret Configured",
        status=FAIL,
        required=True,
        detail="SESSION_SECRET not set — sessions will not persist across restarts.",
        category="Recovery",
    )


def _check_journal_replay() -> ReadinessCheck:
    """Verify the trade journal (paper_trades table) is replayable."""
    try:
        from portfolio_store import load_all_trades_any
        trades = load_all_trades_any()
        n = len(trades) if trades else 0
        return ReadinessCheck(
            name="journal_replay",
            label="Trade Journal Replay",
            status=PASS,
            required=False,
            detail=f"Trade journal accessible — {n} raw trade record(s) available for replay.",
            category="Recovery",
        )
    except Exception as e:
        return ReadinessCheck(
            name="journal_replay",
            label="Trade Journal Replay",
            status=WARN,
            required=False,
            detail=f"Journal replay probe: {str(e)[:120]}",
            category="Recovery",
        )


def _category_score(checks: list) -> float:
    if not checks:
        return 50.0
    total = sum(1.0 if c.status == PASS else 0.5 if c.status == WARN else 0.0 for c in checks)
    return round((total / len(checks)) * 100.0, 2)
