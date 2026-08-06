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
          min_health_pct double precision NOT NULL DEFAULT 70,
          enabled boolean NOT NULL DEFAULT true,
          last_notified_key text,
          created_at timestamptz DEFAULT now(),
          updated_at timestamptz DEFAULT now()
        )
      `)
      .then(() =>
        db.execute(sql`
          ALTER TABLE push_subscriptions
          ADD COLUMN IF NOT EXISTS min_health_pct double precision NOT NULL DEFAULT 70
        `)
      )
      .then(() =>
        db.execute(sql`
          UPDATE push_subscriptions
          SET min_health_pct = 70
          WHERE min_health_pct IS NULL
        `)
      )
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
// Called after each ops-centre snapshot collection. Each subscribed device is
// evaluated independently against its own `min_health_pct` threshold:
//
//   • If health_pct < sub.minHealthPct OR any agent is in ERROR → send alert.
//   • If the device was previously alerted AND is now healthy (health_pct >=
//     sub.minHealthPct AND no ERROR agents) → send one recovery notification
//     and remove the token from the degraded set.
//
// Degradation state is tracked per-token in `degradedSubscriberTokens` so that
// high-threshold subscribers (e.g. 90%) correctly alert at 85%, while
// low-threshold subscribers (e.g. 70%) do not receive a spurious recovery push
// until health climbs above their own threshold.
//
// State is persisted to `signals_cache` under key "ops_health_state" so that
// a recovery push is never silently lost when the API server restarts while
// the platform is degraded. On startup the set is re-populated from the DB;
// every add/remove is written back atomically.
//
// All pushes are deduplicated by their idempotency key in alert_deliveries, so
// re-dispatch of the same scan_id never double-notifies a device.
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

const OPS_HEALTH_STATE_KEY = "ops_health_state";

let healthAlertInFlight = false;

// Per-token degradation state: tracks which device tokens have received a
// health degradation alert. Persisted in signals_cache so the flag survives
// API server restarts — a mid-incident restart no longer silently loses the
// recovery push.
const degradedSubscriberTokens = new Set<string>();

// Lazy-load flag: true once we have read the initial state from the DB.
let healthStateLoaded = false;
let healthStateLoadPromise: Promise<void> | null = null;

async function loadHealthStateFromDb(): Promise<void> {
  if (healthStateLoaded) return;
  if (healthStateLoadPromise) return healthStateLoadPromise;
  healthStateLoadPromise = (async () => {
    try {
      const [row] = await db
        .select()
        .from(signalsCacheTable)
        .where(eq(signalsCacheTable.key, OPS_HEALTH_STATE_KEY));
      if (row?.payload) {
        const payload = row.payload as { degraded_tokens?: unknown };
        if (Array.isArray(payload.degraded_tokens)) {
          for (const token of payload.degraded_tokens) {
            if (typeof token === "string") {
              degradedSubscriberTokens.add(token);
            }
          }
        }
      }
    } catch (err) {
      logger.warn(
        { err: err instanceof Error ? err.message : String(err) },
        "Failed to load ops health state from DB — starting with empty degraded set",
      );
    } finally {
      healthStateLoaded = true;
    }
  })();
  return healthStateLoadPromise;
}

async function persistHealthStateToDb(): Promise<void> {
  const degradedTokens = [...degradedSubscriberTokens];
  try {
    await db
      .insert(signalsCacheTable)
      .values({
        key: OPS_HEALTH_STATE_KEY,
        payload: { degraded_tokens: degradedTokens },
        updatedAt: new Date(),
      })
      .onConflictDoUpdate({
        target: signalsCacheTable.key,
        set: {
          payload: { degraded_tokens: degradedTokens },
          updatedAt: new Date(),
        },
      });
  } catch (err) {
    logger.warn(
      { err: err instanceof Error ? err.message : String(err) },
      "Failed to persist ops health state to DB",
    );
  }
}

export async function dispatchHealthAlertPushNotifications(
  snapshot: OpsHealthSnapshot,
): Promise<void> {
  if (healthAlertInFlight) return;

  // Feature flag — default enabled
  const flagVal = (process.env["OPS_HEALTH_ALERTS_ENABLED"] ?? "true").toLowerCase();
  if (flagVal === "false" || flagVal === "0" || flagVal === "no") return;

  const healthPct = snapshot.platform?.health_pct ?? 100;
  const scanId = (snapshot.platform?.scan_id ?? "").trim() || "unknown";

  // Collect ERROR agents (global — same for every subscriber)
  const errorAgents = Object.entries(snapshot.agents ?? {})
    .filter(([, a]) => a.status === "ERROR")
    .map(([, a]) => a.name ?? "Unknown agent");
  const hasErrors = errorAgents.length > 0;

  healthAlertInFlight = true;
  try {
    await ensurePushSubscriptionsTable();
    // Restore persisted degraded-token state if this is the first call after
    // a server restart (idempotent: no-op on subsequent calls).
    await loadHealthStateFromDb();

    const subs = await db
      .select()
      .from(pushSubscriptionsTable)
      .where(eq(pushSubscriptionsTable.enabled, true));
    if (subs.length === 0) return;

    let enqueued = 0;

    for (const sub of subs) {
      const rawThreshold = sub.minHealthPct ?? 70;
      const threshold = Number.isFinite(rawThreshold)
        ? Math.min(90, Math.max(50, rawThreshold))
        : 70;
      const subDegraded = healthPct < threshold;
      const shouldAlert = subDegraded || hasErrors;
      const wasAlerted = degradedSubscriberTokens.has(sub.token);

      if (shouldAlert) {
        // Mark this subscriber as having received a degradation alert and
        // persist so the flag survives a server restart.
        degradedSubscriberTokens.add(sub.token);
        await persistHealthStateToDb();

        let title: string;
        let body: string;
        if (subDegraded && hasErrors) {
          title = `Platform health ${healthPct}% — ${errorAgents.length} agent${errorAgents.length === 1 ? "" : "s"} in error`;
          body = `Agents in error: ${errorAgents.slice(0, 3).join(", ")}${errorAgents.length > 3 ? ` +${errorAgents.length - 3} more` : ""}. Check the Pipeline tab.`;
        } else if (subDegraded) {
          title = `Platform health degraded — ${healthPct}%`;
          body = `Overall pipeline health has dropped below ${threshold}%. Open Pipeline for details.`;
        } else {
          // hasErrors only
          title = `${errorAgents.length} agent${errorAgents.length === 1 ? "" : "s"} in error`;
          body = `${errorAgents.slice(0, 3).join(", ")}${errorAgents.length > 3 ? ` +${errorAgents.length - 3} more` : ""}. Open Pipeline to investigate.`;
        }

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
      } else if (wasAlerted) {
        // Platform has recovered above this subscriber's personal threshold
        // and all agents are healthy — send a one-time "all-clear" push.
        degradedSubscriberTokens.delete(sub.token);
        await persistHealthStateToDb();

        const title = `Platform recovered — health now ${healthPct}%`;
        const body = `All agents are active. Pipeline is operating normally.`;
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
      // else: platform healthy for this subscriber and was never degraded — nothing to send
    }

    if (enqueued > 0) {
      logger.info(
        { enqueued, scanId, healthPct, errorAgents: errorAgents.length },
        "Health alert/recovery push notifications queued",
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

// Exported for tests only — resets both the in-process degraded-token set
// and the persisted DB record so each test case starts from a clean slate.
export async function _resetPlatformDegradedStateForTests(): Promise<void> {
  degradedSubscriberTokens.clear();
  healthStateLoaded = false;
  healthStateLoadPromise = null;
  try {
    await db
      .delete(signalsCacheTable)
      .where(eq(signalsCacheTable.key, OPS_HEALTH_STATE_KEY));
  } catch {
    // Best-effort — ignore failures during test teardown.
  }
}

// Exported for tests only — resets only the in-process state (the Set and
// the load flags) WITHOUT touching the DB. Used to simulate a server restart:
// the DB record is intact so the next dispatch re-loads it from storage.
export function _resetInMemoryHealthStateOnlyForTests(): void {
  degradedSubscriberTokens.clear();
  healthStateLoaded = false;
  healthStateLoadPromise = null;
}
