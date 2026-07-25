/**
 * AppHeader — ApexQuant AI branded top bar for every mobile tab page.
 * Shows the pyramid mark (navy/cream + teal bars+arrow), wordmark, and PAPER badge.
 * Handles its own safe-area top inset so callers don't need topPadding logic.
 */
import React from "react";
import { StyleSheet, Text, View, useColorScheme } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import Svg, { Path, Polyline, Rect } from "react-native-svg";

interface AppHeaderProps {
  /** Pass true when the parent already applied top safe-area padding. */
  noSafeArea?: boolean;
}

export function AppHeader({ noSafeArea = false }: AppHeaderProps) {
  const insets = useSafeAreaInsets();
  const scheme = useColorScheme();
  const isDark = scheme === "dark";

  // A-frame + bar fill = navy in light, cream in dark
  const markColor = isDark ? "#F7F4ED" : "#17395F";
  const wordColor = isDark ? "#F7F4ED" : "#17395F";
  // Teal accent is fixed across both themes
  const teal = "#129C8C";

  return (
    <View
      style={[
        styles.header,
        { paddingTop: noSafeArea ? 8 : insets.top + 8 },
        isDark ? styles.dark : styles.light,
      ]}
    >
      {/* ── Logo mark ── */}
      <View style={styles.logoRow}>
        <Svg width={22} height={20} viewBox="0 0 60 56">
          {/* Left leg of A-frame */}
          <Path d="M3,54 L16,54 L30,4 Z" fill={markColor} />
          {/* Right leg of A-frame */}
          <Path d="M57,54 L44,54 L30,4 Z" fill={markColor} />
          {/* Rising bar chart (teal) */}
          <Rect x="20" y="44" width="4" height="10" fill={teal} />
          <Rect x="26" y="36" width="4" height="18" fill={teal} />
          <Rect x="32" y="28" width="4" height="26" fill={teal} />
          {/* Trend line + arrow (teal) */}
          <Polyline
            points="20,50 26,38 32,30 43,18"
            stroke={teal}
            strokeWidth="3"
            fill="none"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
          <Path d="M43,18 L42,24 L37,20 Z" fill={teal} />
        </Svg>

        {/* ── Wordmark ── */}
        <Text style={[styles.wordmark, { color: wordColor }]}>
          ApexQuant{"\u2009"}
          <Text style={[styles.wordmarkAi, { color: teal }]}>AI</Text>
        </Text>
      </View>

      {/* ── PAPER badge ── */}
      <View style={[styles.badge, isDark ? styles.badgeDark : styles.badgeLight]}>
        <Text style={[styles.badgeText, isDark ? styles.badgeTextDark : styles.badgeTextLight]}>
          PAPER
        </Text>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  header: {
    flexDirection: "row",
    alignItems: "center",
    paddingHorizontal: 16,
    paddingBottom: 10,
    borderBottomWidth: StyleSheet.hairlineWidth,
  },
  light: {
    backgroundColor: "#F7F4ED",
    borderBottomColor: "#E5E0D8",
  },
  dark: {
    backgroundColor: "#0F1923",
    borderBottomColor: "#1E2A38",
  },
  logoRow: {
    flex: 1,
    flexDirection: "row",
    alignItems: "center",
    gap: 7,
  },
  wordmark: {
    fontSize: 15,
    fontFamily: "Inter_700Bold",
    letterSpacing: -0.3,
  },
  wordmarkAi: {
    fontSize: 15,
    fontFamily: "Inter_700Bold",
    letterSpacing: -0.3,
  },
  badge: {
    borderRadius: 999,
    borderWidth: 1,
    paddingHorizontal: 8,
    paddingVertical: 2,
  },
  badgeLight: {
    backgroundColor: "#FFF4D8",
    borderColor: "#C9851840",
  },
  badgeDark: {
    backgroundColor: "#2B2211",
    borderColor: "#8A641860",
  },
  badgeText: {
    fontSize: 9,
    fontFamily: "Inter_700Bold",
    letterSpacing: 1.2,
  },
  badgeTextLight: { color: "#8A4B00" },
  badgeTextDark:  { color: "#F6C453" },
});
