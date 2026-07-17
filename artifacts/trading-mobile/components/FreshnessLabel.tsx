import { Ionicons } from "@expo/vector-icons";
import React, { useEffect, useState } from "react";
import { StyleSheet, Text, View } from "react-native";

import { useColors } from "@/hooks/useColors";
import { formatAge, SnapshotSource } from "@/lib/offlineCache";

// Ticks every ~30s so age labels stay current without any refetch.
function useNow(intervalMs = 30_000): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), intervalMs);
    return () => clearInterval(id);
  }, [intervalMs]);
  return now;
}

/**
 * Subtle "Updated X ago" label for live data. Renders nothing until a
 * successful fetch has happened (ts falsy). The label re-renders on a
 * 30-second tick so the age stays accurate between refetches.
 */
export function FreshnessLabel({
  ts,
  color,
  style,
}: {
  ts: number | null | undefined;
  color?: string;
  style?: object;
}) {
  const colors = useColors();
  useNow();
  if (!ts) return null;
  const labelColor = color ?? colors.mutedForeground;
  return (
    <View style={[styles.row, style]}>
      <Ionicons name="time-outline" size={11} color={labelColor} />
      <Text style={[styles.text, { color: labelColor }]}>
        Updated {formatAge(ts)}
      </Text>
    </View>
  );
}

export type FreshnessBand = "FRESH" | "AGING" | "STALE" | "OFFLINE CACHE" | "UNAVAILABLE";

const FRESH_LIMIT_MS = 5 * 60_000;
const AGING_LIMIT_MS = 15 * 60_000;

/**
 * Classify the shown data. Ages are computed from the backend data timestamp
 * (fetch/snapshot time of a real payload), never from screen-render time.
 */
export function computeFreshness(
  ts: number | null | undefined,
  source: SnapshotSource,
  now: number,
): FreshnessBand {
  if (source === "none" || (!ts && source !== "live")) return "UNAVAILABLE";
  if (source === "offline-cache") return "OFFLINE CACHE";
  if (!ts) return "FRESH"; // live data just arrived without a recorded ts
  const age = now - ts;
  if (age < FRESH_LIMIT_MS) return "FRESH";
  if (age < AGING_LIMIT_MS) return "AGING";
  return "STALE";
}

/**
 * "FRESH · Updated 2 minutes ago" style badge for Positions, Health and
 * Alerts tabs. The age label re-renders on a 30-second tick — the underlying
 * data timestamp is never fabricated or refreshed by the tick.
 */
export function FreshnessStatusBadge({
  ts,
  source,
  style,
}: {
  ts: number | null | undefined;
  source: SnapshotSource;
  style?: object;
}) {
  const colors = useColors();
  const now = useNow();
  const band = computeFreshness(ts, source, now);

  const tone =
    band === "FRESH"
      ? colors.success
      : band === "AGING"
      ? "#d4a017"
      : band === "OFFLINE CACHE"
      ? colors.primary
      : band === "UNAVAILABLE"
      ? colors.mutedForeground
      : colors.destructive;

  const ageText =
    band === "UNAVAILABLE"
      ? "no data received"
      : band === "OFFLINE CACHE"
      ? `cached ${formatAge(ts ?? null)}`
      : `Updated ${formatAge(ts ?? null)}`;

  return (
    <View style={[badgeStyles.row, style]}>
      <View style={[badgeStyles.pill, { backgroundColor: tone + "1c", borderColor: tone + "55" }]}>
        <View style={[badgeStyles.dot, { backgroundColor: tone }]} />
        <Text style={[badgeStyles.pillText, { color: tone }]}>{band}</Text>
      </View>
      <Text style={[badgeStyles.age, { color: band === "OFFLINE CACHE" ? tone : colors.mutedForeground }]}>
        {ageText}
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  row: { flexDirection: "row", alignItems: "center", gap: 4 },
  text: { fontSize: 11, fontFamily: "Inter_400Regular" },
});

const badgeStyles = StyleSheet.create({
  row: { flexDirection: "row", alignItems: "center", gap: 8, flexWrap: "wrap" },
  pill: {
    flexDirection: "row",
    alignItems: "center",
    gap: 5,
    paddingHorizontal: 8,
    paddingVertical: 3,
    borderRadius: 10,
    borderWidth: StyleSheet.hairlineWidth,
  },
  dot: { width: 6, height: 6, borderRadius: 3 },
  pillText: { fontSize: 10, fontFamily: "Inter_700Bold", letterSpacing: 0.4 },
  age: { fontSize: 11, fontFamily: "Inter_400Regular" },
});
