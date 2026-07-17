/**
 * ArchivedSessions.tsx — Priority 2 (#21): review and restore archived
 * paper-trading sessions.
 *
 * Every portfolio reset archives the full session. This card lists archives,
 * supports read-only inspection, and a guarded two-step restore:
 *   step 1 — type the exact phrase "RESTORE PAPER SESSION" → server issues a
 *            one-time restore token (5 min TTL)
 *   step 2 — second confirmation click sends the phrase again + token.
 * Only simulated paper state is restored; the current session is archived
 * first, and the server rolls back automatically on failure.
 */

import { useCallback, useEffect, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import {
  Archive, Loader2, Eye, RotateCcw, ShieldAlert, X,
} from "lucide-react";
import { apiJson } from "@/lib/api";
import { useToast } from "@/hooks/use-toast";

/* eslint-disable @typescript-eslint/no-explicit-any */

const PHRASE = "RESTORE PAPER SESSION";

const inr = (v: unknown) =>
  typeof v === "number" ? `₹${v.toLocaleString("en-IN", { maximumFractionDigits: 2 })}` : "—";
const when = (s?: string | null) => (s ? new Date(s).toLocaleString() : "—");

export default function ArchivedSessions() {
  const { toast } = useToast();
  const [archives, setArchives] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [inspecting, setInspecting] = useState<any | null>(null);
  const [restoreTarget, setRestoreTarget] = useState<string | null>(null);
  const [phrase, setPhrase] = useState("");
  const [pending, setPending] = useState<{ token: string; expires: string } | null>(null);
  const [busy, setBusy] = useState(false);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const d = await apiJson("/session-archives");
      setArchives(d.archives ?? []);
    } catch (e: any) {
      toast({ title: "Could not load archives", description: e.message, variant: "destructive" });
    } finally {
      setLoading(false);
    }
  }, [toast]);

  useEffect(() => { void refresh(); }, [refresh]);

  const inspect = async (id: string) => {
    try {
      const d = await apiJson(`/session-archives/${id}`);
      if (d.success === false) throw new Error(d.error);
      setInspecting(d.archive);
    } catch (e: any) {
      toast({ title: "Inspection failed", description: e.message, variant: "destructive" });
    }
  };

  const beginRestore = (id: string) => {
    setRestoreTarget(id);
    setPhrase("");
    setPending(null);
  };

  const cancelRestore = () => {
    setRestoreTarget(null);
    setPhrase("");
    setPending(null);
  };

  const requestToken = async () => {
    if (!restoreTarget) return;
    setBusy(true);
    try {
      const d = await apiJson(`/session-archives/${restoreTarget}/restore`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ confirmation: phrase }),
      });
      if (!d.success) throw new Error(d.error ?? d.detail ?? "Request rejected");
      setPending({ token: d.restore_token, expires: d.expires_at });
    } catch (e: any) {
      toast({ title: "Restore blocked", description: e.message, variant: "destructive" });
    } finally {
      setBusy(false);
    }
  };

  const confirmRestore = async () => {
    if (!restoreTarget || !pending) return;
    setBusy(true);
    try {
      const d = await apiJson(`/session-archives/${restoreTarget}/restore`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ confirmation: phrase, restore_token: pending.token }),
      });
      if (!d.success) throw new Error(d.error ?? "Restore failed");
      toast({
        title: "Session restored",
        description: `Archive ${d.restored_archive_id} restored. Previous session saved as ${d.backup_archive_id}.`,
      });
      cancelRestore();
      await refresh();
    } catch (e: any) {
      toast({ title: "Restore failed", description: e.message, variant: "destructive" });
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card className="border-zinc-800 bg-zinc-900/60" data-testid="card-archived-sessions">
      <CardHeader className="px-5 pb-2 pt-4">
        <h2 className="flex items-center gap-2 font-mono text-sm font-bold uppercase tracking-widest text-zinc-300">
          <Archive className="h-4 w-4 text-primary" />Archived Sessions
          <Badge variant="outline" className="text-[10px] text-amber-400 border-amber-700">
            PAPER STATE ONLY
          </Badge>
        </h2>
      </CardHeader>
      <CardContent className="px-5 pb-5 text-xs">
        <p className="mb-3 text-zinc-500">
          Every portfolio reset archives the full session below. Restoring replaces the
          current simulated portfolio with an archived one — the current session is
          archived first. Credentials, live-order controls, evidence and audit history
          are never touched.
        </p>

        {loading ? (
          <div className="flex items-center gap-2 text-zinc-400">
            <Loader2 className="h-4 w-4 animate-spin" />Loading archives…
          </div>
        ) : archives.length === 0 ? (
          <p className="text-zinc-500" data-testid="text-no-archives">
            No archived sessions yet. Archives appear after a portfolio reset.
          </p>
        ) : (
          <div className="space-y-2">
            {archives.map((a) => (
              <div key={a.id}
                className="rounded border border-zinc-800 bg-zinc-950/50 p-3"
                data-testid={`row-archive-${a.id}`}>
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div>
                    <span className="font-bold text-zinc-200">{a.id}</span>
                    {a.restored_at && (
                      <Badge variant="outline" className="ml-2 text-[10px] text-emerald-400 border-emerald-800">
                        RESTORED {when(a.restored_at)}
                      </Badge>
                    )}
                    <div className="mt-1 text-zinc-500">
                      Reset {when(a.reset_at)} — {a.reset_reason || "no reason recorded"}
                    </div>
                  </div>
                  <div className="flex gap-2">
                    <Button size="sm" variant="outline" className="gap-1 text-xs"
                      onClick={() => inspect(a.id)} data-testid={`button-inspect-${a.id}`}>
                      <Eye className="h-3.5 w-3.5" />Inspect
                    </Button>
                    <Button size="sm" variant="outline" className="gap-1 text-xs text-amber-400"
                      onClick={() => beginRestore(a.id)} data-testid={`button-restore-${a.id}`}>
                      <RotateCcw className="h-3.5 w-3.5" />Restore…
                    </Button>
                  </div>
                </div>
                <div className="mt-2 grid grid-cols-2 gap-x-4 gap-y-1 text-zinc-400 sm:grid-cols-4">
                  <span>Value: <b className="text-zinc-200">{inr(a.metrics?.portfolio_value)}</b></span>
                  <span>Cash: <b className="text-zinc-200">{inr(a.metrics?.cash)}</b></span>
                  <span>Realized P&L: <b className="text-zinc-200">{inr(a.metrics?.realized_pnl)}</b></span>
                  <span>Unrealized P&L: <b className="text-zinc-200">{inr(a.metrics?.unrealized_pnl)}</b></span>
                  <span>Open positions: <b className="text-zinc-200">{a.metrics?.open_positions ?? "—"}</b></span>
                  <span>Pending orders: <b className="text-zinc-200">{a.metrics?.pending_orders ?? "—"}</b></span>
                  <span className="truncate">Config: <b className="text-zinc-200">{a.metrics?.config_hash?.slice(0, 10) || "—"}</b></span>
                  <span className="truncate">Scan: <b className="text-zinc-200">{a.metrics?.latest_scan_id || "—"}</b></span>
                </div>

                {restoreTarget === a.id && (
                  <div className="mt-3 rounded border border-amber-900/60 bg-amber-950/20 p-3"
                    data-testid={`panel-restore-${a.id}`}>
                    <div className="mb-2 flex items-center gap-1.5 font-bold text-amber-400">
                      <ShieldAlert className="h-4 w-4" />Guarded restore
                      <button className="ml-auto text-zinc-500 hover:text-zinc-300"
                        onClick={cancelRestore} data-testid="button-cancel-restore">
                        <X className="h-4 w-4" />
                      </button>
                    </div>
                    {!pending ? (
                      <>
                        <p className="mb-2 text-amber-200/80">
                          Type <b>{PHRASE}</b> exactly to request a restore. Your current
                          session will be archived before anything changes.
                        </p>
                        <div className="flex gap-2">
                          <input
                            className="w-64 rounded border border-zinc-700 bg-zinc-900 px-2 py-1 font-mono text-xs text-zinc-200"
                            value={phrase}
                            onChange={(e) => setPhrase(e.target.value)}
                            placeholder={PHRASE}
                            data-testid="input-restore-phrase"
                          />
                          <Button size="sm" disabled={phrase !== PHRASE || busy}
                            onClick={requestToken} data-testid="button-request-restore">
                            {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : "Continue"}
                          </Button>
                        </div>
                      </>
                    ) : (
                      <>
                        <p className="mb-2 text-amber-200/80">
                          Second confirmation required. This will replace the current paper
                          portfolio with archive <b>{a.id}</b>. Token expires {when(pending.expires)}.
                        </p>
                        <div className="flex gap-2">
                          <Button size="sm" variant="destructive" disabled={busy}
                            onClick={confirmRestore} data-testid="button-confirm-restore">
                            {busy
                              ? <Loader2 className="h-3.5 w-3.5 animate-spin" />
                              : <>Yes, restore this session</>}
                          </Button>
                          <Button size="sm" variant="outline" onClick={cancelRestore}>Cancel</Button>
                        </div>
                      </>
                    )}
                  </div>
                )}
              </div>
            ))}
          </div>
        )}

        {inspecting && (
          <div className="mt-4 rounded border border-zinc-800 bg-zinc-950/70 p-3"
            data-testid="panel-inspect">
            <div className="mb-2 flex items-center gap-2 font-bold text-zinc-200">
              <Eye className="h-4 w-4" />Read-only inspection — {inspecting.id}
              <button className="ml-auto text-zinc-500 hover:text-zinc-300"
                onClick={() => setInspecting(null)} data-testid="button-close-inspect">
                <X className="h-4 w-4" />
              </button>
            </div>
            <pre className="max-h-72 overflow-auto rounded bg-zinc-900 p-3 text-[11px] leading-5 text-zinc-400">
              {JSON.stringify(inspecting.snapshot, null, 2)}
            </pre>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
