import { afterAll, beforeAll, describe, expect, it, vi } from "vitest";
import type { Server } from "node:http";
import { EventEmitter } from "node:events";
import { createSession } from "../lib/session";

function processFor(payload: unknown) {
  const proc = Object.assign(new EventEmitter(), {
    stdout: new EventEmitter(),
    stderr: new EventEmitter(),
    kill: vi.fn(),
  });
  setImmediate(() => {
    (proc.stdout as EventEmitter).emit("data", Buffer.from(JSON.stringify(payload)));
    proc.emit("close", 0);
  });
  return proc;
}

const spawnMock = vi.fn(() => processFor({ success: true }));
vi.mock("node:child_process", () => ({ spawn: spawnMock }));

async function request(
  server: Server,
  path: string,
  options: { method?: string; body?: unknown; session?: boolean } = {},
) {
  const address = server.address();
  if (!address || typeof address === "string") throw new Error("server not listening");
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (options.session) headers.Cookie = `__session=${createSession()}`;
  const response = await fetch(`http://127.0.0.1:${address.port}${path}`, {
    method: options.method ?? "GET",
    headers,
    body: options.body === undefined ? undefined : JSON.stringify(options.body),
  });
  return { status: response.status, body: await response.json() as Record<string, unknown> };
}

describe("universe management v1 contract", () => {
  let server: Server;

  beforeAll(async () => {
    const { default: app } = await import("../app.js");
    await new Promise<void>((resolve) => {
      server = app.listen(0, "127.0.0.1", resolve);
    });
  });

  afterAll(() => server?.close());

  it("requires a session for versioned reads before it starts Python", async () => {
    // App startup starts the unrelated pipeline tail. The authorization
    // assertion is about this request, so discard startup side effects first.
    spawnMock.mockClear();
    const response = await request(server, "/api/universe/v1/active");

    expect(response.status).toBe(401);
    expect(spawnMock).not.toHaveBeenCalled();
  });

  it("serves authenticated active-revision reads through the versioned contract", async () => {
    spawnMock.mockClear();
    spawnMock.mockImplementation(() => processFor({
      success: true,
      active_revision: { version: 1, status: "ACTIVE" },
      activation: { locked: true },
    }));

    const response = await request(server, "/api/universe/v1/active", { session: true });

    expect(response.status).toBe(200);
    expect(response.body).toMatchObject({
      api_version: "v1",
      active_revision: { version: 1, status: "ACTIVE" },
      activation: { locked: true },
    });
    expect((spawnMock.mock.calls[0][1] as string[])).toContain("universe_management_active");
  });

  it("keeps activation server-side locked even for an authenticated caller", async () => {
    spawnMock.mockClear();
    spawnMock.mockImplementation(() => processFor({
      success: false,
      error: "activation_locked",
      status: "LOCKED",
      lock_reason: "Certification pending",
    }));

    const response = await request(
      server,
      "/api/universe/v1/revisions/2/activate",
      { method: "POST", session: true, body: { confirmation: "ACTIVATE 2" } },
    );

    expect(response.status).toBe(423);
    expect(response.body).toMatchObject({
      error: "activation_locked",
      status: "LOCKED",
    });
  });

  it("retired direct member mutation cannot dispatch an admin-token bypass", async () => {
    spawnMock.mockClear();
    const response = await request(
      server,
      "/api/universe/custom/upsert",
      { method: "POST", body: { rows: [{ symbol: "WIPRO" }] } },
    );

    expect(response.status).toBe(410);
    expect(response.body).toMatchObject({
      error: "retired_universe_mutation_route",
      replacement: "/api/universe/v1",
    });
    expect(spawnMock).not.toHaveBeenCalled();
  });
});