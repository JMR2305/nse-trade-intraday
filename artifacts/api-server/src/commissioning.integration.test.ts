import { afterAll, beforeAll, describe, expect, it, vi } from "vitest";
import type { Server } from "node:http";

const {
  spawnMock,
  fullRouterFactory,
  pythonEnvFactory,
  streamFactory,
  dbFactory,
} = vi.hoisted(() => ({
  spawnMock: vi.fn(() => {
    throw new Error("Python subprocess forbidden in commissioning mode");
  }),
  fullRouterFactory: vi.fn(() => {
    throw new Error("full router forbidden in commissioning mode");
  }),
  pythonEnvFactory: vi.fn(() => {
    throw new Error("Python environment forbidden in commissioning mode");
  }),
  streamFactory: vi.fn(() => {
    throw new Error("stream runtime forbidden in commissioning mode");
  }),
  dbFactory: vi.fn(() => {
    throw new Error("database module forbidden in commissioning mode");
  }),
}));

vi.mock("child_process", () => ({ spawn: spawnMock }));
vi.mock("node:child_process", () => ({ spawn: spawnMock }));
vi.mock("./routes/index.js", fullRouterFactory);
vi.mock("./lib/python-env.js", pythonEnvFactory);
vi.mock("./routes/stream.js", streamFactory);
vi.mock("@workspace/db", dbFactory);

async function request(server: Server, path: string) {
  const address = server.address();
  if (!address || typeof address === "string") throw new Error("server not bound");
  const response = await fetch(`http://127.0.0.1:${address.port}${path}`);
  let body: unknown = null;
  try { body = await response.json(); } catch { /* 404 may have a non-JSON body */ }
  return { status: response.status, body };
}

describe("real commissioning app boundary", () => {
  let server: Server;

  beforeAll(async () => {
    vi.stubEnv("HEALTH_ONLY_NO_SCHEDULERS", "true");
    vi.resetModules();
    const { default: app } = await import("./app");
    await new Promise<void>((resolve) => {
      server = app.listen(0, "127.0.0.1", resolve);
    });
  });

  afterAll(async () => {
    vi.unstubAllEnvs();
    await new Promise<void>((resolve) => server.close(() => resolve()));
  });

  it.each(["/api/healthz", "/api/health/live", "/api/health/ready", "/api/health/details"])(
    "exposes only static health route %s without a subprocess",
    async (path) => {
      const result = await request(server, path);
      expect(result.status).toBe(200);
      if (path.endsWith("/ready") || path.endsWith("/details")) {
        expect(result.body).toMatchObject({ commissioning_mode: true });
      }
      expect(spawnMock).not.toHaveBeenCalled();
      expect(fullRouterFactory).not.toHaveBeenCalled();
      expect(pythonEnvFactory).not.toHaveBeenCalled();
      expect(streamFactory).not.toHaveBeenCalled();
      expect(dbFactory).not.toHaveBeenCalled();
    },
  );

  it.each([
    "/",
    "/api/trading/status",
    "/api/portfolio/reset",
    "/api/scan",
    "/api/backtest/scheduler/status",
    "/api/certification/status",
    "/api/universe-management/status",
    "/api/admin/settings",
    "/api/controlled-paper-entry/status",
    "/api/pipeline/events",
  ])("does not mount mutation/runtime route %s", async (path) => {
    expect((await request(server, path)).status).toBe(404);
    expect(spawnMock).not.toHaveBeenCalled();
    expect(fullRouterFactory).not.toHaveBeenCalled();
    expect(pythonEnvFactory).not.toHaveBeenCalled();
    expect(streamFactory).not.toHaveBeenCalled();
    expect(dbFactory).not.toHaveBeenCalled();
  });
});
