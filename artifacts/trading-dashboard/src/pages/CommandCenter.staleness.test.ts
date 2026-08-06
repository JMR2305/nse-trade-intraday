/**
 * CommandCenter.staleness.test.ts
 *
 * Contract tests for the StalenessTag / freshness-signal integration in
 * CommandCenter.tsx.
 *
 * These are source-inspection tests (same pattern as ExecutiveDashboard.aiHealth):
 * they parse the component source and assert structural/field-path contracts
 * so regressions are caught without spinning up a full React testing environment.
 *
 * Covered cases:
 * 1. StalenessTag component is defined and accepts both `generatedAt` and
 *    `dataUpdatedAt` props.
 * 2. Summary-backed sections use `cache_created_at` (the real server-cache
 *    slot timestamp) — NOT the synthesized Python-side `generated_at`.
 * 3. Standalone query cards use React Query `dataUpdatedAt` — not a
 *    synthesized `generated_at` or `as_of` field.
 * 4. Phase 11 card does NOT use `as_of` as a generatedAt source (it is
 *    synthesised per response and always appears fresh).
 * 5. `cache_created_at` is injected by the Node.js route layer so the
 *    backend truthfully reflects the cache slot creation time.
 */

import { describe, it, expect } from "vitest";
import { readFileSync } from "node:fs";
import { resolve, join } from "node:path";

const SRC = resolve(__dirname, "..");
const CC_SRC = readFileSync(join(SRC, "pages", "CommandCenter.tsx"), "utf8");

const ROUTE_SRC = readFileSync(
  resolve(__dirname, "../../../../artifacts/api-server/src/routes/command-center.ts"),
  "utf8",
);

// ── 1. StalenessTag component definition ─────────────────────────────────────

describe("StalenessTag component", () => {
  it("is defined in CommandCenter.tsx", () => {
    expect(CC_SRC).toMatch(/function StalenessTag/);
  });

  it("accepts a `generatedAt` prop (ISO-8601 string for real snapshot timestamps)", () => {
    expect(CC_SRC).toMatch(/generatedAt\?:\s*string/);
  });

  it("accepts a `dataUpdatedAt` prop (React Query epoch ms for synthesised-timestamp cards)", () => {
    expect(CC_SRC).toMatch(/dataUpdatedAt\?:\s*number/);
  });

  it("uses a tick interval so the age label stays current", () => {
    expect(CC_SRC).toMatch(/setInterval/);
  });

  it("shows amber Cached styling above the 60-second threshold", () => {
    expect(CC_SRC).toMatch(/Cached\s*·/);
    expect(CC_SRC).toMatch(/bg-amber-950/);
  });

  it("shows emerald Live styling below the 60-second threshold", () => {
    expect(CC_SRC).toMatch(/Live\s*·/);
    expect(CC_SRC).toMatch(/bg-emerald-950/);
  });
});

// ── 2. Summary-backed sections: use cache_created_at, not generated_at ────────

describe("Summary-backed sections — freshness source contract", () => {
  it("passes cache_created_at (not generated_at) from the summary response to overview sections", () => {
    // The parent render must pass r.cache_created_at, never bare r.generated_at
    expect(CC_SRC).toMatch(/generatedAt=\{r\.cache_created_at\}/);
  });

  it("does NOT pass r.generated_at to any section (would show synthesised Python timestamp)", () => {
    // generatedAt={r.generated_at} must not appear — only cache_created_at is safe
    expect(CC_SRC).not.toMatch(/generatedAt=\{r\.generated_at\}/);
  });

  it("PlatformHeader prefers cache_created_at with generated_at fallback", () => {
    expect(CC_SRC).toMatch(/cache_created_at.*generated_at|cache_created_at/);
  });

  it("sub-section tags do NOT use obj.generated_at as a primary source (it is synthesised)", () => {
    // Patterns like `market.generated_at ?? generatedAt` must be absent
    expect(CC_SRC).not.toMatch(/market\.generated_at\s*\?\?/);
    expect(CC_SRC).not.toMatch(/portfolio\.generated_at\s*\?\?/);
    expect(CC_SRC).not.toMatch(/trading\.generated_at\s*\?\?/);
    expect(CC_SRC).not.toMatch(/ai\.generated_at\s*\?\?/);
    expect(CC_SRC).not.toMatch(/risk\.generated_at\s*\?\?/);
    expect(CC_SRC).not.toMatch(/mi\.generated_at\s*\?\?/);
    expect(CC_SRC).not.toMatch(/systemHealth\.generated_at\s*\?\?/);
    expect(CC_SRC).not.toMatch(/watchlist\.generated_at\s*\?\?/);
  });
});

// ── 3. Standalone cards: use dataUpdatedAt ────────────────────────────────────

describe("Standalone query cards — freshness source contract", () => {
  it("AnalysisLayerCard passes dataUpdatedAt to StalenessTag", () => {
    expect(CC_SRC).toMatch(/AnalysisLayerCard[\s\S]{0,2000}?dataUpdatedAt=\{dataUpdatedAt\}/);
  });

  it("DecisionLayerCard passes dataUpdatedAt to StalenessTag", () => {
    expect(CC_SRC).toMatch(/DecisionLayerCard[\s\S]{0,2000}?dataUpdatedAt=\{dataUpdatedAt\}/);
  });

  it("LearningLayerCard passes dataUpdatedAt to StalenessTag", () => {
    expect(CC_SRC).toMatch(/LearningLayerCard[\s\S]{0,2000}?dataUpdatedAt=\{dataUpdatedAt\}/);
  });

  it("MultiAgentOpsCard passes dataUpdatedAt to StalenessTag", () => {
    // MultiAgentOpsCard is a larger function; allow up to 4000 chars look-ahead
    expect(CC_SRC).toMatch(/MultiAgentOpsCard[\s\S]{0,4000}?dataUpdatedAt=\{dataUpdatedAt\}/);
  });

  it("AlertCentreSection passes dataUpdatedAt to StalenessTag", () => {
    expect(CC_SRC).toMatch(/AlertCentreSection[\s\S]{0,2000}?dataUpdatedAt=\{dataUpdatedAt\}/);
  });

  it("BriefingSection passes dataUpdatedAt to StalenessTag", () => {
    expect(CC_SRC).toMatch(/BriefingSection[\s\S]{0,2000}?dataUpdatedAt=\{dataUpdatedAt\}/);
  });

  it("TimelineSection passes dataUpdatedAt to StalenessTag", () => {
    expect(CC_SRC).toMatch(/TimelineSection[\s\S]{0,2000}?dataUpdatedAt=\{dataUpdatedAt\}/);
  });
});

// ── 4. Phase 11 does NOT use as_of ───────────────────────────────────────────

describe("PaperTradingCentreCard (Phase 11) — source contract", () => {
  it("does NOT use as_of as generatedAt source (it is synthesised per response)", () => {
    expect(CC_SRC).not.toMatch(/generatedAt=\{.*as_of.*\}/);
  });

  it("uses dataUpdatedAt for its StalenessTag", () => {
    expect(CC_SRC).toMatch(/PaperTradingCentreCard[\s\S]{0,3000}?dataUpdatedAt=\{dataUpdatedAt\}/);
  });
});

// ── 5. Backend: cache_created_at is injected by the Node.js route layer ──────

describe("Backend route — cache_created_at contract", () => {
  it("injects cache_created_at into the summary response on a cache hit", () => {
    expect(ROUTE_SRC).toMatch(/cache_created_at/);
  });

  it("derives cache_created_at from the Node.js cache slot ts (not from Python)", () => {
    // The pattern: new Date(summaryCache.ts).toISOString() or new Date(ts).toISOString()
    expect(ROUTE_SRC).toMatch(/new Date\(.*ts.*\)\.toISOString\(\)/);
  });

  it("spreads the original Python data to avoid losing any existing fields", () => {
    // ...summaryCache.data or ...(data as Record<string, unknown>)
    expect(ROUTE_SRC).toMatch(/\.\.\.\(summaryCache\.data|\.\.\.\(data as/);
  });
});
