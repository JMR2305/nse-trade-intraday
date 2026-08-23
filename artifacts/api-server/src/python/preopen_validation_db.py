"""
preopen_validation_db.py — Phase 5B database layer.

Creates 5 isolated, additive tables:
  preopen_validation_sessions
  preopen_candidate_outcomes
  preopen_score_band_metrics
  preopen_factor_metrics
  preopen_daily_reports

Never modifies any existing table. Falls back gracefully when DB is unavailable.

PAPER TRADING / ADVISORY ONLY.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

try:
    from scan_state_store import db_available, _connect
except ImportError:
    def db_available() -> bool:
        return False
    def _connect():
        raise RuntimeError("DB not available")

_SCHEMA_READY = False


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _ensure_schema(conn) -> None:
    global _SCHEMA_READY
    if _SCHEMA_READY:
        return
    with conn.cursor() as cur:

        # preopen_validation_sessions
        cur.execute("""
            CREATE TABLE IF NOT EXISTS preopen_validation_sessions (
                session_id          TEXT PRIMARY KEY,
                trading_date        TEXT NOT NULL,
                phase5a_session_id  TEXT,
                status              TEXT NOT NULL DEFAULT 'PENDING',
                total_candidates    INTEGER DEFAULT 0,
                valid_candidates    INTEGER DEFAULT 0,
                excluded_candidates INTEGER DEFAULT 0,
                classified_candidates INTEGER DEFAULT 0,
                data_quality_pct    DOUBLE PRECISION DEFAULT 0,
                metrics_computed    BOOLEAN DEFAULT FALSE,
                daily_report_path   TEXT,
                created_at          TIMESTAMPTZ DEFAULT NOW(),
                updated_at          TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_val_sessions_date
            ON preopen_validation_sessions (trading_date DESC)
        """)

        # preopen_candidate_outcomes
        cur.execute("""
            CREATE TABLE IF NOT EXISTS preopen_candidate_outcomes (
                validation_id           TEXT PRIMARY KEY,
                trading_date            TEXT NOT NULL,
                session_id              TEXT REFERENCES preopen_validation_sessions(session_id),
                symbol                  TEXT NOT NULL,
                sector                  TEXT,
                preopen_rank            INTEGER,
                opportunity_score       DOUBLE PRECISION DEFAULT 0,
                classification          TEXT,
                previous_close          DOUBLE PRECISION,
                indicative_price        DOUBLE PRECISION,
                final_preopen_price     DOUBLE PRECISION,
                actual_open             DOUBLE PRECISION,
                price_0920              DOUBLE PRECISION,
                price_0930              DOUBLE PRECISION,
                price_1000              DOUBLE PRECISION,
                price_1030              DOUBLE PRECISION,
                intraday_high           DOUBLE PRECISION,
                intraday_low            DOUBLE PRECISION,
                closing_price           DOUBLE PRECISION,
                buy_quantity            BIGINT DEFAULT 0,
                sell_quantity           BIGINT DEFAULT 0,
                imbalance_percent       DOUBLE PRECISION DEFAULT 0,
                executed_quantity       BIGINT DEFAULT 0,
                liquidity_score         DOUBLE PRECISION DEFAULT 0,
                sector_score            DOUBLE PRECISION DEFAULT 0,
                index_context           DOUBLE PRECISION,
                vix_context             DOUBLE PRECISION,
                gap_percent             DOUBLE PRECISION,
                open_error_percent      DOUBLE PRECISION,
                return_0920             DOUBLE PRECISION,
                return_0930             DOUBLE PRECISION,
                return_1000             DOUBLE PRECISION,
                return_1030             DOUBLE PRECISION,
                max_favourable_excursion DOUBLE PRECISION,
                max_adverse_excursion   DOUBLE PRECISION,
                closing_return          DOUBLE PRECISION,
                continuation_flag       BOOLEAN DEFAULT FALSE,
                reversal_flag           BOOLEAN DEFAULT FALSE,
                prediction_result       TEXT,
                validation_status       TEXT DEFAULT 'PENDING',
                data_quality_status     TEXT DEFAULT 'MISSING',
                created_at              TIMESTAMPTZ DEFAULT NOW(),
                updated_at              TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_val_outcomes_date_sym
            ON preopen_candidate_outcomes (trading_date, symbol)
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_val_outcomes_session
            ON preopen_candidate_outcomes (session_id)
        """)
        cur.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_val_outcomes_date_sym_unique
            ON preopen_candidate_outcomes (trading_date, symbol)
        """)

        # preopen_score_band_metrics
        cur.execute("""
            CREATE TABLE IF NOT EXISTS preopen_score_band_metrics (
                id              BIGSERIAL PRIMARY KEY,
                session_id      TEXT REFERENCES preopen_validation_sessions(session_id),
                trading_date    TEXT NOT NULL,
                band            TEXT NOT NULL,
                score_min       INTEGER,
                score_max       INTEGER,
                candidates      INTEGER DEFAULT 0,
                continuation_rate DOUBLE PRECISION,
                reversal_rate   DOUBLE PRECISION,
                avg_return_0930 DOUBLE PRECISION,
                avg_return_1030 DOUBLE PRECISION,
                avg_closing_return DOUBLE PRECISION,
                avg_mfe         DOUBLE PRECISION,
                avg_mae         DOUBLE PRECISION,
                inconclusive    BOOLEAN DEFAULT TRUE,
                created_at      TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_val_score_bands_date
            ON preopen_score_band_metrics (trading_date DESC)
        """)

        # preopen_factor_metrics
        cur.execute("""
            CREATE TABLE IF NOT EXISTS preopen_factor_metrics (
                id              BIGSERIAL PRIMARY KEY,
                session_id      TEXT REFERENCES preopen_validation_sessions(session_id),
                trading_date    TEXT NOT NULL,
                factor          TEXT NOT NULL,
                sample_size     INTEGER DEFAULT 0,
                factor_success_rate   DOUBLE PRECISION,
                factor_avg_return     DOUBLE PRECISION,
                factor_failure_rate   DOUBLE PRECISION,
                factor_reliability_score DOUBLE PRECISION,
                inconclusive    BOOLEAN DEFAULT TRUE,
                created_at      TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_val_factor_metrics_date
            ON preopen_factor_metrics (trading_date DESC)
        """)

        # preopen_daily_reports
        cur.execute("""
            CREATE TABLE IF NOT EXISTS preopen_daily_reports (
                id              BIGSERIAL PRIMARY KEY,
                session_id      TEXT REFERENCES preopen_validation_sessions(session_id),
                trading_date    TEXT NOT NULL UNIQUE,
                metrics_json    JSONB NOT NULL,
                score_bands_json JSONB,
                factor_metrics_json JSONB,
                sector_breakdown_json JSONB,
                report_md_path  TEXT,
                report_json_path TEXT,
                generated_at    TIMESTAMPTZ DEFAULT NOW(),
                created_at      TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_val_daily_reports_date
            ON preopen_daily_reports (trading_date DESC)
        """)

    conn.commit()
    _SCHEMA_READY = True


def _with_db(fn, fallback=None):
    if not db_available():
        return fallback() if callable(fallback) else fallback
    try:
        conn = _connect()
        try:
            _ensure_schema(conn)
            return fn(conn)
        finally:
            conn.close()
    except Exception:
        return fallback() if callable(fallback) else fallback


# ── Session CRUD ──────────────────────────────────────────────────────────────

def _forward_session_status(existing: str, incoming: Optional[str]) -> str:
    """Mirror the SQL upsert lifecycle guard for focused policy tests."""
    incoming = incoming or "PENDING"
    if existing in ("COMPLETE", "NO_CANDIDATES"):
        return existing
    if incoming == "PENDING" and existing != "PENDING":
        return existing
    return incoming


def upsert_validation_session(session: dict) -> None:
    def to_db(conn):
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO preopen_validation_sessions
                    (session_id, trading_date, phase5a_session_id, status,
                     total_candidates, valid_candidates, excluded_candidates,
                     classified_candidates, data_quality_pct, metrics_computed,
                     daily_report_path, updated_at)
                VALUES (%s,%s,%s,COALESCE(%s, 'PENDING'),%s,%s,%s,%s,%s,%s,%s,NOW())
                ON CONFLICT (session_id) DO UPDATE SET
                    phase5a_session_id=COALESCE(EXCLUDED.phase5a_session_id, preopen_validation_sessions.phase5a_session_id),
                    -- EOD terminal outcomes are immutable.  Partial
                    -- checkpoint writes may update their supplied counts but
                    -- must not reopen COMPLETE/NO_CANDIDATES sessions.
                    status=CASE
                        WHEN preopen_validation_sessions.status IN ('COMPLETE', 'NO_CANDIDATES')
                            THEN preopen_validation_sessions.status
                        WHEN EXCLUDED.status = 'PENDING'
                             AND preopen_validation_sessions.status <> 'PENDING'
                            THEN preopen_validation_sessions.status
                        ELSE EXCLUDED.status
                    END,
                    total_candidates=COALESCE(EXCLUDED.total_candidates, preopen_validation_sessions.total_candidates),
                    valid_candidates=COALESCE(EXCLUDED.valid_candidates, preopen_validation_sessions.valid_candidates),
                    excluded_candidates=COALESCE(EXCLUDED.excluded_candidates, preopen_validation_sessions.excluded_candidates),
                    classified_candidates=COALESCE(EXCLUDED.classified_candidates, preopen_validation_sessions.classified_candidates),
                    data_quality_pct=COALESCE(EXCLUDED.data_quality_pct, preopen_validation_sessions.data_quality_pct),
                    metrics_computed=COALESCE(EXCLUDED.metrics_computed, preopen_validation_sessions.metrics_computed),
                    daily_report_path=COALESCE(EXCLUDED.daily_report_path, preopen_validation_sessions.daily_report_path),
                    updated_at=NOW()
            """, [
                session.get("session_id"), session.get("trading_date"),
                session.get("phase5a_session_id"),
                session.get("status"),
                session.get("total_candidates"),
                session.get("valid_candidates"),
                session.get("excluded_candidates"),
                session.get("classified_candidates"),
                session.get("data_quality_pct"),
                session.get("metrics_computed"),
                session.get("daily_report_path"),
            ])
        conn.commit()
    _with_db(to_db)


def get_validation_sessions(limit: int = 10) -> List[dict]:
    def from_db(conn):
        with conn.cursor() as cur:
            cur.execute("""
                SELECT * FROM preopen_validation_sessions
                ORDER BY trading_date DESC LIMIT %s
            """, [limit])
            cols = [d[0] for d in cur.description]
            rows = cur.fetchall()
            result = []
            for row in rows:
                d = dict(zip(cols, row))
                for k, v in d.items():
                    if isinstance(v, datetime):
                        d[k] = v.isoformat()
                result.append(d)
            return result
    return _with_db(from_db) or []


# ── Candidate outcome CRUD ────────────────────────────────────────────────────

def upsert_candidate_outcome(record: dict) -> None:
    def to_db(conn):
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO preopen_candidate_outcomes
                    (validation_id, trading_date, session_id, symbol, sector,
                     preopen_rank, opportunity_score, classification,
                     previous_close, indicative_price, final_preopen_price,
                     actual_open, price_0920, price_0930, price_1000, price_1030,
                     intraday_high, intraday_low, closing_price,
                     buy_quantity, sell_quantity, imbalance_percent, executed_quantity,
                     liquidity_score, sector_score, index_context, vix_context, gap_percent,
                     open_error_percent, return_0920, return_0930, return_1000, return_1030,
                     max_favourable_excursion, max_adverse_excursion, closing_return,
                     continuation_flag, reversal_flag, prediction_result,
                     validation_status, data_quality_status, updated_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                        %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW())
                ON CONFLICT (trading_date, symbol) DO UPDATE SET
                    actual_open=EXCLUDED.actual_open,
                    price_0920=EXCLUDED.price_0920,
                    price_0930=EXCLUDED.price_0930,
                    price_1000=EXCLUDED.price_1000,
                    price_1030=EXCLUDED.price_1030,
                    intraday_high=EXCLUDED.intraday_high,
                    intraday_low=EXCLUDED.intraday_low,
                    closing_price=EXCLUDED.closing_price,
                    return_0920=EXCLUDED.return_0920,
                    return_0930=EXCLUDED.return_0930,
                    return_1000=EXCLUDED.return_1000,
                    return_1030=EXCLUDED.return_1030,
                    max_favourable_excursion=EXCLUDED.max_favourable_excursion,
                    max_adverse_excursion=EXCLUDED.max_adverse_excursion,
                    closing_return=EXCLUDED.closing_return,
                    continuation_flag=EXCLUDED.continuation_flag,
                    reversal_flag=EXCLUDED.reversal_flag,
                    prediction_result=EXCLUDED.prediction_result,
                    validation_status=EXCLUDED.validation_status,
                    data_quality_status=EXCLUDED.data_quality_status,
                    updated_at=NOW()
            """, [
                record.get("validation_id"), record.get("trading_date"),
                record.get("session_id"), record.get("symbol"), record.get("sector"),
                record.get("preopen_rank"), record.get("opportunity_score", 0),
                record.get("classification"),
                record.get("previous_close"), record.get("indicative_price"),
                record.get("final_preopen_price"), record.get("actual_open"),
                record.get("price_0920"), record.get("price_0930"),
                record.get("price_1000"), record.get("price_1030"),
                record.get("intraday_high"), record.get("intraday_low"),
                record.get("closing_price"),
                record.get("buy_quantity", 0), record.get("sell_quantity", 0),
                record.get("imbalance_percent", 0), record.get("executed_quantity", 0),
                record.get("liquidity_score", 0), record.get("sector_score", 0),
                record.get("index_context"), record.get("vix_context"),
                record.get("gap_percent"),
                record.get("open_error_percent"), record.get("return_0920"),
                record.get("return_0930"), record.get("return_1000"), record.get("return_1030"),
                record.get("max_favourable_excursion"), record.get("max_adverse_excursion"),
                record.get("closing_return"),
                record.get("continuation_flag", False), record.get("reversal_flag", False),
                record.get("prediction_result"),
                record.get("validation_status", "PENDING"),
                record.get("data_quality_status", "MISSING"),
            ])
        conn.commit()
    _with_db(to_db)


def get_candidate_outcomes(trading_date: Optional[str] = None,
                            limit: int = 200) -> List[dict]:
    def from_db(conn):
        with conn.cursor() as cur:
            if trading_date:
                cur.execute("""
                    SELECT * FROM preopen_candidate_outcomes
                    WHERE trading_date = %s
                    ORDER BY preopen_rank ASC NULLS LAST, opportunity_score DESC
                    LIMIT %s
                """, [trading_date, limit])
            else:
                cur.execute("""
                    SELECT * FROM preopen_candidate_outcomes
                    WHERE trading_date = (
                        SELECT MAX(trading_date) FROM preopen_candidate_outcomes
                    )
                    ORDER BY preopen_rank ASC NULLS LAST, opportunity_score DESC
                    LIMIT %s
                """, [limit])
            cols = [d[0] for d in cur.description]
            rows = cur.fetchall()
            result = []
            for row in rows:
                d = dict(zip(cols, row))
                for k, v in d.items():
                    if isinstance(v, datetime):
                        d[k] = v.isoformat()
                result.append(d)
            return result
    return _with_db(from_db) or []


def get_candidate_outcome_symbol(trading_date: str, symbol: str) -> Optional[dict]:
    def from_db(conn):
        with conn.cursor() as cur:
            cur.execute("""
                SELECT * FROM preopen_candidate_outcomes
                WHERE trading_date = %s AND symbol = %s
            """, [trading_date, symbol.upper()])
            row = cur.fetchone()
            if not row:
                return None
            cols = [d[0] for d in cur.description]
            d = dict(zip(cols, row))
            for k, v in d.items():
                if isinstance(v, datetime):
                    d[k] = v.isoformat()
            return d
    return _with_db(from_db)


# ── Score band + factor metrics ───────────────────────────────────────────────

def save_score_band_metrics(session_id: str, trading_date: str,
                             bands: List[dict]) -> None:
    def to_db(conn):
        with conn.cursor() as cur:
            for b in bands:
                cur.execute("""
                    INSERT INTO preopen_score_band_metrics
                        (session_id, trading_date, band, score_min, score_max,
                         candidates, continuation_rate, reversal_rate,
                         avg_return_0930, avg_return_1030, avg_closing_return,
                         avg_mfe, avg_mae, inconclusive)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                """, [
                    session_id, trading_date, b.get("band"),
                    b.get("score_min"), b.get("score_max"),
                    b.get("candidates", 0),
                    b.get("continuation_rate"), b.get("reversal_rate"),
                    b.get("avg_return_0930"), b.get("avg_return_1030"),
                    b.get("avg_closing_return"), b.get("avg_mfe"), b.get("avg_mae"),
                    b.get("inconclusive", True),
                ])
        conn.commit()
    _with_db(to_db)


def get_score_band_metrics(trading_date: Optional[str] = None) -> List[dict]:
    def from_db(conn):
        with conn.cursor() as cur:
            if trading_date:
                cur.execute("""
                    SELECT * FROM preopen_score_band_metrics WHERE trading_date = %s
                    ORDER BY score_min DESC
                """, [trading_date])
            else:
                cur.execute("""
                    SELECT * FROM preopen_score_band_metrics
                    WHERE trading_date = (SELECT MAX(trading_date) FROM preopen_score_band_metrics)
                    ORDER BY score_min DESC
                """)
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]
    return _with_db(from_db) or []


def save_factor_metrics(session_id: str, trading_date: str,
                         factors: List[dict]) -> None:
    def to_db(conn):
        with conn.cursor() as cur:
            for f in factors:
                cur.execute("""
                    INSERT INTO preopen_factor_metrics
                        (session_id, trading_date, factor, sample_size,
                         factor_success_rate, factor_avg_return, factor_failure_rate,
                         factor_reliability_score, inconclusive)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                """, [
                    session_id, trading_date, f.get("factor"),
                    f.get("sample_size", 0),
                    f.get("factor_success_rate"), f.get("factor_avg_return"),
                    f.get("factor_failure_rate"), f.get("factor_reliability_score"),
                    f.get("inconclusive", True),
                ])
        conn.commit()
    _with_db(to_db)


def get_factor_metrics(trading_date: Optional[str] = None) -> List[dict]:
    def from_db(conn):
        with conn.cursor() as cur:
            if trading_date:
                cur.execute("""
                    SELECT * FROM preopen_factor_metrics WHERE trading_date = %s
                    ORDER BY factor
                """, [trading_date])
            else:
                cur.execute("""
                    SELECT * FROM preopen_factor_metrics
                    WHERE trading_date = (SELECT MAX(trading_date) FROM preopen_factor_metrics)
                    ORDER BY factor
                """)
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]
    return _with_db(from_db) or []


# ── Daily report storage ──────────────────────────────────────────────────────

def save_daily_report(session_id: str, trading_date: str,
                       metrics: dict, score_bands: list, factor_metrics: list,
                       sector_breakdown: list, json_path: Optional[str],
                       md_path: Optional[str]) -> None:
    def to_db(conn):
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO preopen_daily_reports
                    (session_id, trading_date, metrics_json, score_bands_json,
                     factor_metrics_json, sector_breakdown_json,
                     report_json_path, report_md_path)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (trading_date) DO UPDATE SET
                    metrics_json=EXCLUDED.metrics_json,
                    score_bands_json=EXCLUDED.score_bands_json,
                    factor_metrics_json=EXCLUDED.factor_metrics_json,
                    sector_breakdown_json=EXCLUDED.sector_breakdown_json,
                    report_json_path=EXCLUDED.report_json_path,
                    report_md_path=EXCLUDED.report_md_path,
                    generated_at=NOW()
            """, [
                session_id, trading_date,
                json.dumps(metrics), json.dumps(score_bands),
                json.dumps(factor_metrics), json.dumps(sector_breakdown),
                json_path, md_path,
            ])
        conn.commit()
    _with_db(to_db)


def get_daily_reports(limit: int = 10) -> List[dict]:
    def from_db(conn):
        with conn.cursor() as cur:
            cur.execute("""
                SELECT trading_date, metrics_json, score_bands_json,
                       factor_metrics_json, sector_breakdown_json,
                       report_json_path, report_md_path, generated_at
                FROM preopen_daily_reports
                ORDER BY trading_date DESC LIMIT %s
            """, [limit])
            cols = [d[0] for d in cur.description]
            rows = cur.fetchall()
            result = []
            for row in rows:
                d = dict(zip(cols, row))
                for k, v in d.items():
                    if isinstance(v, datetime):
                        d[k] = v.isoformat()
                result.append(d)
            return result
    return _with_db(from_db) or []
