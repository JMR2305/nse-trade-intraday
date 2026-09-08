import { db, alertDeliveriesTable } from "@workspace/db";
import { and, asc, eq, inArray, lte, or, sql } from "drizzle-orm";
import { logger } from "./logger";

// Priority 4 (#41) — durable alert delivery queue.
//
// Lifecycle: QUEUED → SENDING → DELIVERED | RETRY_SCHEDULED | FAILED | EXPIRED
// - Idempotency keys make enqueue safe to repeat (ON CONFLICT DO NOTHING).
// - Transient failures retry with bounded exponential backoff.
// - Permanent failures (e.g. DeviceNotRegistered) fail immediately.
// - Rows that exhaust retries are dead-lettered (status FAILED,
//   dead_letter = true) — visible, never silently dropped.
// - Critical alerts never auto-expire; non-critical rows expire after
//   expires_at (default 24 h).
// - No API secrets in payloads or logs: destination is a device push token
//   (the delivery address) and log lines only ever show a truncated form.

export const BACKOFF_SECONDS = [60, 300, 900, 3600, 10800, 21600];
export const DEFAULT_MAX_ATTEMPTS = 6;
export const CRITICAL_MAX_ATTEMPTS = 10;
export const DEFAULT_TTL_HOURS = 24;

export type AlertChannel = "push" | "email";

export interface EnqueueInput {
  channel: AlertChannel;
  kind: string;
  severity?: string;
  title: string;
  body?: string;
  destination: string;
  payload?: Record<string, unknown>;
  idempotencyKey: string;
  critical?: boolean;
}

export function truncateDestination(dest: string): string {
  return dest.length > 24 ? dest.slice(0, 24) + "…" : dest;
}

let tableEnsured: Promise<void> | null = null;

export function ensureAlertDeliveriesTable(): Promise<void> {
  if (!tableEnsured) {
    tableEnsured = db
      .execute(sql`
        CREATE TABLE IF NOT EXISTS alert_deliveries (
          id bigserial PRIMARY KEY,
          idempotency_key text NOT NULL UNIQUE,
          channel text NOT NULL,
          kind text NOT NULL,
          severity text NOT NULL DEFAULT 'INFO',
          title text NOT NULL,
          body text NOT NULL DEFAULT '',
          destination text NOT NULL,
          payload jsonb,
          status text NOT NULL DEFAULT 'QUEUED',
          attempts integer NOT NULL DEFAULT 0,
          max_attempts integer NOT NULL DEFAULT 6,
          critical boolean NOT NULL DEFAULT false,
          dead_letter boolean NOT NULL DEFAULT false,
          next_attempt_at timestamptz DEFAULT now(),
          expires_at timestamptz,
          last_error text,
          provider_id text,
          provider_response jsonb,
          created_at timestamptz DEFAULT now(),
          updated_at timestamptz DEFAULT now(),
          delivered_at timestamptz
        )
      `)
      .then(() => undefined)
      .catch((err: unknown) => {
        tableEnsured = null;
        throw err;
      });
  }
  return tableEnsured;
}

export async function enqueueAlert(input: EnqueueInput): Promise<boolean> {
  await ensureAlertDeliveriesTable();
  const critical = input.critical ?? false;
  const expiresAt = critical
    ? null
    : new Date(Date.now() + DEFAULT_TTL_HOURS * 3600 * 1000);
  const inserted = await db
    .insert(alertDeliveriesTable)
    .values({
      idempotencyKey: input.idempotencyKey,
      channel: input.channel,
      kind: input.kind,
      severity: input.severity ?? "INFO",
      title: input.title.slice(0, 300),
      body: (input.body ?? "").slice(0, 2000),
      destination: input.destination,
      payload: input.payload ?? {},
      critical,
      maxAttempts: critical ? CRITICAL_MAX_ATTEMPTS : DEFAULT_MAX_ATTEMPTS,
      expiresAt,
    })
    .onConflictDoNothing({ target: alertDeliveriesTable.idempotencyKey })
    .returning({ id: alertDeliveriesTable.id });
  return inserted.length > 0;
}

export function backoffSeconds(attempts: number): number {
  const idx = Math.min(Math.max(attempts - 1, 0), BACKOFF_SECONDS.length - 1);
  return BACKOFF_SECONDS[idx]!;
}

interface AttemptOutcome {
  ok: boolean;
  permanent?: boolean;      // don't retry
  providerId?: string;
  providerResponse?: Record<string, unknown>;
  error?: string;
}

export type AttemptSender = (row: typeof alertDeliveriesTable.$inferSelect)
  => Promise<AttemptOutcome>;

/**
 * Process due deliveries for one channel using the given sender.
 * Never throws; returns counters for logging/monitoring.
 */
export async function processDueDeliveries(
  channel: AlertChannel,
  sender: AttemptSender,
  limit = 50,
): Promise<{ delivered: number; retried: number; failed: number; expired: number }> {
  const counters = { delivered: 0, retried: 0, failed: 0, expired: 0 };
  try {
    await ensureAlertDeliveriesTable();
    const now = new Date();
    // Queue timestamps default to PostgreSQL now() at microsecond precision.
    // A JS Date cutoff can precede an already committed enqueue within the
    // same millisecond. Compare in the database, without rounding stored data
    // or admitting future retries. Statement time also works in transactions.
    const databaseNow = sql`statement_timestamp()`;

    // Expire overdue non-critical rows first (critical never auto-expires).
    const expiredRows = await db
      .update(alertDeliveriesTable)
      .set({ status: "EXPIRED", updatedAt: now })
      .where(and(
        eq(alertDeliveriesTable.channel, channel),
        inArray(alertDeliveriesTable.status, ["QUEUED", "RETRY_SCHEDULED"]),
        eq(alertDeliveriesTable.critical, false),
        lte(alertDeliveriesTable.expiresAt, databaseNow),
      ))
      .returning({ id: alertDeliveriesTable.id });
    counters.expired = expiredRows.length;

    const due = await db
      .select()
      .from(alertDeliveriesTable)
      .where(and(
        eq(alertDeliveriesTable.channel, channel),
        inArray(alertDeliveriesTable.status, ["QUEUED", "RETRY_SCHEDULED"]),
        or(
          lte(alertDeliveriesTable.nextAttemptAt, databaseNow),
          sql`${alertDeliveriesTable.nextAttemptAt} IS NULL`,
        ),
      ))
      .orderBy(asc(alertDeliveriesTable.createdAt))
      .limit(limit);

    for (const row of due) {
      // Claim: only proceed if we flipped it to SENDING (guards double-send
      // across processes).
      const claimed = await db
        .update(alertDeliveriesTable)
        .set({ status: "SENDING", updatedAt: new Date() })
        .where(and(
          eq(alertDeliveriesTable.id, row.id),
          inArray(alertDeliveriesTable.status, ["QUEUED", "RETRY_SCHEDULED"]),
        ))
        .returning({ id: alertDeliveriesTable.id });
      if (claimed.length === 0) continue;

      const attempts = row.attempts + 1;
      let outcome: AttemptOutcome;
      try {
        outcome = await sender(row);
      } catch (err) {
        outcome = { ok: false, error: err instanceof Error ? err.message : String(err) };
      }

      const base = {
        attempts,
        updatedAt: new Date(),
        lastError: outcome.ok ? null : (outcome.error ?? "unknown error").slice(0, 500),
        providerId: outcome.providerId ?? row.providerId,
        providerResponse: outcome.providerResponse ?? row.providerResponse,
      };

      if (outcome.ok) {
        await db.update(alertDeliveriesTable)
          .set({ ...base, status: "DELIVERED", deliveredAt: new Date() })
          .where(eq(alertDeliveriesTable.id, row.id));
        counters.delivered++;
      } else if (outcome.permanent) {
        await db.update(alertDeliveriesTable)
          .set({ ...base, status: "FAILED" })
          .where(eq(alertDeliveriesTable.id, row.id));
        counters.failed++;
        logger.warn({ id: row.id, dest: truncateDestination(row.destination), error: base.lastError },
          "Alert delivery failed permanently");
      } else if (attempts >= row.maxAttempts) {
        await db.update(alertDeliveriesTable)
          .set({ ...base, status: "FAILED", deadLetter: true })
          .where(eq(alertDeliveriesTable.id, row.id));
        counters.failed++;
        logger.warn({ id: row.id, dest: truncateDestination(row.destination), attempts },
          "Alert delivery dead-lettered after exhausting retries");
      } else {
        const delay = backoffSeconds(attempts);
        await db.update(alertDeliveriesTable)
          .set({
            ...base,
            status: "RETRY_SCHEDULED",
            nextAttemptAt: new Date(Date.now() + delay * 1000),
          })
          .where(eq(alertDeliveriesTable.id, row.id));
        counters.retried++;
      }
    }
  } catch (err) {
    const cause = err instanceof Error && err.cause instanceof Error
      ? err.cause.message : undefined;
    logger.warn({ err: err instanceof Error ? err.message : String(err), cause },
      "Alert queue processing failed (will retry on next tick)");
  }
  return counters;
}
