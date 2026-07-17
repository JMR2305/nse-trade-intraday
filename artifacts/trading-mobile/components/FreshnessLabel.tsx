import { Ionicons } from "@expo/vector-icons";
import React, { useEffect, useState } from "react";
import { StyleSheet, Text, View } from "react-native";

import { useColors } from "@/hooks/useColors";
import { formatAge } from "@/lib/offlineCache";

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

const styles = StyleSheet.create({
  row: { flexDirection: "row", alignItems: "center", gap: 4 },
  text: { fontSize: 11, fontFamily: "Inter_400Regular" },
});
