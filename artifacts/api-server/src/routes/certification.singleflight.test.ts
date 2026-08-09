/**
 * POST /api/certification/run — single-flight + short-cache regression test.
 *
 * The Phase 23.9 dashboard polls certification endpoints; a full cert run
 * spawns a Python process that is allowed up to 10 minutes. This test proves
 * that concurrent/rapid POSTs can never stack slow Python processes:
 *   1. three concurrent POSTs spawn EXACTLY ONE `cert_run` Python process
 *      and all receive the same report (single-flight);
 *   2. a follow-up POST inside the 10 s result cache also spawns nothing new;
 *   3. GET /certification/validate/:domain single-flights the same way.
 *
 * (Live-verified 2026-08-09: a real full cert_run completes in ~1.5 s — the
 * data validator reads the candle cache only, it never fetches from the
 * network — so the 10 s cache + single-flight comfortably covers polling.)
 */
import { afterAll, beforeAll, describe, expect, it, vi } from "vitest";
import type { Server } from "node:http";
import { EventEmitter } from "node:events";

const CERT_PAYLOAD = {
  ok: true,
  cert_id: "CERT-singleflight",
  verdict: "NOT_READY",
  certification_pct: 67.5,
  domains: {},
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
    // Simulate a slow Python run (long enough that all three concurrent
    // requests are in flight together before it resolves).
    setTimeout(() => {
      proc.stdout.emit("data", JSON.stringify(CERT_PAYLOAD));
      proc.emit("close", 0);
    }, 150);
    return proc;
  }),
}));

const certRunSpawns = () =>
  spawnCalls.filter((args) => args.includes("cert_run")).length;

describe("certification route — single-flight & cache (no process stacking)", () => {
  let server: Server;
  let base: string;

  beforeAll(async () => {
    const { default: app } = await import("../app.js");
    await new Promise<void>((resolve) => {
      server = app.listen(0, "127.0.0.1", () => resolve());
    });
    const addr = server.address() as { port: number };
    base = `http://127.0.0.1:${addr.port}/api`;
  });

  afterAll(() => {
    server?.close();
  });

  it("three concurrent POST /certification/run spawn exactly one python process", async () => {
    const post = () =>
      fetch(`${base}/certification/run`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: "{}",
      });
    const [a, b, c] = await Promise.all([post(), post(), post()]);
    expect(a.status).toBe(200);
    expect(b.status).toBe(200);
    expect(c.status).toBe(200);
    const bodies = await Promise.all([a.json(), b.json(), c.json()]);
    for (const body of bodies as Array<typeof CERT_PAYLOAD>) {
      expect(body.cert_id).toBe("CERT-singleflight");
    }
    expect(certRunSpawns()).toBe(1);
  });

  it("a rapid follow-up POST is served from the result cache (no new spawn)", async () => {
    const res = await fetch(`${base}/certification/run`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: "{}",
    });
    expect(res.status).toBe(200);
    expect(((await res.json()) as typeof CERT_PAYLOAD).cert_id).toBe(
      "CERT-singleflight",
    );
    expect(certRunSpawns()).toBe(1); // still exactly one
  });

  it("concurrent GET /certification/validate/:domain single-flights too", async () => {
    const get = () => fetch(`${base}/certification/validate/portfolio`);
    const results = await Promise.all([get(), get(), get()]);
    for (const r of results) expect(r.status).toBe(200);
    expect(
      spawnCalls.filter((args) => args.includes("cert_validate")).length,
    ).toBe(1);
  });
});
