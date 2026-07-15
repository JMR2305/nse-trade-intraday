"""
phase18_notebook.py — Phase 18: Research Notebook & Daily Validation Workflow

A permanent daily research journal. One entry per IST trading date, created
automatically after the first successful scan of the day, updated intraday,
and finalized after market close by the user.

Strictly research / paper-trading only:
- Never places, closes, or modifies trades.
- Never changes thresholds, models, strategies, or risk limits.
- Records evidence only from stored platform data — nothing is invented.
- Missing data is marked "Insufficient Data", never fabricated.

Storage:
- phase18_notebook.json  {"entries": {"YYYY-MM-DD": entry}}
- phase18_issues.json    {"issues": [...], "next_id": int}
- phase18_targets.json   configurable evidence-readiness targets
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import market_hours
import phase15_scan_context as scan_ctx

_DIR = os.path.dirname(os.path.abspath(__file__))
NOTEBOOK_PATH = os.path.join(_DIR, "phase18_notebook.json")
ISSUES_PATH = os.path.join(_DIR, "phase18_issues.json")
TARGETS_PATH = os.path.join(_DIR, "phase18_targets.json")

INSUFFICIENT = "Insufficient Data"
NOT_APPLICABLE = "NOT APPLICABLE"
LABEL = "PAPER / RESEARCH ONLY"

DECISION_STATES = [
    "PAPER TRADE TAKEN", "SKIPPED", "WATCHED", "REJECTED BY RISK",
    "REJECTED BY DATA QUALITY", "NO ACTION", "POSITION EXITED",
]
ISSUE_STATUSES = ["OPEN", "INVESTIGATING", "FIXED", "VERIFIED", "DEFERRED"]
ISSUE_SEVERITIES = ["CRITICAL", "HIGH", "MEDIUM", "LOW"]

DEFAULT_TARGETS = {
    "trading_sessions": 50,
    "completed_paper_trades": 100,
    "market_regimes": 3,
    "min_strategy_sample": 20,
    "min_confidence_band_sample": 15,
    "max_unresolved_critical_issues": 0,
    "note": "Configurable readiness targets — advisory only, never auto-promote.",
}


# ── low-level io ─────────────────────────────────────────────────────────────

_LOCK_PATH = os.path.join(_DIR, "phase18_state.lock")


def _locked(fn):
    """Serialize read-modify-write cycles across concurrently spawned
    processes with an exclusive advisory file lock (prevents lost updates)."""
    import fcntl
    from functools import wraps

    @wraps(fn)
    def wrapper(*args, **kwargs):
        with open(_LOCK_PATH, "a") as lf:
            fcntl.flock(lf, fcntl.LOCK_EX)
            try:
                return fn(*args, **kwargs)
            finally:
                fcntl.flock(lf, fcntl.LOCK_UN)
    return wrapper


def _now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _fmt_inr(v: Any) -> str:
    try:
        return f"₹{float(v):,.2f}"
    except (TypeError, ValueError):
        return INSUFFICIENT


def _load(path: str, default: Any) -> Any:
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return default


def _save(path: str, data: Any) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2, default=str)
    os.replace(tmp, path)


def _load_json_file(fname: str, default: Any) -> Any:
    return _load(os.path.join(_DIR, fname), default)


def _notebook() -> Dict[str, Any]:
    nb = _load(NOTEBOOK_PATH, {"entries": {}})
    if "entries" not in nb:
        nb["entries"] = {}
    return nb


def _save_notebook(nb: Dict[str, Any]) -> None:
    _save(NOTEBOOK_PATH, nb)


def ist_today() -> str:
    return market_hours.now_ist().date().isoformat()


# ── data integrity block (spec §15) ──────────────────────────────────────────

def _integrity_block(ctx: Dict[str, Any]) -> Dict[str, Any]:
    registry = _load_json_file("phase14_model_registry.json", {})
    calib = _load_json_file("calibration_state.json", {})
    provider = INSUFFICIENT
    scan = _load_json_file("phase7_scan_cache.json", {})
    audit = scan.get("scan_audit") or {}
    provider = audit.get("data_provider") or audit.get("provider") or scan.get("provider") or "yfinance"
    return {
        "source_scan_id": ctx.get("scan_id") or INSUFFICIENT,
        "source_snapshot_ts": ctx.get("snapshot_ts") or INSUFFICIENT,
        "data_provider": provider,
        "data_age_seconds": ctx.get("scan_age_seconds"),
        "model_version": registry.get("champion_version") or INSUFFICIENT,
        "calibrator_version": ("active" if calib.get("active") else INSUFFICIENT)
                              if isinstance(calib, dict) else INSUFFICIENT,
        "paper_trading_mode": True,
        "live_execution_enabled": False,
    }


# ── market / platform snapshots (stored data only) ──────────────────────────

def _market_snapshot() -> Dict[str, Any]:
    mc = _load_json_file("market_context_cache.json", {})
    sectors = mc.get("sector_strength") or {}
    ranked = sorted(sectors, key=lambda s: sectors[s], reverse=True) if sectors else []
    return {
        "market_regime": mc.get("regime") or INSUFFICIENT,
        "nifty_price": mc.get("nifty_price"),
        "nifty_trend": mc.get("nifty_trend") or INSUFFICIENT,
        "nifty_change_pct": mc.get("nifty_change_pct"),
        "banknifty_price": mc.get("banknifty_price"),
        "banknifty_trend": mc.get("banknifty_trend") or INSUFFICIENT,
        "banknifty_change_pct": mc.get("banknifty_change_pct"),
        "india_vix": mc.get("vix"),
        "vix_category": mc.get("vix_category") or INSUFFICIENT,
        "market_breadth": mc.get("market_breadth"),
        "breadth_label": mc.get("breadth_label") or INSUFFICIENT,
        "strongest_sectors": ranked[:3] if ranked else [INSUFFICIENT],
        "weakest_sectors": ranked[-3:][::-1] if ranked else [INSUFFICIENT],
        "context_computed_at": mc.get("computed_at") or INSUFFICIENT,
    }


def _data_quality_summary(ctx: Dict[str, Any]) -> Dict[str, Any]:
    if not ctx.get("available"):
        return {"status": INSUFFICIENT, "reason": ctx.get("reason")}
    syms = ctx.get("symbols", {})
    counts: Dict[str, int] = {}
    errors = 0
    for s in syms.values():
        if s.get("error"):
            errors += 1
        q = s.get("data_quality") or "UNKNOWN"
        counts[q] = counts.get(q, 0) + 1
    return {
        "status": "OK" if not ctx.get("stale") else "STALE",
        "scan_stale": ctx.get("stale"),
        "symbols_scanned": len(syms),
        "symbol_errors": errors,
        "quality_counts": counts,
    }


def _opportunities(ctx: Dict[str, Any], top: int = 5) -> List[Dict[str, Any]]:
    if not ctx.get("available"):
        return []
    ranked = sorted(
        (s for s in ctx["symbols"].values() if not s.get("error")),
        key=lambda s: float(s.get("opportunity_score") or 0), reverse=True)
    out = []
    for s in ranked[:top]:
        out.append({k: s.get(k) for k in (
            "symbol", "final_action", "effective_action", "opportunity_score",
            "confidence", "strategy_name", "sector", "rr_ratio")})
    return out


def _avoid_list(ctx: Dict[str, Any], top: int = 5) -> List[Dict[str, Any]]:
    if not ctx.get("available"):
        return []
    out = []
    for s in ctx["symbols"].values():
        if s.get("error") or s.get("final_action") in ("AVOID", "IGNORE", "SELL") \
                or s.get("all_gates_passed") is False:
            out.append({
                "symbol": s.get("symbol"), "final_action": s.get("final_action"),
                "reason": (s.get("error") or
                           ("failed gates: " + ", ".join(k for k, v in (s.get("gates") or {}).items() if v is False)
                            if s.get("all_gates_passed") is False else "action")),
            })
    return out[:top]


def _trades_on(date_iso: str) -> List[Dict[str, Any]]:
    """All raw trades whose IST date == date_iso."""
    state = _load_json_file("state.json", {})
    out = []
    for t in state.get("trades", []):
        ts = str(t.get("timestamp") or "")
        try:
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            d = dt.astimezone(market_hours.IST).date().isoformat()
        except Exception:
            d = ts[:10]
        if d == date_iso:
            out.append(t)
    return out


def _open_positions() -> List[Dict[str, Any]]:
    state = _load_json_file("state.json", {})
    pos = state.get("positions", {})
    out = []
    for sym, p in pos.items():
        out.append({"symbol": sym, "quantity": p.get("quantity"),
                    "avg_price": p.get("avg_price"),
                    "stop_loss": p.get("stop_loss"), "target": p.get("target"),
                    "scan_id": p.get("scan_id")})
    return out


def _validation_summary() -> Dict[str, Any]:
    last = _load_json_file("phase17_last_run.json", {})
    if not last:
        return {"status": INSUFFICIENT}
    return {
        "generated_at": last.get("generated_at"),
        "verdict": last.get("verdict"),
        "health_score": last.get("health_score"),
        "readiness_status": last.get("readiness_status"),
        "passed": last.get("passed"), "failed": last.get("failed"),
        "warnings": last.get("warnings"),
    }


def _alerts_on(date_iso: str) -> int:
    n = 0
    for fname, key in (("phase9_alerts.json", "alerts"), ("phase14_alerts.json", "alerts")):
        data = _load_json_file(fname, {})
        items = data if isinstance(data, list) else data.get(key, [])
        if isinstance(items, list):
            for a in items:
                ts = str(a.get("created_at") or a.get("timestamp") or "")
                if ts[:10] == date_iso:
                    n += 1
    return n


# ── decision journal (spec §3) ───────────────────────────────────────────────

def _auto_decisions(ctx: Dict[str, Any], date_iso: str) -> List[Dict[str, Any]]:
    """Platform-derived decision rows for every symbol in the canonical scan."""
    if not ctx.get("available"):
        return []
    trades = _trades_on(date_iso)
    bought = {t.get("symbol") for t in trades if t.get("action") == "BUY"}
    sold = {t.get("symbol") for t in trades if t.get("action") == "SELL"}
    rows = []
    for s in ctx["symbols"].values():
        sym = s.get("symbol")
        if s.get("error"):
            state = "REJECTED BY DATA QUALITY"
        elif sym in sold:
            state = "POSITION EXITED"
        elif sym in bought:
            state = "PAPER TRADE TAKEN"
        elif s.get("all_gates_passed") is False:
            gates = s.get("gates") or {}
            if gates.get("data_quality") is False:
                state = "REJECTED BY DATA QUALITY"
            elif gates.get("rr") is False or gates.get("price") is False:
                state = "REJECTED BY RISK"
            else:
                state = "NO ACTION"
        elif s.get("effective_action") == "WATCH":
            state = "WATCHED"
        elif s.get("final_action") in ("STRONG BUY", "BUY"):
            state = "SKIPPED"  # recommended but not taken (yet)
        else:
            state = "NO ACTION"
        gates = s.get("gates") or {}
        blocking = ", ".join(k for k, v in gates.items() if v is False) or None
        rows.append({
            "symbol": sym,
            "raw_signal": s.get("final_action"),
            "final_action": s.get("effective_action"),
            "decision_state": state,
            "confidence": s.get("confidence"),
            "opportunity_score": s.get("opportunity_score"),
            "strategy": s.get("strategy_name"),
            "market_regime": s.get("regime") or ctx.get("market_regime"),
            "sector": s.get("sector"),
            "sector_rank": s.get("sector_rank"),
            "rr_ratio": s.get("rr_ratio"),
            "data_quality": s.get("data_quality"),
            "blocking_rule": blocking,
            "explanation": (s.get("error") or
                            (f"Blocked by gate(s): {blocking}" if blocking else
                             f"Scan action {s.get('final_action')}")),
            "user_action": None,       # set via record_user_decision
            "user_reason": None,
            "outcome": None,           # filled at finalize / when trade closes
            "scan_id": ctx.get("scan_id"),
        })
    return rows


@_locked
def record_user_decision(date_iso: str, symbol: str, user_action: str,
                         reason: str = "") -> Dict[str, Any]:
    """Record what the user actually did (taken / skipped) with a reason."""
    if user_action not in DECISION_STATES:
        return {"success": False,
                "error": f"user_action must be one of {DECISION_STATES}"}
    nb = _notebook()
    entry = nb["entries"].get(date_iso)
    if not entry:
        return {"success": False, "error": f"No notebook entry for {date_iso}"}
    sym = symbol.upper()
    found = False
    for row in entry.get("decisions", []):
        if row["symbol"] == sym:
            row["user_action"] = user_action
            row["user_reason"] = reason[:500]
            found = True
    if not found:
        entry.setdefault("decisions", []).append({
            "symbol": sym, "raw_signal": INSUFFICIENT, "final_action": INSUFFICIENT,
            "decision_state": user_action, "user_action": user_action,
            "user_reason": reason[:500], "scan_id": entry.get("integrity", {}).get("source_scan_id"),
            "explanation": "Manually added by user — not in canonical scan.",
        })
    entry["updated_at"] = _now_utc()
    _save_notebook(nb)
    return {"success": True, "date": date_iso, "symbol": sym,
            "user_action": user_action, "label": LABEL}


# ── daily checklist (spec §5) ────────────────────────────────────────────────

def _checklist(entry: Dict[str, Any], ctx: Dict[str, Any],
               date_iso: str) -> Dict[str, List[Dict[str, str]]]:
    def item(name: str, status: str, detail: str = "") -> Dict[str, str]:
        return {"item": name, "status": status, "detail": detail}

    status = market_hours.market_status()
    kill = _load_json_file("phase11_kill_switch.json", {})
    val = _validation_summary()
    trades = _trades_on(date_iso)
    positions = _open_positions()
    consistency = _load_json_file("phase15_consistency_report.json", {})

    scan_ok = bool(ctx.get("available"))
    scan_today = scan_ok and str(ctx.get("snapshot_ts") or "")[:10] == date_iso

    before = [
        item("Data provider healthy",
             "PASS" if scan_ok else "WARNING",
             "canonical scan cache present" if scan_ok else "no scan cache — provider unverified"),
        item("Market calendar valid",
             "PASS" if status.get("timezone") == "Asia/Kolkata" else "FAIL",
             f"state={status.get('state')}"),
        item("Latest historical data available",
             "PASS" if scan_ok and not ctx.get("stale") else
             ("WARNING" if scan_ok else "FAIL"),
             f"scan age {ctx.get('scan_age_seconds')}s" if scan_ok else "no scan"),
        item("Canonical scan context available",
             "PASS" if scan_ok else "FAIL",
             str(ctx.get("scan_id") or ctx.get("reason"))),
        item("Paper-trading mode confirmed", "PASS", "hard-coded paper mode"),
        item("Live execution disabled", "PASS", "no live execution path exists"),
        item("Kill switch available",
             "PASS" if isinstance(kill, dict) and kill else "WARNING",
             "phase11 kill-switch state present" if kill else "kill-switch file missing"),
        item("No critical QA failures",
             "PASS" if val.get("failed") == 0 else
             ("FAIL" if isinstance(val.get("failed"), int) and val["failed"] > 0 else "WARNING"),
             f"last QA verdict={val.get('verdict')} failed={val.get('failed')}"),
    ]

    dup_trades = len(trades) != len({(t.get("symbol"), t.get("action"), t.get("timestamp")) for t in trades})
    missing_stops = [p["symbol"] for p in positions if not p.get("stop_loss") or not p.get("target")]
    mismatches = consistency.get("mismatch_count", None)
    during = [
        item("Scan completed successfully",
             "PASS" if scan_today else ("WARNING" if scan_ok else "FAIL"),
             f"scan_id={ctx.get('scan_id')}" if scan_ok else "no scan"),
        item("No stale-data violations",
             "PASS" if scan_ok and not ctx.get("stale") else "WARNING",
             "scan fresh" if scan_ok and not ctx.get("stale") else "scan stale or missing"),
        item("No cross-page mismatches",
             NOT_APPLICABLE if mismatches is None else ("PASS" if mismatches == 0 else "WARNING"),
             "no consistency report" if mismatches is None else f"{mismatches} mismatches"),
        item("No duplicate paper trades",
             "PASS" if not dup_trades else "FAIL", f"{len(trades)} trades today"),
        item("No duplicate alerts", NOT_APPLICABLE, "alert dedup enforced upstream by scan_id"),
        item("Open positions have stop and target",
             "PASS" if not missing_stops else "WARNING",
             "all covered" if not missing_stops else f"missing: {', '.join(missing_stops)} (legacy metadata)"),
        item("Risk limits respected",
             "PASS" if not any(t.get("blocked") for t in trades) else "WARNING",
             "no blocked trades recorded today"),
    ]

    finalized = entry.get("state") == "FINALIZED"
    after = [
        item("Daily notebook finalized", "PASS" if finalized else "WARNING",
             entry.get("state", "DRAFT")),
        item("Paper trades reconciled",
             "PASS" if finalized else NOT_APPLICABLE,
             "reconciled at finalize" if finalized else "pending finalize"),
        item("Daily P&L reconciled",
             "PASS" if finalized and entry.get("eod") else NOT_APPLICABLE,
             "eod snapshot stored" if finalized else "pending finalize"),
        item("Validation report generated",
             "PASS" if val.get("verdict") else "WARNING",
             f"phase17 verdict={val.get('verdict')}"),
        item("Errors reviewed", NOT_APPLICABLE, "manual review — record in notes"),
        item("Alerts reviewed", NOT_APPLICABLE, "manual review — record in notes"),
        item("Lessons recorded",
             "PASS" if entry.get("lessons_learned") else "WARNING",
             "lessons present" if entry.get("lessons_learned") else "no lessons recorded yet"),
    ]
    return {"before_market": before, "during_market": during, "after_market": after}


# ── entry lifecycle ──────────────────────────────────────────────────────────

def _build_entry(date_iso: str, existing: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    ctx = scan_ctx.build_scan_context()
    market = _market_snapshot()
    status = market_hours.market_status()
    trades = _trades_on(date_iso)
    entry: Dict[str, Any] = existing or {}
    created = entry.get("created_at") or _now_utc()

    # Preserve user-authored fields across refreshes.
    preserved = {k: entry.get(k) for k in
                 ("user_notes", "lessons_learned", "follow_up_actions", "tags",
                  "state", "finalized_at", "eod")}
    user_decisions = {r["symbol"]: (r.get("user_action"), r.get("user_reason"))
                      for r in entry.get("decisions", []) if r.get("user_action")}

    decisions = _auto_decisions(ctx, date_iso)
    for row in decisions:
        ua = user_decisions.get(row["symbol"])
        if ua:
            row["user_action"], row["user_reason"] = ua
    # Keep manually added rows not present in scan.
    known = {r["symbol"] for r in decisions}
    for r in entry.get("decisions", []):
        if r["symbol"] not in known and r.get("user_action"):
            decisions.append(r)

    entry.update({
        "trading_date": date_iso,
        "state": preserved.get("state") or "DRAFT",
        "market_status": {"state": status.get("state"),
                          "is_open": status.get("is_open"),
                          "holiday_today": status.get("holiday_today")},
        "market": market,
        "scan": {
            "scan_id": ctx.get("scan_id") or INSUFFICIENT,
            "snapshot_ts": ctx.get("snapshot_ts") or INSUFFICIENT,
            "stale": ctx.get("stale"),
            "universe_size": ctx.get("universe_size"),
            "historical_source": (str(ctx.get("snapshot_ts") or "")[:10] != date_iso)
                                 if ctx.get("available") else None,
        },
        "data_quality": _data_quality_summary(ctx),
        "best_opportunities": _opportunities(ctx),
        "stocks_to_avoid": _avoid_list(ctx),
        "open_positions": _open_positions(),
        "new_paper_trades": [t for t in trades if t.get("action") == "BUY"],
        "closed_paper_trades": [t for t in trades if t.get("action") == "SELL"],
        "trades_skipped": [r["symbol"] for r in decisions if r["decision_state"] == "SKIPPED"],
        "risk_warnings": [r["symbol"] + ": " + (r.get("blocking_rule") or "")
                          for r in decisions if r["decision_state"] == "REJECTED BY RISK"],
        "validation": _validation_summary(),
        "alerts_generated": _alerts_on(date_iso),
        "decisions": decisions,
        "user_notes": preserved.get("user_notes") or [],
        "lessons_learned": preserved.get("lessons_learned") or "",
        "follow_up_actions": preserved.get("follow_up_actions") or [],
        "tags": preserved.get("tags") or [],
        "eod": preserved.get("eod"),
        "finalized_at": preserved.get("finalized_at"),
        "integrity": _integrity_block(ctx),
        "created_at": created,
        "updated_at": _now_utc(),
        "label": LABEL,
    })
    entry["checklist"] = _checklist(entry, ctx, date_iso)
    return entry


@_locked
def ensure_today_entry() -> Dict[str, Any]:
    """
    Create (once) or refresh today's draft entry. Creation requires a canonical
    scan whose snapshot date is today (spec: after first successful scan of the
    trading day). Never duplicates: keyed by IST date.
    """
    today = ist_today()
    nb = _notebook()
    existing = nb["entries"].get(today)
    ctx = scan_ctx.build_scan_context()
    scan_today = ctx.get("available") and str(ctx.get("snapshot_ts") or "")[:10] == today

    if existing is None and not scan_today:
        return {"success": True, "created": False, "date": today,
                "reason": "No successful scan for today yet — entry not created "
                          "(created automatically after first scan of the day).",
                "label": LABEL}
    if existing is not None and existing.get("state") == "FINALIZED":
        return {"success": True, "created": False, "date": today,
                "finalized": True, "entry": existing, "label": LABEL}
    entry = _build_entry(today, existing)
    nb["entries"][today] = entry
    _save_notebook(nb)
    return {"success": True, "created": existing is None, "date": today,
            "entry": entry, "label": LABEL}


def get_entry(date_iso: Optional[str] = None) -> Dict[str, Any]:
    nb = _notebook()
    date_iso = date_iso or ist_today()
    entry = nb["entries"].get(date_iso)
    if not entry:
        return {"success": True, "available": False, "date": date_iso,
                "reason": "No notebook entry for this date.", "label": LABEL}
    return {"success": True, "available": True, "date": date_iso,
            "entry": entry, "label": LABEL}


def list_entries(limit: int = 60) -> Dict[str, Any]:
    nb = _notebook()
    rows = []
    for d in sorted(nb["entries"], reverse=True)[:limit]:
        e = nb["entries"][d]
        rows.append({
            "trading_date": d, "state": e.get("state"),
            "market_regime": (e.get("market") or {}).get("market_regime"),
            "scan_id": (e.get("scan") or {}).get("scan_id"),
            "trades_opened": len(e.get("new_paper_trades") or []),
            "trades_closed": len(e.get("closed_paper_trades") or []),
            "notes": len(e.get("user_notes") or []),
            "tags": e.get("tags") or [],
            "daily_pnl": (e.get("eod") or {}).get("daily_pnl"),
        })
    return {"success": True, "entries": rows, "total": len(nb["entries"]), "label": LABEL}


@_locked
def save_notes(date_iso: str, notes: Optional[List[Dict[str, Any]]] = None,
               lessons: Optional[str] = None,
               follow_ups: Optional[List[str]] = None,
               tags: Optional[List[str]] = None,
               note_text: Optional[str] = None,
               note_category: str = "observation",
               note_tags: Optional[List[str]] = None) -> Dict[str, Any]:
    """Save / append user notes. Notes never alter trading logic."""
    nb = _notebook()
    entry = nb["entries"].get(date_iso)
    if not entry:
        return {"success": False, "error": f"No notebook entry for {date_iso}"}
    if note_text:
        entry.setdefault("user_notes", []).append({
            "id": uuid.uuid4().hex[:8], "text": note_text[:4000],
            "category": note_category, "tags": note_tags or [],
            "created_at": _now_utc(),
        })
    if notes is not None:
        entry["user_notes"] = notes
    if lessons is not None:
        entry["lessons_learned"] = lessons[:8000]
    if follow_ups is not None:
        entry["follow_up_actions"] = follow_ups
    if tags is not None:
        entry["tags"] = tags
    entry["updated_at"] = _now_utc()
    _save_notebook(nb)
    return {"success": True, "date": date_iso,
            "notes_count": len(entry.get("user_notes") or []), "label": LABEL}


@_locked
def finalize_day(date_iso: Optional[str] = None) -> Dict[str, Any]:
    """Finalize the day's entry with EOD reconciliation (spec §2)."""
    date_iso = date_iso or ist_today()
    nb = _notebook()
    entry = nb["entries"].get(date_iso)
    if not entry:
        return {"success": False, "error": f"No notebook entry for {date_iso}"}
    # Refresh with latest data first (keeps user fields).
    ctx = scan_ctx.build_scan_context()
    entry = _build_entry(date_iso, entry)

    import paper_trader
    portfolio = paper_trader.get_portfolio()
    trades = _trades_on(date_iso)
    sells = [t for t in trades if t.get("action") == "SELL"]
    replay = paper_trader.get_trade_replay()
    closed_today = [r for r in replay if str(r.get("exit_time") or "")[:10] == date_iso]
    stops_hit = sum(1 for r in closed_today if r.get("exit_type") == "STOP_HIT")
    targets_hit = sum(1 for r in closed_today if r.get("exit_type") == "TARGET_HIT")
    daily_pnl = round(sum(float(r.get("pnl") or 0) for r in closed_today), 2)

    high_conf_missed = [r["symbol"] for r in entry.get("decisions", [])
                        if r.get("decision_state") == "SKIPPED"
                        and isinstance(r.get("confidence"), (int, float))
                        and r["confidence"] >= 70]
    false_positives = [r.get("symbol") for r in closed_today
                       if float(r.get("pnl") or 0) < 0
                       and float(r.get("signal_confidence") or 0) >= 70]

    val = _validation_summary()
    entry["eod"] = {
        "portfolio_value": portfolio.get("total_value"),
        "cash": portfolio.get("cash"),
        "daily_pnl": daily_pnl,
        "trades_opened": len([t for t in trades if t.get("action") == "BUY"]),
        "trades_closed": len(sells),
        "stops_hit": stops_hit,
        "targets_hit": targets_hit,
        "exit_recommendations": [r["symbol"] for r in entry.get("decisions", [])
                                 if r.get("decision_state") == "POSITION EXITED"],
        "missed_opportunities": high_conf_missed or [],
        "false_positive_signals": false_positives or [],
        "data_quality_issues": entry.get("data_quality"),
        "alerts_generated": entry.get("alerts_generated"),
        "validation_warnings": val.get("warnings"),
        "qa_status": val.get("verdict") or INSUFFICIENT,
        "final_summary": (
            f"{len(trades)} trade action(s); {len(closed_today)} round-trip(s) closed "
            f"(₹{daily_pnl:+.2f}); {stops_hit} stop(s), {targets_hit} target(s) hit; "
            f"portfolio {_fmt_inr(portfolio.get('total_value'))}. QA: {val.get('verdict') or INSUFFICIENT}."
        ),
    }
    # Fill decision outcomes from replay data.
    outcome_by_symbol = {r.get("symbol"): r for r in closed_today}
    for row in entry.get("decisions", []):
        r = outcome_by_symbol.get(row["symbol"])
        if r:
            row["outcome"] = {"pnl": r.get("pnl"), "pnl_pct": r.get("pnl_pct"),
                              "exit_type": r.get("exit_type"),
                              "classification": r.get("outcome_classification")}
    entry["state"] = "FINALIZED"
    entry["finalized_at"] = _now_utc()
    entry["checklist"] = _checklist(entry, ctx, date_iso)
    entry["updated_at"] = _now_utc()
    nb["entries"][date_iso] = entry
    _save_notebook(nb)
    return {"success": True, "date": date_iso, "eod": entry["eod"],
            "state": "FINALIZED", "label": LABEL}


@_locked
def reopen_day(date_iso: str) -> Dict[str, Any]:
    """Allow the user to edit a finalized day (state back to DRAFT)."""
    nb = _notebook()
    entry = nb["entries"].get(date_iso)
    if not entry:
        return {"success": False, "error": f"No notebook entry for {date_iso}"}
    entry["state"] = "DRAFT"
    entry["updated_at"] = _now_utc()
    _save_notebook(nb)
    return {"success": True, "date": date_iso, "state": "DRAFT", "label": LABEL}


# ── search (spec §4 & §10) ───────────────────────────────────────────────────

def search(query: str = "", tag: str = "", strategy: str = "", sector: str = "",
           regime: str = "", symbol: str = "", outcome: str = "",
           decision_state: str = "", date_from: str = "", date_to: str = "",
           stale_only: bool = False, limit: int = 200) -> Dict[str, Any]:
    """Searchable research memory. Results link back to date/scan/trade."""
    nb = _notebook()
    q = query.lower().strip()
    results: List[Dict[str, Any]] = []

    def link(d: str, e: Dict[str, Any], **extra) -> Dict[str, Any]:
        return {"notebook_date": d, "scan_id": (e.get("scan") or {}).get("scan_id"),
                **extra}

    for d in sorted(nb["entries"], reverse=True):
        if date_from and d < date_from:
            continue
        if date_to and d > date_to:
            continue
        e = nb["entries"][d]
        if regime and str((e.get("market") or {}).get("market_regime", "")).upper() != regime.upper():
            continue
        if stale_only and not ((e.get("data_quality") or {}).get("scan_stale")):
            continue
        # notes
        for n in e.get("user_notes") or []:
            hay = (n.get("text", "") + " " + " ".join(n.get("tags") or [])).lower()
            if q and q not in hay:
                continue
            if tag and tag.lower() not in [t.lower() for t in (n.get("tags") or [])]:
                continue
            if symbol and symbol.upper() not in n.get("text", "").upper():
                continue
            if strategy or sector or outcome or decision_state:
                continue
            results.append(link(d, e, type="note", note=n))
        # decisions
        for r in e.get("decisions") or []:
            if symbol and r.get("symbol") != symbol.upper():
                continue
            if strategy and strategy.lower() not in str(r.get("strategy") or "").lower():
                continue
            if sector and sector.lower() not in str(r.get("sector") or "").lower():
                continue
            if decision_state and r.get("decision_state") != decision_state:
                continue
            if outcome:
                oc = (r.get("outcome") or {})
                if outcome.upper() == "WIN" and not (isinstance(oc.get("pnl"), (int, float)) and oc["pnl"] > 0):
                    continue
                if outcome.upper() == "LOSS" and not (isinstance(oc.get("pnl"), (int, float)) and oc["pnl"] < 0):
                    continue
                if outcome.upper() not in ("WIN", "LOSS") and \
                        outcome.lower() not in str(oc.get("classification") or "").lower():
                    continue
            if tag:
                continue
            hay = json.dumps(r).lower()
            if q and q not in hay:
                continue
            results.append(link(d, e, type="decision", decision=r))
        if stale_only and not (e.get("user_notes") or e.get("decisions")):
            results.append(link(d, e, type="stale_day",
                                data_quality=e.get("data_quality")))
        if len(results) >= limit:
            break
    return {"success": True, "count": len(results), "results": results[:limit],
            "label": LABEL}


# ── issue tracking (spec §12) ────────────────────────────────────────────────

def _issues() -> Dict[str, Any]:
    d = _load(ISSUES_PATH, {"issues": [], "next_id": 1})
    d.setdefault("issues", [])
    d.setdefault("next_id", 1)
    return d


@_locked
def add_issue(description: str, severity: str = "MEDIUM", page: str = "",
              scan_id: str = "", trade_id: str = "", reproducible: bool = False,
              date_iso: Optional[str] = None) -> Dict[str, Any]:
    if severity.upper() not in ISSUE_SEVERITIES:
        return {"success": False, "error": f"severity must be one of {ISSUE_SEVERITIES}"}
    d = _issues()
    issue = {
        "issue_id": f"ISS-{d['next_id']:04d}",
        "date": date_iso or ist_today(),
        "severity": severity.upper(),
        "page": page[:100],
        "description": description[:2000],
        "related_scan_id": scan_id or None,
        "related_trade_id": trade_id or None,
        "reproducible": bool(reproducible),
        "status": "OPEN",
        "resolution": None, "resolved_date": None, "notes": [],
        "created_at": _now_utc(), "updated_at": _now_utc(),
    }
    d["issues"].append(issue)
    d["next_id"] += 1
    _save(ISSUES_PATH, d)
    return {"success": True, "issue": issue, "label": LABEL}


@_locked
def update_issue(issue_id: str, status: Optional[str] = None,
                 resolution: Optional[str] = None,
                 note: Optional[str] = None) -> Dict[str, Any]:
    d = _issues()
    for issue in d["issues"]:
        if issue["issue_id"] == issue_id:
            if status:
                if status.upper() not in ISSUE_STATUSES:
                    return {"success": False,
                            "error": f"status must be one of {ISSUE_STATUSES}"}
                issue["status"] = status.upper()
                if status.upper() in ("FIXED", "VERIFIED"):
                    issue["resolved_date"] = ist_today()
            if resolution is not None:
                issue["resolution"] = resolution[:2000]
            if note:
                issue["notes"].append({"text": note[:1000], "at": _now_utc()})
            issue["updated_at"] = _now_utc()
            _save(ISSUES_PATH, d)
            return {"success": True, "issue": issue, "label": LABEL}
    return {"success": False, "error": f"Issue not found: {issue_id}"}


def list_issues(status: str = "", severity: str = "") -> Dict[str, Any]:
    d = _issues()
    items = d["issues"]
    if status:
        items = [i for i in items if i["status"] == status.upper()]
    if severity:
        items = [i for i in items if i["severity"] == severity.upper()]
    open_critical = sum(1 for i in d["issues"]
                        if i["severity"] == "CRITICAL"
                        and i["status"] in ("OPEN", "INVESTIGATING"))
    return {"success": True, "issues": list(reversed(items)),
            "total": len(d["issues"]), "open_critical": open_critical,
            "label": LABEL}


# ── targets (spec §9, configurable) ──────────────────────────────────────────

def get_targets() -> Dict[str, Any]:
    t = _load(TARGETS_PATH, None)
    if not isinstance(t, dict):
        t = dict(DEFAULT_TARGETS)
        _save(TARGETS_PATH, t)
    return t


@_locked
def update_targets(changes: Dict[str, Any]) -> Dict[str, Any]:
    t = get_targets()
    rejected: Dict[str, str] = {}
    for k, v in changes.items():
        if k in DEFAULT_TARGETS and k != "note":
            try:
                iv = int(v)
            except (TypeError, ValueError):
                rejected[k] = f"not an integer: {v!r}"
                continue
            floor = 0 if k == "max_unresolved_critical_issues" else 1
            if iv < floor:
                rejected[k] = f"must be >= {floor}, got {iv}"
                continue
            t[k] = iv
    _save(TARGETS_PATH, t)
    out: Dict[str, Any] = {"success": True, "targets": t, "label": LABEL}
    if rejected:
        out["rejected"] = rejected
    return out
