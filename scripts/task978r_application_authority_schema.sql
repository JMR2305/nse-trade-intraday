-- Task978R deterministic application-authority schema.
-- Generated statically; application modules are never imported.

-- source: lib/db/migrations/0000_initial_baseline.sql:1
CREATE TABLE IF NOT EXISTS "paper_portfolio" (
	"id" integer PRIMARY KEY NOT NULL,
	"cash" double precision NOT NULL,
	"positions" jsonb NOT NULL,
	"pnl_history" jsonb NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now()
);
--> bootstrap-breakpoint

-- source: lib/db/migrations/0000_initial_baseline.sql:2
CREATE TABLE IF NOT EXISTS "paper_trades" (
	"id" text PRIMARY KEY NOT NULL,
	"symbol" text NOT NULL,
	"action" text NOT NULL,
	"quantity" integer NOT NULL,
	"price" double precision NOT NULL,
	"total" double precision NOT NULL,
	"trade_ts" timestamp with time zone NOT NULL,
	"reason" text DEFAULT '',
	"metadata" jsonb NOT NULL,
	"created_at" timestamp with time zone DEFAULT now()
);
--> bootstrap-breakpoint

-- source: lib/db/migrations/0000_initial_baseline.sql:3
CREATE TABLE IF NOT EXISTS "push_subscriptions" (
	"token" text PRIMARY KEY NOT NULL,
	"min_confidence" double precision DEFAULT 70 NOT NULL,
	"enabled" boolean DEFAULT true NOT NULL,
	"last_notified_key" text,
	"created_at" timestamp with time zone DEFAULT now(),
	"updated_at" timestamp with time zone DEFAULT now()
);
--> bootstrap-breakpoint

-- source: lib/db/migrations/0000_initial_baseline.sql:4
CREATE TABLE IF NOT EXISTS "signal_snapshots" (
	"id" bigserial PRIMARY KEY NOT NULL,
	"scan_id" text NOT NULL,
	"canonical_scan_id" text,
	"snapshot_ts" timestamp with time zone DEFAULT now() NOT NULL,
	"signals" jsonb NOT NULL,
	"market_context" jsonb NOT NULL
);
--> bootstrap-breakpoint

-- source: lib/db/migrations/0000_initial_baseline.sql:5
CREATE TABLE IF NOT EXISTS "signals_cache" (
	"key" text PRIMARY KEY NOT NULL,
	"payload" jsonb NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now()
);
--> bootstrap-breakpoint

-- source: lib/db/migrations/0001_alert_deliveries.sql:1
CREATE TABLE IF NOT EXISTS "alert_deliveries" (
	"id" bigserial PRIMARY KEY NOT NULL,
	"idempotency_key" text NOT NULL,
	"channel" text NOT NULL,
	"kind" text NOT NULL,
	"severity" text DEFAULT 'INFO' NOT NULL,
	"title" text NOT NULL,
	"body" text DEFAULT '' NOT NULL,
	"destination" text NOT NULL,
	"payload" jsonb,
	"status" text DEFAULT 'QUEUED' NOT NULL,
	"attempts" integer DEFAULT 0 NOT NULL,
	"max_attempts" integer DEFAULT 6 NOT NULL,
	"critical" boolean DEFAULT false NOT NULL,
	"dead_letter" boolean DEFAULT false NOT NULL,
	"next_attempt_at" timestamp with time zone DEFAULT now(),
	"expires_at" timestamp with time zone,
	"last_error" text,
	"provider_id" text,
	"provider_response" jsonb,
	"created_at" timestamp with time zone DEFAULT now(),
	"updated_at" timestamp with time zone DEFAULT now(),
	"delivered_at" timestamp with time zone,
	CONSTRAINT "alert_deliveries_idempotency_key_unique" UNIQUE("idempotency_key")
);
--> bootstrap-breakpoint

-- source: lib/db/migrations/0002_universe_authority_schema_parity.sql:1
CREATE TABLE IF NOT EXISTS "trading_universe_sources" (
  "id" BIGSERIAL PRIMARY KEY,
  "source_type" TEXT NOT NULL,
  "source_reference" TEXT NOT NULL,
  "source_table" TEXT,
  "source_snapshot_at" TIMESTAMPTZ,
  "source_set_hash" TEXT NOT NULL,
  "imported_at" TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  "imported_by" TEXT NOT NULL,
  "metadata" JSONB NOT NULL DEFAULT '{}'::jsonb,
  UNIQUE ("source_type", "source_reference", "source_set_hash")
);
--> bootstrap-breakpoint

-- source: lib/db/migrations/0002_universe_authority_schema_parity.sql:2
CREATE TABLE IF NOT EXISTS "trading_universes" (
  "id" BIGSERIAL PRIMARY KEY,
  "universe_key" TEXT NOT NULL,
  "display_name" TEXT NOT NULL,
  "version" INTEGER NOT NULL,
  "status" TEXT NOT NULL CHECK (
    "status" IN (
      'DRAFT', 'PENDING_ACTIVATION', 'ACTIVE', 'SUPERSEDED', 'CANCELLED'
    )
  ),
  "effective_from" TIMESTAMPTZ,
  "effective_until" TIMESTAMPTZ,
  "created_at" TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  "created_by" TEXT NOT NULL,
  "approved_at" TIMESTAMPTZ,
  "approved_by" TEXT,
  "notes" TEXT,
  "exact_set_hash" TEXT NOT NULL,
  "enabled_symbol_count" INTEGER NOT NULL DEFAULT 0
    CHECK ("enabled_symbol_count" >= 0),
  "source_id" BIGINT REFERENCES "trading_universe_sources"("id"),
  UNIQUE ("universe_key", "version")
);
--> bootstrap-breakpoint

-- source: lib/db/migrations/0002_universe_authority_schema_parity.sql:5
CREATE TABLE IF NOT EXISTS "trading_universe_members" (
  "id" BIGSERIAL PRIMARY KEY,
  "universe_id" BIGINT NOT NULL REFERENCES "trading_universes"("id"),
  "symbol" TEXT NOT NULL,
  "exchange" TEXT,
  "sector" TEXT,
  "instrument_token" BIGINT,
  "mapping_status" TEXT NOT NULL DEFAULT 'UNVERIFIED',
  "enabled" BOOLEAN NOT NULL DEFAULT TRUE,
  "added_at" TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  "added_by" TEXT NOT NULL,
  "removed_at" TIMESTAMPTZ,
  "removed_by" TEXT,
  "notes" TEXT,
  UNIQUE ("universe_id", "symbol"),
  CHECK (NOT "enabled" OR "removed_at" IS NULL),
  CHECK (
    "enabled" OR "removed_at" IS NOT NULL OR "removed_by" IS NOT NULL
  )
);
--> bootstrap-breakpoint

-- source: lib/db/migrations/0002_universe_authority_schema_parity.sql:8
CREATE TABLE IF NOT EXISTS "trading_universe_audit_events" (
  "id" BIGSERIAL PRIMARY KEY,
  "occurred_at" TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  "actor" TEXT NOT NULL,
  "action" TEXT NOT NULL CHECK (
    "action" IN (
      'DRAFT_CREATED', 'SYMBOL_ADDED', 'SYMBOL_REMOVED', 'SYMBOL_RESTORED',
      'VALIDATION_RUN', 'ACTIVATION_REQUESTED', 'ACTIVATION_APPROVED',
      'ACTIVATED', 'CANCELLED', 'BASELINE_IMPORTED'
    )
  ),
  "universe_key" TEXT NOT NULL,
  "old_version" INTEGER,
  "new_version" INTEGER,
  "symbol" TEXT,
  "change_type" TEXT,
  "old_value" JSONB,
  "new_value" JSONB,
  "notes" TEXT,
  "correlation_id" TEXT,
  "approval_state" TEXT,
  CONSTRAINT "trading_universe_audit_events_correlation_id_action_key"
    UNIQUE ("correlation_id", "action")
);
--> bootstrap-breakpoint

-- source: lib/db/migrations/0002_universe_authority_schema_parity.sql:10
CREATE TABLE IF NOT EXISTS "runtime_universe_session_pins" (
  "natural_session" TEXT PRIMARY KEY,
  "universe_key" TEXT NOT NULL,
  "universe_id" BIGINT NOT NULL,
  "universe_version" INTEGER NOT NULL,
  "universe_symbols" JSONB NOT NULL,
  "universe_symbol_count" INTEGER NOT NULL,
  "universe_set_hash" TEXT NOT NULL,
  "effective_from" TIMESTAMPTZ,
  "pinned_at" TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
--> bootstrap-breakpoint

-- source: lib/db/migrations/0002_universe_authority_schema_parity.sql:11
CREATE TABLE IF NOT EXISTS "trading_universe_member_details" (
  "universe_id" BIGINT NOT NULL REFERENCES "trading_universes"("id"),
  "symbol" TEXT NOT NULL,
  "metadata" JSONB NOT NULL DEFAULT '{}'::jsonb,
  "created_at" TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  "created_by" TEXT NOT NULL,
  PRIMARY KEY ("universe_id", "symbol")
);
--> bootstrap-breakpoint

-- source: lib/db/migrations/0002_universe_authority_schema_parity.sql:12
CREATE TABLE IF NOT EXISTS "trading_universe_validations" (
  "id" BIGSERIAL PRIMARY KEY,
  "universe_id" BIGINT NOT NULL REFERENCES "trading_universes"("id"),
  "result" TEXT NOT NULL
    CHECK ("result" IN ('VALIDATION_PASS', 'VALIDATION_FAIL')),
  "checked_at" TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  "checked_by" TEXT NOT NULL,
  "correlation_id" TEXT,
  "evidence" JSONB NOT NULL DEFAULT '{}'::jsonb
);
--> bootstrap-breakpoint

-- source: lib/db/migrations/0002_universe_authority_schema_parity.sql:14
CREATE TABLE IF NOT EXISTS "trading_universe_baseline_migrations" (
  "id" BIGSERIAL PRIMARY KEY,
  "occurred_at" TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  "actor" TEXT NOT NULL,
  "action" TEXT NOT NULL CHECK ("action" = 'BASELINE_MIGRATION'),
  "universe_key" TEXT NOT NULL,
  "destination_universe_id" BIGINT NOT NULL
    REFERENCES "trading_universes"("id"),
  "destination_version" INTEGER NOT NULL,
  "source_authority" TEXT NOT NULL,
  "exact_symbol_count" INTEGER NOT NULL CHECK ("exact_symbol_count" > 0),
  "exact_set_hash" TEXT NOT NULL,
  "mapping_count" INTEGER NOT NULL,
  "previous_configured_universe_key" TEXT NOT NULL,
  "reason" TEXT NOT NULL,
  "correlation_id" TEXT NOT NULL UNIQUE,
  "evidence" JSONB NOT NULL,
  UNIQUE ("universe_key", "destination_version")
);
--> bootstrap-breakpoint

-- source: artifacts/api-server/src/python/backtest_portfolio.py:170
CREATE TABLE IF NOT EXISTS backtest_runs (
    run_id TEXT PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    status TEXT NOT NULL DEFAULT 'PENDING',
    config JSONB NOT NULL DEFAULT '{}'::jsonb,
    progress JSONB NOT NULL DEFAULT '{}'::jsonb,
    metrics JSONB,
    missed JSONB,
    validation JSONB,
    error TEXT,
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    pending_at TIMESTAMPTZ
);
--> bootstrap-breakpoint

-- source: artifacts/api-server/src/python/backtest_portfolio.py:195
CREATE TABLE IF NOT EXISTS backtest_trades (
    trade_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    scan_id TEXT,
    symbol TEXT NOT NULL,
    strategy_id TEXT,
    strategy_name TEXT,
    side TEXT NOT NULL DEFAULT 'BUY',
    signal_ts TEXT,
    fill_ts TEXT,
    signal_price DOUBLE PRECISION,
    fill_price DOUBLE PRECISION,
    quantity INTEGER,
    stop_loss DOUBLE PRECISION,
    target DOUBLE PRECISION,
    est_charges DOUBLE PRECISION,
    slippage DOUBLE PRECISION,
    confidence DOUBLE PRECISION,
    opportunity_score DOUBLE PRECISION,
    regime TEXT,
    status TEXT NOT NULL DEFAULT 'OPEN',
    exit_ts TEXT,
    exit_price DOUBLE PRECISION,
    exit_rule TEXT,
    realized_pnl DOUBLE PRECISION,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
--> bootstrap-breakpoint

-- source: artifacts/api-server/src/python/certification_engine.py:72
CREATE TABLE IF NOT EXISTS certification_runs (
    cert_id TEXT PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    certification_pct DOUBLE PRECISION NOT NULL,
    verdict TEXT NOT NULL,
    report JSONB NOT NULL DEFAULT '{}'::jsonb
);
--> bootstrap-breakpoint

-- source: artifacts/api-server/src/python/custom_universe_store.py:52
CREATE TABLE IF NOT EXISTS custom_universe_master (
    symbol              TEXT PRIMARY KEY,
    yahoo_symbol        TEXT,
    kite_symbol         TEXT,
    instrument_token    BIGINT,
    company_name        TEXT,
    sector              TEXT,
    industry            TEXT,
    allowed_universe    TEXT NOT NULL DEFAULT 'CUSTOM_LOW_PRICE_SECTOR',
    price_min           NUMERIC(12,2),
    price_max           NUMERIC(12,2),
    is_active           BOOLEAN NOT NULL DEFAULT FALSE,
    reason_included     TEXT,
    reason_excluded     TEXT,
    last_ltp            NUMERIC(14,4),
    last_ltp_source     TEXT,
    avg_volume_20d      NUMERIC(20,2),
    avg_turnover_20d    NUMERIC(20,2),
    ohlcv_available     BOOLEAN NOT NULL DEFAULT FALSE,
    last_verified_at    TIMESTAMPTZ,
    instrument_exchange TEXT,
    instrument_tradingsymbol TEXT,
    instrument_cache_date DATE,
    instrument_mapping_at TIMESTAMPTZ,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
--> bootstrap-breakpoint

-- source: artifacts/api-server/src/python/custom_universe_store.py:87
CREATE TABLE IF NOT EXISTS custom_universe_membership_history (
    snapshot_at      TIMESTAMPTZ NOT NULL,
    snapshot_date    DATE NOT NULL,
    symbol           TEXT NOT NULL,
    allowed_universe TEXT NOT NULL,
    is_active        BOOLEAN NOT NULL,
    sector           TEXT,
    last_verified_at TIMESTAMPTZ,
    PRIMARY KEY (snapshot_at, symbol)
);
--> bootstrap-breakpoint

-- source: artifacts/api-server/src/python/data_quality/history_store.py:66
CREATE TABLE IF NOT EXISTS data_quality_runs (
    id             SERIAL      PRIMARY KEY,
    run_ts         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    quality_score  REAL        NOT NULL,
    grade          TEXT        NOT NULL,
    critical_count INT         NOT NULL DEFAULT 0,
    warning_count  INT         NOT NULL DEFAULT 0,
    domain_scores  JSONB       NOT NULL DEFAULT '{}'::jsonb
);
--> bootstrap-breakpoint

-- source: artifacts/api-server/src/python/eod_reconciliation.py:54
CREATE TABLE IF NOT EXISTS broker_reconciliation_runs (
    run_id          TEXT PRIMARY KEY,
    trigger         TEXT NOT NULL DEFAULT 'manual',
    started_at      TIMESTAMPTZ NOT NULL,
    completed_at    TIMESTAMPTZ,
    orders_checked  INTEGER NOT NULL DEFAULT 0,
    clean           BOOLEAN NOT NULL DEFAULT TRUE,
    discrepancy_count INTEGER NOT NULL DEFAULT 0,
    paper_mode      BOOLEAN NOT NULL DEFAULT FALSE,
    error           TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
--> bootstrap-breakpoint

-- source: artifacts/api-server/src/python/eod_reconciliation.py:68
CREATE TABLE IF NOT EXISTS broker_reconciliation_discrepancies (
    id                  SERIAL PRIMARY KEY,
    run_id              TEXT NOT NULL REFERENCES broker_reconciliation_runs(run_id),
    discrepancy_type    TEXT NOT NULL,
    internal_order_id   TEXT,
    broker_order_id     TEXT,
    trading_symbol      TEXT,
    description         TEXT,
    local_value         TEXT,
    broker_value        TEXT,
    requires_manual_review BOOLEAN NOT NULL DEFAULT FALSE,
    resolved            BOOLEAN NOT NULL DEFAULT FALSE,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
--> bootstrap-breakpoint

-- source: artifacts/api-server/src/python/historical_data_engine.py:51
CREATE TABLE IF NOT EXISTS backtest_candles (
    symbol TEXT NOT NULL,
    interval TEXT NOT NULL,
    ts TIMESTAMPTZ NOT NULL,
    open DOUBLE PRECISION NOT NULL,
    high DOUBLE PRECISION NOT NULL,
    low DOUBLE PRECISION NOT NULL,
    close DOUBLE PRECISION NOT NULL,
    volume BIGINT NOT NULL DEFAULT 0,
    PRIMARY KEY (symbol, interval, ts)
);
--> bootstrap-breakpoint

-- source: artifacts/api-server/src/python/historical_data_engine.py:73
CREATE TABLE IF NOT EXISTS backtest_candle_meta (
    symbol TEXT NOT NULL,
    interval TEXT NOT NULL,
    range_start DATE NOT NULL,
    range_end DATE NOT NULL,
    fetched_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (symbol, interval, range_start, range_end)
);
--> bootstrap-breakpoint

-- source: artifacts/api-server/src/python/historical_data_engine.py:85
CREATE TABLE IF NOT EXISTS backtest_corporate_actions (
    symbol TEXT NOT NULL,
    action_date DATE NOT NULL,
    kind TEXT NOT NULL,
    value DOUBLE PRECISION NOT NULL,
    fetched_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (symbol, action_date, kind)
);
--> bootstrap-breakpoint

-- source: artifacts/api-server/src/python/kite_instrument_cache.py:310
CREATE TABLE IF NOT EXISTS kite_instrument_sync_audit (
    id BIGSERIAL PRIMARY KEY,
    attempted_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ,
    provider TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('SUCCESS', 'FAILED', 'SKIPPED')),
    previous_row_count INTEGER NOT NULL,
    candidate_row_count INTEGER,
    promoted_row_count INTEGER,
    candidate_hash TEXT,
    failure_reason TEXT,
    evidence JSONB NOT NULL
);
--> bootstrap-breakpoint

-- source: artifacts/api-server/src/python/market_data_incidents.py:87
CREATE TABLE IF NOT EXISTS market_data_fallback_incidents (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('ACTIVE', 'RECOVERED')),
    severity TEXT NOT NULL,
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_detected_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    recovered_at TIMESTAMPTZ,
    latest_scan_id TEXT,
    active_universe_count INTEGER NOT NULL DEFAULT 0,
    symbols_on_kite INTEGER NOT NULL DEFAULT 0,
    symbols_fallback INTEGER NOT NULL DEFAULT 0,
    symbols_stale INTEGER NOT NULL DEFAULT 0,
    symbols_unavailable INTEGER NOT NULL DEFAULT 0,
    symbols_synthetic INTEGER NOT NULL DEFAULT 0,
    current_quote_provider TEXT NOT NULL,
    current_quote_freshness TEXT NOT NULL,
    detection_count INTEGER NOT NULL DEFAULT 1,
    evidence JSONB NOT NULL DEFAULT '{}'::jsonb,
    recovery_summary TEXT
);
--> bootstrap-breakpoint

-- source: artifacts/api-server/src/python/nifty50_company_master_store.py:48
CREATE TABLE IF NOT EXISTS nifty50_company_master (
    symbol              TEXT PRIMARY KEY,
    yahoo_symbol        TEXT,
    kite_symbol         TEXT,
    instrument_token    BIGINT,
    company_name        TEXT,
    sector              TEXT,
    industry            TEXT,
    exchange            TEXT DEFAULT 'NSE',
    lot_size            INTEGER,
    tick_size           NUMERIC(10,4),
    isin                TEXT,
    index_membership    TEXT DEFAULT 'NIFTY_50',
    is_active           BOOLEAN DEFAULT TRUE,
    last_verified_at    TIMESTAMPTZ,
    source              TEXT DEFAULT 'config'
);
--> bootstrap-breakpoint

-- source: artifacts/api-server/src/python/ohlcv_cache_store.py:81
CREATE TABLE IF NOT EXISTS daily_ohlcv_cache (
    symbol          TEXT NOT NULL,
    trading_date    DATE NOT NULL,
    open            NUMERIC(14,4),
    high            NUMERIC(14,4),
    low             NUMERIC(14,4),
    close           NUMERIC(14,4),
    adjusted_close  NUMERIC(14,4),
    volume          BIGINT,
    source          TEXT DEFAULT 'yfinance',
    fetched_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW(),
    data_quality    TEXT,
    PRIMARY KEY (symbol, trading_date)
);
--> bootstrap-breakpoint

-- source: artifacts/api-server/src/python/ohlcv_cache_store.py:98
CREATE TABLE IF NOT EXISTS daily_ohlcv_refresh_state (
    id                  SERIAL PRIMARY KEY,
    refresh_date        DATE,
    refresh_type        TEXT,
    status              TEXT,
    symbols_requested   INTEGER DEFAULT 0,
    symbols_updated     INTEGER DEFAULT 0,
    missing_symbols     TEXT[],
    stale_symbols       TEXT[],
    failed_symbols      TEXT[],
    start_time          TIMESTAMPTZ,
    end_time            TIMESTAMPTZ,
    duration_seconds    NUMERIC(10,2),
    error_summary       TEXT
);
--> bootstrap-breakpoint

-- source: artifacts/api-server/src/python/paper_capital_migration.py:101
CREATE TABLE IF NOT EXISTS phase20_kv (
    key TEXT PRIMARY KEY,
    value JSONB,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
--> bootstrap-breakpoint

-- source: artifacts/api-server/src/python/paper_exploration_engine.py:70
CREATE TABLE IF NOT EXISTS experimental_paper_trades (
    trade_id TEXT PRIMARY KEY,
    scan_id TEXT,
    snapshot_ts TEXT,
    symbol TEXT,
    action_type TEXT,
    original_action TEXT,
    entry_price DOUBLE PRECISION,
    fill_price DOUBLE PRECISION,
    quantity INTEGER,
    confidence DOUBLE PRECISION,
    opportunity_score DOUBLE PRECISION,
    rr_at_entry DOUBLE PRECISION,
    stop_loss DOUBLE PRECISION,
    target DOUBLE PRECISION,
    slippage DOUBLE PRECISION,
    reason_accepted TEXT,
    would_normally_reject TEXT,
    rule_allowed TEXT,
    strategy_id TEXT,
    strategy_name TEXT,
    regime TEXT,
    status TEXT DEFAULT 'OPEN',
    exit_ts TEXT,
    exit_price DOUBLE PRECISION,
    exit_rule TEXT,
    realized_pnl DOUBLE PRECISION,
    max_favorable_excursion DOUBLE PRECISION,
    max_adverse_excursion DOUBLE PRECISION,
    holding_days DOUBLE PRECISION,
    evidence JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
--> bootstrap-breakpoint

-- source: artifacts/api-server/src/python/phase11_autonomous.py:48
CREATE TABLE IF NOT EXISTS phase11_capital_topups (
    id          SERIAL PRIMARY KEY,
    amount      DOUBLE PRECISION NOT NULL,
    before_cash DOUBLE PRECISION NOT NULL,
    after_cash  DOUBLE PRECISION NOT NULL,
    reason      TEXT NOT NULL DEFAULT '',
    mode        TEXT NOT NULL DEFAULT 'B',
    ts          TIMESTAMPTZ DEFAULT NOW()
);
--> bootstrap-breakpoint

-- source: artifacts/api-server/src/python/phase11_autonomous.py:74
CREATE TABLE IF NOT EXISTS phase11_price_snapshots (
    id          SERIAL PRIMARY KEY,
    symbol      TEXT NOT NULL,
    price       DOUBLE PRECISION NOT NULL,
    scan_id     TEXT NOT NULL DEFAULT '',
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
--> bootstrap-breakpoint

-- source: artifacts/api-server/src/python/phase20_eod_outcomes.py:59
CREATE TABLE IF NOT EXISTS phase20_eod_outcomes (
    id              SERIAL PRIMARY KEY,
    session_date    TEXT NOT NULL,
    trade_id        TEXT NOT NULL,
    symbol          TEXT NOT NULL,
    attempted_at    TEXT NOT NULL,
    job_type        TEXT NOT NULL,
    selected_outcome TEXT NOT NULL,
    exit_rule       TEXT,
    exit_price      DOUBLE PRECISION,
    exit_price_source TEXT,
    realized_pnl    DOUBLE PRECISION,
    reason          TEXT,
    config_hash     TEXT,
    build_id        TEXT,
    process_id      TEXT,
    correlation_id  TEXT,
    error_detail    TEXT,
    created_at      TEXT NOT NULL
);
--> bootstrap-breakpoint

-- source: artifacts/api-server/src/python/phase20_executor.py:65
CREATE TABLE IF NOT EXISTS phase20_paper_trades (
    trade_id TEXT PRIMARY KEY,
    scan_id TEXT,
    snapshot_ts TEXT,
    symbol TEXT,
    sector TEXT,
    strategy_id TEXT,
    strategy_name TEXT,
    side TEXT,
    signal_ts TEXT,
    decision_ts TEXT,
    simulated_order_ts TEXT,
    fill_ts TEXT,
    signal_price DOUBLE PRECISION,
    fill_price DOUBLE PRECISION,
    quantity INTEGER,
    stop_loss DOUBLE PRECISION,
    target DOUBLE PRECISION,
    risk_amount DOUBLE PRECISION,
    est_charges DOUBLE PRECISION,
    slippage DOUBLE PRECISION,
    fill_model TEXT,
    confidence DOUBLE PRECISION,
    opportunity_score DOUBLE PRECISION,
    trade_quality_score DOUBLE PRECISION,
    regime TEXT,
    model_version TEXT,
    rule_version TEXT,
    config_hash TEXT,
    trigger_source TEXT,
    status TEXT,
    exit_ts TEXT,
    exit_price DOUBLE PRECISION,
    exit_rule TEXT,
    exit_scan_id TEXT,
    realized_pnl DOUBLE PRECISION,
    evidence JSONB,
    recomputed BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
--> bootstrap-breakpoint

-- source: artifacts/api-server/src/python/phase20_store.py:215
CREATE TABLE IF NOT EXISTS phase20_settings (
    id INTEGER PRIMARY KEY,
    data JSONB NOT NULL,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
--> bootstrap-breakpoint

-- source: artifacts/api-server/src/python/phase20_store.py:224
CREATE TABLE IF NOT EXISTS phase20_scan_runs (
    id BIGSERIAL PRIMARY KEY,
    scan_id TEXT,
    trigger_source TEXT,
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    duration_s DOUBLE PRECISION,
    symbols_requested INTEGER,
    symbols_received INTEGER,
    missing_symbols JSONB,
    stale_symbols JSONB,
    unavailable_symbols JSONB,
    provider TEXT,
    status TEXT,
    error TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
--> bootstrap-breakpoint

-- source: artifacts/api-server/src/python/phase20_store.py:245
CREATE TABLE IF NOT EXISTS phase20_scheduler_state (
    id INTEGER PRIMARY KEY,
    last_attempt_at TIMESTAMPTZ,
    last_success_at TIMESTAMPTZ,
    last_scan_id TEXT,
    next_due_at TIMESTAMPTZ,
    missed_count INTEGER DEFAULT 0,
    status TEXT,
    detail TEXT,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
--> bootstrap-breakpoint

-- source: artifacts/api-server/src/python/phase20_store.py:299
CREATE TABLE IF NOT EXISTS phase20_notifications (
    id BIGSERIAL PRIMARY KEY,
    kind TEXT,
    severity TEXT,
    title TEXT,
    body TEXT,
    context JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    read BOOLEAN DEFAULT FALSE
);
--> bootstrap-breakpoint

-- source: artifacts/api-server/src/python/phase22_evidence.py:59
CREATE TABLE IF NOT EXISTS phase22_evidence (
    evidence_id TEXT PRIMARY KEY,
    recorded_at TEXT,
    scan_id TEXT,
    snapshot_ts TEXT,
    symbol TEXT,
    decision TEXT,
    raw_confidence DOUBLE PRECISION,
    calibrated_confidence DOUBLE PRECISION,
    opportunity_score DOUBLE PRECISION,
    trade_quality_score DOUBLE PRECISION,
    rank INTEGER,
    strategy TEXT,
    regime TEXT,
    sector TEXT,
    quote_source TEXT,
    gates JSONB,
    eligibility_result TEXT,
    trade_opened BOOLEAN,
    paper_trade_id TEXT,
    blocking_reasons JSONB,
    signal_price DOUBLE PRECISION,
    observations JSONB,
    ret_15m DOUBLE PRECISION, ret_15m_at TEXT,
    ret_30m DOUBLE PRECISION, ret_30m_at TEXT,
    ret_60m DOUBLE PRECISION, ret_60m_at TEXT,
    ret_eod DOUBLE PRECISION, ret_eod_at TEXT,
    ret_1d DOUBLE PRECISION, ret_1d_at TEXT,
    ret_3d DOUBLE PRECISION, ret_3d_at TEXT,
    ret_5d DOUBLE PRECISION, ret_5d_at TEXT,
    mae_pct DOUBLE PRECISION,
    mfe_pct DOUBLE PRECISION,
    final_outcome TEXT,
    outcome_complete BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
--> bootstrap-breakpoint

-- source: artifacts/api-server/src/python/phase24_store.py:62
CREATE TABLE IF NOT EXISTS phase24_trade_intelligence (
    trade_id   TEXT PRIMARY KEY,
    scan_id    TEXT,
    symbol     TEXT,
    closed_date TEXT,
    record     JSONB NOT NULL,
    analysis   JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
--> bootstrap-breakpoint

-- source: artifacts/api-server/src/python/phase24_store.py:72
CREATE TABLE IF NOT EXISTS phase24_missed_opps (
    id              TEXT PRIMARY KEY,
    scan_id         TEXT,
    symbol          TEXT,
    record          JSONB NOT NULL,
    source          TEXT NOT NULL DEFAULT 'live',
    backtest_run_id TEXT,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);
--> bootstrap-breakpoint

-- source: artifacts/api-server/src/python/phase24_store.py:89
CREATE TABLE IF NOT EXISTS phase24_recommendations (
    id         TEXT PRIMARY KEY,
    rec_date   TEXT,
    record     JSONB NOT NULL,
    status     TEXT NOT NULL DEFAULT 'PROPOSED',
    decided_at TEXT,
    decision_note TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
--> bootstrap-breakpoint

-- source: artifacts/api-server/src/python/phase24_store.py:99
CREATE TABLE IF NOT EXISTS phase24_reports (
    id         TEXT PRIMARY KEY,
    period     TEXT NOT NULL,
    period_key TEXT NOT NULL,
    record     JSONB NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (period, period_key)
);
--> bootstrap-breakpoint

-- source: artifacts/api-server/src/python/phase24_store.py:314
CREATE TABLE IF NOT EXISTS advisory_bot_outputs (
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
    UNIQUE (scan_id, bot_name, symbol, strategy_name, build_id, config_hash)
);
--> bootstrap-breakpoint

-- source: artifacts/api-server/src/python/phase24_store.py:314
CREATE TABLE IF NOT EXISTS advisory_decision_audit (
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
    UNIQUE (scan_id, symbol, build_id, config_hash)
);
--> bootstrap-breakpoint

-- source: artifacts/api-server/src/python/phase24_store.py:314
CREATE TABLE IF NOT EXISTS advisory_strategy_scores (
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
    UNIQUE (scan_id, symbol, strategy_name, build_id, config_hash)
);
--> bootstrap-breakpoint

-- source: artifacts/api-server/src/python/phase24_store.py:314
CREATE TABLE IF NOT EXISTS advisory_universe_health (
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
    UNIQUE (scan_id, build_id, config_hash)
);
--> bootstrap-breakpoint

-- source: artifacts/api-server/src/python/phase26_live_store.py:62
CREATE TABLE IF NOT EXISTS phase26_live_snapshots (
    snapshot_id TEXT PRIMARY KEY,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    in_session  BOOLEAN,
    verdict     TEXT,
    result      JSONB NOT NULL
);
--> bootstrap-breakpoint

-- source: artifacts/api-server/src/python/phase26_live_store.py:75
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
);
--> bootstrap-breakpoint

-- source: artifacts/api-server/src/python/phase26_reports.py:87
CREATE TABLE IF NOT EXISTS phase26_daily_reports (
    report_id   TEXT PRIMARY KEY,
    report_date DATE NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    verdict     TEXT,
    report      JSONB NOT NULL
);
--> bootstrap-breakpoint

-- source: artifacts/api-server/src/python/phase26_store.py:50
CREATE TABLE IF NOT EXISTS phase26_validation_runs (
    run_id     TEXT PRIMARY KEY,
    scan_id    TEXT,
    verdict    TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    result     JSONB NOT NULL
);
--> bootstrap-breakpoint

-- source: artifacts/api-server/src/python/phase26c_store.py:51
CREATE TABLE IF NOT EXISTS phase26c_results (
    result_id  TEXT PRIMARY KEY,
    area       TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    verdict    TEXT,
    result     JSONB NOT NULL
);
--> bootstrap-breakpoint

-- source: artifacts/api-server/src/python/pipeline_events.py:90
CREATE TABLE IF NOT EXISTS pipeline_events (
    id BIGSERIAL PRIMARY KEY,
    ts TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    mode TEXT NOT NULL DEFAULT 'LIVE',
    run_id TEXT,
    scan_id TEXT,
    event_type TEXT NOT NULL,
    stage TEXT NOT NULL,
    symbol TEXT,
    payload JSONB,
    dedupe_key TEXT
);
--> bootstrap-breakpoint

-- source: artifacts/api-server/src/python/portfolio_config_overrides.py:66
CREATE TABLE IF NOT EXISTS portfolio_config_overrides (
    portfolio_id TEXT PRIMARY KEY,
    overrides JSONB NOT NULL,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
--> bootstrap-breakpoint

-- source: artifacts/api-server/src/python/preopen_db.py:42
CREATE TABLE IF NOT EXISTS preopen_sessions (
    session_id     TEXT PRIMARY KEY,
    trading_date   TEXT NOT NULL,
    started_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    status         TEXT NOT NULL DEFAULT 'INITIALISING',
    symbol_count   INTEGER DEFAULT 0,
    valid_count    INTEGER DEFAULT 0,
    stale_count    INTEGER DEFAULT 0,
    provider_status TEXT DEFAULT 'UNAVAILABLE',
    provider_collected_count INTEGER,
    persisted_count INTEGER,
    failed_count INTEGER,
    expected_count INTEGER,
    provider_returned_count INTEGER,
    normalized_count INTEGER,
    missing_count INTEGER,
    duplicate_count INTEGER,
    malformed_count INTEGER,
    collection_coverage JSONB,
    collection_started_at TIMESTAMPTZ,
    collection_completed_at TIMESTAMPTZ,
    collection_source TEXT,
    persistence_status TEXT,
    verified_collection_batch_id TEXT,
    frozen_collection_batch_id TEXT,
    retry_state TEXT,
    phase_state JSONB NOT NULL DEFAULT '{}'::jsonb,
    frozen_at      TIMESTAMPTZ,
    reconciled_at  TIMESTAMPTZ,
    error          TEXT,
    universe_context JSONB,
    created_at     TIMESTAMPTZ DEFAULT NOW(),
    updated_at     TIMESTAMPTZ DEFAULT NOW()
);
--> bootstrap-breakpoint

-- source: artifacts/api-server/src/python/preopen_db.py:109
CREATE TABLE IF NOT EXISTS preopen_snapshots (
    snapshot_id              TEXT PRIMARY KEY,
    session_id               TEXT REFERENCES preopen_sessions(session_id),
    collection_batch_id      TEXT,
    trading_date             TEXT NOT NULL,
    timestamp_ist            TIMESTAMPTZ NOT NULL,
    symbol                   TEXT NOT NULL,
    company_name             TEXT,
    sector                   TEXT,
    previous_close           DOUBLE PRECISION,
    indicative_equilibrium_price DOUBLE PRECISION,
    indicative_open_price    DOUBLE PRECISION,
    final_open_price         DOUBLE PRECISION,
    price_change             DOUBLE PRECISION,
    gap_percent              DOUBLE PRECISION,
    total_buy_quantity       BIGINT DEFAULT 0,
    total_sell_quantity      BIGINT DEFAULT 0,
    matched_quantity         BIGINT DEFAULT 0,
    final_executed_quantity  BIGINT DEFAULT 0,
    total_traded_value       DOUBLE PRECISION DEFAULT 0,
    buy_sell_imbalance       BIGINT DEFAULT 0,
    imbalance_percent        DOUBLE PRECISION DEFAULT 0,
    volume_rank              INTEGER,
    gap_rank                 INTEGER,
    liquidity_score          DOUBLE PRECISION DEFAULT 0,
    classification           TEXT,
    opportunity_score        DOUBLE PRECISION DEFAULT 0,
    factor_scores            JSONB,
    data_source              TEXT,
    data_freshness_seconds   INTEGER DEFAULT 0,
    source_status            TEXT,
    is_stale                 BOOLEAN DEFAULT TRUE,
    validation_status        TEXT DEFAULT 'UNVALIDATED',
    raw_payload_reference    TEXT,
    created_at               TIMESTAMPTZ DEFAULT NOW()
);
--> bootstrap-breakpoint

-- source: artifacts/api-server/src/python/preopen_db.py:169
CREATE TABLE IF NOT EXISTS preopen_collection_outcomes (
    session_id                TEXT NOT NULL REFERENCES preopen_sessions(session_id),
    collection_batch_id       TEXT NOT NULL,
    symbol                    TEXT NOT NULL,
    outcome_status            TEXT NOT NULL,
    reason_code               TEXT NOT NULL,
    provider_symbol           TEXT,
    provider_response_present BOOLEAN NOT NULL DEFAULT FALSE,
    normalization_result      TEXT,
    eligibility_status        TEXT,
    snapshot_id               TEXT,
    provider_scope            TEXT,
    provider_raw_count        INTEGER,
    created_at                TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (session_id, collection_batch_id, symbol)
);
--> bootstrap-breakpoint

-- source: artifacts/api-server/src/python/preopen_db.py:193
CREATE TABLE IF NOT EXISTS preopen_rankings (
    id             BIGSERIAL PRIMARY KEY,
    session_id     TEXT REFERENCES preopen_sessions(session_id),
    trading_date   TEXT NOT NULL,
    frozen_at      TIMESTAMPTZ,
    rankings_json  JSONB NOT NULL,
    summary        JSONB,
    created_at     TIMESTAMPTZ DEFAULT NOW()
);
--> bootstrap-breakpoint

-- source: artifacts/api-server/src/python/preopen_db.py:210
CREATE TABLE IF NOT EXISTS preopen_watchlists (
    id             BIGSERIAL PRIMARY KEY,
    session_id     TEXT REFERENCES preopen_sessions(session_id),
    trading_date   TEXT NOT NULL,
    list_type      TEXT NOT NULL,
    items_json     JSONB NOT NULL,
    generated_at   TIMESTAMPTZ DEFAULT NOW(),
    created_at     TIMESTAMPTZ DEFAULT NOW()
);
--> bootstrap-breakpoint

-- source: artifacts/api-server/src/python/preopen_db.py:227
CREATE TABLE IF NOT EXISTS preopen_provider_health (
    id             BIGSERIAL PRIMARY KEY,
    session_id     TEXT,
    trading_date   TEXT NOT NULL,
    checked_at     TIMESTAMPTZ DEFAULT NOW(),
    provider_name  TEXT NOT NULL,
    status         TEXT NOT NULL,
    latency_ms     INTEGER,
    message        TEXT,
    raw_response   JSONB,
    created_at     TIMESTAMPTZ DEFAULT NOW()
);
--> bootstrap-breakpoint

-- source: artifacts/api-server/src/python/preopen_db.py:247
CREATE TABLE IF NOT EXISTS preopen_reconciliation (
    id                            BIGSERIAL PRIMARY KEY,
    session_id                    TEXT REFERENCES preopen_sessions(session_id),
    symbol                        TEXT NOT NULL,
    trading_date                  TEXT NOT NULL,
    indicative_equilibrium_price  DOUBLE PRECISION,
    final_pre_open_price          DOUBLE PRECISION,
    actual_open_price             DOUBLE PRECISION,
    price_at_0920                 DOUBLE PRECISION,
    price_at_0930                 DOUBLE PRECISION,
    indicative_to_open_error      DOUBLE PRECISION,
    opening_continuation          BOOLEAN,
    opening_reversal              BOOLEAN,
    watchlist_confirmed           BOOLEAN,
    was_in_watchlist              BOOLEAN DEFAULT FALSE,
    reconciled_at                 TIMESTAMPTZ DEFAULT NOW(),
    created_at                    TIMESTAMPTZ DEFAULT NOW()
);
--> bootstrap-breakpoint

-- source: artifacts/api-server/src/python/preopen_validation_db.py:43
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
);
--> bootstrap-breakpoint

-- source: artifacts/api-server/src/python/preopen_validation_db.py:66
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
);
--> bootstrap-breakpoint

-- source: artifacts/api-server/src/python/preopen_validation_db.py:127
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
);
--> bootstrap-breakpoint

-- source: artifacts/api-server/src/python/preopen_validation_db.py:153
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
);
--> bootstrap-breakpoint

-- source: artifacts/api-server/src/python/preopen_validation_db.py:174
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
);
--> bootstrap-breakpoint

-- source: artifacts/api-server/src/python/scan_state_store.py:61
CREATE TABLE IF NOT EXISTS scan_state (
    id INTEGER PRIMARY KEY,
    scan_id TEXT,
    status TEXT,
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    snapshot_ts TEXT,
    provider TEXT,
    symbols_requested INTEGER,
    symbols_received INTEGER,
    symbols_missing INTEGER,
    symbols_stale INTEGER,
    trigger_origin TEXT NOT NULL DEFAULT 'UNKNOWN',
    missing_symbols JSONB,
    stale_symbols JSONB,
    universe_context JSONB,
    error TEXT,
    snapshot JSONB,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
--> bootstrap-breakpoint

-- source: artifacts/api-server/src/python/scan_state_store.py:90
CREATE TABLE IF NOT EXISTS scan_lock (
    name TEXT PRIMARY KEY,
    holder TEXT,
    acquired_at TIMESTAMPTZ,
    expires_at TIMESTAMPTZ
);
--> bootstrap-breakpoint

-- source: artifacts/api-server/src/python/session_archive.py:57
CREATE TABLE IF NOT EXISTS session_archives (
    id            TEXT PRIMARY KEY,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    reset_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    reset_reason  TEXT NOT NULL DEFAULT '',
    snapshot      JSONB NOT NULL,
    metrics       JSONB NOT NULL DEFAULT '{}',
    restored_at   TIMESTAMPTZ,
    restore_token TEXT,
    token_expires TIMESTAMPTZ
);
--> bootstrap-breakpoint

-- source: artifacts/api-server/src/python/signal_validation_db.py:42
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


CREATE TABLE IF NOT EXISTS signal_strategy_metrics (
    id                  SERIAL PRIMARY KEY,
    trading_date        DATE NOT NULL,
    session_id          TEXT,
    strategy_id         TEXT NOT NULL,
    strategy_name       TEXT,
    strategy_version    TEXT,
    grouping_key        TEXT NOT NULL,
    grouping_value      TEXT NOT NULL,
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


CREATE TABLE IF NOT EXISTS signal_ai_metrics (
    id                  SERIAL PRIMARY KEY,
    trading_date        DATE NOT NULL,
    session_id          TEXT,
    agreement_group     TEXT NOT NULL,
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


CREATE TABLE IF NOT EXISTS signal_preopen_metrics (
    id                  SERIAL PRIMARY KEY,
    trading_date        DATE NOT NULL,
    session_id          TEXT,
    confirmation_group  TEXT NOT NULL,
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


CREATE TABLE IF NOT EXISTS signal_risk_metrics (
    id                  SERIAL PRIMARY KEY,
    trading_date        DATE NOT NULL,
    session_id          TEXT,
    risk_decision       TEXT NOT NULL,
    rejection_reason    TEXT,
    signals_count       INTEGER DEFAULT 0,
    hypothetical_win_rate DOUBLE PRECISION,
    rejection_justified_rate DOUBLE PRECISION,
    sample_size         INTEGER DEFAULT 0,
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (trading_date, risk_decision, rejection_reason)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_srisk_unique_no_reason
    ON signal_risk_metrics(trading_date, risk_decision)
    WHERE rejection_reason IS NULL;
CREATE UNIQUE INDEX IF NOT EXISTS idx_srisk_unique_with_reason
    ON signal_risk_metrics(trading_date, risk_decision, rejection_reason)
    WHERE rejection_reason IS NOT NULL;


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

CREATE UNIQUE INDEX IF NOT EXISTS idx_sregime_unique_no_strategy
    ON signal_regime_metrics(trading_date, regime)
    WHERE strategy_id IS NULL;
CREATE UNIQUE INDEX IF NOT EXISTS idx_sregime_unique_with_strategy
    ON signal_regime_metrics(trading_date, regime, strategy_id)
    WHERE strategy_id IS NOT NULL;


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
--> bootstrap-breakpoint

-- source: artifacts/api-server/src/python/simulation_lab.py:69
CREATE TABLE IF NOT EXISTS sim_scenarios (
    scenario_id TEXT PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    name TEXT NOT NULL,
    base_run_id TEXT,
    params JSONB NOT NULL DEFAULT '{}'::jsonb
);
--> bootstrap-breakpoint

-- source: artifacts/api-server/src/python/simulation_lab.py:80
CREATE TABLE IF NOT EXISTS sim_runs (
    sim_id TEXT PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    scenario_id TEXT,
    label TEXT,
    base_run_id TEXT,
    params JSONB NOT NULL DEFAULT '{}'::jsonb,
    result JSONB NOT NULL DEFAULT '{}'::jsonb
);
--> bootstrap-breakpoint

-- source: artifacts/api-server/src/python/src/portfolio/repositories/portfolio_event.py:62
CREATE TABLE IF NOT EXISTS portfolio_events (
    id SERIAL PRIMARY KEY,
    event_id TEXT NOT NULL UNIQUE,
    idempotency_key TEXT NOT NULL,
    event_type TEXT NOT NULL,
    portfolio_id TEXT NOT NULL,
    sequence INTEGER,
    version INTEGER NOT NULL DEFAULT 1,
    instrument_token INTEGER,
    internal_order_id TEXT,
    broker_order_id TEXT,
    strategy_id TEXT,
    correlation_id TEXT,
    payload JSONB NOT NULL,
    occurred_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (portfolio_id, idempotency_key)
);
CREATE INDEX IF NOT EXISTS idx_portfolio_events_pid_time
    ON portfolio_events (portfolio_id, occurred_at);
--> bootstrap-breakpoint

-- source: artifacts/api-server/src/python/src/portfolio/repositories/portfolio_snapshot.py:103
CREATE TABLE IF NOT EXISTS portfolio_snapshots (
    id SERIAL PRIMARY KEY,
    snapshot_id TEXT NOT NULL UNIQUE,
    portfolio_id TEXT NOT NULL,
    status TEXT NOT NULL,
    version INTEGER NOT NULL,
    paper_mode BOOLEAN NOT NULL DEFAULT TRUE,
    cash_available NUMERIC(20,6) NOT NULL,
    cash_blocked NUMERIC(20,6) NOT NULL,
    cash_total NUMERIC(20,6) NOT NULL,
    buying_power_net NUMERIC(20,6) NOT NULL,
    equity NUMERIC(20,6) NOT NULL,
    open_position_count INTEGER NOT NULL DEFAULT 0,
    pending_order_count INTEGER NOT NULL DEFAULT 0,
    realised_pnl NUMERIC(20,6) NOT NULL DEFAULT 0,
    unrealised_pnl NUMERIC(20,6) NOT NULL DEFAULT 0,
    daily_pnl NUMERIC(20,6) NOT NULL DEFAULT 0,
    drawdown NUMERIC(20,6) NOT NULL DEFAULT 0,
    snapshot_payload JSONB,
    checksum TEXT,
    snapshotted_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_portfolio_snapshots_pid
    ON portfolio_snapshots (portfolio_id, snapshotted_at DESC);
ALTER TABLE portfolio_snapshots
    ADD COLUMN IF NOT EXISTS event_cursor BIGINT;
--> bootstrap-breakpoint

-- source: artifacts/api-server/src/python/src/portfolio/repositories/reconciliation.py:51
CREATE TABLE IF NOT EXISTS reconciliation_runs (
    id SERIAL PRIMARY KEY,
    run_id TEXT NOT NULL UNIQUE,
    portfolio_id TEXT NOT NULL,
    dry_run BOOLEAN NOT NULL,
    critical_count INTEGER NOT NULL DEFAULT 0,
    warning_count INTEGER NOT NULL DEFAULT 0,
    portfolio_ready BOOLEAN NOT NULL,
    notes TEXT,
    state_version INTEGER NOT NULL DEFAULT 0,
    broker_snapshot_age_s NUMERIC(20,6),
    report_payload JSONB,
    started_at TIMESTAMPTZ NOT NULL,
    completed_at TIMESTAMPTZ
);
ALTER TABLE reconciliation_runs
    ADD COLUMN IF NOT EXISTS report_payload JSONB;
CREATE INDEX IF NOT EXISTS idx_recon_runs_pid_time
    ON reconciliation_runs (portfolio_id, started_at DESC);
--> bootstrap-breakpoint

-- source: artifacts/api-server/src/python/validation_v2_engine.py:192
CREATE TABLE IF NOT EXISTS validation_v2_runs (
    run_id      TEXT PRIMARY KEY,
    config      JSONB NOT NULL DEFAULT '{}',
    status      TEXT NOT NULL DEFAULT 'PENDING',
    symbols     JSONB NOT NULL DEFAULT '[]',
    strategies  JSONB NOT NULL DEFAULT '[]',
    start_date  TEXT,
    end_date    TEXT,
    interval    TEXT DEFAULT '1h',
    total_decisions INTEGER DEFAULT 0,
    total_trades    INTEGER DEFAULT 0,
    symbols_done    INTEGER DEFAULT 0,
    symbols_total   INTEGER DEFAULT 0,
    current_symbol  TEXT DEFAULT '',
    symbol_errors   JSONB DEFAULT '[]',
    error           TEXT,
    last_progress_at TIMESTAMPTZ DEFAULT NOW(),
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    completed_at TIMESTAMPTZ
);
CREATE TABLE IF NOT EXISTS validation_v2_decisions (
    id          BIGSERIAL PRIMARY KEY,
    run_id      TEXT NOT NULL REFERENCES validation_v2_runs(run_id) ON DELETE CASCADE,
    symbol      TEXT NOT NULL,
    strategy    TEXT NOT NULL DEFAULT '',
    bar_date    TEXT NOT NULL,
    bar_close   DOUBLE PRECISION,
    recommendation TEXT,
    final_confidence DOUBLE PRECISION,
    reason      TEXT,
    threshold   DOUBLE PRECISION,
    entry_signal BOOLEAN DEFAULT FALSE,
    filter_passed BOOLEAN DEFAULT FALSE,
    rr_ratio    DOUBLE PRECISION,
    detail      JSONB DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_v2_dec_run ON validation_v2_decisions(run_id);
CREATE INDEX IF NOT EXISTS idx_v2_dec_sym ON validation_v2_decisions(run_id, symbol);
CREATE TABLE IF NOT EXISTS validation_v2_trades (
    id            BIGSERIAL PRIMARY KEY,
    run_id        TEXT NOT NULL REFERENCES validation_v2_runs(run_id) ON DELETE CASCADE,
    symbol        TEXT NOT NULL,
    strategy      TEXT NOT NULL DEFAULT '',
    entry_date    TEXT,
    entry_price   DOUBLE PRECISION,
    stop_loss     DOUBLE PRECISION,
    target_price  DOUBLE PRECISION,
    trailing_stop DOUBLE PRECISION,
    exit_date     TEXT,
    exit_price    DOUBLE PRECISION,
    exit_reason   TEXT,
    pnl_pct       DOUBLE PRECISION,
    pnl_abs       DOUBLE PRECISION,
    holding_days  INTEGER,
    mfe_pct       DOUBLE PRECISION,
    mad_pct       DOUBLE PRECISION,
    result        TEXT,
    confidence    DOUBLE PRECISION,
    recommendation TEXT,
    agent_scores  JSONB DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_v2_trades_run ON validation_v2_trades(run_id);
CREATE TABLE IF NOT EXISTS validation_v2_missed (
    id                  BIGSERIAL PRIMARY KEY,
    run_id              TEXT NOT NULL REFERENCES validation_v2_runs(run_id) ON DELETE CASCADE,
    symbol              TEXT NOT NULL,
    strategy            TEXT NOT NULL DEFAULT '',
    bar_date            TEXT,
    ai_decision         TEXT,
    ai_confidence       DOUBLE PRECISION,
    actual_move_pct     DOUBLE PRECISION,
    potential_profit_pct DOUBLE PRECISION,
    rejection_reason    TEXT,
    improvement_suggestion TEXT
);
CREATE INDEX IF NOT EXISTS idx_v2_missed_run ON validation_v2_missed(run_id);
CREATE TABLE IF NOT EXISTS validation_v2_optimizer_runs (
    opt_run_id   TEXT PRIMARY KEY,
    config       JSONB NOT NULL DEFAULT '{}',
    best_config  JSONB,
    results      JSONB NOT NULL DEFAULT '[]',
    combinations_tested INTEGER DEFAULT 0,
    recommendation TEXT,
    created_at   TIMESTAMPTZ DEFAULT NOW()
);
--> bootstrap-breakpoint

-- source: lib/db/migrations/0002_universe_authority_schema_parity.sql:3
CREATE INDEX IF NOT EXISTS "idx_trading_universes_lookup"
  ON "trading_universes" ("universe_key", "status", "effective_from");
--> bootstrap-breakpoint

-- source: lib/db/migrations/0002_universe_authority_schema_parity.sql:4
CREATE UNIQUE INDEX IF NOT EXISTS "uq_trading_universes_one_draft"
  ON "trading_universes" ("universe_key")
  WHERE "status" = 'DRAFT';
--> bootstrap-breakpoint

-- source: lib/db/migrations/0002_universe_authority_schema_parity.sql:6
CREATE UNIQUE INDEX IF NOT EXISTS "uq_trading_universe_enabled_token"
  ON "trading_universe_members" ("universe_id", "instrument_token")
  WHERE "enabled" AND "instrument_token" IS NOT NULL;
--> bootstrap-breakpoint

-- source: lib/db/migrations/0002_universe_authority_schema_parity.sql:7
CREATE INDEX IF NOT EXISTS "idx_trading_universe_members_symbol"
  ON "trading_universe_members" ("symbol", "enabled");
--> bootstrap-breakpoint

-- source: lib/db/migrations/0002_universe_authority_schema_parity.sql:9
CREATE INDEX IF NOT EXISTS "idx_trading_universe_audit_lookup"
  ON "trading_universe_audit_events" ("universe_key", "occurred_at" DESC);
--> bootstrap-breakpoint

-- source: lib/db/migrations/0002_universe_authority_schema_parity.sql:13
CREATE INDEX IF NOT EXISTS "idx_trading_universe_validations_revision"
  ON "trading_universe_validations" ("universe_id", "checked_at" DESC);
--> bootstrap-breakpoint

-- source: lib/db/migrations/0002_universe_authority_schema_parity.sql:15
DO $migration$
BEGIN
  IF to_regprocedure(
    format('%I.task946_reject_history_mutation()', current_schema())
  ) IS NULL THEN
    EXECUTE $function$
      CREATE FUNCTION "task946_reject_history_mutation"()
      RETURNS trigger AS $body$
      BEGIN
        RAISE EXCEPTION
          'Task 946 history is append-only: % on % is forbidden',
          TG_OP, TG_TABLE_NAME;
      END;
      $body$ LANGUAGE plpgsql
    $function$;
  END IF;

  IF to_regprocedure(
    format('%I.task946_guard_revision_snapshot()', current_schema())
  ) IS NULL THEN
    EXECUTE $function$
      CREATE FUNCTION "task946_guard_revision_snapshot"()
      RETURNS trigger AS $body$
      BEGIN
        IF TG_OP = 'DELETE' THEN
          RAISE EXCEPTION 'Universe revisions cannot be deleted';
        END IF;
        IF OLD.universe_key IS DISTINCT FROM NEW.universe_key
          OR OLD.display_name IS DISTINCT FROM NEW.display_name
          OR OLD.version IS DISTINCT FROM NEW.version
          OR OLD.created_at IS DISTINCT FROM NEW.created_at
          OR OLD.created_by IS DISTINCT FROM NEW.created_by
          OR OLD.notes IS DISTINCT FROM NEW.notes
          OR OLD.exact_set_hash IS DISTINCT FROM NEW.exact_set_hash
          OR OLD.enabled_symbol_count IS DISTINCT FROM NEW.enabled_symbol_count
          OR OLD.source_id IS DISTINCT FROM NEW.source_id THEN
          RAISE EXCEPTION 'Universe revision snapshot fields are immutable';
        END IF;
        RETURN NEW;
      END;
      $body$ LANGUAGE plpgsql
    $function$;
  END IF;

  IF to_regprocedure(
    format('%I.task946_guard_member_write()', current_schema())
  ) IS NULL THEN
    EXECUTE $function$
      CREATE FUNCTION "task946_guard_member_write"()
      RETURNS trigger AS $body$
      DECLARE revision_status TEXT;
      BEGIN
        IF TG_OP IN ('UPDATE', 'DELETE') THEN
          RAISE EXCEPTION 'Universe members are immutable once recorded';
        END IF;
        SELECT status INTO revision_status
        FROM trading_universes WHERE id = NEW.universe_id;
        IF revision_status IS DISTINCT FROM 'DRAFT' THEN
          RAISE EXCEPTION 'Members may only be added to DRAFT revisions';
        END IF;
        RETURN NEW;
      END;
      $body$ LANGUAGE plpgsql
    $function$;
  END IF;
END
$migration$;
--> bootstrap-breakpoint

-- source: lib/db/migrations/0002_universe_authority_schema_parity.sql:16
DO $migration$
DECLARE
  bad_trigger TEXT;
BEGIN
  SELECT trigger_row.tgname INTO bad_trigger
  FROM (
    VALUES
      ('trg_task946_source_immutable',
       'trading_universe_sources',
       'task946_reject_history_mutation'),
      ('trg_task946_audit_immutable',
       'trading_universe_audit_events',
       'task946_reject_history_mutation'),
      ('trg_task946_member_history_guard',
       'trading_universe_members',
       'task946_reject_history_mutation'),
      ('trg_task946_member_guard',
       'trading_universe_members',
       'task946_guard_member_write'),
      ('trg_task946_revision_guard',
       'trading_universes',
       'task946_guard_revision_snapshot')
  ) AS expected(trigger_name, table_name, function_name)
  JOIN pg_trigger trigger_row
    ON trigger_row.tgname = expected.trigger_name
  JOIN pg_class table_row ON table_row.oid = trigger_row.tgrelid
  JOIN pg_namespace table_namespace
    ON table_namespace.oid = table_row.relnamespace
  JOIN pg_proc function_row ON function_row.oid = trigger_row.tgfoid
  JOIN pg_namespace function_namespace
    ON function_namespace.oid = function_row.pronamespace
  WHERE table_namespace.nspname = current_schema()
    AND (
      table_row.relname <> expected.table_name
      OR function_row.proname <> expected.function_name
      OR function_namespace.nspname <> current_schema()
    )
  LIMIT 1;

  IF bad_trigger IS NOT NULL THEN
    RAISE EXCEPTION '% has unexpected table/function identity', bad_trigger;
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM pg_trigger trigger_row
    JOIN pg_class table_row ON table_row.oid = trigger_row.tgrelid
    JOIN pg_namespace table_namespace
      ON table_namespace.oid = table_row.relnamespace
    WHERE trigger_row.tgname = 'trg_task946_source_immutable'
      AND table_namespace.nspname = current_schema()
  ) THEN
    CREATE TRIGGER "trg_task946_source_immutable"
    BEFORE UPDATE OR DELETE ON "trading_universe_sources"
    FOR EACH ROW EXECUTE FUNCTION "task946_reject_history_mutation"();
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM pg_trigger trigger_row
    JOIN pg_class table_row ON table_row.oid = trigger_row.tgrelid
    JOIN pg_namespace table_namespace
      ON table_namespace.oid = table_row.relnamespace
    WHERE trigger_row.tgname = 'trg_task946_audit_immutable'
      AND table_namespace.nspname = current_schema()
  ) THEN
    CREATE TRIGGER "trg_task946_audit_immutable"
    BEFORE UPDATE OR DELETE ON "trading_universe_audit_events"
    FOR EACH ROW EXECUTE FUNCTION "task946_reject_history_mutation"();
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM pg_trigger trigger_row
    JOIN pg_class table_row ON table_row.oid = trigger_row.tgrelid
    JOIN pg_namespace table_namespace
      ON table_namespace.oid = table_row.relnamespace
    WHERE trigger_row.tgname = 'trg_task946_member_history_guard'
      AND table_namespace.nspname = current_schema()
  ) THEN
    CREATE TRIGGER "trg_task946_member_history_guard"
    BEFORE UPDATE OR DELETE ON "trading_universe_members"
    FOR EACH ROW EXECUTE FUNCTION "task946_reject_history_mutation"();
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM pg_trigger trigger_row
    JOIN pg_class table_row ON table_row.oid = trigger_row.tgrelid
    JOIN pg_namespace table_namespace
      ON table_namespace.oid = table_row.relnamespace
    WHERE trigger_row.tgname = 'trg_task946_member_guard'
      AND table_namespace.nspname = current_schema()
  ) THEN
    CREATE TRIGGER "trg_task946_member_guard"
    BEFORE INSERT OR UPDATE OR DELETE ON "trading_universe_members"
    FOR EACH ROW EXECUTE FUNCTION "task946_guard_member_write"();
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM pg_trigger trigger_row
    JOIN pg_class table_row ON table_row.oid = trigger_row.tgrelid
    JOIN pg_namespace table_namespace
      ON table_namespace.oid = table_row.relnamespace
    WHERE trigger_row.tgname = 'trg_task946_revision_guard'
      AND table_namespace.nspname = current_schema()
  ) THEN
    CREATE TRIGGER "trg_task946_revision_guard"
    BEFORE UPDATE OR DELETE ON "trading_universes"
    FOR EACH ROW EXECUTE FUNCTION "task946_guard_revision_snapshot"();
  END IF;
END
$migration$;
--> bootstrap-breakpoint

-- source: lib/db/migrations/0002_universe_authority_schema_parity.sql:17
DO $migration$
BEGIN
  IF to_regprocedure(
    format('%I.task947_reject_management_history()', current_schema())
  ) IS NULL THEN
    EXECUTE $function$
      CREATE FUNCTION "task947_reject_management_history"()
      RETURNS trigger AS $body$
      BEGIN
        RAISE EXCEPTION 'Universe management history is append-only';
      END;
      $body$ LANGUAGE plpgsql
    $function$;
  END IF;

  IF EXISTS (
    SELECT 1
    FROM pg_trigger trigger_row
    JOIN pg_class table_row ON table_row.oid = trigger_row.tgrelid
    JOIN pg_namespace table_namespace
      ON table_namespace.oid = table_row.relnamespace
    JOIN pg_proc function_row ON function_row.oid = trigger_row.tgfoid
    JOIN pg_namespace function_namespace
      ON function_namespace.oid = function_row.pronamespace
    WHERE trigger_row.tgname = 'trg_task947_details_immutable'
      AND table_namespace.nspname = current_schema()
      AND (
        table_row.relname <> 'trading_universe_member_details'
        OR function_row.proname <> 'task947_reject_management_history'
        OR function_namespace.nspname <> current_schema()
      )
  ) THEN
    RAISE EXCEPTION
      'trg_task947_details_immutable has unexpected table/function identity';
  END IF;

  IF NOT EXISTS (
    SELECT 1
    FROM pg_trigger trigger_row
    JOIN pg_class table_row ON table_row.oid = trigger_row.tgrelid
    JOIN pg_namespace table_namespace
      ON table_namespace.oid = table_row.relnamespace
    JOIN pg_proc function_row ON function_row.oid = trigger_row.tgfoid
    JOIN pg_namespace function_namespace
      ON function_namespace.oid = function_row.pronamespace
    WHERE trigger_row.tgname = 'trg_task947_details_immutable'
      AND table_namespace.nspname = current_schema()
      AND table_row.relname = 'trading_universe_member_details'
      AND function_row.proname = 'task947_reject_management_history'
      AND function_namespace.nspname = current_schema()
  ) THEN
    CREATE TRIGGER "trg_task947_details_immutable"
    BEFORE UPDATE OR DELETE ON "trading_universe_member_details"
    FOR EACH ROW EXECUTE FUNCTION "task947_reject_management_history"();
  END IF;

  IF EXISTS (
    SELECT 1
    FROM pg_trigger trigger_row
    JOIN pg_class table_row ON table_row.oid = trigger_row.tgrelid
    JOIN pg_namespace table_namespace
      ON table_namespace.oid = table_row.relnamespace
    JOIN pg_proc function_row ON function_row.oid = trigger_row.tgfoid
    JOIN pg_namespace function_namespace
      ON function_namespace.oid = function_row.pronamespace
    WHERE trigger_row.tgname = 'trg_task947_validation_immutable'
      AND table_namespace.nspname = current_schema()
      AND (
        table_row.relname <> 'trading_universe_validations'
        OR function_row.proname <> 'task947_reject_management_history'
        OR function_namespace.nspname <> current_schema()
      )
  ) THEN
    RAISE EXCEPTION
      'trg_task947_validation_immutable has unexpected table/function identity';
  END IF;

  IF NOT EXISTS (
    SELECT 1
    FROM pg_trigger trigger_row
    JOIN pg_class table_row ON table_row.oid = trigger_row.tgrelid
    JOIN pg_namespace table_namespace
      ON table_namespace.oid = table_row.relnamespace
    JOIN pg_proc function_row ON function_row.oid = trigger_row.tgfoid
    JOIN pg_namespace function_namespace
      ON function_namespace.oid = function_row.pronamespace
    WHERE trigger_row.tgname = 'trg_task947_validation_immutable'
      AND table_namespace.nspname = current_schema()
      AND table_row.relname = 'trading_universe_validations'
      AND function_row.proname = 'task947_reject_management_history'
      AND function_namespace.nspname = current_schema()
  ) THEN
    CREATE TRIGGER "trg_task947_validation_immutable"
    BEFORE UPDATE OR DELETE ON "trading_universe_validations"
    FOR EACH ROW EXECUTE FUNCTION "task947_reject_management_history"();
  END IF;
END
 $migration$;
--> bootstrap-breakpoint

-- source: lib/db/migrations/0002_universe_authority_schema_parity.sql:18
DO $migration$
BEGIN
  IF to_regprocedure(
    format(
      '%I.reject_baseline_migration_history_mutation()',
      current_schema()
    )
  ) IS NULL THEN
    EXECUTE $function$
      CREATE FUNCTION "reject_baseline_migration_history_mutation"()
      RETURNS trigger AS $body$
      BEGIN
        RAISE EXCEPTION 'Baseline migration audit is append-only';
      END;
      $body$ LANGUAGE plpgsql
    $function$;
  END IF;

  IF EXISTS (
    SELECT 1
    FROM pg_trigger trigger_row
    JOIN pg_class table_row ON table_row.oid = trigger_row.tgrelid
    JOIN pg_namespace table_namespace
      ON table_namespace.oid = table_row.relnamespace
    JOIN pg_proc function_row ON function_row.oid = trigger_row.tgfoid
    JOIN pg_namespace function_namespace
      ON function_namespace.oid = function_row.pronamespace
    WHERE trigger_row.tgname = 'trg_baseline_migration_audit_immutable'
      AND table_namespace.nspname = current_schema()
      AND (
        table_row.relname <> 'trading_universe_baseline_migrations'
        OR function_row.proname
          <> 'reject_baseline_migration_history_mutation'
        OR function_namespace.nspname <> current_schema()
      )
  ) THEN
    RAISE EXCEPTION
      'trg_baseline_migration_audit_immutable has unexpected table/function identity';
  END IF;

  IF NOT EXISTS (
    SELECT 1
    FROM pg_trigger trigger_row
    JOIN pg_class table_row ON table_row.oid = trigger_row.tgrelid
    JOIN pg_namespace table_namespace
      ON table_namespace.oid = table_row.relnamespace
    JOIN pg_proc function_row ON function_row.oid = trigger_row.tgfoid
    JOIN pg_namespace function_namespace
      ON function_namespace.oid = function_row.pronamespace
    WHERE trigger_row.tgname = 'trg_baseline_migration_audit_immutable'
      AND table_namespace.nspname = current_schema()
      AND table_row.relname = 'trading_universe_baseline_migrations'
      AND function_row.proname
        = 'reject_baseline_migration_history_mutation'
      AND function_namespace.nspname = current_schema()
  ) THEN
    CREATE TRIGGER "trg_baseline_migration_audit_immutable"
    BEFORE UPDATE OR DELETE ON "trading_universe_baseline_migrations"
    FOR EACH ROW
    EXECUTE FUNCTION "reject_baseline_migration_history_mutation"();
  END IF;
END
 $migration$;
--> bootstrap-breakpoint

-- source: artifacts/api-server/src/python/backtest_portfolio.py:189
ALTER TABLE backtest_runs
ADD COLUMN IF NOT EXISTS pending_at TIMESTAMPTZ;
--> bootstrap-breakpoint

-- source: artifacts/api-server/src/python/backtest_portfolio.py:226
CREATE INDEX IF NOT EXISTS idx_backtest_trades_run ON backtest_trades (run_id, created_at);
--> bootstrap-breakpoint

-- source: artifacts/api-server/src/python/backtest_portfolio.py:232
ALTER TABLE backtest_trades ADD COLUMN IF NOT EXISTS tranche INTEGER NOT NULL DEFAULT 0;
--> bootstrap-breakpoint

-- source: artifacts/api-server/src/python/backtest_portfolio.py:239
CREATE UNIQUE INDEX IF NOT EXISTS idx_backtest_trades_open_tranche ON backtest_trades (run_id, symbol, tranche) WHERE status = 'OPEN';
--> bootstrap-breakpoint

-- source: artifacts/api-server/src/python/certification_engine.py:83
CREATE INDEX IF NOT EXISTS idx_cert_runs_created ON certification_runs (created_at DESC);
--> bootstrap-breakpoint

-- source: artifacts/api-server/src/python/custom_universe_baseline_migration.py:64
CREATE OR REPLACE FUNCTION reject_baseline_migration_history_mutation()
RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'Baseline migration audit is append-only';
END;
$$ LANGUAGE plpgsql;
--> bootstrap-breakpoint

-- source: artifacts/api-server/src/python/custom_universe_baseline_migration.py:72
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_trigger
        WHERE tgname = 'trg_baseline_migration_audit_immutable'
    ) THEN
        CREATE TRIGGER trg_baseline_migration_audit_immutable
        BEFORE UPDATE OR DELETE ON trading_universe_baseline_migrations
        FOR EACH ROW
        EXECUTE FUNCTION reject_baseline_migration_history_mutation();
    END IF;
END
$$;
--> bootstrap-breakpoint

-- source: artifacts/api-server/src/python/custom_universe_store.py:81
CREATE INDEX IF NOT EXISTS idx_custom_universe_master_active
ON custom_universe_master (is_active, sector);
--> bootstrap-breakpoint

-- source: artifacts/api-server/src/python/custom_universe_store.py:99
CREATE INDEX IF NOT EXISTS idx_custom_universe_history_date
ON custom_universe_membership_history
   (snapshot_date, snapshot_at, is_active);
--> bootstrap-breakpoint

-- source: artifacts/api-server/src/python/eod_reconciliation.py:84
CREATE INDEX IF NOT EXISTS idx_recon_discrepancies_run_id
    ON broker_reconciliation_discrepancies(run_id);
--> bootstrap-breakpoint

-- source: artifacts/api-server/src/python/eod_reconciliation.py:88
CREATE INDEX IF NOT EXISTS idx_recon_runs_started_at
    ON broker_reconciliation_runs(started_at DESC);
--> bootstrap-breakpoint

-- source: artifacts/api-server/src/python/eod_reconciliation.py:94
ALTER TABLE broker_reconciliation_discrepancies
    ADD COLUMN IF NOT EXISTS resolved_at   TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS resolved_note TEXT;
--> bootstrap-breakpoint

-- source: artifacts/api-server/src/python/eod_reconciliation.py:102
ALTER TABLE broker_reconciliation_runs
    ADD COLUMN IF NOT EXISTS paper_fallback_count INTEGER NOT NULL DEFAULT 0;
--> bootstrap-breakpoint

-- source: artifacts/api-server/src/python/eod_reconciliation.py:106
CREATE INDEX IF NOT EXISTS idx_recon_discrepancies_resolved
    ON broker_reconciliation_discrepancies(resolved, resolved_at DESC);
--> bootstrap-breakpoint

-- source: artifacts/api-server/src/python/historical_data_engine.py:67
ALTER TABLE backtest_candles
ADD COLUMN IF NOT EXISTS source TEXT NOT NULL DEFAULT 'yfinance';
--> bootstrap-breakpoint

-- source: artifacts/api-server/src/python/kite_instrument_cache.py:325
CREATE OR REPLACE FUNCTION reject_kite_instrument_sync_audit_mutation()
RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'Kite instrument sync audit is append-only';
END;
$$ LANGUAGE plpgsql;
--> bootstrap-breakpoint

-- source: artifacts/api-server/src/python/kite_instrument_cache.py:333
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_trigger
        WHERE tgname = 'trg_kite_instrument_sync_audit_immutable'
    ) THEN
        CREATE TRIGGER trg_kite_instrument_sync_audit_immutable
        BEFORE UPDATE OR DELETE ON kite_instrument_sync_audit
        FOR EACH ROW
        EXECUTE FUNCTION reject_kite_instrument_sync_audit_mutation();
    END IF;
END
$$;
--> bootstrap-breakpoint

-- source: artifacts/api-server/src/python/market_data_incidents.py:112
CREATE UNIQUE INDEX IF NOT EXISTS market_data_fallback_incidents_one_active
ON market_data_fallback_incidents (kind) WHERE status = 'ACTIVE';
--> bootstrap-breakpoint

-- source: artifacts/api-server/src/python/market_data_incidents.py:118
CREATE INDEX IF NOT EXISTS market_data_fallback_incidents_history
ON market_data_fallback_incidents (status, started_at DESC);
--> bootstrap-breakpoint

-- source: artifacts/api-server/src/python/paper_exploration_engine.py:109
CREATE INDEX IF NOT EXISTS exp_trades_created_idx ON experimental_paper_trades (created_at DESC);
--> bootstrap-breakpoint

-- source: artifacts/api-server/src/python/paper_exploration_engine.py:113
CREATE UNIQUE INDEX IF NOT EXISTS exp_trades_open_sym_uidx ON experimental_paper_trades (symbol) WHERE status = 'OPEN';
--> bootstrap-breakpoint

-- source: artifacts/api-server/src/python/phase11_autonomous.py:84
CREATE INDEX IF NOT EXISTS idx_phase11_price_snaps_sym_ts
ON phase11_price_snapshots (symbol, recorded_at DESC);
--> bootstrap-breakpoint

-- source: artifacts/api-server/src/python/phase11_autonomous.py:91
CREATE UNIQUE INDEX IF NOT EXISTS uidx_phase11_price_snaps_scan_sym
ON phase11_price_snapshots (scan_id, symbol)
WHERE scan_id != '';
--> bootstrap-breakpoint

-- source: artifacts/api-server/src/python/phase20_eod_outcomes.py:84
CREATE INDEX IF NOT EXISTS ix_eod_outcomes_session
ON phase20_eod_outcomes (session_date, trade_id);
--> bootstrap-breakpoint

-- source: artifacts/api-server/src/python/phase20_executor.py:110
CREATE UNIQUE INDEX IF NOT EXISTS phase20_open_symbol_uidx
ON phase20_paper_trades (symbol) WHERE status = 'OPEN';
--> bootstrap-breakpoint

-- source: artifacts/api-server/src/python/phase20_store.py:282
ALTER TABLE phase20_scheduler_state ADD COLUMN IF NOT EXISTS heartbeat_at TIMESTAMPTZ;
--> bootstrap-breakpoint

-- source: artifacts/api-server/src/python/phase20_store.py:282
ALTER TABLE phase20_scheduler_state ADD COLUMN IF NOT EXISTS last_error TEXT;
--> bootstrap-breakpoint

-- source: artifacts/api-server/src/python/phase20_store.py:282
ALTER TABLE phase20_scheduler_state ADD COLUMN IF NOT EXISTS last_trigger TEXT;
--> bootstrap-breakpoint

-- source: artifacts/api-server/src/python/phase20_store.py:282
ALTER TABLE phase20_scheduler_state ADD COLUMN IF NOT EXISTS owner TEXT;
--> bootstrap-breakpoint

-- source: artifacts/api-server/src/python/phase20_store.py:282
ALTER TABLE phase20_scheduler_state ADD COLUMN IF NOT EXISTS process_start_at TIMESTAMPTZ;
--> bootstrap-breakpoint

-- source: artifacts/api-server/src/python/phase20_store.py:296
ALTER TABLE phase20_scan_runs ADD COLUMN IF NOT EXISTS completed_at_ist TEXT;
--> bootstrap-breakpoint

-- source: artifacts/api-server/src/python/phase20_store.py:296
ALTER TABLE phase20_scan_runs ADD COLUMN IF NOT EXISTS details JSONB;
--> bootstrap-breakpoint

-- source: artifacts/api-server/src/python/phase20_store.py:296
ALTER TABLE phase20_scan_runs ADD COLUMN IF NOT EXISTS entry_eligible BOOLEAN;
--> bootstrap-breakpoint

-- source: artifacts/api-server/src/python/phase20_store.py:296
ALTER TABLE phase20_scan_runs ADD COLUMN IF NOT EXISTS execution_eligible BOOLEAN;
--> bootstrap-breakpoint

-- source: artifacts/api-server/src/python/phase20_store.py:296
ALTER TABLE phase20_scan_runs ADD COLUMN IF NOT EXISTS job_type TEXT;
--> bootstrap-breakpoint

-- source: artifacts/api-server/src/python/phase20_store.py:296
ALTER TABLE phase20_scan_runs ADD COLUMN IF NOT EXISTS market_state TEXT;
--> bootstrap-breakpoint

-- source: artifacts/api-server/src/python/phase20_store.py:296
ALTER TABLE phase20_scan_runs ADD COLUMN IF NOT EXISTS perf TEXT;
--> bootstrap-breakpoint

-- source: artifacts/api-server/src/python/phase20_store.py:296
ALTER TABLE phase20_scan_runs ADD COLUMN IF NOT EXISTS scan_type TEXT;
--> bootstrap-breakpoint

-- source: artifacts/api-server/src/python/phase20_store.py:296
ALTER TABLE phase20_scan_runs ADD COLUMN IF NOT EXISTS source TEXT;
--> bootstrap-breakpoint

-- source: artifacts/api-server/src/python/phase20_store.py:296
ALTER TABLE phase20_scan_runs ADD COLUMN IF NOT EXISTS started_at_ist TEXT;
--> bootstrap-breakpoint

-- source: artifacts/api-server/src/python/phase20_store.py:296
ALTER TABLE phase20_scan_runs ADD COLUMN IF NOT EXISTS timings JSONB;
--> bootstrap-breakpoint

-- source: artifacts/api-server/src/python/phase22_evidence.py:99
CREATE UNIQUE INDEX IF NOT EXISTS phase22_evidence_scan_sym_uidx
ON phase22_evidence (scan_id, symbol);
--> bootstrap-breakpoint

-- source: artifacts/api-server/src/python/phase24_store.py:83
ALTER TABLE phase24_missed_opps
    ADD COLUMN IF NOT EXISTS source TEXT NOT NULL DEFAULT 'live';
--> bootstrap-breakpoint

-- source: artifacts/api-server/src/python/phase24_store.py:86
ALTER TABLE phase24_missed_opps
    ADD COLUMN IF NOT EXISTS backtest_run_id TEXT;
--> bootstrap-breakpoint

-- source: artifacts/api-server/src/python/phase24_store.py:343
ALTER TABLE advisory_bot_outputs
ADD COLUMN IF NOT EXISTS advisory_only BOOLEAN NOT NULL DEFAULT TRUE;
--> bootstrap-breakpoint

-- source: artifacts/api-server/src/python/phase24_store.py:343
ALTER TABLE advisory_bot_outputs
ADD COLUMN IF NOT EXISTS paper_only BOOLEAN NOT NULL DEFAULT TRUE;
--> bootstrap-breakpoint

-- source: artifacts/api-server/src/python/phase24_store.py:343
ALTER TABLE advisory_decision_audit
ADD COLUMN IF NOT EXISTS advisory_only BOOLEAN NOT NULL DEFAULT TRUE;
--> bootstrap-breakpoint

-- source: artifacts/api-server/src/python/phase24_store.py:343
ALTER TABLE advisory_decision_audit
ADD COLUMN IF NOT EXISTS paper_only BOOLEAN NOT NULL DEFAULT TRUE;
--> bootstrap-breakpoint

-- source: artifacts/api-server/src/python/phase24_store.py:343
ALTER TABLE advisory_strategy_scores
ADD COLUMN IF NOT EXISTS advisory_only BOOLEAN NOT NULL DEFAULT TRUE;
--> bootstrap-breakpoint

-- source: artifacts/api-server/src/python/phase24_store.py:343
ALTER TABLE advisory_strategy_scores
ADD COLUMN IF NOT EXISTS paper_only BOOLEAN NOT NULL DEFAULT TRUE;
--> bootstrap-breakpoint

-- source: artifacts/api-server/src/python/phase24_store.py:343
ALTER TABLE advisory_universe_health
ADD COLUMN IF NOT EXISTS advisory_only BOOLEAN NOT NULL DEFAULT TRUE;
--> bootstrap-breakpoint

-- source: artifacts/api-server/src/python/phase24_store.py:343
ALTER TABLE advisory_universe_health
ADD COLUMN IF NOT EXISTS paper_only BOOLEAN NOT NULL DEFAULT TRUE;
--> bootstrap-breakpoint

-- source: artifacts/api-server/src/python/phase24_store.py:363
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_advisory_bot_outputs_advisory_only_true') THEN
        ALTER TABLE advisory_bot_outputs ADD CONSTRAINT ck_advisory_bot_outputs_advisory_only_true CHECK (advisory_only IS TRUE);
    END IF;
END $$;
--> bootstrap-breakpoint

-- source: artifacts/api-server/src/python/phase24_store.py:363
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_advisory_bot_outputs_paper_only_true') THEN
        ALTER TABLE advisory_bot_outputs ADD CONSTRAINT ck_advisory_bot_outputs_paper_only_true CHECK (paper_only IS TRUE);
    END IF;
END $$;
--> bootstrap-breakpoint

-- source: artifacts/api-server/src/python/phase24_store.py:363
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_advisory_decision_audit_advisory_only_true') THEN
        ALTER TABLE advisory_decision_audit ADD CONSTRAINT ck_advisory_decision_audit_advisory_only_true CHECK (advisory_only IS TRUE);
    END IF;
END $$;
--> bootstrap-breakpoint

-- source: artifacts/api-server/src/python/phase24_store.py:363
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_advisory_decision_audit_paper_only_true') THEN
        ALTER TABLE advisory_decision_audit ADD CONSTRAINT ck_advisory_decision_audit_paper_only_true CHECK (paper_only IS TRUE);
    END IF;
END $$;
--> bootstrap-breakpoint

-- source: artifacts/api-server/src/python/phase24_store.py:363
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_advisory_strategy_scores_advisory_only_true') THEN
        ALTER TABLE advisory_strategy_scores ADD CONSTRAINT ck_advisory_strategy_scores_advisory_only_true CHECK (advisory_only IS TRUE);
    END IF;
END $$;
--> bootstrap-breakpoint

-- source: artifacts/api-server/src/python/phase24_store.py:363
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_advisory_strategy_scores_paper_only_true') THEN
        ALTER TABLE advisory_strategy_scores ADD CONSTRAINT ck_advisory_strategy_scores_paper_only_true CHECK (paper_only IS TRUE);
    END IF;
END $$;
--> bootstrap-breakpoint

-- source: artifacts/api-server/src/python/phase24_store.py:363
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_advisory_universe_health_advisory_only_true') THEN
        ALTER TABLE advisory_universe_health ADD CONSTRAINT ck_advisory_universe_health_advisory_only_true CHECK (advisory_only IS TRUE);
    END IF;
END $$;
--> bootstrap-breakpoint

-- source: artifacts/api-server/src/python/phase24_store.py:363
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_advisory_universe_health_paper_only_true') THEN
        ALTER TABLE advisory_universe_health ADD CONSTRAINT ck_advisory_universe_health_paper_only_true CHECK (paper_only IS TRUE);
    END IF;
END $$;
--> bootstrap-breakpoint

-- source: artifacts/api-server/src/python/phase26_live_store.py:71
CREATE INDEX IF NOT EXISTS idx_p26_live_created
ON phase26_live_snapshots (created_at DESC);
--> bootstrap-breakpoint

-- source: artifacts/api-server/src/python/phase26_reports.py:96
CREATE INDEX IF NOT EXISTS idx_p26d_date_created
ON phase26_daily_reports (report_date DESC, created_at DESC);
--> bootstrap-breakpoint

-- source: artifacts/api-server/src/python/phase26_store.py:59
CREATE INDEX IF NOT EXISTS idx_p26_runs_created
ON phase26_validation_runs (created_at DESC);
--> bootstrap-breakpoint

-- source: artifacts/api-server/src/python/phase26c_store.py:60
CREATE INDEX IF NOT EXISTS idx_p26c_area_created
ON phase26c_results (area, created_at DESC);
--> bootstrap-breakpoint

-- source: artifacts/api-server/src/python/pipeline_events.py:109
ALTER TABLE pipeline_events ADD COLUMN IF NOT EXISTS dedupe_key TEXT;
--> bootstrap-breakpoint

-- source: artifacts/api-server/src/python/pipeline_events.py:113
CREATE INDEX IF NOT EXISTS idx_pipeline_events_scan ON pipeline_events (scan_id, id);
--> bootstrap-breakpoint

-- source: artifacts/api-server/src/python/pipeline_events.py:117
CREATE INDEX IF NOT EXISTS idx_pipeline_events_mode_id ON pipeline_events (mode, id DESC);
--> bootstrap-breakpoint

-- source: artifacts/api-server/src/python/pipeline_events.py:121
CREATE UNIQUE INDEX IF NOT EXISTS idx_pipeline_events_dedupe_key ON pipeline_events (dedupe_key) WHERE dedupe_key IS NOT NULL;
--> bootstrap-breakpoint

-- source: artifacts/api-server/src/python/portfolio_store.py:134
ALTER TABLE paper_trades ADD COLUMN IF NOT EXISTS archived_at TIMESTAMPTZ;
--> bootstrap-breakpoint

-- source: artifacts/api-server/src/python/portfolio_store.py:137
CREATE INDEX IF NOT EXISTS paper_trades_symbol_idx ON paper_trades (symbol);
--> bootstrap-breakpoint

-- source: artifacts/api-server/src/python/portfolio_store.py:140
CREATE INDEX IF NOT EXISTS paper_trades_ts_idx ON paper_trades (trade_ts);
--> bootstrap-breakpoint

-- source: artifacts/api-server/src/python/preopen_db.py:81
ALTER TABLE preopen_sessions
    ADD COLUMN IF NOT EXISTS provider_collected_count INTEGER,
    ADD COLUMN IF NOT EXISTS persisted_count INTEGER,
    ADD COLUMN IF NOT EXISTS failed_count INTEGER,
    ADD COLUMN IF NOT EXISTS expected_count INTEGER,
    ADD COLUMN IF NOT EXISTS provider_returned_count INTEGER,
    ADD COLUMN IF NOT EXISTS normalized_count INTEGER,
    ADD COLUMN IF NOT EXISTS missing_count INTEGER,
    ADD COLUMN IF NOT EXISTS duplicate_count INTEGER,
    ADD COLUMN IF NOT EXISTS malformed_count INTEGER,
    ADD COLUMN IF NOT EXISTS collection_coverage JSONB,
    ADD COLUMN IF NOT EXISTS collection_started_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS collection_completed_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS collection_source TEXT,
    ADD COLUMN IF NOT EXISTS persistence_status TEXT,
    ADD COLUMN IF NOT EXISTS verified_collection_batch_id TEXT,
    ADD COLUMN IF NOT EXISTS frozen_collection_batch_id TEXT,
    ADD COLUMN IF NOT EXISTS retry_state TEXT,
    ADD COLUMN IF NOT EXISTS phase_state JSONB NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS universe_context JSONB;
--> bootstrap-breakpoint

-- source: artifacts/api-server/src/python/preopen_db.py:103
CREATE INDEX IF NOT EXISTS idx_preopen_sessions_date
ON preopen_sessions (trading_date DESC);
--> bootstrap-breakpoint

-- source: artifacts/api-server/src/python/preopen_db.py:147
CREATE INDEX IF NOT EXISTS idx_preopen_snaps_date_sym
ON preopen_snapshots (trading_date, symbol);
--> bootstrap-breakpoint

-- source: artifacts/api-server/src/python/preopen_db.py:153
ALTER TABLE preopen_snapshots
    ADD COLUMN IF NOT EXISTS collection_batch_id TEXT;
--> bootstrap-breakpoint

-- source: artifacts/api-server/src/python/preopen_db.py:157
CREATE INDEX IF NOT EXISTS idx_preopen_snaps_session
ON preopen_snapshots (session_id);
--> bootstrap-breakpoint

-- source: artifacts/api-server/src/python/preopen_db.py:161
CREATE INDEX IF NOT EXISTS idx_preopen_snaps_session_batch
ON preopen_snapshots (session_id, collection_batch_id);
--> bootstrap-breakpoint

-- source: artifacts/api-server/src/python/preopen_db.py:187
CREATE INDEX IF NOT EXISTS idx_preopen_outcomes_session_batch
ON preopen_collection_outcomes (session_id, collection_batch_id);
--> bootstrap-breakpoint

-- source: artifacts/api-server/src/python/preopen_db.py:204
CREATE INDEX IF NOT EXISTS idx_preopen_rankings_date
ON preopen_rankings (trading_date DESC);
--> bootstrap-breakpoint

-- source: artifacts/api-server/src/python/preopen_db.py:221
CREATE INDEX IF NOT EXISTS idx_preopen_watchlists_date_type
ON preopen_watchlists (trading_date, list_type);
--> bootstrap-breakpoint

-- source: artifacts/api-server/src/python/preopen_db.py:241
CREATE INDEX IF NOT EXISTS idx_preopen_health_date
ON preopen_provider_health (trading_date DESC, checked_at DESC);
--> bootstrap-breakpoint

-- source: artifacts/api-server/src/python/preopen_db.py:267
CREATE INDEX IF NOT EXISTS idx_preopen_recon_date_sym
ON preopen_reconciliation (trading_date, symbol);
--> bootstrap-breakpoint

-- source: artifacts/api-server/src/python/preopen_validation_db.py:60
CREATE INDEX IF NOT EXISTS idx_val_sessions_date
ON preopen_validation_sessions (trading_date DESC);
--> bootstrap-breakpoint

-- source: artifacts/api-server/src/python/preopen_validation_db.py:113
CREATE INDEX IF NOT EXISTS idx_val_outcomes_date_sym
ON preopen_candidate_outcomes (trading_date, symbol);
--> bootstrap-breakpoint

-- source: artifacts/api-server/src/python/preopen_validation_db.py:117
CREATE INDEX IF NOT EXISTS idx_val_outcomes_session
ON preopen_candidate_outcomes (session_id);
--> bootstrap-breakpoint

-- source: artifacts/api-server/src/python/preopen_validation_db.py:121
CREATE UNIQUE INDEX IF NOT EXISTS idx_val_outcomes_date_sym_unique
ON preopen_candidate_outcomes (trading_date, symbol);
--> bootstrap-breakpoint

-- source: artifacts/api-server/src/python/preopen_validation_db.py:147
CREATE INDEX IF NOT EXISTS idx_val_score_bands_date
ON preopen_score_band_metrics (trading_date DESC);
--> bootstrap-breakpoint

-- source: artifacts/api-server/src/python/preopen_validation_db.py:168
CREATE INDEX IF NOT EXISTS idx_val_factor_metrics_date
ON preopen_factor_metrics (trading_date DESC);
--> bootstrap-breakpoint

-- source: artifacts/api-server/src/python/preopen_validation_db.py:189
CREATE INDEX IF NOT EXISTS idx_val_daily_reports_date
ON preopen_daily_reports (trading_date DESC);
--> bootstrap-breakpoint

-- source: artifacts/api-server/src/python/scan_state_store.py:85
ALTER TABLE scan_state
    ADD COLUMN IF NOT EXISTS trigger_origin TEXT NOT NULL DEFAULT 'UNKNOWN',
    ADD COLUMN IF NOT EXISTS universe_context JSONB;
--> bootstrap-breakpoint

-- source: artifacts/api-server/src/python/signals_store.py:80
ALTER TABLE signal_snapshots
ADD COLUMN IF NOT EXISTS canonical_scan_id TEXT;
--> bootstrap-breakpoint

-- source: artifacts/api-server/src/python/signals_store.py:86
CREATE UNIQUE INDEX IF NOT EXISTS signal_snapshots_scan_id_uidx
ON signal_snapshots (scan_id);
--> bootstrap-breakpoint

-- source: artifacts/api-server/src/python/signals_store.py:92
CREATE INDEX IF NOT EXISTS signal_snapshots_ts_idx
ON signal_snapshots (snapshot_ts DESC);
--> bootstrap-breakpoint

-- source: artifacts/api-server/src/python/simulation_lab.py:93
CREATE INDEX IF NOT EXISTS idx_sim_runs_created ON sim_runs (created_at DESC);
--> bootstrap-breakpoint

-- source: artifacts/api-server/src/python/universe_management.py:315
CREATE INDEX IF NOT EXISTS idx_trading_universe_validations_revision
ON trading_universe_validations (universe_id, checked_at DESC);
--> bootstrap-breakpoint

-- source: artifacts/api-server/src/python/universe_management.py:319
CREATE OR REPLACE FUNCTION task947_reject_management_history()
RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'Universe management history is append-only';
END;
$$ LANGUAGE plpgsql;
--> bootstrap-breakpoint

-- source: artifacts/api-server/src/python/universe_management.py:327
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_trigger
        WHERE tgname = 'trg_task947_details_immutable'
    ) THEN
        CREATE TRIGGER trg_task947_details_immutable
        BEFORE UPDATE OR DELETE ON trading_universe_member_details
        FOR EACH ROW EXECUTE FUNCTION task947_reject_management_history();
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_trigger
        WHERE tgname = 'trg_task947_validation_immutable'
    ) THEN
        CREATE TRIGGER trg_task947_validation_immutable
        BEFORE UPDATE OR DELETE ON trading_universe_validations
        FOR EACH ROW EXECUTE FUNCTION task947_reject_management_history();
    END IF;
END
$$;
--> bootstrap-breakpoint

-- source: artifacts/api-server/src/python/universe_version_store.py:124
CREATE INDEX IF NOT EXISTS idx_trading_universes_lookup
ON trading_universes (universe_key, status, effective_from);
--> bootstrap-breakpoint

-- source: artifacts/api-server/src/python/universe_version_store.py:133
CREATE UNIQUE INDEX IF NOT EXISTS uq_trading_universes_one_draft
ON trading_universes (universe_key)
WHERE status = 'DRAFT';
--> bootstrap-breakpoint

-- source: artifacts/api-server/src/python/universe_version_store.py:162
CREATE UNIQUE INDEX IF NOT EXISTS
    uq_trading_universe_enabled_token
ON trading_universe_members (universe_id, instrument_token)
WHERE enabled AND instrument_token IS NOT NULL;
--> bootstrap-breakpoint

-- source: artifacts/api-server/src/python/universe_version_store.py:170
CREATE INDEX IF NOT EXISTS idx_trading_universe_members_symbol
ON trading_universe_members (symbol, enabled);
--> bootstrap-breakpoint

-- source: artifacts/api-server/src/python/universe_version_store.py:204
CREATE INDEX IF NOT EXISTS idx_trading_universe_audit_lookup
ON trading_universe_audit_events (universe_key, occurred_at DESC);
--> bootstrap-breakpoint

-- source: artifacts/api-server/src/python/universe_version_store.py:230
CREATE OR REPLACE FUNCTION task946_reject_history_mutation()
RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'Task 946 history is append-only: % on % is forbidden',
        TG_OP, TG_TABLE_NAME;
END;
$$ LANGUAGE plpgsql;
--> bootstrap-breakpoint

-- source: artifacts/api-server/src/python/universe_version_store.py:241
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_trigger
        WHERE tgname = 'trg_task946_audit_immutable'
    ) THEN
        CREATE TRIGGER trg_task946_audit_immutable
        BEFORE UPDATE OR DELETE ON trading_universe_audit_events
        FOR EACH ROW EXECUTE FUNCTION task946_reject_history_mutation();
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_trigger
        WHERE tgname = 'trg_task946_member_history_guard'
    ) THEN


        CREATE TRIGGER trg_task946_member_history_guard
        BEFORE UPDATE OR DELETE ON trading_universe_members
        FOR EACH ROW EXECUTE FUNCTION task946_reject_history_mutation();
    END IF;
END
$$;
--> bootstrap-breakpoint

-- source: artifacts/api-server/src/python/universe_version_store.py:416
CREATE OR REPLACE FUNCTION task946_guard_revision_snapshot()
RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'Universe revisions cannot be deleted';
    END IF;
    IF OLD.universe_key IS DISTINCT FROM NEW.universe_key
       OR OLD.display_name IS DISTINCT FROM NEW.display_name
       OR OLD.version IS DISTINCT FROM NEW.version
       OR OLD.created_at IS DISTINCT FROM NEW.created_at
       OR OLD.created_by IS DISTINCT FROM NEW.created_by
       OR OLD.notes IS DISTINCT FROM NEW.notes
       OR OLD.exact_set_hash IS DISTINCT FROM NEW.exact_set_hash
       OR OLD.enabled_symbol_count IS DISTINCT FROM NEW.enabled_symbol_count
       OR OLD.source_id IS DISTINCT FROM NEW.source_id THEN
        RAISE EXCEPTION 'Universe revision snapshot fields are immutable';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
--> bootstrap-breakpoint

-- source: artifacts/api-server/src/python/universe_version_store.py:440
CREATE OR REPLACE FUNCTION task946_guard_member_write()
RETURNS trigger AS $$
DECLARE revision_status TEXT;
BEGIN
    IF TG_OP IN ('UPDATE', 'DELETE') THEN
        RAISE EXCEPTION 'Universe members are immutable once recorded';
    END IF;
    SELECT status INTO revision_status
    FROM trading_universes WHERE id = NEW.universe_id;
    IF revision_status IS DISTINCT FROM 'DRAFT' THEN
        RAISE EXCEPTION 'Members may only be added to DRAFT revisions';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
--> bootstrap-breakpoint

-- source: artifacts/api-server/src/python/universe_version_store.py:459
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_trigger
        WHERE tgname = 'trg_task946_source_immutable'
    ) THEN
        CREATE TRIGGER trg_task946_source_immutable
        BEFORE UPDATE OR DELETE ON trading_universe_sources
        FOR EACH ROW EXECUTE FUNCTION task946_reject_history_mutation();
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_trigger
        WHERE tgname = 'trg_task946_audit_immutable'
    ) THEN
        CREATE TRIGGER trg_task946_audit_immutable
        BEFORE UPDATE OR DELETE ON trading_universe_audit_events
        FOR EACH ROW EXECUTE FUNCTION task946_reject_history_mutation();
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_trigger
        WHERE tgname = 'trg_task946_member_guard'
    ) THEN
        CREATE TRIGGER trg_task946_member_guard
        BEFORE INSERT OR UPDATE OR DELETE ON trading_universe_members
        FOR EACH ROW EXECUTE FUNCTION task946_guard_member_write();
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_trigger
        WHERE tgname = 'trg_task946_revision_guard'
    ) THEN
        CREATE TRIGGER trg_task946_revision_guard
        BEFORE UPDATE OR DELETE ON trading_universes
        FOR EACH ROW EXECUTE FUNCTION task946_guard_revision_snapshot();
    END IF;
END
$$;
--> bootstrap-breakpoint

-- source: artifacts/api-server/src/python/validation_v2_engine.py:193
ALTER TABLE IF EXISTS validation_v2_runs
    ADD COLUMN IF NOT EXISTS symbols_done  INTEGER DEFAULT 0,
    ADD COLUMN IF NOT EXISTS symbols_total INTEGER DEFAULT 0,
    ADD COLUMN IF NOT EXISTS current_symbol TEXT DEFAULT '',
    ADD COLUMN IF NOT EXISTS symbol_errors JSONB DEFAULT '[]',
    ADD COLUMN IF NOT EXISTS strategies JSONB NOT NULL DEFAULT '[]',
    ADD COLUMN IF NOT EXISTS error TEXT,
    ADD COLUMN IF NOT EXISTS last_progress_at TIMESTAMPTZ DEFAULT NOW();
ALTER TABLE IF EXISTS validation_v2_decisions
    ADD COLUMN IF NOT EXISTS stage TEXT DEFAULT '';
ALTER TABLE IF EXISTS validation_v2_decisions
    ALTER COLUMN stage SET DEFAULT '',
    ADD COLUMN IF NOT EXISTS strategy TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS recommendation TEXT,
    ADD COLUMN IF NOT EXISTS final_confidence DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS entry_signal BOOLEAN DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS filter_passed BOOLEAN DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS rr_ratio DOUBLE PRECISION;
ALTER TABLE IF EXISTS validation_v2_trades
    ADD COLUMN IF NOT EXISTS trailing_stop DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS recommendation TEXT;
ALTER TABLE IF EXISTS validation_v2_missed
    ADD COLUMN IF NOT EXISTS strategy TEXT NOT NULL DEFAULT '';
--> bootstrap-breakpoint
