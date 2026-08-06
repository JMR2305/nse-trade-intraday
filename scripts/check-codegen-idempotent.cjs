#!/usr/bin/env node
/**
 * check-codegen-idempotent.js
 *
 * Regression guard for the orval duplicate-export bug (fixed in Task #392).
 *
 * What it catches
 * ───────────────
 * 1. Manually-maintained index mutation — orval writes to a file it should
 *    never touch (lib/api-client-react/src/index.ts).  This was the original
 *    bug: the barrel index.ts landed outside the clean:true zone, so it
 *    accumulated duplicate `export *` lines on every codegen run.
 *
 * 2. Non-idempotent output — running codegen twice produces different files.
 *    This catches any config regression where orval APPENDs instead of
 *    OVERWRITing a generated file.
 *
 * How it works
 * ────────────
 * 1. Hash the PROTECTED file (lib/api-client-react/src/index.ts) before.
 * 2. Run `pnpm --filter @workspace/api-spec run codegen:orval` (orval + fix step).
 * 3. Verify PROTECTED file is unchanged.
 * 4. Hash all files in both generated/ dirs + lib/api-zod/src/index.ts.
 * 5. Run codegen:orval again.
 * 6. Verify every hashed file is byte-for-byte identical between run 1 and run 2.
 * 7. Verify PROTECTED file still unchanged.
 *
 * Usage
 * ─────
 *   pnpm run codegen:check            (from workspace root)
 *   node ./scripts/check-codegen-idempotent.js
 *
 * Exit codes: 0 = all checks passed, 1 = regression detected.
 */

"use strict";

const { createHash } = require("crypto");
const { readFileSync, readdirSync, statSync, existsSync } = require("fs");
const { execSync }  = require("child_process");
const { resolve, join, relative } = require("path");

// ── Config ────────────────────────────────────────────────────────────────────

const ROOT = resolve(__dirname, "..");

/**
 * These files must NEVER be mutated by orval or any codegen step.
 * lib/api-client-react/src/index.ts is manually maintained — orval's
 * workspace is set to src/generated/ (inside clean:true zone) so it should
 * never touch the parent index.ts.
 */
const PROTECTED_FILES = [
  "lib/api-client-react/src/index.ts",
];

/**
 * Dirs/files included in the idempotency snapshot.
 * lib/api-zod/src/index.ts IS written by fix-zod-index.js (deterministic),
 * so it's not "protected" but MUST be identical between run 1 and run 2.
 */
const SNAPSHOT_TARGETS = [
  "lib/api-zod/src/generated",
  "lib/api-client-react/src/generated",
  "lib/api-zod/src/index.ts",
];

// ── Helpers ───────────────────────────────────────────────────────────────────

function hashFile(absPath) {
  return createHash("sha256").update(readFileSync(absPath)).digest("hex");
}

function walkDir(absDir, out) {
  for (const entry of readdirSync(absDir, { withFileTypes: true })) {
    const full = join(absDir, entry.name);
    if (entry.isDirectory()) walkDir(full, out);
    else out[relative(ROOT, full)] = hashFile(full);
  }
}

function snapshot() {
  const hashes = {};
  for (const target of SNAPSHOT_TARGETS) {
    const abs = resolve(ROOT, target);
    if (!existsSync(abs)) continue;
    if (statSync(abs).isDirectory()) walkDir(abs, hashes);
    else hashes[target] = hashFile(abs);
  }
  return hashes;
}

function protectedHashes() {
  const h = {};
  for (const f of PROTECTED_FILES) {
    const abs = resolve(ROOT, f);
    if (!existsSync(abs)) { h[f] = null; continue; }
    h[f] = hashFile(abs);
  }
  return h;
}

function diffSnapshots(a, b) {
  const changed = [];
  const allKeys = new Set([...Object.keys(a), ...Object.keys(b)]);
  for (const k of allKeys) {
    if (a[k] !== b[k]) changed.push(k);
  }
  return changed;
}

function runCodegen(label) {
  console.log(`\n──────────────────────────────────────────────────`);
  console.log(`  ${label}`);
  console.log(`──────────────────────────────────────────────────`);
  execSync("pnpm --filter @workspace/api-spec run codegen:orval", {
    cwd: ROOT,
    stdio: "inherit",
  });
}

// ── Main ──────────────────────────────────────────────────────────────────────

let exitCode = 0;

const protectedBefore = protectedHashes();

// ── Run 1 ─────────────────────────────────────────────────────────────────────
runCodegen("Codegen run 1 of 2");
const snap1           = snapshot();
const protectedAfter1 = protectedHashes();

// Check: PROTECTED files must not have changed after run 1
const mutatedRun1 = PROTECTED_FILES.filter(f => protectedBefore[f] !== protectedAfter1[f]);
if (mutatedRun1.length > 0) {
  console.error("\n✗ FAIL — orval mutated a manually-maintained file during run 1:");
  for (const f of mutatedRun1) {
    console.error(`    ${f}`);
    console.error(`      before: ${protectedBefore[f] ?? "(missing)"}`);
    console.error(`      after:  ${protectedAfter1[f] ?? "(missing)"}`);
  }
  console.error("\n  This is the duplicate-export regression.");
  console.error("  Check orval.config.ts: ensure `workspace` is inside the `clean: true` zone");
  console.error("  and `indexFiles: false` is set for the zod output.");
  exitCode = 1;
} else {
  console.log("\n✓ Protected index files unchanged after run 1");
}

// ── Run 2 ─────────────────────────────────────────────────────────────────────
runCodegen("Codegen run 2 of 2");
const snap2           = snapshot();
const protectedAfter2 = protectedHashes();

// Check: PROTECTED files must not have changed after run 2 either
const mutatedRun2 = PROTECTED_FILES.filter(f => protectedAfter1[f] !== protectedAfter2[f]);
if (mutatedRun2.length > 0) {
  console.error("\n✗ FAIL — orval mutated a manually-maintained file during run 2:");
  for (const f of mutatedRun2) console.error(`    ${f}`);
  exitCode = 1;
} else {
  console.log("✓ Protected index files unchanged after run 2");
}

// Check: idempotency — every generated file must be identical between run 1 and run 2
const drifted = diffSnapshots(snap1, snap2);
if (drifted.length > 0) {
  console.error("\n✗ FAIL — codegen is NOT idempotent (output changed between run 1 and run 2):");
  for (const f of drifted) {
    const h1 = snap1[f] ? snap1[f].slice(0, 12) : "(missing)";
    const h2 = snap2[f] ? snap2[f].slice(0, 12) : "(missing)";
    console.error(`    ${f}`);
    console.error(`      run 1: ${h1}…`);
    console.error(`      run 2: ${h2}…`);
  }
  console.error("\n  This means orval is appending to an existing file instead of overwriting it.");
  console.error("  Check that the orval workspace is inside the `clean: true` zone");
  console.error("  in lib/api-spec/orval.config.ts.");
  exitCode = 1;
} else {
  console.log("✓ Codegen output is idempotent (run 1 === run 2)");
}

// ── Result ────────────────────────────────────────────────────────────────────
if (exitCode === 0) {
  console.log("\n══════════════════════════════════════════════════");
  console.log("  ✓ All codegen idempotency checks passed");
  console.log("══════════════════════════════════════════════════\n");
} else {
  console.error("\n══════════════════════════════════════════════════");
  console.error("  ✗ codegen:check FAILED — see errors above");
  console.error("══════════════════════════════════════════════════\n");
}
process.exit(exitCode);
