import { Router, type IRouter } from "express";
import { spawn } from "child_process";
import path from "path";

const router: IRouter = Router();

const PYTHON_DIR = path.join(process.cwd(), "src", "python");
const PYTHON_BIN = "python3";

function runPython(args: string[]): Promise<unknown> {
  return new Promise((resolve, reject) => {
    const proc = spawn(PYTHON_BIN, [path.join(PYTHON_DIR, "main.py"), ...args], {
      cwd: PYTHON_DIR,
    });

    let stdout = "";
    let stderr = "";

    proc.stdout.on("data", (d: Buffer) => {
      stdout += d.toString();
    });
    proc.stderr.on("data", (d: Buffer) => {
      stderr += d.toString();
    });

    proc.on("close", (code) => {
      if (code !== 0) {
        try {
          const parsed = JSON.parse(stdout.trim());
          if (parsed.error) return reject(new Error(parsed.error));
        } catch {
          // ignore parse error
        }
        reject(new Error(stderr || `Python exited with code ${code}`));
      } else {
        try {
          resolve(JSON.parse(stdout.trim()));
        } catch {
          reject(new Error(`Failed to parse Python output: ${stdout}`));
        }
      }
    });

    proc.on("error", (err) => {
      reject(err);
    });
  });
}

// GET /api/portfolio
router.get("/portfolio", async (_req, res) => {
  try {
    const data = await runPython(["portfolio"]);
    res.json(data);
  } catch (err: unknown) {
    res.status(500).json({ error: err instanceof Error ? err.message : String(err) });
  }
});

// GET /api/signals
router.get("/signals", async (_req, res) => {
  try {
    const data = await runPython(["signals"]);
    res.json(data);
  } catch (err: unknown) {
    res.status(500).json({ error: err instanceof Error ? err.message : String(err) });
  }
});

// GET /api/trades
router.get("/trades", async (_req, res) => {
  try {
    const data = await runPython(["trades"]);
    res.json(data);
  } catch (err: unknown) {
    res.status(500).json({ error: err instanceof Error ? err.message : String(err) });
  }
});

// POST /api/run-scan
router.post("/run-scan", async (_req, res) => {
  try {
    const signals = await runPython(["scan"]) as unknown[];
    res.json({ signals, scanned_at: new Date().toISOString() });
  } catch (err: unknown) {
    res.status(500).json({ error: err instanceof Error ? err.message : String(err) });
  }
});

// GET /api/watchlist
router.get("/watchlist", async (_req, res) => {
  try {
    const data = await runPython(["watchlist"]) as string[];
    res.json({ watchlist: data });
  } catch (err: unknown) {
    res.status(500).json({ error: err instanceof Error ? err.message : String(err) });
  }
});

// POST /api/watchlist
router.post("/watchlist", async (req, res) => {
  const { symbol } = req.body as { symbol?: string };
  if (!symbol) {
    res.status(400).json({ error: "symbol is required" });
    return;
  }
  try {
    const data = await runPython(["watchlist_add", symbol]);
    res.json(data);
  } catch (err: unknown) {
    res.status(500).json({ error: err instanceof Error ? err.message : String(err) });
  }
});

// DELETE /api/watchlist/:symbol
router.delete("/watchlist/:symbol", async (req, res) => {
  const { symbol } = req.params;
  try {
    const data = await runPython(["watchlist_remove", symbol]);
    res.json(data);
  } catch (err: unknown) {
    res.status(500).json({ error: err instanceof Error ? err.message : String(err) });
  }
});

// POST /api/portfolio/reset
router.post("/portfolio/reset", async (_req, res) => {
  try {
    const data = await runPython(["reset"]);
    res.json(data);
  } catch (err: unknown) {
    res.status(500).json({ error: err instanceof Error ? err.message : String(err) });
  }
});

// GET /api/market-overview
router.get("/market-overview", async (_req, res) => {
  try {
    const data = await runPython(["market_overview"]);
    res.json(data);
  } catch (err: unknown) {
    res.status(500).json({ error: err instanceof Error ? err.message : String(err) });
  }
});

export default router;
