#!/usr/bin/env node
/**
 * Tests for safe-migrate: SQL classification, protected-table guard,
 * offline adversarial cases, and an additive scratch run in an explicit disposable database
 * using a representative copy of the production schema.
 *
 * Requires a preloaded canonical disposable public schema for the legacy parity check.
 * No production connection, destructive sample execution, or DELETE/DROP cleanup.
 */
import { execFileSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import pg from "pg";
import { classifyMigration, classifyStatement, assertSafeMigration } from "./safe-migrate.mjs";

// Never fall back to an application's DATABASE_URL for integration tests.
const disposableUrl = process.env.TASK967_TEST_DATABASE_URL;
if (!disposableUrl) throw new Error("Set TASK967_TEST_DATABASE_URL to a disposable PostgreSQL instance");
const endpoint = new URL(disposableUrl);
if (!["postgres:", "postgresql:"].includes(endpoint.protocol) || endpoint.search || endpoint.hash ||
    !["127.0.0.1", "localhost", "[::1]"].includes(endpoint.hostname) ||
    !/^\/task967_disposable(?:_[a-z0-9_]+)?$/.test(endpoint.pathname)) {
  throw new Error("Only explicitly named local disposable databases are allowed");
}

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.join(__dirname, "..");
const SAFE = path.join(__dirname, "safe-migrate.mjs");

let passed = 0, failed = 0;
function check(name, cond, extra = "") {
  if (cond) { passed++; console.log(`  PASS  ${name}`); }
  else { failed++; console.log(`  FAIL  ${name} ${extra}`); }
}

// ── 1. Classification tests ──────────────────────────────────────────────────
console.log("== SQL classification ==");
{
  const c = classifyStatement('CREATE TABLE "widgets" (id int);');
  check("create table classified additive", c.kind === "table_added" && !c.destructive);

  const d = classifyStatement('DROP TABLE "phase20_settings";');
  check("drop of protected table flagged", d.kind === "table_dropped" && d.destructive && d.protected);

  const t = classifyStatement("TRUNCATE TABLE paper_trades;");
  check("truncate protected flagged", t.destructive && t.protected);

  const a = classifyStatement('ALTER TABLE "signals_cache" ADD COLUMN foo text;');
  check("add column additive", a.kind === "column_added" && !a.destructive);

  const dc = classifyStatement('ALTER TABLE "phase22_evidence" DROP COLUMN outcome;');
  check("drop column on protected flagged", dc.destructive && dc.protected);

  const del = classifyStatement("DELETE FROM phase20_kv;");
  check("delete rows flagged destructive", del.destructive && del.protected);

  const un = classifyStatement('DROP TABLE "smtest_scratch";');
  check("drop of unprotected table not protected", un.destructive && !un.protected);

  for (const table of [
    "runtime_universe_session_pins",
    "trading_universe_audit_events",
    "trading_universe_baseline_migrations",
    "trading_universe_member_details",
    "trading_universe_members",
    "trading_universe_sources",
    "trading_universe_validations",
    "trading_universes",
  ]) {
    for (const [operation, statement, kind] of [
      ["drop", `DROP TABLE "${table}" CASCADE;`, "table_dropped"],
      ["truncate", `TRUNCATE TABLE "${table}";`, "table_truncated"],
      ["delete", `DELETE FROM "${table}";`, "rows_deleted"],
      [
        "destructive alter",
        `ALTER TABLE "${table}" DROP COLUMN evidence;`,
        "column_dropped",
      ],
    ]) {
      const finding = classifyStatement(statement);
      check(
        `${operation} of universe authority table ${table} blocked`,
        finding.kind === kind && finding.destructive && finding.protected,
      );
    }
  }
}

{
  const sql = [
    'CREATE TABLE "new_thing" (id int);',
    '--> statement-breakpoint',
    'ALTER TABLE "paper_trades" ADD COLUMN note text;',
    '--> statement-breakpoint',
    'DROP TABLE "phase20_scheduler_state";',
  ].join("\n");
  const { summary } = classifyMigration(sql);
  check("summary tables added", summary.tablesAdded.includes("new_thing"));
  check("summary columns added", summary.columnsAdded.includes("paper_trades"));
  check("summary data-loss risk", summary.dataLossRisk === true);
  check("summary protected at risk", summary.protectedAtRisk.includes("phase20_scheduler_state"));
}

// ── 2. Full authority migration applies to a clean schema ───────────────────
console.log("== Clean-schema authority migration ==");
{
  const cleanClient = new pg.Client({ connectionString: disposableUrl });
  await cleanClient.connect();
  const authoritySql = fs.readFileSync(
    path.join(ROOT, "migrations", "0002_universe_authority_schema_parity.sql"),
    "utf8",
  );
  const authorityStatements = authoritySql
    .split(/-->\s*statement-breakpoint/i)
    .map((statement) => statement.trim())
    .filter(Boolean);
  try {
    await cleanClient.query("BEGIN");
    await cleanClient.query('CREATE SCHEMA "smtest_authority"');
    await cleanClient.query(
      'SET LOCAL search_path TO "smtest_authority", pg_catalog',
    );
    for (const statement of authorityStatements) {
      await cleanClient.query(statement);
    }

    const tables = await cleanClient.query(
      `SELECT table_name
       FROM information_schema.tables
       WHERE table_schema = 'smtest_authority'
         AND table_name = ANY($1::text[])
       ORDER BY table_name`,
      [[
        "runtime_universe_session_pins",
        "trading_universe_audit_events",
        "trading_universe_baseline_migrations",
        "trading_universe_member_details",
        "trading_universe_members",
        "trading_universe_sources",
        "trading_universe_validations",
        "trading_universes",
      ]],
    );
    check(
      "fresh schema contains complete authority table chain",
      tables.rowCount === 8,
      tables.rows.map((row) => row.table_name).join(","),
    );

    const triggers = await cleanClient.query(
      `SELECT trigger_name
       FROM information_schema.triggers
       WHERE trigger_schema = 'smtest_authority'
       GROUP BY trigger_name
       ORDER BY trigger_name`,
    );
    check(
      "fresh schema contains every append-only authority trigger",
      triggers.rowCount === 8,
      triggers.rows.map((row) => row.trigger_name).join(","),
    );

    const foreignKeys = await cleanClient.query(
      `SELECT COUNT(*)::int AS count
       FROM information_schema.table_constraints
       WHERE table_schema = 'smtest_authority'
         AND constraint_type = 'FOREIGN KEY'`,
    );
    check(
      "fresh schema creates authority foreign keys in dependency order",
      foreignKeys.rows[0].count === 5,
      String(foreignKeys.rows[0].count),
    );

    async function catalogSignature(schema) {
      const tableNames = tables.rows.map((row) => row.table_name);
      const columns = await cleanClient.query(
        `SELECT table_name, column_name, data_type, is_nullable,
                CASE
                  WHEN column_default LIKE 'nextval(%'
                    THEN 'nextval(<sequence>)'
                  ELSE COALESCE(column_default, '')
                END AS column_default
         FROM information_schema.columns
         WHERE table_schema = $1
           AND table_name = ANY($2::text[])
         ORDER BY table_name, ordinal_position`,
        [schema, tableNames],
      );
      const constraints = await cleanClient.query(
        `SELECT table_row.relname AS table_name,
                constraint_row.conname AS constraint_name,
                constraint_row.contype AS constraint_type,
                regexp_replace(
                  pg_get_constraintdef(constraint_row.oid),
                  '(public|smtest_authority)\\.',
                  '',
                  'g'
                ) AS definition
         FROM pg_constraint constraint_row
         JOIN pg_class table_row
           ON table_row.oid = constraint_row.conrelid
         JOIN pg_namespace namespace_row
           ON namespace_row.oid = table_row.relnamespace
         WHERE namespace_row.nspname = $1
           AND table_row.relname = ANY($2::text[])
         ORDER BY table_row.relname, constraint_row.conname`,
        [schema, tableNames],
      );
      const indexes = await cleanClient.query(
        `SELECT table_row.relname AS table_name,
                index_row.relname AS index_name,
                regexp_replace(
                  pg_get_indexdef(index_row.oid),
                  '(public|smtest_authority)\\.',
                  '',
                  'g'
                ) AS definition
         FROM pg_index index_metadata
         JOIN pg_class table_row
           ON table_row.oid = index_metadata.indrelid
         JOIN pg_class index_row
           ON index_row.oid = index_metadata.indexrelid
         JOIN pg_namespace namespace_row
           ON namespace_row.oid = table_row.relnamespace
         WHERE namespace_row.nspname = $1
           AND table_row.relname = ANY($2::text[])
         ORDER BY table_row.relname, index_row.relname`,
        [schema, tableNames],
      );
      const triggerRows = await cleanClient.query(
        `SELECT event_object_table, trigger_name, action_timing,
                string_agg(
                  event_manipulation,
                  ',' ORDER BY event_manipulation
                ) AS operations,
                regexp_replace(
                  action_statement,
                  '(public|smtest_authority)\\.',
                  '',
                  'g'
                ) AS action_statement
         FROM information_schema.triggers
         WHERE trigger_schema = $1
           AND event_object_table = ANY($2::text[])
         GROUP BY event_object_table, trigger_name, action_timing,
                  action_statement
         ORDER BY event_object_table, trigger_name`,
        [schema, tableNames],
      );
      return {
        columns: columns.rows,
        constraints: constraints.rows,
        indexes: indexes.rows,
        triggers: triggerRows.rows,
      };
    }

    const cleanCatalog = await catalogSignature("smtest_authority");
    const canonicalCatalog = await catalogSignature("public");
    const cleanCatalogJson = JSON.stringify(cleanCatalog);
    const canonicalCatalogJson = JSON.stringify(canonicalCatalog);
    check(
      "fresh schema exactly matches reconciled authority catalog",
      cleanCatalogJson === canonicalCatalogJson,
      cleanCatalogJson === canonicalCatalogJson
        ? ""
        : JSON.stringify({
            cleanOnly: Object.fromEntries(
              Object.entries(cleanCatalog).map(([key, rows]) => [
                key,
                rows.filter(
                  (row) => !canonicalCatalog[key].some(
                    (candidate) => JSON.stringify(candidate) === JSON.stringify(row),
                  ),
                ),
              ]),
            ),
            canonicalOnly: Object.fromEntries(
              Object.entries(canonicalCatalog).map(([key, rows]) => [
                key,
                rows.filter(
                  (row) => !cleanCatalog[key].some(
                    (candidate) => JSON.stringify(candidate) === JSON.stringify(row),
                  ),
                ),
              ]),
            ),
          }),
    );
  } finally {
    await cleanClient.query("ROLLBACK");
    await cleanClient.end();
  }
}

// ── 3. Destructive samples go only to offline guard validation ─────────────
execFileSync(process.execPath, ["--test", path.join(__dirname, "test-guard-adversarial.mjs")],
  { stdio: "inherit" });

// ── 4. Additive scratch validation, with no destructive cleanup ────────────
const client = new pg.Client({ connectionString: disposableUrl });
await client.connect();
try {
  await client.query("BEGIN");
  const schema = `task967_add_${process.pid}_${Date.now()}`;
  await client.query(`CREATE SCHEMA "${schema}"`);
  await client.query(`SET LOCAL search_path TO "${schema}"`);
  const statements = [
    'CREATE TABLE IF NOT EXISTS smtest_scratch (id int PRIMARY KEY)',
    'ALTER TABLE smtest_scratch ADD COLUMN note text',
  ];
  for (const sql of statements) { assertSafeMigration(sql); await client.query(sql); }
  const result = await client.query(
    "SELECT column_name FROM information_schema.columns WHERE table_schema=$1 AND table_name='smtest_scratch' ORDER BY column_name", [schema]);
  check("scratch table has additive column", result.rows.map(r => r.column_name).join(",") === "id,note");
} finally {
  await client.query("ROLLBACK");
  await client.end();
}

console.log(`\n${passed} passed, ${failed} failed`);
console.log("This legacy clean-schema check is not the full Task966 preservation/idempotency sequence.");
process.exit(failed ? 1 : 0);
