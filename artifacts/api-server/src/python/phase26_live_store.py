"""
phase26_live_store.py — Phase 26B: live-validation snapshot + issue storage.

Two stores:

1. Live-validation snapshots — append-only records of the 5-minute in-session
   subsystem liveness checks (phase26_live_monitor). Never overwritten.

2. Issue store — deduplicated, lifecycle-tracked issues detected by the live
   monitor, the cross-page consistency validator, and the Phase 26A E2E
   validators. Dedup key is (category, key): re-detections update last_seen
   and count on the SAME row; a category sweep auto-resolves open issues that
   are no longer detected; a later re-detection reopens the same row
   (preserving first_seen).

With DATABASE_URL: Postgres is authoritative. Without it (local dev/tests):
JSON file fallback in this directory, serialized with flock — every
read-modify-write on the fallback files holds the exclusive lock.

PAPER TRADING / RESEARCH ONLY.
"""
from __future__ import annotations

import fcntl
import json
import os
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

_DIR = os.path.dirname(os.path.abspath(__file__))
SNAPSHOTS_FILE = os.path.join(_DIR, "phase26_live_snapshots.json")
ISSUES_FILE = os.path.join(_DIR, "phase26_issues.json")
_SNAP_CAP = 500              # keep local-dev fallback bounded
_ISSUE_CAP = 1000

SEVERITIES = ("INFO", "WARNING", "CRITICAL")
_SEV_RANK = {"INFO": 0, "WARNING": 1, "CRITICAL": 2}

_SCHEMA_READY = False


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


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
            CREATE TABLE IF NOT EXISTS phase26_live_snapshots (
                snapshot_id TEXT PRIMARY KEY,
                created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
                in_session  BOOLEAN,
                verdict     TEXT,
                result      JSONB NOT NULL
            )
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_p26_live_created
            ON phase26_live_snapshots (created_at DESC)
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS phase26_issues (
                category    TEXT NOT NULL,
                key         TEXT NOT NULL,
                severity    TEXT NOT NULL,
                title       TEXT,
                detail      TEXT,
                source      TEXT,
                first_seen  TIMESTAMPTZ NOT NULL,
                last_seen   TIMESTAMPTZ NOT NULL,
                count       INTEGER NOT NULL DEFAULT 1,
                status      TEXT NOT NULL DEFAULT 'OPEN',
                resolved_at TIMESTAMPTZ,
                PRIMARY KEY (category, key)
            )
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
    """Serialize cross-process read-modify-write on a fallback file."""
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


# ── Live-validation snapshots (append-only) ──────────────────────────────────

def new_snapshot_id() -> str:
    return f"live-{uuid.uuid4().hex[:12]}"


def append_snapshot(result: Dict[str, Any]) -> Dict[str, Any]:
    snap_id = str(result.get("snapshot_id") or new_snapshot_id())
    result = dict(result)
    result["snapshot_id"] = snap_id
    record = {
        "snapshot_id": snap_id,
        "created_at": result.get("generated_at") or _now(),
        "in_session": bool(result.get("in_session")),
        "verdict": result.get("verdict"),
        "result": result,
    }

    def in_db(conn):
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO phase26_live_snapshots
                    (snapshot_id, created_at, in_session, verdict, result)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (snapshot_id) DO NOTHING
                """,
                (snap_id, record["created_at"], record["in_session"],
                 str(record["verdict"]), json.dumps(result, default=str)),
            )
        return record

    def in_file():
        with _file_lock(SNAPSHOTS_FILE):
            rows = _read_json(SNAPSHOTS_FILE, [])
            if any(r.get("snapshot_id") == snap_id for r in rows):
                return record
            rows.append(record)
            _write_json(SNAPSHOTS_FILE, rows[-_SNAP_CAP:])
        return record

    out = _with_db(in_db, in_file)
    maybe_prune()  # opportunistic, daily-guarded, never raises
    return out


# ── Retention ────────────────────────────────────────────────────────────────
#
# Mirrors the pipeline_events 14-day prune pattern: Postgres rows would
# otherwise grow forever (~75 snapshots per session). The JSON fallbacks are
# already capped (_SNAP_CAP / _ISSUE_CAP), but prune() also ages them out so
# behaviour matches across backends. OPEN issues are NEVER pruned.

RETENTION_DAYS = 14


def prune(days: int = RETENTION_DAYS) -> Dict[str, Any]:
    """Delete snapshots older than `days`, and RESOLVED issues whose
    resolved_at is older than `days`. OPEN issues are never touched.
    NEVER raises — retention must not break a validation cycle."""
    days = int(days)
    try:
        def in_db(conn):
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM phase26_live_snapshots"
                    " WHERE created_at < NOW() - (%s || ' days')::interval",
                    (days,))
                snaps = cur.rowcount
                cur.execute(
                    "DELETE FROM phase26_issues"
                    " WHERE status = 'RESOLVED' AND resolved_at IS NOT NULL"
                    " AND resolved_at < NOW() - (%s || ' days')::interval",
                    (days,))
                issues = cur.rowcount
            return {"snapshots_deleted": snaps, "issues_deleted": issues,
                    "days": days}

        def in_file():
            from datetime import timedelta
            cutoff = datetime.now(timezone.utc) - timedelta(days=days)

            def _older(ts: Any) -> bool:
                try:
                    d = datetime.fromisoformat(
                        str(ts).replace("Z", "+00:00"))
                    if d.tzinfo is None:
                        d = d.replace(tzinfo=timezone.utc)
                    return d < cutoff
                except Exception:
                    return False  # unparsable timestamps are kept

            with _file_lock(SNAPSHOTS_FILE):
                rows = _read_json(SNAPSHOTS_FILE, [])
                kept = [r for r in rows if not _older(r.get("created_at"))]
                snaps = len(rows) - len(kept)
                if snaps:
                    _write_json(SNAPSHOTS_FILE, kept)
            with _file_lock(ISSUES_FILE):
                rows = _read_json(ISSUES_FILE, [])
                kept = [r for r in rows
                        if not (r.get("status") == "RESOLVED"
                                and r.get("resolved_at")
                                and _older(r.get("resolved_at")))]
                issues = len(rows) - len(kept)
                if issues:
                    _write_json(ISSUES_FILE, kept)
            return {"snapshots_deleted": snaps, "issues_deleted": issues,
                    "days": days}

        return _with_db(in_db, in_file)
    except Exception:
        return {"snapshots_deleted": 0, "issues_deleted": 0,
                "days": days, "error": True}


def maybe_prune(days: int = RETENTION_DAYS) -> Dict[str, Any]:
    """Opportunistic daily prune: runs at most once per UTC day across all
    processes via the phase20 KV first-claimant guard. NEVER raises."""
    try:
        import phase20_store
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if not phase20_store.kv_claim_once(f"phase26_live_prune:{today}"):
            return {"skipped": True}
        return prune(days)
    except Exception:
        return {"skipped": True, "error": True}


def list_snapshots(limit: int = 50) -> List[Dict[str, Any]]:
    """Newest-first snapshot summaries."""
    limit = max(1, min(int(limit or 50), 500))

    def in_db(conn):
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT snapshot_id, created_at, in_session, verdict,
                       result->'subsystem_counts' AS counts
                FROM phase26_live_snapshots
                ORDER BY created_at DESC LIMIT %s
                """, (limit,))
            return [{"snapshot_id": r[0], "created_at": str(r[1]),
                     "in_session": r[2], "verdict": r[3],
                     "subsystem_counts": r[4]}
                    for r in cur.fetchall()]

    def in_file():
        rows = _read_json(SNAPSHOTS_FILE, [])
        rows = sorted(rows, key=lambda r: str(r.get("created_at") or ""),
                      reverse=True)[:limit]
        return [{"snapshot_id": r.get("snapshot_id"),
                 "created_at": r.get("created_at"),
                 "in_session": r.get("in_session"),
                 "verdict": r.get("verdict"),
                 "subsystem_counts":
                     (r.get("result") or {}).get("subsystem_counts")}
                for r in rows]

    return _with_db(in_db, in_file)


def latest_snapshot() -> Optional[Dict[str, Any]]:
    def in_db(conn):
        with conn.cursor() as cur:
            cur.execute(
                "SELECT result FROM phase26_live_snapshots"
                " ORDER BY created_at DESC LIMIT 1")
            row = cur.fetchone()
        return row[0] if row else None

    def in_file():
        rows = _read_json(SNAPSHOTS_FILE, [])
        if not rows:
            return None
        rows = sorted(rows, key=lambda r: str(r.get("created_at") or ""))
        return rows[-1].get("result")

    return _with_db(in_db, in_file)


# ── Issue store (deduplicated, lifecycle-tracked) ────────────────────────────

def _norm_sev(severity: Any) -> str:
    s = str(severity or "").upper()
    return s if s in SEVERITIES else "WARNING"


def report_issue(category: str, key: str, severity: str, title: str,
                 detail: str = "", source: str = "") -> Dict[str, Any]:
    """Upsert one detected issue. Dedup by (category, key):
    - new → OPEN row with first_seen = last_seen = now, count 1
    - existing OPEN → bump last_seen/count; severity escalates only upward
    - existing RESOLVED → reopen (first_seen preserved, count continues)

    Returns {"category", "key", "status", "transition"} where transition is
    "OPENED" when the row transitioned to OPEN this call (new or reopened)
    and "STILL_OPEN" when it was already open — callers alert on OPENED only.
    """
    category = str(category).strip().upper()
    key = str(key).strip()
    severity = _norm_sev(severity)
    now = _now()

    def in_db(conn):
        with conn.cursor() as cur:
            cur.execute(
                "SELECT status FROM phase26_issues"
                " WHERE category=%s AND key=%s", (category, key))
            row = cur.fetchone()
            transition = "STILL_OPEN" if row and row[0] == "OPEN" \
                else "OPENED"
            cur.execute(
                """
                INSERT INTO phase26_issues
                    (category, key, severity, title, detail, source,
                     first_seen, last_seen, count, status, resolved_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,1,'OPEN',NULL)
                ON CONFLICT (category, key) DO UPDATE SET
                    severity = CASE
                        WHEN phase26_issues.status = 'RESOLVED'
                            THEN EXCLUDED.severity
                        WHEN (CASE EXCLUDED.severity WHEN 'CRITICAL' THEN 2
                              WHEN 'WARNING' THEN 1 ELSE 0 END) >
                             (CASE phase26_issues.severity WHEN 'CRITICAL' THEN 2
                              WHEN 'WARNING' THEN 1 ELSE 0 END)
                            THEN EXCLUDED.severity
                        ELSE phase26_issues.severity END,
                    title = EXCLUDED.title,
                    detail = EXCLUDED.detail,
                    source = EXCLUDED.source,
                    last_seen = EXCLUDED.last_seen,
                    count = phase26_issues.count + 1,
                    status = 'OPEN',
                    resolved_at = NULL
                """,
                (category, key, severity, str(title)[:300], str(detail)[:1000],
                 str(source)[:100], now, now),
            )
        return {"category": category, "key": key, "status": "OPEN",
                "transition": transition}

    def in_file():
        with _file_lock(ISSUES_FILE):
            rows = _read_json(ISSUES_FILE, [])
            for r in rows:
                if r.get("category") == category and r.get("key") == key:
                    reopened = r.get("status") == "RESOLVED"
                    if reopened or _SEV_RANK.get(severity, 1) > \
                            _SEV_RANK.get(str(r.get("severity")), 1):
                        r["severity"] = severity
                    r.update(title=str(title)[:300], detail=str(detail)[:1000],
                             source=str(source)[:100], last_seen=now,
                             count=int(r.get("count") or 0) + 1,
                             status="OPEN", resolved_at=None)
                    _write_json(ISSUES_FILE, rows)
                    return {"category": category, "key": key,
                            "status": "OPEN",
                            "transition": "OPENED" if reopened
                            else "STILL_OPEN"}
            rows.append({"category": category, "key": key,
                         "severity": severity, "title": str(title)[:300],
                         "detail": str(detail)[:1000],
                         "source": str(source)[:100],
                         "first_seen": now, "last_seen": now, "count": 1,
                         "status": "OPEN", "resolved_at": None})
            _write_json(ISSUES_FILE, rows[-_ISSUE_CAP:])
        return {"category": category, "key": key, "status": "OPEN",
                "transition": "OPENED"}

    return _with_db(in_db, in_file)


def resolve_issue(category: str, key: str) -> bool:
    """Mark one issue RESOLVED. Returns True when a row changed."""
    category = str(category).strip().upper()
    key = str(key).strip()
    now = _now()

    def in_db(conn):
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE phase26_issues SET status='RESOLVED', resolved_at=%s"
                " WHERE category=%s AND key=%s AND status='OPEN'",
                (now, category, key))
            return cur.rowcount > 0

    def in_file():
        with _file_lock(ISSUES_FILE):
            rows = _read_json(ISSUES_FILE, [])
            changed = False
            for r in rows:
                if r.get("category") == category and r.get("key") == key \
                        and r.get("status") == "OPEN":
                    r["status"] = "RESOLVED"
                    r["resolved_at"] = now
                    changed = True
            if changed:
                _write_json(ISSUES_FILE, rows)
            return changed

    return _with_db(in_db, in_file)


def sweep_category(category: str, active_keys: List[str]) -> Dict[str, Any]:
    """Auto-resolve OPEN issues in `category` whose key is NOT in
    `active_keys` (the set of issues the just-finished validation cycle still
    detects). Only call this after a cycle that fully evaluated the category —
    a partial/failed cycle must not resolve anything."""
    category = str(category).strip().upper()
    keys = {str(k) for k in active_keys}
    now = _now()

    def in_db(conn):
        with conn.cursor() as cur:
            if keys:
                cur.execute(
                    "UPDATE phase26_issues SET status='RESOLVED',"
                    " resolved_at=%s WHERE category=%s AND status='OPEN'"
                    " AND NOT (key = ANY(%s))",
                    (now, category, list(keys)))
            else:
                cur.execute(
                    "UPDATE phase26_issues SET status='RESOLVED',"
                    " resolved_at=%s WHERE category=%s AND status='OPEN'",
                    (now, category))
            return {"resolved": cur.rowcount}

    def in_file():
        with _file_lock(ISSUES_FILE):
            rows = _read_json(ISSUES_FILE, [])
            n = 0
            for r in rows:
                if r.get("category") == category and \
                        r.get("status") == "OPEN" and r.get("key") not in keys:
                    r["status"] = "RESOLVED"
                    r["resolved_at"] = now
                    n += 1
            if n:
                _write_json(ISSUES_FILE, rows)
            return {"resolved": n}

    return _with_db(in_db, in_file)


def reconcile_category(category: str,
                       issues: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Atomically reconcile one category against a fully-evaluated cycle:
    upsert every detected issue AND resolve open issues absent from the
    cycle, as ONE unit. DB path holds a per-category advisory lock inside a
    single transaction; file path holds the flock across the whole cycle —
    so a concurrent run can never sweep away an issue another run just
    reported (report+sweep interleave).

    Returns {"reported", "resolved", "opened", "resolved_keys"}:
    - opened: the detected issues (dicts incl. category) that transitioned
      to OPEN this cycle (new or reopened) — callers alert on these only,
      never on issues that were already open.
    - resolved_keys: keys of OPEN issues this cycle auto-resolved.
    """
    category = str(category).strip().upper()
    now = _now()
    norm = []
    for i in issues:
        norm.append({
            "key": str(i.get("key") or "").strip(),
            "severity": _norm_sev(i.get("severity")),
            "title": str(i.get("title") or "")[:300],
            "detail": str(i.get("detail") or "")[:1000],
            "source": str(i.get("source") or "")[:100],
        })
    active_keys = {n["key"] for n in norm}

    def in_db(conn):
        with conn.cursor() as cur:
            cur.execute("SELECT pg_advisory_xact_lock(hashtext(%s))",
                        (f"phase26_issues:{category}",))
            cur.execute(
                "SELECT key FROM phase26_issues"
                " WHERE category=%s AND status='OPEN'", (category,))
            already_open = {r[0] for r in cur.fetchall()}
            for n in norm:
                cur.execute(
                    """
                    INSERT INTO phase26_issues
                        (category, key, severity, title, detail, source,
                         first_seen, last_seen, count, status, resolved_at)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,1,'OPEN',NULL)
                    ON CONFLICT (category, key) DO UPDATE SET
                        severity = CASE
                            WHEN phase26_issues.status = 'RESOLVED'
                                THEN EXCLUDED.severity
                            WHEN (CASE EXCLUDED.severity WHEN 'CRITICAL' THEN 2
                                  WHEN 'WARNING' THEN 1 ELSE 0 END) >
                                 (CASE phase26_issues.severity
                                  WHEN 'CRITICAL' THEN 2
                                  WHEN 'WARNING' THEN 1 ELSE 0 END)
                                THEN EXCLUDED.severity
                            ELSE phase26_issues.severity END,
                        title = EXCLUDED.title,
                        detail = EXCLUDED.detail,
                        source = EXCLUDED.source,
                        last_seen = EXCLUDED.last_seen,
                        count = phase26_issues.count + 1,
                        status = 'OPEN',
                        resolved_at = NULL
                    """,
                    (category, n["key"], n["severity"], n["title"],
                     n["detail"], n["source"], now, now))
            if active_keys:
                cur.execute(
                    "UPDATE phase26_issues SET status='RESOLVED',"
                    " resolved_at=%s WHERE category=%s AND status='OPEN'"
                    " AND NOT (key = ANY(%s)) RETURNING key",
                    (now, category, list(active_keys)))
            else:
                cur.execute(
                    "UPDATE phase26_issues SET status='RESOLVED',"
                    " resolved_at=%s WHERE category=%s AND status='OPEN'"
                    " RETURNING key",
                    (now, category))
            resolved_keys = [r[0] for r in cur.fetchall()]
        opened = [{**n, "category": category} for n in norm
                  if n["key"] not in already_open]
        return {"reported": len(norm), "resolved": len(resolved_keys),
                "opened": opened, "resolved_keys": resolved_keys}

    def in_file():
        with _file_lock(ISSUES_FILE):
            rows = _read_json(ISSUES_FILE, [])
            by_key = {r.get("key"): r for r in rows
                      if r.get("category") == category}
            already_open = {k for k, r in by_key.items()
                            if r.get("status") == "OPEN"}
            for n in norm:
                r = by_key.get(n["key"])
                if r is None:
                    rows.append({"category": category, **n,
                                 "first_seen": now, "last_seen": now,
                                 "count": 1, "status": "OPEN",
                                 "resolved_at": None})
                else:
                    reopened = r.get("status") == "RESOLVED"
                    if reopened or _SEV_RANK.get(n["severity"], 1) > \
                            _SEV_RANK.get(str(r.get("severity")), 1):
                        r["severity"] = n["severity"]
                    r.update(title=n["title"], detail=n["detail"],
                             source=n["source"], last_seen=now,
                             count=int(r.get("count") or 0) + 1,
                             status="OPEN", resolved_at=None)
            resolved_keys = []
            for r in rows:
                if r.get("category") == category and \
                        r.get("status") == "OPEN" and \
                        r.get("key") not in active_keys:
                    r["status"] = "RESOLVED"
                    r["resolved_at"] = now
                    resolved_keys.append(r.get("key"))
            _write_json(ISSUES_FILE, rows[-_ISSUE_CAP:])
            opened = [{**n, "category": category} for n in norm
                      if n["key"] not in already_open]
            return {"reported": len(norm), "resolved": len(resolved_keys),
                    "opened": opened, "resolved_keys": resolved_keys}

    return _with_db(in_db, in_file)


def list_issues(status: Optional[str] = None,
                category: Optional[str] = None,
                limit: int = 200) -> List[Dict[str, Any]]:
    """Issues newest-last_seen first, optionally filtered."""
    limit = max(1, min(int(limit or 200), 1000))
    status_f = str(status).upper() if status else None
    category_f = str(category).upper() if category else None

    def in_db(conn):
        clauses, args = [], []
        if status_f:
            clauses.append("status = %s"); args.append(status_f)
        if category_f:
            clauses.append("category = %s"); args.append(category_f)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT category, key, severity, title, detail, source,
                       first_seen, last_seen, count, status, resolved_at
                FROM phase26_issues {where}
                ORDER BY last_seen DESC LIMIT %s
                """, (*args, limit))
            cols = ("category", "key", "severity", "title", "detail",
                    "source", "first_seen", "last_seen", "count", "status",
                    "resolved_at")
            return [dict(zip(cols, (str(v) if i in (6, 7, 10) and v is not None
                                    else v for i, v in enumerate(r))))
                    for r in cur.fetchall()]

    def in_file():
        rows = _read_json(ISSUES_FILE, [])
        out = [r for r in rows
               if (not status_f or r.get("status") == status_f)
               and (not category_f or r.get("category") == category_f)]
        out.sort(key=lambda r: str(r.get("last_seen") or ""), reverse=True)
        return out[:limit]

    return _with_db(in_db, in_file)
