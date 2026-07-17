import { Feather, Ionicons } from "@expo/vector-icons";
import { useGetSignals, useGetTradeDecisions, useRunScan } from "@workspace/api-client-react";
import * as Haptics from "expo-haptics";
import React, { useCallback, useState } from "react";
import {
  ActivityIndicator,
  DimensionValue,
  Platform,
  Pressable,
  RefreshControl,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { SkeletonCard } from "@/components/Skeleton";
import { StaleBanner } from "@/components/StaleBanner";
import { useColors } from "@/hooks/useColors";
import { useOfflineSnapshot } from "@/lib/offlineCache";

type SignalAction = "BUY" | "SELL" | "HOLD" | string;

interface Signal {
  stock?: string;
  signal?: SignalAction;
  confidence?: number;
  price?: number;
  risk_level?: string;
  reasons?: string[];
  time?: string;
}

interface TradeDecision {
  stock?: string;
  sector?: string;
  recommendation?: string;
  data_status?: string;
  final_confidence?: number;
}

function getBadgeColors(action: SignalAction, colors: ReturnType<typeof useColors>) {
  if (action === "BUY") return { bg: colors.success, text: colors.successForeground };
  if (action === "SELL") return { bg: colors.destructive, text: colors.destructiveForeground };
  return { bg: colors.muted, text: colors.mutedForeground };
}

function SignalCard({ item }: { item: Signal }) {
  const colors = useColors();
  const action = (item.signal ?? "HOLD").toUpperCase().replace(/_/g, " ");
  const badge = getBadgeColors(action, colors);
  const confidence = Math.round(item.confidence ?? 0);
  const firstReason = Array.isArray(item.reasons) ? item.reasons[0] : undefined;

  return (
    <View style={[styles.card, { backgroundColor: colors.card, borderColor: colors.border }]}>
      <View style={styles.cardHeader}>
        <View style={styles.symbolRow}>
          <Text style={[styles.symbol, { color: colors.foreground }]}>{item.stock ?? "—"}</Text>
          <View style={[styles.badge, { backgroundColor: badge.bg }]}>
            <Text style={[styles.badgeText, { color: badge.text }]}>{action}</Text>
          </View>
        </View>
        {item.price != null && (
          <Text style={[styles.price, { color: colors.foreground }]}>
            ₹{item.price.toLocaleString("en-IN", { maximumFractionDigits: 2 })}
          </Text>
        )}
      </View>

      {confidence > 0 && (
        <View style={styles.confidenceRow}>
          <Text style={[styles.label, { color: colors.mutedForeground }]}>Confidence</Text>
          <View style={[styles.progressTrack, { backgroundColor: colors.muted }]}>
            <View
              style={[
                styles.progressFill,
                {
                  width: `${confidence}%` as DimensionValue,
                  backgroundColor:
                    action === "BUY" ? colors.success : action === "SELL" ? colors.destructive : colors.primary,
                },
              ]}
            />
          </View>
          <Text style={[styles.confidenceValue, { color: colors.foreground }]}>{confidence}%</Text>
        </View>
      )}

      {item.risk_level && (
        <Text style={[styles.strategy, { color: colors.mutedForeground }]}>Risk: {item.risk_level}</Text>
      )}
      {firstReason && (
        <Text style={[styles.reason, { color: colors.mutedForeground }]} numberOfLines={2}>
          {firstReason}
        </Text>
      )}
    </View>
  );
}

function DecisionCard({ item }: { item: TradeDecision }) {
  const colors = useColors();
  const decision = (item.recommendation ?? "—").toUpperCase().replace(/_/g, " ");
  const badge = getBadgeColors(decision, colors);
  const confidence = Math.round(item.final_confidence ?? 0);

  return (
    <View style={[styles.card, { backgroundColor: colors.card, borderColor: colors.border }]}>
      <View style={styles.cardHeader}>
        <View style={styles.symbolRow}>
          <Text style={[styles.symbol, { color: colors.foreground }]}>{item.stock ?? "—"}</Text>
          <View style={[styles.badge, { backgroundColor: badge.bg }]}>
            <Text style={[styles.badgeText, { color: badge.text }]}>{decision}</Text>
          </View>
        </View>
        {confidence > 0 && (
          <Text style={[styles.price, { color: colors.foreground }]}>{confidence}%</Text>
        )}
      </View>
      {item.sector ? (
        <Text style={[styles.strategy, { color: colors.mutedForeground }]}>{item.sector}</Text>
      ) : null}
      {item.data_status === "DATA_UNAVAILABLE" ? (
        <Text style={[styles.reason, { color: colors.mutedForeground }]}>Live data unavailable for this symbol</Text>
      ) : null}
    </View>
  );
}

export default function SignalsScreen() {
  const colors = useColors();
  const insets = useSafeAreaInsets();
  const isWeb = Platform.OS === "web";
  const [scanError, setScanError] = useState(false);

  const { data: liveSignals, isLoading, isError, refetch, isFetching, dataUpdatedAt } = useGetSignals();
  const decisions = useGetTradeDecisions();

  const {
    data: signals,
    isStale: signalsStale,
    staleTs,
  } = useOfflineSnapshot("signals", liveSignals, isError, dataUpdatedAt);
  const decisionsSnapshot = useOfflineSnapshot(
    "trade-decisions",
    decisions.data,
    decisions.isError,
    decisions.dataUpdatedAt,
  );
  const { mutateAsync: runScan, isPending: isScanning } = useRunScan();

  const handleScan = useCallback(async () => {
    Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium);
    setScanError(false);
    try {
      await runScan();
      await Promise.all([refetch(), decisions.refetch()]);
    } catch {
      setScanError(true);
    }
  }, [runScan, refetch, decisions]);

  const topPadding = isWeb ? 67 : insets.top;

  const rawSignals = signals as { signals?: Signal[] } | Signal[] | undefined;
  const signalList: Signal[] = Array.isArray(rawSignals)
    ? rawSignals
    : Array.isArray(rawSignals?.signals)
    ? rawSignals.signals
    : [];
  const rawDecisions = decisionsSnapshot.data as { decisions?: TradeDecision[] } | TradeDecision[] | undefined;
  const decisionList: TradeDecision[] = Array.isArray(rawDecisions)
    ? rawDecisions
    : Array.isArray(rawDecisions?.decisions)
    ? rawDecisions.decisions
    : [];

  return (
    <View style={[styles.container, { backgroundColor: colors.background }]}>
      <View
        style={[
          styles.header,
          { paddingTop: topPadding + 16, backgroundColor: colors.background, borderBottomColor: colors.border },
        ]}
      >
        <Text style={[styles.headerTitle, { color: colors.foreground }]}>Signals</Text>
        <Pressable
          style={[styles.scanBtn, { backgroundColor: colors.primary }, (isScanning || isFetching) && { opacity: 0.6 }]}
          onPress={handleScan}
          disabled={isScanning || isFetching}
          testID="run-scan-btn"
        >
          {isScanning || isFetching ? (
            <ActivityIndicator size="small" color={colors.primaryForeground} />
          ) : (
            <Feather name="refresh-cw" size={16} color={colors.primaryForeground} />
          )}
          <Text style={[styles.scanBtnText, { color: colors.primaryForeground }]}>Scan</Text>
        </Pressable>
      </View>

      {scanError && (
        <Text style={[styles.inlineError, { color: colors.destructive }]}>
          Scan failed. Check system health and try again.
        </Text>
      )}

      {isLoading && signals === undefined ? (
        <ScrollView contentContainerStyle={[styles.list, { paddingBottom: 120 }]} showsVerticalScrollIndicator={false}>
          <Text style={[styles.sectionTitle, { color: colors.foreground }]}>Latest Signals</Text>
          {[0, 1, 2, 3].map((i) => (
            <SkeletonCard key={i} lines={2} />
          ))}
        </ScrollView>
      ) : isError && signals === undefined ? (
        <View style={styles.center}>
          <Ionicons name="cloud-offline-outline" size={48} color={colors.destructive} />
          <Text style={[styles.errorText, { color: colors.mutedForeground }]}>
            Server unreachable and no saved signals yet
          </Text>
          <Pressable style={[styles.retryBtn, { borderColor: colors.border }]} onPress={() => refetch()}>
            <Text style={[styles.retryText, { color: colors.primary }]}>Try again</Text>
          </Pressable>
        </View>
      ) : (
        <ScrollView
          contentContainerStyle={[styles.list, { paddingBottom: 120 }]}
          showsVerticalScrollIndicator={false}
          refreshControl={
            <RefreshControl
              refreshing={isFetching && !isLoading}
              onRefresh={() => Promise.all([refetch(), decisions.refetch()])}
              tintColor={colors.primary}
            />
          }
        >
          {(signalsStale || decisionsSnapshot.isStale) && (
            <StaleBanner staleTs={staleTs ?? decisionsSnapshot.staleTs} onRetry={() => refetch()} />
          )}
          <Text style={[styles.sectionTitle, { color: colors.foreground }]}>Latest Signals</Text>
          {signalList.length === 0 ? (
            <View style={styles.empty}>
              <Ionicons name="pulse-outline" size={40} color={colors.mutedForeground} />
              <Text style={[styles.emptyText, { color: colors.mutedForeground }]}>
                No signals yet. Run a scan to generate signals.
              </Text>
            </View>
          ) : (
            signalList.map((s, i) => <SignalCard key={`${s.stock}-${i}`} item={s} />)
          )}

          <Text style={[styles.sectionTitle, { color: colors.foreground, marginTop: 12 }]}>Trade Decisions</Text>
          {decisions.isLoading && decisionsSnapshot.data === undefined ? (
            <>
              <SkeletonCard lines={1} />
              <SkeletonCard lines={1} />
            </>
          ) : decisionList.length === 0 ? (
            <View style={styles.empty}>
              <Ionicons name="git-branch-outline" size={40} color={colors.mutedForeground} />
              <Text style={[styles.emptyText, { color: colors.mutedForeground }]}>
                No trade decisions recorded yet
              </Text>
            </View>
          ) : (
            decisionList.map((d, i) => <DecisionCard key={`${d.stock}-${i}`} item={d} />)
          )}
        </ScrollView>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1 },
  header: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    paddingHorizontal: 20,
    paddingBottom: 16,
    borderBottomWidth: StyleSheet.hairlineWidth,
  },
  headerTitle: { fontSize: 28, fontFamily: "Inter_700Bold", letterSpacing: -0.5 },
  scanBtn: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    paddingHorizontal: 14,
    paddingVertical: 8,
    borderRadius: 20,
  },
  scanBtnText: { fontSize: 14, fontFamily: "Inter_600SemiBold" },
  inlineError: { fontSize: 12, fontFamily: "Inter_500Medium", paddingHorizontal: 20, paddingTop: 8 },
  list: { paddingTop: 12, paddingHorizontal: 16 },
  sectionTitle: { fontSize: 16, fontFamily: "Inter_600SemiBold", marginBottom: 8 },
  card: {
    borderRadius: 12,
    borderWidth: StyleSheet.hairlineWidth,
    padding: 16,
    marginBottom: 10,
  },
  cardHeader: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "flex-start",
    marginBottom: 10,
  },
  symbolRow: { flexDirection: "row", alignItems: "center", gap: 10 },
  symbol: { fontSize: 17, fontFamily: "Inter_700Bold", letterSpacing: -0.3 },
  badge: { paddingHorizontal: 8, paddingVertical: 3, borderRadius: 6 },
  badgeText: { fontSize: 11, fontFamily: "Inter_700Bold", letterSpacing: 0.5 },
  price: { fontSize: 16, fontFamily: "Inter_600SemiBold" },
  confidenceRow: { flexDirection: "row", alignItems: "center", gap: 8, marginBottom: 8 },
  label: { fontSize: 12, fontFamily: "Inter_500Medium", width: 72 },
  progressTrack: { flex: 1, height: 4, borderRadius: 2, overflow: "hidden" },
  progressFill: { height: "100%", borderRadius: 2 },
  confidenceValue: { fontSize: 12, fontFamily: "Inter_600SemiBold", width: 36, textAlign: "right" },
  strategy: { fontSize: 12, fontFamily: "Inter_500Medium", marginBottom: 4 },
  reason: { fontSize: 12, fontFamily: "Inter_400Regular", lineHeight: 18 },
  reasonRow: { flexDirection: "row", alignItems: "flex-start", gap: 8, marginBottom: 4 },
  reasonDot: { width: 4, height: 4, borderRadius: 2, marginTop: 7 },
  timeText: { fontSize: 11, fontFamily: "Inter_400Regular", marginTop: 6 },
  center: { flex: 1, justifyContent: "center", alignItems: "center", gap: 12 },
  empty: { alignItems: "center", gap: 8, paddingVertical: 24 },
  emptyText: { fontSize: 13, fontFamily: "Inter_400Regular", textAlign: "center", paddingHorizontal: 32 },
  errorText: { fontSize: 14, fontFamily: "Inter_400Regular" },
  retryBtn: { marginTop: 8, paddingHorizontal: 20, paddingVertical: 10, borderRadius: 8, borderWidth: 1 },
  retryText: { fontSize: 14, fontFamily: "Inter_600SemiBold" },
});
