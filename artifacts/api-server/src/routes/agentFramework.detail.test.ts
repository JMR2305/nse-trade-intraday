/**
 * Agent Framework detail recovery.
 *
 * A canonical agent can be listed before the per-request supervisor registry
 * has initialised. Detail callers must receive an actionable retry state rather
 * than a generic server failure.
 */
import { afterAll, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import type { Server } from "node:http";
import { EventEmitter } from "node:events";

const mockSpawn = vi.fn();
vi.mock("child_process", () => ({ spawn: mockSpawn }));

function makePythonProcess(payload: unknown, code = 0) {
  const proc = Object.assign(new EventEmitter(), {
    stdout: new EventEmitter(),
    stderr: new EventEmitter(),
    kill: vi.fn(),
  });
  setImmediate(() => {
    if (payload !== undefined) {
      proc.stdout.emit("data", Buffer.from(JSON.stringify(payload)));
    }
    proc.emit("close", code);
  });
  return proc;
}

describe("Agent Framework detail recovery", () => {
  let server: Server;
  let port: number;
  let resetAgentListCacheForTest: () => void;

  async function getDetail(agentId: string): Promise<{
    status: number;
    body: Record<string, unknown>;
  }> {
    const response = await fetch(
      `http://127.0.0.1:${port}/api/agent-framework/agents/${agentId}`,
    );
    return { status: response.status, body: await response.json() as Record<string, unknown> };
  }

  beforeAll(async () => {
    const [{ default: app }, route] = await Promise.all([
      import("../app.js"),
      import("./agentFramework.js"),
    ]);
    resetAgentListCacheForTest = route.resetAgentListCacheForTest;
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

  it("returns the current detail when the agent is ready", async () => {
    const detail = {
      available: true,
      agent_id: "risk",
      name: "Risk Agent",
      state: "RUNNING",
    };
    mockSpawn.mockImplementation(() => makePythonProcess(detail));

    const response = await getDetail("risk");

    expect(response.status).toBe(200);
    expect(response.body).toEqual(detail);
  });

  it("returns a recoverable status when the agent has not initialised", async () => {
    mockSpawn.mockImplementation(() => makePythonProcess({
      error: "Agent 'risk' not found",
    }, 1));

    const response = await getDetail("risk");

    expect(response.status).toBe(200);
    expect(response.body).toMatchObject({
      available: false,
      agent_id: "risk",
      status: "INITIALIZING",
      recoverable: true,
    });
    expect(response.body.message).toMatch(/initialising.*retrying automatically/i);
  });

  it("converts subprocess failures into a recoverable detail response", async () => {
    mockSpawn.mockImplementation(() => makePythonProcess(undefined));

    const response = await getDetail("risk");

    expect(response.status).toBe(200);
    expect(response.body).toMatchObject({
      available: false,
      agent_id: "risk",
      status: "INITIALIZING",
      recoverable: true,
    });
  });
});