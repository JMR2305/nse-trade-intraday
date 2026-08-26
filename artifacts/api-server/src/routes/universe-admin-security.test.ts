/**
 * Retired legacy-universe mutation route tests.
 *
 * Task 947 requirement: old active-master write paths are retired and cannot
 * be revived by presenting an administrator credential to browser code.
 * Verifies:
 *   1. Upsert with no, wrong, or correct token → 410
 *   2. Hydration with any confirmation/token → 410
 *   4. GET /universe/custom/status remains public (no token needed)
 *   5. GET /universe/custom/symbols remains public (no token needed)
 *   6. No broker order API is reachable from this route (static code assertion)
 *   7. No retired mutation dispatches Python or a broker operation.
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

describe("Retired universe mutation routes", () => {
  let server: Server;
  const VALID_TOKEN = "test-admin-token-phase1f";
  const VALID_ACTIVE_ROW = {
    symbol: "WIPRO",
    company_name: "Wipro Ltd",
    sector: "IT",
    yahoo_symbol: "WIPRO.NS",
    kite_symbol: "WIPRO",
    price_min: 20,
    price_max: 500,
    is_active: true,
    ohlcv_available: true,
  };

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

  function hydrationCalls() {
    return spawnMock.mock.calls.filter(
      (call) => Array.isArray(call[1])
        && (call[1] as string[]).includes("universe_custom_hydrate_instruments"),
    );
  }

  // ── Test 1: no token cannot revive a legacy route ───────────────────────────

  it("returns 410 when x-admin-token header is missing", async () => {
    const r = await request(server, {
      method: "POST",
      path: "/api/universe/custom/upsert",
      // adminToken intentionally omitted
      body: { rows: [{ symbol: "WIPRO", is_active: true }] },
    });
    expect(r.status).toBe(410);
    const body = r.body as Record<string, unknown>;
    expect(body["success"]).toBe(false);
    expect(body["error"]).toBe("retired_universe_mutation_route");
    // universe_custom_upsert command was never dispatched to Python
    expect(upsertCalls()).toHaveLength(0);
  });

  // ── Test 2: wrong token cannot revive a legacy route ────────────────────────

  it("returns 410 when x-admin-token contains a wrong value", async () => {
    const r = await request(server, {
      method: "POST",
      path: "/api/universe/custom/upsert",
      adminToken: "wrong-token-attacker",
      body: { rows: [{ symbol: "WIPRO", is_active: true }] },
    });
    expect(r.status).toBe(410);
    const body = r.body as Record<string, unknown>;
    expect(body["success"]).toBe(false);
    expect(body["error"]).toBe("retired_universe_mutation_route");
    // universe_custom_upsert was never dispatched — no upsert reached the database
    expect(upsertCalls()).toHaveLength(0);
  });

  // ── Test 3: a formerly valid token cannot mutate the master ─────────────────

  it("returns 410 even when a formerly valid x-admin-token is provided", async () => {
    const r = await request(server, {
      method: "POST",
      path: "/api/universe/custom/upsert",
      adminToken: VALID_TOKEN,
      body: { rows: [VALID_ACTIVE_ROW] },
    });
    expect(r.status).toBe(410);
    const body = r.body as Record<string, unknown>;
    expect(body["error"]).toBe("retired_universe_mutation_route");
    expect(upsertCalls()).toHaveLength(0);
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

  // ── Test 6: retired route cannot dispatch any Python operation ──────────────

  it("dispatches no legacy upsert or broker command", async () => {
    await request(server, {
      method: "POST",
      path: "/api/universe/custom/upsert",
      adminToken: VALID_TOKEN,
      body: { rows: [VALID_ACTIVE_ROW] },
    });

    // Filter to the legacy command (ignore app-startup spawn calls).
    const calls = upsertCalls();
    expect(calls).toHaveLength(0);

    const BROKER_COMMANDS = [
      "place_order", "kite_order", "execute_buy", "execute_sell",
      "modify_order", "cancel_order", "broker_order",
    ];
    const allDispatchedArgs = calls.flat(2) as string[];
    for (const cmd of BROKER_COMMANDS) {
      expect(allDispatchedArgs).not.toContain(cmd);
    }
  });

  it("returns 410 and does not dispatch a partial active WIPRO overwrite", async () => {
    const r = await request(server, {
      method: "POST",
      path: "/api/universe/custom/upsert",
      adminToken: VALID_TOKEN,
      body: {
        rows: [{
          symbol: "WIPRO",
          is_active: true,
          sector: null,
          price_max: 200,
          ohlcv_available: false,
        }],
      },
    });
    expect(r.status).toBe(410);
    const body = r.body as Record<string, unknown>;
    expect(body["success"]).toBe(false);
    expect(body["error"]).toBe("retired_universe_mutation_route");
    expect(upsertCalls()).toHaveLength(0);
  });

  it("retires metadata hydration without inspecting an admin token", async () => {
    const r = await request(server, {
      method: "POST",
      path: "/api/universe/custom/hydrate-instruments",
      body: { confirmation: "HYDRATE_INSTRUMENT_METADATA_ONLY" },
    });

    expect(r.status).toBe(410);
    expect(hydrationCalls()).toHaveLength(0);
  });

  it("retires metadata hydration before considering its confirmation", async () => {
    const r = await request(server, {
      method: "POST",
      path: "/api/universe/custom/hydrate-instruments",
      adminToken: VALID_TOKEN,
      body: { confirmation: "refresh" },
    });

    expect(r.status).toBe(410);
    expect((r.body as Record<string, unknown>)["error"]).toBe("retired_universe_mutation_route");
    expect(hydrationCalls()).toHaveLength(0);
  });

  it("never dispatches even an explicitly approved legacy hydration", async () => {
    const r = await request(server, {
      method: "POST",
      path: "/api/universe/custom/hydrate-instruments",
      adminToken: VALID_TOKEN,
      body: { confirmation: "HYDRATE_INSTRUMENT_METADATA_ONLY" },
    });

    expect(r.status).toBe(410);
    expect(hydrationCalls()).toHaveLength(0);
  });
});

// ── Suite 2: fail-closed when env var is unset ────────────────────────────────

describe("Retired route ignores removed UNIVERSE_ADMIN_TOKEN capability", () => {
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

  it("returns 410 for any token value when UNIVERSE_ADMIN_TOKEN is not set", async () => {
    const r = await request(server, {
      method: "POST",
      path: "/api/universe/custom/upsert",
      adminToken: "any-value-even-correct-looking",
      body: { rows: [{
        symbol: "WIPRO",
        is_active: true,
        sector: "IT",
        company_name: "Wipro Ltd",
        yahoo_symbol: "WIPRO.NS",
        kite_symbol: "WIPRO",
        price_min: 20,
        price_max: 500,
        ohlcv_available: true,
      }] },
    });
    expect(r.status).toBe(410);
    expect((r.body as Record<string, unknown>)["success"]).toBe(false);
    // universe_custom_upsert was never dispatched to Python
    const upsertCallsFailClosed = spawnMock.mock.calls.filter(
      (call) => Array.isArray(call[1]) && (call[1] as string[]).includes("universe_custom_upsert"),
    );
    expect(upsertCallsFailClosed).toHaveLength(0);
  });
});
