/**
 * platform-cache.test.ts — Task #325
 *
 * Integration tests for the /api/ops-centre/platform Node.js cache:
 *
 *   1. Cache hit        — second request served without a Python spawn
 *   2. clearPlatformCache() — forces a cache miss on the next request
 *   3. scan.completed event — clears cache via eventBus listener
 *   4. /ops-centre/snapshot success — clears cache (fresh KV written)
 *   5. Concurrent coalescing — N simultaneous misses → 1 Python spawn
 *
 * All tests use a real Express server (same wiring as production) with a
 * mocked child_process so no Python subprocess is ever spawned.
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

// ── Mock child_process ────────────────────────────────────────────────────────
// Variables whose names start with "mock" are allowed inside vi.mock factories
// under vitest's hoisting rule — the factory runs before the rest of the file.
const mockSpawn = vi.fn();

vi.mock("node:child_process", () => ({ spawn: mockSpawn }));

// ── Helpers ───────────────────────────────────────────────────────────────────

/**
 * Returns a fake ChildProcess that emits JSON data on stdout then exits 0.
 * setImmediate defers the emit so the caller's promise chain is fully set up
 * before the data arrives (mirrors real async subprocess behaviour).
 */
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

/** Extract the command name from a mockSpawn call (second element of the args array). */
function spawnCmd(callArgs: unknown[]): string {
  return ((callArgs[1] as string[])[1]) ?? "";
}

/** Count how many times mockSpawn was called with a given command name. */
function spawnCount(cmd: string): number {
  return mockSpawn.mock.calls.filter((c) => spawnCmd(c) === cmd).length;
}

// ── Fixture payloads ─────────────────────────────────────────────────────────

const PLATFORM_PAYLOAD = {
  fast: true,
  generated_at: "2026-08-05T09:00:00.000Z",
  cache_ts: null as string | null,
  platform: { health_pct: 95, market_state: "PRE_OPEN", scan_status: "SUCCESS" },
  pipeline_nodes: [],
};

const SNAPSHOT_PAYLOAD = {
  fast: false,
  generated_at: "2026-08-05T09:01:00.000Z",
  agents: [],
  platform: { health_pct: 98, market_state: "PRE_OPEN" },
};

// ── Default spawn mock — platform returns PLATFORM_PAYLOAD, snapshot returns SNAPSHOT_PAYLOAD
function defaultSpawnImpl(_bin: string, spawnArgs: string[]) {
  const cmd = spawnArgs[1] ?? "";
  if (cmd === "ops_centre_snapshot") return makePyProc(SNAPSHOT_PAYLOAD);
  return makePyProc(PLATFORM_PAYLOAD);
}

// ── Suite ─────────────────────────────────────────────────────────────────────

describe("Platform cache — Node.js cache invalidation (Task #325)", () => {
  let server: Server;
  let port: number;
  let clearPlatformCache: () => void;
  let eventBus: import("../lib/events.js")["eventBus"];

  // HTTP helper — always against the local test server
  async function get(path: string): Promise<{ status: number; body: unknown }> {
    const res = await fetch(`http://127.0.0.1:${port}${path}`);
    const body = await res.json().catch(() => null);
    return { status: res.status, body };
  }

  beforeAll(async () => {
    // Apply default spawn implementation before the app module loads.
    mockSpawn.mockImplementation(defaultSpawnImpl);

    // Import app + the two modules whose exports we need.
    // Dynamic import ensures the vi.mock above is already in effect.
    const [{ default: app }, routesMod, eventsMod] = await Promise.all([
      import("../app.js"),
      import("./trading.js"),
      import("../lib/events.js"),
    ]);
    clearPlatformCache = routesMod.clearPlatformCache;
    eventBus = eventsMod.eventBus;

    await new Promise<void>((resolve) => {
      server = app.listen(0, "127.0.0.1", () => resolve());
    });
    port = (server.address() as { port: number }).port;
  });

  afterAll(() => {
    server?.close();
  });

  beforeEach(() => {
    // Always start each test with an empty cache and a clean spawn call log.
    clearPlatformCache();
    mockSpawn.mockClear();
    mockSpawn.mockImplementation(defaultSpawnImpl);
  });

  // ── 1. Cache hit ───────────────────────────────────────────────────────────

  it("serves the second /platform request from cache without spawning Python again", async () => {
    const r1 = await get("/api/ops-centre/platform");
    expect(r1.status).toBe(200);

    const r2 = await get("/api/ops-centre/platform");
    expect(r2.status).toBe(200);

    // Python spawned exactly once for two requests
    expect(spawnCount("ops_centre_platform")).toBe(1);

    // Both responses carry identical data (second is the cached copy)
    expect((r1.body as Record<string, unknown>)["fast"]).toBe(true);
    expect(r2.body).toEqual(r1.body);
  });

  // ── 2. clearPlatformCache() forces a cache miss ───────────────────────────

  it("spawns Python again after clearPlatformCache() is called", async () => {
    // Populate the cache
    await get("/api/ops-centre/platform");
    expect(spawnCount("ops_centre_platform")).toBe(1);

    // Invalidate
    clearPlatformCache();

    // Next request must miss and spawn Python a second time
    const r = await get("/api/ops-centre/platform");
    expect(r.status).toBe(200);
    expect(spawnCount("ops_centre_platform")).toBe(2);
  });

  // ── 3. scan.completed event clears the cache ──────────────────────────────

  it("clears the cache when scan.completed is published on eventBus", async () => {
    // Populate the cache
    await get("/api/ops-centre/platform");
    expect(spawnCount("ops_centre_platform")).toBe(1);

    // Simulate a full scan completing — eventBus listener calls clearPlatformCache()
    eventBus.publish("scan.completed", { scan_id: "test-scan-123" });
    // EventEmitter.emit is synchronous, so cache is cleared immediately

    // Next /platform must be a cache miss
    const r = await get("/api/ops-centre/platform");
    expect(r.status).toBe(200);
    expect(spawnCount("ops_centre_platform")).toBe(2);
  });

  // ── 4. Snapshot route success clears the cache ────────────────────────────

  it("clears the platform cache when /ops-centre/snapshot returns successfully", async () => {
    // Populate the platform cache
    await get("/api/ops-centre/platform");
    expect(spawnCount("ops_centre_platform")).toBe(1);

    // Call the snapshot route — writes fresh KV and must clear the platform cache
    const snap = await get("/api/ops-centre/snapshot");
    expect(snap.status).toBe(200);

    // Next /platform request must be a cache miss (new cache_ts available)
    const r = await get("/api/ops-centre/platform");
    expect(r.status).toBe(200);
    expect(spawnCount("ops_centre_platform")).toBe(2);
  });

  // ── 5. Concurrent cache miss coalescing ───────────────────────────────────

  it("coalesces concurrent cache misses into a single Python spawn", async () => {
    // Fire 4 concurrent requests before any response arrives.
    // All must succeed and resolve to the same data.
    const [r1, r2, r3, r4] = await Promise.all([
      get("/api/ops-centre/platform"),
      get("/api/ops-centre/platform"),
      get("/api/ops-centre/platform"),
      get("/api/ops-centre/platform"),
    ]);

    expect(r1.status).toBe(200);
    expect(r2.status).toBe(200);
    expect(r3.status).toBe(200);
    expect(r4.status).toBe(200);

    // Despite 4 concurrent requests, Python should be spawned exactly once
    expect(spawnCount("ops_centre_platform")).toBe(1);

    // All four responses carry the same data
    expect(r2.body).toEqual(r1.body);
    expect(r3.body).toEqual(r1.body);
    expect(r4.body).toEqual(r1.body);
  });

  // ── 6. Snapshot in-flight coalescing ─────────────────────────────────────

  it("coalesces concurrent /ops-centre/snapshot requests into a single Python spawn", async () => {
    // Fire 3 concurrent snapshot requests; only one Python process should be spawned.
    const [r1, r2, r3] = await Promise.all([
      get("/api/ops-centre/snapshot"),
      get("/api/ops-centre/snapshot"),
      get("/api/ops-centre/snapshot"),
    ]);

    expect(r1.status).toBe(200);
    expect(r2.status).toBe(200);
    expect(r3.status).toBe(200);

    // Despite 3 concurrent requests, Python spawned exactly once for the snapshot
    expect(spawnCount("ops_centre_snapshot")).toBe(1);

    // All three callers receive the same data
    expect(r2.body).toEqual(r1.body);
    expect(r3.body).toEqual(r1.body);
  });

  // ── 7. Sequential snapshot requests each get their own spawn ──────────────

  it("spawns Python for each sequential (non-concurrent) snapshot request", async () => {
    // Requests that arrive after the previous one resolves are NOT coalesced —
    // each is a fresh spawn (no result cache, only in-flight dedup).
    await get("/api/ops-centre/snapshot");
    await get("/api/ops-centre/snapshot");

    expect(spawnCount("ops_centre_snapshot")).toBe(2);
  });

  // ── 8. Snapshot failure does NOT clear the cache ───────────────────────────

  it("does not clear the platform cache when /ops-centre/snapshot fails", async () => {
    // Populate the platform cache
    await get("/api/ops-centre/platform");
    expect(spawnCount("ops_centre_platform")).toBe(1);

    // Make the snapshot Python call fail
    mockSpawn.mockImplementationOnce((_bin: string, spawnArgs: string[]) => {
      const cmd = spawnArgs[1] ?? "";
      if (cmd === "ops_centre_snapshot") {
        const proc = Object.assign(new EventEmitter(), {
          stdout: new EventEmitter(),
          stderr: new EventEmitter(),
          kill: vi.fn(),
        });
        setImmediate(() => {
          (proc.stderr as EventEmitter).emit("data", Buffer.from("snapshot failed"));
          proc.emit("close", 1);
        });
        return proc;
      }
      return makePyProc(PLATFORM_PAYLOAD);
    });

    const snap = await get("/api/ops-centre/snapshot");
    expect(snap.status).toBe(500);

    // Cache must still be warm — no second platform spawn
    const r = await get("/api/ops-centre/platform");
    expect(r.status).toBe(200);
    expect(spawnCount("ops_centre_platform")).toBe(1);
  });
});
