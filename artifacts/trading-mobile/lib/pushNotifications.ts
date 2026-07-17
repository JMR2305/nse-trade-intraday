import AsyncStorage from "@react-native-async-storage/async-storage";
import Constants from "expo-constants";
import * as Device from "expo-device";
import * as Notifications from "expo-notifications";
import { Platform } from "react-native";

import { apiJson } from "@/lib/monitorApi";

// Advisory push alerts for high-confidence signals (research only).
// Registration is always user-initiated from the Alerts screen; on launch we
// only *silently re-register* if the user previously enabled alerts and the
// OS permission is still granted.

const ENABLED_KEY = "pushAlertsEnabled";
const TOKEN_KEY = "pushAlertsToken";
const MIN_CONF_KEY = "pushAlertsMinConfidence";

export const DEFAULT_MIN_CONFIDENCE = 70;

export interface PushStatus {
  registered: boolean;
  enabled?: boolean;
  minConfidence?: number;
}

export function configureNotificationHandler(): void {
  Notifications.setNotificationHandler({
    handleNotification: async () => ({
      shouldShowBanner: true,
      shouldShowList: true,
      shouldPlaySound: true,
      shouldSetBadge: false,
    }),
  });
}

export async function getStoredPushPrefs(): Promise<{
  enabled: boolean;
  token: string | null;
  minConfidence: number;
}> {
  const [enabled, token, minConf] = await Promise.all([
    AsyncStorage.getItem(ENABLED_KEY),
    AsyncStorage.getItem(TOKEN_KEY),
    AsyncStorage.getItem(MIN_CONF_KEY),
  ]);
  const parsed = Number(minConf);
  return {
    enabled: enabled === "true",
    token,
    minConfidence: Number.isFinite(parsed) && parsed > 0 ? parsed : DEFAULT_MIN_CONFIDENCE,
  };
}

function getProjectId(): string | undefined {
  return (
    (Constants.expoConfig?.extra as { eas?: { projectId?: string } } | undefined)?.eas
      ?.projectId ?? (Constants as { easConfig?: { projectId?: string } }).easConfig?.projectId
  );
}

async function fetchExpoPushToken(): Promise<string> {
  if (Platform.OS === "web") {
    throw new Error("Push alerts are only available in the mobile app.");
  }
  if (!Device.isDevice) {
    throw new Error("Push alerts require a physical device.");
  }
  const projectId = getProjectId();
  const response = await Notifications.getExpoPushTokenAsync(
    projectId ? { projectId } : undefined,
  );
  return response.data;
}

// User-initiated enable: asks for permission, gets a token, registers it.
export async function enablePushAlerts(minConfidence: number): Promise<string> {
  const existing = await Notifications.getPermissionsAsync();
  let status = existing.status;
  if (status !== "granted") {
    const requested = await Notifications.requestPermissionsAsync();
    status = requested.status;
  }
  if (status !== "granted") {
    throw new Error(
      "Notification permission was not granted. Enable it in your device settings.",
    );
  }
  const token = await fetchExpoPushToken();
  await apiJson("/notifications/push/register", {
    method: "POST",
    body: JSON.stringify({ token, minConfidence }),
  });
  await Promise.all([
    AsyncStorage.setItem(ENABLED_KEY, "true"),
    AsyncStorage.setItem(TOKEN_KEY, token),
    AsyncStorage.setItem(MIN_CONF_KEY, String(minConfidence)),
  ]);
  return token;
}

export async function disablePushAlerts(): Promise<void> {
  const { token } = await getStoredPushPrefs();
  await AsyncStorage.setItem(ENABLED_KEY, "false");
  if (token) {
    try {
      await apiJson("/notifications/push/preferences", {
        method: "POST",
        body: JSON.stringify({ token, enabled: false }),
      });
    } catch {
      // Server-side flag update is best-effort; local flag already off.
    }
  }
}

export async function updateMinConfidence(minConfidence: number): Promise<void> {
  await AsyncStorage.setItem(MIN_CONF_KEY, String(minConfidence));
  const { enabled, token } = await getStoredPushPrefs();
  if (enabled && token) {
    await apiJson("/notifications/push/preferences", {
      method: "POST",
      body: JSON.stringify({ token, minConfidence }),
    });
  }
}

// Silent re-registration on app launch. Never prompts; only refreshes the
// token server-side when the user already enabled alerts and permission is
// still granted. All failures are swallowed (e.g. Expo Go on Android).
export async function silentReRegister(): Promise<void> {
  try {
    if (Platform.OS === "web") return;
    const { enabled, minConfidence } = await getStoredPushPrefs();
    if (!enabled) return;
    const perms = await Notifications.getPermissionsAsync();
    if (perms.status !== "granted") return;
    const token = await fetchExpoPushToken();
    await apiJson("/notifications/push/register", {
      method: "POST",
      body: JSON.stringify({ token, minConfidence }),
    });
    await AsyncStorage.setItem(TOKEN_KEY, token);
  } catch {
    // Best-effort only.
  }
}
