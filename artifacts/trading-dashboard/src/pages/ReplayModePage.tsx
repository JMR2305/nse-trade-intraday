/**
 * ReplayModePage.tsx — Features 11–16: Operations Centre Replay Mode
 *
 * Feature 11 – Pipeline Replay: animated 9-stage agent flow with IN/OUT counts
 * Feature 12 – Click Any Stock: per-symbol full agent timeline
 * Feature 13 – Agent Thinking Panel: WHY each agent decided
 * Feature 14 – Decision Comparison: AI decision vs actual market outcome
 * Feature 15 – Time Travel Debugger: pause replay at any stage
 * Feature 16 – Replay Summary: executive summary with funnel stats
 */

import { useState, useEffect, useRef, useCallback } from "react";
import { useQuery } from "@tanstack/react-query";
import { apiJson } from "@/lib/api";
import {
  Play, Pause, RotateCcw, ChevronRight, Clock, TrendingUp,
  TrendingDown, AlertTriangle, CheckCircle2, XCircle, Eye,
  Brain, BarChart3, Layers, Zap, Target, ArrowRight, Info,
  ChevronDown, ChevronUp, Award, Activity
} from "lucide-react";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface Session {
  scan_id: string;
  snapshot_ts: string;
  status: string;
  universe_size: number | null;
  symbols_processed: number | null;
  buy_signals: number | null;
  paper_orders: number | null;
  duration_s: number | null;
  is_latest: boolean;
}

interface Stage {
  id: string;
  label: string;
  order: number;
  stocks_in: number;
  stocks_out: number;
  rejected: number;
  pending: number;
  cancelled: number;
  rejected_symbols: string[];
  anomalies?: string[];
  anomaly_count?: number;
  stocks: string[];
  duration_ms: number | null;
  description: string;
  status: string;
  buy_count?: number;
  avoid_count?: number;
  paper_orders?: number;
}

interface SymbolRow {
  symbol: string;
  sector: string | null;
  final_action: string | null;
  confidence: number;
  technical_score: number;
  strategy: string | null;
  all_gates_passed: boolean;
  paper_eligible: boolean;
  data_quality: string | null;
}

interface ReplayData {
  scan_id: string;
  snapshot_ts: string;
  stages: Stage[];
  symbols: SymbolRow[];
  total_symbols: number;
  universe_size: number;
  duration_s: number | null;
  regime: string | null;
}

interface JourneyStep {
  stage: string;
  label: string;
  result: string;
  score: number | null;
  reason: string;
  detail: Record<string, unknown> | null;
}

interface SymbolDetail {
  symbol: string;
  sector: string | null;
  journey: JourneyStep[];
  thinking: {
    strategy_agent: Record<string, unknown>;
    risk_agent: Record<string, unknown>;
    ai_decision_agent: Record<string, unknown>;
  };
  recommendation: {
    final_action: string | null;
    confidence: number;
    opportunity_score: number;
    entry_price: number | null;
    stop_loss: number | null;
    target_price: number | null;
    rr_ratio: number | null;
    strategy: string | null;
  };
}

interface Comparison {
  symbol: string;
  sector: string | null;
  ai_action: string;
  confidence: number;
  entry_price: number | null;
  outcome_pct: number | null;
  status: string;
  strategy: string | null;
}

interface Summary {
  funnel: Record<string, number>;
  performance: { win_rate: number | null; total_trades: number; profitable_trades: number };
  agents: { most_rejections: string; slowest: string; fastest: string; slowest_ms: number | null; fastest_ms: number | null };
  overall_ai_score: number;
  verdict: string;
  scan_duration_s: number | null;
  regime: string | null;
}

// ---------------------------------------------------------------------------
// Tiny helpers
// ---------------------------------------------------------------------------

const fmt = (n: number | null | undefined, digits = 0) =>
  n == null ? "—" : n.toFixed(digits);

const actionColor: Record<string, string> = {
  BUY: "text-emerald-400", SELL: "text-red-400", AVOID: "text-red-400",
  WATCH: "text-amber-400", HOLD: "text-slate-400",
  PASS: "text-emerald-400", FAIL: "text-red-400", WARN: "text-amber-400",
  APPROVED: "text-emerald-400", REJECTED: "text-red-400",
  "PAPER BUY": "text-teal-400", SKIPPED: "text-slate-400", PENDING: "text-slate-400",
};
const actionBg: Record<string, string> = {
  BUY: "bg-emerald-400/15 border-emerald-500/30",
  SELL: "bg-red-400/15 border-red-500/30",
  AVOID: "bg-red-400/15 border-red-500/30",
  WATCH: "bg-amber-400/15 border-amber-500/30",
  HOLD: "bg-slate-400/15 border-slate-500/30",
  PASS: "bg-emerald-400/15 border-emerald-500/30",
  FAIL: "bg-red-400/15 border-red-500/30",
  APPROVED: "bg-emerald-400/15 border-emerald-500/30",
  REJECTED: "bg-red-400/15 border-red-500/30",
  CORRECT: "bg-emerald-400/15 border-emerald-500/30",
  LOSS: "bg-red-400/15 border-red-500/30",
  MISSED_OPPORTUNITY: "bg-amber-400/15 border-amber-500/30",
  CORRECT_AVOID: "bg-teal-400/15 border-teal-500/30",
  NEUTRAL: "bg-slate-400/15 border-slate-500/30",
  PENDING: "bg-slate-700/40 border-slate-600/30",
};

function Badge({ label }: { label: string }) {
  return (
    <span className={`inline-block px-2 py-0.5 text-xs font-semibold rounded border ${actionBg[label] ?? "bg-slate-700/40 border-slate-600"} ${actionColor[label] ?? "text-slate-300"}`}>
      {label}
    </span>
  );
}

function ts(raw: string) {
  if (!raw) return "—";
  try {
    return new Date(raw).toLocaleString("en-IN", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" });
  } catch { return raw; }
}

// ---------------------------------------------------------------------------
// Feature 11 — Animated Pipeline (the "AI thinking" visualiser)
// ---------------------------------------------------------------------------

function PipelineReplay({ stages, onSelectStage }: {
  stages: Stage[];
  onSelectStage: (s: Stage) => void;
}) {
  const [currentIdx, setCurrentIdx] = useState(-1);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(800);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const reset = useCallback(() => {
    setPlaying(false);
    setCurrentIdx(-1);
    if (timerRef.current) clearInterval(timerRef.current);
  }, []);

  const pause = useCallback(() => {
    setPlaying(false);
    if (timerRef.current) clearInterval(timerRef.current);
  }, []);

  const play = useCallback(() => {
    setPlaying(true);
    let idx = currentIdx;
    timerRef.current = setInterval(() => {
      idx++;
      if (idx >= stages.length) {
        clearInterval(timerRef.current!);
        setPlaying(false);
        setCurrentIdx(stages.length);
        return;
      }
      setCurrentIdx(idx);
    }, speed);
  }, [currentIdx, stages.length, speed]);

  useEffect(() => () => { if (timerRef.current) clearInterval(timerRef.current); }, []);

  const complete = currentIdx >= stages.length;
  const stagesDone = Math.min(currentIdx + 1, stages.length);

  return (
    <div className="space-y-6">
      {/* Controls */}
      <div className="flex items-center gap-3 flex-wrap">
        <button
          onClick={playing ? pause : play}
          disabled={complete && !playing}
          className="flex items-center gap-2 px-4 py-2 rounded-lg bg-teal-500 hover:bg-teal-400 text-white text-sm font-semibold disabled:opacity-40 transition-colors"
        >
          {playing ? <Pause size={15} /> : <Play size={15} />}
          {playing ? "Pause" : currentIdx < 0 ? "Replay" : "Resume"}
        </button>
        <button
          onClick={reset}
          className="flex items-center gap-2 px-4 py-2 rounded-lg bg-slate-700 hover:bg-slate-600 text-slate-200 text-sm font-semibold transition-colors"
        >
          <RotateCcw size={15} /> Reset
        </button>
        <div className="flex items-center gap-2 ml-auto text-xs text-slate-400">
          <span>Speed</span>
          {[400, 800, 1500].map(s => (
            <button key={s} onClick={() => setSpeed(s)}
              className={`px-2 py-1 rounded ${speed === s ? "bg-teal-600 text-white" : "bg-slate-700 text-slate-300"}`}>
              {s === 400 ? "Fast" : s === 800 ? "Normal" : "Slow"}
            </button>
          ))}
        </div>
        <span className="text-xs text-slate-400">
          {complete ? "✓ Complete" : currentIdx < 0 ? "Press Replay to start" : `Stage ${stagesDone} / ${stages.length}`}
        </span>
      </div>

      {/* Stage flow */}
      <div className="overflow-x-auto pb-4">
        <div className="flex items-stretch gap-0 min-w-max">
          {stages.map((stage, i) => {
            const done = i <= currentIdx;
            const active = i === currentIdx && playing;
            const future = i > currentIdx;
            return (
              <div key={stage.id} className="flex items-center">
                {/* Stage card */}
                <button
                  onClick={() => onSelectStage(stage)}
                  className={`relative flex flex-col items-center p-4 w-32 rounded-xl border transition-all duration-500 text-center cursor-pointer hover:scale-105
                    ${active ? "bg-teal-500/20 border-teal-400 shadow-lg shadow-teal-400/20 scale-105" :
                      done ? "bg-emerald-500/15 border-emerald-600/50" :
                      "bg-slate-800/60 border-slate-700/50 opacity-50"}`}
                >
                  {active && (
                    <span className="absolute -top-1 -right-1 flex h-3 w-3">
                      <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-teal-400 opacity-75" />
                      <span className="relative inline-flex rounded-full h-3 w-3 bg-teal-500" />
                    </span>
                  )}
                  <div className={`w-8 h-8 rounded-full border-2 flex items-center justify-center mb-2 text-sm font-bold
                    ${active ? "border-teal-400 text-teal-400" :
                      done ? "border-emerald-500 bg-emerald-500/20 text-emerald-400" :
                      "border-slate-600 text-slate-600"}`}>
                    {done && !active ? <CheckCircle2 size={16} /> : stage.order + 1}
                  </div>
                  <p className={`text-xs font-semibold leading-tight mb-1
                    ${active ? "text-teal-300" : done ? "text-emerald-300" : "text-slate-500"}`}>
                    {stage.label}
                  </p>
                  {done && (
                    <div className="space-y-0.5 mt-1 text-left w-full">
                      <div className="flex justify-between"><span className="text-xs text-slate-400">IN</span> <span className="text-xs text-white font-medium">{stage.stocks_in}</span></div>
                      <div className="flex justify-between"><span className="text-xs text-slate-400">OUT</span> <span className={`text-xs font-medium ${stage.id === "ai_decision" ? "text-emerald-400" : "text-white"}`}>{stage.stocks_out}</span></div>
                      {stage.rejected > 0 && <div className="flex justify-between"><span className="text-xs text-red-400/80">REJ</span> <span className="text-xs text-red-400">{stage.rejected}</span></div>}
                      {stage.pending > 0 && <div className="flex justify-between"><span className="text-xs text-amber-400/80">PND</span> <span className="text-xs text-amber-400">{stage.pending}</span></div>}
                      {stage.cancelled > 0 && <div className="flex justify-between"><span className="text-xs text-slate-500">CAN</span> <span className="text-xs text-slate-400">{stage.cancelled}</span></div>}
                    </div>
                  )}
                  {done && stage.duration_ms && (
                    <p className="text-xs text-slate-500 mt-1">{stage.duration_ms > 1000 ? `${(stage.duration_ms / 1000).toFixed(1)}s` : `${stage.duration_ms}ms`}</p>
                  )}
                  {done && (stage.anomaly_count ?? 0) > 0 && (
                    <div className="absolute -top-2 -left-2 bg-red-900 border border-red-500 rounded-full w-6 h-6 flex items-center justify-center text-[10px] font-bold text-red-100 shadow-sm" title={`Anomalies: ${(stage.anomalies ?? []).join(", ")}`}>
                      !{stage.anomaly_count}
                    </div>
                  )}
                </button>
                {/* Connector */}
                {i < stages.length - 1 && (
                  <div className={`flex items-center px-1 transition-colors duration-500 ${i < currentIdx ? "text-emerald-500" : "text-slate-700"}`}>
                    <ArrowRight size={18} />
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </div>

      {/* Stocks moving indicator */}
      {playing && currentIdx >= 0 && currentIdx < stages.length && (
        <div className="bg-slate-800/60 border border-teal-500/30 rounded-xl p-4">
          <p className="text-sm text-teal-300 font-semibold mb-2 flex items-center gap-2">
            <Activity size={14} className="animate-pulse" />
            Processing in {stages[currentIdx]?.label}…
          </p>
          <div className="flex flex-wrap gap-1.5">
            {(stages[currentIdx]?.stocks ?? []).slice(0, 20).map(sym => (
              <span key={sym} className="text-xs bg-teal-900/40 border border-teal-700/40 text-teal-300 px-2 py-0.5 rounded-full animate-pulse">
                {sym}
              </span>
            ))}
            {(stages[currentIdx]?.stocks?.length ?? 0) > 20 && (
              <span className="text-xs text-slate-500">+{(stages[currentIdx]?.stocks?.length ?? 0) - 20} more</span>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Feature 15 — Time Travel Debugger
// ---------------------------------------------------------------------------

function TimeTravelDebugger({ stages, symbols }: { stages: Stage[]; symbols: SymbolRow[] }) {
  const [pausedAt, setPausedAt] = useState(0);
  const stage = stages[pausedAt];

  const stocksAtStage = symbols.filter(s => {
    if (pausedAt < 5) return true; // Before strategy: show all
    if (pausedAt === 5) return s.technical_score > 0; // Strategy: has score
    if (pausedAt === 6) return s.all_gates_passed; // Risk: gates passed
    if (pausedAt === 7) return s.final_action && s.final_action !== "AVOID";
    if (pausedAt === 8) return s.paper_eligible;
    return true;
  });

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3">
        <Clock size={16} className="text-amber-400" />
        <h3 className="text-sm font-semibold text-white">Time Travel Debugger</h3>
        <span className="text-xs text-slate-400">Click any stage to inspect the pipeline at that moment</span>
      </div>

      {/* Stage scrubber */}
      <div className="bg-slate-800/60 border border-slate-700 rounded-xl p-4">
        <div className="flex gap-2 flex-wrap">
          {stages.map((s, i) => (
            <button key={s.id} onClick={() => setPausedAt(i)}
              className={`px-3 py-2 rounded-lg text-xs font-medium transition-colors ${i === pausedAt ? "bg-amber-500/20 border border-amber-500/50 text-amber-300" : "bg-slate-700/50 text-slate-400 hover:text-white"}`}>
              {i + 1}. {s.label}
            </button>
          ))}
        </div>
      </div>

      {/* Paused snapshot */}
      {stage && (
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <div className="md:col-span-1 bg-slate-800/60 border border-slate-700 rounded-xl p-4 space-y-3">
            <h4 className="text-sm font-semibold text-amber-300 flex items-center gap-2">
              <Layers size={14} /> {stage.label} — Snapshot
            </h4>
            <div className="space-y-2 text-sm">
              <div className="flex justify-between"><span className="text-slate-400">Stocks IN</span><span className="text-white font-semibold">{stage.stocks_in}</span></div>
              <div className="flex justify-between"><span className="text-slate-400">Stocks OUT</span><span className="text-emerald-400 font-semibold">{stage.stocks_out}</span></div>
              <div className="flex justify-between"><span className="text-slate-400">Rejected</span><span className="text-red-400 font-semibold">{stage.rejected}</span></div>
              {stage.duration_ms && <div className="flex justify-between"><span className="text-slate-400">Processing</span><span className="text-white">{stage.duration_ms}ms</span></div>}
            </div>
            <p className="text-xs text-slate-500 border-t border-slate-700 pt-2">{stage.description}</p>
            {stage.rejected_symbols.length > 0 && (
              <div>
                <p className="text-xs text-red-400 mb-1">Rejected here:</p>
                <div className="flex flex-wrap gap-1">
                  {stage.rejected_symbols.map(s => (
                    <span key={s} className="text-xs bg-red-900/30 border border-red-700/30 text-red-300 px-1.5 py-0.5 rounded">{s}</span>
                  ))}
                </div>
              </div>
            )}
          </div>

          <div className="md:col-span-2 bg-slate-800/60 border border-slate-700 rounded-xl p-4">
            <h4 className="text-sm font-semibold text-white mb-3">
              {stocksAtStage.length} stocks active at this stage
            </h4>
            <div className="grid grid-cols-2 sm:grid-cols-3 gap-2 max-h-64 overflow-y-auto">
              {stocksAtStage.map(sym => (
                <div key={sym.symbol} className="bg-slate-700/40 border border-slate-600/30 rounded-lg p-2">
                  <p className="text-xs font-semibold text-white">{sym.symbol}</p>
                  <p className="text-xs text-slate-400">{sym.sector ?? "—"}</p>
                  {sym.technical_score > 0 && <p className="text-xs text-teal-400">Score: {sym.technical_score}</p>}
                  {sym.final_action && <Badge label={sym.final_action} />}
                </div>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Feature 12 — Stock Journey modal
// ---------------------------------------------------------------------------

function StockJourneyPanel({ scanId, symbol, onClose }: {
  scanId: string; symbol: string; onClose: () => void;
}) {
  const { data, isLoading } = useQuery<SymbolDetail>({
    queryKey: ["replay-symbol", scanId, symbol],
    queryFn: () => apiJson(`replay/sessions/${encodeURIComponent(scanId)}/symbol/${encodeURIComponent(symbol)}`),
    enabled: !!symbol,
  });

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4">
      <div className="bg-slate-900 border border-slate-700 rounded-2xl w-full max-w-3xl max-h-[90vh] overflow-y-auto shadow-2xl">
        <div className="sticky top-0 bg-slate-900 border-b border-slate-700 p-4 flex items-center justify-between">
          <div>
            <h2 className="text-lg font-bold text-white">{symbol}</h2>
            {data?.sector && <p className="text-xs text-slate-400">{data.sector}</p>}
          </div>
          <div className="flex items-center gap-3">
            {data?.recommendation?.final_action && <Badge label={data.recommendation.final_action} />}
            <button onClick={onClose} className="text-slate-400 hover:text-white text-xl leading-none">&times;</button>
          </div>
        </div>

        {isLoading && <div className="p-8 text-center text-slate-400 text-sm">Loading journey…</div>}

        {data && (
          <div className="p-4 space-y-6">
            {/* Feature 12 — Timeline */}
            <div>
              <h3 className="text-sm font-semibold text-slate-300 mb-3 flex items-center gap-2"><Clock size={13} /> Agent Timeline</h3>
              <div className="space-y-2">
                {data.journey.map((step, i) => (
                  <div key={i} className={`flex gap-3 p-3 rounded-xl border ${actionBg[step.result] ?? "bg-slate-800/40 border-slate-700"}`}>
                    <div className="w-5 flex-shrink-0 pt-0.5">
                      {step.result === "PASS" || step.result === "APPROVED" || step.result === "PAPER BUY" || step.result === "CORRECT"
                        ? <CheckCircle2 size={16} className="text-emerald-400" />
                        : step.result === "FAIL" || step.result === "REJECTED"
                        ? <XCircle size={16} className="text-red-400" />
                        : step.result === "WARN"
                        ? <AlertTriangle size={16} className="text-amber-400" />
                        : <Info size={16} className="text-slate-400" />
                      }
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 mb-0.5">
                        <span className="text-xs font-semibold text-white">{step.label}</span>
                        <Badge label={step.result} />
                        {step.score != null && <span className="text-xs text-slate-400">Score: {step.score}</span>}
                      </div>
                      <p className="text-xs text-slate-400">{step.reason}</p>
                      {step.detail && Object.keys(step.detail).length > 0 && (
                        <div className="mt-1.5 grid grid-cols-2 sm:grid-cols-3 gap-x-4 gap-y-0.5">
                          {Object.entries(step.detail).filter(([, v]) => v != null).map(([k, v]) => (
                            <span key={k} className="text-xs text-slate-500">
                              {k.replace(/_/g, " ")}: <span className="text-slate-300">{String(v)}</span>
                            </span>
                          ))}
                        </div>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            </div>

            {/* Feature 13 — Agent Thinking */}
            {data.thinking && (
              <AgentThinkingPanelInner thinking={data.thinking} />
            )}
          </div>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Feature 13 — Agent Thinking Panel (inline component)
// ---------------------------------------------------------------------------

function AgentThinkingPanelInner({ thinking }: { thinking: SymbolDetail["thinking"] }) {
  const [open, setOpen] = useState<string>("strategy");
  const strategy = thinking.strategy_agent as Record<string, unknown>;
  const risk = thinking.risk_agent as Record<string, unknown>;
  const ai = thinking.ai_decision_agent as Record<string, unknown>;

  const sections = [
    {
      id: "strategy", label: "Strategy Agent", icon: <TrendingUp size={14} />, color: "text-teal-400",
      content: (
        <div className="space-y-3">
          <div className="flex items-center gap-3 flex-wrap">
            <div className="text-center"><p className="text-xs text-slate-400">Strategy</p><p className="text-sm font-semibold text-white">{String(strategy.strategy ?? "—")}</p></div>
            <div className="text-center"><p className="text-xs text-slate-400">Score</p><p className="text-xl font-bold text-teal-400">{String(strategy.score ?? "—")}</p></div>
            <div className="text-center"><p className="text-xs text-slate-400">Confidence</p><p className="text-xl font-bold text-white">{String(strategy.confidence ?? "—")}%</p></div>
            <div className="text-center"><p className="text-xs text-slate-400">Decision</p><Badge label={String(strategy.decision ?? "?")} /></div>
          </div>
          {Array.isArray(strategy.indicators) && (
            <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
              {(strategy.indicators as Array<{ name: string; value: string | number; status: string }>).map(ind => (
                <div key={ind.name} className="bg-slate-800/60 border border-slate-700 rounded-lg p-2">
                  <p className="text-xs text-slate-400">{ind.name}</p>
                  <p className="text-sm font-semibold text-white">{String(ind.value)}</p>
                  <Badge label={ind.status} />
                </div>
              ))}
            </div>
          )}
          {strategy.win_rate != null && (
            <div className="flex gap-4 text-xs text-slate-400">
              <span>Win rate: <strong className="text-white">{Number(strategy.win_rate).toFixed(1)}%</strong></span>
              <span>Profit factor: <strong className="text-white">{fmt(strategy.profit_factor as number | null, 2)}</strong></span>
              <span>Historical trades: <strong className="text-white">{String(strategy.total_historical_trades ?? "—")}</strong></span>
            </div>
          )}
        </div>
      ),
    },
    {
      id: "risk", label: "Risk Agent", icon: <AlertTriangle size={14} />, color: "text-amber-400",
      content: (
        <div className="space-y-3">
          <div className="flex items-center gap-4 flex-wrap">
            <div className="text-center"><p className="text-xs text-slate-400">Position Size</p><p className="text-sm font-semibold text-white">{fmt(risk.position_size_pct as number | null, 1)}%</p></div>
            <div className="text-center"><p className="text-xs text-slate-400">Risk</p><p className="text-sm font-semibold text-red-400">{fmt(risk.risk_pct as number | null, 2)}%</p></div>
            <div className="text-center"><p className="text-xs text-slate-400">R:R Ratio</p><p className="text-sm font-semibold text-white">{fmt(risk.rr_ratio as number | null, 2)}</p></div>
            <div className="text-center"><p className="text-xs text-slate-400">Heat</p><p className="text-sm font-semibold text-white">{fmt(risk.heat as number | null, 2)}</p></div>
            <div className="text-center"><p className="text-xs text-slate-400">Decision</p><Badge label={String(risk.decision ?? "?")} /></div>
          </div>
          {risk.entry_price != null && (
            <div className="grid grid-cols-3 gap-2 text-xs">
              <div className="bg-slate-800/60 border border-slate-700 rounded p-2"><p className="text-slate-400">Entry</p><p className="text-white font-medium">₹{fmt(risk.entry_price as number, 2)}</p></div>
              <div className="bg-red-900/20 border border-red-700/30 rounded p-2"><p className="text-slate-400">Stop Loss</p><p className="text-red-400 font-medium">₹{fmt(risk.stop_loss as number, 2)}</p></div>
              <div className="bg-emerald-900/20 border border-emerald-700/30 rounded p-2"><p className="text-slate-400">Target</p><p className="text-emerald-400 font-medium">₹{fmt(risk.target_price as number, 2)}</p></div>
            </div>
          )}
          {risk.gates != null && typeof risk.gates === "object" && (
            <div>
              <p className="text-xs text-slate-400 mb-1.5">Gate Results</p>
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
                {Object.entries(risk.gates as Record<string, boolean>).map(([gate, passed]) => (
                  <div key={gate} className={`flex items-center gap-1.5 px-2 py-1.5 rounded text-xs font-medium ${passed ? "bg-emerald-900/30 text-emerald-400" : "bg-red-900/30 text-red-400"}`}>
                    {passed ? <CheckCircle2 size={12} /> : <XCircle size={12} />}
                    {gate.replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase())}
                  </div>
                ))}
              </div>
            </div>
          )}
          {!String(risk.decision ?? "").includes("APPROVED") && risk.rejection_reason != null && (
            <p className="text-xs text-red-400 bg-red-900/20 border border-red-700/30 rounded-lg p-2">⚠ {String(risk.rejection_reason)}</p>
          )}
        </div>
      ),
    },
    {
      id: "ai", label: "AI Decision Agent", icon: <Brain size={14} />, color: "text-violet-400",
      content: (
        <div className="space-y-3">
          <div className="flex items-center gap-4 flex-wrap">
            <div className="text-center">
              <p className="text-xs text-slate-400">Decision</p>
              <Badge label={String(ai.decision ?? "?")} />
            </div>
            <div className="text-center"><p className="text-xs text-slate-400">Confidence</p><p className="text-2xl font-bold text-white">{String(ai.confidence ?? "—")}%</p></div>
            <div className="text-center"><p className="text-xs text-slate-400">Opportunity</p><p className="text-xl font-bold text-violet-400">{String(ai.opportunity_score ?? "—")}</p></div>
            <div className="text-center"><p className="text-xs text-slate-400">Holding Days</p><p className="text-sm text-white">{String(ai.holding_days ?? "—")}</p></div>
          </div>
          {Array.isArray(ai.reasons) && (
            <div>
              <p className="text-xs text-slate-400 mb-1.5">Reasoning</p>
              <div className="space-y-1">
                {(ai.reasons as string[]).map((r, i) => (
                  <div key={i} className="flex items-center gap-2 text-sm">
                    <span className="text-emerald-400">✓</span>
                    <span className="text-slate-200">{r}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      ),
    },
  ];

  return (
    <div>
      <h3 className="text-sm font-semibold text-slate-300 mb-3 flex items-center gap-2"><Brain size={13} /> Agent Thinking</h3>
      <div className="space-y-2">
        {sections.map(sec => (
          <div key={sec.id} className="border border-slate-700 rounded-xl overflow-hidden">
            <button
              onClick={() => setOpen(open === sec.id ? "" : sec.id)}
              className="w-full flex items-center justify-between p-3 bg-slate-800/60 hover:bg-slate-800 transition-colors"
            >
              <span className={`flex items-center gap-2 text-sm font-semibold ${sec.color}`}>{sec.icon}{sec.label}</span>
              {open === sec.id ? <ChevronUp size={14} className="text-slate-400" /> : <ChevronDown size={14} className="text-slate-400" />}
            </button>
            {open === sec.id && <div className="p-4 bg-slate-900/40">{sec.content}</div>}
          </div>
        ))}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Feature 14 — Decision Comparison
// ---------------------------------------------------------------------------

function DecisionComparison({ scanId }: { scanId: string }) {
  const { data, isLoading } = useQuery<{ comparisons: Comparison[]; summary: Record<string, number>; scan_id: string }>({
    queryKey: ["replay-comparison", scanId],
    queryFn: () => apiJson(`replay/sessions/${encodeURIComponent(scanId)}/comparison`),
    enabled: !!scanId,
  });

  if (isLoading) return <div className="text-center py-8 text-slate-400 text-sm">Loading comparison…</div>;
  if (!data) return <div className="text-center py-8 text-red-400 text-sm">No data available</div>;

  const summary = data.summary ?? {};

  const statusLabel: Record<string, string> = {
    CORRECT: "✓ Correct", LOSS: "✗ Loss", MISSED_OPPORTUNITY: "⚠ Missed",
    CORRECT_AVOID: "✓ Right AVOID", NEUTRAL: "· Neutral", PENDING: "· Pending",
  };

  return (
    <div className="space-y-4">
      {/* Summary cards */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        {[
          { label: "Correct Calls", value: summary.correct ?? 0, color: "text-emerald-400" },
          { label: "Losses", value: summary.losses ?? 0, color: "text-red-400" },
          { label: "Missed Opps", value: summary.missed_opportunities ?? 0, color: "text-amber-400" },
          { label: "Pending", value: summary.pending ?? 0, color: "text-slate-400" },
        ].map(c => (
          <div key={c.label} className="bg-slate-800/60 border border-slate-700 rounded-xl p-3 text-center">
            <p className={`text-2xl font-bold ${c.color}`}>{c.value}</p>
            <p className="text-xs text-slate-400">{c.label}</p>
          </div>
        ))}
      </div>

      {/* Table */}
      <div className="bg-slate-800/60 border border-slate-700 rounded-xl overflow-hidden flex flex-col max-h-96">
        <div className="overflow-x-auto overflow-y-auto flex-1">
          <table className="w-full text-xs">
            <thead className="sticky top-0 bg-slate-900 z-10">
              <tr className="border-b border-slate-700 text-slate-400">
                <th className="text-left p-3">Symbol</th>
                <th className="text-left p-3">AI Action</th>
                <th className="text-left p-3">Confidence</th>
                <th className="text-left p-3">Entry Price</th>
                <th className="text-left p-3">Outcome</th>
                <th className="text-left p-3">Status</th>
                <th className="text-left p-3">Strategy</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-700/50">
              {data.comparisons.map(c => (
                <tr key={c.symbol} className="hover:bg-slate-700/20">
                  <td className="p-3 font-semibold text-white">{c.symbol}</td>
                  <td className="p-3"><Badge label={c.ai_action} /></td>
                  <td className="p-3 text-slate-300">{c.confidence}%</td>
                  <td className="p-3 text-slate-300">{c.entry_price ? `₹${c.entry_price.toFixed(2)}` : "—"}</td>
                  <td className={`p-3 font-semibold ${c.outcome_pct == null ? "text-slate-500" : c.outcome_pct >= 0 ? "text-emerald-400" : "text-red-400"}`}>
                    {c.outcome_pct != null ? `${c.outcome_pct >= 0 ? "+" : ""}${c.outcome_pct.toFixed(2)}%` : "—"}
                  </td>
                  <td className="p-3"><span className={`font-medium ${actionColor[c.status] ?? "text-slate-400"}`}>{statusLabel[c.status] ?? c.status}</span></td>
                  <td className="p-3 text-slate-400 max-w-[100px] truncate">{c.strategy ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Feature 16 — Replay Summary
// ---------------------------------------------------------------------------

function ReplaySummary({ scanId }: { scanId: string }) {
  const { data, isLoading } = useQuery<Summary>({
    queryKey: ["replay-summary", scanId],
    queryFn: () => apiJson(`replay/sessions/${encodeURIComponent(scanId)}/summary`),
    enabled: !!scanId,
  });

  if (isLoading) return <div className="text-center py-8 text-slate-400 text-sm">Generating summary…</div>;
  if (!data) return <div className="text-center py-8 text-red-400 text-sm">No data</div>;

  const f = data.funnel ?? {};
  const funnelSteps = [
    { label: "Stocks Scanned", value: f.scanned ?? 0, icon: "📡" },
    { label: "Passed Market Data", value: f.passed_market_data ?? 0, icon: "📊" },
    { label: "Passed Research", value: f.passed_research ?? 0, icon: "🔬" },
    { label: "Passed Market Intel", value: f.passed_market_intelligence ?? 0, icon: "🧠" },
    { label: "Passed Strategy", value: f.passed_strategy ?? 0, icon: "📈" },
    { label: "BUY Candidates", value: f.buy_candidates ?? 0, icon: "✅" },
    { label: "Risk Approved", value: f.risk_approved ?? 0, icon: "🛡️" },
    { label: "Paper Trades", value: f.paper_trades ?? 0, icon: "FileText" },
  ];
  const total = f.scanned || 1;
  const perf = data.performance ?? {};
  const agents = data.agents ?? {};
  const isReady = (data.verdict ?? "").toLowerCase().includes("ready");

  return (
    <div className="space-y-6">
      {/* Verdict */}
      <div className={`rounded-2xl border p-5 flex items-center gap-4 ${isReady ? "bg-emerald-900/20 border-emerald-600/40" : "bg-amber-900/20 border-amber-600/40"}`}>
        <div className={`p-3 rounded-full ${isReady ? "bg-emerald-900/40 text-emerald-400" : "bg-amber-900/40 text-amber-400"}`}>
          {isReady ? <CheckCircle2 size={24} /> : <AlertTriangle size={24} />}
        </div>
        <div>
          <p className={`text-lg font-bold ${isReady ? "text-emerald-300" : "text-amber-300"}`}>{data.verdict}</p>
          <p className="text-sm text-slate-400">AI Score: <strong className="text-white">{data.overall_ai_score ?? "—"}/100</strong>
            {data.regime && <> · Regime: <strong className="text-white">{data.regime}</strong></>}
            {data.scan_duration_s && <> · Duration: <strong className="text-white">{data.scan_duration_s.toFixed(1)}s</strong></>}
          </p>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Funnel */}
        <div className="bg-slate-800/60 border border-slate-700 rounded-xl p-4">
          <h3 className="text-sm font-semibold text-white mb-4 flex items-center gap-2"><BarChart3 size={14} /> Pipeline Funnel</h3>
          <div className="space-y-2">
            {funnelSteps.map((step, i) => {
              const pct = Math.round((step.value / total) * 100);
              return (
                <div key={i}>
                  <div className="flex justify-between items-center mb-0.5">
                    <span className="text-xs text-slate-300">{step.icon} {step.label}</span>
                    <span className="text-xs font-semibold text-white">{step.value} <span className="text-slate-500">({pct}%)</span></span>
                  </div>
                  <div className="h-2 bg-slate-700 rounded-full overflow-hidden">
                    <div
                      className="h-full rounded-full transition-all"
                      style={{
                        width: `${pct}%`,
                        backgroundColor: i < 3 ? "#14b8a6" : i < 5 ? "#3b82f6" : "#10b981",
                      }}
                    />
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        {/* Stats */}
        <div className="space-y-4">
          {/* Performance */}
          <div className="bg-slate-800/60 border border-slate-700 rounded-xl p-4">
            <h3 className="text-sm font-semibold text-white mb-3 flex items-center gap-2"><Award size={14} /> Performance</h3>
            <div className="grid grid-cols-3 gap-3 text-center">
              <div><p className="text-xl font-bold text-white">{perf.win_rate != null ? `${perf.win_rate}%` : "—"}</p><p className="text-xs text-slate-400">Win Rate</p></div>
              <div><p className="text-xl font-bold text-teal-400">{perf.profitable_trades ?? "—"}</p><p className="text-xs text-slate-400">Profitable</p></div>
              <div><p className="text-xl font-bold text-white">{perf.total_trades ?? "—"}</p><p className="text-xs text-slate-400">Total Trades</p></div>
            </div>
          </div>

          {/* Agent stats */}
          <div className="bg-slate-800/60 border border-slate-700 rounded-xl p-4">
            <h3 className="text-sm font-semibold text-white mb-3 flex items-center gap-2"><Zap size={14} /> Agent Stats</h3>
            <div className="space-y-2 text-xs">
              <div className="flex justify-between"><span className="text-slate-400">Most Rejections</span><span className="text-red-400 font-semibold">{agents.most_rejections ?? "—"}</span></div>
              <div className="flex justify-between"><span className="text-slate-400">Slowest Agent</span>
                <span className="text-amber-400 font-semibold">{agents.slowest ?? "—"}{agents.slowest_ms ? ` (${agents.slowest_ms}ms)` : ""}</span>
              </div>
              <div className="flex justify-between"><span className="text-slate-400">Fastest Agent</span>
                <span className="text-emerald-400 font-semibold">{agents.fastest ?? "—"}{agents.fastest_ms ? ` (${agents.fastest_ms}ms)` : ""}</span>
              </div>
              <div className="flex justify-between"><span className="text-slate-400">Overall AI Score</span>
                <span className={`font-bold text-base ${(data.overall_ai_score ?? 0) >= 70 ? "text-emerald-400" : "text-amber-400"}`}>{data.overall_ai_score ?? "—"}/100</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Stock list — Feature 12 entry point
// ---------------------------------------------------------------------------

function StockList({ symbols, onSelect }: { symbols: SymbolRow[]; onSelect: (sym: string) => void }) {
  const [filter, setFilter] = useState<string>("ALL");
  const [search, setSearch] = useState("");

  const filtered = symbols.filter(s => {
    const matchAction = filter === "ALL" || s.final_action === filter;
    const matchSearch = !search || s.symbol.toLowerCase().includes(search.toLowerCase()) ||
      (s.sector ?? "").toLowerCase().includes(search.toLowerCase());
    return matchAction && matchSearch;
  });

  const filters = ["ALL", "BUY", "WATCH", "HOLD", "AVOID"];

  return (
    <div className="space-y-3">
      <div className="flex gap-2 flex-wrap items-center">
        <input
          value={search} onChange={e => setSearch(e.target.value)} placeholder="Search symbol or sector…"
          className="flex-1 min-w-48 bg-slate-800 border border-slate-700 rounded-lg px-3 py-1.5 text-sm text-white placeholder-slate-500 focus:outline-none focus:border-teal-500"
        />
        {filters.map(f => (
          <button key={f} onClick={() => setFilter(f)}
            className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${filter === f ? "bg-teal-600 text-white" : "bg-slate-700 text-slate-400 hover:text-white"}`}>
            {f}
          </button>
        ))}
      </div>
      <div className="text-xs text-slate-500">{filtered.length} stocks · click to inspect full journey</div>
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-2 max-h-96 overflow-y-auto">
        {filtered.map(sym => (
          <button key={sym.symbol} onClick={() => onSelect(sym.symbol)}
            className="flex items-center justify-between p-3 bg-slate-800/60 hover:bg-slate-700/60 border border-slate-700 hover:border-teal-600/50 rounded-xl text-left transition-colors group">
            <div>
              <p className="text-sm font-semibold text-white group-hover:text-teal-300">{sym.symbol}</p>
              <p className="text-xs text-slate-500">{sym.sector ?? "—"}</p>
              {sym.strategy && <p className="text-xs text-slate-400 truncate max-w-[120px]">{sym.strategy}</p>}
            </div>
            <div className="text-right space-y-1">
              {sym.final_action && <Badge label={sym.final_action} />}
              <p className="text-xs text-slate-400">{sym.confidence}%</p>
              {sym.paper_eligible && <p className="text-xs text-teal-400">Paper Eligible</p>}
            </div>
          </button>
        ))}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

const TABS = [
  { id: "pipeline", label: "Pipeline Replay", icon: <Play size={13} />, feature: 11 },
  { id: "stocks", label: "Stock Journey", icon: <Eye size={13} />, feature: 12 },
  { id: "thinking", label: "Agent Thinking", icon: <Brain size={13} />, feature: 13 },
  { id: "comparison", label: "Decision Comparison", icon: <BarChart3 size={13} />, feature: 14 },
  { id: "timetravel", label: "Time Travel", icon: <Clock size={13} />, feature: 15 },
  { id: "summary", label: "Summary", icon: <Target size={13} />, feature: 16 },
] as const;

type Tab = (typeof TABS)[number]["id"];

export default function ReplayModePage() {
  const [activeTab, setActiveTab] = useState<Tab>("pipeline");
  const [selectedScanId, setSelectedScanId] = useState<string>("latest");
  const [selectedStage, setSelectedStage] = useState<Stage | null>(null);
  const [journeySymbol, setJourneySymbol] = useState<string | null>(null);
  const [thinkingSymbol, setThinkingSymbol] = useState<string>("");

  const { data: sessions } = useQuery<{ sessions: Session[] }>({
    queryKey: ["replay-sessions"],
    queryFn: () => apiJson("replay/sessions"),
    staleTime: 60_000,
  });

  const { data: replay, isLoading: replayLoading } = useQuery<ReplayData>({
    queryKey: ["replay-build", selectedScanId],
    queryFn: () => apiJson(`replay/sessions/${encodeURIComponent(selectedScanId)}`),
    enabled: !!selectedScanId,
    staleTime: 60_000,
  });

  const thinkingData = useQuery<SymbolDetail>({
    queryKey: ["replay-symbol", selectedScanId, thinkingSymbol],
    queryFn: () => apiJson(`replay/sessions/${encodeURIComponent(selectedScanId)}/symbol/${encodeURIComponent(thinkingSymbol)}`),
    enabled: !!thinkingSymbol && activeTab === "thinking",
    staleTime: 60_000,
  });

  const handleStageSelect = useCallback((stage: Stage) => {
    setSelectedStage(stage);
    setActiveTab("timetravel");
  }, []);

  const stages = replay?.stages ?? [];
  const symbols = replay?.symbols ?? [];

  return (
    <div className="min-h-screen bg-slate-950 text-white">
      <div className="max-w-screen-2xl mx-auto px-4 py-6 space-y-6">

        {/* Header */}
        <div className="flex items-start justify-between flex-wrap gap-4">
          <div>
            <div className="flex items-center gap-3 mb-1">
              <div className="w-8 h-8 rounded-lg bg-teal-600/20 border border-teal-500/30 flex items-center justify-center">
                <Play size={16} className="text-teal-400" />
              </div>
              <h1 className="text-2xl font-bold text-white">Operations Centre — Replay Mode</h1>
            </div>
            <p className="text-sm text-slate-400 ml-11">Watch the AI pipeline think in real-time · Debug any decision · Compare outcomes</p>
          </div>

          {/* Session selector */}
          <div className="flex items-center gap-3">
            <span className="text-xs text-slate-400">Session</span>
            <select
              value={selectedScanId}
              onChange={e => setSelectedScanId(e.target.value)}
              className="bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-teal-500 min-w-56"
            >
              {(sessions?.sessions ?? []).map(s => (
                <option key={s.scan_id} value={s.scan_id}>
                  {s.is_latest ? "★ " : ""}{ts(s.snapshot_ts)}
                  {s.universe_size ? ` · ${s.universe_size} stocks` : ""}
                  {s.buy_signals != null ? ` · ${s.buy_signals} BUY` : ""}
                </option>
              ))}
              {!sessions?.sessions?.length && <option value="latest">Latest Scan</option>}
            </select>
          </div>
        </div>

        {/* Scan meta strip */}
        {replay && (
          <div className="grid grid-cols-2 sm:grid-cols-5 gap-3">
            {[
              { label: "Universe", value: replay.universe_size || "—", color: "text-white" },
              { label: "Evaluated", value: replay.total_symbols || "—", color: "text-white" },
              { label: "BUY Signals", value: stages.find(s => s.id === "ai_decision")?.buy_count ?? "—", color: "text-emerald-400" },
              { label: "Paper Orders", value: stages.find(s => s.id === "execution")?.paper_orders ?? "—", color: "text-teal-400" },
              { label: "Duration", value: replay.duration_s ? `${replay.duration_s.toFixed(1)}s` : "—", color: "text-slate-300" },
            ].map(m => (
              <div key={m.label} className="bg-slate-800/50 border border-slate-700 rounded-xl px-4 py-3 text-center">
                <p className={`text-xl font-bold ${m.color}`}>{String(m.value)}</p>
                <p className="text-xs text-slate-400">{m.label}</p>
              </div>
            ))}
          </div>
        )}

        {/* Tab bar */}
        <div className="flex gap-1 bg-slate-900/60 border border-slate-700 rounded-xl p-1 overflow-x-auto">
          {TABS.map(tab => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={`flex items-center gap-1.5 px-3 py-2 rounded-lg text-xs font-semibold whitespace-nowrap transition-colors ${activeTab === tab.id ? "bg-teal-600 text-white" : "text-slate-400 hover:text-white hover:bg-slate-700/50"}`}
            >
              {tab.icon}
              {tab.label}
              <span className={`text-[10px] px-1.5 py-0.5 rounded-full ${activeTab === tab.id ? "bg-teal-500/40 text-teal-100" : "bg-slate-700 text-slate-500"}`}>F{tab.feature}</span>
            </button>
          ))}
        </div>

        {/* Tab content */}
        <div className="bg-slate-900/40 border border-slate-700/60 rounded-2xl p-6">
          {replayLoading && (
            <div className="text-center py-12 text-slate-400">
              <Activity size={24} className="mx-auto mb-2 animate-spin text-teal-400" />
              <p className="text-sm">Loading scan replay…</p>
            </div>
          )}

          {!replayLoading && activeTab === "pipeline" && (
            <PipelineReplay stages={stages} onSelectStage={handleStageSelect} />
          )}

          {!replayLoading && activeTab === "stocks" && (
            <div className="space-y-4">
              <div className="flex items-center gap-2 text-sm">
                <Eye size={14} className="text-teal-400" />
                <h2 className="font-semibold text-white">Click Any Stock to See Its Full Journey</h2>
                <span className="text-slate-400">— Feature 12</span>
              </div>
              <StockList symbols={symbols} onSelect={sym => setJourneySymbol(sym)} />
            </div>
          )}

          {!replayLoading && activeTab === "thinking" && (
            <div className="space-y-4">
              <div className="flex items-center gap-2 text-sm">
                <Brain size={14} className="text-violet-400" />
                <h2 className="font-semibold text-white">Agent Thinking Panel</h2>
                <span className="text-slate-400">— Feature 13 · Select a symbol to inspect</span>
              </div>
              <div className="flex gap-2 flex-wrap">
                {symbols.filter(s => s.final_action === "BUY" || s.paper_eligible).slice(0, 12).map(sym => (
                  <button key={sym.symbol} onClick={() => setThinkingSymbol(sym.symbol)}
                    className={`px-3 py-1.5 rounded-lg text-xs font-semibold border transition-colors ${thinkingSymbol === sym.symbol ? "bg-violet-600/30 border-violet-500/50 text-violet-300" : "bg-slate-800 border-slate-700 text-slate-300 hover:border-violet-500/30"}`}>
                    {sym.symbol}
                  </button>
                ))}
                {symbols.length > 12 && (
                  <select onChange={e => setThinkingSymbol(e.target.value)} value={thinkingSymbol}
                    className="bg-slate-800 border border-slate-700 rounded-lg px-2 py-1 text-xs text-white focus:outline-none">
                    <option value="">More symbols…</option>
                    {symbols.slice(12).map(s => <option key={s.symbol} value={s.symbol}>{s.symbol}</option>)}
                  </select>
                )}
              </div>
              {thinkingData.isLoading && <div className="text-center py-6 text-slate-400 text-sm">Loading agent thinking…</div>}
              {thinkingData.data && <AgentThinkingPanelInner thinking={thinkingData.data.thinking} />}
              {!thinkingSymbol && <div className="text-center py-8 text-slate-500 text-sm">Select a symbol above to see why each agent made its decision</div>}
            </div>
          )}

          {!replayLoading && activeTab === "comparison" && (
            <div className="space-y-4">
              <div className="flex items-center gap-2 text-sm">
                <TrendingUp size={14} className="text-amber-400" />
                <h2 className="font-semibold text-white">AI Decision vs Actual Market Outcome</h2>
                <span className="text-slate-400">— Feature 14</span>
              </div>
              <DecisionComparison scanId={selectedScanId} />
            </div>
          )}

          {!replayLoading && activeTab === "timetravel" && (
            <div className="space-y-4">
              <div className="flex items-center gap-2 text-sm">
                <Clock size={14} className="text-amber-400" />
                <h2 className="font-semibold text-white">Time Travel Debugger</h2>
                <span className="text-slate-400">— Feature 15 · Pause and inspect any agent stage</span>
              </div>
              <TimeTravelDebugger stages={stages} symbols={symbols} />
            </div>
          )}

          {!replayLoading && activeTab === "summary" && (
            <div className="space-y-4">
              <div className="flex items-center gap-2 text-sm">
                <Target size={14} className="text-emerald-400" />
                <h2 className="font-semibold text-white">Replay Executive Summary</h2>
                <span className="text-slate-400">— Feature 16</span>
              </div>
              <ReplaySummary scanId={selectedScanId} />
            </div>
          )}
        </div>
      </div>

      {/* Feature 12 — Stock Journey modal */}
      {journeySymbol && (
        <StockJourneyPanel
          scanId={selectedScanId}
          symbol={journeySymbol}
          onClose={() => setJourneySymbol(null)}
        />
      )}
    </div>
  );
}
