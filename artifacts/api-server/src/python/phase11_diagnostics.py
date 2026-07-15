"""
phase11_diagnostics.py — Phase 11 Live Data Foundation
Diagnostic bundle generator: one honest snapshot of system health for
support/debugging. Writes phase11_diagnostic_bundle.json and
phase11_summary.csv next to this file.

PAPER TRADING ONLY — research system, no real orders.
"""

from __future__ import annotations

import csv
import json
import os
import platform
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

_DIR = os.path.dirname(__file__)
BUNDLE_FILE = os.path.join(_DIR, "phase11_diagnostic_bundle.json")
SUMMARY_CSV = os.path.join(_DIR, "phase11_summary.csv")

RESEARCH_ENGINE_VERSION = "Research Engine v1.0"


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _read_json(filename: str) -> Optional[Any]:
    path = os.path.join(_DIR, filename)
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return None


def _file_meta(filename: str) -> Dict[str, Any]:
    path = os.path.join(_DIR, filename)
    if not os.path.exists(path):
        return {"file": filename, "exists": False, "size_bytes": None, "modified": None}
    st = os.stat(path)
    return {
        "file": filename,
        "exists": True,
        "size_bytes": st.st_size,
        "modified": datetime.fromtimestamp(st.st_mtime, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def build_diagnostic_bundle() -> Dict[str, Any]:
    """Assemble the bundle, write JSON + CSV, and return the bundle."""
    from market_hours import market_status
    from live_quote_service import provider_status

    scan_cache = _read_json("phase7_scan_cache.json") or {}
    kill_switch = _read_json("phase11_kill_switch.json")
    risk_alerts = _read_json("phase11_risk_alerts.json")
    alerts = _read_json("phase9_alerts.json") or []
    portfolio = _read_json("portfolio.json") or {}

    recs = scan_cache.get("recommendations", []) if isinstance(scan_cache, dict) else []
    ph = scan_cache.get("provider_health", {}) if isinstance(scan_cache, dict) else {}

    key_files = [
        "phase7_scan_cache.json", "phase9_alerts.json", "portfolio.json",
        "phase11_kill_switch.json", "phase11_risk_alerts.json",
        "nse_holidays.json", "phase11_quote_state.json",
    ]

    bundle: Dict[str, Any] = {
        "bundle_version": 1,
        "generated_at": _now(),
        "engine_version": RESEARCH_ENGINE_VERSION,
        "mode": "PAPER_TRADING_RESEARCH_ONLY",
        "environment": {
            "python_version": sys.version.split()[0],
            "platform": platform.platform(),
        },
        "market_status": market_status(),
        "quote_provider": provider_status(),
        "scan": {
            "scan_id": scan_cache.get("scan_id") if isinstance(scan_cache, dict) else None,
            "snapshot_ts": scan_cache.get("snapshot_ts") if isinstance(scan_cache, dict) else None,
            "recommendation_count": len(recs),
            "provider_connection": ph.get("connection_status"),
            "symbol_coverage_pct": ph.get("symbol_coverage_pct"),
            "quality_summary": ph.get("quality_summary"),
            "paper_execution_eligible": ph.get("paper_execution_eligible"),
        },
        "risk": {
            "kill_switch": kill_switch,
            "risk_alert_count": len(risk_alerts) if isinstance(risk_alerts, list) else None,
        },
        "notifications": {
            "total_alerts": len(alerts) if isinstance(alerts, list) else None,
            "unread": sum(1 for a in alerts if isinstance(a, dict) and not a.get("read")) if isinstance(alerts, list) else None,
        },
        "portfolio": {
            "cash": portfolio.get("cash"),
            "open_positions": len(portfolio.get("positions", []) or portfolio.get("holdings", []) or []),
        },
        "files": [_file_meta(f) for f in key_files],
        "notes": [
            "All values are honest point-in-time observations; missing data is null.",
            "PAPER TRADING ONLY — no real broker orders are placed by this system.",
        ],
    }

    try:
        with open(BUNDLE_FILE, "w") as f:
            json.dump(bundle, f, indent=2, default=str)
    except Exception as exc:
        bundle["write_error"] = str(exc)

    _write_summary_csv(bundle)
    bundle["bundle_file"] = os.path.basename(BUNDLE_FILE)
    bundle["summary_csv"] = os.path.basename(SUMMARY_CSV)
    return bundle


def _flatten(prefix: str, obj: Any, rows: List[Dict[str, Any]]) -> None:
    if isinstance(obj, dict):
        for k, v in obj.items():
            _flatten(f"{prefix}.{k}" if prefix else str(k), v, rows)
    elif isinstance(obj, list):
        rows.append({"key": prefix, "value": f"[{len(obj)} items]"})
    else:
        rows.append({"key": prefix, "value": "" if obj is None else str(obj)})


def _write_summary_csv(bundle: Dict[str, Any]) -> None:
    rows: List[Dict[str, Any]] = []
    for section in ("generated_at", "engine_version", "mode", "market_status",
                    "quote_provider", "scan", "risk", "notifications", "portfolio"):
        _flatten(section, bundle.get(section), rows)
    try:
        with open(SUMMARY_CSV, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["key", "value"])
            w.writeheader()
            w.writerows(rows)
    except Exception:
        pass
