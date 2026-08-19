/**
 * Agent Framework status reload resilience.
 *
 * The agent list is fetched by multiple Mission Control widgets on page load.
 * A transient Python startup failure must return a recoverable JSON payload,
 * not a 500 that leaves both widgets blank.
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
vi.mock("child_process", () => ({ spawn: mockSpawn }));

function makePythonProcess(payload: unknown, code = 0, stderr = "") {
  const proc = Object.assign(new EventEmitter(), {
    stdout: new EventEmitter(),
    stderr: new EventEmitter(),
    kill: vi.fn(),
  });
  setImmediate(() => {
    if (payload !== undefined) {
      (proc.stdout as EventEmitter).emit("data", Buffer.from(JSON.stringify(payload)));
    }
    if (stderr) {
      (proc.stderr as EventEmitter).emit("data", Buffer.from(stderr));
    }
    proc.emit("close", code);
  });
  return proc;
}

describe("Agent Framework status reload resilience", () => {
  let server: Server;
  let port: number;
  let resetAgentListCacheForTest: () => void;
  let expireAgentListCacheForTest: () => void;

  async function getAgents(): Promise<{ status: number; body: Record<string, unknown> }> {
    const response = await fetch(`http://127.0.0.1:${port}/api/agent-framework/agents`);
    return {
      status: response.status,
      body: await response.json() as Record<string, unknown>,
    };
  }

  beforeAll(async () => {
    const [{ default: app }, route] = await Promise.all([
      import("../app.js"),
      import("./agentFramework.js"),
    ]);
    resetAgentListCacheForTest = route.resetAgentListCacheForTest;
    expireAgentListCacheForTest = route.expireAgentListCacheForTest;
    await new Promise<void>((resolve) => {
      server = app.listen(0, "127.0.0.1", resolve);
    });
    port = (server.address() as { port: number }).port;
  });

  afterAll(() => server?.close());

  beforeEach(() => {
    resetAgentListCacheForTest();
    mockSpawn.mockClear();
  });

  it("returns a recoverable status instead of HTTP 500 when agents are still initialising", async () => {
    // main.py catches command exceptions, emits JSON to stdout, and exits 1.
    // The route must reject this error-shaped payload rather than cache it.
    mockSpawn.mockImplementation(() => makePythonProcess({
      error: "agent startup failed",
      trace: "initialisation traceback",
    }, 1));

    const response = await getAgents();

    expect(response.status).toBe(200);
    expect(response.body).toMatchObject({
      available: false,
      status: "UNAVAILABLE",
      recoverable: true,
      agents: [],
    });
    expect(response.body.message).toMatch(/initialising.*retrying automatically/i);
  });

  it("keeps the last known agent rows visible when a later JSON error occurs", async () => {
    const payload = {
      available: true,
      agents: [{ agent_id: "risk", name: "Risk Agent", state: "RUNNING" }],
      count: 1,
    };
    mockSpawn.mockImplementationOnce(() => makePythonProcess(payload));
    await getAgents();
    expireAgentListCacheForTest();

    mockSpawn.mockImplementationOnce(() => makePythonProcess({
      error: "agent refresh failed",
      trace: "refresh traceback",
    }, 1));
    const response = await getAgents();

    expect(response.status).toBe(200);
    expect(response.body).toMatchObject({
      available: true,
      status: "DEGRADED",
      recoverable: true,
      stale: true,
      agents: payload.agents,
    });
    expect(response.body.message).toMatch(/last known agent state.*retrying automatically/i);
    expect(mockSpawn).toHaveBeenCalledTimes(2);
  });

  it("coalesces the concurrent agent status requests made during a Mission Control reload", async () => {
    const payload = {
      available: true,
      agents: [{ agent_id: "risk", name: "Risk Agent", state: "RUNNING" }],
      count: 1,
    };
    mockSpawn.mockImplementation(() => makePythonProcess(payload));

    const [first, second] = await Promise.all([getAgents(), getAgents()]);

    expect(first.status).toBe(200);
    expect(second.status).toBe(200);
    expect(first.body).toEqual(payload);
    expect(second.body).toEqual(payload);
    expect(mockSpawn).toHaveBeenCalledTimes(1);
  });
});