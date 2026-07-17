import React, { useEffect, useRef } from "react";
import { Animated, StyleProp, StyleSheet, View, ViewStyle } from "react-native";

import { useColors } from "@/hooks/useColors";

export function Skeleton({ style }: { style?: StyleProp<ViewStyle> }) {
  const colors = useColors();
  const opacity = useRef(new Animated.Value(0.45)).current;

  useEffect(() => {
    const loop = Animated.loop(
      Animated.sequence([
        Animated.timing(opacity, { toValue: 1, duration: 700, useNativeDriver: true }),
        Animated.timing(opacity, { toValue: 0.45, duration: 700, useNativeDriver: true }),
      ]),
    );
    loop.start();
    return () => loop.stop();
  }, [opacity]);

  return (
    <Animated.View
      style={[styles.base, { backgroundColor: colors.muted, opacity }, style]}
    />
  );
}

export function SkeletonCard({ lines = 2 }: { lines?: number }) {
  const colors = useColors();
  return (
    <View style={[styles.card, { backgroundColor: colors.card, borderColor: colors.border }]}>
      <View style={styles.cardHeader}>
        <Skeleton style={{ width: 110, height: 18 }} />
        <Skeleton style={{ width: 64, height: 18 }} />
      </View>
      {Array.from({ length: lines }).map((_, i) => (
        <Skeleton key={i} style={{ width: i % 2 === 0 ? "100%" : "70%", height: 12, marginTop: 10 }} />
      ))}
    </View>
  );
}

const styles = StyleSheet.create({
  base: { borderRadius: 6 },
  card: {
    borderRadius: 12,
    borderWidth: StyleSheet.hairlineWidth,
    padding: 16,
    marginBottom: 10,
  },
  cardHeader: { flexDirection: "row", justifyContent: "space-between", alignItems: "center" },
});
