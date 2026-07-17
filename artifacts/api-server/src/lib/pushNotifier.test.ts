import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { alertDeliveriesTable, db, pool, pushSubscriptionsTable, signalsCacheTable } from "@workspace/db";
import { eq, like } from "drizzle-orm";
import {
  dispatchSignalPushNotifications,
  ensurePushSubscriptionsTable,
} from "./pushNotifier";
import { ensureAlertDeliveriesTable } from "./alertQueue";

const TEST_TOKEN_PREFIX = "ExponentPushToken[vitest-push-";
const TEST_TOKEN_LIKE = "ExponentPushToken[vitest-push-%";
const SIGNALS_KEY = "signals";

function testToken(n: number): string {
  return `${TEST_TOKEN_PREFIX}${n}]`;
}

type FetchMock = ReturnType<typeof vi.fn>;

function okTickets(count: number) {
  return {
    ok: true,
    status: 200,
    json: async () => ({
      data: Array.from({ length: count }, () => ({ status: "ok" })),
    }),
  };
}

function mockFetchOk(): FetchMock {
  const mock = vi.fn(async (_url: unknown, init?: { body?: string }) => {
    const messages = JSON.parse(init?.body ?? "[]") as unknown[];
    return okTickets(messages.length);
  });
  vi.stubGlobal("fetch", mock);
  return mock;
}

interface BackedUpSub {
  token: string;
  minConfidence: number;
  enabled: boolean;
  lastNotifiedKey: string | null;
}

let originalSubs: BackedUpSub[] = [];
let originalSignalsRow: { payload: unknown; updatedAt: Date | null } | null = null;

async function setSignalsSnapshot(payload: unknown, updatedAt: Date): Promise<void> {
  await db
    .insert(signalsCacheTable)
    .values({ key: SIGNALS_KEY, payload, updatedAt })
    .onConflictDoUpdate({
      target: signalsCacheTable.key,
      set: { payload, updatedAt },
    });
}

async function insertSub(
  token: string,
  opts: { minConfidence?: number; enabled?: boolean; lastNotifiedKey?: string | null } = {},
): Promise<void> {
  await db.insert(pushSubscriptionsTable).values({
    token,
    minConfidence: opts.minConfidence ?? 70,
    enabled: opts.enabled ?? true,
    lastNotifiedKey: opts.lastNotifiedKey ?? null,
  });
}

async function getSub(token: string) {
  const [row] = await db
    .select()
    .from(pushSubscriptionsTable)
    .where(eq(pushSubscriptionsTable.token, token));
  return row;
}

async function clearTestState(): Promise<void> {
  // Remove every subscription so tests fully control who gets notified,
  // and clear queued deliveries for test tokens (Priority 4 durable queue).
  await db.delete(pushSubscriptionsTable);
  await db
    .delete(alertDeliveriesTable)
    .where(like(alertDeliveriesTable.destination, TEST_TOKEN_LIKE));
}

beforeAll(async () => {
  await ensurePushSubscriptionsTable();
  await ensureAlertDeliveriesTable();
  // Back up real dev data so tests leave the database untouched.
  originalSubs = (await db.select().from(pushSubscriptionsTable)).map((s) => ({
    token: s.token,
    minConfidence: s.minConfidence,
    enabled: s.enabled,
    lastNotifiedKey: s.lastNotifiedKey,
  }));
  const [row] = await db
    .select()
    .from(signalsCacheTable)
    .where(eq(signalsCacheTable.key, SIGNALS_KEY));
  originalSignalsRow = row ? { payload: row.payload, updatedAt: row.updatedAt } : null;
});

beforeEach(async () => {
  await clearTestState();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

afterAll(async () => {
  // Restore original state.
  await db.delete(pushSubscriptionsTable);
  await db.delete(pushSubscriptionsTable).where(like(pushSubscriptionsTable.token, TEST_TOKEN_LIKE));
  for (const s of originalSubs) {
    await db.insert(pushSubscriptionsTable).values(s);
  }
  if (originalSignalsRow) {
    await setSignalsSnapshot(
      originalSignalsRow.payload,
      originalSignalsRow.updatedAt ?? new Date(),
    );
  } else {
    await db.delete(signalsCacheTable).where(eq(signalsCacheTable.key, SIGNALS_KEY));
  }
  await pool.end();
});

describe("dispatchSignalPushNotifications", () => {
  it("does nothing when there are no enabled subscriptions", async () => {
    const fetchMock = mockFetchOk();
    await setSignalsSnapshot(
      [{ stock: "RELIANCE", final_action: "BUY", confidence: 95 }],
      new Date(),
    );
    // One disabled subscription — must be ignored entirely.
    await insertSub(testToken(1), { enabled: false });

    await dispatchSignalPushNotifications();

    expect(fetchMock).not.toHaveBeenCalled();
    const sub = await getSub(testToken(1));
    expect(sub?.lastNotifiedKey).toBeNull();
  });

  it("does nothing (and records nothing) when the signals cache row is missing", async () => {
    const fetchMock = mockFetchOk();
    await db.delete(signalsCacheTable).where(eq(signalsCacheTable.key, SIGNALS_KEY));
    await insertSub(testToken(1));

    await dispatchSignalPushNotifications();

    expect(fetchMock).not.toHaveBeenCalled();
    const sub = await getSub(testToken(1));
    expect(sub?.lastNotifiedKey).toBeNull();
  });

  it("records the snapshot key even when no signals match, so the scan is never re-considered", async () => {
    const fetchMock = mockFetchOk();
    const snapshotTs = new Date("2026-07-17T04:00:00.000Z");
    // Signals below the subscriber's threshold plus a HOLD (never actionable).
    await setSignalsSnapshot(
      [
        { stock: "TCS", final_action: "BUY", confidence: 55 },
        { stock: "INFY", final_action: "HOLD", confidence: 99 },
      ],
      snapshotTs,
    );
    await insertSub(testToken(1), { minConfidence: 70 });

    await dispatchSignalPushNotifications();

    expect(fetchMock).not.toHaveBeenCalled();
    const sub = await getSub(testToken(1));
    expect(sub?.lastNotifiedKey).toBe(snapshotTs.toISOString());

    // Dispatching again for the same snapshot stays a no-op.
    await dispatchSignalPushNotifications();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("handles an empty signals snapshot without sending, while recording the key", async () => {
    const fetchMock = mockFetchOk();
    const snapshotTs = new Date("2026-07-17T04:05:00.000Z");
    await setSignalsSnapshot([], snapshotTs);
    await insertSub(testToken(1));

    await dispatchSignalPushNotifications();

    expect(fetchMock).not.toHaveBeenCalled();
    expect((await getSub(testToken(1)))?.lastNotifiedKey).toBe(snapshotTs.toISOString());
  });

  it("sends matching signals exactly once per snapshot (dedupe across repeated scans)", async () => {
    const fetchMock = mockFetchOk();
    const snapshotTs = new Date("2026-07-17T04:10:00.000Z");
    await setSignalsSnapshot(
      [
        { stock: "RELIANCE", final_action: "BUY", confidence: 92, price: 2900 },
        { stock: "HDFCBANK", final_action: "SELL", confidence: 81 },
        { stock: "TCS", final_action: "BUY", confidence: 40 },
      ],
      snapshotTs,
    );
    await insertSub(testToken(1), { minConfidence: 70 });

    await dispatchSignalPushNotifications();

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const body = JSON.parse(
      (fetchMock.mock.calls[0]![1] as { body: string }).body,
    ) as Array<Record<string, unknown>>;
    expect(body).toHaveLength(1);
    expect(body[0]!["to"]).toBe(testToken(1));
    expect(String(body[0]!["title"])).toContain("2 high-confidence signals");
    expect(String(body[0]!["body"])).toContain("RELIANCE: BUY (92%)");
    expect(String(body[0]!["body"])).not.toContain("TCS");
    expect((await getSub(testToken(1)))?.lastNotifiedKey).toBe(snapshotTs.toISOString());

    // Same snapshot again → no second push.
    await dispatchSignalPushNotifications();
    expect(fetchMock).toHaveBeenCalledTimes(1);

    // A newer snapshot → notified again.
    const nextTs = new Date("2026-07-17T04:20:00.000Z");
    await setSignalsSnapshot(
      [{ stock: "INFY", final_action: "BUY", confidence: 88 }],
      nextTs,
    );
    await dispatchSignalPushNotifications();
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect((await getSub(testToken(1)))?.lastNotifiedKey).toBe(nextTs.toISOString());
  });

  it("respects each subscriber's own min_confidence threshold", async () => {
    const fetchMock = mockFetchOk();
    const snapshotTs = new Date("2026-07-17T04:30:00.000Z");
    await setSignalsSnapshot(
      [{ stock: "RELIANCE", final_action: "BUY", confidence: 75 }],
      snapshotTs,
    );
    await insertSub(testToken(1), { minConfidence: 70 }); // matches
    await insertSub(testToken(2), { minConfidence: 90 }); // does not match

    await dispatchSignalPushNotifications();

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const body = JSON.parse(
      (fetchMock.mock.calls[0]![1] as { body: string }).body,
    ) as Array<Record<string, unknown>>;
    expect(body.map((m) => m["to"])).toEqual([testToken(1)]);
    // Both subs still get the snapshot recorded.
    expect((await getSub(testToken(2)))?.lastNotifiedKey).toBe(snapshotTs.toISOString());
  });

  it("deletes tokens that Expo reports as DeviceNotRegistered and fails the delivery permanently", async () => {
    const snapshotTs = new Date("2026-07-17T04:40:00.000Z");
    await setSignalsSnapshot(
      [{ stock: "RELIANCE", final_action: "BUY", confidence: 95 }],
      snapshotTs,
    );
    await insertSub(testToken(1));
    await insertSub(testToken(2));

    const fetchMock = vi.fn(async (_url: unknown, init?: { body?: string }) => {
      const messages = JSON.parse(init?.body ?? "[]") as Array<{ to: string }>;
      return {
        ok: true,
        status: 200,
        json: async () => ({
          data: messages.map((m) =>
            m.to === testToken(1)
              ? { status: "error", message: "gone", details: { error: "DeviceNotRegistered" } }
              : { status: "ok" },
          ),
        }),
      };
    });
    vi.stubGlobal("fetch", fetchMock);

    await dispatchSignalPushNotifications();

    // Queue processes one delivery per request now.
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(await getSub(testToken(1))).toBeUndefined(); // deleted
    expect(await getSub(testToken(2))).toBeDefined(); // kept

    const [failedRow] = await db
      .select()
      .from(alertDeliveriesTable)
      .where(eq(alertDeliveriesTable.destination, testToken(1)));
    expect(failedRow?.status).toBe("FAILED");
    expect(failedRow?.deadLetter).toBe(false); // permanent, not dead-lettered
    const [okRow] = await db
      .select()
      .from(alertDeliveriesTable)
      .where(eq(alertDeliveriesTable.destination, testToken(2)));
    expect(okRow?.status).toBe("DELIVERED");
  });

  it("delivers to every subscriber, one queued delivery per device", async () => {
    const fetchMock = mockFetchOk();
    const snapshotTs = new Date("2026-07-17T04:50:00.000Z");
    await setSignalsSnapshot(
      [{ stock: "RELIANCE", final_action: "BUY", confidence: 95 }],
      snapshotTs,
    );
    const total = 105;
    for (let i = 0; i < total; i++) {
      await insertSub(testToken(i));
    }

    await dispatchSignalPushNotifications();

    // One send per queued delivery; all drained in a single dispatch.
    expect(fetchMock).toHaveBeenCalledTimes(total);
    const firstBody = JSON.parse(
      (fetchMock.mock.calls[0]![1] as { body: string }).body,
    ) as unknown[];
    expect(firstBody).toHaveLength(1);
  });

  it("schedules a retry (does not lose the alert) when the push service is down", async () => {
    const snapshotTs = new Date("2026-07-17T05:00:00.000Z");
    await setSignalsSnapshot(
      [{ stock: "RELIANCE", final_action: "BUY", confidence: 95 }],
      snapshotTs,
    );
    await insertSub(testToken(1));

    const fetchMock = vi.fn(async () => ({ ok: false, status: 500, json: async () => ({}) }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(dispatchSignalPushNotifications()).resolves.toBeUndefined();
    expect(fetchMock).toHaveBeenCalledTimes(1);

    // Priority 4 (#41): the failed delivery is retained with backoff — not
    // dropped. Its next attempt is in the future, so an immediate
    // re-dispatch does NOT hammer the provider (and idempotency prevents a
    // duplicate row for the same snapshot).
    const [row] = await db
      .select()
      .from(alertDeliveriesTable)
      .where(eq(alertDeliveriesTable.destination, testToken(1)));
    expect(row?.status).toBe("RETRY_SCHEDULED");
    expect(row?.attempts).toBe(1);
    expect(row?.lastError).toBeTruthy();
    expect(row!.nextAttemptAt!.getTime()).toBeGreaterThan(Date.now());

    await dispatchSignalPushNotifications();
    expect(fetchMock).toHaveBeenCalledTimes(1);

    // Once due (simulate backoff elapsed), the retry goes out and delivers.
    await db
      .update(alertDeliveriesTable)
      .set({ nextAttemptAt: new Date(Date.now() - 1000) })
      .where(eq(alertDeliveriesTable.id, row!.id));
    const okMock = mockFetchOk();
    await dispatchSignalPushNotifications();
    expect(okMock).toHaveBeenCalledTimes(1);
    const [after] = await db
      .select()
      .from(alertDeliveriesTable)
      .where(eq(alertDeliveriesTable.id, row!.id));
    expect(after?.status).toBe("DELIVERED");
    expect(after?.attempts).toBe(2);
    expect(after?.deliveredAt).toBeTruthy();
  });
});
