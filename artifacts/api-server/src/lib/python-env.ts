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
  const candidates = [
    path.join(process.cwd(), ".pythonlibs", "bin", "python3"),
    path.join(process.cwd(), "..", "..", ".pythonlibs", "bin", "python3"),
  ];
  for (const bin of candidates) {
    if (fs.existsSync(bin)) return bin;
  }
  return "python3";
}

export const PYTHON_DIR = resolvePythonDir();
export const PYTHON_BIN = resolvePythonBin();

// ── Deployment-safe PYTHONPATH ────────────────────────────────────────────────
// Set PYTHONPATH once at module load so every spawned Python child process can
// find all local modules (e.g. paper_trader, config, analytics_engine) without
// depending solely on the sys.path.insert inside each script.  This is the
// canonical, non-hack approach: parent sets PYTHONPATH, children inherit it.
const _existing = process.env.PYTHONPATH;
process.env.PYTHONPATH = _existing
  ? `${PYTHON_DIR}:${_existing}`
  : PYTHON_DIR;

console.info(`[python-env] PYTHON_DIR=${PYTHON_DIR}  BIN=${PYTHON_BIN}  PYTHONPATH=${process.env.PYTHONPATH}`);
