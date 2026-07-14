/**
 * ResearchIntelligence.tsx — Phase 5 AI Research Intelligence page.
 *
 * Research only. Everything on this page is derived from stored, completed
 * out-of-sample experiment results. Recommendations are advisory research
 * suggestions — nothing here modifies live or paper trading.
 */
import { useState, useEffect, useCallback, useMemo } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  Loader2, Brain, ChevronDown, ChevronRight, ShieldAlert,
  Lightbulb, GraduationCap, HeartPulse, GitCompare, Stethoscope, History,
  RefreshCw, ArrowUpDown,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { apiJson } from "@/lib/api";
import { ContributionChart } from "@/pages/experiments/ReportCharts";
import { StatusBadge } from "@/pages/experiments/ResearchReport";
import MetaLearningTab from "@/pages/MetaLearningTab";

/* eslint-disable @typescript-eslint/no-explicit-any */

const DISCLAIMER =
  "Research only — these are research suggestions based on historical out-of-sample " +
  "results. They do not modify live or paper trading and do not guarantee future results.";

function na(v: any, suffix = ""): string {
  if (v === null || v === undefined || v === "") return "N/A";
  if (typeof v === "number" && (!isFinite(v) || isNaN(v))) return "N/A";
  if (typeof v === "number") return `${+v.toFixed(2)}${suffix}`;
  return String(v);
}

function ConfBadge({ level }: { level?: string }) {
  const cls: Record<string, string> = {
    HIGH: "text-emerald-400 border-emerald-700",
    MEDIUM: "text-sky-400 border-sky-700",
    LOW: "text-amber-400 border-amber-700",
  };
  if (!level) return null;
  return (
    <Badge variant="outline" className={cn("text-[9px] font-mono px-1", cls[level] ?? "text-zinc-400 border-zinc-600")}>
      {level} CONFIDENCE
    </Badge>
  );
}

function RatingBadge({ rating }: { rating?: string }) {
  const cls: Record<string, string> = {
    Excellent: "text-emerald-400 border-emerald-600 bg-emerald-500/10",
    Good: "text-sky-400 border-sky-600 bg-sky-500/10",
    Average: "text-zinc-300 border-zinc-600 bg-zinc-500/10",
    Weak: "text-amber-400 border-amber-600 bg-amber-500/10",
    Reject: "text-red-400 border-red-600 bg-red-500/10",
  };
  return (
    <Badge variant="outline" className={cn("text-[10px] font-mono px-1.5", cls[rating ?? ""] ?? "text-zinc-400 border-zinc-600")}>
      {rating ?? "N/A"}
    </Badge>
  );
}

// ── Trade Diagnostics tab ────────────────────────────────────────────────────
function TradeDiagnostics({ experiments }: { experiments: any[] }) {
  const [expId, setExpId] = useState<string>("");
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState<Record<number, boolean>>({});
  const [filter, setFilter] = useState<"ALL" | "WIN" | "LOSS">("ALL");

  useEffect(() => {
    if (!expId && experiments.length > 0) setExpId(experiments[0].id);
  }, [experiments, expId]);

  useEffect(() => {
    if (!expId) return;
    setLoading(true); setError(null); setData(null); setOpen({});
    apiJson(`/experiments/${expId}/trade-diagnostics`)
      .then(setData)
      .catch(e => setError(String(e?.message ?? e)))
      .finally(() => setLoading(false));
  }, [expId]);

  const trades = (data?.trades ?? []).filter((t: any) => filter === "ALL" || t.outcome === filter);

  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2 flex-wrap">
        <select value={expId} onChange={e => setExpId(e.target.value)}
          className="bg-zinc-900 border border-zinc-700 rounded text-[11px] font-mono text-zinc-200 px-2 py-1">
          {experiments.map(e => <option key={e.id} value={e.id}>{e.name ?? e.id}</option>)}
        </select>
        {(["ALL", "WIN", "LOSS"] as const).map(f => (
          <Button key={f} size="sm" variant={filter === f ? "default" : "outline"}
            className="h-6 px-2 font-mono text-[10px]" onClick={() => setFilter(f)}>{f}</Button>
        ))}
        {data && <span className="text-[10px] font-mono text-zinc-500">{trades.length} of {data.trade_count} trades</span>}
      </div>
      {loading && <div className="flex items-center gap-2 text-[11px] font-mono text-zinc-500 py-3"><Loader2 className="h-3.5 w-3.5 animate-spin" />Analyzing trades…</div>}
      {error && <p className="text-[10px] font-mono text-red-400 bg-red-500/10 border border-red-500/30 rounded px-2 py-1.5">{error}</p>}
      {data && data.trade_count === 0 && <p className="text-[10px] font-mono text-zinc-500">{na(data.note)}</p>}
      {data && trades.length > 0 && (
        <p className="text-[9px] font-mono text-zinc-500">{trades[0]?.indicator_note}</p>
      )}
      {trades.map((t: any, i: number) => (
        <div key={i} className="border border-zinc-800 rounded-md">
          <button className="w-full flex items-center gap-2 px-2.5 py-1.5 text-left flex-wrap" onClick={() => setOpen(o => ({ ...o, [i]: !o[i] }))}>
            {open[i] ? <ChevronDown className="h-3 w-3 text-zinc-500" /> : <ChevronRight className="h-3 w-3 text-zinc-500" />}
            <Badge variant="outline" className={cn("text-[9px] font-mono px-1", t.outcome === "WIN" ? "text-emerald-400 border-emerald-700" : "text-red-400 border-red-700")}>{t.outcome}</Badge>
            <span className="text-[11px] font-mono text-zinc-200 font-semibold">{t.symbol}</span>
            <span className="text-[10px] font-mono text-zinc-500">{t.strategy_name} · {t.entry_date} → {t.exit_date}</span>
            <span className={cn("text-[10px] font-mono ml-auto", (t.net_pnl ?? 0) >= 0 ? "text-emerald-400" : "text-red-400")}>₹{na(t.net_pnl)} ({na(t.return_pct)}%)</span>
          </button>
          {open[i] && (
            <div className="px-3 pb-2 space-y-1.5 text-[10px] font-mono">
              <p className="text-zinc-300"><span className="text-zinc-500">Why entered: </span>{t.entry_rationale}</p>
              <p className="text-zinc-300"><span className="text-zinc-500">Why it {t.outcome === "WIN" ? "succeeded" : "failed"}: </span>{t.outcome_explanation}</p>
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-x-4 gap-y-0.5 text-zinc-400">
                <span>Regime: <span className="text-zinc-200">{na(t.market_regime)}</span></span>
                <span>Sector: <span className="text-zinc-200">{na(t.sector)}</span></span>
                <span>Confidence: <span className="text-zinc-200">{na(t.confidence)}%{t.calibrated_confidence != null ? ` (${na(t.calibrated_confidence)}% cal.)` : ""}</span></span>
                <span>Holding: <span className="text-zinc-200">{na(t.holding_days)}d</span></span>
                <span>Exit: <span className="text-zinc-200">{na(t.exit_reason)}</span></span>
                <span>MAE: <span className="text-zinc-200">{na(t.mae_pct)}%</span></span>
                <span>MFE: <span className="text-zinc-200">{na(t.mfe_pct)}%</span></span>
                <span>Gap: <span className="text-zinc-200">{na(t.gap_pct)}%</span></span>
              </div>
              <div>
                <p className="text-zinc-500 mb-0.5">Filter checks {t.filters_respected ? "— all respected" : "— attention"}:</p>
                {(t.filters ?? []).map((f: any, j: number) => (
                  <p key={j} className={cn("pl-2", f.respected ? "text-zinc-400" : "text-amber-400")}>
                    {f.respected ? "✓" : "!"} {f.filter}: {f.value}{f.note ? ` — ${f.note}` : ""}
                  </p>
                ))}
              </div>
              <p className="text-zinc-500">Indicator values (MACD, RSI, EMA, ATR, trend/sector strength): <span className="text-zinc-400">Not available — not stored with this experiment's trades.</span></p>
              {t.counterfactual?.available ? (
                <div>
                  <p className="text-zinc-500">Other model variants on the same setup:</p>
                  {t.counterfactual.alternatives.map((a: any, j: number) => (
                    <p key={j} className="pl-2 text-zinc-400">Variant {a.variant}: ₹{na(a.net_pnl)} ({na(a.exit_reason)})</p>
                  ))}
                </div>
              ) : (
                <p className="text-zinc-500">{t.counterfactual?.note}</p>
              )}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

// ── Compare tab ──────────────────────────────────────────────────────────────
const COMPARE_METRICS: [string, string, string][] = [
  ["net_return_pct", "Net Return", "%"], ["net_pnl", "Net P&L ₹", ""],
  ["profit_factor", "Profit Factor", ""], ["expectancy_rs", "Expectancy ₹", ""],
  ["win_rate", "Win Rate", "%"], ["sharpe", "Sharpe", ""],
  ["max_drawdown_pct", "Max Drawdown", "%"], ["recovery_factor", "Recovery", ""],
  ["calibration_ece_after", "Calibration ECE", ""], ["score", "Research Score", ""],
  ["oos_trades", "Trades", ""], ["windows", "Windows", ""],
];

function CompareTab({ experiments }: { experiments: any[] }) {
  const [selected, setSelected] = useState<string[]>([]);
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sortKey, setSortKey] = useState<string>("net_return_pct");

  useEffect(() => {
    if (selected.length === 0 && experiments.length > 0) {
      setSelected(experiments.slice(0, 3).map(e => e.id));
    }
  }, [experiments]); // eslint-disable-line react-hooks/exhaustive-deps

  const run = useCallback(() => {
    if (selected.length === 0) { setData(null); return; }
    setLoading(true); setError(null);
    apiJson(`/experiments/compare?ids=${selected.join(",")}`)
      .then(setData)
      .catch(e => setError(String(e?.message ?? e)))
      .finally(() => setLoading(false));
  }, [selected]);

  useEffect(() => { run(); }, [run]);

  const rows = useMemo(() => {
    const r = (data?.experiments ?? []).filter((x: any) => x.available);
    return [...r].sort((a: any, b: any) => (Number(b[sortKey]) || -1e18) - (Number(a[sortKey]) || -1e18));
  }, [data, sortKey]);
  const unavailable = (data?.experiments ?? []).filter((x: any) => !x.available);

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap gap-1.5">
        {experiments.map(e => (
          <button key={e.id}
            className={cn("text-[9px] font-mono rounded px-1.5 py-0.5 border",
              selected.includes(e.id) ? "text-violet-300 border-violet-600 bg-violet-500/10" : "text-zinc-400 border-zinc-700")}
            onClick={() => setSelected(s => s.includes(e.id) ? s.filter(x => x !== e.id) : [...s, e.id])}>
            {e.name ?? e.id}
          </button>
        ))}
      </div>
      {loading && <div className="flex items-center gap-2 text-[11px] font-mono text-zinc-500 py-2"><Loader2 className="h-3.5 w-3.5 animate-spin" />Comparing…</div>}
      {error && <p className="text-[10px] font-mono text-red-400 bg-red-500/10 border border-red-500/30 rounded px-2 py-1.5">{error}</p>}
      {unavailable.map((u: any) => (
        <p key={u.experiment_id} className="text-[9px] font-mono text-amber-400/80">{u.experiment_name ?? u.experiment_id}: {u.note}</p>
      ))}
      {rows.length > 0 && (
        <>
          <div className="overflow-x-auto">
            <table className="w-full text-[10px] font-mono">
              <thead>
                <tr className="text-zinc-500 border-b border-zinc-800">
                  <th className="text-left py-1 pr-3">Metric</th>
                  {rows.map((r: any) => (
                    <th key={r.experiment_id} className="text-left py-1 pr-3 whitespace-nowrap">
                      {r.experiment_name}<br />
                      <StatusBadge value={r.verdict} />
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {COMPARE_METRICS.map(([k, label, suffix]) => (
                  <tr key={k} className="border-b border-zinc-800/50">
                    <td className="py-1 pr-3 text-zinc-500 whitespace-nowrap">
                      <button className="flex items-center gap-1 hover:text-zinc-300" onClick={() => setSortKey(k)}>
                        {label}{sortKey === k && <ArrowUpDown className="h-2.5 w-2.5" />}
                      </button>
                    </td>
                    {rows.map((r: any) => (
                      <td key={r.experiment_id} className="py-1 pr-3 text-zinc-300 whitespace-nowrap">{na(r[k], suffix)}</td>
                    ))}
                  </tr>
                ))}
                <tr className="border-b border-zinc-800/50">
                  <td className="py-1 pr-3 text-zinc-500">Evidence</td>
                  {rows.map((r: any) => <td key={r.experiment_id} className="py-1 pr-3 text-zinc-300">{na(r.evidence_verdict)}</td>)}
                </tr>
                <tr className="border-b border-zinc-800/50">
                  <td className="py-1 pr-3 text-zinc-500">Dominant Regime</td>
                  {rows.map((r: any) => <td key={r.experiment_id} className="py-1 pr-3 text-zinc-300">{na(r.dominant_regime)}</td>)}
                </tr>
                <tr className="border-b border-zinc-800/50">
                  <td className="py-1 pr-3 text-zinc-500">Best Strategy</td>
                  {rows.map((r: any) => <td key={r.experiment_id} className="py-1 pr-3 text-emerald-400">{r.best_strategy ? `${r.best_strategy.name} (₹${na(r.best_strategy.net_pnl)})` : "N/A"}</td>)}
                </tr>
                <tr>
                  <td className="py-1 pr-3 text-zinc-500">Worst Strategy</td>
                  {rows.map((r: any) => <td key={r.experiment_id} className="py-1 pr-3 text-red-400">{r.worst_strategy ? `${r.worst_strategy.name} (₹${na(r.worst_strategy.net_pnl)})` : "N/A"}</td>)}
                </tr>
              </tbody>
            </table>
          </div>
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-2">
            <ContributionChart title="Net return by experiment (%)"
              rows={rows.map((r: any) => ({ group: r.experiment_name, v: r.net_return_pct }))}
              dataKey="v" name="Net Return %" />
            <ContributionChart title="Expectancy per trade by experiment (₹)"
              rows={rows.map((r: any) => ({ group: r.experiment_name, v: r.expectancy_rs }))}
              dataKey="v" name="Expectancy ₹" />
          </div>
        </>
      )}
    </div>
  );
}

// ── main page ────────────────────────────────────────────────────────────────
export default function ResearchIntelligence() {
  const [intel, setIntel] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [experiments, setExperiments] = useState<any[]>([]);

  const load = useCallback(() => {
    setLoading(true); setError(null);
    Promise.all([
      apiJson("/research/intelligence"),
      apiJson("/experiments").catch(() => ({ experiments: [] })),
    ])
      .then(([i, e]) => {
        setIntel(i);
        const list = (e.experiments ?? [])
          .filter((x: any) => ["completed", "rejected", "failed_evidence", "done"].includes(String(x.status ?? "").toLowerCase()))
          .map((x: any) => ({ id: x.id, name: x.name ?? x.id }));
        setExperiments(list);
      })
      .catch(err => setError(String(err?.message ?? err)))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => { load(); }, [load]);

  const ls = intel?.learning_summary ?? {};
  const tables = ls.tables ?? {};

  return (
    <div className="space-y-3 max-w-6xl">
      <div className="flex items-center gap-2 flex-wrap">
        <Brain className="h-4 w-4 text-violet-400" />
        <h1 className="text-sm font-mono font-bold text-zinc-100">AI Research Intelligence</h1>
        <Badge variant="outline" className="text-[9px] font-mono text-violet-400 border-violet-700 px-1.5">RESEARCH ONLY</Badge>
        {intel && <span className="text-[10px] font-mono text-zinc-500">{intel.experiments_analyzed} experiments · {intel.total_oos_trades} OOS trades analyzed</span>}
        <Button size="sm" variant="outline" className="h-6 px-2 font-mono text-[10px] ml-auto" onClick={load} disabled={loading}>
          {loading ? <Loader2 className="h-3 w-3 animate-spin" /> : <RefreshCw className="h-3 w-3 mr-1" />}Refresh
        </Button>
      </div>
      <p className="text-[9px] font-mono text-amber-400/90 bg-amber-500/5 border border-amber-500/20 rounded px-2 py-1 flex gap-1.5">
        <ShieldAlert className="h-3 w-3 flex-shrink-0 mt-0.5" />{DISCLAIMER}
      </p>

      {error && <p className="text-[10px] font-mono text-red-400 bg-red-500/10 border border-red-500/30 rounded px-2 py-1.5">{error}</p>}
      {loading && !intel && <div className="flex items-center gap-2 text-[11px] font-mono text-zinc-500 py-4"><Loader2 className="h-4 w-4 animate-spin" />Learning from all completed experiments…</div>}

      {intel && (
        <Tabs defaultValue="insights">
          <TabsList className="h-7 flex-wrap">
            <TabsTrigger value="insights" className="text-[10px] font-mono h-6"><Lightbulb className="h-3 w-3 mr-1" />Insights</TabsTrigger>
            <TabsTrigger value="learning" className="text-[10px] font-mono h-6"><GraduationCap className="h-3 w-3 mr-1" />Learning Summary</TabsTrigger>
            <TabsTrigger value="health" className="text-[10px] font-mono h-6"><HeartPulse className="h-3 w-3 mr-1" />Strategy Health</TabsTrigger>
            <TabsTrigger value="recs" className="text-[10px] font-mono h-6"><Brain className="h-3 w-3 mr-1" />Recommendations</TabsTrigger>
            <TabsTrigger value="diagnostics" className="text-[10px] font-mono h-6"><Stethoscope className="h-3 w-3 mr-1" />Trade Diagnostics</TabsTrigger>
            <TabsTrigger value="compare" className="text-[10px] font-mono h-6"><GitCompare className="h-3 w-3 mr-1" />Compare</TabsTrigger>
            <TabsTrigger value="timeline" className="text-[10px] font-mono h-6"><History className="h-3 w-3 mr-1" />Timeline</TabsTrigger>
            <TabsTrigger value="meta" className="text-[10px] font-mono h-6"><Brain className="h-3 w-3 mr-1" />Meta-Learning</TabsTrigger>
          </TabsList>

          <TabsContent value="meta" className="mt-2">
            <MetaLearningTab />
          </TabsContent>

          <TabsContent value="insights" className="space-y-2 mt-2">
            {(intel.insights ?? []).length === 0 && <p className="text-[10px] font-mono text-zinc-500">No evidence-backed patterns identified yet — more completed experiments are needed.</p>}
            {(intel.insights ?? []).map((ins: any) => (
              <div key={ins.id} className="border border-zinc-800 rounded-md p-2 space-y-1">
                <div className="flex items-center gap-2 flex-wrap">
                  <Lightbulb className="h-3 w-3 text-amber-400" />
                  <span className="text-[11px] font-mono font-semibold text-zinc-200">{ins.title}</span>
                  <ConfBadge level={ins.confidence_level} />
                  <span className="text-[9px] font-mono text-zinc-500 ml-auto">{ins.evidence?.trades} trades · {ins.evidence?.metric}</span>
                </div>
                <p className="text-[10px] font-mono text-zinc-400">{ins.detail}</p>
              </div>
            ))}
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-2">
              <ContributionChart title="Confidence band vs expectancy (₹/trade)" rows={tables.by_confidence_band} dataKey="expectancy_rs" name="Expectancy ₹" />
              <ContributionChart title="Holding period vs expectancy (₹/trade)" rows={tables.by_holding_period} dataKey="expectancy_rs" name="Expectancy ₹" />
            </div>
          </TabsContent>

          <TabsContent value="learning" className="space-y-2 mt-2">
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2">
              {([
                ["Most consistent strategy", ls.most_consistent_strategy, "strategy"],
                ["Weakest strategy", ls.weakest_strategy, "strategy"],
                ["Safest regime", ls.safest_regime, "regime"],
                ["Riskiest regime", ls.riskiest_regime, "regime"],
                ["Best confidence band", ls.best_confidence_band, "band"],
              ] as [string, any, string][]).map(([label, obj, key]) => (
                <div key={label} className="border border-zinc-800 rounded-md p-2">
                  <p className="text-[9px] font-mono text-zinc-500 uppercase">{label}</p>
                  {obj ? (
                    <>
                      <p className="text-[11px] font-mono font-semibold text-zinc-200">{obj[key]}</p>
                      <p className="text-[9px] font-mono text-zinc-500">₹{na(obj.expectancy_rs)}/trade · {obj.trades} trades · evidence {obj.sample_label}</p>
                    </>
                  ) : <p className="text-[10px] font-mono text-zinc-500">Not available — insufficient data.</p>}
                </div>
              ))}
              <div className="border border-zinc-800 rounded-md p-2">
                <p className="text-[9px] font-mono text-zinc-500 uppercase">Underperforming sectors</p>
                <p className="text-[11px] font-mono text-zinc-200">{(ls.underperforming_sectors ?? []).join(", ") || "None identified"}</p>
              </div>
            </div>
            {(ls.repeatedly_failing_configs ?? []).length > 0 && (
              <div className="border border-zinc-800 rounded-md p-2 space-y-1">
                <p className="text-[10px] font-mono text-zinc-400 font-semibold">Configurations that failed research validation</p>
                {(ls.repeatedly_failing_configs ?? []).map((c: any, i: number) => (
                  <p key={i} className="text-[10px] font-mono text-zinc-500">• {c.experiment} — {c.verdict} ({Object.entries(c.config_summary ?? {}).map(([k, v]) => `${k}=${v}`).join(", ") || "config N/A"})</p>
                ))}
              </div>
            )}
            <p className="text-[9px] font-mono text-zinc-500">{ls.filters_note}</p>
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-2">
              <ContributionChart title="Strategy net P&L across all experiments (₹)" rows={tables.by_strategy} />
              <ContributionChart title="Sector net P&L across all experiments (₹)" rows={tables.by_sector} />
              <ContributionChart title="Regime net P&L across all experiments (₹)" rows={tables.by_regime} />
              <ContributionChart title="Confidence band trade counts" rows={tables.by_confidence_band} dataKey="trades" name="Trades" />
            </div>
          </TabsContent>

          <TabsContent value="health" className="space-y-2 mt-2">
            {(intel.strategy_health ?? []).map((h: any) => (
              <div key={h.strategy} className="border border-zinc-800 rounded-md p-2 space-y-1">
                <div className="flex items-center gap-2 flex-wrap">
                  <HeartPulse className="h-3 w-3 text-violet-400" />
                  <span className="text-[11px] font-mono font-semibold text-zinc-200">{h.strategy}</span>
                  <RatingBadge rating={h.rating} />
                  <span className="text-[10px] font-mono text-zinc-400">Health {h.health_score}/100</span>
                  <span className="text-[9px] font-mono text-zinc-500 ml-auto">{h.trades} trades · evidence {h.evidence}</span>
                </div>
                <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-7 gap-x-4 gap-y-0.5 text-[9px] font-mono text-zinc-500">
                  <span>PF <span className="text-zinc-200">{na(h.profit_factor)}</span></span>
                  <span>Exp ₹ <span className="text-zinc-200">{na(h.expectancy_rs)}</span></span>
                  <span>Win% <span className="text-zinc-200">{na(h.win_rate)}</span></span>
                  <span>Net ₹ <span className="text-zinc-200">{na(h.net_pnl)}</span></span>
                  <span>Sharpe* <span className="text-zinc-200">{na(h.sharpe_proxy)}</span></span>
                  <span>Consistency <span className="text-zinc-200">{na(h.consistency_pct)}%</span></span>
                  <span>Stability σ <span className="text-zinc-200">{na(h.stability_rs_std)}</span></span>
                </div>
                <p className="text-[10px] font-mono text-zinc-400">{h.explanation}</p>
              </div>
            ))}
            <p className="text-[9px] font-mono text-zinc-600">* Per-trade Sharpe proxy (mean/std of trade returns) — portfolio Sharpe lives in each experiment's report.</p>
          </TabsContent>

          <TabsContent value="recs" className="space-y-2 mt-2">
            {(intel.recommendations ?? []).length === 0 && <p className="text-[10px] font-mono text-zinc-500">No evidence-backed recommendations yet.</p>}
            {(intel.recommendations ?? []).map((r: any) => (
              <div key={r.id} className="border border-zinc-800 rounded-md p-2 space-y-1">
                <div className="flex items-center gap-2 flex-wrap">
                  <Badge variant="outline" className="text-[8px] font-mono text-zinc-400 border-zinc-600 px-1 uppercase">{r.category}</Badge>
                  <span className="text-[11px] font-mono font-semibold text-zinc-200">{r.action}</span>
                  <ConfBadge level={r.confidence_level} />
                </div>
                <p className="text-[10px] font-mono text-emerald-400/90">Expected benefit: {r.expected_benefit}</p>
                <p className="text-[10px] font-mono text-zinc-500">Evidence: {r.supporting_evidence} ({r.evidence_trades} trades)</p>
                <p className="text-[9px] font-mono text-violet-400/80">Research suggestion only — never applied automatically.</p>
              </div>
            ))}
            <div className="border border-zinc-800 rounded-md p-2 space-y-1">
              <p className="text-[10px] font-mono text-zinc-300 font-semibold">Portfolio improvement suggestions (advisory)</p>
              {(intel.portfolio_suggestions ?? []).map((p: any, i: number) => (
                <p key={i} className="text-[10px] font-mono text-zinc-400">
                  • {p.suggestion}
                  {p.suggested_research_weight_pct != null && <span className="text-zinc-500"> — suggested research weight {na(p.suggested_research_weight_pct)}%</span>}
                  {p.rating && <span className="text-zinc-600"> ({p.rating})</span>}
                </p>
              ))}
            </div>
          </TabsContent>

          <TabsContent value="diagnostics" className="mt-2">
            <TradeDiagnostics experiments={experiments} />
          </TabsContent>

          <TabsContent value="compare" className="mt-2">
            <CompareTab experiments={experiments} />
          </TabsContent>

          <TabsContent value="timeline" className="mt-2 space-y-0">
            {(intel.timeline ?? []).length === 0 && <p className="text-[10px] font-mono text-zinc-500">No events yet.</p>}
            <div className="border-l border-zinc-800 ml-1.5 pl-3 space-y-2">
              {(intel.timeline ?? []).map((e: any, i: number) => (
                <div key={i} className="relative">
                  <div className={cn("absolute -left-[17px] top-1 h-2 w-2 rounded-full",
                    e.type === "discovery" ? "bg-amber-400" : e.type === "report_generated" ? "bg-sky-500" : "bg-violet-500")} />
                  <p className="text-[9px] font-mono text-zinc-500">{String(e.date ?? "").slice(0, 16).replace("T", " ")}</p>
                  <p className="text-[10px] font-mono text-zinc-200">{e.title}</p>
                  {e.type === "experiment_completed" && e.detail && (
                    <p className="text-[9px] font-mono text-zinc-500">
                      Verdict {na(e.detail.verdict)} · {na(e.detail.oos_trades)} trades · net {na(e.detail.net_return_pct)}% · score {na(e.detail.score)}
                      {e.detail.ece_before != null && e.detail.ece_after != null && ` · calibration ECE ${na(e.detail.ece_before)} → ${na(e.detail.ece_after)}`}
                    </p>
                  )}
                </div>
              ))}
            </div>
          </TabsContent>
        </Tabs>
      )}
    </div>
  );
}
