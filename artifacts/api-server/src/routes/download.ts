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
  res.setHeader(
    "Content-Disposition",
    'attachment; filename="nse-intraday-backend-source.zip"'
  );
  res.setHeader("Content-Type", "application/zip");
  res.sendFile(filePath);
});

export default router;
