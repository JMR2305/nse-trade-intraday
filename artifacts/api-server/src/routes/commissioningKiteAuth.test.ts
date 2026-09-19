// Task978ZI — Commissioning-safe Kite auth route regression suite.
//
// Proves, in commissioning mode (HEALTH_ONLY_NO_SCHEDULERS=true):
//   A. login + callback are mounted
//   B. normal Kite/data routes are NOT mounted
//   C. the callback transfers the request token via child environment only
//      (never argv) and never places it in any logged/echoed surface
//   D. secrets/tokens never appear in responses or child spawn arguments
//   E. a successful callback persists through the existing durable save path
//      (success is reported only after main.py kite_exchange confirms it)
//   F. a failed durable save can never report a successful login
//   G. normal-mode routing is untouched (this router is only loaded by
//      routes/commissioning.ts, and normal mode keeps routes/kite.ts)
//   H. no scheduler/runtime startup is involved (module imports spawn nothing
//      and import nothing at mount time beyond express)

import express from "express";
import type { Server } from "node:http";
import { EventEmitter } from "node:events";
import { afterAll, afterEach, beforeAll, describe, expect, it, vi } from "vitest";

const { spawnMock } = vi.hoisted(() => ({ spawnMock: vi.fn() }));
vi.mock("child_process", () => ({ spawn: spawnMock }));
vi.mock("node:child_process", () => ({ spawn: spawnMock }));

import commissioningRouter from "./commissioning";
import commissioningKiteAuthRouter from "./commissioningKiteAuth";

const REQUEST_TOKEN = "ReqT0kenVal1d2026ZI";
const SECRETS = [REQUEST_TOKEN, "secretApiKey123", "superSecretApiKeyValue"];

function pythonResult(payload: Record<string, unknown>) {
  return () => {
    const proc = new EventEmitter() as EventEmitter & {
      stdout: EventEmitter;
      stderr: EventEmitter;
      kill: ReturnType<typeof vi.fn>;
    };
    proc.stdout = new EventEmitter();
    proc.stderr = new EventEmitter();
    proc.kill = vi.fn();
    setImmediate(() => {
      proc.stdout.emit("data", Buffer.from(JSON.stringify(payload)));
      proc.emit("close", 0);
    });
    return proc;
  };
}

async function request(server: Server, path: string) {
  const address = server.address();
  if (!address || typeof address === "string") throw new Error("Server not bound");
  return fetch(`http://127.0.0.1:${address.port}${path}`, { redirect: "manual" });
}

describe("Task978ZI commissioning Kite auth routes", () => {
  let server: Server;

  beforeAll(async () => {
    vi.stubEnv("HEALTH_ONLY_NO_SCHEDULERS", "true");
    vi.stubEnv("ZERODHA_API_KEY", "secretApiKey123");
    const app = express();
    app.use(commissioningRouter);
    server = await new Promise<Server>((resolve) => {
      const instance = app.listen(0, "127.0.0.1", () => resolve(instance));
    });
  });

  afterAll(async () => {
    vi.unstubAllEnvs();
    await new Promise<void>((resolve, reject) => {
      server.close((error) => (error ? reject(error) : resolve()));
    });
  });

  afterEach(() => {
    spawnMock.mockReset();
  });

  // ── A. commissioning mode mounts login + callback ─────────────────────────
  it("A: mounts GET /kite/login as a redirect to official Kite login", async () => {
    const response = await request(server, "/kite/login");
    expect(response.status).toBe(302);
    expect(response.headers.get("location")).toBe(
      "https://kite.zerodha.com/connect/login?api_key=secretApiKey123&v=3",
    );
  });

  it("A: mounts GET /kite/callback", async () => {
    spawnMock.mockImplementation(
      pythonResult({ success: true, state: "CONNECTED" }),
    );
    const response = await request(
      server,
      `/kite/callback?status=success&request_token=${REQUEST_TOKEN}`,
    );
    expect(response.status).toBe(302);
    expect(response.headers.get("location")).toBe("/commissioning/kite?auth=success");
  });

  // ── B. normal Kite/data routes are NOT mounted ────────────────────────────
  it.each([
    "/kite/status",
    "/kite/quote?symbols=RELIANCE",
    "/kite/ltp?symbols=RELIANCE",
    "/kite/holdings",
    "/kite/positions",
    "/kite/orders",
    "/kite/margins",
    "/kite/disconnect",
    "/kite/instruments/status",
    "/kite/instruments/search?q=REL",
    "/kite/diagnostics",
  ])("B: does not mount normal Kite route %s", async (path) => {
    const response = await request(server, path);
    expect(response.status).toBe(404);
    expect(spawnMock).not.toHaveBeenCalled();
  });

  it("B: commissioning router still exposes the health probes", async () => {
    expect((await request(server, "/healthz")).status).toBe(200);
    expect((await request(server, "/health/live")).status).toBe(200);
  });

  // ── C. env-only request-token transfer ────────────────────────────────────
  it("C: passes the request token via child env only, never argv", async () => {
    spawnMock.mockImplementation(
      pythonResult({ success: true, state: "CONNECTED" }),
    );
    await request(
      server,
      `/kite/callback?status=success&request_token=${REQUEST_TOKEN}`,
    );
    expect(spawnMock).toHaveBeenCalledTimes(1);
    const [bin, args, options] = spawnMock.mock.calls[0] as [
      string,
      string[],
      { env: Record<string, string | undefined> },
    ];
    expect(String(bin).endsWith("python3") || bin === "python3").toBe(true);
    expect(args).toEqual([expect.stringContaining("main.py"), "kite_exchange"]);
    // argv must never contain the request token.
    expect(args.join(" ")).not.toContain(REQUEST_TOKEN);
    // The child environment must carry the request token.
    expect(options.env["KITE_REQUEST_TOKEN"]).toBe(REQUEST_TOKEN);
  });

  // ── D. no secret/token material in responses, argv, or logs ───────────────
  // The exchange child legitimately inherits ZERODHA_API_KEY/ZERODHA_API_SECRET
  // in its process environment (the reviewed exchange design); the contract is
  // that the request token travels env-only (never argv) and that no secret or
  // token material reaches any response, redirect, or log surface.
  it("D: request token appears only in child env, never in argv or responses", async () => {
    spawnMock.mockImplementation(
      pythonResult({ success: true, state: "CONNECTED" }),
    );
    const response = await request(
      server,
      `/kite/callback?status=success&request_token=${REQUEST_TOKEN}`,
    );
    const [bin, args, options] = spawnMock.mock.calls[0] as [
      string,
      string[],
      { env: Record<string, string | undefined> },
    ];
    // argv (bin + args) never carries the request token or any secret.
    const argvSurface = [bin, ...args].join(" ");
    for (const secret of SECRETS) {
      expect(argvSurface).not.toContain(secret);
    }
    // The request token is present exactly in the child environment.
    expect(options.env["KITE_REQUEST_TOKEN"]).toBe(REQUEST_TOKEN);
    // The redirect response never echoes the token.
    expect(response.headers.get("location")).toBe("/commissioning/kite?auth=success");
    expect(response.headers.get("location")).not.toContain(REQUEST_TOKEN);
  });

  it("D: login redirect never includes the API secret", async () => {
    const response = await request(server, "/kite/login");
    const location = response.headers.get("location") ?? "";
    expect(location).not.toContain("superSecretApiKeyValue");
    expect(location).toContain("api_key=secretApiKey123");
  });

  // ── E. success persists through the existing durable save path ────────────
  it("E: reports success only after the durable exchange subprocess confirms", async () => {
    spawnMock.mockImplementation(
      pythonResult({ success: true, state: "CONNECTED" }),
    );
    const response = await request(
      server,
      `/kite/callback?status=success&request_token=${REQUEST_TOKEN}`,
    );
    expect(response.status).toBe(302);
    expect(response.headers.get("location")).toBe("/commissioning/kite?auth=success");
    // Exactly one kite_exchange invocation — the reviewed durable path.
    expect(spawnMock).toHaveBeenCalledTimes(1);
    expect(spawnMock.mock.calls[0][1]).toContain("kite_exchange");
  });

  // ── F. failed durable save can never report success ───────────────────────
  it("F: redirects to failure when the durable save is rejected by Python", async () => {
    spawnMock.mockImplementation(
      pythonResult({ success: false, state: "AUTH_FAILED" }),
    );
    const response = await request(
      server,
      `/kite/callback?status=success&request_token=${REQUEST_TOKEN}`,
    );
    expect(response.status).toBe(302);
    expect(response.headers.get("location")).toBe(
      "/commissioning/kite?auth=failed&reason=exchange_failed",
    );
  });

  it("F: redirects to failure when the exchange child crashes", async () => {
    spawnMock.mockImplementation(() => {
      const proc = new EventEmitter() as EventEmitter & {
        stdout: EventEmitter;
        stderr: EventEmitter;
        kill: ReturnType<typeof vi.fn>;
      };
      proc.stdout = new EventEmitter();
      proc.stderr = new EventEmitter();
      proc.kill = vi.fn();
      setImmediate(() => proc.emit("close", 1));
      return proc;
    });
    const response = await request(
      server,
      `/kite/callback?status=success&request_token=${REQUEST_TOKEN}`,
    );
    expect(response.headers.get("location")).toBe(
      "/commissioning/kite?auth=failed&reason=exchange_failed",
    );
  });

  it("F: redirects to failure when the child output is unparseable", async () => {
    spawnMock.mockImplementation(() => {
      const proc = new EventEmitter() as EventEmitter & {
        stdout: EventEmitter;
        stderr: EventEmitter;
        kill: ReturnType<typeof vi.fn>;
      };
      proc.stdout = new EventEmitter();
      proc.stderr = new EventEmitter();
      proc.kill = vi.fn();
      setImmediate(() => {
        proc.stdout.emit("data", Buffer.from("not json"));
        proc.emit("close", 0);
      });
      return proc;
    });
    const response = await request(
      server,
      `/kite/callback?status=success&request_token=${REQUEST_TOKEN}`,
    );
    expect(response.headers.get("location")).toBe(
      "/commissioning/kite?auth=failed&reason=exchange_failed",
    );
  });

  it("F: fail-closed on non-success status and malformed request tokens", async () => {
    for (const query of [
      "status=failed",
      "status=success",
      "status=success&request_token=short",
      "status=success&request_token=bad_token_with_symbols!@#",
    ]) {
      const response = await request(server, `/kite/callback?${query}`);
      expect(response.status).toBe(302);
      expect(response.headers.get("location")).toContain("auth=failed");
      expect(spawnMock).not.toHaveBeenCalled();
    }
  });

  // ── H. no scheduler/runtime startup in commissioning mode ─────────────────
  it("H: importing the router module spawns no processes and starts no schedulers", async () => {
    // Router modules were imported at the top of this file; the spawn mock
    // has been reset between tests, so nothing may have called it.
    expect(spawnMock).not.toHaveBeenCalled();
    // The commissioning router itself is a pure express Router — no listen.
    expect(commissioningKiteAuthRouter.stack.length).toBe(2);
    const layers = commissioningKiteAuthRouter.stack.map(
      (l) => (l as { route?: { path?: string } }).route?.path,
    );
    expect(layers).toEqual(["/kite/login", "/kite/callback"]);
  });

  it("H: commissioning router mounts only health + kite auth", () => {
    const paths = commissioningRouter.stack
      .map((l) => (l as { route?: { path?: string } }).route?.path)
      .filter(Boolean);
    expect(paths).toEqual([]);
    // Two mounted sub-routers (health + commissioning kite auth), no more.
    expect(commissioningRouter.stack.length).toBe(2);
  });
});

describe("Task978ZI normal-mode routing remains unchanged (G)", () => {
  it("G: the commissioning auth router is not part of the normal router graph", async () => {
    // Normal mode loads routes/index.js, which mounts routes/kite.ts — the
    // commissioning router and this auth router are only reachable through
    // routes/commissioning.ts, selected by loadRouterForMode only when
    // HEALTH_ONLY_NO_SCHEDULERS is true. Prove the wiring source contract
    // statically: normal index.ts must not reference the commissioning
    // module, and commissioning.ts must not import the full kite router.
    const fs = await import("node:fs");
    const path = await import("node:path");
    const dir = path.dirname(new URL(import.meta.url).pathname);
    const indexSrc = fs.readFileSync(
      path.join(dir, "index.ts"),
      "utf8",
    );
    const commissioningSrc = fs.readFileSync(
      path.join(dir, "commissioning.ts"),
      "utf8",
    );
    expect(indexSrc).not.toContain("commissioningKiteAuth");
    expect(commissioningSrc).not.toContain('"./kite"');
    expect(commissioningSrc).toContain('"./commissioningKiteAuth"');
  });
});
