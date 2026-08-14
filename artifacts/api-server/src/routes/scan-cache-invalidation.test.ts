/**
 * scan-cache-invalidation.test.ts — Task 719
 *
 * Integration tests for the scanStatusCache invalidation behaviour in
 * POST /api/live-data/scan/run.
 *
 * What is verified here that source analysis alone cannot confirm:
 *
 *   1. After GET /live-data/scan/status populates the in-process Node.js
 *      cache, a subsequent GET within the 15-second TTL is served from cache
 *      (zero additional Python spawns).
 *
 *   2. POST /live-data/scan/run immediately nulls the cache on the POST
 *      handler (trading.ts ~line 1320, the "immediate invalidation" path).
 *
 *   3. A status poll that fires WHILE the phase7_scan is still running will
 *      re-populate scanStatusCache with a fresh rotation:1 entry.  This
 *      simulates the real-world race where the scanner UI polls between the
 *      moment the scan is started and the moment it finishes.
 *
 *   4. When the background phase7_scan eventually completes, the COMPLETION
 *      CALLBACK fires (trading.ts ~line 1344, the "deferred invalidation" path)
 *      and clears the re-populated rotation:1 cache entry.  The next GET
 *      /live-data/scan/status then spawns a fresh Python call and returns
 *      rotation:2.  If the completion callback's scanStatusCache = null line
 *      were removed, this test would fail because the stale rotation:1 entry
 *      would persist and be served as the response.
 *
 *   5. POST /live-data/scan/run returns { started: true, status: "RUNNING" }
 *      and is not blocked by the in-flight check (p7InFlight starts null after
 *      resetScanStateForTest()).
 *
 *   6. A rate-limited POST (429) does not clear the cache.
 *
 * Pattern: single real Express server, mocked child_process.spawn (no Python
 * runs).  Cache state is reset in beforeEach via resetScanStateForTest() —
 * mirrors the approach used by platform-cache.test.ts.
 *
 * Mock design:
 *   - scan_status commands: return a makePyProc that closes immediately
 *     (setImmediate), so GET /status requests complete synchronously from the
 *     test's perspective.
 *   - phase7_scan commands: return a CONTROLLABLE proc that does NOT close
 *     until the test calls phase7Trigger(data).  This lets the test issue a
 *     GET /status while the scan is still in-flight (repopulating the cache),
 *     then manually fire completion to test the deferred-invalidation path.
 *   - system_event and any other commands: return makePyProc({}) (fast-close).
 *   Dispatch is by command name (spawnArgs[1]), not by call order, so the test
 *   is robust to side-effect spawns added inside the POST /run handler.
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
const mockSpawn = vi.fn();
vi.mock("node:child_process", () => ({ spawn: mockSpawn }));

// ── Helpers ───────────────────────────────────────────────────────────────────

/**
 * A fake ChildProcess that emits JSON data on stdout then exits 0.
 * setImmediate defers the emit so the caller's promise chain is fully set up.
 */
function makePyProc(jsonData: unknown) {
  const proc = Object.assign(new EventEmitter(), {
    stdout: new EventEmitter(),
    stderr: new EventEmitter(),
    kill: vi.fn(),
  });
  setImmediate(() => {
    (proc.stdout as EventEmitter).emit("data", Buffer.from(JSON.stringify(jsonData)));
    proc.emit("close", 0);
  });
  return proc;
}

/**
 * A fake ChildProcess that does NOT close until trigger(data) is called.
 * Used for phase7_scan so the test controls exactly when the scan "completes".
 *
 * Returns { proc, trigger } where calling trigger(data) emits the data and
 * closes the process, resolving the spawnP7Scan Promise and causing the
 * completion callback (trading.ts ~line 1344) to run.
 */
function makeControllableProc(): { proc: ReturnType<typeof makePyProc>; trigger: (data: unknown) => void } {
  const proc = Object.assign(new EventEmitter(), {
    stdout: new EventEmitter(),
    stderr: new EventEmitter(),
    kill: vi.fn(),
  });
  const trigger = (jsonData: unknown) => {
    (proc.stdout as EventEmitter).emit("data", Buffer.from(JSON.stringify(jsonData)));
    proc.emit("close", 0);
  };
  return { proc: proc as ReturnType<typeof makePyProc>, trigger };
}

/** Extract the Python command name from a mockSpawn call. */
function spawnCmd(callArgs: unknown[]): string {
  return ((callArgs[1] as string[])[1]) ?? "";
}

/** Count how many times mockSpawn was called with a given command name. */
function spawnCount(cmd: string): number {
  return mockSpawn.mock.calls.filter((c) => spawnCmd(c) === cmd).length;
}

// ── Fixture payloads ─────────────────────────────────────────────────────────

function makeScanStatusPayload(rotation: number) {
  return {
    success: true,
    status: "IDLE",
    scan_id: `test-scan-${rotation}`,
    snapshot_ts: new Date().toISOString(),
    age_minutes: 2,
    scan_count_today: rotation,
    cadence_minutes: 4,
    rotation,
    latest_scan: {
      scan_id: `test-scan-${rotation}`,
      status: "completed",
      symbols_total: 50,
      symbols_done: 50,
      duration_s: 90,
    },
    progress: null,
  };
}

function makeScanResult() {
  return {
    scan_id: "test-phase7-scan",
    snapshot_ts: new Date().toISOString(),
    signals: [],
    ai_decisions: [],
    summary: { total: 0, buy: 0, hold: 0, avoid: 0 },
  };
}

// ── Stateful spawn dispatcher ─────────────────────────────────────────────────
//
// currentStatusRotation: what scan_status returns; advanced by each test.
// currentPhase7Trigger:  populated when phase7_scan is spawned; the test calls
//                        it to simulate scan completion at the right moment.

let currentStatusRotation = 1;
let currentPhase7Trigger: ((data: unknown) => void) | null = null;

function makeSpawnImpl() {
  return (_bin: string, spawnArgs: string[]) => {
    const cmd = (spawnArgs as string[])[1] ?? "";
    if (cmd === "phase7_scan") {
      const { proc, trigger } = makeControllableProc();
      currentPhase7Trigger = trigger;
      return proc;
    }
    if (cmd === "scan_status") {
      return makePyProc(makeScanStatusPayload(currentStatusRotation));
    }
    // system_event and any other side-effect commands: fast-close.
    return makePyProc({});
  };
}

// ── Server setup ─────────────────────────────────────────────────────────────

describe("scan/status cache invalidation — POST /live-data/scan/run", () => {
  let server: Server;
  let port: number;
  let resetScanStateForTest: () => void;

  async function get(path: string): Promise<{ status: number; body: unknown }> {
    const res = await fetch(`http://127.0.0.1:${port}${path}`);
    const body = await res.json().catch(() => null);
    return { status: res.status, body };
  }

  async function post(path: string, body = "{}"): Promise<{ status: number; body: unknown }> {
    const res = await fetch(`http://127.0.0.1:${port}${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body,
    });
    const responseBody = await res.json().catch(() => null);
    return { status: res.status, body: responseBody };
  }

  /**
   * Allow pending microtasks and one round of setImmediates to settle.
   * Used after phase7Trigger() to let the completion callback run before
   * issuing the next GET /status.
   */
  async function flushAsync(): Promise<void> {
    await Promise.resolve();           // let .then() microtasks run
    await new Promise<void>((r) => setImmediate(r)); // let setImmediate queue drain once
  }

  beforeAll(async () => {
    mockSpawn.mockImplementation(makeSpawnImpl());

    const [{ default: app }, routesMod] = await Promise.all([
      import("../app.js"),
      import("./trading.js"),
    ]);
    resetScanStateForTest = routesMod.resetScanStateForTest;

    await new Promise<void>((resolve) => {
      server = app.listen(0, "127.0.0.1", () => resolve());
    });
    port = (server.address() as { port: number }).port;
  });

  afterAll(() => { server?.close(); });

  beforeEach(() => {
    // Clear all scan-related module state between tests.
    // resetScanStateForTest() also nulls p7InFlight, so a previous test's
    // phase7_scan proc (never triggered) does not block the next POST /run.
    resetScanStateForTest();
    currentStatusRotation = 1;
    currentPhase7Trigger = null;
    mockSpawn.mockClear();
    mockSpawn.mockImplementation(makeSpawnImpl());
  });

  // ── 1. Cache hit ───────────────────────────────────────────────────────────

  it("serves a second GET /live-data/scan/status from cache without spawning Python again", async () => {
    const r1 = await get("/api/live-data/scan/status");
    expect(r1.status).toBe(200);
    expect((r1.body as Record<string, unknown>)["rotation"]).toBe(1);
    expect(spawnCount("scan_status")).toBe(1);

    // Second request within the 15 s TTL — cache hit, no new spawn.
    const r2 = await get("/api/live-data/scan/status");
    expect(r2.status).toBe(200);
    expect((r2.body as Record<string, unknown>)["rotation"]).toBe(1);
    expect(spawnCount("scan_status")).toBe(1); // still 1
  });

  // ── 2. Immediate invalidation (POST /run handler, ~line 1320) ─────────────

  it("POST /live-data/scan/run immediately clears the cache so the very next GET fetches fresh data", async () => {
    // Populate cache with rotation:1.
    await get("/api/live-data/scan/status");
    expect(spawnCount("scan_status")).toBe(1);

    // Verify cache hit.
    await get("/api/live-data/scan/status");
    expect(spawnCount("scan_status")).toBe(1);

    // POST /run → cache cleared synchronously inside the handler.
    const r2 = await post("/api/live-data/scan/run");
    expect(r2.status).toBe(200);
    expect((r2.body as Record<string, unknown>)["started"]).toBe(true);
    expect((r2.body as Record<string, unknown>)["status"]).toBe("RUNNING");
    expect(spawnCount("phase7_scan")).toBe(1);

    // Advance rotation to distinguish fresh vs cached.
    currentStatusRotation = 2;

    // GET after POST — must be a cache miss (immediate invalidation).
    const r3 = await get("/api/live-data/scan/status");
    expect(r3.status).toBe(200);
    expect((r3.body as Record<string, unknown>)["rotation"]).toBe(2);
    expect(spawnCount("scan_status")).toBe(2); // one before POST, one after
  });

  // ── 3. Deferred invalidation (completion callback, ~line 1344) ────────────
  //
  // This is the CRITICAL regression scenario: a status poll fires WHILE the
  // phase7_scan is still in-flight, re-populating the cache with rotation:1.
  // The completion callback MUST clear that re-populated entry so the next poll
  // returns rotation:2 from a fresh Python call.
  //
  // If the `scanStatusCache = null` line inside the completion callback
  // (trading.ts ~line 1344) were removed, this test would fail: step 6 would
  // return the stale cached rotation:1 instead of the fresh rotation:2.

  it("completion callback clears the re-populated cache so the next GET after scan completion fetches fresh data", async () => {
    // Step 1: Populate cache with rotation:1.
    const r1 = await get("/api/live-data/scan/status");
    expect((r1.body as Record<string, unknown>)["rotation"]).toBe(1);
    expect(spawnCount("scan_status")).toBe(1);

    // Step 2: POST /run — this immediately clears the cache AND starts
    //         phase7_scan (which is a controllable proc — it does NOT complete
    //         until we manually call currentPhase7Trigger below).
    const rPost = await post("/api/live-data/scan/run");
    expect(rPost.status).toBe(200);
    expect((rPost.body as Record<string, unknown>)["status"]).toBe("RUNNING");
    expect(currentPhase7Trigger).not.toBeNull(); // proc was captured

    // Step 3: GET /status while phase7_scan is STILL IN-FLIGHT.
    //         scanStatusCache is null (cleared by POST), so this triggers a new
    //         Python scan_status call and RE-POPULATES the cache with rotation:1.
    const rMidScan = await get("/api/live-data/scan/status");
    expect((rMidScan.body as Record<string, unknown>)["rotation"]).toBe(1);
    // Two scan_status spawns so far (before POST + during scan).
    expect(spawnCount("scan_status")).toBe(2);

    // Step 4: Advance the rotation counter — the next scan_status Python call
    //         (which will happen only if the completion callback clears the cache)
    //         should return rotation:2.
    currentStatusRotation = 2;

    // Step 5: Trigger phase7_scan completion.
    //         This resolves the getP7Scan Promise.  The .then() callback
    //         (trading.ts ~line 1344) fires as a microtask and sets:
    //           scanStatusGen++
    //           scanStatusCache = null   ← the line this test validates
    //           scanStatusInFlight = null
    //         Then a fire-and-forget system_event SCAN_COMPLETED is spawned.
    currentPhase7Trigger!(makeScanResult());

    // Let microtasks run (completion callback) then let the system_event
    // setImmediate drain — both are harmless side effects of the callback.
    await flushAsync();
    await flushAsync();

    // Step 6: GET /status — scanStatusCache must be null (cleared by the
    //         completion callback) so a THIRD Python scan_status call fires and
    //         returns rotation:2.
    //
    //         WITHOUT the completion callback's cache-clear, this would return
    //         the rotation:1 entry that was cached in step 3 — a silent stale-
    //         cache bug that this test exists to catch.
    const r2 = await get("/api/live-data/scan/status");
    expect(r2.status).toBe(200);
    expect((r2.body as Record<string, unknown>)["rotation"]).toBe(2);
    expect(spawnCount("scan_status")).toBe(3); // before POST, during scan, after completion
  });

  // ── 4. scan_count_today increments after completion ────────────────────────

  it("scan_count_today increments in the fresh response after scan completion", async () => {
    currentStatusRotation = 3;
    await get("/api/live-data/scan/status");

    await post("/api/live-data/scan/run");
    // Re-populate cache mid-scan.
    await get("/api/live-data/scan/status");
    expect((await get("/api/live-data/scan/status")).body).toMatchObject({ scan_count_today: 3 });

    currentStatusRotation = 4;
    currentPhase7Trigger!(makeScanResult());
    await flushAsync();
    await flushAsync();

    const r = await get("/api/live-data/scan/status");
    expect((r.body as Record<string, unknown>)["scan_count_today"]).toBe(4);
  });

  // ── 5. Rate-limited POST does not corrupt the cache ───────────────────────

  it("a rate-limited POST /run (429) does not clear the cache", async () => {
    currentStatusRotation = 5;
    await get("/api/live-data/scan/status");

    // First POST → RUNNING, cache cleared.
    await post("/api/live-data/scan/run");

    // Re-populate cache with rotation:6.
    currentStatusRotation = 6;
    const rFresh = await get("/api/live-data/scan/status");
    expect((rFresh.body as Record<string, unknown>)["rotation"]).toBe(6);
    const spawnsBeforeRateLimit = spawnCount("scan_status");

    // Second POST immediately — rate-limited (30-second gap not elapsed).
    const r429 = await post("/api/live-data/scan/run");
    expect(r429.status).toBe(429);
    expect((r429.body as Record<string, unknown>)["status"]).toBe("RATE_LIMITED");

    // Cache must still hold rotation:6 — rate-limited POST must NOT clear it.
    // Sentinel rotation so any unexpected Python call would be detectable.
    currentStatusRotation = 999;
    const rAfter429 = await get("/api/live-data/scan/status");
    expect(rAfter429.status).toBe(200);
    expect((rAfter429.body as Record<string, unknown>)["rotation"]).toBe(6); // cached
    expect(spawnCount("scan_status")).toBe(spawnsBeforeRateLimit); // no extra spawn
  });
});
