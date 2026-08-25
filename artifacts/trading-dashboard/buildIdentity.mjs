import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const dashboardDir = path.dirname(fileURLToPath(import.meta.url));
const workspaceRoot = path.resolve(dashboardDir, "../..");

export const RETIRED_BUILD_IDS = new Set([
  "apexquant-v1.0.0",
  "apexquant-phase0c-20260821",
]);

const SOURCE_COMMIT_KEYS = [
  "APEXQUANT_GIT_COMMIT",
  "REPLIT_GIT_COMMIT",
  "GIT_COMMIT",
  "SOURCE_COMMIT",
];

export function isValidSourceCommit(value) {
  return /^[0-9a-f]{40}$/i.test(value?.trim() ?? "");
}

/**
 * Resolve the commit handoff before a production image removes .git.
 * An explicitly supplied value wins and is validated by the caller; the
 * persisted handoff is the no-Git fallback created by deploy-build.sh.
 */
export function sourceGitCommit(env = process.env, root = workspaceRoot) {
  const configured = SOURCE_COMMIT_KEYS
    .map((key) => env[key]?.trim())
    .find(Boolean);
  if (configured) return configured;

  try {
    return execFileSync("git", ["rev-parse", "HEAD"], {
      cwd: root,
      encoding: "utf8",
      stdio: ["ignore", "pipe", "ignore"],
    }).trim();
  } catch {
    try {
      return readFileSync(path.join(root, ".apexquant-source-commit"), "utf8").trim();
    } catch {
      return "";
    }
  }
}

/**
 * Production UI identity is derived from the exact source commit only.
 * A configured build label may confirm that value, but cannot override it.
 */
export function resolveUiBuildIdentity(env = process.env, root = workspaceRoot) {
  const production = env.NODE_ENV === "production";
  const gitCommit = sourceGitCommit(env, root);

  if (production && !isValidSourceCommit(gitCommit)) {
    throw new Error(
      "Unable to resolve an exact source commit for the dashboard build. " +
      "Set APEXQUANT_GIT_COMMIT or preserve .apexquant-source-commit before publishing.",
    );
  }

  const uiGitCommit = isValidSourceCommit(gitCommit) ? gitCommit : "unknown";
  const uiBuildId = isValidSourceCommit(gitCommit)
    ? `apexquant-${gitCommit.slice(0, 12)}`
    : "development";
  const configuredBuildId = env.APEXQUANT_BUILD_ID?.trim();

  if (production && configuredBuildId && configuredBuildId !== uiBuildId) {
    const retired = RETIRED_BUILD_IDS.has(configuredBuildId);
    throw new Error(
      `Invalid dashboard build identity "${configuredBuildId}". ` +
      (retired
        ? "The supplied label is retired; "
        : "Generic or overridden labels are not allowed; ") +
      `the UI build must be derived as "${uiBuildId}" from the source commit.`,
    );
  }

  return {
    ui_git_commit: uiGitCommit,
    ui_build_id: uiBuildId,
  };
}