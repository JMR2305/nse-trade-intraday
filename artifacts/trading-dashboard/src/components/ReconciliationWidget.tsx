/**
 * ReconciliationWidget.tsx — EOD broker reconciliation status panel.
 *
 * Shows:
 *  - Last reconciliation run summary (clean/discrepancies, timestamp)
 *  - Open discrepancies requiring manual review (with confirm-before-resolve)
 *  - Resolved discrepancies in a collapsible section (type, symbol, timestamp)
 *  - Manual trigger button (with force option)
 */

import { useState, useCallback } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  CheckCircle2, XCircle, AlertTriangle, RefreshCw,
  Loader2, ShieldCheck, Clock, ChevronDown, ChevronUp,
  CheckCheck,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { API_BASE } from "@/lib/api";
import { useToast } from "@/hooks/use-toast";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";

/* eslint-disable @typescript-eslint/no-explicit-any */

async function apiFetch(path: string, init?: RequestInit): Promise<any> {
  const resp = await fetch(`${API_BASE}${path}`, init);
  const text = await resp.text();
  if (!text.trim()) throw new Error(`Empty response from ${path}`);
  let data: any;
  try { data = JSON.parse(text); } catch { throw new Error(`Invalid JSON from ${path}`); }
  if (!resp.ok) throw new Error(String(data?.error ?? `HTTP ${resp.status}`));
  return data;
}

const DISCREPANCY_COLORS: Record<string, string> = {
  STATE_MISMATCH:   "text-red-400 border-red-800 bg-red-950/20",
  FILL_MISMATCH:    "text-red-400 border-red-800 bg-red-950/20",
  LOCAL_ONLY:       "text-amber-400 border-amber-800 bg-amber-950/20",
  BROKER_ONLY:      "text-amber-400 border-amber-800 bg-amber-950/20",
  QUANTITY_MISMATCH:"text-orange-400 border-orange-800 bg-orange-950/20",
  PRICE_MISMATCH:   "text-orange-400 border-orange-800 bg-orange-950/20",
  DUPLICATE_ORDER:  "text-purple-400 border-purple-800 bg-purple-950/20",
  UNRESOLVED_BROKER_EVENT: "text-zinc-400 border-zinc-700 bg-zinc-900/40",
  MISSING_EXCHANGE_ORDER_ID: "text-zinc-400 border-zinc-700 bg-zinc-900/40",
};

function fmtTs(ts: string | null | undefined): string {
  if (!ts) return "—";
  try {
    return new Date(ts).toLocaleString("en-IN", {
      timeZone: "Asia/Kolkata",
      dateStyle: "short",
      timeStyle: "short",
    }) + " IST";
  } catch { return ts; }
}

function RunSummaryRow({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between text-xs py-1.5 border-b border-zinc-800 last:border-0">
      <span className="text-zinc-500">{label}</span>
      <span className="font-mono">{value}</span>
    </div>
  );
}

// ── Inline confirmation state per discrepancy ────────────────────────────────
interface ConfirmState {
  id: number;
  note: string;
}

export default function ReconciliationWidget() {
  const { toast } = useToast();
  const qc = useQueryClient();
  const [showHistory, setShowHistory] = useState(false);
  const [showResolved, setShowResolved] = useState(false);
  const [resolvingId, setResolvingId] = useState<number | null>(null);
  // confirmState: which discrepancy is in the "are you sure?" step
  const [confirm, setConfirm] = useState<ConfirmState | null>(null);

  // ── Data fetching ─────────────────────────────────────────────────────────
  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: ["reconciliation-status"],
    queryFn: () => apiFetch("/broker/reconciliation"),
    refetchInterval: 60_000,
  });

  // ── Manual trigger ────────────────────────────────────────────────────────
  const triggerMutation = useMutation({
    mutationFn: (force: boolean) =>
      apiFetch("/broker/reconciliation/trigger", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ force }),
      }),
    onSuccess: (result: any) => {
      qc.invalidateQueries({ queryKey: ["reconciliation-status"] });
      if (result?.skipped) {
        toast({ title: "Reconciliation skipped", description: result.reason });
      } else {
        const dc = result?.discrepancy_count ?? 0;
        toast({
          title: dc === 0 ? "✅ Reconciliation clean" : `⚠️ ${dc} discrepancy/ies found`,
          description: `Run ${result?.run_id?.slice(0, 8)}… — ${result?.orders_checked ?? 0} orders checked`,
          variant: dc > 0 ? "destructive" : "default",
        });
      }
    },
    onError: (err: any) => {
      toast({ title: "Trigger failed", description: err.message, variant: "destructive" });
    },
  });

  // ── Confirm step: open ────────────────────────────────────────────────────
  const beginResolve = useCallback((id: number) => {
    setConfirm({ id, note: "" });
  }, []);

  // ── Confirm step: cancel ──────────────────────────────────────────────────
  const cancelResolve = useCallback(() => {
    setConfirm(null);
  }, []);

  // ── Confirm step: commit ──────────────────────────────────────────────────
  const commitResolve = useCallback(async () => {
    if (!confirm) return;
    const { id, note } = confirm;
    setConfirm(null);
    setResolvingId(id);
    try {
      await apiFetch("/broker/reconciliation/resolve", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ id, note: note.trim() || undefined }),
      });
      toast({ title: "Discrepancy resolved", description: `ID ${id} marked as resolved` });
      qc.invalidateQueries({ queryKey: ["reconciliation-status"] });
    } catch (err: any) {
      toast({ title: "Resolve failed", description: err.message, variant: "destructive" });
    } finally {
      setResolvingId(null);
    }
  }, [confirm, qc, toast]);

  // ── Derived state ─────────────────────────────────────────────────────────
  const lastRun = data?.last_run ?? {};
  const dbRun = lastRun?.db_latest_run ?? lastRun;
  const openDisc: any[] = data?.open_discrepancies ?? [];
  const resolvedDisc: any[] = data?.resolved_discrepancies ?? [];
  const reviewNeeded = openDisc.filter((d: any) => d.requires_manual_review);
  const recentRuns: any[] = lastRun?.recent_runs ?? [];
  const lastRanToday = data?.last_ran_today ?? false;
  const eodWindowActive = data?.eod_window_active ?? false;
  const isClean = (dbRun?.clean ?? true) && openDisc.length === 0;

  // ── Render helpers ────────────────────────────────────────────────────────
  if (isLoading) return (
    <Card className="border-zinc-800 bg-zinc-900/60">
      <CardContent className="flex items-center gap-2 py-6 text-zinc-500 text-sm font-mono">
        <Loader2 className="h-4 w-4 animate-spin" />Loading reconciliation status…
      </CardContent>
    </Card>
  );

  if (isError) return (
    <Card className="border-zinc-800 bg-zinc-900/60">
      <CardContent className="py-4">
        <div className="flex items-center gap-2 text-sm font-mono text-red-400">
          <XCircle className="h-4 w-4" />
          {(error as any)?.message ?? "Failed to load reconciliation status"}
        </div>
        <Button size="sm" variant="outline" className="mt-2 text-xs" onClick={() => refetch()}>
          Retry
        </Button>
      </CardContent>
    </Card>
  );

  return (
    <Card className="border-zinc-800 bg-zinc-900/60">
      <CardHeader className="pb-2 pt-4 px-5">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2 font-mono font-bold text-sm text-zinc-300 uppercase tracking-widest">
            <ShieldCheck className="h-4 w-4 text-primary" />
            EOD Order Reconciliation
            {reviewNeeded.length > 0 && (
              <Badge variant="destructive" className="text-[10px] ml-1">
                {reviewNeeded.length} needs review
              </Badge>
            )}
            {isClean && !reviewNeeded.length && lastRun?.run_id && (
              <Badge variant="outline" className="text-[10px] text-emerald-400 border-emerald-800">
                CLEAN
              </Badge>
            )}
          </div>
          <div className="flex items-center gap-2">
            <Button size="sm" variant="outline" onClick={() => refetch()}
              className="gap-1.5 text-xs h-7">
              <RefreshCw className="h-3 w-3" />
            </Button>
            <Button size="sm" variant="outline"
              onClick={() => triggerMutation.mutate(false)}
              disabled={triggerMutation.isPending}
              className="gap-1.5 text-xs h-7">
              {triggerMutation.isPending
                ? <Loader2 className="h-3 w-3 animate-spin" />
                : <Clock className="h-3 w-3" />}
              Run Now
            </Button>
            <Button size="sm" variant="outline"
              onClick={() => triggerMutation.mutate(true)}
              disabled={triggerMutation.isPending}
              className="gap-1.5 text-xs h-7 border-amber-800 text-amber-400 hover:bg-amber-950/30">
              {triggerMutation.isPending
                ? <Loader2 className="h-3 w-3 animate-spin" />
                : <AlertTriangle className="h-3 w-3" />}
              Force
            </Button>
          </div>
        </div>
      </CardHeader>

      <CardContent className="px-5 pb-5 space-y-4">

        {/* Status bar */}
        <div className={cn(
          "flex items-center gap-3 px-3 py-2.5 rounded-md border text-xs font-mono",
          reviewNeeded.length > 0
            ? "bg-red-950/30 border-red-800 text-red-300"
            : isClean && lastRun?.run_id
              ? "bg-emerald-950/20 border-emerald-900 text-emerald-300"
              : "bg-zinc-900 border-zinc-700 text-zinc-400",
        )}>
          {reviewNeeded.length > 0
            ? <AlertTriangle className="h-4 w-4 flex-shrink-0" />
            : isClean && lastRun?.run_id
              ? <CheckCircle2 className="h-4 w-4 flex-shrink-0" />
              : <Clock className="h-4 w-4 flex-shrink-0" />}
          <div className="flex-1">
            {reviewNeeded.length > 0
              ? `${reviewNeeded.length} discrepancy/ies require manual review`
              : isClean && lastRun?.run_id
                ? `Clean — ${dbRun?.orders_checked ?? 0} orders verified`
                : "No reconciliation run recorded yet"}
          </div>
          <div className="ml-auto flex items-center gap-3 text-zinc-500 text-[10px]">
            {eodWindowActive
              ? <span className="text-emerald-400">EOD window active</span>
              : <span>Runs after 15:35 IST</span>}
            {lastRanToday && <span className="text-emerald-400">✓ Ran today</span>}
          </div>
        </div>

        {/* Last run summary */}
        {dbRun?.run_id && (
          <div className="border border-zinc-800 rounded-lg overflow-hidden">
            <div className="bg-zinc-900 px-4 py-2 text-[10px] font-mono text-zinc-500 uppercase tracking-wide">
              Last run
            </div>
            <div className="px-4 py-1">
              <RunSummaryRow label="Run ID" value={
                <span className="text-zinc-400">{String(dbRun.run_id).slice(0, 8)}…</span>
              } />
              <RunSummaryRow label="Trigger" value={
                <Badge variant="outline" className="text-[10px]">
                  {String(dbRun.trigger ?? "—").toUpperCase()}
                </Badge>
              } />
              <RunSummaryRow label="Started" value={fmtTs(dbRun.started_at)} />
              <RunSummaryRow label="Orders checked" value={dbRun.orders_checked ?? "—"} />
              <RunSummaryRow label="Discrepancies" value={
                <span className={dbRun.discrepancy_count > 0 ? "text-red-400" : "text-emerald-400"}>
                  {dbRun.discrepancy_count ?? 0}
                </span>
              } />
              <RunSummaryRow label="Result" value={
                dbRun.paper_mode
                  ? <span className="text-zinc-400">PAPER MODE</span>
                  : dbRun.clean
                    ? <span className="text-emerald-400">CLEAN</span>
                    : <span className="text-red-400">DISCREPANCIES</span>
              } />
              {dbRun.error && (
                <div className="py-2 text-[10px] text-red-400 font-mono break-all">{dbRun.error}</div>
              )}
            </div>
          </div>
        )}

        {/* Open discrepancies */}
        {openDisc.length > 0 && (
          <div>
            <div className="text-[10px] font-mono text-zinc-500 uppercase tracking-wide mb-2">
              Open discrepancies ({openDisc.length})
            </div>
            <div className="space-y-1.5">
              {openDisc.map((d: any) => {
                const isConfirming = confirm?.id === d.id;
                const isResolving = resolvingId === d.id;
                return (
                  <div key={d.id}
                    className={cn(
                      "rounded-md border px-3 py-2.5 text-xs font-mono transition-colors",
                      DISCREPANCY_COLORS[d.discrepancy_type] ?? "text-zinc-400 border-zinc-700 bg-zinc-900/40",
                    )}>
                    <div className="flex items-start justify-between gap-2">
                      <div className="flex-1">
                        <div className="flex items-center gap-2 mb-0.5">
                          <span className="font-bold">{d.discrepancy_type}</span>
                          {d.trading_symbol && (
                            <span className="text-zinc-300">{d.trading_symbol}</span>
                          )}
                          {d.requires_manual_review && (
                            <Badge variant="destructive" className="text-[9px] h-4">
                              REVIEW
                            </Badge>
                          )}
                        </div>
                        <div className="text-[11px] text-zinc-400 mt-0.5">{d.description}</div>
                        <div className="flex items-center gap-3 text-[10px] text-zinc-500 mt-1">
                          {d.broker_order_id && <span>broker={d.broker_order_id}</span>}
                          {d.local_value && <span>local={d.local_value}</span>}
                          {d.broker_value && <span>broker_val={d.broker_value}</span>}
                          <span>{fmtTs(d.created_at)}</span>
                        </div>
                      </div>

                      {/* Resolve action — two-step confirm */}
                      <div className="flex-shrink-0">
                        {isResolving ? (
                          <Loader2 className="h-4 w-4 animate-spin text-zinc-400 mt-1" />
                        ) : isConfirming ? (
                          <div className="flex flex-col gap-1.5 items-end">
                            <input
                              type="text"
                              placeholder="Note (optional)"
                              value={confirm?.note ?? ""}
                              onChange={e => setConfirm(c => c ? { ...c, note: e.target.value } : c)}
                              maxLength={500}
                              className="w-40 px-2 py-1 text-[10px] rounded border border-zinc-600 bg-zinc-800 text-zinc-200 placeholder:text-zinc-600 focus:outline-none focus:border-zinc-400"
                            />
                            <div className="flex gap-1">
                              <Button size="sm" variant="outline"
                                className="h-6 text-[10px] gap-1 border-zinc-600 text-zinc-400"
                                onClick={cancelResolve}>
                                Cancel
                              </Button>
                              <Button size="sm"
                                className="h-6 text-[10px] gap-1 bg-emerald-700 hover:bg-emerald-600 text-white border-0"
                                onClick={commitResolve}>
                                <CheckCheck className="h-2.5 w-2.5" />
                                Confirm
                              </Button>
                            </div>
                          </div>
                        ) : (
                          <Button size="sm" variant="outline"
                            className="h-6 text-[10px] gap-1"
                            onClick={() => beginResolve(d.id)}>
                            <CheckCircle2 className="h-2.5 w-2.5" />
                            Resolve
                          </Button>
                        )}
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {/* Resolved discrepancies — collapsible audit trail */}
        {resolvedDisc.length > 0 && (
          <div>
            <button
              onClick={() => setShowResolved(v => !v)}
              className="flex items-center gap-2 text-[10px] font-mono text-zinc-500 hover:text-zinc-300 transition-colors uppercase tracking-wide">
              {showResolved ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />}
              <CheckCheck className="h-3 w-3 text-emerald-600" />
              Resolved ({resolvedDisc.length})
            </button>
            {showResolved && (
              <div className="mt-2 space-y-1.5">
                {resolvedDisc.map((d: any) => (
                  <div key={d.id}
                    className="rounded-md border border-zinc-800 bg-zinc-900/30 px-3 py-2 text-xs font-mono opacity-75">
                    <div className="flex items-center gap-2">
                      <CheckCircle2 className="h-3 w-3 text-emerald-600 flex-shrink-0" />
                      <span className="text-zinc-400 font-semibold">{d.discrepancy_type}</span>
                      {d.trading_symbol && (
                        <span className="text-zinc-500">{d.trading_symbol}</span>
                      )}
                      <span className="ml-auto text-[10px] text-zinc-600">
                        resolved {fmtTs(d.resolved_at)}
                      </span>
                    </div>
                    {d.resolved_note && (
                      <div className="mt-1 text-[10px] text-zinc-600 pl-5 italic">
                        "{d.resolved_note}"
                      </div>
                    )}
                    {d.description && (
                      <div className="mt-0.5 text-[10px] text-zinc-700 pl-5">{d.description}</div>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {/* Run history (collapsible) */}
        {recentRuns.length > 0 && (
          <div>
            <button
              onClick={() => setShowHistory(v => !v)}
              className="flex items-center gap-2 text-[10px] font-mono text-zinc-500 hover:text-zinc-300 transition-colors uppercase tracking-wide">
              {showHistory ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />}
              Run history ({recentRuns.length})
            </button>
            {showHistory && (
              <div className="mt-2 overflow-x-auto">
                <table className="w-full text-[10px] font-mono">
                  <thead>
                    <tr className="text-zinc-500 border-b border-zinc-800">
                      <th className="text-left py-1.5 pr-3">Date/Time</th>
                      <th className="text-left py-1.5 pr-3">Trigger</th>
                      <th className="text-right py-1.5 pr-3">Orders</th>
                      <th className="text-right py-1.5 pr-3">Discrepancies</th>
                      <th className="text-left py-1.5">Result</th>
                    </tr>
                  </thead>
                  <tbody>
                    {recentRuns.map((r: any, i: number) => (
                      <tr key={r.run_id ?? i} className="border-b border-zinc-800/50 hover:bg-zinc-800/20">
                        <td className="py-1.5 pr-3 text-zinc-400">{fmtTs(r.started_at)}</td>
                        <td className="py-1.5 pr-3 text-zinc-400">{String(r.trigger ?? "").toUpperCase()}</td>
                        <td className="py-1.5 pr-3 text-right text-zinc-300">{r.orders_checked ?? "—"}</td>
                        <td className={cn("py-1.5 pr-3 text-right",
                          r.discrepancy_count > 0 ? "text-red-400" : "text-emerald-400")}>
                          {r.discrepancy_count ?? 0}
                        </td>
                        <td className="py-1.5">
                          {r.paper_mode
                            ? <span className="text-zinc-500">PAPER</span>
                            : r.clean
                              ? <span className="text-emerald-400">CLEAN</span>
                              : <span className="text-red-400">DISCREPANCIES</span>}
                          {r.error && <span className="text-red-500 ml-1">ERR</span>}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        )}

      </CardContent>
    </Card>
  );
}
