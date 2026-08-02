/**
 * TradeMemoryPage.tsx — Phase 10D
 * Trade Memory — full learning record for every completed paper trade.
 *
 * READ-ONLY · ADVISORY-ONLY
 */
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { apiJson } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Database, Shield, ChevronDown, ChevronUp, TrendingUp, TrendingDown } from "lucide-react";

const q = (path: string) => ({
  queryKey:  ["trade-memory", path],
  queryFn:   () => apiJson("learning-layer/" + path),
  refetchInterval: 60_000,
  retry: 1,
  staleTime: 30_000,
});

function OutcomeBadge({ outcome }: { outcome: string }) {
  const cls = outcome === "WIN"
    ? "bg-emerald-600 text-white"
    : "bg-red-600 text-white";
  return (
    <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-semibold ${cls}`}>
      {outcome === "WIN" ? <TrendingUp className="w-3 h-3 mr-1" /> : <TrendingDown className="w-3 h-3 mr-1" />}
      {outcome}
    </span>
  );
}

function MemoryCard({ mem }: { mem: any }) {
  const [exp, setExp] = useState(false);
  const pnl = mem.pnl_pct ?? 0;
  const pnlColor = pnl >= 0 ? "text-emerald-400" : "text-red-400";

  return (
    <div className="bg-card rounded-xl border border-border overflow-hidden">
      {/* Header */}
      <div className="p-4 flex items-start justify-between gap-3">
        <div className="flex items-start gap-3">
          <div>
            <div className="flex items-center gap-2 mb-1">
              <span className="font-bold text-base">{mem.symbol}</span>
              <OutcomeBadge outcome={mem.outcome} />
            </div>
            <p className="text-xs text-muted-foreground">
              {mem.strategy} · {mem.sector}
            </p>
          </div>
        </div>
        <div className="text-right">
          <p className={`text-xl font-bold font-mono ${pnlColor}`}>
            {pnl >= 0 ? "+" : ""}{pnl.toFixed(2)}%
          </p>
          <p className="text-xs text-muted-foreground">{mem.decision_type?.replace(/_/g, " ")}</p>
        </div>
      </div>

      {/* Compact meta */}
      <div className="px-4 pb-3 grid grid-cols-2 sm:grid-cols-4 gap-2 text-xs">
        <div>
          <p className="text-muted-foreground">Confidence</p>
          <p className="font-mono">{((mem.decision_confidence ?? 0) * 100).toFixed(0)}%</p>
        </div>
        <div>
          <p className="text-muted-foreground">Entry</p>
          <p className="font-mono">₹{mem.entry_price?.toFixed(2) ?? "—"}</p>
        </div>
        <div>
          <p className="text-muted-foreground">Exit</p>
          <p className="font-mono">₹{mem.exit_price?.toFixed(2) ?? "—"}</p>
        </div>
        <div>
          <p className="text-muted-foreground">Qty</p>
          <p className="font-mono">{mem.quantity ?? "—"}</p>
        </div>
      </div>

      {/* Expandable detail */}
      {exp && (
        <div className="border-t border-border px-4 py-3 space-y-3">
          {mem.ai_explanation_summary && (
            <div>
              <p className="text-xs font-semibold text-muted-foreground mb-1">AI Explanation</p>
              <p className="text-xs text-muted-foreground">{mem.ai_explanation_summary}</p>
            </div>
          )}
          {(mem.supporting_signals ?? []).length > 0 && (
            <div>
              <p className="text-xs font-semibold text-muted-foreground mb-1">Supporting Signals</p>
              <div className="flex flex-wrap gap-1">
                {mem.supporting_signals.slice(0, 5).map((s: string, i: number) => (
                  <Badge key={i} variant="outline" className="text-[10px]">{s}</Badge>
                ))}
              </div>
            </div>
          )}
          {(mem.lessons_learned ?? []).length > 0 && (
            <div>
              <p className="text-xs font-semibold text-teal-400 mb-1">Lessons Learned</p>
              <ul className="space-y-1">
                {mem.lessons_learned.map((l: string, i: number) => (
                  <li key={i} className="text-xs text-muted-foreground flex items-start gap-2">
                    <span className="mt-1 w-1.5 h-1.5 rounded-full bg-teal-400 flex-shrink-0" />
                    {l}
                  </li>
                ))}
              </ul>
            </div>
          )}
          <div className="grid grid-cols-2 gap-3 text-xs">
            <div>
              <p className="text-muted-foreground">Stop Loss</p>
              <p className="font-mono">₹{mem.stop_loss?.toFixed(2) ?? "—"}</p>
            </div>
            <div>
              <p className="text-muted-foreground">Risk %</p>
              <p className="font-mono">{mem.risk_pct?.toFixed(2) ?? "—"}%</p>
            </div>
          </div>
          {mem.timestamp && (
            <p className="text-[10px] text-muted-foreground">Recorded: {mem.timestamp}</p>
          )}
        </div>
      )}

      {/* Expand toggle */}
      <button
        onClick={() => setExp(!exp)}
        className="w-full px-4 py-2 text-xs text-muted-foreground hover:text-foreground flex items-center justify-center gap-1 border-t border-border/50 transition-colors"
      >
        {exp ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
        {exp ? "Collapse" : "View Full Memory"}
      </button>
    </div>
  );
}

export default function TradeMemoryPage() {
  const memQ = useQuery(q("knowledge/memory"));
  const data: any = memQ.data ?? {};
  const memory: any[] = data.trade_memory ?? [];
  const wins  = memory.filter(m => m.outcome === "WIN").length;
  const losses = memory.filter(m => m.outcome === "LOSS").length;

  return (
    <div className="p-6 space-y-6 max-w-5xl mx-auto">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Database className="w-6 h-6 text-teal-400" />
          <div>
            <h1 className="text-xl font-bold">Trade Memory</h1>
            <p className="text-sm text-muted-foreground">Full learning record for every completed paper trade</p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <Badge variant="outline" className="text-xs border-teal-500/50 text-teal-400">READ-ONLY</Badge>
          <Badge variant="outline" className="text-xs border-amber-500/50 text-amber-400">ADVISORY</Badge>
          <Badge className="text-xs bg-teal-600">{memory.length} Trade{memory.length !== 1 ? "s" : ""}</Badge>
        </div>
      </div>

      <Alert className="border-teal-500/30 bg-teal-500/10">
        <Shield className="h-4 w-4 text-teal-400" />
        <AlertDescription className="text-xs text-teal-300">
          Trade memory is a read-only record. {wins} win{wins !== 1 ? "s" : ""},{" "}
          {losses} loss{losses !== 1 ? "es" : ""}. All lessons are advisory.
        </AlertDescription>
      </Alert>

      {/* Summary row */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <div className="bg-card rounded-xl border border-border p-4">
          <p className="text-xs text-muted-foreground">Trades Learned</p>
          <p className="text-2xl font-bold text-teal-400">{memory.length}</p>
        </div>
        <div className="bg-card rounded-xl border border-border p-4">
          <p className="text-xs text-muted-foreground">Winners</p>
          <p className="text-2xl font-bold text-emerald-400">{wins}</p>
        </div>
        <div className="bg-card rounded-xl border border-border p-4">
          <p className="text-xs text-muted-foreground">Losses</p>
          <p className="text-2xl font-bold text-red-400">{losses}</p>
        </div>
        <div className="bg-card rounded-xl border border-border p-4">
          <p className="text-xs text-muted-foreground">Win Rate</p>
          <p className="text-2xl font-bold">
            {memory.length > 0 ? `${((wins / memory.length) * 100).toFixed(0)}%` : "—"}
          </p>
        </div>
      </div>

      {memory.length === 0 ? (
        <div className="bg-card rounded-xl border border-border p-8 text-center">
          <Database className="w-8 h-8 text-muted-foreground mx-auto mb-3" />
          <p className="text-sm text-muted-foreground">
            No completed paper trades yet. Trade memory will populate as paper trades are executed and closed.
          </p>
        </div>
      ) : (
        <div className="space-y-4">
          {memory.map((m: any) => <MemoryCard key={m.memory_id} mem={m} />)}
        </div>
      )}

      <p className="text-xs text-muted-foreground text-right">
        Updated {data.generated_at ?? "—"} · READ-ONLY · ADVISORY-ONLY
      </p>
    </div>
  );
}
