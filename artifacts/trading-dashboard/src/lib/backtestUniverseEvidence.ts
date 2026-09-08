export type BacktestUniverseEvidence =
  | "HISTORICAL_SNAPSHOT"
  | "CURRENT_MEMBERSHIP_FALLBACK"
  | "HISTORICAL_SNAPSHOT_UNAVAILABLE";

export interface UniverseResolution {
  evidence?: BacktestUniverseEvidence | string;
  source?: string;
  as_of_date?: string | null;
  snapshot_at?: string | null;
  degraded?: boolean;
}

export interface UniverseEvidenceNotice {
  tone: "verified" | "warning";
  heading: string;
  detail: string;
}

export function getUniverseEvidenceNotice(
  evidence?: string | null,
  resolution?: UniverseResolution | null,
): UniverseEvidenceNotice | null {
  const asOfDate = resolution?.as_of_date ? ` as of ${resolution.as_of_date}` : "";
  if (evidence === "HISTORICAL_SNAPSHOT") {
    const snapshotAt = resolution?.snapshot_at
      ? ` Snapshot recorded ${new Date(resolution.snapshot_at).toLocaleString()}.`
      : "";
    return {
      tone: "verified",
      heading: "Immutable historical universe snapshot used",
      detail: `Membership was resolved from the recorded universe${asOfDate}.${snapshotAt}`,
    };
  }
  if (evidence === "CURRENT_MEMBERSHIP_FALLBACK") {
    return {
      tone: "warning",
      heading: "Current universe membership fallback used",
      detail: `No immutable universe snapshot existed${asOfDate}. This run used today's active list, which can introduce look-ahead bias; treat its results as degraded evidence.`,
    };
  }
  return null;
}