"""
phase26_reports.py — Phase 26D: Reports & Readiness Dashboard (backend).

Presentation/aggregation ONLY — this module never recalculates anything.
It assembles operator-facing reports from the PERSISTED outputs of the
Phase 26 validation engines and the certification engine:

* Daily Validation Report — one report per IST trading day covering
  System / Trading / AI / Portfolio / Execution / Replay / Learning health,
  plus a Validation Score, the Certification Score, outstanding issues and
  rule-based recommendations. Generated automatically post-close by the
  Phase 20 scheduler (idempotent per day), persisted APPEND-ONLY.
* Five-Day Acceptance Tracker — rolling window over the last 5 consecutive
  NSE trading days (IST calendar incl. holidays): a day passes only when its
  daily report shows zero open CRITICAL issues and zero failing health
  sections. Overall verdict: PASS / PENDING / FAIL.
* Final Production Readiness Report — on-demand document combining the
  five-day result, the latest certification run, the latest performance
  grades and outstanding issues into a single strict verdict
  (READY / PENDING / NOT_READY). Exportable through the Phase 23.9 export
  engine ("readiness" report).

Data sources (all persisted, read-only):
  phase26_store (26A e2e runs) · phase26_live_store (26B snapshots + issue
  store) · phase26c_store (26C recovery/performance/quality results) ·
  certification_engine (append-only certification_runs).

PAPER TRADING / RESEARCH ONLY.
"""
from __future__ import annotations

import fcntl
import json
import os
import uuid
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

ADVISORY = ("Phase 26D reports — read-only aggregation of persisted "
            "validation results. PAPER TRADING / RESEARCH ONLY.")

IST = timezone(timedelta(hours=5, minutes=30))

_DIR = os.path.dirname(os.path.abspath(__file__))
REPORTS_FILE = os.path.join(_DIR, "phase26_daily_reports.json")
_FILE_CAP = 400          # hard cap on the local-dev fallback file

# Retention (mirrors the phase26c_store on-write prune pattern): delete
# reports older than RETENTION_DAYS but always keep the newest
# RETENTION_MIN_KEEP rows regardless of age, so latest_daily_report(),
# the five-day acceptance tracker (needs only the last ~5 trading days)
# and recent history are never affected.
RETENTION_DAYS = 90
RETENTION_MIN_KEEP = 30

PASS, WARN, FAIL = "PASS", "WARN", "FAIL"
INSUFFICIENT = "INSUFFICIENT_EVIDENCE"

# Sections of the daily report and where each verdict comes from.
SECTIONS = ("system", "trading", "ai", "portfolio", "execution",
            "replay", "learning")

_SCHEMA_READY = False


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Append-only daily-report store (Postgres + flock file fallback) ──────────

def db_available() -> bool:
    return bool(os.environ.get("DATABASE_URL"))


def _connect():
    import psycopg2
    return psycopg2.connect(os.environ["DATABASE_URL"], connect_timeout=10)


def _ensure_schema(conn) -> None:
    global _SCHEMA_READY
    if _SCHEMA_READY:
        return
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS phase26_daily_reports (
                report_id   TEXT PRIMARY KEY,
                report_date DATE NOT NULL,
                created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
                verdict     TEXT,
                report      JSONB NOT NULL
            )
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_p26d_date_created
            ON phase26_daily_reports (report_date DESC, created_at DESC)
        """)
    conn.commit()
    _SCHEMA_READY = True


def _with_db(fn, fallback):
    if not db_available():
        return fallback()
    conn = _connect()
    try:
        _ensure_schema(conn)
        out = fn(conn)
        conn.commit()
        return out
    finally:
        conn.close()


def _read_json(path: str, default):
    try:
        with open(path, "r") as f:
            return json.load(f)
    except Exception:
        return default


def _write_json(path: str, data) -> None:
    tmp = f"{path}.{os.getpid()}.{uuid.uuid4().hex[:6]}.tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, default=str)
    os.replace(tmp, path)


@contextmanager
def _file_lock(path: str):
    lock_path = path + ".lock"
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)


def append_daily_report(report: Dict[str, Any]) -> Dict[str, Any]:
    """Persist one daily report append-only (never overwrites). Multiple
    reports on the same date are allowed (manual re-runs); readers take the
    newest per date."""
    report = dict(report)
    report_id = str(report.get("report_id")
                    or f"dr-{uuid.uuid4().hex[:12]}")
    report["report_id"] = report_id
    record = {
        "report_id": report_id,
        "report_date": str(report.get("report_date") or ""),
        "created_at": report.get("generated_at") or _now_iso(),
        "verdict": report.get("verdict"),
        "report": report,
    }

    def in_db(conn):
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO phase26_daily_reports
                    (report_id, report_date, created_at, verdict, report)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (report_id) DO NOTHING
                """,
                (report_id, record["report_date"], record["created_at"],
                 str(record["verdict"]), json.dumps(report, default=str)))
        return record

    def in_file():
        with _file_lock(REPORTS_FILE):
            rows = _read_json(REPORTS_FILE, [])
            if not any(r.get("report_id") == report_id for r in rows):
                rows.append(record)
                rows = sorted(rows, key=lambda r: (
                    str(r.get("report_date") or ""),
                    str(r.get("created_at") or "")))[-_FILE_CAP:]
                _write_json(REPORTS_FILE, rows)
        return record

    stored = _with_db(in_db, in_file)
    # Retention: bound history after each write; fail-safe, never affects
    # the append result.
    prune_daily_reports()
    return stored


def prune_daily_reports(days: int = RETENTION_DAYS,
                        keep_min: int = RETENTION_MIN_KEEP
                        ) -> Dict[str, Any]:
    """Bounded retention for phase26_daily_reports (DB and file fallback).

    Deletes reports whose report_date is older than `days`, always keeping
    the newest `keep_min` rows regardless of age. NEVER raises — retention
    must not break report persistence. Returns
    {"deleted": n, "days": days, "keep_min": k}."""
    days = max(1, int(days))
    keep_min = max(1, int(keep_min))
    try:
        def in_db(conn):
            with conn.cursor() as cur:
                cur.execute(
                    """
                    DELETE FROM phase26_daily_reports
                    WHERE report_date <
                          (NOW() - (%s || ' days')::interval)::date
                      AND report_id NOT IN (
                          SELECT report_id FROM phase26_daily_reports
                          ORDER BY report_date DESC, created_at DESC
                          LIMIT %s
                      )
                    """,
                    (days, keep_min))
                deleted = cur.rowcount
            return {"deleted": deleted, "days": days, "keep_min": keep_min}

        def in_file():
            cutoff = (datetime.now(timezone.utc).astimezone(IST).date()
                      - timedelta(days=days)).isoformat()
            deleted = 0
            with _file_lock(REPORTS_FILE):
                rows = _read_json(REPORTS_FILE, [])
                ordered = sorted(rows, key=lambda r: (
                    str(r.get("report_date") or ""),
                    str(r.get("created_at") or "")), reverse=True)
                kept: List[Dict[str, Any]] = []
                for i, r in enumerate(ordered):
                    if i < keep_min or \
                            str(r.get("report_date") or "") >= cutoff:
                        kept.append(r)
                    else:
                        deleted += 1
                if deleted:
                    kept.sort(key=lambda r: (
                        str(r.get("report_date") or ""),
                        str(r.get("created_at") or "")))
                    _write_json(REPORTS_FILE, kept)
            return {"deleted": deleted, "days": days, "keep_min": keep_min}

        return _with_db(in_db, in_file)
    except Exception as exc:
        return {"deleted": 0, "days": days, "keep_min": keep_min,
                "error": str(exc)[:200]}


def get_daily_report(report_date: str) -> Optional[Dict[str, Any]]:
    """Newest persisted report for one IST calendar date (YYYY-MM-DD)."""
    report_date = str(report_date)

    def in_db(conn):
        with conn.cursor() as cur:
            cur.execute(
                "SELECT report FROM phase26_daily_reports "
                "WHERE report_date = %s "
                "ORDER BY created_at DESC LIMIT 1", (report_date,))
            row = cur.fetchone()
        return row[0] if row else None

    def in_file():
        rows = [r for r in _read_json(REPORTS_FILE, [])
                if str(r.get("report_date")) == report_date]
        if not rows:
            return None
        rows.sort(key=lambda r: str(r.get("created_at") or ""))
        return rows[-1].get("report")

    return _with_db(in_db, in_file)


def latest_daily_report() -> Optional[Dict[str, Any]]:
    def in_db(conn):
        with conn.cursor() as cur:
            cur.execute(
                "SELECT report FROM phase26_daily_reports "
                "ORDER BY report_date DESC, created_at DESC LIMIT 1")
            row = cur.fetchone()
        return row[0] if row else None

    def in_file():
        rows = _read_json(REPORTS_FILE, [])
        if not rows:
            return None
        rows.sort(key=lambda r: (str(r.get("report_date") or ""),
                                 str(r.get("created_at") or "")))
        return rows[-1].get("report")

    return _with_db(in_db, in_file)


def list_daily_reports(limit: int = 30) -> List[Dict[str, Any]]:
    """Newest-first summaries (one row per persisted report)."""
    limit = max(1, min(int(limit or 30), 200))

    def in_db(conn):
        with conn.cursor() as cur:
            cur.execute(
                "SELECT report_id, report_date, created_at, verdict, "
                "report->'acceptance' FROM phase26_daily_reports "
                "ORDER BY report_date DESC, created_at DESC LIMIT %s",
                (limit,))
            return [{"report_id": r[0], "report_date": str(r[1]),
                     "created_at": str(r[2]), "verdict": r[3],
                     "acceptance": r[4]} for r in cur.fetchall()]

    def in_file():
        rows = sorted(_read_json(REPORTS_FILE, []),
                      key=lambda r: (str(r.get("report_date") or ""),
                                     str(r.get("created_at") or "")),
                      reverse=True)[:limit]
        return [{"report_id": r.get("report_id"),
                 "report_date": r.get("report_date"),
                 "created_at": r.get("created_at"),
                 "verdict": r.get("verdict"),
                 "acceptance": (r.get("report") or {}).get("acceptance")}
                for r in rows]

    return _with_db(in_db, in_file)


# ── Verdict normalisation ────────────────────────────────────────────────────

def _norm_verdict(v: Any) -> str:
    """Map heterogeneous engine verdicts onto PASS/WARN/FAIL/INSUFFICIENT.
    Unknown or missing verdicts are INSUFFICIENT — never silently healthy."""
    s = str(v or "").upper()
    if not s:
        return INSUFFICIENT
    if any(t in s for t in ("FAIL", "DOWN", "CRITICAL", "ERROR",
                            "NOT_READY", "NOT_ACCEPTED")):
        return FAIL
    if any(t in s for t in ("INSUFFICIENT", "UNKNOWN", "PENDING",
                            "NO_DATA", "OFF_SESSION", "IDLE", "DISABLED")):
        return INSUFFICIENT
    if any(t in s for t in ("WARN", "DEGRADED", "STALE", "WATCH")):
        return WARN
    if any(t in s for t in ("PASS", "OK", "HEALTHY", "READY", "ACCEPTED",
                            "ACTIVE", "SUCCESS")):
        return PASS
    return INSUFFICIENT


_SCORE = {PASS: 100.0, WARN: 50.0, FAIL: 0.0}


def _same_ist_day(ts: Any, report_date: str) -> bool:
    """True only when `ts` parses and falls on the given IST calendar date.
    Missing/unparseable timestamps are NOT same-day — evidence without a
    provable timestamp can never count as fresh (fail-safe)."""
    if not ts:
        return False
    try:
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(IST).date().isoformat() == str(report_date)
    except Exception:
        return False


# ── Input collection (persisted stores only — no recalculation) ─────────────

def collect_daily_inputs() -> Dict[str, Any]:
    """Read the latest persisted outputs of every Phase 26 engine + the
    certification engine. Each source is independent and fail-soft: an
    unreadable store contributes None (reported as NO_DATA), it never takes
    the whole report down."""
    inputs: Dict[str, Any] = {}

    def _safe(name, fn):
        try:
            inputs[name] = fn()
        except Exception as exc:
            inputs[name] = None
            inputs.setdefault("collection_errors", {})[name] = str(exc)[:200]

    def _live():
        import phase26_live_store as ls
        return ls.latest_snapshot()

    def _issues():
        import phase26_live_store as ls
        return ls.list_issues(status="OPEN", limit=200)

    def _e2e():
        import phase26_store
        runs = phase26_store.list_runs(limit=1)
        return runs[0] if runs else None

    def _c(area):
        import phase26c_store
        return phase26c_store.latest_result(area)

    def _cert():
        import certification_engine as ce
        items = ce.list_certifications(limit=1).get("items") or []
        if not items:
            return None
        return ce.get_certification(str(items[0]["cert_id"]))

    _safe("live", _live)
    _safe("open_issues", _issues)
    _safe("e2e", _e2e)
    _safe("recovery", lambda: _c("RECOVERY"))
    _safe("performance", lambda: _c("PERFORMANCE"))
    _safe("quality", lambda: _c("QUALITY"))
    _safe("certification", _cert)
    return inputs


# ── Daily Validation Report ──────────────────────────────────────────────────

def _cert_domain(cert: Optional[Dict[str, Any]], domain: str
                 ) -> Optional[str]:
    if not cert:
        return None
    d = (cert.get("domains") or {}).get(domain) or {}
    return d.get("verdict")


def build_daily_report(inputs: Dict[str, Any],
                       report_date: Optional[str] = None,
                       now: Optional[datetime] = None) -> Dict[str, Any]:
    """Pure assembly of one Daily Validation Report from persisted inputs.
    No store access, no recalculation — fully testable with fixtures."""
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    report_date = str(report_date or now.astimezone(IST).date().isoformat())

    live = inputs.get("live") or None
    cert = inputs.get("certification") or None
    e2e = inputs.get("e2e") or None
    quality = inputs.get("quality") or None
    performance = inputs.get("performance") or None
    recovery = inputs.get("recovery") or None
    issues = list(inputs.get("open_issues") or [])

    # Section health — each traces to exactly one persisted source.
    raw: Dict[str, Dict[str, Any]] = {
        "system": {"verdict": (live or {}).get("verdict"),
                   "source": "phase26b_live_snapshot",
                   "detail": (live or {}).get("subsystem_counts"),
                   "as_of": (live or {}).get("generated_at")},
        "trading": {"verdict": (quality or {}).get("verdict"),
                    "source": "phase26c_quality",
                    "detail": {"scan_id": (quality or {}).get("scan_id")},
                    "as_of": (quality or {}).get("generated_at")},
        "ai": {"verdict": _cert_domain(cert, "ai_decision"),
               "source": "certification.ai_decision",
               "as_of": (cert or {}).get("created_at")},
        "portfolio": {"verdict": _cert_domain(cert, "portfolio"),
                      "source": "certification.portfolio",
                      "as_of": (cert or {}).get("created_at")},
        "execution": {"verdict": (e2e or {}).get("verdict"),
                      "source": "phase26a_e2e_run",
                      "detail": {"run_id": (e2e or {}).get("run_id"),
                                 "scan_id": (e2e or {}).get("scan_id")},
                      "as_of": (e2e or {}).get("created_at")},
        "replay": {"verdict": _cert_domain(cert, "replay"),
                   "source": "certification.replay",
                   "as_of": (cert or {}).get("created_at")},
        "learning": {"verdict": _cert_domain(cert, "learning"),
                     "source": "certification.learning",
                     "as_of": (cert or {}).get("created_at")},
    }
    sections: Dict[str, Dict[str, Any]] = {}
    for name in SECTIONS:
        s = raw[name]
        status = _norm_verdict(s.get("verdict"))
        fresh = _same_ist_day(s.get("as_of"), report_date)
        # Evidence from a different IST day (or without a provable
        # timestamp) can never count as today's validation evidence —
        # downgrade to INSUFFICIENT so it can't pass (or fail) today.
        if status != INSUFFICIENT and not fresh:
            sections[name] = {**s, "status": INSUFFICIENT, "stale": True,
                              "stale_verdict": status,
                              "stale_reason": ("evidence not from report "
                                               f"date {report_date} (IST)")}
        else:
            sections[name] = {**s, "status": status, "stale": False}

    # Validation score: mean over sections WITH evidence (INSUFFICIENT
    # sections are excluded from the average, never counted as pass).
    scored = [_SCORE[s["status"]] for s in sections.values()
              if s["status"] in _SCORE]
    validation_score = round(sum(scored) / len(scored), 1) if scored else None
    evaluated = len(scored)

    critical = [i for i in issues
                if str(i.get("severity")).upper() == "CRITICAL"]
    fails = [n for n, s in sections.items() if s["status"] == FAIL]
    warns = [n for n, s in sections.items() if s["status"] == WARN]
    no_data = [n for n, s in sections.items() if s["status"] == INSUFFICIENT]

    if fails or critical:
        verdict = FAIL
    elif warns or no_data:
        verdict = WARN
    else:
        verdict = PASS

    # Acceptance-day criterion (drives the five-day tracker): complete
    # same-day evidence for EVERY section, zero open CRITICAL issues and
    # zero failing health sections. WARN days still count — missing/stale
    # evidence, criticals and hard failures never do (fail-safe: unknown
    # is never healthy).
    evidence_complete = not no_data
    acceptance = {
        "passed": bool(evidence_complete and not fails and not critical),
        "evidence_complete": evidence_complete,
        "insufficient_sections": no_data,
        "critical_open_issues": len(critical),
        "failed_sections": fails,
        "criteria": ("same-day evidence for all sections, zero open "
                     "CRITICAL issues (pipeline/portfolio/replay/execution/"
                     "mission-control mismatches surface here) and zero "
                     "FAIL health sections"),
    }

    recommendations: List[str] = []
    for n in fails:
        recommendations.append(
            f"Investigate the {n} section FAIL "
            f"(source: {sections[n]['source']}) before the next session.")
    if critical:
        recommendations.append(
            f"Resolve {len(critical)} open CRITICAL issue(s) in the issue "
            "store — acceptance days cannot pass while they remain open.")
    for n in warns:
        recommendations.append(
            f"Review the {n} section WARN (source: "
            f"{sections[n]['source']}).")
    if no_data:
        recommendations.append(
            "No persisted evidence for: " + ", ".join(no_data) +
            " — run the corresponding validation engine(s).")
    if cert is None:
        recommendations.append(
            "No certification run recorded — trigger one from the "
            "Validation Dashboard so AI/portfolio/replay/learning health "
            "can be reported.")
    if not recommendations:
        recommendations.append("All monitored areas healthy — no action "
                               "required.")

    return {
        "ok": True,
        "kind": "daily_validation_report",
        "report_date": report_date,
        "generated_at": now.isoformat(),
        "verdict": verdict,
        "validation_score": validation_score,
        "sections_evaluated": evaluated,
        "sections": sections,
        "certification": None if not cert else {
            "cert_id": cert.get("cert_id"),
            "created_at": cert.get("created_at"),
            "certification_pct": cert.get("certification_pct"),
            "verdict": cert.get("verdict"),
            "blockers": cert.get("blockers") or [],
        },
        "recovery": None if not recovery else {
            "verdict": recovery.get("verdict"),
            "generated_at": recovery.get("generated_at")},
        "performance": None if not performance else {
            "verdict": performance.get("verdict"),
            "grade_counts": performance.get("grade_counts"),
            "generated_at": performance.get("generated_at")},
        "open_issues": {
            "total": len(issues),
            "critical": len(critical),
            "items": issues[:50],
        },
        "acceptance": acceptance,
        "recommendations": recommendations,
        "collection_errors": inputs.get("collection_errors") or {},
        "advisory_only": True,
        "note": ADVISORY,
    }


def run_daily_report(persist: bool = True,
                     inputs: Optional[Dict[str, Any]] = None,
                     report_date: Optional[str] = None,
                     generated_by: str = "manual") -> Dict[str, Any]:
    """Assemble (and by default persist) today's Daily Validation Report."""
    report = build_daily_report(inputs if inputs is not None
                                else collect_daily_inputs(),
                                report_date=report_date)
    report["generated_by"] = str(generated_by or "manual")
    if persist:
        record = append_daily_report(report)
        report["report_id"] = record["report_id"]
        report["persisted"] = True
    else:
        report["persisted"] = False
    return report


# ── Scheduler hook (idempotent per IST day) ──────────────────────────────────

def maybe_generate_daily_report(mstate: str) -> Optional[Dict[str, Any]]:
    """Post-close automatic generation, exactly once per IST trading day.

    Order matters: the report is BUILT first (read-only, cheap); the atomic
    KV claim is only taken immediately before persisting, so a build failure
    leaves the day unclaimed and the next tick retries. Never raises.
    """
    if str(mstate).upper() != "CLOSED":
        return None
    # Compute the target day up front so a failure is always recorded under
    # the day whose report we attempted — a tick that crosses midnight IST
    # must not stamp yesterday's failure onto today's error key.
    today_ist = datetime.now(IST).date().isoformat()
    try:
        import phase20_store as store
        if get_daily_report(today_ist) is not None:
            return None                      # already generated today
        report = build_daily_report(collect_daily_inputs(),
                                    report_date=today_ist)
        report["generated_by"] = "scheduler"
        claim_key = f"p26d_daily_report:{today_ist}"
        if not store.kv_claim_once(claim_key):
            return None                      # another process won the day
        try:
            record = append_daily_report(report)
        except Exception:
            # Persist failed AFTER claiming: release the claim so the next
            # tick retries — otherwise the day would be skipped forever.
            try:
                store.kv_release(claim_key)
            except Exception:
                pass
            raise
        _record_generation_error(today_ist, None)   # clear any prior error
        return {"generated": True, "report_date": today_ist,
                "report_id": record["report_id"],
                "verdict": report.get("verdict")}
    except Exception as exc:                 # never break the scheduler tick
        err = str(exc)[:200]
        try:
            _record_generation_error(today_ist, err)
        except Exception:
            pass
        return {"generated": False, "error": err}


def _gen_error_key(day: str) -> str:
    return f"p26d_daily_report_error:{day}"


def _record_generation_error(day: str, error: Optional[str]) -> None:
    """Persist (or clear, when error is None) the last automatic-generation
    failure for `day` in the phase20 KV store, so the status endpoint can
    surface it. Never raises."""
    try:
        import phase20_store as store
        if error is None:
            store.kv_set(_gen_error_key(day), None)
        else:
            store.kv_set(_gen_error_key(day),
                         {"error": error, "at": _now_iso()})
    except Exception:
        pass


def today_report_status(now: Optional[datetime] = None,
                        trading_day_fn=None) -> Dict[str, Any]:
    """Lightweight status of TODAY's daily-report generation for operators.

    status ∈:
      NOT_EXPECTED — today is not an NSE trading day (weekend/holiday)
      NOT_DUE      — trading day, but market has not closed yet (pre-15:30 IST)
      GENERATED    — today's report exists (mode: scheduler | manual)
      ERROR        — no report yet and the last automatic attempt failed
      PENDING      — no report yet; scheduler retries every tick post-close
    """
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    now_ist = now.astimezone(IST)
    today = now_ist.date().isoformat()
    is_td = trading_day_fn or _is_trading_day
    base = {"ok": True, "kind": "daily_report_status", "report_date": today,
            "checked_at": now.isoformat(), "note": ADVISORY}

    if not is_td(now_ist.date()):
        return {**base, "status": "NOT_EXPECTED",
                "detail": "not an NSE trading day (weekend/holiday) — "
                          "no daily report expected"}

    report = get_daily_report(today)
    if report is not None:
        mode = str(report.get("generated_by") or "").lower()
        if mode not in ("scheduler", "manual"):
            # Older reports lack generated_by — the KV day-claim exists only
            # for scheduler-generated reports.
            try:
                import phase20_store as store
                claimed = bool(store.kv_get(f"p26d_daily_report:{today}"))
            except Exception:
                claimed = False
            mode = "scheduler" if claimed else "manual"
        gen_at_ist = None
        try:
            dt = datetime.fromisoformat(
                str(report.get("generated_at")).replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            gen_at_ist = dt.astimezone(IST).strftime("%H:%M IST")
        except Exception:
            pass
        return {**base, "status": "GENERATED", "mode": mode,
                "report_id": report.get("report_id"),
                "verdict": report.get("verdict"),
                "generated_at": report.get("generated_at"),
                "generated_at_ist": gen_at_ist,
                "detail": (f"generated {gen_at_ist or 'today'} "
                           + ("automatically by the scheduler"
                              if mode == "scheduler" else "manually"))}

    if (now_ist.hour, now_ist.minute) < (15, 30):
        return {**base, "status": "NOT_DUE",
                "detail": "market not closed yet — the daily report is "
                          "generated automatically after 15:30 IST"}

    last_error = None
    try:
        import phase20_store as store
        last_error = store.kv_get(_gen_error_key(today))
    except Exception:
        pass
    if isinstance(last_error, dict) and last_error.get("error"):
        # Defensive freshness check: only surface an ERROR recorded TODAY
        # (IST). A stale entry from an earlier day (e.g. a midnight-crossing
        # tick under the old keying) must never mask today's real status.
        err_day = None
        try:
            err_dt = datetime.fromisoformat(
                str(last_error.get("at")).replace("Z", "+00:00"))
            if err_dt.tzinfo is None:
                err_dt = err_dt.replace(tzinfo=timezone.utc)
            err_day = err_dt.astimezone(IST).date().isoformat()
        except Exception:
            pass
        if err_day == today or err_day is None:
            return {**base, "status": "ERROR",
                    "error": last_error.get("error"),
                    "error_at": last_error.get("at"),
                    "detail": ("last automatic generation attempt failed: "
                               f"{last_error.get('error')} — the scheduler "
                               "retries every tick")}
        return {**base, "status": "PENDING",
                "stale_error": {"error": last_error.get("error"),
                                "at": last_error.get("at"),
                                "day": err_day},
                "detail": ("post-close, report not generated yet — the "
                           "scheduler retries every tick (a stale "
                           f"generation error from {err_day} was ignored)")}
    return {**base, "status": "PENDING",
            "detail": "post-close, report not generated yet — the "
                      "scheduler retries every tick"}


# ── Five-Day Acceptance Tracker ──────────────────────────────────────────────

def _is_trading_day(d: date) -> bool:
    try:
        from market_hours import is_trading_day
        return bool(is_trading_day(d))
    except Exception:
        return d.weekday() < 5


def last_trading_days(n: int = 5, now: Optional[datetime] = None,
                      trading_day_fn=None) -> List[str]:
    """The last `n` consecutive NSE trading days (IST calendar, newest last),
    ending at the most recent COMPLETED session day: today only counts after
    market close (15:30 IST), because its daily report is a post-close
    artifact."""
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    is_td = trading_day_fn or _is_trading_day
    now_ist = now.astimezone(IST)
    day = now_ist.date()
    if not (is_td(day) and (now_ist.hour, now_ist.minute) >= (15, 30)):
        day -= timedelta(days=1)
    days: List[str] = []
    guard = 0
    while len(days) < n and guard < 400:
        guard += 1
        if is_td(day):
            days.append(day.isoformat())
        day -= timedelta(days=1)
    return list(reversed(days))


def build_five_day_acceptance(now: Optional[datetime] = None,
                              reports: Optional[Dict[str, Optional[Dict]]]
                              = None, trading_day_fn=None) -> Dict[str, Any]:
    """Rolling acceptance over the last 5 consecutive trading days.

    Per day: PASS when that day's daily report exists and its stored
    acceptance criterion passed; FAIL when it exists and failed; PENDING
    when no report exists for the day. Overall: FAIL if any day failed,
    PENDING if none failed but any day is missing, PASS only when all five
    days passed.
    """
    days = last_trading_days(5, now=now, trading_day_fn=trading_day_fn)
    rows: List[Dict[str, Any]] = []
    for d in days:
        report = (reports.get(d) if reports is not None
                  else get_daily_report(d))
        if report is None:
            rows.append({"date": d, "status": "PENDING",
                         "detail": "no daily validation report recorded"})
            continue
        acc = report.get("acceptance") or {}
        passed = bool(acc.get("passed"))
        hard_fail = bool(acc.get("failed_sections")
                         or acc.get("critical_open_issues"))
        if passed:
            status, detail = PASS, "zero mismatches / zero critical errors"
        elif hard_fail:
            status, detail = FAIL, "acceptance criteria not met"
        else:
            # Report exists but evidence was incomplete/stale — the day is
            # unproven, not failed: it holds the window at PENDING.
            status, detail = "PENDING", (
                "incomplete validation evidence: "
                + ", ".join(acc.get("insufficient_sections") or [])
                or "incomplete validation evidence")
        rows.append({
            "date": d,
            "status": status,
            "report_id": report.get("report_id"),
            "verdict": report.get("verdict"),
            "critical_open_issues": acc.get("critical_open_issues"),
            "failed_sections": acc.get("failed_sections") or [],
            "detail": detail,
        })
    statuses = [r["status"] for r in rows]
    if FAIL in statuses:
        overall = FAIL
    elif "PENDING" in statuses or len(rows) < 5:
        overall = "PENDING"
    else:
        overall = PASS
    return {
        "ok": True,
        "kind": "five_day_acceptance",
        "generated_at": _now_iso(),
        "window_days": days,
        "days": rows,
        "days_passed": statuses.count(PASS),
        "days_failed": statuses.count(FAIL),
        "days_pending": statuses.count("PENDING"),
        "verdict": overall,
        "policy": ("PASS requires 5 consecutive completed trading days each "
                   "with zero open CRITICAL issues and zero failing health "
                   "sections; any missing day is PENDING, any failed day is "
                   "FAIL."),
        "note": ADVISORY,
    }


# ── Final Production Readiness Report ────────────────────────────────────────

_UNSET: Any = object()      # sentinel: None is a VALID injected value
                            # ("no cert recorded"), distinct from "collect"


def build_readiness_report(now: Optional[datetime] = None,
                           five_day: Optional[Dict[str, Any]] = None,
                           certification: Any = _UNSET,
                           performance: Any = _UNSET,
                           open_issues: Any = _UNSET) -> Dict[str, Any]:
    """On-demand Final Production Readiness Report. Strict verdict:

    READY      — five-day acceptance PASS, latest certification READY, and
                 zero open CRITICAL issues.
    PENDING    — nothing hard-failed, but evidence is incomplete (five-day
                 window pending, or no certification run yet).
    NOT_READY  — any hard blocker: a failed acceptance day, certification
                 NOT_READY, or open CRITICAL issues.
    """
    fd = five_day if five_day is not None else build_five_day_acceptance(now)
    if certification is _UNSET or performance is _UNSET \
            or open_issues is _UNSET:
        inputs = collect_daily_inputs()
        if certification is _UNSET:
            certification = inputs.get("certification")
        if performance is _UNSET:
            performance = inputs.get("performance")
        if open_issues is _UNSET:
            open_issues = inputs.get("open_issues") or []
    open_issues = list(open_issues or [])
    critical = [i for i in open_issues
                if str(i.get("severity")).upper() == "CRITICAL"]

    blockers: List[str] = []
    pending: List[str] = []
    if fd.get("verdict") == FAIL:
        blockers.append(f"five-day acceptance FAIL "
                        f"({fd.get('days_failed')} failed day(s))")
    elif fd.get("verdict") != PASS:
        pending.append(f"five-day acceptance {fd.get('verdict')} "
                       f"({fd.get('days_passed')}/5 days passed)")
    if certification is None:
        pending.append("no certification run recorded yet")
    elif certification.get("verdict") != "READY":
        blockers.append(
            f"latest certification {certification.get('verdict')} "
            f"({certification.get('certification_pct')}%)")
    if critical:
        blockers.append(f"{len(critical)} open CRITICAL issue(s)")
    if performance is None:
        pending.append("no performance validation run recorded yet")

    if blockers:
        verdict = "NOT_READY"
    elif pending:
        verdict = "PENDING"
    else:
        verdict = "READY"

    now_dt = now or datetime.now(timezone.utc)
    if now_dt.tzinfo is None:
        now_dt = now_dt.replace(tzinfo=timezone.utc)
    return {
        "ok": True,
        "kind": "production_readiness_report",
        "title": "Final Production Readiness Report",
        "generated_at": now_dt.isoformat(),
        "verdict": verdict,
        "ready": verdict == "READY",
        "blockers": blockers,
        "pending": pending,
        "five_day_acceptance": fd,
        "certification": None if not certification else {
            "cert_id": certification.get("cert_id"),
            "created_at": certification.get("created_at"),
            "certification_pct": certification.get("certification_pct"),
            "verdict": certification.get("verdict"),
            "blockers": certification.get("blockers") or [],
        },
        "performance": None if not performance else {
            "verdict": performance.get("verdict"),
            "grade_counts": performance.get("grade_counts"),
            "metrics": performance.get("metrics") or [],
            "generated_at": performance.get("generated_at"),
        },
        "open_issues": {
            "total": len(open_issues),
            "critical": len(critical),
            "items": open_issues[:50],
        },
        "policy": ("READY requires five-day acceptance PASS + certification "
                   "READY + zero open CRITICAL issues. Warnings and missing "
                   "evidence never certify — they hold the verdict at "
                   "PENDING."),
        "advisory_only": True,
        "note": ADVISORY,
    }
