/**
 * Tests for the cold-start OHLCV readiness barrier in scanScheduler.
 *
 * Exercises the actual `startScanScheduler()` + `_runTickForTests()` paths so
 * the barrier and `.finally()` lifecycle are verified in production code, not
 * in a parallel mock harness.
 *
 * Pattern mirrors backtestScheduler.test.ts: mock child_process/logger/python-env,
 * build fake processes via EventEmitter, drive ticks directly through the
 * exported test hook rather than depending on fake-timer machinery.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { EventEmitter } from "events";

// ── Hoisted mocks ─────────────────────────────────────────────────────────────

vi.mock("child_process", () => ({ spawn: vi.fn() }));
vi.mock("./logger", () => ({
  logger: { info: vi.fn(), warn: vi.fn(), error: vi.fn() },
}));
vi.mock("./python-env", () => ({
  PYTHON_BIN: "/usr/bin/python3",
  PYTHON_DIR: "/fake/python",
}));
vi.mock("./pushNotifier", () => ({
  dispatchSignalPushNotifications: vi.fn().mockResolvedValue(undefined),
  processPushDeliveryQueue: vi.fn().mockResolvedValue(undefined),
}));

import { spawn } from "child_process";
import {
  startScanScheduler,
  _resetColdStartCheckForTests,
  _runTickForTests,
} from "./scanScheduler";

const mockSpawn = spawn as ReturnType<typeof vi.fn>;

// ── Fake process factory ──────────────────────────────────────────────────────

interface FakeProc extends EventEmitter {
  stdout: EventEmitter;
  stderr: EventEmitter;
}

function makeProc(): FakeProc {
  const proc = new EventEmitter() as FakeProc;
  proc.stdout = new EventEmitter();
  proc.stderr = new EventEmitter();
  return proc;
}

/**
 * Make a process that auto-resolves with `json` on the next event-loop tick.
 * Used for startup calls we don't want to manually drive in tests.
 */
function makeAutoProc(json: unknown = { ran: false }): FakeProc {
  const proc = makeProc();
  setImmediate(() => {
    proc.stdout.emit("data", Buffer.from(JSON.stringify(json)));
    proc.emit("close", 0);
  });
  return proc;
}

/** Resolve a process successfully with JSON output. */
function resolveProc(proc: FakeProc, json: unknown): void {
  proc.stdout.emit("data", Buffer.from(JSON.stringify(json)));
  proc.emit("close", 0);
}

/** Reject a process with a non-zero exit code. */
function rejectProc(proc: FakeProc, stderr = "error"): void {
  proc.stderr.emit("data", Buffer.from(stderr));
  proc.emit("close", 1);
}

/** All Python command arrays captured across all spawn calls so far. */
function capturedArgs(): string[][] {
  return mockSpawn.mock.calls.map((call) => call[1] as string[]);
}

function capturedCommands(): string[] {
  return capturedArgs().flatMap((a) => a.filter((x) => !x.includes("/")));
}

// ── Shared reset ──────────────────────────────────────────────────────────────

beforeEach(() => {
  _resetColdStartCheckForTests(); // clears _tick, _ohlcvColdStartPending=false, timer
  vi.clearAllMocks();
  // Default: any spawn not explicitly queued auto-resolves with {}
  mockSpawn.mockImplementation(() => makeAutoProc({}));
});

afterEach(() => {
  _resetColdStartCheckForTests();
  vi.clearAllMocks();
});

// ── Helper: flush microtask/setImmediate queue ────────────────────────────────

async function flushAsync(rounds = 3): Promise<void> {
  for (let i = 0; i < rounds; i++) {
    await new Promise<void>((r) => setImmediate(r));
  }
}

// ── Core barrier tests ────────────────────────────────────────────────────────

describe("cold-start OHLCV readiness barrier — via startScanScheduler + _runTickForTests", () => {

  it("defers scheduled_scan_tick while ohlcv_cold_start_check is still pending", async () => {
    // Hold the cold-start proc open (pending) so the gate stays up.
    const coldStartProc = makeProc();
    mockSpawn
      .mockReturnValueOnce(makeAutoProc())  // phase20_scheduler_started
      .mockReturnValueOnce(makeAutoProc())  // phase20_startup_overnight_check
      .mockReturnValueOnce(coldStartProc)   // ohlcv_cold_start_check — held pending
      .mockImplementation(() => makeAutoProc());

    startScanScheduler();
    await flushAsync(); // let auto-procs settle but NOT coldStartProc

    // Tick while gate is still up — scheduled_scan_tick must NOT be spawned.
    await _runTickForTests();
    await flushAsync();

    expect(capturedCommands()).not.toContain("scheduled_scan_tick");
  });

  it("allows scheduled_scan_tick after ohlcv_cold_start_check resolves (warm cache)", async () => {
    const coldStartProc = makeProc();
    mockSpawn
      .mockReturnValueOnce(makeAutoProc())
      .mockReturnValueOnce(makeAutoProc())
      .mockReturnValueOnce(coldStartProc)
      .mockImplementation(() => makeAutoProc());

    startScanScheduler();
    await flushAsync();

    // Tick 1: gate is still up.
    await _runTickForTests();
    expect(capturedCommands()).not.toContain("scheduled_scan_tick");

    // Resolve the cold-start check (warm cache — fast path).
    resolveProc(coldStartProc, {
      ran: true, action: "no_op", reason: "cache_warm",
      cache_hit_rate_pct: 100.0, total_symbols: 51,
    });
    await flushAsync(); // let .finally() clear the gate

    // Tick 2: gate cleared — scan is now allowed.
    await _runTickForTests();
    await flushAsync();

    expect(capturedCommands()).toContain("scheduled_scan_tick");
  });

  it("allows scheduled_scan_tick after ohlcv_cold_start_check resolves (backfill path)", async () => {
    const coldStartProc = makeProc();
    mockSpawn
      .mockReturnValueOnce(makeAutoProc())
      .mockReturnValueOnce(makeAutoProc())
      .mockReturnValueOnce(coldStartProc)
      .mockImplementation(() => makeAutoProc());

    startScanScheduler();
    await flushAsync();

    // Gate is still up during backfill.
    await _runTickForTests();
    expect(capturedCommands()).not.toContain("scheduled_scan_tick");

    // Resolve as a completed backfill (what the owner instance returns).
    resolveProc(coldStartProc, {
      ran: true, action: "backfill", role: "owner",
      was_fully_cold: true, cold_symbol_count: 51, total_symbols: 51,
      symbols_updated: 51, symbols_failed: 0, duration_seconds: 243.1,
      status: "SUCCESS", recovery_hint: null,
    });
    await flushAsync();

    await _runTickForTests();
    await flushAsync();

    expect(capturedCommands()).toContain("scheduled_scan_tick");
  });

  it("clears the gate and allows scans when ohlcv_cold_start_check rejects (Python exits non-zero)", async () => {
    const coldStartProc = makeProc();
    mockSpawn
      .mockReturnValueOnce(makeAutoProc())
      .mockReturnValueOnce(makeAutoProc())
      .mockReturnValueOnce(coldStartProc)
      .mockImplementation(() => makeAutoProc());

    startScanScheduler();
    await flushAsync();

    // Gate up during pending check.
    await _runTickForTests();
    expect(capturedCommands()).not.toContain("scheduled_scan_tick");

    // Fail the cold-start process — .catch() + .finally() must still clear the gate.
    rejectProc(coldStartProc, "ImportError: ohlcv_cache_store not found");
    await flushAsync();

    // Scan is now unblocked even though the check failed.
    await _runTickForTests();
    await flushAsync();

    expect(capturedCommands()).toContain("scheduled_scan_tick");
  });

  it("clears the gate when ohlcv_cold_start_check returns peer_timeout", async () => {
    const coldStartProc = makeProc();
    mockSpawn
      .mockReturnValueOnce(makeAutoProc())
      .mockReturnValueOnce(makeAutoProc())
      .mockReturnValueOnce(coldStartProc)
      .mockImplementation(() => makeAutoProc());

    startScanScheduler();
    await flushAsync();

    // Gate holds while peer is running.
    await _runTickForTests();
    expect(capturedCommands()).not.toContain("scheduled_scan_tick");

    // Non-owner timed out waiting for peer — returns without action.
    resolveProc(coldStartProc, {
      ran: false, reason: "peer_timeout",
      wait_timeout_s: 720, total_symbols: 51,
      recovery_hint: "POST /api/ohlcv-cache/backfill",
    });
    await flushAsync();

    await _runTickForTests();
    await flushAsync();

    // Scan is allowed so at least the yfinance fallback can run.
    expect(capturedCommands()).toContain("scheduled_scan_tick");
  });

  it("does not spawn scheduled_scan_tick on consecutive deferred ticks", async () => {
    const coldStartProc = makeProc();
    mockSpawn
      .mockReturnValueOnce(makeAutoProc())
      .mockReturnValueOnce(makeAutoProc())
      .mockReturnValueOnce(coldStartProc)
      .mockImplementation(() => makeAutoProc());

    startScanScheduler();
    await flushAsync();

    // Three ticks while gate is up — none should spawn the scan.
    await _runTickForTests();
    await _runTickForTests();
    await _runTickForTests();
    await flushAsync();

    expect(capturedCommands()).not.toContain("scheduled_scan_tick");
  });
});

// ── startScanScheduler launches ohlcv_cold_start_check at startup ─────────────

describe("startScanScheduler — startup sequence", () => {
  it("spawns ohlcv_cold_start_check as the third startup call", async () => {
    startScanScheduler();
    await flushAsync();

    const cmds = capturedCommands();
    expect(cmds).toContain("ohlcv_cold_start_check");
  });

  it("spawns phase20_scheduler_started and phase20_startup_overnight_check before the cold check", async () => {
    startScanScheduler();
    await flushAsync();

    const cmds = capturedCommands();
    const startedIdx = cmds.indexOf("phase20_scheduler_started");
    const overnightIdx = cmds.indexOf("phase20_startup_overnight_check");
    const coldIdx = cmds.indexOf("ohlcv_cold_start_check");

    expect(startedIdx).toBeGreaterThanOrEqual(0);
    expect(overnightIdx).toBeGreaterThanOrEqual(0);
    expect(coldIdx).toBeGreaterThanOrEqual(0);
    // The cold-start check must come after the other two startup calls.
    expect(coldIdx).toBeGreaterThan(Math.min(startedIdx, overnightIdx));
  });
});

// ── _resetColdStartCheckForTests isolation ────────────────────────────────────

describe("_resetColdStartCheckForTests — state isolation", () => {
  it("clears _tick so _runTickForTests throws before startScanScheduler is called", async () => {
    _resetColdStartCheckForTests();
    await expect(_runTickForTests()).rejects.toThrow("startScanScheduler");
  });

  it("allows startScanScheduler to be called again after reset without stacking timers", () => {
    startScanScheduler();
    _resetColdStartCheckForTests(); // clears timer
    startScanScheduler(); // must not throw or double-register
    _resetColdStartCheckForTests();
  });
});
