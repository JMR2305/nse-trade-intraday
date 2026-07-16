"""
phase21_exports.py — Phase 21: Downloadable JSON / CSV / PDF reports.

PAPER / RESEARCH ONLY.
"""
from __future__ import annotations

import csv
import json
import os
from datetime import datetime, timezone

from phase21_baseline import load_baseline, baseline_report
from phase21_calibration import load_calibration
from phase21_thresholds import load_thresholds
from phase21_regime import load_regime_matrix
from phase21_stoptarget import load_stoptarget
from phase21_challenger import get_registry
from phase21_scorecard import build_scorecard

_DIR = os.path.dirname(os.path.abspath(__file__))
EXPORT_DIR = os.path.join(_DIR, "phase21_exports")

JSON_FILE = os.path.join(EXPORT_DIR, "Phase21_Report.json")
CSV_FILE = os.path.join(EXPORT_DIR, "Phase21_Report.csv")
PDF_FILE = os.path.join(EXPORT_DIR, "Phase21_Summary.pdf")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _bundle() -> dict:
    return {
        "generated_at": _now(),
        "label": "PAPER / RESEARCH ONLY",
        "baseline": load_baseline(),
        "baseline_report": baseline_report(),
        "calibration": load_calibration(),
        "thresholds": load_thresholds(),
        "regime_matrix": load_regime_matrix(),
        "stop_target": load_stoptarget(),
        "challenger_registry": get_registry(),
        "scorecard": build_scorecard(),
    }


def _write_csv(bundle: dict) -> None:
    with open(CSV_FILE, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Phase 21 Report — PAPER / RESEARCH ONLY",
                    bundle["generated_at"]])
        w.writerow([])
        sc = bundle["scorecard"]
        w.writerow(["Scorecard"])
        for k in ("baseline_model_version", "champion_version", "challenger_count",
                  "total_evaluated_trades", "confidence_calibration_score",
                  "threshold_quality", "readiness_status", "auto_paper_entries",
                  "live_orders"):
            w.writerow([k, sc.get(k)])
        w.writerow([])
        w.writerow(["Calibration buckets"])
        w.writerow(["bucket", "trades", "win_rate", "profit_factor",
                    "expectancy", "calibration_error", "status"])
        for b in bundle["calibration"].get("buckets", []):
            w.writerow([b["bucket"], b["trades"], b["win_rate"],
                        b["profit_factor"], b["expectancy"],
                        b["calibration_error"], b["status"]])
        w.writerow([])
        w.writerow(["Threshold candidates"])
        w.writerow(["buy_threshold", "trades", "win_rate", "profit_factor",
                    "expectancy", "max_drawdown", "overfit_risk", "recommended"])
        for c in bundle["thresholds"].get("candidates", []):
            w.writerow([c["threshold_set"]["buy"], c["trades"], c["win_rate"],
                        c["profit_factor"], c["expectancy"], c["max_drawdown"],
                        c["overfit_risk"], c["recommended"]])
        w.writerow([])
        w.writerow(["Strategy x Regime"])
        w.writerow(["strategy", "regime", "trades", "win_rate", "profit_factor",
                    "expectancy", "classification"])
        for p in bundle["regime_matrix"].get("pairs", []):
            w.writerow([p["strategy"], p["regime"], p.get("sample_size"),
                        p.get("win_rate"), p.get("profit_factor"),
                        p.get("expectancy"), p.get("classification")])


def _write_pdf(bundle: dict) -> bool:
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.units import cm
        from reportlab.pdfgen import canvas as pdfcanvas
    except ImportError:
        return False
    c = pdfcanvas.Canvas(PDF_FILE, pagesize=A4)
    w, h = A4
    y = h - 2 * cm

    def line(text, size=10, dy=0.55):
        nonlocal y
        if y < 2 * cm:
            c.showPage()
            y = h - 2 * cm
        c.setFont("Helvetica", size)
        c.drawString(2 * cm, y, str(text)[:110])
        y -= dy * cm

    sc = bundle["scorecard"]
    c.setFont("Helvetica-Bold", 14)
    c.drawString(2 * cm, y, "Phase 21 Summary — PAPER / RESEARCH ONLY")
    y -= 1 * cm
    line(f"Generated: {bundle['generated_at']}")
    line(f"Baseline: {sc.get('baseline_model_version')}   "
         f"Champion: {sc.get('champion_version')}")
    line(f"Challengers: {sc.get('challenger_count')}   "
         f"Evaluated trades: {sc.get('total_evaluated_trades')}")
    line(f"Calibration error: {sc.get('confidence_calibration_score')}   "
         f"Threshold status: {sc.get('threshold_quality')}")
    line(f"Readiness: {sc.get('readiness_status')}")
    line(f"Auto paper entries: {sc.get('auto_paper_entries')}   "
         f"Live orders: {sc.get('live_orders')}")
    line("")
    line("Calibration buckets:", 11)
    for b in bundle["calibration"].get("buckets", []):
        line(f"  {b['bucket']}: trades={b['trades']} win_rate={b['win_rate']} "
             f"status={b['status']}", 9, 0.45)
    line("")
    line("Threshold candidates (test window):", 11)
    for cand in bundle["thresholds"].get("candidates", []):
        line(f"  buy>={cand['threshold_set']['buy']}: trades={cand['trades']} "
             f"expectancy={cand['expectancy']} overfit={cand['overfit_risk']} "
             f"recommended={cand['recommended']}", 9, 0.45)
    line("")
    line("No challenger was auto-promoted. Champion unchanged.", 10)
    line("APPROVED_FOR_PAPER_TEST does not mean live trading approval.", 10)
    c.save()
    return True


def build_phase21_exports() -> dict:
    os.makedirs(EXPORT_DIR, exist_ok=True)
    bundle = _bundle()
    with open(JSON_FILE, "w") as f:
        json.dump(bundle, f, indent=1, default=str)
    _write_csv(bundle)
    pdf_ok = _write_pdf(bundle)
    files = [JSON_FILE, CSV_FILE] + ([PDF_FILE] if pdf_ok else [])
    return {"success": True,
            "files": [os.path.basename(p) for p in files],
            "dir": EXPORT_DIR,
            "pdf_generated": pdf_ok,
            "label": "PAPER / RESEARCH ONLY"}
