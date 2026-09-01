import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { alertDeliveriesTable, db, pool, pushSubscriptionsTable, signalsCacheTable } from "@workspace/db";
import { eq } from "drizzle-orm";
import {
  dispatchSignalPushNotifications,
  dispatchHealthAlertPushNotifications,
  ensurePushSubscriptionsTable,
  _resetPlatformDegradedStateForTests,
  _resetInMemoryHealthStateOnlyForTests,
  type OpsHealthSnapshot,
} from "./pushNotifier";
import { ensureAlertDeliveriesTable } from "./alertQueue";

// This suite must never borrow a developer or production DATABASE_URL.
vi.mock("@workspace/db", async () => {
  const raw = process.env.TASK967_TEST_DATABASE_URL;
  if (!raw) throw new Error("Disposable PostgreSQL required: set TASK967_TEST_DATABASE_URL");
  const url = new URL(raw);
  if (!["postgres:", "postgresql:"].includes(url.protocol) || url.search || url.hash ||
      !["127.0.0.1", "localhost", "[::1]"].includes(url.hostname) ||
      !/^\/task967_disposable(?:_[a-z0-9_]+)?$/.test(url.pathname)) {
    throw new Error("Only an explicitly named local task967_disposable database is accepted");
  }
  const [{ default: pg }, { drizzle }, schema] = await Promise.all([
    import("pg"), import("drizzle-orm/node-postgres"), import("@workspace/db/schema"),
  ]);
  const isolatedPool = new pg.Pool({ connectionString: raw, max: 1 });
  return { ...schema, pool: isolatedPool, db: drizzle(isolatedPool, { schema }) };
});

const TEST_TOKEN_PREFIX = "ExponentPushToken[vitest-push-";
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
  opts: { minConfidence?: number; minHealthPct?: number; enabled?: boolean; lastNotifiedKey?: string | null } = {},
): Promise<void> {
  await db.insert(pushSubscriptionsTable).values({
    token,
    minConfidence: opts.minConfidence ?? 70,
    minHealthPct: opts.minHealthPct ?? 70,
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

let templateSchema: string;
let schemaSequence = 0;
const suiteId = `task967_push_${process.pid}_${Date.now()}`;

beforeAll(async () => {
  templateSchema = `${suiteId}_template`;
  await pool.query(`CREATE SCHEMA "${templateSchema}"`);
  await pool.query(`SET search_path TO "${templateSchema}"`);
  await ensurePushSubscriptionsTable();
  await ensureAlertDeliveriesTable();
  await pool.query(`CREATE TABLE signals_cache (
    key text PRIMARY KEY, payload jsonb NOT NULL,
    updated_at timestamp with time zone DEFAULT now()
  )`);
});

beforeEach(async () => {
  // New empty schema per test: no DELETE/TRUNCATE cleanup or shared dev data.
  const schema = `${suiteId}_${++schemaSequence}`;
  await pool.query(`CREATE SCHEMA "${schema}"`);
  for (const table of ["push_subscriptions", "alert_deliveries", "signals_cache"]) {
    await pool.query(`CREATE TABLE "${schema}"."${table}"
      (LIKE "${templateSchema}"."${table}" INCLUDING ALL)`);
  }
  await pool.query(`SET search_path TO "${schema}"`);
});

afterEach(() => { vi.unstubAllGlobals(); });
afterAll(async () => { await pool.end(); });

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

// ── dispatchHealthAlertPushNotifications ──────────────────────────────────────

const HEALTH_TOKEN_PREFIX = "ExponentPushToken[vitest-health-";
const HEALTH_TOKEN_LIKE = "ExponentPushToken[vitest-health-%";

function healthToken(n: number): string {
  return `${HEALTH_TOKEN_PREFIX}${n}]`;
}

function degradedSnapshot(
  healthPct: number,
  errorAgentNames: string[] = [],
  scanId = "scan-abc-123",
): OpsHealthSnapshot {
  const agents: Record<string, { status: string; name: string }> = {};
  const allNames = [
    "supervisor", "market_data", "research", "market_intelligence",
    "monitoring", "strategy", "risk", "ai_decision",
    "execution", "learning", "knowledge", "operations",
  ];
  for (const key of allNames) {
    const isError = errorAgentNames.some(
      (n) => n.toLowerCase() === key.toLowerCase() || n.toLowerCase().replace(/ /g, "_") === key,
    );
    agents[key] = {
      status: isError ? "ERROR" : "ACTIVE",
      name: key.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase()),
    };
  }
  return { platform: { health_pct: healthPct, scan_id: scanId }, agents };
}

async function insertHealthSub(
  n: number,
  opts: { enabled?: boolean; minHealthPct?: number } = {},
): Promise<void> {
  await insertSub(healthToken(n), {
    enabled: opts.enabled ?? true,
    minHealthPct: opts.minHealthPct,
  });
}

describe("dispatchHealthAlertPushNotifications", () => {
  beforeEach(async () => {
    // Clear health-alert test tokens in addition to the standard cleanup.
    await db
      .delete(alertDeliveriesTable)
      .where(like(alertDeliveriesTable.destination, HEALTH_TOKEN_LIKE));
    await db.delete(pushSubscriptionsTable);
    // Reset in-process degraded-token set AND the persisted ops_health_state
    // key so tests that write to DB don't leak state into subsequent tests.
    await _resetPlatformDegradedStateForTests();
  });

  afterEach(async () => {
    // Ensure health token rows are removed after each test.
    await db
      .delete(alertDeliveriesTable)
      .where(like(alertDeliveriesTable.destination, HEALTH_TOKEN_LIKE));
    vi.unstubAllEnvs();
  });

  it("does nothing when platform health is ≥ 70 and no agents are in ERROR", async () => {
    const fetchMock = mockFetchOk();
    await insertHealthSub(1);

    await dispatchHealthAlertPushNotifications(
      degradedSnapshot(85),  // healthy
    );

    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("does nothing when OPS_HEALTH_ALERTS_ENABLED=false", async () => {
    const fetchMock = mockFetchOk();
    vi.stubEnv("OPS_HEALTH_ALERTS_ENABLED", "false");
    await insertHealthSub(1);

    await dispatchHealthAlertPushNotifications(degradedSnapshot(40));

    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("does nothing when there are no enabled subscriptions", async () => {
    const fetchMock = mockFetchOk();
    await insertHealthSub(1, { enabled: false });

    await dispatchHealthAlertPushNotifications(degradedSnapshot(50));

    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("sends one alert per enabled subscriber when health_pct < 70", async () => {
    const fetchMock = mockFetchOk();
    await insertHealthSub(1);
    await insertHealthSub(2);

    await dispatchHealthAlertPushNotifications(degradedSnapshot(55, [], "scan-001"));

    // One fetch call per queued delivery (two subscribers)
    expect(fetchMock).toHaveBeenCalledTimes(2);
    const sentBody = JSON.parse(
      (fetchMock.mock.calls[0]![1] as { body: string }).body,
    ) as Array<Record<string, unknown>>;
    expect(sentBody).toHaveLength(1);
    const msg = sentBody[0]!;
    expect(String(msg["title"])).toContain("55%");
    const data = msg["data"] as Record<string, unknown>;
    expect(data["screen"]).toBe("ai-ops");
    expect(data["healthPct"]).toBe(55);
  });

  it("includes ERROR agent names in the notification body", async () => {
    const fetchMock = mockFetchOk();
    await insertHealthSub(1);

    await dispatchHealthAlertPushNotifications(
      degradedSnapshot(80, ["risk", "strategy"], "scan-002"),
    );

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const body = JSON.parse(
      (fetchMock.mock.calls[0]![1] as { body: string }).body,
    ) as Array<Record<string, unknown>>;
    const msg = body[0]!;
    expect(String(msg["title"])).toContain("2 agent");
    expect(String(msg["body"])).toMatch(/risk|strategy/i);
    const data = msg["data"] as Record<string, unknown>;
    expect(data["screen"]).toBe("ai-ops");
  });

  it("is idempotent: same scan_id is never sent twice (deduped by idempotency key)", async () => {
    const fetchMock = mockFetchOk();
    await insertHealthSub(1);
    const snap = degradedSnapshot(40, [], "scan-dedupe");

    await dispatchHealthAlertPushNotifications(snap);
    expect(fetchMock).toHaveBeenCalledTimes(1);

    // Second call with the same scan_id — idempotency key prevents a second row.
    await dispatchHealthAlertPushNotifications(snap);
    expect(fetchMock).toHaveBeenCalledTimes(1);  // no additional send
  });

  it("sends again for a different scan_id", async () => {
    const fetchMock = mockFetchOk();
    await insertHealthSub(1);

    await dispatchHealthAlertPushNotifications(degradedSnapshot(40, [], "scan-A"));
    expect(fetchMock).toHaveBeenCalledTimes(1);

    await dispatchHealthAlertPushNotifications(degradedSnapshot(40, [], "scan-B"));
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("fires even when health_pct ≥ 70 but an agent is in ERROR", async () => {
    const fetchMock = mockFetchOk();
    await insertHealthSub(1);

    await dispatchHealthAlertPushNotifications(
      degradedSnapshot(75, ["risk"], "scan-error-only"),
    );

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const msg = JSON.parse(
      (fetchMock.mock.calls[0]![1] as { body: string }).body,
    )[0] as Record<string, unknown>;
    expect(String(msg["title"])).toContain("agent");
    expect(String(msg["title"])).toContain("error");
  });

  // ── Recovery-push precision tests (Task 371) ─────────────────────────────

  it("recovery: skips the recovery push when the platform was never degraded", async () => {
    await _resetPlatformDegradedStateForTests();
    const fetchMock = mockFetchOk();
    await insertHealthSub(1);

    // Healthy snapshot on a session that was never degraded — no alert,
    // no recovery, nothing should be enqueued or delivered.
    await dispatchHealthAlertPushNotifications(
      degradedSnapshot(85, [], "scan-healthy-only"),
    );

    // Nothing should have been enqueued (no delivery row) and fetch untouched.
    expect(fetchMock).not.toHaveBeenCalled();
    const rows = await db
      .select()
      .from(alertDeliveriesTable)
      .where(eq(alertDeliveriesTable.destination, healthToken(1)));
    expect(rows).toHaveLength(0);
  });

  it("recovery: fires exactly one recovery push per device when health climbs back above the threshold", async () => {
    await _resetPlatformDegradedStateForTests();
    await insertHealthSub(1);
    await insertHealthSub(2);

    const fetchMock = mockFetchOk();

    // Step 1 — degrade: both subscribers are alerted.
    await dispatchHealthAlertPushNotifications(
      degradedSnapshot(50, [], "scan-degrade-r1"),
    );
    // Two degradation deliveries were enqueued and processed.
    expect(fetchMock).toHaveBeenCalledTimes(2);

    // Step 2 — recover: health climbs above the threshold.
    fetchMock.mockClear();
    await dispatchHealthAlertPushNotifications(
      degradedSnapshot(90, [], "scan-recover-r1"),
    );

    // Exactly one recovery push per device (two devices total).
    expect(fetchMock).toHaveBeenCalledTimes(2);

    // Verify the recovery message content for the first call.
    const msg = JSON.parse(
      (fetchMock.mock.calls[0]![1] as { body: string }).body,
    )[0] as Record<string, unknown>;
    expect(String(msg["title"])).toMatch(/recover/i);
    expect(String(msg["title"])).toContain("90%");

    // Both tokens have a recovery delivery row in the DB.
    const rows = await db
      .select()
      .from(alertDeliveriesTable)
      .where(like(alertDeliveriesTable.destination, HEALTH_TOKEN_LIKE));
    const recoveryRows = rows.filter((r) =>
      r.idempotencyKey?.startsWith("health_recovery:"),
    );
    expect(recoveryRows).toHaveLength(2);
    expect(recoveryRows.every((r) => r.status === "DELIVERED")).toBe(true);
  });

  it("recovery: a second healthy snapshot after recovery does not re-fire the recovery push", async () => {
    await _resetPlatformDegradedStateForTests();
    await insertHealthSub(1);

    const fetchMock = mockFetchOk();

    // Step 1 — degrade.
    await dispatchHealthAlertPushNotifications(
      degradedSnapshot(45, [], "scan-degrade-r2"),
    );
    expect(fetchMock).toHaveBeenCalledTimes(1);

    // Step 2 — first recovery snapshot: exactly one recovery push.
    fetchMock.mockClear();
    await dispatchHealthAlertPushNotifications(
      degradedSnapshot(88, [], "scan-recover-r2"),
    );
    expect(fetchMock).toHaveBeenCalledTimes(1);

    // Step 3 — second healthy snapshot: token is no longer in degraded set,
    // so no degradation alert and no further recovery push should be sent.
    fetchMock.mockClear();
    await dispatchHealthAlertPushNotifications(
      degradedSnapshot(95, [], "scan-healthy-again-r2"),
    );
    expect(fetchMock).not.toHaveBeenCalled();

    // Confirm there is still only one recovery row in the DB.
    const rows = await db
      .select()
      .from(alertDeliveriesTable)
      .where(like(alertDeliveriesTable.destination, HEALTH_TOKEN_LIKE));
    const recoveryRows = rows.filter((r) =>
      r.idempotencyKey?.startsWith("health_recovery:"),
    );
    expect(recoveryRows).toHaveLength(1);
  });

  it("recovery: fires the recovery push when the server restarts mid-incident (DB state survives)", async () => {
    await insertHealthSub(1);
    await insertHealthSub(2);

    const fetchMock = mockFetchOk();

    // Step 1 — degrade: both tokens are written to degradedSubscriberTokens
    // and persisted to signals_cache key "ops_health_state".
    await dispatchHealthAlertPushNotifications(
      degradedSnapshot(50, [], "scan-pre-restart"),
    );
    expect(fetchMock).toHaveBeenCalledTimes(2);

    // Step 2 — simulate a server restart: wipe only the in-process Set and
    // load flags (DB record is intentionally left intact).
    _resetInMemoryHealthStateOnlyForTests();

    // Step 3 — recovery snapshot arrives after the simulated restart.
    // loadHealthStateFromDb() re-populates degradedSubscriberTokens from DB,
    // so both tokens are still considered "was alerted" and each receives a
    // recovery push.
    fetchMock.mockClear();
    await dispatchHealthAlertPushNotifications(
      degradedSnapshot(92, [], "scan-post-restart"),
    );
    expect(fetchMock).toHaveBeenCalledTimes(2);

    // Verify recovery message content.
    const msg = JSON.parse(
      (fetchMock.mock.calls[0]![1] as { body: string }).body,
    )[0] as Record<string, unknown>;
    expect(String(msg["title"])).toMatch(/recover/i);
    expect(String(msg["title"])).toContain("92%");

    // Both tokens must have a recovery delivery row in the DB.
    const rows = await db
      .select()
      .from(alertDeliveriesTable)
      .where(like(alertDeliveriesTable.destination, HEALTH_TOKEN_LIKE));
    const recoveryRows = rows.filter((r) =>
      r.idempotencyKey?.startsWith("health_recovery:"),
    );
    expect(recoveryRows).toHaveLength(2);
    expect(recoveryRows.every((r) => r.status === "DELIVERED")).toBe(true);
  });

  // ── Per-subscriber minHealthPct threshold tests (Task 373) ──────────────────

  it("skips a subscriber when healthPct >= their minHealthPct and no agent errors", async () => {
    const fetchMock = mockFetchOk();
    // minHealthPct=70, healthPct=75 → 75 >= 70 → subDegraded=false, hasErrors=false → skip
    await insertHealthSub(1, { minHealthPct: 70 });

    await dispatchHealthAlertPushNotifications(
      degradedSnapshot(75, [], "scan-thresh-skip"),
    );

    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("alerts a subscriber when healthPct < their minHealthPct even when health is above the default 70% floor", async () => {
    const fetchMock = mockFetchOk();
    // minHealthPct=90, healthPct=75 → 75 < 90 → subDegraded=true → alert sent
    await insertHealthSub(1, { minHealthPct: 90 });

    await dispatchHealthAlertPushNotifications(
      degradedSnapshot(75, [], "scan-thresh-alert"),
    );

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const msg = JSON.parse(
      (fetchMock.mock.calls[0]![1] as { body: string }).body,
    )[0] as Record<string, unknown>;
    expect(String(msg["title"])).toContain("75%");
    const data = msg["data"] as Record<string, unknown>;
    expect(data["screen"]).toBe("ai-ops");
    expect(data["healthPct"]).toBe(75);
  });

  it("alerts ALL subscribers when agents are in ERROR regardless of their minHealthPct threshold", async () => {
    const fetchMock = mockFetchOk();
    // Both subscribers have 70% threshold — health at 75 is above their floor
    // so without errors neither would receive an alert. Agent errors force shouldAlert for all.
    await insertHealthSub(1, { minHealthPct: 70 });
    await insertHealthSub(2, { minHealthPct: 70 });

    await dispatchHealthAlertPushNotifications(
      degradedSnapshot(75, ["risk"], "scan-errors-override-thresh"),
    );

    // Both subscribers must be alerted even though healthPct (75) >= minHealthPct (70)
    expect(fetchMock).toHaveBeenCalledTimes(2);
    const msg = JSON.parse(
      (fetchMock.mock.calls[0]![1] as { body: string }).body,
    )[0] as Record<string, unknown>;
    // Title reflects error-only path (health not degraded below their threshold)
    expect(String(msg["title"])).toMatch(/agent|error/i);
    const data = msg["data"] as Record<string, unknown>;
    expect(data["screen"]).toBe("ai-ops");
    expect((data["errorAgents"] as string[]).length).toBeGreaterThan(0);
  });

  it("schedules a retry (does not lose the health alert) when the push service is down", async () => {
    await _resetPlatformDegradedStateForTests();
    await insertHealthSub(1);

    // Expo is down — every push attempt gets a 500.
    const fetchMock = vi.fn(async () => ({ ok: false, status: 500, json: async () => ({}) }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(
      dispatchHealthAlertPushNotifications(degradedSnapshot(40, [], "scan-retry-down")),
    ).resolves.toBeUndefined();

    // One attempt was made before the 500 was recorded.
    expect(fetchMock).toHaveBeenCalledTimes(1);

    // The delivery row must be retained as RETRY_SCHEDULED — not dropped.
    const [row] = await db
      .select()
      .from(alertDeliveriesTable)
      .where(eq(alertDeliveriesTable.destination, healthToken(1)));
    expect(row?.status).toBe("RETRY_SCHEDULED");
    expect(row?.attempts).toBe(1);
    expect(row?.lastError).toBeTruthy();
    expect(row!.nextAttemptAt!.getTime()).toBeGreaterThan(Date.now());

    // An immediate re-dispatch must NOT hammer the provider (backoff not elapsed).
    await dispatchHealthAlertPushNotifications(degradedSnapshot(40, [], "scan-retry-down-2"));
    // The first scan's row is still in backoff; the second scan enqueues a new
    // row but the first one is not retried yet — fetch call count stays at 2
    // (one new enqueue attempt for scan-retry-down-2 fired, original still gated).
    const callCountAfterSecondDispatch = fetchMock.mock.calls.length;
    expect(callCountAfterSecondDispatch).toBeLessThanOrEqual(2);

    // Once the backoff window elapses, re-running the queue delivers successfully.
    await db
      .update(alertDeliveriesTable)
      .set({ nextAttemptAt: new Date(Date.now() - 1000) })
      .where(eq(alertDeliveriesTable.id, row!.id));

    const okMock = mockFetchOk();
    await dispatchHealthAlertPushNotifications(degradedSnapshot(40, [], "scan-retry-down-3"));

    // The overdue row is now retried and delivered.
    expect(okMock).toHaveBeenCalled();
    const [after] = await db
      .select()
      .from(alertDeliveriesTable)
      .where(eq(alertDeliveriesTable.id, row!.id));
    expect(after?.status).toBe("DELIVERED");
    expect(after?.attempts).toBe(2);
    expect(after?.deliveredAt).toBeTruthy();
  });
});
