"""
phase24_store.py — Phase 24: AI Learning Engine durable storage.

Append-only enrichment layer keyed to EXISTING trade/scan IDs.
- phase24_trade_intelligence : one permanent record per CLOSED phase20 trade
- phase24_missed_opps        : one permanent record per (scan_id, symbol) rejection
- phase24_recommendations    : advisory recommendations with a manual
                               approve/dismiss lifecycle (intent only — approval
                               NEVER mutates trading configuration)
- phase24_reports            : generated daily/weekly/monthly/quarterly reports

ADVISORY ONLY. This module has NO write path into trading rules, thresholds,
strategy enablement, or risk gates. It only stores learning artifacts.

With DATABASE_URL: Postgres is authoritative. Without it (local dev / tests):
JSON file fallback in this directory.

Append-only enforcement:
- trade intelligence + missed opps insert with ON CONFLICT DO NOTHING —
  a captured record is never overwritten or re-evaluated.
- recommendations may only transition PROPOSED → APPROVED | DISMISSED once.
"""
from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

_DIR = os.path.dirname(os.path.abspath(__file__))
# File-fallback paths (module-level so tests can point them at a tmpdir)
TRADES_FILE = os.path.join(_DIR, "phase24_trade_intelligence.json")
MISSED_FILE = os.path.join(_DIR, "phase24_missed_opps.json")
RECS_FILE = os.path.join(_DIR, "phase24_recommendations.json")
REPORTS_FILE = os.path.join(_DIR, "phase24_reports.json")

_SCHEMA_READY = False

REC_STATES = ("PROPOSED", "APPROVED", "DISMISSED")
REPORT_PERIODS = ("daily", "weekly", "monthly", "quarterly")


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
            CREATE TABLE IF NOT EXISTS phase24_trade_intelligence (
                trade_id   TEXT PRIMARY KEY,
                scan_id    TEXT,
                symbol     TEXT,
                closed_date TEXT,
                record     JSONB NOT NULL,
                analysis   JSONB,
                created_at TIMESTAMPTZ DEFAULT NOW()
            )""")
        cur.execute("""
            CREATE TABLE IF NOT EXISTS phase24_missed_opps (
                id         TEXT PRIMARY KEY,
                scan_id    TEXT,
                symbol     TEXT,
                record     JSONB NOT NULL,
                created_at TIMESTAMPTZ DEFAULT NOW()
            )""")
        cur.execute("""
            CREATE TABLE IF NOT EXISTS phase24_recommendations (
                id         TEXT PRIMARY KEY,
                rec_date   TEXT,
                record     JSONB NOT NULL,
                status     TEXT NOT NULL DEFAULT 'PROPOSED',
                decided_at TEXT,
                decision_note TEXT,
                created_at TIMESTAMPTZ DEFAULT NOW()
            )""")
        cur.execute("""
            CREATE TABLE IF NOT EXISTS phase24_reports (
                id         TEXT PRIMARY KEY,
                period     TEXT NOT NULL,
                period_key TEXT NOT NULL,
                record     JSONB NOT NULL,
                created_at TIMESTAMPTZ DEFAULT NOW(),
                UNIQUE (period, period_key)
            )""")
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
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ── JSON fallback helpers ────────────────────────────────────────────────────

def _read_json(path: str, default):
    if os.path.exists(path):
        try:
            with open(path) as f:
                return json.load(f)
        except Exception:
            pass
    return default


def _write_json(path: str, data) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=1, default=str)
    os.replace(tmp, path)


# ── Trade intelligence (append-only) ─────────────────────────────────────────

def insert_trade_record(trade_id: str, scan_id: Optional[str], symbol: str,
                        closed_date: str, record: Dict[str, Any],
                        analysis: Optional[Dict[str, Any]] = None) -> bool:
    """Insert a permanent trade intelligence record. Returns True if inserted,
    False if the trade was already captured (append-only: never overwrites)."""
    def in_db(conn):
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO phase24_trade_intelligence
                   (trade_id, scan_id, symbol, closed_date, record, analysis)
                   VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT (trade_id) DO NOTHING""",
                (trade_id, scan_id, symbol, closed_date,
                 json.dumps(record, default=str),
                 json.dumps(analysis, default=str) if analysis is not None else None))
            return cur.rowcount == 1

    def in_file():
        rows = _read_json(TRADES_FILE, [])
        if any(r.get("trade_id") == trade_id for r in rows):
            return False
        rows.append({"trade_id": trade_id, "scan_id": scan_id, "symbol": symbol,
                     "closed_date": closed_date, "record": record,
                     "analysis": analysis, "created_at": _now()})
        _write_json(TRADES_FILE, rows)
        return True

    return _with_db(in_db, in_file)


def has_trade_record(trade_id: str) -> bool:
    def in_db(conn):
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM phase24_trade_intelligence WHERE trade_id=%s",
                        (trade_id,))
            return cur.fetchone() is not None
    return _with_db(in_db, lambda: any(
        r.get("trade_id") == trade_id for r in _read_json(TRADES_FILE, [])))


def list_trade_records(limit: int = 500) -> List[Dict[str, Any]]:
    def in_db(conn):
        with conn.cursor() as cur:
            cur.execute(
                """SELECT trade_id, scan_id, symbol, closed_date, record, analysis,
                          created_at
                   FROM phase24_trade_intelligence
                   ORDER BY closed_date DESC, created_at DESC LIMIT %s""", (limit,))
            rows = cur.fetchall()
        out = []
        for tid, sid, sym, cd, rec, ana, cat in rows:
            if isinstance(rec, str):
                rec = json.loads(rec)
            if isinstance(ana, str):
                ana = json.loads(ana)
            out.append({"trade_id": tid, "scan_id": sid, "symbol": sym,
                        "closed_date": cd, "record": rec, "analysis": ana,
                        "created_at": str(cat)})
        return out

    def in_file():
        rows = _read_json(TRADES_FILE, [])
        rows.sort(key=lambda r: (str(r.get("closed_date") or ""),
                                 str(r.get("created_at") or "")), reverse=True)
        return rows[:limit]

    return _with_db(in_db, in_file)


# ── Missed opportunities (append-only) ───────────────────────────────────────

def insert_missed_opp(scan_id: str, symbol: str, record: Dict[str, Any]) -> bool:
    """Append-only per (scan_id, symbol)."""
    mid = f"{scan_id}:{symbol}"

    def in_db(conn):
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO phase24_missed_opps (id, scan_id, symbol, record)
                   VALUES (%s,%s,%s,%s) ON CONFLICT (id) DO NOTHING""",
                (mid, scan_id, symbol, json.dumps(record, default=str)))
            return cur.rowcount == 1

    def in_file():
        rows = _read_json(MISSED_FILE, [])
        if any(r.get("id") == mid for r in rows):
            return False
        rows.append({"id": mid, "scan_id": scan_id, "symbol": symbol,
                     "record": record, "created_at": _now()})
        _write_json(MISSED_FILE, rows)
        return True

    return _with_db(in_db, in_file)


def list_missed_opps(limit: int = 500) -> List[Dict[str, Any]]:
    def in_db(conn):
        with conn.cursor() as cur:
            cur.execute(
                """SELECT id, scan_id, symbol, record, created_at
                   FROM phase24_missed_opps ORDER BY created_at DESC LIMIT %s""",
                (limit,))
            rows = cur.fetchall()
        out = []
        for rid, sid, sym, rec, cat in rows:
            if isinstance(rec, str):
                rec = json.loads(rec)
            out.append({"id": rid, "scan_id": sid, "symbol": sym,
                        "record": rec, "created_at": str(cat)})
        return out

    def in_file():
        rows = _read_json(MISSED_FILE, [])
        return sorted(rows, key=lambda r: str(r.get("created_at") or ""),
                      reverse=True)[:limit]

    return _with_db(in_db, in_file)


# ── Recommendations (manual approval lifecycle) ──────────────────────────────

def insert_recommendation(rec_date: str, record: Dict[str, Any],
                          rec_id: Optional[str] = None) -> Dict[str, Any]:
    rid = rec_id or f"P24R-{uuid.uuid4().hex[:10]}"
    row = {"id": rid, "rec_date": rec_date, "record": record,
           "status": "PROPOSED", "decided_at": None, "decision_note": None,
           "created_at": _now()}

    def in_db(conn):
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO phase24_recommendations (id, rec_date, record)
                   VALUES (%s,%s,%s) ON CONFLICT (id) DO NOTHING""",
                (rid, rec_date, json.dumps(record, default=str)))
        return row

    def in_file():
        rows = _read_json(RECS_FILE, [])
        if not any(r.get("id") == rid for r in rows):
            rows.append(row)
            _write_json(RECS_FILE, rows)
        return row

    return _with_db(in_db, in_file)


def list_recommendations(limit: int = 200,
                         status: Optional[str] = None) -> List[Dict[str, Any]]:
    def in_db(conn):
        q = """SELECT id, rec_date, record, status, decided_at, decision_note,
                      created_at FROM phase24_recommendations"""
        params: list = []
        if status:
            q += " WHERE status = %s"
            params.append(status)
        q += " ORDER BY created_at DESC LIMIT %s"
        params.append(limit)
        with conn.cursor() as cur:
            cur.execute(q, tuple(params))
            rows = cur.fetchall()
        out = []
        for rid, rd, rec, st, da, note, cat in rows:
            if isinstance(rec, str):
                rec = json.loads(rec)
            out.append({"id": rid, "rec_date": rd, "record": rec, "status": st,
                        "decided_at": da, "decision_note": note,
                        "created_at": str(cat)})
        return out

    def in_file():
        rows = _read_json(RECS_FILE, [])
        if status:
            rows = [r for r in rows if r.get("status") == status]
        return sorted(rows, key=lambda r: str(r.get("created_at") or ""),
                      reverse=True)[:limit]

    return _with_db(in_db, in_file)


def decide_recommendation(rec_id: str, decision: str,
                          note: str = "") -> Dict[str, Any]:
    """Record an operator decision. INTENT ONLY — this never applies any
    change to trading rules, thresholds, or strategy enablement.
    Only PROPOSED recommendations may be decided; decisions are final."""
    decision = decision.upper()
    if decision not in ("APPROVED", "DISMISSED"):
        return {"success": False, "error": "decision must be approve or dismiss"}
    decided_at = _now()

    def in_db(conn):
        with conn.cursor() as cur:
            cur.execute(
                """UPDATE phase24_recommendations
                   SET status=%s, decided_at=%s, decision_note=%s
                   WHERE id=%s AND status='PROPOSED'""",
                (decision, decided_at, note[:500], rec_id))
            if cur.rowcount != 1:
                return {"success": False,
                        "error": f"Recommendation {rec_id} not found or already decided"}
        return {"success": True, "id": rec_id, "status": decision,
                "decided_at": decided_at,
                "note": "Decision recorded as intent only. No trading rule, "
                        "threshold, or strategy was modified."}

    def in_file():
        rows = _read_json(RECS_FILE, [])
        for r in rows:
            if r.get("id") == rec_id:
                if r.get("status") != "PROPOSED":
                    return {"success": False,
                            "error": f"Recommendation {rec_id} already decided"}
                r["status"] = decision
                r["decided_at"] = decided_at
                r["decision_note"] = note[:500]
                _write_json(RECS_FILE, rows)
                return {"success": True, "id": rec_id, "status": decision,
                        "decided_at": decided_at,
                        "note": "Decision recorded as intent only. No trading "
                                "rule, threshold, or strategy was modified."}
        return {"success": False, "error": f"Recommendation {rec_id} not found"}

    return _with_db(in_db, in_file)


# ── Reports ──────────────────────────────────────────────────────────────────

def save_report(period: str, period_key: str,
                record: Dict[str, Any]) -> Dict[str, Any]:
    """Save a generated report. Idempotent per (period, period_key) — the
    first generated report for a period is permanent."""
    rid = f"P24REP-{period}-{period_key}"

    def in_db(conn):
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO phase24_reports (id, period, period_key, record)
                   VALUES (%s,%s,%s,%s) ON CONFLICT (period, period_key) DO NOTHING""",
                (rid, period, period_key, json.dumps(record, default=str)))
            inserted = cur.rowcount == 1
        return {"id": rid, "inserted": inserted}

    def in_file():
        rows = _read_json(REPORTS_FILE, [])
        if any(r.get("period") == period and r.get("period_key") == period_key
               for r in rows):
            return {"id": rid, "inserted": False}
        rows.append({"id": rid, "period": period, "period_key": period_key,
                     "record": record, "created_at": _now()})
        _write_json(REPORTS_FILE, rows)
        return {"id": rid, "inserted": True}

    return _with_db(in_db, in_file)


def list_reports(period: Optional[str] = None,
                 limit: int = 50) -> List[Dict[str, Any]]:
    def in_db(conn):
        q = "SELECT id, period, period_key, record, created_at FROM phase24_reports"
        params: list = []
        if period:
            q += " WHERE period = %s"
            params.append(period)
        q += " ORDER BY period_key DESC LIMIT %s"
        params.append(limit)
        with conn.cursor() as cur:
            cur.execute(q, tuple(params))
            rows = cur.fetchall()
        out = []
        for rid, p, pk, rec, cat in rows:
            if isinstance(rec, str):
                rec = json.loads(rec)
            out.append({"id": rid, "period": p, "period_key": pk,
                        "record": rec, "created_at": str(cat)})
        return out

    def in_file():
        rows = _read_json(REPORTS_FILE, [])
        if period:
            rows = [r for r in rows if r.get("period") == period]
        return sorted(rows, key=lambda r: str(r.get("period_key") or ""),
                      reverse=True)[:limit]

    return _with_db(in_db, in_file)


def get_report(period: str, period_key: str) -> Optional[Dict[str, Any]]:
    for r in list_reports(period=period, limit=1000):
        if r.get("period_key") == period_key:
            return r
    return None
