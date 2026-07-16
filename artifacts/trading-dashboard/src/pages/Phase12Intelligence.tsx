import { useState } from "react";
import { useQuery, useMutation } from "@tanstack/react-query";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import {
  Brain, TrendingUp, TrendingDown, Minus, Activity, AlertTriangle,
  Layers, BarChart3, RefreshCcw, Download, ChevronDown, ChevronRight,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { apiJson, API_BASE } from "@/lib/api";
import DataFreshnessBar from "@/components/DataFreshnessBar";

// ── Regime helpers ─────────────────────────────────────────────────────────────
const REGIME_META: Record<string, { color: string; bg: string; icon: React.ReactNode }> = {
  TRENDING_UP:   { color: "text-emerald-400", bg: "bg-emerald-500/10 border-emerald-500/30", icon: <TrendingUp className="h-4 w-4" /> },
  TRENDING_DOWN: { color: "text-red-400",     bg: "bg-red-500/10 border-red-500/30",         icon: <TrendingDown className="h-4 w-4" /> },
  VOLATILE:      { color: "text-amber-400",   bg: "bg-amber-500/10 border-amber-500/30",     icon: <Activity className="h-4 w-4" /> },
  RANGE_BOUND:   { color: "text-sky-400",     bg: "bg-sky-500/10 border-sky-500/30",         icon: <Minus className="h-4 w-4" /> },
  CRISIS:        { color: "text-red-600",     bg: "bg-red-900/20 border-red-600/40",         icon: <AlertTriangle className="h-4 w-4" /> },
};

const ACTION_META: Record<string, { color: string; bg: string; label: string }> = {
  STRONG_BUY: { color: "text-emerald-300", bg: "bg-emerald-500/15 border-emerald-500/40", label: "STRONG BUY" },
  BUY:        { color: "text-green-400",   bg: "bg-green-500/10 border-green-500/30",     label: "BUY"        },
  WATCH:      { color: "text-yellow-400",  bg: "bg-yellow-500/10 border-yellow-500/30",   label: "WATCH"      },
  AVOID:      { color: "text-zinc-500",    bg: "bg-zinc-800/40 border-zinc-700",           label: "AVOID"      },
};

const CONTRADICTION_COLOR: Record<string, string> = {
  NONE: "text-emerald-400", LOW: "text-yellow-400", MEDIUM: "text-amber-400", HIGH: "text-red-400",
};

const MOMENTUM_COLOR: Record<string, string> = {
  STRONG: "text-emerald-400", OUTPERFORMING: "text-green-400", NEUTRAL: "text-zinc-400",
  UNDERPERFORMING: "text-amber-400", WEAK: "text-red-400",
};

function RegimeBadge({ regime }: { regime: string }) {
  const m = REGIME_META[regime] ?? REGIME_META.RANGE_BOUND;
  return (
    <span className={cn("inline-flex items-center gap-1.5 px-3 py-1 rounded-full border text-sm font-bold font-mono", m.color, m.bg)}>
      {m.icon}{regime.replace("_", " ")}
    </span>
  );
}

function ActionBadge({ action }: { action: string }) {
  const m = ACTION_META[action] ?? ACTION_META.WATCH;
  return (
    <span className={cn("inline-flex px-2 py-0.5 rounded border text-xs font-bold font-mono", m.color, m.bg)}>
      {m.label}
    </span>
  );
}

function FactorBar({ name, score, weight, rationale }: { name: string; score: number; weight: number; rationale?: string }) {
  const color = score >= 65 ? "bg-emerald-500" : score >= 45 ? "bg-sky-500" : "bg-red-500";
  return (
    <div className="space-y-0.5">
      <div className="flex items-center justify-between">
        <span className="text-xs font-mono text-zinc-400 capitalize">{name.replace(/_/g, " ")}</span>
        <span className="text-xs font-mono font-bold text-zinc-300">{score.toFixed(0)}</span>
      </div>
      <div className="h-1.5 rounded-full bg-zinc-800 overflow-hidden">
        <div className={cn("h-full rounded-full transition-all", color)} style={{ width: `${score}%` }} />
      </div>
      {rationale && <div className="text-[9px] text-zinc-600 truncate">{rationale} · wt {(weight * 100).toFixed(0)}%</div>}
    </div>
  );
}

function ScoreRing({ score, size = 64 }: { score: number; size?: number }) {
  const r = (size - 8) / 2;
  const circ = 2 * Math.PI * r;
  const fill = (score / 100) * circ;
  const color = score >= 70 ? "#34d399" : score >= 50 ? "#38bdf8" : "#f87171";
  return (
    <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} className="rotate-[-90deg]">
      <circle cx={size/2} cy={size/2} r={r} fill="none" stroke="#27272a" strokeWidth={6} />
      <circle cx={size/2} cy={size/2} r={r} fill="none" stroke={color} strokeWidth={6}
        strokeDasharray={`${fill} ${circ - fill}`} strokeLinecap="round" />
      <text x={size/2} y={size/2} dominantBaseline="middle" textAnchor="middle"
        className="fill-white font-bold text-sm rotate-90"
        style={{ transform: `rotate(90deg) translate(0px, -${size}px)`, fontSize: 13, fontFamily: "monospace" }}>
        {score.toFixed(0)}
      </text>
    </svg>
  );
}

function SymbolCard({ r, expanded, toggle }: { r: any; expanded: boolean; toggle: () => void }) {
  const cont = r.contradiction ?? {};
  const sz = r.sizing ?? {};
  const rs = r.relative_strength ?? {};
  const factors = r.factor_scores ?? {};
  const rationales = r.factor_rationales ?? {};
  const expl = r.explanation ?? {};

  return (
    <Card className={cn("border-zinc-800/60 bg-zinc-900/40",
      r.p12_action === "STRONG_BUY" && "border-emerald-700/50",
      r.p12_action === "AVOID" && "border-zinc-700/30 opacity-70")}>
      <CardContent className="p-3">
        {/* Header row */}
        <div className="flex items-center justify-between gap-2 flex-wrap">
          <div className="flex items-center gap-2">
            <button onClick={toggle} className="text-zinc-500 hover:text-zinc-300">
              {expanded ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}
            </button>
            <span className="font-mono font-bold text-zinc-100">{r.symbol}</span>
            {r.sector && <span className="text-[10px] text-zinc-500 border border-zinc-700 rounded px-1">{r.sector}</span>}
          </div>
          <div className="flex items-center gap-2">
            <ActionBadge action={r.p12_action} />
            <ScoreRing score={r.fused_score ?? 50} size={42} />
          </div>
        </div>

        {/* Blocker */}
        {r.blocker && (
          <div className="mt-2 flex items-start gap-1.5 rounded bg-amber-900/20 border border-amber-700/30 p-2">
            <AlertTriangle className="h-3 w-3 text-amber-400 mt-0.5 shrink-0" />
            <span className="text-[10px] text-amber-300">{r.blocker}</span>
          </div>
        )}

        {/* Quick stats */}
        <div className="mt-2 grid grid-cols-3 gap-2 text-center">
          <div>
            <div className="text-[9px] text-zinc-500 uppercase tracking-wider">Contradiction</div>
            <div className={cn("text-xs font-bold font-mono", CONTRADICTION_COLOR[cont.level ?? "NONE"])}>{cont.level ?? "—"}</div>
          </div>
          <div>
            <div className="text-[9px] text-zinc-500 uppercase tracking-wider">RS vs NIFTY</div>
            <div className={cn("text-xs font-bold font-mono", (rs.rs_vs_index ?? 0) >= 0 ? "text-emerald-400" : "text-red-400")}>
              {rs.rs_vs_index != null ? `${rs.rs_vs_index > 0 ? "+" : ""}${rs.rs_vs_index.toFixed(1)}%` : "—"}
            </div>
          </div>
          <div>
            <div className="text-[9px] text-zinc-500 uppercase tracking-wider">Sizing</div>
            <div className="text-xs font-bold font-mono text-zinc-300">
              {sz.feasible ? `${sz.suggested_quantity} sh` : "N/A"}
            </div>
          </div>
        </div>

        {expanded && (
          <div className="mt-3 space-y-3 border-t border-zinc-800 pt-3">
            {/* Factor bars */}
            <div>
              <div className="text-[10px] uppercase tracking-wider text-zinc-500 mb-2">Factor Scores</div>
              <div className="grid grid-cols-1 gap-1.5 sm:grid-cols-2">
                {Object.entries(factors).map(([f, s]) => (
                  <FactorBar key={f} name={f} score={s as number} weight={(r.explanation?.factor_contributions ?? []).find((c: any) => c.factor === f)?.weight ?? 0} rationale={rationales[f]} />
                ))}
              </div>
            </div>

            {/* Contradiction detail */}
            {cont.level && cont.level !== "NONE" && (
              <div className={cn("rounded p-2 text-[10px]", CONTRADICTION_COLOR[cont.level ?? "NONE"])}>
                <div className="font-bold mb-0.5">⚡ Contradiction: {cont.level}</div>
                <div className="text-zinc-400">{cont.explanation}</div>
              </div>
            )}

            {/* Sizing detail */}
            <div className="rounded bg-zinc-800/50 p-2 text-[10px] text-zinc-400">
              <span className="text-zinc-300 font-bold">Position Sizing: </span>{sz.sizing_note ?? "N/A"}
            </div>

            {/* What would change */}
            {expl.what_would_change && (
              <div className="rounded bg-sky-900/20 border border-sky-800/30 p-2 text-[10px] text-sky-300">
                <span className="font-bold">What would change: </span>{expl.what_would_change}
              </div>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function Phase12Intelligence() {
  const [expandedSymbols, setExpandedSymbols] = useState<Set<string>>(new Set());
  const [actionFilter, setActionFilter] = useState<string>("ALL");

  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ["phase12-analysis"],
    queryFn: () => apiJson("/phase12/analysis"),
    staleTime: 60_000,
    retry: 1,
  });

  const bundleMutation = useMutation({
    mutationFn: () => apiJson("/phase12/bundle", { method: "POST" }),
  });

  const regime = data?.regime ?? {};
  const sectorRotation: any[] = data?.sector_rotation ?? [];
  const fused: any[] = data?.fused_results ?? [];
  const actionSummary = data?.action_summary ?? {};
  const contradict = data?.contradiction_summary ?? {};

  const filtered = actionFilter === "ALL" ? fused : fused.filter(r => r.p12_action === actionFilter);

  const toggle = (sym: string) => setExpandedSymbols(prev => {
    const n = new Set(prev);
    n.has(sym) ? n.delete(sym) : n.add(sym);
    return n;
  });

  return (
    <div className="min-h-screen bg-background p-4 space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between flex-wrap gap-2">
        <div>
          <h1 className="text-xl font-bold font-mono flex items-center gap-2">
            <Brain className="h-5 w-5 text-primary" />
            Phase 12 Intelligence
          </h1>
          <p className="text-xs text-zinc-500 mt-0.5">
            Multi-factor institutional-grade analysis · {data?.engine_version ?? "Research Engine v1.0 · Phase 12"} ·{" "}
            <span className="text-amber-500">PAPER / RESEARCH ONLY</span>
          </p>
        </div>
        <div className="flex gap-2">
          <Button size="sm" variant="outline" onClick={() => refetch()} disabled={isLoading}>
            <RefreshCcw className="h-3.5 w-3.5 mr-1" />Refresh
          </Button>
          <Button size="sm" variant="outline" asChild>
            <a href={`${API_BASE}/phase12/bundle/download?file=json`} download>
              <Download className="h-3.5 w-3.5 mr-1" />JSON
            </a>
          </Button>
          <Button size="sm" variant="outline" asChild>
            <a href={`${API_BASE}/phase12/bundle/download?file=csv`} download>
              <Download className="h-3.5 w-3.5 mr-1" />CSV
            </a>
          </Button>
        </div>
      </div>

      <DataFreshnessBar variant="scan" />

      {error && (
        <div className="rounded border border-red-800/40 bg-red-900/20 p-3 text-sm text-red-300">
          {String(error)}
        </div>
      )}

      {/* Regime + summary strip */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Card className="border-zinc-800 bg-zinc-900/40">
          <CardContent className="p-3">
            <div className="text-[10px] uppercase tracking-wider text-zinc-500 mb-1.5">Market Regime</div>
            {regime.regime ? <RegimeBadge regime={regime.regime} /> : <span className="text-zinc-600 text-xs">Loading…</span>}
            {regime.reasoning && (
              <div className="text-[9px] text-zinc-600 mt-1 truncate">{regime.reasoning}</div>
            )}
          </CardContent>
        </Card>

        {(["STRONG_BUY", "BUY", "WATCH"] as const).map(action => (
          <Card key={action} className="border-zinc-800 bg-zinc-900/40">
            <CardContent className="p-3">
              <div className="text-[10px] uppercase tracking-wider text-zinc-500 mb-1">{action.replace("_", " ")}</div>
              <div className={cn("text-2xl font-bold font-mono", ACTION_META[action]?.color)}>
                {actionSummary[action] ?? 0}
              </div>
              <div className="text-[9px] text-zinc-600">of {fused.length} symbols</div>
            </CardContent>
          </Card>
        ))}
      </div>

      {/* Contradiction summary */}
      {Object.values(contradict).some(v => (v as number) > 0) && (
        <Card className="border-zinc-800 bg-zinc-900/40">
          <CardContent className="p-3">
            <div className="text-[10px] uppercase tracking-wider text-zinc-500 mb-2">Signal Contradictions</div>
            <div className="flex gap-4 flex-wrap">
              {Object.entries(contradict).map(([level, count]) => (
                <div key={level} className="text-center">
                  <div className={cn("text-lg font-bold font-mono", CONTRADICTION_COLOR[level])}>{count as number}</div>
                  <div className="text-[10px] text-zinc-500">{level}</div>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      {/* Sector rotation */}
      {sectorRotation.length > 0 && (
        <Card className="border-zinc-800 bg-zinc-900/40">
          <CardHeader className="px-4 pb-2 pt-3">
            <h2 className="flex items-center gap-2 text-sm font-bold font-mono uppercase tracking-wider text-zinc-300">
              <Layers className="h-4 w-4 text-primary" />Sector Rotation
            </h2>
          </CardHeader>
          <CardContent className="px-4 pb-3">
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead>
                  <tr className="border-b border-zinc-800 text-zinc-500">
                    {["Rank","Sector","Avg Score","Stocks","vs Median","Momentum"].map(h => (
                      <th key={h} className="py-1.5 pr-4 text-left font-medium text-[10px] uppercase tracking-wider">{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {sectorRotation.map((row: any) => (
                    <tr key={row.sector} className="border-b border-zinc-800/50 hover:bg-zinc-800/20">
                      <td className="py-1.5 pr-4 font-mono text-zinc-500">{row.rank ?? "—"}</td>
                      <td className="py-1.5 pr-4 font-bold text-zinc-200">{row.sector}</td>
                      <td className="py-1.5 pr-4 font-mono">{row.avg_score?.toFixed(1) ?? "—"}</td>
                      <td className="py-1.5 pr-4 font-mono text-zinc-400">{row.stock_count}</td>
                      <td className={cn("py-1.5 pr-4 font-mono",
                        (row.vs_median ?? 0) >= 0 ? "text-emerald-400" : "text-red-400")}>
                        {row.vs_median != null ? `${row.vs_median > 0 ? "+" : ""}${row.vs_median.toFixed(1)}` : "—"}
                      </td>
                      <td className={cn("py-1.5 pr-4 font-bold", MOMENTUM_COLOR[row.momentum ?? "NEUTRAL"])}>
                        {row.momentum ?? "—"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Symbol results */}
      <Card className="border-zinc-800 bg-zinc-900/40">
        <CardHeader className="px-4 pb-2 pt-3">
          <div className="flex items-center justify-between flex-wrap gap-2">
            <h2 className="flex items-center gap-2 text-sm font-bold font-mono uppercase tracking-wider text-zinc-300">
              <BarChart3 className="h-4 w-4 text-primary" />Symbol Analysis
            </h2>
            <div className="flex gap-1">
              {["ALL","STRONG_BUY","BUY","WATCH","AVOID"].map(f => (
                <button key={f} onClick={() => setActionFilter(f)}
                  className={cn("px-2 py-0.5 text-[10px] font-mono rounded border",
                    actionFilter === f
                      ? "border-primary text-primary bg-primary/10"
                      : "border-zinc-700 text-zinc-500 hover:border-zinc-500")}>
                  {f.replace("_", " ")}
                </button>
              ))}
            </div>
          </div>
        </CardHeader>
        <CardContent className="px-4 pb-4">
          {isLoading && (
            <div className="text-sm text-zinc-500 text-center py-8">Loading Phase 12 intelligence…</div>
          )}
          {!isLoading && filtered.length === 0 && (
            <div className="text-sm text-zinc-500 text-center py-8">
              {fused.length === 0
                ? "No scan data available. Run a market scan first."
                : `No symbols match filter "${actionFilter}".`}
            </div>
          )}
          <div className="space-y-2">
            {filtered.map((r: any) => (
              <SymbolCard key={r.symbol} r={r}
                expanded={expandedSymbols.has(r.symbol)}
                toggle={() => toggle(r.symbol)} />
            ))}
          </div>
        </CardContent>
      </Card>

      {/* Factor weights legend */}
      <Card className="border-zinc-800/40 bg-zinc-900/20">
        <CardContent className="p-3">
          <div className="text-[10px] uppercase tracking-wider text-zinc-600 mb-2">Factor Weight Legend</div>
          <div className="flex flex-wrap gap-2">
            {data?.factor_weights && Object.entries(data.factor_weights).map(([f, w]) => (
              <span key={f} className="text-[9px] font-mono text-zinc-500 border border-zinc-800 rounded px-1.5 py-0.5">
                {f.replace(/_/g, " ")} {((w as number) * 100).toFixed(0)}%
              </span>
            ))}
          </div>
          <div className="mt-2 text-[9px] text-zinc-600">
            Scan source: {data?.scan_source ?? "N/A"} · Generated: {data?.generated_at ?? "—"} ·{" "}
            {data?.completed_trade_count ?? 0} completed trades used for learning
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
