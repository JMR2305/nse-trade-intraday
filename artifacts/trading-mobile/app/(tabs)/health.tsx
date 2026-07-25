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
  useColorScheme,
} from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { FreshnessStatusBadge } from "@/components/FreshnessLabel";
import { Skeleton } from "@/components/Skeleton";
import { StaleBanner } from "@/components/StaleBanner";
import { useColors } from "@/hooks/useColors";
import {
  BASE,
  useBrokerStatus,
  useDisableAutoPaperEntries,
  useKiteStatus,
  useLiveDataHealth,
  usePhase20Settings,
  useRiskKillSwitch,
  useSchedulerHealth,
} from "@/lib/monitorApi";
import { SnapshotSource, useOfflineSnapshot } from "@/lib/offlineCache";
import { AppHeader } from "@/components/AppHeader";
import { computeFreshness } from "@/components/FreshnessLabel";

// ── Market index definitions ───────────────────────────────────────────────────
// NIFTY / BANK NIFTY / INDIA VIX are fetched as part of the scan watchlist.
// On mobile there is no SSE stream; freshness is derived from the overall
// scan connection status and last-scan timestamp.
const MARKET_INDICES = [
  { key: "NIFTY",     label: "NIFTY 50"   },
  { key: "BANKNIFTY", label: "BANK NIFTY" },
  { key: "INDIAVIX",  label: "INDIA VIX"  },
] as const;

// Map the backend connectionStatus string to a SnapshotSource understood by
// computeFreshness / FreshnessStatusBadge.
//   HEALTHY  → "live"          (data is actively refreshed)
//   DEGRADED → "memory"        (data present but provider degraded → DELAYED)
//   anything else → "offline-cache"  (cached data, provider offline → CACHED)
//   undefined / null → "none"  (no data ever received → UNAVAILABLE)
function connectionStatusToSource(status?: string | null): SnapshotSource {
  if (!status) return "none";
  if (status === "HEALTHY") return "live";
  if (status === "DEGRADED") return "memory";
  return "offline-cache";
}

// Worst source across sections wins; age shown is the oldest data timestamp.
const SOURCE_RANK: Record<SnapshotSource, number> = { none: 3, "offline-cache": 2, memory: 1, live: 0 };
function combineFreshness(
  snaps: { source: SnapshotSource; dataTs: number | null }[],
): { source: SnapshotSource; ts: number | null } {
  let worst: SnapshotSource = "live";
  let oldest: number | null = null;
  for (const s of snaps) {
    if (SOURCE_RANK[s.source] > SOURCE_RANK[worst]) worst = s.source;
    if (s.dataTs != null && (oldest == null || s.dataTs < oldest)) oldest = s.dataTs;
  }
  return { source: worst, ts: oldest };
}

type Tone = "good" | "bad" | "warn" | "muted";

// Warn colour: dark amber (#8A4B00) on light bg gives 8.8:1 contrast;
// light amber (#F6C453) on dark bg gives 9.2:1 contrast — both pass WCAG AA.
function toneColor(tone: Tone, colors: ReturnType<typeof useColors>, isDark: boolean) {
  if (tone === "good") return colors.success;
  if (tone === "bad") return colors.destructive;
  if (tone === "warn") return isDark ? "#F6C453" : "#8A4B00";
  return colors.mutedForeground;
}

function StatusPill({ label, tone }: { label: string; tone: Tone }) {
  const colors = useColors();
  const isDark = useColorScheme() === "dark";
  const c = toneColor(tone, colors, isDark);
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
  const isDark = useColorScheme() === "dark";
  const warnColor = isDark ? "#F6C453" : "#8A4B00";
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

  const freshness = combineFreshness([liveSnap, schedSnap, settingsSnap, kiteSnap, killSnap, brokerSnap]);

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
    <View style={{ flex: 1, backgroundColor: colors.background }}>
      <AppHeader />
      <ScrollView
        style={{ flex: 1 }}
        contentContainerStyle={[styles.scroll, { paddingTop: 16, paddingBottom: 120 }]}
        showsVerticalScrollIndicator={false}
        refreshControl={
          <RefreshControl refreshing={isFetching} onRefresh={refetchAll} tintColor={colors.primary} />
        }
      >
      <Text style={[styles.pageTitle, { color: colors.foreground }]}>System Health</Text>
      <Text style={[styles.pageSub, { color: colors.mutedForeground }]}>
        Monitoring only — no orders can be placed from this app
      </Text>
      <FreshnessStatusBadge
        ts={freshness.ts}
        source={freshness.source}
        sourceLabel="yfinance / NSE"
        style={{ marginBottom: 14 }}
      />

      {anyStale && <StaleBanner staleTs={staleTs} onRetry={refetchAll} />}

      {/* ── Market Indices ─────────────────────────────────────────────────
           Each index card shows its own canonical freshness badge derived from
           the overall scan connection status. Mobile has no SSE stream, so the
           three indices share the same scan snapshot but each carries an
           independent badge (not a single global bar). */}
      <Section title="Market Indices">
        {live.isLoading && liveData === undefined ? (
          <RowsSkeleton rows={3} />
        ) : (
          (() => {
            const indexSource = connectionStatusToSource(liveData?.connectionStatus);
            // Convert ISO timestamp to epoch ms; computeFreshness expects ms.
            const lastScanMs = liveData?.lastScanTs
              ? new Date(liveData.lastScanTs).getTime()
              : null;
            return (
              <>
                {MARKET_INDICES.map(({ key, label }) => {
                  // Each index independently shows its freshness status.
                  // Currently all three derive from the same scan snapshot;
                  // when per-symbol quality data is exposed by the API they
                  // can diverge without any component-level changes.
                  const band = computeFreshness(lastScanMs, indexSource, Date.now());
                  return (
                    <View
                      key={key}
                      style={[styles.indexRow, { borderBottomColor: colors.border }]}
                      testID={`index-card-${key}`}
                    >
                      <Text style={[styles.indexLabel, { color: colors.foreground }]}>
                        {label}
                      </Text>
                      <FreshnessStatusBadge
                        ts={lastScanMs}
                        source={indexSource}
                        sourceLabel="yfinance / NSE"
                      />
                      {/* Status text for screen readers / quick scan */}
                      <Text style={[styles.indexBand, {
                        color: band === "LIVE" ? colors.success
                          : band === "UNAVAILABLE" ? colors.mutedForeground
                          : colors.destructive,
                      }]}>
                        {band}
                      </Text>
                    </View>
                  );
                })}
                <Text style={[styles.indexNote, { color: colors.mutedForeground }]}>
                  Values shown at last scan · Live ticker available on desktop
                </Text>
              </>
            );
          })()
        )}
      </Section>

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
                  ? warnColor
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
              valueColor={autoEntries ? warnColor : colors.mutedForeground}
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

      {/* Dev-only diagnostics — shows resolved API origin so operators can confirm
          connectivity at a glance. Hidden in production builds (__DEV__ = false). */}
      {__DEV__ && (
        <View style={[styles.diagnostics, { borderColor: colors.border }]}>
          <Text style={[styles.diagnosticsLabel, { color: colors.mutedForeground }]}>
            🔌 DEV — API origin
          </Text>
          <Text style={[styles.diagnosticsValue, { color: colors.mutedForeground }]} numberOfLines={1}>
            {BASE}
          </Text>
        </View>
      )}
    </ScrollView>
    </View>
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
  // Market Indices section
  indexRow: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    paddingVertical: 10,
    borderBottomWidth: StyleSheet.hairlineWidth,
    gap: 8,
    flexWrap: "wrap",
  },
  indexLabel: { fontSize: 13, fontFamily: "Inter_600SemiBold", minWidth: 90 },
  indexBand: { fontSize: 10, fontFamily: "Inter_700Bold", letterSpacing: 0.4, flexShrink: 0 },
  indexNote: { fontSize: 11, fontFamily: "Inter_400Regular", paddingVertical: 10, textAlign: "center" },
  diagnostics: {
    borderTopWidth: StyleSheet.hairlineWidth,
    paddingVertical: 10,
    paddingHorizontal: 4,
    marginTop: 4,
    gap: 2,
  },
  diagnosticsLabel: { fontSize: 10, fontFamily: "Inter_500Medium", letterSpacing: 0.3 },
  diagnosticsValue: { fontSize: 10, fontFamily: "Inter_400Regular" },
});
