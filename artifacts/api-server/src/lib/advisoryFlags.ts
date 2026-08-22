export const ADVISORY_FLAG_NAMES = [
  "ADVISORY_BOTS_ENABLED",
  "ADVISORY_BOTS_API_ENABLED",
  "ADVISORY_BOTS_UI_ENABLED",
  "ADVISORY_BOTS_PERSIST_ENABLED",
  "ADVISORY_BOTS_SCHEDULER_ENABLED",
] as const;

export type AdvisoryFeatureFlags = {
  advisoryBotsEnabled: boolean;
  advisoryApiEnabled: boolean;
  advisoryUiEnabled: boolean;
  advisoryPersistEnabled: boolean;
  advisorySchedulerEnabled: boolean;
  isProduction: boolean;
  persistenceEnvironmentAllowed: boolean;
};

function isTrue(value: unknown): boolean {
  return String(value ?? "").trim().toLowerCase() === "true";
}

function normaliseEnvironment(value: unknown): string {
  return String(value ?? "").trim().toLowerCase();
}

/**
 * Persistence is safe only with a positive development/test attestation.
 * Missing, unknown, or conflicting environment markers fail closed.
 */
export function isAdvisoryPersistenceEnvironmentAllowed(
  env: NodeJS.ProcessEnv = process.env,
): boolean {
  const nodeEnvironment = normaliseEnvironment(env.NODE_ENV);
  const declaredEnvironment = normaliseEnvironment(env.ENVIRONMENT);
  if (nodeEnvironment !== "development" && nodeEnvironment !== "test") return false;
  return !declaredEnvironment || declaredEnvironment === nodeEnvironment;
}

export function readAdvisoryFlags(
  env: NodeJS.ProcessEnv = process.env,
): AdvisoryFeatureFlags {
  return {
    advisoryBotsEnabled: isTrue(env.ADVISORY_BOTS_ENABLED),
    advisoryApiEnabled: isTrue(env.ADVISORY_BOTS_API_ENABLED),
    advisoryUiEnabled: isTrue(env.ADVISORY_BOTS_UI_ENABLED),
    advisoryPersistEnabled: isTrue(env.ADVISORY_BOTS_PERSIST_ENABLED),
    advisorySchedulerEnabled: isTrue(env.ADVISORY_BOTS_SCHEDULER_ENABLED),
    isProduction: normaliseEnvironment(env.NODE_ENV) === "production",
    persistenceEnvironmentAllowed: isAdvisoryPersistenceEnvironmentAllowed(env),
  };
}