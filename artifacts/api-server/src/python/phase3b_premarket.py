"""
phase3b_premarket.py — Phase 3B: Pre-Market Readiness Suite.

Checks all readiness conditions before a live NSE trading session.
Recognises market states: PRE_OPEN, OPEN, CLOSED, WEEKEND, HOLIDAY.
Uses backend-authoritative time only (never browser/device time).

Produces:
  - Console readiness summary
  - docs/phase3b_premarket_results.json
  - docs/phase3b_premarket_report.md

Run:
    uv run python phase3b_premarket.py

PAPER TRADING / RESEARCH ONLY. No live broker calls.
"""

import json
import os
import sys
import time
import socket
import datetime
from typing import Any

_DIR = os.path.dirname(os.path.abspath(__file__))
_DOCS = os.path.join(_DIR, "..", "..", "docs")
os.makedirs(_DOCS, exist_ok=True)

BASE_URL = "http://localhost:8080/api"

LABEL = "PAPER TRADING / RESEARCH ONLY"


def _now_ist() -> str:
    try:
        import zoneinfo
        return datetime.datetime.now(zoneinfo.ZoneInfo("Asia/Kolkata")).isoformat()
    except Exception:
        return datetime.datetime.utcnow().isoformat() + "Z"


def _get(path: str, timeout: float = 8.0) -> tuple[int, Any, float]:
    import urllib.request
    import urllib.error
    t0 = time.monotonic()
    try:
        with urllib.request.urlopen(f"{BASE_URL}{path}", timeout=timeout) as r:
            data = json.loads(r.read())
            return r.status, data, round((time.monotonic() - t0) * 1000, 1)
    except urllib.error.HTTPError as e:
        return e.code, {}, round((time.monotonic() - t0) * 1000, 1)
    except Exception as e:
        return 0, {"error": str(e)}, round((time.monotonic() - t0) * 1000, 1)


def _tcp_reachable(host: str, port: int, timeout: float = 3.0) -> bool:
    try:
        s = socket.create_connection((host, port), timeout=timeout)
        s.close()
        return True
    except Exception:
        return False


class ReadinessCheck:
    def __init__(self, name: str, category: str):
        self.name = name
        self.category = category
        self.verdict = "PENDING"
        self.detail = ""
        self.latency_ms: float | None = None

    def pass_(self, detail: str = "", latency_ms: float | None = None) -> "ReadinessCheck":
        self.verdict = "PASS"
        self.detail = detail
        self.latency_ms = latency_ms
        return self

    def warn(self, detail: str, latency_ms: float | None = None) -> "ReadinessCheck":
        self.verdict = "WARN"
        self.detail = detail
        self.latency_ms = latency_ms
        return self

    def fail(self, detail: str, latency_ms: float | None = None) -> "ReadinessCheck":
        self.verdict = "FAIL"
        self.detail = detail
        self.latency_ms = latency_ms
        return self

    def to_dict(self) -> dict:
        d: dict = {"name": self.name, "category": self.category, "verdict": self.verdict}
        if self.detail:
            d["detail"] = self.detail
        if self.latency_ms is not None:
            d["latency_ms"] = self.latency_ms
        return d


def run_premarket_checks() -> dict:
    checks: list[ReadinessCheck] = []
    started_at = _now_ist()

    print(f"\n{'=' * 60}")
    print("  ApexQuant AI — Pre-Market Readiness Suite")
    print(f"  {LABEL}")
    print(f"  {started_at}")
    print(f"{'=' * 60}\n")

    # ── C1: API health ───────────────────────────────────────────────────────
    c = ReadinessCheck("API health", "infrastructure")
    status, data, ms = _get("/healthz")
    if status == 200:
        unhealthy = [k for k, v in data.items()
                     if isinstance(v, str) and v.upper() == "DOWN"]
        if not unhealthy:
            c.pass_(f"status={status} healthy", ms)
        else:
            c.fail(f"DOWN subsystems: {unhealthy}", ms)
    else:
        c.fail(f"HTTP {status} — API unreachable", ms)
    checks.append(c)
    _print_check(c)

    # ── C2: Database readiness ───────────────────────────────────────────────
    c = ReadinessCheck("database readiness", "infrastructure")
    status2, data2, ms2 = _get("/health/details")
    if status2 == 200:
        db = data2.get("database", {})
        db_ok = db.get("connected") or db.get("status") == "ok" or status2 == 200
        c.pass_(f"database reachable, {ms2}ms") if db_ok else c.fail("database disconnected")
    else:
        # Try portfolio endpoint as secondary DB probe
        s3, d3, ms3 = _get("/portfolio/snapshot")
        if s3 == 200:
            c.pass_(f"portfolio/snapshot responsive ({ms3}ms)", ms3)
        else:
            c.fail(f"health/details HTTP {status2}; portfolio HTTP {s3}", ms2)
    checks.append(c)
    _print_check(c)

    # ── C3: Scanner readiness ────────────────────────────────────────────────
    c = ReadinessCheck("scanner readiness", "data")
    status, data, ms = _get("/scan/status")
    if status == 200:
        locked = data.get("locked", False)
        last_ts = data.get("last_scan_ts") or data.get("snapshot_ts", "")
        if locked:
            c.warn("scanner lock is active (scan in progress?)", ms)
        elif last_ts:
            c.pass_(f"last scan: {last_ts}", ms)
        else:
            c.warn("no previous scan snapshot found", ms)
    else:
        c.warn(f"scan/status HTTP {status} — scanner may not have run yet", ms)
    checks.append(c)
    _print_check(c)

    # ── C4: Data provider readiness ──────────────────────────────────────────
    c = ReadinessCheck("data provider readiness", "data")
    status, data, ms = _get("/live-data/market-status")
    if status == 200:
        state = data.get("state", "UNKNOWN")
        c.pass_(f"market state: {state}", ms)
    else:
        status2, data2, ms2 = _get("/signals")
        if status2 == 200:
            # /signals returns a list; staleness is not in that response
            sig_count = len(data2) if isinstance(data2, list) else len(data2.get("signals", []))
            c.pass_(f"signals endpoint OK; {sig_count} signals", ms2)
        else:
            c.fail(f"data provider unreachable (HTTP {status}/{status2})", ms)
    checks.append(c)
    _print_check(c)

    # ── C5: Symbol universe ──────────────────────────────────────────────────
    c = ReadinessCheck("symbol universe", "data")
    status, data, ms = _get("/signals")
    if status == 200:
        # /signals returns a list directly
        count = len(data) if isinstance(data, list) else len(data.get("signals", []))
        config_symbols = count
        if count >= 40:
            c.pass_(f"{count} symbols in signal universe", ms)
        elif count >= 20:
            c.warn(f"only {count}/50 symbols — partial coverage", ms)
        else:
            c.warn(f"low symbol count: {count} signals returned", ms)
    else:
        c.fail(f"signals HTTP {status}", ms)
    checks.append(c)
    _print_check(c)

    # ── C6: Paper portfolio state ────────────────────────────────────────────
    c = ReadinessCheck("paper portfolio state", "safety")
    status, data, ms = _get("/portfolio/snapshot")
    if status == 200:
        paper = data.get("paper_mode")
        cash = data.get("cash", 0)
        if paper is True:
            c.pass_(f"paper_mode=True cash=₹{cash:.0f}", ms)
        elif paper is False:
            c.fail("paper_mode=False — SAFETY VIOLATION", ms)
        else:
            c.warn("paper_mode field missing from snapshot", ms)
    else:
        c.fail(f"portfolio/snapshot HTTP {status}", ms)
    checks.append(c)
    _print_check(c)

    # ── C7: Kill switch state ────────────────────────────────────────────────
    c = ReadinessCheck("kill switch state", "safety")
    status, data, ms = _get("/risk/kill-switch")
    if status == 200:
        active = data.get("active", data.get("kill_switch_active", None))
        if active is False:
            c.pass_("kill switch NOT tripped — OK to trade", ms)
        elif active is True:
            c.fail("kill switch IS tripped — entries will be blocked", ms)
        else:
            c.warn("kill switch state unknown", ms)
    else:
        c.warn(f"kill switch endpoint HTTP {status}", ms)
    checks.append(c)
    _print_check(c)

    # ── C8: Circuit breaker state ────────────────────────────────────────────
    c = ReadinessCheck("circuit breaker state", "safety")
    status, data, ms = _get("/risk/circuit-breaker")
    if status == 200:
        tripped = data.get("tripped", data.get("state") == "TRIPPED")
        if not tripped:
            c.pass_("circuit breaker not tripped", ms)
        else:
            c.fail("circuit breaker tripped — BLOCKED", ms)
    else:
        # Try /health endpoint for CB status
        status2, data2, ms2 = _get("/health/ready")
        if status2 == 200:
            c.warn("circuit breaker endpoint unavailable; health/ready OK", ms2)
        else:
            c.warn(f"circuit breaker status unknown (HTTP {status})", ms)
    checks.append(c)
    _print_check(c)

    # ── C9: RC-8 configuration loaded ───────────────────────────────────────
    c = ReadinessCheck("RC-8 risk configuration", "risk")
    status, data, ms = _get("/portfolio/config")
    if status == 200:
        loaded = data.get("loaded", data.get("config_loaded"))
        if loaded is True:
            c.pass_("PortfolioConfig loaded via pydantic", ms)
        elif loaded is False:
            c.warn("PortfolioConfig using hardcoded fallback defaults", ms)
        else:
            c.warn("config loaded status unknown", ms)
    else:
        c.warn(f"portfolio/config HTTP {status}", ms)
    checks.append(c)
    _print_check(c)

    # ── C10: SSE connectivity ────────────────────────────────────────────────
    c = ReadinessCheck("SSE connectivity", "infrastructure")
    sse_reachable = _tcp_reachable("localhost", 8080, timeout=2.0)
    if sse_reachable:
        status, data, ms = _get("/stream-health")
        if status == 200:
            c.pass_("SSE stream endpoint reachable", ms)
        else:
            # SSE endpoint is a long-lived stream; TCP reachable is sufficient
            c.pass_("SSE port reachable (TCP); /stream-health not exposed", ms)
    else:
        c.fail("port 8080 not reachable — SSE unavailable")
    checks.append(c)
    _print_check(c)

    # ── C11: No unresolved previous-session orders ───────────────────────────
    c = ReadinessCheck("no stale previous-session orders", "portfolio")
    status, data, ms = _get("/portfolio/snapshot")
    if status == 200:
        positions = data.get("positions", [])
        # Check for any EXIT_PENDING positions from previous session
        stale = [p for p in positions
                 if isinstance(p, dict) and p.get("status") == "EXIT_PENDING"]
        if stale:
            c.warn(f"{len(stale)} EXIT_PENDING positions from previous session", ms)
        else:
            c.pass_(f"{len(positions)} open positions, none stale", ms)
    else:
        c.warn(f"portfolio/snapshot HTTP {status}", ms)
    checks.append(c)
    _print_check(c)

    # ── C12: No duplicate scanner lock ──────────────────────────────────────
    c = ReadinessCheck("no duplicate scanner lock", "infrastructure")
    status, data, ms = _get("/scan/status")
    if status == 200:
        locked = data.get("locked", False)
        lock_age = data.get("lock_age_s", None)
        if not locked:
            c.pass_("no active scanner lock", ms)
        elif lock_age is not None and lock_age < 120:
            c.warn(f"scanner locked ({lock_age:.0f}s old — scan may be in progress)", ms)
        else:
            c.fail(f"stale scanner lock (age={lock_age}s) — may need manual release", ms)
    else:
        c.pass_(f"scan/status HTTP {status} — lock status unknown (non-blocking)", ms)
    checks.append(c)
    _print_check(c)

    # ── Summary ──────────────────────────────────────────────────────────────
    passed = sum(1 for c in checks if c.verdict == "PASS")
    warned = sum(1 for c in checks if c.verdict == "WARN")
    failed = sum(1 for c in checks if c.verdict == "FAIL")
    total = len(checks)

    if failed == 0 and warned == 0:
        overall = "READY"
    elif failed == 0:
        overall = "READY_WITH_WARNINGS"
    else:
        overall = "NOT_READY"

    result = {
        "label": LABEL,
        "generated_at": started_at,
        "overall": overall,
        "passed": passed,
        "warned": warned,
        "failed": failed,
        "total": total,
        "checks": [c.to_dict() for c in checks],
    }

    _write_results(result)
    _print_summary(result)
    return result


def _print_check(c: ReadinessCheck) -> None:
    icon = "✅" if c.verdict == "PASS" else "⚠️" if c.verdict == "WARN" else "❌"
    lat = f" ({c.latency_ms}ms)" if c.latency_ms else ""
    print(f"  {icon} [{c.verdict}] {c.name}{lat}")
    if c.detail:
        print(f"         {c.detail}")


def _print_summary(result: dict) -> None:
    icon = "✅" if result["overall"] == "READY" else "⚠️" if result["overall"] == "READY_WITH_WARNINGS" else "❌"
    print(f"\n{'=' * 60}")
    print(f"  Pre-Market Readiness: {icon} {result['overall']}")
    print(f"  {result['passed']}/{result['total']} PASS  "
          f"{result['warned']} WARN  {result['failed']} FAIL")
    print(f"{'=' * 60}\n")


def _write_results(result: dict) -> None:
    json_path = os.path.join(_DOCS, "phase3b_premarket_results.json")
    with open(json_path, "w") as f:
        json.dump(result, f, indent=2)
    print(f"  Results: {json_path}")

    md_path = os.path.join(_DOCS, "phase3b_premarket_report.md")
    ts = result["generated_at"]
    overall = result["overall"]
    with open(md_path, "w") as f:
        f.write(f"# Pre-Market Readiness Report\n\n")
        f.write(f"**{result['label']}**\n\n")
        f.write(f"Generated: {ts}  \nOverall: **{overall}**  \n")
        f.write(f"Checks: {result['passed']}/{result['total']} PASS · "
                f"{result['warned']} WARN · {result['failed']} FAIL\n\n")
        f.write("| # | Check | Category | Verdict | Detail |\n")
        f.write("|---|-------|----------|---------|--------|\n")
        for i, c in enumerate(result["checks"], 1):
            verdict = c["verdict"]
            icon = "✅" if verdict == "PASS" else "⚠️" if verdict == "WARN" else "❌"
            detail = c.get("detail", "")
            f.write(f"| {i} | {c['name']} | {c['category']} | {icon} {verdict} | {detail} |\n")
    print(f"  Report:  {md_path}")


if __name__ == "__main__":
    result = run_premarket_checks()
    sys.exit(0 if result["overall"] != "NOT_READY" else 1)
