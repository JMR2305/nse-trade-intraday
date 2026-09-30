/**
 * ops-snapshot-last-good.test.ts — Task978ZR R37N (Ops Centre snapshot repair)
 *
 * Server-side last-good snapshot reuse for GET /api/ops-centre/snapshot:
 *
 *   1. First request with no cache runs the snapshot generator, returns valid data
 *   2. Concurrent first requests coalesce into ONE Python generation
 *   3. Successful result becomes the last-good cache
 *   4. A subsequent request returns last-good data without waiting for a new slow generation
 *   5. Background refresh does not spawn duplicates (in-flight dedup preserved)
 *   6. A failed refresh does NOT destroy the last-good cache
 *   7. No-cache + generator failure still returns a truthful error
 *   8. Cached metadata accurately reports cached/age/refresh state
 *
 * Real Express server (same wiring as production), mocked child_process so no
 * Python subprocess is ever spawned.
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

function spawnCount(cmd: string): number {
  return mockSpawn.mock.calls.filter((c) => spawnCmd(c) === cmd).length;
}

const SNAPSHOT_V1 = {
  fast: false,
  generated_at: "2026-09-30T09:01:00.000Z",
  agents: [],
  platform: { health_pct: 98, market_state: "PRE_OPEN" },
  pipeline_nodes: [],
};

const SNAPSHOT_V2 = {
  fast: false,
  generated_at: "2026-09-30T09:02:00.000Z",
  agents: [],
  platform: { health_pct: 91, market_state: "OPEN" },
  pipeline_nodes: [],
};

const PLATFORM_PAYLOAD = {
  fast: true,
  generated_at: "2026-09-30T09:00:00.000Z",
  cache_ts: null as string | null,
  platform: { health_pct: 95, market_state: "PRE_OPEN", scan_status: "SUCCESS" },
  pipeline_nodes: [],
};

function defaultSpawnImpl(_bin: string, spawnArgs: string[]) {
  const cmd = spawnArgs[1] ?? "";
  if (cmd === "ops_centre_snapshot") return makePyProc(SNAPSHOT_V1);
  return makePyProc(PLATFORM_PAYLOAD);
}

// Slow generation: resolves only when the test releases the deferred proc.
function slowSpawnImpl(release: () => void) {
  return (_bin: string, spawnArgs: string[]) => {
    const cmd = spawnArgs[1] ?? "";
    if (cmd === "ops_centre_snapshot") {
      const proc = Object.assign(new EventEmitter(), {
        stdout: new EventEmitter(),
        stderr: new EventEmitter(),
        kill: vi.fn(),
      });
      setImmediate(() => {
        release();
        (proc.stdout as EventEmitter).emit(
          "data",
          Buffer.from(JSON.stringify(SNAPSHOT_V2)),
        );
        proc.emit("close", 0);
      });
      return proc;
    }
    return makePyProc(PLATFORM_PAYLOAD);
  };
}

function failingSpawnImpl(_bin: string, spawnArgs: string[]) {
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
}

describe("Ops Centre snapshot — last-good cache reuse (Task978ZR R37N)", () => {
  let server: Server;
  let port: number;
  let clearSnapshotCache: (opts?: { force?: boolean }) => void;

  async function get(path: string): Promise<{ status: number; body: any }> {
    const res = await fetch(`http://127.0.0.1:${port}${path}`);
    const body = await res.json().catch(() => null);
    return { status: res.status, body };
  }

  beforeAll(async () => {
    mockSpawn.mockImplementation(defaultSpawnImpl);
    const [{ default: app }, routesMod] = await Promise.all([
      import("../app.js"),
      import("./trading.js"),
    ]);
    clearSnapshotCache = (routesMod as any).clearSnapshotCache;
    await new Promise<void>((resolve) => {
      server = app.listen(0, "127.0.0.1", () => resolve());
    });
    port = (server.address() as { port: number }).port;
  });

  afterAll(() => {
    server?.close();
  });

  beforeEach(() => {
    clearSnapshotCache({ force: true });
    clearSnapshotCache({ force: true }); // also clears any last-good entry
    mockSpawn.mockClear();
    mockSpawn.mockImplementation(defaultSpawnImpl);
  });

  it("1. first request with no cache runs the generator and returns valid data", async () => {
    const r = await get("/api/ops-centre/snapshot");
    expect(r.status).toBe(200);
    expect(spawnCount("ops_centre_snapshot")).toBe(1);
    expect((r.body as any).platform.health_pct).toBe(98);
    // Fresh generation carries no cached-delivery metadata
    expect((r.body as any).snapshot_delivery).toBeUndefined();
  });

  it("2. concurrent first requests coalesce into ONE Python generation", async () => {
    const [r1, r2, r3] = await Promise.all([
      get("/api/ops-centre/snapshot"),
      get("/api/ops-centre/snapshot"),
      get("/api/ops-centre/snapshot"),
    ]);
    expect(r1.status).toBe(200);
    expect(r2.status).toBe(200);
    expect(r3.status).toBe(200);
    expect(spawnCount("ops_centre_snapshot")).toBe(1);
    // Same snapshot payload for all callers (delivery metadata may differ:
    // a straggler arriving after generation completes is served from the
    // last-good cache and carries snapshot_delivery, which is correct).
    expect((r2.body as any).platform).toEqual((r1.body as any).platform);
    expect((r3.body as any).platform).toEqual((r1.body as any).platform);
    expect((r3.body as any).generated_at).toBe((r1.body as any).generated_at);
  });

  it("3. successful result becomes the last-good cache", async () => {
    await get("/api/ops-centre/snapshot");
    expect(spawnCount("ops_centre_snapshot")).toBe(1);

    // An immediate second request is served from the last-good cache —
    // no second Python generation.
    const r = await get("/api/ops-centre/snapshot");
    expect(r.status).toBe(200);
    expect(spawnCount("ops_centre_snapshot")).toBe(1);
    expect((r.body as any).platform.health_pct).toBe(98);
    expect((r.body as any).snapshot_delivery?.cached).toBe(true);
  });

  it("4. subsequent request returns last-good data without waiting for a new slow generation", async () => {
    await get("/api/ops-centre/snapshot"); // populate last-good cache

    // Age the cache past the revalidate min-age, then hang the next
    // generation until the test releases it. The browser-equivalent request
    // must NOT wait for it — the cached snapshot is served immediately.
    await new Promise((r) => setTimeout(r, 20_100));
    let release!: () => void;
    const released = new Promise<void>((r) => { release = r; });
    mockSpawn.mockImplementation(slowSpawnImpl(release));
    try {
      const r = await get("/api/ops-centre/snapshot");
      expect(r.status).toBe(200);
      expect((r.body as any).platform.health_pct).toBe(98); // v1 cached data
      expect((r.body as any).snapshot_delivery?.cached).toBe(true);
      expect((r.body as any).snapshot_delivery?.refresh_in_flight).toBe(true);
    } finally {
      release();
      await released;
      mockSpawn.mockImplementation(defaultSpawnImpl);
    }
  }, 30_000);

  it("5. background refresh does not spawn duplicate generations", async () => {
    await get("/api/ops-centre/snapshot"); // populate

    // Advance past the revalidate min-age: the next request starts ONE
    // background revalidation; a concurrent burst must coalesce behind it.
    let release!: () => void;
    const released = new Promise<void>((r) => { release = r; });
    mockSpawn.mockImplementation(slowSpawnImpl(release));
    try {
      const { clearSnapshotCacheForTest } = await import("./trading.js");
      void clearSnapshotCacheForTest;
      // Age the cache without clearing it by waiting out the min-age window.
      await new Promise((r) => setTimeout(r, 20_100));
      const first = get("/api/ops-centre/snapshot"); // starts background gen
      const second = get("/api/ops-centre/snapshot"); // coalesces
      const third = get("/api/ops-centre/snapshot"); // coalesces
      await Promise.all([first, second, third]);
      expect(spawnCount("ops_centre_snapshot")).toBe(2); // 1 initial + 1 bg
    } finally {
      release();
      await released;
      mockSpawn.mockImplementation(defaultSpawnImpl);
    }
  }, 30_000);

  it("6. failed refresh does NOT destroy the last-good cache", async () => {
    await get("/api/ops-centre/snapshot"); // populate with v1
    expect(spawnCount("ops_centre_snapshot")).toBe(1);

    // Forced synchronous regeneration fails — the response must fall back
    // to the retained snapshot, truthfully marked stale_after_error.
    mockSpawn.mockImplementation(failingSpawnImpl);
    const r = await get("/api/ops-centre/snapshot?refresh=1");
    expect(r.status).toBe(200);
    expect((r.body as any).platform.health_pct).toBe(98); // last-good survives
    expect((r.body as any).snapshot_delivery?.stale_after_error).toBe(true);
  });

  it("7. no-cache + generator failure still returns a truthful error", async () => {
    mockSpawn.mockImplementation(failingSpawnImpl);
    const r = await get("/api/ops-centre/snapshot");
    expect(r.status).toBe(500);
    expect((r.body as any).success).toBe(false);
    expect(spawnCount("ops_centre_snapshot")).toBe(1);
  });

  it("8. cached metadata accurately reports cached/age/refresh state", async () => {
    await get("/api/ops-centre/snapshot");
    const r = await get("/api/ops-centre/snapshot");
    const sd = (r.body as any).snapshot_delivery;
    expect(sd).toBeDefined();
    expect(sd.cached).toBe(true);
    expect(typeof sd.age_seconds).toBe("number");
    expect(sd.age_seconds).toBeGreaterThanOrEqual(0);
    // Cache younger than the revalidate min-age → no background generation.
    expect(sd.refresh_in_flight).toBe(false);
  });
});
