import { createRequire } from "node:module";
import { execFileSync } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { build as esbuild } from "esbuild";
import esbuildPluginPino from "esbuild-plugin-pino";
import { readFileSync } from "node:fs";
import { rm } from "node:fs/promises";

// Plugins (e.g. 'esbuild-plugin-pino') may use `require` to resolve dependencies
globalThis.require = createRequire(import.meta.url);

const artifactDir = path.dirname(fileURLToPath(import.meta.url));
const projectRoot = path.resolve(artifactDir, "../..");
const GENERIC_BUILD_IDS = new Set(["apexquant-v1.0.0"]);

export function sourceGitCommit(env = process.env, root = projectRoot) {
  const configured = [
    env.APEXQUANT_GIT_COMMIT,
    env.REPLIT_GIT_COMMIT,
    env.GIT_COMMIT,
    env.SOURCE_COMMIT,
  ].map((value) => value?.trim()).find(Boolean);
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

export function resolveBuildIdentity(env = process.env, root = projectRoot) {
  const gitCommit = sourceGitCommit(env, root);
  if (!/^[0-9a-f]{7,64}$/i.test(gitCommit)) {
    throw new Error(
      "Unable to resolve an exact source commit for the API build. " +
      "Set APEXQUANT_GIT_COMMIT (or provide an available Git checkout) before publishing."
    );
  }
  const configuredBuildId = env.APEXQUANT_BUILD_ID?.trim();
  const buildId = configuredBuildId && !GENERIC_BUILD_IDS.has(configuredBuildId)
    ? configuredBuildId
    : `apexquant-${gitCommit.slice(0, 12)}`;
  return { gitCommit, buildId };
}

async function buildAll() {
  const distDir = path.resolve(artifactDir, "dist");
  await rm(distDir, { recursive: true, force: true });
  const { gitCommit, buildId } = resolveBuildIdentity();

  await esbuild({
    entryPoints: [path.resolve(artifactDir, "src/index.ts")],
    platform: "node",
    bundle: true,
    format: "esm",
    outdir: distDir,
    outExtension: { ".js": ".mjs" },
    logLevel: "info",
    // Embed the source identity in the production bundle. The runtime health
    // contract can therefore identify the code even when the deployed image
    // does not contain a .git directory.
    define: {
      "process.env.APEXQUANT_GIT_COMMIT": JSON.stringify(gitCommit),
      "process.env.APEXQUANT_BUILD_ID": JSON.stringify(buildId),
    },
    // Some packages may not be bundleable, so we externalize them, we can add more here as needed.
    // Some of the packages below may not be imported or installed, but we're adding them in case they are in the future.
    // Examples of unbundleable packages:
    // - uses native modules and loads them dynamically (e.g. sharp)
    // - use path traversal to read files (e.g. @google-cloud/secret-manager loads sibling .proto files)
    external: [
      "*.node",
      "sharp",
      "better-sqlite3",
      "sqlite3",
      "canvas",
      "bcrypt",
      "argon2",
      "fsevents",
      "re2",
      "farmhash",
      "xxhash-addon",
      "bufferutil",
      "utf-8-validate",
      "ssh2",
      "cpu-features",
      "dtrace-provider",
      "isolated-vm",
      "lightningcss",
      "pg-native",
      "oracledb",
      "mongodb-client-encryption",
      "nodemailer",
      "handlebars",
      "knex",
      "typeorm",
      "protobufjs",
      "onnxruntime-node",
      "@tensorflow/*",
      "@prisma/client",
      "@mikro-orm/*",
      "@grpc/*",
      "@swc/*",
      "@aws-sdk/*",
      "@azure/*",
      "@opentelemetry/*",
      "@google-cloud/*",
      "@google/*",
      "googleapis",
      "firebase-admin",
      "@parcel/watcher",
      "@sentry/profiling-node",
      "@tree-sitter/*",
      "aws-sdk",
      "classic-level",
      "dd-trace",
      "ffi-napi",
      "grpc",
      "hiredis",
      "kerberos",
      "leveldown",
      "miniflare",
      "mysql2",
      "newrelic",
      "odbc",
      "piscina",
      "realm",
      "ref-napi",
      "rocksdb",
      "sass-embedded",
      "sequelize",
      "serialport",
      "snappy",
      "tinypool",
      "usb",
      "workerd",
      "wrangler",
      "zeromq",
      "zeromq-prebuilt",
      "playwright",
      "puppeteer",
      "puppeteer-core",
      "electron",
    ],
    sourcemap: "linked",
    plugins: [
      // pino relies on workers to handle logging, instead of externalizing it we use a plugin to handle it
      esbuildPluginPino({ transports: ["pino-pretty"] })
    ],
    // Make sure packages that are cjs only (e.g. express) but are bundled continue to work in our esm output file
    banner: {
      js: `import { createRequire as __bannerCrReq } from 'node:module';
import __bannerPath from 'node:path';
import __bannerUrl from 'node:url';

globalThis.require = __bannerCrReq(import.meta.url);
globalThis.__filename = __bannerUrl.fileURLToPath(import.meta.url);
globalThis.__dirname = __bannerPath.dirname(globalThis.__filename);
    `,
    },
  });
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  buildAll().catch((err) => {
    console.error(err);
    process.exit(1);
  });
}
