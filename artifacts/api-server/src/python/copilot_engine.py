"""
copilot_engine.py — Phase 9: AI Copilot, Alerts & Explainability

Rule-based AI copilot layer built strictly on cached, point-in-time data:
  - phase7_scan_cache.json   (latest full market scan — no look-ahead)
  - market_context_cache.json (regime, sentiment, VIX, sectors)
  - state.json               (paper portfolio)
  - watchlist.json

Provides:
  copilot_summary()      — market regime, sentiment, portfolio health, risks,
                           best opportunity, stocks to avoid, top confidence trade
  generate_alerts()      — smart rule-based alerts (persisted, dedup by scan)
  list_alerts()          — notification center feed with sections + unread
  mark_alerts_read()     — mark one/all read
  daily_briefing()       — AI-generated morning briefing (voice-ready)
  trade_explanation()    — indicators for/against, risk, hold period, win rate
  why_not()              — why a stock was NOT selected (failed gates/rules)
  watchlist_insights()   — per-stock trend/momentum/strength/confidence/risk
  record_confidence_snapshot() / confidence_history() — confidence over time
  export_phase9()        — CSV/JSON export of alerts + summaries

SAFETY: read-only analysis. No trades placed. No look-ahead (uses cached scan
snapshots only). All summaries include voice_text for future TTS support.
"""

from __future__ import annotations

import csv
import json
import os
import uuid
from datetime import datetime, timezone

_DIR = os.path.dirname(os.path.abspath(__file__))
SCAN_CACHE = os.path.join(_DIR, "phase7_scan_cache.json")
MARKET_CACHE = os.path.join(_DIR, "market_context_cache.json")
STATE_FILE = os.path.join(_DIR, "state.json")
WATCHLIST_FILE = os.path.join(_DIR, "watchlist.json")
ALERTS_FILE = os.path.join(_DIR, "phase9_alerts.json")
CONF_HISTORY_FILE = os.path.join(_DIR, "phase9_confidence_history.json")
EXPORT_DIR = os.path.join(_DIR, "exports")

LABEL = "PAPER / LIVE DATA VALIDATION"
MAX_ALERTS = 500
MAX_HISTORY_SNAPSHOTS = 200

INITIAL_CAPITAL = 5000.0


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _load(path: str, default):
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return default


def _save(path: str, data) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=1)
    os.replace(tmp, path)


def _scan() -> dict:
    return _load(SCAN_CACHE, {})


def _market() -> dict:
    return _load(MARKET_CACHE, {})


def _state() -> dict:
    return _load(STATE_FILE, {"cash": INITIAL_CAPITAL, "positions": [], "trades": []})


def _watchlist() -> list[str]:
    wl = _load(WATCHLIST_FILE, None)
    if wl is None:
        try:
            from config import DEFAULT_WATCHLIST
            wl = list(DEFAULT_WATCHLIST)
        except Exception:
            wl = []
    if isinstance(wl, dict):
        wl = wl.get("symbols", [])
    return [str(s).upper() for s in wl]


def _recs() -> list[dict]:
    return [r for r in _scan().get("recommendations", []) if not r.get("error")]


def _rec_for(symbol: str) -> dict | None:
    for r in _scan().get("recommendations", []):
        if r.get("symbol", "").upper() == symbol.upper():
            return r
    return None


# ── Portfolio helpers ─────────────────────────────────────────────────────────

def _portfolio_metrics() -> dict:
    st = _state()
    cash = float(st.get("cash", 0))
    raw_positions = st.get("positions", {})
    # positions stored as {symbol: {quantity, avg_price, ...}} in state.json
    if isinstance(raw_positions, dict):
        positions = [{"symbol": sym, **(p if isinstance(p, dict) else {})}
                     for sym, p in raw_positions.items()]
    else:
        positions = list(raw_positions)
    trades = st.get("trades", [])
    deployed = sum(
        float(p.get("avg_price", p.get("entry_price", 0)) or 0)
        * int(p.get("quantity", p.get("shares", 0)) or 0)
        for p in positions
    )
    total_value = cash + deployed
    deployed_pct = (deployed / total_value * 100) if total_value > 0 else 0.0
    closed = [t for t in trades if t.get("action") in ("SELL", "EXIT") or t.get("side") == "SELL"]
    realized_pnl = total_value - INITIAL_CAPITAL if not positions else None

    if deployed_pct >= 70:
        risk = "HIGH"
    elif deployed_pct >= 40:
        risk = "MEDIUM"
    else:
        risk = "LOW"

    return {
        "cash": round(cash, 2),
        "open_positions": len(positions),
        "positions": [
            {
                "symbol": p.get("symbol"),
                "quantity": int(p.get("quantity", p.get("shares", 0)) or 0),
                "entry_price": p.get("avg_price", p.get("entry_price")),
                "stop_loss": p.get("stop_loss"),
                "target": p.get("target") or p.get("target_price"),
            }
            for p in positions
        ],
        "deployed_value": round(deployed, 2),
        "deployed_pct": round(deployed_pct, 1),
        "total_trades": len(trades),
        "closed_trades": len(closed),
        "risk_level": risk,
        "approx_total_value": round(total_value, 2),
    }


def _sector_lists() -> tuple[list, list]:
    sectors = _market().get("sector_strength", {})
    if not isinstance(sectors, dict) or not sectors:
        return [], []
    items = []
    for name, v in sectors.items():
        score = v.get("score", v) if isinstance(v, dict) else v
        try:
            items.append((name, float(score)))
        except (TypeError, ValueError):
            continue
    items.sort(key=lambda x: -x[1])
    top = [{"sector": n, "score": round(s, 1)} for n, s in items[:3]]
    weak = [{"sector": n, "score": round(s, 1)} for n, s in items[-3:]][::-1] if len(items) > 3 else []
    return top, weak


# ── 1. Copilot summary ────────────────────────────────────────────────────────

def copilot_summary() -> dict:
    scan = _scan()
    mkt = _market()
    pm = _portfolio_metrics()
    recs = _recs()

    regime = mkt.get("regime", scan.get("summary", {}).get("regime", "UNKNOWN"))
    bias = mkt.get("bias", "NEUTRAL")
    vix_cat = mkt.get("vix_category", "UNKNOWN")

    actionable = [r for r in recs if r.get("final_action") in ("STRONG_BUY", "BUY", "WATCH")]
    ranked = sorted(recs, key=lambda r: -(r.get("opportunity_score") or 0))
    best = None
    pool = actionable or ranked
    if pool:
        b = sorted(pool, key=lambda r: -(r.get("opportunity_score") or 0))[0]
        best = {
            "symbol": b.get("symbol"),
            "action": b.get("final_action"),
            "confidence": b.get("calibrated_confidence"),
            "opportunity_score": b.get("opportunity_score"),
            "strategy": b.get("strategy_name"),
            "note": "Highest opportunity score in latest scan"
            + ("" if actionable else " (no BUY/WATCH candidates — top-ranked overall shown)"),
        }

    top_conf = sorted(recs, key=lambda r: -(r.get("calibrated_confidence") or 0))
    highest_confidence = None
    if top_conf:
        t = top_conf[0]
        highest_confidence = {
            "symbol": t.get("symbol"),
            "action": t.get("final_action"),
            "confidence": t.get("calibrated_confidence"),
            "rr_ratio": t.get("rr_ratio"),
        }

    avoid = []
    for r in sorted(recs, key=lambda r: (r.get("opportunity_score") or 0))[:3]:
        reasons = []
        if (r.get("rsi") or 50) < 40:
            reasons.append("weak RSI")
        if not r.get("above_ema20"):
            reasons.append("below EMA20")
        if (r.get("volume_ratio") or 1) < 0.8:
            reasons.append("low volume")
        if (r.get("adx") or 25) < 20:
            reasons.append("weak trend (ADX)")
        avoid.append({
            "symbol": r.get("symbol"),
            "opportunity_score": r.get("opportunity_score"),
            "reason": ", ".join(reasons) or "low opportunity score",
        })

    risks = []
    if pm["risk_level"] != "LOW":
        risks.append(f"Portfolio deployment at {pm['deployed_pct']}% — {pm['risk_level']} risk")
    if vix_cat in ("HIGH", "ELEVATED", "EXTREME"):
        risks.append(f"Volatility elevated (VIX category: {vix_cat})")
    dq = scan.get("summary", {}).get("data_quality_breakdown", {})
    stale = dq.get("STALE", 0) + dq.get("UNAVAILABLE", 0)
    if stale:
        risks.append(f"{stale} symbols with degraded data quality in latest scan")
    for p in pm["positions"]:
        risks.append(f"Open position: {p['symbol']} ({p['quantity']} shares) — monitor stop loss")
    if not risks:
        risks.append("No significant risks detected")

    summary = scan.get("summary", {})
    voice_text = (
        f"Market is {regime.lower().replace('_', ' ')} with {bias.lower().replace('_', ' ')} sentiment. "
        + (f"Best opportunity is {best['symbol']} with confidence {round(best['confidence'] or 0)}. " if best else "No strong opportunities today. ")
        + (f"Avoid {avoid[0]['symbol']} due to {avoid[0]['reason']}. " if avoid else "")
        + f"Portfolio risk is {pm['risk_level'].lower()}. "
        + f"Cash available: {round(pm['cash'])} rupees. "
        + f"Open positions: {pm['open_positions']}."
    )

    return {
        "success": True,
        "generated_at": _now(),
        "scan_id": scan.get("scan_id"),
        "snapshot_ts": scan.get("snapshot_ts"),
        "market": {
            "regime": regime,
            "sentiment": bias,
            "nifty_trend": mkt.get("nifty_trend"),
            "nifty_change_pct": mkt.get("nifty_change_pct"),
            "vix": mkt.get("vix"),
            "vix_category": vix_cat,
            "breadth": mkt.get("breadth_label"),
        },
        "portfolio": pm,
        "risks": risks,
        "best_opportunity": best,
        "highest_confidence_trade": highest_confidence,
        "avoid": avoid,
        "scan_summary": {
            "buy_count": (summary.get("strong_buy_count", 0) or 0) + (summary.get("buy_count", 0) or 0),
            "watch_count": summary.get("watch_count", 0),
            "ignore_count": summary.get("ignore_count", 0),
            "avg_opportunity_score": summary.get("avg_opportunity_score"),
        },
        "voice_text": voice_text,
        "label": LABEL,
    }


# ── 2. Smart alerts ───────────────────────────────────────────────────────────

def _load_alerts() -> list[dict]:
    return _load(ALERTS_FILE, [])


def _save_alerts(alerts: list[dict]) -> None:
    _save(ALERTS_FILE, alerts[-MAX_ALERTS:])


def _mk_alert(a_type: str, severity: str, symbol: str | None, reason: str,
              confidence: float | None, action: str, scan_id: str | None,
              category: str) -> dict:
    return {
        "alert_id": uuid.uuid4().hex[:10],
        "ts": _now(),
        "date": _today(),
        "type": a_type,
        "severity": severity,          # INFO / WARNING / CRITICAL
        "category": category,          # trade / risk / market / ai
        "symbol": symbol,
        "reason": reason,
        "confidence": confidence,
        "action_recommendation": action,
        "scan_id": scan_id,
        "read": False,
    }


def generate_alerts() -> dict:
    """Rule-based alert generation from latest scan + portfolio + market context.
    Deduplicates per (type, symbol, scan_id) — safe to call repeatedly."""
    scan = _scan()
    scan_id = scan.get("scan_id")
    mkt = _market()
    pm = _portfolio_metrics()
    recs = _recs()
    existing = _load_alerts()
    seen = {(a.get("type"), a.get("symbol"), a.get("scan_id")) for a in existing}
    new: list[dict] = []

    def add(a):
        key = (a["type"], a["symbol"], a["scan_id"])
        if key not in seen:
            seen.add(key)
            new.append(a)

    for r in recs:
        sym = r.get("symbol")
        conf = r.get("calibrated_confidence")
        act = r.get("final_action")
        if act in ("STRONG_BUY", "BUY"):
            add(_mk_alert("BUY_ALERT", "INFO", sym,
                          f"{r.get('strategy_name')} signals {act} (opp score {r.get('opportunity_score')})",
                          conf, f"Review {sym} — entry ₹{r.get('entry_price')}, SL ₹{r.get('stop_loss')}, target ₹{r.get('target_price')}",
                          scan_id, "trade"))
        if (r.get("volume_ratio") or 0) >= 2.0:
            add(_mk_alert("HIGH_VOLUME_BREAKOUT", "INFO", sym,
                          f"Volume {r.get('volume_ratio')}x average", conf,
                          f"Watch {sym} for continuation", scan_id, "market"))
        if (r.get("adx") or 0) >= 30 and (r.get("rsi") or 0) > 55 and r.get("above_ema20"):
            add(_mk_alert("MOMENTUM_INCREASING", "INFO", sym,
                          f"ADX {r.get('adx')}, RSI {r.get('rsi')}, above EMA20", conf,
                          f"Monitor {sym} for entry setup", scan_id, "market"))
        if r.get("above_ema50") and not r.get("above_ema20") and (r.get("rsi") or 50) < 45:
            add(_mk_alert("WEAKENING_TREND", "WARNING", sym,
                          f"Price slipped below EMA20 with RSI {r.get('rsi')}", conf,
                          f"Caution on {sym} — trend weakening", scan_id, "market"))

    # Position alerts: SL / target proximity based on scan prices
    for p in pm["positions"]:
        r = _rec_for(p["symbol"] or "")
        if not r:
            continue
        price = r.get("entry_price")  # latest close from scan snapshot
        sl, tgt = p.get("stop_loss"), p.get("target")
        if price and sl and price <= float(sl):
            add(_mk_alert("STOP_LOSS_HIT", "CRITICAL", p["symbol"],
                          f"Latest price ₹{price} at/below stop loss ₹{sl}", None,
                          f"Review exit for {p['symbol']} — manual confirmation required", scan_id, "risk"))
        elif price and sl and price <= float(sl) * 1.02:
            add(_mk_alert("SELL_ALERT", "WARNING", p["symbol"],
                          f"Price ₹{price} within 2% of stop loss ₹{sl}", None,
                          f"Watch {p['symbol']} closely", scan_id, "risk"))
        if price and tgt and price >= float(tgt):
            add(_mk_alert("TARGET_ACHIEVED", "INFO", p["symbol"],
                          f"Latest price ₹{price} at/above target ₹{tgt}", None,
                          f"Consider booking profit on {p['symbol']}", scan_id, "trade"))

    # Market-level alerts
    vix_cat = mkt.get("vix_category")
    if vix_cat in ("HIGH", "ELEVATED", "EXTREME"):
        add(_mk_alert("VOLATILITY_RISING", "WARNING", None,
                      f"India VIX at {mkt.get('vix')} ({vix_cat})", None,
                      "Reduce position sizes; widen stops with care", scan_id, "market"))
    if pm["deployed_pct"] >= 70:
        add(_mk_alert("RISK_LIMIT_REACHED", "CRITICAL", None,
                      f"Portfolio {pm['deployed_pct']}% deployed (cap 80%)", None,
                      "Avoid new entries until exposure reduces", scan_id, "risk"))

    # Regime change detection vs previous alert history
    regime = mkt.get("regime")
    prev_regime_alerts = [a for a in existing if a.get("type") == "MARKET_REGIME_CHANGED"]
    last_regime = prev_regime_alerts[-1].get("reason", "").split("→")[-1].strip() if prev_regime_alerts else None
    stored_regime = _load(os.path.join(_DIR, "phase9_last_regime.json"), {}).get("regime")
    if regime and stored_regime and regime != stored_regime:
        add(_mk_alert("MARKET_REGIME_CHANGED", "WARNING", None,
                      f"Regime changed: {stored_regime} → {regime}", None,
                      "Re-evaluate open positions against new regime", scan_id, "market"))
    if regime:
        _save(os.path.join(_DIR, "phase9_last_regime.json"), {"regime": regime, "ts": _now()})

    # Confidence increase/decrease vs previous snapshot
    hist = _load(CONF_HISTORY_FILE, [])
    if len(hist) >= 2:
        prev = {s["symbol"]: s for s in hist[-2].get("stocks", [])}
        curr = {s["symbol"]: s for s in hist[-1].get("stocks", [])}
        for sym, c in curr.items():
            p = prev.get(sym)
            if not p:
                continue
            dc = (c.get("confidence") or 0) - (p.get("confidence") or 0)
            if dc >= 10:
                add(_mk_alert("CONFIDENCE_INCREASED", "INFO", sym,
                              f"Confidence rose {round(dc)} pts ({p.get('confidence')} → {c.get('confidence')})",
                              c.get("confidence"), f"Re-check {sym} setup", scan_id, "ai"))
            elif dc <= -10:
                add(_mk_alert("CONFIDENCE_DECREASED", "WARNING", sym,
                              f"Confidence fell {round(-dc)} pts ({p.get('confidence')} → {c.get('confidence')})",
                              c.get("confidence"), f"Reduce priority on {sym}", scan_id, "ai"))

    # Sector rotation: top sector changed
    top, _weak = _sector_lists()
    stored_sector = _load(os.path.join(_DIR, "phase9_last_sector.json"), {}).get("top_sector")
    if top:
        if stored_sector and top[0]["sector"] != stored_sector:
            add(_mk_alert("SECTOR_ROTATION", "INFO", None,
                          f"Leading sector rotated: {stored_sector} → {top[0]['sector']}", None,
                          f"Focus scans on {top[0]['sector']}", scan_id, "market"))
        _save(os.path.join(_DIR, "phase9_last_sector.json"), {"top_sector": top[0]["sector"], "ts": _now()})

    all_alerts = existing + new
    _save_alerts(all_alerts)
    return {
        "success": True,
        "generated_at": _now(),
        "scan_id": scan_id,
        "new_alerts": len(new),
        "total_alerts": len(all_alerts),
        "alerts": new,
        "label": LABEL,
    }


def list_alerts(limit: int = 100) -> dict:
    alerts = _load_alerts()
    alerts_sorted = sorted(alerts, key=lambda a: a.get("ts", ""), reverse=True)[:limit]
    today = _today()
    unread = [a for a in alerts_sorted if not a.get("read")]
    return {
        "success": True,
        "total": len(alerts),
        "unread_count": len([a for a in alerts if not a.get("read")]),
        "sections": {
            "today": [a for a in alerts_sorted if a.get("date") == today],
            "unread": unread,
            "risk_alerts": [a for a in alerts_sorted if a.get("category") == "risk"],
            "market_alerts": [a for a in alerts_sorted if a.get("category") == "market"],
            "ai_suggestions": [a for a in alerts_sorted if a.get("category") == "ai"],
            "trade_alerts": [a for a in alerts_sorted if a.get("category") == "trade"],
        },
        "alerts": alerts_sorted,
        "label": LABEL,
    }


def mark_alerts_read(alert_id: str = "all") -> dict:
    alerts = _load_alerts()
    n = 0
    for a in alerts:
        if alert_id == "all" or a.get("alert_id") == alert_id:
            if not a.get("read"):
                a["read"] = True
                n += 1
    _save_alerts(alerts)
    return {"success": True, "marked_read": n, "unread_remaining": len([a for a in alerts if not a.get("read")])}


# ── 3. Daily briefing ─────────────────────────────────────────────────────────

def daily_briefing() -> dict:
    mkt = _market()
    scan = _scan()
    pm = _portfolio_metrics()
    recs = _recs()
    top, weak = _sector_lists()
    regime = mkt.get("regime", "UNKNOWN")
    bias = mkt.get("bias", "NEUTRAL")
    vix = mkt.get("vix")
    vix_cat = mkt.get("vix_category", "UNKNOWN")

    opportunities = [
        {"symbol": r.get("symbol"), "action": r.get("final_action"),
         "confidence": r.get("calibrated_confidence"), "opportunity_score": r.get("opportunity_score"),
         "strategy": r.get("strategy_name")}
        for r in sorted(recs, key=lambda r: -(r.get("opportunity_score") or 0))[:5]
    ]
    avoid_symbols = [r.get("symbol") for r in sorted(recs, key=lambda r: (r.get("opportunity_score") or 0))[:3]]

    hour = datetime.now(timezone.utc).hour
    greeting = "Good Morning" if 0 <= (hour + 5.5) % 24 < 12 else "Good Afternoon" if (hour + 5.5) % 24 < 17 else "Good Evening"

    lines = [
        f"{greeting}.",
        f"Market regime is {regime.replace('_', ' ').title()} with {bias.replace('_', ' ').lower()} sentiment.",
    ]
    if top:
        lines.append(f"{top[0]['sector']} sector is strongest.")
    if weak:
        lines.append(f"{weak[0]['sector']} sector is weakest — approach with caution.")
    if opportunities:
        o = opportunities[0]
        lines.append(f"Watch {o['symbol']} — top opportunity today (score {o['opportunity_score']}).")
    if avoid_symbols:
        lines.append(f"Avoid {', '.join(avoid_symbols[:2])} today.")
    lines.append(f"Portfolio risk remains {pm['risk_level'].lower()} with {pm['open_positions']} open position(s) and ₹{round(pm['cash'])} cash.")
    lines.append(f"Expected volatility: {str(vix_cat).lower()} (VIX {vix}).")
    voice_text = " ".join(lines)

    return {
        "success": True,
        "generated_at": _now(),
        "date": _today(),
        "greeting": greeting,
        "market_summary": {
            "regime": regime, "sentiment": bias,
            "nifty_trend": mkt.get("nifty_trend"), "nifty_change_pct": mkt.get("nifty_change_pct"),
            "breadth": mkt.get("breadth_label"),
        },
        "top_sectors": top,
        "weak_sectors": weak,
        "opportunities": opportunities,
        "avoid": avoid_symbols,
        "portfolio_summary": pm,
        "risk_assessment": pm["risk_level"],
        "expected_volatility": {"vix": vix, "category": vix_cat},
        "economic_events": [
            {"event": "Economic calendar integration", "status": "PLACEHOLDER",
             "note": "External economic events feed not connected in research build"}
        ],
        "briefing_lines": lines,
        "voice_text": voice_text,
        "label": LABEL,
    }


# ── 4. Trade explanations ─────────────────────────────────────────────────────

def _explain_rec(r: dict) -> dict:
    supporting, against = [], []
    rsi, adx, vr = r.get("rsi"), r.get("adx"), r.get("volume_ratio")

    if r.get("above_ema20"):
        supporting.append("Price above EMA20 (short-term uptrend)")
    else:
        against.append("Price below EMA20 (short-term weakness)")
    if r.get("above_ema50"):
        supporting.append("Price above EMA50 (medium-term uptrend)")
    else:
        against.append("Price below EMA50 (medium-term weakness)")
    if rsi is not None:
        if 50 <= rsi <= 70:
            supporting.append(f"RSI {rsi} — healthy momentum")
        elif rsi > 70:
            against.append(f"RSI {rsi} — overbought risk")
        elif rsi < 40:
            against.append(f"RSI {rsi} — weak momentum")
        else:
            against.append(f"RSI {rsi} — below momentum threshold (50)")
    if adx is not None:
        (supporting if adx >= 25 else against).append(
            f"ADX {adx} — {'strong trend' if adx >= 25 else 'weak/no trend'}")
    if vr is not None:
        (supporting if vr >= 1.2 else against).append(
            f"Volume {vr}x average — {'above' if vr >= 1.2 else 'below'} confirmation level")
    if (r.get("rr_ratio") or 0) >= 1.5:
        supporting.append(f"Risk/Reward {r.get('rr_ratio')} meets minimum 1.5")
    else:
        against.append(f"Risk/Reward {r.get('rr_ratio')} below minimum 1.5")

    regime = r.get("regime")
    mkt_regime = _market().get("regime")
    if regime and mkt_regime:
        if regime == mkt_regime:
            supporting.append(f"Strategy regime ({regime}) matches market")
        else:
            against.append(f"Strategy regime ({regime}) mismatches market ({mkt_regime})")

    conf = r.get("calibrated_confidence") or 0
    risk = "LOW" if conf >= 65 and (r.get("rr_ratio") or 0) >= 2 else "HIGH" if conf < 45 else "MEDIUM"

    entry, tgt = r.get("entry_price"), r.get("target_price")
    expected_reward_pct = round((tgt - entry) / entry * 100, 2) if entry and tgt else None

    action = r.get("final_action", "IGNORE")
    voice_text = (
        f"{action.replace('_', ' ')} {r.get('symbol')}. "
        + (f"Main reasons: {'; '.join(supporting[:3])}. " if supporting else "")
        + (f"Concerns: {'; '.join(against[:2])}. " if against else "")
        + f"Risk is {risk.lower()}. "
        + (f"Expected holding period {r.get('expected_holding_days')} days. " if r.get("expected_holding_days") else "")
        + (f"Historical win rate {round(r.get('win_rate') or 0)} percent." if r.get("win_rate") is not None else "")
    )

    return {
        "symbol": r.get("symbol"),
        "action": action,
        "strategy": r.get("strategy_name"),
        "confidence": conf,
        "opportunity_score": r.get("opportunity_score"),
        "indicators_supporting": supporting,
        "indicators_against": against,
        "risk": risk,
        "expected_holding_period_days": r.get("expected_holding_days"),
        "historical_win_rate": r.get("win_rate"),
        "historical_trades": r.get("total_trades"),
        "profit_factor": r.get("profit_factor"),
        "entry_price": entry,
        "stop_loss": r.get("stop_loss"),
        "target_price": tgt,
        "expected_reward_pct": expected_reward_pct,
        "rr_ratio": r.get("rr_ratio"),
        "data_quality": r.get("data_quality"),
        "voice_text": voice_text,
    }


def trade_explanations(limit: int = 20) -> dict:
    recs = sorted(_recs(), key=lambda r: -(r.get("opportunity_score") or 0))[:limit]
    return {
        "success": True,
        "generated_at": _now(),
        "scan_id": _scan().get("scan_id"),
        "explanations": [_explain_rec(r) for r in recs],
        "label": LABEL,
    }


def trade_explanation(symbol: str) -> dict:
    r = _rec_for(symbol)
    if not r:
        return {"success": False, "error": f"{symbol.upper()} not found in latest scan"}
    if r.get("error"):
        return {"success": False, "error": f"{symbol.upper()} had scan error: {r.get('error')}"}
    return {"success": True, "generated_at": _now(), "scan_id": _scan().get("scan_id"),
            "explanation": _explain_rec(r), "label": LABEL}


# ── 5. Why not buy? ───────────────────────────────────────────────────────────

def why_not(symbol: str) -> dict:
    r = _rec_for(symbol)
    if not r:
        return {"success": False, "error": f"{symbol.upper()} not found in latest scan"}
    if r.get("error"):
        return {"success": True, "symbol": symbol.upper(), "final_action": "ERROR",
                "reasons": [f"Scan error: {r.get('error')}"], "failed_rules": [],
                "missing_confirmations": [], "label": LABEL}

    reasons, failed_rules, missing = [], [], []
    gates = {
        "gate_price": "Price gate (min price / liquidity)",
        "gate_data_quality": "Data quality gate",
        "gate_rr": "Risk/Reward gate (min 1.5)",
        "gate_volume": "Volume gate",
    }
    for g, lab in gates.items():
        if not r.get(g, True):
            failed_rules.append(lab)
            reasons.append(f"Failed: {lab}")

    if (r.get("rsi") or 50) < 50:
        missing.append(f"RSI below threshold ({r.get('rsi')} < 50)")
    if not r.get("above_ema20"):
        missing.append("Price not above EMA20")
    if not r.get("above_ema50"):
        missing.append("Price not above EMA50")
    if (r.get("volume_ratio") or 1) < 1.2:
        missing.append(f"Volume confirmation missing ({r.get('volume_ratio')}x < 1.2x)")
    if (r.get("adx") or 25) < 25:
        missing.append(f"Trend strength insufficient (ADX {r.get('adx')} < 25)")

    mkt_regime = _market().get("regime")
    if r.get("regime") and mkt_regime and r.get("regime") != mkt_regime:
        reasons.append(f"Market regime mismatch (strategy: {r.get('regime')}, market: {mkt_regime})")

    conf = r.get("calibrated_confidence")
    hist_adj = r.get("historical_evidence_adjustment")
    confidence_lost = None
    if hist_adj is not None and hist_adj < 0:
        confidence_lost = abs(hist_adj)
        reasons.append(f"Confidence reduced {confidence_lost} pts by weak historical evidence")

    if r.get("final_action") == "IGNORE" and not reasons and not missing:
        reasons.append(f"Opportunity score too low ({r.get('opportunity_score')})")

    voice_text = (
        f"{symbol.upper()} was {'ignored' if r.get('final_action') == 'IGNORE' else 'rated ' + str(r.get('final_action'))}. "
        + (f"Missing confirmations: {'; '.join(missing[:3])}. " if missing else "")
        + (f"{reasons[0]}." if reasons else "")
    )

    return {
        "success": True,
        "symbol": symbol.upper(),
        "final_action": r.get("final_action"),
        "confidence": conf,
        "confidence_lost_to_history": confidence_lost,
        "opportunity_score": r.get("opportunity_score"),
        "reasons": reasons or ["All gates passed — score simply below actionable threshold"],
        "failed_rules": failed_rules,
        "missing_confirmations": missing,
        "voice_text": voice_text,
        "label": LABEL,
    }


# ── 7. Watchlist insights ─────────────────────────────────────────────────────

def watchlist_insights() -> dict:
    wl = _watchlist()
    insights = []
    for sym in wl:
        r = _rec_for(sym)
        if not r or r.get("error"):
            insights.append({"symbol": sym, "available": False,
                             "note": "Not in latest scan or scan error"})
            continue
        rsi, adx = r.get("rsi"), r.get("adx")
        trend = "UP" if r.get("above_ema20") and r.get("above_ema50") else \
                "DOWN" if not r.get("above_ema20") and not r.get("above_ema50") else "MIXED"
        momentum = "STRONG" if (rsi or 0) >= 60 else "WEAK" if (rsi or 50) < 45 else "NEUTRAL"
        strength = "STRONG" if (adx or 0) >= 30 else "MODERATE" if (adx or 0) >= 20 else "WEAK"
        entry, sl, tgt = r.get("entry_price"), r.get("stop_loss"), r.get("target_price")
        upside = round((tgt - entry) / entry * 100, 2) if entry and tgt else None
        downside = round((entry - sl) / entry * 100, 2) if entry and sl else None
        conf = r.get("calibrated_confidence") or 0
        risk = "LOW" if conf >= 65 else "HIGH" if conf < 45 else "MEDIUM"
        insights.append({
            "symbol": sym, "available": True,
            "action": r.get("final_action"),
            "trend": trend, "momentum": momentum, "strength": strength,
            "confidence": conf,
            "estimated_upside_pct": upside,
            "estimated_downside_pct": downside,
            "risk": risk,
            "holding_period_days": r.get("expected_holding_days"),
            "rsi": rsi, "adx": adx, "volume_ratio": r.get("volume_ratio"),
            "price": entry, "data_quality": r.get("data_quality"),
        })
    return {"success": True, "generated_at": _now(), "watchlist_size": len(wl),
            "insights": insights, "scan_id": _scan().get("scan_id"), "label": LABEL}


# ── 8. Confidence history ─────────────────────────────────────────────────────

def record_confidence_snapshot() -> dict:
    """Append one snapshot per scan_id (idempotent). No look-ahead: only cached scan."""
    scan = _scan()
    scan_id = scan.get("scan_id")
    if not scan_id:
        return {"success": False, "error": "No cached scan available"}
    hist = _load(CONF_HISTORY_FILE, [])
    if any(h.get("scan_id") == scan_id for h in hist):
        return {"success": True, "recorded": False, "reason": "Snapshot for this scan already recorded",
                "snapshots": len(hist)}
    recs = _recs()
    stocks = [{
        "symbol": r.get("symbol"),
        "confidence": r.get("calibrated_confidence"),
        "opportunity_score": r.get("opportunity_score"),
        "action": r.get("final_action"),
        "technical_score": r.get("technical_score"),
    } for r in recs]
    quality = [r for r in recs if r.get("all_gates_passed")]
    hist.append({
        "scan_id": scan_id,
        "snapshot_ts": scan.get("snapshot_ts"),
        "recorded_at": _now(),
        "avg_confidence": round(sum((s["confidence"] or 0) for s in stocks) / len(stocks), 1) if stocks else 0,
        "avg_opportunity_score": round(sum((s["opportunity_score"] or 0) for s in stocks) / len(stocks), 1) if stocks else 0,
        "trade_quality_pct": round(len(quality) / len(recs) * 100, 1) if recs else 0,
        "buy_count": len([s for s in stocks if s["action"] in ("STRONG_BUY", "BUY")]),
        "watch_count": len([s for s in stocks if s["action"] == "WATCH"]),
        "stocks": stocks,
    })
    _save(CONF_HISTORY_FILE, hist[-MAX_HISTORY_SNAPSHOTS:])
    return {"success": True, "recorded": True, "scan_id": scan_id, "snapshots": len(hist)}


def confidence_history(symbol: str | None = None) -> dict:
    hist = _load(CONF_HISTORY_FILE, [])
    series = [{
        "scan_id": h.get("scan_id"),
        "snapshot_ts": h.get("snapshot_ts"),
        "avg_confidence": h.get("avg_confidence"),
        "avg_opportunity_score": h.get("avg_opportunity_score"),
        "trade_quality_pct": h.get("trade_quality_pct"),
        "buy_count": h.get("buy_count"),
        "watch_count": h.get("watch_count"),
    } for h in hist]
    out = {"success": True, "snapshots": len(hist), "series": series, "label": LABEL}
    if symbol:
        sym = symbol.upper()
        out["symbol"] = sym
        out["symbol_series"] = [
            {"scan_id": h.get("scan_id"), "snapshot_ts": h.get("snapshot_ts"),
             **next(({"confidence": s.get("confidence"), "opportunity_score": s.get("opportunity_score"),
                      "action": s.get("action")} for s in h.get("stocks", []) if s.get("symbol") == sym),
                    {"confidence": None, "opportunity_score": None, "action": None})}
            for h in hist
        ]
    return out


# ── 10. Export ────────────────────────────────────────────────────────────────

def export_phase9(kind: str = "json") -> dict:
    os.makedirs(EXPORT_DIR, exist_ok=True)
    alerts = _load_alerts()
    summary = copilot_summary()
    briefing = daily_briefing()
    if kind == "csv":
        path = os.path.join(EXPORT_DIR, "phase9_alerts.csv")
        cols = ["alert_id", "ts", "type", "severity", "category", "symbol",
                "reason", "confidence", "action_recommendation", "scan_id", "read"]
        with open(path, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
            w.writeheader()
            for a in alerts:
                w.writerow(a)
        # Also write summaries CSV
        spath = os.path.join(EXPORT_DIR, "phase9_summaries.csv")
        with open(spath, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["generated_at", "kind", "voice_text"])
            w.writerow([summary.get("generated_at"), "copilot_summary", summary.get("voice_text")])
            w.writerow([briefing.get("generated_at"), "daily_briefing", briefing.get("voice_text")])
        return {"success": True, "file": path, "summaries_file": spath,
                "alerts_exported": len(alerts), "label": LABEL}
    path = os.path.join(EXPORT_DIR, "phase9_export.json")
    _save(path, {"exported_at": _now(), "label": LABEL, "alerts": alerts,
                 "copilot_summary": summary, "daily_briefing": briefing})
    return {"success": True, "file": path, "alerts_exported": len(alerts), "label": LABEL}
