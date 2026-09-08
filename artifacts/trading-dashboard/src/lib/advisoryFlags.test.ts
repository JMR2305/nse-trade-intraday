import { describe, expect, it } from "vitest";
import { readAdvisoryUiFlags } from "./advisoryFlags";

describe("advisory UI feature flag", () => {
  it("defaults every browser-facing advisory flag to false", () => {
    expect(readAdvisoryUiFlags({})).toEqual({
      enabled: false,
      apiEnabled: false,
      persistEnabled: false,
      schedulerEnabled: false,
    });
  });

  it("requires the explicit VITE true value", () => {
    expect(readAdvisoryUiFlags({
      VITE_ADVISORY_BOTS_UI_ENABLED: "true",
      VITE_ADVISORY_BOTS_API_ENABLED: "false",
      VITE_ADVISORY_BOTS_PERSIST_ENABLED: "1",
      VITE_ADVISORY_BOTS_SCHEDULER_ENABLED: "yes",
    })).toEqual({
      enabled: true,
      apiEnabled: false,
      persistEnabled: false,
      schedulerEnabled: false,
    });
  });
});
