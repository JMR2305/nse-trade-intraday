"""
phase15_risk_gate.py — Phase 15: Risk Engine Hardening

Before every recommendation is actionable, validate the full pre-trade
checklist. Every rule is evaluated explicitly with a pass/fail and reason —
failures BLOCK the trade and explain why. Nothing is silently ignored.

Checks: capital available, maximum daily loss, risk per trade, maximum
exposure, sector exposure, correlation (sector concentration proxy),
market regime, position limits, data quality, stale data.

PAPER TRADING / RESEARCH ONLY — no real orders.
"""

from __future__ import annotations

from typing import Any, Dict, List

from phase15_scan_context import symbol_context
from phase15_quality import score_symbol, staleness_report

# Conservative research defaults (₹5,000 capital)
MAX_DAILY_LOSS_PCT = 3.0        # stop trading if daily loss exceeds 3%
MAX_RISK_PER_TRADE_PCT = 2.0    # risk per trade ≤ 2% of capital
MAX_EXPOSURE_PCT = 80.0         # total invested ≤ 80% of portfolio value
MAX_SECTOR_EXPOSURE_PCT = 40.0  # single-sector exposure ≤ 40%
MAX_OPEN_POSITIONS = 5


def _check(name: str, passed: bool, reason: str) -> Dict[str, Any]:
    return {"check": name, "passed": bool(passed), "reason": reason}


def risk_gate(symbol: str) -> Dict[str, Any]:
    ctx = symbol_context(symbol)
    if not ctx.get("available"):
        return {"available": False, "reason": ctx.get("reason")}

    from paper_trader import _load_state, get_portfolio, INITIAL_CAPITAL
    from market_scanner import _sector_of

    state = _load_state()
    portfolio = get_portfolio()
    cash = float(portfolio["cash"])
    total_value = float(portfolio["total_value"])
    invested = float(portfolio["invested_value"])
    positions = portfolio["positions"]

    checks: List[Dict[str, Any]] = []
    entry = float(ctx.get("entry_price") or 0)
    stop = float(ctx.get("stop_loss") or 0)

    # 1. Capital available
    checks.append(_check(
        "capital_available", cash >= entry > 0,
        f"Cash ₹{cash:.2f} {'covers' if cash >= entry > 0 else 'cannot cover'} "
        f"one share at ₹{entry:.2f}" if entry > 0 else "No valid entry price"))

    # 2. Maximum daily loss
    from datetime import datetime
    today = datetime.now().date().isoformat()
    daily_pnl = sum(float(t.get("pnl") or 0) for t in state.get("trades", [])
                    if t.get("action") == "SELL" and str(t.get("timestamp", "")).startswith(today))
    daily_loss_limit = INITIAL_CAPITAL * MAX_DAILY_LOSS_PCT / 100
    checks.append(_check(
        "max_daily_loss", daily_pnl > -daily_loss_limit,
        f"Realised P&L today ₹{daily_pnl:.2f} vs limit -₹{daily_loss_limit:.2f} "
        f"({MAX_DAILY_LOSS_PCT}% of capital)"))

    # Intended position size: qty bounded by the 2% risk budget AND available
    # cash — checks below evaluate the PORTFOLIO AFTER this position is taken.
    risk_budget = total_value * MAX_RISK_PER_TRADE_PCT / 100
    risk_per_share = entry - stop if entry > 0 and stop > 0 else 0.0
    if risk_per_share > 0 and entry > 0:
        qty = min(int(risk_budget // risk_per_share), int(cash // entry))
        qty = max(qty, 0)
    else:
        qty = 1 if 0 < entry <= cash else 0
    position_value = qty * entry

    # 3. Risk per trade (for the intended quantity, not just one share)
    if risk_per_share > 0:
        trade_risk = qty * risk_per_share
        risk_pct = trade_risk / total_value * 100 if total_value > 0 else 999
        checks.append(_check(
            "risk_per_trade", qty > 0 and risk_pct <= MAX_RISK_PER_TRADE_PCT,
            f"{qty} share(s) × ₹{risk_per_share:.2f} stop risk = ₹{trade_risk:.2f} "
            f"({risk_pct:.2f}% of portfolio, limit {MAX_RISK_PER_TRADE_PCT}%)"
            if qty > 0 else "Risk budget or cash allows 0 shares — trade not sizeable"))
    else:
        checks.append(_check("risk_per_trade", False,
                             "No valid stop-loss — risk per trade cannot be bounded"))

    # 4. Maximum exposure AFTER taking this position
    exposure_after = invested + position_value
    exposure_pct = exposure_after / total_value * 100 if total_value > 0 else 0
    checks.append(_check(
        "max_exposure", exposure_pct <= MAX_EXPOSURE_PCT,
        f"Post-trade exposure {exposure_pct:.1f}% of portfolio "
        f"(current ₹{invested:.2f} + new ₹{position_value:.2f}, limit {MAX_EXPOSURE_PCT}%)"))

    # 5. Sector exposure AFTER taking this position
    sector = ctx.get("sector") or _sector_of(symbol)
    sector_value = sum(p["quantity"] * p["current_price"] for p in positions
                       if _sector_of(p["symbol"]) == sector) + position_value
    sector_pct = sector_value / total_value * 100 if total_value > 0 else 0
    checks.append(_check(
        "sector_exposure", sector_pct <= MAX_SECTOR_EXPOSURE_PCT,
        f"Post-trade {sector} exposure {sector_pct:.1f}% (limit {MAX_SECTOR_EXPOSURE_PCT}%)"))

    # 6. Correlation (same-sector open position proxy)
    same_sector_positions = [p["symbol"] for p in positions
                             if _sector_of(p["symbol"]) == sector and p["symbol"] != symbol.upper()]
    checks.append(_check(
        "correlation", len(same_sector_positions) < 2,
        f"{len(same_sector_positions)} open position(s) in same sector "
        f"{sector} ({', '.join(same_sector_positions) or 'none'}) — limit 2"))

    # 7. Market regime
    regime = str(ctx.get("market_regime") or "UNKNOWN").upper()
    regime_ok = "BEAR" not in regime and "PANIC" not in regime
    checks.append(_check(
        "market_regime", regime_ok,
        f"Market regime {regime} — {'acceptable' if regime_ok else 'hostile regime: new BUYs blocked'}"))

    # 8. Position limits
    checks.append(_check(
        "position_limits", len(positions) < MAX_OPEN_POSITIONS,
        f"{len(positions)} open positions (limit {MAX_OPEN_POSITIONS})"))

    # 9. Data quality
    q = score_symbol(ctx)
    checks.append(_check(
        "data_quality", q["tradeable"],
        f"Data quality {q['data_quality_score']}/100 ({q['band']})"
        + ("" if q["tradeable"] else " — DO NOT TRADE band")))

    # 10. Stale data
    stale = staleness_report()
    checks.append(_check(
        "stale_data", not stale["stale"],
        stale["warning"] or f"Scan fresh ({stale['scan_age_human']} old)"))

    failed = [c for c in checks if not c["passed"]]
    blocked = len(failed) > 0
    return {
        "available": True,
        "symbol": ctx["symbol"],
        "scan_id": ctx["scan_id"],
        "checks": checks,
        "passed_count": len(checks) - len(failed),
        "failed_count": len(failed),
        "blocked": blocked,
        "verdict": "BLOCKED" if blocked else "CLEARED",
        "block_reasons": [c["reason"] for c in failed],
        "note": ("Trade blocked — every failed rule is listed explicitly; nothing "
                 "is silently ignored.") if blocked else
                "All pre-trade risk checks passed.",
        "label": "PAPER / RESEARCH ONLY",
    }
