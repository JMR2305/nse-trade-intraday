import { Ionicons } from "@expo/vector-icons";
import * as Haptics from "expo-haptics";
import React from "react";
import {
  ActivityIndicator,
  FlatList,
  Platform,
  Pressable,
  RefreshControl,
  StyleSheet,
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
          ListEmptyComponent={
            <View style={styles.empty}>
              <Ionicons name="notifications-off-outline" size={48} color={colors.mutedForeground} />
              <Text style={[styles.emptyTitle, { color: colors.foreground }]}>No notifications</Text>
              <Text style={[styles.emptyText, { color: colors.mutedForeground }]}>
                Scan results, entries, exits and risk alerts will appear here
              </Text>
            </View>
          }
          scrollEnabled={!!list.length}
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
});
