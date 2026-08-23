import express from "express";
import type { Server } from "node:http";
import { EventEmitter } from "node:events";
import { afterAll, afterEach, beforeAll, describe, expect, it, vi } from "vitest";

const { spawnMock } = vi.hoisted(() => ({ spawnMock: vi.fn() }));
vi.mock("child_process", () => ({ spawn: spawnMock }));
vi.mock("node:child_process", () => ({ spawn: spawnMock }));

import kiteRouter from "./kite";

function pythonResult(payload: Record<string, unknown>) {
  return () => {
    const proc = new EventEmitter() as EventEmitter & {
      stdout: EventEmitter;
      stderr: EventEmitter;
      kill: ReturnType<typeof vi.fn>;
    };
    proc.stdout = new EventEmitter();
    proc.stderr = new EventEmitter();
    proc.kill = vi.fn();
    setImmediate(() => {
      proc.stdout.emit("data", Buffer.from(JSON.stringify(payload)));
      proc.emit("close", 0);
    });
    return proc;
  };
}

async function request(
  server: Server,
  path: string,
  init?: RequestInit,
) {
  const address = server.address();
  if (!address || typeof address === "string") throw new Error("Server not bound");
  return fetch(`http://127.0.0.1:${address.port}${path}`, {
    ...init,
    redirect: "manual",
  });
}

describe("Kite callback durability contract", () => {
  let server: Server;

  beforeAll(async () => {
    const app = express();
    app.use(kiteRouter);
    server = await new Promise<Server>((resolve) => {
      const instance = app.listen(0, () => resolve(instance));
    });
  });

  afterAll(async () => {
    await new Promise<void>((resolve, reject) => {
      server.close((error) => error ? reject(error) : resolve());
    });
  });

  afterEach(() => {
    spawnMock.mockReset();
  });

  it("redirects to a safe failure state when Python rejects durable session save", async () => {
    spawnMock.mockImplementation(pythonResult({ success: false, state: "AUTH_FAILED" }));

    const response = await request(
      server,
      "/kite/callback?status=success&request_token=validToken123",
    );

    expect(response.status).toBe(302);
    expect(response.headers.get("location")).toBe(
      "/trading-dashboard/kite-connect?auth=failed&reason=exchange_failed",
    );
  });

  it("redirects to success only after Python confirms the exchange", async () => {
    spawnMock.mockImplementation(pythonResult({ success: true, state: "CONNECTED" }));

    const response = await request(
      server,
      "/kite/callback?status=success&request_token=validToken123",
    );

    expect(response.status).toBe(302);
    expect(response.headers.get("location")).toBe(
      "/trading-dashboard/kite-connect?auth=success",
    );
  });

  it("returns a failure status when shared-session deletion is not confirmed", async () => {
    spawnMock.mockImplementation(pythonResult({
      success: false,
      state: "DISCONNECT_FAILED",
      error: "Could not disconnect the Kite session safely. Please try again.",
    }));

    const response = await request(server, "/kite/disconnect", { method: "POST" });

    expect(response.status).toBe(503);
    await expect(response.json()).resolves.toMatchObject({
      success: false,
      state: "DISCONNECT_FAILED",
    });
  });
});