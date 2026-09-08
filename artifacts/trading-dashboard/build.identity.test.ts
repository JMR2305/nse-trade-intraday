import { describe, expect, it } from "vitest";
import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import {
  resolveUiBuildIdentity,
  sourceGitCommit,
} from "./buildIdentity.mjs";

describe("dashboard build identity injection", () => {
  it("derives the UI commit and build ID from an exact configured source commit", () => {
    const commit = "a".repeat(40);
    expect(resolveUiBuildIdentity({
      NODE_ENV: "production",
      APEXQUANT_GIT_COMMIT: commit,
    })).toEqual({
      ui_git_commit: commit,
      ui_build_id: "apexquant-aaaaaaaaaaaa",
    });
  });

  it("reads the persisted commit handoff after Git metadata is removed", () => {
    const commit = "b".repeat(40);
    const root = mkdtempSync(path.join(tmpdir(), "apexquant-dashboard-build-"));
    try {
      writeFileSync(path.join(root, ".apexquant-source-commit"), `${commit}\n`);
      expect(sourceGitCommit({ NODE_ENV: "production" }, root)).toBe(commit);
      expect(resolveUiBuildIdentity({ NODE_ENV: "production" }, root)).toEqual({
        ui_git_commit: commit,
        ui_build_id: "apexquant-bbbbbbbbbbbb",
      });
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });

  it("fails closed for missing or invalid production source identity", () => {
    const root = mkdtempSync(path.join(tmpdir(), "apexquant-dashboard-empty-"));
    try {
      expect(() => resolveUiBuildIdentity({ NODE_ENV: "production" }, root))
        .toThrow("Unable to resolve an exact source commit");
      expect(() => resolveUiBuildIdentity({
        NODE_ENV: "production",
        APEXQUANT_GIT_COMMIT: "not-a-commit",
      }, root)).toThrow("Unable to resolve an exact source commit");
      for (const shortCommit of ["a".repeat(7), "b".repeat(11)]) {
        expect(() => resolveUiBuildIdentity({
          NODE_ENV: "production",
          APEXQUANT_GIT_COMMIT: shortCommit,
        }, root)).toThrow("Unable to resolve an exact source commit");
      }
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });

  it("rejects retired, generic, and overriding build labels", () => {
    const commit = "c".repeat(40);
    for (const label of ["apexquant-v1.0.0", "1", "apexquant-other"]) {
      expect(() => resolveUiBuildIdentity({
        NODE_ENV: "production",
        APEXQUANT_GIT_COMMIT: commit,
        APEXQUANT_BUILD_ID: label,
      })).toThrow("Invalid dashboard build identity");
    }
  });

  it("allows a matching derived label without letting it become the source", () => {
    const commit = "d".repeat(40);
    expect(resolveUiBuildIdentity({
      NODE_ENV: "production",
      APEXQUANT_GIT_COMMIT: commit,
      APEXQUANT_BUILD_ID: "apexquant-dddddddddddd",
    }).ui_git_commit).toBe(commit);
  });

  it("always derives a 12-character build suffix from a full source commit", () => {
    const identity = resolveUiBuildIdentity({
      NODE_ENV: "production",
      APEXQUANT_GIT_COMMIT: "e".repeat(40),
    });
    expect(identity.ui_build_id).toMatch(/^apexquant-[0-9a-f]{12}$/);
  });
});