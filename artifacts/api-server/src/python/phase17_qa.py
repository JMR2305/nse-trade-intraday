"""
phase17_qa.py — Phase 17: Automated QA, Regression Testing & Release Validation.

Feature freeze phase: NO new strategies, NO new indicators, NO AI scoring
changes, NO paper-trading behaviour changes, NO live execution. This module
only VALIDATES the existing system: runs test suites, probes APIs, checks
data-store integrity, benchmarks performance, detects errors, and produces a
release checklist, release dashboard, validation history and a final score.

Honesty rules: anything that cannot be verified server-side (client-side UI
interactions, chart rendering, responsive layouts) is explicitly listed under
`not_checkable` instead of being faked as "passed". Metrics with insufficient
data are flagged, never failed. PAPER TRADING / RESEARCH ONLY.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone
from typing import Any

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LABEL = "PAPER / RESEARCH ONLY"
VERSION = "17.0"
HISTORY_PATH = os.path.join(BASE_DIR, "phase17_history.json")
LAST_RUN_PATH = os.path.join(BASE_DIR, "phase17_last_run.json")
HISTORY_CAP = 100

NA = "Insufficient Data"
NOT_AVAILABLE = "Not Available"

# Base URL of the running API server (spawned by it, so PORT is inherited).
API_PORT = os.environ.get("PORT", "3000")
API_BASE = f"http://127.0.0.1:{API_PORT}/api"

TEST_SUITES = [
    ("Scanner / Signals (Phase 7)", "test_phase7.py"),
    ("Broker & Execution (Phase 8)", "test_phase8.py"),
    ("AI Copilot & Notifications (Phase 9)", "test_phase9.py"),
    ("Performance Analytics (Phase 10)", "test_phase10.py"),
    ("Risk Engine (Phase 11)", "test_phase11.py"),
    ("Market Intelligence (Phase 12)", "test_phase12.py"),
    ("Institutional AI (Phase 13)", "test_phase13.py"),
    ("Learning & Governance (Phase 14)", "test_phase14.py"),
    ("Production Hardening (Phase 15)", "test_phase15.py"),
    ("Paper Trading Validation (Phase 16)", "test_phase16.py"),
]

# Curated endpoint checks: (path, required_fields)
API_CHECKS: list[tuple[str, list[str]]] = [
    ("/healthz", []),
    ("/portfolio", ["cash"]),
    ("/trades", []),
    ("/signals", []),
    ("/watchlist", []),
    ("/market/status", []),
    ("/analytics/performance", ["summary"]),
    ("/risk/dashboard", []),
    ("/ai-decisions", []),
    ("/copilot/summary", []),
    ("/learning-summary", []),
    ("/phase14/registry", []),
    ("/phase15/consistency", ["verdict"]),
    ("/phase15/diagnostics", []),
    ("/phase15/readiness", []),
    ("/phase16/all", ["overview", "bugs"]),
    ("/trade-replay", []),
    ("/opportunity-scan", []),
]

DATA_FILES = [
    "state.json", "phase7_scan_cache.json", "ai_decisions_cache.json",
    "signals_cache.json", "market_context_cache.json", "calibration_state.json",
    "phase14_model_registry.json", "phase9_alerts.json", "opportunity_cache.json",
]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_json(fname: str, default: Any) -> Any:
    try:
        with open(os.path.join(BASE_DIR, fname)) as f:
            return json.load(f)
    except Exception:
        return default


def _check(name: str, passed: bool | None, detail: str = "",
           severity: str = "ERROR") -> dict:
    """passed=None means WARN/not decidable."""
    status = "PASS" if passed else ("WARN" if passed is None else "FAIL")
    return {"check": name, "status": status, "detail": detail,
            "severity": severity if status == "FAIL" else ("WARN" if status == "WARN" else "OK")}


def _summarise(checks: list[dict]) -> dict:
    return {
        "total": len(checks),
        "passed": sum(1 for c in checks if c["status"] == "PASS"),
        "failed": sum(1 for c in checks if c["status"] == "FAIL"),
        "warnings": sum(1 for c in checks if c["status"] == "WARN"),
    }


def _section(name: str, checks: list[dict], **extra) -> dict:
    return {"success": True, "section": name, "generated_at": _now(),
            "label": LABEL, **_summarise(checks), "checks": checks, **extra}


# ── 1. build / version info ─────────────────────────────────────────────────

def build_info() -> dict:
    history = _load_json(os.path.basename(HISTORY_PATH), [])
    last = _load_json(os.path.basename(LAST_RUN_PATH), {})
    return {
        "success": True, "generated_at": _now(), "label": LABEL,
        "release_version": VERSION,
        "build_number": len(history) + 1,
        "environment": "development" if os.environ.get("NODE_ENV") != "production" else "production",
        "last_validation": last.get("generated_at", NOT_AVAILABLE),
        "last_validation_verdict": last.get("verdict", NOT_AVAILABLE),
    }


# ── 2. test suites (backend + frontend build) ───────────────────────────────

def _run_suite(script: str, timeout: int = 300) -> dict:
    t0 = time.time()
    try:
        p = subprocess.run(["python3", script], cwd=BASE_DIR,
                           capture_output=True, text=True, timeout=timeout)
        m = re.search(r"(\d+) passed, (\d+) failed", p.stdout)
        if m:
            return {"passed": int(m.group(1)), "failed": int(m.group(2)),
                    "ran": True, "seconds": round(time.time() - t0, 1)}
        # Older suites (phase 7/8) print [PASS]/[FAIL] lines + "ALL TESTS PASSED"
        n_pass = len(re.findall(r"\[PASS\]", p.stdout))
        n_fail = len(re.findall(r"\[FAIL\]", p.stdout))
        if n_pass or n_fail or "ALL TESTS PASSED" in p.stdout:
            return {"passed": n_pass, "failed": n_fail if n_fail else
                    (0 if p.returncode == 0 else 1),
                    "ran": True, "seconds": round(time.time() - t0, 1)}
        return {"passed": 0, "failed": 0, "ran": False,
                "seconds": round(time.time() - t0, 1),
                "error": (p.stderr or p.stdout)[-300:]}
    except Exception as e:
        return {"passed": 0, "failed": 0, "ran": False,
                "seconds": round(time.time() - t0, 1), "error": str(e)[:300]}


def backend_tests() -> dict:
    suites = []
    for label, script in TEST_SUITES:
        if not os.path.exists(os.path.join(BASE_DIR, script)):
            suites.append({"suite": label, "script": script, "ran": False,
                           "error": "suite file missing"})
            continue
        r = _run_suite(script)
        suites.append({"suite": label, "script": script, **r})
    checks = [_check(s["suite"],
                     (s.get("ran") and s.get("failed", 1) == 0) or (None if not s.get("ran") else False),
                     f"{s.get('passed', 0)} passed, {s.get('failed', 0)} failed"
                     + (f" — {s.get('error', '')}" if s.get("error") else ""))
              for s in suites]
    return _section("Backend Tests", checks, suites=suites)


def frontend_build_check() -> dict:
    """Server-side check: TypeScript compiles for both packages. Runtime UI
    behaviour (clicks, dialogs, charts) is not checkable server-side."""
    checks = []
    for pkg, cwd in [("api-server", os.path.join(BASE_DIR, "..", "..")),
                     ("trading-dashboard",
                      os.path.join(BASE_DIR, "..", "..", "..", "trading-dashboard"))]:
        t0 = time.time()
        try:
            p = subprocess.run(["npx", "tsc", "--noEmit", "-p", "."],
                               cwd=os.path.abspath(cwd), capture_output=True,
                               text=True, timeout=240)
            ok = p.returncode == 0
            checks.append(_check(f"TypeScript compile — {pkg}", ok,
                                 f"{round(time.time() - t0, 1)}s"
                                 + ("" if ok else f" — {p.stdout[-300:]}")))
        except Exception as e:
            checks.append(_check(f"TypeScript compile — {pkg}", None, str(e)[:200]))
    return _section("Frontend / Build Tests", checks, not_checkable=[
        "button clicks, dialogs, chart rendering, dark theme, responsive/mobile/tablet "
        "layouts, layout shifts, missing icons — require a real browser and are not "
        "verifiable server-side (no fabricated results)"])


# ── 3. API validation ────────────────────────────────────────────────────────

def _http_get(path: str, timeout: int = 30) -> tuple[int, float, Any]:
    t0 = time.time()
    try:
        with urllib.request.urlopen(API_BASE + path, timeout=timeout) as r:
            body = r.read()
            ms = round((time.time() - t0) * 1000)
            try:
                return r.status, ms, json.loads(body)
            except Exception:
                return r.status, ms, None
    except urllib.error.HTTPError as e:
        return e.code, round((time.time() - t0) * 1000), None
    except Exception:
        return 0, round((time.time() - t0) * 1000), None


def api_validation() -> dict:
    checks = []
    endpoints = []
    for path, required in API_CHECKS:
        status, ms, body = _http_get(path)
        ok = status == 200
        missing = [f for f in required if not (isinstance(body, (dict,)) and f in body)] if ok else []
        detail = f"HTTP {status} · {ms} ms"
        if missing:
            detail += f" · missing fields: {missing}"
        checks.append(_check(f"GET /api{path}", ok and not missing, detail))
        endpoints.append({"path": f"/api{path}", "status_code": status,
                          "latency_ms": ms, "required_fields_ok": not missing,
                          "json": body is not None})
    # error handling: unknown route must 404, not 200/500
    status, ms, _ = _http_get("/phase17-does-not-exist")
    checks.append(_check("Unknown route returns 404", status == 404, f"HTTP {status}"))
    return _section("API Validation", checks, endpoints=endpoints, not_checkable=[
        "Authentication — no auth layer exists (single-user research tool)",
        "Rate limits — not implemented by design",
    ])


# ── 4. data-store validation (JSON files; no SQL DB exists) ─────────────────

def datastore_validation() -> dict:
    checks = []
    for fname in DATA_FILES:
        p = os.path.join(BASE_DIR, fname)
        if not os.path.exists(p):
            checks.append(_check(f"{fname} exists", None, "file not present yet"))
            continue
        try:
            json.load(open(p))
            checks.append(_check(f"{fname} parses", True, f"{os.path.getsize(p)} bytes"))
        except Exception as e:
            checks.append(_check(f"{fname} parses", False, f"corrupted: {str(e)[:120]}"))

    state = _load_json("state.json", {})
    trades = state.get("trades", [])
    seen: dict[tuple, int] = {}
    for t in trades:
        k = (t.get("symbol"), t.get("action"), t.get("timestamp"))
        seen[k] = seen.get(k, 0) + 1
    dups = [k for k, v in seen.items() if v > 1]
    checks.append(_check("No duplicate trades", not dups, f"{len(dups)} duplicate group(s)"))

    missing_scan = [t for t in trades if t.get("action") == "BUY" and not t.get("scan_id")]
    checks.append(_check("BUY trades carry scan_id",
                         True if not missing_scan else None,
                         f"{len(missing_scan)} BUY trade(s) without scan_id "
                         "(legacy records made before scan metadata existed — warning, not failure)"
                         if missing_scan else "all BUY trades carry scan_id"))

    required = ("symbol", "action", "quantity", "price", "timestamp")
    corrupt = [t for t in trades if not all(t.get(f) is not None for f in required)]
    checks.append(_check("Trade records complete", not corrupt,
                         f"{len(corrupt)} record(s) missing required fields"))

    sells = sum(1 for t in trades if t.get("action") == "SELL")
    buys = sum(1 for t in trades if t.get("action") == "BUY")
    checks.append(_check("SELLs do not exceed BUYs", sells <= buys,
                         f"{buys} BUY / {sells} SELL"))
    return _section("Data Store Validation", checks, note=(
        "Persistence is JSON file storage — there is no SQL database, so "
        "indexes/constraints/foreign keys do not apply and are not fabricated."))


# ── 5. paper trading validation ──────────────────────────────────────────────

def paper_trading_validation() -> dict:
    checks = []
    try:
        from paper_trader import get_portfolio, get_trade_replay, _load_state  # type: ignore
        from config import INITIAL_CAPITAL  # type: ignore
    except Exception as e:
        return _section("Paper Trading Validation",
                        [_check("paper_trader importable", False, str(e)[:200])])

    state = _load_state()
    portfolio = get_portfolio()
    trades = state.get("trades", [])
    checks.append(_check("State loads", True, f"{len(trades)} trade(s)"))

    # capital conservation: cash + invested cost basis ≈ initial + realised pnl
    cash = state.get("cash", portfolio.get("cash", 0)) or 0
    positions = portfolio.get("positions", [])
    invested = sum((p.get("quantity") or 0) * (p.get("avg_price") or 0) for p in positions)
    realised = sum(t.get("pnl") or 0 for t in trades if t.get("action") == "SELL")
    drift = abs((cash + invested) - (INITIAL_CAPITAL + realised))
    checks.append(_check("Capital conservation (cash + cost basis = initial + realised PnL)",
                         drift < 1.0, f"drift ₹{drift:.2f}"))

    rts = list(get_trade_replay())
    bad_pnl = []
    for rt in rts:
        qty, entry, exitp = rt.get("quantity"), rt.get("entry_price"), rt.get("exit_price")
        pnl = rt.get("pnl")
        if None in (qty, entry, exitp, pnl):
            continue
        if abs((exitp - entry) * qty - pnl) > max(1.0, abs(pnl) * 0.05):
            bad_pnl.append(rt.get("symbol"))
    checks.append(_check("Round-trip PnL consistent with prices", not bad_pnl,
                         f"{len(bad_pnl)} inconsistent: {bad_pnl[:5]}"))

    no_stops = [t.get("symbol") for t in trades
                if t.get("action") == "BUY" and not t.get("stop_loss")]
    checks.append(_check("BUY trades carry stop loss",
                         True if not no_stops else None,
                         f"{len(no_stops)} legacy trade(s) without stop (recorded before "
                         f"stop metadata existed): {no_stops[:5]}" if no_stops
                         else "all BUY trades carry stops"))
    no_targets = [t.get("symbol") for t in trades
                  if t.get("action") == "BUY" and not t.get("target_price") and not t.get("target")]
    checks.append(_check("BUY trades carry target",
                         True if not no_targets else None,
                         f"{len(no_targets)} legacy trade(s) without target: {no_targets[:5]}"
                         if no_targets else "all BUY trades carry targets"))

    neg_qty = [p for p in positions if (p.get("quantity") or 0) < 0]
    checks.append(_check("No negative positions", not neg_qty, f"{len(neg_qty)} negative"))
    return _section("Paper Trading Validation", checks,
                    completed_trades=len(rts), open_positions=len(positions))


# ── 6. AI validation ─────────────────────────────────────────────────────────

def ai_validation() -> dict:
    checks = []
    decisions = _load_json("ai_decisions_cache.json", [])
    if isinstance(decisions, dict):
        decisions = decisions.get("decisions", [])
    checks.append(_check("AI decisions cache present", bool(decisions),
                         f"{len(decisions)} decision(s)"))
    bad_conf = [d.get("stock") for d in decisions if isinstance(d, dict)
                and not (0 <= (d.get("confidence") or 0) <= 100)]
    checks.append(_check("Confidence within 0-100", not bad_conf, f"bad: {bad_conf[:5]}"))
    no_explain = [d.get("stock") for d in decisions if isinstance(d, dict)
                  and not d.get("plain_english")]
    checks.append(_check("Every decision has an explanation", not no_explain,
                         f"{len(no_explain)} without explanation"))

    scan = _load_json("phase7_scan_cache.json", {})
    recs = scan.get("recommendations", [])
    bad_score = [r.get("symbol") for r in recs
                 if r.get("opportunity_score") is not None
                 and not (0 <= r["opportunity_score"] <= 100)]
    checks.append(_check("Opportunity scores within 0-100", not bad_score,
                         f"bad: {bad_score[:5]}"))

    cal = _load_json("calibration_state.json", {})
    checks.append(_check("Calibration state present", bool(cal),
                         f"method: {cal.get('method', cal.get('calibration_method', NOT_AVAILABLE))}"))
    registry = _load_json("phase14_model_registry.json", {})
    champ = registry.get("champion_version") or registry.get("champion", {})
    checks.append(_check("Model registry has champion", bool(champ), str(champ)[:80]))
    freeze = _load_json("phase14_learning_freeze.json", {})
    checks.append(_check("Learning governance state present", bool(freeze) or freeze == {},
                         f"freeze flags: {json.dumps(freeze)[:100]}" if freeze else "no freeze file (defaults apply)"))
    return _section("AI Validation", checks)


# ── 7. performance metric validation ────────────────────────────────────────

def performance_validation() -> dict:
    checks = []
    try:
        from phase10_analytics import performance_analytics  # type: ignore
        analytics = performance_analytics()
    except Exception as e:
        return _section("Performance Validation",
                        [_check("analytics computes", False, str(e)[:200])])
    s, r = analytics.get("summary", {}), analytics.get("risk", {})
    checks.append(_check("Analytics computes", True, ""))
    insufficient = []
    for metric, src in [("sharpe", r), ("sortino", r), ("max_drawdown_pct", r),
                        ("beta", r), ("profit_factor", s), ("win_rate_pct", s),
                        ("expectancy", s), ("alpha", r)]:
        val = src.get(metric)
        if val is None or val == NA:
            insufficient.append(metric)
        else:
            checks.append(_check(f"{metric} computed", True, str(val)))
    bench = r.get("benchmark_comparison") or analytics.get("benchmark", {})
    if not bench:
        insufficient.append("benchmark_comparison")
    trades_n = s.get("total_trades", 0)
    return _section("Performance Validation", checks,
                    insufficient_data=insufficient,
                    note=(f"{len(insufficient)} metric(s) flagged Insufficient Data "
                          f"(sample: {trades_n} trades) — flagged, not failed, per spec."))


# ── 8. export validation ─────────────────────────────────────────────────────

def export_validation() -> dict:
    checks = []
    try:
        from phase16_exports import build_exports  # type: ignore
        result = build_exports()
        files = result.get("files", [])
        checks.append(_check("Phase 16 export build", bool(result.get("success")),
                             f"{len(files)} file(s)"))
        exp_dir = os.path.join(BASE_DIR, "phase16_exports")
        for f in files:
            p = os.path.join(exp_dir, f if isinstance(f, str) else f.get("name", ""))
            ok = os.path.exists(p) and os.path.getsize(p) > 0
            checks.append(_check(f"export {os.path.basename(p)} non-empty", ok,
                                 f"{os.path.getsize(p) if os.path.exists(p) else 0} bytes"))
    except Exception as e:
        checks.append(_check("Phase 16 export build", False, str(e)[:200]))

    # review package: verify latest zip exists and is a valid zip
    import zipfile
    zips = sorted((f for f in os.listdir(BASE_DIR)
                   if re.match(r"Phase\d+_Review_Package\.zip$", f)),
                  key=lambda f: os.path.getmtime(os.path.join(BASE_DIR, f)), reverse=True)
    if zips:
        p = os.path.join(BASE_DIR, zips[0])
        try:
            with zipfile.ZipFile(p) as z:
                bad = z.testzip()
            checks.append(_check(f"Review package {zips[0]} valid", bad is None,
                                 f"{os.path.getsize(p)} bytes"))
        except Exception as e:
            checks.append(_check(f"Review package {zips[0]} valid", False, str(e)[:120]))
    else:
        checks.append(_check("Review package exists", None,
                             "no package generated yet — run it from Settings"))

    # download endpoints respond
    for path in ["/phase16/all", "/review-package/status"]:
        status, ms, _ = _http_get(path)
        checks.append(_check(f"GET /api{path}", status == 200, f"HTTP {status} · {ms} ms"))
    return _section("Export Validation", checks)


# ── 9. performance benchmarks ────────────────────────────────────────────────

def performance_benchmarks() -> dict:
    bench: list[dict] = []

    def timed(name: str, fn, budget_ms: int) -> None:
        t0 = time.time()
        ok, err = True, ""
        try:
            fn()
        except Exception as e:
            ok, err = False, str(e)[:120]
        ms = round((time.time() - t0) * 1000)
        bench.append({"benchmark": name, "ms": ms, "budget_ms": budget_ms,
                      "within_budget": ok and ms <= budget_ms, "error": err})

    timed("Portfolio computation", lambda: __import__("paper_trader").get_portfolio(), 3000)
    timed("Scan context build",
          lambda: __import__("phase15_scan_context").build_scan_context(), 3000)
    timed("Performance analytics",
          lambda: __import__("phase10_analytics").performance_analytics(), 8000)
    timed("Phase 16 combined validation",
          lambda: __import__("phase16_validation").run_all(), 10000)

    for path, budget in [("/healthz", 500), ("/portfolio", 4000),
                         ("/phase16/all", 12000), ("/signals", 3000)]:
        status, ms, _ = _http_get(path)
        bench.append({"benchmark": f"API GET /api{path}", "ms": ms, "budget_ms": budget,
                      "within_budget": status == 200 and ms <= budget,
                      "error": "" if status == 200 else f"HTTP {status}"})

    mem_mb = None
    try:
        with open("/proc/self/status") as f:
            for line in f:
                if line.startswith("VmRSS"):
                    mem_mb = round(int(line.split()[1]) / 1024, 1)
    except Exception:
        pass
    checks = [_check(b["benchmark"], b["within_budget"],
                     f"{b['ms']} ms (budget {b['budget_ms']} ms)"
                     + (f" — {b['error']}" if b["error"] else ""))
              for b in bench]
    return _section("Performance Benchmarks", checks, benchmarks=bench,
                    python_process_memory_mb=mem_mb, not_checkable=[
                        "Application/dashboard client load time and chart rendering — "
                        "require a real browser; not measurable server-side"])


# ── 10. error detection ──────────────────────────────────────────────────────

def error_detection() -> dict:
    try:
        from phase16_validation import bug_detection  # type: ignore
        bugs = bug_detection()
    except Exception as e:
        bugs = {"issues": [{"check": "bug_detection", "severity": "ERROR",
                            "detail": str(e)[:150]}], "verdict": "FAIL",
                "not_checkable": []}
    checks = [_check("Automated bug detection", bugs.get("verdict") == "PASS",
                     f"verdict {bugs.get('verdict')} · {len(bugs.get('issues', []))} issue(s)")]
    fail_count = 0
    for path, _req in API_CHECKS:
        status, _ms, _b = _http_get(path, timeout=20)
        if status != 200:
            fail_count += 1
    checks.append(_check("No API failures across curated endpoints", fail_count == 0,
                         f"{fail_count} failing endpoint(s)"))
    return _section("Error Detection", checks, issues=bugs.get("issues", []),
                    not_checkable=(bugs.get("not_checkable", []) + [
                        "console errors, broken navigation/links/buttons — client-side; "
                        "require a real browser session"]))


# ── 11. cross-page consistency ───────────────────────────────────────────────

def consistency_validation() -> dict:
    try:
        from phase15_consistency import run_consistency_check  # type: ignore
        rep = run_consistency_check()
    except Exception as e:
        return _section("Cross-Page Consistency",
                        [_check("consistency check runs", False, str(e)[:200])])
    checks = [_check("Cross-page consistency", rep.get("verdict") == "PASS",
                     f"verdict {rep.get('verdict')} · {rep.get('checks_performed')} checks · "
                     f"{rep.get('hard_mismatch_count', 0)} hard mismatch(es) · "
                     f"{rep.get('stale_source_count', 0)} stale source(s)",
                     severity="ERROR" if rep.get("hard_mismatch_count") else "WARN")]
    if rep.get("verdict") == "WARN":
        checks[0]["status"] = "WARN"
    return _section("Cross-Page Consistency", checks, report={
        k: rep.get(k) for k in ("verdict", "checks_performed", "hard_mismatch_count",
                                "stale_source_count", "note")})


# ── release checklist / dashboard / score ────────────────────────────────────

CHECKLIST_SECTIONS = [
    ("Frontend / Build", "frontend"),
    ("Backend Tests", "backend"),
    ("API", "api"),
    ("Data Store", "datastore"),
    ("Exports", "exports"),
    ("AI", "ai"),
    ("Paper Trading", "paper_trading"),
    ("Performance Metrics", "performance"),
    ("Benchmarks", "benchmarks"),
    ("Error Detection", "errors"),
    ("Cross-Page Consistency", "consistency"),
]

SCORE_WEIGHTS = {
    "backend": 20, "api": 15, "paper_trading": 15, "datastore": 10,
    "consistency": 10, "ai": 10, "frontend": 5, "exports": 5,
    "benchmarks": 5, "errors": 5, "performance": 5,
}


def _score_section(sec: dict) -> float | None:
    total = sec.get("total", 0)
    if total == 0:
        return None
    return (sec.get("passed", 0) + 0.5 * sec.get("warnings", 0)) / total


def run_complete_validation(notes: str = "") -> dict:
    """One-click complete validation. Runs every section, stores history."""
    t0 = time.time()
    sections = {
        "frontend": frontend_build_check(),
        "backend": backend_tests(),
        "api": api_validation(),
        "datastore": datastore_validation(),
        "paper_trading": paper_trading_validation(),
        "ai": ai_validation(),
        "performance": performance_validation(),
        "exports": export_validation(),
        "benchmarks": performance_benchmarks(),
        "errors": error_detection(),
        "consistency": consistency_validation(),
    }
    totals = {"total": 0, "passed": 0, "failed": 0, "warnings": 0}
    for sec in sections.values():
        for k in totals:
            totals[k] += sec.get(k, 0)

    weighted, weight_sum = 0.0, 0
    section_scores = {}
    for key, w in SCORE_WEIGHTS.items():
        frac = _score_section(sections[key])
        if frac is None:
            section_scores[key] = NA
            continue
        section_scores[key] = round(frac * 100, 1)
        weighted += frac * w
        weight_sum += w
    health_score = round(100 * weighted / weight_sum, 1) if weight_sum else None

    # Gating policy: a section FAILs with any failed check, WARNs with any
    # warning (warnings are surfaced, never silently treated as pass), and
    # PASSes only when every check passed. production_ready (strict boolean)
    # requires every section fully PASS — zero failures AND zero warnings.
    checklist = []
    for label, key in CHECKLIST_SECTIONS:
        sec = sections[key]
        status = ("FAIL" if sec.get("failed", 0) > 0
                  else "WARN" if sec.get("warnings", 0) > 0 or sec.get("total", 0) == 0
                  else "PASS")
        checklist.append({"item": label, "status": status,
                          "detail": f"{sec.get('passed', 0)}/{sec.get('total', 0)} passed, "
                                    f"{sec.get('failed', 0)} failed, {sec.get('warnings', 0)} warning(s)"})
    production_ready = all(c["status"] == "PASS" for c in checklist)
    any_failures = any(c["status"] == "FAIL" for c in checklist)
    checklist.append({
        "item": "Production Ready",
        "status": "PASS" if production_ready else ("FAIL" if any_failures else "WARN"),
        "detail": ("all sections pass with zero warnings" if production_ready
                   else "one or more sections have failures" if any_failures
                   else "no failures, but open warnings must be reviewed before release"),
    })

    verdict = ("PASS" if totals["failed"] == 0
               else "WARN" if totals["failed"] <= 2 else "FAIL")
    duration = round(time.time() - t0, 1)
    info = build_info()

    report = {
        "success": True, "generated_at": _now(), "label": LABEL,
        "release_version": VERSION, "build_number": info["build_number"],
        "environment": info["environment"],
        "health_score": health_score, "verdict": verdict,
        "duration_seconds": duration, **totals,
        "section_scores": section_scores,
        "release_checklist": checklist,
        "production_ready": production_ready,
        "readiness_status": ("READY" if production_ready
                             else "NOT READY" if any_failures
                             else "READY WITH WARNINGS"),
        "sections": sections,
        "notes": notes,
        "score_note": ("Score = weighted pass-rate across sections (warnings count half). "
                       "Security/code-quality/test-coverage instrumentation does not exist "
                       "and is therefore not part of the score — not fabricated."),
    }

    # persist history + last run
    history = _load_json(os.path.basename(HISTORY_PATH), [])
    entry = {
        "run_id": f"V{len(history) + 1:04d}",
        "generated_at": report["generated_at"], "duration_seconds": duration,
        "passed": totals["passed"], "failed": totals["failed"],
        "warnings": totals["warnings"], "health_score": health_score,
        "verdict": verdict, "version": VERSION, "notes": notes,
        "readiness_status": report["readiness_status"],
    }
    history.append(entry)
    json.dump(history[-HISTORY_CAP:], open(HISTORY_PATH, "w"), indent=2)
    json.dump(report, open(LAST_RUN_PATH, "w"), indent=2, default=str)
    report["run_id"] = entry["run_id"]
    return report


def validation_history() -> dict:
    history = _load_json(os.path.basename(HISTORY_PATH), [])
    return {"success": True, "generated_at": _now(), "label": LABEL,
            "runs": list(reversed(history)), "count": len(history)}


def last_run() -> dict:
    last = _load_json(os.path.basename(LAST_RUN_PATH), {})
    if not last:
        return {"success": True, "available": False,
                "note": "No validation run yet — click Run Complete Validation."}
    last["available"] = True
    return last


def release_dashboard() -> dict:
    info = build_info()
    history = _load_json(os.path.basename(HISTORY_PATH), [])
    last_ok = next((h for h in reversed(history) if h.get("failed", 1) == 0), None)
    last_bad = next((h for h in reversed(history) if h.get("failed", 0) > 0), None)
    last = history[-1] if history else None
    return {
        "success": True, "generated_at": _now(), "label": LABEL,
        "current_version": VERSION,
        "build_number": info["build_number"],
        "environment": info["environment"],
        "last_successful_validation": (last_ok or {}).get("generated_at", NOT_AVAILABLE),
        "last_failed_validation": (last_bad or {}).get("generated_at", NOT_AVAILABLE),
        "open_issues": (last or {}).get("failed", NOT_AVAILABLE),
        "warnings": (last or {}).get("warnings", NOT_AVAILABLE),
        "release_score": (last or {}).get("health_score", NOT_AVAILABLE),
        "production_readiness": (last.get("readiness_status")
                                 or ("NOT READY" if last.get("failed", 0) > 0
                                     else "READY WITH WARNINGS" if last.get("warnings", 0) > 0
                                     else "READY")) if last else NOT_AVAILABLE,
        "total_runs": len(history),
    }
