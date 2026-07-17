import { describe, expect, it } from "vitest";

import {
  CACHE_SCHEMA_VERSION,
  decodeSnapshot,
  encodeSnapshot,
} from "../cacheSchema";

describe("offline cache schema (Priority 7 / #37)", () => {
  it("accepts a current-version record round-trip", () => {
    const raw = encodeSnapshot([{ id: "n1" }], 1_700_000_000_000);
    const res = decodeSnapshot<unknown[]>("notifications", raw);
    expect(res.ok).toBe(true);
    if (res.ok) {
      expect(res.data).toEqual([{ id: "n1" }]);
      expect(res.ts).toBe(1_700_000_000_000);
      expect(res.migrated).toBe(false);
    }
  });

  it("migrates an old compatible (v1 un-versioned) record", () => {
    const legacy = JSON.stringify({ data: [{ id: "n1" }], ts: 1_700_000_000_000 });
    const res = decodeSnapshot<unknown[]>("notifications", legacy);
    expect(res.ok).toBe(true);
    if (res.ok) {
      expect(res.migrated).toBe(true);
      expect(res.data).toEqual([{ id: "n1" }]);
    }
  });

  it("rejects an incompatible future cache version", () => {
    const future = JSON.stringify({ v: CACHE_SCHEMA_VERSION + 1, data: [], ts: Date.now() });
    const res = decodeSnapshot("notifications", future);
    expect(res).toEqual({ ok: false, reason: "incompatible" });
  });

  it("rejects corrupt records (bad JSON, non-object, empty, bad version type)", () => {
    expect(decodeSnapshot("trades", "{not json").ok).toBe(false);
    expect(decodeSnapshot("trades", "42").ok).toBe(false);
    expect(decodeSnapshot("trades", "")).toEqual({ ok: false, reason: "corrupt" });
    expect(decodeSnapshot("trades", null)).toEqual({ ok: false, reason: "corrupt" });
    expect(decodeSnapshot("trades", JSON.stringify({ v: "two", data: [], ts: 1 }))).toEqual({
      ok: false,
      reason: "corrupt",
    });
  });

  it("rejects partial records (missing ts or data)", () => {
    expect(decodeSnapshot("trades", JSON.stringify({ v: 2, data: [] }))).toEqual({
      ok: false,
      reason: "missing-fields",
    });
    expect(decodeSnapshot("trades", JSON.stringify({ v: 2, ts: Date.now() }))).toEqual({
      ok: false,
      reason: "missing-fields",
    });
    expect(decodeSnapshot("trades", JSON.stringify({ v: 2, data: [], ts: -5 }))).toEqual({
      ok: false,
      reason: "missing-fields",
    });
  });

  it("rejects records whose payload no longer matches the key's required fields", () => {
    // notifications must be an array — an object is an API schema change.
    const changed = JSON.stringify({ v: CACHE_SCHEMA_VERSION, data: { items: [] }, ts: Date.now() });
    expect(decodeSnapshot("notifications", changed)).toEqual({ ok: false, reason: "invalid-payload" });

    // phase20-positions must contain a positions array.
    const missingField = JSON.stringify({
      v: CACHE_SCHEMA_VERSION,
      data: { summary: { total_pnl: 0 } },
      ts: Date.now(),
    });
    expect(decodeSnapshot("phase20-positions", missingField)).toEqual({
      ok: false,
      reason: "invalid-payload",
    });
  });

  it("never silently reinterprets — valid envelope with wrong-shape data is rejected, not coerced", () => {
    const res = decodeSnapshot("trades", JSON.stringify({ v: 2, data: "BUY RELIANCE", ts: Date.now() }));
    expect(res.ok).toBe(false);
  });

  it("accepts unknown keys with any non-null payload (default validator)", () => {
    const res = decodeSnapshot("some-new-key", encodeSnapshot({ any: 1 }, Date.now()));
    expect(res.ok).toBe(true);
    const nullRes = decodeSnapshot("some-new-key", JSON.stringify({ v: 2, data: null, ts: Date.now() }));
    expect(nullRes).toEqual({ ok: false, reason: "invalid-payload" });
  });
});
