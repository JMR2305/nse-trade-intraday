import { afterEach, describe, expect, it, vi } from "vitest";

describe("app startup commissioning flag gate", () => {
  afterEach(() => {
    vi.unstubAllEnvs();
    vi.resetModules();
  });

  it.each(["True", "TRUE", "1", "yes", "", " true "])(
    "rejects malformed HEALTH_ONLY_NO_SCHEDULERS=%j before routing",
    async (value) => {
      vi.stubEnv("HEALTH_ONLY_NO_SCHEDULERS", value);
      await expect(import("./app"))
        .rejects.toThrow(/must be exactly true or false/);
    },
  );
});
