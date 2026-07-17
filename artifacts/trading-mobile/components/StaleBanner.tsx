import { Ionicons } from "@expo/vector-icons";
import React from "react";
import { Pressable, StyleSheet, Text, View } from "react-native";

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
  const amber = "#d97706";
  return (
    <View style={[styles.banner, { backgroundColor: amber + "18", borderColor: amber }]}>
      <Ionicons name="cloud-offline-outline" size={16} color={amber} />
      <Text style={[styles.text, { color: amber }]}>
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
