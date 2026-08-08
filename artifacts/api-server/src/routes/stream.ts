/**
 * stream.ts — Phase 11 Live Data Foundation
 * Server-Sent Events endpoint + shared market refresh loop.
 *
 * GET  /api/stream            — SSE stream (market.quote / market.status /
 *                               market.health / scan.* / notification.created)
 * POST /api/stream/reconnect  — force an immediate refresh cycle
 * GET  /api/market/status     — market-hours state (Asia/Kolkata)
 * GET  /api/market/quotes     — normalized index/symbol quotes
 *
 * PAPER TRADING ONLY — research system; honest values, nulls never fabricated.
 */
import { Router, type IRouter, type Request, type Response } from "express";
import { spawn } from "child_process";
import path from "path";
import { eventBus, type AppEvent } from "../lib/events";
import { logger } from "../lib/logger";

const router: IRouter = Router();

import { PYTHON_DIR, PYTHON_BIN } from "../lib/python-env";

function runPython(args: string[], timeoutMs = 60_000): Promise<unknown> {
  return new Promise((resolve, reject) => {
    const proc = spawn(PYTHON_BIN, [path.join(PYTHON_DIR, "main.py"), ...args], {
      cwd: PYTHON_DIR,
    });
    let stdout = "";
    let stderr = "";
    const timer = setTimeout(() => {
      proc.kill("SIGKILL");
      reject(new Error(`Python command timed out after ${timeoutMs}ms`));
    }, timeoutMs);
    proc.stdout.on("data", (d: Buffer) => { stdout += d.toString(); });
    proc.stderr.on("data", (d: Buffer) => { stderr += d.toString(); });
    proc.on("close", (code) => {
      clearTimeout(timer);
      if (code !== 0) {
        try {
          const parsed = JSON.parse(stdout.trim());
          if (parsed.error) return reject(new Error(String(parsed.error)));
        } catch { /* fallthrough */ }
        reject(new Error(stderr || `Python exited with code ${code}`));
      } else {
        try { resolve(JSON.parse(stdout.trim())); }
        catch { reject(new Error("Failed to parse Python output")); }
      }
    });
    proc.on("error", reject);
  });
}

// ── Shared refresh loop ──────────────────────────────────────────────────────
// One loop serves all SSE clients; interval adapts to market state.

const OPEN_INTERVAL_MS = 30_000;     // market open: refresh every 30s
const CLOSED_INTERVAL_MS = 300_000;  // closed: every 5 min

interface RefreshState {
  lastQuotes: unknown;
  lastMarket: Record<string, unknown> | null;
  lastRefreshTs: string | null;
  lastError: string | null;
  consecutiveFailures: number;
  refreshCount: number;
  running: boolean;
  timer: NodeJS.Timeout | null;
  wasConnected: boolean | null;
}

export const refreshState: RefreshState = {
  lastQuotes: null,
  lastMarket: null,
  lastRefreshTs: null,
  lastError: null,
  consecutiveFailures: 0,
  refreshCount: 0,
  running: false,
  timer: null,
  wasConnected: null,
};

let clients = 0;

/** Phase 23: lets the pipeline tail poller run only while dashboards listen. */
export function sseClientCount(): number {
  return clients;
}

async function refreshOnce(force = false): Promise<void> {
  if (refreshState.running) return;
  refreshState.running = true;
  try {
    const data = (await runPython([
      "quotes", "NIFTY,BANKNIFTY,INDIAVIX", ...(force ? ["force"] : []),
    ])) as Record<string, unknown>;
    refreshState.lastQuotes = data;
    refreshState.lastMarket = (data["market"] as Record<string, unknown>) ?? null;
    refreshState.lastRefreshTs = new Date().toISOString();
    refreshState.lastError = null;
    refreshState.refreshCount += 1;

    eventBus.publish("market.quote", {
      quotes: data["quotes"],
      market: data["market"],
      provider: data["provider"],
    });
    eventBus.publish("market.status", data["market"]);

    const quotes = (data["quotes"] ?? {}) as Record<string, { ltp?: number | null }>;
    const anyPrice = Object.values(quotes).some((q) => q && q.ltp != null);
    const connected = anyPrice;
    if (refreshState.wasConnected === false && connected) {
      void runPython(["system_event", "DATA_RESTORED", JSON.stringify({
        reason: "Live data provider recovered — quotes flowing again.",
      })]).then((r) => eventBus.publish("notification.created", r)).catch(() => undefined);
    }
    if (refreshState.wasConnected !== false && !connected) {
      void runPython(["system_event", "DATA_DISCONNECTED", JSON.stringify({
        reason: "Live data provider returned no prices for index quotes.",
      })]).then((r) => eventBus.publish("notification.created", r)).catch(() => undefined);
    }
    refreshState.wasConnected = connected;
    refreshState.consecutiveFailures = connected ? 0 : refreshState.consecutiveFailures + 1;
  } catch (err) {
    refreshState.lastError = err instanceof Error ? err.message : String(err);
    refreshState.consecutiveFailures += 1;
    eventBus.publish("market.health", {
      ok: false,
      error: refreshState.lastError,
      consecutive_failures: refreshState.consecutiveFailures,
    });
    if (refreshState.wasConnected !== false) {
      refreshState.wasConnected = false;
      void runPython(["system_event", "DATA_DISCONNECTED", JSON.stringify({
        reason: `Quote refresh failed: ${refreshState.lastError?.slice(0, 200)}`,
      })]).then((r) => eventBus.publish("notification.created", r)).catch(() => undefined);
    }
    logger.warn({ err: refreshState.lastError }, "Live quote refresh failed");
  } finally {
    refreshState.running = false;
  }
}

function scheduleNext(): void {
  const state = (refreshState.lastMarket?.["state"] as string) ?? "CLOSED";
  const interval = state === "OPEN" || state === "PRE_OPEN" ? OPEN_INTERVAL_MS : CLOSED_INTERVAL_MS;
  refreshState.timer = setTimeout(async () => {
    if (clients > 0) await refreshOnce();
    scheduleNext();
  }, interval);
  refreshState.timer.unref?.();
}
scheduleNext();

// ── SSE endpoint ─────────────────────────────────────────────────────────────

const HEARTBEAT_MS = 15_000;
const MAX_SSE_CLIENTS = 20;

router.get("/stream", async (req: Request, res: Response) => {
  if (clients >= MAX_SSE_CLIENTS) {
    res.status(429).json({ error: "Too many concurrent stream connections" });
    return;
  }
  res.setHeader("Content-Type", "text/event-stream");
  res.setHeader("Cache-Control", "no-cache, no-transform");
  res.setHeader("Connection", "keep-alive");
  res.setHeader("X-Accel-Buffering", "no");
  res.flushHeaders?.();

  clients += 1;

  const send = (evt: AppEvent) => {
    res.write(`id: ${evt.id}\nevent: ${evt.event}\ndata: ${JSON.stringify({ ...(typeof evt.data === "object" && evt.data !== null ? evt.data : { value: evt.data }), _ts: evt.ts })}\n\n`);
  };

  // Replay missed events for reconnecting clients.
  const lastEventId = Number(req.headers["last-event-id"] ?? 0);
  if (Number.isFinite(lastEventId) && lastEventId > 0) {
    for (const evt of eventBus.since(lastEventId)) send(evt);
  }

  // Initial snapshot so the client renders immediately.
  if (!refreshState.lastQuotes) await refreshOnce();
  res.write(`event: snapshot\ndata: ${JSON.stringify({
    quotes: refreshState.lastQuotes,
    last_refresh: refreshState.lastRefreshTs,
    last_error: refreshState.lastError,
    label: "PAPER / RESEARCH ONLY",
  })}\n\n`);

  const onEvent = (evt: AppEvent) => send(evt);
  eventBus.on("event", onEvent);

  const heartbeat = setInterval(() => {
    res.write(`: heartbeat ${new Date().toISOString()}\n\n`);
  }, HEARTBEAT_MS);

  req.on("close", () => {
    clients -= 1;
    clearInterval(heartbeat);
    eventBus.off("event", onEvent);
  });
});

// ── Rate-limited reconnect / force refresh ───────────────────────────────────

let lastReconnect = 0;
router.post("/stream/reconnect", async (_req, res) => {
  const now = Date.now();
  if (now - lastReconnect < 5_000) {
    res.status(429).json({ success: false, error: "Reconnect throttled — wait a few seconds." });
    return;
  }
  lastReconnect = now;
  try {
    await refreshOnce(true);
    res.json({
      success: true,
      last_refresh: refreshState.lastRefreshTs,
      last_error: refreshState.lastError,
      label: "PAPER / RESEARCH ONLY",
    });
  } catch (err: unknown) {
    res.status(500).json({ success: false, error: err instanceof Error ? err.message : String(err) });
  }
});

// ── Plain HTTP fallbacks ─────────────────────────────────────────────────────

router.get("/market/status", async (_req, res) => {
  try { res.json(await runPython(["market_status"], 20_000)); }
  catch (err) { res.status(500).json({ success: false, error: err instanceof Error ? err.message : String(err) }); }
});

const SYMBOL_RE = /^[A-Z0-9&.\-]{1,20}$/i;
router.get("/market/quotes", async (req, res) => {
  try {
    const raw = String(req.query.symbols ?? "NIFTY,BANKNIFTY,INDIAVIX");
    const symbols = raw.split(",").map((s) => s.trim()).filter(Boolean).slice(0, 60);
    if (symbols.length === 0 || symbols.some((s) => !SYMBOL_RE.test(s))) {
      res.status(400).json({ success: false, error: "Invalid symbols parameter" });
      return;
    }
    res.json(await runPython(["quotes", symbols.join(",")]));
  } catch (err) {
    res.status(500).json({ success: false, error: err instanceof Error ? err.message : String(err) });
  }
});

export function getStreamStats() {
  return {
    sse_clients: clients,
    refresh_count: refreshState.refreshCount,
    last_refresh: refreshState.lastRefreshTs,
    last_error: refreshState.lastError,
    consecutive_failures: refreshState.consecutiveFailures,
  };
}

export default router;
