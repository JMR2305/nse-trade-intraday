import { Ionicons } from "@expo/vector-icons";
import * as Haptics from "expo-haptics";
import React from "react";
import {
  ActivityIndicator,
  Alert,
  FlatList,
  Platform,
  Pressable,
  RefreshControl,
  StyleSheet,
  Switch,
  Text,
  View,
} from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { useColors } from "@/hooks/useColors";
import {
  MonitorNotification,
  useMarkNotificationsRead,
  useNotifications,
} from "@/lib/monitorApi";
import {
  DEFAULT_MIN_CONFIDENCE,
  disablePushAlerts,
  enablePushAlerts,
  getStoredPushPrefs,
  updateMinConfidence,
} from "@/lib/pushNotifications";

function iconForType(type?: string): { name: keyof typeof Ionicons.glyphMap; tone: "good" | "bad" | "info" } {
  const t = (type ?? "").toUpperCase();
  if (t.includes("RISK") || t.includes("ERROR") || t.includes("EXIT")) return { name: "warning-outline", tone: "bad" };
  if (t.includes("ENTRY") || t.includes("SIGNAL")) return { name: "trending-up-outline", tone: "good" };
  return { name: "information-circle-outline", tone: "info" };
}

function NotificationRow({ item }: { item: MonitorNotification }) {
  const colors = useColors();
  const { name, tone } = iconForType(item.type);
  const iconColor = tone === "bad" ? colors.destructive : tone === "good" ? colors.success : colors.primary;

  return (
    <View
      style={[
        styles.notifRow,
        { backgroundColor: colors.card, borderColor: colors.border },
        !item.read && { borderLeftWidth: 3, borderLeftColor: colors.primary },
      ]}
    >
      <View style={[styles.notifIcon, { backgroundColor: iconColor + "18" }]}>
        <Ionicons name={name} size={18} color={iconColor} />
      </View>
      <View style={styles.notifBody}>
        <Text style={[styles.notifTitle, { color: colors.foreground }]} numberOfLines={1}>
          {item.title ?? item.type ?? "Notification"}
        </Text>
        {item.message ? (
          <Text style={[styles.notifMsg, { color: colors.mutedForeground }]} numberOfLines={3}>
            {item.message}
          </Text>
        ) : null}
        <Text style={[styles.notifTime, { color: colors.mutedForeground }]}>
          {item.ts
            ? new Date(item.ts).toLocaleString("en-IN", {
                month: "short",
                day: "numeric",
                hour: "2-digit",
                minute: "2-digit",
              })
            : ""}
        </Text>
      </View>
    </View>
  );
}

const CONFIDENCE_OPTIONS = [60, 70, 80, 90];

function PushAlertsCard() {
  const colors = useColors();
  const isWeb = Platform.OS === "web";
  const [loaded, setLoaded] = React.useState(false);
  const [enabled, setEnabled] = React.useState(false);
  const [minConfidence, setMinConfidence] = React.useState(DEFAULT_MIN_CONFIDENCE);
  const [busy, setBusy] = React.useState(false);

  React.useEffect(() => {
    getStoredPushPrefs()
      .then((prefs) => {
        setEnabled(prefs.enabled);
        setMinConfidence(prefs.minConfidence);
      })
      .finally(() => setLoaded(true));
  }, []);

  const handleToggle = async (next: boolean) => {
    if (busy) return;
    Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
    setBusy(true);
    try {
      if (next) {
        await enablePushAlerts(minConfidence);
        setEnabled(true);
      } else {
        await disablePushAlerts();
        setEnabled(false);
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Could not update push alerts.";
      Alert.alert("Push alerts", msg);
    } finally {
      setBusy(false);
    }
  };

  const handleConfidence = async (value: number) => {
    if (busy || value === minConfidence) return;
    Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
    setMinConfidence(value);
    try {
      await updateMinConfidence(value);
    } catch {
      Alert.alert("Push alerts", "Could not save the confidence threshold on the server. It will be applied next time you re-enable alerts.");
    }
  };

  if (isWeb || !loaded) return null;

  return (
    <View style={[styles.pushCard, { backgroundColor: colors.card, borderColor: colors.border }]}>
      <View style={styles.pushHeader}>
        <View style={styles.pushTitleRow}>
          <Ionicons name="phone-portrait-outline" size={16} color={colors.primary} />
          <Text style={[styles.pushTitle, { color: colors.foreground }]}>Push alerts</Text>
        </View>
        {busy ? (
          <ActivityIndicator size="small" color={colors.primary} />
        ) : (
          <Switch
            value={enabled}
            onValueChange={handleToggle}
            trackColor={{ true: colors.primary }}
            testID="push-alerts-toggle"
          />
        )}
      </View>
      <Text style={[styles.pushSub, { color: colors.mutedForeground }]}>
        Get notified on this phone when a scan finds a high-confidence signal. Research alerts only — nothing is traded automatically.
      </Text>
      {enabled && (
        <View style={styles.confRow}>
          <Text style={[styles.confLabel, { color: colors.mutedForeground }]}>Minimum confidence</Text>
          <View style={styles.confChips}>
            {CONFIDENCE_OPTIONS.map((opt) => {
              const active = opt === minConfidence;
              return (
                <Pressable
                  key={opt}
                  onPress={() => handleConfidence(opt)}
                  style={[
                    styles.confChip,
                    { borderColor: active ? colors.primary : colors.border },
                    active && { backgroundColor: colors.primary + "18" },
                  ]}
                  testID={`push-conf-${opt}`}
                >
                  <Text style={[styles.confChipText, { color: active ? colors.primary : colors.mutedForeground }]}>
                    {opt}%
                  </Text>
                </Pressable>
              );
            })}
          </View>
        </View>
      )}
    </View>
  );
}

export default function AlertsScreen() {
  const colors = useColors();
  const insets = useSafeAreaInsets();
  const isWeb = Platform.OS === "web";
  const topPadding = isWeb ? 67 : insets.top;

  const { data, isLoading, isError, refetch, isFetching } = useNotifications();
  const markRead = useMarkNotificationsRead();

  const list = Array.isArray(data) ? data : [];
  const unreadCount = list.filter((n) => !n.read).length;

  const handleMarkAllRead = async () => {
    Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
    try {
      await markRead.mutateAsync(null);
    } catch {
      // markRead.isError shown below
    }
  };

  return (
    <View style={[styles.container, { backgroundColor: colors.background }]}>
      <View style={[styles.header, { paddingTop: topPadding + 16, borderBottomColor: colors.border }]}>
        <View>
          <Text style={[styles.headerTitle, { color: colors.foreground }]}>Notifications</Text>
          {unreadCount > 0 && (
            <Text style={[styles.headerSub, { color: colors.mutedForeground }]}>
              {unreadCount} unread
            </Text>
          )}
        </View>
        {unreadCount > 0 && (
          <Pressable
            style={[styles.markBtn, { borderColor: colors.border }]}
            onPress={handleMarkAllRead}
            disabled={markRead.isPending}
            testID="mark-all-read-btn"
          >
            {markRead.isPending ? (
              <ActivityIndicator size="small" color={colors.primary} />
            ) : (
              <Text style={[styles.markBtnText, { color: colors.primary }]}>Mark all read</Text>
            )}
          </Pressable>
        )}
      </View>

      {markRead.isError && (
        <Text style={[styles.inlineError, { color: colors.destructive }]}>
          Could not mark notifications as read.
        </Text>
      )}

      {isLoading ? (
        <View style={styles.center}>
          <ActivityIndicator size="large" color={colors.primary} />
        </View>
      ) : isError ? (
        <View style={styles.center}>
          <Ionicons name="alert-circle-outline" size={48} color={colors.destructive} />
          <Text style={[styles.errorText, { color: colors.mutedForeground }]}>Could not load notifications</Text>
          <Pressable style={[styles.retryBtn, { borderColor: colors.border }]} onPress={() => refetch()}>
            <Text style={[styles.retryText, { color: colors.primary }]}>Try again</Text>
          </Pressable>
        </View>
      ) : (
        <FlatList
          data={list}
          keyExtractor={(item, i) => item.id ?? `n-${i}`}
          renderItem={({ item }) => <NotificationRow item={item} />}
          contentContainerStyle={[styles.list, { paddingBottom: 120 }]}
          ListHeaderComponent={<PushAlertsCard />}
          ListEmptyComponent={
            <View style={styles.empty}>
              <Ionicons name="notifications-off-outline" size={48} color={colors.mutedForeground} />
              <Text style={[styles.emptyTitle, { color: colors.foreground }]}>No notifications</Text>
              <Text style={[styles.emptyText, { color: colors.mutedForeground }]}>
                Scan results, entries, exits and risk alerts will appear here
              </Text>
            </View>
          }
          scrollEnabled
          showsVerticalScrollIndicator={false}
          refreshControl={
            <RefreshControl refreshing={isFetching && !isLoading} onRefresh={refetch} tintColor={colors.primary} />
          }
        />
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
  headerSub: { fontSize: 12, fontFamily: "Inter_400Regular", marginTop: 2 },
  markBtn: { paddingHorizontal: 12, paddingVertical: 8, borderRadius: 16, borderWidth: 1 },
  markBtnText: { fontSize: 13, fontFamily: "Inter_600SemiBold" },
  inlineError: { fontSize: 12, fontFamily: "Inter_400Regular", paddingHorizontal: 20, paddingTop: 8 },
  list: { padding: 16, gap: 10 },
  notifRow: {
    flexDirection: "row",
    gap: 12,
    padding: 14,
    borderRadius: 12,
    borderWidth: StyleSheet.hairlineWidth,
  },
  notifIcon: { width: 36, height: 36, borderRadius: 18, alignItems: "center", justifyContent: "center" },
  notifBody: { flex: 1, gap: 3 },
  notifTitle: { fontSize: 14, fontFamily: "Inter_600SemiBold" },
  notifMsg: { fontSize: 12, fontFamily: "Inter_400Regular", lineHeight: 17 },
  notifTime: { fontSize: 11, fontFamily: "Inter_400Regular", marginTop: 2 },
  center: { flex: 1, justifyContent: "center", alignItems: "center", gap: 12 },
  empty: { alignItems: "center", gap: 8, paddingTop: 80 },
  emptyTitle: { fontSize: 18, fontFamily: "Inter_600SemiBold" },
  emptyText: { fontSize: 14, fontFamily: "Inter_400Regular", textAlign: "center", paddingHorizontal: 32 },
  errorText: { fontSize: 14, fontFamily: "Inter_400Regular" },
  retryBtn: { marginTop: 8, paddingHorizontal: 20, paddingVertical: 10, borderRadius: 8, borderWidth: 1 },
  retryText: { fontSize: 14, fontFamily: "Inter_600SemiBold" },
  pushCard: {
    borderRadius: 12,
    borderWidth: StyleSheet.hairlineWidth,
    padding: 14,
    gap: 8,
    marginBottom: 6,
  },
  pushHeader: { flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  pushTitleRow: { flexDirection: "row", alignItems: "center", gap: 8 },
  pushTitle: { fontSize: 14, fontFamily: "Inter_600SemiBold" },
  pushSub: { fontSize: 12, fontFamily: "Inter_400Regular", lineHeight: 17 },
  confRow: { gap: 8, marginTop: 4 },
  confLabel: { fontSize: 12, fontFamily: "Inter_600SemiBold" },
  confChips: { flexDirection: "row", gap: 8 },
  confChip: { paddingHorizontal: 14, paddingVertical: 7, borderRadius: 16, borderWidth: 1 },
  confChipText: { fontSize: 13, fontFamily: "Inter_600SemiBold" },
});
