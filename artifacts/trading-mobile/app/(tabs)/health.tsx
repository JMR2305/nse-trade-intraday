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

  const cbOpen = (live.data?.circuitBreaker ?? "").toUpperCase() === "OPEN";
  const marketState = live.data?.marketState ?? "UNKNOWN";
  const autoEntries = settings.data?.auto_paper_entries === true;
  const killActive = kill.data?.active === true;
  const kiteOk = (kite.data?.token_status ?? "").toUpperCase() === "VALID";
  const quality = live.data?.qualitySummary;
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

      <Section
        title="Live Data"
        pill={
          live.isLoading ? undefined : (
            <StatusPill
              label={marketState.replace(/_/g, " ")}
              tone={marketState === "OPEN" ? "good" : "muted"}
            />
          )
        }
      >
        {live.isLoading ? (
          <ActivityIndicator style={styles.loader} color={colors.primary} />
        ) : live.isError ? (
          <Text style={[styles.errorText, { color: colors.destructive }]}>Could not load live data health</Text>
        ) : (
          <>
            <Row label="Provider" value={live.data?.provider ?? "—"} />
            <Row
              label="Circuit breaker"
              value={cbOpen ? "OPEN — data paused" : "CLOSED — normal"}
              valueColor={cbOpen ? colors.destructive : colors.success}
            />
            <Row label="Consecutive failures" value={String(live.data?.consecutiveFailures ?? 0)} />
            <Row label="Last successful fetch" value={fmtTs(live.data?.lastSuccessTs)} />
            <Row label="Last scan" value={fmtTs(live.data?.lastScanTs)} />
            <Row
              label="Scan connection"
              value={live.data?.connectionStatus ?? "—"}
              valueColor={
                live.data?.connectionStatus === "HEALTHY"
                  ? colors.success
                  : live.data?.connectionStatus === "DEGRADED"
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
          sched.isLoading ? undefined : (
            <StatusPill
              label={(sched.data?.status ?? "unknown").toUpperCase()}
              tone={sched.data?.status === "active" ? "good" : "muted"}
            />
          )
        }
      >
        {sched.isLoading || settings.isLoading ? (
          <ActivityIndicator style={styles.loader} color={colors.primary} />
        ) : sched.isError && settings.isError ? (
          <Text style={[styles.errorText, { color: colors.destructive }]}>Could not load automation health</Text>
        ) : (
          <>
            <Row label="Last success" value={fmtTs(sched.data?.last_success_at)} />
            <Row label="Last attempt" value={fmtTs(sched.data?.last_attempt_at)} />
            <Row label="Next due" value={fmtTs(sched.data?.next_due_at)} />
            <Row
              label="Missed runs"
              value={String(sched.data?.missed_count ?? 0)}
              valueColor={(sched.data?.missed_count ?? 0) > 0 ? colors.destructive : undefined}
            />
            {sched.data?.detail ? <Row label="Status detail" value={sched.data.detail} /> : null}
            <Row
              label="Auto scans"
              value={
                settings.data?.auto_scan_enabled
                  ? `Every ${settings.data?.scan_interval_minutes ?? "—"} min`
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
                settings.data?.min_confidence != null
                  ? `≥${settings.data.min_confidence}% conf, max ${settings.data?.max_trades_per_day ?? "—"}/day`
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
          kill.isLoading ? undefined : (
            <StatusPill label={killActive ? "KILL SWITCH ON" : "NORMAL"} tone={killActive ? "bad" : "good"} />
          )
        }
      >
        {kill.isLoading || broker.isLoading ? (
          <ActivityIndicator style={styles.loader} color={colors.primary} />
        ) : (
          <>
            <Row
              label="Risk kill switch"
              value={killActive ? "ACTIVE" : "Inactive"}
              valueColor={killActive ? colors.destructive : colors.success}
            />
            {killActive && kill.data?.reason ? <Row label="Reason" value={kill.data.reason} /> : null}
            {killActive && kill.data?.triggered_at ? (
              <Row label="Triggered" value={fmtTs(kill.data.triggered_at)} />
            ) : null}
            <Row label="Execution mode" value={(broker.data?.execution_mode ?? "—").replace(/_/g, " ")} />
            <Row
              label="Broker kill switch"
              value={broker.data?.safety_controls?.kill_switch ? "ACTIVE" : "Inactive"}
              valueColor={broker.data?.safety_controls?.kill_switch ? colors.destructive : colors.success}
            />
            {broker.data?.broker?.is_mock ? (
              <Row label="Broker" value={`${broker.data?.broker?.broker ?? "Mock"} — no real orders`} />
            ) : null}
          </>
        )}
      </Section>

      <Section
        title="Zerodha Connection"
        pill={
          kite.isLoading ? undefined : (
            <StatusPill label={kiteOk ? "CONNECTED" : "NOT CONNECTED"} tone={kiteOk ? "good" : "muted"} />
          )
        }
      >
        {kite.isLoading ? (
          <ActivityIndicator style={styles.loader} color={colors.primary} />
        ) : kite.isError ? (
          <Text style={[styles.errorText, { color: colors.destructive }]}>Could not load Zerodha status</Text>
        ) : (
          <>
            <Row
              label="Session token"
              value={(kite.data?.token_status ?? "UNKNOWN").toUpperCase()}
              valueColor={kiteOk ? colors.success : colors.mutedForeground}
            />
            <Row
              label="Credentials"
              value={kite.data?.credentials_present ? "Configured" : "Not configured"}
            />
            {kite.data?.token_age_hours != null ? (
              <Row label="Token age" value={`${kite.data.token_age_hours.toFixed(1)} h`} />
            ) : null}
            {kite.data?.token_expiry_note ? (
              <Row label="Expiry" value={kite.data.token_expiry_note} />
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
