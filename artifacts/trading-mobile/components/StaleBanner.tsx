import { Ionicons } from "@expo/vector-icons";
import React from "react";
import { Pressable, StyleSheet, Text, View, useColorScheme } from "react-native";

import { useColors } from "@/hooks/useColors";
import { formatAge } from "@/lib/offlineCache";

export function StaleBanner({
  staleTs,
  onRetry,
}: {
  staleTs: number | null;
  onRetry?: () => void;
}) {
  const colors = useColors();
  const scheme = useColorScheme();
  // Dark amber (#8A4B00) on light bg: 8.8:1 contrast; light amber (#F6C453) on dark bg: 9.2:1
  const warnColor = scheme === "dark" ? "#F6C453" : "#8A4B00";
  return (
    <View style={[styles.banner, { backgroundColor: warnColor + "18", borderColor: warnColor }]}>
      <Ionicons name="cloud-offline-outline" size={16} color={warnColor} />
      <Text style={[styles.text, { color: warnColor }]}>
        Server unreachable — showing data from {formatAge(staleTs)}
      </Text>
      {onRetry ? (
        <Pressable onPress={onRetry} hitSlop={8}>
          <Text style={[styles.retry, { color: colors.primary }]}>Retry</Text>
        </Pressable>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  banner: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    borderRadius: 10,
    borderWidth: 1,
    padding: 12,
    marginBottom: 12,
  },
  text: { flex: 1, fontSize: 12, fontFamily: "Inter_600SemiBold" },
  retry: { fontSize: 12, fontFamily: "Inter_700Bold" },
});
