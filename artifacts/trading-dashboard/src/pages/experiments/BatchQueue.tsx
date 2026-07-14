/**
 * BatchQueue.tsx — Phase 4.1: Batch runner for sequential experiment execution.
 *
 * Manages groups of experiments submitted as a batch (from sweep templates or
 * manual batch submission).  Auto-advances through queued experiments one at a
 * time, shows progress, elapsed time, per-experiment status, and allows cancel.
 *
 * Paper trading and research only.  No auto-promotion.
 */
import { useState, useEffect, useRef, useCallback } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import {
  Play, Square, Loader2, CheckCircle2, XCircle, Clock,
  AlertTriangle, RefreshCw, ChevronDown, ChevronRight, Trash2,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useToast } from "@/hooks/use-toast";

/* eslint-disable @typescript-eslint/no-explicit-any */

import { apiJson } from "@/lib/api";

// ── Types ──────────────────────────────────────────────────────────────────

interface BatchExpEntry {
  id: string;
  name: string;
  status: "queued" | "running" | "completed" | "rejected" | "failed";
  batch_index: number;
  score?: number;
  verdict?: string;
  overfitting_flags?: string[];
  auto_rejected?: boolean;
  metrics?: any;
  created_at: string;
  completed_at?: string;
  started_at?: string;
  error?: string;
  wf_progress?: any;
}

interface BatchInfo {
  id: string;
  name: string;
  template_family: string;
  template_id: string;
  experiments: BatchExpEntry[];
  total: number;
  completed: number;
  failed: number;
  running: number;
  queued: number;
  status: "queued" | "running" | "completed" | "failed" | "partial";
  created_at: string;
}

// ── Helpers ────────────────────────────────────────────────────────────────

const FAMILY_LABELS: Record<string, string> = {
  market_conditions: "Market Conditions",
  confidence_sweep:  "Confidence Sweep",
  holding_sweep:     "Holding-Period Sweep",
  window_sweep:      "Window Sweep",
};

function fmtNum(v?: number | null, d = 2) {
  if (v == null) return "—";
  return v.toFixed(d);
}

function expStatusBadge(s: BatchExpEntry["status"]) {
  switch (s) {
    case "queued":    return <Badge variant="outline" className="text-zinc-400 border-zinc-600 text-[10px] font-mono"><Clock className="h-3 w-3 mr-1" />Queued</Badge>;
    case "running":   return <Badge variant="outline" className="text-sky-400 border-sky-500 text-[10px] font-mono animate-pulse"><Loader2 className="h-3 w-3 mr-1 animate-spin" />Running</Badge>;
    case "completed": return <Badge variant="outline" className="text-emerald-400 border-emerald-600 text-[10px] font-mono"><CheckCircle2 className="h-3 w-3 mr-1" />Done</Badge>;
    case "rejected":  return <Badge variant="outline" className="text-amber-400 border-amber-600 text-[10px] font-mono"><AlertTriangle className="h-3 w-3 mr-1" />Rejected</Badge>;
    case "failed":    return <Badge variant="outline" className="text-red-400 border-red-600 text-[10px] font-mono"><XCircle className="h-3 w-3 mr-1" />Failed</Badge>;
  }
}

function batchStatusBadge(s: BatchInfo["status"]) {
  const map: Record<string, [string, string]> = {
    queued:    ["text-zinc-400 border-zinc-600",     "Queued"],
    running:   ["text-sky-400 border-sky-500",       "Running"],
    completed: ["text-emerald-400 border-emerald-600","Done"],
    failed:    ["text-red-400 border-red-600",       "Failed"],
    partial:   ["text-amber-400 border-amber-600",   "Partial"],
  };
  const [cls, label] = map[s] ?? ["text-zinc-400", s];
  return <Badge variant="outline" className={cn("text-[10px] font-mono", cls)}>{label}</Badge>;
}

function formatElapsed(secs: number) {
  const m = Math.floor(secs / 60);
  const s = secs % 60;
  return `${m}:${String(s).padStart(2, "0")}`;
}

// ── BatchCard ──────────────────────────────────────────────────────────────

function BatchCard({
  batch, isAutoRunning, isCancelled, startTime,
  onRun, onCancel,
}: {
  batch: BatchInfo;
  isAutoRunning: boolean;
  isCancelled: boolean;
  startTime?: number;
  onRun: () => void;
  onCancel: () => void;
}) {
  const [expanded, setExpanded] = useState(true);
  const [elapsed, setElapsed] = useState(0);

  useEffect(() => {
    if (!startTime) return;
    const tick = () => setElapsed(Math.floor((Date.now() - startTime) / 1000));
    tick();
    const t = setInterval(tick, 1000);
    return () => clearInterval(t);
  }, [startTime]);

  const progressPct = batch.total > 0
    ? Math.round((batch.completed + batch.failed) / batch.total * 100)
    : 0;

  const hasQueued = batch.queued > 0;
  const runningExp = batch.experiments.find(e => e.status === "running");
  const wfProg = runningExp?.wf_progress;

  const familyLabel = FAMILY_LABELS[batch.template_family] || batch.template_family || "Custom";

  return (
    <div className={cn(
      "rounded-md border p-3 space-y-2",
      batch.status === "running" ? "border-sky-500/40 bg-sky-500/5"
        : batch.status === "completed" ? "border-emerald-700/30 bg-emerald-900/5"
        : batch.status === "failed" ? "border-red-500/30 bg-red-500/5"
        : "border-zinc-700 bg-zinc-800/20"
    )}>
      {/* Header row */}
      <div className="flex items-start gap-2 flex-wrap">
        <div className="flex-1 min-w-0 space-y-1">
          <div className="flex items-center gap-2 flex-wrap">
            {batchStatusBadge(isCancelled ? "failed" : batch.status)}
            <span className="text-xs font-mono font-semibold truncate">{batch.name}</span>
            {batch.template_family && (
              <Badge variant="outline" className="text-[9px] font-mono text-violet-300 border-violet-700 px-1">
                {familyLabel}
              </Badge>
            )}
            {isCancelled && (
              <Badge variant="outline" className="text-red-400 border-red-600 text-[9px] font-mono">CANCELLED</Badge>
            )}
          </div>
          <p className="text-[10px] font-mono text-zinc-500">
            {batch.completed}/{batch.total} complete
            {batch.failed > 0 ? ` · ${batch.failed} failed` : ""}
            {batch.running > 0 ? ` · 1 running` : ""}
            {batch.queued > 0 ? ` · ${batch.queued} queued` : ""}
            {startTime ? ` · ${formatElapsed(elapsed)} elapsed` : ""}
          </p>
        </div>
        <div className="flex items-center gap-1.5 flex-shrink-0">
          {hasQueued && !isAutoRunning && !isCancelled && (
            <Button size="sm"
              className="h-7 px-2.5 font-mono text-[11px] bg-sky-600 hover:bg-sky-500 text-white"
              onClick={onRun}>
              <Play className="h-3.5 w-3.5 mr-1" />
              Run Batch
            </Button>
          )}
          {isAutoRunning && !isCancelled && (
            <Button size="sm" variant="outline"
              className="h-7 px-2.5 font-mono text-[11px] text-red-400 border-red-600 hover:bg-red-900/20"
              onClick={onCancel}>
              <Square className="h-3.5 w-3.5 mr-1" />
              Cancel
            </Button>
          )}
          <button className="text-zinc-500 hover:text-zinc-300"
            onClick={() => setExpanded(e => !e)}>
            {expanded
              ? <ChevronDown className="h-4 w-4" />
              : <ChevronRight className="h-4 w-4" />}
          </button>
        </div>
      </div>

      {/* Progress bar */}
      {batch.total > 0 && (
        <div className="space-y-1">
          <div className="h-1.5 bg-zinc-700 rounded-full overflow-hidden">
            <div
              className={cn(
                "h-full rounded-full transition-all",
                batch.failed > 0 && batch.completed + batch.failed === batch.total
                  ? "bg-red-500"
                  : batch.status === "completed" ? "bg-emerald-500"
                  : "bg-sky-500"
              )}
              style={{ width: `${progressPct}%` }}
            />
          </div>
          {/* Running WF progress */}
          {wfProg && (
            <div className="flex items-center gap-2 text-[10px] font-mono text-zinc-400">
              <Loader2 className="h-3 w-3 animate-spin flex-shrink-0" />
              <span className="truncate">
                {runningExp?.name} — {wfProg.phase || "running"}
                {wfProg.progress_pct != null ? ` (${wfProg.progress_pct}%)` : ""}
              </span>
            </div>
          )}
        </div>
      )}

      {/* Experiment list */}
      {expanded && (
        <div className="space-y-1 pt-1">
          {batch.experiments.map((exp, idx) => (
            <div key={exp.id}
              className={cn(
                "flex items-center gap-2 px-2 py-1 rounded text-[10px] font-mono",
                exp.status === "running" ? "bg-sky-500/10" : "bg-zinc-800/40"
              )}>
              <span className="text-zinc-600 w-4 flex-shrink-0">{idx + 1}.</span>
              {expStatusBadge(exp.status)}
              <span className="flex-1 truncate text-zinc-300">{exp.name}</span>
              {exp.score != null && (
                <span className={cn(
                  "tabular-nums flex-shrink-0",
                  exp.auto_rejected ? "text-amber-400" : "text-emerald-400"
                )}>
                  {exp.score.toFixed(0)}/100
                </span>
              )}
              {exp.metrics?.profit_factor != null && (
                <span className="text-zinc-500 flex-shrink-0">
                  PF {fmtNum(exp.metrics.profit_factor)}
                </span>
              )}
              {exp.status === "failed" && exp.error && (
                <span className="text-red-400 truncate max-w-[120px]">{exp.error}</span>
              )}
              {exp.auto_rejected && (
                <Badge variant="outline" className="text-[8px] font-mono text-amber-400 border-amber-600 px-1 flex-shrink-0">
                  OVERFIT
                </Badge>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ── Main export ────────────────────────────────────────────────────────────

export function BatchQueue({
  hasAnyRunning,
  onExperimentsChanged,
}: {
  hasAnyRunning: boolean;
  onExperimentsChanged: () => Promise<void>;
}) {
  const { toast } = useToast();
  const [batches, setBatches] = useState<BatchInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [cancelledBatches, setCancelledBatches] = useState<Set<string>>(new Set());
  const [autoRunBatchId, setAutoRunBatchId] = useState<string | null>(null);
  const [batchStartTimes, setBatchStartTimes] = useState<Record<string, number>>({});
  const prevHasAnyRunning = useRef(hasAnyRunning);

  const fetchBatches = useCallback(async () => {
    try {
      const data = await apiJson("/batches");
      if (data.batches) setBatches(data.batches);
    } catch { /* silent */ }
  }, []);

  useEffect(() => {
    fetchBatches().finally(() => setLoading(false));
  }, [fetchBatches]);

  // Poll while auto-running
  useEffect(() => {
    if (!autoRunBatchId) return;
    const t = setInterval(async () => {
      await fetchBatches();
      await onExperimentsChanged();
    }, 4000);
    return () => clearInterval(t);
  }, [autoRunBatchId, fetchBatches, onExperimentsChanged]);

  // Auto-advance: when hasAnyRunning transitions true→false, check if next queued exists
  useEffect(() => {
    const wasRunning = prevHasAnyRunning.current;
    prevHasAnyRunning.current = hasAnyRunning;

    if (!wasRunning || hasAnyRunning) return; // only fire on true→false
    if (!autoRunBatchId) return;
    if (cancelledBatches.has(autoRunBatchId)) {
      setAutoRunBatchId(null);
      return;
    }

    // Refresh batches then try to advance
    fetchBatches().then(() => {
      setBatches(current => {
        const batch = current.find(b => b.id === autoRunBatchId);
        if (!batch) { setAutoRunBatchId(null); return current; }

        const nextQueued = [...batch.experiments]
          .sort((a, b) => a.batch_index - b.batch_index)
          .find(e => e.status === "queued");

        if (!nextQueued) {
          setAutoRunBatchId(null);
          toast({
            title: "Batch complete",
            description: `"${batch.name}" — all ${batch.total} experiments finished.`,
          });
          return current;
        }

        // Kick off next experiment
        apiJson(`/experiments/${nextQueued.id}/run`, { method: "POST" })
          .then(() => { onExperimentsChanged(); })
          .catch(e => {
            toast({ title: "Auto-advance failed", description: String(e), variant: "destructive" });
            setAutoRunBatchId(null);
          });
        return current;
      });
    });
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [hasAnyRunning]);

  async function startBatch(batch: BatchInfo) {
    if (hasAnyRunning || cancelledBatches.has(batch.id)) return;
    const nextQueued = [...batch.experiments]
      .sort((a, b) => a.batch_index - b.batch_index)
      .find(e => e.status === "queued");
    if (!nextQueued) {
      toast({ title: "Nothing to run", description: "All experiments in this batch are already done." });
      return;
    }
    setBatchStartTimes(t => ({ ...t, [batch.id]: t[batch.id] ?? Date.now() }));
    setAutoRunBatchId(batch.id);
    try {
      await apiJson(`/experiments/${nextQueued.id}/run`, { method: "POST" });
      await fetchBatches();
      await onExperimentsChanged();
      toast({
        title: "Batch started",
        description: `Running "${nextQueued.name}" (1 of ${batch.queued} queued)…`,
      });
    } catch (e) {
      setAutoRunBatchId(null);
      toast({ title: "Start failed", description: String(e), variant: "destructive" });
    }
  }

  function cancelBatch(batchId: string) {
    setCancelledBatches(c => new Set([...c, batchId]));
    if (autoRunBatchId === batchId) setAutoRunBatchId(null);
    toast({
      title: "Batch cancelled",
      description: "Auto-run stopped. Any currently running experiment will complete normally.",
    });
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center py-12 text-sm font-mono text-muted-foreground">
        <Loader2 className="h-5 w-5 animate-spin mr-2 text-zinc-600" />
        Loading batches…
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {/* Toolbar */}
      <div className="flex items-center justify-between">
        <p className="text-[10px] font-mono text-zinc-500">
          Experiments in a batch run sequentially — one at a time, in order.
          Cancel stops auto-advance; the current experiment still finishes.
        </p>
        <Button size="sm" variant="outline" className="font-mono text-xs gap-1.5 h-7"
          onClick={() => fetchBatches()}>
          <RefreshCw className="h-3.5 w-3.5" />
          Refresh
        </Button>
      </div>

      {batches.length === 0 && (
        <Card>
          <CardContent className="py-10 text-center space-y-2">
            <Trash2 className="h-8 w-8 mx-auto text-zinc-700" />
            <p className="text-sm font-mono text-muted-foreground">No batches yet.</p>
            <p className="text-xs font-mono text-zinc-600">
              Use a parameter sweep template (Confidence, Holding, Window) to create a batch,
              or add experiments manually with the same batch name.
            </p>
          </CardContent>
        </Card>
      )}

      {batches.map(batch => (
        <BatchCard
          key={batch.id}
          batch={batch}
          isAutoRunning={autoRunBatchId === batch.id}
          isCancelled={cancelledBatches.has(batch.id)}
          startTime={batchStartTimes[batch.id]}
          onRun={() => startBatch(batch)}
          onCancel={() => cancelBatch(batch.id)}
        />
      ))}

      <p className="text-[10px] font-mono text-zinc-600 border-t border-zinc-800 pt-2 text-center">
        Research only · paper trading · results do not affect live strategy selection
      </p>
    </div>
  );
}
