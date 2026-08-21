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
                id              TEXT PRIMARY KEY,
                scan_id         TEXT,
                symbol          TEXT,
                record          JSONB NOT NULL,
                source          TEXT NOT NULL DEFAULT 'live',
                backtest_run_id TEXT,
                created_at      TIMESTAMPTZ DEFAULT NOW()
            )""")
        # Idempotent schema upgrades for existing tables
        cur.execute("""
            ALTER TABLE phase24_missed_opps
                ADD COLUMN IF NOT EXISTS source TEXT NOT NULL DEFAULT 'live'""")
        cur.execute("""
            ALTER TABLE phase24_missed_opps
                ADD COLUMN IF NOT EXISTS backtest_run_id TEXT""")
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

def insert_missed_opp(scan_id: str, symbol: str, record: Dict[str, Any],
                      source: str = "live",
                      backtest_run_id: Optional[str] = None) -> bool:
    """Append-only per (scan_id, symbol) for live; per (run_id, scan_id, symbol,
    decision) for backtest so both pools coexist without collision."""
    if source == "backtest" and backtest_run_id:
        decision = record.get("decision", "WATCH")
        mid = f"BT:{backtest_run_id}:{scan_id}:{symbol}:{decision}"
    else:
        mid = f"{scan_id}:{symbol}"

    def in_db(conn):
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO phase24_missed_opps
                   (id, scan_id, symbol, record, source, backtest_run_id)
                   VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT (id) DO NOTHING""",
                (mid, scan_id, symbol, json.dumps(record, default=str),
                 source, backtest_run_id))
            return cur.rowcount == 1

    def in_file():
        rows = _read_json(MISSED_FILE, [])
        if any(r.get("id") == mid for r in rows):
            return False
        rows.append({"id": mid, "scan_id": scan_id, "symbol": symbol,
                     "record": record, "source": source,
                     "backtest_run_id": backtest_run_id,
                     "created_at": _now()})
        _write_json(MISSED_FILE, rows)
        return True

    return _with_db(in_db, in_file)


# ── Phase 2B advisory multi-bot audit store (append-only) ─────────────────────
#
# These records are deliberately separate from Phase 20 trade, position, and
# portfolio state.  They store only advisory evidence and have no update/delete
# API.  The explicit allow-list below prevents the generic writer from being
# pointed at any other table.

ADVISORY_OUTPUTS_FILE = os.path.join(_DIR, "advisory_bot_outputs.json")
ADVISORY_STRATEGY_SCORES_FILE = os.path.join(_DIR, "advisory_strategy_scores.json")
ADVISORY_DECISION_AUDIT_FILE = os.path.join(_DIR, "advisory_decision_audit.json")
ADVISORY_UNIVERSE_HEALTH_FILE = os.path.join(_DIR, "advisory_universe_health.json")

ADVISORY_TABLES = frozenset({
    "advisory_bot_outputs",
    "advisory_strategy_scores",
    "advisory_decision_audit",
    "advisory_universe_health",
})
_ADVISORY_FILES = {
    "advisory_bot_outputs": ADVISORY_OUTPUTS_FILE,
    "advisory_strategy_scores": ADVISORY_STRATEGY_SCORES_FILE,
    "advisory_decision_audit": ADVISORY_DECISION_AUDIT_FILE,
    "advisory_universe_health": ADVISORY_UNIVERSE_HEALTH_FILE,
}
_ADVISORY_DECISIONS = (
    "WATCH",
    "CANDIDATE",
    "REJECTED",
    "BLOCKED_DATA_QUALITY",
    "INSUFFICIENT_CONTEXT",
    "SUPERVISOR_BLOCKED",
)
_ADVISORY_REQUIRED = (
    "timestamp", "scan_id", "symbol", "bot_name", "strategy_name",
    "score", "decision", "reason", "data_quality", "risk_flags",
    "build_id", "config_hash", "advisory_only", "paper_only",
)


def _ensure_advisory_schema(conn) -> None:
    """Create Phase 2B advisory tables only; never references Phase 20 tables."""
    with conn.cursor() as cur:
        for table, unique_key in (
            (
                "advisory_bot_outputs",
                "scan_id, bot_name, symbol, strategy_name, build_id, config_hash",
            ),
            (
                "advisory_strategy_scores",
                "scan_id, symbol, strategy_name, build_id, config_hash",
            ),
            (
                "advisory_decision_audit",
                "scan_id, symbol, build_id, config_hash",
            ),
            (
                "advisory_universe_health",
                "scan_id, build_id, config_hash",
            ),
        ):
            cur.execute(f"""
                CREATE TABLE IF NOT EXISTS {table} (
                    id              TEXT PRIMARY KEY,
                    observed_at     TIMESTAMPTZ NOT NULL,
                    scan_id         TEXT NOT NULL,
                    symbol          TEXT NOT NULL,
                    bot_name        TEXT NOT NULL,
                    strategy_name   TEXT NOT NULL,
                    score           NUMERIC(8,2) NOT NULL,
                    decision        TEXT NOT NULL CHECK (
                        decision IN (
                            'WATCH', 'CANDIDATE', 'REJECTED',
                            'BLOCKED_DATA_QUALITY', 'INSUFFICIENT_CONTEXT',
                            'SUPERVISOR_BLOCKED'
                        )
                    ),
                    reason          TEXT NOT NULL,
                    data_quality    JSONB NOT NULL,
                    risk_flags      JSONB NOT NULL,
                    build_id        TEXT NOT NULL,
                    config_hash     TEXT NOT NULL,
                    advisory_only   BOOLEAN NOT NULL DEFAULT TRUE CHECK (advisory_only IS TRUE),
                    paper_only      BOOLEAN NOT NULL DEFAULT TRUE CHECK (paper_only IS TRUE),
                    record          JSONB NOT NULL,
                    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    UNIQUE ({unique_key})
                )
            """)
            cur.execute(f"""
                ALTER TABLE {table}
                ADD COLUMN IF NOT EXISTS advisory_only BOOLEAN NOT NULL DEFAULT TRUE
            """)
            constraint = f"ck_{table}_advisory_only_true"
            cur.execute(
                "SELECT 1 FROM pg_constraint WHERE conname = %s",
                (constraint,),
            )
            if cur.fetchone() is None:
                cur.execute(
                    f"SELECT COUNT(*) FROM {table} "
                    "WHERE advisory_only IS DISTINCT FROM TRUE"
                )
                invalid_count = int(cur.fetchone()[0])
                if invalid_count:
                    raise ValueError(
                        f"{table} contains {invalid_count} non-advisory rows; "
                        "refusing to add the advisory-only constraint"
                    )
                cur.execute(
                    f"ALTER TABLE {table} ADD CONSTRAINT {constraint} "
                    "CHECK (advisory_only IS TRUE)"
                )
    conn.commit()


def _advisory_record_id(table: str, record: Dict[str, Any]) -> str:
    """Stable idempotency key for immutable advisory evidence."""
    material = {
        "table": table,
        "scan_id": record["scan_id"],
        "symbol": record["symbol"],
        "bot_name": record["bot_name"],
        "strategy_name": record["strategy_name"],
        "build_id": record["build_id"],
        "config_hash": record["config_hash"],
    }
    import hashlib
    digest = hashlib.sha256(
        json.dumps(material, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return f"ADV:{digest}"


def _validate_advisory_record(table: str, record: Dict[str, Any]) -> Dict[str, Any]:
    if table not in ADVISORY_TABLES:
        raise ValueError(f"table is not approved for advisory storage: {table}")
    # Direct callers are held to the same boundary as audit_bot.  This prevents
    # storage from becoming an escape hatch around supervisor validation.
    from advisory_bots.contracts import assert_advisory_output
    assert_advisory_output(record)
    missing = [key for key in _ADVISORY_REQUIRED if key not in record or record[key] is None]
    if missing:
        raise ValueError(f"missing advisory fields: {', '.join(missing)}")
    if record.get("paper_only") is not True:
        raise ValueError("paper_only=true is required")
    if record.get("advisory_only") is not True:
        raise ValueError("advisory_only=true is required")
    if record.get("decision") not in _ADVISORY_DECISIONS:
        raise ValueError("decision is not an approved advisory value")
    if not isinstance(record.get("risk_flags"), list):
        raise ValueError("risk_flags must be a list")
    try:
        score = float(record["score"])
    except (TypeError, ValueError) as exc:
        raise ValueError("score must be numeric") from exc
    if score < 0 or score > 100:
        raise ValueError("score must be between 0 and 100")
    clean = dict(record)
    clean["score"] = round(score, 2)
    clean["id"] = clean.get("id") or _advisory_record_id(table, clean)
    return clean


def insert_advisory_record(table: str, record: Dict[str, Any]) -> bool:
    """Append one advisory record.  Returns false for an existing immutable key."""
    clean = _validate_advisory_record(table, record)

    def in_db(conn):
        _ensure_advisory_schema(conn)
        with conn.cursor() as cur:
            cur.execute(
                f"""INSERT INTO {table} (
                    id, observed_at, scan_id, symbol, bot_name, strategy_name,
                    score, decision, reason, data_quality, risk_flags,
                    build_id, config_hash, advisory_only, paper_only, record
                ) VALUES (
                    %(id)s, %(timestamp)s, %(scan_id)s, %(symbol)s, %(bot_name)s,
                    %(strategy_name)s, %(score)s, %(decision)s, %(reason)s,
                    %(data_quality)s, %(risk_flags)s, %(build_id)s, %(config_hash)s,
                    %(advisory_only)s, %(paper_only)s, %(record)s
                ) ON CONFLICT DO NOTHING""",
                {
                    **clean,
                    "data_quality": json.dumps(clean["data_quality"], default=str),
                    "risk_flags": json.dumps(clean["risk_flags"], default=str),
                    "record": json.dumps(clean, default=str),
                },
            )
            return cur.rowcount == 1

    def in_file():
        path = _ADVISORY_FILES[table]
        rows = _read_json(path, [])
        if any(row.get("id") == clean["id"] for row in rows):
            return False
        rows.append(clean)
        _write_json(path, rows)
        return True

    return _with_db(in_db, in_file)


def list_advisory_records(table: str, limit: int = 500) -> List[Dict[str, Any]]:
    """Read advisory evidence.  No update or delete operation exists."""
    if table not in ADVISORY_TABLES:
        raise ValueError(f"table is not approved for advisory storage: {table}")
    limit = max(1, min(int(limit), 5_000))

    def in_db(conn):
        _ensure_advisory_schema(conn)
        with conn.cursor() as cur:
            cur.execute(
                f"""SELECT record FROM {table}
                    ORDER BY observed_at DESC, created_at DESC LIMIT %s""",
                (limit,),
            )
            rows = cur.fetchall()
        out = []
        for (record,) in rows:
            out.append(json.loads(record) if isinstance(record, str) else record)
        return out

    def in_file():
        rows = _read_json(_ADVISORY_FILES[table], [])
        rows.sort(key=lambda item: str(item.get("timestamp") or ""), reverse=True)
        return rows[:limit]

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
