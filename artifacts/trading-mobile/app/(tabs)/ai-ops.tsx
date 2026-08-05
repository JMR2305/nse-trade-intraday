/**
 * AI Operations Centre — Mobile Screen
 *
 * Lightweight pipeline oversight panel for operators monitoring the
 * ApexQuant AI 12-agent pipeline from their phone.
 *
 * READ-ONLY · ADVISORY-ONLY · No trading controls.
 */

import { Ionicons } from "@expo/vector-icons";
import { Feather } from "@expo/vector-icons";
import * as Haptics from "expo-haptics";
import React, { useEffect, useRef, useState } from "react";
import {
  ActivityIndicator,
  Animated,
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

import { AppHeader } from "@/components/AppHeader";
import { Skeleton } from "@/components/Skeleton";
import { StaleBanner } from "@/components/StaleBanner";
import { useColors } from "@/hooks/useColors";
import { useOpsSnapshot, type AgentState, type OpsSnapshot } from "@/lib/monitorApi";
import { useOfflineSnapshot } from "@/lib/offlineCache";

// ── Constants ─────────────────────────────────────────────────────────────────

const AGENT_ORDER = [
  "supervisor",
  "market_data",
  "research",
  "market_intelligence",
  "monitoring",
  "strategy",
  "risk",
  "ai_decision",
  "execution",
  "learning",
  "knowledge",
  "operations",
] as const;

const AGENT_ICONS: Record<string, keyof typeof Feather.glyphMap> = {
  supervisor:          "git-branch",
  market_data:         "globe",
  research:            "book-open",
  market_intelligence: "cpu",
  monitoring:          "radio",
  strategy:            "trending-up",
  risk:                "shield",
  ai_decision:         "zap",
  execution:           "play-circle",
  learning:            "repeat",
  knowledge:           "database",
  operations:          "settings",
};

const AGENT_SHORT_NAMES: Record<string, string> = {
  supervisor:          "Supervisor",
  market_data:         "Mkt Data",
  research:            "Research",
  market_intelligence: "Intel",
  monitoring:          "Monitor",
  strategy:            "Strategy",
  risk:                "Risk",
  ai_decision:         "AI Dec",
  execution:           "Execution",
  learning:            "Learning",
  knowledge:           "Knowledge",
  operations:          "Ops",
};

// ── Helpers ───────────────────────────────────────────────────────────────────

type AgentStatus = "ACTIVE" | "WAITING" | "ERROR" | "DISABLED" | "UNKNOWN";

function statusColor(s: AgentStatus, colors: ReturnType<typeof useColors>, isDark: boolean) {
  switch (s) {
    case "ACTIVE":   return "#10B981";   // emerald-500
    case "WAITING":  return isDark ? "#F6C453" : "#8A4B00";
    case "ERROR":    return "#F43F5E";   // rose-500
    case "DISABLED": return colors.mutedForeground;
    default:         return colors.mutedForeground;
  }
}

function healthBarColor(pct: number) {
  if (pct >= 90) return "#10B981";
  if (pct >= 70) return "#F6C453";
  return "#F43F5E";
}

function fmtMs(ms: number) {
  if (!ms) return "—";
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

// ── Sub-components ────────────────────────────────────────────────────────────

function Row({ label, value, valueColor }: { label: string; value: string; valueColor?: string }) {
  const colors = useColors();
  return (
    <View style={[s.row, { borderBottomColor: colors.border }]}>
      <Text style={[s.rowLabel, { color: colors.mutedForeground }]} numberOfLines={1}>{label}</Text>
      <Text style={[s.rowValue, { color: valueColor ?? colors.foreground }]} numberOfLines={2}>
        {value}
      </Text>
    </View>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  const colors = useColors();
  return (
    <View style={s.section}>
      <Text style={[s.sectionTitle, { color: colors.foreground }]}>{title}</Text>
      <View style={[s.card, { backgroundColor: colors.card, borderColor: colors.border }]}>
        {children}
      </View>
    </View>
  );
}

// ── Platform Health Card ───────────────────────────────────────────────────────

function PlatformHealthCard({
  data,
  loading,
}: {
  data?: OpsSnapshot;
  loading: boolean;
}) {
  const colors = useColors();
  const isDark = useColorScheme() === "dark";
  const p = data?.platform;
  const health = p?.health_pct ?? 0;
  const barColor = healthBarColor(health);
  const healthLabel =
    health >= 90 ? "OPERATIONAL" : health >= 70 ? "DEGRADED" : "UNHEALTHY";
  const marketState = p?.market_state ?? "UNKNOWN";
  const marketColor =
    marketState === "OPEN" ? "#10B981" : isDark ? "#F6C453" : "#8A4B00";

  // Live "N seconds ago" ticker derived from server-side generated_at
  const [ageSecs, setAgeSecs] = useState(0);
  const generatedAt = data?.generated_at;
  useEffect(() => {
    if (!generatedAt) { setAgeSecs(0); return; }
    const tick = () => {
      const diff = Math.round((Date.now() - new Date(generatedAt).getTime()) / 1000);
      setAgeSecs(Math.max(0, diff));
    };
    tick();
    const id = setInterval(tick, 1_000);
    return () => clearInterval(id);
  }, [generatedAt]);

  // The mobile app only calls the full snapshot (always freshly computed).
  // Treat data older than 2 minutes as a cached/stale snapshot.
  const isCached = ageSecs >= 120;
  const ageLabel = ageSecs < 60 ? `${ageSecs}s ago` : `${Math.round(ageSecs / 60)}m ago`;
  const snapshotColor  = isCached ? "#F6C453" : "#10B981";   // amber or emerald
  const snapshotBadge  = isCached ? "Cached snapshot" : "Live";

  return (
    <Section title="Platform Health">
      {loading && !data ? (
        <View style={{ paddingVertical: 16, gap: 10 }}>
          <Skeleton style={{ height: 14, width: "60%" }} />
          <Skeleton style={{ height: 8, width: "100%", borderRadius: 4 }} />
          <Skeleton style={{ height: 13, width: "40%" }} />
        </View>
      ) : (
        <>
          {/* Health % + label */}
          <View style={[s.row, { borderBottomColor: colors.border }]}>
            <Text style={[s.rowLabel, { color: colors.mutedForeground }]}>Overall Health</Text>
            <View style={{ flexDirection: "row", alignItems: "center", gap: 8 }}>
              <Text style={[s.rowValue, { color: barColor, fontSize: 20, fontFamily: "Inter_700Bold" }]}>
                {health}%
              </Text>
              <View style={[s.pill, { backgroundColor: barColor + "22" }]}>
                <Text style={[s.pillText, { color: barColor }]}>{healthLabel}</Text>
              </View>
            </View>
          </View>

          {/* Progress bar */}
          <View style={[s.barTrack, { backgroundColor: colors.border + "88" }]}>
            <View
              style={[s.barFill, { width: `${health}%` as `${number}%`, backgroundColor: barColor }]}
            />
          </View>

          {/* Cache vs live badge */}
          {generatedAt ? (
            <View style={[s.row, { borderBottomColor: colors.border }]}>
              <Text style={[s.rowLabel, { color: colors.mutedForeground }]}>Snapshot</Text>
              <View style={{
                flexDirection: "row", alignItems: "center", gap: 5,
                paddingHorizontal: 8, paddingVertical: 3,
                borderRadius: 99, borderWidth: 1,
                backgroundColor: snapshotColor + "18",
                borderColor: snapshotColor + "55",
              }}>
                <View style={{
                  width: 6, height: 6, borderRadius: 3,
                  backgroundColor: snapshotColor,
                }} />
                <Text style={{ fontSize: 11, fontWeight: "600", color: snapshotColor }}>
                  {snapshotBadge} · {ageLabel}
                </Text>
              </View>
            </View>
          ) : null}

          {/* Market state */}
          <Row
            label="Market State"
            value={marketState.replace(/_/g, " ")}
            valueColor={marketColor}
          />
          <Row label="Session" value={p?.trading_session ?? "—"} />
          <Row label="Scan #" value={p?.scan_number ? `#${p.scan_number}` : (p?.scan_id ?? "—")} />
          <Row label="Last Refresh" value={p?.last_refresh_ist ?? "—"} />
          <Row label="Next Refresh" value={p?.next_refresh_est ?? "—"} />
          <Row label="Current Time" value={p?.current_time_ist ?? "—"} />
        </>
      )}
    </Section>
  );
}

// ── Agent Grid ────────────────────────────────────────────────────────────────

function AgentDot({
  agentKey,
  agent,
  selected,
  onPress,
}: {
  agentKey: string;
  agent?: AgentState;
  selected: boolean;
  onPress: () => void;
}) {
  const colors = useColors();
  const isDark = useColorScheme() === "dark";
  const status = (agent?.status ?? "UNKNOWN") as AgentStatus;
  const dotColor = statusColor(status, colors, isDark);
  const health = agent?.health_pct ?? 0;
  const icon = AGENT_ICONS[agentKey] ?? "circle";
  const shortName = AGENT_SHORT_NAMES[agentKey] ?? agentKey;

  const pulseAnim = useRef(new Animated.Value(1)).current;
  useEffect(() => {
    if (status === "ACTIVE" || status === "ERROR") {
      const anim = Animated.loop(
        Animated.sequence([
          Animated.timing(pulseAnim, { toValue: 0.35, duration: 900, useNativeDriver: true }),
          Animated.timing(pulseAnim, { toValue: 1, duration: 900, useNativeDriver: true }),
        ]),
      );
      anim.start();
      return () => anim.stop();
    }
    pulseAnim.setValue(1);
  }, [status]);

  return (
    <Pressable
      onPress={() => {
        Haptics.selectionAsync();
        onPress();
      }}
      style={[
        s.agentDot,
        {
          backgroundColor: selected ? dotColor + "18" : colors.card,
          borderColor: selected ? dotColor : colors.border,
        },
      ]}
    >
      {/* Status ring */}
      <View style={{ position: "relative", alignItems: "center", justifyContent: "center" }}>
        <Animated.View
          style={[
            s.dotRing,
            { backgroundColor: dotColor + "30", opacity: pulseAnim },
          ]}
        />
        <View style={[s.dotInner, { backgroundColor: dotColor }]}>
          <Feather name={icon} size={10} color="#fff" />
        </View>
      </View>

      <Text style={[s.agentDotName, { color: colors.foreground }]} numberOfLines={1}>
        {shortName}
      </Text>
      <Text style={[s.agentDotHealth, { color: dotColor }]}>
        {agent ? `${health}%` : "—"}
      </Text>
    </Pressable>
  );
}

function AgentExpandedCard({
  agentKey,
  agent,
}: {
  agentKey: string;
  agent: AgentState;
}) {
  const colors = useColors();
  const isDark = useColorScheme() === "dark";
  const status = agent.status as AgentStatus;
  const dotColor = statusColor(status, colors, isDark);
  const d = agent.details ?? {};

  // Build a concise detail row set based on agent type
  const rows: Array<[string, string | number | null | undefined]> = [
    ["Activity", agent.current_activity || "—"],
    ["Health", `${agent.health_pct}%`],
    ["Status", agent.status],
    ["In → Out", agent.stocks_in || agent.stocks_out
      ? `${agent.stocks_in} → ${agent.stocks_out}`
      : "—"],
    ["Last refresh", agent.last_refresh_time || "—"],
    ["Avg latency", fmtMs(agent.avg_processing_ms)],
  ];

  // Append up to 3 agent-specific fields
  if (agentKey === "risk") {
    if (d.risk_level) rows.push(["Risk Level", d.risk_level as string]);
    if (d.risk_score != null) rows.push(["Risk Score", `${(d.risk_score as number).toFixed(0)}/100`]);
    if (d.capital_used) rows.push(["Capital Used", d.capital_used as string]);
    if (d.open_positions != null) rows.push(["Open Positions", String(d.open_positions)]);
  } else if (agentKey === "market_data") {
    if (d.market_regime) rows.push(["Regime", d.market_regime as string]);
    if (d.coverage_pct != null) rows.push(["Coverage", `${(d.coverage_pct as number).toFixed(0)}%`]);
  } else if (agentKey === "market_intelligence") {
    if (d.market_regime) rows.push(["Regime", d.market_regime as string]);
    if (d.volatility_regime) rows.push(["Volatility", d.volatility_regime as string]);
  } else if (agentKey === "strategy") {
    if (d.top_strategy) rows.push(["Top Strategy", d.top_strategy as string]);
    if (d.highest_confidence != null) rows.push(["Top Confidence", `${(d.highest_confidence as number).toFixed(0)}%`]);
  } else if (agentKey === "ai_decision") {
    if (d.buy_candidate != null) rows.push(["BUY", String(d.buy_candidate)]);
    if (d.avg_confidence != null) rows.push(["Avg Confidence", `${(d.avg_confidence as number).toFixed(0)}%`]);
  } else if (agentKey === "execution") {
    if (d.open_positions != null) rows.push(["Open Positions", String(d.open_positions)]);
    if (d.capital_available) rows.push(["Cash Available", String(d.capital_available)]);
  } else if (agentKey === "supervisor") {
    if (d.total_agents != null) rows.push(["Total Agents", String(d.total_agents)]);
    if (d.running_agents != null) rows.push(["Running", String(d.running_agents)]);
    if (d.error_agents != null) rows.push(["Error", String(d.error_agents)]);
  }

  // Rejection reason
  if (agent.rejection_reason) {
    rows.push(["Rejection", agent.rejection_reason]);
  }

  // Errors
  if (agent.errors?.length) {
    rows.push(["Errors", agent.errors[0]]);
  }

  return (
    <View
      style={[
        s.expandedCard,
        { backgroundColor: dotColor + "0D", borderColor: dotColor + "50" },
      ]}
    >
      <View style={[s.expandedHeader, { borderBottomColor: dotColor + "30" }]}>
        <Text style={[s.expandedTitle, { color: dotColor }]}>{agent.name}</Text>
        <View style={[s.pill, { backgroundColor: dotColor + "22" }]}>
          <View style={[s.pillDot, { backgroundColor: dotColor }]} />
          <Text style={[s.pillText, { color: dotColor }]}>{agent.status}</Text>
        </View>
      </View>
      {rows.map(([label, value]) => (
        <Row
          key={label}
          label={label}
          value={value == null ? "—" : String(value) || "—"}
        />
      ))}
    </View>
  );
}

function AgentGrid({
  data,
  loading,
}: {
  data?: OpsSnapshot;
  loading: boolean;
}) {
  const colors = useColors();
  const [selected, setSelected] = useState<string | null>(null);

  const handlePress = (key: string) => {
    setSelected(prev => (prev === key ? null : key));
  };

  return (
    <View style={s.section}>
      <View style={s.sectionHeaderRow}>
        <Text style={[s.sectionTitle, { color: colors.foreground }]}>12-Agent Pipeline</Text>
        <Text style={[s.sectionHint, { color: colors.mutedForeground }]}>
          Tap an agent for details
        </Text>
      </View>

      {loading && !data ? (
        <View style={[s.card, { backgroundColor: colors.card, borderColor: colors.border }]}>
          <View style={s.agentGrid}>
            {Array.from({ length: 12 }).map((_, i) => (
              <Skeleton key={i} style={s.agentDotSkeleton} />
            ))}
          </View>
        </View>
      ) : (
        <View style={[s.card, { backgroundColor: colors.card, borderColor: colors.border, padding: 12 }]}>
          <View style={s.agentGrid}>
            {AGENT_ORDER.map(key => (
              <AgentDot
                key={key}
                agentKey={key}
                agent={data?.agents?.[key]}
                selected={selected === key}
                onPress={() => handlePress(key)}
              />
            ))}
          </View>

          {selected && data?.agents?.[selected] && (
            <AgentExpandedCard
              agentKey={selected}
              agent={data.agents[selected]}
            />
          )}
        </View>
      )}
    </View>
  );
}

// ── Pipeline Funnel ───────────────────────────────────────────────────────────

function PipelineFunnel({ data, loading }: { data?: OpsSnapshot; loading: boolean }) {
  const colors = useColors();
  const p = data?.pipeline;

  const stages = [
    { label: "Universe",      value: p?.universe_loaded   ?? 0 },
    { label: "Mkt Data",      value: p?.passed_market_data ?? 0 },
    { label: "Research",      value: p?.passed_research   ?? 0 },
    { label: "Intelligence",  value: p?.passed_intelligence ?? 0 },
    { label: "Monitoring",    value: p?.passed_monitoring  ?? 0 },
    { label: "Strategy",      value: p?.passed_strategy   ?? 0 },
    { label: "Risk OK",       value: p?.passed_risk       ?? 0 },
    { label: "BUY Recs",      value: p?.buy_recommendations ?? 0 },
    { label: "Orders",        value: p?.paper_orders_executed ?? 0 },
    { label: "Open Pos",      value: p?.open_positions    ?? 0 },
  ];

  return (
    <Section title="Pipeline Funnel">
      {loading && !data ? (
        <View style={{ paddingVertical: 12, gap: 8 }}>
          <Skeleton style={{ height: 13, width: "80%" }} />
          <Skeleton style={{ height: 13, width: "65%" }} />
          <Skeleton style={{ height: 13, width: "50%" }} />
        </View>
      ) : (
        <ScrollView
          horizontal
          showsHorizontalScrollIndicator={false}
          contentContainerStyle={s.funnelScroll}
        >
          {stages.map((stage, idx) => {
            const next = stages[idx + 1];
            const pct = stage.value > 0 && next
              ? Math.round((next.value / stage.value) * 100)
              : null;
            return (
              <View key={stage.label} style={s.funnelItem}>
                <View
                  style={[
                    s.funnelBubble,
                    {
                      backgroundColor: stage.value > 0 ? "#10B98118" : colors.border + "44",
                      borderColor: stage.value > 0 ? "#10B981" : colors.border,
                    },
                  ]}
                >
                  <Text
                    style={[
                      s.funnelValue,
                      { color: stage.value > 0 ? "#10B981" : colors.mutedForeground },
                    ]}
                  >
                    {stage.value}
                  </Text>
                </View>
                <Text style={[s.funnelLabel, { color: colors.mutedForeground }]}>
                  {stage.label}
                </Text>
                {idx < stages.length - 1 && (
                  <View style={s.funnelArrow}>
                    <Text style={[s.funnelArrowText, { color: colors.mutedForeground }]}>›</Text>
                    {pct !== null && (
                      <Text style={[s.funnelPct, { color: colors.mutedForeground }]}>
                        {pct}%
                      </Text>
                    )}
                  </View>
                )}
              </View>
            );
          })}
        </ScrollView>
      )}
    </Section>
  );
}

// ── Main Screen ───────────────────────────────────────────────────────────────

export default function AiOpsScreen() {
  const colors = useColors();
  const isDark = useColorScheme() === "dark";
  const insets = useSafeAreaInsets();
  const isWeb = Platform.OS === "web";

  const { data: liveData, isLoading, isFetching, isError, refetch, dataUpdatedAt } = useOpsSnapshot();

  // Persist each successful fetch to AsyncStorage; serve it immediately on next
  // cold-start so the screen never shows a blank spinner when offline.
  const { data, isStale, staleTs } = useOfflineSnapshot<OpsSnapshot>(
    "ops-centre-snapshot",
    liveData,
    isError,
    dataUpdatedAt,
  );

  // Show the StaleBanner only when the cached data is more than 5 minutes old.
  const STALE_THRESHOLD_MS = 5 * 60 * 1_000;
  const showStaleBanner = isStale && staleTs != null && Date.now() - staleTs > STALE_THRESHOLD_MS;

  // Countdown to next auto-refresh (30 s)
  const [countdown, setCountdown] = useState(30);
  useEffect(() => {
    setCountdown(30);
    const id = setInterval(() => setCountdown(c => (c <= 1 ? 30 : c - 1)), 1_000);
    return () => clearInterval(id);
  }, [dataUpdatedAt]);

  const lastUpdated = dataUpdatedAt
    ? new Date(dataUpdatedAt).toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit", second: "2-digit" })
    : null;

  // Count active agents
  const activeCount = data
    ? Object.values(data.agents).filter(a => a.status === "ACTIVE").length
    : 0;
  const errorCount = data
    ? Object.values(data.agents).filter(a => a.status === "ERROR").length
    : 0;
  const waitingCount = data
    ? Object.values(data.agents).filter(a => a.status === "WAITING").length
    : 0;

  return (
    <View style={{ flex: 1, backgroundColor: colors.background }}>
      <AppHeader />
      <ScrollView
        style={{ flex: 1 }}
        contentContainerStyle={[
          s.scroll,
          { paddingBottom: isWeb ? 100 : insets.bottom + 100 },
        ]}
        showsVerticalScrollIndicator={false}
        refreshControl={
          <RefreshControl
            refreshing={isFetching}
            onRefresh={refetch}
            tintColor={colors.primary}
          />
        }
      >
        {/* Title */}
        <Text style={[s.pageTitle, { color: colors.foreground }]}>AI Operations</Text>
        <View style={s.badgeRow}>
          <View style={[s.pill, { backgroundColor: "#0EA5E922" }]}>
            <Text style={[s.pillText, { color: "#0EA5E9" }]}>ADVISORY ONLY</Text>
          </View>
          <View style={[s.pill, { backgroundColor: colors.border + "44" }]}>
            <Text style={[s.pillText, { color: colors.mutedForeground }]}>READ-ONLY</Text>
          </View>
          {isStale && (
            <View style={[s.pill, { backgroundColor: "#F6C45322", borderWidth: 1, borderColor: "#F6C45366" }]}>
              <Text style={[s.pillText, { color: isDark ? "#F6C453" : "#8A4B00" }]}>CACHED</Text>
            </View>
          )}
        </View>

        {/* Agent status summary row */}
        {!isLoading && data && (
          <View style={[s.summaryRow, { borderColor: colors.border }]}>
            <View style={s.summaryItem}>
              <View style={[s.pillDot, { backgroundColor: "#10B981", width: 8, height: 8, borderRadius: 4 }]} />
              <Text style={[s.summaryLabel, { color: colors.mutedForeground }]}>
                {activeCount} Active
              </Text>
            </View>
            {waitingCount > 0 && (
              <View style={s.summaryItem}>
                <View style={[s.pillDot, { backgroundColor: isDark ? "#F6C453" : "#8A4B00", width: 8, height: 8, borderRadius: 4 }]} />
                <Text style={[s.summaryLabel, { color: colors.mutedForeground }]}>
                  {waitingCount} Waiting
                </Text>
              </View>
            )}
            {errorCount > 0 && (
              <View style={s.summaryItem}>
                <View style={[s.pillDot, { backgroundColor: "#F43F5E", width: 8, height: 8, borderRadius: 4 }]} />
                <Text style={[s.summaryLabel, { color: colors.mutedForeground }]}>
                  {errorCount} Error
                </Text>
              </View>
            )}
            <Text style={[s.refreshCountdown, { color: colors.mutedForeground }]}>
              ↺ {countdown}s
            </Text>
          </View>
        )}

        {/* Last updated + manual refresh */}
        <View style={s.refreshRow}>
          {lastUpdated && (
            <Text style={[s.lastUpdated, { color: colors.mutedForeground }]}>
              Updated {lastUpdated}
            </Text>
          )}
          <Pressable
            onPress={() => {
              Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
              refetch();
            }}
            style={[s.refreshBtn, { borderColor: colors.border }]}
          >
            {isFetching ? (
              <ActivityIndicator size="small" color={colors.primary} />
            ) : (
              <Feather name="refresh-cw" size={14} color={colors.primary} />
            )}
            <Text style={[s.refreshBtnText, { color: colors.primary }]}>
              {isFetching ? "Refreshing…" : "Refresh"}
            </Text>
          </Pressable>
        </View>

        {/* Stale cache banner — shown when offline data is > 5 minutes old */}
        {showStaleBanner && (
          <StaleBanner staleTs={staleTs} onRetry={refetch} />
        )}

        {/* Error state — only shown when there is no cached fallback */}
        {isError && !data && (
          <View style={[s.errorBanner, { backgroundColor: "#F43F5E18", borderColor: "#F43F5E" }]}>
            <Ionicons name="warning-outline" size={16} color="#F43F5E" />
            <Text style={[s.errorBannerText, { color: "#F43F5E" }]}>
              Could not load pipeline snapshot. The snapshot takes ~35 s to compute — pull down to retry.
            </Text>
          </View>
        )}

        {/* Initial loading — suppressed when cached data is already available */}
        {isLoading && !data && (
          <View style={[s.loadingCard, { backgroundColor: colors.card, borderColor: colors.border }]}>
            <ActivityIndicator size="large" color={colors.primary} />
            <Text style={[s.loadingText, { color: colors.mutedForeground }]}>
              Loading pipeline snapshot…
            </Text>
            <Text style={[s.loadingHint, { color: colors.mutedForeground }]}>
              Aggregating all 12 agents — usually takes 30–40 s on first load
            </Text>
          </View>
        )}

        {/* Platform health */}
        <PlatformHealthCard data={data} loading={isLoading} />

        {/* Agent grid */}
        <AgentGrid data={data} loading={isLoading} />

        {/* Pipeline funnel */}
        <PipelineFunnel data={data} loading={isLoading} />

        {/* Advisory footer */}
        <Text style={[s.footer, { color: colors.mutedForeground }]}>
          All data is read-only and advisory only. No orders can be placed from this screen.
          Auto-refreshes every 30 s.
        </Text>
      </ScrollView>
    </View>
  );
}

// ── Styles ────────────────────────────────────────────────────────────────────

const s = StyleSheet.create({
  scroll:         { paddingHorizontal: 16, paddingTop: 16 },
  pageTitle:      { fontSize: 28, fontFamily: "Inter_700Bold", letterSpacing: -0.5, marginBottom: 8 },
  badgeRow:       { flexDirection: "row", gap: 8, marginBottom: 12 },
  pill:           { flexDirection: "row", alignItems: "center", gap: 4, paddingHorizontal: 8, paddingVertical: 3, borderRadius: 10 },
  pillDot:        { width: 6, height: 6, borderRadius: 3 },
  pillText:       { fontSize: 9, fontFamily: "Inter_700Bold", letterSpacing: 0.5 },
  summaryRow:     { flexDirection: "row", alignItems: "center", gap: 12, paddingVertical: 10, marginBottom: 8, borderBottomWidth: StyleSheet.hairlineWidth },
  summaryItem:    { flexDirection: "row", alignItems: "center", gap: 5 },
  summaryLabel:   { fontSize: 12, fontFamily: "Inter_500Medium" },
  refreshCountdown: { marginLeft: "auto", fontSize: 11, fontFamily: "Inter_400Regular" },
  refreshRow:     { flexDirection: "row", alignItems: "center", justifyContent: "space-between", marginBottom: 16, gap: 8 },
  lastUpdated:    { fontSize: 11, fontFamily: "Inter_400Regular" },
  refreshBtn:     { flexDirection: "row", alignItems: "center", gap: 5, paddingHorizontal: 10, paddingVertical: 6, borderRadius: 8, borderWidth: StyleSheet.hairlineWidth },
  refreshBtnText: { fontSize: 12, fontFamily: "Inter_500Medium" },
  errorBanner:    { flexDirection: "row", gap: 8, alignItems: "flex-start", borderWidth: 1, borderRadius: 10, padding: 12, marginBottom: 16 },
  errorBannerText:{ flex: 1, fontSize: 12, fontFamily: "Inter_400Regular" },
  loadingCard:    { borderRadius: 12, borderWidth: StyleSheet.hairlineWidth, padding: 32, alignItems: "center", gap: 12, marginBottom: 16 },
  loadingText:    { fontSize: 14, fontFamily: "Inter_500Medium", textAlign: "center" },
  loadingHint:    { fontSize: 11, fontFamily: "Inter_400Regular", textAlign: "center" },
  section:        { marginBottom: 20 },
  sectionTitle:   { fontSize: 15, fontFamily: "Inter_600SemiBold", marginBottom: 8 },
  sectionHeaderRow: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", marginBottom: 8 },
  sectionHint:    { fontSize: 11, fontFamily: "Inter_400Regular" },
  card:           { borderRadius: 12, borderWidth: StyleSheet.hairlineWidth, overflow: "hidden", paddingHorizontal: 14 },
  row:            { flexDirection: "row", justifyContent: "space-between", alignItems: "flex-start", paddingVertical: 10, borderBottomWidth: StyleSheet.hairlineWidth, gap: 12 },
  rowLabel:       { fontSize: 12, fontFamily: "Inter_500Medium", flex: 1 },
  rowValue:       { fontSize: 12, fontFamily: "Inter_600SemiBold", flexShrink: 1, textAlign: "right", maxWidth: "60%" },
  barTrack:       { height: 6, borderRadius: 3, marginHorizontal: 14, marginBottom: 2, overflow: "hidden" },
  barFill:        { height: 6, borderRadius: 3 },
  // Agent grid
  agentGrid:      { flexDirection: "row", flexWrap: "wrap", gap: 8 },
  agentDot:       { width: "30%", flexGrow: 1, alignItems: "center", paddingVertical: 10, paddingHorizontal: 4, borderRadius: 10, borderWidth: 1, gap: 4 },
  agentDotSkeleton: { width: "30%", height: 72, borderRadius: 10 },
  dotRing:        { position: "absolute", width: 28, height: 28, borderRadius: 14 },
  dotInner:       { width: 22, height: 22, borderRadius: 11, alignItems: "center", justifyContent: "center" },
  agentDotName:   { fontSize: 10, fontFamily: "Inter_600SemiBold", textAlign: "center" },
  agentDotHealth: { fontSize: 9, fontFamily: "Inter_400Regular" },
  // Expanded card
  expandedCard:   { marginTop: 10, borderRadius: 10, borderWidth: 1, paddingHorizontal: 12, paddingBottom: 4 },
  expandedHeader: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingVertical: 10, borderBottomWidth: 1, marginBottom: 2 },
  expandedTitle:  { fontSize: 13, fontFamily: "Inter_700Bold" },
  // Funnel
  funnelScroll:   { paddingVertical: 8, gap: 2, paddingBottom: 4 },
  funnelItem:     { alignItems: "center", flexDirection: "row", gap: 4 },
  funnelBubble:   { width: 44, height: 44, borderRadius: 22, alignItems: "center", justifyContent: "center", borderWidth: 1 },
  funnelValue:    { fontSize: 14, fontFamily: "Inter_700Bold" },
  funnelLabel:    { position: "absolute", top: 50, fontSize: 9, fontFamily: "Inter_500Medium", width: 52, textAlign: "center", left: -4 },
  funnelArrow:    { alignItems: "center", marginBottom: 0 },
  funnelArrowText:{ fontSize: 16, fontFamily: "Inter_400Regular" },
  funnelPct:      { fontSize: 8, fontFamily: "Inter_400Regular", marginTop: -4 },
  footer:         { fontSize: 11, fontFamily: "Inter_400Regular", textAlign: "center", marginTop: 8, marginBottom: 8, lineHeight: 16 },
});
