#!/usr/bin/env node
/**
 * safe-migrate.mjs — versioned, guarded schema migrations.
 *
 * Replaces `drizzle-kit push` (which diffs the live DB against the Drizzle
 * schema and can propose DROPPING every table it does not know about —
 * scheduler state, settings, Kite tokens, evidence, ...).
 *
 * Commands:
 *   generate --name <n>  Generate a versioned SQL migration from schema diff
 *   dry-run              Show pending migrations + change/risk classification
 *   migrate              Apply pending migrations (destructive ops on
 *                        protected tables are BLOCKED unless explicitly
 *                        confirmed with a verified backup — see below)
 *   baseline             Mark all pending migrations as applied WITHOUT
 *                        executing them (for pre-existing databases)
 *   backup               pg_dump all protected tables + row-count manifest
 *   verify-backup        Verify the newest backup matches its manifest
 *
 * Destructive migration unlock (ALL required):
 *   1. A verified backup created in the last 24h (backup + verify-backup)
 *   2. A migration plan file:  migrations/<file>.plan.md
 *   3. env SAFE_MIGRATE_CONFIRM="I HAVE A VERIFIED BACKUP AND APPROVE DESTRUCTIVE MIGRATION"
 */
import { execFileSync, spawnSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import crypto from "node:crypto";
import { fileURLToPath } from "node:url";
import pg from "pg";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.join(__dirname, "..");
const MIGRATIONS_DIR = path.join(ROOT, "migrations");
const BACKUPS_DIR = path.join(ROOT, "backups");
const REGISTRY = JSON.parse(
  fs.readFileSync(path.join(ROOT, "protected-tables.json"), "utf8"),
);
const PROTECTED = new Set(REGISTRY.protected.map((t) => t.toLowerCase()));
const CONFIRM_PHRASE =
  "I HAVE A VERIFIED BACKUP AND APPROVE DESTRUCTIVE MIGRATION";
const LEDGER = "_safe_migrations";

const DATABASE_URL = process.env.DATABASE_URL;
if (!DATABASE_URL) {
  console.error("DATABASE_URL is not set");
  process.exit(1);
}

function client() {
  return new pg.Client({ connectionString: DATABASE_URL });
}

// ── SQL classification ───────────────────────────────────────────────────────

const ident = String.raw`"?([A-Za-z_][A-Za-z0-9_]*)"?`;
const RULES = [
  { kind: "table_added", re: new RegExp(`\\bCREATE\\s+TABLE\\s+(?:IF\\s+NOT\\s+EXISTS\\s+)?(?:${ident}\\.)?${ident}`, "i"), destructive: false },
  { kind: "column_added", re: new RegExp(`\\bALTER\\s+TABLE\\s+(?:ONLY\\s+)?(?:IF\\s+EXISTS\\s+)?(?:${ident}\\.)?${ident}[\\s\\S]*?\\bADD\\s+COLUMN\\b`, "i"), destructive: false },
  { kind: "column_changed", re: new RegExp(`\\bALTER\\s+TABLE\\s+(?:ONLY\\s+)?(?:IF\\s+EXISTS\\s+)?(?:${ident}\\.)?${ident}[\\s\\S]*?\\bALTER\\s+COLUMN\\b`, "i"), destructive: false },
  { kind: "column_dropped", re: new RegExp(`\\bALTER\\s+TABLE\\s+(?:ONLY\\s+)?(?:IF\\s+EXISTS\\s+)?(?:${ident}\\.)?${ident}[\\s\\S]*?\\bDROP\\s+COLUMN\\b`, "i"), destructive: true },
  { kind: "table_dropped", re: new RegExp(`\\bDROP\\s+TABLE\\s+(?:IF\\s+EXISTS\\s+)?(?:${ident}\\.)?${ident}`, "i"), destructive: true },
  { kind: "table_truncated", re: new RegExp(`\\bTRUNCATE\\s+(?:TABLE\\s+)?(?:ONLY\\s+)?(?:${ident}\\.)?${ident}`, "i"), destructive: true },
  { kind: "rows_deleted", re: new RegExp(`\\bDELETE\\s+FROM\\s+(?:ONLY\\s+)?(?:${ident}\\.)?${ident}`, "i"), destructive: true },
  { kind: "table_renamed", re: new RegExp(`\\bALTER\\s+TABLE\\s+(?:ONLY\\s+)?(?:IF\\s+EXISTS\\s+)?(?:${ident}\\.)?${ident}[\\s\\S]*?\\bRENAME\\s+TO\\b`, "i"), destructive: true },
];

export function classifyStatement(stmt) {
  const s = stmt.trim();
  if (!s) return null;
  for (const rule of RULES) {
    const m = rule.re.exec(s);
    if (m) {
      // last two capture groups are (schema, table); table is the last defined
      const groups = m.slice(1).filter((g) => g !== undefined);
      const table = (groups[groups.length - 1] || "").toLowerCase();
      return {
        kind: rule.kind,
        table,
        destructive: rule.destructive,
        protected: PROTECTED.has(table),
        sql: s.length > 160 ? s.slice(0, 160) + " …" : s,
      };
    }
  }
  return { kind: "other", table: "", destructive: false, protected: false,
           sql: s.length > 160 ? s.slice(0, 160) + " …" : s };
}

export function classifyMigration(sqlText) {
  const statements = sqlText
    .split(/-->\s*statement-breakpoint/i)
    .flatMap((chunk) => (chunk.includes("statement-breakpoint") ? [chunk] : [chunk]))
    .map((s) => s.trim())
    .filter(Boolean);
  const findings = statements.map(classifyStatement).filter(Boolean);
  const summary = {
    tablesAdded: findings.filter((f) => f.kind === "table_added").map((f) => f.table),
    columnsAdded: findings.filter((f) => f.kind === "column_added").map((f) => f.table),
    columnsChanged: findings.filter((f) => f.kind === "column_changed").map((f) => f.table),
    destructive: findings.filter((f) => f.destructive),
    tablesAtRisk: [...new Set(findings.filter((f) => f.destructive).map((f) => f.table))],
    protectedAtRisk: [...new Set(findings.filter((f) => f.destructive && f.protected).map((f) => f.table))],
  };
  summary.dataLossRisk = summary.destructive.length > 0;
  return { findings, summary };
}

// ── Ledger / pending ─────────────────────────────────────────────────────────

async function ensureLedger(c) {
  await c.query(`CREATE TABLE IF NOT EXISTS ${LEDGER} (
    filename TEXT PRIMARY KEY,
    hash TEXT NOT NULL,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    baseline BOOLEAN NOT NULL DEFAULT FALSE
  )`);
}

function migrationFiles() {
  if (!fs.existsSync(MIGRATIONS_DIR)) return [];
  return fs.readdirSync(MIGRATIONS_DIR).filter((f) => f.endsWith(".sql")).sort();
}

async function pendingMigrations(c) {
  await ensureLedger(c);
  const { rows } = await c.query(`SELECT filename FROM ${LEDGER}`);
  const applied = new Set(rows.map((r) => r.filename));
  return migrationFiles().filter((f) => !applied.has(f));
}

const hashOf = (text) => crypto.createHash("sha256").update(text).digest("hex");

// ── Backup / verify ──────────────────────────────────────────────────────────

async function rowCounts(c, tables) {
  const counts = {};
  for (const t of tables) {
    const { rows } = await c.query(
      "SELECT EXISTS (SELECT 1 FROM pg_tables WHERE schemaname='public' AND tablename=$1) AS e", [t]);
    counts[t] = rows[0].e
      ? Number((await c.query(`SELECT COUNT(*) AS n FROM "${t}"`)).rows[0].n)
      : null; // table does not exist yet
  }
  return counts;
}

async function cmdBackup() {
  fs.mkdirSync(BACKUPS_DIR, { recursive: true });
  const c = client(); await c.connect();
  try {
    const tables = [...PROTECTED].sort();
    const counts = await rowCounts(c, tables);
    const existing = tables.filter((t) => counts[t] !== null);
    const ts = new Date().toISOString().replace(/[:.]/g, "-");
    const file = path.join(BACKUPS_DIR, `backup-${ts}.sql`);
    const args = ["--no-owner", "--no-privileges", "--dbname", DATABASE_URL];
    for (const t of existing) args.push("-t", `public.${t}`);
    execFileSync("pg_dump", [...args, "-f", file], { stdio: "inherit" });
    const manifest = {
      file: path.basename(file),
      created_at: new Date().toISOString(),
      tables: existing,
      row_counts: counts,
      sha256: hashOf(fs.readFileSync(file, "utf8")),
      verified: false,
    };
    fs.writeFileSync(file + ".manifest.json", JSON.stringify(manifest, null, 2));
    console.log(`Backup written: ${file}`);
    console.log(`Tables: ${existing.length}, total rows: ${existing.reduce((a, t) => a + counts[t], 0)}`);
    console.log("Run `verify-backup` to verify it.");
  } finally { await c.end(); }
}

function newestBackupManifest() {
  if (!fs.existsSync(BACKUPS_DIR)) return null;
  const manifests = fs.readdirSync(BACKUPS_DIR)
    .filter((f) => f.endsWith(".manifest.json")).sort();
  if (!manifests.length) return null;
  const p = path.join(BACKUPS_DIR, manifests[manifests.length - 1]);
  return { path: p, data: JSON.parse(fs.readFileSync(p, "utf8")) };
}

async function cmdVerifyBackup() {
  const m = newestBackupManifest();
  if (!m) { console.error("No backup manifest found. Run `backup` first."); process.exit(1); }
  const dumpPath = path.join(BACKUPS_DIR, m.data.file);
  if (!fs.existsSync(dumpPath)) { console.error(`Dump missing: ${dumpPath}`); process.exit(1); }
  const text = fs.readFileSync(dumpPath, "utf8");
  if (hashOf(text) !== m.data.sha256) { console.error("Backup file hash mismatch — file was modified."); process.exit(1); }
  const problems = [];
  for (const t of m.data.tables) {
    if (!new RegExp(`CREATE TABLE (?:IF NOT EXISTS )?public\\."?${t}"?`, "i").test(text))
      problems.push(`missing CREATE TABLE for ${t}`);
    const expected = m.data.row_counts[t];
    if (expected > 0 && !new RegExp(`COPY public\\."?${t}"?`, "i").test(text))
      problems.push(`missing data COPY for ${t} (expected ${expected} rows)`);
  }
  if (problems.length) { console.error("Backup verification FAILED:\n - " + problems.join("\n - ")); process.exit(1); }
  m.data.verified = true;
  m.data.verified_at = new Date().toISOString();
  fs.writeFileSync(m.path, JSON.stringify(m.data, null, 2));
  console.log(`Backup VERIFIED: ${m.data.file} (${m.data.tables.length} tables, hash OK)`);
}

function verifiedRecentBackup() {
  const m = newestBackupManifest();
  if (!m || !m.data.verified || !m.data.verified_at) return null;
  const ageH = (Date.now() - Date.parse(m.data.verified_at)) / 3.6e6;
  return ageH <= 24 ? m : null;
}

// ── Commands ────────────────────────────────────────────────────────────────

function cmdGenerate(nameArg) {
  const name = nameArg || `migration_${Date.now()}`;
  const r = spawnSync("pnpm", ["exec", "drizzle-kit", "generate",
    "--config", "./drizzle.config.ts", "--name", name],
    { cwd: ROOT, stdio: "inherit" });
  process.exit(r.status ?? 1);
}

async function reportPending(c) {
  const pending = await pendingMigrations(c);
  if (!pending.length) { console.log("No pending migrations."); return []; }
  const report = [];
  for (const f of pending) {
    const sql = fs.readFileSync(path.join(MIGRATIONS_DIR, f), "utf8");
    const { summary } = classifyMigration(sql);
    report.push({ file: f, summary });
    console.log(`\n=== ${f} ===`);
    console.log(`  tables added:    ${summary.tablesAdded.join(", ") || "-"}`);
    console.log(`  columns added:   ${summary.columnsAdded.join(", ") || "-"}`);
    console.log(`  columns changed: ${summary.columnsChanged.join(", ") || "-"}`);
    console.log(`  tables at risk:  ${summary.tablesAtRisk.join(", ") || "-"}`);
    console.log(`  DATA-LOSS RISK:  ${summary.dataLossRisk ? "YES" : "no"}`);
    if (summary.protectedAtRisk.length)
      console.log(`  !! PROTECTED TABLES AT RISK: ${summary.protectedAtRisk.join(", ")}`);
    for (const d of summary.destructive) console.log(`    - [${d.kind}] ${d.sql}`);
  }
  return report;
}

async function cmdDryRun() {
  const c = client(); await c.connect();
  try { await reportPending(c); } finally { await c.end(); }
}

async function cmdBaseline() {
  const c = client(); await c.connect();
  try {
    const pending = await pendingMigrations(c);
    if (!pending.length) { console.log("Nothing to baseline."); return; }
    for (const f of pending) {
      const sql = fs.readFileSync(path.join(MIGRATIONS_DIR, f), "utf8");
      await c.query(
        `INSERT INTO ${LEDGER} (filename, hash, baseline) VALUES ($1, $2, TRUE)
         ON CONFLICT (filename) DO NOTHING`, [f, hashOf(sql)]);
      console.log(`baselined: ${f}`);
    }
  } finally { await c.end(); }
}

async function cmdMigrate() {
  const c = client(); await c.connect();
  try {
    const report = await reportPending(c);
    if (!report.length) return;

    const dangerous = report.filter((r) => r.summary.protectedAtRisk.length > 0);
    if (dangerous.length) {
      const confirmed = process.env.SAFE_MIGRATE_CONFIRM === CONFIRM_PHRASE;
      const backup = verifiedRecentBackup();
      const missingPlans = dangerous.filter(
        (r) => !fs.existsSync(path.join(MIGRATIONS_DIR, r.file + ".plan.md")));
      const reasons = [];
      if (!backup) reasons.push("no VERIFIED backup from the last 24h (run: backup, then verify-backup)");
      if (missingPlans.length) reasons.push(`missing migration plan file(s): ${missingPlans.map((r) => r.file + ".plan.md").join(", ")}`);
      if (!confirmed) reasons.push(`SAFE_MIGRATE_CONFIRM env var must equal exactly: "${CONFIRM_PHRASE}"`);
      if (reasons.length) {
        console.error("\nBLOCKED: migration would destructively modify PROTECTED tables:");
        for (const r of dangerous)
          console.error(`  ${r.file}: ${r.summary.protectedAtRisk.join(", ")}`);
        console.error("\nRequired before proceeding:\n - " + reasons.join("\n - "));
        process.exit(2);
      }
      console.log("\nDestructive migration UNLOCKED (verified backup + plan + explicit confirmation).");
    }

    // Pre-migration row counts for protected tables (loss check)
    const before = await rowCounts(c, [...PROTECTED]);

    for (const r of report) {
      const sql = fs.readFileSync(path.join(MIGRATIONS_DIR, r.file), "utf8");
      const statements = sql.split(/-->\s*statement-breakpoint/i).map((s) => s.trim()).filter(Boolean);
      await c.query("BEGIN");
      try {
        for (const stmt of statements) await c.query(stmt);
        await c.query(
          `INSERT INTO ${LEDGER} (filename, hash) VALUES ($1, $2)`,
          [r.file, hashOf(sql)]);
        await c.query("COMMIT");
        console.log(`applied: ${r.file}`);
      } catch (err) {
        await c.query("ROLLBACK");
        console.error(`FAILED (rolled back): ${r.file}\n${err.message}`);
        process.exit(1);
      }
    }

    // Post-migration loss check on protected tables that existed before
    const after = await rowCounts(c, [...PROTECTED]);
    const lost = Object.keys(before).filter(
      (t) => before[t] !== null && after[t] !== null && after[t] < before[t]);
    if (lost.length) {
      console.error(`WARNING: row count decreased on protected tables: ${lost.join(", ")}`);
      console.error("If this was not the explicit intent of an approved destructive migration, restore from the verified backup immediately.");
      process.exit(3);
    }
    console.log("All migrations applied. Protected-table row counts preserved.");
  } finally { await c.end(); }
}

// ── Entry point ──────────────────────────────────────────────────────────────

const [cmd, ...rest] = process.argv.slice(2);
const nameFlag = rest.includes("--name") ? rest[rest.indexOf("--name") + 1] : undefined;

const isMain = process.argv[1] && fileURLToPath(import.meta.url) === path.resolve(process.argv[1]);
if (isMain) {
  switch (cmd) {
    case "generate": cmdGenerate(nameFlag); break;
    case "dry-run": await cmdDryRun(); break;
    case "migrate": await cmdMigrate(); break;
    case "baseline": await cmdBaseline(); break;
    case "backup": await cmdBackup(); break;
    case "verify-backup": await cmdVerifyBackup(); break;
    default:
      console.log("Usage: safe-migrate.mjs <generate [--name n]|dry-run|migrate|baseline|backup|verify-backup>");
      process.exit(cmd ? 1 : 0);
  }
}
