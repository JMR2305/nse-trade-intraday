/**
 * Disabled-by-default, read-only Phase 4A controlled paper-entry status.
 *
 * GET /api/controlled-paper-entry/status
 *
 * This route deliberately has no run, execute, order, trade, settings, or
 * broker surface. It reports BLOCKED until a future caller supplies evidence
 * to the pure checker in the isolated Python review tooling.
 */
import { Router, type Response } from "express";
import { requireApiKey } from "../lib/auth";
import { readControlledPaperEntryFlags } from "../lib/controlledPaperEntryFlags";

const router = Router();

function unavailable(res: Response): void {
  res.status(404).json({
    status: "DISABLED",
    controlled_paper_entry: true,
    dry_run_only: true,
    execution_allowed: false,
  });
}

router.use("/controlled-paper-entry", (req, res, next) => {
  if (!readControlledPaperEntryFlags().frameworkEnabled) {
    unavailable(res);
    return;
  }
  requireApiKey(req, res, next);
});

router.get("/controlled-paper-entry/status", (_req, res) => {
  const flags = readControlledPaperEntryFlags();
  res.json({
    status: "BLOCKED",
    controlled_paper_entry: true,
    readiness_status: "BLOCKED",
    readiness_reason: "No caller-supplied Phase 1H and EOD evidence is attached to this status-only surface.",
    dry_run_only: flags.dryRunOnly,
    execution_allowed: false,
    auto_enable_allowed: false,
    bootstrap_allowed: false,
    flags,
  });
});

export default router;