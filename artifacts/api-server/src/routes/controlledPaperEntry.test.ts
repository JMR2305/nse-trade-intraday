import express from "express";
import type { Server } from "node:http";
import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";

import { createSession } from "../lib/session";
import controlledPaperEntryRouter from "./controlledPaperEntry";
import { readControlledPaperEntryFlags } from "../lib/controlledPaperEntryFlags";

const FLAG_NAMES = [
  "CONTROLLED_PAPER_ENTRY_FRAMEWORK_ENABLED",
  "CONTROLLED_PAPER_ENTRY_DRY_RUN_ONLY",
  "CONTROLLED_PAPER_ENTRY_REQUIRE_PHASE1H_PASS",
  "CONTROLLED_PAPER_ENTRY_REQUIRE_OPERATOR_APPROVAL",
  "CONTROLLED_PAPER_ENTRY_ALLOW_AUTO_ENABLE",
  "CONTROLLED_PAPER_ENTRY_ALLOW_BOOTSTRAP",
] as const;

const originalValues = Object.fromEntries(
  FLAG_NAMES.map((name) => [name, process.env[name]]),
);

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

describe("controlled paper-entry status API", () => {
  const app = express();
  let server: Server;

  app.use(controlledPaperEntryRouter);

  beforeAll(async () => {
    server = await new Promise<Server>((resolve) => {
      const instance = app.listen(0, () => resolve(instance));
    });
  });

  afterAll(async () => {
    await new Promise<void>((resolve, reject) => server.close((error) => error ? reject(error) : resolve()));
  });

  afterEach(() => {
    for (const name of FLAG_NAMES) {
      if (originalValues[name] === undefined) delete process.env[name];
      else process.env[name] = originalValues[name];
    }
  });

  it("uses the safe flag defaults", () => {
    const flags = readControlledPaperEntryFlags({});
    expect(flags).toMatchObject({
      frameworkEnabled: false,
      dryRunOnly: true,
      requirePhase1hPass: true,
      requireOperatorApproval: true,
      allowAutoEnable: false,
      allowBootstrap: false,
      reviewGateSafe: false,
      executionAllowed: false,
    });
  });

  it("returns 404 by default without parsing or exposing a status surface", async () => {
    const result = await request(server, "/controlled-paper-entry/status");
    expect(result.status).toBe(404);
    expect(result.body.status).toBe("DISABLED");
    expect(result.body.execution_allowed).toBe(false);
  });

  it("requires an operator session when explicitly enabled", async () => {
    process.env.CONTROLLED_PAPER_ENTRY_FRAMEWORK_ENABLED = "true";
    const missing = await request(server, "/controlled-paper-entry/status");
    expect(missing.status).toBe(401);
  });

  it("returns blocked readiness only, even with safe controls enabled", async () => {
    process.env.CONTROLLED_PAPER_ENTRY_FRAMEWORK_ENABLED = "true";
    const result = await request(server, "/controlled-paper-entry/status", {
      headers: { cookie: `__session=${createSession()}` },
    });
    expect(result.status).toBe(200);
    expect(result.body.status).toBe("BLOCKED");
    expect(result.body.readiness_status).toBe("BLOCKED");
    expect(result.body.dry_run_only).toBe(true);
    expect(result.body.execution_allowed).toBe(false);
    expect(result.body.auto_enable_allowed).toBe(false);
    expect(result.body.bootstrap_allowed).toBe(false);
  });

  it("does not expose mutation or execution route names", async () => {
    for (const suffix of ["/execute", "/place-order", "/enable-auto-entry", "/create-trade"]) {
      const result = await request(server, `/controlled-paper-entry${suffix}`);
      expect(result.status).toBe(404);
    }
  });
});