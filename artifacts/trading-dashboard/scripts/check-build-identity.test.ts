import { describe, expect, it } from "vitest";
import {
  extractHashedEntryAsset,
  inspectUiAsset,
  validateIdentity,
} from "./check-build-identity.mjs";

const commit = "a".repeat(40);
const buildId = "apexquant-aaaaaaaaaaaa";

describe("published dashboard build identity smoke helpers", () => {
  it("resolves only a hashed Vite entry asset from public HTML", () => {
    expect(extractHashedEntryAsset(
      '<script type="module" src="/trading-dashboard/assets/index-AbCdEf12.js"></script>',
      "https://example.test/trading-dashboard/",
    )).toBe("https://example.test/trading-dashboard/assets/index-AbCdEf12.js");

    expect(() => extractHashedEntryAsset(
      '<script type="module" src="/trading-dashboard/src/main.tsx"></script>',
      "https://example.test/trading-dashboard/",
    )).toThrow("hashed");
  });

  it("requires a full UI commit that derives the public build identity", () => {
    const identity = inspectUiAsset(
      `const build="${buildId}"; const commit="${commit}";`,
    );
    expect(identity).toMatchObject({
      uiBuildId: buildId,
      uiGitCommit: commit,
      valid: true,
      retiredBuildIds: [],
    });
  });

  it("flags retired labels even when no valid identity remains", () => {
    const identity = inspectUiAsset('const legacy = "apexquant-v1.0.0";');
    expect(identity.retiredBuildIds).toEqual(["apexquant-v1.0.0"]);
    expect(validateIdentity({
      uiBuildId: identity.uiBuildId,
      uiGitCommit: identity.uiGitCommit,
      apiBuildId: buildId,
      apiGitCommit: commit,
      retiredBuildIds: identity.retiredBuildIds,
    }).failures).toContain(
      'Public UI asset contains retired build identity "apexquant-v1.0.0".',
    );
  });

  it("makes a genuine UI/API build difference a visible mismatch", () => {
    const result = validateIdentity({
      uiBuildId: buildId,
      uiGitCommit: commit,
      apiBuildId: "apexquant-bbbbbbbbbbbb",
      apiGitCommit: "b".repeat(40),
    });
    expect(result.expectedRenderedState).toBe("MISMATCH");
    expect(result.failures).toContain(
      "UI/API build mismatch: UI apexquant-aaaaaaaaaaaa, API apexquant-bbbbbbbbbbbb.",
    );
  });
});