/**
 * OpsV3Sections.tsx — AI Operations Centre V3 "AI Investigation Centre"
 *
 * All sections derive from the existing OpsSnapshot (no new polling).
 * The single on-demand call is StockJourneyPanel which only fires on user search.
 *
 * Sections implemented:
 *  §1  Stock Journey (StockJourneyPanel)
 *  §2  Decision Breakdown (inside StockJourneyPanel)
 *  §3  Scan Replay (ScanReplayPanel)
 *  §4  AI Missed Opportunities (MissedOpportunities)
 *  §5  Confidence Distribution (ConfidenceDistribution)
 *  §6  Recommendation Leaderboard (RecommendationLeaderboard)
 *  §7  Agent Load Monitor (AgentLoadMonitor)
 *  §8  Historical Agent Performance (HistoricalAgentPerf)
 *  §9  AI vs Market (AIvsMarket)
 *  §10+11 Why This / Why Not (TradeExplainer — inside leaderboard + journey)
 *  §12 Pipeline Heatmap (PipelineHeatmap)
 *  §13 Smart Insights (SmartInsights)
 *  §14 End of Day Summary (EndOfDaySummary)
 *  §15 Investigation Mode (embedded in StockJourneyPanel)
 *  §16 Filters (FilterBar)
 *  §17 Search (GlobalSearch — unified with StockJourneyPanel)
 *  §18 Mobile — all components use responsive grid
 *  §19 Performance — no new polling; snapshot reuse
 */

import { useState, useRef, useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import { apiJson } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Activity, AlertTriangle, ArrowRight, BarChart2, BookOpen,
  Brain, CheckCircle2, ChevronDown, ChevronRight, Clock,
  Cpu, Database, Download, Eye, Filter, Gauge,
  GitBranch, Globe, Info, Layers, Lightbulb,
  Network, Radio, RefreshCcw, Search, Server,
  Shield, Star, Target, TrendingDown, TrendingUp,
  Trophy, XCircle, Zap, FileText, FlaskConical, Swords,
  Play, Pause, RotateCcw, ArrowDown, BarChart,
} from "lucide-react";
import type { OpsSnapshotV2 } from "@/components/ops-v2/OpsV2Sections";

// ── Extended V3 snapshot type ─────────────────────────────────────────────────

export interface MissedOpp {
  symbol: string;
  decision_type: string;
  confidence: number;
  reason: string;
  expected_return: number;
}

export interface RecEntry {
  symbol: string;
  decision_type: string;
  confidence: number;
  expected_return: number;
  explanation: string;
  scores: Record<string, number>;
}

export interface HeatmapStage {
  agent_key: string;
  label: string;
  ms: number;
  colour: "green" | "yellow" | "red" | "grey";
  status: string;
  stocks_out: number;
  health_pct: number;
}

export interface SmartInsight {
  label: string;
  value: string;
  icon: string;
}

export interface AgentLoad {
  name: string;
  queue_size: number;
  items_processed: number;
  items_rejected: number;
  avg_processing_ms: number;
  max_processing_ms: number;
  utilisation_pct: number;
  capacity_pct: number;
  status: string;
}

export interface OpsSnapshotV3 extends OpsSnapshotV2 {
  missed_opportunities: MissedOpp[];
  confidence_distribution: Record<string, number>;
  recommendation_leaderboard: {
    top_buy: RecEntry[];
    top_watch: RecEntry[];
    top_sell: RecEntry[];
  };
  pipeline_heatmap: HeatmapStage[];
  smart_insights: SmartInsight[];
  executive_summary: string;
  agent_load_monitor: Record<string, AgentLoad>;
}

interface StockJourneyResult {
  symbol: string;
  found: boolean;
  decision_type: string;
  confidence: number;
  stages: Array<{
    agent: string;
    agent_id: string;
    decision: string;
    reason: string;
    timestamp: string;
    processing_ms: number;
    status: "PASS" | "FAIL" | "WARN" | "INFO";
  }>;
  factor_breakdown: Array<{ factor: string; weight_pct: number; score_pct: number }>;
  explanation: string;
  scores: Record<string, number>;
  why_not: {
    rejected_by: string;
    reason: string;
    failing_criteria: Array<{ field: string; current: string; threshold: string }>;
    alternative: string;
  } | null;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function fmtMs(ms: number) {
  if (!ms) return "—";
  return ms < 1000 ? `${ms}ms` : `${(ms / 1000).toFixed(1)}s`;
}

const STATUS_COLOUR: Record<string, string> = {
  PASS: "text-emerald-400 bg-emerald-950/30 border-emerald-700/40",
  FAIL: "text-rose-400 bg-rose-950/30 border-rose-700/40",
  WARN: "text-amber-400 bg-amber-950/20 border-amber-700/30",
  INFO: "text-slate-400 bg-slate-800/30 border-slate-700/30",
};

const STATUS_DOT: Record<string, string> = {
  PASS: "bg-emerald-400",
  FAIL: "bg-rose-500 animate-pulse",
  WARN: "bg-amber-400",
  INFO: "bg-slate-500",
};

function decBadge(d: string) {
  const cls =
    d === "BUY" || d === "STRONG_BUY" ? "bg-emerald-900/50 border-emerald-700/50 text-emerald-300" :
    d === "WATCH" || d === "HOLD"       ? "bg-amber-900/40 border-amber-700/40 text-amber-300" :
    d === "SELL" || d === "STRONG_SELL" ? "bg-rose-900/40 border-rose-700/40 text-rose-300" :
                                           "bg-slate-800/40 border-slate-700/30 text-slate-400";
  return <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded border ${cls}`}>{d}</span>;
}

const HEAT_CLS: Record<string, string> = {
  green: "bg-emerald-700/50 border-emerald-700/30 text-emerald-300",
  yellow:"bg-amber-700/40 border-amber-700/30 text-amber-300",
  red:   "bg-rose-800/40 border-rose-700/40 text-rose-300",
  grey:  "bg-slate-800/30 border-slate-700/20 text-slate-500",
};

const INSIGHT_ICONS: Record<string, React.ReactNode> = {
  "trophy":        <Trophy className="w-4 h-4 text-yellow-400" />,
  "alert":         <AlertTriangle className="w-4 h-4 text-amber-400" />,
  "funnel":        <Filter className="w-4 h-4 text-rose-400" />,
  "x-circle":      <XCircle className="w-4 h-4 text-rose-400" />,
  "star":          <Star className="w-4 h-4 text-teal-400" />,
  "trending-down": <TrendingDown className="w-4 h-4 text-orange-400" />,
  "zap":           <Zap className="w-4 h-4 text-blue-400" />,
};

// ─────────────────────────────────────────────────────────────────────────────
// §1 + §2 + §10 + §11 + §15 + §17  Stock Journey / Investigation / Search
// ─────────────────────────────────────────────────────────────────────────────

export function StockJourneyPanel() {
  const [query, setQuery] = useState("");
  const [submitted, setSubmitted] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);

  const { data, isLoading, isError } = useQuery<StockJourneyResult>({
    queryKey: ["ops-v3-journey", submitted],
    queryFn: () => apiJson(`/ops-centre/journey/${submitted}`),
    enabled: !!submitted,
    staleTime: 60_000,
    retry: 1,
  });

  function handleSearch(e: React.FormEvent) {
    e.preventDefault();
    const sym = query.trim().toUpperCase();
    if (sym) setSubmitted(sym);
  }

  return (
    <div className="bg-slate-900/60 border border-slate-800/50 rounded-xl p-4">
      {/* Header */}
      <div className="flex items-center gap-2 mb-3">
        <Search className="w-4 h-4 text-teal-400" />
        <h2 className="font-semibold text-xs tracking-widest uppercase text-slate-400">
          Stock Journey — Investigation Mode
        </h2>
        <Badge className="ml-auto text-[10px] bg-teal-950 border-teal-700/50 text-teal-400">V3 §1+§15+§17</Badge>
      </div>
      <p className="text-[11px] text-slate-500 mb-3">
        Search any stock to see its complete pipeline journey — every agent decision, confidence factor, and rejection reason.
      </p>

      {/* Search bar */}
      <form onSubmit={handleSearch} className="flex gap-2 mb-4">
        <input
          ref={inputRef}
          value={query}
          onChange={e => setQuery(e.target.value.toUpperCase())}
          placeholder="Type symbol e.g. RELIANCE, TCS, INFY…"
          className="flex-1 bg-slate-800/60 border border-slate-700/50 rounded-lg px-3 py-2 text-sm text-slate-200 placeholder:text-slate-600 focus:outline-none focus:border-teal-600/60 font-mono"
        />
        <button
          type="submit"
          disabled={!query.trim()}
          className="px-4 py-2 text-sm rounded-lg bg-teal-700/60 border border-teal-600/50 text-teal-200 hover:bg-teal-600/60 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
        >
          Investigate
        </button>
      </form>

      {/* Results */}
      {!submitted && (
        <div className="rounded-lg bg-slate-800/20 border border-slate-700/20 p-6 text-center">
          <Eye className="w-8 h-8 text-slate-600 mx-auto mb-2" />
          <p className="text-xs text-slate-500">Enter a stock symbol to trace its complete journey through the AI pipeline.</p>
        </div>
      )}

      {submitted && isLoading && (
        <div className="space-y-3">
          {[...Array(5)].map((_, i) => <Skeleton key={i} className="h-12 w-full rounded-lg" />)}
        </div>
      )}

      {submitted && isError && (
        <div className="rounded-lg bg-rose-950/20 border border-rose-700/30 p-4 text-center">
          <XCircle className="w-5 h-5 text-rose-400 mx-auto mb-1" />
          <p className="text-xs text-rose-300">Could not retrieve journey data. Try again after a scan completes.</p>
        </div>
      )}

      {data && (
        <div className="space-y-4">
          {/* Symbol header */}
          <div className="flex items-center justify-between flex-wrap gap-2">
            <div className="flex items-center gap-2">
              <span className="text-xl font-bold font-mono text-slate-100">{data.symbol}</span>
              {decBadge(data.decision_type)}
              <span className="text-sm font-mono font-semibold text-teal-300">{data.confidence}% conf.</span>
            </div>
            {!data.found && (
              <span className="text-xs text-amber-400 bg-amber-950/30 border border-amber-700/30 rounded px-2 py-0.5">
                Not found in last scan
              </span>
            )}
          </div>

          {/* §1 Stage pipeline */}
          <div className="space-y-1">
            {data.stages.map((s, i) => (
              <div key={i} className={`rounded-lg border px-3 py-2 ${STATUS_COLOUR[s.status] ?? STATUS_COLOUR.INFO}`}>
                <div className="flex items-center gap-2 flex-wrap">
                  <div className={`w-2 h-2 rounded-full flex-shrink-0 ${STATUS_DOT[s.status] ?? "bg-slate-500"}`} />
                  <span className="text-xs font-semibold text-slate-300 w-32 flex-shrink-0">{s.agent}</span>
                  <ArrowRight className="w-3 h-3 text-slate-600 flex-shrink-0" />
                  <span className="text-xs font-bold flex-shrink-0">{s.decision}</span>
                  <span className="text-[10px] text-slate-500 ml-auto flex-shrink-0">{s.timestamp}</span>
                </div>
                <p className="text-[10px] text-slate-500 mt-0.5 ml-4 pl-2">{s.reason}</p>
              </div>
            ))}
          </div>

          {/* §2 Decision Breakdown (factor weights) */}
          {data.factor_breakdown.length > 0 && (
            <div>
              <p className="text-[10px] text-slate-500 mb-2 flex items-center gap-1.5">
                <BarChart className="w-3 h-3" /> Decision Breakdown — factor contributions
              </p>
              <div className="space-y-1.5">
                {data.factor_breakdown.map(f => (
                  <div key={f.factor} className="flex items-center gap-2"
                    title={`${f.factor}: ${f.score_pct}% score · ${f.weight_pct}% of decision weight`}>
                    <span className="text-[10px] text-slate-400 w-28 flex-shrink-0">{f.factor}</span>
                    <div className="flex-1 h-3 bg-slate-800 rounded-full overflow-hidden">
                      <div className="h-full bg-teal-600/60 rounded-full" style={{ width: `${f.score_pct}%` }} />
                    </div>
                    <span className="text-[10px] font-mono text-slate-300 w-12 text-right">{f.score_pct}%</span>
                    <span className="text-[9px] text-slate-600 w-14 text-right">({f.weight_pct}% wt)</span>
                  </div>
                ))}
              </div>
              {data.explanation && (
                <p className="text-[11px] text-slate-400 mt-2 italic border-l-2 border-teal-700/40 pl-2">
                  {data.explanation}
                </p>
              )}
            </div>
          )}

          {/* §11 Why Not This Trade */}
          {data.why_not && (
            <div className="rounded-lg bg-rose-950/20 border border-rose-700/30 p-3">
              <p className="text-[10px] font-bold text-rose-400 mb-1.5 flex items-center gap-1.5">
                <XCircle className="w-3 h-3" /> Why Not This Trade — Rejected by {data.why_not.rejected_by}
              </p>
              <p className="text-xs text-slate-400 mb-2">{data.why_not.reason}</p>
              {data.why_not.failing_criteria.length > 0 && (
                <div className="space-y-1 mb-2">
                  {data.why_not.failing_criteria.map((c, i) => (
                    <div key={i} className="flex items-center gap-2 text-[10px]">
                      <span className="text-slate-500 w-24">{c.field}</span>
                      <span className="text-rose-300 font-mono">{c.current}</span>
                      <span className="text-slate-600">vs required</span>
                      <span className="text-emerald-400 font-mono">{c.threshold}</span>
                    </div>
                  ))}
                </div>
              )}
              <div className="bg-slate-900/50 rounded px-2 py-1.5 border border-amber-800/20">
                <p className="text-[10px] text-amber-300">
                  <span className="text-slate-500 mr-1">What would pass?</span>
                  {data.why_not.alternative}
                </p>
              </div>
            </div>
          )}

          {/* §10 Why This Trade (when BUY) */}
          {(data.decision_type === "BUY" || data.decision_type === "STRONG_BUY") && data.scores && (
            <div className="rounded-lg bg-emerald-950/20 border border-emerald-700/30 p-3">
              <p className="text-[10px] font-bold text-emerald-400 mb-1.5 flex items-center gap-1.5">
                <CheckCircle2 className="w-3 h-3" /> Why This Trade?
              </p>
              <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
                {Object.entries(data.scores).map(([k, v]) => (
                  <div key={k} className="text-center bg-slate-900/40 rounded p-1.5">
                    <p className="text-[9px] text-slate-500 capitalize">{k}</p>
                    <p className="text-xs font-mono font-bold text-emerald-300">{v}%</p>
                  </div>
                ))}
              </div>
              <p className="text-[10px] text-slate-400 mt-2 italic">{data.explanation}</p>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// §3 Scan Replay
// ─────────────────────────────────────────────────────────────────────────────

const REPLAY_STAGES = [
  "Supervisor","Market Data","Research","Market Intelligence",
  "Monitoring","Strategy","Risk","AI Decision","Execution",
];

export function ScanReplayPanel({ data }: { data?: OpsSnapshotV3 }) {
  const [step, setStep] = useState(-1);
  const [playing, setPlaying] = useState(false);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (playing) {
      timerRef.current = setTimeout(() => {
        setStep(s => {
          if (s >= REPLAY_STAGES.length - 1) { setPlaying(false); return s; }
          return s + 1;
        });
      }, 700);
    }
    return () => { if (timerRef.current) clearTimeout(timerRef.current); };
  }, [playing, step]);

  function startReplay() { setStep(-1); setPlaying(true); }
  function resetReplay() { setStep(-1); setPlaying(false); }
  function togglePause()  { setPlaying(p => !p); }

  const nodes = data?.pipeline_nodes ?? [];
  const pipeStats = data?.pipeline ?? null;
  const pipelineKeys = ["supervisor","market_data","research","market_intelligence","monitoring","strategy","risk","ai_decision","execution"];

  const pipeCounts = pipeStats ? [
    pipeStats.universe_loaded, pipeStats.stocks_reviewed,
    pipeStats.passed_market_data, pipeStats.passed_research,
    pipeStats.passed_intelligence, pipeStats.passed_monitoring,
    pipeStats.passed_strategy, pipeStats.passed_risk,
    pipeStats.buy_recommendations,
  ] : [];

  return (
    <div className="bg-slate-900/60 border border-slate-800/50 rounded-xl p-4">
      <div className="flex items-center gap-2 mb-3">
        <Play className="w-4 h-4 text-teal-400" />
        <h2 className="font-semibold text-xs tracking-widest uppercase text-slate-400">Scan Replay</h2>
        <span className="text-[10px] text-slate-600 ml-1">— animate the last scan through the pipeline</span>
        <Badge className="ml-auto text-[10px] bg-slate-800 border-slate-700 text-slate-500">V3 §3</Badge>
      </div>

      {/* Controls */}
      <div className="flex items-center gap-2 mb-4">
        <button onClick={startReplay}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs bg-teal-700/50 border border-teal-600/40 text-teal-200 hover:bg-teal-600/50 transition-colors">
          <Play className="w-3 h-3" /> Replay
        </button>
        <button onClick={togglePause} disabled={step < 0}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs bg-slate-700/50 border border-slate-600/40 text-slate-300 hover:bg-slate-600/50 disabled:opacity-40 transition-colors">
          {playing ? <Pause className="w-3 h-3" /> : <Play className="w-3 h-3" />}
          {playing ? "Pause" : "Resume"}
        </button>
        <button onClick={resetReplay}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs bg-slate-800/50 border border-slate-700/30 text-slate-400 hover:bg-slate-700/50 transition-colors">
          <RotateCcw className="w-3 h-3" /> Reset
        </button>
        <span className="text-[10px] text-slate-600 ml-2">
          {step < 0 ? "Press Replay to start" :
           step >= REPLAY_STAGES.length - 1 ? "Complete" :
           `Stage ${step + 1} / ${REPLAY_STAGES.length}`}
        </span>
      </div>

      {/* Animated pipeline */}
      <div className="overflow-x-auto pb-2">
        <div className="flex items-center gap-0 min-w-max">
          {REPLAY_STAGES.map((label, idx) => {
            const active  = step === idx;
            const done    = step > idx;
            const nodeKey = pipelineKeys[idx];
            const node    = nodes.find(n => n.agent_key === nodeKey);
            const cnt     = pipeCounts[idx] ?? node?.stocks_out ?? 0;

            return (
              <div key={idx} className="flex items-center">
                <div className={`flex flex-col items-center p-2.5 rounded-lg border transition-all duration-300 min-w-[80px] ${
                  active ? "bg-teal-900/40 border-teal-600/60 scale-105 shadow-lg shadow-teal-900/20" :
                  done   ? "bg-emerald-950/20 border-emerald-700/30" :
                           "bg-slate-800/20 border-slate-700/20 opacity-40"
                }`}>
                  {active ? (
                    <div className="w-2.5 h-2.5 rounded-full bg-teal-400 animate-ping mb-1" />
                  ) : done ? (
                    <CheckCircle2 className="w-3 h-3 text-emerald-400 mb-1" />
                  ) : (
                    <div className="w-2.5 h-2.5 rounded-full bg-slate-700 mb-1" />
                  )}
                  <span className={`text-[10px] font-semibold text-center leading-tight ${
                    active ? "text-teal-200" : done ? "text-slate-300" : "text-slate-600"
                  }`}>{label}</span>
                  <span className={`text-[9px] font-mono mt-0.5 ${done ? "text-emerald-400" : "text-slate-700"}`}>
                    {done || active ? `→ ${cnt}` : ""}
                  </span>
                </div>
                {idx < REPLAY_STAGES.length - 1 && (
                  <div className={`w-4 h-px mx-0.5 transition-colors duration-300 ${done ? "bg-emerald-700/60" : "bg-slate-700/30"}`} />
                )}
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// §4 AI Missed Opportunities
// ─────────────────────────────────────────────────────────────────────────────

export function MissedOpportunities({ data, loading }: { data?: OpsSnapshotV3; loading: boolean }) {
  const [filter, setFilter] = useState<string>("ALL");
  const [showAll, setShowAll] = useState(false);
  const missed = data?.missed_opportunities ?? [];

  const types = ["ALL", ...Array.from(new Set(missed.map(m => m.decision_type)))];
  const filtered = missed.filter(m => filter === "ALL" || m.decision_type === filter);
  const shown = showAll ? filtered : filtered.slice(0, 8);

  return (
    <div className="bg-slate-900/60 border border-slate-800/50 rounded-xl p-4">
      <div className="flex items-center gap-2 mb-2">
        <TrendingDown className="w-4 h-4 text-rose-400" />
        <h2 className="font-semibold text-xs tracking-widest uppercase text-slate-400">AI Missed Opportunities</h2>
        <Badge className="ml-auto text-[10px] bg-rose-950 border-rose-700/50 text-rose-300">
          {missed.length} not purchased
        </Badge>
      </div>
      <p className="text-[10px] text-slate-500 mb-3">Stocks that received a non-BUY decision this cycle, with the AI's reason.</p>

      {/* Type filter */}
      <div className="flex flex-wrap gap-1 mb-3">
        {types.map(t => (
          <button key={t} onClick={() => setFilter(t)}
            className={`text-[10px] px-2 py-0.5 rounded border transition-colors ${
              filter === t ? "bg-teal-900/50 border-teal-700/50 text-teal-300" : "bg-slate-800/30 border-slate-700/30 text-slate-500 hover:text-slate-300"
            }`}>
            {t}
          </button>
        ))}
      </div>

      {loading ? (
        <div className="space-y-2">{[...Array(5)].map((_, i) => <Skeleton key={i} className="h-10 w-full" />)}</div>
      ) : shown.length === 0 ? (
        <p className="text-xs text-slate-500 text-center py-4">No missed opportunities this cycle.</p>
      ) : (
        <>
          <div className="space-y-1.5">
            {shown.map((m, i) => (
              <div key={i}
                title={`${m.symbol}: ${m.reason}. Confidence: ${m.confidence}%`}
                className="flex items-start gap-2 rounded-lg border border-slate-700/30 bg-slate-800/20 px-3 py-2 hover:bg-slate-800/40 transition-colors cursor-help">
                <div className="flex-shrink-0 mt-0.5">
                  {decBadge(m.decision_type)}
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="text-xs font-bold font-mono text-slate-200">{m.symbol}</span>
                    <span className="text-[10px] text-slate-500">conf. {m.confidence}%</span>
                    {m.expected_return !== 0 && (
                      <span className={`text-[10px] ml-auto ${m.expected_return > 0 ? "text-emerald-400" : "text-rose-400"}`}>
                        {m.expected_return > 0 ? "+" : ""}{m.expected_return}% exp. ret
                      </span>
                    )}
                  </div>
                  <p className="text-[10px] text-slate-500 mt-0.5 truncate">{m.reason}</p>
                </div>
              </div>
            ))}
          </div>
          {filtered.length > 8 && (
            <button onClick={() => setShowAll(s => !s)}
              className="mt-2 text-[10px] text-teal-400 hover:text-teal-300 flex items-center gap-1 mx-auto">
              {showAll ? "Show less" : `Show ${filtered.length - 8} more`}
              <ChevronDown className={`w-3 h-3 transition-transform ${showAll ? "rotate-180" : ""}`} />
            </button>
          )}
        </>
      )}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// §5 Confidence Distribution
// ─────────────────────────────────────────────────────────────────────────────

export function ConfidenceDistribution({ data, loading }: { data?: OpsSnapshotV3; loading: boolean }) {
  const dist = data?.confidence_distribution;
  const buckets = [
    { key: "90_100", label: "90–100%", cls: "bg-emerald-500/60" },
    { key: "80_90",  label: "80–90%",  cls: "bg-teal-500/60" },
    { key: "70_80",  label: "70–80%",  cls: "bg-blue-500/60" },
    { key: "60_70",  label: "60–70%",  cls: "bg-amber-500/60" },
    { key: "below_60", label: "< 60%", cls: "bg-rose-500/60" },
  ];
  const total = dist ? Object.values(dist).reduce((s, v) => s + v, 0) : 0;

  return (
    <div className="bg-slate-900/60 border border-slate-800/50 rounded-xl p-4">
      <div className="flex items-center gap-2 mb-3">
        <BarChart2 className="w-4 h-4 text-teal-400" />
        <h2 className="font-semibold text-xs tracking-widest uppercase text-slate-400">Confidence Distribution</h2>
        <Badge className="ml-auto text-[10px] bg-slate-800 border-slate-700 text-slate-500">{total} stocks</Badge>
      </div>
      {loading ? (
        <div className="space-y-2">{[...Array(5)].map((_, i) => <Skeleton key={i} className="h-8 w-full" />)}</div>
      ) : !dist || total === 0 ? (
        <p className="text-xs text-slate-500 text-center py-4">No confidence data yet — run a scan first.</p>
      ) : (
        <div className="space-y-2">
          {buckets.map(b => {
            const v = dist[b.key] ?? 0;
            const pct = total > 0 ? (v / total) * 100 : 0;
            return (
              <div key={b.key} className="flex items-center gap-2"
                title={`${b.label}: ${v} stocks (${pct.toFixed(1)}%)`}>
                <span className="text-[10px] text-slate-400 w-16 flex-shrink-0">{b.label}</span>
                <div className="flex-1 h-5 bg-slate-800/60 rounded relative overflow-hidden">
                  <div className={`h-full rounded transition-all duration-500 ${b.cls}`} style={{ width: `${pct}%` }} />
                  <span className="absolute right-2 top-0 bottom-0 flex items-center text-[10px] font-mono font-bold text-slate-300">{v}</span>
                </div>
                <span className="text-[10px] text-slate-500 w-10 text-right">{pct.toFixed(0)}%</span>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// §6 Recommendation Leaderboard + §10 Why This Trade
// ─────────────────────────────────────────────────────────────────────────────

function LeaderboardTable({ entries, emptyMsg }: { entries: RecEntry[]; emptyMsg: string }) {
  const [expanded, setExpanded] = useState<string | null>(null);

  if (!entries.length) return <p className="text-xs text-slate-500 text-center py-3">{emptyMsg}</p>;
  return (
    <div className="space-y-1.5">
      {entries.map((e, i) => (
        <div key={e.symbol} className="border border-slate-700/30 rounded-lg overflow-hidden">
          <button
            onClick={() => setExpanded(expanded === e.symbol ? null : e.symbol)}
            className="w-full flex items-center gap-2 px-3 py-2 hover:bg-slate-800/40 transition-colors text-left">
            <span className="text-[10px] text-slate-600 font-mono w-4">{i + 1}</span>
            <span className="text-xs font-bold font-mono text-slate-200 w-24">{e.symbol}</span>
            {decBadge(e.decision_type)}
            <div className="flex-1" />
            <span className="text-xs font-mono font-bold text-teal-300">{e.confidence}%</span>
            {e.expected_return !== 0 && (
              <span className={`text-[10px] font-mono ${e.expected_return > 0 ? "text-emerald-400" : "text-rose-400"}`}>
                {e.expected_return > 0 ? "+" : ""}{e.expected_return}%
              </span>
            )}
            <ChevronDown className={`w-3.5 h-3.5 text-slate-600 transition-transform ${expanded === e.symbol ? "rotate-180" : ""}`} />
          </button>
          {expanded === e.symbol && (
            <div className="border-t border-slate-700/30 px-3 py-2 bg-slate-900/40 space-y-2">
              {/* §10 Why This Trade */}
              {e.explanation && (
                <p className="text-[11px] text-slate-400 italic border-l-2 border-teal-700/40 pl-2">{e.explanation}</p>
              )}
              {Object.keys(e.scores).length > 0 && (
                <div className="grid grid-cols-3 sm:grid-cols-6 gap-1.5">
                  {Object.entries(e.scores).map(([k, v]) => (
                    <div key={k} title={`${k}: ${v}%`} className="text-center bg-slate-800/40 rounded p-1 cursor-help">
                      <p className="text-[9px] text-slate-500 capitalize truncate">{k}</p>
                      <p className="text-[10px] font-mono font-bold text-teal-300">{v}%</p>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

export function RecommendationLeaderboard({ data, loading }: { data?: OpsSnapshotV3; loading: boolean }) {
  const [tab, setTab] = useState<"buy" | "watch" | "sell">("buy");
  const lb = data?.recommendation_leaderboard;

  return (
    <div className="bg-slate-900/60 border border-slate-800/50 rounded-xl p-4">
      <div className="flex items-center gap-2 mb-3">
        <Trophy className="w-4 h-4 text-yellow-400" />
        <h2 className="font-semibold text-xs tracking-widest uppercase text-slate-400">Recommendation Leaderboard</h2>
        <Badge className="ml-auto text-[10px] bg-slate-800 border-slate-700 text-slate-500">V3 §6+§10</Badge>
      </div>

      <div className="flex gap-1 mb-3">
        {(["buy","watch","sell"] as const).map(t => (
          <button key={t} onClick={() => setTab(t)}
            className={`px-2.5 py-1 text-[10px] rounded-md font-semibold uppercase tracking-wide transition-colors ${
              tab === t
                ? t === "buy" ? "bg-emerald-900/50 border border-emerald-700/50 text-emerald-300"
                : t === "watch" ? "bg-amber-900/40 border border-amber-700/40 text-amber-300"
                : "bg-rose-900/40 border border-rose-700/40 text-rose-300"
                : "bg-slate-800/30 border border-slate-700/20 text-slate-500 hover:text-slate-300"
            }`}>{t === "buy" ? "Top BUY" : t === "watch" ? "Top WATCH" : "Top SELL"}</button>
        ))}
      </div>

      {loading ? (
        <div className="space-y-2">{[...Array(5)].map((_, i) => <Skeleton key={i} className="h-9 w-full" />)}</div>
      ) : (
        <LeaderboardTable
          entries={tab === "buy" ? lb?.top_buy ?? [] : tab === "watch" ? lb?.top_watch ?? [] : lb?.top_sell ?? []}
          emptyMsg={`No ${tab.toUpperCase()} recommendations this scan.`}
        />
      )}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// §7 Agent Load Monitor
// ─────────────────────────────────────────────────────────────────────────────

const AGENT_KEYS_ORDER = [
  "supervisor","market_data","research","market_intelligence",
  "monitoring","strategy","risk","ai_decision",
  "execution","learning","knowledge","operations",
];

export function AgentLoadMonitor({ data, loading }: { data?: OpsSnapshotV3; loading: boolean }) {
  const load = data?.agent_load_monitor ?? {};

  return (
    <div className="bg-slate-900/60 border border-slate-800/50 rounded-xl p-4">
      <div className="flex items-center gap-2 mb-3">
        <Gauge className="w-4 h-4 text-teal-400" />
        <h2 className="font-semibold text-xs tracking-widest uppercase text-slate-400">Agent Load Monitor</h2>
        <Badge className="ml-auto text-[10px] bg-slate-800 border-slate-700 text-slate-500">V3 §7</Badge>
      </div>

      {loading ? (
        <div className="space-y-2">{[...Array(6)].map((_, i) => <Skeleton key={i} className="h-8 w-full" />)}</div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-[11px]">
            <thead>
              <tr className="border-b border-slate-800/60">
                {["Agent","Queue","Processed","Rejected","Avg Time","Utilisation"].map(h => (
                  <th key={h} className="text-left text-[10px] text-slate-500 pb-1.5 pr-3 font-normal">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800/20">
              {AGENT_KEYS_ORDER.map(key => {
                const a = load[key];
                if (!a) return null;
                const uCls = a.utilisation_pct >= 90 ? "text-emerald-400" : a.utilisation_pct >= 60 ? "text-amber-400" : "text-rose-400";
                return (
                  <tr key={key}>
                    <td className="py-1.5 pr-3 text-slate-300 font-medium">{a.name.replace(" Agent","")}</td>
                    <td className="py-1.5 pr-3 font-mono text-slate-400"
                      title="Items waiting to be processed">{a.queue_size}</td>
                    <td className="py-1.5 pr-3 font-mono text-emerald-400"
                      title="Items successfully processed and forwarded">{a.items_processed}</td>
                    <td className="py-1.5 pr-3 font-mono text-rose-400"
                      title="Items rejected at this stage">{a.items_rejected}</td>
                    <td className="py-1.5 pr-3 font-mono text-slate-400"
                      title="Average processing time per item">{fmtMs(a.avg_processing_ms)}</td>
                    <td className="py-1.5 pr-3">
                      <div className="flex items-center gap-1.5">
                        <div className="w-12 h-1.5 bg-slate-800 rounded-full overflow-hidden">
                          <div className={`h-full rounded-full ${a.utilisation_pct >= 90 ? "bg-emerald-500" : a.utilisation_pct >= 60 ? "bg-amber-500" : "bg-rose-500"}`}
                            style={{ width: `${a.utilisation_pct}%` }} />
                        </div>
                        <span className={`text-[10px] font-mono ${uCls}`}>{a.utilisation_pct}%</span>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// §8 Historical Agent Performance (today — 7d/30d shown as advisory)
// ─────────────────────────────────────────────────────────────────────────────

export function HistoricalAgentPerf({ data, loading }: { data?: OpsSnapshotV3; loading: boolean }) {
  const [period, setPeriod] = useState<"today" | "7d" | "30d">("today");
  const load = data?.agent_load_monitor ?? {};
  const agents = data?.agents ?? {};

  return (
    <div className="bg-slate-900/60 border border-slate-800/50 rounded-xl p-4">
      <div className="flex items-center gap-2 mb-3">
        <Clock className="w-4 h-4 text-teal-400" />
        <h2 className="font-semibold text-xs tracking-widest uppercase text-slate-400">Historical Agent Performance</h2>
        <Badge className="ml-auto text-[10px] bg-slate-800 border-slate-700 text-slate-500">V3 §8</Badge>
      </div>

      <div className="flex gap-1 mb-3">
        {(["today","7d","30d"] as const).map(p => (
          <button key={p} onClick={() => setPeriod(p)}
            className={`px-2.5 py-1 text-[10px] rounded-md font-semibold transition-colors ${
              period === p ? "bg-teal-900/50 border border-teal-700/50 text-teal-300" : "bg-slate-800/30 border border-slate-700/20 text-slate-500 hover:text-slate-300"
            }`}>{p === "today" ? "Today" : p === "7d" ? "7 Days" : "30 Days"}</button>
        ))}
      </div>

      {period !== "today" ? (
        <div className="rounded-lg bg-slate-800/20 border border-slate-700/20 p-4 text-center">
          <Database className="w-6 h-6 text-slate-600 mx-auto mb-2" />
          <p className="text-xs text-slate-500">
            {period === "7d" ? "7-day" : "30-day"} history requires stored scan records.
          </p>
          <p className="text-[10px] text-slate-600 mt-1">
            Historical data will accumulate after multiple daily scans are completed.
          </p>
        </div>
      ) : loading ? (
        <div className="space-y-2">{[...Array(6)].map((_, i) => <Skeleton key={i} className="h-8 w-full" />)}</div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-[11px]">
            <thead>
              <tr className="border-b border-slate-800/60">
                {["Agent","Avg Latency","Avg Health","Rejection %","Success %"].map(h => (
                  <th key={h} className="text-left text-[10px] text-slate-500 pb-1.5 pr-3 font-normal">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800/20">
              {AGENT_KEYS_ORDER.map(key => {
                const a = agents[key];
                const l = load[key];
                if (!a || !l) return null;
                const total = l.items_processed + l.items_rejected;
                const rejPct = total > 0 ? Math.round((l.items_rejected / total) * 100) : 0;
                const sucPct = total > 0 ? Math.round((l.items_processed / total) * 100) : 0;
                return (
                  <tr key={key}>
                    <td className="py-1.5 pr-3 text-slate-300 font-medium">{a.name.replace(" Agent","")}</td>
                    <td className="py-1.5 pr-3 font-mono text-slate-400">{fmtMs(l.avg_processing_ms)}</td>
                    <td className="py-1.5 pr-3 font-mono text-emerald-400">{a.health_pct}%</td>
                    <td className="py-1.5 pr-3 font-mono text-rose-400">{rejPct}%</td>
                    <td className="py-1.5 pr-3 font-mono text-teal-300">{sucPct}%</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// §9 AI vs Market
// ─────────────────────────────────────────────────────────────────────────────

export function AIvsMarket() {
  const { data, isLoading } = useQuery<{
    total_pnl?: number; win_rate?: number; win_rate_pct?: number;
    best_strategy?: string; worst_strategy?: string; total_trades?: number;
    total_return_pct?: number; paper_pnl_pct?: number;
  }>({
    queryKey: ["analytics-perf-summary"],
    queryFn: () => apiJson("/analytics/performance"),
    staleTime: 60_000, retry: 1,
  });

  const { data: benchmarks, isLoading: bLoading } = useQuery<{
    nifty_50?: { change_pct?: number; current?: number };
    bank_nifty?: { change_pct?: number };
    nifty_change_pct?: number; bank_nifty_change_pct?: number;
  }>({
    queryKey: ["market-benchmark"],
    queryFn: () => apiJson("/market-data/NIFTY50"),
    staleTime: 60_000, retry: 1,
  });

  const aiRet    = data?.total_return_pct ?? data?.paper_pnl_pct ?? null;
  const niftyRet = benchmarks?.nifty_change_pct ?? benchmarks?.nifty_50?.change_pct ?? null;
  const bankRet  = benchmarks?.bank_nifty_change_pct ?? benchmarks?.bank_nifty?.change_pct ?? null;
  const alpha    = aiRet !== null && niftyRet !== null ? aiRet - niftyRet : null;
  const loading  = isLoading || bLoading;

  function pctCls(v: number | null) {
    if (v === null) return "text-slate-400";
    return v > 0 ? "text-emerald-400" : v < 0 ? "text-rose-400" : "text-slate-400";
  }
  function fmt(v: number | null) {
    if (v === null) return "—";
    return `${v > 0 ? "+" : ""}${v.toFixed(2)}%`;
  }

  const kpis = [
    { label: "AI Return (Paper)", value: aiRet, tip: "Total paper portfolio return this session" },
    { label: "NIFTY 50 Change",   value: niftyRet, tip: "NIFTY 50 % change today" },
    { label: "BANK NIFTY Change", value: bankRet,  tip: "BANK NIFTY % change today" },
    { label: "Alpha Generated",   value: alpha,    tip: "AI Return minus NIFTY return" },
  ];

  return (
    <div className="bg-slate-900/60 border border-slate-800/50 rounded-xl p-4">
      <div className="flex items-center gap-2 mb-3">
        <TrendingUp className="w-4 h-4 text-teal-400" />
        <h2 className="font-semibold text-xs tracking-widest uppercase text-slate-400">AI vs Market</h2>
        <Badge className="ml-auto text-[10px] bg-slate-800 border-slate-700 text-slate-500">V3 §9 · Paper Only</Badge>
      </div>
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-2 mb-3">
        {kpis.map(k => (
          <div key={k.label} title={k.tip} className="bg-slate-800/30 rounded-lg p-2.5 cursor-help">
            <p className="text-[9px] text-slate-500 mb-0.5">{k.label}</p>
            {loading ? <Skeleton className="h-5 w-14" /> :
              <p className={`text-sm font-bold font-mono ${pctCls(k.value)}`}>{fmt(k.value)}</p>}
          </div>
        ))}
      </div>
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
        {[
          { label: "Win Rate",        value: (data?.win_rate_pct ?? data?.win_rate) != null ? `${((data?.win_rate_pct ?? data?.win_rate) as number).toFixed(1)}%` : "—", tip: "% of paper trades closed at a profit" },
          { label: "Total Trades",    value: data?.total_trades ?? "—", tip: "Paper trades executed this session" },
          { label: "Best Strategy",   value: data?.best_strategy ?? "—", tip: "Strategy with highest paper returns" },
          { label: "Worst Strategy",  value: data?.worst_strategy ?? "—", tip: "Strategy with lowest paper returns" },
        ].map(k => (
          <div key={k.label} title={k.tip} className="bg-slate-800/20 rounded-lg px-2.5 py-2 cursor-help">
            <p className="text-[9px] text-slate-500 mb-0.5">{k.label}</p>
            {loading ? <Skeleton className="h-4 w-16" /> :
              <p className="text-xs font-mono font-semibold text-slate-200">{String(k.value)}</p>}
          </div>
        ))}
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// §12 Pipeline Heatmap
// ─────────────────────────────────────────────────────────────────────────────

export function PipelineHeatmap({ data, loading }: { data?: OpsSnapshotV3; loading: boolean }) {
  const heatmap = data?.pipeline_heatmap ?? [];

  return (
    <div className="bg-slate-900/60 border border-slate-800/50 rounded-xl p-4">
      <div className="flex items-center gap-2 mb-3">
        <Layers className="w-4 h-4 text-teal-400" />
        <h2 className="font-semibold text-xs tracking-widest uppercase text-slate-400">Pipeline Heatmap</h2>
        <span className="text-[10px] text-slate-600 ml-1">— colour shows processing speed</span>
        <Badge className="ml-auto text-[10px] bg-slate-800 border-slate-700 text-slate-500">V3 §12</Badge>
      </div>

      {/* Legend */}
      <div className="flex items-center gap-4 mb-3 flex-wrap">
        {[
          { colour:"green",  label: "Fast (< 2s)",    cls: "bg-emerald-500" },
          { colour:"yellow", label: "Slow (2–5s)",    cls: "bg-amber-500" },
          { colour:"red",    label: "Blocked (> 5s)", cls: "bg-rose-500" },
          { colour:"grey",   label: "Unknown",        cls: "bg-slate-600" },
        ].map(l => (
          <div key={l.colour} className="flex items-center gap-1.5">
            <div className={`w-2.5 h-2.5 rounded-sm ${l.cls}`} />
            <span className="text-[10px] text-slate-500">{l.label}</span>
          </div>
        ))}
      </div>

      {loading ? (
        <div className="grid grid-cols-4 sm:grid-cols-6 lg:grid-cols-12 gap-1.5">
          {[...Array(12)].map((_, i) => <Skeleton key={i} className="h-16 w-full rounded-lg" />)}
        </div>
      ) : (
        <div className="grid grid-cols-4 sm:grid-cols-6 lg:grid-cols-12 gap-1.5">
          {heatmap.map(s => (
            <div key={s.agent_key}
              title={`${s.label}: ${fmtMs(s.ms)} · Status: ${s.status} · Forwarded: ${s.stocks_out} stocks`}
              className={`rounded-lg border p-2 flex flex-col items-center gap-1 cursor-help ${HEAT_CLS[s.colour] ?? HEAT_CLS.grey}`}>
              <span className="text-[9px] font-semibold text-center leading-tight">{s.label.replace(" Agent","")}</span>
              <span className="text-[9px] font-mono">{fmtMs(s.ms)}</span>
              <span className="text-[8px] opacity-70">→ {s.stocks_out}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// §13 Smart Insights
// ─────────────────────────────────────────────────────────────────────────────

export function SmartInsights({ data, loading }: { data?: OpsSnapshotV3; loading: boolean }) {
  const insights = data?.smart_insights ?? [];

  return (
    <div className="bg-slate-900/60 border border-slate-800/50 rounded-xl p-4">
      <div className="flex items-center gap-2 mb-3">
        <Lightbulb className="w-4 h-4 text-yellow-400" />
        <h2 className="font-semibold text-xs tracking-widest uppercase text-slate-400">Smart Insights</h2>
        <Badge className="ml-auto text-[10px] bg-yellow-950/50 border-yellow-700/30 text-yellow-400">V3 §13 · AI-Generated</Badge>
      </div>

      {loading ? (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-2">
          {[...Array(7)].map((_, i) => <Skeleton key={i} className="h-16 w-full rounded-lg" />)}
        </div>
      ) : insights.length === 0 ? (
        <p className="text-xs text-slate-500 text-center py-4">Run a scan to generate insights.</p>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-2">
          {insights.map((ins, i) => (
            <div key={i} className="bg-slate-800/30 border border-slate-700/30 rounded-lg p-2.5 flex items-start gap-2">
              <span className="flex-shrink-0 mt-0.5">{INSIGHT_ICONS[ins.icon] ?? <Zap className="w-4 h-4 text-slate-400"/>}</span>
              <div className="min-w-0">
                <p className="text-[10px] text-slate-500 mb-0.5">{ins.label}</p>
                <p className="text-xs font-semibold text-slate-200 break-words leading-tight">{ins.value}</p>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// §14 End of Day Executive Summary
// ─────────────────────────────────────────────────────────────────────────────

export function EndOfDaySummary({ data, loading }: { data?: OpsSnapshotV3; loading: boolean }) {
  const text = data?.executive_summary;
  const p    = data?.pipeline;

  return (
    <div className="bg-gradient-to-br from-slate-900/90 to-slate-800/30 border border-slate-700/50 rounded-xl p-4">
      <div className="flex items-center gap-2 mb-3">
        <FileText className="w-4 h-4 text-teal-400" />
        <h2 className="font-semibold text-xs tracking-widest uppercase text-slate-400">End-of-Day Executive Summary</h2>
        <Badge className="ml-auto text-[10px] bg-teal-950 border-teal-700/50 text-teal-400">V3 §14</Badge>
      </div>
      {loading ? (
        <div className="space-y-2">
          {[...Array(3)].map((_, i) => <Skeleton key={i} className="h-5 w-full" />)}
        </div>
      ) : (
        <>
          <blockquote className="text-sm text-slate-200 leading-relaxed font-medium italic border-l-4 border-teal-700/60 pl-3 mb-3">
            "{text || "No pipeline activity recorded yet."}"
          </blockquote>
          {p && (
            <div className="grid grid-cols-3 sm:grid-cols-6 gap-2">
              {[
                { label: "Scanned",     value: p.universe_loaded,      tip: "Total stocks in universe" },
                { label: "→ Strategy",  value: p.passed_strategy,       tip: "Passed strategy evaluation" },
                { label: "→ Risk",      value: p.passed_risk,            tip: "Approved by risk gate" },
                { label: "BUY Recs",   value: p.buy_recommendations,    tip: "BUY recommendations generated" },
                { label: "Executed",   value: p.paper_orders_executed,   tip: "Paper orders placed" },
                { label: "Positions",  value: p.open_positions,          tip: "Currently open positions" },
              ].map(k => (
                <div key={k.label} title={k.tip} className="text-center bg-slate-800/30 rounded-lg p-2 cursor-help">
                  <p className="text-base font-bold font-mono text-teal-300">{k.value}</p>
                  <p className="text-[9px] text-slate-500">{k.label}</p>
                </div>
              ))}
            </div>
          )}
        </>
      )}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// §16 Filter Bar
// ─────────────────────────────────────────────────────────────────────────────

export interface FilterState {
  agent: string;
  decision: string;
  minConf: number;
}

export function FilterBar({ filters, onChange }: { filters: FilterState; onChange: (f: FilterState) => void }) {
  return (
    <div className="bg-slate-900/60 border border-slate-800/50 rounded-xl px-4 py-3">
      <div className="flex items-center gap-2 mb-2">
        <Filter className="w-3.5 h-3.5 text-teal-400" />
        <h2 className="font-semibold text-[10px] tracking-widest uppercase text-slate-500">Global Filters</h2>
        <Badge className="ml-auto text-[10px] bg-slate-800 border-slate-700 text-slate-500">V3 §16</Badge>
      </div>
      <div className="flex flex-wrap gap-3 items-end">
        {/* Decision type */}
        <div>
          <label className="text-[10px] text-slate-500 block mb-1">Decision</label>
          <select value={filters.decision}
            onChange={e => onChange({ ...filters, decision: e.target.value })}
            className="bg-slate-800/50 border border-slate-700/40 rounded text-[11px] text-slate-300 px-2 py-1 focus:outline-none">
            {["ALL","BUY","STRONG_BUY","WATCH","HOLD","SELL","AVOID","NO_ACTION"].map(v => (
              <option key={v} value={v}>{v}</option>
            ))}
          </select>
        </div>
        {/* Min confidence */}
        <div>
          <label className="text-[10px] text-slate-500 block mb-1">Min Confidence: {filters.minConf}%</label>
          <input type="range" min={0} max={100} step={5}
            value={filters.minConf}
            onChange={e => onChange({ ...filters, minConf: Number(e.target.value) })}
            className="accent-teal-500 w-28"
          />
        </div>
        {/* Reset */}
        <button onClick={() => onChange({ agent: "ALL", decision: "ALL", minConf: 0 })}
          className="text-[10px] text-slate-500 hover:text-teal-400 flex items-center gap-1 transition-colors">
          <RotateCcw className="w-3 h-3" /> Reset
        </button>
      </div>
    </div>
  );
}
