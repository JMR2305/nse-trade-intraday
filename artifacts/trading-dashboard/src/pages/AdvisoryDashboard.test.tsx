import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

describe("hidden advisory dashboard safety boundary", () => {
  const appSource = readFileSync(new URL("../App.tsx", import.meta.url), "utf8");
  const pageSource = readFileSync(new URL("./AdvisoryDashboard.tsx", import.meta.url), "utf8");

  it("registers the route only behind the UI flag", () => {
    expect(appSource).toContain("isAdvisoryUiEnabled() &&");
    expect(appSource).toContain('path="/advisory"');
  });

  it("contains no trade or control buttons or mutations", () => {
    for (const forbidden of [
      "place_order",
      "create_trade",
      "usemutation",
      "onclick=",
      "<button",
    ]) {
      expect(pageSource.toLowerCase()).not.toContain(forbidden);
    }
    expect(pageSource).toContain("ADVISORY ONLY — NOT ORDER INSTRUCTIONS");
  });
});