import { describe, expect, it } from "vitest";
import { resolveBuildIdentity } from "./build.mjs";

describe("API build identity injection", () => {
  it("uses an exact configured source commit and replaces the retired generic build label", () => {
    const commit = "a".repeat(40);

    expect(resolveBuildIdentity({
      APEXQUANT_GIT_COMMIT: commit,
      APEXQUANT_BUILD_ID: "apexquant-v1.0.0",
    } as NodeJS.ProcessEnv)).toEqual({
      gitCommit: commit,
      buildId: "apexquant-aaaaaaaaaaaa",
    });
  });

  it("fails closed when no exact source commit can be resolved", () => {
    expect(() => resolveBuildIdentity({
      APEXQUANT_GIT_COMMIT: "unknown",
    } as NodeJS.ProcessEnv)).toThrow("Unable to resolve an exact source commit");
  });
});