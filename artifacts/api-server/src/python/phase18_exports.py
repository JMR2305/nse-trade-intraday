"""
phase18_exports.py — Phase 18 Research Notebook exports.

Generates, into phase18_exports/:
  Daily_Notebook_<date>.pdf / .json / .csv
  Weekly_Research_Review.json
  Monthly_Research_Review.json
  Evidence_Accumulation_Report.json
  Issue_Log.csv / .json
  Notes_Export.csv
  Research_Notebook_Archive.zip  (everything + README, no secrets)

All content derives from stored notebook / trade / validation data.
Honest markers only. PAPER TRADING / RESEARCH ONLY.
"""

from __future__ import annotations

import csv
import json
import os
import zipfile
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import phase18_notebook as nb
import phase18_reviews as rv

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
EXPORT_DIR = os.path.join(BASE_DIR, "phase18_exports")
ARCHIVE_NAME = "Research_Notebook_Archive.zip"

# Never allow these substrings in export payloads (secret hygiene).
FORBIDDEN_KEYS = ("api_key", "apikey", "secret", "token", "password", "credential")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ensure_dir() -> None:
    os.makedirs(EXPORT_DIR, exist_ok=True)


def _scrub(obj: Any) -> Any:
    """Drop any key that looks like a credential (defence in depth)."""
    if isinstance(obj, dict):
        return {k: _scrub(v) for k, v in obj.items()
                if not any(f in k.lower() for f in FORBIDDEN_KEYS)}
    if isinstance(obj, list):
        return [_scrub(v) for v in obj]
    return obj


def _write_json(path: str, data: Any) -> None:
    with open(path, "w") as f:
        json.dump(_scrub(data), f, indent=2, default=str)


# ── daily notebook exports ───────────────────────────────────────────────────

def _daily_csv(path: str, entry: Dict[str, Any]) -> None:
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Research Notebook — Daily Entry", entry.get("trading_date")])
        w.writerow(["State", entry.get("state"), "Scan ID",
                    (entry.get("scan") or {}).get("scan_id")])
        m = entry.get("market") or {}
        w.writerow(["Regime", m.get("market_regime"), "NIFTY", m.get("nifty_trend"),
                    "BANKNIFTY", m.get("banknifty_trend"), "VIX", m.get("india_vix"),
                    "Breadth", m.get("breadth_label")])
        w.writerow([])
        w.writerow(["Decision Journal"])
        w.writerow(["Symbol", "Raw Signal", "Final Action", "Decision State",
                    "Confidence", "Opportunity", "Strategy", "Sector", "RR",
                    "Blocking Rule", "User Action", "User Reason", "Outcome PnL"])
        for r in entry.get("decisions", []):
            w.writerow([r.get("symbol"), r.get("raw_signal"), r.get("final_action"),
                        r.get("decision_state"), r.get("confidence"),
                        r.get("opportunity_score"), r.get("strategy"), r.get("sector"),
                        r.get("rr_ratio"), r.get("blocking_rule"),
                        r.get("user_action"), r.get("user_reason"),
                        (r.get("outcome") or {}).get("pnl")])
        w.writerow([])
        w.writerow(["Notes"])
        for n in entry.get("user_notes", []):
            w.writerow([n.get("created_at"), n.get("category"),
                        ";".join(n.get("tags") or []), n.get("text")])


def _daily_pdf(path: str, entry: Dict[str, Any]) -> Optional[str]:
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.units import cm
        from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer,
                                        Table, TableStyle)
        from reportlab.lib.styles import getSampleStyleSheet
    except Exception as e:
        return f"pdf unavailable: {e}"
    styles = getSampleStyleSheet()
    doc = SimpleDocTemplate(path, pagesize=A4, topMargin=1.5 * cm, bottomMargin=1.5 * cm)
    m = entry.get("market") or {}
    eod = entry.get("eod") or {}
    story = [
        Paragraph(f"Research Notebook — {entry.get('trading_date')}", styles["Title"]),
        Paragraph(f"State: {entry.get('state')} · Scan {  (entry.get('scan') or {}).get('scan_id')} · "
                  "PAPER TRADING / RESEARCH ONLY", styles["Normal"]),
        Spacer(1, 10),
        Paragraph("Market Context", styles["Heading2"]),
        Paragraph(f"Regime {m.get('market_regime')} · NIFTY {m.get('nifty_trend')} "
                  f"({m.get('nifty_change_pct')}%) · BANKNIFTY {m.get('banknifty_trend')} "
                  f"({m.get('banknifty_change_pct')}%) · VIX {m.get('india_vix')} "
                  f"({m.get('vix_category')}) · Breadth {m.get('breadth_label')}",
                  styles["Normal"]),
        Spacer(1, 8),
    ]
    if eod:
        story += [Paragraph("End of Day", styles["Heading2"]),
                  Paragraph(str(eod.get("final_summary") or ""), styles["Normal"]),
                  Spacer(1, 8)]
    rows = [["Symbol", "Signal", "State", "Conf", "Strategy", "User", "PnL"]]
    for r in entry.get("decisions", [])[:40]:
        rows.append([str(r.get("symbol")), str(r.get("raw_signal")),
                     str(r.get("decision_state"))[:22], str(r.get("confidence")),
                     str(r.get("strategy"))[:18], str(r.get("user_action") or "-"),
                     str((r.get("outcome") or {}).get("pnl", "-"))])
    t = Table(rows, repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#16324f")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTSIZE", (0, 0), (-1, -1), 7),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
    ]))
    story += [Paragraph("Decision Journal (first 40)", styles["Heading2"]), t, Spacer(1, 8)]
    if entry.get("user_notes"):
        story.append(Paragraph("Notes", styles["Heading2"]))
        for n in entry["user_notes"][:20]:
            story.append(Paragraph(
                f"[{n.get('category')}] {n.get('text')}", styles["Normal"]))
    if entry.get("lessons_learned"):
        story += [Paragraph("Lessons Learned", styles["Heading2"]),
                  Paragraph(str(entry["lessons_learned"]), styles["Normal"])]
    doc.build(story)
    return None


def export_daily(date_iso: Optional[str] = None) -> Dict[str, Any]:
    _ensure_dir()
    date_iso = date_iso or nb.ist_today()
    got = nb.get_entry(date_iso)
    if not got.get("available"):
        return {"success": False, "error": f"No notebook entry for {date_iso}"}
    entry = got["entry"]
    files, warnings = [], []
    jpath = os.path.join(EXPORT_DIR, f"Daily_Notebook_{date_iso}.json")
    _write_json(jpath, entry)
    files.append(os.path.basename(jpath))
    cpath = os.path.join(EXPORT_DIR, f"Daily_Notebook_{date_iso}.csv")
    _daily_csv(cpath, entry)
    files.append(os.path.basename(cpath))
    ppath = os.path.join(EXPORT_DIR, f"Daily_Notebook_{date_iso}.pdf")
    err = _daily_pdf(ppath, entry)
    if err:
        warnings.append(err)
    else:
        files.append(os.path.basename(ppath))
    return {"success": True, "date": date_iso, "files": files,
            "warnings": warnings, "label": nb.LABEL}


# ── review / issue / notes exports ───────────────────────────────────────────

def export_reviews() -> Dict[str, Any]:
    _ensure_dir()
    files = []
    for name, data in (
        ("Weekly_Research_Review.json", rv.weekly_review()),
        ("Monthly_Research_Review.json", rv.monthly_review()),
        ("Evidence_Accumulation_Report.json", rv.evidence_tracker()),
    ):
        _write_json(os.path.join(EXPORT_DIR, name), data)
        files.append(name)
    return {"success": True, "files": files, "label": nb.LABEL}


def export_issues() -> Dict[str, Any]:
    _ensure_dir()
    issues = nb.list_issues()["issues"]
    _write_json(os.path.join(EXPORT_DIR, "Issue_Log.json"), issues)
    with open(os.path.join(EXPORT_DIR, "Issue_Log.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Issue ID", "Date", "Severity", "Page", "Description",
                    "Scan ID", "Trade ID", "Reproducible", "Status",
                    "Resolution", "Resolved Date"])
        for i in issues:
            w.writerow([i.get("issue_id"), i.get("date"), i.get("severity"),
                        i.get("page"), i.get("description"),
                        i.get("related_scan_id"), i.get("related_trade_id"),
                        i.get("reproducible"), i.get("status"),
                        i.get("resolution"), i.get("resolved_date")])
    return {"success": True, "files": ["Issue_Log.json", "Issue_Log.csv"],
            "label": nb.LABEL}


def export_notes() -> Dict[str, Any]:
    _ensure_dir()
    path = os.path.join(EXPORT_DIR, "Notes_Export.csv")
    entries = nb._notebook()["entries"]
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Date", "Created At", "Category", "Tags", "Text",
                    "Lessons Learned", "Follow-ups"])
        for d in sorted(entries):
            e = entries[d]
            notes = e.get("user_notes") or []
            if not notes and not e.get("lessons_learned"):
                continue
            if notes:
                for n in notes:
                    w.writerow([d, n.get("created_at"), n.get("category"),
                                ";".join(n.get("tags") or []), n.get("text"),
                                e.get("lessons_learned"),
                                ";".join(e.get("follow_up_actions") or [])])
            else:
                w.writerow([d, "", "", "", "", e.get("lessons_learned"),
                            ";".join(e.get("follow_up_actions") or [])])
    return {"success": True, "files": ["Notes_Export.csv"], "label": nb.LABEL}


# ── complete archive (spec §13) ──────────────────────────────────────────────

_README = """RESEARCH NOTEBOOK ARCHIVE — NSE Trader (PAPER / RESEARCH ONLY)
================================================================

Generated: {generated}

Contents
--------
daily/            One JSON per trading-day notebook entry (draft or finalized)
reviews/          Weekly review, monthly review, evidence accumulation report
issues/           Operational issue log (CSV + JSON)
notes/            All user notes and lessons (CSV)
validation/       Latest Phase 17 QA summary attached for context
trade_links.json  Trade IDs referenced by notebook entries → use Trade Replay

Integrity
---------
- Every entry records its source scan ID, snapshot timestamp, data provider,
  model version and creation/update timestamps.
- live_execution_enabled is false everywhere. No live orders are possible.
- Missing data is marked "Insufficient Data" — nothing is fabricated.
- Credentials, secrets, tokens and broker-private data are excluded.

This archive is a research audit record only. It contains no investment advice.
"""


def build_archive() -> Dict[str, Any]:
    """Build Research_Notebook_Archive.zip with everything, README, no secrets."""
    _ensure_dir()
    entries = nb._notebook()["entries"]
    # Refresh component exports first.
    export_reviews()
    export_issues()
    export_notes()

    trade_links = []
    for d in sorted(entries):
        e = entries[d]
        for t in (e.get("new_paper_trades") or []) + (e.get("closed_paper_trades") or []):
            trade_links.append({"notebook_date": d, "trade_id": t.get("id"),
                                "symbol": t.get("symbol"), "action": t.get("action"),
                                "scan_id": (e.get("scan") or {}).get("scan_id")})

    zip_path = os.path.join(EXPORT_DIR, ARCHIVE_NAME)
    val = nb._validation_summary()
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("README.txt", _README.format(generated=_now()))
        for d in sorted(entries):
            z.writestr(f"daily/Daily_Notebook_{d}.json",
                       json.dumps(_scrub(entries[d]), indent=2, default=str))
        for name in ("Weekly_Research_Review.json", "Monthly_Research_Review.json",
                     "Evidence_Accumulation_Report.json", "Issue_Log.json",
                     "Issue_Log.csv", "Notes_Export.csv"):
            p = os.path.join(EXPORT_DIR, name)
            if os.path.exists(p):
                arc = ("reviews/" if "Review" in name or "Evidence" in name
                       else "issues/" if "Issue" in name else "notes/") + name
                z.write(p, arc)
        z.writestr("validation/phase17_summary.json",
                   json.dumps(_scrub(val), indent=2, default=str))
        z.writestr("trade_links.json", json.dumps(trade_links, indent=2, default=str))
    size = os.path.getsize(zip_path)
    return {"success": True, "zip_name": ARCHIVE_NAME, "zip_path": zip_path,
            "size_bytes": size, "daily_entries": len(entries),
            "trade_links": len(trade_links), "generated_at": _now(),
            "label": nb.LABEL}


def export_all(date_iso: Optional[str] = None) -> Dict[str, Any]:
    daily = export_daily(date_iso)
    reviews = export_reviews()
    issues = export_issues()
    notes = export_notes()
    archive = build_archive()
    return {"success": True,
            "daily": daily, "reviews": reviews, "issues": issues,
            "notes": notes, "archive": archive, "label": nb.LABEL}
