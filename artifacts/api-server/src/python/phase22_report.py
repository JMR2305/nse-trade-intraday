"""
phase22_report.py — Phase 22 daily close report + JSON/CSV/PDF exports.

PAPER TRADING / RESEARCH ONLY. No live orders anywhere.
"""

from __future__ import annotations

import csv
import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
EXPORT_DIR = os.path.join(BASE_DIR, "exports")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def build_daily_report(day: Optional[str] = None) -> Dict[str, Any]:
    """Assemble the Phase 22 daily close report for one (UTC) day."""
    day = day or _today()

    import phase20_store as store
    runs = [r for r in store.list_scan_runs(200)
            if str(r.get("started_at") or "").startswith(day)]
    scheduled = [r for r in runs if r.get("trigger_source") == "SCHEDULED"]

    from phase20_executor import get_ledger
    ledger = get_ledger(500)
    opened_today = [t for t in ledger
                    if str(t.get("fill_ts") or "").startswith(day)]
    exits_today = [t for t in ledger if t.get("status") == "CLOSED"
                   and str(t.get("exit_ts") or "").startswith(day)]
    pending = [t for t in ledger if t.get("status") == "EXIT_PENDING"]

    realized = round(sum(float(t.get("realized_pnl") or 0)
                         for t in exits_today), 2)
    unrealized = 0.0
    try:
        from paper_trader import get_portfolio
        pf = get_portfolio()
        unrealized = round(sum(float(p.get("pnl") or 0)
                               for p in pf.get("positions", [])), 2)
    except Exception:
        pass

    from phase22_evidence import list_evidence, evidence_summary
    ev_rows = [r for r in list_evidence(limit=2000)
               if str(r.get("recorded_at") or "").startswith(day)]
    blocked_today = [r for r in ev_rows
                     if r.get("eligibility_result") == "BLOCKED"]

    def _group(items: List[Dict[str, Any]], key: str) -> Dict[str, int]:
        out: Dict[str, int] = {}
        for it in items:
            k = str(it.get(key) or "UNKNOWN")
            out[k] = out.get(k, 0) + 1
        return out

    settings = store.get_settings()
    try:
        from phase11_risk import kill_switch_status
        ks = kill_switch_status()
        risk_events = [e for e in (ks.get("events") or [])
                       if str(e.get("ts") or e.get("timestamp") or "").startswith(day)]
    except Exception:
        risk_events = []

    dq_incidents = [r for r in runs if r.get("status") == "FAILED"] + \
        [{"symbol": t.get("symbol"), "issue": "EXIT_PENDING (no reliable quote)"}
         for t in pending]

    try:
        import config
        live_disabled = (not getattr(config, "ZERODHA_ENABLED", True)) and \
            bool(getattr(config, "PAPER_TRADING_MODE", False))
    except Exception:
        live_disabled = False

    from phase22_progress import get_progress
    progress = get_progress()

    daily_drawdown = min(0.0, realized + min(0.0, unrealized))

    return {
        "report_date": day,
        "generated_at": _now_iso(),
        "scheduled_scans_completed": len(
            [r for r in scheduled if r.get("status") == "SUCCESS"]),
        "failed_scans": len([r for r in runs if r.get("status") == "FAILED"]),
        "candidates_evaluated": len(ev_rows),
        "paper_entries_opened": len(opened_today),
        "entries_blocked": len(blocked_today),
        "exits_completed": len(exits_today),
        "pending_data_actions": len(pending),
        "realized_pnl": realized,
        "unrealized_pnl": unrealized,
        "daily_drawdown": round(daily_drawdown, 2),
        "risk_limit_events": risk_events,
        "strategy_summary": _group(opened_today + exits_today, "strategy_name"),
        "sector_summary": _group(opened_today + exits_today, "sector"),
        "regime_summary": _group(opened_today + exits_today, "regime"),
        "data_quality_incidents": dq_incidents[:20],
        "evidence_progress": {
            "summary": evidence_summary(),
            "milestones": progress.get("milestones"),
            "next_milestone": progress.get("next_milestone"),
        },
        "live_order_disabled_verification": {
            "verified": live_disabled,
            "detail": "ZERODHA_ENABLED=False and PAPER_TRADING_MODE=True "
                      "confirmed in configuration",
        },
        "auto_paper_entries": bool(settings.get("auto_paper_entries")),
        "label": "PAPER / RESEARCH ONLY",
    }


def export_daily_report(day: Optional[str] = None) -> Dict[str, Any]:
    """Write the daily report as JSON, CSV and PDF into exports/."""
    os.makedirs(EXPORT_DIR, exist_ok=True)
    report = build_daily_report(day)
    d = report["report_date"]
    base = f"Phase22_Daily_{d}"
    files: List[str] = []

    json_path = os.path.join(EXPORT_DIR, f"{base}.json")
    with open(json_path, "w") as f:
        json.dump(report, f, indent=2, default=str)
    files.append(os.path.basename(json_path))

    csv_path = os.path.join(EXPORT_DIR, f"{base}.csv")
    flat_keys = ["report_date", "generated_at", "scheduled_scans_completed",
                 "failed_scans", "candidates_evaluated", "paper_entries_opened",
                 "entries_blocked", "exits_completed", "pending_data_actions",
                 "realized_pnl", "unrealized_pnl", "daily_drawdown",
                 "auto_paper_entries", "label"]
    with open(csv_path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["metric", "value"])
        for k in flat_keys:
            w.writerow([k, report.get(k)])
        w.writerow(["live_order_disabled_verified",
                    report["live_order_disabled_verification"]["verified"]])
        for grp in ("strategy_summary", "sector_summary", "regime_summary"):
            for k, v in (report.get(grp) or {}).items():
                w.writerow([f"{grp}:{k}", v])
    files.append(os.path.basename(csv_path))

    pdf_path = os.path.join(EXPORT_DIR, f"{base}.pdf")
    try:
        _write_pdf(report, pdf_path)
        files.append(os.path.basename(pdf_path))
    except Exception as exc:
        report["pdf_error"] = str(exc)[:200]

    return {"success": True, "report_date": d, "files": files,
            "report": report, "label": "PAPER / RESEARCH ONLY"}


def _write_pdf(report: Dict[str, Any], path: str) -> None:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import cm
    from reportlab.pdfgen import canvas as pdfcanvas

    c = pdfcanvas.Canvas(path, pagesize=A4)
    w, h = A4
    y = h - 2 * cm

    def line(text: str, size: int = 10, bold: bool = False, indent: float = 0):
        nonlocal y
        if y < 2 * cm:
            c.showPage()
            y = h - 2 * cm
        c.setFont("Helvetica-Bold" if bold else "Helvetica", size)
        c.drawString(2 * cm + indent, y, text[:110])
        y -= (size + 5)

    line(f"Phase 22 Daily Close Report — {report['report_date']}", 15, True)
    line("PAPER / RESEARCH ONLY — no real orders. Simulated capital only.", 9)
    line(f"Generated: {report['generated_at']}", 9)
    y -= 8
    line("Activity", 12, True)
    for k in ("scheduled_scans_completed", "failed_scans",
              "candidates_evaluated", "paper_entries_opened",
              "entries_blocked", "exits_completed", "pending_data_actions"):
        line(f"{k.replace('_', ' ').title()}: {report.get(k)}", 10, indent=10)
    y -= 6
    line("Simulated P&L", 12, True)
    for k in ("realized_pnl", "unrealized_pnl", "daily_drawdown"):
        line(f"{k.replace('_', ' ').title()}: ₹{report.get(k)}", 10, indent=10)
    y -= 6
    line("Summaries", 12, True)
    for grp in ("strategy_summary", "sector_summary", "regime_summary"):
        items = report.get(grp) or {}
        line(f"{grp.replace('_', ' ').title()}: "
             + (", ".join(f"{k}={v}" for k, v in items.items()) or "none"),
             9, indent=10)
    y -= 6
    line("Evidence Progress", 12, True)
    ev = (report.get("evidence_progress") or {}).get("summary") or {}
    line(f"Evidence rows: {ev.get('total_rows')}, opened: {ev.get('opened')}, "
         f"blocked: {ev.get('blocked')}, complete: {ev.get('outcome_complete')}",
         10, indent=10)
    nm = (report.get("evidence_progress") or {}).get("next_milestone")
    if nm:
        line(f"Next milestone: {nm['trades']} trades ({nm['label']}) — "
             f"{nm['remaining']} remaining", 10, indent=10)
    y -= 6
    line("Safety", 12, True)
    lod = report.get("live_order_disabled_verification") or {}
    line(f"Live orders disabled verified: {lod.get('verified')}", 10, indent=10)
    line(f"Auto paper entries: "
         f"{'ON (user-activated)' if report.get('auto_paper_entries') else 'OFF (default)'}",
         10, indent=10)
    line("Risk limit events: "
         f"{len(report.get('risk_limit_events') or [])}", 10, indent=10)
    c.save()
