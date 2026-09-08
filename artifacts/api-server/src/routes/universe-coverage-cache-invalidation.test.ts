/**
 * Route-level legacy-mutation safety test.
 *
 * The scanner-coverage endpoint has a 30-second server-side cache. This test
 * verifies that deprecated direct active-universe mutations do not clear the
 * cache or alter the live setting. Only the locked versioned workflow may
 * ever schedule a future revision.
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
import { createSession } from "../lib/session";

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

function makeHeldPyProc(jsonData: unknown) {
  const proc = Object.assign(new EventEmitter(), {
    stdout: new EventEmitter(),
    stderr: new EventEmitter(),
    kill: vi.fn(),
  });
  return {
    proc,
    release: () => {
      (proc.stdout as EventEmitter).emit(
        "data",
        Buffer.from(JSON.stringify(jsonData)),
      );
      proc.emit("close", 0);
    },
  };
}

function spawnCmd(callArgs: unknown[]): string {
  return ((callArgs[1] as string[])[1]) ?? "";
}

describe("scanner coverage cache around versioned universe changes", () => {
  let server: Server;
  let port: number;
  let activeUniverse = "NIFTY_50";
  let invalidateCoverageCache: () => void;
  let holdCoverage = false;
  let releaseHeldCoverage: (() => void) | null = null;

  async function request(
    path: string,
    options: { method?: string; body?: unknown; session?: boolean } = {},
  ): Promise<{ status: number; body: unknown }> {
    const headers: Record<string, string> = options.body === undefined
      ? {}
      : { "Content-Type": "application/json" };
    if (options.session) {
      headers.Cookie = `__session=${createSession()}`;
    }
    const response = await fetch(`http://127.0.0.1:${port}${path}`, {
      method: options.method ?? "GET",
      headers,
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
        // Capture the universe at subprocess start. The test must prove this
        // delayed, old-world response cannot become the next cached value.
        const universeAtStart = activeUniverse;
        const custom = universeAtStart === "CUSTOM_LOW_PRICE_SECTOR";
        const payload = {
          success: true,
          ok: true,
          active_universe: universeAtStart,
          min_symbols_expected: custom ? 2 : 50,
          coverage: custom ? 2 : 50,
        };
        if (holdCoverage) {
          holdCoverage = false;
          const held = makeHeldPyProc(payload);
          releaseHeldCoverage = held.release;
          return held.proc;
        }
        return makePyProc(payload);
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
      if (command === "universe_management_activate") {
        activeUniverse = "CUSTOM_LOW_PRICE_SECTOR";
        return makePyProc({
          success: true,
          active_revision: { version: 2, status: "ACTIVE" },
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
    holdCoverage = false;
    releaseHeldCoverage = null;
    invalidateCoverageCache();
    mockSpawn.mockClear();
  });

  it("rejects the legacy active-universe switch without invalidating coverage", async () => {
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
    expect(update.status).toBe(410);
    expect(update.body).toMatchObject({
      success: false,
      error: "retired_universe_mutation_route",
    });

    const afterSwitch = await request("/api/live-data/coverage");
    expect(afterSwitch.status).toBe(200);
    expect(afterSwitch.body).toMatchObject({
      active_universe: "NIFTY_50",
      min_symbols_expected: 50,
      coverage: 50,
    });
    expect(mockSpawn.mock.calls.filter((call) => spawnCmd(call) === "scanner_coverage"))
      .toHaveLength(1);
  });

  it("rejects generic settings attempts to change the active universe", async () => {
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
    expect(update.status).toBe(410);
    expect(update.body).toMatchObject({
      success: false,
      error: "retired_universe_mutation_route",
    });

    const afterSwitch = await request("/api/live-data/coverage");
    expect(afterSwitch.status).toBe(200);
    expect(afterSwitch.body).toMatchObject({
      active_universe: "NIFTY_50",
      min_symbols_expected: 50,
      coverage: 50,
    });
    expect(mockSpawn.mock.calls.filter((call) => spawnCmd(call) === "scanner_coverage"))
      .toHaveLength(1);
  });

  it("does not let a delayed pre-activation coverage poll overwrite the newly active universe", async () => {
    holdCoverage = true;
    const delayedOldCoverage = request("/api/live-data/coverage");

    await vi.waitFor(() => {
      expect(mockSpawn.mock.calls.filter((call) => spawnCmd(call) === "scanner_coverage"))
        .toHaveLength(1);
    });

    const activation = await request("/api/universe/v1/revisions/2/activate", {
      method: "POST",
      session: true,
      body: { confirmation: "ACTIVATE 2" },
    });
    expect(activation.status).toBe(200);
    expect(activation.body).toMatchObject({
      active_revision: { version: 2, status: "ACTIVE" },
    });

    expect(releaseHeldCoverage).not.toBeNull();
    releaseHeldCoverage?.();

    const oldResponse = await delayedOldCoverage;
    expect(oldResponse.status).toBe(200);
    expect(oldResponse.body).toMatchObject({
      active_universe: "NIFTY_50",
      min_symbols_expected: 50,
    });

    const nextCoverage = await request("/api/live-data/coverage");
    expect(nextCoverage.status).toBe(200);
    expect(nextCoverage.body).toMatchObject({
      active_universe: "CUSTOM_LOW_PRICE_SECTOR",
      min_symbols_expected: 2,
      coverage: 2,
    });
    expect(mockSpawn.mock.calls.filter((call) => spawnCmd(call) === "scanner_coverage"))
      .toHaveLength(2);
  });
});