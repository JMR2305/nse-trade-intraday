/**
 * MetaLearningTab.tsx — Phase 6.5 Meta-Learning tab inside Research Intelligence.
 *
 * Research only. Shows strategy health, failure attribution, eligibility maps,
 * improvement suggestions and contradictions derived from completed
 * out-of-sample experiments. Nothing here modifies live or paper trading;
 * draft mutations created from findings require explicit human approval.
 */
import { useState, useEffect, useCallback } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Loader2, ChevronDown, ChevronRight, Download, RefreshCw, AlertTriangle,
  FlaskConical, ShieldCheck,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { API_BASE } from "@/lib/api";
import { useToast } from "@/hooks/use-toast";

/* eslint-disable @typescript-eslint/no-explicit-any */

function na(v: any, suffix = ""): string {
  if (v === null || v === undefined || v === "") return "N/A";
  if (typeof v === "number" && (!isFinite(v) || isNaN(v))) return "N/A";
  if (typeof v === "number") return `${+v.toFixed(2)}${suffix}`;
  return String(v);
}

/** Defensive fetch: checks HTTP status, content type, empty body and JSON parse. */
async function safeJson(path: string, init?: RequestInit): Promise<any> {
  const resp = await fetch(`${API_BASE}${path}`, init);
  const text = await resp.text();
  if (!text.trim()) throw new Error(`Empty response from ${path} (HTTP ${resp.status})`);
  let data: any;
  try { data = JSON.parse(text); }
  catch { throw new Error(`Invalid JSON from ${path} (HTTP ${resp.status})`); }
  if (!resp.ok) throw new Error(String(data?.error ?? `HTTP ${resp.status}`));
  return data;
}

const EVIDENCE_CLS: Record<string, string> = {
  STRONG: "text-emerald-400 border-emerald-700",
  MODERATE: "text-sky-400 border-sky-700",
  LOW: "text-amber-400 border-amber-700",
  "VERY LOW": "text-orange-400 border-orange-700",
  INSUFFICIENT: "text-red-400 border-red-700",
};

function Ev({ e }: { e?: string }) {
  if (!e) return <span className="text-zinc-500">N/A</span>;
  return <Badge variant="outline" className={cn("text-[9px] font-mono px-1", EVIDENCE_CLS[e] ?? "text-zinc-400 border-zinc-600")}>{e}</Badge>;
}

const ACTION_CLS: Record<string, string> = {
  "PROMISING — HUMAN REVIEW REQUIRED": "text-emerald-400 border-emerald-700",
  "KEEP RESEARCHING": "text-sky-400 border-sky-700",
  "REQUIRE MORE DATA": "text-zinc-300 border-zinc-600",
  "RESTRICT BY REGIME": "text-amber-400 border-amber-700",
  "MODIFY ENTRY FILTER": "text-amber-400 border-amber-700",
  "MODIFY EXIT LOGIC": "text-amber-400 border-amber-700",
  "REDUCE HOLDING PERIOD": "text-amber-400 border-amber-700",
  ARCHIVE: "text-orange-400 border-orange-700",
  REJECT: "text-red-400 border-red-700",
};

const CELL_CLS: Record<string, string> = {
  "eligible (research)": "bg-emerald-500/15 text-emerald-300",
  "research-only": "bg-sky-500/15 text-sky-300",
  ineligible: "bg-red-500/15 text-red-300",
  "insufficient evidence": "bg-zinc-800 text-zinc-500",
};

export default function MetaLearningTab() {
  const { toast } = useToast();
  const [loading, setLoading] = useState(true);
  const [errors, setErrors] = useState<string[]>([]);
  const [health, setHealth] = useState<any>(null);
  const [failures, setFailures] = useState<any>(null);
  const [eligibility, setEligibility] = useState<any>(null);
  const [improvements, setImprovements] = useState<any>(null);
  const [contradictions, setContradictions] = useState<any>(null);
  const [openFail, setOpenFail] = useState<string | null>(null);
  const [creating, setCreating] = useState<string | null>(null);
  const [exporting, setExporting] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    const errs: string[] = [];
    const grab = async (path: string, set: (v: any) => void, label: string) => {
      try { set(await safeJson(path)); }
      catch (e) { errs.push(`${label}: ${e instanceof Error ? e.message : String(e)}`); set(null); }
    };
    await Promise.all([
      grab("/meta-learning/health", setHealth, "Strategy health"),
      grab("/meta-learning/failures", setFailures, "Failure attribution"),
      grab("/meta-learning/eligibility", setEligibility, "Eligibility"),
      grab("/meta-learning/improvements", setImprovements, "Improvements"),
      grab("/meta-learning/contradictions", setContradictions, "Contradictions"),
    ]);
    setErrors(errs);
    setLoading(false);
  }, []);

  useEffect(() => { void load(); }, [load]);

  async function createMutation(strategy: string, s: any) {
    const key = `${strategy}|${s.mutation_parameter}|${s.mutation_value}`;
    setCreating(key);
    try {
      const r = await safeJson("/meta-learning/create-mutation", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          strategyName: strategy,
          parameter: s.mutation_parameter,
          value: s.mutation_value,
          evidence: `${s.suggestion} — uplift ₹${s.historical_uplift_rs}/trade over ${s.sample_size} trades (${s.evidence}). ${s.hypothesis}`,
        }),
      });
      if (r?.success) {
        toast({ title: "Draft mutation created", description: "Added to Strategy Evolution as Draft — research only, human approval required." });
      } else {
        toast({ title: "Could not create draft", description: String(r?.error ?? "Unknown error"), variant: "destructive" });
      }
    } catch (e) {
      toast({ title: "Could not create draft", description: String(e instanceof Error ? e.message : e), variant: "destructive" });
    } finally {
      setCreating(null);
    }
  }

  async function downloadExport(kind: "csv" | "json" | "html") {
    setExporting(true);
    try {
      const resp = await fetch(`${API_BASE}/meta-learning/export?file=${kind}`);
      if (!resp.ok) throw new Error(`Export failed (HTTP ${resp.status})`);
      const blob = await resp.blob();
      if (blob.size === 0) throw new Error("Export returned an empty file");
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = kind === "csv" ? "phase65_meta_learning_export.csv"
        : kind === "json" ? "phase65_meta_learning_export.json" : "phase65_meta_learning_report.html";
      document.body.appendChild(a); a.click(); document.body.removeChild(a);
      URL.revokeObjectURL(url);
      toast({ title: `Meta-learning ${kind.toUpperCase()} downloaded`, description: "Research-only report." });
    } catch (e) {
      toast({ title: "Export failed", description: String(e instanceof Error ? e.message : e), variant: "destructive" });
    } finally {
      setExporting(false);
    }
  }

  if (loading) {
    return <div className="flex items-center gap-2 text-[11px] font-mono text-zinc-500 py-4"><Loader2 className="h-4 w-4 animate-spin" />Running meta-learning analysis…</div>;
  }

  const audit = health?.no_lookahead_audit;
  const regimes: string[] = eligibility?.regimes ?? [];

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2 flex-wrap">
        {audit && (
          <Badge variant="outline" className={cn("text-[9px] font-mono px-1.5",
            audit.status === "PASS" ? "text-emerald-400 border-emerald-700" : "text-amber-400 border-amber-700")}>
            <ShieldCheck className="h-3 w-3 mr-1" />NO-LOOKAHEAD AUDIT: {audit.status} ({audit.checked} trades, {audit.violations} violations)
          </Badge>
        )}
        <div className="ml-auto flex gap-1.5">
          <Button size="sm" variant="outline" className="h-6 px-2 font-mono text-[10px]" onClick={() => void load()}>
            <RefreshCw className="h-3 w-3 mr-1" />Refresh
          </Button>
          {(["csv", "json"] as const).map(k => (
            <Button key={k} size="sm" variant="outline" className="h-6 px-2 font-mono text-[10px]" disabled={exporting} onClick={() => void downloadExport(k)}>
              <Download className="h-3 w-3 mr-1" />{k.toUpperCase()}
            </Button>
          ))}
          <Button size="sm" variant="outline" className="h-6 px-2 font-mono text-[10px] text-violet-300 border-violet-700" disabled={exporting} onClick={() => void downloadExport("html")}>
            <Download className="h-3 w-3 mr-1" />Complete Meta-Learning Report
          </Button>
        </div>
      </div>

      {errors.map(e => (
        <p key={e} className="text-[10px] font-mono text-red-400 bg-red-500/10 border border-red-500/30 rounded px-2 py-1.5">{e}</p>
      ))}

      {/* A. Strategy Health Summary */}
      <div>
        <h3 className="text-[11px] font-mono font-bold text-zinc-200 mb-1">A · Strategy Health Summary</h3>
        <div className="border border-zinc-700 rounded overflow-x-auto">
          <table className="w-full font-mono text-[11px]">
            <thead><tr className="text-zinc-500 text-[9px] uppercase border-b border-zinc-700">
              {["Strategy", "Status", "OOS trades", "Expectancy ₹", "PF", "Drawdown ₹", "Evidence", "Dominant failure", "Best regime", "Worst regime", "Recommended action"].map(h => (
                <th key={h} className="text-left px-2 py-1.5">{h}</th>))}
            </tr></thead>
            <tbody>
              {(health?.strategies ?? []).length === 0 && (
                <tr><td colSpan={11} className="px-2 py-3 text-zinc-500">INSUFFICIENT DATA — no completed experiments with trades.</td></tr>)}
              {(health?.strategies ?? []).map((s: any) => (
                <tr key={s.strategy} className="border-b border-zinc-800 text-zinc-300">
                  <td className="px-2 py-1.5 text-zinc-100">{s.strategy}</td>
                  <td className={cn("px-2 py-1.5", s.status === "POSITIVE" ? "text-emerald-400" : "text-red-400")}>{s.status}</td>
                  <td className="px-2 py-1.5">{na(s.oos_trades)}</td>
                  <td className="px-2 py-1.5">{na(s.expectancy_rs)}</td>
                  <td className="px-2 py-1.5">{na(s.profit_factor)}</td>
                  <td className="px-2 py-1.5">{na(s.max_drawdown_rs)}</td>
                  <td className="px-2 py-1.5"><Ev e={s.evidence} /></td>
                  <td className="px-2 py-1.5 text-zinc-500">{s.dominant_failure_reason ?? "—"}</td>
                  <td className="px-2 py-1.5 text-zinc-500">{s.best_regime ? `${s.best_regime.regime} (₹${na(s.best_regime.expectancy_rs)})` : "N/A"}</td>
                  <td className="px-2 py-1.5 text-zinc-500">{s.worst_regime ? `${s.worst_regime.regime} (₹${na(s.worst_regime.expectancy_rs)})` : "N/A"}</td>
                  <td className="px-2 py-1.5"><Badge variant="outline" className={cn("text-[9px] font-mono px-1", ACTION_CLS[s.recommended_action] ?? "text-zinc-400 border-zinc-600")}>{s.recommended_action}</Badge></td>
                </tr>))}
            </tbody>
          </table>
        </div>
      </div>

      {/* B. Why Strategies Failed */}
      <div>
        <h3 className="text-[11px] font-mono font-bold text-zinc-200 mb-1">B · Why Strategies Failed</h3>
        {(failures?.reports ?? []).filter((r: any) => r.is_failure).length === 0 && (
          <p className="text-[10px] font-mono text-zinc-500">No failing strategies detected (or INSUFFICIENT DATA).</p>)}
        {(failures?.reports ?? []).filter((r: any) => r.is_failure).map((r: any) => (
          <div key={r.strategy} className="border border-zinc-700 rounded mb-1.5">
            <button className="w-full flex items-center gap-2 px-2 py-1.5 font-mono text-[11px] text-zinc-200"
              onClick={() => setOpenFail(openFail === r.strategy ? null : r.strategy)}>
              {openFail === r.strategy ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
              {r.strategy}
              <Badge variant="outline" className="text-[9px] font-mono text-red-400 border-red-700 px-1">{r.primary_reason}</Badge>
              <Ev e={r.evidence} />
              <span className="text-zinc-500 text-[10px]">{r.sample_size} trades · failure is {String(r.failure_breadth).toLowerCase()}</span>
            </button>
            {openFail === r.strategy && (
              <div className="px-3 pb-2 space-y-1.5 font-mono text-[10px] text-zinc-400">
                <p className="text-zinc-300">{r.primary_detail}</p>
                {r.secondary_reasons?.length > 0 && (
                  <ul className="list-disc ml-4">{r.secondary_reasons.map((x: any) => <li key={x.code}><b>{x.code}</b>: {x.detail}</li>)}</ul>)}
                <p>Gross ₹{na(r.gross_pnl)} vs net ₹{na(r.net_pnl)} (costs ₹{na(r.total_costs)}) —
                  {r.negative_gross_edge ? " negative gross edge before costs." : r.costs_caused_failure ? " costs caused the failure." : " costs did not flip the sign."}</p>
                <p>Win rate {na(r.win_rate)}% · PF {na(r.profit_factor)} · calibration error {na(r.calibration_error)} · max drawdown ₹{na(r.max_drawdown_rs)}</p>
                {(r.affected_regimes ?? []).length > 0 && <p>Affected regimes: {r.affected_regimes.map((x: any) => `${x.value} (₹${na(x.expectancy_rs)}, ${x.trades}t)`).join("; ")}</p>}
                {(r.affected_sectors ?? []).length > 0 && <p>Affected sectors: {r.affected_sectors.map((x: any) => `${x.value} (₹${na(x.expectancy_rs)}, ${x.trades}t)`).join("; ")}</p>}
                {(r.affected_holding_periods ?? []).length > 0 && <p>Affected holding periods: {r.affected_holding_periods.map((x: any) => `${x.band} (₹${na(x.expectancy_rs)})`).join("; ")}</p>}
                <p className="text-amber-400/90 flex gap-1"><AlertTriangle className="h-3 w-3 mt-0.5 shrink-0" />
                  Robustness: {r.robustness_passed}/{r.robustness_total} checks passed. Findings are associations, not proven causes.</p>
              </div>)}
          </div>))}
      </div>

      {/* C. Eligibility Map */}
      <div>
        <h3 className="text-[11px] font-mono font-bold text-zinc-200 mb-1">C · Eligibility Map <span className="text-[9px] text-amber-400">(RESEARCH CANDIDATE — HUMAN APPROVAL REQUIRED)</span></h3>
        <div className="border border-zinc-700 rounded overflow-x-auto">
          <table className="w-full font-mono text-[10px]">
            <thead><tr className="text-zinc-500 text-[9px] uppercase border-b border-zinc-700">
              <th className="text-left px-2 py-1.5">Strategy</th>
              {regimes.map(r => <th key={r} className="text-left px-2 py-1.5">{r}</th>)}
            </tr></thead>
            <tbody>
              {(eligibility?.matrix ?? []).map((row: any) => (
                <tr key={row.strategy} className="border-b border-zinc-800">
                  <td className="px-2 py-1.5 text-zinc-200">{row.strategy}</td>
                  {regimes.map(r => {
                    const c = row.cells?.[r];
                    return (
                      <td key={r} className="px-1 py-1">
                        <div className={cn("rounded px-1.5 py-1", CELL_CLS[c?.state] ?? "bg-zinc-800 text-zinc-500")}>
                          <div className="uppercase text-[8px]">{c?.state ?? "N/A"}</div>
                          <div>{c?.trades ?? 0}t · ₹{na(c?.expectancy_rs)} · PF {na(c?.profit_factor)}</div>
                        </div>
                      </td>);
                  })}
                </tr>))}
            </tbody>
          </table>
        </div>
        <p className="text-[9px] font-mono text-zinc-500 mt-1">{eligibility?.note}</p>
      </div>

      {/* D. What Would Improve the Strategy */}
      <div>
        <h3 className="text-[11px] font-mono font-bold text-zinc-200 mb-1">D · What Would Improve the Strategy</h3>
        {(improvements?.suggestions ?? []).every((s: any) => (s.suggestions ?? []).length === 0) && (
          <p className="text-[10px] font-mono text-zinc-500">No evidence-supported improvements yet — INSUFFICIENT DATA for reliable suggestions.</p>)}
        <div className="grid gap-2 md:grid-cols-2">
          {(improvements?.suggestions ?? []).filter((s: any) => (s.suggestions ?? []).length > 0).map((s: any) => (
            <div key={s.strategy} className="border border-zinc-700 rounded p-2 space-y-1.5">
              <p className="font-mono text-[11px] text-zinc-100">{s.strategy}</p>
              {s.suggestions.map((x: any) => {
                const key = `${s.strategy}|${x.mutation_parameter}|${x.mutation_value}`;
                return (
                  <div key={key} className="border border-zinc-800 rounded p-2 font-mono text-[10px] text-zinc-300 space-y-1">
                    <p>{x.suggestion}</p>
                    <p className="text-zinc-500">Uplift ₹{na(x.historical_uplift_rs)}/trade · {x.sample_size} trades · <Ev e={x.evidence} /></p>
                    <p className="text-zinc-500">{x.hypothesis}</p>
                    <p className="text-amber-400/80">{x.known_risk}</p>
                    <Button size="sm" variant="outline" className="h-6 px-2 font-mono text-[10px]"
                      disabled={creating !== null} onClick={() => void createMutation(s.strategy, x)}>
                      {creating === key ? <Loader2 className="h-3 w-3 animate-spin mr-1" /> : <FlaskConical className="h-3 w-3 mr-1" />}
                      Create draft mutation
                    </Button>
                  </div>);
              })}
            </div>))}
        </div>
        <p className="text-[9px] font-mono text-zinc-500 mt-1">Draft mutations appear in Strategy Evolution with Draft status; archive them there any time. Nothing is tested or activated automatically.</p>
      </div>

      {/* E. Contradictions */}
      <div>
        <h3 className="text-[11px] font-mono font-bold text-zinc-200 mb-1">E · Contradictions</h3>
        {(contradictions?.contradictions ?? []).length === 0 && (
          <p className="text-[10px] font-mono text-zinc-500">No contradictions detected in current research data.</p>)}
        {(contradictions?.contradictions ?? []).map((c: any, i: number) => (
          <div key={i} className="border border-amber-800/60 bg-amber-500/5 rounded px-2 py-1.5 mb-1 font-mono text-[10px] text-zinc-300 flex items-start gap-2 flex-wrap">
            <AlertTriangle className="h-3 w-3 text-amber-400 mt-0.5 shrink-0" />
            <Badge variant="outline" className="text-[9px] font-mono text-amber-400 border-amber-700 px-1">{c.type}</Badge>
            <span className="text-zinc-200">{c.strategy}</span>
            <span className="text-zinc-400">{c.detail}</span>
            <Ev e={c.evidence} />
          </div>))}
      </div>
    </div>
  );
}
