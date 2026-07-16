"""
phase20_gates.py — Phase 20 paper-trade entry eligibility gates.

A paper BUY may be created ONLY when every mandatory gate passes. On failure,
the exact failed gates are recorded so every UI page can show the reason.

All inputs come from the STORED canonical scan snapshot (no look-ahead) and
durable Phase 20 settings. PAPER TRADING / RESEARCH ONLY — no live orders.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import phase20_store as store

ZERODHA_PROVIDERS = ("zerodha", "kite", "zerodha_kite", "kite_connect")


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _gate(name: str, passed: bool, reason: str) -> Dict[str, Any]:
    return {"gate": name, "passed": bool(passed), "reason": reason}


def _sector_of(symbol: str) -> str:
    try:
        from market_scanner import _sector_of as sec
        return sec(symbol) or "Other"
    except Exception:
        return "Other"


def evaluate_entries(candidate_symbols: Optional[List[str]] = None) -> Dict[str, Any]:
    """
    Evaluate the entry gates for all BUY / STRONG BUY candidates in the
    stored canonical scan (or an explicit symbol list).

    Returns {evaluated_at, scan_id, snapshot_ts, market_state, global_gates,
    candidates: [{symbol, eligible, failed_gates, gates, sizing, ...}]}
    and persists the evaluation durably for the UI.
    """
    settings = store.get_settings()

    from phase15_scan_context import build_scan_context
    ctx = build_scan_context()

    from market_hours import market_status
    mstat = market_status()
    mstate = str(mstat.get("state") or mstat.get("market_state") or "").upper()

    from scan_state_store import load_latest_meta
    meta = load_latest_meta() or {}

    # ── Global gates (apply to every candidate) ──────────────────────────────
    global_gates: List[Dict[str, Any]] = []
    provider = str(meta.get("provider") or "").lower()
    scan_ok = bool(ctx.get("available"))
    stale = bool(ctx.get("stale", True))
    consistency_pass = scan_ok and meta.get("scan_id") == ctx.get("scan_id")

    global_gates.append(_gate(
        "scan_fresh", scan_ok and not stale,
        f"Scan age {ctx.get('scan_age_seconds')}s (stale after "
        f"{ctx.get('stale_after_seconds')}s)" if scan_ok else "No scan available"))
    global_gates.append(_gate(
        "snapshot_consistency", consistency_pass,
        f"Durable meta scan_id={meta.get('scan_id')} vs snapshot "
        f"scan_id={ctx.get('scan_id')}"))
    provider_is_zerodha = (
        any(p in provider for p in ZERODHA_PROVIDERS)
        and "not configured" not in provider
        and "yahoo" not in provider
        and "fallback" not in provider
        and "mock" not in provider
    )
    global_gates.append(_gate(
        "provider_zerodha", provider_is_zerodha,
        f"Data provider is '{meta.get('provider')}'"))
    global_gates.append(_gate(
        "no_fallback_data",
        provider != "" and "mock" not in provider and "fallback" not in provider,
        f"Provider '{meta.get('provider')}' must not be fallback/mock"))
    global_gates.append(_gate(
        "market_open", mstate == "OPEN", f"Market state is {mstate or 'UNKNOWN'}"))

    global_pass = all(g["passed"] for g in global_gates)

    # ── Portfolio state ──────────────────────────────────────────────────────
    from paper_trader import _load_state, get_portfolio
    state = _load_state()
    portfolio = get_portfolio()
    cash = float(portfolio["cash"])
    total_value = float(portfolio["total_value"]) or 1.0
    invested = float(portfolio["invested_value"])
    positions = {str(p["symbol"]).upper(): p for p in portfolio["positions"]}

    today = datetime.now(timezone.utc).date().isoformat()
    ledger_today = 0
    recent_by_symbol: Dict[str, str] = {}
    try:
        from phase20_executor import get_ledger
        for t in get_ledger(200):
            if str(t.get("simulated_order_ts") or "").startswith(today):
                ledger_today += 1
            sym = str(t.get("symbol") or "").upper()
            ts = str(t.get("simulated_order_ts") or "")
            if sym and ts > recent_by_symbol.get(sym, ""):
                recent_by_symbol[sym] = ts
    except Exception:
        pass

    daily_pnl = sum(float(t.get("pnl") or 0) for t in state.get("trades", [])
                    if t.get("action") == "SELL"
                    and str(t.get("timestamp", "")).startswith(today))
    daily_loss_limit = total_value * float(settings["daily_loss_limit_pct"]) / 100.0

    symbols_ctx: Dict[str, Any] = ctx.get("symbols") or {}
    if candidate_symbols:
        pool = [s.upper() for s in candidate_symbols]
    else:
        pool = [s for s, r in symbols_ctx.items()
                if str(r.get("final_action") or "").upper() in ("BUY", "STRONG BUY")]

    candidates: List[Dict[str, Any]] = []
    for sym in pool:
        rec = symbols_ctx.get(sym) or {}
        gates: List[Dict[str, Any]] = list(global_gates)

        action = str(rec.get("final_action") or "").upper()
        entry = float(rec.get("entry_price") or 0)
        stop = float(rec.get("stop_loss") or 0)
        target = float(rec.get("target_price") or 0)
        rr = float(rec.get("rr_ratio") or 0)
        conf = float(rec.get("confidence") or 0)
        opp = float(rec.get("opportunity_score") or 0)
        quality = float(rec.get("technical_score") or 0)
        dq = str(rec.get("data_quality") or "").upper()

        gates.append(_gate(
            "quote_available", entry > 0 and dq in ("LIVE", "NEAR_LIVE") and not rec.get("error"),
            f"data_quality={dq or 'UNKNOWN'}, entry_price={entry}"))
        gates.append(_gate(
            "strategy_regime_eligible", bool(rec.get("all_gates_passed")),
            f"Scanner strategy/regime gates "
            f"{'passed' if rec.get('all_gates_passed') else 'failed'} "
            f"(strategy={rec.get('strategy_name')}, regime={rec.get('regime')})"))
        gates.append(_gate(
            "recommendation_buy", action in ("BUY", "STRONG BUY"),
            f"Recommendation is {action or 'NONE'}"))
        gates.append(_gate(
            "min_confidence", conf >= float(settings["min_confidence"]),
            f"Confidence {conf} vs minimum {settings['min_confidence']}"))
        gates.append(_gate(
            "min_opportunity_score", opp >= float(settings["min_opportunity_score"]),
            f"Opportunity score {opp} vs minimum {settings['min_opportunity_score']}"))
        gates.append(_gate(
            "min_trade_quality", quality >= float(settings["min_trade_quality_score"]),
            f"Trade-quality (technical) score {quality} vs minimum "
            f"{settings['min_trade_quality_score']}"))
        gates.append(_gate(
            "min_risk_reward", rr >= float(settings["min_risk_reward"]),
            f"R:R {rr} vs minimum {settings['min_risk_reward']}"))
        gates.append(_gate(
            "valid_stop_loss", 0 < stop < entry,
            f"Stop ₹{stop} vs entry ₹{entry}"))

        # Position sizing from the configured risk budget.
        risk_budget = total_value * float(settings["risk_per_trade_pct"]) / 100.0
        risk_per_share = entry - stop if 0 < stop < entry else 0.0
        qty = 0
        if risk_per_share > 0 and entry > 0:
            qty = min(int(risk_budget // risk_per_share), int(cash // entry))
            qty = max(qty, 0)
        position_value = qty * entry
        gates.append(_gate(
            "position_size", qty >= 1,
            f"Risk budget ₹{risk_budget:.2f} / stop distance ₹{risk_per_share:.2f} "
            f"and cash ₹{cash:.2f} size {qty} share(s)"))
        gates.append(_gate(
            "sufficient_cash", qty >= 1 and cash >= position_value > 0,
            f"Cash ₹{cash:.2f} vs position ₹{position_value:.2f}"))

        per_stock_cap = float(settings["per_stock_exposure_cap_pct"])
        existing_value = 0.0
        if sym in positions:
            p = positions[sym]
            existing_value = float(p["quantity"]) * float(p["current_price"])
        stock_pct = (existing_value + position_value) / total_value * 100.0
        gates.append(_gate(
            "per_stock_cap", stock_pct <= per_stock_cap,
            f"Post-trade {sym} exposure {stock_pct:.1f}% (cap {per_stock_cap}%)"))

        sector = rec.get("sector") or _sector_of(sym)
        sector_value = sum(float(p["quantity"]) * float(p["current_price"])
                           for p in portfolio["positions"]
                           if _sector_of(str(p["symbol"])) == sector) + position_value
        sector_pct = sector_value / total_value * 100.0
        gates.append(_gate(
            "sector_cap", sector_pct <= float(settings["sector_exposure_cap_pct"]),
            f"Post-trade {sector} exposure {sector_pct:.1f}% "
            f"(cap {settings['sector_exposure_cap_pct']}%)"))

        deployed_pct = (invested + position_value) / total_value * 100.0
        gates.append(_gate(
            "portfolio_deployed_cap",
            deployed_pct <= float(settings["portfolio_deployed_cap_pct"]),
            f"Post-trade deployed {deployed_pct:.1f}% "
            f"(cap {settings['portfolio_deployed_cap_pct']}%)"))

        gates.append(_gate(
            "daily_loss_limit", daily_pnl > -daily_loss_limit,
            f"Realised P&L today ₹{daily_pnl:.2f} vs limit -₹{daily_loss_limit:.2f}"))
        gates.append(_gate(
            "daily_trade_limit", ledger_today < int(settings["max_trades_per_day"]),
            f"{ledger_today} paper trade(s) today (limit "
            f"{settings['max_trades_per_day']})"))
        gates.append(_gate(
            "no_open_duplicate", sym not in positions,
            f"{'Open position exists' if sym in positions else 'No open position'} in {sym}"))

        cooldown_min = float(settings["cooldown_minutes"])
        cooldown_ok = True
        last_ts = recent_by_symbol.get(sym)
        if last_ts:
            try:
                last_dt = datetime.fromisoformat(last_ts.replace("Z", "+00:00"))
                age_min = (datetime.now(timezone.utc) - last_dt).total_seconds() / 60.0
                cooldown_ok = age_min >= cooldown_min
            except Exception:
                cooldown_ok = True
        gates.append(_gate(
            "cooldown", cooldown_ok,
            f"Last {sym} paper entry at {last_ts or 'never'} "
            f"(cooldown {cooldown_min:.0f}m)"))

        failed = [g["gate"] for g in gates if not g["passed"]]
        candidates.append({
            "symbol": sym,
            "sector": sector,
            "recommendation": action,
            "eligible": len(failed) == 0,
            "failed_gates": failed,
            "gates": gates,
            "sizing": {
                "quantity": qty,
                "entry_price": entry,
                "stop_loss": stop,
                "target_price": target,
                "position_value": round(position_value, 2),
                "risk_amount": round(qty * risk_per_share, 2),
                "rr_ratio": rr,
            },
            "confidence": conf,
            "opportunity_score": opp,
            "trade_quality_score": quality,
            "strategy_id": rec.get("strategy_id"),
            "strategy_name": rec.get("strategy_name"),
            "regime": rec.get("regime"),
            "expected_holding_days": rec.get("expected_holding_days"),
        })

    evaluation = {
        "evaluated_at": _now_iso(),
        "scan_id": ctx.get("scan_id"),
        "snapshot_ts": ctx.get("snapshot_ts"),
        "market_state": mstate,
        "settings_config_hash": settings.get("config_hash"),
        "global_gates": global_gates,
        "global_pass": global_pass,
        "candidates": candidates,
        "eligible_count": sum(1 for c in candidates if c["eligible"]),
        "blocked_count": sum(1 for c in candidates if not c["eligible"]),
        "label": "PAPER / RESEARCH ONLY",
    }
    try:
        store.kv_set("last_entry_evaluation", evaluation)
        counters = store.kv_get("entry_eval_counters", {}) or {}
        counters["evaluated"] = int(counters.get("evaluated", 0)) + len(candidates)
        counters["passed"] = int(counters.get("passed", 0)) + evaluation["eligible_count"]
        counters["blocked"] = int(counters.get("blocked", 0)) + evaluation["blocked_count"]
        store.kv_set("entry_eval_counters", counters)
    except Exception:
        pass
    return evaluation


def get_last_evaluation() -> Optional[Dict[str, Any]]:
    return store.kv_get("last_entry_evaluation")
