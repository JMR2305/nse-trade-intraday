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

/**
 * Canonical data-status vocabulary — Phase C (Data Truthfulness).
 *
 * LIVE        — fresh data from a connected live feed (age < 5 min)
 * DELAYED     — provider connected but delivery is slow (was AGING)
 * STALE       — data age has crossed the staleness threshold
 * CACHED      — data from a previous snapshot; provider offline (was OFFLINE CACHE)
 * UNAVAILABLE — no data has ever been received
 *
 * Renamed from the legacy vocabulary:
 *   AGING        → DELAYED  (more honest: the data is merely late, not corrupted)
 *   OFFLINE CACHE → CACHED  (shorter, matches the canonical vocabulary)
 *   FRESH        → LIVE     (signals an active, connected feed)
 */
export type FreshnessBand = "LIVE" | "DELAYED" | "STALE" | "CACHED" | "UNAVAILABLE";

const FRESH_LIMIT_MS = 5 * 60_000;   // < 5 min  → LIVE
const DELAYED_LIMIT_MS = 15 * 60_000; // < 15 min → DELAYED (was AGING_LIMIT_MS)

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
  if (source === "offline-cache") return "CACHED";   // was "OFFLINE CACHE"
  if (!ts) return "LIVE"; // live data just arrived without a recorded ts
  const age = now - ts;
  if (age < FRESH_LIMIT_MS) return "LIVE";           // was "FRESH"
  if (age < DELAYED_LIMIT_MS) return "DELAYED";      // was "AGING"
  return "STALE";
}

/**
 * "LIVE · yfinance / NSE · Updated 2 minutes ago" style badge for Positions,
 * Health, and Alerts tabs. The age label re-renders on a 30-second tick —
 * the underlying data timestamp is never fabricated or refreshed by the tick.
 *
 * Optional `sourceLabel` (e.g. "yfinance / NSE") is shown beneath the pill
 * when provided, giving operators full traceability of where the data came from.
 */
export function FreshnessStatusBadge({
  ts,
  source,
  sourceLabel,
  style,
}: {
  ts: number | null | undefined;
  source: SnapshotSource;
  /** Human-readable data source name, e.g. "yfinance / NSE". Optional. */
  sourceLabel?: string;
  style?: object;
}) {
  const colors = useColors();
  const now = useNow();
  const band = computeFreshness(ts, source, now);

  // Colour mapping for the canonical vocabulary
  const tone =
    band === "LIVE"
      ? colors.success          // green  — connected, fresh
      : band === "DELAYED"
      ? "#F59E0B"               // amber  — slow / partially missing
      : band === "CACHED"
      ? colors.primary          // blue   — offline cache
      : band === "UNAVAILABLE"
      ? colors.mutedForeground  // grey   — no data
      : colors.destructive;     // red    — STALE

  const ageText =
    band === "UNAVAILABLE"
      ? "no data received"
      : band === "CACHED"
      ? `cached ${formatAge(ts ?? null)}`
      : `Updated ${formatAge(ts ?? null)}`;

  return (
    <View style={[badgeStyles.row, style]}>
      <View style={[badgeStyles.pill, { backgroundColor: tone + "1c", borderColor: tone + "55" }]}>
        {/* Connection dot — pulses when LIVE */}
        <View style={[badgeStyles.dot, { backgroundColor: tone }]} />
        <Text style={[badgeStyles.pillText, { color: tone }]}>{band}</Text>
      </View>
      <View style={badgeStyles.metaCol}>
        {sourceLabel ? (
          <Text style={[badgeStyles.source, { color: colors.mutedForeground }]}>
            {sourceLabel}
          </Text>
        ) : null}
        <Text style={[badgeStyles.age, { color: band === "CACHED" ? tone : colors.mutedForeground }]}>
          {ageText}
        </Text>
      </View>
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
  metaCol: { flexDirection: "column", gap: 1 },
  source: { fontSize: 9, fontFamily: "Inter_400Regular", letterSpacing: 0.2 },
  age: { fontSize: 11, fontFamily: "Inter_400Regular" },
});
