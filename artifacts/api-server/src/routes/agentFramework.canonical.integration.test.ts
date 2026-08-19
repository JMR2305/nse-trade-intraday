/**
 * Cold-start agent detail integration.
 *
 * The API server executes main.py in a fresh Python process for every request.
 * Agent detail must therefore resolve from the canonical ops snapshot instead of
 * the empty in-process AgentRegistry.
 */
import { describe, expect, it } from "vitest";
import { execFile } from "node:child_process";
import { promisify } from "node:util";
import path from "node:path";
import { PYTHON_BIN, PYTHON_DIR } from "../lib/python-env";

const execFileAsync = promisify(execFile);

describe("canonical agent detail cold start", () => {
  it("returns usable detail for a canonical agent from a fresh Python process", async () => {
    const { stdout } = await execFileAsync(
      PYTHON_BIN,
      [path.join(PYTHON_DIR, "main.py"), "agent_detail", "risk"],
      {
        cwd: PYTHON_DIR,
        env: { ...process.env },
        timeout: 60_000,
        maxBuffer: 1024 * 1024,
      },
    );
    const jsonLine = stdout
      .trim()
      .split(/\r?\n/)
      .reverse()
      .find((line) => line.trim().startsWith("{"));
    expect(jsonLine).toBeTruthy();

    const detail = JSON.parse(jsonLine!) as Record<string, unknown>;
    expect(detail).toMatchObject({
      available: true,
      advisory_only: true,
      read_only: true,
      agent_id: "risk",
      name: "Risk Agent",
      state: expect.any(String),
      current_activity: expect.any(String),
      detail_source: "canonical_ops_snapshot",
    });
  }, 65_000);
});