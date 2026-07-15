"""
phase11_risk.py — Phase 11: Institutional Risk Engine (research / paper only).

Evaluates every proposed paper trade before execution and provides a
portfolio-level risk view. No real-money execution exists anywhere in
this module.

Components
  1. Pre-trade risk checks (8): max risk per trade, position sizing,
     liquidity, gap risk, sector exposure, stock concentration,
     correlation, portfolio heat.
  2. Portfolio risk dashboard payload.
  3. Dynamic position sizing.
  4. Risk alerts (persisted, deduped).
  5. Kill switch (simulated halt; explicit acknowledgement to resume).
  6. Downloadable risk reports (5 kinds).

Honesty rules
  - Values that cannot be computed from real data are None / "Not Available".
  - Correlation is a sector-proxy estimate (no per-symbol OHLC history is
    cached); it is labelled as such everywhere.
  - ATR is not directly available from cached scan data; sizing uses the
    real stop-loss distance and says so.
  - Every assessment echoes its inputs and intermediates for auditability.
"""

from __future__ import annotations

import csv
import json
import os
from datetime import datetime, timedelta, timezone
from typing import Optional

import config

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
EXPORT_DIR = os.path.join(BASE_DIR, "exports")
CONFIG_FILE = os.path.join(BASE_DIR, "phase11_risk_config.json")
KILL_SWITCH_FILE = os.path.join(BASE_DIR, "phase11_kill_switch.json")
ALERTS_FILE = os.path.join(BASE_DIR, "phase11_risk_alerts.json")
STATE_FILE = os.path.join(BASE_DIR, "state.json")
SCAN_CACHE_FILE = os.path.join(BASE_DIR, "phase7_scan_cache.json")
MARKET_CACHE_FILE = os.path.join(BASE_DIR, "market_context_cache.json")

ENGINE_VERSION = "11.0"

DEFAULT_CONFIG: dict = {
    "max_risk_per_trade_pct": 1.0,      # % of portfolio value at risk per trade
    "max_position_pct": 20.0,           # max capital in a single new trade
    "max_stock_pct": 25.0,              # max total exposure to one stock
    "max_sector_pct": 40.0,             # max total exposure to one sector
    "max_portfolio_heat_pct": 6.0,      # sum of open risk-to-stop across positions
    "min_volume_ratio": 0.3,            # liquidity floor (today vol / 20d avg)
    "max_data_age_days": 3.0,           # stale data ⇒ gap-risk fail
    "min_stop_distance_pct": 1.0,       # tighter stop ⇒ overnight gap likely blows through
    "max_avg_correlation": 0.60,        # sector-proxy correlation ceiling
    "same_sector_correlation": 0.70,    # proxy value: same sector
    "cross_sector_correlation": 0.25,   # proxy value: different sector
    "daily_loss_limit_pct": 3.0,        # kill-switch trigger
    "max_drawdown_alert_pct": 8.0,      # kill-switch trigger
    "vix_spike_threshold": 22.0,        # volatility alert
    "auto_kill_switch": True,           # trigger automatically on breach
    "confidence_bands": [               # confidence → risk-budget multiplier
        [75.0, 1.25], [60.0, 1.0], [45.0, 0.75], [0.0, 0.5]
    ],
}


# ── Small helpers ─────────────────────────────────────────────────────────────

def _now() -> str:
    return datetime.now().isoformat()


def _load(path: str, default):
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return default


def _save(path: str, data) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2, default=str)
    os.replace(tmp, path)


def _r(v, nd=2):
    return None if v is None else round(float(v), nd)


def get_config() -> dict:
    cfg = dict(DEFAULT_CONFIG)
    cfg.update(_load(CONFIG_FILE, {}))
    return cfg


def update_config(changes: dict) -> dict:
    allowed = set(DEFAULT_CONFIG)
    bad = [k for k in changes if k not in allowed]
    if bad:
        return {"success": False, "error": f"Unknown config keys: {', '.join(sorted(bad))}"}
    stored = _load(CONFIG_FILE, {})
    stored.update(changes)
    _save(CONFIG_FILE, stored)
    return {"success": True, "config": get_config()}


def _sector_of(symbol: str) -> str:
    for sector, symbols in config.SECTOR_MAP.items():
        if symbol.upper() in symbols:
            return sector
    return "UNKNOWN"


def _state() -> dict:
    return _load(STATE_FILE, {"cash": config.INITIAL_CAPITAL, "positions": {}, "trades": [], "pnl_history": []})


def _scan_rec(symbol: str) -> Optional[dict]:
    cache = _load(SCAN_CACHE_FILE, {})
    for rec in cache.get("recommendations", []):
        if rec.get("symbol", "").upper() == symbol.upper():
            return rec
    return None


def _last_price(symbol: str, state: dict) -> Optional[float]:
    """Best available price: scan cache entry price, else avg cost basis."""
    rec = _scan_rec(symbol)
    if rec and rec.get("entry_price"):
        return float(rec["entry_price"])
    pos = state.get("positions", {}).get(symbol.upper())
    if pos:
        return float(pos["avg_price"])
    return None


def _portfolio_value(state: dict) -> tuple[float, dict[str, float]]:
    """Portfolio value and per-position market value (last known prices)."""
    values: dict[str, float] = {}
    for sym, pos in state.get("positions", {}).items():
        price = _last_price(sym, state) or pos["avg_price"]
        values[sym] = pos["quantity"] * price
    return state.get("cash", 0.0) + sum(values.values()), values


def _position_stop(symbol: str, state: dict) -> Optional[float]:
    """Stop-loss recorded on the most recent open BUY of this symbol."""
    for t in reversed(state.get("trades", [])):
        if t.get("symbol") == symbol.upper() and t.get("action") == "BUY":
            sl = t.get("stop_loss") or t.get("stop_loss_price")
            return float(sl) if sl else None
    return None


def _portfolio_heat(state: dict, pv: float) -> tuple[float, list[dict], list[dict]]:
    """
    Heat = Σ open risk-to-stop / portfolio value (%), for positions with a stop.
    Positions without a recorded stop have UNBOUNDED risk — they are reported
    separately (not silently folded into heat) and raise a NO_STOP alert.
    """
    detail = []
    unbounded = []
    total_risk = 0.0
    for sym, pos in state.get("positions", {}).items():
        price = _last_price(sym, state) or pos["avg_price"]
        stop = _position_stop(sym, state)
        if stop and stop < price:
            risk = (price - stop) * pos["quantity"]
            total_risk += risk
            detail.append({"symbol": sym, "risk_amount": _r(risk),
                           "basis": f"(price {price} - stop {stop}) x {pos['quantity']}"})
        else:
            unbounded.append({"symbol": sym, "position_value": _r(price * pos["quantity"]),
                              "basis": "no stop-loss recorded — risk is unbounded (excluded from heat, flagged)"})
    heat_pct = (total_risk / pv * 100.0) if pv > 0 else 0.0
    return heat_pct, detail, unbounded


def _equity_series(state: dict) -> list[dict]:
    return [
        {"timestamp": p["timestamp"], "value": float(p["value"])}
        for p in state.get("pnl_history", [])
        if p.get("timestamp") and p.get("value") is not None
    ]


def _drawdown_windows(state: dict) -> dict:
    """Daily / weekly / monthly drawdown from the pnl_history equity series."""
    series = _equity_series(state)
    out = {}
    now = datetime.now()
    for label, days in (("daily", 1), ("weekly", 7), ("monthly", 30)):
        cutoff = now - timedelta(days=days)
        window = [p for p in series if datetime.fromisoformat(p["timestamp"]) >= cutoff]
        if len(window) < 2:
            out[label] = {"drawdown_pct": None, "note": "Not Available — fewer than 2 equity points in window"}
            continue
        peak = window[0]["value"]
        max_dd = 0.0
        for p in window:
            peak = max(peak, p["value"])
            if peak > 0:
                max_dd = max(max_dd, (peak - p["value"]) / peak * 100.0)
        out[label] = {"drawdown_pct": _r(max_dd), "points": len(window)}
    return out


def _daily_realized_loss_pct(state: dict, pv: float) -> float:
    today = datetime.now().date().isoformat()
    pnl = sum(
        float(t.get("pnl", 0.0))
        for t in state.get("trades", [])
        if t.get("action") == "SELL" and str(t.get("timestamp", "")).startswith(today)
    )
    return (-pnl / pv * 100.0) if (pnl < 0 and pv > 0) else 0.0


def _proxy_correlation(sym_a: str, sym_b: str, cfg: dict) -> float:
    if sym_a.upper() == sym_b.upper():
        return 1.0
    return (
        cfg["same_sector_correlation"]
        if _sector_of(sym_a) == _sector_of(sym_b)
        else cfg["cross_sector_correlation"]
    )


# ── Kill switch ───────────────────────────────────────────────────────────────

def kill_switch_status() -> dict:
    ks = _load(KILL_SWITCH_FILE, {"active": False, "events": []})
    ks.setdefault("active", False)
    ks.setdefault("events", [])
    return ks


def trigger_kill_switch(reason: str, source: str = "manual") -> dict:
    ks = kill_switch_status()
    event = {"event": "TRIGGERED", "reason": reason, "source": source, "ts": _now()}
    ks.update({"active": True, "reason": reason, "triggered_at": _now(), "triggered_by": source})
    ks["events"].append(event)
    _save(KILL_SWITCH_FILE, ks)
    return {"success": True, "kill_switch": ks,
            "note": "SIMULATED halt — paper trading only; no real orders exist to stop."}


def resume_trading(acknowledge: bool = False) -> dict:
    ks = kill_switch_status()
    if not ks["active"]:
        return {"success": False, "error": "Kill switch is not active."}
    if not acknowledge:
        return {"success": False,
                "error": "Explicit acknowledgement required: pass acknowledge=true to confirm you reviewed the risk event."}
    ks["events"].append({"event": "RESUMED", "acknowledged": True, "ts": _now()})
    ks.update({"active": False, "reason": None, "resumed_at": _now()})
    _save(KILL_SWITCH_FILE, ks)
    return {"success": True, "kill_switch": ks}


def _maybe_auto_kill(state: dict, pv: float, cfg: dict) -> Optional[str]:
    """Trigger the kill switch automatically on configured risk events."""
    if not cfg.get("auto_kill_switch") or kill_switch_status()["active"]:
        return None
    daily_loss = _daily_realized_loss_pct(state, pv)
    if daily_loss >= cfg["daily_loss_limit_pct"]:
        reason = f"Daily loss limit reached: -{daily_loss:.2f}% >= {cfg['daily_loss_limit_pct']}%"
        trigger_kill_switch(reason, source="auto:daily_loss")
        return reason
    dd = _drawdown_windows(state).get("monthly", {}).get("drawdown_pct")
    if dd is not None and dd >= cfg["max_drawdown_alert_pct"]:
        reason = f"Excessive drawdown: {dd:.2f}% >= {cfg['max_drawdown_alert_pct']}%"
        trigger_kill_switch(reason, source="auto:drawdown")
        return reason
    return None


# ── 3. Dynamic position sizing ────────────────────────────────────────────────

def position_size(
    symbol: str,
    price: float,
    stop_loss: Optional[float] = None,
    confidence: Optional[float] = None,
) -> dict:
    """
    Recommended quantity from portfolio value, risk budget, confidence,
    stop distance and existing exposure. Fully auditable output.
    """
    cfg = get_config()
    state = _state()
    pv, values = _portfolio_value(state)
    sym = symbol.upper()
    rec = _scan_rec(sym)

    if stop_loss is None and rec and rec.get("stop_loss"):
        stop_loss = float(rec["stop_loss"])
    if confidence is None and rec and rec.get("calibrated_confidence") is not None:
        confidence = float(rec["calibrated_confidence"])

    steps: list[str] = []
    if price <= 0:
        return {"success": False, "error": "Price must be positive"}
    if not stop_loss or stop_loss >= price:
        return {
            "success": False, "recommended_quantity": 0,
            "error": "No valid stop-loss below entry price — cannot size the trade. "
                     "ATR is Not Available from cached data; a stop-loss is required.",
        }

    stop_distance = price - stop_loss
    risk_budget = pv * cfg["max_risk_per_trade_pct"] / 100.0
    steps.append(f"risk_budget = portfolio_value {pv:.2f} x {cfg['max_risk_per_trade_pct']}% = {risk_budget:.2f}")

    conf_mult = 0.5
    if confidence is not None:
        for threshold, mult in cfg["confidence_bands"]:
            if confidence >= threshold:
                conf_mult = mult
                break
        steps.append(f"confidence {confidence:.1f} -> multiplier {conf_mult}")
    else:
        steps.append("confidence Not Available -> conservative multiplier 0.5")

    adjusted_budget = risk_budget * conf_mult
    qty_by_risk = int(adjusted_budget // stop_distance)
    steps.append(f"qty_by_risk = {adjusted_budget:.2f} / stop_distance {stop_distance:.2f} = {qty_by_risk}")

    qty_by_capital = int((pv * cfg["max_position_pct"] / 100.0) // price)
    steps.append(f"qty_by_capital ({cfg['max_position_pct']}% of PV) = {qty_by_capital}")
    qty_by_cash = int(state.get("cash", 0.0) // price)
    steps.append(f"qty_by_cash = {qty_by_cash}")

    existing_value = values.get(sym, 0.0)
    room_stock = max(0.0, pv * cfg["max_stock_pct"] / 100.0 - existing_value)
    qty_by_stock = int(room_stock // price)
    steps.append(f"qty_by_stock_concentration (room {room_stock:.2f}) = {qty_by_stock}")

    sector = _sector_of(sym)
    sector_value = sum(v for s, v in values.items() if _sector_of(s) == sector)
    room_sector = max(0.0, pv * cfg["max_sector_pct"] / 100.0 - sector_value)
    qty_by_sector = int(room_sector // price)
    steps.append(f"qty_by_sector ({sector}, room {room_sector:.2f}) = {qty_by_sector}")

    heat_pct, _, _ = _portfolio_heat(state, pv)
    room_heat = max(0.0, (cfg["max_portfolio_heat_pct"] - heat_pct) / 100.0 * pv)
    qty_by_heat = int(room_heat // stop_distance)
    steps.append(f"qty_by_heat (current {heat_pct:.2f}%, room {room_heat:.2f}) = {qty_by_heat}")

    recommended = max(0, min(qty_by_risk, qty_by_capital, qty_by_cash, qty_by_stock, qty_by_sector, qty_by_heat))

    return {
        "success": True,
        "symbol": sym,
        "recommended_quantity": recommended,
        "inputs": {
            "price": _r(price), "stop_loss": _r(stop_loss), "stop_distance": _r(stop_distance),
            "confidence": _r(confidence, 1), "portfolio_value": _r(pv),
            "cash": _r(state.get("cash", 0.0)), "existing_position_value": _r(existing_value),
            "sector": sector, "sector_value": _r(sector_value),
            "current_heat_pct": _r(heat_pct),
            "atr": None,
            "atr_note": "Not Available — no cached OHLC history; sizing uses actual stop-loss distance",
        },
        "constraints": {
            "by_risk_budget": qty_by_risk, "by_capital_limit": qty_by_capital,
            "by_cash": qty_by_cash, "by_stock_concentration": qty_by_stock,
            "by_sector_limit": qty_by_sector, "by_portfolio_heat": qty_by_heat,
        },
        "risk_amount": _r(recommended * stop_distance),
        "capital_used": _r(recommended * price),
        "audit_steps": steps,
        "engine_version": ENGINE_VERSION,
        "computed_at": _now(),
    }


# ── 1. Pre-trade risk assessment ──────────────────────────────────────────────

def assess_trade(
    symbol: str,
    quantity: int,
    price: float,
    stop_loss: Optional[float] = None,
    confidence: Optional[float] = None,
) -> dict:
    """
    Full 8-check pre-trade risk assessment.
    Verdict: APPROVE | REDUCE (use recommended_quantity) | REJECT.
    """
    cfg = get_config()
    state = _state()
    pv, values = _portfolio_value(state)
    sym = symbol.upper()
    rec = _scan_rec(sym)

    if stop_loss is None and rec and rec.get("stop_loss"):
        stop_loss = float(rec["stop_loss"])
    if confidence is None and rec and rec.get("calibrated_confidence") is not None:
        confidence = float(rec["calibrated_confidence"])

    checks: list[dict] = []

    def check(name, passed, value, limit, detail, severity="FAIL"):
        checks.append({
            "check": name,
            "status": "PASS" if passed else severity,
            "value": value, "limit": limit, "detail": detail,
        })
        return passed

    ks = kill_switch_status()
    if ks["active"]:
        return {
            "success": True, "symbol": sym, "verdict": "REJECT",
            "reason": f"Kill switch active: {ks.get('reason')} — acknowledge and resume before trading.",
            "checks": [], "kill_switch": ks,
            "engine_version": ENGINE_VERSION, "computed_at": _now(),
        }

    sizing = position_size(sym, price, stop_loss, confidence)
    recommended = sizing.get("recommended_quantity", 0)

    # 1. Max risk per trade
    if stop_loss and stop_loss < price:
        trade_risk = quantity * (price - stop_loss)
        risk_pct = trade_risk / pv * 100.0 if pv > 0 else 0.0
        check("max_risk_per_trade", risk_pct <= cfg["max_risk_per_trade_pct"] * 1.25 + 1e-9,
              _r(risk_pct), cfg["max_risk_per_trade_pct"],
              f"Risk to stop = qty {quantity} x distance {price - stop_loss:.2f} = ₹{trade_risk:.2f} "
              f"({risk_pct:.2f}% of PV; limit {cfg['max_risk_per_trade_pct']}%, +25% tolerance for confidence scaling)")
    else:
        check("max_risk_per_trade", False, None, cfg["max_risk_per_trade_pct"],
              "No valid stop-loss below entry — risk to stop cannot be bounded", severity="FAIL")

    # 2. Position sizing — hard fail only when nothing can be sized at all;
    # oversize vs recommendation becomes a REDUCE verdict, not a REJECT.
    check("position_sizing", 0 < quantity <= max(recommended, 0),
          quantity, recommended,
          f"Requested {quantity} vs recommended {recommended} "
          f"(risk budget x confidence / stop distance, capped by exposure limits)",
          severity="FAIL" if recommended <= 0 else "WARN")

    # 3. Liquidity
    if rec and rec.get("volume_ratio") is not None:
        vr = float(rec["volume_ratio"])
        check("liquidity", vr >= cfg["min_volume_ratio"], _r(vr), cfg["min_volume_ratio"],
              f"Volume ratio (today/20d avg) from latest scan = {vr}", severity="WARN")
    else:
        check("liquidity", False, None, cfg["min_volume_ratio"],
              "Not Available — symbol not in latest scan cache; liquidity unverified", severity="WARN")

    # 4. Gap risk
    gap_notes = []
    gap_ok = True
    if rec and rec.get("data_age_days") is not None:
        age = float(rec["data_age_days"])
        if age > cfg["max_data_age_days"]:
            gap_ok = False
        gap_notes.append(f"data age {age}d (limit {cfg['max_data_age_days']}d)")
    else:
        gap_notes.append("data age Not Available")
    if stop_loss and stop_loss < price:
        sd_pct = (price - stop_loss) / price * 100.0
        if sd_pct < cfg["min_stop_distance_pct"]:
            gap_ok = False
        gap_notes.append(f"stop distance {sd_pct:.2f}% (min {cfg['min_stop_distance_pct']}% to survive overnight gaps)")
    mc = _load(MARKET_CACHE_FILE, {})
    if mc.get("vix") is not None:
        gap_notes.append(f"India VIX {mc['vix']} ({mc.get('vix_category', '?')})")
        if float(mc["vix"]) >= cfg["vix_spike_threshold"]:
            gap_ok = False
            gap_notes.append(f"VIX >= spike threshold {cfg['vix_spike_threshold']}")
    check("gap_risk", gap_ok, None, None, "; ".join(gap_notes), severity="WARN")

    # 5. Sector exposure
    sector = _sector_of(sym)
    sector_value = sum(v for s, v in values.items() if _sector_of(s) == sector)
    new_sector_pct = (sector_value + quantity * price) / pv * 100.0 if pv > 0 else 0.0
    check("sector_exposure", new_sector_pct <= cfg["max_sector_pct"],
          _r(new_sector_pct), cfg["max_sector_pct"],
          f"{sector}: current ₹{sector_value:.2f} + trade ₹{quantity * price:.2f} = {new_sector_pct:.2f}% of PV")

    # 6. Stock concentration
    new_stock_pct = (values.get(sym, 0.0) + quantity * price) / pv * 100.0 if pv > 0 else 0.0
    check("stock_concentration", new_stock_pct <= cfg["max_stock_pct"],
          _r(new_stock_pct), cfg["max_stock_pct"],
          f"{sym} total exposure after trade = {new_stock_pct:.2f}% of PV")

    # 7. Correlation (sector-proxy — honestly labelled)
    others = [s for s in state.get("positions", {}) if s != sym]
    if others:
        corrs = [_proxy_correlation(sym, o, cfg) for o in others]
        avg_corr = sum(corrs) / len(corrs)
        check("correlation", avg_corr <= cfg["max_avg_correlation"],
              _r(avg_corr), cfg["max_avg_correlation"],
              f"Sector-proxy estimate vs {len(others)} position(s) "
              f"(same sector={cfg['same_sector_correlation']}, cross={cfg['cross_sector_correlation']}; "
              "no OHLC history cached for true return correlation)", severity="WARN")
    else:
        check("correlation", True, 0.0, cfg["max_avg_correlation"], "No other open positions")

    # 8. Portfolio heat
    heat_pct, _, unbounded = _portfolio_heat(state, pv)
    add_heat = (quantity * (price - stop_loss) / pv * 100.0) if (stop_loss and stop_loss < price and pv > 0) else None
    if add_heat is not None:
        new_heat = heat_pct + add_heat
        extra = f"; {len(unbounded)} position(s) without stops excluded (unbounded risk, flagged)" if unbounded else ""
        check("portfolio_heat", new_heat <= cfg["max_portfolio_heat_pct"],
              _r(new_heat), cfg["max_portfolio_heat_pct"],
              f"Current heat {heat_pct:.2f}% + this trade {add_heat:.2f}% = {new_heat:.2f}%{extra}")
    else:
        check("portfolio_heat", False, _r(heat_pct), cfg["max_portfolio_heat_pct"],
              "Cannot compute added heat without a valid stop-loss")

    hard_fails = [c for c in checks if c["status"] == "FAIL"]
    warns = [c for c in checks if c["status"] == "WARN"]
    if hard_fails:
        verdict = "REJECT"
    elif quantity > recommended and recommended > 0:
        verdict = "REDUCE"
    elif warns:
        verdict = "APPROVE_WITH_WARNINGS"
    else:
        verdict = "APPROVE"

    return {
        "success": True,
        "symbol": sym,
        "verdict": verdict,
        "recommended_quantity": recommended,
        "requested_quantity": quantity,
        "checks": checks,
        "hard_fails": [c["check"] for c in hard_fails],
        "warnings": [c["check"] for c in warns],
        "inputs": {
            "price": _r(price), "stop_loss": _r(stop_loss), "confidence": _r(confidence, 1),
            "portfolio_value": _r(pv), "cash": _r(state.get("cash", 0.0)),
            "scan_data_used": bool(rec),
        },
        "sizing": sizing if sizing.get("success") else {"error": sizing.get("error")},
        "engine_version": ENGINE_VERSION,
        "computed_at": _now(),
        "note": "Research/paper-trading assessment only. No real-money execution.",
    }


def pre_trade_check(
    symbol: str,
    quantity: int,
    price: float,
    stop_loss: Optional[float] = None,
    confidence: Optional[float] = None,
) -> tuple[bool, str]:
    """
    Enforcement hook used by paper_trader.execute_buy.
    Blocks on kill switch and hard REJECT; allows REDUCE/warnings with message.
    """
    assessment = assess_trade(symbol, quantity, price, stop_loss, confidence)
    verdict = assessment.get("verdict")
    if verdict == "REJECT":
        if assessment.get("kill_switch", {}).get("active"):
            return False, assessment.get("reason", "Kill switch active")
        fails = ", ".join(assessment.get("hard_fails", []))
        return False, f"Risk assessment REJECT ({fails}). Recommended quantity: {assessment.get('recommended_quantity', 0)}"
    if verdict == "REDUCE":
        return True, (f"Risk note: requested {quantity} exceeds recommended "
                      f"{assessment.get('recommended_quantity')} — trade allowed (paper), flagged for review")
    return True, f"Risk assessment {verdict}"


# ── 2. Portfolio risk dashboard ───────────────────────────────────────────────

def portfolio_risk() -> dict:
    cfg = get_config()
    state = _state()
    pv, values = _portfolio_value(state)
    heat_pct, heat_detail, unbounded = _portfolio_heat(state, pv)
    auto_reason = _maybe_auto_kill(state, pv, cfg)

    # Sector allocation
    sector_alloc: dict[str, float] = {}
    for sym, val in values.items():
        sector_alloc.setdefault(_sector_of(sym), 0.0)
        sector_alloc[_sector_of(sym)] += val
    sector_allocation = [
        {"sector": s, "value": _r(v), "pct_of_portfolio": _r(v / pv * 100.0 if pv else 0.0)}
        for s, v in sorted(sector_alloc.items(), key=lambda kv: -kv[1])
    ]

    # Correlation matrix (sector proxy)
    symbols = sorted(values.keys())
    matrix = [
        {"symbol": a, "correlations": {b: _r(_proxy_correlation(a, b, cfg)) for b in symbols}}
        for a in symbols
    ]

    # Diversification score: 100 x (1 - HHI of position weights incl. cash bucket)
    if pv > 0:
        weights = [v / pv for v in values.values()] + [state.get("cash", 0.0) / pv]
        hhi = sum(w * w for w in weights)
        n = len(weights)
        diversification = _r((1 - hhi) / (1 - 1 / n) * 100.0) if n > 1 else 0.0
    else:
        diversification = None

    exposures = sorted(
        [{"symbol": s, "value": _r(v), "pct_of_portfolio": _r(v / pv * 100.0 if pv else 0.0),
          "sector": _sector_of(s)} for s, v in values.items()],
        key=lambda e: -(e["value"] or 0),
    )

    daily_loss_pct = _daily_realized_loss_pct(state, pv)

    return {
        "success": True,
        "portfolio_value": _r(pv),
        "cash": _r(state.get("cash", 0.0)),
        "cash_allocation_pct": _r(state.get("cash", 0.0) / pv * 100.0 if pv else 0.0),
        "invested_pct": _r(sum(values.values()) / pv * 100.0 if pv else 0.0),
        "portfolio_heat_pct": _r(heat_pct),
        "heat_detail": heat_detail,
        "unbounded_risk_positions": unbounded,
        "risk_budget": {
            "max_heat_pct": cfg["max_portfolio_heat_pct"],
            "used_pct_of_budget": _r(heat_pct / cfg["max_portfolio_heat_pct"] * 100.0),
            "remaining_heat_pct": _r(max(0.0, cfg["max_portfolio_heat_pct"] - heat_pct)),
        },
        "sector_allocation": sector_allocation,
        "correlation_matrix": {
            "method": "sector-proxy estimate (no OHLC history cached for true return correlation)",
            "symbols": symbols,
            "matrix": matrix,
        },
        "diversification_score": diversification,
        "diversification_note": "100 x normalized (1 - HHI) over position + cash weights",
        "largest_exposures": exposures[:5],
        "drawdowns": _drawdown_windows(state),
        "daily_realized_loss_pct": _r(daily_loss_pct),
        "limits": {k: cfg[k] for k in (
            "max_risk_per_trade_pct", "max_position_pct", "max_stock_pct", "max_sector_pct",
            "max_portfolio_heat_pct", "daily_loss_limit_pct", "max_drawdown_alert_pct")},
        "kill_switch": kill_switch_status(),
        "auto_kill_triggered": auto_reason,
        "engine_version": ENGINE_VERSION,
        "computed_at": _now(),
    }


# ── 4. Risk alerts ────────────────────────────────────────────────────────────

def risk_alerts(generate: bool = True) -> dict:
    cfg = get_config()
    state = _state()
    pv, values = _portfolio_value(state)
    stored = _load(ALERTS_FILE, {"alerts": []})
    existing_keys = {a.get("key") for a in stored["alerts"]}
    new_alerts: list[dict] = []
    today = datetime.now().date().isoformat()

    def alert(atype, severity, message, key_extra=""):
        key = f"{atype}|{today}|{key_extra}"
        if key in existing_keys:
            return
        new_alerts.append({"key": key, "type": atype, "severity": severity,
                           "message": message, "ts": _now(), "acknowledged": False})
        existing_keys.add(key)

    if generate:
        daily_loss = _daily_realized_loss_pct(state, pv)
        if daily_loss >= cfg["daily_loss_limit_pct"]:
            alert("DAILY_LOSS_LIMIT", "CRITICAL",
                  f"Daily realized loss {daily_loss:.2f}% >= limit {cfg['daily_loss_limit_pct']}%")
        dd = _drawdown_windows(state).get("monthly", {}).get("drawdown_pct")
        if dd is not None and dd >= cfg["max_drawdown_alert_pct"]:
            alert("EXCESSIVE_DRAWDOWN", "CRITICAL",
                  f"Monthly drawdown {dd:.2f}% >= limit {cfg['max_drawdown_alert_pct']}%")
        for s in {_sector_of(sym) for sym in values}:
            sector_pct = sum(v for sym, v in values.items() if _sector_of(sym) == s) / pv * 100.0 if pv else 0.0
            if sector_pct > cfg["max_sector_pct"]:
                alert("SECTOR_CONCENTRATION", "WARNING",
                      f"{s} exposure {sector_pct:.2f}% > limit {cfg['max_sector_pct']}%", key_extra=s)
        syms = list(values)
        if len(syms) >= 2:
            pairs = [(a, b) for i, a in enumerate(syms) for b in syms[i + 1:]]
            avg_corr = sum(_proxy_correlation(a, b, cfg) for a, b in pairs) / len(pairs)
            if avg_corr > cfg["max_avg_correlation"]:
                alert("HIGH_CORRELATION", "WARNING",
                      f"Avg sector-proxy correlation {avg_corr:.2f} > limit {cfg['max_avg_correlation']}")
        for sym in values:
            rec = _scan_rec(sym)
            if rec and rec.get("volume_ratio") is not None and float(rec["volume_ratio"]) < cfg["min_volume_ratio"]:
                alert("LIQUIDITY_WARNING", "WARNING",
                      f"{sym} volume ratio {rec['volume_ratio']} < floor {cfg['min_volume_ratio']}", key_extra=sym)
        mc = _load(MARKET_CACHE_FILE, {})
        if mc.get("vix") is not None and float(mc["vix"]) >= cfg["vix_spike_threshold"]:
            alert("VOLATILITY_SPIKE", "WARNING",
                  f"India VIX {mc['vix']} >= spike threshold {cfg['vix_spike_threshold']}")
        _, _, unbounded = _portfolio_heat(state, pv)
        for u in unbounded:
            alert("POSITION_NO_STOP", "WARNING",
                  f"{u['symbol']} has no stop-loss recorded — risk unbounded (value ₹{u['position_value']})",
                  key_extra=u["symbol"])
        for sym, pos in state.get("positions", {}).items():
            price = _last_price(sym, state) or pos["avg_price"]
            stop = _position_stop(sym, state)
            sizing = position_size(sym, price, stop, None)
            recq = sizing.get("recommended_quantity")
            if sizing.get("success") and recq is not None and pos["quantity"] > recq:
                alert("POSITION_OVERSIZED", "WARNING",
                      f"{sym} holds {pos['quantity']} vs recommended {recq} at current limits", key_extra=sym)

        if new_alerts:
            stored["alerts"].extend(new_alerts)
            stored["alerts"] = stored["alerts"][-200:]
            _save(ALERTS_FILE, stored)

    return {
        "success": True,
        "new_alerts": new_alerts,
        "alerts": sorted(stored["alerts"], key=lambda a: a["ts"], reverse=True)[:50],
        "kill_switch": kill_switch_status(),
        "computed_at": _now(),
    }


# ── 6. Risk reports ───────────────────────────────────────────────────────────

REPORT_KINDS = ("risk_summary", "exposure", "correlation", "position_sizing", "drawdown")


def risk_report(kind: str) -> dict:
    if kind not in REPORT_KINDS:
        return {"success": False, "error": f"Unknown report kind '{kind}'. Allowed: {', '.join(REPORT_KINDS)}"}
    os.makedirs(EXPORT_DIR, exist_ok=True)
    dash = portfolio_risk()
    state = _state()
    path = os.path.join(EXPORT_DIR, f"phase11_{kind}_report.csv")

    def write(header, rows):
        with open(path, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow([f"# Phase 11 {kind} report", f"generated {_now()}", f"engine {ENGINE_VERSION}",
                        "PAPER TRADING RESEARCH ONLY"])
            w.writerow(header)
            w.writerows(rows)

    if kind == "risk_summary":
        rows = [
            ["Portfolio Value", dash["portfolio_value"]],
            ["Cash", dash["cash"]],
            ["Cash Allocation %", dash["cash_allocation_pct"]],
            ["Portfolio Heat %", dash["portfolio_heat_pct"]],
            ["Risk Budget Used %", dash["risk_budget"]["used_pct_of_budget"]],
            ["Diversification Score", dash["diversification_score"]],
            ["Daily Realized Loss %", dash["daily_realized_loss_pct"]],
            ["Daily Drawdown %", dash["drawdowns"]["daily"].get("drawdown_pct", "Not Available")],
            ["Weekly Drawdown %", dash["drawdowns"]["weekly"].get("drawdown_pct", "Not Available")],
            ["Monthly Drawdown %", dash["drawdowns"]["monthly"].get("drawdown_pct", "Not Available")],
            ["Kill Switch Active", dash["kill_switch"]["active"]],
        ] + [[f"Limit: {k}", v] for k, v in dash["limits"].items()]
        write(["Metric", "Value"], rows)
    elif kind == "exposure":
        rows = [[e["symbol"], e["sector"], e["value"], e["pct_of_portfolio"]]
                for e in dash["largest_exposures"]]
        rows += [[f"SECTOR:{s['sector']}", "-", s["value"], s["pct_of_portfolio"]]
                 for s in dash["sector_allocation"]]
        write(["Exposure", "Sector", "Value", "% of Portfolio"], rows)
    elif kind == "correlation":
        syms = dash["correlation_matrix"]["symbols"]
        rows = [[row["symbol"]] + [row["correlations"][b] for b in syms]
                for row in dash["correlation_matrix"]["matrix"]]
        rows.append([dash["correlation_matrix"]["method"]])
        write(["Symbol"] + syms, rows)
    elif kind == "position_sizing":
        rows = []
        for sym, pos in state.get("positions", {}).items():
            price = _last_price(sym, state) or pos["avg_price"]
            sizing = position_size(sym, price, _position_stop(sym, state), None)
            rows.append([sym, pos["quantity"], sizing.get("recommended_quantity", "Not Available"),
                         price, sizing.get("risk_amount", "Not Available"),
                         "; ".join(sizing.get("audit_steps", [])[:3])])
        if not rows:
            rows = [["(no open positions)", "-", "-", "-", "-", "-"]]
        write(["Symbol", "Held Qty", "Recommended Qty", "Price", "Risk Amount", "Sizing Basis"], rows)
    else:  # drawdown
        rows = [[label, d.get("drawdown_pct", "Not Available"), d.get("points", d.get("note", ""))]
                for label, d in dash["drawdowns"].items()]
        series = _equity_series(state)
        rows += [[p["timestamp"], p["value"], ""] for p in series[-50:]]
        write(["Window/Timestamp", "Drawdown % / Equity", "Points/Note"], rows)

    return {"success": True, "kind": kind, "file": path,
            "file_name": os.path.basename(path), "generated_at": _now()}
