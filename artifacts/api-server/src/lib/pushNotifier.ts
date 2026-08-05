import { db, pushSubscriptionsTable, signalsCacheTable } from "@workspace/db";
import { eq, sql } from "drizzle-orm";
import { logger } from "./logger";
import {
  enqueueAlert,
  processDueDeliveries,
  truncateDestination,
  type AttemptSender,
} from "./alertQueue";

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

    if (messages.length > 0) {
      // Priority 4 (#41): enqueue into the durable alert delivery queue
      // instead of firing directly — a briefly-down push service no longer
      // loses alerts. Idempotency key = token + snapshot, so re-dispatch of
      // the same scan can never double-notify a device.
      let enqueued = 0;
      for (let i = 0; i < messages.length; i++) {
        const token = messageTokens[i]!;
        const ok = await enqueueAlert({
          channel: "push",
          kind: "signal_alert",
          severity: "INFO",
          title: String(messages[i]!["title"] ?? "Signal alert"),
          body: String(messages[i]!["body"] ?? ""),
          destination: token,
          payload: messages[i],
          idempotencyKey: `push:${token}:${snapshotKey}`,
        });
        if (ok) enqueued++;
      }
      logger.info({ enqueued, snapshotKey }, "Signal push notifications queued");
    }

    // Always drain due deliveries (including retries from earlier snapshots).
    await processPushDeliveryQueue();
  } finally {
    dispatchInFlight = false;
  }
}

// ── Queue processor (Priority 4 / #41) ───────────────────────────────────────

const PERMANENT_TICKET_ERRORS = new Set([
  "DeviceNotRegistered", "InvalidCredentials", "MessageTooBig",
]);

const expoSender: AttemptSender = async (row) => {
  const message = (row.payload && typeof row.payload === "object")
    ? (row.payload as Record<string, unknown>)
    : { to: row.destination, title: row.title, body: row.body, sound: "default" };
  const startedAt = Date.now();
  const tickets = await sendExpoPush([message]);
  const latencyMs = Date.now() - startedAt;
  const ticket = tickets[0];
  if (!ticket) {
    return { ok: false, error: "Expo returned no ticket" };
  }
  const response: Record<string, unknown> = {
    status: ticket.status, id: (ticket as Record<string, unknown>)["id"],
    error: ticket.details?.error, latency_ms: latencyMs,
  };
  if (ticket.status === "ok") {
    // Expo "ok" = accepted handoff to the push gateway (Expo's supported
    // status model); receipts are not polled here.
    return {
      ok: true,
      providerId: String((ticket as Record<string, unknown>)["id"] ?? ""),
      providerResponse: response,
    };
  }
  const errCode = ticket.details?.error ?? "unknown";
  if (errCode === "DeviceNotRegistered") {
    await db.delete(pushSubscriptionsTable)
      .where(eq(pushSubscriptionsTable.token, row.destination));
    logger.info({ token: truncateDestination(row.destination) },
      "Removed unregistered push token");
  }
  return {
    ok: false,
    permanent: PERMANENT_TICKET_ERRORS.has(errCode),
    providerResponse: response,
    error: `${errCode}: ${ticket.message ?? ""}`.slice(0, 300),
  };
};

let queueProcessing = false;

export async function processPushDeliveryQueue(): Promise<void> {
  if (queueProcessing) return;
  queueProcessing = true;
  try {
    const counters = await processDueDeliveries("push", expoSender, 500);
    if (counters.delivered || counters.retried || counters.failed || counters.expired) {
      logger.info(counters, "Push delivery queue processed");
    }
  } finally {
    queueProcessing = false;
  }
}

// ── Health-alert push notifications (Task 316) ────────────────────────────────
//
// Called after each ops-centre snapshot collection. If platform health drops
// below 70% or any enabled agent is in ERROR state, every subscribed device
// gets one advisory push per scan_id — deduplicated by
// `health_alert:<token>:<scanId>` in the alert_deliveries idempotency key.
//
// Recovery tracking: once the platform was degraded in the current process
// session, `platformWasDegraded` is set to true. The next snapshot that shows
// health_pct ≥ 70 with no ERROR agents sends a single "platform recovered"
// push per device, deduped by `health_recovery:<token>:<scanId>`, and resets
// the flag. No recovery push fires if the system was never degraded.
//
// Feature-flagged behind OPS_HEALTH_ALERTS_ENABLED (default: true).
// Purely advisory — never triggers any trading action.

export interface OpsHealthSnapshot {
  platform?: {
    health_pct?: number;
    scan_id?: string;
  };
  agents?: Record<string, { status?: string; name?: string }>;
}

let healthAlertInFlight = false;

// Tracks whether the platform was degraded (health < 70 or agent ERROR) at
// any point in the current server session. Persists across snapshots so a
// recovery notification can be issued exactly once when health climbs back.
let platformWasDegraded = false;

export async function dispatchHealthAlertPushNotifications(
  snapshot: OpsHealthSnapshot,
): Promise<void> {
  if (healthAlertInFlight) return;

  // Feature flag — default enabled
  const flagVal = (process.env["OPS_HEALTH_ALERTS_ENABLED"] ?? "true").toLowerCase();
  if (flagVal === "false" || flagVal === "0" || flagVal === "no") return;

  const healthPct = snapshot.platform?.health_pct ?? 100;
  const scanId = (snapshot.platform?.scan_id ?? "").trim() || "unknown";

  // Collect ERROR agents
  const errorAgents = Object.entries(snapshot.agents ?? {})
    .filter(([, a]) => a.status === "ERROR")
    .map(([, a]) => a.name ?? "Unknown agent");

  const healthDegraded = healthPct < 70;
  const hasErrors = errorAgents.length > 0;
  const platformHealthy = !healthDegraded && !hasErrors;

  // ── Recovery path ─────────────────────────────────────────────────────────
  // Platform is healthy now. If it was previously degraded, send one
  // "all-clear" push per subscribed device and reset the degraded flag.
  if (platformHealthy) {
    if (!platformWasDegraded) return; // never degraded this session — nothing to send

    healthAlertInFlight = true;
    try {
      await ensurePushSubscriptionsTable();
      const subs = await db
        .select()
        .from(pushSubscriptionsTable)
        .where(eq(pushSubscriptionsTable.enabled, true));

      // Reset regardless of whether anyone is subscribed so a later alert
      // cycle starts fresh.
      platformWasDegraded = false;

      if (subs.length === 0) return;

      const title = `Platform recovered — health now ${healthPct}%`;
      const body = `All agents are active. Pipeline is operating normally.`;

      let enqueued = 0;
      for (const sub of subs) {
        const idempotencyKey = `health_recovery:${sub.token}:${scanId}`;
        const ok = await enqueueAlert({
          channel: "push",
          kind: "health_alert",
          severity: "INFO",
          title,
          body,
          destination: sub.token,
          payload: {
            to: sub.token,
            sound: "default",
            title,
            body,
            data: { screen: "ai-ops", scanId, healthPct },
          },
          idempotencyKey,
          critical: false,
        });
        if (ok) enqueued++;
      }

      if (enqueued > 0) {
        logger.info(
          { enqueued, scanId, healthPct },
          "Platform recovery push notifications queued",
        );
      }

      // Drain due deliveries so alerts go out promptly
      await processPushDeliveryQueue();
    } catch (err) {
      logger.error(
        { err: err instanceof Error ? err.message : String(err) },
        "Platform recovery push dispatch failed",
      );
    } finally {
      healthAlertInFlight = false;
    }
    return;
  }

  // ── Degraded path ─────────────────────────────────────────────────────────
  // Mark that we have seen a degraded state so a recovery push can fire later.
  platformWasDegraded = true;

  healthAlertInFlight = true;
  try {
    await ensurePushSubscriptionsTable();
    const subs = await db
      .select()
      .from(pushSubscriptionsTable)
      .where(eq(pushSubscriptionsTable.enabled, true));
    if (subs.length === 0) return;

    // Build notification content
    let title: string;
    let body: string;

    if (healthDegraded && hasErrors) {
      title = `Platform health ${healthPct}% — ${errorAgents.length} agent${errorAgents.length === 1 ? "" : "s"} in error`;
      body = `Agents in error: ${errorAgents.slice(0, 3).join(", ")}${errorAgents.length > 3 ? ` +${errorAgents.length - 3} more` : ""}. Check the Pipeline tab.`;
    } else if (healthDegraded) {
      title = `Platform health degraded — ${healthPct}%`;
      body = `Overall pipeline health has dropped below 70%. Open Pipeline for details.`;
    } else {
      // hasErrors only
      title = `${errorAgents.length} agent${errorAgents.length === 1 ? "" : "s"} in error`;
      body = `${errorAgents.slice(0, 3).join(", ")}${errorAgents.length > 3 ? ` +${errorAgents.length - 3} more` : ""}. Open Pipeline to investigate.`;
    }

    let enqueued = 0;
    for (const sub of subs) {
      const idempotencyKey = `health_alert:${sub.token}:${scanId}`;
      const ok = await enqueueAlert({
        channel: "push",
        kind: "health_alert",
        severity: "WARN",
        title,
        body,
        destination: sub.token,
        payload: {
          to: sub.token,
          sound: "default",
          title,
          body,
          // Deep-links to the Pipeline tab in the mobile app
          data: { screen: "ai-ops", scanId, healthPct, errorAgents },
        },
        idempotencyKey,
        critical: false,
      });
      if (ok) enqueued++;
    }

    if (enqueued > 0) {
      logger.info(
        { enqueued, scanId, healthPct, errorAgents: errorAgents.length },
        "Health alert push notifications queued",
      );
    }

    // Drain due deliveries so alerts go out promptly
    await processPushDeliveryQueue();
  } catch (err) {
    logger.error(
      { err: err instanceof Error ? err.message : String(err) },
      "Health alert push dispatch failed",
    );
  } finally {
    healthAlertInFlight = false;
  }
}

// Exported for tests only — allows resetting the in-process degraded flag
// between test cases without restarting the process.
export function _resetPlatformDegradedStateForTests(): void {
  platformWasDegraded = false;
}
