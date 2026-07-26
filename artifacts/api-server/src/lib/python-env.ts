import path from "path";
import fs from "fs";

function resolvePythonDir(): string {
  const candidates = [
    path.join(process.cwd(), "src", "python"),
    path.join(process.cwd(), "artifacts", "api-server", "src", "python"),
  ];
  for (const dir of candidates) {
    if (fs.existsSync(path.join(dir, "main.py"))) return dir;
  }
  console.error(
    `[python-env] main.py not found in any candidate dir (cwd=${process.cwd()}): ${candidates.join(", ")}`,
  );
  return candidates[0];
}

function resolvePythonBin(): string {
  // 1. Use the exact uv-managed Python written by deploy-build.sh at build time.
  //    This is the only binary guaranteed to have all packages from uv sync.
  const exeFile = path.join(process.cwd(), ".python-exe");
  if (fs.existsSync(exeFile)) {
    try {
      const exe = fs.readFileSync(exeFile, "utf8").trim();
      if (exe && fs.existsSync(exe)) {
        console.info(`[python-env] Using build-resolved Python: ${exe}`);
        return exe;
      }
    } catch {}
  }

  // 2. Workspace .venv created by deploy-build.sh (belt-and-suspenders if .python-exe is stale).
  const venvBin = path.join(process.cwd(), ".venv", "bin", "python3");
  if (fs.existsSync(venvBin)) return venvBin;

  // 3. Dev fallback: Nix-managed Python in .pythonlibs (Replit workspace).
  const candidates = [
    path.join(process.cwd(), ".pythonlibs", "bin", "python3"),
    path.join(process.cwd(), "..", "..", ".pythonlibs", "bin", "python3"),
  ];
  for (const bin of candidates) {
    if (fs.existsSync(bin)) return bin;
  }

  // 3. Last resort: system python3.
  return "python3";
}

/** Directory containing all Python modules (main.py lives here). */
export const PYTHON_DIR = resolvePythonDir();

/** Python binary to use for all spawned processes. */
export const PYTHON_BIN = resolvePythonBin();

// ── Deployment-safe PYTHONPATH ────────────────────────────────────────────────
// Combine three sources so every spawned Python child can find:
//   1. Local modules   (paper_trader, config, analytics_engine, …)  ← PYTHON_DIR
//   2. uv site-pkgs    (yfinance, pandas, …)  ← .python-site written by build
//   3. Anything already in the inherited PYTHONPATH
const _parts: string[] = [PYTHON_DIR];

const siteFile = path.join(process.cwd(), ".python-site");
if (fs.existsSync(siteFile)) {
  try {
    const site = fs.readFileSync(siteFile, "utf8").trim();
    if (site) _parts.push(site);
  } catch {}
}

if (process.env.PYTHONPATH) _parts.push(process.env.PYTHONPATH);
process.env.PYTHONPATH = _parts.join(":");

console.info(
  `[python-env] PYTHON_DIR=${PYTHON_DIR}  BIN=${PYTHON_BIN}\n` +
  `             PYTHONPATH=${process.env.PYTHONPATH}`,
);
