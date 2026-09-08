import { execFileSync } from "node:child_process";
import {
  existsSync,
  mkdtempSync,
  readdirSync,
  readFileSync,
  rmSync,
} from "node:fs";
import { createRequire } from "node:module";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const dashboardDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
export const RETIRED_BUILD_IDS = new Set([
  "apexquant-v1.0.0",
  "apexquant-phase0c-20260821",
]);
export const UI_BUILD_ID_PATTERN = /^apexquant-([0-9a-f]{12})$/i;
export const FULL_COMMIT_PATTERN = /^[0-9a-f]{40}$/i;

const DEFAULT_DASHBOARD_PATH = "/trading-dashboard/";
const PUBLIC_URL_KEYS = ["APEXQUANT_PUBLIC_URL", "PUBLIC_URL"];
const EVIDENCE_HEADERS = [
  "cache-control",
  "etag",
  "last-modified",
  "age",
  "expires",
  "x-cache",
  "x-cache-status",
  "cf-cache-status",
  "x-served-by",
  "content-type",
];

function responseHeaders(response) {
  return Object.fromEntries(
    EVIDENCE_HEADERS.map((key) => [key, response.headers.get(key)]),
  );
}

export function extractHashedEntryAsset(html, documentUrl) {
  const scripts = [...html.matchAll(
    /<script\b[^>]*\bsrc\s*=\s*["']([^"']+)["'][^>]*>/gi,
  )].map((match) => match[1]);
  const entry = scripts.find((src) => {
    const pathname = new URL(src, documentUrl).pathname;
    return /\/assets\/index-[A-Za-z0-9_-]{6,}\.js$/.test(pathname);
  });
  if (!entry) {
    throw new Error(
      "Dashboard HTML did not reference a hashed /assets/index-*.js entry asset.",
    );
  }
  return new URL(entry, documentUrl).toString();
}

export function inspectUiAsset(bundle) {
  const buildIds = [...new Set(
    [...bundle.matchAll(/apexquant-[0-9a-f]{12}/gi)].map((match) => match[0]),
  )];
  const commits = [...new Set(
    [...bundle.matchAll(/(?<![0-9a-f])([0-9a-f]{40})(?![0-9a-f])/gi)]
      .map((match) => match[1]),
  )];
  const uiBuildId = buildIds.find((value) => !RETIRED_BUILD_IDS.has(value.toLowerCase()));
  const uiGitCommit = commits.find(
    (commit) => uiBuildId?.toLowerCase() === `apexquant-${commit.slice(0, 12).toLowerCase()}`,
  ) ?? null;
  const retiredBuildIds = [...RETIRED_BUILD_IDS].filter((value) =>
    bundle.toLowerCase().includes(value),
  );
  return {
    uiBuildId: uiBuildId ?? null,
    uiGitCommit,
    buildIds,
    retiredBuildIds,
    valid: Boolean(
      uiBuildId &&
      UI_BUILD_ID_PATTERN.test(uiBuildId) &&
      uiGitCommit &&
      FULL_COMMIT_PATTERN.test(uiGitCommit),
    ),
  };
}

export function validateIdentity({
  uiBuildId,
  uiGitCommit,
  apiBuildId,
  apiGitCommit,
  retiredBuildIds = [],
}) {
  const failures = [];
  if (retiredBuildIds.length > 0) {
    failures.push(
      `Public UI asset contains retired build identity "${retiredBuildIds.join(", ")}".`,
    );
  }
  if (!uiGitCommit || !FULL_COMMIT_PATTERN.test(uiGitCommit)) {
    failures.push("Public UI asset does not contain a full 40-character source commit.");
  }
  if (!uiBuildId || !UI_BUILD_ID_PATTERN.test(uiBuildId)) {
    failures.push(
      "Public UI asset does not contain an apexquant-<12-character-commit> build identity.",
    );
  } else if (
    uiGitCommit &&
    uiBuildId.toLowerCase() !== `apexquant-${uiGitCommit.slice(0, 12).toLowerCase()}`
  ) {
    failures.push("Public UI build identity does not match its full embedded source commit.");
  }
  if (!apiBuildId || !UI_BUILD_ID_PATTERN.test(apiBuildId)) {
    failures.push("Production API did not return a commit-derived build identity.");
  }
  if (!apiGitCommit || !FULL_COMMIT_PATTERN.test(apiGitCommit)) {
    failures.push("Production API did not return a full 40-character source commit.");
  } else if (
    apiBuildId &&
    apiBuildId.toLowerCase() !== `apexquant-${apiGitCommit.slice(0, 12).toLowerCase()}`
  ) {
    failures.push("Production API build identity does not match its full source commit.");
  }
  if (
    uiBuildId &&
    apiBuildId &&
    uiBuildId.toLowerCase() !== apiBuildId.toLowerCase()
  ) {
    failures.push(
      `UI/API build mismatch: UI ${uiBuildId}, API ${apiBuildId}.`,
    );
  }
  return {
    failures,
    expectedRenderedState: uiBuildId && apiBuildId && uiBuildId === apiBuildId
      ? "MATCH"
      : "MISMATCH",
  };
}

async function fetchResponse(url, init = {}) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 20_000);
  const { signal: callerSignal, ...requestInit } = init;
  try {
    const response = await fetch(url, {
      redirect: "follow",
      ...requestInit,
      signal: callerSignal
        ? AbortSignal.any([callerSignal, controller.signal])
        : controller.signal,
      headers: {
        "cache-control": "no-cache",
        pragma: "no-cache",
        ...(init.headers ?? {}),
        "user-agent": "ApexQuant-build-identity-smoke/1.0",
      },
    });
    return {
      url: response.url || url,
      status: response.status,
      ok: response.ok,
      headers: responseHeaders(response),
      body: await response.text(),
    };
  } finally {
    clearTimeout(timeout);
  }
}

async function fetchServiceWorkerEvidence(dashboardUrl, html, assetBody) {
  const dashboardRoot = new URL(".", dashboardUrl).toString();
  const candidates = [
    new URL("sw.js", dashboardRoot).toString(),
    new URL("service-worker.js", dashboardRoot).toString(),
    new URL("workbox-sw.js", dashboardRoot).toString(),
  ];
  const probes = await Promise.all(candidates.map(async (url) => {
    try {
      const response = await fetchResponse(url);
      return {
        url,
        status: response.status,
        ok: response.ok,
        headers: response.headers,
        bodyMarkers: {
          serviceWorker: /serviceworker|workbox/i.test(response.body),
          htmlFallback: /<html[\s>]/i.test(response.body),
        },
      };
    } catch (error) {
      return { url, error: error instanceof Error ? error.message : String(error) };
    }
  }));
  return {
    sourceMarkers: {
      html: /serviceworker|workbox|navigator\.serviceWorker/i.test(html),
      asset: /serviceworker|workbox|navigator\.serviceWorker/i.test(assetBody),
    },
    probes,
  };
}

async function resolveChromiumExecutable(chromium) {
  const candidates = [
    process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH,
    process.env.CHROMIUM_PATH,
    chromium.executablePath?.(),
  ];
  try {
    candidates.push(execFileSync("which", ["chromium"], { encoding: "utf8" }).trim());
  } catch {
    // The explicit Nix path below is used in this workspace when `which` is absent.
  }
  candidates.push(
    "/nix/store/qa9cnw4v5xkxyip6mb9kxqfq1z4x2dx1-chromium-138.0.7204.100/bin/chromium",
  );
  return candidates.find((candidate) => candidate && existsSync(candidate));
}

async function checkRenderedMissionControl(
  dashboardUrl,
  { expectedState, uiBuildId, apiBuildId },
) {
  const require = createRequire(import.meta.url);
  const { chromium } = require("@playwright/test");
  const executablePath = await resolveChromiumExecutable(chromium);
  if (!executablePath) {
    throw new Error(
      "Chromium executable not found. Set PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH to run the rendered check.",
    );
  }
  const browser = await chromium.launch({
    executablePath,
    headless: true,
    args: ["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"],
  });
  try {
    const page = await browser.newPage();
    const missionControlUrl = new URL("mission-control", dashboardUrl).toString();
    await page.goto(missionControlUrl, {
      waitUntil: "domcontentloaded",
      timeout: 30_000,
    });
    const identity = page.locator('[data-testid="mc-build-ids"]');
    await identity.waitFor({ state: "visible", timeout: 30_000 });
    // A stale bundle can keep its API field at "loading" forever because it
    // predates the current scan-status contract. Capture that visible failure
    // promptly instead of hiding it behind a long browser timeout.
    await page.waitForTimeout(2_000);
    const text = (await identity.textContent()) ?? "";
    const statusNode = page.locator('[data-testid="mc-build-match"]');
    const status = await statusNode.count() > 0
      ? (await statusNode.textContent()) ?? ""
      : "";
    const requiredLabels = ["Product Version", "UI Build", "API Build"];
    const failures = requiredLabels
      .filter((label) => !text.includes(label))
      .map((label) => `Rendered Mission Control identity is missing "${label}".`);
    if (uiBuildId && !text.includes(`UI Build ${uiBuildId}`)) {
      failures.push(
        `Rendered Mission Control UI Build does not show public asset identity "${uiBuildId}".`,
      );
    }
    if (apiBuildId && !text.includes(`API Build ${apiBuildId}`)) {
      failures.push(
        `Rendered Mission Control API Build does not show production API identity "${apiBuildId}".`,
      );
    }
    if (!status.trim()) {
      failures.push("Rendered Mission Control identity is missing a MATCH or MISMATCH state.");
    }
    if (status.trim() !== expectedState) {
      failures.push(
        `Rendered Mission Control state was "${status.trim()}", expected "${expectedState}".`,
      );
    }
    const serviceWorkerRegistrations = await page.evaluate(async () => {
      if (!("serviceWorker" in navigator)) return { supported: false, registrations: [] };
      const registrations = await navigator.serviceWorker.getRegistrations();
      return {
        supported: true,
        registrations: registrations.map((registration) => ({
          active: registration.active?.scriptURL ?? null,
          waiting: registration.waiting?.scriptURL ?? null,
          installing: registration.installing?.scriptURL ?? null,
        })),
      };
    });
    return {
      url: missionControlUrl,
      text,
      status: status.trim(),
      failures,
      serviceWorkerRegistrations,
    };
  } finally {
    await browser.close();
  }
}

export async function checkPublicDashboard({
  publicUrl,
  dashboardPath = DEFAULT_DASHBOARD_PATH,
  render = true,
} = {}) {
  if (!publicUrl) {
    throw new Error(
      "A production URL is required. Set APEXQUANT_PUBLIC_URL or pass --url https://your-app.replit.app.",
    );
  }
  const dashboardUrl = new URL(dashboardPath, publicUrl).toString();
  const report = {
    mode: "public",
    dashboardUrl,
    checkedAt: new Date().toISOString(),
    failures: [],
  };
  let htmlResponse;
  let assetResponse;
  try {
    htmlResponse = await fetchResponse(dashboardUrl);
    report.html = {
      url: htmlResponse.url,
      status: htmlResponse.status,
      headers: htmlResponse.headers,
    };
    if (!htmlResponse.ok) {
      report.failures.push(`Dashboard HTML returned HTTP ${htmlResponse.status}.`);
      return report;
    }
    const assetUrl = extractHashedEntryAsset(htmlResponse.body, dashboardUrl);
    assetResponse = await fetchResponse(assetUrl);
    report.asset = {
      url: assetResponse.url,
      status: assetResponse.status,
      headers: assetResponse.headers,
    };
    if (!assetResponse.ok) {
      report.failures.push(`Dashboard entry asset returned HTTP ${assetResponse.status}.`);
      return report;
    }
    const ui = inspectUiAsset(assetResponse.body);
    report.ui = {
      buildId: ui.uiBuildId,
      gitCommit: ui.uiGitCommit,
      retiredBuildIds: ui.retiredBuildIds,
    };

    const apiUrl = new URL("/api/health/details", publicUrl).toString();
    const apiResponse = await fetchResponse(apiUrl);
    report.api = { url: apiResponse.url, status: apiResponse.status };
    if (!apiResponse.ok) {
      report.failures.push(`Production API health/details returned HTTP ${apiResponse.status}.`);
    } else {
      let apiBody;
      try {
        apiBody = JSON.parse(apiResponse.body);
      } catch {
        report.failures.push("Production API health/details returned invalid JSON.");
      }
      const runtime = apiBody?.runtime_identity ?? {};
      report.api.buildId = runtime.build_id ?? null;
      report.api.gitCommit = runtime.git_commit ?? null;
      if (apiBody) {
        report.failures.push(
          ...validateIdentity({
            uiBuildId: ui.uiBuildId,
            uiGitCommit: ui.uiGitCommit,
            apiBuildId: runtime.build_id,
            apiGitCommit: runtime.git_commit,
            retiredBuildIds: ui.retiredBuildIds,
          }).failures,
        );
      }
    }
    if (render) {
      try {
        report.rendered = await checkRenderedMissionControl(
          dashboardUrl,
          {
            expectedState: report.ui?.buildId &&
              report.api?.buildId &&
              report.ui.buildId.toLowerCase() === report.api.buildId.toLowerCase()
              ? "MATCH"
              : "MISMATCH",
            uiBuildId: report.ui?.buildId,
            apiBuildId: report.api?.buildId,
          },
        );
        report.failures.push(...report.rendered.failures);
      } catch (error) {
        report.failures.push(
          `Rendered Mission Control check failed: ${error instanceof Error ? error.message : String(error)}`,
        );
      }
    }
    if (report.failures.length > 0) {
      report.cacheEvidence = {
        html: report.html?.headers,
        asset: report.asset?.headers,
      };
      report.serviceWorkerEvidence = await fetchServiceWorkerEvidence(
        dashboardUrl,
        htmlResponse.body,
        assetResponse.body,
      );
      if (report.rendered?.serviceWorkerRegistrations) {
        report.serviceWorkerEvidence.browser = report.rendered.serviceWorkerRegistrations;
      }
    }
    return report;
  } catch (error) {
    report.failures.push(error instanceof Error ? error.message : String(error));
    if (htmlResponse || assetResponse) {
      report.cacheEvidence = {
        html: htmlResponse?.headers,
        asset: assetResponse?.headers,
      };
    }
    if (htmlResponse && assetResponse) {
      report.serviceWorkerEvidence = await fetchServiceWorkerEvidence(
        dashboardUrl,
        htmlResponse.body,
        assetResponse.body,
      );
    }
    return report;
  }
}

function runLocalAssetCheck() {
  const commit = "a".repeat(40);
  const expectedBuildId = "apexquant-aaaaaaaaaaaa";
  const require = createRequire(import.meta.url);
  const viteBin = path.resolve(
    path.dirname(require.resolve("vite")),
    "../..",
    "bin/vite.js",
  );
  const outDir = mkdtempSync(path.join(tmpdir(), "apexquant-dashboard-identity-"));
  const { APEXQUANT_BUILD_ID: _retiredOrGenericBuildId, ...baseEnv } = process.env;
  try {
    execFileSync(process.execPath, [
      viteBin, "build", "--config", "vite.config.ts", "--outDir", outDir,
    ], {
      cwd: dashboardDir,
      env: {
        ...baseEnv,
        NODE_ENV: "production",
        PORT: "24210",
        BASE_PATH: DEFAULT_DASHBOARD_PATH,
        APEXQUANT_GIT_COMMIT: commit,
      },
      stdio: "inherit",
    });
    const assetsDir = path.join(outDir, "assets");
    const entryAsset = readdirSync(assetsDir).find((file) => /^index-.*\.js$/.test(file));
    if (!entryAsset) throw new Error("Production build must emit a hashed JavaScript entry asset");
    const bundle = readFileSync(path.join(assetsDir, entryAsset), "utf8");
    const result = inspectUiAsset(bundle);
    if (result.uiBuildId !== expectedBuildId || result.uiGitCommit !== commit) {
      throw new Error("UI build asset did not contain the expected commit-derived identity.");
    }
    if (result.retiredBuildIds.length > 0) {
      throw new Error(`Retired deployment label was injected: ${result.retiredBuildIds.join(", ")}`);
    }
    console.log(`Verified asset identity: ${expectedBuildId} from ${commit}`);
  } finally {
    rmSync(outDir, { recursive: true, force: true });
  }
}

function parseArgs(argv) {
  const args = [...argv];
  const urlIndex = args.indexOf("--url");
  return {
    public: args.includes("--public") || urlIndex >= 0,
    publicUrl: urlIndex >= 0 ? args[urlIndex + 1] : PUBLIC_URL_KEYS
      .map((key) => process.env[key]?.trim())
      .find(Boolean),
    render: !args.includes("--no-render"),
    dashboardPath: process.env.APEXQUANT_DASHBOARD_PATH || DEFAULT_DASHBOARD_PATH,
  };
}

async function main() {
  const options = parseArgs(process.argv.slice(2));
  if (!options.public) {
    runLocalAssetCheck();
    return;
  }
  const report = await checkPublicDashboard(options);
  console.log(JSON.stringify(report, null, 2));
  if (report.failures.length > 0) {
    console.error(`Build identity smoke check FAILED (${report.failures.length} issue(s)).`);
    process.exitCode = 1;
  } else {
    console.log("Build identity smoke check PASSED.");
  }
}

const invokedDirectly = process.argv[1] &&
  import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href;
if (invokedDirectly) {
  await main();
}