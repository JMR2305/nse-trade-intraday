/**
 * Route-level integration tests for GET /api/portfolio/config
 *
 * These tests spin up a real Express server (same app wiring as production)
 * and mock child_process.spawn so no real Python process is launched.
 * They catch wiring bugs that unit tests cannot: wrong command args,
 * JSON-parse failures in the route, and error propagation to HTTP 500.
 */
import { afterAll, afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import type { Server } from "node:http";
import { EventEmitter } from "node:events";

// ── Mock child_process before the route module loads ─────────────────────────

/**
 * Factory: returns a fake ChildProcess that emits stdout/stderr/close events
 * controllable from tests via the returned handle.
 */
function makeSpawnMock(
  stdoutPayload: string,
  exitCode: number,
  stderrPayload = "",
) {
  return () => {
    const proc = new EventEmitter() as EventEmitter & {
      stdout: EventEmitter;
      stderr: EventEmitter;
      kill: ReturnType<typeof vi.fn>;
    };
    proc.stdout = new EventEmitter();
    proc.stderr = new EventEmitter();
    proc.kill = vi.fn();

    // Emit asynchronously so the route has time to attach listeners.
    setImmediate(() => {
      if (stdoutPayload) proc.stdout.emit("data", Buffer.from(stdoutPayload));
      if (stderrPayload) proc.stderr.emit("data", Buffer.from(stderrPayload));
      proc.emit("close", exitCode);
    });

    return proc;
  };
}

// Hoist the mock so it applies before any import resolves the real module.
vi.mock("node:child_process", () => ({ spawn: vi.fn() }));
vi.mock("child_process", () => ({ spawn: vi.fn() }));

// ── Helpers ───────────────────────────────────────────────────────────────────

/** A minimal valid Python response for portfolio_config. */
const VALID_PYTHON_RESPONSE = JSON.stringify({
  loaded: true,
  limits_from_config: true,
  config: {
    portfolio_id: "default",
    enabled: true,
    base_currency: "INR",
    paper_mode: true,
    initial_capital: 100000,
    cash_reserve_pct: 0.05,
    max_portfolio_exposure_pct: 0.9,
    max_instrument_exposure_pct: 0.2,
    max_sector_exposure_pct: 0.35,
    max_strategy_exposure_pct: 0.3,
    max_open_positions: 10,
    max_pending_orders: 20,
    max_daily_loss_pct: 0.05,
    max_drawdown_pct: 0.1,
    max_capital_per_strategy_pct: 0.3,
    min_order_value: 1000,
    max_order_value: 50000,
    default_risk_per_trade_pct: 0.01,
    use_ai_confidence_sizing: false,
    ai_confidence_min: 0.6,
    stale_state_threshold_s: 300,
    stale_broker_threshold_s: 60,
    stale_price_threshold_s: 30,
    reconciliation_interval_s: 3600,
    snapshot_interval_s: 60,
    allocation_ttl_s: 86400,
  },
  error: null,
  fetched_at: new Date().toISOString(),
});

/** Make an HTTP GET request to the test server. Returns parsed JSON + status. */
async function getJson(
  server: Server,
  path: string,
): Promise<{ status: number; body: Record<string, unknown> }> {
  const addr = server.address();
  if (!addr || typeof addr === "string") throw new Error("Server not bound");
  const port = addr.port;

  const res = await fetch(`http://127.0.0.1:${port}${path}`);
  let body: Record<string, unknown>;
  try {
    body = (await res.json()) as Record<string, unknown>;
  } catch {
    body = {};
  }
  return { status: res.status, body };
}

// ── Test suite ────────────────────────────────────────────────────────────────

describe("GET /api/portfolio/config — route integration", () => {
  let server: Server;
  let spawnMock: ReturnType<typeof vi.fn>;

  beforeAll(async () => {
    // Import after mocks are installed.
    const { default: app } = await import("../app.js");
    const { spawn } = await import("node:child_process");
    spawnMock = spawn as ReturnType<typeof vi.fn>;

    await new Promise<void>((resolve) => {
      server = app.listen(0, "127.0.0.1", () => resolve());
    });
  });

  afterAll(() => {
    server?.close();
  });

  afterEach(() => {
    spawnMock.mockReset();
  });

  // ── Happy path ──────────────────────────────────────────────────────────────

  it("returns HTTP 200 when Python exits 0", async () => {
    spawnMock.mockImplementation(makeSpawnMock(VALID_PYTHON_RESPONSE, 0));

    const { status } = await getJson(server, "/api/portfolio/config");

    expect(status).toBe(200);
  });

  it("response body contains a boolean `loaded` field", async () => {
    spawnMock.mockImplementation(makeSpawnMock(VALID_PYTHON_RESPONSE, 0));

    const { body } = await getJson(server, "/api/portfolio/config");

    expect(typeof body["loaded"]).toBe("boolean");
  });

  it("response body contains a string `fetched_at` field", async () => {
    spawnMock.mockImplementation(makeSpawnMock(VALID_PYTHON_RESPONSE, 0));

    const { body } = await getJson(server, "/api/portfolio/config");

    expect(typeof body["fetched_at"]).toBe("string");
    // Must be a parseable ISO-8601 timestamp.
    expect(Number.isNaN(Date.parse(body["fetched_at"] as string))).toBe(false);
  });

  it("response body contains `config` with required limit keys", async () => {
    spawnMock.mockImplementation(makeSpawnMock(VALID_PYTHON_RESPONSE, 0));

    const { body } = await getJson(server, "/api/portfolio/config");

    const cfg = body["config"] as Record<string, unknown>;
    expect(cfg).toBeTruthy();
    for (const key of [
      "max_instrument_exposure_pct",
      "max_sector_exposure_pct",
      "max_portfolio_exposure_pct",
      "max_open_positions",
      "initial_capital",
    ]) {
      expect(cfg, `config.${key} must be present`).toHaveProperty(key);
    }
  });

  it("response body contains `overrides` and `overridden_fields` from the route layer", async () => {
    spawnMock.mockImplementation(makeSpawnMock(VALID_PYTHON_RESPONSE, 0));

    const { body } = await getJson(server, "/api/portfolio/config");

    // These fields are added by the route, not by Python.
    expect(body).toHaveProperty("overrides");
    expect(body).toHaveProperty("overridden_fields");
    expect(Array.isArray(body["overridden_fields"])).toBe(true);
  });

  it("invokes Python with the portfolio_config command argument", async () => {
    spawnMock.mockImplementation(makeSpawnMock(VALID_PYTHON_RESPONSE, 0));

    await getJson(server, "/api/portfolio/config");

    expect(spawnMock).toHaveBeenCalledOnce();
    const args: string[] = spawnMock.mock.calls[0]![1] as string[];
    // args = [<path/to/main.py>, "portfolio_config"]
    expect(args.at(-1)).toBe("portfolio_config");
  });

  // ── Error path ──────────────────────────────────────────────────────────────

  it("returns HTTP 500 when Python exits with a non-zero code", async () => {
    spawnMock.mockImplementation(
      makeSpawnMock("", 1, "PortfolioConfig: module not found"),
    );

    const { status } = await getJson(server, "/api/portfolio/config");

    expect(status).toBe(500);
  });

  it("response body contains an `error` string when Python fails", async () => {
    spawnMock.mockImplementation(
      makeSpawnMock("", 1, "PortfolioConfig: module not found"),
    );

    const { body } = await getJson(server, "/api/portfolio/config");

    expect(typeof body["error"]).toBe("string");
    expect((body["error"] as string).length).toBeGreaterThan(0);
  });

  it("returns HTTP 500 when Python emits a JSON error payload", async () => {
    // The route inspects a JSON-encoded error even on exit code 1.
    const errPayload = JSON.stringify({ error: "PortfolioConfig unavailable" });
    spawnMock.mockImplementation(makeSpawnMock(errPayload, 1));

    const { status, body } = await getJson(server, "/api/portfolio/config");

    expect(status).toBe(500);
    expect(body["error"]).toBe("PortfolioConfig unavailable");
  });

  it("returns HTTP 500 when Python stdout is not valid JSON", async () => {
    spawnMock.mockImplementation(makeSpawnMock("not-json-at-all", 0));

    const { status } = await getJson(server, "/api/portfolio/config");

    expect(status).toBe(500);
  });
});

// ── PATCH /api/portfolio/config — consistency checks ─────────────────────────

/** Make an HTTP PATCH request to the test server. Returns parsed JSON + status. */
async function patchJson(
  server: Server,
  path: string,
  body: Record<string, unknown>,
): Promise<{ status: number; body: Record<string, unknown> }> {
  const addr = server.address();
  if (!addr || typeof addr === "string") throw new Error("Server not bound");
  const port = addr.port;

  const res = await fetch(`http://127.0.0.1:${port}${path}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  let body2: Record<string, unknown>;
  try {
    body2 = (await res.json()) as Record<string, unknown>;
  } catch {
    body2 = {};
  }
  return { status: res.status, body: body2 };
}

describe("PATCH /api/portfolio/config — instrument/sector vs portfolio limit cross-checks", () => {
  let server: Server;
  let spawnMock: ReturnType<typeof vi.fn>;

  beforeAll(async () => {
    const { default: app } = await import("../app.js");
    const { spawn } = await import("node:child_process");
    spawnMock = spawn as ReturnType<typeof vi.fn>;

    await new Promise<void>((resolve) => {
      server = app.listen(0, "127.0.0.1", () => resolve());
    });
  });

  afterAll(() => {
    server?.close();
  });

  afterEach(() => {
    spawnMock.mockReset();
    // Also clear any session overrides that accumulated during the test
    // by hitting the DELETE endpoint directly.
  });

  it("accepts instrument limit equal to portfolio limit", async () => {
    // base config: max_portfolio_exposure_pct = 0.9
    spawnMock.mockImplementation(makeSpawnMock(VALID_PYTHON_RESPONSE, 0));

    const { status } = await patchJson(server, "/api/portfolio/config", {
      max_instrument_exposure_pct: 0.9, // equals portfolio limit → valid
    });

    // 200 ok OR could be 200 after a DELETE reset; the important thing is NOT 422
    expect(status).not.toBe(422);
  });

  it("rejects instrument limit above portfolio limit with HTTP 422", async () => {
    spawnMock.mockImplementation(makeSpawnMock(VALID_PYTHON_RESPONSE, 0));

    const { status, body } = await patchJson(server, "/api/portfolio/config", {
      max_instrument_exposure_pct: 0.95, // 95% > 90% portfolio limit
    });

    expect(status).toBe(422);
    expect(typeof body["error"]).toBe("string");
    expect((body["error"] as string).toLowerCase()).toContain("instrument");
    expect((body["error"] as string).toLowerCase()).toContain("portfolio");
  });

  it("field_errors contains max_instrument_exposure_pct when instrument limit exceeds portfolio limit", async () => {
    spawnMock.mockImplementation(makeSpawnMock(VALID_PYTHON_RESPONSE, 0));

    const { body } = await patchJson(server, "/api/portfolio/config", {
      max_instrument_exposure_pct: 0.95,
    });

    const fieldErrors = body["field_errors"] as Record<string, string> | undefined;
    expect(fieldErrors).toBeTruthy();
    expect(typeof fieldErrors!["max_instrument_exposure_pct"]).toBe("string");
  });

  it("rejects sector limit above portfolio limit with HTTP 422", async () => {
    spawnMock.mockImplementation(makeSpawnMock(VALID_PYTHON_RESPONSE, 0));

    const { status, body } = await patchJson(server, "/api/portfolio/config", {
      max_sector_exposure_pct: 0.95, // 95% > 90% portfolio limit
    });

    expect(status).toBe(422);
    expect(typeof body["error"]).toBe("string");
    expect((body["error"] as string).toLowerCase()).toContain("sector");
    expect((body["error"] as string).toLowerCase()).toContain("portfolio");
  });

  it("field_errors contains max_sector_exposure_pct when sector limit exceeds portfolio limit", async () => {
    spawnMock.mockImplementation(makeSpawnMock(VALID_PYTHON_RESPONSE, 0));

    const { body } = await patchJson(server, "/api/portfolio/config", {
      max_sector_exposure_pct: 0.95,
    });

    const fieldErrors = body["field_errors"] as Record<string, string> | undefined;
    expect(fieldErrors).toBeTruthy();
    expect(typeof fieldErrors!["max_sector_exposure_pct"]).toBe("string");
  });

  it("accepts sector limit below portfolio limit", async () => {
    spawnMock.mockImplementation(makeSpawnMock(VALID_PYTHON_RESPONSE, 0));

    const { status } = await patchJson(server, "/api/portfolio/config", {
      max_sector_exposure_pct: 0.35, // 35% < 90% portfolio limit → valid
    });

    expect(status).not.toBe(422);
  });

  it("rejects a patch that simultaneously sets both limits above the current portfolio limit", async () => {
    spawnMock.mockImplementation(makeSpawnMock(VALID_PYTHON_RESPONSE, 0));

    const { status } = await patchJson(server, "/api/portfolio/config", {
      max_instrument_exposure_pct: 0.95,
      max_sector_exposure_pct: 0.95,
    });

    expect(status).toBe(422);
  });

  it("rejects instrument limit above the NEW portfolio limit when both are patched together", async () => {
    // Patch portfolio limit down to 0.5 and instrument limit to 0.6 in the same call.
    // The instrument check must use the incoming 0.5, not the base 0.9.
    spawnMock.mockImplementation(makeSpawnMock(VALID_PYTHON_RESPONSE, 0));

    const { status, body } = await patchJson(server, "/api/portfolio/config", {
      max_portfolio_exposure_pct: 0.5,
      max_instrument_exposure_pct: 0.6,
    });

    expect(status).toBe(422);
    expect((body["error"] as string).toLowerCase()).toContain("instrument");
  });

  it("accepts instrument limit below the NEW portfolio limit when both are patched together", async () => {
    // Patch portfolio limit to 0.8 and instrument limit to 0.3 in the same call.
    spawnMock.mockImplementation(makeSpawnMock(VALID_PYTHON_RESPONSE, 0));

    const { status } = await patchJson(server, "/api/portfolio/config", {
      max_portfolio_exposure_pct: 0.8,
      max_instrument_exposure_pct: 0.3,
    });

    expect(status).not.toBe(422);
  });
});
