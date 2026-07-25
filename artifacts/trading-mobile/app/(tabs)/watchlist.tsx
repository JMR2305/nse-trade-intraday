import { Ionicons } from "@expo/vector-icons";
import * as Haptics from "expo-haptics";
import React, { useState } from "react";
import {
  ActivityIndicator,
  Platform,
  Pressable,
  RefreshControl,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { Skeleton } from "@/components/Skeleton";
import { StaleBanner } from "@/components/StaleBanner";
import { useColors } from "@/hooks/useColors";
import {
  useAddWatchlistSymbol,
  useRemoveWatchlistSymbol,
  useWatchlist,
} from "@/lib/monitorApi";
import { useOfflineSnapshot } from "@/lib/offlineCache";
import { AppHeader } from "@/components/AppHeader";

export default function WatchlistScreen() {
  const colors = useColors();
  const insets = useSafeAreaInsets();
  const isWeb = Platform.OS === "web";
  const topPadding = isWeb ? 67 : insets.top;

  const [input, setInput] = useState("");
  const [error, setError] = useState<string | null>(null);

  const { data: liveWatchlist, isLoading, isError, refetch, isFetching, dataUpdatedAt } = useWatchlist();
  const {
    data: watchlist,
    isStale: watchlistStale,
    staleTs,
  } = useOfflineSnapshot("watchlist", liveWatchlist, isError, dataUpdatedAt);
  const addSymbol = useAddWatchlistSymbol();
  const removeSymbol = useRemoveWatchlistSymbol();

  const handleAdd = async () => {
    const symbol = input.trim().toUpperCase();
    if (!symbol) return;
    setError(null);
    Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
    try {
      await addSymbol.mutateAsync(symbol);
      setInput("");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not add symbol");
    }
  };

  const handleRemove = async (symbol: string) => {
    setError(null);
    Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
    try {
      await removeSymbol.mutateAsync(symbol);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not remove symbol");
    }
  };

  const list = watchlist ?? [];

  return (
    <View style={{ flex: 1, backgroundColor: colors.background }}>
      <AppHeader />
      <ScrollView
        style={{ flex: 1 }}
        contentContainerStyle={[styles.scroll, { paddingTop: 16, paddingBottom: 120 }]}
        showsVerticalScrollIndicator={false}
        refreshControl={
          <RefreshControl refreshing={isFetching && !isLoading} onRefresh={() => refetch()} tintColor={colors.primary} />
        }
      >
      <Text style={[styles.pageTitle, { color: colors.foreground }]}>Watchlist</Text>
      <Text style={[styles.subtitle, { color: colors.mutedForeground }]}>
        Symbols scanned for signals and paper trading
      </Text>

      <View style={styles.addRow}>
        <TextInput
          style={[
            styles.input,
            { backgroundColor: colors.card, borderColor: colors.border, color: colors.foreground },
          ]}
          placeholder="Add NSE symbol (e.g. TATAMOTORS)"
          placeholderTextColor={colors.mutedForeground}
          value={input}
          onChangeText={(t) => setInput(t.toUpperCase())}
          autoCapitalize="characters"
          autoCorrect={false}
          onSubmitEditing={handleAdd}
          returnKeyType="done"
        />
        <Pressable
          style={[styles.addBtn, { backgroundColor: colors.primary, opacity: input.trim() ? 1 : 0.5 }]}
          onPress={handleAdd}
          disabled={!input.trim() || addSymbol.isPending}
        >
          {addSymbol.isPending ? (
            <ActivityIndicator size="small" color={colors.primaryForeground} />
          ) : (
            <Ionicons name="add" size={22} color={colors.primaryForeground} />
          )}
        </Pressable>
      </View>

      {error ? <Text style={[styles.errorText, { color: colors.destructive }]}>{error}</Text> : null}

      {watchlistStale && <StaleBanner staleTs={staleTs} onRetry={() => refetch()} />}

      {isLoading && watchlist === undefined ? (
        <View style={[styles.listCard, { backgroundColor: colors.card, borderColor: colors.border }]}>
          {[0, 1, 2, 3, 4].map((i) => (
            <View
              key={i}
              style={[
                styles.row,
                i < 4 && { borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: colors.border },
              ]}
            >
              <Skeleton style={{ width: 120, height: 16 }} />
              <Skeleton style={{ width: 19, height: 16 }} />
            </View>
          ))}
        </View>
      ) : isError && watchlist === undefined ? (
        <View style={styles.center}>
          <Ionicons name="cloud-offline-outline" size={40} color={colors.destructive} />
          <Text style={[styles.emptyText, { color: colors.mutedForeground }]}>
            Server unreachable and no saved watchlist yet
          </Text>
          <Pressable style={[styles.retryBtn, { borderColor: colors.border }]} onPress={() => refetch()}>
            <Text style={{ color: colors.primary, fontFamily: "Inter_600SemiBold" }}>Try again</Text>
          </Pressable>
        </View>
      ) : list.length === 0 ? (
        <View style={styles.center}>
          <Ionicons name="list-outline" size={40} color={colors.mutedForeground} />
          <Text style={[styles.emptyText, { color: colors.mutedForeground }]}>
            Watchlist is empty. Add a symbol above.
          </Text>
        </View>
      ) : (
        <View style={[styles.listCard, { backgroundColor: colors.card, borderColor: colors.border }]}>
          {list.map((symbol, i) => (
            <View
              key={symbol}
              style={[
                styles.row,
                i < list.length - 1 && { borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: colors.border },
              ]}
            >
              <Text style={[styles.symbol, { color: colors.foreground }]}>{symbol}</Text>
              <Pressable
                hitSlop={8}
                onPress={() => handleRemove(symbol)}
                disabled={removeSymbol.isPending}
                style={{ opacity: removeSymbol.isPending ? 0.4 : 1 }}
              >
                <Ionicons name="trash-outline" size={19} color={colors.destructive} />
              </Pressable>
            </View>
          ))}
        </View>
      )}

      <Text style={[styles.note, { color: colors.mutedForeground }]}>
        Changes apply to the next scan. The scanner uses this same list on the desktop dashboard.
      </Text>
    </ScrollView>
    </View>
  );
}

const styles = StyleSheet.create({
  scroll: { paddingHorizontal: 16 },
  pageTitle: { fontSize: 30, fontFamily: "Inter_700Bold", letterSpacing: -0.5 },
  subtitle: { fontSize: 13, fontFamily: "Inter_400Regular", marginTop: 2, marginBottom: 16 },
  addRow: { flexDirection: "row", gap: 8, marginBottom: 12 },
  input: {
    flex: 1,
    borderWidth: 1,
    borderRadius: 12,
    paddingHorizontal: 14,
    paddingVertical: 10,
    fontSize: 15,
    fontFamily: "Inter_500Medium",
  },
  addBtn: { width: 44, borderRadius: 12, alignItems: "center", justifyContent: "center" },
  errorText: { fontSize: 13, fontFamily: "Inter_500Medium", marginBottom: 10 },
  center: { alignItems: "center", paddingVertical: 40, gap: 10 },
  emptyText: { fontSize: 14, fontFamily: "Inter_500Medium", textAlign: "center" },
  retryBtn: { borderWidth: 1, borderRadius: 10, paddingHorizontal: 16, paddingVertical: 8 },
  listCard: { borderWidth: 1, borderRadius: 14, overflow: "hidden" },
  row: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    paddingHorizontal: 16,
    paddingVertical: 14,
  },
  symbol: { fontSize: 16, fontFamily: "Inter_600SemiBold", letterSpacing: -0.2 },
  note: { fontSize: 12, fontFamily: "Inter_400Regular", marginTop: 14, lineHeight: 17 },
});
