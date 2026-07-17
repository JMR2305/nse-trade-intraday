#!/usr/bin/env node
/**
 * Tests for safe-migrate: SQL classification, protected-table guard,
 * backup/verify, and an end-to-end scratch run against the dev database
 * using a representative copy of the production schema.
 *
 * Never touches real production tables destructively: the end-to-end test
 * operates only on scratch tables prefixed `smtest_`.
 */
import { execFileSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import pg from "pg";
import { classifyMigration, classifyStatement } from "./safe-migrate.mjs";

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

// ── 2. Guard blocks destructive migration on protected table ────────────────
console.log("== Destructive-migration guard (end-to-end) ==");
const MIG_DIR = path.join(ROOT, "migrations");
const guardFile = path.join(MIG_DIR, "9999_smtest_guard.sql");
fs.writeFileSync(guardFile, 'DROP TABLE "phase20_settings";\n');
try {
  let blocked = false, output = "";
  try {
    output = execFileSync("node", [SAFE, "migrate"],
      { cwd: ROOT, encoding: "utf8", stdio: ["ignore", "pipe", "pipe"],
        env: { ...process.env, SAFE_MIGRATE_CONFIRM: "" } });
  } catch (err) {
    blocked = err.status === 2;
    output = String(err.stdout) + String(err.stderr);
  }
  check("destructive migration BLOCKED without confirmation", blocked, output.slice(0, 200));
  check("block message names protected table", output.includes("phase20_settings"));
  check("block requires verified backup", /VERIFIED backup/i.test(output));
  check("block requires plan file", /plan/i.test(output));
  check("block requires confirm phrase", /SAFE_MIGRATE_CONFIRM/.test(output));
} finally {
  fs.rmSync(guardFile, { force: true });
}

// ── 3. Additive migration applies cleanly on scratch table ──────────────────
console.log("== Additive migration applies (scratch) ==");
const client = new pg.Client({ connectionString: process.env.DATABASE_URL });
await client.connect();
const addFile = path.join(MIG_DIR, "9998_smtest_add.sql");
try {
  await client.query('DROP TABLE IF EXISTS "smtest_scratch"');
  fs.writeFileSync(addFile, [
    'CREATE TABLE "smtest_scratch" (id int primary key);',
    "--> statement-breakpoint",
    'ALTER TABLE "smtest_scratch" ADD COLUMN note text;',
  ].join("\n"));
  execFileSync("node", [SAFE, "migrate"], { cwd: ROOT, stdio: "pipe" });
  const { rows } = await client.query(
    "SELECT column_name FROM information_schema.columns WHERE table_name='smtest_scratch' ORDER BY 1");
  check("scratch table created with added column",
    rows.map((r) => r.column_name).join(",") === "id,note");
  const ledger = await client.query(
    "SELECT baseline FROM _safe_migrations WHERE filename='9998_smtest_add.sql'");
  check("migration recorded in ledger", ledger.rowCount === 1 && ledger.rows[0].baseline === false);
} finally {
  fs.rmSync(addFile, { force: true });
  await client.query('DROP TABLE IF EXISTS "smtest_scratch"');
  await client.query("DELETE FROM _safe_migrations WHERE filename LIKE '999%smtest%'");
}

// ── 4. Protected-table data preservation across migrate ─────────────────────
console.log("== Protected data preserved ==");
{
  const before = await client.query("SELECT COUNT(*) AS n FROM phase20_settings");
  // run a no-op migrate (no pending files)
  execFileSync("node", [SAFE, "migrate"], { cwd: ROOT, stdio: "pipe" });
  const after = await client.query("SELECT COUNT(*) AS n FROM phase20_settings");
  check("phase20_settings row count unchanged", before.rows[0].n === after.rows[0].n);
}

// ── 5. Backup + verify round-trip ────────────────────────────────────────────
console.log("== Backup & verify ==");
{
  execFileSync("node", [SAFE, "backup"], { cwd: ROOT, stdio: "pipe" });
  const out = execFileSync("node", [SAFE, "verify-backup"], { cwd: ROOT, encoding: "utf8" });
  check("backup verifies", /VERIFIED/.test(out), out);
}

await client.end();
console.log(`\n${passed} passed, ${failed} failed`);
process.exit(failed ? 1 : 0);
