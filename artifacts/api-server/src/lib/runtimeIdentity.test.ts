import { describe, expect, it, afterEach } from "vitest";
import { runtimeIdentity } from "./runtimeIdentity";

const original = {
  NODE_ENV: process.env.NODE_ENV,
  ENVIRONMENT: process.env.ENVIRONMENT,
  APEXQUANT_BUILD_ID: process.env.APEXQUANT_BUILD_ID,
  APEXQUANT_GIT_COMMIT: process.env.APEXQUANT_GIT_COMMIT,
  REPLIT_DEPLOYMENT_ID: process.env.REPLIT_DEPLOYMENT_ID,
  REPLIT_INSTANCE_ID: process.env.REPLIT_INSTANCE_ID,
};

afterEach(() => {
  for (const key of Object.keys(original) as Array<keyof typeof original>) {
    const value = original[key];
    if (value === undefined) delete process.env[key];
    else process.env[key] = value;
  }
});

describe("runtime identity", () => {
  it("returns only non-secret production identity fields", () => {
    process.env.NODE_ENV = "production";
    process.env.APEXQUANT_GIT_COMMIT = "abc123";
    process.env.APEXQUANT_BUILD_ID = "apexquant-test";
    process.env.REPLIT_DEPLOYMENT_ID = "deploy-1";
    process.env.REPLIT_INSTANCE_ID = "instance-1";

    const identity = runtimeIdentity();

    expect(identity).toMatchObject({
      environment: "production",
      git_commit: "abc123",
      build_id: "apexquant-test",
      deployment_id: "deploy-1",
      instance_id: "instance-1",
    });
    expect(identity.runtime_timestamp).toMatch(/^\d{4}-\d{2}-\d{2}T/);
    expect(Object.keys(identity)).toEqual([
      "environment",
      "git_commit",
      "build_id",
      "deployment_id",
      "instance_id",
      "runtime_timestamp",
    ]);
  });

  it("does not label an unidentified production process as development", () => {
    process.env.NODE_ENV = "production";
    delete process.env.APEXQUANT_GIT_COMMIT;
    delete process.env.APEXQUANT_BUILD_ID;

    const identity = runtimeIdentity();

    expect(identity.environment).toBe("production");
    expect(identity.git_commit).toBe("production-unidentified");
    expect(identity.build_id).toBe("production-unidentified");
  });
});