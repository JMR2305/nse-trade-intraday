import express from "express";
import type { Server } from "node:http";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { afterAll, afterEach, beforeAll, describe, expect, it, vi } from "vitest";

const { spawnMock } = vi.hoisted(() => ({ spawnMock: vi.fn() }));
vi.mock("node:child_process", () => ({ spawn: spawnMock }));

import advisoryRouter from "./advisory";
import { AdvisoryPreviewGate } from "./advisory";
import { readAdvisoryFlags } from "../lib/advisoryFlags";
import { createSession } from "../lib/session";

const FLAG_NAMES = [
  "ADVISORY_BOTS_ENABLED",
  "ADVISORY_BOTS_API_ENABLED",
  "ADVISORY_BOTS_UI_ENABLED",
  "ADVISORY_BOTS_PERSIST_ENABLED",
  "ADVISORY_BOTS_SCHEDULER_ENABLED",
] as const;
const ORIGINAL_NODE_ENV = process.env.NODE_ENV;
const ORIGINAL_DECLARED_ENVIRONMENT = process.env.ENVIRONMENT;

interface FetchResult {
  status: number;
  body: Record<string, unknown>;
}

async function request(server: Server, path: string, init?: RequestInit): Promise<FetchResult> {
  const address = server.address();
  if (!address || typeof address === "string") throw new Error("Server not bound");
  const response = await fetch(`http://127.0.0.1:${address.port}${path}`, init);
  return { status: response.status, body: (await response.json()) as Record<string, unknown> };
}

describe("disabled advisory API integration", () => {
  const app = express();
  let server: Server;

  app.use(express.json());
  app.use(advisoryRouter);

  beforeAll(async () => {
    server = await new Promise<Server>((resolve) => {
      const instance = app.listen(0, () => resolve(instance));
    });
  });

  afterAll(async () => {
    await new Promise<void>((resolve, reject) => server.close((error) => error ? reject(error) : resolve()));
  });

  afterEach(() => {
    for (const name of FLAG_NAMES) delete process.env[name];
    delete process.env.NODE_ENV;
    delete process.env.ENVIRONMENT;
    if (ORIGINAL_NODE_ENV !== undefined) process.env.NODE_ENV = ORIGINAL_NODE_ENV;
    if (ORIGINAL_DECLARED_ENVIRONMENT !== undefined) {
      process.env.ENVIRONMENT = ORIGINAL_DECLARED_ENVIRONMENT;
    }
    spawnMock.mockReset();
  });

  it("treats every missing feature flag as false", () => {
    expect(readAdvisoryFlags({})).toEqual({
      advisoryBotsEnabled: false,
      advisoryApiEnabled: false,
      advisoryUiEnabled: false,
      advisoryPersistEnabled: false,
      advisorySchedulerEnabled: false,
      isProduction: false,
      persistenceEnvironmentAllowed: false,
    });
  });

  it("allows persistence only for an explicit, non-conflicting development or test environment", () => {
    expect(readAdvisoryFlags({ NODE_ENV: "development" }).persistenceEnvironmentAllowed).toBe(true);
    expect(readAdvisoryFlags({ NODE_ENV: "test", ENVIRONMENT: "TEST" }).persistenceEnvironmentAllowed).toBe(true);
    expect(readAdvisoryFlags({}).persistenceEnvironmentAllowed).toBe(false);
    expect(readAdvisoryFlags({ NODE_ENV: "staging" }).persistenceEnvironmentAllowed).toBe(false);
    expect(readAdvisoryFlags({
      NODE_ENV: "development",
      ENVIRONMENT: "production",
    }).persistenceEnvironmentAllowed).toBe(false);
  });

  it("returns 404 for status while the API flag is disabled", async () => {
    const result = await request(server, "/advisory/status");
    expect(result.status).toBe(404);
    expect(result.body.status).toBe("DISABLED");
    expect(spawnMock).not.toHaveBeenCalled();
  });

  it("returns 404 for preview before validating or spawning when disabled", async () => {
    const result = await request(server, "/advisory/run-preview", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ unexpected: "input" }),
    });
    expect(result.status).toBe(404);
    expect(spawnMock).not.toHaveBeenCalled();
  });

  it("exposes only read-only flags when the optional API is explicitly enabled", async () => {
    process.env.ADVISORY_BOTS_API_ENABLED = "true";
    process.env.ADVISORY_BOTS_ENABLED = "false";
    const result = await request(server, "/advisory/status", {
      headers: { cookie: `__session=${createSession()}` },
    });
    expect(result.status).toBe(200);
    expect(result.body.status).toBe("DISABLED");
    expect(result.body.manual_only).toBe(true);
    expect(result.body.scheduler_hook).toBe(false);
    expect(result.body.last_run_at).toBeNull();
  });

  it("requires a valid operator session whenever the optional API is enabled", async () => {
    process.env.ADVISORY_BOTS_API_ENABLED = "true";

    const missing = await request(server, "/advisory/status");
    expect(missing.status).toBe(401);

    const invalid = await request(server, "/advisory/status", {
      headers: { cookie: "__session=not-a-valid-session" },
    });
    expect(invalid.status).toBe(401);
    expect(spawnMock).not.toHaveBeenCalled();
  });

  it("rejects unauthenticated preview requests before spawning Python", async () => {
    process.env.ADVISORY_BOTS_API_ENABLED = "true";
    process.env.ADVISORY_BOTS_ENABLED = "true";
    const result = await request(server, "/advisory/run-preview", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        scan_id: "test",
        universe_rows: [],
        scan_items: [],
        settings: {},
      }),
    });
    expect(result.status).toBe(401);
    expect(spawnMock).not.toHaveBeenCalled();
  });

  it("allows only one preview at a time and applies a cooldown after release", () => {
    const gate = new AdvisoryPreviewGate();
    expect(gate.tryEnter(1_000)).toEqual({ allowed: true });
    expect(gate.tryEnter(1_001).allowed).toBe(false);
    gate.release();
    expect(gate.tryEnter(2_000)).toEqual({ allowed: false, retryAfterMs: 14_000 });
    expect(gate.tryEnter(16_000)).toEqual({ allowed: true });
  });

  it("rejects persistence for missing, unknown, and conflicting environment attestations", async () => {
    const session = `__session=${createSession()}`;
    const environments = [
      {},
      { NODE_ENV: "staging" },
      { NODE_ENV: "development", ENVIRONMENT: "production" },
    ];

    for (const environment of environments) {
      process.env.ADVISORY_BOTS_API_ENABLED = "true";
      process.env.ADVISORY_BOTS_ENABLED = "true";
      process.env.ADVISORY_BOTS_PERSIST_ENABLED = "true";
      delete process.env.NODE_ENV;
      delete process.env.ENVIRONMENT;
      Object.assign(process.env, environment);

      const result = await request(server, "/advisory/run-preview", {
        method: "POST",
        headers: { "content-type": "application/json", cookie: session },
        body: JSON.stringify({
          scan_id: "persistence-safety-test",
          universe_rows: [],
          scan_items: [],
          settings: {},
          persist: true,
        }),
      });
      expect(result.status).toBe(403);
    }
    expect(spawnMock).not.toHaveBeenCalled();
  });

  it("imports no Phase 20, broker, scheduler, or settings-write module", () => {
    const source = readFileSync(resolve(import.meta.dirname, "advisory.ts"), "utf8");
    expect(source).not.toMatch(/from\s+["'][^"']*(phase20|broker|kite|paper_trader|settings)/i);
    expect(source).not.toMatch(/startScanScheduler|startBacktestScheduler|run_auto_entries|manage_open_positions/);
  });
});