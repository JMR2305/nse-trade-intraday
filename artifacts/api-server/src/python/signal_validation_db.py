"""
signal_validation_db.py — Phase 5C database layer.

Creates and manages 10 isolated additive tables.
Zero modifications to existing orders/trades/portfolio/strategy tables.

Tables:
  signal_validation_sessions
  signal_validation_records
  signal_lifecycle_events
  signal_price_checkpoints
  signal_strategy_metrics
  signal_ai_metrics
  signal_preopen_metrics
  signal_risk_metrics
  signal_regime_metrics
  signal_daily_reports

PAPER TRADING / ADVISORY ONLY.
"""
from __future__ import annotations

import json
import os
from decimal import Decimal
from typing import Any, Dict, List, Optional

_DB_URL = os.environ.get("DATABASE_URL")


def _get_conn():
    import psycopg2
    return psycopg2.connect(_DB_URL)


def _db_available() -> bool:
    return bool(_DB_URL)


# ── Schema creation ────────────────────────────────────────────────────────────

_DDL = """
-- Phase 5C: Signal Validation Sessions
CREATE TABLE IF NOT EXISTS signal_validation_sessions (
    session_id          TEXT PRIMARY KEY,
    trading_date        DATE NOT NULL,
    status              TEXT NOT NULL DEFAULT 'ACTIVE',
    signals_generated   INTEGER DEFAULT 0,
    signals_approved    INTEGER DEFAULT 0,
    paper_trades        INTEGER DEFAULT 0,
    risk_rejections     INTEGER DEFAULT 0,
    win_count           INTEGER DEFAULT 0,
    loss_count          INTEGER DEFAULT 0,
    win_rate            DOUBLE PRECISION,
    expectancy          DOUBLE PRECISION,
    false_positives     INTEGER DEFAULT 0,
    missed_opportunities INTEGER DEFAULT 0,
    data_completeness_pct DOUBLE PRECISION,
    daily_report_path   TEXT,
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ DEFAULT NOW()
);

-- Phase 5C: Signal Validation Records (41+ fields)
CREATE TABLE IF NOT EXISTS signal_validation_records (
    validation_id              TEXT PRIMARY KEY,
    trading_date               DATE NOT NULL,
    session_id                 TEXT REFERENCES signal_validation_sessions(session_id),
    signal_id                  TEXT NOT NULL,
    audit_id                   TEXT,
    journal_id                 TEXT,
    strategy_id                TEXT,
    strategy_name              TEXT,
    strategy_version           TEXT,
    symbol                     TEXT NOT NULL,
    sector                     TEXT,
    exchange                   TEXT DEFAULT 'NSE',
    signal_direction           TEXT,
    signal_type                TEXT,
    signal_timestamp_ist       TIMESTAMPTZ,
    signal_price               NUMERIC(14,4),
    signal_strength            NUMERIC(8,4),
    deterministic_score        NUMERIC(8,4),
    ai_recommendation          TEXT,
    ai_confidence              NUMERIC(8,4),
    ai_agreement               TEXT,
    ai_explanation_latency_ms  INTEGER,
    preopen_rank               INTEGER,
    preopen_opportunity_score  NUMERIC(8,4),
    preopen_classification     TEXT,
    market_regime              TEXT,
    index_direction            TEXT,
    sector_direction           TEXT,
    india_vix_value            NUMERIC(8,4),
    volume                     BIGINT,
    relative_volume            NUMERIC(8,4),
    vwap                       NUMERIC(14,4),
    atr                        NUMERIC(14,4),
    spread                     NUMERIC(14,4),
    liquidity_score            NUMERIC(8,4),
    data_age_seconds           INTEGER,
    data_quality_status        TEXT DEFAULT 'UNKNOWN',
    risk_decision              TEXT,
    risk_rejection_reason      TEXT,
    proposed_position_size     INTEGER,
    approved_position_size     INTEGER,
    paper_order_created        BOOLEAN DEFAULT FALSE,
    paper_order_id             TEXT,
    entry_price                NUMERIC(14,4),
    entry_timestamp            TIMESTAMPTZ,
    stop_loss                  NUMERIC(14,4),
    target_price               NUMERIC(14,4),
    exit_price                 NUMERIC(14,4),
    exit_timestamp             TIMESTAMPTZ,
    exit_reason                TEXT,
    realised_pnl               NUMERIC(14,4),
    unrealised_pnl             NUMERIC(14,4),
    r_multiple                 NUMERIC(8,4),
    max_favourable_excursion   NUMERIC(14,4),
    max_adverse_excursion      NUMERIC(14,4),
    price_5m                   NUMERIC(14,4),
    price_15m                  NUMERIC(14,4),
    price_30m                  NUMERIC(14,4),
    price_60m                  NUMERIC(14,4),
    end_of_day_price           NUMERIC(14,4),
    outcome_class              TEXT,
    validation_status          TEXT NOT NULL DEFAULT 'GENERATED',
    missed_reason              TEXT,
    is_hypothetical            BOOLEAN DEFAULT FALSE,
    hypothetical_label         TEXT,
    hyp_return_5m              NUMERIC(8,4),
    hyp_return_15m             NUMERIC(8,4),
    hyp_return_30m             NUMERIC(8,4),
    hyp_return_60m             NUMERIC(8,4),
    hyp_mfe                    NUMERIC(8,4),
    hyp_mae                    NUMERIC(8,4),
    hyp_rejection_justified    BOOLEAN,
    created_at                 TIMESTAMPTZ DEFAULT NOW(),
    updated_at                 TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (trading_date, signal_id)
);
CREATE INDEX IF NOT EXISTS idx_svr_trading_date    ON signal_validation_records(trading_date);
CREATE INDEX IF NOT EXISTS idx_svr_symbol          ON signal_validation_records(symbol);
CREATE INDEX IF NOT EXISTS idx_svr_strategy        ON signal_validation_records(strategy_id);
CREATE INDEX IF NOT EXISTS idx_svr_validation_status ON signal_validation_records(validation_status);
CREATE INDEX IF NOT EXISTS idx_svr_outcome_class   ON signal_validation_records(outcome_class);

-- Phase 5C: Lifecycle Events (full audit trail)
CREATE TABLE IF NOT EXISTS signal_lifecycle_events (
    event_id           TEXT PRIMARY KEY,
    validation_id      TEXT NOT NULL REFERENCES signal_validation_records(validation_id) ON DELETE CASCADE,
    from_state         TEXT NOT NULL,
    to_state           TEXT NOT NULL,
    timestamp_ist      TIMESTAMPTZ NOT NULL,
    reason             TEXT,
    source_component   TEXT,
    correlation_id     TEXT,
    metadata           JSONB DEFAULT '{}',
    created_at         TIMESTAMPTZ DEFAULT NOW()
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_sle_validation_state_ts
    ON signal_lifecycle_events(validation_id, to_state, timestamp_ist);
CREATE INDEX IF NOT EXISTS idx_sle_validation_id ON signal_lifecycle_events(validation_id);

-- Phase 5C: Price Checkpoints
CREATE TABLE IF NOT EXISTS signal_price_checkpoints (
    id               SERIAL PRIMARY KEY,
    validation_id    TEXT NOT NULL REFERENCES signal_validation_records(validation_id) ON DELETE CASCADE,
    checkpoint_type  TEXT NOT NULL,
    price            NUMERIC(14,4),
    timestamp_ist    TIMESTAMPTZ,
    source           TEXT,
    is_hypothetical  BOOLEAN DEFAULT FALSE,
    return_pct       NUMERIC(8,4),
    created_at       TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (validation_id, checkpoint_type)
);

-- Phase 5C: Strategy Attribution Metrics
CREATE TABLE IF NOT EXISTS signal_strategy_metrics (
    id                  SERIAL PRIMARY KEY,
    trading_date        DATE NOT NULL,
    session_id          TEXT,
    strategy_id         TEXT NOT NULL,
    strategy_name       TEXT,
    strategy_version    TEXT,
    grouping_key        TEXT NOT NULL,  -- e.g. "strategy", "sector", "regime"
    grouping_value      TEXT NOT NULL,  -- e.g. "RSI_DIVERGENCE", "BANKING", "BULLISH"
    signals_generated   INTEGER DEFAULT 0,
    signals_approved    INTEGER DEFAULT 0,
    paper_trades        INTEGER DEFAULT 0,
    closed_trades       INTEGER DEFAULT 0,
    win_count           INTEGER DEFAULT 0,
    loss_count          INTEGER DEFAULT 0,
    win_rate            DOUBLE PRECISION,
    loss_rate           DOUBLE PRECISION,
    avg_return          DOUBLE PRECISION,
    median_return       DOUBLE PRECISION,
    avg_r_multiple      DOUBLE PRECISION,
    profit_factor       DOUBLE PRECISION,
    expectancy          DOUBLE PRECISION,
    avg_mfe             DOUBLE PRECISION,
    avg_mae             DOUBLE PRECISION,
    max_drawdown_contrib DOUBLE PRECISION,
    false_positive_rate DOUBLE PRECISION,
    missed_opp_rate     DOUBLE PRECISION,
    sample_size         INTEGER DEFAULT 0,
    confidence_level    TEXT,
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (trading_date, strategy_id, grouping_key, grouping_value)
);

-- Phase 5C: AI Attribution Metrics
CREATE TABLE IF NOT EXISTS signal_ai_metrics (
    id                  SERIAL PRIMARY KEY,
    trading_date        DATE NOT NULL,
    session_id          TEXT,
    agreement_group     TEXT NOT NULL,  -- AGREE|DISAGREE|WATCH|NO_RESULT|STALE
    signals_count       INTEGER DEFAULT 0,
    continuation_rate   DOUBLE PRECISION,
    reversal_rate       DOUBLE PRECISION,
    win_rate            DOUBLE PRECISION,
    expectancy          DOUBLE PRECISION,
    avg_mfe             DOUBLE PRECISION,
    avg_mae             DOUBLE PRECISION,
    false_positive_rate DOUBLE PRECISION,
    missed_opp_rate     DOUBLE PRECISION,
    avg_latency_ms      DOUBLE PRECISION,
    sample_size         INTEGER DEFAULT 0,
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (trading_date, agreement_group)
);

-- Phase 5C: Pre-Open Attribution Metrics
CREATE TABLE IF NOT EXISTS signal_preopen_metrics (
    id                  SERIAL PRIMARY KEY,
    trading_date        DATE NOT NULL,
    session_id          TEXT,
    confirmation_group  TEXT NOT NULL,  -- STRONG|MODERATE|CONFLICTING|NONE|STALE
    signals_count       INTEGER DEFAULT 0,
    win_rate            DOUBLE PRECISION,
    expectancy          DOUBLE PRECISION,
    avg_r_multiple      DOUBLE PRECISION,
    avg_mfe             DOUBLE PRECISION,
    avg_mae             DOUBLE PRECISION,
    sample_size         INTEGER DEFAULT 0,
    predictive_value_declared BOOLEAN DEFAULT FALSE,
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (trading_date, confirmation_group)
);

-- Phase 5C: Risk Attribution Metrics
CREATE TABLE IF NOT EXISTS signal_risk_metrics (
    id                  SERIAL PRIMARY KEY,
    trading_date        DATE NOT NULL,
    session_id          TEXT,
    risk_decision       TEXT NOT NULL,  -- APPROVED|REJECTED|etc.
    rejection_reason    TEXT,
    signals_count       INTEGER DEFAULT 0,
    hypothetical_win_rate DOUBLE PRECISION,
    rejection_justified_rate DOUBLE PRECISION,
    sample_size         INTEGER DEFAULT 0,
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (trading_date, risk_decision, rejection_reason)
);
-- Expression-based uniqueness for risk_metrics (handles NULLs via partial index)
CREATE UNIQUE INDEX IF NOT EXISTS idx_srisk_unique_no_reason
    ON signal_risk_metrics(trading_date, risk_decision)
    WHERE rejection_reason IS NULL;
CREATE UNIQUE INDEX IF NOT EXISTS idx_srisk_unique_with_reason
    ON signal_risk_metrics(trading_date, risk_decision, rejection_reason)
    WHERE rejection_reason IS NOT NULL;

-- Phase 5C: Regime Attribution Metrics
CREATE TABLE IF NOT EXISTS signal_regime_metrics (
    id                  SERIAL PRIMARY KEY,
    trading_date        DATE NOT NULL,
    session_id          TEXT,
    regime              TEXT NOT NULL,
    strategy_id         TEXT,
    signals_count       INTEGER DEFAULT 0,
    win_rate            DOUBLE PRECISION,
    expectancy          DOUBLE PRECISION,
    avg_r_multiple      DOUBLE PRECISION,
    sample_size         INTEGER DEFAULT 0,
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (trading_date, regime, strategy_id)
);
-- Expression-based uniqueness for regime_metrics (handles NULLs via partial index)
CREATE UNIQUE INDEX IF NOT EXISTS idx_sregime_unique_no_strategy
    ON signal_regime_metrics(trading_date, regime)
    WHERE strategy_id IS NULL;
CREATE UNIQUE INDEX IF NOT EXISTS idx_sregime_unique_with_strategy
    ON signal_regime_metrics(trading_date, regime, strategy_id)
    WHERE strategy_id IS NOT NULL;

-- Phase 5C: Daily Reports
CREATE TABLE IF NOT EXISTS signal_daily_reports (
    id              SERIAL PRIMARY KEY,
    trading_date    DATE NOT NULL UNIQUE,
    session_id      TEXT,
    report_json     JSONB,
    report_md       TEXT,
    report_json_path TEXT,
    report_md_path   TEXT,
    five_day_report_json JSONB,
    five_day_report_md   TEXT,
    five_day_verdict     TEXT,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);
"""

_schema_created = False


def ensure_schema() -> None:
    global _schema_created
    if _schema_created or not _db_available():
        return
    import logging
    _log = logging.getLogger("signal_validation_db")
    try:
        conn = _get_conn()
        with conn:
            with conn.cursor() as cur:
                for stmt in _DDL.split(";"):
                    s = stmt.strip()
                    if s:
                        try:
                            cur.execute(s)
                        except Exception as stmt_err:
                            _log.error(
                                "Phase 5C schema DDL statement failed: %s | stmt=%.120s",
                                stmt_err, s,
                            )
                            raise  # re-raise so the outer try marks as not created
        conn.close()
        _schema_created = True
        _log.info("Phase 5C signal validation schema ready")
    except Exception as e:
        _log.error("Phase 5C ensure_schema failed — validation DB unavailable: %s", e)


# ── CRUD helpers ───────────────────────────────────────────────────────────────

def _row_to_dict(cur, row) -> dict:
    cols = [d[0] for d in cur.description]
    return dict(zip(cols, row))


def upsert_session(data: dict) -> None:
    if not _db_available():
        return
    ensure_schema()
    try:
        conn = _get_conn()
        with conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO signal_validation_sessions
                        (session_id, trading_date, status)
                    VALUES (%(session_id)s, %(trading_date)s, %(status)s)
                    ON CONFLICT (session_id) DO UPDATE SET
                        status              = COALESCE(EXCLUDED.status, signal_validation_sessions.status),
                        signals_generated   = COALESCE(%(signals_generated)s, signal_validation_sessions.signals_generated),
                        signals_approved    = COALESCE(%(signals_approved)s, signal_validation_sessions.signals_approved),
                        paper_trades        = COALESCE(%(paper_trades)s, signal_validation_sessions.paper_trades),
                        risk_rejections     = COALESCE(%(risk_rejections)s, signal_validation_sessions.risk_rejections),
                        win_count           = COALESCE(%(win_count)s, signal_validation_sessions.win_count),
                        loss_count          = COALESCE(%(loss_count)s, signal_validation_sessions.loss_count),
                        win_rate            = COALESCE(%(win_rate)s, signal_validation_sessions.win_rate),
                        expectancy          = COALESCE(%(expectancy)s, signal_validation_sessions.expectancy),
                        false_positives     = COALESCE(%(false_positives)s, signal_validation_sessions.false_positives),
                        missed_opportunities = COALESCE(%(missed_opportunities)s, signal_validation_sessions.missed_opportunities),
                        data_completeness_pct = COALESCE(%(data_completeness_pct)s, signal_validation_sessions.data_completeness_pct),
                        daily_report_path   = COALESCE(%(daily_report_path)s, signal_validation_sessions.daily_report_path),
                        updated_at          = NOW()
                """, {
                    "session_id": data.get("session_id"),
                    "trading_date": data.get("trading_date"),
                    "status": data.get("status", "ACTIVE"),
                    "signals_generated": data.get("signals_generated"),
                    "signals_approved": data.get("signals_approved"),
                    "paper_trades": data.get("paper_trades"),
                    "risk_rejections": data.get("risk_rejections"),
                    "win_count": data.get("win_count"),
                    "loss_count": data.get("loss_count"),
                    "win_rate": data.get("win_rate"),
                    "expectancy": data.get("expectancy"),
                    "false_positives": data.get("false_positives"),
                    "missed_opportunities": data.get("missed_opportunities"),
                    "data_completeness_pct": data.get("data_completeness_pct"),
                    "daily_report_path": data.get("daily_report_path"),
                })
        conn.close()
    except Exception:
        pass


def upsert_record(rec: dict) -> None:
    """Upsert a signal_validation_record. Unique on (trading_date, signal_id)."""
    if not _db_available():
        return
    ensure_schema()
    try:
        conn = _get_conn()
        with conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO signal_validation_records (
                        validation_id, trading_date, session_id, signal_id,
                        audit_id, journal_id, strategy_id, strategy_name, strategy_version,
                        symbol, sector, exchange,
                        signal_direction, signal_type, signal_timestamp_ist,
                        signal_price, signal_strength, deterministic_score,
                        ai_recommendation, ai_confidence, ai_agreement, ai_explanation_latency_ms,
                        preopen_rank, preopen_opportunity_score, preopen_classification,
                        market_regime, index_direction, sector_direction, india_vix_value,
                        volume, relative_volume, vwap, atr, spread, liquidity_score,
                        data_age_seconds, data_quality_status,
                        risk_decision, risk_rejection_reason,
                        proposed_position_size, approved_position_size,
                        paper_order_created, paper_order_id,
                        entry_price, entry_timestamp, stop_loss, target_price,
                        exit_price, exit_timestamp, exit_reason,
                        realised_pnl, unrealised_pnl, r_multiple,
                        max_favourable_excursion, max_adverse_excursion,
                        price_5m, price_15m, price_30m, price_60m, end_of_day_price,
                        outcome_class, validation_status, missed_reason,
                        is_hypothetical, hypothetical_label,
                        hyp_return_5m, hyp_return_15m, hyp_return_30m, hyp_return_60m,
                        hyp_mfe, hyp_mae, hyp_rejection_justified
                    ) VALUES (
                        %(validation_id)s, %(trading_date)s, %(session_id)s, %(signal_id)s,
                        %(audit_id)s, %(journal_id)s, %(strategy_id)s, %(strategy_name)s, %(strategy_version)s,
                        %(symbol)s, %(sector)s, %(exchange)s,
                        %(signal_direction)s, %(signal_type)s, %(signal_timestamp_ist)s,
                        %(signal_price)s, %(signal_strength)s, %(deterministic_score)s,
                        %(ai_recommendation)s, %(ai_confidence)s, %(ai_agreement)s, %(ai_explanation_latency_ms)s,
                        %(preopen_rank)s, %(preopen_opportunity_score)s, %(preopen_classification)s,
                        %(market_regime)s, %(index_direction)s, %(sector_direction)s, %(india_vix_value)s,
                        %(volume)s, %(relative_volume)s, %(vwap)s, %(atr)s, %(spread)s, %(liquidity_score)s,
                        %(data_age_seconds)s, %(data_quality_status)s,
                        %(risk_decision)s, %(risk_rejection_reason)s,
                        %(proposed_position_size)s, %(approved_position_size)s,
                        %(paper_order_created)s, %(paper_order_id)s,
                        %(entry_price)s, %(entry_timestamp)s, %(stop_loss)s, %(target_price)s,
                        %(exit_price)s, %(exit_timestamp)s, %(exit_reason)s,
                        %(realised_pnl)s, %(unrealised_pnl)s, %(r_multiple)s,
                        %(max_favourable_excursion)s, %(max_adverse_excursion)s,
                        %(price_5m)s, %(price_15m)s, %(price_30m)s, %(price_60m)s, %(end_of_day_price)s,
                        %(outcome_class)s, %(validation_status)s, %(missed_reason)s,
                        %(is_hypothetical)s, %(hypothetical_label)s,
                        %(hyp_return_5m)s, %(hyp_return_15m)s, %(hyp_return_30m)s, %(hyp_return_60m)s,
                        %(hyp_mfe)s, %(hyp_mae)s, %(hyp_rejection_justified)s
                    )
                    ON CONFLICT (trading_date, signal_id) DO UPDATE SET
                        -- Always overwrite the status — this is the primary lifecycle field
                        validation_status           = EXCLUDED.validation_status,
                        -- Outcome / classification
                        outcome_class               = COALESCE(EXCLUDED.outcome_class, signal_validation_records.outcome_class),
                        missed_reason               = COALESCE(EXCLUDED.missed_reason, signal_validation_records.missed_reason),
                        -- Risk decision fields (written on risk-review/rejection transition)
                        risk_decision               = COALESCE(EXCLUDED.risk_decision, signal_validation_records.risk_decision),
                        risk_rejection_reason       = COALESCE(EXCLUDED.risk_rejection_reason, signal_validation_records.risk_rejection_reason),
                        -- Hypothetical / missed-signal metadata
                        is_hypothetical             = COALESCE(EXCLUDED.is_hypothetical, signal_validation_records.is_hypothetical),
                        hypothetical_label          = COALESCE(EXCLUDED.hypothetical_label, signal_validation_records.hypothetical_label),
                        -- AI review fields (written on AI_REVIEWED transition)
                        ai_recommendation           = COALESCE(EXCLUDED.ai_recommendation, signal_validation_records.ai_recommendation),
                        ai_confidence               = COALESCE(EXCLUDED.ai_confidence, signal_validation_records.ai_confidence),
                        ai_agreement                = COALESCE(EXCLUDED.ai_agreement, signal_validation_records.ai_agreement),
                        ai_explanation_latency_ms   = COALESCE(EXCLUDED.ai_explanation_latency_ms, signal_validation_records.ai_explanation_latency_ms),
                        -- Trade / position sizing (written on APPROVED/PAPER_ORDER_FILLED transition)
                        proposed_position_size      = COALESCE(EXCLUDED.proposed_position_size, signal_validation_records.proposed_position_size),
                        approved_position_size      = COALESCE(EXCLUDED.approved_position_size, signal_validation_records.approved_position_size),
                        paper_order_created         = COALESCE(EXCLUDED.paper_order_created, signal_validation_records.paper_order_created),
                        paper_order_id              = COALESCE(EXCLUDED.paper_order_id, signal_validation_records.paper_order_id),
                        entry_price                 = COALESCE(EXCLUDED.entry_price, signal_validation_records.entry_price),
                        entry_timestamp             = COALESCE(EXCLUDED.entry_timestamp, signal_validation_records.entry_timestamp),
                        -- Exit / P&L (written on close_position / EOD)
                        exit_price                  = COALESCE(EXCLUDED.exit_price, signal_validation_records.exit_price),
                        exit_timestamp              = COALESCE(EXCLUDED.exit_timestamp, signal_validation_records.exit_timestamp),
                        exit_reason                 = COALESCE(EXCLUDED.exit_reason, signal_validation_records.exit_reason),
                        realised_pnl                = COALESCE(EXCLUDED.realised_pnl, signal_validation_records.realised_pnl),
                        unrealised_pnl              = COALESCE(EXCLUDED.unrealised_pnl, signal_validation_records.unrealised_pnl),
                        r_multiple                  = COALESCE(EXCLUDED.r_multiple, signal_validation_records.r_multiple),
                        max_favourable_excursion    = COALESCE(EXCLUDED.max_favourable_excursion, signal_validation_records.max_favourable_excursion),
                        max_adverse_excursion       = COALESCE(EXCLUDED.max_adverse_excursion, signal_validation_records.max_adverse_excursion),
                        -- Price checkpoints (written by _run_price_checkpoint)
                        price_5m                    = COALESCE(EXCLUDED.price_5m, signal_validation_records.price_5m),
                        price_15m                   = COALESCE(EXCLUDED.price_15m, signal_validation_records.price_15m),
                        price_30m                   = COALESCE(EXCLUDED.price_30m, signal_validation_records.price_30m),
                        price_60m                   = COALESCE(EXCLUDED.price_60m, signal_validation_records.price_60m),
                        end_of_day_price            = COALESCE(EXCLUDED.end_of_day_price, signal_validation_records.end_of_day_price),
                        -- Hypothetical return tracking
                        hyp_return_5m               = COALESCE(EXCLUDED.hyp_return_5m, signal_validation_records.hyp_return_5m),
                        hyp_return_15m              = COALESCE(EXCLUDED.hyp_return_15m, signal_validation_records.hyp_return_15m),
                        hyp_return_30m              = COALESCE(EXCLUDED.hyp_return_30m, signal_validation_records.hyp_return_30m),
                        hyp_return_60m              = COALESCE(EXCLUDED.hyp_return_60m, signal_validation_records.hyp_return_60m),
                        hyp_mfe                     = COALESCE(EXCLUDED.hyp_mfe, signal_validation_records.hyp_mfe),
                        hyp_mae                     = COALESCE(EXCLUDED.hyp_mae, signal_validation_records.hyp_mae),
                        hyp_rejection_justified     = COALESCE(EXCLUDED.hyp_rejection_justified, signal_validation_records.hyp_rejection_justified),
                        updated_at                  = NOW()
                """, _coerce_for_db(rec))
        conn.close()
    except Exception:
        pass


# ── Field-name translation (model field names → DB snake_case column names) ───
# The model uses Python-style mixed-case names; the DB schema uses snake_case.
# All SQL in this module uses snake_case params (%(r_multiple)s etc.).
# This dict must mirror SignalValidationRecord._MODEL_TO_DB exactly.
_MODEL_TO_DB_KEYS: Dict[str, str] = {
    "AI_recommendation":         "ai_recommendation",
    "AI_confidence":             "ai_confidence",
    "AI_agreement":              "ai_agreement",
    "AI_explanation_latency_ms": "ai_explanation_latency_ms",
    "India_VIX_value":           "india_vix_value",
    "R_multiple":                "r_multiple",
    "VWAP":                      "vwap",
    "ATR":                       "atr",
}


def _normalize_rec_keys(rec: dict) -> dict:
    """
    Translate model field names to DB snake_case column names.
    Idempotent — already-normalized keys pass through unchanged.
    Must be called at the top of every function that passes a rec dict to SQL.
    """
    if not any(k in _MODEL_TO_DB_KEYS for k in rec):
        return rec  # fast path — already normalized
    return {_MODEL_TO_DB_KEYS.get(k, k): v for k, v in rec.items()}


def _coerce_for_db(rec: dict) -> dict:
    """
    Normalize field names to DB column names, then convert Decimal/string
    numeric values to float for psycopg2 compatibility.
    Call this as the final step before passing params to cursor.execute().
    """
    normalized = _normalize_rec_keys(rec)
    out = {}
    for k, v in normalized.items():
        if isinstance(v, str):
            try:
                from decimal import Decimal as D
                out[k] = float(D(v))
            except Exception:
                out[k] = v
        elif isinstance(v, Decimal):
            out[k] = float(v)
        else:
            out[k] = v
    return out


def insert_lifecycle_event(evt: dict) -> None:
    if not _db_available():
        return
    ensure_schema()
    try:
        conn = _get_conn()
        with conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO signal_lifecycle_events
                        (event_id, validation_id, from_state, to_state,
                         timestamp_ist, reason, source_component, correlation_id, metadata)
                    VALUES
                        (%(event_id)s, %(validation_id)s, %(from_state)s, %(to_state)s,
                         %(timestamp_ist)s, %(reason)s, %(source_component)s,
                         %(correlation_id)s, %(metadata)s)
                    ON CONFLICT DO NOTHING
                """, {**evt, "metadata": json.dumps(evt.get("metadata", {}))})
        conn.close()
    except Exception:
        pass


def upsert_price_checkpoint(cp: dict) -> None:
    if not _db_available():
        return
    ensure_schema()
    try:
        conn = _get_conn()
        with conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO signal_price_checkpoints
                        (validation_id, checkpoint_type, price, timestamp_ist,
                         source, is_hypothetical, return_pct)
                    VALUES
                        (%(validation_id)s, %(checkpoint_type)s, %(price)s,
                         %(timestamp_ist)s, %(source)s, %(is_hypothetical)s, %(return_pct)s)
                    ON CONFLICT (validation_id, checkpoint_type) DO UPDATE SET
                        price           = COALESCE(EXCLUDED.price, signal_price_checkpoints.price),
                        return_pct      = COALESCE(EXCLUDED.return_pct, signal_price_checkpoints.return_pct),
                        source          = EXCLUDED.source
                """, cp)
        conn.close()
    except Exception:
        pass


def save_strategy_metrics(metrics_list: List[dict]) -> None:
    if not _db_available() or not metrics_list:
        return
    ensure_schema()
    for m in metrics_list:
        try:
            conn = _get_conn()
            with conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        INSERT INTO signal_strategy_metrics
                            (trading_date, session_id, strategy_id, strategy_name,
                             strategy_version, grouping_key, grouping_value,
                             signals_generated, signals_approved, paper_trades, closed_trades,
                             win_count, loss_count, win_rate, loss_rate,
                             avg_return, median_return, avg_r_multiple,
                             profit_factor, expectancy, avg_mfe, avg_mae,
                             max_drawdown_contrib, false_positive_rate, missed_opp_rate,
                             sample_size, confidence_level)
                        VALUES
                            (%(trading_date)s, %(session_id)s, %(strategy_id)s, %(strategy_name)s,
                             %(strategy_version)s, %(grouping_key)s, %(grouping_value)s,
                             %(signals_generated)s, %(signals_approved)s, %(paper_trades)s, %(closed_trades)s,
                             %(win_count)s, %(loss_count)s, %(win_rate)s, %(loss_rate)s,
                             %(avg_return)s, %(median_return)s, %(avg_r_multiple)s,
                             %(profit_factor)s, %(expectancy)s, %(avg_mfe)s, %(avg_mae)s,
                             %(max_drawdown_contrib)s, %(false_positive_rate)s, %(missed_opp_rate)s,
                             %(sample_size)s, %(confidence_level)s)
                        ON CONFLICT (trading_date, strategy_id, grouping_key, grouping_value)
                        DO UPDATE SET
                            win_rate          = EXCLUDED.win_rate,
                            profit_factor     = EXCLUDED.profit_factor,
                            expectancy        = EXCLUDED.expectancy,
                            sample_size       = EXCLUDED.sample_size,
                            confidence_level  = EXCLUDED.confidence_level
                    """, m)
            conn.close()
        except Exception:
            pass


def save_ai_metrics(metrics_list: List[dict]) -> None:
    if not _db_available() or not metrics_list:
        return
    ensure_schema()
    for m in metrics_list:
        try:
            conn = _get_conn()
            with conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        INSERT INTO signal_ai_metrics
                            (trading_date, session_id, agreement_group, signals_count,
                             continuation_rate, reversal_rate, win_rate, expectancy,
                             avg_mfe, avg_mae, false_positive_rate, missed_opp_rate,
                             avg_latency_ms, sample_size)
                        VALUES
                            (%(trading_date)s, %(session_id)s, %(agreement_group)s, %(signals_count)s,
                             %(continuation_rate)s, %(reversal_rate)s, %(win_rate)s, %(expectancy)s,
                             %(avg_mfe)s, %(avg_mae)s, %(false_positive_rate)s, %(missed_opp_rate)s,
                             %(avg_latency_ms)s, %(sample_size)s)
                        ON CONFLICT (trading_date, agreement_group) DO UPDATE SET
                            win_rate          = EXCLUDED.win_rate,
                            expectancy        = EXCLUDED.expectancy,
                            sample_size       = EXCLUDED.sample_size
                    """, m)
            conn.close()
        except Exception:
            pass


def save_preopen_metrics(metrics_list: List[dict]) -> None:
    if not _db_available() or not metrics_list:
        return
    ensure_schema()
    for m in metrics_list:
        try:
            conn = _get_conn()
            with conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        INSERT INTO signal_preopen_metrics
                            (trading_date, session_id, confirmation_group, signals_count,
                             win_rate, expectancy, avg_r_multiple, avg_mfe, avg_mae,
                             sample_size, predictive_value_declared)
                        VALUES
                            (%(trading_date)s, %(session_id)s, %(confirmation_group)s, %(signals_count)s,
                             %(win_rate)s, %(expectancy)s, %(avg_r_multiple)s, %(avg_mfe)s, %(avg_mae)s,
                             %(sample_size)s, %(predictive_value_declared)s)
                        ON CONFLICT (trading_date, confirmation_group) DO UPDATE SET
                            win_rate = EXCLUDED.win_rate, sample_size = EXCLUDED.sample_size
                    """, m)
            conn.close()
        except Exception:
            pass


def save_daily_report(data: dict) -> None:
    if not _db_available():
        return
    ensure_schema()
    try:
        import json as _json
        conn = _get_conn()
        with conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO signal_daily_reports
                        (trading_date, session_id, report_json, report_md,
                         report_json_path, report_md_path,
                         five_day_report_json, five_day_report_md, five_day_verdict)
                    VALUES
                        (%(trading_date)s, %(session_id)s, %(report_json)s, %(report_md)s,
                         %(report_json_path)s, %(report_md_path)s,
                         %(five_day_report_json)s, %(five_day_report_md)s, %(five_day_verdict)s)
                    ON CONFLICT (trading_date) DO UPDATE SET
                        report_json         = COALESCE(EXCLUDED.report_json, signal_daily_reports.report_json),
                        report_md           = COALESCE(EXCLUDED.report_md, signal_daily_reports.report_md),
                        report_json_path    = COALESCE(EXCLUDED.report_json_path, signal_daily_reports.report_json_path),
                        report_md_path      = COALESCE(EXCLUDED.report_md_path, signal_daily_reports.report_md_path),
                        five_day_report_json = COALESCE(EXCLUDED.five_day_report_json, signal_daily_reports.five_day_report_json),
                        five_day_report_md   = COALESCE(EXCLUDED.five_day_report_md, signal_daily_reports.five_day_report_md),
                        five_day_verdict     = COALESCE(EXCLUDED.five_day_verdict, signal_daily_reports.five_day_verdict),
                        updated_at           = NOW()
                """, {
                    "trading_date":       data.get("trading_date"),
                    "session_id":         data.get("session_id"),
                    "report_json":        _json.dumps(data.get("report_json")) if data.get("report_json") else None,
                    "report_md":          data.get("report_md"),
                    "report_json_path":   data.get("report_json_path"),
                    "report_md_path":     data.get("report_md_path"),
                    "five_day_report_json": _json.dumps(data.get("five_day_report_json")) if data.get("five_day_report_json") else None,
                    "five_day_report_md": data.get("five_day_report_md"),
                    "five_day_verdict":   data.get("five_day_verdict"),
                })
        conn.close()
    except Exception:
        pass


# ── Read helpers ───────────────────────────────────────────────────────────────

def get_records(trading_date: Optional[str] = None,
                strategy_id: Optional[str] = None,
                symbol: Optional[str] = None,
                validation_status: Optional[str] = None,
                outcome_class: Optional[str] = None,
                limit: Optional[int] = 200,
                offset: int = 0) -> List[dict]:
    """
    Fetch signal_validation_records with optional filters.

    Pass limit=None to retrieve ALL matching records (no LIMIT clause).
    Internal processing paths (EOD close, shared-claimed seeding, attribution)
    must pass limit=None to guarantee every signal is processed.
    API/UI paths may retain a numeric limit for pagination.
    """
    if not _db_available():
        return []
    ensure_schema()
    try:
        conn = _get_conn()
        with conn.cursor() as cur:
            filters = []
            params: dict = {"offset": offset}
            if trading_date:
                filters.append("trading_date = %(trading_date)s")
                params["trading_date"] = trading_date
            if strategy_id:
                filters.append("strategy_id = %(strategy_id)s")
                params["strategy_id"] = strategy_id
            if symbol:
                filters.append("symbol = %(symbol)s")
                params["symbol"] = symbol
            if validation_status:
                filters.append("validation_status = %(validation_status)s")
                params["validation_status"] = validation_status
            if outcome_class:
                filters.append("outcome_class = %(outcome_class)s")
                params["outcome_class"] = outcome_class
            where = ("WHERE " + " AND ".join(filters)) if filters else ""
            if limit is not None:
                params["limit"] = limit
                limit_clause = "LIMIT %(limit)s"
            else:
                limit_clause = ""
            cur.execute(f"""
                SELECT * FROM signal_validation_records
                {where}
                ORDER BY signal_timestamp_ist DESC NULLS LAST
                {limit_clause} OFFSET %(offset)s
            """, params)
            rows = [_row_to_dict(cur, r) for r in cur.fetchall()]
        conn.close()
        return rows
    except Exception:
        return []


def get_record_by_signal_id(signal_id: str, trading_date: str) -> Optional[dict]:
    if not _db_available():
        return None
    ensure_schema()
    try:
        conn = _get_conn()
        with conn.cursor() as cur:
            cur.execute("""
                SELECT * FROM signal_validation_records
                WHERE signal_id = %s AND trading_date = %s
            """, (signal_id, trading_date))
            row = cur.fetchone()
            result = _row_to_dict(cur, row) if row else None
        conn.close()
        return result
    except Exception:
        return None


def get_lifecycle_events(validation_id: str) -> List[dict]:
    if not _db_available():
        return []
    ensure_schema()
    try:
        conn = _get_conn()
        with conn.cursor() as cur:
            cur.execute("""
                SELECT * FROM signal_lifecycle_events
                WHERE validation_id = %s ORDER BY timestamp_ist ASC
            """, (validation_id,))
            rows = [_row_to_dict(cur, r) for r in cur.fetchall()]
        conn.close()
        return rows
    except Exception:
        return []


def get_price_checkpoints(validation_id: str) -> List[dict]:
    if not _db_available():
        return []
    ensure_schema()
    try:
        conn = _get_conn()
        with conn.cursor() as cur:
            cur.execute("""
                SELECT * FROM signal_price_checkpoints
                WHERE validation_id = %s ORDER BY checkpoint_type ASC
            """, (validation_id,))
            rows = [_row_to_dict(cur, r) for r in cur.fetchall()]
        conn.close()
        return rows
    except Exception:
        return []


def get_latest_session(trading_date: Optional[str] = None) -> Optional[dict]:
    if not _db_available():
        return None
    ensure_schema()
    try:
        conn = _get_conn()
        with conn.cursor() as cur:
            if trading_date:
                cur.execute("""
                    SELECT * FROM signal_validation_sessions
                    WHERE trading_date = %s ORDER BY created_at DESC LIMIT 1
                """, (trading_date,))
            else:
                cur.execute("""
                    SELECT * FROM signal_validation_sessions
                    ORDER BY trading_date DESC, created_at DESC LIMIT 1
                """)
            row = cur.fetchone()
            result = _row_to_dict(cur, row) if row else None
        conn.close()
        return result
    except Exception:
        return None


def get_sessions(limit: int = 10) -> List[dict]:
    if not _db_available():
        return []
    ensure_schema()
    try:
        conn = _get_conn()
        with conn.cursor() as cur:
            cur.execute("""
                SELECT * FROM signal_validation_sessions
                ORDER BY trading_date DESC LIMIT %s
            """, (limit,))
            rows = [_row_to_dict(cur, r) for r in cur.fetchall()]
        conn.close()
        return rows
    except Exception:
        return []


def count_valid_sessions() -> int:
    """Count sessions with at least 1 closed trade for five-day report gate."""
    if not _db_available():
        return 0
    ensure_schema()
    try:
        conn = _get_conn()
        with conn.cursor() as cur:
            cur.execute("""
                SELECT COUNT(*) FROM signal_validation_sessions
                WHERE paper_trades > 0
            """)
            row = cur.fetchone()
            result = row[0] if row else 0
        conn.close()
        return result
    except Exception:
        return 0


def get_daily_report(trading_date: str) -> Optional[dict]:
    if not _db_available():
        return None
    ensure_schema()
    try:
        conn = _get_conn()
        with conn.cursor() as cur:
            cur.execute("""
                SELECT * FROM signal_daily_reports WHERE trading_date = %s
            """, (trading_date,))
            row = cur.fetchone()
            result = _row_to_dict(cur, row) if row else None
        conn.close()
        return result
    except Exception:
        return None


def get_strategy_metrics(trading_date: Optional[str] = None) -> List[dict]:
    if not _db_available():
        return []
    ensure_schema()
    try:
        conn = _get_conn()
        with conn.cursor() as cur:
            if trading_date:
                cur.execute("""
                    SELECT * FROM signal_strategy_metrics
                    WHERE trading_date = %s ORDER BY strategy_id, grouping_key
                """, (trading_date,))
            else:
                cur.execute("""
                    SELECT * FROM signal_strategy_metrics
                    ORDER BY trading_date DESC, strategy_id
                    LIMIT 500
                """)
            rows = [_row_to_dict(cur, r) for r in cur.fetchall()]
        conn.close()
        return rows
    except Exception:
        return []


def get_ai_metrics(trading_date: Optional[str] = None) -> List[dict]:
    if not _db_available():
        return []
    ensure_schema()
    try:
        conn = _get_conn()
        with conn.cursor() as cur:
            if trading_date:
                cur.execute("""
                    SELECT * FROM signal_ai_metrics WHERE trading_date = %s
                    ORDER BY agreement_group
                """, (trading_date,))
            else:
                cur.execute("""
                    SELECT * FROM signal_ai_metrics
                    ORDER BY trading_date DESC LIMIT 100
                """)
            rows = [_row_to_dict(cur, r) for r in cur.fetchall()]
        conn.close()
        return rows
    except Exception:
        return []


def get_preopen_metrics(trading_date: Optional[str] = None) -> List[dict]:
    if not _db_available():
        return []
    ensure_schema()
    try:
        conn = _get_conn()
        with conn.cursor() as cur:
            if trading_date:
                cur.execute("""
                    SELECT * FROM signal_preopen_metrics WHERE trading_date = %s
                    ORDER BY confirmation_group
                """, (trading_date,))
            else:
                cur.execute("""
                    SELECT * FROM signal_preopen_metrics
                    ORDER BY trading_date DESC LIMIT 50
                """)
            rows = [_row_to_dict(cur, r) for r in cur.fetchall()]
        conn.close()
        return rows
    except Exception:
        return []
