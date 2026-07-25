/**
 * useReconciliationBadge — lightweight background poll for open review-required
 * reconciliation discrepancies. Fetches every 2 minutes so the sidebar badge
 * stays fresh without slowing page loads.
 */

import { useQuery } from "@tanstack/react-query";
import { apiJson } from "@/lib/api";

interface ReconciliationSummary {
  open_discrepancies?: Array<{ requires_manual_review?: boolean }>;
}

export function useReconciliationBadge(): number {
  const { data } = useQuery<ReconciliationSummary>({
    queryKey: ["reconciliation-badge"],
    queryFn: () => apiJson("/broker/reconciliation"),
    refetchInterval: 2 * 60 * 1000, // 2 minutes
    // Stale immediately so any mounted instance uses fresh data on next interval
    staleTime: 0,
    // Don't retry aggressively — this is ambient, non-blocking
    retry: 1,
    // Suppress error toasts; the badge simply shows 0 on failure
    throwOnError: false,
  });

  if (!data?.open_discrepancies) return 0;
  return data.open_discrepancies.filter((d) => d.requires_manual_review).length;
}
