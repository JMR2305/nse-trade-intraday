import { Ionicons } from "@expo/vector-icons";
import { useGetPortfolio } from "@workspace/api-client-react";
import React from "react";
import {
  ActivityIndicator,
  Platform,
  Pressable,
  RefreshControl,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { Skeleton } from "@/components/Skeleton";
import { FreshnessLabel } from "@/components/FreshnessLabel";
import { StaleBanner } from "@/components/StaleBanner";
import { useColors } from "@/hooks/useColors";
import { useOfflineSnapshot } from "@/lib/offlineCache";
import { AppHeader } from "@/components/AppHeader";
import {
  useKiteStatus,
  useLiveDataHealth,
  usePhase20Positions,
  usePhase20Settings,
  useRiskKillSwitch,
  useSchedulerHealth,
} from "@/lib/monitorApi";

interface Portfolio {
  cash?: number;
  total_value?: number;
  invested_value?: number;
  total_pnl?: number;
  total_pnl_pct?: number;
}

function formatInr(value: number) {
  const abs = Math.abs(value);
  if (abs >= 1e7) return `₹${(value / 1e7).toFixed(2)}Cr`;
  if (abs >= 1e5) return `₹${(value / 1e5).toFixed(2)}L`;
  return `₹${value.toLocaleString("en-IN", { maximumFractionDigits: 0 })}`;
}

function StatCard({
  label,
  value,
  positive,
}: {
  label: string;
  value: string;
  positive?: boolean | null;
}) {
  const colors = useColors();
  const valueColor =
    positive === true ? colors.success : positive === false ? colors.destructive : colors.foreground;
  return (
    <View style={[styles.statCard, { backgroundColor: colors.card, borderColor: colors.border }]}>
      <Text style={[styles.statLabel, { color: colors.mutedForeground }]}>{label}</Text>
      <Text style={[styles.statValue, { color: valueColor }]}>{value}</Text>
    </View>
  );
}

function StatusTile({
  icon,
  label,
  value,
  ok,
  loading,
}: {
  icon: keyof typeof Ionicons.glyphMap;
  label: string;
  value: string;
  ok: boolean | null;
  loading?: boolean;
}) {
  const colors = useColors();
  const c = ok === true ? colors.success : ok === false ? colors.destructive : colors.mutedForeground;
  return (
    <View style={[styles.tile, { backgroundColor: colors.card, borderColor: colors.border }]}>
      <View style={[styles.tileIcon, { backgroundColor: c + "18" }]}>
        <Ionicons name={icon} size={16} color={c} />
      </View>
      <Text style={[styles.tileLabel, { color: colors.mutedForeground }]}>{label}</Text>
      {loading ? (
        <Skeleton style={{ width: 64, height: 16 }} />
      ) : (
        <Text style={[styles.tileValue, { color: c }]} numberOfLines={1}>
          {value}
        </Text>
      )}
    </View>
  );
}

export default function DashboardScreen() {
  const colors = useColors();
  const insets = useSafeAreaInsets();
  const isWeb = Platform.OS === "web";
  const topPadding = isWeb ? 67 : insets.top;

  const {
    data: livePortfolio,
    isLoading,
    isError,
    refetch: refetchPortfolio,
    isFetching,
    dataUpdatedAt,
  } = useGetPortfolio();

  const {
    data: portfolio,
    isStale: portfolioStale,
    staleTs,
  } = useOfflineSnapshot("portfolio", livePortfolio, isError, dataUpdatedAt);

  const live = useLiveDataHealth();
  const sched = useSchedulerHealth();
  const settings = usePhase20Settings();
  const kite = useKiteStatus();
  const kill = useRiskKillSwitch();
  const p20 = usePhase20Positions();

  const p = portfolio as Portfolio | undefined;
  const totalPnl = p?.total_pnl ?? 0;

  const marketState = live.data?.marketState ?? "—";
  const cbOpen = (live.data?.circuitBreaker ?? "").toUpperCase() === "OPEN";
  const schedStatus = (sched.data?.status ?? "").toUpperCase();
  const schedActive = schedStatus === "ACTIVE" || schedStatus === "RUNNING";
  const autoEntries = settings.data?.auto_paper_entries === true;
  const kiteOk = (kite.data?.token_status ?? "").toUpperCase() === "VALID";
  const killActive = kill.data?.active === true;
  const openCount = p20.data?.summary?.open_count ?? p20.data?.positions?.length ?? 0;
  const openPnl = p20.data?.summary?.total_pnl ?? 0;

  const onRefresh = () =>
    Promise.all([
      refetchPortfolio(),
      live.refetch(),
      sched.refetch(),
      settings.refetch(),
      kite.refetch(),
      kill.refetch(),
      p20.refetch(),
    ]);

  if (isError && portfolio === undefined) {
    return (
      <View style={{ flex: 1, backgroundColor: colors.background }}>
        <AppHeader />
        <View style={[styles.center]}>
          <Ionicons name="cloud-offline-outline" size={48} color={colors.destructive} />
          <Text style={[styles.errorText, { color: colors.mutedForeground }]}>
            Server unreachable and no saved data yet.
          </Text>
          <Text style={[styles.errorText, { color: colors.mutedForeground }]}>
            It may be starting up — try again in a moment.
          </Text>
          <Pressable style={[styles.retryBtn, { borderColor: colors.border }]} onPress={() => refetchPortfolio()}>
            <Text style={[styles.retryText, { color: colors.primary }]}>Try again</Text>
          </Pressable>
        </View>
      </View>
    );
  }

  return (
    <View style={{ flex: 1, backgroundColor: colors.background }}>
      <AppHeader />
      <ScrollView
        style={{ flex: 1 }}
        contentContainerStyle={[styles.scroll, { paddingTop: 16, paddingBottom: 120 }]}
      showsVerticalScrollIndicator={false}
      refreshControl={
        <RefreshControl refreshing={isFetching && !isLoading} onRefresh={onRefresh} tintColor={colors.primary} />
      }
    >
      <View style={styles.pageHeader}>
        <Text style={[styles.greeting, { color: colors.mutedForeground }]}>
          {new Date().toLocaleDateString("en-IN", { weekday: "long", month: "long", day: "numeric" })}
        </Text>
        <Text style={[styles.pageTitle, { color: colors.foreground }]}>Dashboard</Text>
      </View>

      {portfolioStale && <StaleBanner staleTs={staleTs} onRetry={() => refetchPortfolio()} />}

      {killActive && (
        <View style={[styles.banner, { backgroundColor: colors.destructive + "18", borderColor: colors.destructive }]}>
          <Ionicons name="warning" size={16} color={colors.destructive} />
          <Text style={[styles.bannerText, { color: colors.destructive }]}>
            Risk kill switch is active{kill.data?.reason ? `: ${kill.data.reason}` : ""}
          </Text>
        </View>
      )}
      {cbOpen && (
        <View style={[styles.banner, { backgroundColor: "#d9770618", borderColor: "#d97706" }]}>
          <Ionicons name="flash-off" size={16} color="#d97706" />
          <Text style={[styles.bannerText, { color: "#d97706" }]}>
            Data provider circuit breaker is open — quotes paused
          </Text>
        </View>
      )}

      <View style={[styles.heroCard, { backgroundColor: colors.primary }]}>
        <Text style={[styles.heroLabel, { color: colors.primaryForeground + "aa" }]}>Paper Portfolio Value</Text>
        {isLoading && portfolio === undefined ? (
          <Skeleton style={{ width: 180, height: 40, marginBottom: 16, backgroundColor: "rgba(255,255,255,0.3)" }} />
        ) : (
          <Text style={[styles.heroValue, { color: colors.primaryForeground }]}>
            {formatInr(p?.total_value ?? 0)}
          </Text>
        )}
        <View style={styles.heroRow}>
          <View>
            <Text style={[styles.heroLabel, { color: colors.primaryForeground + "aa" }]}>Total P&L</Text>
            <Text style={[styles.heroPnl, { color: totalPnl >= 0 ? colors.primaryForeground : "#ff8080" }]}>
              {totalPnl >= 0 ? "+" : ""}{formatInr(totalPnl)}
            </Text>
          </View>
          <View style={styles.heroSep} />
          <View>
            <Text style={[styles.heroLabel, { color: colors.primaryForeground + "aa" }]}>Open Positions</Text>
            <Text style={[styles.heroPnl, { color: colors.primaryForeground }]}>
              {openCount}
              {openCount > 0 && (
                <Text style={{ fontSize: 13 }}>
                  {"  "}({openPnl >= 0 ? "+" : ""}{formatInr(openPnl)})
                </Text>
              )}
            </Text>
          </View>
        </View>
        {!portfolioStale && (
          <FreshnessLabel ts={dataUpdatedAt} color={colors.primaryForeground + "aa"} style={{ marginTop: 12 }} />
        )}
      </View>

      <View style={styles.statsRow}>
        <StatCard
          label="Invested"
          value={
            isLoading && portfolio === undefined
              ? "…"
              : p?.invested_value != null
              ? formatInr(p.invested_value)
              : "—"
          }
        />
        <StatCard
          label="Cash"
          value={p?.cash != null ? formatInr(p.cash) : "—"}
        />
        <StatCard
          label="P&L %"
          value={p?.total_pnl_pct != null ? `${p.total_pnl_pct >= 0 ? "+" : ""}${p.total_pnl_pct.toFixed(2)}%` : "—"}
          positive={p?.total_pnl_pct != null ? p.total_pnl_pct >= 0 : null}
        />
      </View>

      <Text style={[styles.sectionTitle, { color: colors.foreground }]}>System Status</Text>
      <View style={styles.tileGrid}>
        <StatusTile
          icon="pulse-outline"
          label="Market"
          value={String(marketState).replace(/_/g, " ")}
          ok={marketState === "OPEN" ? true : null}
          loading={live.isLoading}
        />
        <StatusTile
          icon="flash-outline"
          label="Data Circuit"
          value={cbOpen ? "OPEN" : "NORMAL"}
          ok={live.isError ? null : !cbOpen}
          loading={live.isLoading}
        />
        <StatusTile
          icon="cog-outline"
          label="Automation"
          value={sched.isError ? "—" : schedActive ? "ACTIVE" : "IDLE"}
          ok={sched.isError ? null : schedActive ? true : null}
          loading={sched.isLoading}
        />
        <StatusTile
          icon="repeat-outline"
          label="Auto Entries"
          value={settings.isError ? "—" : autoEntries ? "ON" : "OFF"}
          ok={settings.isError ? null : autoEntries ? false : true}
          loading={settings.isLoading}
        />
        <StatusTile
          icon="link-outline"
          label="Zerodha"
          value={kite.isError ? "—" : kiteOk ? "CONNECTED" : "OFFLINE"}
          ok={kite.isError ? null : kiteOk ? true : null}
          loading={kite.isLoading}
        />
        <StatusTile
          icon="shield-checkmark-outline"
          label="Kill Switch"
          value={kill.isError ? "—" : killActive ? "ACTIVE" : "NORMAL"}
          ok={kill.isError ? null : !killActive}
          loading={kill.isLoading}
        />
      </View>

      <View style={[styles.footerNote, { borderColor: colors.border }]}>
        <Ionicons name="eye-outline" size={14} color={colors.mutedForeground} />
        <Text style={[styles.footerNoteText, { color: colors.mutedForeground }]}>
          Monitoring-only app. Orders cannot be placed, modified or cancelled from here.
        </Text>
      </View>
    </ScrollView>
    </View>
  );
}

const styles = StyleSheet.create({
  scroll: { paddingHorizontal: 16 },
  center: { flex: 1, justifyContent: "center", alignItems: "center", gap: 12 },
  pageHeader: { marginBottom: 16 },
  greeting: { fontSize: 13, fontFamily: "Inter_400Regular", marginBottom: 2 },
  pageTitle: { fontSize: 28, fontFamily: "Inter_700Bold", letterSpacing: -0.5 },
  banner: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    borderRadius: 10,
    borderWidth: 1,
    padding: 12,
    marginBottom: 12,
  },
  bannerText: { flex: 1, fontSize: 12, fontFamily: "Inter_600SemiBold" },
  heroCard: { borderRadius: 16, padding: 20, marginBottom: 12 },
  heroLabel: { fontSize: 12, fontFamily: "Inter_500Medium", marginBottom: 4 },
  heroValue: { fontSize: 36, fontFamily: "Inter_700Bold", letterSpacing: -1, marginBottom: 16 },
  heroRow: { flexDirection: "row", alignItems: "center", gap: 20 },
  heroPnl: { fontSize: 18, fontFamily: "Inter_600SemiBold" },
  heroSep: { width: 1, height: 32, backgroundColor: "rgba(255,255,255,0.3)" },
  statsRow: { flexDirection: "row", gap: 10, marginBottom: 20 },
  statCard: { flex: 1, borderRadius: 12, borderWidth: StyleSheet.hairlineWidth, padding: 14 },
  statLabel: { fontSize: 11, fontFamily: "Inter_500Medium", marginBottom: 4 },
  statValue: { fontSize: 18, fontFamily: "Inter_700Bold" },
  sectionTitle: { fontSize: 16, fontFamily: "Inter_600SemiBold", marginBottom: 10 },
  tileGrid: { flexDirection: "row", flexWrap: "wrap", gap: 10, marginBottom: 20 },
  tile: {
    width: "48%" as const,
    flexGrow: 1,
    borderRadius: 12,
    borderWidth: StyleSheet.hairlineWidth,
    padding: 12,
    gap: 6,
  },
  tileIcon: { width: 28, height: 28, borderRadius: 14, alignItems: "center", justifyContent: "center" },
  tileLabel: { fontSize: 11, fontFamily: "Inter_500Medium" },
  tileValue: { fontSize: 14, fontFamily: "Inter_700Bold" },
  footerNote: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    borderTopWidth: StyleSheet.hairlineWidth,
    paddingTop: 14,
    paddingHorizontal: 4,
  },
  footerNoteText: { flex: 1, fontSize: 11, fontFamily: "Inter_400Regular", lineHeight: 16 },
  errorText: { fontSize: 14, fontFamily: "Inter_400Regular" },
  retryBtn: { marginTop: 8, paddingHorizontal: 20, paddingVertical: 10, borderRadius: 8, borderWidth: 1 },
  retryText: { fontSize: 14, fontFamily: "Inter_600SemiBold" },
});
