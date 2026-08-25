import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { mkdtempSync, readdirSync, readFileSync, rmSync } from "node:fs";
import { createRequire } from "node:module";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const dashboardDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const commit = "a".repeat(40);
const expectedBuildId = "apexquant-aaaaaaaaaaaa";
const require = createRequire(import.meta.url);
const viteBin = path.resolve(
  path.dirname(require.resolve("vite")),
  "../..",
  "bin/vite.js",
);
const outDir = mkdtempSync(path.join(tmpdir(), "apexquant-dashboard-identity-"));

const {
  APEXQUANT_BUILD_ID: _retiredOrGenericBuildId,
  ...baseEnv
} = process.env;

try {
  execFileSync(process.execPath, [
    viteBin,
    "build",
    "--config",
    "vite.config.ts",
    "--outDir",
    outDir,
  ], {
    cwd: dashboardDir,
    env: {
      ...baseEnv,
      NODE_ENV: "production",
      PORT: "24210",
      BASE_PATH: "/trading-dashboard/",
      APEXQUANT_GIT_COMMIT: commit,
    },
    stdio: "inherit",
  });

  const assetsDir = path.join(outDir, "assets");
  const entryAsset = readdirSync(assetsDir)
    .find((file) => /^index-.*\.js$/.test(file));
  assert.ok(entryAsset, "Production build must emit a hashed JavaScript entry asset");

  const bundle = readFileSync(path.join(assetsDir, entryAsset), "utf8");
  assert.match(bundle, new RegExp(expectedBuildId), "UI build ID must be injected into the served asset");
  assert.match(bundle, new RegExp(commit), "UI source commit must be injected into the served asset");
  assert.doesNotMatch(bundle, /apexquant-v1\.0\.0/, "Retired semantic deployment label must not be injected");

  console.log(`Verified asset identity: ${expectedBuildId} from ${commit}`);
} finally {
  rmSync(outDir, { recursive: true, force: true });
}