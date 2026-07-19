import { Router } from "express";
import path from "path";
import fs from "fs";

const FILES = [
  {
    slug: "batch7d-reference-package.zip",
    fsPath: "/home/runner/workspace/exports/batch7d_reference_package.zip",
    label: "Batch 7D — Reference Package",
    description: "All 30 execution source + test files, database references, operational files, pyproject.toml, and the Kimi context document.",
    type: "ZIP Archive",
    icon: "📦",
  },
  {
    slug: "batch7d-kimi-context.md",
    fsPath: "/home/runner/workspace/exports/BATCH_7D_KIMI_CONTEXT.md",
    label: "Batch 7D — Kimi Context Document",
    description: "Concise design brief for Kimi: merged state, in-memory→DB gap table, key contracts, 7D scope boundaries, and open design questions.",
    type: "Markdown",
    icon: "📄",
  },
];

function humanSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(2)} MB`;
}

function buildPage(): string {
  const cards = FILES.map((f) => {
    const exists = fs.existsSync(f.fsPath);
    const size = exists ? humanSize(fs.statSync(f.fsPath).size) : "unavailable";
    const downloadUrl = `/api/download/${f.slug}`;
    const btn = exists
      ? `<a href="${downloadUrl}" download class="btn">⬇ Download ${size}</a>`
      : `<span class="btn disabled">Unavailable</span>`;
    return `
    <div class="card">
      <div class="card-icon">${f.icon}</div>
      <div class="card-body">
        <div class="card-title">${f.label}</div>
        <div class="card-meta">${f.type} · ${size}</div>
        <div class="card-desc">${f.description}</div>
      </div>
      <div class="card-action">${btn}</div>
    </div>`;
  }).join("");

  return `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width,initial-scale=1"/>
  <title>Batch 7D Downloads</title>
  <style>
    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      font-family: 'Inter', system-ui, -apple-system, sans-serif;
      background: #0d1117; color: #e6edf3;
      min-height: 100vh; display: flex; flex-direction: column;
      align-items: center; justify-content: center; padding: 2rem 1rem;
    }
    .container { max-width: 680px; width: 100%; }
    .header { text-align: center; margin-bottom: 2.5rem; }
    .badge {
      display: inline-block; font-size: 0.7rem; font-weight: 600;
      letter-spacing: 0.08em; text-transform: uppercase;
      background: #1f3a5f; color: #58a6ff; border-radius: 20px;
      padding: 3px 12px; margin-bottom: 0.75rem;
    }
    h1 { font-size: 1.6rem; font-weight: 700; color: #f0f6fc; margin-bottom: 0.4rem; }
    .sub { font-size: 0.88rem; color: #8b949e; }
    .card {
      background: #161b22; border: 1px solid #30363d;
      border-radius: 12px; padding: 1.4rem 1.5rem;
      display: flex; align-items: center; gap: 1.2rem;
      margin-bottom: 1rem; transition: border-color 0.15s;
    }
    .card:hover { border-color: #58a6ff; }
    .card-icon { font-size: 2rem; flex-shrink: 0; }
    .card-body { flex: 1; min-width: 0; }
    .card-title { font-size: 0.95rem; font-weight: 600; color: #f0f6fc; margin-bottom: 2px; }
    .card-meta { font-size: 0.75rem; color: #58a6ff; margin-bottom: 0.4rem; }
    .card-desc { font-size: 0.8rem; color: #8b949e; line-height: 1.5; }
    .card-action { flex-shrink: 0; }
    .btn {
      display: inline-block; background: #238636; color: #fff;
      font-size: 0.82rem; font-weight: 600; padding: 8px 16px;
      border-radius: 8px; text-decoration: none; white-space: nowrap;
      transition: background 0.15s;
    }
    .btn:hover { background: #2ea043; }
    .btn.disabled { background: #30363d; color: #8b949e; cursor: not-allowed; }
    .footer { text-align: center; margin-top: 2rem; font-size: 0.75rem; color: #484f58; }
    @media (max-width: 520px) {
      .card { flex-direction: column; align-items: flex-start; }
      .card-action { width: 100%; }
      .btn { width: 100%; text-align: center; }
    }
  </style>
</head>
<body>
  <div class="container">
    <div class="header">
      <div class="badge">NSE Intraday Platform</div>
      <h1>Batch 7D Downloads</h1>
      <p class="sub">Execution Recovery, Persistence &amp; Deterministic Replay</p>
    </div>
    ${cards}
    <div class="footer">Files are served directly — no login required.</div>
  </div>
</body>
</html>`;
}

const router = Router();

// ── Public download page ────────────────────────────────────────────
router.get("/downloads", (_req, res) => {
  res.setHeader("Content-Type", "text/html; charset=utf-8");
  res.send(buildPage());
});

router.get("/download/nse-intraday-backend-source.zip", (req, res) => {
  const filePath = "/home/runner/workspace/exports/nse-intraday-backend-source.zip";
  if (!fs.existsSync(filePath)) {
    res.status(404).json({ error: "File not found" });
    return;
  }
  res.setHeader("Content-Disposition", 'attachment; filename="nse-intraday-backend-source.zip"');
  res.setHeader("Content-Type", "application/zip");
  res.sendFile(filePath);
});

router.get("/download/batch6-compatibility-report.csv", (req, res) => {
  const filePath = "/home/runner/workspace/exports/batch6-compatibility-report.csv";
  if (!fs.existsSync(filePath)) {
    res.status(404).json({ error: "File not found" });
    return;
  }
  res.setHeader("Content-Disposition", 'attachment; filename="batch6-compatibility-report.csv"');
  res.setHeader("Content-Type", "text/csv");
  res.sendFile(filePath);
});

router.get("/download/market-data-package.zip", (req, res) => {
  const filePath = "/home/runner/workspace/exports/market_data_package.zip";
  if (!fs.existsSync(filePath)) {
    res.status(404).json({ error: "File not found" });
    return;
  }
  res.setHeader("Content-Disposition", 'attachment; filename="market_data_package.zip"');
  res.setHeader("Content-Type", "application/zip");
  res.sendFile(filePath);
});

router.get("/download/batch7d-reference-package.zip", (req, res) => {
  const filePath = "/home/runner/workspace/exports/batch7d_reference_package.zip";
  if (!fs.existsSync(filePath)) {
    res.status(404).json({ error: "File not found" });
    return;
  }
  res.setHeader("Content-Disposition", 'attachment; filename="batch7d_reference_package.zip"');
  res.setHeader("Content-Type", "application/zip");
  res.sendFile(filePath);
});

router.get("/download/batch7d-kimi-context.md", (req, res) => {
  const filePath = "/home/runner/workspace/exports/BATCH_7D_KIMI_CONTEXT.md";
  if (!fs.existsSync(filePath)) {
    res.status(404).json({ error: "File not found" });
    return;
  }
  res.setHeader("Content-Disposition", 'attachment; filename="BATCH_7D_KIMI_CONTEXT.md"');
  res.setHeader("Content-Type", "text/markdown");
  res.sendFile(filePath);
});

export default router;
