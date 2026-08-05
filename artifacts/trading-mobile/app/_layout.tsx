import {
  Inter_400Regular,
  Inter_500Medium,
  Inter_600SemiBold,
  Inter_700Bold,
  useFonts,
} from "@expo-google-fonts/inter";
import { setBaseUrl } from "@workspace/api-client-react";
import { API_BASE_URL } from "@/lib/apiConfig";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Stack, useRouter } from "expo-router";
import * as Notifications from "expo-notifications";
import * as SplashScreen from "expo-splash-screen";
import React, { useEffect } from "react";
import { GestureHandlerRootView } from "react-native-gesture-handler";
import { KeyboardProvider } from "react-native-keyboard-controller";
import { SafeAreaProvider } from "react-native-safe-area-context";

import { ErrorBoundary } from "@/components/ErrorBoundary";
import { configureNotificationHandler, registerOnLaunch } from "@/lib/pushNotifications";

// Set the API base URL for the @workspace/api-client-react generated hooks.
// Strip the trailing "/api" segment — the generated hooks append their own paths.
const _apiOrigin = API_BASE_URL.replace(/\/api\/?$/, "");
setBaseUrl(_apiOrigin || null);

configureNotificationHandler();

SplashScreen.preventAutoHideAsync();

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      // One automatic retry on transient network failures.
      retry: 1,
    },
    mutations: {
      // Mutations are never retried automatically.
      // Broker order-confirm calls in particular must never be silently replayed.
      retry: 0,
    },
  },
});

function RootLayoutNav() {
  const router = useRouter();

  // Deep-link: when the operator taps a health-alert push notification
  // (data.screen === "ai-ops"), navigate to the Pipeline tab.
  useEffect(() => {
    const sub = Notifications.addNotificationResponseReceivedListener((response) => {
      const data = response.notification.request.content.data as Record<string, unknown> | undefined;
      if (data?.["screen"] === "ai-ops") {
        // Navigate to the Pipeline tab (ai-ops)
        router.push("/(tabs)/ai-ops");
      }
    });
    return () => sub.remove();
  }, [router]);

  return (
    <Stack screenOptions={{ headerBackTitle: "Back" }}>
      <Stack.Screen name="(tabs)" options={{ headerShown: false }} />
    </Stack>
  );
}

export default function RootLayout() {
  const [fontsLoaded, fontError] = useFonts({
    Inter_400Regular,
    Inter_500Medium,
    Inter_600SemiBold,
    Inter_700Bold,
  });

  useEffect(() => {
    if (fontsLoaded || fontError) {
      SplashScreen.hideAsync();
    }
  }, [fontsLoaded, fontError]);

  useEffect(() => {
    // Registers this device for signal push alerts on launch. Never prompts:
    // it only proceeds when OS notification permission is already granted
    // and the user hasn't explicitly turned push alerts off.
    void registerOnLaunch();
  }, []);

  if (!fontsLoaded && !fontError) return null;

  return (
    <SafeAreaProvider>
      <ErrorBoundary>
        <QueryClientProvider client={queryClient}>
          <GestureHandlerRootView>
            <KeyboardProvider>
              <RootLayoutNav />
            </KeyboardProvider>
          </GestureHandlerRootView>
        </QueryClientProvider>
      </ErrorBoundary>
    </SafeAreaProvider>
  );
}
