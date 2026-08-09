/**
 * Task-39 — Two-step resolve flow: end-to-end safety gate tests
 *
 * Three areas covered:
 *
 * 1. Pure-logic unit tests: replicate the confirm-state machine from
 *    ReconciliationWidget.tsx so we can assert each transition
 *    (beginResolve → confirm shown, cancelResolve → confirm gone,
 *    commitResolve → API fired once with correct payload).
 *
 * 2. Static source-analysis tests: read ReconciliationWidget.tsx and assert
 *    that the two-step gate is structurally present — so a refactor that
 *    collapses it into a single click cannot silently slip past CI.
 *
 * 3. Backend route shape tests: read reconciliation.ts and
 *    eod_reconciliation.py to confirm the resolve endpoint enforces the
 *    id+note contract the UI sends.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { readFileSync } from "node:fs";
import { resolve, join } from "node:path";

// ── Paths ──────────────────────────────────────────────────────────────────

const COMPONENT = resolve(
  __dirname,
  "ReconciliationWidget.tsx",
);
const ROUTE_TS = resolve(
  __dirname,
  "..",
  "..",
  "..",
  "api-server",
  "src",
  "routes",
  "reconciliation.ts",
);
const RECON_PY = resolve(
  __dirname,
  "..",
  "..",
  "..",
  "api-server",
  "src",
  "python",
  "eod_reconciliation.py",
);

const componentSrc = readFileSync(COMPONENT, "utf8");
const routeSrc     = readFileSync(ROUTE_TS,  "utf8");
const pythonSrc    = readFileSync(RECON_PY,  "utf8");

// ── 1. Pure-logic: confirm-state machine ──────────────────────────────────
//
// Mirror the three callbacks from ReconciliationWidget.tsx:
//   beginResolve(id)  → sets confirm state { id, note: "" }
//   cancelResolve()   → clears confirm state
//   commitResolve()   → calls the API once with { id, note }, then clears state
//
// We deliberately *not* import the React component so these tests run without
// a DOM — the logic is trivially extractable.

interface ConfirmState { id: number; note: string }

function makeResolveStateMachine() {
  let _confirm: ConfirmState | null = null;
  let _resolvingId: number | null   = null;
  const calls: Array<{ id: number; note: string | undefined }> = [];

  const mockFetch = vi.fn(async (_url: string, init: RequestInit) => {
    const body = JSON.parse(init.body as string);
    calls.push({ id: body.id, note: body.note });
    return { ok: true, status: 200, text: async () => JSON.stringify({ success: true }) };
  });

  function beginResolve(id: number) {
    _confirm = { id, note: "" };
  }

  function cancelResolve() {
    _confirm = null;
  }

  function setNote(note: string) {
    if (_confirm) _confirm = { ..._confirm, note };
  }

  async function commitResolve() {
    if (!_confirm) return;
    const { id, note } = _confirm;
    _confirm = null;
    _resolvingId = id;
    const trimmed = note.trim() || undefined;
    await mockFetch("/api/broker/reconciliation/resolve", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id, note: trimmed }),
    });
    _resolvingId = null;
  }

  return {
    get confirm() { return _confirm; },
    get resolvingId() { return _resolvingId; },
    calls, mockFetch, beginResolve, cancelResolve, setNote, commitResolve,
  };
}

describe("Two-step resolve — state machine", () => {
  let sm: ReturnType<typeof makeResolveStateMachine>;

  beforeEach(() => {
    sm = makeResolveStateMachine();
  });

  // (a) Single click on Resolve must NOT fire the API
  it("beginResolve sets confirm state without calling the API", () => {
    sm.beginResolve(42);
    expect(sm.confirm).toEqual({ id: 42, note: "" });
    expect(sm.mockFetch).not.toHaveBeenCalled();
    expect(sm.calls).toHaveLength(0);
  });

  it("confirm state contains the correct discrepancy id", () => {
    sm.beginResolve(7);
    expect(sm.confirm!.id).toBe(7);
  });

  it("confirm note starts empty", () => {
    sm.beginResolve(1);
    expect(sm.confirm!.note).toBe("");
  });

  // (b) Cancel must clear confirm state without calling the API
  it("cancelResolve clears confirm state without calling the API", () => {
    sm.beginResolve(42);
    sm.cancelResolve();
    expect(sm.confirm).toBeNull();
    expect(sm.mockFetch).not.toHaveBeenCalled();
    expect(sm.calls).toHaveLength(0);
  });

  it("cancelling a second time is a no-op (idempotent)", () => {
    sm.beginResolve(3);
    sm.cancelResolve();
    sm.cancelResolve();
    expect(sm.confirm).toBeNull();
    expect(sm.calls).toHaveLength(0);
  });

  // (c) Confirm must fire the API exactly once with { id, note }
  it("commitResolve fires the API exactly once", async () => {
    sm.beginResolve(42);
    await sm.commitResolve();
    expect(sm.mockFetch).toHaveBeenCalledTimes(1);
  });

  it("commitResolve sends the correct discrepancy id in the payload", async () => {
    sm.beginResolve(42);
    await sm.commitResolve();
    expect(sm.calls[0].id).toBe(42);
  });

  it("commitResolve sends an empty note as undefined (omitted from payload)", async () => {
    sm.beginResolve(42);
    await sm.commitResolve();
    expect(sm.calls[0].note).toBeUndefined();
  });

  it("commitResolve sends a non-empty note in the payload", async () => {
    sm.beginResolve(42);
    sm.setNote("Verified manually");
    await sm.commitResolve();
    expect(sm.calls[0].note).toBe("Verified manually");
  });

  it("commitResolve trims whitespace-only notes to undefined", async () => {
    sm.beginResolve(42);
    sm.setNote("   ");
    await sm.commitResolve();
    expect(sm.calls[0].note).toBeUndefined();
  });

  it("commitResolve clears confirm state after firing", async () => {
    sm.beginResolve(42);
    await sm.commitResolve();
    expect(sm.confirm).toBeNull();
  });

  it("commitResolve is a no-op when confirm state is null", async () => {
    await sm.commitResolve(); // confirm is null
    expect(sm.mockFetch).not.toHaveBeenCalled();
    expect(sm.calls).toHaveLength(0);
  });

  it("a second Resolve click on a different item replaces the previous confirm", () => {
    sm.beginResolve(10);
    sm.beginResolve(20);
    // Only the second one should be active
    expect(sm.confirm!.id).toBe(20);
    expect(sm.calls).toHaveLength(0);
  });
});

// ── 2. Static source analysis — ReconciliationWidget.tsx ──────────────────

describe("ReconciliationWidget.tsx — two-step gate is structurally present", () => {
  // Confirm state
  it("declares a ConfirmState interface or type with id and note fields", () => {
    expect(componentSrc).toMatch(/interface\s+ConfirmState/);
    expect(componentSrc).toMatch(/id\s*:\s*number/);
    expect(componentSrc).toMatch(/note\s*:\s*string/);
  });

  it("holds confirm state in a useState hook initialised to null", () => {
    expect(componentSrc).toMatch(/useState\s*<\s*ConfirmState\s*\|\s*null\s*>\s*\(\s*null\s*\)/);
  });

  // beginResolve — step 1
  it("has a beginResolve callback that sets confirm state (no fetch call)", () => {
    expect(componentSrc).toContain("beginResolve");
    // Must NOT call fetch/apiFetch inside beginResolve
    const beginResolveBlock = componentSrc.match(/beginResolve[\s\S]{0,300}cancelResolve/)?.[0] ?? "";
    expect(beginResolveBlock).not.toContain("apiFetch");
    expect(beginResolveBlock).not.toContain("fetch(");
  });

  // cancelResolve — step 1 bail-out
  it("has a cancelResolve callback that sets confirm to null", () => {
    expect(componentSrc).toContain("cancelResolve");
    expect(componentSrc).toMatch(/cancelResolve[\s\S]{0,200}setConfirm\s*\(\s*null\s*\)/);
  });

  // commitResolve — step 2
  it("has a commitResolve callback that calls apiFetch for the resolve endpoint", () => {
    expect(componentSrc).toContain("commitResolve");
    expect(componentSrc).toContain("/broker/reconciliation/resolve");
  });

  it("commitResolve sends a POST with method field", () => {
    // The fetch call inside commitResolve must use POST
    expect(componentSrc).toMatch(/commitResolve[\s\S]{0,600}method\s*:\s*["']POST["']/);
  });

  it("commitResolve includes id in the JSON body", () => {
    expect(componentSrc).toMatch(/JSON\.stringify\s*\(\s*\{\s*id/);
  });

  it("commitResolve includes note (optional) in the JSON body", () => {
    expect(componentSrc).toMatch(/JSON\.stringify\s*\(\s*\{\s*id[^}]*note/s);
  });

  it("commitResolve guards on confirm being non-null before proceeding", () => {
    expect(componentSrc).toMatch(/if\s*\(\s*!confirm\s*\)\s*return/);
  });

  // Render: Resolve button → confirm UI (note input + Cancel + Confirm buttons)
  it("renders a note input when the confirm UI is active (isConfirming)", () => {
    expect(componentSrc).toContain("isConfirming");
    expect(componentSrc).toContain('placeholder="Note (optional)"');
  });

  it("renders a Cancel button that calls cancelResolve", () => {
    expect(componentSrc).toContain("cancelResolve");
    expect(componentSrc).toMatch(/onClick\s*=\s*\{?\s*cancelResolve\s*\}?/);
  });

  it("renders a Confirm button that calls commitResolve", () => {
    expect(componentSrc).toContain("commitResolve");
    expect(componentSrc).toMatch(/onClick\s*=\s*\{?\s*commitResolve\s*\}?/);
  });

  it("the initial Resolve button calls beginResolve, not commitResolve directly", () => {
    // The outer (non-confirming) path must link to beginResolve
    expect(componentSrc).toMatch(/onClick\s*=\s*\{\s*\(\s*\)\s*=>\s*beginResolve\s*\(\s*d\.id\s*\)/);
  });

  // Conditional rendering: exactly three branches (resolving spinner / confirm UI / resolve button)
  it("renders a loading spinner when resolvingId matches the row id", () => {
    expect(componentSrc).toContain("isResolving");
    expect(componentSrc).toContain("animate-spin");
  });

  // Resolved section
  it("invalidates the reconciliation-status query after a successful resolve", () => {
    expect(componentSrc).toContain("reconciliation-status");
    expect(componentSrc).toContain("invalidateQueries");
  });

  it("moves a resolved discrepancy to the Resolved section via query invalidation", () => {
    // The resolved items are driven by data?.resolved_discrepancies
    expect(componentSrc).toContain("resolved_discrepancies");
    expect(componentSrc).toContain("resolvedDisc");
  });
});

// ── 3. Backend route shape — reconciliation.ts + eod_reconciliation.py ────

describe("reconciliation.ts — resolve route enforces correct request shape", () => {
  it("registers a POST route at /broker/reconciliation/resolve", () => {
    expect(routeSrc).toContain('"/broker/reconciliation/resolve"');
    expect(routeSrc).toMatch(/router\.post\s*\(\s*["']\/broker\/reconciliation\/resolve["']/);
  });

  it("parses id from req.body as an integer", () => {
    expect(routeSrc).toMatch(/parseInt\s*\(.*req\.body.*id/);
  });

  it("rejects a missing or non-positive id with HTTP 400", () => {
    expect(routeSrc).toMatch(/status\s*\(\s*400\s*\)/);
    expect(routeSrc).toContain("Valid discrepancy id required");
  });

  it("passes the note string (trimmed, max 500 chars) as a CLI argument", () => {
    expect(routeSrc).toContain(".trim()");
    expect(routeSrc).toContain("slice(0, 500)");
  });

  it("passes the discrepancy id as a CLI argument to reconcil_resolve", () => {
    expect(routeSrc).toContain("reconcil_resolve");
    expect(routeSrc).toContain("String(id)");
  });
});

describe("eod_reconciliation.py — resolve_discrepancy persists resolved state", () => {
  it("contains a resolve_discrepancy function (or equivalent)", () => {
    // The Python side must have a handler for reconcil_resolve
    expect(pythonSrc).toMatch(/def\s+resolve_discrepancy/);
  });

  it("sets resolved=TRUE in the database", () => {
    expect(pythonSrc).toMatch(/resolved\s*=\s*TRUE/i);
  });

  it("records resolved_at timestamp when resolving", () => {
    expect(pythonSrc).toContain("resolved_at");
  });

  it("stores the optional note in resolved_note column", () => {
    expect(pythonSrc).toContain("resolved_note");
  });

  it("returns success:True on a successful resolve", () => {
    expect(pythonSrc).toMatch(/"success"\s*:\s*True/);
  });

  it("returns an error dict when the discrepancy id is not found or already resolved", () => {
    // The Python side must not silently succeed on a missing row
    expect(pythonSrc).toMatch(/not found|already resolved|rowcount|no.*row/i);
  });
});

// ── 4. Paper-fallback (token expiry) count bridge — bot → API → widget ────

describe("paper-fallback count reaches the Broker page", () => {
  it("widget renders the token-expiry paper-fallback row only when count > 0", () => {
    expect(componentSrc).toContain("paper_fallback_count");
    expect(componentSrc).toContain("Orders routed to paper due to token expiry");
    // Conditional render — zero-count days must show nothing
    expect(componentSrc).toMatch(/paper_fallback_count\s*\?\?\s*0\)\s*>\s*0/);
  });

  it("Python status queries expose paper_fallback_count on latest and recent runs", () => {
    const selects = pythonSrc.match(/SELECT[\s\S]*?FROM broker_reconciliation_runs/g) ?? [];
    expect(selects.length).toBeGreaterThanOrEqual(2);
    for (const s of selects) expect(s).toContain("paper_fallback_count");
  });

  it("schema migration adds paper_fallback_count idempotently", () => {
    expect(pythonSrc).toMatch(
      /ADD COLUMN IF NOT EXISTS paper_fallback_count INTEGER NOT NULL DEFAULT 0/,
    );
  });

  it("Python exposes an idempotent publish ingestion function for the bot bridge", () => {
    expect(pythonSrc).toMatch(/def\s+publish_reconciliation_summary/);
    expect(pythonSrc).toMatch(/ON CONFLICT \(run_id\) DO UPDATE/);
  });

  it("publish route is authenticated with a shared-secret token and validates input", () => {
    expect(routeSrc).toMatch(/router\.post\s*\(\s*["']\/broker\/reconciliation\/publish["']/);
    expect(routeSrc).toContain("RECON_PUBLISH_TOKEN");
    expect(routeSrc).toContain("x-recon-publish-token");
    expect(routeSrc).toMatch(/status\s*\(\s*401\s*\)/);
    expect(routeSrc).toMatch(/status\s*\(\s*503\s*\)/);
    expect(routeSrc).toContain("reconcil_publish");
  });
});
