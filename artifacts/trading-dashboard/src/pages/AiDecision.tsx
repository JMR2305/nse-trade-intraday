import { useState } from "react";
import {
  useGetAiDecisions,
  useRunScan,
  type AiDecision,
} from "@workspace/api-client-react";
import { formatCurrency } from "@/lib/format";
import {
  Brain,
  ChevronDown,
  ChevronRight,
  RefreshCw,
  ShieldCheck,
  ShieldX,
  ArrowUpCircle,
  ArrowDownCircle,
  AlertTriangle,
  MinusCircle,
  CheckCircle2,
  XCircle,
} from "lucide-react";

// ── Helpers ────────────────────────────────────────────────────────────────────

const DECISION_META: Record<
  string,
  { label: string; color: string; bg: string; border: string }
> = {
  STRONG_BUY:  { label: "STRONG BUY",  color: "text-emerald-400", bg: "bg-emerald-400/10", border: "border-emerald-500/40" },
  BUY:         { label: "BUY",         color: "text-green-400",   bg: "bg-green-400/10",   border: "border-green-500/40"   },
  STRONG_SELL: { label: "STRONG SELL", color: "text-red-400",     bg: "bg-red-400/10",     border: "border-red-500/40"     },
  SELL:        { label: "SELL",        color: "text-orange-400",  bg: "bg-orange-400/10",  border: "border-orange-500/40"  },
  WATCH:       { label: "WATCH",       color: "text-yellow-400",  bg: "bg-yellow-400/10",  border: "border-yellow-500/40"  },
  NO_TRADE:    { label: "NO TRADE",    color: "text-zinc-500",    bg: "bg-zinc-800/50",    border: "border-zinc-700"       },
};

function DecisionBadge({ decision }: { decision: string }) {
  const m = DECISION_META[decision] ?? DECISION_META.NO_TRADE;
  return (
    <span
      className={`font-mono text-xs font-bold px-2 py-0.5 rounded border ${m.color} ${m.bg} ${m.border}`}
    >
      {m.label}
    </span>
  );
}

function RawBadge({ signal }: { signal: string }) {
  const m = DECISION_META[signal] ?? DECISION_META.NO_TRADE;
  return (
    <span className={`font-mono text-xs px-1.5 py-0.5 rounded ${m.color} ${m.bg}`}>
      {signal.replace("_", " ")}
    </span>
  );
}

function RRBar({ rr }: { rr: number }) {
  const pct = Math.min(rr / 4, 1) * 100;
  const color = rr >= 3 ? "bg-emerald-500" : rr >= 2 ? "bg-green-500" : "bg-red-500";
  return (
    <div className="flex items-center gap-2">
      <div className="w-16 h-1.5 rounded-full bg-zinc-800 overflow-hidden">
        <div className={`h-full rounded-full ${color}`} style={{ width: `${pct}%` }} />
      </div>
      <span className="font-mono text-xs text-foreground/70">{rr.toFixed(1)}:1</span>
    </div>
  );
}

function TFDots({ count }: { count: number }) {
  return (
    <div className="flex gap-1">
      {[0, 1, 2, 3].map((i) => (
        <div
          key={i}
          className={`w-2 h-2 rounded-full ${
            i < count ? "bg-primary" : "bg-zinc-700"
          }`}
        />
      ))}
    </div>
  );
}

function ConfidenceBar({ value }: { value: number }) {
  const color =
    value >= 90 ? "bg-emerald-500" :
    value >= 75 ? "bg-green-500" :
    value >= 60 ? "bg-yellow-500" : "bg-red-500";
  return (
    <div className="flex items-center gap-2">
      <div className="w-20 h-1.5 rounded-full bg-zinc-800 overflow-hidden">
        <div className={`h-full rounded-full ${color}`} style={{ width: `${value}%` }} />
      </div>
      <span className="font-mono text-xs text-foreground/70">{value.toFixed(0)}</span>
    </div>
  );
}

// ── Expanded Detail Row ────────────────────────────────────────────────────────

function DecisionDetail({ d }: { d: AiDecision }) {
  return (
    <div className="bg-zinc-900/60 border border-zinc-800 rounded-lg p-4 space-y-4">
      {/* Plain English */}
      <div className="flex gap-3">
        <Brain className="h-4 w-4 text-primary mt-0.5 shrink-0" />
        <p className="text-sm text-foreground/80 leading-relaxed">{d.plain_english}</p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {/* Upgrade reasons */}
        {d.upgrade_reasons.length > 0 && (
          <div className="space-y-2">
            <div className="flex items-center gap-1.5 text-xs font-mono text-emerald-400 uppercase tracking-wide">
              <ArrowUpCircle className="h-3.5 w-3.5" />
              Upgrades ({d.upgrade_reasons.length})
            </div>
            {d.upgrade_reasons.map((r: string, i: number) => (
              <div key={i} className="flex gap-2 text-sm text-foreground/70">
                <CheckCircle2 className="h-4 w-4 text-emerald-500 shrink-0 mt-0.5" />
                <span>{r}</span>
              </div>
            ))}
          </div>
        )}

        {/* Downgrade reasons */}
        {d.downgrade_reasons.length > 0 && (
          <div className="space-y-2">
            <div className="flex items-center gap-1.5 text-xs font-mono text-red-400 uppercase tracking-wide">
              <ArrowDownCircle className="h-3.5 w-3.5" />
              Downgrades ({d.downgrade_reasons.length})
            </div>
            {d.downgrade_reasons.map((r: string, i: number) => (
              <div key={i} className="flex gap-2 text-sm text-foreground/70">
                <XCircle className="h-4 w-4 text-red-500 shrink-0 mt-0.5" />
                <span>{r}</span>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Price levels */}
      <div className="grid grid-cols-3 gap-3">
        <div className="bg-zinc-800/50 rounded-lg p-3 text-center">
          <div className="text-xs text-foreground/50 font-mono mb-1">ENTRY</div>
          <div className="text-sm font-mono font-bold text-foreground">
            {formatCurrency(d.entry_price)}
          </div>
        </div>
        <div className="bg-red-500/10 border border-red-500/20 rounded-lg p-3 text-center">
          <div className="text-xs text-red-400 font-mono mb-1">STOP LOSS</div>
          <div className="text-sm font-mono font-bold text-red-400">
            {formatCurrency(d.stop_loss)}
          </div>
        </div>
        <div className="bg-emerald-500/10 border border-emerald-500/20 rounded-lg p-3 text-center">
          <div className="text-xs text-emerald-400 font-mono mb-1">TARGET</div>
          <div className="text-sm font-mono font-bold text-emerald-400">
            {formatCurrency(d.target)}
          </div>
        </div>
      </div>
    </div>
  );
}

// ── Rules Reference ────────────────────────────────────────────────────────────

function RulesCard() {
  return (
    <div className="rounded-lg border border-border bg-card p-4">
      <div className="text-xs font-mono text-primary/70 uppercase tracking-widest mb-3">
        AI Engine Rules
      </div>
      <div className="grid grid-cols-2 md:grid-cols-3 gap-2">
        {[
          { icon: ShieldX, label: "RR < 2:1 → WATCH", color: "text-red-400" },
          { icon: ShieldX, label: "MTF < 3/4 → WATCH", color: "text-red-400" },
          { icon: ShieldX, label: "High vol + conf<70 → WATCH", color: "text-orange-400" },
          { icon: ShieldX, label: "Sideways + conf<72 → WATCH", color: "text-orange-400" },
          { icon: ShieldX, label: "Stop <0.5% → WATCH", color: "text-orange-400" },
          { icon: ShieldX, label: "No capital → NO TRADE", color: "text-red-500" },
        ].map(({ icon: Icon, label, color }) => (
          <div key={label} className={`flex items-center gap-1.5 text-xs ${color}`}>
            <Icon className="h-3 w-3 shrink-0" />
            <span className="font-mono">{label}</span>
          </div>
        ))}
        {[
          { label: "RR≥3 + MTF=4 → +5 conf", color: "text-emerald-400" },
          { label: "Regime match → +3 conf", color: "text-emerald-400" },
          { label: "Low-vol + conf≥80 → +3 conf", color: "text-emerald-400" },
        ].map(({ label, color }) => (
          <div key={label} className={`flex items-center gap-1.5 text-xs ${color}`}>
            <ShieldCheck className="h-3 w-3 shrink-0" />
            <span className="font-mono">{label}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Main Page ──────────────────────────────────────────────────────────────────

export default function AiDecisionPage() {
  const { data: decisions = [], isLoading, refetch } = useGetAiDecisions();
  const runScan = useRunScan();
  const [expandedRow, setExpandedRow] = useState<string | null>(null);

  const handleScan = () => {
    runScan.mutate(undefined, { onSuccess: () => refetch() });
  };

  const approved = decisions.filter((d) => d.pass_all_rules && !["WATCH","NO_TRADE"].includes(d.decision));
  const watchlist = decisions.filter((d) => d.decision === "WATCH");
  const blocked   = decisions.filter((d) => d.decision === "NO_TRADE");

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight flex items-center gap-2">
            <Brain className="h-6 w-6 text-primary" />
            AI Decision Engine
          </h1>
          <p className="text-sm text-muted-foreground mt-1">
            Signal review · Risk/reward · Multi-timeframe · Regime filter
          </p>
        </div>
        <button
          onClick={handleScan}
          disabled={runScan.isPending}
          className="flex items-center gap-2 px-4 py-2 bg-primary text-primary-foreground rounded-md text-sm font-medium hover:bg-primary/90 disabled:opacity-50 transition-colors"
          data-testid="button-run-scan"
        >
          <RefreshCw className={`h-4 w-4 ${runScan.isPending ? "animate-spin" : ""}`} />
          {runScan.isPending ? "Scanning…" : "Run Scan"}
        </button>
      </div>

      {/* Rules reference */}
      <RulesCard />

      {/* Summary pills */}
      {decisions.length > 0 && (
        <div className="flex gap-3 flex-wrap">
          <div className="flex items-center gap-2 px-3 py-1.5 rounded-full bg-emerald-500/10 border border-emerald-500/20 text-emerald-400 text-xs font-mono">
            <CheckCircle2 className="h-3.5 w-3.5" />
            {approved.length} Approved
          </div>
          <div className="flex items-center gap-2 px-3 py-1.5 rounded-full bg-yellow-500/10 border border-yellow-500/20 text-yellow-400 text-xs font-mono">
            <AlertTriangle className="h-3.5 w-3.5" />
            {watchlist.length} Watch
          </div>
          <div className="flex items-center gap-2 px-3 py-1.5 rounded-full bg-zinc-800 border border-zinc-700 text-zinc-500 text-xs font-mono">
            <MinusCircle className="h-3.5 w-3.5" />
            {blocked.length} Blocked
          </div>
        </div>
      )}

      {/* Table */}
      <div className="rounded-lg border border-border bg-card overflow-hidden">
        {/* Table header */}
        <div className="hidden md:grid grid-cols-[1.2fr_1fr_1fr_1fr_1fr_1.2fr_0.8fr_32px] gap-3 px-4 py-2.5 border-b border-border bg-muted/30">
          {["STOCK", "RAW → DECISION", "ENTRY", "STOP / TARGET", "RR", "CONFIDENCE", "TF / REGIME", ""].map(
            (h) => (
              <div key={h} className="text-xs font-mono text-muted-foreground uppercase tracking-wider">
                {h}
              </div>
            )
          )}
        </div>

        {isLoading ? (
          <div className="py-16 text-center text-muted-foreground text-sm font-mono">
            Loading AI decisions…
          </div>
        ) : decisions.length === 0 ? (
          <div className="py-16 text-center space-y-2">
            <Brain className="h-10 w-10 text-muted-foreground/30 mx-auto" />
            <p className="text-muted-foreground text-sm font-mono">No decisions yet</p>
            <p className="text-xs text-muted-foreground/60">Run a scan to generate AI-reviewed signals</p>
          </div>
        ) : (
          <div>
            {decisions.map((d) => {
              const key = d.stock;
              const isExpanded = expandedRow === key;
              const m = DECISION_META[d.decision] ?? DECISION_META.NO_TRADE;
              return (
                <div key={key} className="border-b border-border/50 last:border-0">
                  {/* Main row */}
                  <button
                    className={`w-full text-left hover:bg-muted/20 transition-colors ${m.bg}`}
                    onClick={() => setExpandedRow(isExpanded ? null : key)}
                    data-testid={`row-ai-${d.stock}`}
                  >
                    <div className="grid grid-cols-2 md:grid-cols-[1.2fr_1fr_1fr_1fr_1fr_1.2fr_0.8fr_32px] gap-3 px-4 py-3 items-center">
                      {/* Stock */}
                      <div className="flex items-center gap-2">
                        {d.pass_all_rules ? (
                          <CheckCircle2 className="h-3.5 w-3.5 text-emerald-500 shrink-0" />
                        ) : (
                          <AlertTriangle className="h-3.5 w-3.5 text-yellow-500 shrink-0" />
                        )}
                        <span className="font-mono font-bold text-sm">{d.stock}</span>
                      </div>

                      {/* Raw → Decision */}
                      <div className="flex items-center gap-1.5 flex-wrap">
                        <RawBadge signal={d.raw_signal} />
                        <span className="text-muted-foreground/50 text-xs">→</span>
                        <DecisionBadge decision={d.decision} />
                      </div>

                      {/* Entry */}
                      <div className="font-mono text-sm text-foreground/90 hidden md:block">
                        {formatCurrency(d.entry_price)}
                      </div>

                      {/* Stop / Target */}
                      <div className="hidden md:flex flex-col gap-0.5">
                        <span className="font-mono text-xs text-red-400">
                          SL {formatCurrency(d.stop_loss)}
                        </span>
                        <span className="font-mono text-xs text-emerald-400">
                          T {formatCurrency(d.target)}
                        </span>
                      </div>

                      {/* RR */}
                      <div className="hidden md:block">
                        <RRBar rr={d.rr_ratio} />
                      </div>

                      {/* Confidence */}
                      <div className="hidden md:block">
                        <ConfidenceBar value={d.confidence} />
                      </div>

                      {/* TF + Regime */}
                      <div className="hidden md:flex flex-col gap-1">
                        <TFDots count={d.timeframe_alignment} />
                        <span className="text-xs font-mono text-muted-foreground/60">
                          {d.regime}
                        </span>
                      </div>

                      {/* Expand */}
                      <div className="hidden md:flex justify-end text-muted-foreground">
                        {isExpanded ? (
                          <ChevronDown className="h-4 w-4" />
                        ) : (
                          <ChevronRight className="h-4 w-4" />
                        )}
                      </div>
                    </div>
                  </button>

                  {/* Expanded detail */}
                  {isExpanded && (
                    <div className="px-4 pb-4">
                      <DecisionDetail d={d} />
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
