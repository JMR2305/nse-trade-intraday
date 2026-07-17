import { Ionicons } from "@expo/vector-icons";
import { useGetTrades } from "@workspace/api-client-react";
import React from "react";
import {
  Platform,
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
import { Phase20Position, usePhase20Positions } from "@/lib/monitorApi";
import { useOfflineSnapshot } from "@/lib/offlineCache";

interface Trade {
  symbol?: string;
  action?: string;
  quantity?: number;
  price?: number;
  timestamp?: string;
}

function fmtInr(value: number, digits = 0) {
  return `₹${value.toLocaleString("en-IN", { maximumFractionDigits: digits })}`;
}

function PositionCard({ item }: { item: Phase20Position }) {
  const colors = useColors();
  const pnl = item.pnl ?? 0;
  const isPos = pnl >= 0;
  const pnlColor = isPos ? colors.success : colors.destructive;

  return (
    <View style={[styles.posCard, { backgroundColor: colors.card, borderColor: colors.border }]}>
      <View style={styles.posTop}>
        <View>
          <Text style={[styles.posSymbol, { color: colors.foreground }]}>{item.symbol ?? "—"}</Text>
          <Text style={[styles.posMeta, { color: colors.mutedForeground }]}>
            {item.qty ?? 0} × {fmtInr(item.entry_price ?? 0, 2)}
          </Text>
        </View>
        <View style={styles.posRight}>
          <Text style={[styles.posPnl, { color: pnlColor }]}>
            {isPos ? "+" : ""}{fmtInr(pnl)}
          </Text>
          <Text style={[styles.posPct, { color: pnlColor }]}>
            {isPos ? "+" : ""}{(item.pnl_pct ?? 0).toFixed(2)}%
          </Text>
        </View>
      </View>
      <View style={[styles.posBottom, { borderTopColor: colors.border }]}>
        <View style={styles.posStat}>
          <Text style={[styles.posStatLabel, { color: colors.mutedForeground }]}>Current</Text>
          <Text style={[styles.posStatValue, { color: colors.foreground }]}>
            {item.current_price != null ? fmtInr(item.current_price, 2) : "—"}
          </Text>
        </View>
        <View style={styles.posStat}>
          <Text style={[styles.posStatLabel, { color: colors.mutedForeground }]}>Stop loss</Text>
          <Text style={[styles.posStatValue, { color: colors.foreground }]}>
            {item.stop_loss != null ? fmtInr(item.stop_loss, 2) : "—"}
          </Text>
        </View>
        <View style={styles.posStat}>
          <Text style={[styles.posStatLabel, { color: colors.mutedForeground }]}>Target</Text>
          <Text style={[styles.posStatValue, { color: colors.foreground }]}>
            {item.target != null ? fmtInr(item.target, 2) : "—"}
          </Text>
        </View>
      </View>
    </View>
  );
}

export default function PositionsScreen() {
  const colors = useColors();
  const insets = useSafeAreaInsets();
  const isWeb = Platform.OS === "web";
  const topPadding = isWeb ? 67 : insets.top;

  const positions = usePhase20Positions();
  const {
    data: liveTrades,
    isError: tradesError,
    refetch: refetchTrades,
    isFetching: fetchingTrades,
    dataUpdatedAt: tradesUpdatedAt,
  } = useGetTrades();

  const posSnapshot = useOfflineSnapshot(
    "phase20-positions",
    positions.data,
    positions.isError,
    positions.dataUpdatedAt,
  );
  const tradesSnapshot = useOfflineSnapshot("trades", liveTrades, tradesError, tradesUpdatedAt);

  const posData = posSnapshot.data;
  const posList = posData?.positions ?? [];
  const summary = posData?.summary;
  const totalPnl = summary?.total_pnl ?? 0;
  const trades = tradesSnapshot.data;
  const tradeList: Trade[] = Array.isArray(trades) ? trades.slice(0, 15) : [];
  const isStale = posSnapshot.isStale || tradesSnapshot.isStale;
  const staleTs = posSnapshot.staleTs ?? tradesSnapshot.staleTs;

  const onRefresh = () => Promise.all([positions.refetch(), refetchTrades()]);

  return (
    <ScrollView
      style={{ backgroundColor: colors.background }}
      contentContainerStyle={[styles.scroll, { paddingTop: topPadding + 16, paddingBottom: 120 }]}
      showsVerticalScrollIndicator={false}
      refreshControl={
        <RefreshControl
          refreshing={(positions.isFetching || fetchingTrades) && !positions.isLoading}
          onRefresh={onRefresh}
          tintColor={colors.primary}
        />
      }
    >
      <Text style={[styles.pageTitle, { color: colors.foreground }]}>Paper Positions</Text>
      <Text style={[styles.pageSub, { color: colors.mutedForeground }]}>
        Simulated trades only — no real money at risk
      </Text>

      {isStale && <StaleBanner staleTs={staleTs} onRetry={onRefresh} />}

      <View style={[styles.summaryCard, { backgroundColor: colors.primary }]}>
        <View>
          <Text style={[styles.summaryLabel, { color: colors.primaryForeground + "aa" }]}>Open P&L</Text>
          <Text style={[styles.summaryValue, { color: totalPnl >= 0 ? colors.primaryForeground : "#ff8080" }]}>
            {totalPnl >= 0 ? "+" : ""}{fmtInr(totalPnl)}
          </Text>
        </View>
        <View style={styles.summarySep} />
        <View>
          <Text style={[styles.summaryLabel, { color: colors.primaryForeground + "aa" }]}>Open Positions</Text>
          <Text style={[styles.summaryValue, { color: colors.primaryForeground }]}>
            {summary?.open_count ?? posList.length}
          </Text>
        </View>
      </View>

      {positions.isLoading && posData === undefined ? (
        <View style={styles.section}>
          <SkeletonCard lines={2} />
          <SkeletonCard lines={2} />
        </View>
      ) : positions.isError && posData === undefined ? (
        <View style={styles.empty}>
          <Ionicons name="cloud-offline-outline" size={40} color={colors.destructive} />
          <Text style={[styles.emptyText, { color: colors.mutedForeground }]}>
            Server unreachable and no saved positions yet
          </Text>
        </View>
      ) : posList.length === 0 ? (
        <View style={styles.empty}>
          <Ionicons name="file-tray-outline" size={40} color={colors.mutedForeground} />
          <Text style={[styles.emptyText, { color: colors.mutedForeground }]}>No open paper positions</Text>
        </View>
      ) : (
        <View style={styles.section}>
          {posList.map((pos, i) => (
            <PositionCard key={pos.symbol ?? i} item={pos} />
          ))}
        </View>
      )}

      {tradeList.length > 0 && (
        <View style={styles.section}>
          <Text style={[styles.sectionTitle, { color: colors.foreground }]}>Recent Trades</Text>
          <View style={[styles.sectionCard, { backgroundColor: colors.card, borderColor: colors.border }]}>
            {tradeList.map((t, i) => {
              const isBuy = t.action?.toUpperCase() === "BUY";
              return (
                <View key={`${t.symbol}-${i}`} style={[styles.tradeRow, { borderBottomColor: colors.border }]}>
                  <View
                    style={[
                      styles.tradeBadge,
                      { backgroundColor: (isBuy ? colors.success : colors.destructive) + "22" },
                    ]}
                  >
                    <Text style={[styles.tradeBadgeText, { color: isBuy ? colors.success : colors.destructive }]}>
                      {t.action?.toUpperCase() ?? "?"}
                    </Text>
                  </View>
                  <View style={styles.tradeInfo}>
                    <Text style={[styles.tradeSymbol, { color: colors.foreground }]}>{t.symbol ?? "—"}</Text>
                    <Text style={[styles.tradeDetail, { color: colors.mutedForeground }]}>
                      {t.quantity ?? 0} × {fmtInr(t.price ?? 0, 2)}
                    </Text>
                  </View>
                  <Text style={[styles.tradeTime, { color: colors.mutedForeground }]}>
                    {t.timestamp
                      ? new Date(t.timestamp).toLocaleDateString("en-IN", { month: "short", day: "numeric" })
                      : ""}
                  </Text>
                </View>
              );
            })}
          </View>
        </View>
      )}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  scroll: { paddingHorizontal: 16 },
  pageTitle: { fontSize: 28, fontFamily: "Inter_700Bold", letterSpacing: -0.5 },
  pageSub: { fontSize: 13, fontFamily: "Inter_400Regular", marginTop: 2, marginBottom: 16 },
  summaryCard: {
    flexDirection: "row",
    alignItems: "center",
    gap: 24,
    borderRadius: 16,
    padding: 20,
    marginBottom: 16,
  },
  summaryLabel: { fontSize: 12, fontFamily: "Inter_500Medium", marginBottom: 4 },
  summaryValue: { fontSize: 24, fontFamily: "Inter_700Bold", letterSpacing: -0.5 },
  summarySep: { width: 1, height: 40, backgroundColor: "rgba(255,255,255,0.3)" },
  section: { marginBottom: 20, gap: 10 },
  sectionTitle: { fontSize: 16, fontFamily: "Inter_600SemiBold", marginBottom: 8 },
  sectionCard: { borderRadius: 12, borderWidth: StyleSheet.hairlineWidth, overflow: "hidden" },
  posCard: { borderRadius: 12, borderWidth: StyleSheet.hairlineWidth, padding: 14 },
  posTop: { flexDirection: "row", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 12 },
  posSymbol: { fontSize: 16, fontFamily: "Inter_700Bold" },
  posMeta: { fontSize: 12, fontFamily: "Inter_400Regular", marginTop: 2 },
  posRight: { alignItems: "flex-end" },
  posPnl: { fontSize: 16, fontFamily: "Inter_700Bold" },
  posPct: { fontSize: 12, fontFamily: "Inter_500Medium", marginTop: 2 },
  posBottom: { flexDirection: "row", paddingTop: 10, borderTopWidth: StyleSheet.hairlineWidth },
  posStat: { flex: 1 },
  posStatLabel: { fontSize: 10, fontFamily: "Inter_500Medium", marginBottom: 2 },
  posStatValue: { fontSize: 13, fontFamily: "Inter_600SemiBold" },
  empty: { alignItems: "center", gap: 8, paddingVertical: 32 },
  emptyText: { fontSize: 14, fontFamily: "Inter_400Regular", textAlign: "center" },
  tradeRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 12,
    padding: 14,
    borderBottomWidth: StyleSheet.hairlineWidth,
  },
  tradeBadge: { paddingHorizontal: 8, paddingVertical: 4, borderRadius: 6 },
  tradeBadgeText: { fontSize: 11, fontFamily: "Inter_700Bold" },
  tradeInfo: { flex: 1, gap: 2 },
  tradeSymbol: { fontSize: 14, fontFamily: "Inter_600SemiBold" },
  tradeDetail: { fontSize: 12, fontFamily: "Inter_400Regular" },
  tradeTime: { fontSize: 11, fontFamily: "Inter_400Regular" },
});
