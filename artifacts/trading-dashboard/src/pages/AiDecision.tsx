import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { apiJson } from "@/lib/api";
import {
  useGetOpportunityScan,
  useGetAiDecisions,
  useRunScan,
  type OpportunityItem,
  type AiDecision,
} from "@workspace/api-client-react";
import { formatCurrency } from "@/lib/format";
import HistoricalEvidence from "@/components/HistoricalEvidence";
import {
  Brain,
  ChevronDown,
  ChevronRight,
  RefreshCw,
  Flame,
  TrendingUp,
  Eye,
  MinusCircle,
  CheckCircle2,
  XCircle,
  AlertTriangle,
  ArrowUpCircle,
  ArrowDownCircle,
  ShieldCheck,
  ShieldX,
  Coins,
  BarChart2,
  Activity,
  Zap,
} from "lucide-react";

// ── Status helpers ─────────────────────────────────────────────────────────────

const STATUS_META: Record<string, { label: string; color: string; bg: string; border: string; icon: React.ComponentType<{ className?: string }> }> = {
  HOT_BUY: { label: "HOT BUY", color: "text-orange-300", bg: "bg-orange-500/10", border: "border-orange-500/40", icon: Flame },
  BUY:     { label: "BUY",     color: "text-emerald-400", bg: "bg-emerald-500/10", border: "border-emerald-500/40", icon: TrendingUp },
  WATCH:   { label: "WATCH",   color: "text-yellow-400",  bg: "bg-yellow-500/10",  border: "border-yellow-500/40",  icon: Eye },
  IGNORE:  { label: "IGNORE",  color: "text-zinc-500",    bg: "bg-zinc-800/40",    border: "border-zinc-700",       icon: MinusCircle },
};

const DECISION_META: Record<string, { color: string; bg: string }> = {
  STRONG_BUY:  { color: "text-emerald-400", bg: "bg-emerald-400/10" },
  BUY:         { color: "text-green-400",   bg: "bg-green-400/10"   },
  STRONG_SELL: { color: "text-red-400",     bg: "bg-red-400/10"     },
  SELL:        { color: "text-orange-400",  bg: "bg-orange-400/10"  },
  WATCH:       { color: "text-yellow-400",  bg: "bg-yellow-400/10"  },
  NO_TRADE:    { color: "text-zinc-500",    bg: "bg-zinc-800/50"    },
};

// ── Mini components ────────────────────────────────────────────────────────────

function StatusBadge({ status }: { status: string }) {
  const m = STATUS_META[status] ?? STATUS_META.IGNORE;
  const Icon = m.icon;
  return (
    <span className={`inline-flex items-center gap-1 font-mono text-xs font-bold px-2 py-0.5 rounded border ${m.color} ${m.bg} ${m.border}`}>
      <Icon className="h-3 w-3" />
      {m.label}
    </span>
  );
}

function DecisionChip({ decision }: { decision: string }) {
  const m = DECISION_META[decision] ?? DECISION_META.NO_TRADE;
  return (
    <span className={`font-mono text-xs px-1.5 py-0.5 rounded ${m.color} ${m.bg}`}>
      {decision.replace("_", " ")}
    </span>
  );
}

function ScoreRing({ value, size = 44 }: { value: number; size?: number }) {
  const r = size / 2 - 4;
  const circ = 2 * Math.PI * r;
  const filled = (value / 100) * circ;
  const color = value >= 75 ? "#10b981" : value >= 55 ? "#eab308" : "#ef4444";
  return (
    <svg width={size} height={size} className="shrink-0">
      <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="#27272a" strokeWidth={4} />
      <circle
        cx={size / 2} cy={size / 2} r={r}
        fill="none" stroke={color} strokeWidth={4}
        strokeDasharray={`${filled} ${circ - filled}`}
        strokeLinecap="round"
        transform={`rotate(-90 ${size / 2} ${size / 2})`}
      />
      <text x={size / 2} y={size / 2 + 4} textAnchor="middle" fill={color} fontSize={10} fontFamily="monospace" fontWeight="bold">
        {value.toFixed(0)}
      </text>
    </svg>
  );
}

function MiniBar({ label, value, color = "" }: { label: string; value: number; color?: string }) {
  const barColor = color || (value >= 75 ? "bg-emerald-500" : value >= 55 ? "bg-yellow-500" : "bg-red-500");
  return (
    <div className="space-y-0.5">
      <div className="flex items-center justify-between">
        <span className="text-xs font-mono text-muted-foreground">{label}</span>
        <span className="text-xs font-mono text-foreground/80">{value.toFixed(0)}</span>
      </div>
      <div className="h-1.5 rounded-full bg-zinc-800 overflow-hidden">
        <div className={`h-full rounded-full ${barColor} transition-all`} style={{ width: `${value}%` }} />
      </div>
    </div>
  );
}

function OppScoreBar({ value }: { value: number }) {
  const color = value >= 85 ? "bg-orange-400" : value >= 70 ? "bg-emerald-500" : value >= 50 ? "bg-yellow-500" : "bg-zinc-600";
  return (
    <div className="flex items-center gap-2">
      <div className="w-16 h-1.5 rounded-full bg-zinc-800 overflow-hidden">
        <div className={`h-full rounded-full ${color}`} style={{ width: `${value}%` }} />
      </div>
      <span className="font-mono text-xs text-foreground/70">{value.toFixed(0)}</span>
    </div>
  );
}

function GradeBadge({ grade }: { grade: string }) {
  const colors: Record<string, string> = {
    "A+": "text-emerald-300 bg-emerald-500/20 border-emerald-500/40",
    "A":  "text-green-400 bg-green-500/15 border-green-500/30",
    "B":  "text-blue-400 bg-blue-500/10 border-blue-500/30",
    "C":  "text-yellow-400 bg-yellow-500/10 border-yellow-500/30",
    "D":  "text-orange-400 bg-orange-500/10 border-orange-500/30",
    "F":  "text-red-400 bg-red-500/10 border-red-500/30",
  };
  return (
    <span className={`font-mono text-xs font-bold px-1.5 py-0.5 rounded border ${colors[grade] ?? colors["F"]}`}>
      {grade}
    </span>
  );
}

// ── Expanded detail panel ──────────────────────────────────────────────────────

function OpportunityDetail({
  item,
  aiDec,
}: {
  item: OpportunityItem;
  aiDec: AiDecision | undefined;
}) {
  return (
    <div className="bg-zinc-900/70 border border-zinc-800 rounded-lg p-4 space-y-5">
      {/* One-liner */}
      {item.one_liner && (
        <div className="flex gap-2">
          <Zap className="h-4 w-4 text-primary mt-0.5 shrink-0" />
          <p className="text-sm text-foreground/85 leading-relaxed font-mono">{item.one_liner}</p>
        </div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-3 gap-5">
        {/* ── Trade Quality sub-scores ── */}
        <div className="space-y-3">
          <div className="flex items-center gap-1.5 mb-2">
            <Activity className="h-3.5 w-3.5 text-primary" />
            <span className="text-xs font-mono text-primary/80 uppercase tracking-wider">Trade Quality</span>
            <GradeBadge grade={item.tq_grade} />
          </div>
          <MiniBar label="Trend"    value={item.tq_trend}    />
          <MiniBar label="Momentum" value={item.tq_momentum} />
          <MiniBar label="Volume"   value={item.tq_volume}   />
          <MiniBar label="Breakout" value={item.tq_breakout} />
          <MiniBar label="Risk"     value={item.tq_risk}     />
          <MiniBar label="Market"   value={item.tq_market}   />
          <div className="pt-1 border-t border-zinc-800">
            <MiniBar label="Total" value={item.trade_quality} color={
              item.trade_quality >= 75 ? "bg-emerald-400" : item.trade_quality >= 55 ? "bg-yellow-400" : "bg-red-400"
            } />
          </div>
        </div>

        {/* ── Position Sizing ── */}
        <div className="space-y-3">
          <div className="flex items-center gap-1.5 mb-2">
            <Coins className="h-3.5 w-3.5 text-primary" />
            <span className="text-xs font-mono text-primary/80 uppercase tracking-wider">Position Sizing</span>
          </div>

          <div className="grid grid-cols-2 gap-2">
            {[
              { label: "Quantity",    value: item.suggested_qty > 0 ? `${item.suggested_qty} shares` : "—" },
              { label: "Position",   value: item.position_value > 0 ? formatCurrency(item.position_value) : "—" },
              { label: "Max Loss",   value: item.expected_risk > 0  ? formatCurrency(item.expected_risk)  : "—", red: true },
              { label: "Est. Profit",value: item.expected_reward > 0 ? formatCurrency(item.expected_reward): "—", green: true },
              { label: "RR Ratio",   value: `1:${item.rr_ratio.toFixed(1)}` },
              { label: "Capital Use",value: item.capital_used_pct > 0 ? `${item.capital_used_pct.toFixed(1)}%` : "—" },
            ].map(({ label, value, red, green }) => (
              <div key={label} className="bg-zinc-800/50 rounded-md p-2">
                <div className="text-xs text-muted-foreground font-mono mb-0.5">{label}</div>
                <div className={`text-sm font-mono font-bold ${red ? "text-red-400" : green ? "text-emerald-400" : "text-foreground"}`}>
                  {value}
                </div>
              </div>
            ))}
          </div>

          {item.sizing_note && (
            <p className="text-xs text-muted-foreground/70 font-mono bg-zinc-800/40 rounded p-2 leading-relaxed">
              {item.sizing_note}
            </p>
          )}
        </div>

        {/* ── Explainability ── */}
        <div className="space-y-3">
          <div className="flex items-center gap-1.5 mb-2">
            <Brain className="h-3.5 w-3.5 text-primary" />
            <span className="text-xs font-mono text-primary/80 uppercase tracking-wider">Explainability</span>
          </div>

          {item.approve_reasons.length > 0 && (
            <div className="space-y-1.5">
              <div className="flex items-center gap-1 text-xs font-mono text-emerald-400 uppercase tracking-wide">
                <ArrowUpCircle className="h-3 w-3" /> Approve
              </div>
              {item.approve_reasons.map((r, i) => (
                <div key={i} className="flex gap-1.5 text-xs text-foreground/75">
                  <CheckCircle2 className="h-3.5 w-3.5 text-emerald-500 shrink-0 mt-0.5" />
                  <span>{r}</span>
                </div>
              ))}
            </div>
          )}

          {item.avoid_reasons.length > 0 && (
            <div className="space-y-1.5">
              <div className="flex items-center gap-1 text-xs font-mono text-red-400 uppercase tracking-wide">
                <ArrowDownCircle className="h-3 w-3" /> Caution
              </div>
              {item.avoid_reasons.map((r, i) => (
                <div key={i} className="flex gap-1.5 text-xs text-foreground/75">
                  <XCircle className="h-3.5 w-3.5 text-red-500 shrink-0 mt-0.5" />
                  <span>{r}</span>
                </div>
              ))}
            </div>
          )}

          {/* AI engine detail if available */}
          {aiDec && aiDec.plain_english && (
            <div className="pt-2 border-t border-zinc-800">
              <p className="text-xs text-foreground/60 leading-relaxed italic">{aiDec.plain_english}</p>
            </div>
          )}
        </div>
      </div>

      {/* Price levels */}
      <div className="grid grid-cols-3 gap-3">
        <div className="bg-zinc-800/50 rounded-lg p-3 text-center">
          <div className="text-xs text-foreground/50 font-mono mb-1">ENTRY</div>
          <div className="text-sm font-mono font-bold">{formatCurrency(item.entry_price)}</div>
        </div>
        <div className="bg-red-500/10 border border-red-500/20 rounded-lg p-3 text-center">
          <div className="text-xs text-red-400 font-mono mb-1">STOP LOSS</div>
          <div className="text-sm font-mono font-bold text-red-400">{formatCurrency(item.stop_loss)}</div>
        </div>
        <div className="bg-emerald-500/10 border border-emerald-500/20 rounded-lg p-3 text-center">
          <div className="text-xs text-emerald-400 font-mono mb-1">TARGET</div>
          <div className="text-sm font-mono font-bold text-emerald-400">{formatCurrency(item.target)}</div>
        </div>
      </div>

      {/* Historical evidence from the Trade Intelligence database */}
      <HistoricalEvidence symbol={item.stock} defaultOpen />

      {/* Phase 14 adaptive learning context */}
      <Phase14LearningContext item={item} />

      {/* Phase 15 structured explanation (canonical scan factors) */}
      <Phase15Explanation symbol={item.stock} />
    </div>
  );
}

// ── Phase 14 learning context ──────────────────────────────────────────────────

function Phase14LearningContext({ item }: { item: OpportunityItem }) {
  const anyItem = item as any;
  const { data, isLoading } = useQuery({
    queryKey: ["/api/phase14/decision-context", item.stock],
    queryFn: () =>
      apiJson<any>("/phase14/decision-context", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          symbol: item.stock,
          raw_confidence: anyItem.confidence ?? anyItem.ai_confidence ?? item.opportunity_score,
          opportunity_score: item.opportunity_score,
          trade_quality: anyItem.trade_quality,
          strategy: anyItem.strategy ?? "AI Scan",
          sector: anyItem.sector,
          recommendation: item.status,
        }),
      }),
    staleTime: 5 * 60_000,
  });
  if (isLoading) {
    return <div className="text-[10px] font-mono text-muted-foreground/60">Loading learning context…</div>;
  }
  if (!data?.success) return null;
  const adj = data.adaptive_adjustment ?? 0;
  return (
    <div className="rounded-lg border border-purple-500/20 bg-purple-500/5 p-3 space-y-1.5">
      <div className="flex items-center gap-1.5 text-xs font-mono text-purple-300 uppercase tracking-wider">
        <Brain className="h-3.5 w-3.5" /> Learning Context (Phase 14 · research only)
      </div>
      <div className="grid grid-cols-2 md:grid-cols-5 gap-2 text-[11px] font-mono">
        <div><span className="text-muted-foreground block">Raw conf</span>{data.raw_confidence?.toFixed(0)}</div>
        <div><span className="text-muted-foreground block">Calibrated P(win)</span>{(data.calibrated_probability * 100).toFixed(0)}% <span className="text-muted-foreground">({data.calibrator_version})</span></div>
        <div><span className="text-muted-foreground block">Adaptive adj</span><span className={adj > 0 ? "text-emerald-400" : adj < 0 ? "text-red-400" : ""}>{adj > 0 ? "+" : ""}{adj}</span></div>
        <div><span className="text-muted-foreground block">Final conf</span>{data.final_confidence?.toFixed(0)}</div>
        <div><span className="text-muted-foreground block">Model</span>{data.model_version}</div>
      </div>
      <p className="text-[10px] text-muted-foreground font-mono leading-relaxed">{data.explanation}</p>
    </div>
  );
}

// ── Phase 15 structured explanation ────────────────────────────────────────────

function Phase15Explanation({ symbol }: { symbol: string }) {
  const { data, isLoading } = useQuery({
    queryKey: ["/api/phase15/explain", symbol],
    queryFn: () => apiJson<any>(`/phase15/explain/${symbol}`),
    staleTime: 5 * 60_000,
  });
  if (isLoading) {
    return <div className="text-[10px] font-mono text-muted-foreground/60">Loading Phase 15 explanation…</div>;
  }
  if (!data?.available) return null;
  return (
    <div className="rounded-lg border border-sky-500/20 bg-sky-500/5 p-3 space-y-2" data-testid={`phase15-explain-${symbol}`}>
      <div className="flex items-center gap-1.5 flex-wrap text-xs font-mono text-sky-300 uppercase tracking-wider">
        <Brain className="h-3.5 w-3.5" /> Why this decision? (Phase 15 · canonical scan {data.scan_id})
        {data.stale && (
          <span className="flex items-center gap-1 text-amber-400 normal-case">
            <AlertTriangle className="h-3 w-3" /> stale scan — BUY disabled
          </span>
        )}
      </div>
      <p className="text-xs text-foreground/85 font-mono leading-relaxed">{data.headline}</p>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-1">
        {(data.factors ?? []).map((f: any) => (
          <div key={f.factor} className="flex items-start gap-1.5 text-[11px]">
            {f.favourable
              ? <CheckCircle2 className="h-3 w-3 text-emerald-500 shrink-0 mt-0.5" />
              : <XCircle className="h-3 w-3 text-red-500 shrink-0 mt-0.5" />}
            <span className="text-foreground/70">
              <span className="text-muted-foreground font-mono">{String(f.factor).replace(/_/g, " ")}: </span>
              {f.assessment}
            </span>
          </div>
        ))}
      </div>
      <div className="text-[10px] font-mono text-muted-foreground">
        Decision: {data.final_decision}
        {data.effective_decision !== data.final_decision && ` → effective ${data.effective_decision}`}
        {" · "}{data.favourable_count} favourable / {data.unfavourable_count} unfavourable · research only
      </div>
    </div>
  );
}

// ── Rules sidebar ──────────────────────────────────────────────────────────────

function RulesCard() {
  return (
    <div className="rounded-lg border border-border bg-card p-4">
      <div className="text-xs font-mono text-primary/70 uppercase tracking-widest mb-3">Intelligence Engine Rules</div>
      <div className="grid grid-cols-2 md:grid-cols-3 gap-2">
        {[
          { icon: ShieldX, label: "RR < 2:1 → WATCH",             color: "text-red-400"    },
          { icon: ShieldX, label: "MTF < 3/4 → WATCH",            color: "text-red-400"    },
          { icon: ShieldX, label: "High vol + conf<70 → WATCH",   color: "text-orange-400" },
          { icon: ShieldX, label: "Sideways + conf<72 → WATCH",   color: "text-orange-400" },
          { icon: ShieldX, label: "Stop <0.5% → WATCH",           color: "text-orange-400" },
          { icon: ShieldX, label: "No capital → NO TRADE",         color: "text-red-500"    },
        ].map(({ icon: Icon, label, color }) => (
          <div key={label} className={`flex items-center gap-1.5 text-xs ${color}`}>
            <Icon className="h-3 w-3 shrink-0" />
            <span className="font-mono">{label}</span>
          </div>
        ))}
        {[
          { label: "TQ ≥ 75 → Quality setup", color: "text-emerald-400" },
          { label: "OppScore ≥ 85 → HOT BUY", color: "text-orange-300"  },
          { label: "1% max risk per trade",    color: "text-blue-400"    },
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

// ── Phase 13 regime banner ─────────────────────────────────────────────────────

const REGIME_P13_STYLE: Record<string, string> = {
  TRENDING_UP:   "text-emerald-400 bg-emerald-500/8 border-emerald-500/25",
  RANGE_BOUND:   "text-blue-400 bg-blue-500/8 border-blue-500/25",
  TRENDING_DOWN: "text-orange-400 bg-orange-500/8 border-orange-500/25",
  VOLATILE:      "text-yellow-400 bg-yellow-500/8 border-yellow-500/25",
  CRISIS:        "text-red-400 bg-red-500/8 border-red-500/25",
};

function Phase13RegimeBanner() {
  const { data } = useQuery({
    queryKey: ["/api/phase13/regime"],
    queryFn: () => apiJson<any>("/phase13/regime"),
    staleTime: 120_000,
  });
  if (!data?.regime) return null;
  const style = REGIME_P13_STYLE[data.regime] ?? REGIME_P13_STYLE.RANGE_BOUND;
  return (
    <div className={`flex items-center justify-between flex-wrap gap-2 rounded border px-3 py-2 text-xs font-mono ${style}`}>
      <div className="flex items-center gap-3">
        <span className="font-bold">P13 Regime: {data.regime.replace("_", " ")}</span>
        <span className="text-muted-foreground">conf={data.confidence?.toFixed(0)} · bars={data.regime_duration_bars}</span>
        <span>Eligible strategies: <span className="text-foreground">{data.eligible_strategies?.join(", ") || "none"}</span></span>
        {data.regime_changed && <span className="text-yellow-400">↗ REGIME CHANGE from {data.prev_regime?.replace("_", " ")}</span>}
      </div>
      <a href="/phase13" className="underline text-muted-foreground hover:text-foreground transition-colors">Full P13 Intel →</a>
    </div>
  );
}

// ── Main page ──────────────────────────────────────────────────────────────────

export default function AiDecisionPage() {
  const { data: opportunities = [], isLoading, refetch } = useGetOpportunityScan();
  const { data: aiDecisions = [] } = useGetAiDecisions();
  const runScan = useRunScan();
  const [expandedRow, setExpandedRow] = useState<string | null>(null);

  const handleScan = () => {
    runScan.mutate(undefined, { onSuccess: () => refetch() });
  };

  // Build quick lookup: stock → AiDecision
  const aiDecMap: Record<string, AiDecision> = {};
  for (const d of aiDecisions) aiDecMap[d.stock] = d;

  const hotBuy = opportunities.filter((o) => o.status === "HOT_BUY");
  const buy    = opportunities.filter((o) => o.status === "BUY");
  const watch  = opportunities.filter((o) => o.status === "WATCH");
  const ignore = opportunities.filter((o) => o.status === "IGNORE");

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight flex items-center gap-2">
            <Brain className="h-6 w-6 text-primary" />
            Intelligence Layer
          </h1>
          <p className="text-sm text-muted-foreground mt-1">
            Opportunity Scanner · Trade Quality · Position Sizing · Explainability
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

      {/* Phase 13 regime banner */}
      <Phase13RegimeBanner />

      {/* Rules reference */}
      <RulesCard />

      {/* Summary pills */}
      {opportunities.length > 0 && (
        <div className="flex gap-3 flex-wrap">
          {hotBuy.length > 0 && (
            <div className="flex items-center gap-2 px-3 py-1.5 rounded-full bg-orange-500/10 border border-orange-500/30 text-orange-300 text-xs font-mono">
              <Flame className="h-3.5 w-3.5" /> {hotBuy.length} Hot Buy
            </div>
          )}
          <div className="flex items-center gap-2 px-3 py-1.5 rounded-full bg-emerald-500/10 border border-emerald-500/20 text-emerald-400 text-xs font-mono">
            <TrendingUp className="h-3.5 w-3.5" /> {buy.length} Buy
          </div>
          <div className="flex items-center gap-2 px-3 py-1.5 rounded-full bg-yellow-500/10 border border-yellow-500/20 text-yellow-400 text-xs font-mono">
            <Eye className="h-3.5 w-3.5" /> {watch.length} Watch
          </div>
          <div className="flex items-center gap-2 px-3 py-1.5 rounded-full bg-zinc-800 border border-zinc-700 text-zinc-500 text-xs font-mono">
            <MinusCircle className="h-3.5 w-3.5" /> {ignore.length} Ignore
          </div>
        </div>
      )}

      {/* Table */}
      <div className="rounded-lg border border-border bg-card overflow-hidden">
        {/* Header */}
        <div className="hidden md:grid grid-cols-[40px_1fr_1fr_1fr_1fr_80px_80px_60px_32px] gap-3 px-4 py-2.5 border-b border-border bg-muted/30">
          {["#", "STOCK", "STATUS", "OPP SCORE", "TRADE QUALITY", "AI DEC", "RR", "QTY", ""].map((h) => (
            <div key={h} className="text-xs font-mono text-muted-foreground uppercase tracking-wider">{h}</div>
          ))}
        </div>

        {isLoading ? (
          <div className="py-16 text-center text-muted-foreground text-sm font-mono">
            Loading intelligence scan…
          </div>
        ) : opportunities.length === 0 ? (
          <div className="py-16 text-center space-y-2">
            <BarChart2 className="h-10 w-10 text-muted-foreground/30 mx-auto" />
            <p className="text-muted-foreground text-sm font-mono">No scan results yet</p>
            <p className="text-xs text-muted-foreground/60">Run a scan to rank all watchlist opportunities</p>
          </div>
        ) : (
          <div>
            {opportunities.map((item) => {
              const isExpanded = expandedRow === item.stock;
              const sm = STATUS_META[item.status] ?? STATUS_META.IGNORE;

              return (
                <div key={item.stock} className="border-b border-border/50 last:border-0">
                  <button
                    className={`w-full text-left hover:bg-muted/20 transition-colors ${sm.bg}`}
                    onClick={() => setExpandedRow(isExpanded ? null : item.stock)}
                    data-testid={`row-opp-${item.stock}`}
                  >
                    <div className="grid grid-cols-2 md:grid-cols-[40px_1fr_1fr_1fr_1fr_80px_80px_60px_32px] gap-3 px-4 py-3 items-center">
                      {/* Rank */}
                      <div className="hidden md:block font-mono text-xs text-muted-foreground/60 text-center">
                        {item.rank}
                      </div>

                      {/* Stock */}
                      <div className="font-mono font-bold text-sm flex items-center gap-1.5">
                        {item.status === "HOT_BUY" && <Flame className="h-3.5 w-3.5 text-orange-400 shrink-0" />}
                        {item.stock}
                      </div>

                      {/* Status */}
                      <div>
                        <StatusBadge status={item.status} />
                      </div>

                      {/* Opportunity score */}
                      <div className="hidden md:block">
                        <OppScoreBar value={item.opportunity_score} />
                      </div>

                      {/* Trade Quality */}
                      <div className="hidden md:flex items-center gap-2">
                        <ScoreRing value={item.trade_quality} />
                        <GradeBadge grade={item.tq_grade} />
                      </div>

                      {/* AI Decision */}
                      <div className="hidden md:block">
                        <DecisionChip decision={item.ai_decision} />
                      </div>

                      {/* RR */}
                      <div className="hidden md:block font-mono text-xs text-foreground/70">
                        1:{item.rr_ratio.toFixed(1)}
                      </div>

                      {/* Qty */}
                      <div className="hidden md:flex items-center gap-1">
                        {item.feasible ? (
                          <span className="font-mono text-xs text-foreground/80">{item.suggested_qty} sh</span>
                        ) : (
                          <span className="font-mono text-xs text-zinc-600">—</span>
                        )}
                      </div>

                      {/* Expand */}
                      <div className="hidden md:flex justify-end text-muted-foreground">
                        {isExpanded ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
                      </div>
                    </div>
                  </button>

                  {/* Expanded panel */}
                  {isExpanded && (
                    <div className="px-4 pb-4">
                      <OpportunityDetail item={item} aiDec={aiDecMap[item.stock]} />
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
