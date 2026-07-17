import { Ionicons } from "@expo/vector-icons";
import * as Haptics from "expo-haptics";
import React, { useEffect, useState } from "react";
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
import { StaleBanner } from "@/components/StaleBanner";
import { useColors } from "@/hooks/useColors";
import {
  useBrokerStatus,
  useDisableAutoPaperEntries,
  useKiteStatus,
  useLiveDataHealth,
  usePhase20Settings,
  useRiskKillSwitch,
  useSchedulerHealth,
} from "@/lib/monitorApi";
import { useOfflineSnapshot } from "@/lib/offlineCache";

type Tone = "good" | "bad" | "warn" | "muted";

function toneColor(tone: Tone, colors: ReturnType<typeof useColors>) {
  if (tone === "good") return colors.success;
  if (tone === "bad") return colors.destructive;
  if (tone === "warn") return "#d97706";
  return colors.mutedForeground;
}

function StatusPill({ label, tone }: { label: string; tone: Tone }) {
  const colors = useColors();
  const c = toneColor(tone, colors);
  return (
    <View style={[styles.pill, { backgroundColor: c + "22" }]}>
      <View style={[styles.pillDot, { backgroundColor: c }]} />
      <Text style={[styles.pillText, { color: c }]}>{label}</Text>
    </View>
  );
}

function Row({ label, value, valueColor }: { label: string; value: string; valueColor?: string }) {
  const colors = useColors();
  return (
    <View style={[styles.row, { borderBottomColor: colors.border }]}>
      <Text style={[styles.rowLabel, { color: colors.mutedForeground }]}>{label}</Text>
      <Text style={[styles.rowValue, { color: valueColor ?? colors.foreground }]} numberOfLines={1}>
        {value}
      </Text>
    </View>
  );
}

function Section({
  title,
  pill,
  children,
}: {
  title: string;
  pill?: React.ReactNode;
  children: React.ReactNode;
}) {
  const colors = useColors();
  return (
    <View style={styles.section}>
      <View style={styles.sectionHeader}>
        <Text style={[styles.sectionTitle, { color: colors.foreground }]}>{title}</Text>
        {pill}
      </View>
      <View style={[styles.card, { backgroundColor: colors.card, borderColor: colors.border }]}>
        {children}
      </View>
    </View>
  );
}

function RowsSkeleton({ rows = 4 }: { rows?: number }) {
  return (
    <View style={{ paddingVertical: 12, gap: 14 }}>
      {Array.from({ length: rows }).map((_, i) => (
        <Skeleton key={i} style={{ width: i % 2 === 0 ? "100%" : "70%", height: 13 }} />
      ))}
    </View>
  );
}

function fmtTs(ts?: string | null) {
  if (!ts) return "—";
  const d = new Date(ts);
  if (isNaN(d.getTime())) return "—";
  return d.toLocaleString("en-IN", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

export default function HealthScreen() {
  const colors = useColors();
  const insets = useSafeAreaInsets();
  const isWeb = Platform.OS === "web";
  const topPadding = isWeb ? 67 : insets.top;

  const live = useLiveDataHealth();
  const sched = useSchedulerHealth();
  const settings = usePhase20Settings();
  const kite = useKiteStatus();
  const kill = useRiskKillSwitch();
  const broker = useBrokerStatus();
  const disableAuto = useDisableAutoPaperEntries();

  const liveSnap = useOfflineSnapshot("health-live", live.data, live.isError, live.dataUpdatedAt);
  const schedSnap = useOfflineSnapshot("health-sched", sched.data, sched.isError, sched.dataUpdatedAt);
  const settingsSnap = useOfflineSnapshot(
    "health-settings",
    settings.data,
    settings.isError,
    settings.dataUpdatedAt,
  );
  const kiteSnap = useOfflineSnapshot("health-kite", kite.data, kite.isError, kite.dataUpdatedAt);
  const killSnap = useOfflineSnapshot("health-kill", kill.data, kill.isError, kill.dataUpdatedAt);
  const brokerSnap = useOfflineSnapshot(
    "health-broker",
    broker.data,
    broker.isError,
    broker.dataUpdatedAt,
  );

  const liveData = liveSnap.data;
  const schedData = schedSnap.data;
  const settingsData = settingsSnap.data;
  const kiteData = kiteSnap.data;
  const killData = killSnap.data;
  const brokerData = brokerSnap.data;

  const anyStale =
    liveSnap.isStale || schedSnap.isStale || settingsSnap.isStale || kiteSnap.isStale || killSnap.isStale || brokerSnap.isStale;
  const staleTs =
    liveSnap.staleTs ?? schedSnap.staleTs ?? settingsSnap.staleTs ?? kiteSnap.staleTs ?? killSnap.staleTs ?? brokerSnap.staleTs;

  const [confirmDisable, setConfirmDisable] = useState(false);
  useEffect(() => {
    if (!confirmDisable) return;
    const t = setTimeout(() => setConfirmDisable(false), 4000);
    return () => clearTimeout(t);
  }, [confirmDisable]);

  const refetchAll = () =>
    Promise.all([
      live.refetch(),
      sched.refetch(),
      settings.refetch(),
      kite.refetch(),
      kill.refetch(),
      broker.refetch(),
    ]);

  const isFetching =
    live.isFetching || sched.isFetching || settings.isFetching || kite.isFetching;

  const cbOpen = (liveData?.circuitBreaker ?? "").toUpperCase() === "OPEN";
  const marketState = liveData?.marketState ?? "UNKNOWN";
  const autoEntries = settingsData?.auto_paper_entries === true;
  const killActive = killData?.active === true;
  const kiteOk = (kiteData?.token_status ?? "").toUpperCase() === "VALID";
  const quality = liveData?.qualitySummary;
  const qualityText = quality
    ? Object.entries(quality)
        .filter(([, v]) => (v ?? 0) > 0)
        .map(([k, v]) => `${v} ${k}`)
        .join(", ")
    : "—";

  const handleDisable = async () => {
    if (!confirmDisable) {
      Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium);
      setConfirmDisable(true);
      return;
    }
    setConfirmDisable(false);
    Haptics.notificationAsync(Haptics.NotificationFeedbackType.Warning);
    try {
      await disableAuto.mutateAsync();
    } catch {
      // error surfaced via disableAuto.isError below
    }
  };

  return (
    <ScrollView
      style={{ backgroundColor: colors.background }}
      contentContainerStyle={[styles.scroll, { paddingTop: topPadding + 16, paddingBottom: 120 }]}
      showsVerticalScrollIndicator={false}
      refreshControl={
        <RefreshControl refreshing={isFetching} onRefresh={refetchAll} tintColor={colors.primary} />
      }
    >
      <Text style={[styles.pageTitle, { color: colors.foreground }]}>System Health</Text>
      <Text style={[styles.pageSub, { color: colors.mutedForeground }]}>
        Monitoring only — no orders can be placed from this app
      </Text>

      {anyStale && <StaleBanner staleTs={staleTs} onRetry={refetchAll} />}

      <Section
        title="Live Data"
        pill={
          live.isLoading && liveData === undefined ? undefined : (
            <StatusPill
              label={marketState.replace(/_/g, " ")}
              tone={marketState === "OPEN" ? "good" : "muted"}
            />
          )
        }
      >
        {live.isLoading && liveData === undefined ? (
          <RowsSkeleton rows={5} />
        ) : live.isError && liveData === undefined ? (
          <Text style={[styles.errorText, { color: colors.destructive }]}>Could not load live data health</Text>
        ) : (
          <>
            <Row label="Provider" value={liveData?.provider ?? "—"} />
            <Row
              label="Circuit breaker"
              value={cbOpen ? "OPEN — data paused" : "CLOSED — normal"}
              valueColor={cbOpen ? colors.destructive : colors.success}
            />
            <Row label="Consecutive failures" value={String(liveData?.consecutiveFailures ?? 0)} />
            <Row label="Last successful fetch" value={fmtTs(liveData?.lastSuccessTs)} />
            <Row label="Last scan" value={fmtTs(liveData?.lastScanTs)} />
            <Row
              label="Scan connection"
              value={liveData?.connectionStatus ?? "—"}
              valueColor={
                liveData?.connectionStatus === "HEALTHY"
                  ? colors.success
                  : liveData?.connectionStatus === "DEGRADED"
                  ? "#d97706"
                  : undefined
              }
            />
            <Row label="Symbol quality" value={qualityText} />
          </>
        )}
      </Section>

      <Section
        title="Automation"
        pill={
          sched.isLoading && schedData === undefined ? undefined : (
            <StatusPill
              label={(schedData?.status ?? "unknown").toUpperCase()}
              tone={schedData?.status === "active" ? "good" : "muted"}
            />
          )
        }
      >
        {(sched.isLoading || settings.isLoading) && schedData === undefined && settingsData === undefined ? (
          <RowsSkeleton rows={5} />
        ) : sched.isError && settings.isError && schedData === undefined && settingsData === undefined ? (
          <Text style={[styles.errorText, { color: colors.destructive }]}>Could not load automation health</Text>
        ) : (
          <>
            <Row label="Last success" value={fmtTs(schedData?.last_success_at)} />
            <Row label="Last attempt" value={fmtTs(schedData?.last_attempt_at)} />
            <Row label="Next due" value={fmtTs(schedData?.next_due_at)} />
            <Row
              label="Missed runs"
              value={String(schedData?.missed_count ?? 0)}
              valueColor={(schedData?.missed_count ?? 0) > 0 ? colors.destructive : undefined}
            />
            {schedData?.detail ? <Row label="Status detail" value={schedData.detail} /> : null}
            <Row
              label="Auto scans"
              value={
                settingsData?.auto_scan_enabled
                  ? `Every ${settingsData?.scan_interval_minutes ?? "—"} min`
                  : "Disabled"
              }
            />
            <Row
              label="Auto paper entries"
              value={autoEntries ? "ENABLED" : "Disabled"}
              valueColor={autoEntries ? "#d97706" : colors.mutedForeground}
            />
            <Row
              label="Entry gate"
              value={
                settingsData?.min_confidence != null
                  ? `≥${settingsData.min_confidence}% conf, max ${settingsData?.max_trades_per_day ?? "—"}/day`
                  : "—"
              }
            />

            {autoEntries && (
              <View style={styles.actionWrap}>
                <Pressable
                  style={[
                    styles.disableBtn,
                    { backgroundColor: confirmDisable ? colors.destructive : colors.destructive + "18", borderColor: colors.destructive },
                  ]}
                  onPress={handleDisable}
                  disabled={disableAuto.isPending}
                  testID="disable-auto-entries-btn"
                >
                  {disableAuto.isPending ? (
                    <ActivityIndicator size="small" color={confirmDisable ? "#fff" : colors.destructive} />
                  ) : (
                    <Ionicons
                      name="hand-left-outline"
                      size={16}
                      color={confirmDisable ? "#fff" : colors.destructive}
                    />
                  )}
                  <Text style={[styles.disableBtnText, { color: confirmDisable ? "#fff" : colors.destructive }]}>
                    {confirmDisable ? "Tap again to confirm" : "Disable auto paper entries"}
                  </Text>
                </Pressable>
                <Text style={[styles.actionHint, { color: colors.mutedForeground }]}>
                  Stops new automatic paper entries. Re-enabling requires the desktop dashboard.
                </Text>
              </View>
            )}
            {disableAuto.isError && (
              <Text style={[styles.errorText, { color: colors.destructive }]}>
                Could not update setting. Pull to refresh and try again.
              </Text>
            )}
            {disableAuto.isSuccess && !autoEntries && (
              <Text style={[styles.successText, { color: colors.success }]}>
                Auto paper entries disabled.
              </Text>
            )}
          </>
        )}
      </Section>

      <Section
        title="Safety"
        pill={
          kill.isLoading && killData === undefined ? undefined : (
            <StatusPill label={killActive ? "KILL SWITCH ON" : "NORMAL"} tone={killActive ? "bad" : "good"} />
          )
        }
      >
        {(kill.isLoading || broker.isLoading) && killData === undefined && brokerData === undefined ? (
          <RowsSkeleton rows={3} />
        ) : kill.isError && broker.isError && killData === undefined && brokerData === undefined ? (
          <Text style={[styles.errorText, { color: colors.destructive }]}>Could not load safety status</Text>
        ) : (
          <>
            <Row
              label="Risk kill switch"
              value={killActive ? "ACTIVE" : "Inactive"}
              valueColor={killActive ? colors.destructive : colors.success}
            />
            {killActive && killData?.reason ? <Row label="Reason" value={killData.reason} /> : null}
            {killActive && killData?.triggered_at ? (
              <Row label="Triggered" value={fmtTs(killData.triggered_at)} />
            ) : null}
            <Row label="Execution mode" value={(brokerData?.execution_mode ?? "—").replace(/_/g, " ")} />
            <Row
              label="Broker kill switch"
              value={brokerData?.safety_controls?.kill_switch ? "ACTIVE" : "Inactive"}
              valueColor={brokerData?.safety_controls?.kill_switch ? colors.destructive : colors.success}
            />
            {brokerData?.broker?.is_mock ? (
              <Row label="Broker" value={`${brokerData?.broker?.broker ?? "Mock"} — no real orders`} />
            ) : null}
          </>
        )}
      </Section>

      <Section
        title="Zerodha Connection"
        pill={
          kite.isLoading && kiteData === undefined ? undefined : (
            <StatusPill label={kiteOk ? "CONNECTED" : "NOT CONNECTED"} tone={kiteOk ? "good" : "muted"} />
          )
        }
      >
        {kite.isLoading && kiteData === undefined ? (
          <RowsSkeleton rows={3} />
        ) : kite.isError && kiteData === undefined ? (
          <Text style={[styles.errorText, { color: colors.destructive }]}>Could not load Zerodha status</Text>
        ) : (
          <>
            <Row
              label="Session token"
              value={(kiteData?.token_status ?? "UNKNOWN").toUpperCase()}
              valueColor={kiteOk ? colors.success : colors.mutedForeground}
            />
            <Row
              label="Credentials"
              value={kiteData?.credentials_present ? "Configured" : "Not configured"}
            />
            {kiteData?.token_age_hours != null ? (
              <Row label="Token age" value={`${kiteData.token_age_hours.toFixed(1)} h`} />
            ) : null}
            {kiteData?.token_expiry_note ? (
              <Row label="Expiry" value={kiteData.token_expiry_note} />
            ) : null}
            <Text style={[styles.readonlyNote, { color: colors.mutedForeground }]}>
              Read-only. Connect or disconnect from the desktop dashboard.
            </Text>
          </>
        )}
      </Section>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  scroll: { paddingHorizontal: 16 },
  pageTitle: { fontSize: 28, fontFamily: "Inter_700Bold", letterSpacing: -0.5 },
  pageSub: { fontSize: 13, fontFamily: "Inter_400Regular", marginTop: 2, marginBottom: 16 },
  section: { marginBottom: 20 },
  sectionHeader: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", marginBottom: 8 },
  sectionTitle: { fontSize: 16, fontFamily: "Inter_600SemiBold" },
  card: { borderRadius: 12, borderWidth: StyleSheet.hairlineWidth, overflow: "hidden", paddingHorizontal: 14 },
  row: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    paddingVertical: 12,
    borderBottomWidth: StyleSheet.hairlineWidth,
    gap: 12,
  },
  rowLabel: { fontSize: 13, fontFamily: "Inter_500Medium" },
  rowValue: { fontSize: 13, fontFamily: "Inter_600SemiBold", flexShrink: 1, textAlign: "right" },
  pill: { flexDirection: "row", alignItems: "center", gap: 5, paddingHorizontal: 8, paddingVertical: 4, borderRadius: 12 },
  pillDot: { width: 6, height: 6, borderRadius: 3 },
  pillText: { fontSize: 10, fontFamily: "Inter_700Bold", letterSpacing: 0.4 },
  loader: { paddingVertical: 24 },
  errorText: { fontSize: 13, fontFamily: "Inter_400Regular", paddingVertical: 12 },
  successText: { fontSize: 13, fontFamily: "Inter_500Medium", paddingVertical: 12 },
  actionWrap: { paddingVertical: 12, gap: 8 },
  disableBtn: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 8,
    paddingVertical: 12,
    borderRadius: 10,
    borderWidth: 1,
  },
  disableBtnText: { fontSize: 14, fontFamily: "Inter_600SemiBold" },
  actionHint: { fontSize: 11, fontFamily: "Inter_400Regular", textAlign: "center" },
  readonlyNote: { fontSize: 11, fontFamily: "Inter_400Regular", paddingVertical: 12 },
});
