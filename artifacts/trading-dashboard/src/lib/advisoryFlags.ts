export type AdvisoryUiFlags = {
  enabled: boolean;
  apiEnabled: boolean;
  persistEnabled: boolean;
  schedulerEnabled: boolean;
};

function isTrue(value: unknown): boolean {
  return String(value ?? "").trim().toLowerCase() === "true";
}

/**
 * Frontend flags are baked in by Vite. The VITE_ prefix is required for a
 * browser build; the value represents the same server-side
 * ADVISORY_BOTS_UI_ENABLED control and remains false when unset.
 */
export function readAdvisoryUiFlags(
  env: Record<string, unknown> = import.meta.env,
): AdvisoryUiFlags {
  return {
    enabled: isTrue(env.VITE_ADVISORY_BOTS_UI_ENABLED),
    apiEnabled: isTrue(env.VITE_ADVISORY_BOTS_API_ENABLED),
    persistEnabled: isTrue(env.VITE_ADVISORY_BOTS_PERSIST_ENABLED),
    schedulerEnabled: isTrue(env.VITE_ADVISORY_BOTS_SCHEDULER_ENABLED),
  };
}

export function isAdvisoryUiEnabled(): boolean {
  return readAdvisoryUiFlags().enabled;
}