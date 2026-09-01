-- Development-schema parity for Python-owned universe authority evidence.
--
-- Replit Publish compares development and production schemas directly.
-- Production acquired these append-only tables through the guarded baseline
-- authority workflow, while development did not. Their absence in development
-- was therefore rendered as destructive DROP TABLE statements for production.
--
-- This migration is additive and idempotent. It creates only missing
-- development structures and never alters, deletes, truncates, or replaces
-- production authority data.

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
--> statement-breakpoint

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
--> statement-breakpoint

CREATE INDEX IF NOT EXISTS "idx_trading_universes_lookup"
  ON "trading_universes" ("universe_key", "status", "effective_from");
--> statement-breakpoint

CREATE UNIQUE INDEX IF NOT EXISTS "uq_trading_universes_one_draft"
  ON "trading_universes" ("universe_key")
  WHERE "status" = 'DRAFT';
--> statement-breakpoint

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
--> statement-breakpoint

CREATE UNIQUE INDEX IF NOT EXISTS "uq_trading_universe_enabled_token"
  ON "trading_universe_members" ("universe_id", "instrument_token")
  WHERE "enabled" AND "instrument_token" IS NOT NULL;
--> statement-breakpoint

CREATE INDEX IF NOT EXISTS "idx_trading_universe_members_symbol"
  ON "trading_universe_members" ("symbol", "enabled");
--> statement-breakpoint

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
    UNIQUE ("action", "correlation_id")
);
--> statement-breakpoint

CREATE INDEX IF NOT EXISTS "idx_trading_universe_audit_lookup"
  ON "trading_universe_audit_events" ("universe_key", "occurred_at" DESC);
--> statement-breakpoint

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
--> statement-breakpoint

CREATE TABLE IF NOT EXISTS "trading_universe_member_details" (
  "universe_id" BIGINT NOT NULL REFERENCES "trading_universes"("id"),
  "symbol" TEXT NOT NULL,
  "metadata" JSONB NOT NULL DEFAULT '{}'::jsonb,
  "created_at" TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  "created_by" TEXT NOT NULL,
  PRIMARY KEY ("universe_id", "symbol")
);
--> statement-breakpoint

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
--> statement-breakpoint

CREATE INDEX IF NOT EXISTS "idx_trading_universe_validations_revision"
  ON "trading_universe_validations" ("universe_id", "checked_at" DESC);
--> statement-breakpoint

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
--> statement-breakpoint

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
--> statement-breakpoint

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
--> statement-breakpoint

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
--> statement-breakpoint

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