import { Router, type IRouter, type Request, type Response } from "express";
import { db, pushSubscriptionsTable } from "@workspace/db";
import { eq } from "drizzle-orm";
import { isValidExpoPushToken, ensurePushSubscriptionsTable } from "../lib/pushNotifier";
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

// Register (or re-register) a device token.
router.post("/notifications/push/register", async (req: Request, res: Response) => {
  try {
    const { token, minConfidence } = (req.body ?? {}) as Record<string, unknown>;
    if (!isValidExpoPushToken(token)) {
      res.status(400).json({ error: "A valid Expo push token is required" });
      return;
    }
    const min = parseMinConfidence(minConfidence);
    if (minConfidence !== undefined && min === null) {
      res.status(400).json({ error: "minConfidence must be a number between 0 and 100" });
      return;
    }
    await ensurePushSubscriptionsTable();
    await db
      .insert(pushSubscriptionsTable)
      .values({
        token,
        minConfidence: min ?? 70,
        enabled: true,
        updatedAt: new Date(),
      })
      .onConflictDoUpdate({
        target: pushSubscriptionsTable.token,
        set: {
          enabled: true,
          ...(min !== null ? { minConfidence: min } : {}),
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
    const { token, minConfidence, enabled } = (req.body ?? {}) as Record<string, unknown>;
    if (!isValidExpoPushToken(token)) {
      res.status(400).json({ error: "A valid Expo push token is required" });
      return;
    }
    const min = parseMinConfidence(minConfidence);
    if (minConfidence !== undefined && min === null) {
      res.status(400).json({ error: "minConfidence must be a number between 0 and 100" });
      return;
    }
    if (enabled !== undefined && typeof enabled !== "boolean") {
      res.status(400).json({ error: "enabled must be a boolean" });
      return;
    }
    const updates: Record<string, unknown> = { updatedAt: new Date() };
    if (min !== null) updates["minConfidence"] = min;
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
    res.json({ registered: true, enabled: row.enabled, minConfidence: row.minConfidence });
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
    const [row] = await db
      .select()
      .from(pushSubscriptionsTable)
      .where(eq(pushSubscriptionsTable.token, token));
    if (!row) {
      res.json({ registered: false });
      return;
    }
    res.json({ registered: true, enabled: row.enabled, minConfidence: row.minConfidence });
  } catch (err) {
    logger.error({ err: err instanceof Error ? err.message : String(err) },
      "push status lookup failed");
    res.status(500).json({ error: "Failed to look up push status" });
  }
});

export default router;
