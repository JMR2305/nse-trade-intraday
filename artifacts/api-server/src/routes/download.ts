import { Router } from "express";
import path from "path";
import fs from "fs";

const router = Router();

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
