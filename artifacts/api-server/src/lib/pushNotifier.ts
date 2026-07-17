import { db, pushSubscriptionsTable, signalsCacheTable } from "@workspace/db";
import { eq, sql } from "drizzle-orm";
import { logger } from "./logger";

// High-confidence signal push notifications (research alerts only).
//
// After each successful scan, the scheduler calls
// dispatchSignalPushNotifications(). For every enabled subscription we:
//   1. Skip if this signals snapshot (signals_cache.updated_at for key
//      "signals") was already evaluated for that token (last_notified_key).
//   2. Filter signals to actionable BUY/SELL whose confidence meets the
//      subscriber's own min_confidence threshold.
//   3. Send one summary push via Expo's push API when matches exist.
//   4. Always record the snapshot key so a scan is only considered once.
// Invalid tokens (DeviceNotRegistered) are deleted. Purely advisory —
// notifications never trigger any trading action.

const EXPO_PUSH_URL = "https://exp.host/--/api/v2/push/send";

const ACTIONABLE = new Set(["BUY", "SELL", "STRONG BUY", "STRONG_BUY", "STRONG SELL", "STRONG_SELL"]);

interface SignalEntry {
  symbol: string;
  action: string;
  confidence: number;
  price?: number;
}

function extractActionableSignals(payload: unknown): SignalEntry[] {
  if (!Array.isArray(payload)) return [];
  const out: SignalEntry[] = [];
  for (const raw of payload) {
    if (typeof raw !== "object" || raw === null) continue;
    const sig = raw as Record<string, unknown>;
    const symbol = String(sig["stock"] ?? sig["symbol"] ?? "").trim();
    const action = String(sig["final_action"] ?? sig["signal"] ?? "").trim().toUpperCase();
    const confidence = Number(sig["confidence"] ?? 0);
    if (!symbol || !ACTIONABLE.has(action) || !Number.isFinite(confidence)) continue;
    const price = Number(sig["price"] ?? sig["entry_price"]);
    out.push({ symbol, action, confidence, price: Number.isFinite(price) ? price : undefined });
  }
  return out;
}

interface ExpoPushTicket {
  status?: string;
  message?: string;
  details?: { error?: string };
}

async function sendExpoPush(messages: Array<Record<string, unknown>>): Promise<ExpoPushTicket[]> {
  const res = await fetch(EXPO_PUSH_URL, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Accept: "application/json",
      "Accept-Encoding": "gzip, deflate",
    },
    body: JSON.stringify(messages),
  });
  if (!res.ok) {
    throw new Error(`Expo push API responded ${res.status}`);
  }
  const body = (await res.json()) as { data?: ExpoPushTicket[] };
  return body.data ?? [];
}

export function isValidExpoPushToken(token: unknown): token is string {
  return (
    typeof token === "string" &&
    /^Expo(nent)?PushToken\[[A-Za-z0-9_-]+\]$/.test(token)
  );
}

// Cold-start bootstrap: create the table on fresh databases (e.g. a new
// production DB) so registration/dispatch never fail with "relation does
// not exist". Idempotent; runs once per process.
let tableEnsured: Promise<void> | null = null;

export function ensurePushSubscriptionsTable(): Promise<void> {
  if (!tableEnsured) {
    tableEnsured = db
      .execute(sql`
        CREATE TABLE IF NOT EXISTS push_subscriptions (
          token text PRIMARY KEY,
          min_confidence double precision NOT NULL DEFAULT 70,
          enabled boolean NOT NULL DEFAULT true,
          last_notified_key text,
          created_at timestamptz DEFAULT now(),
          updated_at timestamptz DEFAULT now()
        )
      `)
      .then(() => undefined)
      .catch((err: unknown) => {
        tableEnsured = null; // retry on next call
        throw err;
      });
  }
  return tableEnsured;
}

let dispatchInFlight = false;

export async function dispatchSignalPushNotifications(): Promise<void> {
  if (dispatchInFlight) return;
  dispatchInFlight = true;
  try {
    await ensurePushSubscriptionsTable();
    const subs = await db
      .select()
      .from(pushSubscriptionsTable)
      .where(eq(pushSubscriptionsTable.enabled, true));
    if (subs.length === 0) return;

    const [cacheRow] = await db
      .select()
      .from(signalsCacheTable)
      .where(eq(signalsCacheTable.key, "signals"));
    if (!cacheRow || !cacheRow.updatedAt) return;

    const snapshotKey = cacheRow.updatedAt.toISOString();
    const signals = extractActionableSignals(cacheRow.payload);

    const messages: Array<Record<string, unknown>> = [];
    const messageTokens: string[] = [];

    for (const sub of subs) {
      if (sub.lastNotifiedKey === snapshotKey) continue;

      const matches = signals
        .filter((s) => s.confidence >= sub.minConfidence)
        .sort((a, b) => b.confidence - a.confidence);

      // Mark this snapshot as evaluated for this token no matter what,
      // so a scan is never re-considered (and never double-notified).
      await db
        .update(pushSubscriptionsTable)
        .set({ lastNotifiedKey: snapshotKey, updatedAt: new Date() })
        .where(eq(pushSubscriptionsTable.token, sub.token));

      if (matches.length === 0) continue;

      const top = matches.slice(0, 3);
      const lines = top.map(
        (s) => `${s.symbol}: ${s.action} (${Math.round(s.confidence)}%)`,
      );
      const extra = matches.length > top.length ? ` +${matches.length - top.length} more` : "";
      messages.push({
        to: sub.token,
        sound: "default",
        title:
          matches.length === 1
            ? `${top[0]!.symbol} ${top[0]!.action} signal — ${Math.round(top[0]!.confidence)}% confidence`
            : `${matches.length} high-confidence signals`,
        body: lines.join("  ·  ") + extra + " — research only, no orders placed.",
        data: { screen: "signals", snapshotKey },
      });
      messageTokens.push(sub.token);
    }

    if (messages.length === 0) return;

    for (let i = 0; i < messages.length; i += 100) {
      const chunk = messages.slice(i, i + 100);
      const chunkTokens = messageTokens.slice(i, i + 100);
      try {
        const tickets = await sendExpoPush(chunk);
        for (let j = 0; j < tickets.length; j++) {
          const ticket = tickets[j];
          if (ticket?.status === "error") {
            const tokenForTicket = chunkTokens[j];
            if (ticket.details?.error === "DeviceNotRegistered" && tokenForTicket) {
              await db
                .delete(pushSubscriptionsTable)
                .where(eq(pushSubscriptionsTable.token, tokenForTicket));
              logger.info({ token: tokenForTicket.slice(0, 24) + "…" },
                "Removed unregistered push token");
            } else {
              logger.warn({ error: ticket.details?.error, message: ticket.message },
                "Expo push ticket error");
            }
          }
        }
      } catch (err) {
        logger.warn({ err: err instanceof Error ? err.message : String(err) },
          "Expo push send failed (will not retry this snapshot)");
      }
    }
    logger.info({ sent: messages.length, snapshotKey },
      "Signal push notifications dispatched");
  } finally {
    dispatchInFlight = false;
  }
}
