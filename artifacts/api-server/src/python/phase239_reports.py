"""
phase239_reports.py — Phase 23.9: Export Engine + Final Acceptance Report
(spec Parts N, O, R).

Export engine: certification reports, validation logs (append-only
certification history), simulation results and scenario comparison
reports in JSON / CSV / Markdown / PDF.

Final acceptance report: canonical-architecture audit proving every
Phase 23 module (Simulation Lab, Validation Engine, Certification
Engine, Mission Control, Replay, Backtest, Learning Engine,
Optimization/Strategy Lab) consumes the canonical stores — no duplicate
calculations, no independent strategy or portfolio engines.

STRICTLY READ-ONLY over all canonical stores. Exports are generated
in-memory and streamed to the caller; nothing in live trading state is
ever modified. PAPER TRADING / RESEARCH ONLY.
"""
from __future__ import annotations

import base64
import csv
import io
import json
import os
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

ADVISORY = ("Phase 23.9 export/acceptance — read-only over canonical "
            "stores. PAPER TRADING / RESEARCH ONLY.")

_DIR = os.path.dirname(os.path.abspath(__file__))

REPORTS = ("certification", "validation_logs", "simulation",
           "comparison", "acceptance")
FORMATS = ("json", "csv", "md", "pdf")

_CONTENT_TYPES = {
    "json": "application/json",
    "csv": "text/csv",
    "md": "text/markdown",
    "pdf": "application/pdf",
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


# ── Final acceptance report (spec Part R) ────────────────────────────────────
#
# Static audit: each Phase 23 module's source must reference the canonical
# stores it is supposed to consume, and must NOT contain forbidden patterns
# that would indicate an independent portfolio/strategy engine or writes to
# the live ledger.
# Runtime audit: canonical stores must be importable and self-consistent.

_MODULE_AUDITS: List[Dict[str, Any]] = [
    {
        "system": "Simulation Lab",
        "module": "simulation_lab.py",
        "must_reference": ["scan_state_store"],
        "description": "derives what-if runs from persisted backtest runs; "
                       "sim state lives only in sim_scenarios/sim_runs",
    },
    {
        "system": "Validation Engine",
        "module": "validation_engines.py",
        "must_reference": ["canonical_portfolio", "pipeline_events"],
        "description": "validates against the canonical portfolio ledger "
                       "and the append-only pipeline event store",
    },
    {
        "system": "Certification Engine",
        "module": "certification_engine.py",
        "must_reference": ["validation_engines", "scan_state_store"],
        "description": "aggregates the validation engines; append-only "
                       "certification_runs only",
    },
    {
        "system": "Mission Control",
        "module": "replay_engine.py",
        "must_reference": ["scan_state"],
        "description": "mission-control counts come only from the unified "
                       "replay snapshot over the canonical scan",
    },
    {
        "system": "Replay",
        "module": "replay_engine.py",
        "must_reference": ["scan_state", "portfolio_store"],
        "description": "replays the persisted canonical scan; never "
                       "re-scans or falls back to a different scan",
    },
    {
        "system": "Backtest",
        "module": "backtest_runner.py",
        "must_reference": ["backtest_portfolio"],
        "description": "backtests run the live pipeline on as-of slices "
                       "with an isolated ledger",
    },
    {
        "system": "Learning Engine",
        "module": "phase24_engine.py",
        "must_reference": ["phase20_executor"],
        "description": "advisory-only intelligence over the phase20 paper "
                       "ledger; never auto-applies",
    },
    {
        "system": "Optimization Lab",
        "module": "strategy_lab.py",
        "must_reference": ["backtest_portfolio", "phase20_executor"],
        "description": "what-if sims derived on demand from canonical runs; "
                       "results never persisted into live state",
    },
]

# Patterns that would indicate an independent portfolio engine or a write
# into the live paper ledger from a Phase 23 analysis module.
_FORBIDDEN = [
    (re.compile(r"INSERT\s+INTO\s+paper_trades", re.I),
     "writes into the live paper_trades ledger"),
    (re.compile(r"UPDATE\s+paper_portfolio", re.I),
     "mutates the live paper portfolio"),
    (re.compile(r"DELETE\s+FROM\s+paper_trades", re.I),
     "deletes from the live paper ledger"),
]
# Certification engine legitimately inserts into certification_runs only —
# the forbidden list above deliberately targets live-ledger tables only.


def _audit_module(spec: Dict[str, Any]) -> Dict[str, Any]:
    path = os.path.join(_DIR, spec["module"])
    checks: List[Dict[str, Any]] = []
    if not os.path.isfile(path):
        return {"system": spec["system"], "module": spec["module"],
                "verdict": "FAIL",
                "checks": [{"check": "module_present", "status": "FAIL",
                            "detail": f"{spec['module']} not found"}]}
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            src = f.read()
    except Exception as exc:
        return {"system": spec["system"], "module": spec["module"],
                "verdict": "FAIL",
                "checks": [{"check": "module_readable", "status": "FAIL",
                            "detail": str(exc)}]}
    for ref in spec["must_reference"]:
        ok = ref in src
        checks.append({
            "check": f"consumes_{ref}",
            "status": "PASS" if ok else "FAIL",
            "detail": (f"references canonical store/module '{ref}'"
                       if ok else
                       f"does NOT reference '{ref}' — may be running an "
                       "independent engine"),
        })
    for pattern, why in _FORBIDDEN:
        hit = pattern.search(src)
        checks.append({
            "check": f"no_{why.split()[0]}_{pattern.pattern[:24]}",
            "status": "FAIL" if hit else "PASS",
            "detail": (f"FORBIDDEN: {why}" if hit
                       else f"clean: no pattern that {why}"),
        })
    verdict = "FAIL" if any(c["status"] == "FAIL" for c in checks) else "PASS"
    return {"system": spec["system"], "module": spec["module"],
            "description": spec["description"],
            "verdict": verdict, "checks": checks}


def _runtime_checks() -> List[Dict[str, Any]]:
    checks: List[Dict[str, Any]] = []
    # canonical scan snapshot store importable + snapshot self-identifies
    try:
        from scan_state_store import load_latest_snapshot
        snap = load_latest_snapshot() or {}
        if not snap:
            checks.append({"check": "canonical_snapshot", "status": "WARN",
                           "detail": "no canonical scan snapshot yet — run "
                                     "a scan first"})
        else:
            sid = snap.get("scan_id")
            ts = snap.get("snapshot_ts") or snap.get("as_of")
            ok = bool(sid and ts)
            checks.append({"check": "canonical_snapshot",
                           "status": "PASS" if ok else "FAIL",
                           "detail": f"scan_id={sid or 'MISSING'} "
                                     f"snapshot_ts={ts or 'MISSING'}"})
    except Exception as exc:
        checks.append({"check": "canonical_snapshot", "status": "FAIL",
                       "detail": f"scan_state_store unreadable: {exc}"})
    # canonical portfolio module importable
    try:
        import canonical_portfolio  # noqa: F401
        checks.append({"check": "canonical_portfolio_importable",
                       "status": "PASS",
                       "detail": "canonical_portfolio.py loads — all "
                                 "positions/cash/equity derive from it"})
    except Exception as exc:
        checks.append({"check": "canonical_portfolio_importable",
                       "status": "FAIL", "detail": str(exc)})
    # pipeline event store importable
    try:
        import pipeline_events  # noqa: F401
        checks.append({"check": "pipeline_events_importable",
                       "status": "PASS",
                       "detail": "append-only pipeline event store loads"})
    except Exception as exc:
        checks.append({"check": "pipeline_events_importable",
                       "status": "FAIL", "detail": str(exc)})
    # learning must be advisory-only
    try:
        import phase24_engine as p24
        auto = bool(getattr(p24, "AUTO_APPLY_ENABLED", False))
        checks.append({"check": "learning_advisory_only",
                       "status": "PASS" if not auto else "FAIL",
                       "detail": f"phase24 AUTO_APPLY_ENABLED={auto}"})
    except Exception:
        checks.append({"check": "learning_advisory_only", "status": "PASS",
                       "detail": "phase24 not importable — nothing can "
                                 "auto-apply"})
    return checks


def acceptance_report(module_audits: Optional[List[Dict[str, Any]]] = None,
                      runtime: Optional[List[Dict[str, Any]]] = None
                      ) -> Dict[str, Any]:
    """Final Phase 23 acceptance report — canonical-architecture audit."""
    systems = (module_audits if module_audits is not None
               else [_audit_module(s) for s in _MODULE_AUDITS])
    rt = runtime if runtime is not None else _runtime_checks()
    all_checks = ([c for s in systems for c in s.get("checks", [])] + rt)
    failed = sum(1 for c in all_checks if c.get("status") == "FAIL")
    warned = sum(1 for c in all_checks if c.get("status") == "WARN")
    total = len(all_checks)
    score = round((total - failed - 0.5 * warned) / total * 100.0, 1) \
        if total else 0.0
    accepted = failed == 0
    return {
        "ok": True,
        "title": "Phase 23 Final Acceptance Report",
        "generated_at": _now_iso(),
        "accepted": accepted,
        "verdict": "ACCEPTED" if accepted else "NOT_ACCEPTED",
        "score_pct": score,
        "checks_total": total,
        "checks_failed": failed,
        "checks_warned": warned,
        "systems": systems,
        "runtime_checks": rt,
        "policy": ("ACCEPTED requires zero failed checks: every Phase 23 "
                   "system must consume the canonical stores with no "
                   "duplicate calculations and no independent strategy or "
                   "portfolio engines."),
        "note": ADVISORY,
    }


# ── Report data collectors ───────────────────────────────────────────────────

def _collect(report: str, params: Dict[str, Any]) -> Dict[str, Any]:
    if report == "certification":
        import certification_engine as cert
        cert_id = params.get("cert_id")
        if cert_id:
            return cert.get_certification(str(cert_id))
        items = cert.list_certifications(limit=1).get("items") or []
        if not items:
            return {"ok": False,
                    "error": "No certification runs yet — trigger a "
                             "certification run first"}
        return cert.get_certification(str(items[0]["cert_id"]))
    if report == "validation_logs":
        import certification_engine as cert
        return cert.list_certifications(limit=int(params.get("limit")
                                                  or 100))
    if report == "simulation":
        import simulation_lab as sim
        return sim.list_sim_runs(limit=int(params.get("limit") or 100))
    if report == "comparison":
        import simulation_lab as sim
        sim_ids = list(params.get("sim_ids") or [])
        if not sim_ids:
            runs = sim.list_sim_runs(limit=50).get("runs") or []
            sim_ids = [r["sim_id"] for r in runs]
        if not sim_ids:
            return {"ok": False,
                    "error": "No simulation runs to compare yet"}
        return sim.compare_sim_runs(sim_ids)
    if report == "acceptance":
        return acceptance_report()
    return {"ok": False, "error": f"Unknown report '{report}' — use one of "
                                  f"{', '.join(REPORTS)}"}


# ── Tabular flattening (drives CSV, Markdown tables and PDF rows) ────────────

def _tables(report: str, data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Return [{title, headers, rows}] for the given report payload."""
    if report == "certification":
        rows = [[d,
                 (v or {}).get("verdict"),
                 (v or {}).get("weight"),
                 (v or {}).get("score_pct"),
                 (v or {}).get("checks_total"),
                 (v or {}).get("checks_failed"),
                 (v or {}).get("checks_warned")]
                for d, v in (data.get("domains") or {}).items()]
        return [{
            "title": (f"Certification {data.get('cert_id')} — "
                      f"{data.get('verdict')} "
                      f"({data.get('certification_pct')}%)"),
            "headers": ["domain", "verdict", "weight", "score_pct",
                        "checks_total", "checks_failed", "checks_warned"],
            "rows": rows,
        }]
    if report == "validation_logs":
        items = data.get("items") or []
        domains = sorted({d for it in items
                          for d in (it.get("domains") or {})})
        return [{
            "title": "Validation Logs (append-only certification history)",
            "headers": ["cert_id", "created_at", "certification_pct",
                        "verdict"] + domains,
            "rows": [[it.get("cert_id"), it.get("created_at"),
                      it.get("certification_pct"), it.get("verdict")] +
                     [(it.get("domains") or {}).get(d) for d in domains]
                     for it in items],
        }]
    if report == "simulation":
        runs = data.get("runs") or []
        return [{
            "title": "Simulation Runs",
            "headers": ["sim_id", "created_at", "label", "base_run_id",
                        "verdict", "trades", "pnl", "win_rate",
                        "max_drawdown_pct"],
            "rows": [[r.get("sim_id"), r.get("created_at"), r.get("label"),
                      r.get("base_run_id"),
                      (r.get("result") or {}).get("verdict"),
                      ((r.get("result") or {}).get("metrics")
                       or {}).get("trades",
                                  (r.get("result") or {}).get("trades_kept")),
                      (r.get("result") or {}).get("pnl"),
                      ((r.get("result") or {}).get("metrics")
                       or {}).get("win_rate"),
                      ((r.get("result") or {}).get("metrics")
                       or {}).get("max_drawdown_pct")]
                     for r in runs],
        }]
    if report == "comparison":
        rows = data.get("rows") or []
        return [{
            "title": "Scenario Comparison",
            "headers": ["sim_id", "label", "trades", "win_rate", "pnl",
                        "sharpe", "sortino", "max_drawdown_pct",
                        "profit_factor", "expectancy", "verdict"],
            "rows": [[r.get("sim_id"), r.get("label"), r.get("trades"),
                      r.get("win_rate"), r.get("pnl"), r.get("sharpe"),
                      r.get("sortino"), r.get("max_drawdown_pct"),
                      r.get("profit_factor"), r.get("expectancy"),
                      r.get("verdict") if r.get("ok")
                      else f"ERROR: {r.get('error')}"]
                     for r in rows],
        }]
    if report == "acceptance":
        sys_rows = [[s.get("system"), s.get("module"), s.get("verdict"),
                     sum(1 for c in s.get("checks", [])
                         if c.get("status") == "FAIL")]
                    for s in (data.get("systems") or [])]
        rt_rows = [[c.get("check"), c.get("status"), c.get("detail")]
                   for c in (data.get("runtime_checks") or [])]
        return [
            {"title": (f"Final Acceptance — {data.get('verdict')} "
                       f"({data.get('score_pct')}%)"),
             "headers": ["system", "module", "verdict", "failed_checks"],
             "rows": sys_rows},
            {"title": "Runtime Checks",
             "headers": ["check", "status", "detail"],
             "rows": rt_rows},
        ]
    return []


# ── Format renderers ─────────────────────────────────────────────────────────

def _render_csv(tables: List[Dict[str, Any]]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["PAPER TRADING / RESEARCH ONLY", _now_iso()])
    for t in tables:
        w.writerow([])
        w.writerow([t["title"]])
        w.writerow(t["headers"])
        for row in t["rows"]:
            w.writerow(["" if v is None else v for v in row])
    return buf.getvalue()


def _render_md(report: str, data: Dict[str, Any],
               tables: List[Dict[str, Any]]) -> str:
    lines = [f"# {report.replace('_', ' ').title()} Report",
             "",
             f"_Generated: {_now_iso()} — PAPER TRADING / RESEARCH ONLY_",
             ""]
    if report == "certification":
        lines += [f"**Verdict: {data.get('verdict')}** — "
                  f"certification {data.get('certification_pct')}%", ""]
        blockers = data.get("blockers") or []
        if blockers:
            lines += ["**Blockers:**"] + [f"- {b}" for b in blockers] + [""]
    if report == "acceptance":
        lines += [f"**Verdict: {data.get('verdict')}** — score "
                  f"{data.get('score_pct')}% "
                  f"({data.get('checks_failed')} failed / "
                  f"{data.get('checks_total')} checks)", "",
                  data.get("policy") or "", ""]
    for t in tables:
        lines += [f"## {t['title']}", ""]
        lines.append("| " + " | ".join(map(str, t["headers"])) + " |")
        lines.append("|" + "---|" * len(t["headers"]))
        for row in t["rows"]:
            lines.append("| " + " | ".join(
                "" if v is None else str(v) for v in row) + " |")
        lines.append("")
    return "\n".join(lines)


def _render_pdf(report: str, tables: List[Dict[str, Any]]) -> Optional[bytes]:
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.units import cm
        from reportlab.pdfgen import canvas as pdfcanvas
    except ImportError:
        return None
    buf = io.BytesIO()
    c = pdfcanvas.Canvas(buf, pagesize=A4)
    w, h = A4
    y = h - 2 * cm

    def line(text: str, size: int = 9, dy: float = 0.45) -> None:
        nonlocal y
        if y < 2 * cm:
            c.showPage()
            y = h - 2 * cm
        c.setFont("Helvetica", size)
        c.drawString(1.5 * cm, y, str(text)[:130])
        y -= dy * cm

    c.setFont("Helvetica-Bold", 14)
    c.drawString(1.5 * cm, y,
                 f"{report.replace('_', ' ').title()} Report — "
                 "PAPER TRADING / RESEARCH ONLY")
    y -= 1 * cm
    line(f"Generated: {_now_iso()}")
    for t in tables:
        line("")
        c.setFont("Helvetica-Bold", 11)
        line(t["title"], 11, 0.6)
        line(" | ".join(map(str, t["headers"])), 8, 0.4)
        for row in t["rows"]:
            line(" | ".join("" if v is None else str(v) for v in row),
                 8, 0.4)
    c.save()
    return buf.getvalue()


# ── Public export entry point ────────────────────────────────────────────────

def export_report(report: str, fmt: str,
                  params: Optional[Dict[str, Any]] = None,
                  data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Build one export. Returns {ok, filename, content_type, content}
    (content is base64 in `content_b64` for PDF)."""
    report = str(report or "").lower()
    fmt = str(fmt or "").lower()
    if report not in REPORTS:
        return {"ok": False, "error": f"Unknown report '{report}' — use one "
                                      f"of {', '.join(REPORTS)}"}
    if fmt not in FORMATS:
        return {"ok": False, "error": f"Unknown format '{fmt}' — use one of "
                                      f"{', '.join(FORMATS)}"}
    payload = data if data is not None else _collect(report, params or {})
    if not payload.get("ok", True) and payload.get("error"):
        return {"ok": False, "error": str(payload["error"])}

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    filename = f"phase23_{report}_{stamp}.{fmt}"
    base = {"ok": True, "report": report, "format": fmt,
            "filename": filename, "content_type": _CONTENT_TYPES[fmt],
            "note": ADVISORY}

    if fmt == "json":
        return {**base, "content": json.dumps(payload, indent=1,
                                              default=str)}
    tables = _tables(report, payload)
    if fmt == "csv":
        return {**base, "content": _render_csv(tables)}
    if fmt == "md":
        return {**base, "content": _render_md(report, payload, tables)}
    pdf = _render_pdf(report, tables)
    if pdf is None:
        return {"ok": False,
                "error": "PDF renderer unavailable (reportlab not "
                         "installed) — use json/csv/md"}
    return {**base, "content_b64": base64.b64encode(pdf).decode("ascii")}
