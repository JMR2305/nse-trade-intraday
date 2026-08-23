import os from "node:os";

export interface RuntimeIdentity {
  environment: "production" | "development" | "unknown";
  git_commit: string;
  build_id: string;
  deployment_id: string;
  instance_id: string;
  runtime_timestamp: string;
}

function firstNonEmpty(...values: Array<string | undefined>): string | undefined {
  return values.map((value) => value?.trim()).find(Boolean);
}

function isGenericBuildId(value: string | undefined): boolean {
  return value === "apexquant-v1.0.0";
}

/**
 * Public, non-secret process identity for production-vs-source reconciliation.
 * Values intentionally exclude credentials, tokens, and connection details.
 */
export function runtimeIdentity(): RuntimeIdentity {
  const isProduction = process.env.NODE_ENV === "production";
  const declaredEnvironment = firstNonEmpty(
    process.env.ENVIRONMENT,
    process.env.NODE_ENV,
  );

  return {
    environment: isProduction
      ? "production"
      : declaredEnvironment === "development"
        ? "development"
        : "unknown",
    git_commit: firstNonEmpty(
      process.env.APEXQUANT_GIT_COMMIT,
      process.env.REPLIT_GIT_COMMIT,
    ) ?? (isProduction ? "production-unidentified" : "unknown"),
    build_id: firstNonEmpty(
      isGenericBuildId(process.env.APEXQUANT_BUILD_ID)
        ? undefined
        : process.env.APEXQUANT_BUILD_ID,
      process.env.BUILD_ID,
    ) ?? (isProduction ? "production-unidentified" : "unknown"),
    deployment_id: firstNonEmpty(
      process.env.REPLIT_DEPLOYMENT_ID,
      process.env.REPLIT_DEPLOYMENT,
    ) ?? "unknown",
    instance_id: firstNonEmpty(
      process.env.REPLIT_INSTANCE_ID,
      process.env.INSTANCE_ID,
      process.env.HOSTNAME,
    ) ?? os.hostname(),
    runtime_timestamp: new Date().toISOString(),
  };
}