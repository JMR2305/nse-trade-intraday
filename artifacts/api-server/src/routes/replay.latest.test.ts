/**
 * /api/replay/sessions/latest — integration test (Phase 25A).
 *
 * Mission Control's Live AI Pipeline panel depends on this route for the
 * canonical unified in/out/rejected/pending/cancelled stage counts. This
 * test spins up the real Express app (Python spawn mocked) and proves:
 *   1. the explicit /replay/sessions/latest route exists and returns 200;
 *   2. the payload carries the canonical per-stage count fields;
 *   3. the Python engine is invoked as `replay_build latest`.
 */
import { afterAll, beforeAll, describe, expect, it, vi } from "vitest";
import type { Server } from "node:http";
import { EventEmitter } from "node:events";

// Canonical replay payload subset (mirrors replay_engine.build_replay()).
const REPLAY_PAYLOAD = {
  replay_id: "RP-test",
  scan_id: "abc123",
  snapshot_ts: "2026-08-08T09:35:00Z",
  stages: [
    {
      id: "supervisor", label: "Supervisor", order: 0,
      stocks_in: 50, stocks_out: 50, rejected: 0, pending: 0, cancelled: 0,
      duration_ms: 120, status: "COMPLETED",
    },
    {
      id: "execution", label: "Execution", order: 8,
      stocks_in: 5, stocks_out: 0, rejected: 0, pending: 0, cancelled: 5,
      duration_ms: 300, status: "COMPLETED",
    },
  ],
};

const spawnCalls: string[][] = [];

vi.mock("node:child_process", () => ({
  spawn: vi.fn((_cmd: string, args: string[]) => {
    spawnCalls.push(args);
    const proc = new EventEmitter() as EventEmitter & {
      stdout: EventEmitter; stderr: EventEmitter; kill: () => void;
    };
    proc.stdout = new EventEmitter();
    proc.stderr = new EventEmitter();
    proc.kill = () => {};
    // Emit the payload asynchronously, then exit 0.
    setImmediate(() => {
      proc.stdout.emit("data", JSON.stringify(REPLAY_PAYLOAD));
      proc.emit("close", 0);
    });
    return proc;
  }),
}));

describe("GET /api/replay/sessions/latest (Mission Control canonical counts)", () => {
  let server: Server;

  beforeAll(async () => {
    const { default: app } = await import("../app.js");
    await new Promise<void>((resolve) => {
      server = app.listen(0, "127.0.0.1", () => resolve());
    });
  });

  afterAll(() => {
    server?.close();
  });

  it("returns 200 with per-stage in/out/rejected/pending/cancelled counts", async () => {
    const addr = server.address() as { port: number };
    const res = await fetch(`http://127.0.0.1:${addr.port}/api/replay/sessions/latest`);
    expect(res.status).toBe(200);
    const body = (await res.json()) as typeof REPLAY_PAYLOAD;
    expect(body.scan_id).toBe("abc123");
    expect(Array.isArray(body.stages)).toBe(true);
    for (const stage of body.stages) {
      expect(stage).toHaveProperty("stocks_in");
      expect(stage).toHaveProperty("stocks_out");
      expect(stage).toHaveProperty("rejected");
      expect(stage).toHaveProperty("pending");
      expect(stage).toHaveProperty("cancelled");
      expect(stage).toHaveProperty("duration_ms");
      expect(stage).toHaveProperty("label");
    }
    // The engine must be asked for the resolved-latest replay build.
    expect(
      spawnCalls.some((args) => args.includes("replay_build") && args.includes("latest")),
    ).toBe(true);
  });
});
