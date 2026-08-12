/**
 * Tests for backtestScheduler health tracking.
 *
 * Verifies that last_sweep_at is stamped ONLY on successful ticks and that
 * failed / timed-out / spawn-error ticks are correctly reflected in
 * consecutive_failures and last_error, never disguised as healthy sweeps.
 *
 * Tests drive the tick directly via _runQueueTickForTests() to avoid
 * depending on fake-timer machinery for the 45-second startup stagger.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { EventEmitter } from "events";

// ── Hoisted mocks ─────────────────────────────────────────────────────────────

vi.mock("child_process", () => ({ spawn: vi.fn() }));
vi.mock("./logger", () => ({ logger: { info: vi.fn(), warn: vi.fn(), error: vi.fn() } }));
vi.mock("./python-env", () => ({ PYTHON_BIN: "/usr/bin/python3", PYTHON_DIR: "/fake/python" }));

import { spawn } from "child_process";
import {
  getSchedulerStatus,
  _resetSchedulerStateForTests,
  _runQueueTickForTests,
  TICK_TIMEOUT_MS,
} from "./backtestScheduler";

const mockSpawn = spawn as ReturnType<typeof vi.fn>;

// ── Fake process factory ──────────────────────────────────────────────────────

function makeProc() {
  const proc = new EventEmitter() as EventEmitter & {
    stdout: EventEmitter;
    stderr: EventEmitter;
    kill: ReturnType<typeof vi.fn>;
  };
  proc.stdout = new EventEmitter();
  proc.stderr = new EventEmitter();
  proc.kill = vi.fn();
  return proc;
}

// ── Shared reset ──────────────────────────────────────────────────────────────

beforeEach(() => { _resetSchedulerStateForTests(); vi.useFakeTimers(); });
afterEach(() => { _resetSchedulerStateForTests(); vi.useRealTimers(); vi.clearAllMocks(); });

// ── Initial state ─────────────────────────────────────────────────────────────

describe("getSchedulerStatus – initial state", () => {
  it("returns disabled + null timestamps + zero failures before any tick", () => {
    const s = getSchedulerStatus();
    expect(s.enabled).toBe(false);
    expect(s.last_sweep_at).toBeNull();
    expect(s.last_attempt_at).toBeNull();
    expect(s.consecutive_failures).toBe(0);
    expect(s.last_error).toBeNull();
  });
});

// ── Successful sweep ──────────────────────────────────────────────────────────

describe("runQueueTick – successful sweep", () => {
  it("stamps last_sweep_at and resets consecutive_failures on exit code 0", async () => {
    const proc = makeProc();
    mockSpawn.mockReturnValueOnce(proc);

    const tickPromise = _runQueueTickForTests();

    // Emit JSON output then close successfully.
    proc.stdout.emit("data", Buffer.from(JSON.stringify({ swept: 1, promoted: 0 })));
    proc.emit("close", 0);

    await tickPromise;

    const s = getSchedulerStatus();
    expect(s.last_sweep_at).not.toBeNull();
    expect(s.last_attempt_at).not.toBeNull();
    expect(s.consecutive_failures).toBe(0);
    expect(s.last_error).toBeNull();
  });

  it("stamps last_sweep_at even when bt_queue_tick emits no JSON (idle tick)", async () => {
    const proc = makeProc();
    mockSpawn.mockReturnValueOnce(proc);

    const tickPromise = _runQueueTickForTests();
    proc.emit("close", 0); // no stdout — perfectly normal when idle
    await tickPromise;

    const s = getSchedulerStatus();
    expect(s.last_sweep_at).not.toBeNull();
    expect(s.consecutive_failures).toBe(0);
    expect(s.last_error).toBeNull();
  });
});

// ── Non-zero exit ─────────────────────────────────────────────────────────────

describe("runQueueTick – non-zero exit", () => {
  it("does NOT stamp last_sweep_at and increments consecutive_failures on exit code 1", async () => {
    const proc = makeProc();
    mockSpawn.mockReturnValueOnce(proc);

    const tickPromise = _runQueueTickForTests();
    proc.emit("close", 1);
    await tickPromise;

    const s = getSchedulerStatus();
    expect(s.last_sweep_at).toBeNull();       // must NOT be stamped
    expect(s.consecutive_failures).toBe(1);
    expect(s.last_error).toMatch(/code 1/);
  });

  it("records the correct exit code in last_error", async () => {
    const proc = makeProc();
    mockSpawn.mockReturnValueOnce(proc);

    const tickPromise = _runQueueTickForTests();
    proc.emit("close", 42);
    await tickPromise;

    expect(getSchedulerStatus().last_error).toContain("42");
  });

  it("does NOT stamp last_sweep_at on null exit code (SIGKILL from external source)", async () => {
    const proc = makeProc();
    mockSpawn.mockReturnValueOnce(proc);

    const tickPromise = _runQueueTickForTests();
    proc.emit("close", null);
    await tickPromise;

    // null exit code (killed externally before our timeout logic sets didTimeout)
    // is treated as non-zero — sweep should NOT be recorded.
    const s = getSchedulerStatus();
    expect(s.last_sweep_at).toBeNull();
    expect(s.consecutive_failures).toBe(1);
  });
});

// ── Spawn error ───────────────────────────────────────────────────────────────

describe("runQueueTick – spawn error", () => {
  it("does NOT stamp last_sweep_at and records the spawn error in last_error", async () => {
    const proc = makeProc();
    mockSpawn.mockReturnValueOnce(proc);

    const tickPromise = _runQueueTickForTests();
    proc.emit("error", new Error("ENOENT: python not found"));
    await tickPromise;

    const s = getSchedulerStatus();
    expect(s.last_sweep_at).toBeNull();
    expect(s.consecutive_failures).toBe(1);
    expect(s.last_error).toMatch(/ENOENT/);
  });

  it("sets last_attempt_at even when spawn fails", async () => {
    const proc = makeProc();
    mockSpawn.mockReturnValueOnce(proc);

    const tickPromise = _runQueueTickForTests();
    proc.emit("error", new Error("spawn error"));
    await tickPromise;

    expect(getSchedulerStatus().last_attempt_at).not.toBeNull();
  });
});

// ── Timeout ───────────────────────────────────────────────────────────────────

describe("runQueueTick – timeout", () => {
  it("does NOT stamp last_sweep_at when tick times out", async () => {
    const proc = makeProc();
    mockSpawn.mockReturnValueOnce(proc);

    const tickPromise = _runQueueTickForTests();

    // Advance past the 30-second tick timeout.
    await vi.advanceTimersByTimeAsync(TICK_TIMEOUT_MS + 100);
    await tickPromise;

    const s = getSchedulerStatus();
    expect(s.last_sweep_at).toBeNull();
    expect(s.consecutive_failures).toBe(1);
    expect(s.last_error).toMatch(/timed out/i);
    expect(proc.kill).toHaveBeenCalledWith("SIGKILL");
  });

  it("subsequent close event after SIGKILL does NOT overwrite the failure as success", async () => {
    const proc = makeProc();
    mockSpawn.mockReturnValueOnce(proc);

    const tickPromise = _runQueueTickForTests();

    // Trigger timeout (kills the process).
    await vi.advanceTimersByTimeAsync(TICK_TIMEOUT_MS + 100);

    // Simulate the close event that arrives after SIGKILL.
    proc.emit("close", null);
    await tickPromise;

    // State must still reflect the failure — not a phantom success.
    const s = getSchedulerStatus();
    expect(s.last_sweep_at).toBeNull();
    expect(s.consecutive_failures).toBeGreaterThanOrEqual(1);
  });
});

// ── Recovery ──────────────────────────────────────────────────────────────────

describe("consecutive_failures – recovery after failure", () => {
  it("resets consecutive_failures to 0 after a success following a failure", async () => {
    // Tick 1: failure (non-zero exit).
    const proc1 = makeProc();
    mockSpawn.mockReturnValueOnce(proc1);
    const tick1 = _runQueueTickForTests();
    proc1.emit("close", 1);
    await tick1;
    expect(getSchedulerStatus().consecutive_failures).toBe(1);

    // Tick 2: success (exit 0).
    const proc2 = makeProc();
    mockSpawn.mockReturnValueOnce(proc2);
    const tick2 = _runQueueTickForTests();
    proc2.emit("close", 0);
    await tick2;

    const s = getSchedulerStatus();
    expect(s.consecutive_failures).toBe(0);
    expect(s.last_error).toBeNull();
    expect(s.last_sweep_at).not.toBeNull();
  });

  it("accumulates consecutive_failures across multiple sequential failures", async () => {
    for (let i = 1; i <= 3; i++) {
      const proc = makeProc();
      mockSpawn.mockReturnValueOnce(proc);
      const tick = _runQueueTickForTests();
      proc.emit("close", 1);
      await tick;
      expect(getSchedulerStatus().consecutive_failures).toBe(i);
    }
  });
});
