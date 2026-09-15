import { beforeAll, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => {
  const close = vi.fn((callback?: () => void) => callback?.());
  return {
    listen: vi.fn((_port: number, callback: (error?: Error) => void) => {
      callback();
      return { close };
    }),
    close,
    scanModuleFactory: vi.fn(() => ({ startScanScheduler: vi.fn() })),
    backtestModuleFactory: vi.fn(() => ({ startBacktestScheduler: vi.fn() })),
  };
});

vi.mock("./app", () => ({ default: { listen: mocks.listen } }));
vi.mock("./lib/logger", () => ({
  logger: { info: vi.fn(), error: vi.fn(), warn: vi.fn() },
}));
vi.mock("./lib/scanScheduler.js", mocks.scanModuleFactory);
vi.mock("./lib/backtestScheduler.js", mocks.backtestModuleFactory);

describe("production entry boundary in commissioning mode", () => {
  beforeAll(async () => {
    vi.stubEnv("PORT", "8080");
    vi.stubEnv("HEALTH_ONLY_NO_SCHEDULERS", "true");
    await import("./index");
  });

  it("starts the HTTP listener without importing either scheduler module", () => {
    expect(mocks.listen).toHaveBeenCalledOnce();
    expect(mocks.scanModuleFactory).not.toHaveBeenCalled();
    expect(mocks.backtestModuleFactory).not.toHaveBeenCalled();
  });
});
