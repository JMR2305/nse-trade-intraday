/**
 * Route-level coverage freshness test for POST /api/universe/active.
 *
 * The scanner-coverage endpoint has a 30-second server-side cache. This test
 * verifies that changing the active universe clears that cache so the first
 * following coverage poll cannot report the previous universe's expected
 * count.
 */

import {
  afterAll,
  beforeAll,
  beforeEach,
  describe,
  expect,
  it,
  vi,
} from "vitest";
import type { Server } from "node:http";
import { EventEmitter } from "node:events";

const mockSpawn = vi.fn();
vi.mock("node:child_process", () => ({ spawn: mockSpawn }));

function makePyProc(jsonData: unknown) {
  const proc = Object.assign(new EventEmitter(), {
    stdout: new EventEmitter(),
    stderr: new EventEmitter(),
    kill: vi.fn(),
  });
  setImmediate(() => {
    (proc.stdout as EventEmitter).emit(
      "data",
      Buffer.from(JSON.stringify(jsonData)),
    );
    proc.emit("close", 0);
  });
  return proc;
}

function spawnCmd(callArgs: unknown[]): string {
  return ((callArgs[1] as string[])[1]) ?? "";
}

describe("active universe route invalidates scanner coverage cache", () => {
  let server: Server;
  let port: number;
  let activeUniverse = "NIFTY_50";
  let invalidateCoverageCache: () => void;

  async function request(
    path: string,
    options: { method?: string; body?: unknown } = {},
  ): Promise<{ status: number; body: unknown }> {
    const response = await fetch(`http://127.0.0.1:${port}${path}`, {
      method: options.method ?? "GET",
      headers: options.body === undefined
        ? undefined
        : { "Content-Type": "application/json" },
      body: options.body === undefined ? undefined : JSON.stringify(options.body),
    });
    return {
      status: response.status,
      body: await response.json().catch(() => null),
    };
  }

  beforeAll(async () => {
    mockSpawn.mockImplementation((_bin: string, spawnArgs: string[]) => {
      const command = spawnArgs[1] ?? "";
      if (command === "scanner_coverage") {
        const custom = activeUniverse === "CUSTOM_LOW_PRICE_SECTOR";
        return makePyProc({
          success: true,
          ok: true,
          active_universe: activeUniverse,
          min_symbols_expected: custom ? 2 : 50,
          coverage: custom ? 2 : 50,
        });
      }
      if (command === "phase20_settings_update") {
        const payload = JSON.parse(spawnArgs[2] ?? "{}") as {
          patch?: { active_intraday_universe?: string };
        };
        activeUniverse = payload.patch?.active_intraday_universe ?? activeUniverse;
        return makePyProc({
          success: true,
          settings: { active_intraday_universe: activeUniverse },
        });
      }
      return makePyProc({});
    });

    const [{ default: app }, routesMod] = await Promise.all([
      import("../app.js"),
      import("./trading.js"),
    ]);
    invalidateCoverageCache = routesMod.invalidateCoverageCache;

    await new Promise<void>((resolve) => {
      server = app.listen(0, "127.0.0.1", () => resolve());
    });
    port = (server.address() as { port: number }).port;
  }, 30_000);

  afterAll(() => {
    server?.close();
  });

  beforeEach(() => {
    activeUniverse = "NIFTY_50";
    invalidateCoverageCache();
    mockSpawn.mockClear();
  });

  it("does not serve the previous universe after a successful active-universe switch", async () => {
    const initial = await request("/api/live-data/coverage");
    expect(initial.status).toBe(200);
    expect(initial.body).toMatchObject({
      active_universe: "NIFTY_50",
      min_symbols_expected: 50,
    });
    expect(mockSpawn.mock.calls.filter((call) => spawnCmd(call) === "scanner_coverage"))
      .toHaveLength(1);

    const update = await request("/api/universe/active", {
      method: "POST",
      body: { active_intraday_universe: "CUSTOM_LOW_PRICE_SECTOR" },
    });
    expect(update.status).toBe(200);
    expect(update.body).toMatchObject({
      success: true,
      settings: { active_intraday_universe: "CUSTOM_LOW_PRICE_SECTOR" },
    });

    const afterSwitch = await request("/api/live-data/coverage");
    expect(afterSwitch.status).toBe(200);
    expect(afterSwitch.body).toMatchObject({
      active_universe: "CUSTOM_LOW_PRICE_SECTOR",
      min_symbols_expected: 2,
      coverage: 2,
    });
    expect(mockSpawn.mock.calls.filter((call) => spawnCmd(call) === "scanner_coverage"))
      .toHaveLength(2);
  });

  it("does not serve the previous universe after the general settings route changes it", async () => {
    const initial = await request("/api/live-data/coverage");
    expect(initial.status).toBe(200);
    expect(initial.body).toMatchObject({
      active_universe: "NIFTY_50",
      min_symbols_expected: 50,
    });

    const update = await request("/api/phase20/settings", {
      method: "PUT",
      body: {
        patch: { active_intraday_universe: "CUSTOM_LOW_PRICE_SECTOR" },
      },
    });
    expect(update.status).toBe(200);
    expect(update.body).toMatchObject({
      success: true,
      settings: { active_intraday_universe: "CUSTOM_LOW_PRICE_SECTOR" },
    });

    const afterSwitch = await request("/api/live-data/coverage");
    expect(afterSwitch.status).toBe(200);
    expect(afterSwitch.body).toMatchObject({
      active_universe: "CUSTOM_LOW_PRICE_SECTOR",
      min_symbols_expected: 2,
      coverage: 2,
    });
    expect(mockSpawn.mock.calls.filter((call) => spawnCmd(call) === "scanner_coverage"))
      .toHaveLength(2);
  });
});