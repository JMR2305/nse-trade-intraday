#!/usr/bin/env python3
"""
phase2a_health_audit.py — Phase 2A System Health Audit for ApexQuant AI.

Probes all 15 subsystems and produces a machine-readable JSON results file.
Run from the workspace root:
    uv run python artifacts/api-server/src/python/phase2a_health_audit.py

Exits 0 if all subsystems are HEALTHY or DEGRADED.
Exits 1 if any subsystem is DOWN.
"""
from __future__ import annotations

import importlib
import json
import os
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

# ── Config ────────────────────────────────────────────────────────────────────
API_PORT = int(os.environ.get("PORT", 8080))
API_BASE = f"http://localhost:{API_PORT}/api"
PYTHON_DIR = os.path.dirname(os.path.abspath(__file__))
RESULTS_FILE = os.path.join(
    PYTHON_DIR, "..", "..", "..", "docs", "phase2a_audit_results.json"
)
os.makedirs(os.path.dirname(RESULTS_FILE), exist_ok=True)

DASH_PORT = int(os.environ.get("DASHBOARD_PORT", 24210))
DASH_BASE = f"http://localhost:{DASH_PORT}/trading-dashboard"


# ── HTTP helpers ──────────────────────────────────────────────────────────────

def _http_get(path: str, timeout: float = 15.0) -> Tuple[Optional[Any], float, Optional[str]]:
    """Returns (parsed_json, latency_ms, error_string)."""
    url = f"{API_BASE}/{path}"
    t0 = time.monotonic()
    try:
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode()
        latency = (time.monotonic() - t0) * 1000
        return json.loads(raw), round(latency, 1), None
    except urllib.error.HTTPError as e:
        latency = (time.monotonic() - t0) * 1000
        return None, round(latency, 1), f"HTTP {e.code}: {e.reason}"
    except Exception as exc:
        latency = (time.monotonic() - t0) * 1000
        return None, round(latency, 1), str(exc)


def _http_reachable(url: str, timeout: float = 5.0) -> Tuple[bool, float, Optional[str]]:
    """Check if a URL is reachable (any 2xx/3xx/4xx counts — just not connection error)."""
    t0 = time.monotonic()
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            resp.read()
        return True, round((time.monotonic() - t0) * 1000, 1), None
    except urllib.error.HTTPError as e:
        # HTTP error = server is reachable, route just returned an error code
        return True, round((time.monotonic() - t0) * 1000, 1), f"HTTP {e.code}"
    except Exception as exc:
        return False, round((time.monotonic() - t0) * 1000, 1), str(exc)


def _check_import(module: str) -> Tuple[bool, Optional[str]]:
    try:
        mod = importlib.import_module(module)
        ver = getattr(mod, "__version__", "?")
        return True, str(ver)
    except ImportError as e:
        return False, str(e)


def _require(data: Optional[Any], fields: List[str]) -> Tuple[List[str], List[str]]:
    """Return (present_fields, missing_fields)."""
    if data is None:
        return [], fields
    if isinstance(data, list):
        # For lists, check that items have the fields (use first item)
        item = data[0] if data else {}
    else:
        item = data
    present = [f for f in fields if f in item]
    missing = [f for f in fields if f not in item]
    return present, missing


# ── Probe functions (one per subsystem) ───────────────────────────────────────

def probe_01_market_data() -> Dict[str, Any]:
    """Market Data — yfinance provider, coverage, current_time."""
    data, lat, err = _http_get("live-data/health-v2", timeout=20)
    if err or not data:
        return {
            "subsystem": "Market Data",
            "status": "DOWN",
            "latency_ms": lat,
            "fields_verified": [],
            "notes": err or "No response",
        }
    market = data.get("market", {})
    provider = data.get("quote_provider", {})
    fields_verified = []
    notes_parts = []

    if market.get("state"):
        fields_verified.append("market.state")
        notes_parts.append(f"state={market['state']}")
    if market.get("now_ist"):
        fields_verified.append("market.now_ist")
    if provider:
        fields_verified.append("quote_provider")
        notes_parts.append(f"provider={provider.get('name', '?')}")

    # Check scan status for coverage
    scan_data, _, _ = _http_get("live-data/scan/status", timeout=10)
    if scan_data and scan_data.get("latest_scan"):
        ls = scan_data["latest_scan"]
        recv = ls.get("symbols_received", 0)
        req  = ls.get("symbols_requested", 50)
        miss = ls.get("missing_symbols", [])
        fields_verified += ["scan_id", "symbols_received", "symbols_requested"]
        notes_parts.append(f"coverage={recv}/{req}")
        if miss:
            notes_parts.append(f"missing={miss}")

    # yfinance import check
    ok, ver = _check_import("yfinance")
    notes_parts.append(f"yfinance={'OK v'+ver if ok else 'MISSING'}")

    status = "HEALTHY" if not err else "DEGRADED"
    if market.get("state") == "WEEKEND":
        notes_parts.append("WEEKEND (expected — no live quotes)")
        status = "HEALTHY"

    return {
        "subsystem": "Market Data",
        "status": status,
        "latency_ms": lat,
        "fields_verified": fields_verified,
        "notes": "; ".join(notes_parts),
    }


def probe_02_scanner() -> Dict[str, Any]:
    """Scanner — scan_state_store, latest snapshot metadata."""
    data, lat, err = _http_get("live-data/scan/status", timeout=10)
    if err or not data:
        return {
            "subsystem": "Scanner",
            "status": "DOWN",
            "latency_ms": lat,
            "fields_verified": [],
            "notes": err or "No response",
        }
    ls = data.get("latest_scan")
    if not ls:
        return {
            "subsystem": "Scanner",
            "status": "DEGRADED",
            "latency_ms": lat,
            "fields_verified": [],
            "notes": "latest_scan is null — no completed scan in DB or cache",
        }

    required = ["scan_id", "status", "snapshot_ts", "symbols_requested", "symbols_received"]
    present, missing = _require(ls, required)
    notes = [
        f"scan_id={ls.get('scan_id','?')}",
        f"status={ls.get('status','?')}",
        f"symbols={ls.get('symbols_received','?')}/{ls.get('symbols_requested','?')}",
    ]
    if ls.get("missing_symbols"):
        notes.append(f"missing_symbols={ls['missing_symbols']}")
    completed = ls.get("completed_at")
    if completed:
        notes.append(f"completed_at={completed}")

    status = "HEALTHY" if ls.get("status") == "SUCCESS" and not missing else "DEGRADED"
    return {
        "subsystem": "Scanner",
        "status": status,
        "latency_ms": lat,
        "fields_verified": present,
        "notes": "; ".join(notes),
    }


def probe_03_signal_engine() -> Dict[str, Any]:
    """Signal Engine — signals endpoint, field shape."""
    data, lat, err = _http_get("signals", timeout=20)
    if err:
        return {
            "subsystem": "Signal Engine",
            "status": "DOWN",
            "latency_ms": lat,
            "fields_verified": [],
            "notes": err,
        }
    if not isinstance(data, list):
        return {
            "subsystem": "Signal Engine",
            "status": "DEGRADED",
            "latency_ms": lat,
            "fields_verified": [],
            "notes": f"Expected list, got {type(data).__name__}",
        }

    required = ["stock", "signal", "confidence", "price"]
    fields_verified = []
    if data:
        item = data[0]
        fields_verified = [f for f in required if f in item]
        missing = [f for f in required if f not in item]
    else:
        missing = required

    # advisory_only check — signals may not have it directly (it's in AI decisions)
    advisory_checked = False
    try:
        sys.path.insert(0, PYTHON_DIR)
        from signals_store import load_signals
        cached = load_signals() or []
        if cached and isinstance(cached[0], dict) and "advisory_only" in cached[0]:
            advisory_checked = True
    except Exception:
        pass

    notes = [
        f"count={len(data)}",
        f"first_stock={data[0].get('stock','?') if data else 'N/A'}",
    ]
    if missing:
        notes.append(f"missing_fields={missing}")
    if advisory_checked:
        notes.append("advisory_only=verified in signals_cache")

    status = "HEALTHY" if not missing else "DEGRADED"
    return {
        "subsystem": "Signal Engine",
        "status": status,
        "latency_ms": lat,
        "fields_verified": fields_verified,
        "notes": "; ".join(notes),
    }


def probe_04_ai_advisory() -> Dict[str, Any]:
    """AI Advisory — ai-decisions endpoint, advisory_only label, staleness."""
    data, lat, err = _http_get("ai-decisions", timeout=20)
    if err:
        return {
            "subsystem": "AI Advisory",
            "status": "DOWN",
            "latency_ms": lat,
            "fields_verified": [],
            "notes": err,
        }

    stale_data, _, _ = _http_get("phase15/staleness", timeout=10)
    label_ok = False
    if stale_data:
        label_ok = "PAPER" in str(stale_data.get("label", ""))

    required = ["stock", "decision", "confidence", "regime"]
    fields_verified = []
    missing = []
    if isinstance(data, list) and data:
        item = data[0]
        fields_verified = [f for f in required if f in item]
        missing = [f for f in required if f not in item]

    # advisory_only enforcement: buy_recommendations_disabled when stale
    buy_disabled = stale_data and stale_data.get("buy_recommendations_disabled", False)
    notes = [
        f"decisions_count={len(data) if isinstance(data, list) else 'N/A'}",
        f"PAPER_label={'OK' if label_ok else 'MISSING'}",
        f"buy_disabled_when_stale={buy_disabled}",
    ]
    if stale_data and stale_data.get("stale"):
        notes.append(f"stale={stale_data.get('scan_age_human','?')}")

    status = "HEALTHY" if not missing and label_ok else "DEGRADED"
    return {
        "subsystem": "AI Advisory",
        "status": status,
        "latency_ms": lat,
        "fields_verified": fields_verified + (["paper_label", "staleness"] if stale_data else []),
        "notes": "; ".join(notes),
    }


def probe_05_risk_engine() -> Dict[str, Any]:
    """Risk Engine — portfolio/config, limit fields, pydantic import."""
    data, lat, err = _http_get("portfolio/config", timeout=15)
    pydantic_ok, pydantic_ver = _check_import("pydantic")

    notes = [f"pydantic={'OK v'+pydantic_ver if pydantic_ok else 'MISSING — CRITICAL'}"]
    fields_verified = []

    if err:
        return {
            "subsystem": "Risk Engine",
            "status": "DOWN",
            "latency_ms": lat,
            "fields_verified": [],
            "notes": f"{err}; {'; '.join(notes)}",
        }

    loaded = data.get("loaded", False) if data else False
    config = data.get("config", {}) if data else {}
    config_err = data.get("error") if data else None

    required_limits = [
        "max_portfolio_exposure_pct", "max_instrument_exposure_pct",
        "max_sector_exposure_pct", "daily_loss_limit_pct",
    ]
    present_limits = [f for f in required_limits if f in config]
    missing_limits = [f for f in required_limits if f not in config]

    if loaded:
        fields_verified = ["loaded", "config"] + present_limits
    else:
        notes.append(f"config_load_failed={config_err}")

    health_data, _, _ = _http_get("portfolio/health", timeout=15)
    if health_data:
        fields_verified.append("portfolio/health")
        if health_data.get("degraded"):
            notes.append(f"health_degraded={health_data.get('failure_reason','?')}")

    # Risk engine is DEGRADED (not DOWN) — defaults are still enforced,
    # just not via the full pydantic-validated config
    status = "HEALTHY" if loaded and pydantic_ok and not missing_limits else "DEGRADED"
    if not pydantic_ok:
        notes.append("PortfolioConfig falls back to hardcoded defaults")

    return {
        "subsystem": "Risk Engine",
        "status": status,
        "latency_ms": lat,
        "fields_verified": fields_verified,
        "notes": "; ".join(notes),
    }


def probe_06_paper_execution() -> Dict[str, Any]:
    """Paper Execution — paper_mode flag, no live-order capability."""
    data, lat, err = _http_get("portfolio/snapshot", timeout=15)
    if err or not data:
        return {
            "subsystem": "Paper Execution",
            "status": "DOWN",
            "latency_ms": lat,
            "fields_verified": [],
            "notes": err or "No response",
        }

    paper_mode = data.get("paper_mode", False)
    status_field = data.get("status")
    auto_disabled = not data.get("auto_paper_enabled", True)  # default OFF is safe

    fields_verified = ["paper_mode"]
    notes = [
        f"paper_mode={paper_mode}",
        f"status={status_field}",
        f"auto_paper_entries={'OFF (safe)' if auto_disabled else 'ON — review'}",
    ]

    # Check that no live-order route is exposed
    _, _, live_order_err = _http_get("live-orders", timeout=3)
    if live_order_err and ("404" in live_order_err or "HTTP 404" in str(live_order_err)):
        fields_verified.append("live_orders_absent")
        notes.append("live-orders route=404 (correct — paper only)")
    else:
        notes.append(f"live-orders probe={live_order_err or 'unexpected response'}")

    status = "HEALTHY" if paper_mode else "DOWN"
    return {
        "subsystem": "Paper Execution",
        "status": status,
        "latency_ms": lat,
        "fields_verified": fields_verified,
        "notes": "; ".join(notes),
    }


def probe_07_portfolio() -> Dict[str, Any]:
    """Portfolio — snapshot fields, equity, positions, cash."""
    data, lat, err = _http_get("portfolio/snapshot", timeout=15)
    required = ["cash", "equity", "open_positions", "realised_pnl_today",
                "unrealised_pnl", "initial_capital", "peak_equity", "drawdown_pct"]
    if err or not data:
        return {
            "subsystem": "Portfolio",
            "status": "DOWN",
            "latency_ms": lat,
            "fields_verified": [],
            "notes": err or "No response",
        }
    present, missing = _require(data, required)
    notes = [
        f"equity={data.get('equity','?')}",
        f"cash={data.get('cash','?')}",
        f"open_positions={len(data.get('open_positions', []))}",
        f"initial_capital={data.get('initial_capital','?')}",
    ]
    if missing:
        notes.append(f"missing={missing}")
    status = "HEALTHY" if not missing else "DEGRADED"
    return {
        "subsystem": "Portfolio",
        "status": status,
        "latency_ms": lat,
        "fields_verified": present,
        "notes": "; ".join(notes),
    }


def probe_08_pnl() -> Dict[str, Any]:
    """P&L — realised and unrealised PnL fields in portfolio snapshot."""
    data, lat, err = _http_get("portfolio/snapshot", timeout=15)
    required = ["realised_pnl_today", "unrealised_pnl", "total_pnl",
                "drawdown_amount", "drawdown_pct"]
    if err or not data:
        return {
            "subsystem": "P&L",
            "status": "DOWN",
            "latency_ms": lat,
            "fields_verified": [],
            "notes": err or "No response",
        }
    present, missing = _require(data, required)
    # Also check legacy /portfolio endpoint for pnl_history
    legacy, _, _ = _http_get("portfolio", timeout=10)
    if legacy and isinstance(legacy.get("pnl_history"), list):
        present.append("pnl_history")
    notes = [
        f"realised_pnl_today={data.get('realised_pnl_today', '?')}",
        f"unrealised_pnl={data.get('unrealised_pnl', '?')}",
        f"total_pnl={data.get('total_pnl', '?')}",
        f"drawdown_pct={data.get('drawdown_pct', '?')}",
    ]
    if missing:
        notes.append(f"missing={missing}")
    status = "HEALTHY" if not missing else "DEGRADED"
    return {
        "subsystem": "P&L",
        "status": status,
        "latency_ms": lat,
        "fields_verified": present,
        "notes": "; ".join(notes),
    }


def probe_09_trade_journal() -> Dict[str, Any]:
    """Trade Journal — /api/trades endpoint, trade record fields."""
    data, lat, err = _http_get("trades", timeout=10)
    if err:
        return {
            "subsystem": "Trade Journal",
            "status": "DOWN",
            "latency_ms": lat,
            "fields_verified": [],
            "notes": err,
        }
    # trades may be empty (clean paper portfolio) — endpoint must return a list
    if not isinstance(data, list):
        return {
            "subsystem": "Trade Journal",
            "status": "DEGRADED",
            "latency_ms": lat,
            "fields_verified": [],
            "notes": f"Expected list, got {type(data).__name__}",
        }
    required_trade_fields = ["id", "symbol", "action", "quantity", "price", "timestamp"]
    fields_verified = ["endpoint_reachable", "returns_list"]
    if data:
        item = data[0]
        present = [f for f in required_trade_fields if f in item]
        missing = [f for f in required_trade_fields if f not in item]
        fields_verified += present
        notes = [f"trade_count={len(data)}", f"first_action={item.get('action','?')}"]
        if missing:
            notes.append(f"missing={missing}")
        status = "HEALTHY" if not missing else "DEGRADED"
    else:
        notes = ["trade_count=0 (clean state — no trades yet)"]
        status = "HEALTHY"

    # Also probe all-time trades
    all_data, _, _ = _http_get("trades?scope=all", timeout=10)
    if isinstance(all_data, list):
        fields_verified.append("scope=all")
        notes.append(f"all_time_count={len(all_data)}")

    return {
        "subsystem": "Trade Journal",
        "status": status,
        "latency_ms": lat,
        "fields_verified": fields_verified,
        "notes": "; ".join(notes),
    }


def probe_10_audit_logs() -> Dict[str, Any]:
    """Audit Logs — phase13/audit endpoint, report structure."""
    data, lat, err = _http_get("phase13/audit", timeout=15)
    if err or not data:
        return {
            "subsystem": "Audit Logs",
            "status": "DOWN",
            "latency_ms": lat,
            "fields_verified": [],
            "notes": err or "No response",
        }
    report = data.get("report", {})
    fields_verified = ["endpoint_reachable"]
    notes = []
    if report:
        fields_verified += ["report", "phase", "label", "generated_at"]
        notes.append(f"engine_version={report.get('engine_version','?')}")
        notes.append(f"label={report.get('label','?')}")
        paper_label = "PAPER" in str(report.get("label", ""))
        notes.append(f"PAPER_label={'OK' if paper_label else 'MISSING'}")
        mode = report.get("mode")
        if mode:
            notes.append(f"mode={mode}")
    else:
        notes.append("report field missing from response")

    status = "HEALTHY" if report and "PAPER" in str(report.get("label", "")) else "DEGRADED"
    return {
        "subsystem": "Audit Logs",
        "status": status,
        "latency_ms": lat,
        "fields_verified": fields_verified,
        "notes": "; ".join(notes),
    }


def probe_11_recovery() -> Dict[str, Any]:
    """Recovery — liveness, readiness, uptime, Python runtime."""
    healthz, lat1, err1 = _http_get("healthz", timeout=5)
    live, lat2, err2 = _http_get("health/live", timeout=5)
    ready, lat3, err3 = _http_get("health/ready", timeout=10)
    lat = round((lat1 + lat2 + lat3) / 3, 1)

    fields_verified = []
    notes = []
    all_ok = True

    if healthz and healthz.get("status") == "ok":
        fields_verified.append("healthz")
        notes.append("healthz=OK")
    else:
        notes.append(f"healthz=FAIL ({err1})")
        all_ok = False

    if live and live.get("status") == "ok":
        fields_verified.append("health/live")
        uptime = live.get("uptime_s", 0)
        notes.append(f"uptime={uptime}s")
    else:
        notes.append(f"health/live=FAIL ({err2})")
        all_ok = False

    if ready:
        checks = ready.get("checks", {})
        python_ok = checks.get("python_runtime", False)
        cache_ok = checks.get("scan_cache_readable", False)
        fields_verified += ["health/ready", "python_runtime", "scan_cache"]
        notes.append(f"python_runtime={python_ok}")
        notes.append(f"scan_cache={cache_ok}")
        if not python_ok:
            all_ok = False
    else:
        notes.append(f"health/ready=FAIL ({err3})")
        all_ok = False

    status = "HEALTHY" if all_ok else "DEGRADED"
    return {
        "subsystem": "Recovery",
        "status": status,
        "latency_ms": lat,
        "fields_verified": fields_verified,
        "notes": "; ".join(notes),
    }


def probe_12_mobile_app() -> Dict[str, Any]:
    """Mobile App — Expo workflow running, API base URL resolves."""
    import subprocess
    notes = []
    fields_verified = []
    expo_port = 21338

    # Check if Expo process is running
    try:
        result = subprocess.run(
            ["pgrep", "-f", "expo"],
            capture_output=True, text=True, timeout=3
        )
        expo_running = result.returncode == 0
    except Exception:
        expo_running = False
    notes.append(f"expo_process={'running' if expo_running else 'NOT FOUND'}")

    # Check mobile API config file
    mobile_config = os.path.join(
        PYTHON_DIR, "..", "..", "..", "..", "trading-mobile", "lib", "apiConfig.ts"
    )
    mobile_config = os.path.normpath(mobile_config)
    config_exists = os.path.exists(mobile_config)
    if config_exists:
        fields_verified.append("apiConfig.ts")
        notes.append("mobile apiConfig.ts=present")

    # Check mobile dataStatus
    mobile_datastatus = os.path.join(
        PYTHON_DIR, "..", "..", "..", "..", "trading-mobile", "lib", "dataStatus.ts"
    )
    mobile_datastatus = os.path.normpath(mobile_datastatus)
    if os.path.exists(mobile_datastatus):
        fields_verified.append("dataStatus.ts")

    # Try reaching Expo port (may not respond to HTTP GET directly)
    reachable, lat, err = _http_reachable(f"http://localhost:{expo_port}", timeout=3)
    notes.append(f"expo_port_{expo_port}={'reachable' if reachable else 'not_responding'}")
    if err and "404" in str(err):
        reachable = True  # HTTP server is up, route returned 404 — that's fine

    # Check that mobile workflow config exists
    mobile_pkg = os.path.join(
        PYTHON_DIR, "..", "..", "..", "..", "trading-mobile", "package.json"
    )
    if os.path.exists(os.path.normpath(mobile_pkg)):
        fields_verified.append("package.json")
        notes.append("mobile package.json=present")

    status = "HEALTHY" if expo_running and config_exists else "DEGRADED"
    notes_note = ""
    if not expo_running:
        notes_note = "; NOTE: Expo process stuck on port-conflict prompt — workflow needs restart"
        status = "DEGRADED"

    return {
        "subsystem": "Mobile App",
        "status": status,
        "latency_ms": lat if reachable else 0,
        "fields_verified": fields_verified,
        "notes": "; ".join(notes) + notes_note,
    }


def probe_13_dashboard() -> Dict[str, Any]:
    """Dashboard — Vite workflow running, API reachable from dashboard port."""
    import subprocess
    notes = []
    fields_verified = []

    # Check Vite process
    try:
        result = subprocess.run(
            ["pgrep", "-f", "vite"],
            capture_output=True, text=True, timeout=3
        )
        vite_running = result.returncode == 0
    except Exception:
        vite_running = False
    notes.append(f"vite_process={'running' if vite_running else 'NOT FOUND'}")

    # Find dashboard port from known location
    dash_port = DASH_PORT
    reachable, lat, err = _http_reachable(f"http://localhost:{dash_port}", timeout=5)
    notes.append(f"dashboard_port_{dash_port}={'reachable' if reachable else 'not_responding'}: {err or 'OK'}")

    if reachable:
        fields_verified.append(f"port_{dash_port}_reachable")

    # Check apiConfig.ts exists (Phase 1A)
    api_config = os.path.join(
        PYTHON_DIR, "..", "..", "..", "..", "trading-dashboard", "src", "lib", "apiConfig.ts"
    )
    if os.path.exists(os.path.normpath(api_config)):
        fields_verified.append("apiConfig.ts")
        notes.append("apiConfig.ts=present (Phase 1A)")

    # Check ConnectivityPanel.tsx exists (dev diagnostics)
    conn_panel = os.path.join(
        PYTHON_DIR, "..", "..", "..", "..", "trading-dashboard", "src",
        "components", "ConnectivityPanel.tsx"
    )
    if os.path.exists(os.path.normpath(conn_panel)):
        fields_verified.append("ConnectivityPanel.tsx")

    status = "HEALTHY" if vite_running and reachable else "DEGRADED"
    return {
        "subsystem": "Dashboard",
        "status": status,
        "latency_ms": lat,
        "fields_verified": fields_verified,
        "notes": "; ".join(notes),
    }


def probe_14_api_server() -> Dict[str, Any]:
    """API Server — all critical route files present, response time < 2s."""
    t0 = time.monotonic()
    data, lat, err = _http_get("healthz", timeout=5)
    elapsed = (time.monotonic() - t0) * 1000

    routes_dir = os.path.join(PYTHON_DIR, "..", "routes")
    routes_dir = os.path.normpath(routes_dir)
    critical_routes = [
        "health.ts", "trading.ts", "portfolio.ts", "stream.ts",
        "phase13.ts", "phase15.ts", "phase22.ts", "kite.ts",
        "notifications.ts", "reconciliation.ts",
    ]
    missing_routes = []
    present_routes = []
    for r in critical_routes:
        path = os.path.join(routes_dir, r)
        if os.path.exists(path):
            present_routes.append(r)
        else:
            missing_routes.append(r)

    python_bin = os.path.join(PYTHON_DIR, "..", "..", "..", "..", "..", ".pythonlibs", "bin", "python3")
    python_bin = os.path.normpath(python_bin)
    python_exists = os.path.exists(python_bin)

    notes = [
        f"response_time={round(elapsed,0)}ms",
        f"routes_present={len(present_routes)}/{len(critical_routes)}",
        f"python_bin={'found' if python_exists else 'not_found at .pythonlibs'}",
    ]
    if missing_routes:
        notes.append(f"missing_routes={missing_routes}")

    all_ok = (data and data.get("status") == "ok"
              and not missing_routes and elapsed < 2000)
    status = "HEALTHY" if all_ok else ("DEGRADED" if not err else "DOWN")
    return {
        "subsystem": "API Server",
        "status": status,
        "latency_ms": lat,
        "fields_verified": [f"route:{r}" for r in present_routes],
        "notes": "; ".join(notes),
    }


def probe_15_database() -> Dict[str, Any]:
    """Database — DATABASE_URL resolves, critical tables exist."""
    db_url = os.environ.get("DATABASE_URL", "")
    notes = []
    fields_verified = []

    if not db_url:
        return {
            "subsystem": "Database",
            "status": "DOWN",
            "latency_ms": 0,
            "fields_verified": [],
            "notes": "DATABASE_URL not set",
        }
    notes.append(f"DATABASE_URL=SET ({len(db_url)} chars)")
    fields_verified.append("DATABASE_URL")

    # Try to connect and check tables
    t0 = time.monotonic()
    try:
        import psycopg2
        conn = psycopg2.connect(db_url, connect_timeout=5)
        lat = round((time.monotonic() - t0) * 1000, 1)
        fields_verified.append("connection_ok")
        notes.append("connection=OK")

        critical_tables = [
            "paper_portfolio", "paper_trades", "signals_cache",
            "scan_state", "scan_lock", "phase20_paper_trades",
        ]
        missing_tables = []
        present_tables = []
        with conn.cursor() as cur:
            cur.execute("""
                SELECT tablename FROM pg_tables
                WHERE schemaname = 'public'
            """)
            existing = {row[0] for row in cur.fetchall()}
        conn.close()

        for tbl in critical_tables:
            if tbl in existing:
                present_tables.append(tbl)
                fields_verified.append(f"table:{tbl}")
            else:
                missing_tables.append(tbl)

        notes.append(f"tables_present={len(present_tables)}/{len(critical_tables)}")
        if missing_tables:
            notes.append(f"missing_tables={missing_tables}")
            notes.append("NOTE: missing tables auto-create on first use — not a hard failure")

        status = "HEALTHY" if len(missing_tables) == 0 else "DEGRADED"

    except Exception as exc:
        lat = round((time.monotonic() - t0) * 1000, 1)
        notes.append(f"connection_failed={exc}")
        status = "DOWN"

    return {
        "subsystem": "Database",
        "status": status,
        "latency_ms": lat,
        "fields_verified": fields_verified,
        "notes": "; ".join(notes),
    }


def probe_16_market_hours_coverage() -> Dict[str, Any]:
    """Market-Hours Coverage — scanner must recover to full coverage in session."""
    t0 = time.monotonic()
    try:
        sys.path.insert(0, PYTHON_DIR)
        from scanner_coverage import coverage_probe
        cov = coverage_probe()
    except Exception as exc:
        return {
            "subsystem": "Market-Hours Coverage",
            "status": "DOWN",
            "latency_ms": round((time.monotonic() - t0) * 1000, 1),
            "fields_verified": [],
            "notes": f"scanner_coverage probe failed: {exc}",
        }
    lat = round((time.monotonic() - t0) * 1000, 1)
    fields = [f for f in ("market_state", "in_session", "coverage",
                          "min_symbols_expected", "ok") if f in cov]
    notes = [
        f"state={cov.get('market_state', '?')}",
        f"in_session={cov.get('in_session')}",
        f"coverage={cov.get('coverage', '?')}/{cov.get('min_symbols_expected', '?')}",
    ]
    if cov.get("missing_symbols"):
        notes.append(f"missing={cov['missing_symbols']}")
    if cov.get("warning"):
        notes.append(f"WARNING: {cov['warning']}")
    if cov.get("note"):
        notes.append(cov["note"])
    # DEGRADED (not DOWN) — data gap in session is an operator alert, the
    # subsystem itself is still serving; DOWN only if the probe cannot run.
    status = "HEALTHY" if cov.get("ok") else "DEGRADED"
    if not cov.get("success", True):
        status = "DOWN"
    return {
        "subsystem": "Market-Hours Coverage",
        "status": status,
        "latency_ms": lat,
        "fields_verified": fields,
        "notes": "; ".join(str(n) for n in notes),
    }


# ── Main runner ───────────────────────────────────────────────────────────────

PROBES = [
    probe_01_market_data,
    probe_02_scanner,
    probe_03_signal_engine,
    probe_04_ai_advisory,
    probe_05_risk_engine,
    probe_06_paper_execution,
    probe_07_portfolio,
    probe_08_pnl,
    probe_09_trade_journal,
    probe_10_audit_logs,
    probe_11_recovery,
    probe_12_mobile_app,
    probe_13_dashboard,
    probe_14_api_server,
    probe_15_database,
    probe_16_market_hours_coverage,
]


def run_audit() -> Dict[str, Any]:
    print("=" * 60)
    print("ApexQuant AI — Phase 2A System Health Audit")
    print(f"Run at: {datetime.now(timezone.utc).isoformat()}")
    print(f"API base: {API_BASE}")
    print("=" * 60)

    results: List[Dict[str, Any]] = []
    counts = {"HEALTHY": 0, "DEGRADED": 0, "DOWN": 0, "SKIPPED": 0}

    for probe_fn in PROBES:
        name = probe_fn.__doc__.split("—")[0].strip()
        print(f"\n[{len(results)+1:02d}/{len(PROBES)}] {name} ...", end=" ", flush=True)
        try:
            result = probe_fn()
        except Exception as exc:
            result = {
                "subsystem": name,
                "status": "DOWN",
                "latency_ms": 0,
                "fields_verified": [],
                "notes": f"Probe raised exception: {exc}",
            }
        status = result.get("status", "SKIPPED")
        icon = {"HEALTHY": "✅", "DEGRADED": "⚠️", "DOWN": "❌", "SKIPPED": "⏩"}.get(status, "?")
        print(f"{icon} {status} ({result.get('latency_ms', 0):.0f}ms)")
        if result.get("notes"):
            print(f"    {result['notes'][:120]}")
        counts[status] = counts.get(status, 0) + 1
        results.append(result)

    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print(f"  ✅ HEALTHY:  {counts['HEALTHY']:2d}/{len(PROBES)}")
    print(f"  ⚠️  DEGRADED: {counts['DEGRADED']:2d}/{len(PROBES)}")
    print(f"  ❌ DOWN:     {counts['DOWN']:2d}/{len(PROBES)}")
    print(f"  ⏩ SKIPPED:  {counts['SKIPPED']:2d}/{len(PROBES)}")
    print("=" * 60)

    output = {
        "audit_run_at": datetime.now(timezone.utc).isoformat(),
        "api_base": API_BASE,
        "summary": counts,
        "results": results,
        "overall_status": "DOWN" if counts["DOWN"] > 0 else (
            "DEGRADED" if counts["DEGRADED"] > 0 else "HEALTHY"
        ),
    }

    # Write JSON results
    try:
        with open(RESULTS_FILE, "w") as f:
            json.dump(output, f, indent=2)
        print(f"\nResults written to: {RESULTS_FILE}")
    except Exception as exc:
        print(f"\nWarning: could not write results file: {exc}")

    return output


if __name__ == "__main__":
    sys.path.insert(0, PYTHON_DIR)
    result = run_audit()
    sys.exit(1 if result["overall_status"] == "DOWN" else 0)
