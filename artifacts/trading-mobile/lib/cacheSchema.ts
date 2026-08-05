/**
 * Versioned schema + validation for offline cache records (Priority 7 / #37).
 *
 * Every persisted snapshot is wrapped in a versioned envelope. Records are
 * validated before use; incompatible or corrupted records are rejected —
 * screens then show a clear UNAVAILABLE state instead of wrong data.
 * Incompatible fields are never silently reinterpreted.
 */

export const CACHE_SCHEMA_VERSION = 2;

/** Oldest envelope version we can still migrate safely. Version 1 is the
 * legacy un-versioned `{ data, ts }` shape. */
export const MIN_COMPATIBLE_VERSION = 1;

export interface CacheEnvelope<T> {
  v: number;
  data: T;
  ts: number;
}

export type CacheReadResult<T> =
  | { ok: true; data: T; ts: number; migrated: boolean }
  | { ok: false; reason: "corrupt" | "incompatible" | "invalid-payload" | "missing-fields" };

type PayloadValidator = (data: unknown) => boolean;

const isPlainObject = (d: unknown): d is Record<string, unknown> =>
  typeof d === "object" && d !== null && !Array.isArray(d);

/**
 * Per-key payload validators. Each checks the fields screens actually rely
 * on, so an API schema change is rejected rather than misrendered.
 */
const PAYLOAD_VALIDATORS: Record<string, PayloadValidator> = {
  notifications: (d) => Array.isArray(d),
  trades: (d) => Array.isArray(d),
  "phase20-positions": (d) => isPlainObject(d) && Array.isArray((d as { positions?: unknown }).positions),
  signals: (d) => Array.isArray(d) || (isPlainObject(d) && Array.isArray((d as { signals?: unknown }).signals)),
  "trade-decisions": (d) =>
    Array.isArray(d) || (isPlainObject(d) && Array.isArray((d as { decisions?: unknown }).decisions)),
  "health-live": isPlainObject,
  "health-sched": isPlainObject,
  "health-settings": isPlainObject,
  "health-kite": isPlainObject,
  "health-kill": isPlainObject,
  "health-broker": isPlainObject,
  "ops-centre-snapshot": (d) => {
    if (!isPlainObject(d)) return false;
    const obj = d as Record<string, unknown>;
    // Validate all fields the Pipeline tab screen renders.
    return (
      typeof obj.generated_at === "string" &&
      isPlainObject(obj.platform) &&
      typeof (obj.platform as Record<string, unknown>).health_pct === "number" &&
      isPlainObject(obj.agents) &&
      isPlainObject(obj.pipeline) &&
      Array.isArray(obj.pipeline_nodes)
    );
  },
};

function payloadValid(key: string, data: unknown): boolean {
  const validator = PAYLOAD_VALIDATORS[key];
  if (validator) return validator(data);
  return data !== undefined && data !== null;
}

/** Serialize a payload into the current versioned envelope. */
export function encodeSnapshot<T>(data: T, ts: number): string {
  const envelope: CacheEnvelope<T> = { v: CACHE_SCHEMA_VERSION, data, ts };
  return JSON.stringify(envelope);
}

/**
 * Parse, version-check, migrate (when safe) and validate a raw cache record.
 * Any failure is an explicit rejection — never a silent reinterpretation.
 */
export function decodeSnapshot<T>(key: string, raw: string | null | undefined): CacheReadResult<T> {
  if (raw == null || raw === "") return { ok: false, reason: "corrupt" };

  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    return { ok: false, reason: "corrupt" };
  }
  if (!isPlainObject(parsed)) return { ok: false, reason: "corrupt" };

  const obj = parsed as { v?: unknown; data?: unknown; ts?: unknown };
  let version: number;
  let migrated = false;

  if (obj.v === undefined) {
    // Legacy version-1 record: un-versioned { data, ts }.
    version = 1;
  } else if (typeof obj.v === "number" && Number.isInteger(obj.v)) {
    version = obj.v;
  } else {
    return { ok: false, reason: "corrupt" };
  }

  if (version < MIN_COMPATIBLE_VERSION || version > CACHE_SCHEMA_VERSION) {
    return { ok: false, reason: "incompatible" };
  }

  if (version < CACHE_SCHEMA_VERSION) {
    // v1 → v2 migration: same fields, envelope gains explicit `v`.
    migrated = true;
  }

  if (typeof obj.ts !== "number" || !Number.isFinite(obj.ts) || obj.ts <= 0) {
    return { ok: false, reason: "missing-fields" };
  }
  if (obj.data === undefined) {
    return { ok: false, reason: "missing-fields" };
  }
  if (!payloadValid(key, obj.data)) {
    return { ok: false, reason: "invalid-payload" };
  }

  return { ok: true, data: obj.data as T, ts: obj.ts, migrated };
}
