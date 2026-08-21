/**
 * Admin route security tests — POST /universe/custom/upsert
 *
 * Phase 1F requirement: The upsert route must be protected by UNIVERSE_ADMIN_TOKEN.
 * Verifies:
 *   1. Upsert without token → 403
 *   2. Upsert with wrong token → 403
 *   3. Upsert with correct token → success (Python mocked)
 *   4. GET /universe/custom/status remains public (no token needed)
 *   5. GET /universe/custom/symbols remains public (no token needed)
 *   6. No broker order API is reachable from this route (static code assertion)
 *   7. Fail-closed: 403 when UNIVERSE_ADMIN_TOKEN env var is unset
 */

import {
  afterAll,
  afterEach,
  beforeAll,
  describe,
  expect,
  it,
  vi,
} from "vitest";
import type { Server } from "node:http";
import { EventEmitter } from "node:events";

// ── Helper: create a fresh mock proc that emits JSON then closes ──────────────
function makeMockProc(jsonPayload: string, exitCode = 0, delayMs = 10) {
  const proc = new EventEmitter() as EventEmitter & {
    stdout: EventEmitter;
    stderr: EventEmitter;
    kill: ReturnType<typeof vi.fn>;
  };
  proc.stdout = new EventEmitter();
  proc.stderr = new EventEmitter();
  proc.kill = vi.fn();
  // Schedule the emit AFTER listeners have been attached by runPython
  setTimeout(() => {
    proc.stdout.emit("data", Buffer.from(jsonPayload));
    proc.emit("close", exitCode);
  }, delayMs);
  return proc;
}

// ── Base spawn mock (overridden per-test where needed) ────────────────────────
const spawnMock = vi.fn(() => makeMockProc(JSON.stringify({ success: true, upserted: 1 })));

vi.mock("node:child_process", () => ({
  spawn: spawnMock,
}));

// ── HTTP helper ───────────────────────────────────────────────────────────────
interface FetchResult {
  status: number;
  body: unknown;
}

async function request(
  server: Server,
  opts: {
    method?: string;
    path: string;
    adminToken?: string | null;
    body?: unknown;
  },
): Promise<FetchResult> {
  const addr = server.address();
  if (!addr || typeof addr === "string") throw new Error("Server not bound");
  const port = (addr as { port: number }).port;

  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (opts.adminToken != null) headers["x-admin-token"] = opts.adminToken;

  const res = await fetch(`http://127.0.0.1:${port}${opts.path}`, {
    method: opts.method ?? "GET",
    headers,
    body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
  });

  let body: unknown;
  try { body = await res.json(); } catch { body = null; }
  return { status: res.status, body };
}

// ── Suite 1: token gate ───────────────────────────────────────────────────────

describe("Admin route security — POST /api/universe/custom/upsert", () => {
  let server: Server;
  const VALID_TOKEN = "test-admin-token-phase1f";

  beforeAll(async () => {
    process.env.UNIVERSE_ADMIN_TOKEN = VALID_TOKEN;
    const { default: app } = await import("../app.js");
    await new Promise<void>((resolve) => {
      server = app.listen(0, "127.0.0.1", () => resolve());
    });
  });

  afterAll(() => {
    server?.close();
    delete process.env.UNIVERSE_ADMIN_TOKEN;
  });

  afterEach(() => {
    vi.clearAllMocks();
    // Reset default implementation after each test
    spawnMock.mockImplementation(() =>
      makeMockProc(JSON.stringify({ success: true, upserted: 1 })),
    );
  });

  // Helper: filter spawn calls to those that dispatched a specific Python command
  function upsertCalls() {
    return spawnMock.mock.calls.filter(
      (call) => Array.isArray(call[1]) && (call[1] as string[]).includes("universe_custom_upsert"),
    );
  }

  // ── Test 1: missing token → 403 ─────────────────────────────────────────────

  it("returns 403 when x-admin-token header is missing", async () => {
    const r = await request(server, {
      method: "POST",
      path: "/api/universe/custom/upsert",
      // adminToken intentionally omitted
      body: { rows: [{ symbol: "WIPRO", is_active: true }] },
    });
    expect(r.status).toBe(403);
    const body = r.body as Record<string, unknown>;
    expect(body["success"]).toBe(false);
    expect((body["error"] as string).toLowerCase()).toMatch(/forbidden/);
    // universe_custom_upsert command was never dispatched to Python
    expect(upsertCalls()).toHaveLength(0);
  });

  // ── Test 2: wrong token → 403 ───────────────────────────────────────────────

  it("returns 403 when x-admin-token contains a wrong value", async () => {
    const r = await request(server, {
      method: "POST",
      path: "/api/universe/custom/upsert",
      adminToken: "wrong-token-attacker",
      body: { rows: [{ symbol: "WIPRO", is_active: true }] },
    });
    expect(r.status).toBe(403);
    const body = r.body as Record<string, unknown>;
    expect(body["success"]).toBe(false);
    expect((body["error"] as string).toLowerCase()).toMatch(/forbidden/);
    // universe_custom_upsert was never dispatched — no upsert reached the database
    expect(upsertCalls()).toHaveLength(0);
  });

  // ── Test 3: correct token → success ─────────────────────────────────────────

  it("succeeds when correct x-admin-token is provided", async () => {
    const r = await request(server, {
      method: "POST",
      path: "/api/universe/custom/upsert",
      adminToken: VALID_TOKEN,
      body: { rows: [{ symbol: "WIPRO", is_active: true, ohlcv_available: true }] },
    });
    expect(r.status).toBe(200);
    const body = r.body as Record<string, unknown>;
    expect(body["success"]).toBe(true);
    // Python was invoked
    expect(spawnMock).toHaveBeenCalledOnce();
    // Verify it called the upsert command, not any broker command
    const args = spawnMock.mock.calls[0] as [string, string[]];
    expect(args[1]).toContain("universe_custom_upsert");
  });

  // ── Test 4: GET status is public ────────────────────────────────────────────

  it("GET /api/universe/custom/status is public (no token required)", async () => {
    const r = await request(server, {
      method: "GET",
      path: "/api/universe/custom/status",
      // no adminToken
    });
    expect(r.status).not.toBe(403);
    expect(r.status).toBe(200);
  });

  // ── Test 5: GET symbols is public ───────────────────────────────────────────

  it("GET /api/universe/custom/symbols is public (no token required)", async () => {
    const r = await request(server, {
      method: "GET",
      path: "/api/universe/custom/symbols",
      // no adminToken
    });
    expect(r.status).not.toBe(403);
    expect(r.status).toBe(200);
  });

  // ── Test 6: no broker order API reachable from upsert ───────────────────────

  it("dispatches only universe_custom_upsert command — no broker commands", async () => {
    await request(server, {
      method: "POST",
      path: "/api/universe/custom/upsert",
      adminToken: VALID_TOKEN,
      body: { rows: [{ symbol: "WIPRO", is_active: true }] },
    });

    // Filter to calls that contain universe_custom_upsert (ignore app-startup spawn calls)
    const calls = upsertCalls();
    expect(calls).toHaveLength(1);

    // Verify the command dispatched is exactly universe_custom_upsert
    const dispatchedCmd = (calls[0][1] as string[])[1];
    expect(dispatchedCmd).toBe("universe_custom_upsert");

    const BROKER_COMMANDS = [
      "place_order", "kite_order", "execute_buy", "execute_sell",
      "modify_order", "cancel_order", "broker_order",
    ];
    const allDispatchedArgs = calls.flat(2) as string[];
    for (const cmd of BROKER_COMMANDS) {
      expect(allDispatchedArgs).not.toContain(cmd);
    }
  });
});

// ── Suite 2: fail-closed when env var is unset ────────────────────────────────

describe("Admin route fail-closed — upsert blocked when UNIVERSE_ADMIN_TOKEN not set", () => {
  let server: Server;

  beforeAll(async () => {
    // Ensure env var is absent for this suite
    delete process.env.UNIVERSE_ADMIN_TOKEN;
    const { default: app } = await import("../app.js");
    await new Promise<void>((resolve) => {
      server = app.listen(0, "127.0.0.1", () => resolve());
    });
  });

  afterAll(() => {
    server?.close();
  });

  it("returns 403 for any token value when UNIVERSE_ADMIN_TOKEN is not set (fail-closed)", async () => {
    const r = await request(server, {
      method: "POST",
      path: "/api/universe/custom/upsert",
      adminToken: "any-value-even-correct-looking",
      body: { rows: [{ symbol: "WIPRO", is_active: true }] },
    });
    // No env var → always 403 regardless of what the caller sends
    expect(r.status).toBe(403);
    expect((r.body as Record<string, unknown>)["success"]).toBe(false);
    // universe_custom_upsert was never dispatched to Python
    const upsertCallsFailClosed = spawnMock.mock.calls.filter(
      (call) => Array.isArray(call[1]) && (call[1] as string[]).includes("universe_custom_upsert"),
    );
    expect(upsertCallsFailClosed).toHaveLength(0);
  });
});
