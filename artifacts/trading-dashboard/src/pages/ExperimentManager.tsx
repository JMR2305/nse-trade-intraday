/**
 * ExperimentManager.tsx — Phase 4 + 4.1 Research Factory.
 *
 * 4 tabs:
 *   Templates  — 8 ready-to-run template families (5 market conditions + 3 sweeps)
 *   Queue      — submit custom experiments + live queue list
 *   Batches    — sequential batch runner with progress, elapsed time, cancel
 *   Leaderboard — ranked results with grouped/comparison views + CSV/JSON export
 *
 * Paper trading and research only.  No look-ahead bias.
 * No auto-promotion.  No live orders affected.
 */
import { useState, useEffect, useCallback } from "react";
import {
  Card, CardContent, CardHeader, CardTitle,
} from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import {
  FlaskConical, Loader2, Play, Trash2, ChevronDown, ChevronRight,
  Trophy, AlertTriangle, CheckCircle2, Clock, XCircle,
  BarChart3, Plus, RefreshCw, BookTemplate, Layers, Download,
  TestTubes,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useToast } from "@/hooks/use-toast";
import {
  ExperimentTemplates,
  type ExistingExperiment,
} from "@/pages/experiments/ExperimentTemplates";
import { BatchQueue } from "@/pages/experiments/BatchQueue";
import { ResearchReport } from "@/pages/experiments/ResearchReport";

/* eslint-disable @typescript-eslint/no-explicit-any */

import { API_BASE, apiJson } from "@/lib/api";

type Tab = "templates" | "queue" | "batches" | "leaderboard";
type LeaderboardView = "all" | "family" | "compare";

// ── Types ──────────────────────────────────────────────────────────────────

interface ConfigSummary {
  train_years: number;
  test_months: number;
  step_months: number;
  start_date: string;
  end_date: string;
  universe_size: number;
  intrabar_rule: string;
  max_holding_days: number;
  min_confidence_execute?: number;
}

interface Metrics {
  total_trades?: number;
  total_return_pct?: number;
  net_pnl?: number;
  win_rate?: number;
  profit_factor?: number;
  expectancy?: number;
  sharpe?: number;
  max_drawdown_pct?: number;
  brier_score?: number;
  ece?: number;
  ev_verdict?: string;
  ev_trades?: number;
  windows?: number;
  verdict?: string;
}

interface Experiment {
  id: string;
  name: string;
  description: string;
  tags: string[];
  status: "queued" | "running" | "completed" | "rejected" | "failed";
  created_at: string;
  started_at?: string;
  completed_at?: string;
  verdict?: string;
  score?: number;
  score_breakdown?: Record<string, number>;
  overfitting_flags?: string[];
  auto_rejected?: boolean;
  metrics?: Metrics;
  config_summary?: ConfigSummary;
  canonical_config?: any;
  config_hash?: string;
  batch_id?: string;
  batch_name?: string;
  batch_index?: number;
  template_id?: string;
  template_family?: string;
  wf_progress?: any;
  error?: string;
  trace?: string;
  exec_log?: { ts: string; msg: string }[];
}

interface LeaderboardEntry extends Experiment {
  score: number;
}

// ── Shared helpers ─────────────────────────────────────────────────────────

function fmtPct(v?: number | null) {
  if (v == null) return "—";
  return `${v.toFixed(2)}%`;
}
function fmtNum(v?: number | null, d = 2) {
  if (v == null) return "—";
  return v.toFixed(d);
}
function fmtINR(v?: number | null) {
  if (v == null) return "—";
  return `₹${v.toFixed(0)}`;
}
function timeAgo(iso?: string) {
  if (!iso) return "";
  const ms = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(ms / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.floor(hrs / 24)}d ago`;
}

function statusBadge(status: Experiment["status"]) {
  switch (status) {
    case "queued":    return <Badge variant="outline" className="text-zinc-400 border-zinc-600 font-mono text-[10px]"><Clock className="h-3 w-3 mr-1" />Queued</Badge>;
    case "running":   return <Badge variant="outline" className="text-sky-400 border-sky-500 font-mono text-[10px] animate-pulse"><Loader2 className="h-3 w-3 mr-1 animate-spin" />Running</Badge>;
    case "completed": return <Badge variant="outline" className="text-emerald-400 border-emerald-600 font-mono text-[10px]"><CheckCircle2 className="h-3 w-3 mr-1" />Completed</Badge>;
    case "rejected":  return <Badge variant="outline" className="text-amber-400 border-amber-600 font-mono text-[10px]"><AlertTriangle className="h-3 w-3 mr-1" />Rejected</Badge>;
    case "failed":    return <Badge variant="outline" className="text-red-400 border-red-600 font-mono text-[10px]"><XCircle className="h-3 w-3 mr-1" />Failed</Badge>;
  }
}

function verdictBadge(v?: string) {
  if (!v) return null;
  const cls: Record<string, string> = {
    PASS: "text-emerald-400 border-emerald-600",
    INCONCLUSIVE: "text-amber-400 border-amber-600",
    FAIL: "text-red-400 border-red-600",
    INSUFFICIENT_DATA: "text-zinc-400 border-zinc-600",
  };
  return <Badge variant="outline" className={cn("font-mono text-[10px]", cls[v] ?? "text-zinc-400")}>{v}</Badge>;
}

function rankMedal(rank: number) {
  if (rank === 1) return <span className="text-yellow-400 font-bold text-sm">🥇</span>;
  if (rank === 2) return <span className="text-zinc-300 font-bold text-sm">🥈</span>;
  if (rank === 3) return <span className="text-amber-600 font-bold text-sm">🥉</span>;
  return <span className="text-zinc-500 font-mono text-xs">#{rank}</span>;
}

const FAMILY_LABELS: Record<string, string> = {
  market_conditions: "Market Conditions",
  confidence_sweep:  "Confidence Sweep",
  holding_sweep:     "Holding-Period Sweep",
  window_sweep:      "Window Sweep",
};

// ── ScoreBar ───────────────────────────────────────────────────────────────

function ScoreBar({ score, breakdown }: { score: number; breakdown?: Record<string, number> }) {
  const pct = Math.min(100, score);
  const color = score >= 60 ? "bg-emerald-500" : score >= 35 ? "bg-amber-500" : "bg-red-500";
  return (
    <div className="space-y-1">
      <div className="flex items-center gap-2">
        <div className="flex-1 h-2 bg-zinc-700 rounded-full overflow-hidden">
          <div className={cn("h-full rounded-full transition-all", color)} style={{ width: `${pct}%` }} />
        </div>
        <span className="text-xs font-mono font-bold tabular-nums">
          {score.toFixed(1)}<span className="text-zinc-500">/100</span>
        </span>
      </div>
      {breakdown && (
        <div className="flex flex-wrap gap-1">
          {([ ["PF", breakdown.profit_factor, 25], ["Exp", breakdown.expectancy, 20],
              ["Sharpe", breakdown.sharpe, 20], ["DD", breakdown.drawdown, 15],
              ["Cal", breakdown.calibration, 10], ["Evid", breakdown.evidence, 10],
          ] as [string, number, number][]).map(([lbl, val, max]) => (
            <span key={lbl} className="text-[9px] font-mono text-zinc-400">
              {lbl} <span className="text-zinc-200">{Number(val ?? 0).toFixed(0)}</span>/{max}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

// ── SubmitForm ─────────────────────────────────────────────────────────────

const PRESETS = [
  { id: "standard", label: "Standard", desc: "1yr/3mo — baseline", config: { train_years:"1",test_months:"3",step_months:"3",start_date:"",end_date:"",universe_size:"0",max_holding_days:"20",intrabar_rule:"conservative",min_confidence_execute:"55" } },
  { id: "long",     label: "Long Evidence", desc: "2yr/3mo — for PASS",   config: { train_years:"2",test_months:"3",step_months:"3",start_date:"",end_date:"",universe_size:"0",max_holding_days:"20",intrabar_rule:"conservative",min_confidence_execute:"55" } },
  { id: "wide",     label: "Wide Sweep",  desc: "1yr/6mo — fewer windows", config: { train_years:"1",test_months:"6",step_months:"6",start_date:"",end_date:"",universe_size:"0",max_holding_days:"20",intrabar_rule:"conservative",min_confidence_execute:"55" } },
  { id: "custom",   label: "Custom",      desc: "Manual config",           config: {} },
];
const DEFAULT_FORM = { name:"",description:"",tags:"",train_years:"1",test_months:"3",step_months:"3",start_date:"",end_date:"",universe_size:"0",max_holding_days:"20",intrabar_rule:"conservative",min_confidence_execute:"55" };

type FormConfig = typeof DEFAULT_FORM;

function SubmitForm({ onSubmitted }: { onSubmitted: () => void }) {
  const { toast } = useToast();
  const [open, setOpen] = useState(false);
  const [preset, setPreset] = useState("standard");
  const [form, setForm] = useState<FormConfig>({ ...DEFAULT_FORM, ...PRESETS[0].config });
  const [submitting, setSubmitting] = useState(false);

  function applyPreset(pid: string) {
    const p = PRESETS.find(x => x.id === pid);
    if (!p) return;
    setPreset(pid);
    setForm(f => ({ ...f, ...p.config }));
  }
  function set(k: keyof FormConfig, v: string) { setForm(f => ({ ...f, [k]: v })); }

  async function handleSubmit() {
    if (!form.name.trim()) {
      toast({ title: "Name required", variant: "destructive" });
      return;
    }
    setSubmitting(true);
    try {
      const data = await apiJson("/experiments", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: form.name.trim(), description: form.description.trim(),
          tags: form.tags.split(",").map(t => t.trim()).filter(Boolean),
          train_years: parseInt(form.train_years), test_months: parseInt(form.test_months),
          step_months: parseInt(form.step_months), start_date: form.start_date.trim() || null,
          end_date: form.end_date.trim() || null, universe_size: parseInt(form.universe_size)||0,
          max_holding_days: parseInt(form.max_holding_days)||20, intrabar_rule: form.intrabar_rule,
          min_confidence_execute: parseFloat(form.min_confidence_execute)||55,
        }),
      });
      const expId = data?.experiment?.id || data?.id || "";
      toast({ title: "Experiment queued", description: `"${form.name}"${expId ? ` (${expId})` : ""} added.` });
      setForm({ ...DEFAULT_FORM, ...PRESETS.find(x => x.id === preset)?.config });
      setOpen(false);
      onSubmitted();
    } catch (e) {
      toast({ title: "Submit failed", description: String(e), variant: "destructive" });
    } finally { setSubmitting(false); }
  }

  return (
    <Card>
      <CardHeader className="py-3 cursor-pointer" onClick={() => setOpen(o => !o)}>
        <CardTitle className="text-sm font-mono flex items-center gap-2">
          <Plus className="h-4 w-4 text-emerald-400" />
          Custom Experiment
          {open ? <ChevronDown className="h-4 w-4 ml-auto text-zinc-500" /> : <ChevronRight className="h-4 w-4 ml-auto text-zinc-500" />}
        </CardTitle>
      </CardHeader>
      {open && (
        <CardContent className="pt-0 space-y-3">
          <div className="flex flex-wrap gap-1.5">
            {PRESETS.map(p => (
              <button key={p.id} onClick={() => applyPreset(p.id)}
                className={cn("px-2.5 py-1 rounded text-[11px] font-mono border transition-colors",
                  preset === p.id ? "bg-violet-600 border-violet-500 text-white" : "border-zinc-700 text-zinc-400 hover:border-zinc-500")}>
                {p.label}
              </button>
            ))}
          </div>
          <div className="grid grid-cols-2 gap-2">
            <div>
              <Label className="text-[10px] font-mono text-zinc-400 mb-1 block">NAME *</Label>
              <Input className="h-8 font-mono text-xs" value={form.name} onChange={e => set("name", e.target.value)} placeholder="Experiment name" />
            </div>
            <div>
              <Label className="text-[10px] font-mono text-zinc-400 mb-1 block">TAGS</Label>
              <Input className="h-8 font-mono text-xs" value={form.tags} onChange={e => set("tags", e.target.value)} placeholder="tag1, tag2" />
            </div>
          </div>
          <div className="grid grid-cols-3 gap-2">
            <div>
              <Label className="text-[10px] font-mono text-zinc-400 mb-1 block">TRAIN</Label>
              <Select value={form.train_years} onValueChange={v => set("train_years", v)}>
                <SelectTrigger className="h-8 font-mono text-xs"><SelectValue /></SelectTrigger>
                <SelectContent>{[1,2,3].map(n => <SelectItem key={n} value={String(n)}>{n}yr</SelectItem>)}</SelectContent>
              </Select>
            </div>
            <div>
              <Label className="text-[10px] font-mono text-zinc-400 mb-1 block">TEST</Label>
              <Select value={form.test_months} onValueChange={v => set("test_months", v)}>
                <SelectTrigger className="h-8 font-mono text-xs"><SelectValue /></SelectTrigger>
                <SelectContent>{[1,2,3,6].map(n => <SelectItem key={n} value={String(n)}>{n}mo</SelectItem>)}</SelectContent>
              </Select>
            </div>
            <div>
              <Label className="text-[10px] font-mono text-zinc-400 mb-1 block">STEP</Label>
              <Select value={form.step_months} onValueChange={v => set("step_months", v)}>
                <SelectTrigger className="h-8 font-mono text-xs"><SelectValue /></SelectTrigger>
                <SelectContent>{[1,2,3,6].map(n => <SelectItem key={n} value={String(n)}>{n}mo</SelectItem>)}</SelectContent>
              </Select>
            </div>
          </div>
          <div className="grid grid-cols-2 gap-2">
            <div>
              <Label className="text-[10px] font-mono text-zinc-400 mb-1 block">START (optional)</Label>
              <Input className="h-8 font-mono text-xs" value={form.start_date} onChange={e => set("start_date", e.target.value)} placeholder="2021-10-01" />
            </div>
            <div>
              <Label className="text-[10px] font-mono text-zinc-400 mb-1 block">END (optional)</Label>
              <Input className="h-8 font-mono text-xs" value={form.end_date} onChange={e => set("end_date", e.target.value)} placeholder="2023-03-31" />
            </div>
          </div>
          <div className="grid grid-cols-3 gap-2">
            <div>
              <Label className="text-[10px] font-mono text-zinc-400 mb-1 block">MAX HOLD</Label>
              <Input className="h-8 font-mono text-xs" value={form.max_holding_days} onChange={e => set("max_holding_days", e.target.value)} />
            </div>
            <div>
              <Label className="text-[10px] font-mono text-zinc-400 mb-1 block">CONF %</Label>
              <Input className="h-8 font-mono text-xs" value={form.min_confidence_execute} onChange={e => set("min_confidence_execute", e.target.value)} />
            </div>
            <div>
              <Label className="text-[10px] font-mono text-zinc-400 mb-1 block">INTRABAR</Label>
              <Select value={form.intrabar_rule} onValueChange={v => set("intrabar_rule", v)}>
                <SelectTrigger className="h-8 font-mono text-xs"><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="conservative">Conservative</SelectItem>
                  <SelectItem value="optimistic">Optimistic</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>
          <div className="flex justify-end gap-2">
            <Button variant="outline" size="sm" className="font-mono text-xs" onClick={() => setOpen(false)}>Cancel</Button>
            <Button size="sm" className="font-mono text-xs bg-emerald-600 hover:bg-emerald-500 text-white"
              onClick={handleSubmit} disabled={submitting}>
              {submitting ? <><Loader2 className="h-3.5 w-3.5 mr-1.5 animate-spin" />Queuing…</> : <><Plus className="h-3.5 w-3.5 mr-1.5" />Queue</>}
            </Button>
          </div>
        </CardContent>
      )}
    </Card>
  );
}

// ── ExperimentCard ─────────────────────────────────────────────────────────

function ExperimentCard({ exp, onRun, onDelete }: {
  exp: Experiment; onRun: (id: string) => void; onDelete: (id: string) => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const cs = exp.config_summary;
  const prog = exp.wf_progress;

  return (
    <div className={cn(
      "rounded-md border p-3 space-y-2",
      exp.status === "running" ? "border-sky-500/40 bg-sky-500/5"
        : exp.status === "rejected" ? "border-amber-500/30 bg-amber-500/5"
        : exp.status === "failed" ? "border-red-500/30 bg-red-500/5"
        : "border-zinc-700 bg-zinc-800/20"
    )}>
      <div className="flex items-start gap-2 flex-wrap">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            {statusBadge(exp.status)}
            <span className="text-xs font-mono font-semibold truncate">{exp.name}</span>
            {exp.tags?.map(t => <Badge key={t} variant="outline" className="text-[9px] font-mono text-zinc-500 border-zinc-700 px-1">{t}</Badge>)}
            {exp.template_family && (
              <Badge variant="outline" className="text-[9px] font-mono text-violet-400 border-violet-700 px-1">
                {FAMILY_LABELS[exp.template_family] ?? exp.template_family}
              </Badge>
            )}
            {exp.batch_id && (
              <Badge variant="outline" className="text-[9px] font-mono text-sky-400 border-sky-800 px-1">batch</Badge>
            )}
            {exp.auto_rejected && <Badge variant="outline" className="text-amber-400 border-amber-600 text-[9px] font-mono">AUTO-REJECTED</Badge>}
          </div>
          {cs && (
            <p className="text-[10px] font-mono text-zinc-500 mt-0.5">
              {cs.train_years}yr/{cs.test_months}mo · {cs.start_date ? `${cs.start_date}–${cs.end_date||"now"}` : "all history"}
              {" · "}{timeAgo(exp.created_at)}
            </p>
          )}
        </div>
        <div className="flex items-center gap-1.5 flex-shrink-0">
          {exp.verdict && verdictBadge(exp.verdict)}
          {exp.score != null && <span className="text-[10px] font-mono text-zinc-300 bg-zinc-800 border border-zinc-700 rounded px-1.5 py-0.5">{exp.score.toFixed(1)}/100</span>}
          {exp.status === "queued" && (
            <Button size="sm" className="h-6 px-2 font-mono text-[11px] bg-sky-600 hover:bg-sky-500 text-white" onClick={() => onRun(exp.id)}>
              <Play className="h-3 w-3 mr-1" />Run
            </Button>
          )}
          {exp.status === "failed" && (
            <Button size="sm" className="h-6 px-2 font-mono text-[11px] bg-amber-600 hover:bg-amber-500 text-white" onClick={() => onRun(exp.id)}>
              <Play className="h-3 w-3 mr-1" />Retry
            </Button>
          )}
          {exp.status !== "running" && (
            <Button size="sm" variant="ghost" className="h-6 w-6 p-0 text-zinc-500 hover:text-red-400" onClick={() => onDelete(exp.id)}>
              <Trash2 className="h-3.5 w-3.5" />
            </Button>
          )}
          {["completed","rejected","failed"].includes(exp.status) && (
            <button className="text-zinc-500 hover:text-zinc-300" onClick={() => setExpanded(e => !e)}>
              {expanded ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}
            </button>
          )}
        </div>
      </div>
      {exp.status === "running" && prog && (
        <div className="space-y-0.5">
          <div className="flex justify-between text-[10px] font-mono text-zinc-400">
            <span>{prog.phase || "Initializing…"}</span>
            <span>{prog.progress_pct != null ? `${prog.progress_pct}%` : "…"}</span>
          </div>
          {prog.progress_pct != null && (
            <div className="h-1 bg-zinc-700 rounded-full">
              <div className="h-full bg-sky-500 rounded-full" style={{ width: `${prog.progress_pct}%` }} />
            </div>
          )}
        </div>
      )}
      {exp.auto_rejected && exp.overfitting_flags && exp.overfitting_flags.length > 0 && (
        <div className="text-[10px] font-mono text-amber-400 bg-amber-500/10 border border-amber-500/30 rounded px-2 py-1.5">
          Auto-rejected: {exp.overfitting_flags.join(" · ")}
        </div>
      )}
      {exp.status === "failed" && exp.error && (
        <div className="text-[10px] font-mono text-red-400 bg-red-500/10 border border-red-500/30 rounded px-2 py-1.5">{exp.error.slice(0,300)}</div>
      )}
      {expanded && exp.metrics && (
        <div className="pt-1 border-t border-zinc-800 grid grid-cols-4 gap-x-4 gap-y-1 text-[10px] font-mono">
          {([["Trades",exp.metrics.total_trades],["Return",fmtPct(exp.metrics.total_return_pct)],["Win Rate",fmtPct(exp.metrics.win_rate)],["PF",fmtNum(exp.metrics.profit_factor)],["Exp",fmtINR(exp.metrics.expectancy)],["Sharpe",fmtNum(exp.metrics.sharpe)],["DD",fmtPct(exp.metrics.max_drawdown_pct)],["ECE",fmtNum(exp.metrics.ece,4)]] as [string,any][]).map(([l,v])=>(
            <div key={l}><span className="text-zinc-500">{l} </span><span className="text-zinc-200">{String(v??"—")}</span></div>
          ))}
          {exp.score_breakdown && <div className="col-span-4 mt-1"><ScoreBar score={exp.score??0} breakdown={exp.score_breakdown}/></div>}
        </div>
      )}
      {expanded && exp.status === "failed" && exp.trace && (
        <div className="pt-1 border-t border-zinc-800">
          <p className="text-[10px] font-mono text-zinc-500 mb-1">Crash trace</p>
          <pre className="text-[9px] font-mono text-red-300/80 bg-zinc-900/70 border border-zinc-800 rounded p-2 max-h-40 overflow-auto whitespace-pre-wrap">{exp.trace}</pre>
        </div>
      )}
      {expanded && ["completed", "rejected"].includes(exp.status) && (
        <div className="pt-2 border-t border-zinc-800">
          <ResearchReport expId={exp.id} />
        </div>
      )}
      {expanded && exp.exec_log && exp.exec_log.length > 0 && (
        <div className="pt-1 border-t border-zinc-800">
          <p className="text-[10px] font-mono text-zinc-500 mb-1">Execution log</p>
          <div className="space-y-0.5 max-h-40 overflow-auto">
            {exp.exec_log.map((e, i) => (
              <div key={i} className="flex gap-2 text-[9px] font-mono">
                <span className="text-zinc-600 flex-shrink-0">{e.ts.replace("T", " ")}</span>
                <span className={cn(
                  e.msg.startsWith("failed") ? "text-red-400"
                    : e.msg.startsWith("completed") ? "text-emerald-400"
                    : "text-zinc-400"
                )}>{e.msg}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

// ── LeaderboardCard ────────────────────────────────────────────────────────

function LeaderboardCard({ entry, rank, onDelete }: {
  entry: LeaderboardEntry; rank: number; onDelete: (id: string) => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const m = entry.metrics ?? {};
  return (
    <div className={cn(
      "rounded-md border p-3 space-y-2",
      entry.auto_rejected ? "border-amber-500/20 bg-amber-500/5 opacity-75"
        : rank===1 ? "border-yellow-500/40 bg-yellow-500/5"
        : rank===2 ? "border-zinc-400/30"
        : rank===3 ? "border-amber-700/30"
        : "border-zinc-700 bg-zinc-800/20"
    )}>
      <div className="flex items-start gap-3 flex-wrap">
        <div className="flex-shrink-0 w-8 text-center pt-0.5">{rankMedal(rank)}</div>
        <div className="flex-1 min-w-0 space-y-1">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-xs font-mono font-semibold">{entry.name}</span>
            {entry.template_family && (
              <Badge variant="outline" className="text-[9px] font-mono text-violet-400 border-violet-700 px-1">
                {FAMILY_LABELS[entry.template_family]??entry.template_family}
              </Badge>
            )}
            {entry.tags?.map(t=><Badge key={t} variant="outline" className="text-[9px] font-mono text-zinc-500 border-zinc-700 px-1">{t}</Badge>)}
            {verdictBadge(entry.verdict)}
            {m.ev_verdict && <Badge variant="outline" className="text-[9px] font-mono text-sky-400 border-sky-700 px-1">Ev:{m.ev_verdict}</Badge>}
            {entry.auto_rejected && <Badge variant="outline" className="text-amber-400 border-amber-600 text-[9px] font-mono">AUTO-REJECTED</Badge>}
          </div>
          <ScoreBar score={entry.score} breakdown={entry.score_breakdown} />
          <div className="flex flex-wrap gap-x-4 gap-y-0.5 text-[10px] font-mono text-zinc-400">
            <span>PF <span className="text-zinc-200">{fmtNum(m.profit_factor)}</span></span>
            <span>Exp <span className="text-zinc-200">{fmtINR(m.expectancy)}</span></span>
            <span>Sharpe <span className="text-zinc-200">{fmtNum(m.sharpe)}</span></span>
            <span>DD <span className="text-zinc-200">{fmtPct(m.max_drawdown_pct)}</span></span>
            <span>WR <span className="text-zinc-200">{fmtPct(m.win_rate)}</span></span>
            <span>ECE <span className="text-zinc-200">{fmtNum(m.ece,4)}</span></span>
            <span>Trades <span className="text-zinc-200">{m.total_trades??"—"}</span></span>
            <span>Win <span className="text-zinc-200">{m.windows??"—"} win</span></span>
          </div>
          {entry.auto_rejected && entry.overfitting_flags && (
            <p className="text-[10px] font-mono text-amber-400">
              ⚠ {entry.overfitting_flags[0]}{entry.overfitting_flags.length>1?` +${entry.overfitting_flags.length-1} more`:""}
            </p>
          )}
        </div>
        <div className="flex-shrink-0 flex gap-1">
          <button className="text-zinc-500 hover:text-zinc-300" onClick={() => setExpanded(e=>!e)}>
            {expanded?<ChevronDown className="h-4 w-4"/>:<ChevronRight className="h-4 w-4"/>}
          </button>
          <Button size="sm" variant="ghost" className="h-6 w-6 p-0 text-zinc-500 hover:text-red-400" onClick={() => onDelete(entry.id)}>
            <Trash2 className="h-3.5 w-3.5"/>
          </Button>
        </div>
      </div>
      {expanded && (
        <div className="pt-2 border-t border-zinc-800 grid grid-cols-3 gap-x-4 gap-y-1 text-[10px] font-mono">
          {([["Score",`${entry.score.toFixed(1)}/100`],["Trades",m.total_trades],["Return",fmtPct(m.total_return_pct)],["PF",fmtNum(m.profit_factor)],["Exp",fmtINR(m.expectancy)],["Sharpe",fmtNum(m.sharpe)],["DD",fmtPct(m.max_drawdown_pct)],["Win Rate",fmtPct(m.win_rate)],["ECE",fmtNum(m.ece,4)],["Evidence",m.ev_verdict??"—"],["Ev Trades",m.ev_trades],["Windows",m.windows]] as [string,any][]).map(([l,v])=>(
            <div key={l}><span className="text-zinc-500">{l} </span><span className="text-zinc-200">{String(v??"—")}</span></div>
          ))}
          {entry.overfitting_flags && entry.overfitting_flags.length>0 && (
            <div className="col-span-3 text-amber-400 mt-1">Flags: {entry.overfitting_flags.join(" · ")}</div>
          )}
        </div>
      )}
      {expanded && ["completed", "rejected"].includes(entry.status) && (
        <div className="pt-2 border-t border-zinc-800">
          <ResearchReport expId={entry.id} />
        </div>
      )}
    </div>
  );
}

// ── ComparisonTable ────────────────────────────────────────────────────────

function ComparisonTable({ entries }: { entries: LeaderboardEntry[] }) {
  if (entries.length === 0) {
    return <p className="text-sm font-mono text-muted-foreground text-center py-8">No completed experiments to compare.</p>;
  }
  const cols: [string, (e: LeaderboardEntry) => any, string?][] = [
    ["Score",   e => e.score?.toFixed(1)??"—",                    "tabular-nums text-right"],
    ["OOS Trades", e => e.metrics?.total_trades??"—",             "tabular-nums text-right"],
    ["Return %",e => fmtPct(e.metrics?.total_return_pct),         "tabular-nums text-right"],
    ["Exp (₹)", e => fmtINR(e.metrics?.expectancy),               "tabular-nums text-right"],
    ["PF",      e => fmtNum(e.metrics?.profit_factor),            "tabular-nums text-right"],
    ["Sharpe",  e => fmtNum(e.metrics?.sharpe),                   "tabular-nums text-right"],
    ["DD %",    e => fmtPct(e.metrics?.max_drawdown_pct),         "tabular-nums text-right"],
    ["Win %",   e => fmtPct(e.metrics?.win_rate),                 "tabular-nums text-right"],
    ["ECE",     e => fmtNum(e.metrics?.ece,4),                    "tabular-nums text-right"],
    ["Evidence",e => e.metrics?.ev_verdict??"—",                  ""],
    ["Verdict", e => e.verdict??"—",                              ""],
    ["Rejection",e=>e.overfitting_flags?.[0]?.split("(")[0].trim()??"—", "max-w-[120px] truncate text-amber-400"],
  ];
  return (
    <div className="overflow-x-auto rounded-md border border-zinc-800">
      <table className="w-full text-[10px] font-mono">
        <thead className="bg-zinc-900 border-b border-zinc-800">
          <tr>
            <th className="sticky left-0 bg-zinc-900 text-left px-3 py-2 text-zinc-400 font-semibold min-w-[140px]">#  Name</th>
            {cols.map(([h]) => <th key={h} className="px-3 py-2 text-zinc-400 font-semibold text-right whitespace-nowrap">{h}</th>)}
          </tr>
        </thead>
        <tbody>
          {entries.map((entry, idx) => {
            const rank = entry.auto_rejected ? null : idx + 1;
            return (
              <tr key={entry.id}
                className={cn(
                  "border-b border-zinc-800/50 hover:bg-zinc-800/30",
                  entry.auto_rejected && "opacity-60"
                )}>
                <td className="sticky left-0 bg-zinc-900 px-3 py-1.5 text-left">
                  <div className="flex items-center gap-1.5">
                    {rank ? rankMedal(rank) : <span className="text-amber-500 text-[10px]">✗</span>}
                    <span className="truncate max-w-[110px] text-zinc-200">{entry.name}</span>
                  </div>
                  {entry.template_family && (
                    <div className="text-[9px] text-zinc-600 ml-5 truncate">
                      {FAMILY_LABELS[entry.template_family]??entry.template_family}
                    </div>
                  )}
                </td>
                {cols.map(([h, fn, cls]) => (
                  <td key={h} className={cn("px-3 py-1.5 text-zinc-300", cls)}>
                    {String(fn(entry))}
                  </td>
                ))}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

// ── Grouped leaderboard ────────────────────────────────────────────────────

function GroupedLeaderboard({ entries, onDelete }: {
  entries: LeaderboardEntry[]; onDelete: (id: string) => void;
}) {
  const groups: Record<string, LeaderboardEntry[]> = {};
  for (const e of entries) {
    const fam = e.template_family || "custom";
    if (!groups[fam]) groups[fam] = [];
    groups[fam].push(e);
  }
  const ORDER = ["market_conditions","confidence_sweep","holding_sweep","window_sweep","custom"];
  const sortedKeys = [...new Set([...ORDER, ...Object.keys(groups)])].filter(k => groups[k]?.length);

  if (sortedKeys.length === 0) {
    return <p className="text-sm font-mono text-muted-foreground text-center py-8">No completed experiments.</p>;
  }

  return (
    <div className="space-y-5">
      {sortedKeys.map(fam => {
        const grpEntries = groups[fam];
        const label = FAMILY_LABELS[fam] ?? (fam === "custom" ? "Custom / No Template" : fam);
        let rankOffset = 0;
        return (
          <div key={fam}>
            <div className="flex items-center gap-2 mb-2">
              <span className="text-[11px] font-mono font-semibold text-zinc-300">{label}</span>
              <Badge variant="outline" className="text-[9px] font-mono text-zinc-500 border-zinc-700">
                {grpEntries.filter(e=>!e.auto_rejected).length} valid · {grpEntries.length} total
              </Badge>
            </div>
            <div className="space-y-2">
              {grpEntries.map(entry => {
                if (!entry.auto_rejected) rankOffset++;
                return (
                  <LeaderboardCard
                    key={entry.id} entry={entry}
                    rank={entry.auto_rejected ? grpEntries.length : rankOffset}
                    onDelete={onDelete}
                  />
                );
              })}
            </div>
          </div>
        );
      })}
    </div>
  );
}

// ── Main page ──────────────────────────────────────────────────────────────

export default function ExperimentManager() {
  const { toast } = useToast();
  const [tab, setTab] = useState<Tab>(() => {
    const t = new URLSearchParams(window.location.search).get("tab");
    return (["templates", "queue", "batches", "leaderboard"] as Tab[]).includes(t as Tab)
      ? (t as Tab) : "templates";
  });
  const [experiments, setExperiments] = useState<Experiment[]>([]);
  const [leaderboard, setLeaderboard] = useState<LeaderboardEntry[]>([]);
  const [batchCount, setBatchCount] = useState(0);
  const [loading, setLoading] = useState(true);
  const [lbView, setLbView] = useState<LeaderboardView>("all");
  const [phase5Exporting, setPhase5Exporting] = useState(false);

  const hasRunning = experiments.some(e => e.status === "running");
  const completedCount = leaderboard.length;

  const fetchExperiments = useCallback(async () => {
    try {
      const data = await apiJson("/experiments");
      if (data.experiments) setExperiments(data.experiments);
    } catch { /* silent */ }
  }, []);

  const fetchLeaderboard = useCallback(async () => {
    try {
      const data = await apiJson("/experiments/leaderboard");
      if (data.entries) setLeaderboard(data.entries);
    } catch { /* silent */ }
  }, []);

  const fetchBatchCount = useCallback(async () => {
    try {
      const data = await apiJson("/batches");
      if (data.batches) setBatchCount(data.batches.length);
    } catch { /* silent */ }
  }, []);

  const fetchAll = useCallback(async () => {
    await Promise.all([fetchExperiments(), fetchLeaderboard(), fetchBatchCount()]);
  }, [fetchExperiments, fetchLeaderboard, fetchBatchCount]);

  useEffect(() => {
    setLoading(true);
    fetchAll().finally(() => setLoading(false));
  }, [fetchAll]);

  // Poll while running
  useEffect(() => {
    if (!hasRunning) return;
    const t = setInterval(async () => {
      await fetchExperiments();
      fetchLeaderboard();
    }, 4000);
    return () => clearInterval(t);
  }, [hasRunning, fetchExperiments, fetchLeaderboard]);

  useEffect(() => {
    if (!hasRunning) { fetchLeaderboard(); fetchBatchCount(); }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [hasRunning]);

  async function handleRun(id: string) {
    if (hasRunning) {
      toast({ title: "Already running", description: "Wait for the current experiment to finish.", variant: "destructive" });
      return;
    }
    try {
      await apiJson(`/experiments/${id}/run`, { method: "POST" });
      toast({ title: "Started", description: "Walk-forward validation running." });
      await fetchExperiments();
    } catch (e) {
      toast({ title: "Failed", description: String(e), variant: "destructive" });
    }
  }

  async function handleDelete(id: string) {
    try {
      await apiJson(`/experiments/${id}`, { method: "DELETE" });
      toast({ title: "Deleted" });
      await fetchAll();
    } catch (e) {
      toast({ title: "Delete failed", description: String(e), variant: "destructive" });
    }
  }

  async function downloadPhase5Review() {
    setPhase5Exporting(true);
    toast({ title: "Generating Phase 5 review export…", description: "Collecting all Phase 5 research data. This can take up to a minute." });
    try {
      let totalRows = 0;
      for (const file of ["main", "summary"] as const) {
        const resp = await fetch(`${API_BASE}/research/phase5-review-export?file=${file}`);
        const ctype = resp.headers.get("Content-Type") ?? "";
        if (!resp.ok || !ctype.includes("text/csv")) {
          let detail = "";
          try {
            detail = ctype.includes("application/json")
              ? (JSON.stringify((await resp.json())?.error ?? "") || "")
              : (await resp.text()).slice(0, 300);
          } catch { /* unreadable body */ }
          throw new Error(`Export failed (HTTP ${resp.status})${detail ? `: ${detail}` : ""}`);
        }
        const rows = Number(resp.headers.get("X-Row-Count") ?? 0);
        totalRows += rows;
        const blob = await resp.blob();
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = file === "main" ? "phase5_review_export.csv" : "phase5_review_summary.csv";
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
      }
      toast({ title: "Phase 5 review export downloaded", description: `${totalRows} rows across phase5_review_export.csv + phase5_review_summary.csv. Research only.` });
    } catch (e) {
      toast({ title: "Phase 5 export failed", description: String(e instanceof Error ? e.message : e), variant: "destructive" });
    } finally {
      setPhase5Exporting(false);
    }
  }

  function downloadExport(type: "csv" | "json") {
    const url = `${API_BASE}/experiments/export/${type}`;
    const a = document.createElement("a");
    a.href = url;
    a.download = `experiments_${Date.now()}.${type}`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    toast({ title: `Downloading ${type.toUpperCase()}`, description: "Research-only export — no live order data." });
  }

  const existingForTemplates: ExistingExperiment[] = experiments.map(e => ({
    id: e.id, name: e.name, status: e.status,
    config_hash: e.config_hash, canonical_config: e.canonical_config,
    config_summary: e.config_summary,
  }));

  const TABS = [
    { id: "templates" as Tab, label: "Templates",      icon: BookTemplate, count: null },
    { id: "queue"     as Tab, label: "Queue",          icon: TestTubes,    count: experiments.length },
    { id: "batches"   as Tab, label: "Batches",        icon: Layers,       count: batchCount },
    { id: "leaderboard" as Tab, label: "Leaderboard",  icon: Trophy,       count: completedCount },
  ];

  return (
    <div className="space-y-4 max-w-6xl mx-auto">
      {/* Header */}
      <div className="flex items-start justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-xl font-mono font-bold flex items-center gap-2">
            <FlaskConical className="h-5 w-5 text-violet-400" />
            Research Factory
          </h1>
          <p className="text-sm font-mono text-muted-foreground mt-1">
            Templates · batch runner · ranked leaderboard · CSV/JSON export · auto-reject overfitting
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Badge variant="outline" className="text-[10px] font-mono text-violet-300 border-violet-500/40">
            PAPER · RESEARCH ONLY
          </Badge>
          <Button size="sm" variant="outline" className="font-mono text-xs gap-1.5" onClick={() => fetchAll()} disabled={loading}>
            <RefreshCw className={cn("h-3.5 w-3.5", loading && "animate-spin")} />
            Refresh
          </Button>
        </div>
      </div>

      {/* Safety banner */}
      <div className="rounded-md border border-amber-500/30 bg-amber-500/5 px-3 py-2 text-[11px] font-mono text-amber-400">
        ⚠ Out-of-sample historical performance does not guarantee future results. Strict no-lookahead
        train/test splits. Paper trading and research only. Results do not affect live strategy selection.
      </div>

      {/* Tabs */}
      <div className="flex gap-0 border border-zinc-700 rounded-md overflow-hidden w-fit">
        {TABS.map(({ id, label, icon: Icon, count }) => (
          <button key={id} onClick={() => setTab(id)}
            className={cn(
              "px-4 py-2 text-xs font-mono flex items-center gap-1.5 transition-colors border-r border-zinc-700 last:border-r-0",
              tab === id ? "bg-zinc-700 text-zinc-100" : "text-zinc-400 hover:text-zinc-200 hover:bg-zinc-800"
            )}>
            <Icon className="h-3.5 w-3.5" />
            {label}
            {count != null && count > 0 && (
              <span className="bg-zinc-600 text-zinc-200 rounded-full text-[9px] px-1.5 ml-0.5">{count}</span>
            )}
            {id === "queue" && hasRunning && (
              <span className="w-1.5 h-1.5 rounded-full bg-sky-400 animate-pulse" />
            )}
          </button>
        ))}
      </div>

      {/* ── Templates tab ────────────────────────────────────────────────── */}
      {tab === "templates" && (
        <ExperimentTemplates existing={existingForTemplates} onQueued={fetchAll} />
      )}

      {/* ── Queue tab ────────────────────────────────────────────────────── */}
      {tab === "queue" && (
        <div className="space-y-3">
          <SubmitForm onSubmitted={fetchAll} />
          {loading && experiments.length === 0 && (
            <div className="text-center py-10 text-sm font-mono text-muted-foreground">
              <Loader2 className="h-5 w-5 animate-spin mx-auto mb-2 text-zinc-600" />Loading…
            </div>
          )}
          {!loading && experiments.length === 0 && (
            <Card>
              <CardContent className="py-10 text-center">
                <FlaskConical className="h-8 w-8 mx-auto mb-3 text-zinc-700" />
                <p className="text-sm font-mono text-muted-foreground">No experiments yet.</p>
                <p className="text-xs font-mono text-zinc-600 mt-1">Use the Templates tab to add one.</p>
              </CardContent>
            </Card>
          )}
          {experiments.map(exp => (
            <ExperimentCard key={exp.id} exp={exp} onRun={handleRun} onDelete={handleDelete} />
          ))}
        </div>
      )}

      {/* ── Batches tab ──────────────────────────────────────────────────── */}
      {tab === "batches" && (
        <BatchQueue hasAnyRunning={hasRunning} onExperimentsChanged={fetchAll} />
      )}

      {/* ── Leaderboard tab ──────────────────────────────────────────────── */}
      {tab === "leaderboard" && (
        <div className="space-y-3">
          {/* Toolbar */}
          <div className="flex items-center justify-between flex-wrap gap-2">
            <div className="flex gap-0 border border-zinc-700 rounded overflow-hidden">
              {([ ["all","All",BarChart3], ["family","By Family",Layers], ["compare","Compare",Trophy] ] as const).map(([v,l,Icon])=>(
                <button key={v} onClick={() => setLbView(v)}
                  className={cn("px-3 py-1.5 text-[11px] font-mono flex items-center gap-1.5 border-r border-zinc-700 last:border-r-0",
                    lbView===v ? "bg-zinc-700 text-zinc-100" : "text-zinc-400 hover:text-zinc-200 hover:bg-zinc-800")}>
                  <Icon className="h-3.5 w-3.5"/>{l}
                </button>
              ))}
            </div>
            <div className="flex gap-1.5">
              <Button size="sm" variant="outline" className="font-mono text-xs h-8 gap-1.5" onClick={() => downloadExport("csv")}>
                <Download className="h-3.5 w-3.5"/>CSV
              </Button>
              <Button size="sm" variant="outline" className="font-mono text-xs h-8 gap-1.5" onClick={() => downloadExport("json")}>
                <Download className="h-3.5 w-3.5"/>JSON
              </Button>
              <Button size="sm" variant="outline" className="font-mono text-xs h-8 gap-1.5" disabled={phase5Exporting} onClick={downloadPhase5Review}>
                <Download className="h-3.5 w-3.5"/>{phase5Exporting ? "Exporting…" : "Export Phase 5 Review CSV"}
              </Button>
            </div>
          </div>

          {/* Score legend (only when not in compare mode) */}
          {lbView !== "compare" && leaderboard.length > 0 && (
            <p className="text-[10px] font-mono text-zinc-500">
              Score 0–100: profit factor(25) + expectancy(20) + Sharpe(20) + drawdown(15) + calibration(10) + evidence(10).
              Auto-rejected entries shown at bottom.
            </p>
          )}

          {leaderboard.length === 0 && (
            <Card>
              <CardContent className="py-10 text-center space-y-2">
                <Trophy className="h-8 w-8 mx-auto text-zinc-700" />
                <p className="text-sm font-mono text-muted-foreground">No completed experiments yet.</p>
                <p className="text-xs font-mono text-zinc-600">
                  {experiments.some(e=>e.status==="queued") ? "Experiments are queued — go to the Queue tab and click Run." : "Use the Templates tab to queue your first experiment."}
                </p>
              </CardContent>
            </Card>
          )}

          {lbView === "all" && (() => {
            let rank = 0;
            return leaderboard.map(e => {
              if (!e.auto_rejected) rank++;
              return <LeaderboardCard key={e.id} entry={e} rank={e.auto_rejected ? leaderboard.length : rank} onDelete={handleDelete} />;
            });
          })()}

          {lbView === "family" && <GroupedLeaderboard entries={leaderboard} onDelete={handleDelete} />}

          {lbView === "compare" && <ComparisonTable entries={leaderboard} />}
        </div>
      )}

      {/* Footer */}
      <p className="text-[10px] font-mono text-zinc-600 text-center border-t border-zinc-800 pt-3">
        NIFTY 50 universe · ₹5,000 paper capital · no auto-promotion · no live orders affected
      </p>
    </div>
  );
}
