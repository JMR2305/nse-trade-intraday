import { describe, expect, it } from "vitest";
import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { resolveBuildIdentity } from "./build.mjs";

describe("API build identity injection", () => {
  it("uses an exact configured source commit and derives its build ID", () => {
    const commit = "a".repeat(40);

    expect(resolveBuildIdentity({
      APEXQUANT_GIT_COMMIT: commit,
    } as NodeJS.ProcessEnv)).toEqual({
      gitCommit: commit,
      buildId: "apexquant-aaaaaaaaaaaa",
    });
  });

  it("rejects retired or generic configured deployment labels", () => {
    const commit = "c".repeat(40);
    for (const label of ["apexquant-v1.0.0", "apexquant-phase0c-20260821", "1"]) {
      expect(() => resolveBuildIdentity({
        APEXQUANT_GIT_COMMIT: commit,
        APEXQUANT_BUILD_ID: label,
      } as NodeJS.ProcessEnv)).toThrow("Invalid API build identity");
    }
  });

  it("fails closed when no full source commit can be resolved", () => {
    expect(() => resolveBuildIdentity({
      APEXQUANT_GIT_COMMIT: "unknown",
    } as NodeJS.ProcessEnv)).toThrow("Unable to resolve an exact source commit");
    expect(() => resolveBuildIdentity({
      APEXQUANT_GIT_COMMIT: "a".repeat(11),
    } as NodeJS.ProcessEnv)).toThrow("Unable to resolve an exact source commit");
  });

  it("reads the commit handoff after the deployment cleanup removes git", () => {
    const commit = "b".repeat(40);
    const root = mkdtempSync(path.join(tmpdir(), "apexquant-build-"));

    try {
      writeFileSync(path.join(root, ".apexquant-source-commit"), `${commit}\n`);
      expect(resolveBuildIdentity({}, root)).toEqual({
        gitCommit: commit,
        buildId: "apexquant-bbbbbbbbbbbb",
      });
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });
});