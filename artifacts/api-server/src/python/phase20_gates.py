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
    universe_context = dict(meta.get("universe_context") or {})
    required_universe_fields = (
        "natural_session", "universe_key", "universe_id", "version",
        "exact_set_hash", "symbol_count",
    )
    universe_complete = all(
        universe_context.get(field) not in (None, "")
        for field in required_universe_fields
    )
    global_gates.append(_gate(
        "pinned_universe_provenance",
        universe_complete,
        ("Pinned universe provenance is complete"
         if universe_complete else
         "Pinned universe provenance is unavailable or incomplete — entries blocked"),
    ))
    # Structured provider flags from the canonical snapshot (authoritative),
    # with the string label as a defensive second check. Auto paper entries
    # may run ONLY on the intended Zerodha-connected provider — a Yahoo-only
    # fallback scan must never create entries.
    kite_connected = False
    snap_label = ""
    try:
        from scan_state_store import load_latest_snapshot
        _snap = load_latest_snapshot() or {}
        _safety = _snap.get("safety") or {}
        # Structured flag only counts for the SAME scan the meta points at.
        if _snap.get("scan_id") == meta.get("scan_id"):
            kite_connected = bool(_safety.get("kite_connected"))
            snap_label = str(_safety.get("data_provider") or "").lower()
    except Exception:
        pass
    label = snap_label or provider
    label_is_zerodha = (
        any(p in label for p in ZERODHA_PROVIDERS)
        and "not configured" not in label
        and "login required" not in label
        and "fallback" not in label
        and "mock" not in label
    )
    provider_is_zerodha = kite_connected and label_is_zerodha
    # ── Provider quality gates ──────────────────────────────────────────────
    # For LIVE orders, Kite/Zerodha is mandatory.
    # For PAPER-ONLY trading, any provider that delivers LIVE-quality data
    # is acceptable.  Yahoo Finance delivers intraday LIVE quotes; the
    # "Zerodha login required" label is informational (it means Kite is not
    # configured), NOT an indicator of stale or degraded data.
    #
    # Gate passes when EITHER:
    #   a) Zerodha is connected (best), OR
    #   b) The scan has ≥ 1 LIVE-quality symbol (Yahoo live is acceptable
    #      for paper trading)
    live_symbol_count = 0
    try:
        from scan_state_store import load_latest_snapshot as _lsnap
        _full = _lsnap() or {}
        if _full.get("scan_id") == meta.get("scan_id"):
            _dqb = (_full.get("summary") or {}).get("data_quality_breakdown") or {}
            live_symbol_count = int(_dqb.get("LIVE", 0)) + int(_dqb.get("NEAR_LIVE", 0))
    except Exception:
        pass
    live_data_ok = live_symbol_count > 0
    provider_ok = provider_is_zerodha or live_data_ok

    global_gates.append(_gate(
        "provider_zerodha",
        provider_ok,
        f"kite_connected={kite_connected}, live_symbols={live_symbol_count}, "
        f"provider='{meta.get('provider')}'"))

    # Truly degraded providers: mock / explicit fallback / completely unconfigured.
    # Yahoo Finance with "login required" is NOT degraded — it is delivering
    # live market data; the annotation only means Kite is absent.
    _raw_label = meta.get("provider", "") or ""
    _is_degraded = (
        label == ""
        or "mock" in label
        or "fallback" in label
        or ("not configured" in label and "login required" not in label)
    )
    global_gates.append(_gate(
        "no_fallback_data",
        not _is_degraded,
        f"Provider '{_raw_label}' {'is degraded/mock/fallback' if _is_degraded else 'delivers live data'}"))
    global_gates.append(_gate(
        "market_open", mstate == "OPEN", f"Market state is {mstate or 'UNKNOWN'}"))
    # Circuit breaker: entries pause on losing streaks / daily loss / negative
    # rolling expectancy until MANUAL review. Exits/monitoring are unaffected.
    try:
        from phase20_circuit_breaker import get_state as _cb_state
        _cb = _cb_state()
        _cb_reason = ("; ".join(r.get("detail", r.get("code", "?"))
                                for r in (_cb.get("reasons") or []))
                      if _cb.get("tripped") else "Not tripped")
        global_gates.append(_gate(
            "entry_circuit_breaker", not _cb.get("tripped"),
            f"Circuit breaker {'TRIPPED — manual review required' if _cb.get('tripped') else 'clear'}: {_cb_reason}"))
    except Exception:
        global_gates.append(_gate(
            "entry_circuit_breaker", False,
            "Circuit breaker state unavailable — entries blocked (fail-safe)"))

    # V4.3 — Research availability gate (fail-closed mode enforcement).
    # This gate only fails when the operator has chosen "fail_closed" AND every
    # research source failed in the most recent Research Agent cycle.
    # Under "fail_open" (default) the gate always passes — the pipeline
    # continues on market-data signals regardless of research health.
    _research_halted = False
    _research_mode_str = "NORMAL"
    try:
        _mode_info = store.kv_get("research_agent_mode") or {}
        _research_mode_str = str(_mode_info.get("mode", "NORMAL"))
        _failure_mode = str(settings.get("research_failure_mode", "fail_open"))
        _research_halted = (
            _research_mode_str == "PIPELINE_HALTED"
            and _failure_mode == "fail_closed"
        )
    except Exception:
        pass  # KV unavailable → gate passes (fail-open is the safe default)
    global_gates.append(_gate(
        "research_available",
        not _research_halted,
        f"Research mode: {_research_mode_str}"
        + (" — all sources failed, entries paused (fail-closed)" if _research_halted
           else " (pipeline continues)")))

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

    # Quality-allocation evidence is advisory to the NORMAL gate path: cache or
    # history failures can only deny 2x/3x and must never break 1x evaluation.
    cache_status: Dict[str, Dict[str, Any]] = {}
    try:
        from ohlcv_cache_store import get_cache_status
        cache_status = get_cache_status(pool)
    except Exception:
        cache_status = {}
    try:
        allocation_history = store.kv_get("allocation_override_history") or []
    except Exception:
        allocation_history = []

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
        existing_sector_value = sum(
            float(p["quantity"]) * float(p["current_price"])
            for p in portfolio["positions"]
            if _sector_of(str(p["symbol"])) == sector
        )
        sector_value = existing_sector_value + position_value
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

        # ── V4.3 risk-tuning gates ────────────────────────────────────────────
        # All setting reads use safe_int() / safe_float() helpers to guard
        # against malformed or legacy persisted values that predate validation.
        # On any conversion error the gate is silently disabled (conservative
        # fail-safe: skip the gate rather than crash entry evaluation).

        def _safe_int(raw, default: int = 0) -> int:
            """Convert raw to int; return default on any error."""
            try:
                fv = float(raw)
                return int(fv) if fv == int(fv) else default
            except (TypeError, ValueError):
                return default

        def _safe_float(raw, default: float = 0.0) -> float:
            """Convert raw to float; return default on any error."""
            try:
                return float(raw)
            except (TypeError, ValueError):
                return default

        # max_concurrent_positions: cap how many open paper positions may exist
        # across the portfolio at once.  0 = feature disabled.
        max_conc = _safe_int(settings.get("max_concurrent_positions"), default=0)
        open_count = len(positions)
        if max_conc > 0:
            # A candidate that would open a new position fails when we are
            # already AT the limit (not strictly over it).
            conc_ok = sym in positions or open_count < max_conc
            gates.append(_gate(
                "max_concurrent_positions",
                conc_ok,
                f"Open positions: {open_count} vs max {max_conc}"
                + (" (adding to existing position)" if sym in positions else "")))

        # min_liquidity_filter: minimum average daily volume (thousands of
        # shares).  Reads the 'avg_volume' or 'volume' field from the scan
        # record.  If neither is present, the gate passes — data unavailable
        # is not the same as data failing the threshold.
        min_liq = _safe_float(settings.get("min_liquidity_filter"), default=0.0)
        if min_liq > 0:
            # avg_volume is shares/day, min_liquidity_filter is in thousands
            raw_vol = _safe_float(
                rec.get("avg_volume") or rec.get("avg_daily_volume") or
                rec.get("volume") or 0
            )
            if raw_vol > 0:
                vol_k = raw_vol / 1_000.0
                gates.append(_gate(
                    "min_liquidity",
                    vol_k >= min_liq,
                    f"Avg volume {vol_k:.0f}k vs min {min_liq:.0f}k"))
            # When the scanner did not supply volume data the gate is skipped
            # (no false positives on data absence).

        # max_volatility_filter: maximum acceptable ATR as a percentage of
        # current price.  Reads 'atr_pct', 'atr_percent', or computes from
        # 'atr_abs' / entry_price when available.  0 = feature disabled.
        max_vol_f = _safe_float(settings.get("max_volatility_filter"), default=0.0)
        if max_vol_f > 0:
            atr_pct = _safe_float(rec.get("atr_pct") or rec.get("atr_percent") or 0)
            if atr_pct == 0 and entry > 0:
                atr_abs = _safe_float(rec.get("atr_abs") or rec.get("atr") or 0)
                if atr_abs > 0:
                    atr_pct = (atr_abs / entry) * 100.0
            if atr_pct > 0:
                gates.append(_gate(
                    "max_volatility",
                    atr_pct <= max_vol_f,
                    f"ATR {atr_pct:.2f}% vs max {max_vol_f:.2f}%"))
            # When ATR is not in the scan record, the gate is skipped.

        failed = [g["gate"] for g in gates if not g["passed"]]
        cache_info = cache_status.get(sym, {})
        cache_quality = str(cache_info.get("data_quality") or "").upper()
        atr_pct: Optional[float] = None
        try:
            from ohlcv_cache_store import read_symbol_from_cache
            cached_bars = read_symbol_from_cache(sym, min_bars=20)
            if cached_bars is not None and len(cached_bars) >= 15:
                prev_close = cached_bars["close"].shift(1)
                true_range = (
                    (cached_bars["high"] - cached_bars["low"]).abs()
                    .to_frame("high_low")
                )
                true_range["high_prev_close"] = (
                    cached_bars["high"] - prev_close
                ).abs()
                true_range["low_prev_close"] = (
                    cached_bars["low"] - prev_close
                ).abs()
                atr = float(true_range.max(axis=1).tail(14).mean())
                last_close = float(cached_bars["close"].iloc[-1])
                if atr > 0 and last_close > 0:
                    atr_pct = round(atr / last_close * 100.0, 4)
        except Exception:
            atr_pct = None

        candidate = {
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
            "data_quality": dq,
            "kite_ltp": rec.get("kite_ltp"),
            "kite_ltp_available": bool(rec.get("kite_ltp_available")),
            "kite_session_verified_flag": bool(
                rec.get("kite_session_verified_flag")
            ),
            "kite_ltp_overlay_enabled": bool(
                rec.get("kite_ltp_overlay_enabled")
            ),
            "current_price_source": rec.get("current_price_source"),
            "execution_price_source": rec.get("execution_price_source"),
            "quote_reliable": bool(rec.get("quote_reliable")),
            "indicator_source": rec.get("indicator_source"),
            "ohlcv_source": rec.get("ohlcv_source"),
            "yfinance_last_close": rec.get("yfinance_last_close"),
            "reason_not_live_ltp": rec.get("reason_not_live_ltp"),
            "latest_price_time_ist": rec.get("latest_price_time_ist"),
            # Preserve the exact scan envelope through gate evaluation; entry
            # execution must never reconstruct this from a newer cache.
            "universe_context": dict(rec.get("universe_context") or {}),
            "allocation_context": {
                "total_capital": total_value,
                "cash": cash,
                "invested_value": invested,
                "existing_stock_value": existing_value,
                "existing_sector_value": existing_sector_value,
                "daily_realized_pnl": daily_pnl,
                "risk_per_trade_pct": float(settings["risk_per_trade_pct"]),
                "normal_risk_budget_pct": float(settings["risk_per_trade_pct"]),
                "ohlcv_cache_hit": bool(cache_info.get("cached")),
                "ohlcv_cache_fresh": (
                    bool(cache_info.get("cached"))
                    and cache_quality in ("LIVE", "NEAR_LIVE")
                    and not bool(cache_info.get("missing_required"))
                ),
                "ohlcv_cache_data_quality": cache_quality,
                "ohlcv_cache_latest_date": cache_info.get("latest_date"),
                "ohlcv_cache_age_days": cache_info.get("age_days"),
                "atr_pct": atr_pct,
                "stale_or_blocked_close_warning": bool(
                    ctx.get("stale")
                    or rec.get("error")
                    or dq not in ("LIVE", "NEAR_LIVE")
                    or rec.get("reason_not_live_ltp")
                ),
            },
        }
        try:
            from quality_allocation_override import (
                evaluate_allocation_override,
                previous_scan_3x_valid,
            )
            previous_valid = previous_scan_3x_valid(
                allocation_history, ctx.get("scan_id"), sym
            )
            candidate["allocation_context"][
                "previous_scan_3x_valid"
            ] = previous_valid
            preview_price = float(candidate.get("kite_ltp") or entry)
            candidate["allocation_override_preview"] = (
                evaluate_allocation_override(
                    candidate,
                    settings,
                    preview_price,
                    previous_scan_valid=previous_valid,
                    trigger_source="AUTO",
                )
            )
        except Exception as exc:
            candidate["allocation_override_preview"] = {
                "policy": "QUALITY_ALLOCATION_OVERRIDE",
                "tier": "NORMAL",
                "requested_multiplier": 1.0,
                "effective_multiplier": 1.0,
                "override_approved": False,
                "reason": (
                    "ALLOCATION_EVALUATOR_UNAVAILABLE: "
                    f"{type(exc).__name__}"
                ),
                "paper_only": True,
                "live_broker_orders_called": False,
            }
        candidates.append(candidate)

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
        # Append lightweight summary to evaluation_history (dedup by scan_id, max 60)
        _gate_blocked: Dict[str, int] = {}
        _blocked_symbols: List[str] = []
        for _c in candidates:
            _sym_blocked = False
            for _g in _c.get("gates", []):
                if not _g["passed"]:
                    _gate_blocked[_g["gate"]] = _gate_blocked.get(_g["gate"], 0) + 1
                    _sym_blocked = True
            if _sym_blocked:
                _sym = _c.get("symbol")
                if _sym:
                    _blocked_symbols.append(_sym)
        _hist: List[Dict[str, Any]] = store.kv_get("evaluation_history") or []
        _scan_id = evaluation.get("scan_id")
        if not _hist or _hist[-1].get("scan_id") != _scan_id:
            _hist.append({
                "evaluated_at": evaluation["evaluated_at"],
                "scan_id": _scan_id,
                "total_count": len(candidates),
                "blocked_count": evaluation["blocked_count"],
                "gate_blocked_counts": _gate_blocked,
            })
            store.kv_set("evaluation_history", _hist[-60:])
        # ── Per-symbol consecutive-block history (canonical pipeline only) ───
        # Only written when this is the default BUY-candidate evaluation
        # (candidate_symbols is None).  Ad-hoc callers (gate_rejection_audit,
        # phase24 missed-opportunity analysis) pass an explicit symbol list and
        # must NOT pollute this key — they evaluate all symbols, not just the
        # current BUY candidates, and the scan-id dedup would otherwise let a
        # non-BUY audit invocation win the slot and report a misleading streak.
        if candidate_symbols is None:
            _bp_hist: List[Dict[str, Any]] = (
                store.kv_get("buy_pipeline_eval_history") or []
            )
            if not _bp_hist or _bp_hist[-1].get("scan_id") != _scan_id:
                _bp_hist.append({
                    "evaluated_at": evaluation["evaluated_at"],
                    "scan_id": _scan_id,
                    "blocked_symbols": _blocked_symbols,
                })
                store.kv_set("buy_pipeline_eval_history", _bp_hist[-60:])
        # Structured pipeline cycle log (P8 — per-cycle structured audit trail)
        try:
            _cycle_log: List[Dict[str, Any]] = store.kv_get("pipeline_cycle_log") or []
            _cycle_entry: Dict[str, Any] = {
                "pipeline_id":          evaluation.get("scan_id") or "—",
                "scan_id":              evaluation.get("scan_id"),
                "snapshot_ts":          evaluation.get("snapshot_ts"),
                "start_time":           evaluation["evaluated_at"],
                "end_time":             _now_iso(),
                "market_state":         evaluation["market_state"],
                "global_pass":          evaluation["global_pass"],
                "global_gate_failures": [
                    g["gate"] for g in evaluation.get("global_gates", [])
                    if not g["passed"]
                ],
                "agents": {
                    "risk": {
                        "status":        "OK" if evaluation["global_pass"] else "BLOCKED",
                        "input_count":   len(candidates),
                        "output_count":  evaluation["eligible_count"],
                        "reject_count":  evaluation["blocked_count"],
                        "execution_time_ms": None,
                    },
                },
                "candidates_total":    len(candidates),
                "candidates_eligible": evaluation["eligible_count"],
                "candidates_blocked":  evaluation["blocked_count"],
                "top_blockers": sorted(
                    _gate_blocked.items(), key=lambda x: x[1], reverse=True
                )[:5],
            }
            _cycle_log.append(_cycle_entry)
            store.kv_set("pipeline_cycle_log", _cycle_log[-50:])  # keep last 50
        except Exception:
            pass
        # Track rejected candidates for V3 analytics
        try:
            from phase20_v3_analytics import record_rejections
            record_rejections(evaluation)
        except Exception:
            pass
    except Exception:
        pass
    return evaluation


def get_last_evaluation() -> Optional[Dict[str, Any]]:
    return store.kv_get("last_entry_evaluation")


# ── V4.3 Risk Audit ───────────────────────────────────────────────────────────

def build_risk_audit() -> Dict[str, Any]:
    """
    Return a structured risk-rule manifest for every BUY/STRONG BUY candidate
    in the current scan.  Each rule record shows:

        rule_id   — gate identifier
        label     — human-readable gate name
        scope     — "global" (applies to all) or "per_symbol"
        required  — threshold / expected value (string, for display)
        actual    — the value observed for this candidate
        unit      — "%", "×", "₹", "mins", "bool", …
        passed    — True / False

    Falls back to ``risk_decision_report()`` so that existing cached
    evaluation data is re-used without re-running the scan.

    READ-ONLY · ADVISORY ONLY · PAPER TRADING
    """
    settings = store.get_settings()

    # Reuse the enriched report (avoids a redundant evaluate_entries() call).
    report = risk_decision_report()
    if not report.get("available"):
        return {
            "available": False,
            "reason": report.get("reason", "No evaluation data"),
            "generated_at": _now_iso(),
        }

    candidates: List[Dict[str, Any]] = report.get("candidates") or []
    global_gates: List[Dict[str, Any]] = report.get("global_gates") or []

    # ── Global rule manifest ─────────────────────────────────────────────────
    # The following rules apply identically to all candidates.
    global_rule_meta = [
        ("scan_fresh",            "Scan Freshness",        "bool",  "fresh",     "global"),
        ("snapshot_consistency",  "Snapshot Consistency",  "bool",  "match",     "global"),
        ("provider_zerodha",      "Data Provider OK",      "bool",  "live",      "global"),
        ("no_fallback_data",      "No Fallback Data",      "bool",  "live",      "global"),
        ("market_open",           "Market Open",           "bool",  "OPEN",      "global"),
        ("entry_circuit_breaker", "Circuit Breaker",       "bool",  "clear",     "global"),
        ("research_available",    "Research Pipeline",     "bool",  "available", "global"),
    ]

    # Build a lookup for actual gate outcomes from the first candidate
    # (global gates are identical for all candidates).
    _global_lookup: Dict[str, Dict[str, Any]] = {}
    if candidates:
        for g in candidates[0].get("gates", []):
            if g.get("gate") in {r[0] for r in global_rule_meta}:
                _global_lookup[g["gate"]] = g
    # Also use global_gates list from the report directly
    for g in global_gates:
        _global_lookup[g["gate"]] = g

    global_manifest: List[Dict[str, Any]] = []
    for rule_id, label, unit, required, scope in global_rule_meta:
        gate_data = _global_lookup.get(rule_id, {})
        global_manifest.append({
            "rule_id":  rule_id,
            "label":    label,
            "scope":    scope,
            "required": required,
            "actual":   gate_data.get("reason", "—"),
            "unit":     unit,
            "passed":   gate_data.get("passed", False),
        })

    # ── Per-symbol threshold manifest ────────────────────────────────────────
    # Build from settings so operators can compare required vs actual for each
    # candidate at a glance.
    per_symbol_rules = [
        # (gate_id, label, unit, setting_key, always_applicable)
        # always_applicable=True  → gate always runs; missing from gate_lookup is a bug.
        # always_applicable=False → gate is conditional (disabled when setting=0 or
        #                           data absent); missing from gate_lookup is expected
        #                           and must not default to failed.
        ("min_confidence",          "Min Confidence",          "%",      "min_confidence",             True),
        ("min_opportunity_score",   "Min Opportunity",         "score",  "min_opportunity_score",      True),
        ("min_trade_quality",       "Min Trade Quality",       "score",  "min_trade_quality_score",    True),
        ("min_risk_reward",         "Min Risk/Reward",         "×",      "min_risk_reward",            True),
        ("valid_stop_loss",         "Valid Stop-Loss",         "bool",   None,                         True),
        ("position_size",           "Position Sizing",         "qty",    None,                         True),
        ("sufficient_cash",         "Sufficient Cash",         "₹",      None,                         True),
        ("per_stock_cap",           "Per-Stock Cap",           "%",      "per_stock_exposure_cap_pct", True),
        ("sector_cap",              "Sector Cap",              "%",      "sector_exposure_cap_pct",    True),
        ("portfolio_deployed_cap",  "Portfolio Cap",           "%",      "portfolio_deployed_cap_pct", True),
        ("daily_loss_limit",        "Daily Loss Limit",        "%",      "daily_loss_limit_pct",       True),
        ("daily_trade_limit",       "Daily Trade Limit",       "count",  "max_trades_per_day",         True),
        ("no_open_duplicate",       "No Duplicate Trade",      "bool",   None,                         True),
        ("cooldown",                "Symbol Cooldown",         "mins",   "cooldown_minutes",           True),
        # V4.3 risk-tuning — conditional: only evaluated when setting > 0 AND
        # the required scan data is available.  always_applicable=False.
        ("max_concurrent_positions","Max Concurrent Positions","count",  "max_concurrent_positions",   False),
        ("min_liquidity",           "Min Liquidity (vol/day)", "k-shr",  "min_liquidity_filter",       False),
        ("max_volatility",          "Max Volatility (ATR%)",   "%",      "max_volatility_filter",      False),
    ]

    # Determine which V4.3 gates could possibly be active given current settings.
    # Use safe conversions in case persisted values predate validation.
    def _safe_pos_int(raw, default=0) -> int:
        try:
            fv = float(raw)
            return max(0, int(fv))
        except (TypeError, ValueError):
            return default

    def _safe_pos_float(raw, default=0.0) -> float:
        try:
            return max(0.0, float(raw))
        except (TypeError, ValueError):
            return default

    _conc_enabled = _safe_pos_int(settings.get("max_concurrent_positions")) > 0
    _liq_enabled  = _safe_pos_float(settings.get("min_liquidity_filter")) > 0
    _vol_enabled  = _safe_pos_float(settings.get("max_volatility_filter")) > 0.0

    # For each candidate, attach a structured rule_manifest.
    # Rules that are not applicable (disabled by setting OR conditionally skipped
    # due to absent scan data) are included in the manifest with
    # ``applicable: false`` so the UI can render them visually distinct, but they
    # are EXCLUDED from total_checks and failed_rule_checks so they cannot corrupt
    # the pass_rate or verdict.
    enriched_candidates: List[Dict[str, Any]] = []
    for c in candidates:
        gate_lookup: Dict[str, Dict[str, Any]] = {
            g["gate"]: g for g in c.get("gates", [])
        }
        candidate_rules: List[Dict[str, Any]] = []
        for rule_id, label, unit, setting_key, always_applicable in per_symbol_rules:
            gate_data = gate_lookup.get(rule_id)
            required_val = (
                str(settings.get(setting_key, "—"))
                if setting_key and setting_key in settings
                else "—"
            )

            if gate_data is not None:
                # Gate was evaluated — applicable regardless of always_applicable flag.
                candidate_rules.append({
                    "rule_id":    rule_id,
                    "label":      label,
                    "scope":      "per_symbol",
                    "required":   required_val,
                    "actual":     gate_data.get("reason", "—"),
                    "unit":       unit,
                    "passed":     gate_data.get("passed", False),
                    "applicable": True,
                })
            elif always_applicable:
                # Gate should always be present but isn't — treat as failed (data
                # issue or evaluation gap) so it surfaces in the audit.
                candidate_rules.append({
                    "rule_id":    rule_id,
                    "label":      label,
                    "scope":      "per_symbol",
                    "required":   required_val,
                    "actual":     "not evaluated",
                    "unit":       unit,
                    "passed":     False,
                    "applicable": True,
                })
            else:
                # Conditional gate that was legitimately skipped.
                # Determine the reason so the UI can explain it clearly.
                if rule_id == "max_concurrent_positions" and not _conc_enabled:
                    skip_reason = "disabled (setting = 0)"
                elif rule_id == "min_liquidity" and not _liq_enabled:
                    skip_reason = "disabled (setting = 0)"
                elif rule_id == "max_volatility" and not _vol_enabled:
                    skip_reason = "disabled (setting = 0.0)"
                else:
                    skip_reason = "skipped — required data not in scan record"
                candidate_rules.append({
                    "rule_id":    rule_id,
                    "label":      label,
                    "scope":      "per_symbol",
                    "required":   required_val,
                    "actual":     skip_reason,
                    "unit":       unit,
                    "passed":     True,   # not-applicable is not a failure
                    "applicable": False,
                })
        enriched_candidates.append({
            **c,
            "rule_manifest": candidate_rules,
        })

    # ── Summary metrics — applicable rules only ───────────────────────────────
    # Disabled / data-absent gates are excluded so they cannot inflate
    # failed_rule_checks or deflate pass_rate.
    total_checks   = (
        sum(1 for r in global_manifest if r.get("applicable", True))
        + sum(
            1 for c in enriched_candidates
            for r in c.get("rule_manifest", []) if r.get("applicable", True)
        )
    )
    failed_checks  = (
        sum(1 for r in global_manifest if r.get("applicable", True) and not r["passed"])
        + sum(
            1 for c in enriched_candidates
            for r in c.get("rule_manifest", [])
            if r.get("applicable", True) and not r["passed"]
        )
    )

    return {
        "available":         True,
        "generated_at":      _now_iso(),
        "evaluated_at":      report.get("evaluated_at"),
        "scan_id":           report.get("scan_id"),
        "snapshot_ts":       report.get("snapshot_ts"),
        "market_state":      report.get("market_state"),
        "label":             "PAPER / RESEARCH ONLY",
        "global_manifest":   global_manifest,
        "global_pass":       report.get("global_pass", False),
        "candidates":        enriched_candidates,
        "total_count":       len(enriched_candidates),
        "eligible_count":    report.get("eligible_count", 0),
        "blocked_count":     report.get("blocked_count", 0),
        "gate_pressure":     report.get("gate_pressure", []),
        "top_blockers":      report.get("top_blockers", []),
        "total_rule_checks": total_checks,
        "failed_rule_checks": failed_checks,
        "pass_rate":         round(
            (total_checks - failed_checks) / total_checks * 100, 1
        ) if total_checks else 100.0,
        # Current threshold snapshot so the UI can render a compact rule legend
        "thresholds": {
            "min_confidence":          settings.get("min_confidence", 60),
            "min_opportunity_score":   settings.get("min_opportunity_score", 60),
            "min_trade_quality_score": settings.get("min_trade_quality_score", 50),
            "min_risk_reward":         settings.get("min_risk_reward", 2.0),
            "per_stock_exposure_cap_pct": settings.get("per_stock_exposure_cap_pct", 25),
            "sector_exposure_cap_pct":    settings.get("sector_exposure_cap_pct", 40),
            "portfolio_deployed_cap_pct": settings.get("portfolio_deployed_cap_pct", 80),
            "daily_loss_limit_pct":       settings.get("daily_loss_limit_pct", 3.0),
            "max_trades_per_day":         settings.get("max_trades_per_day", 3),
            "cooldown_minutes":           settings.get("cooldown_minutes", 30),
            "max_concurrent_positions":   settings.get("max_concurrent_positions", 5),
            "min_liquidity_filter":       settings.get("min_liquidity_filter", 0),
            "max_volatility_filter":      settings.get("max_volatility_filter", 0.0),
        },
    }


# ── Human-readable gate metadata ─────────────────────────────────────────────

_GATE_META: Dict[str, str] = {
    "scan_fresh":               "Scan Freshness",
    "snapshot_consistency":     "Snapshot Consistency",
    "provider_zerodha":         "Data Provider",
    "no_fallback_data":         "No Fallback/Mock Data",
    "market_open":              "Market Open",
    "entry_circuit_breaker":    "Circuit Breaker",
    "research_available":       "Research Pipeline",       # V4.3
    "quote_available":          "Quote Available",
    "strategy_regime_eligible": "Strategy / Regime",
    "recommendation_buy":       "BUY Recommendation",
    "min_confidence":           "Minimum Confidence",
    "min_opportunity_score":    "Minimum Opportunity Score",
    "min_trade_quality":        "Minimum Trade Quality",
    "min_risk_reward":          "Minimum Risk / Reward",
    "valid_stop_loss":          "Valid Stop-Loss",
    "position_size":            "Position Sizing",
    "sufficient_cash":          "Sufficient Cash",
    "per_stock_cap":            "Per-Stock Exposure Cap",
    "sector_cap":               "Sector Exposure Cap",
    "portfolio_deployed_cap":   "Portfolio Deployed Cap",
    "daily_loss_limit":         "Daily Loss Limit",
    "daily_trade_limit":        "Daily Trade Limit",
    "no_open_duplicate":        "No Duplicate Open Trade",
    "cooldown":                 "Symbol Cooldown",
    "max_concurrent_positions": "Max Concurrent Positions",  # V4.3
    "min_liquidity":            "Min Liquidity",              # V4.3
    "max_volatility":           "Max Volatility (ATR%)",      # V4.3
}

_GLOBAL_GATES = frozenset({
    "scan_fresh", "snapshot_consistency", "provider_zerodha",
    "no_fallback_data", "market_open", "entry_circuit_breaker",
    "research_available",  # V4.3
})


def risk_decision_report() -> Dict[str, Any]:
    """
    Return the last Risk Agent entry evaluation, enriched with:
      • gate_pressure  — per-gate count of blocked candidates, sorted desc
      • top_blockers   — top-3 gates by block count (human labels)

    Falls back to running a fresh evaluate_entries() if no cached evaluation
    exists yet.  Read-only: never modifies positions or triggers a scan.
    """
    evaluation = get_last_evaluation()
    if not evaluation:
        # No prior evaluation — run one now so the page has something to show.
        try:
            evaluation = evaluate_entries()
        except Exception as exc:
            return {
                "available": False,
                "reason": f"No entry evaluation available and fresh run failed: {exc}",
            }

    candidates: List[Dict[str, Any]] = evaluation.get("candidates") or []

    # Count how many candidates each gate blocked (failed).
    pressure: Dict[str, int] = {}
    for c in candidates:
        for g in c.get("gates", []):
            if not g["passed"]:
                gate_id = g["gate"]
                pressure[gate_id] = pressure.get(gate_id, 0) + 1

    gate_pressure = [
        {
            "gate_id":    gid,
            "label":      _GATE_META.get(gid, gid.replace("_", " ").title()),
            "is_global":  gid in _GLOBAL_GATES,
            "blocked":    cnt,
            "blocked_pct": round(cnt / len(candidates) * 100, 1) if candidates else 0,
        }
        for gid, cnt in sorted(pressure.items(), key=lambda x: x[1], reverse=True)
    ]

    top_blockers = [g["label"] for g in gate_pressure[:3]]

    # Annotate each gate in each candidate with its human label.
    for c in candidates:
        for g in c.get("gates", []):
            g["label"] = _GATE_META.get(g["gate"], g["gate"].replace("_", " ").title())
            g["is_global"] = g["gate"] in _GLOBAL_GATES

    # ── History enrichment (Sections 5, 10, 11) ──────────────────────────────
    raw_hist: List[Dict[str, Any]] = store.kv_get("evaluation_history") or []

    # Compute 7-day / 30-day blocked counts + trend per gate
    from datetime import datetime, timedelta, timezone
    now_utc = datetime.now(timezone.utc)
    cutoff_7d  = now_utc - timedelta(days=7)
    cutoff_30d = now_utc - timedelta(days=30)

    def _parse_dt(s: Optional[str]) -> Optional[datetime]:
        if not s:
            return None
        try:
            return datetime.fromisoformat(s.replace("Z", "+00:00"))
        except Exception:
            return None

    for gp in gate_pressure:
        gid = gp["gate_id"]
        cnt_7d, cnt_30d = 0, 0
        recent: List[int] = []  # blocked counts ordered old→new for trend
        for entry in raw_hist:
            dt = _parse_dt(entry.get("evaluated_at"))
            bc = entry.get("gate_blocked_counts", {}).get(gid, 0)
            if dt and dt >= cutoff_30d:
                cnt_30d += bc
                recent.append(bc)
            if dt and dt >= cutoff_7d:
                cnt_7d += bc
        gp["blocked_7d"]  = cnt_7d
        gp["blocked_30d"] = cnt_30d
        # Trend: compare first vs second half of recent entries
        if len(recent) < 4:
            gp["trend"] = "insufficient_data"
        else:
            mid    = len(recent) // 2
            first  = sum(recent[:mid])
            second = sum(recent[mid:])
            if second > first * 1.1:
                gp["trend"] = "increasing"
            elif second < first * 0.9:
                gp["trend"] = "decreasing"
            else:
                gp["trend"] = "stable"

    # Build history timeline for Section 11
    timeline: List[Dict[str, Any]] = []
    seen_dates: set = set()
    for entry in raw_hist:
        dt = _parse_dt(entry.get("evaluated_at"))
        if not dt:
            continue
        date_str = dt.date().isoformat()
        total = int(entry.get("total_count", 0))
        blocked = int(entry.get("blocked_count", 0))
        eligible = total - blocked
        timeline.append({
            "date":           date_str,
            "evaluated_at":   entry.get("evaluated_at"),
            "total_count":    total,
            "blocked_count":  blocked,
            "eligible_count": eligible,
            "pass_rate":      round(eligible / total * 100, 1) if total else 0.0,
        })
        seen_dates.add(date_str)

    history_days = len(seen_dates)

    return {
        "available": True,
        "evaluated_at": evaluation.get("evaluated_at"),
        "scan_id": evaluation.get("scan_id"),
        "snapshot_ts": evaluation.get("snapshot_ts"),
        "market_state": evaluation.get("market_state"),
        "global_gates": [
            {**g, "label": _GATE_META.get(g["gate"], g["gate"])}
            for g in (evaluation.get("global_gates") or [])
        ],
        "global_pass": evaluation.get("global_pass"),
        "candidates": candidates,
        "total_count": len(candidates),
        "eligible_count": evaluation.get("eligible_count", 0),
        "blocked_count": evaluation.get("blocked_count", len(candidates)),
        "gate_pressure": gate_pressure,
        "top_blockers": top_blockers,
        "history_timeline": timeline,
        "history_days": history_days,
        "history_entries": len(raw_hist),
        "label": "PAPER / RESEARCH ONLY",
    }
