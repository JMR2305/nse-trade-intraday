export const CONTROLLED_PAPER_ENTRY_FLAG_NAMES = [
  "CONTROLLED_PAPER_ENTRY_FRAMEWORK_ENABLED",
  "CONTROLLED_PAPER_ENTRY_DRY_RUN_ONLY",
  "CONTROLLED_PAPER_ENTRY_REQUIRE_PHASE1H_PASS",
  "CONTROLLED_PAPER_ENTRY_REQUIRE_OPERATOR_APPROVAL",
  "CONTROLLED_PAPER_ENTRY_ALLOW_AUTO_ENABLE",
  "CONTROLLED_PAPER_ENTRY_ALLOW_BOOTSTRAP",
] as const;

export type ControlledPaperEntryFlags = {
  frameworkEnabled: boolean;
  dryRunOnly: boolean;
  requirePhase1hPass: boolean;
  requireOperatorApproval: boolean;
  allowAutoEnable: boolean;
  allowBootstrap: boolean;
  reviewGateSafe: boolean;
  executionAllowed: false;
};

function safeBoolean(value: unknown, safeDefault: boolean): boolean {
  const token = String(value ?? "").trim().toLowerCase();
  if (token === "true") return true;
  if (token === "false") return false;
  return safeDefault;
}

export function readControlledPaperEntryFlags(
  env: NodeJS.ProcessEnv = process.env,
): ControlledPaperEntryFlags {
  const flags = {
    frameworkEnabled: safeBoolean(env.CONTROLLED_PAPER_ENTRY_FRAMEWORK_ENABLED, false),
    dryRunOnly: safeBoolean(env.CONTROLLED_PAPER_ENTRY_DRY_RUN_ONLY, true),
    requirePhase1hPass: safeBoolean(env.CONTROLLED_PAPER_ENTRY_REQUIRE_PHASE1H_PASS, true),
    requireOperatorApproval: safeBoolean(
      env.CONTROLLED_PAPER_ENTRY_REQUIRE_OPERATOR_APPROVAL,
      true,
    ),
    allowAutoEnable: safeBoolean(env.CONTROLLED_PAPER_ENTRY_ALLOW_AUTO_ENABLE, false),
    allowBootstrap: safeBoolean(env.CONTROLLED_PAPER_ENTRY_ALLOW_BOOTSTRAP, false),
  };

  return {
    ...flags,
    reviewGateSafe:
      flags.frameworkEnabled &&
      flags.dryRunOnly &&
      flags.requirePhase1hPass &&
      flags.requireOperatorApproval &&
      !flags.allowAutoEnable &&
      !flags.allowBootstrap,
    executionAllowed: false,
  };
}