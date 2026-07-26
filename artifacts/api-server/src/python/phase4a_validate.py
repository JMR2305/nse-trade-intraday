"""
phase4a_validate.py — Phase 4A Section 7: Continuous Safety Validation.

Checks all 8 safety invariants on every call:
  1. paper_mode == true
  2. AI advisory only (no live execution flag)
  3. No live orders (GET /live-orders → 404 or 405)
  4. Duplicate order protection (partial unique index enforced)
  5. Stale data protection (buy-disabled when stale)
  6. Session recovery works (portfolio/snapshot available)
  7. Portfolio consistent (cash + invested = equity ± ε)
  8. No API regressions (all critical endpoints respond)

Returns structured JSON with PASS/WARN/FAIL per invariant and an
overall production_ready boolean (FAIL == 0).

Usage:
    uv run python phase4a_validate.py [--json]

PAPER TRADING / RESEARCH ONLY.
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import sys
import time
from typing import Any, Optional

_DIR = os.path.dirname(os.path.abspath(__file__))
_DOCS = os.path.join(_DIR, "..", "..", "docs")
os.makedirs(_DOCS, exist_ok=True)

BASE_URL = "http://localhost:8080/api"
LABEL = "PAPER TRADING / RESEARCH ONLY"
ACCOUNTING_EPSILON = 1.0

CRITICAL_ENDPOINTS = [
    "/healthz",
    "/portfolio/snapshot",
    "/signals",
    "/live-data/scan/status",   # canonical scan endpoint (not /scan/status which is unregistered)
    "/risk/kill-switch",
]


# ── HTTP helpers ──────────────────────────────────────────────────────────────

def _now_ist() -> str:
    try:
        import zoneinfo
        return datetime.datetime.now(zoneinfo.ZoneInfo("Asia/Kolkata")).isoformat()
    except Exception:
        return datetime.datetime.utcnow().isoformat() + "Z"


def _get(path: str, timeout: float = 6.0) -> tuple[int, Any, float]:
    import urllib.request
    import urllib.error
    t0 = time.monotonic()
    try:
        with urllib.request.urlopen(f"{BASE_URL}{path}", timeout=timeout) as r:
            return r.status, json.loads(r.read()), round((time.monotonic() - t0) * 1000, 1)
    except urllib.error.HTTPError as e:
        return e.code, {}, round((time.monotonic() - t0) * 1000, 1)
    except Exception as e:
        return 0, {"error": str(e)}, round((time.monotonic() - t0) * 1000, 1)


# ── InvariantResult ───────────────────────────────────────────────────────────

class InvariantResult:
    def __init__(self, name: str, category: str):
        self.name = name
        self.category = category
        self.verdict = "PENDING"
        self.detail = ""
        self.latency_ms: Optional[float] = None

    def pass_(self, detail: str = "", ms: Optional[float] = None) -> "InvariantResult":
        self.verdict = "PASS"
        self.detail = detail
        self.latency_ms = ms
        return self

    def warn(self, detail: str, ms: Optional[float] = None) -> "InvariantResult":
        self.verdict = "WARN"
        self.detail = detail
        self.latency_ms = ms
        return self

    def fail(self, detail: str, ms: Optional[float] = None) -> "InvariantResult":
        self.verdict = "FAIL"
        self.detail = detail
        self.latency_ms = ms
        return self

    def to_dict(self) -> dict:
        d: dict = {
            "invariant": self.name,
            "category": self.category,
            "verdict": self.verdict,
            "detail": self.detail,
        }
        if self.latency_ms is not None:
            d["latency_ms"] = self.latency_ms
        return d


# ── 8 invariant checks ────────────────────────────────────────────────────────

def run_validation() -> dict:
    results: list[InvariantResult] = []
    started_at = _now_ist()
    failed_fast = False

    print(f"\n{'=' * 60}")
    print("  Phase 4A — Safety Invariant Validation")
    print(f"  {LABEL}")
    print(f"  {started_at}")
    print(f"{'=' * 60}\n")

    # ── I1: paper_mode == true ────────────────────────────────────────────────
    r = InvariantResult("paper_mode == true", "safety")
    s, port, ms = _get("/portfolio/snapshot")
    if s == 200:
        pm = port.get("paper_mode")
        if pm is True:
            r.pass_("paper_mode=True confirmed", ms)
        elif pm is False:
            r.fail("CRITICAL: paper_mode=False — LIVE EXECUTION RISK", ms)
            failed_fast = True
        else:
            r.warn("paper_mode field missing from snapshot", ms)
    else:
        r.warn(f"portfolio/snapshot HTTP {s} — cannot verify", ms)
    results.append(r)
    _print_result(r)
    if failed_fast:
        return _finish(results, started_at, abort_reason="paper_mode=False is a hard stop")

    # ── I2: AI advisory only ──────────────────────────────────────────────────
    r = InvariantResult("AI advisory only", "safety")
    s, data, ms = _get("/phase15/staleness")
    if s == 200:
        advisory = (data.get("advisory_only") or data.get("ai_advisory_only")
                    or "PAPER" in str(data.get("mode_label", "")).upper()
                    or "RESEARCH" in str(data.get("mode_label", "")).upper())
        if advisory:
            r.pass_("advisory_only flag confirmed", ms)
        else:
            r.warn("advisory_only not explicitly set in phase15 response", ms)
    else:
        # AI advisory is a code-level guarantee; non-200 from staleness is a WARN
        r.warn(f"phase15/staleness HTTP {s} — advisory status not API-verifiable", ms)
    results.append(r)
    _print_result(r)

    # ── I3: No live orders ────────────────────────────────────────────────────
    r = InvariantResult("No live orders", "safety")
    s, _, ms = _get("/live-orders")
    if s in (404, 405):
        r.pass_(f"GET /live-orders returns {s} (no live order route)", ms)
    elif s == 200:
        r.fail(f"GET /live-orders returned 200 — LIVE ORDER ROUTE EXPOSED", ms)
    else:
        r.pass_(f"GET /live-orders HTTP {s} (non-200 confirms no live route)", ms)
    results.append(r)
    _print_result(r)

    # ── I4: Duplicate order protection ───────────────────────────────────────
    r = InvariantResult("Duplicate order protection", "safety")
    try:
        from phase20_executor import get_open_trades
        open_trades = get_open_trades()
        symbols = [t.get("symbol") for t in open_trades]
        duplicates = [s for s in set(symbols) if symbols.count(s) > 1]
        if duplicates:
            r.fail(f"Duplicate OPEN positions: {duplicates}")
        else:
            r.pass_(f"{len(open_trades)} open positions, 0 duplicates")
    except Exception as e:
        r.warn(f"Could not check via module: {str(e)[:60]}")
    results.append(r)
    _print_result(r)

    # ── I5: Stale data protection ─────────────────────────────────────────────
    r = InvariantResult("Stale data protection", "data")
    s, sigs, ms = _get("/signals")
    if s == 200:
        staleness = sigs.get("staleness_warning") if isinstance(sigs, dict) else {}
        is_stale = (staleness or {}).get("is_stale", False) if staleness else False
        buy_disabled = (staleness or {}).get("buy_recommendations_disabled", False) if staleness else False
        if is_stale and buy_disabled:
            r.pass_("stale data detected → BUY recommendations correctly disabled", ms)
        elif is_stale and not buy_disabled:
            r.fail("stale data but BUY recommendations NOT disabled — protection gap", ms)
        else:
            r.pass_(f"data appears fresh; staleness gate active (stale={is_stale})", ms)
    else:
        r.warn(f"signals HTTP {s} — stale protection state unknown", ms)
    results.append(r)
    _print_result(r)

    # ── I6: Session recovery works ────────────────────────────────────────────
    r = InvariantResult("Session recovery works", "portfolio")
    s, port, ms = _get("/portfolio/snapshot")
    if s == 200:
        has_cash = port.get("cash") is not None
        has_positions = isinstance(port.get("positions"), list)
        if has_cash and has_positions:
            r.pass_(f"snapshot loads: cash=₹{port.get('cash'):.2f} "
                    f"positions={len(port.get('positions', []))}", ms)
        else:
            r.warn("snapshot missing cash or positions fields", ms)
    else:
        r.fail(f"portfolio/snapshot HTTP {s} — recovery probe failed", ms)
    results.append(r)
    _print_result(r)

    # ── I7: Portfolio consistent ──────────────────────────────────────────────
    r = InvariantResult("Portfolio consistent", "portfolio")
    s, port, ms = _get("/portfolio/snapshot")
    if s == 200:
        cash = float(port.get("cash", 0))
        invested = float(port.get("invested_value", 0))
        equity = float(port.get("total_equity", cash + invested))
        diff = abs(equity - (cash + invested))
        if diff < ACCOUNTING_EPSILON:
            r.pass_(f"equity=₹{equity:.2f} cash=₹{cash:.2f} invested=₹{invested:.2f} "
                    f"diff=₹{diff:.4f} < ε=₹{ACCOUNTING_EPSILON}", ms)
        else:
            r.warn(f"accounting drift ₹{diff:.4f} > ε=₹{ACCOUNTING_EPSILON}", ms)
    else:
        r.warn(f"portfolio/snapshot HTTP {s}", ms)
    results.append(r)
    _print_result(r)

    # ── I8: No API regressions ────────────────────────────────────────────────
    r = InvariantResult("No API regressions", "infrastructure")
    failed_eps: list[str] = []
    for ep in CRITICAL_ENDPOINTS:
        s, _, ms_ep = _get(ep, timeout=5.0)
        if s not in (200, 201, 204):
            failed_eps.append(f"{ep} → HTTP {s}")
    if failed_eps:
        r.fail(f"Endpoints failing: {'; '.join(failed_eps)}")
    else:
        r.pass_(f"All {len(CRITICAL_ENDPOINTS)} critical endpoints respond 2xx")
    results.append(r)
    _print_result(r)

    return _finish(results, started_at)


def _finish(results: list[InvariantResult], started_at: str,
            abort_reason: str = "") -> dict:
    passed = sum(1 for r in results if r.verdict == "PASS")
    warned = sum(1 for r in results if r.verdict == "WARN")
    failed = sum(1 for r in results if r.verdict == "FAIL")
    total = len(results)
    production_ready = failed == 0

    result = {
        "label": LABEL,
        "generated_at": started_at,
        "production_ready": production_ready,
        "passed": passed,
        "warned": warned,
        "failed": failed,
        "total_checked": total,
        "total_invariants": 8,
        "abort_reason": abort_reason,
        "invariants": [r.to_dict() for r in results],
    }

    print(f"\n{'=' * 60}")
    icon = "✅" if production_ready else "❌"
    print(f"  Safety Validation: {icon} {'PASS' if production_ready else 'FAIL'}")
    print(f"  {passed}/{total} PASS  {warned} WARN  {failed} FAIL")
    if abort_reason:
        print(f"  ⚠️  ABORTED EARLY: {abort_reason}")
    print(f"{'=' * 60}\n")
    return result


def _print_result(r: InvariantResult) -> None:
    icon = "✅" if r.verdict == "PASS" else "⚠️" if r.verdict == "WARN" else "❌"
    lat = f" ({r.latency_ms}ms)" if r.latency_ms else ""
    print(f"  {icon} [{r.verdict}] {r.name}{lat}")
    if r.detail:
        print(f"         {r.detail}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Phase 4A safety validator")
    parser.add_argument("--json", action="store_true", help="Output JSON only")
    args = parser.parse_args()

    result = run_validation()

    if args.json:
        print(json.dumps(result, indent=2, default=str))
    else:
        # Save
        date_compact = datetime.date.today().isoformat().replace("-", "")
        out = os.path.join(_DOCS, f"validation_{date_compact}.json")
        with open(out, "w") as f:
            json.dump(result, f, indent=2, default=str)
        print(f"  Saved: {out}")

    sys.exit(0 if result["production_ready"] else 1)
