import express from "express";
import { mkdtemp, mkdir, rm, writeFile } from "node:fs/promises";
import type { Server } from "node:http";
import { tmpdir } from "node:os";
import path from "node:path";
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { mountDashboardSpa } from "./dashboardSpa";

describe("dashboard SPA serving boundary", () => {
  let server: Server;
  let fixtureDir: string;

  beforeAll(async () => {
    fixtureDir = await mkdtemp(path.join(tmpdir(), "apexquant-dashboard-spa-"));
    await mkdir(path.join(fixtureDir, "assets"));
    await writeFile(
      path.join(fixtureDir, "index.html"),
      '<!doctype html><html><body><div id="root">dashboard-spa</div></body></html>',
    );
    await writeFile(path.join(fixtureDir, "assets", "app.js"), "dashboard-asset");

    const app = express();
    app.get("/api/health/details", (_req, res) => {
      res.json({ service_ready: true });
    });
    app.get("/api/kite/login", (_req, res) => {
      res.redirect(302, "https://kite.trade/connect/login?v=3&api_key=redacted");
    });
    mountDashboardSpa(app, fixtureDir);

    await new Promise<void>((resolve) => {
      server = app.listen(0, "127.0.0.1", resolve);
    });
  });

  afterAll(async () => {
    await new Promise<void>((resolve) => server.close(() => resolve()));
    await rm(fixtureDir, { recursive: true, force: true });
  });

  async function request(requestPath: string, redirect: RequestRedirect = "follow") {
    const address = server.address();
    if (!address || typeof address === "string") throw new Error("server not bound");
    return fetch(`http://127.0.0.1:${address.port}${requestPath}`, { redirect });
  }

  it.each(["/trading-dashboard/kite-connect", "/trading-dashboard/dashboard"])(
    "serves the SPA entry for client route %s",
    async (requestPath) => {
      const response = await request(requestPath);
      expect(response.status).toBe(200);
      expect(response.headers.get("content-type")).toContain("text/html");
      expect(await response.text()).toContain("dashboard-spa");
    },
  );

  it("serves dashboard static assets", async () => {
    const response = await request("/trading-dashboard/assets/app.js");
    expect(response.status).toBe(200);
    expect(await response.text()).toBe("dashboard-asset");
  });

  it("does not swallow the health API", async () => {
    const response = await request("/api/health/details");
    expect(response.status).toBe(200);
    expect(response.headers.get("content-type")).toContain("application/json");
    await expect(response.json()).resolves.toEqual({ service_ready: true });
  });

  it("does not swallow the Kite login API or follow its external redirect", async () => {
    const response = await request("/api/kite/login", "manual");
    expect(response.status).toBe(302);
    expect(response.headers.get("location")).toMatch(/^https:\/\/kite\.trade\/connect\/login/);
    expect(response.headers.get("content-type")).not.toContain("text/html; charset=utf-8");
  });

  it("leaves unknown API routes as backend 404 responses", async () => {
    const response = await request("/api/nonexistent-route");
    expect(response.status).toBe(404);
    expect(await response.text()).not.toContain("dashboard-spa");
  });

  it("leaves unknown non-dashboard paths as backend 404 responses", async () => {
    const response = await request("/not-a-dashboard-route");
    expect(response.status).toBe(404);
    expect(await response.text()).not.toContain("dashboard-spa");
  });
});
