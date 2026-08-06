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

// ── ops-centre-snapshot payload validator ─────────────────────────────────────
//
// The Pipeline tab in the mobile app reads from this key. The validator must
// accept the real OpsSnapshot shape and reject every partial/wrong-type variant
// so the tab never renders wrong data silently.

describe("ops-centre-snapshot payload validator", () => {
  const TS = 1_754_000_000_000;

  // Minimal valid OpsSnapshot matching cacheSchema.ts validator requirements
  const VALID: Record<string, unknown> = {
    generated_at: "2026-08-06T10:00:00Z",
    platform: { health_pct: 92, market_state: "OPEN" },
    agents: { supervisor: { status: "ACTIVE", health_pct: 100 } },
    pipeline: { universe_loaded: 200, buy_recommendations: 5 },
    pipeline_nodes: [],
  };

  function encode(data: unknown) {
    return JSON.stringify({ v: CACHE_SCHEMA_VERSION, data, ts: TS });
  }

  it("accepts a valid OpsSnapshot envelope", () => {
    const res = decodeSnapshot("ops-centre-snapshot", encode(VALID));
    expect(res.ok).toBe(true);
    if (res.ok) {
      expect(res.ts).toBe(TS);
      expect(res.migrated).toBe(false);
    }
  });

  it("accepts when pipeline_nodes is an empty array", () => {
    const res = decodeSnapshot("ops-centre-snapshot", encode({ ...VALID, pipeline_nodes: [] }));
    expect(res.ok).toBe(true);
  });

  it("accepts when pipeline_nodes contains items", () => {
    const res = decodeSnapshot(
      "ops-centre-snapshot",
      encode({ ...VALID, pipeline_nodes: [{ label: "Universe", count: 200 }] }),
    );
    expect(res.ok).toBe(true);
  });

  it("rejects when generated_at is missing", () => {
    const { generated_at: _omit, ...noGeneratedAt } = VALID;
    const res = decodeSnapshot("ops-centre-snapshot", encode(noGeneratedAt));
    expect(res).toEqual({ ok: false, reason: "invalid-payload" });
  });

  it("rejects when generated_at is not a string (e.g. a number)", () => {
    const res = decodeSnapshot("ops-centre-snapshot", encode({ ...VALID, generated_at: 1_700_000_000 }));
    expect(res).toEqual({ ok: false, reason: "invalid-payload" });
  });

  it("rejects when platform is missing", () => {
    const { platform: _omit, ...noPlatform } = VALID;
    const res = decodeSnapshot("ops-centre-snapshot", encode(noPlatform));
    expect(res).toEqual({ ok: false, reason: "invalid-payload" });
  });

  it("rejects when platform.health_pct is absent (not a number)", () => {
    const res = decodeSnapshot(
      "ops-centre-snapshot",
      encode({ ...VALID, platform: { market_state: "OPEN" } }),
    );
    expect(res).toEqual({ ok: false, reason: "invalid-payload" });
  });

  it("rejects when platform is an array instead of an object", () => {
    const res = decodeSnapshot("ops-centre-snapshot", encode({ ...VALID, platform: [92] }));
    expect(res).toEqual({ ok: false, reason: "invalid-payload" });
  });

  it("rejects when agents is missing", () => {
    const { agents: _omit, ...noAgents } = VALID;
    const res = decodeSnapshot("ops-centre-snapshot", encode(noAgents));
    expect(res).toEqual({ ok: false, reason: "invalid-payload" });
  });

  it("rejects when agents is an array", () => {
    const res = decodeSnapshot("ops-centre-snapshot", encode({ ...VALID, agents: [] }));
    expect(res).toEqual({ ok: false, reason: "invalid-payload" });
  });

  it("rejects when pipeline is missing", () => {
    const { pipeline: _omit, ...noPipeline } = VALID;
    const res = decodeSnapshot("ops-centre-snapshot", encode(noPipeline));
    expect(res).toEqual({ ok: false, reason: "invalid-payload" });
  });

  it("rejects when pipeline is a string", () => {
    const res = decodeSnapshot("ops-centre-snapshot", encode({ ...VALID, pipeline: "ok" }));
    expect(res).toEqual({ ok: false, reason: "invalid-payload" });
  });

  it("rejects when pipeline_nodes is missing", () => {
    const { pipeline_nodes: _omit, ...noNodes } = VALID;
    const res = decodeSnapshot("ops-centre-snapshot", encode(noNodes));
    expect(res).toEqual({ ok: false, reason: "invalid-payload" });
  });

  it("rejects when pipeline_nodes is an object instead of an array", () => {
    const res = decodeSnapshot("ops-centre-snapshot", encode({ ...VALID, pipeline_nodes: {} }));
    expect(res).toEqual({ ok: false, reason: "invalid-payload" });
  });

  it("rejects a completely empty object", () => {
    const res = decodeSnapshot("ops-centre-snapshot", encode({}));
    expect(res).toEqual({ ok: false, reason: "invalid-payload" });
  });

  it("rejects a plain array at the top level", () => {
    const res = decodeSnapshot("ops-centre-snapshot", encode([]));
    expect(res).toEqual({ ok: false, reason: "invalid-payload" });
  });

  it("round-trips correctly: encode then decode produces identical data", () => {
    const encoded = encodeSnapshot(VALID, TS);
    const res = decodeSnapshot("ops-centre-snapshot", encoded);
    expect(res.ok).toBe(true);
    if (res.ok) {
      expect(res.data).toEqual(VALID);
      expect(res.ts).toBe(TS);
    }
  });
});
