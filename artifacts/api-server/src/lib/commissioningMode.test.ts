import { readFileSync } from "node:fs";
import { describe, expect, it, vi } from "vitest";
import {
  healthOnlyNoSchedulers,
  loadRouterForMode,
  startSchedulersForMode,
} from "./commissioningMode";

describe("HEALTH_ONLY_NO_SCHEDULERS parsing", () => {
  it.each([
    [undefined, false],
    ["false", false],
    ["true", true],
  ])("maps %s exactly to %s", (value, expected) => {
    const env = value === undefined ? {} : { HEALTH_ONLY_NO_SCHEDULERS: value };
    expect(healthOnlyNoSchedulers(env)).toBe(expected);
  });

  it.each(["True", "TRUE", "1", "yes", "", " true ", "0", "FALSE"])(
    "rejects malformed value %j",
    (value) => {
      expect(() => healthOnlyNoSchedulers({ HEALTH_ONLY_NO_SCHEDULERS: value }))
        .toThrow(/must be exactly true or false/);
    },
  );
});

describe("commissioning import boundary", () => {
  it("keeps the commissioning router dependency graph health-only", () => {
    const source = readFileSync(
      new URL("../routes/commissioning.ts", import.meta.url),
      "utf8",
    );
    expect(source).toContain('import healthRouter from "./health"');
    expect(source).not.toMatch(/trading|portfolio|scanScheduler|backtest|certification|universe|pipeline/i);
  });

  it("loads only the commissioning router in health-only mode", async () => {
    const normal = vi.fn().mockResolvedValue({ default: "normal" });
    const commissioning = vi.fn().mockResolvedValue({ default: "commissioning" });
    await expect(loadRouterForMode(true, { normal, commissioning }))
      .resolves.toBe("commissioning");
    expect(normal).not.toHaveBeenCalled();
    expect(commissioning).toHaveBeenCalledOnce();
  });

  it.each([false, undefined])("loads only the normal router for %s", async (mode) => {
    const normal = vi.fn().mockResolvedValue({ default: "normal" });
    const commissioning = vi.fn().mockResolvedValue({ default: "commissioning" });
    await expect(loadRouterForMode(mode, { normal, commissioning }))
      .resolves.toBe("normal");
    expect(normal).toHaveBeenCalledOnce();
    expect(commissioning).not.toHaveBeenCalled();
  });
});

describe("scheduler import boundary", () => {
  it("imports and starts no scheduler in health-only mode", async () => {
    const scan = vi.fn();
    const backtest = vi.fn();
    await startSchedulersForMode(true, { scan, backtest });
    expect(scan).not.toHaveBeenCalled();
    expect(backtest).not.toHaveBeenCalled();
  });

  it.each([false, undefined])("preserves both scheduler starts for %s", async (mode) => {
    const startScanScheduler = vi.fn();
    const startBacktestScheduler = vi.fn();
    const scan = vi.fn().mockResolvedValue({ startScanScheduler });
    const backtest = vi.fn().mockResolvedValue({ startBacktestScheduler });
    await startSchedulersForMode(mode, { scan, backtest });
    expect(scan).toHaveBeenCalledOnce();
    expect(backtest).toHaveBeenCalledOnce();
    expect(startScanScheduler).toHaveBeenCalledOnce();
    expect(startBacktestScheduler).toHaveBeenCalledOnce();
  });

  it("propagates a normal-mode scheduler import failure", async () => {
    const error = new Error("scheduler import failed");
    await expect(startSchedulersForMode(false, {
      scan: vi.fn().mockRejectedValue(error),
      backtest: vi.fn().mockResolvedValue({ startBacktestScheduler: vi.fn() }),
    })).rejects.toBe(error);
  });
});
