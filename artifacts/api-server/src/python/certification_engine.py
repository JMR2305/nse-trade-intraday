"""
Phase 23.8B — Automated Certification Engine + Long-Duration Validation
(spec Parts M, P).

Aggregates the six validation engines (validation_engines.py) plus learning
engine + mission-control integrity checks into a weighted certification
report with per-domain PASS/WARN/FAIL verdicts, an overall certification
percentage, and a strict READY / NOT READY verdict for continuous paper
trading. Warnings are NEVER treated as pass.

Certification runs are persisted APPEND-ONLY (certification_runs table with
file fallback). Every execution INSERTS a new row — there is no update path
for a completed certification, so history stays auditable.

Long-duration validation scores stability / reliability / consistency /
confidence over configurable 1-week…1-year windows from the paper ledger and
the pipeline event store; windows with insufficient history report
INSUFFICIENT_EVIDENCE instead of extrapolating.

STRICTLY READ-ONLY over the canonical stores (except the dedicated
append-only certification_runs table). PAPER TRADING / RESEARCH ONLY.
"""
from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import validation_engines as ve
from scan_state_store import _connect, db_available

PASS, WARN, FAIL = ve.PASS, ve.WARN, ve.FAIL
INSUFFICIENT = ve.INSUFFICIENT
MIN_EVIDENCE = ve.MIN_EVIDENCE

ADVISORY = ("Automated certification — read-only aggregation of the "
            "validation engines. PAPER TRADING / RESEARCH ONLY.")

# Weighted domains (spec Part M). Portfolio balance carries the most weight;
# learning/mission-control are integrity spot checks.
DOMAIN_WEIGHTS: Dict[str, float] = {
    "data": 0.15,
    "pipeline": 0.15,
    "portfolio": 0.20,
    "replay": 0.15,
    "ai_decision": 0.15,
    "performance": 0.10,
    "learning": 0.05,
    "mission_control": 0.05,
}
# WARN scores half credit; it still blocks READY (warnings never pass).
_STATUS_SCORE = {PASS: 1.0, WARN: 0.5, FAIL: 0.0, INSUFFICIENT: 0.0}

_DIR = os.path.dirname(os.path.abspath(__file__))
_CERT_FILE = os.path.join(_DIR, "certification_runs.json")
_SCHEMA_READY = False


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


# ── Append-only store (Postgres + file fallback) ─────────────────────────────

def _ensure_schema(conn) -> None:
    global _SCHEMA_READY
    if _SCHEMA_READY:
        return
    with conn.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS certification_runs (
                cert_id TEXT PRIMARY KEY,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                certification_pct DOUBLE PRECISION NOT NULL,
                verdict TEXT NOT NULL,
                report JSONB NOT NULL DEFAULT '{}'::jsonb
            )
            """
        )
        cur.execute("CREATE INDEX IF NOT EXISTS idx_cert_runs_created"
                    " ON certification_runs (created_at DESC)")
    conn.commit()
    _SCHEMA_READY = True


def _load_file(path: str) -> List[Dict[str, Any]]:
    try:
        with open(path, "r") as f:
            return json.load(f)
    except Exception:
        return []


def _append_file(path: str, row: Dict[str, Any]) -> None:
    rows = _load_file(path)
    rows.append(row)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(rows, f, default=str)
    os.replace(tmp, path)


def _insert_cert(row: Dict[str, Any]) -> None:
    if db_available():
        try:
            conn = _connect()
            try:
                _ensure_schema(conn)
                with conn.cursor() as cur:
                    cur.execute(
                        "INSERT INTO certification_runs "
                        "(cert_id, created_at, certification_pct, verdict, "
                        "report) VALUES (%s, %s, %s, %s, %s)",
                        (row["cert_id"], row["created_at"],
                         row["certification_pct"], row["verdict"],
                         json.dumps(row, default=str)))
                conn.commit()
                return
            finally:
                conn.close()
        except Exception:
            pass
    _append_file(_CERT_FILE, row)


def list_certifications(limit: int = 50) -> Dict[str, Any]:
    rows: List[Dict[str, Any]] = []
    if db_available():
        try:
            conn = _connect()
            try:
                _ensure_schema(conn)
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT report FROM certification_runs "
                        "ORDER BY created_at DESC LIMIT %s", (limit,))
                    for (report,) in cur.fetchall():
                        rows.append(report if isinstance(report, dict)
                                    else json.loads(report))
            finally:
                conn.close()
        except Exception:
            rows = []
    if not rows:
        rows = sorted(_load_file(_CERT_FILE),
                      key=lambda r: str(r.get("created_at") or ""),
                      reverse=True)[:limit]
    items = [{"cert_id": r.get("cert_id"),
              "created_at": r.get("created_at"),
              "certification_pct": r.get("certification_pct"),
              "verdict": r.get("verdict"),
              "domains": {d: (v or {}).get("verdict")
                          for d, v in (r.get("domains") or {}).items()}}
             for r in rows]
    return {"ok": True, "items": items, "note": ADVISORY}


def get_certification(cert_id: str) -> Dict[str, Any]:
    if db_available():
        try:
            conn = _connect()
            try:
                _ensure_schema(conn)
                with conn.cursor() as cur:
                    cur.execute("SELECT report FROM certification_runs "
                                "WHERE cert_id = %s", (cert_id,))
                    hit = cur.fetchone()
                    if hit:
                        report = hit[0]
                        return report if isinstance(report, dict) \
                            else json.loads(report)
            finally:
                conn.close()
        except Exception:
            pass
    for r in _load_file(_CERT_FILE):
        if r.get("cert_id") == cert_id:
            return r
    return {"ok": False, "error": f"Unknown certification {cert_id}"}


# ── Integrity spot checks (learning engine + mission control) ────────────────

def check_learning_engine() -> Dict[str, Any]:
    """Learning must be advisory-only: nothing may auto-apply."""
    checks: List[Dict[str, Any]] = []
    try:
        import phase24_engine as p24  # noqa: F401
        auto = bool(getattr(p24, "AUTO_APPLY_ENABLED", False))
        checks.append(ve._check(
            "learning_advisory_only", PASS if not auto else FAIL,
            f"phase24 AUTO_APPLY_ENABLED={auto} — learning may recommend, "
            "never apply"))
    except Exception:
        checks.append(ve._check("learning_advisory_only", PASS,
                                "phase24 learning module not importable — "
                                "nothing can auto-apply"))
    return ve._result("learning", checks)


def check_mission_control(snapshot: Optional[Dict[str, Any]] = None
                          ) -> Dict[str, Any]:
    """Mission-control integrity: the canonical scan snapshot the dashboards
    hang off must exist and self-identify (scan_id + snapshot_ts)."""
    checks: List[Dict[str, Any]] = []
    if snapshot is None:
        try:
            from scan_state_store import load_latest_snapshot
            snapshot = load_latest_snapshot() or {}
        except Exception as exc:
            checks.append(ve._check("canonical_snapshot_readable", FAIL,
                                    f"snapshot store unreadable: {exc}"))
            return ve._result("mission_control", checks)
    if not snapshot:
        checks.append(ve._check("canonical_snapshot_present", INSUFFICIENT,
                                "no canonical scan snapshot yet — run a "
                                "scan first"))
        return ve._result("mission_control", checks, verdict=INSUFFICIENT)
    sid = snapshot.get("scan_id")
    ts = snapshot.get("snapshot_ts") or snapshot.get("as_of")
    checks.append(ve._check(
        "snapshot_identity", PASS if sid and ts else FAIL,
        f"scan_id={sid or 'MISSING'}, snapshot_ts={ts or 'MISSING'} — "
        "every dashboard value must trace to one scan"))
    return ve._result("mission_control", checks, scan_id=sid,
                      snapshot_ts=ts)


# ── Certification aggregation (spec Part M) ──────────────────────────────────

def run_certification(config: Optional[Dict[str, Any]] = None,
                      validator_results: Optional[Dict[str, Dict[str, Any]]]
                      = None, persist: bool = True) -> Dict[str, Any]:
    """Run all validators, aggregate into a weighted certification score and
    a strict READY verdict, and persist the run append-only."""
    cfg = config or {}
    results: Dict[str, Dict[str, Any]] = {}
    if validator_results is not None:
        results = dict(validator_results)
    else:
        run_id = cfg.get("run_id")
        for name, fn in (("data", lambda: ve.validate_data()),
                         ("pipeline", lambda: ve.validate_pipeline(
                             run_id=run_id)),
                         ("portfolio", lambda: ve.validate_portfolio()),
                         ("replay", lambda: ve.validate_replay(
                             run_id=run_id)),
                         ("ai_decision", lambda: ve.validate_ai_decisions(
                             run_id=run_id)),
                         ("performance", lambda: ve.validate_performance(
                             source=str(cfg.get("source") or "paper")))):
            try:
                results[name] = fn()
            except Exception as exc:
                results[name] = {"ok": False, "domain": name,
                                 "verdict": FAIL,
                                 "checks": [ve._check("validator_error",
                                                      FAIL, str(exc))]}
        try:
            results["learning"] = check_learning_engine()
        except Exception as exc:
            results["learning"] = {"domain": "learning", "verdict": FAIL,
                                   "checks": [ve._check("validator_error",
                                                        FAIL, str(exc))]}
        try:
            results["mission_control"] = check_mission_control()
        except Exception as exc:
            results["mission_control"] = {
                "domain": "mission_control", "verdict": FAIL,
                "checks": [ve._check("validator_error", FAIL, str(exc))]}

    domains: Dict[str, Dict[str, Any]] = {}
    weighted = 0.0
    weight_total = 0.0
    blockers: List[str] = []
    for domain, weight in DOMAIN_WEIGHTS.items():
        r = results.get(domain) or {"verdict": INSUFFICIENT, "checks": []}
        verdict = str(r.get("verdict") or INSUFFICIENT)
        score = _STATUS_SCORE.get(verdict, 0.0)
        weighted += weight * score
        weight_total += weight
        checks = r.get("checks") or []
        domains[domain] = {
            "verdict": verdict,
            "weight": weight,
            "score_pct": round(score * 100.0, 1),
            "checks_total": len(checks),
            "checks_failed": sum(1 for c in checks
                                 if c.get("status") == FAIL),
            "checks_warned": sum(1 for c in checks
                                 if c.get("status") == WARN),
            "detail": r,
        }
        if verdict != PASS:
            blockers.append(f"{domain}: {verdict}")

    certification_pct = round(weighted / weight_total * 100.0, 1) \
        if weight_total else 0.0
    # STRICT: READY only when EVERY domain is PASS. WARN and
    # INSUFFICIENT_EVIDENCE both block readiness — warnings never pass.
    ready = all(d["verdict"] == PASS for d in domains.values())
    report = {
        "ok": True,
        "cert_id": f"CERT-{uuid.uuid4().hex[:12]}",
        "created_at": _now_iso(),
        "certification_pct": certification_pct,
        "verdict": "READY" if ready else "NOT_READY",
        "ready_for_continuous_paper_trading": ready,
        "blockers": blockers,
        "domains": domains,
        "policy": ("READY requires every domain to PASS. WARN is never "
                   "treated as PASS; INSUFFICIENT_EVIDENCE never "
                   "extrapolates to PASS."),
        "note": ADVISORY,
    }
    if persist:
        try:
            _insert_cert(report)
        except Exception:
            pass  # certification result is still returned; persistence is
            #       best-effort and never blocks the read path
    return report


# ── Long-duration validation (spec Part P) ───────────────────────────────────

WINDOWS: Dict[str, int] = {"1w": 7, "2w": 14, "1m": 30, "3m": 90,
                           "6m": 180, "1y": 365}


def _ts(row: Dict[str, Any], *keys: str) -> Optional[datetime]:
    for k in keys:
        dt = ve._parse_ts(row.get(k))
        if dt:
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    return None


def long_duration_validation(window: str = "1m",
                             ledger_rows: Optional[List[Dict[str, Any]]]
                             = None,
                             scan_events: Optional[List[Dict[str, Any]]]
                             = None,
                             now: Optional[datetime] = None
                             ) -> Dict[str, Any]:
    """Stability / reliability / consistency / confidence scores over a
    1-week…1-year window from the paper ledger + event store."""
    if window not in WINDOWS:
        return {"ok": False,
                "error": f"Unknown window '{window}' — "
                         f"use one of {sorted(WINDOWS)}"}
    days = WINDOWS[window]
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=days)

    if ledger_rows is None:
        import phase20_executor as p20
        ledger_rows = p20.get_ledger(limit=10_000)
    if scan_events is None:
        try:
            from pipeline_events import query_events
            raw = query_events(mode="LIVE", stage="SCANNER",
                               limit=2000, newest_first=True)
            scan_events = [e for e in raw
                           if (ve._parse_ts(e.get("ts")) or now) >= cutoff]
        except Exception:
            scan_events = []

    closed = [r for r in ledger_rows if r.get("status") == "CLOSED"]
    in_window = [r for r in closed
                 if (_ts(r, "exit_ts", "updated_at") or now) >= cutoff]
    all_ts = [t for t in (_ts(r, "fill_ts", "created_at")
                          for r in ledger_rows) if t]
    history_days = (now - min(all_ts)).days if all_ts else 0

    base = {"ok": True, "window": window, "window_days": days,
            "history_days": history_days,
            "trades_in_window": len(in_window),
            "generated_at": _now_iso(), "note": ADVISORY}

    # never extrapolate: require both enough trades AND enough history
    if len(in_window) < MIN_EVIDENCE or history_days < days * 0.8:
        return {**base, "verdict": INSUFFICIENT,
                "recommendation": INSUFFICIENT,
                "reason": (f"{len(in_window)} closed trades in window "
                           f"(need ≥{MIN_EVIDENCE}) and {history_days} days "
                           f"of ledger history (need ≥{round(days * 0.8)}) — "
                           "refusing to extrapolate"),
                "scores": None}

    in_window.sort(key=lambda r: str(r.get("exit_ts") or ""))
    pnls = [float(r.get("realized_pnl") or 0.0) for r in in_window]

    # stability: drawdown of the cumulative realized-PnL curve vs capital
    try:
        from portfolio_store import INITIAL_CAPITAL as _CAP
    except Exception:
        _CAP = 50_000.0
    equity = []
    run_total = 0.0
    for p in pnls:
        run_total += p
        equity.append(_CAP + run_total)
    peak = equity[0]
    max_dd_pct = 0.0
    for v in equity:
        peak = max(peak, v)
        if peak > 0:
            max_dd_pct = max(max_dd_pct, (peak - v) / peak * 100.0)
    stability = round(max(0.0, 100.0 - max_dd_pct * 5.0), 1)

    # reliability: scan completion rate from the event store (None when the
    # window has no scan telemetry — reported, never invented)
    completed = sum(1 for e in scan_events
                    if e.get("event_type") == "SCAN_COMPLETED")
    failed = sum(1 for e in scan_events
                 if e.get("event_type") == "SCAN_FAILED")
    reliability = (round(completed / (completed + failed) * 100.0, 1)
                   if (completed + failed) > 0 else None)

    # consistency: win-rate spread across sequential quarters of the window
    seg_n = min(4, max(2, len(in_window) // MIN_EVIDENCE))
    seg_size = max(1, len(in_window) // seg_n)
    seg_rates = []
    for i in range(0, len(in_window), seg_size):
        seg = pnls[i:i + seg_size]
        if seg:
            seg_rates.append(sum(1 for p in seg if p > 0) / len(seg) * 100.0)
    spread = (max(seg_rates) - min(seg_rates)) if len(seg_rates) > 1 else 0.0
    consistency = round(max(0.0, 100.0 - spread), 1)

    # confidence: calibration error between stated confidence and outcomes
    conf_rows = [(float(r.get("confidence")),
                  1.0 if float(r.get("realized_pnl") or 0) > 0 else 0.0)
                 for r in in_window if r.get("confidence") is not None]
    if len(conf_rows) >= MIN_EVIDENCE:
        err = sum(abs(c - o * 100.0) for c, o in conf_rows) / len(conf_rows)
        confidence = round(max(0.0, 100.0 - err), 1)
    else:
        confidence = None

    scores = {"stability": stability, "reliability": reliability,
              "consistency": consistency, "confidence": confidence}
    known = [v for v in scores.values() if v is not None]
    overall = round(sum(known) / len(known), 1) if known else 0.0
    if overall >= 70.0:
        rec = "CONTINUE_PAPER_TRADING"
    elif overall >= 50.0:
        rec = "MONITOR_CLOSELY"
    else:
        rec = "REVIEW_REQUIRED"
    return {**base, "verdict": PASS if overall >= 70.0 else WARN,
            "scores": scores, "overall_score": overall,
            "max_drawdown_pct": round(max_dd_pct, 2),
            "scan_events": {"completed": completed, "failed": failed},
            "recommendation": rec}
