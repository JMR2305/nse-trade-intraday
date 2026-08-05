import { Router, type IRouter, type Request, type Response } from "express";
import { db, pushSubscriptionsTable, alertDeliveriesTable } from "@workspace/db";
import { and, desc, eq, gte, ilike, lte, max, sql, count } from "drizzle-orm";
import { isValidExpoPushToken, ensurePushSubscriptionsTable } from "../lib/pushNotifier";
import { ensureAlertDeliveriesTable, truncateDestination } from "../lib/alertQueue";
import { logger } from "../lib/logger";

// Push notification subscriptions for the mobile app.
// Register/update/inspect a device's Expo push token and its personal
// minimum-confidence threshold. Advisory alerts only — never trades.

const router: IRouter = Router();

function parseMinConfidence(value: unknown): number | null {
  if (value === undefined || value === null) return null;
  const n = Number(value);
  if (!Number.isFinite(n) || n < 0 || n > 100) return null;
  return n;
}

function parseMinHealthPct(value: unknown): number | null {
  if (value === undefined || value === null) return null;
  const n = Number(value);
  if (!Number.isFinite(n) || n < 50 || n > 90) return null;
  return n;
}

// Register (or re-register) a device token.
router.post("/notifications/push/register", async (req: Request, res: Response) => {
  try {
    const { token, minConfidence, minHealthPct } = (req.body ?? {}) as Record<string, unknown>;
    if (!isValidExpoPushToken(token)) {
      res.status(400).json({ error: "A valid Expo push token is required" });
      return;
    }
    const min = parseMinConfidence(minConfidence);
    if (minConfidence !== undefined && min === null) {
      res.status(400).json({ error: "minConfidence must be a number between 0 and 100" });
      return;
    }
    const minHp = parseMinHealthPct(minHealthPct);
    if (minHealthPct !== undefined && minHp === null) {
      res.status(400).json({ error: "minHealthPct must be a number between 50 and 90" });
      return;
    }
    await ensurePushSubscriptionsTable();
    await db
      .insert(pushSubscriptionsTable)
      .values({
        token,
        minConfidence: min ?? 70,
        minHealthPct: minHp ?? 70,
        enabled: true,
        updatedAt: new Date(),
      })
      .onConflictDoUpdate({
        target: pushSubscriptionsTable.token,
        set: {
          enabled: true,
          ...(min !== null ? { minConfidence: min } : {}),
          ...(minHp !== null ? { minHealthPct: minHp } : {}),
          updatedAt: new Date(),
        },
      });
    const [row] = await db
      .select()
      .from(pushSubscriptionsTable)
      .where(eq(pushSubscriptionsTable.token, token));
    res.json({
      registered: true,
      enabled: row?.enabled ?? true,
      minConfidence: row?.minConfidence ?? 70,
      minHealthPct: row?.minHealthPct ?? 70,
    });
  } catch (err) {
    logger.error({ err: err instanceof Error ? err.message : String(err) },
      "push register failed");
    res.status(500).json({ error: "Failed to register push token" });
  }
});

// Update preferences (threshold and/or enabled) for an existing token.
router.post("/notifications/push/preferences", async (req: Request, res: Response) => {
  try {
    const { token, minConfidence, minHealthPct, enabled } = (req.body ?? {}) as Record<string, unknown>;
    if (!isValidExpoPushToken(token)) {
      res.status(400).json({ error: "A valid Expo push token is required" });
      return;
    }
    const min = parseMinConfidence(minConfidence);
    if (minConfidence !== undefined && min === null) {
      res.status(400).json({ error: "minConfidence must be a number between 0 and 100" });
      return;
    }
    const minHp = parseMinHealthPct(minHealthPct);
    if (minHealthPct !== undefined && minHp === null) {
      res.status(400).json({ error: "minHealthPct must be a number between 50 and 90" });
      return;
    }
    if (enabled !== undefined && typeof enabled !== "boolean") {
      res.status(400).json({ error: "enabled must be a boolean" });
      return;
    }
    await ensurePushSubscriptionsTable();
    const updates: Record<string, unknown> = { updatedAt: new Date() };
    if (min !== null) updates["minConfidence"] = min;
    if (minHp !== null) updates["minHealthPct"] = minHp;
    if (typeof enabled === "boolean") updates["enabled"] = enabled;
    const result = await db
      .update(pushSubscriptionsTable)
      .set(updates)
      .where(eq(pushSubscriptionsTable.token, token))
      .returning();
    if (result.length === 0) {
      res.status(404).json({ error: "Token not registered" });
      return;
    }
    const row = result[0]!;
    res.json({
      registered: true,
      enabled: row.enabled,
      minConfidence: row.minConfidence,
      minHealthPct: row.minHealthPct,
    });
  } catch (err) {
    logger.error({ err: err instanceof Error ? err.message : String(err) },
      "push preferences update failed");
    res.status(500).json({ error: "Failed to update push preferences" });
  }
});

// Inspect a token's subscription state.
router.get("/notifications/push/status", async (req: Request, res: Response) => {
  try {
    const token = req.query["token"];
    if (!isValidExpoPushToken(token)) {
      res.status(400).json({ error: "A valid Expo push token is required" });
      return;
    }
    await ensurePushSubscriptionsTable();
    const [row] = await db
      .select()
      .from(pushSubscriptionsTable)
      .where(eq(pushSubscriptionsTable.token, token));
    if (!row) {
      res.json({ registered: false });
      return;
    }
    res.json({
      registered: true,
      enabled: row.enabled,
      minConfidence: row.minConfidence,
      minHealthPct: row.minHealthPct,
    });
  } catch (err) {
    logger.error({ err: err instanceof Error ? err.message : String(err) },
      "push status lookup failed");
    res.status(500).json({ error: "Failed to look up push status" });
  }
});

// ── Priority 5 (#31): push/email delivery monitoring ───────────────────────
// Read-only views over alert_deliveries. DELIVERED means the provider
// confirmed delivery or accepted handoff per its supported status model
// (Expo ticket status "ok"); a mere send attempt is never reported as
// DELIVERED.

const DELIVERY_STATUSES = new Set([
  "QUEUED", "SENDING", "DELIVERED", "RETRY_SCHEDULED", "FAILED", "EXPIRED",
]);

function latencyMs(providerResponse: unknown): number | null {
  if (providerResponse && typeof providerResponse === "object") {
    const v = (providerResponse as Record<string, unknown>)["latency_ms"];
    if (typeof v === "number" && Number.isFinite(v)) return v;
  }
  return null;
}

// Recent delivery history with filters: kind, severity, status, channel,
// destination (substring), since/until dates.
router.get("/notifications/deliveries", async (req: Request, res: Response) => {
  try {
    await ensureAlertDeliveriesTable();
    const q = req.query as Record<string, string | undefined>;
    const conditions = [];
    if (q["channel"] && ["push", "email"].includes(q["channel"])) {
      conditions.push(eq(alertDeliveriesTable.channel, q["channel"]));
    }
    if (q["status"] && DELIVERY_STATUSES.has(q["status"].toUpperCase())) {
      conditions.push(eq(alertDeliveriesTable.status, q["status"].toUpperCase()));
    }
    if (q["kind"]) conditions.push(eq(alertDeliveriesTable.kind, q["kind"]));
    if (q["severity"]) {
      conditions.push(eq(alertDeliveriesTable.severity, q["severity"].toUpperCase()));
    }
    if (q["destination"]) {
      conditions.push(ilike(alertDeliveriesTable.destination, `%${q["destination"]}%`));
    }
    const since = q["since"] ? new Date(q["since"]) : null;
    if (since && !isNaN(since.getTime())) {
      conditions.push(gte(alertDeliveriesTable.createdAt, since));
    }
    const until = q["until"] ? new Date(q["until"]) : null;
    if (until && !isNaN(until.getTime())) {
      conditions.push(lte(alertDeliveriesTable.createdAt, until));
    }
    const limit = Math.min(Math.max(Number(q["limit"]) || 100, 1), 500);
    const rows = await db
      .select()
      .from(alertDeliveriesTable)
      .where(conditions.length ? and(...conditions) : undefined)
      .orderBy(desc(alertDeliveriesTable.createdAt))
      .limit(limit);
    res.json({
      deliveries: rows.map((r) => ({
        id: r.id,
        channel: r.channel,
        kind: r.kind,
        severity: r.severity,
        title: r.title,
        destination: truncateDestination(r.destination),
        status: r.status,
        attempts: r.attempts,
        maxAttempts: r.maxAttempts,
        critical: r.critical,
        deadLetter: r.deadLetter,
        lastError: r.lastError,
        providerId: r.providerId ?? null,
        latencyMs: latencyMs(r.providerResponse),
        nextAttemptAt: r.nextAttemptAt,
        expiresAt: r.expiresAt,
        createdAt: r.createdAt,
        updatedAt: r.updatedAt,
        deliveredAt: r.deliveredAt,
      })),
      note: "DELIVERED = provider-confirmed delivery or accepted handoff only",
    });
  } catch (err) {
    logger.error({ err: err instanceof Error ? err.message : String(err) },
      "delivery history lookup failed");
    res.status(500).json({ error: "Failed to load delivery history" });
  }
});

// At-a-glance stats: counts per channel/status, last delivery, last
// failure, average provider latency, device-token status.
router.get("/notifications/deliveries/stats", async (_req: Request, res: Response) => {
  try {
    await ensureAlertDeliveriesTable();
    await ensurePushSubscriptionsTable();
    const grouped = await db
      .select({
        channel: alertDeliveriesTable.channel,
        status: alertDeliveriesTable.status,
        n: count(),
      })
      .from(alertDeliveriesTable)
      .groupBy(alertDeliveriesTable.channel, alertDeliveriesTable.status);
    const counts: Record<string, Record<string, number>> = {};
    for (const g of grouped) {
      counts[g.channel] = counts[g.channel] ?? {};
      counts[g.channel]![g.status] = Number(g.n);
    }
    const lastDelivered = await db
      .select({
        channel: alertDeliveriesTable.channel,
        ts: max(alertDeliveriesTable.deliveredAt),
      })
      .from(alertDeliveriesTable)
      .groupBy(alertDeliveriesTable.channel);
    const lastFailed = await db
      .select({
        channel: alertDeliveriesTable.channel,
        ts: max(alertDeliveriesTable.updatedAt),
      })
      .from(alertDeliveriesTable)
      .where(eq(alertDeliveriesTable.status, "FAILED"))
      .groupBy(alertDeliveriesTable.channel);
    const [latency] = await db
      .select({
        avgMs: sql<number | null>`avg((provider_response->>'latency_ms')::numeric)`,
        maxMs: sql<number | null>`max((provider_response->>'latency_ms')::numeric)`,
      })
      .from(alertDeliveriesTable)
      .where(and(
        eq(alertDeliveriesTable.status, "DELIVERED"),
        sql`provider_response ? 'latency_ms'`,
      ));
    const [dead] = await db
      .select({ n: count() })
      .from(alertDeliveriesTable)
      .where(eq(alertDeliveriesTable.deadLetter, true));
    const tokens = await db
      .select({
        enabled: pushSubscriptionsTable.enabled,
        n: count(),
      })
      .from(pushSubscriptionsTable)
      .groupBy(pushSubscriptionsTable.enabled);
    const tokenStatus = { enabled: 0, disabled: 0 };
    for (const t of tokens) {
      if (t.enabled) tokenStatus.enabled = Number(t.n);
      else tokenStatus.disabled = Number(t.n);
    }
    res.json({
      counts,
      lastDelivered: Object.fromEntries(
        lastDelivered.filter((r) => r.ts).map((r) => [r.channel, r.ts])),
      lastFailed: Object.fromEntries(
        lastFailed.filter((r) => r.ts).map((r) => [r.channel, r.ts])),
      providerLatency: {
        avgMs: latency?.avgMs != null ? Math.round(Number(latency.avgMs)) : null,
        maxMs: latency?.maxMs != null ? Math.round(Number(latency.maxMs)) : null,
      },
      deadLetterCount: Number(dead?.n ?? 0),
      deviceTokens: tokenStatus,
      note: "DELIVERED = provider-confirmed delivery or accepted handoff only",
    });
  } catch (err) {
    logger.error({ err: err instanceof Error ? err.message : String(err) },
      "delivery stats lookup failed");
    res.status(500).json({ error: "Failed to load delivery stats" });
  }
});

export default router;
