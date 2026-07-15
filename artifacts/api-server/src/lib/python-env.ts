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
