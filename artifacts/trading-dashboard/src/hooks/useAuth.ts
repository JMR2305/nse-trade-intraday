/**
 * useAuth — operator session state for the trading dashboard.
 *
 * Queries GET /api/auth/me on mount to determine whether the operator has
 * an active session.  Returns:
 *   - isLoading  true while the initial check is in flight
 *   - authenticated  true when the server confirms a valid session
 *   - logout()   POST /api/auth/logout then clear local query cache
 */

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "@/lib/apiFetch";
import { buildApiUrl } from "@/lib/apiConfig";

interface AuthState {
  authenticated: boolean;
}

async function fetchAuthMe(): Promise<AuthState> {
  try {
    return await apiFetch<AuthState>("/auth/me");
  } catch {
    return { authenticated: false };
  }
}

export function useAuth() {
  const queryClient = useQueryClient();

  const { data, isLoading } = useQuery<AuthState>({
    queryKey: ["auth", "me"],
    queryFn: fetchAuthMe,
    staleTime: 60_000,
    retry: false,         // a 401 is not a transient error
    refetchOnWindowFocus: true,
  });

  const authenticated = data?.authenticated ?? false;

  async function logout(): Promise<void> {
    try {
      await fetch(buildApiUrl("/auth/logout"), { method: "POST" });
    } catch { /* ignore network errors on logout */ }
    // Invalidate all cached queries so stale data is not shown after logout
    queryClient.clear();
  }

  return { authenticated, isLoading, logout };
}
