/**
 * StrategyEvolution.tsx — Phase 6 Strategy Evolution Laboratory page.
 *
 * Research only. Generates, compares and ranks strategy variations using data
 * already produced by the Research Factory. Nothing here modifies live trading,
 * paper trading, trade decisions, the scanner or the portfolio. All variants
 * are research candidates requiring explicit human approval.
 */
import { useState, useEffect, useCallback } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  Loader2, GitBranch, FlaskConical, Dna, Trophy, BookOpen, History,
  ShieldAlert, RefreshCw, ChevronDown, ChevronRight, Download, GitCompare,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { apiJson, API_BASE } from "@/lib/api";
import { useToast } from "@/hooks/use-toast";
import DataFreshnessBar from "@/components/DataFreshnessBar";

/* eslint-disable @typescript-eslint/no-explicit-any */

const DISCLAIMER =
  "Research only — the Strategy Evolution Laboratory produces research candidates from " +
  "historical out-of-sample results. Nothing here changes live or paper trading, and no " +
  "strategy is ever promoted automatically. Human approval is required for any future use.";

function na(v: any, suffix = ""): string {
  if (v === null || v === undefined || v === "") return "N/A";
  if (typeof v === "number" && (!isFinite(v) || isNaN(v))) return "N/A";
  if (typeof v === "number") return `${+v.toFixed(2)}${suffix}`;
  return String(v);
}

const STATUS_CLS: Record<string, string> = {
  Draft: "text-zinc-300 border-zinc-600 bg-zinc-500/10",
  Research: "text-sky-400 border-sky-600 bg-sky-500/10",
  Candidate: "text-emerald-400 border-emerald-600 bg-emerald-500/10",
  Archived: "text-amber-400 border-amber-600 bg-amber-500/10",
  Rejected: "text-red-400 border-red-600 bg-red-500/10",
};

function StatusPill({ s }: { s?: string }) {
  return (
    <Badge variant="outline" className={cn("text-[9px] font-mono px-1.5", STATUS_CLS[s ?? ""] ?? "text-zinc-400 border-zinc-600")}>
      {s ?? "N/A"}
    </Badge>
  );
}

function EvidencePill({ e }: { e?: string }) {
  const cls: Record<string, string> = {
    STRONG: "text-emerald-400 border-emerald-700",
    MODERATE: "text-sky-400 border-sky-700",
    WEAK: "text-amber-400 border-amber-700",
    INSUFFICIENT: "text-red-400 border-red-700",
  };
  if (!e) return <span className="text-zinc-500">N/A</span>;
  return <Badge variant="outline" className={cn("text-[9px] font-mono px-1", cls[e] ?? "text-zinc-400 border-zinc-600")}>{e}</Badge>;
}

// ── Family tree node ─────────────────────────────────────────────────────────
function TreeNode({ node, depth }: { node: any; depth: number }) {
  const [open, setOpen] = useState(depth === 0);
  const kids = node.children ?? [];
  return (
    <div className={cn(depth > 0 && "ml-5 border-l border-zinc-700 pl-3")}>
      <div className="flex items-center gap-2 py-1.5">
        {kids.length > 0 ? (
          <button onClick={() => setOpen(o => !o)} className="text-zinc-400 hover:text-zinc-200">
            {open ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}
          </button>
        ) : <span className="w-3.5" />}
        <span className="font-mono text-xs text-zinc-200">{node.name}</span>
        <span className="font-mono text-[10px] text-zinc-500">v{node.version}</span>
        <StatusPill s={node.status} />
        {node.performance && (
          <span className="font-mono text-[10px] text-zinc-500">
            PF {na(node.performance.profit_factor)} · {na(node.performance.trades)} trades · <EvidencePill e={node.performance.evidence} />
          </span>
        )}
      </div>
      {node.mutation && open && (
        <p className="ml-6 font-mono text-[10px] text-zinc-500 pb-1">
          {node.change_summary} — {node.mutation.expected_benefit}
        </p>
      )}
      {open && kids.map((c: any) => <TreeNode key={c.strategy_id} node={c} depth={depth + 1} />)}
    </div>
  );
}

export default function StrategyEvolution() {
  const { toast } = useToast();
  const [loading, setLoading] = useState(true);
  const [registry, setRegistry] = useState<any>(null);
  const [tree, setTree] = useState<any>(null);
  const [leaderboard, setLeaderboard] = useState<any>(null);
  const [knowledge, setKnowledge] = useState<any>(null);
  const [abTests, setAbTests] = useState<any[]>([]);
  const [mutating, setMutating] = useState<string | null>(null);
  const [exporting, setExporting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [reg, tr, lb, kb, ab] = await Promise.all([
        apiJson("/evolution/registry"),
        apiJson("/evolution/tree"),
        apiJson("/evolution/leaderboard"),
        apiJson("/evolution/knowledge"),
        apiJson("/evolution/ab-tests"),
      ]);
      setRegistry(reg);
      setTree(tr);
      setLeaderboard(lb);
      setKnowledge(kb);
      setAbTests(ab?.ab_tests ?? []);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  async function mutate(strategyId: string) {
    setMutating(strategyId);
    try {
      const r = await apiJson("/evolution/mutate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ strategyId }),
      });
      if (r?.success) {
        toast({ title: `Generated ${r.created} draft variants`, description: "Research candidates only — nothing was activated." });
        await load();
      } else {
        toast({ title: "Mutation failed", description: String(r?.error ?? "Unknown error"), variant: "destructive" });
      }
    } catch (e) {
      toast({ title: "Mutation failed", description: String(e instanceof Error ? e.message : e), variant: "destructive" });
    } finally {
      setMutating(null);
    }
  }

  async function downloadExport(kind: "csv" | "json" | "html") {
    setExporting(true);
    try {
      const resp = await fetch(`${API_BASE}/evolution/export?file=${kind}`);
      const ctype = resp.headers.get("Content-Type") ?? "";
      if (!resp.ok || ctype.includes("application/json") && kind !== "json" && !resp.ok) {
        throw new Error(`Export failed (HTTP ${resp.status})`);
      }
      if (!resp.ok) throw new Error(`Export failed (HTTP ${resp.status})`);
      const blob = await resp.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = kind === "csv" ? "phase6_evolution_export.csv"
        : kind === "json" ? "phase6_evolution_export.json" : "phase6_evolution_report.html";
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
      toast({ title: `Evolution ${kind.toUpperCase()} downloaded`, description: "Research package export. Research only." });
    } catch (e) {
      toast({ title: "Export failed", description: String(e instanceof Error ? e.message : e), variant: "destructive" });
    } finally {
      setExporting(false);
    }
  }

  const strategies: any[] = registry?.strategies ?? [];
  const roots = strategies.filter(s => !s.parent_id);
  const variants: any[] = leaderboard?.variants ?? [];
  const highlights = leaderboard?.highlights ?? {};
  const counts = registry?.status_counts ?? {};

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64 gap-2 text-zinc-400 font-mono text-sm">
        <Loader2 className="h-4 w-4 animate-spin" /> Loading Strategy Evolution Laboratory…
      </div>
    );
  }

  return (
    <div className="space-y-4 p-4 max-w-6xl mx-auto">
      <div className="flex items-start justify-between gap-3 flex-wrap">
        <div>
          <h1 className="text-lg font-semibold text-zinc-100 flex items-center gap-2">
            <Dna className="h-5 w-5 text-violet-400" /> Strategy Evolution
          </h1>
          <p className="text-xs font-mono text-zinc-500 mt-1 max-w-3xl flex items-start gap-1.5">
            <ShieldAlert className="h-3.5 w-3.5 mt-0.5 shrink-0 text-amber-500" /> {DISCLAIMER}
          </p>
        </div>
        <div className="flex gap-1.5">
          <Button size="sm" variant="outline" className="font-mono text-xs h-8 gap-1.5" onClick={() => void load()}>
            <RefreshCw className="h-3.5 w-3.5" /> Refresh
          </Button>
          {(["csv", "json", "html"] as const).map(k => (
            <Button key={k} size="sm" variant="outline" className="font-mono text-xs h-8 gap-1.5"
              disabled={exporting} onClick={() => void downloadExport(k)}>
              <Download className="h-3.5 w-3.5" /> {k.toUpperCase()}
            </Button>
          ))}
        </div>
      </div>

      <DataFreshnessBar variant="scan" />

      {error && (
        <div className="border border-red-800 bg-red-950/40 rounded p-3 font-mono text-xs text-red-300">
          Failed to load: {error}
        </div>
      )}

      <div className="flex gap-2 flex-wrap">
        {["Draft", "Research", "Candidate", "Archived", "Rejected"].map(s => (
          <div key={s} className="border border-zinc-700 rounded px-3 py-1.5 font-mono text-xs text-zinc-300 flex items-center gap-2">
            <StatusPill s={s} /> {counts[s] ?? 0}
          </div>
        ))}
      </div>

      <Tabs defaultValue="tree">
        <TabsList className="font-mono text-xs flex-wrap h-auto">
          <TabsTrigger value="tree" className="gap-1.5"><GitBranch className="h-3.5 w-3.5" />Family Tree</TabsTrigger>
          <TabsTrigger value="mutate" className="gap-1.5"><FlaskConical className="h-3.5 w-3.5" />Mutation Lab</TabsTrigger>
          <TabsTrigger value="leaderboard" className="gap-1.5"><Trophy className="h-3.5 w-3.5" />Leaderboard</TabsTrigger>
          <TabsTrigger value="ab" className="gap-1.5"><GitCompare className="h-3.5 w-3.5" />A/B Tests</TabsTrigger>
          <TabsTrigger value="knowledge" className="gap-1.5"><BookOpen className="h-3.5 w-3.5" />Knowledge Base</TabsTrigger>
          <TabsTrigger value="timeline" className="gap-1.5"><History className="h-3.5 w-3.5" />Timeline</TabsTrigger>
        </TabsList>

        {/* Family tree */}
        <TabsContent value="tree" className="space-y-2">
          <div className="border border-zinc-700 rounded p-3">
            {(tree?.tree ?? []).length === 0 ? (
              <p className="font-mono text-xs text-zinc-500">No strategies in the registry yet.</p>
            ) : (
              (tree?.tree ?? []).map((n: any) => <TreeNode key={n.strategy_id} node={n} depth={0} />)
            )}
          </div>
        </TabsContent>

        {/* Mutation lab */}
        <TabsContent value="mutate" className="space-y-3">
          <p className="font-mono text-[11px] text-zinc-500">
            Controlled mutation: exactly one major parameter changes per variant. Variants are created
            as Drafts in the research registry and are never activated automatically.
          </p>
          <div className="grid gap-2 md:grid-cols-2">
            {roots.map(s => (
              <div key={s.strategy_id} className="border border-zinc-700 rounded p-3 space-y-2">
                <div className="flex items-center justify-between gap-2">
                  <div>
                    <span className="font-mono text-sm text-zinc-100">{s.name}</span>
                    <span className="ml-2 font-mono text-[10px] text-zinc-500">v{s.version}</span>
                  </div>
                  <StatusPill s={s.status} />
                </div>
                <p className="font-mono text-[10px] text-zinc-500">{s.notes}</p>
                {s.current_performance ? (
                  <p className="font-mono text-[11px] text-zinc-400">
                    PF {na(s.current_performance.profit_factor)} · Win {na(s.current_performance.win_rate, "%")} ·
                    Exp ₹{na(s.current_performance.expectancy_rs)} · {na(s.current_performance.trades)} trades ·{" "}
                    <EvidencePill e={s.current_performance.evidence} />
                  </p>
                ) : (
                  <p className="font-mono text-[11px] text-zinc-500">No out-of-sample research data yet.</p>
                )}
                <div className="flex items-center gap-2">
                  <Badge variant="outline" className="text-[9px] font-mono text-zinc-400 border-zinc-600">
                    Verdict: {s.research_verdict ?? "N/A"}
                  </Badge>
                  <Badge variant="outline" className="text-[9px] font-mono text-zinc-400 border-zinc-600">
                    Evidence score {na(s.evidence_score)}/100
                  </Badge>
                </div>
                <Button size="sm" variant="outline" className="font-mono text-xs h-7 gap-1.5"
                  disabled={mutating !== null} onClick={() => void mutate(s.strategy_id)}>
                  {mutating === s.strategy_id
                    ? <Loader2 className="h-3.5 w-3.5 animate-spin" />
                    : <FlaskConical className="h-3.5 w-3.5" />}
                  Generate variants
                </Button>
              </div>
            ))}
          </div>
        </TabsContent>

        {/* Leaderboard */}
        <TabsContent value="leaderboard" className="space-y-3">
          <div className="grid gap-2 md:grid-cols-3">
            {[["Best Performing", highlights.best_performing, "highest profit factor"],
              ["Most Stable", highlights.most_stable, "highest share of positive walk-forward windows"],
              ["Highest Evidence", highlights.highest_evidence, "largest out-of-sample trade count"]].map(([label, v, sub]: any) => (
              <div key={label} className="border border-zinc-700 rounded p-3">
                <p className="font-mono text-[10px] uppercase text-zinc-500">{label}</p>
                {v ? (
                  <>
                    <p className="font-mono text-sm text-zinc-100 mt-1">{v.name}</p>
                    <p className="font-mono text-[10px] text-zinc-500">{v.change_summary}</p>
                    <p className="font-mono text-[11px] text-zinc-400 mt-1">
                      PF {na(v.profit_factor)} · Sharpe {na(v.sharpe)} · {na(v.trades)} trades
                    </p>
                  </>
                ) : (
                  <p className="font-mono text-xs text-zinc-500 mt-1">No tested variants yet — {sub} will appear here.</p>
                )}
              </div>
            ))}
          </div>
          <div className="border border-zinc-700 rounded overflow-x-auto">
            <table className="w-full font-mono text-xs">
              <thead>
                <tr className="text-zinc-500 text-[10px] uppercase border-b border-zinc-700">
                  {["Variant", "Change", "Status", "PF", "Sharpe", "Return %", "Max DD %", "Trades", "Evidence", "Windows +%", "Robustness"].map(h => (
                    <th key={h} className="text-left px-3 py-2">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {variants.length === 0 && (
                  <tr><td colSpan={11} className="px-3 py-4 text-zinc-500">No variants generated yet — use the Mutation Lab.</td></tr>
                )}
                {variants.map(v => (
                  <tr key={v.strategy_id} className="border-b border-zinc-800 text-zinc-300">
                    <td className="px-3 py-1.5">{v.name}</td>
                    <td className="px-3 py-1.5 text-zinc-500">{v.change_summary}</td>
                    <td className="px-3 py-1.5"><StatusPill s={v.status} /></td>
                    <td className="px-3 py-1.5">{na(v.profit_factor)}</td>
                    <td className="px-3 py-1.5">{na(v.sharpe)}</td>
                    <td className="px-3 py-1.5">{na(v.net_return_pct)}</td>
                    <td className="px-3 py-1.5">{na(v.max_drawdown_pct)}</td>
                    <td className="px-3 py-1.5">{na(v.trades)}</td>
                    <td className="px-3 py-1.5"><EvidencePill e={v.tested ? v.evidence : undefined} /></td>
                    <td className="px-3 py-1.5">{na(v.window_positive_pct)}</td>
                    <td className="px-3 py-1.5">{na(v.robustness_score)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="font-mono text-[10px] text-zinc-500">{leaderboard?.note}</p>
        </TabsContent>

        {/* A/B tests */}
        <TabsContent value="ab" className="space-y-2">
          {abTests.length === 0 && (
            <p className="font-mono text-xs text-zinc-500 border border-zinc-700 rounded p-3">
              No A/B tests recorded yet. A/B tests compare a parent and candidate over Research Factory
              experiments with identical settings.
            </p>
          )}
          {abTests.slice().reverse().map((t: any) => (
            <div key={t.id} className="border border-zinc-700 rounded p-3 space-y-2">
              <div className="flex items-center gap-2 flex-wrap">
                <span className="font-mono text-sm text-zinc-100">
                  {t.parent_strategy?.name} vs {t.candidate_strategy?.name}
                </span>
                <Badge variant="outline" className={cn("text-[9px] font-mono",
                  t.winner === "candidate" ? "text-emerald-400 border-emerald-700"
                    : t.winner === "parent" ? "text-sky-400 border-sky-700" : "text-zinc-400 border-zinc-600")}>
                  WINNER: {String(t.winner).toUpperCase()}
                </Badge>
                <Badge variant="outline" className="text-[9px] font-mono text-zinc-400 border-zinc-600">
                  {t.confidence} CONFIDENCE
                </Badge>
                {!t.controlled && (
                  <Badge variant="outline" className="text-[9px] font-mono text-amber-400 border-amber-700">
                    NOT FULLY CONTROLLED
                  </Badge>
                )}
              </div>
              <div className="overflow-x-auto">
                <table className="font-mono text-[11px]">
                  <thead><tr className="text-zinc-500 text-[10px] uppercase">
                    <th className="text-left pr-4 py-1">Metric</th><th className="text-left pr-4">Parent</th>
                    <th className="text-left pr-4">Candidate</th><th className="text-left">Better</th>
                  </tr></thead>
                  <tbody>
                    {(t.metric_checks ?? []).map((c: any) => (
                      <tr key={c.metric} className="text-zinc-300">
                        <td className="pr-4 py-0.5 text-zinc-500">{c.metric}</td>
                        <td className="pr-4">{na(c.parent)}</td>
                        <td className="pr-4">{na(c.candidate)}</td>
                        <td className={cn(c.winner === "candidate" ? "text-emerald-400" : c.winner === "parent" ? "text-sky-400" : "text-zinc-500")}>{c.winner}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <p className="font-mono text-[11px] text-zinc-400">
                Statistical difference: t = {na(t.statistical_difference?.welch_t)} ({t.statistical_difference?.interpretation})
                · Evidence Δ {na(t.evidence?.evidence_difference)} trades
              </p>
              <p className="font-mono text-[11px] text-zinc-300 border-l-2 border-violet-600 pl-2">{t.recommendation}</p>
            </div>
          ))}
        </TabsContent>

        {/* Knowledge base */}
        <TabsContent value="knowledge" className="space-y-2">
          {(knowledge?.lessons ?? []).length === 0 && (
            <p className="font-mono text-xs text-zinc-500 border border-zinc-700 rounded p-3">{knowledge?.note ?? "No lessons yet."}</p>
          )}
          {(knowledge?.lessons ?? []).map((l: any) => (
            <div key={l.strategy} className="border border-zinc-700 rounded p-3">
              <p className="font-mono text-sm text-zinc-100">{l.strategy} <span className="text-[10px] text-zinc-500">({l.total_trades} research trades)</span></p>
              <div className="grid md:grid-cols-2 gap-3 mt-2">
                {[["Works well", l.works_well, "text-emerald-400"], ["Fails", l.fails, "text-red-400"]].map(([label, items, color]: any) => (
                  <div key={label}>
                    <p className={cn("font-mono text-[10px] uppercase", color)}>{label}</p>
                    {(items ?? []).length === 0 && <p className="font-mono text-[11px] text-zinc-500">No contexts with enough evidence.</p>}
                    {(items ?? []).map((i: any) => (
                      <div key={i.context} className="font-mono text-[11px] text-zinc-300 py-0.5 flex items-center gap-2 flex-wrap">
                        <span>{i.context}</span>
                        <span className="text-zinc-500">₹{na(i.expectancy_rs)}/trade · {na(i.win_rate)}% win · {i.trades} trades</span>
                        <EvidencePill e={i.confidence} />
                      </div>
                    ))}
                  </div>
                ))}
              </div>
            </div>
          ))}
          <p className="font-mono text-[10px] text-zinc-500">{knowledge?.note}</p>
        </TabsContent>

        {/* Timeline */}
        <TabsContent value="timeline" className="space-y-1">
          {(tree?.timeline ?? []).length === 0 && <p className="font-mono text-xs text-zinc-500">No events yet.</p>}
          {(tree?.timeline ?? []).slice().reverse().map((ev: any, i: number) => (
            <div key={i} className="border border-zinc-800 rounded px-3 py-2 font-mono text-[11px] flex items-center gap-2 flex-wrap">
              <span className="text-zinc-500">{String(ev.at).replace("T", " ").replace("Z", "")}</span>
              <Badge variant="outline" className="text-[9px] text-zinc-400 border-zinc-600">{ev.type}</Badge>
              <span className="text-zinc-200">{ev.name}</span>
              <span className="text-zinc-400">{ev.what_changed}</span>
              {ev.why && <span className="text-zinc-500">— {ev.why}</span>}
              <StatusPill s={ev.status} />
            </div>
          ))}
        </TabsContent>
      </Tabs>
    </div>
  );
}
