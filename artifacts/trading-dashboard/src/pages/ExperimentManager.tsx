/**
 * ExperimentManager.tsx — Phase 4 Research Factory: Experiment Manager.
 *
 * Queue and run multiple walk-forward experiments across different date
 * ranges, regimes, and config variants.  Ranked leaderboard with composite
 * objective score.  Auto-rejected experiments highlighted at the bottom.
 *
 * No look-ahead bias — every experiment uses the same strict train/test
 * split logic as the main Walk-Forward Validation.
 * Paper trading and research only.
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
  Trophy, Medal, AlertTriangle, CheckCircle2, Clock, XCircle,
  BarChart3, Plus, RefreshCw,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useToast } from "@/hooks/use-toast";

/* eslint-disable @typescript-eslint/no-explicit-any */

const API_BASE = `${import.meta.env.BASE_URL}api`;

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
  universe_size?: number;
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
  wf_progress?: any;
  error?: string;
}

interface LeaderboardEntry extends Experiment {
  score: number;
}

// ── Presets ────────────────────────────────────────────────────────────────

interface Preset {
  id: string;
  label: string;
  description: string;
  config: Partial<FormConfig>;
}

interface FormConfig {
  name: string;
  description: string;
  tags: string;
  train_years: string;
  test_months: string;
  step_months: string;
  start_date: string;
  end_date: string;
  universe_size: string;
  max_holding_days: string;
  intrabar_rule: string;
  min_confidence_execute: string;
}

const PRESETS: Preset[] = [
  {
    id: "standard",
    label: "Standard",
    description: "1yr train, 3mo test — baseline config, full NIFTY 50",
    config: { train_years: "1", test_months: "3", step_months: "3", start_date: "", end_date: "", universe_size: "0", max_holding_days: "20", intrabar_rule: "conservative", min_confidence_execute: "55" },
  },
  {
    id: "long_evidence",
    label: "Long Evidence",
    description: "2yr train, 3mo test — recommended for 300+ OOS trades (PASS)",
    config: { train_years: "2", test_months: "3", step_months: "3", start_date: "", end_date: "", universe_size: "0", max_holding_days: "20", intrabar_rule: "conservative", min_confidence_execute: "55" },
  },
  {
    id: "bear_market",
    label: "Bear Market Focus",
    description: "Oct 2021 – Mar 2023 — post-peak bear cycle",
    config: { train_years: "1", test_months: "3", step_months: "3", start_date: "2021-10-01", end_date: "2023-03-31", universe_size: "0", max_holding_days: "20", intrabar_rule: "conservative", min_confidence_execute: "55" },
  },
  {
    id: "bull_market",
    label: "Bull Market Focus",
    description: "Apr 2023 – Dec 2025 — recovery and bull cycle",
    config: { train_years: "1", test_months: "3", step_months: "3", start_date: "2023-04-01", end_date: "2025-12-31", universe_size: "0", max_holding_days: "20", intrabar_rule: "conservative", min_confidence_execute: "55" },
  },
  {
    id: "wide_sweep",
    label: "Wide Sweep",
    description: "1yr train, 6mo test — fewer windows, broader OOS slices",
    config: { train_years: "1", test_months: "6", step_months: "6", start_date: "", end_date: "", universe_size: "0", max_holding_days: "20", intrabar_rule: "conservative", min_confidence_execute: "55" },
  },
  {
    id: "tight_stops",
    label: "Tight Stops",
    description: "Standard config with optimistic same-candle rule",
    config: { train_years: "1", test_months: "3", step_months: "3", start_date: "", end_date: "", universe_size: "0", max_holding_days: "15", intrabar_rule: "optimistic", min_confidence_execute: "60" },
  },
  {
    id: "custom",
    label: "Custom",
    description: "Fully manual — set every parameter",
    config: {},
  },
];

const DEFAULT_FORM: FormConfig = {
  name: "", description: "", tags: "",
  train_years: "1", test_months: "3", step_months: "3",
  start_date: "", end_date: "", universe_size: "0",
  max_holding_days: "20", intrabar_rule: "conservative",
  min_confidence_execute: "55",
};

// ── Helpers ────────────────────────────────────────────────────────────────

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
    case "queued":    return <Badge variant="outline" className="text-zinc-400 border-zinc-600 font-mono text-[10px]"><Clock className="h-3 w-3 mr-1" /> Queued</Badge>;
    case "running":   return <Badge variant="outline" className="text-sky-400 border-sky-500 font-mono text-[10px] animate-pulse"><Loader2 className="h-3 w-3 mr-1 animate-spin" /> Running</Badge>;
    case "completed": return <Badge variant="outline" className="text-emerald-400 border-emerald-600 font-mono text-[10px]"><CheckCircle2 className="h-3 w-3 mr-1" /> Completed</Badge>;
    case "rejected":  return <Badge variant="outline" className="text-amber-400 border-amber-600 font-mono text-[10px]"><AlertTriangle className="h-3 w-3 mr-1" /> Rejected</Badge>;
    case "failed":    return <Badge variant="outline" className="text-red-400 border-red-600 font-mono text-[10px]"><XCircle className="h-3 w-3 mr-1" /> Failed</Badge>;
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

function ScoreBar({ score, breakdown }: { score: number; breakdown?: Record<string, number> }) {
  const pct = Math.min(100, score);
  const color = score >= 60 ? "bg-emerald-500" : score >= 35 ? "bg-amber-500" : "bg-red-500";
  return (
    <div className="space-y-1">
      <div className="flex items-center gap-2">
        <div className="flex-1 h-2 bg-zinc-700 rounded-full overflow-hidden">
          <div className={cn("h-full rounded-full transition-all", color)} style={{ width: `${pct}%` }} />
        </div>
        <span className="text-xs font-mono font-bold tabular-nums">{score.toFixed(1)}<span className="text-zinc-500">/100</span></span>
      </div>
      {breakdown && (
        <div className="flex flex-wrap gap-1">
          {[
            ["PF", breakdown.profit_factor, 25],
            ["Exp", breakdown.expectancy, 20],
            ["Sharpe", breakdown.sharpe, 20],
            ["DD", breakdown.drawdown, 15],
            ["Cal", breakdown.calibration, 10],
            ["Evid", breakdown.evidence, 10],
          ].map(([lbl, val, max]) => (
            <span key={String(lbl)} className="text-[9px] font-mono text-zinc-400">
              {lbl} <span className="text-zinc-200">{Number(val).toFixed(0)}</span>/{max}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

// ── Submit Form ────────────────────────────────────────────────────────────

function SubmitForm({ onSubmitted }: { onSubmitted: () => void }) {
  const { toast } = useToast();
  const [open, setOpen] = useState(false);
  const [preset, setPreset] = useState<string>("standard");
  const [form, setForm] = useState<FormConfig>({ ...DEFAULT_FORM, ...PRESETS[0].config });
  const [submitting, setSubmitting] = useState(false);

  function applyPreset(pid: string) {
    const p = PRESETS.find(x => x.id === pid);
    if (!p) return;
    setPreset(pid);
    setForm(f => ({ ...f, ...p.config }));
  }

  function set(k: keyof FormConfig, v: string) {
    setForm(f => ({ ...f, [k]: v }));
  }

  async function handleSubmit() {
    if (!form.name.trim()) {
      toast({ title: "Name required", description: "Give this experiment a name.", variant: "destructive" });
      return;
    }
    setSubmitting(true);
    try {
      const payload = {
        name: form.name.trim(),
        description: form.description.trim(),
        tags: form.tags.split(",").map(t => t.trim()).filter(Boolean),
        train_years: parseInt(form.train_years),
        test_months: parseInt(form.test_months),
        step_months: parseInt(form.step_months),
        start_date: form.start_date.trim(),
        end_date: form.end_date.trim(),
        universe_size: parseInt(form.universe_size) || 0,
        max_holding_days: parseInt(form.max_holding_days) || 20,
        intrabar_rule: form.intrabar_rule,
        min_confidence_execute: parseFloat(form.min_confidence_execute) || 55,
      };
      const res = await fetch(`${API_BASE}/experiments`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const data = await res.json();
      if (!res.ok || data.error) throw new Error(data.error || `HTTP ${res.status}`);
      toast({ title: "Experiment queued", description: `"${form.name}" added to the queue.` });
      setForm({ ...DEFAULT_FORM, ...PRESETS.find(x => x.id === preset)?.config });
      setOpen(false);
      onSubmitted();
    } catch (e) {
      toast({ title: "Submit failed", description: String(e), variant: "destructive" });
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Card>
      <CardHeader className="py-3 cursor-pointer" onClick={() => setOpen(o => !o)}>
        <CardTitle className="text-sm font-mono flex items-center gap-2">
          <Plus className="h-4 w-4 text-emerald-400" />
          New Experiment
          {open ? <ChevronDown className="h-4 w-4 ml-auto text-zinc-500" /> : <ChevronRight className="h-4 w-4 ml-auto text-zinc-500" />}
        </CardTitle>
      </CardHeader>
      {open && (
        <CardContent className="pt-0 space-y-4">
          {/* Presets */}
          <div>
            <Label className="text-[10px] font-mono text-zinc-400 mb-1.5 block">PRESET</Label>
            <div className="flex flex-wrap gap-1.5">
              {PRESETS.map(p => (
                <button
                  key={p.id}
                  onClick={() => applyPreset(p.id)}
                  className={cn(
                    "px-2.5 py-1 rounded text-[11px] font-mono border transition-colors",
                    preset === p.id
                      ? "bg-violet-600 border-violet-500 text-white"
                      : "border-zinc-700 text-zinc-400 hover:border-zinc-500 hover:text-zinc-300"
                  )}
                >
                  {p.label}
                </button>
              ))}
            </div>
            {preset !== "custom" && (
              <p className="text-[10px] font-mono text-zinc-500 mt-1">
                {PRESETS.find(p => p.id === preset)?.description}
              </p>
            )}
          </div>

          {/* Name + Description */}
          <div className="grid grid-cols-2 gap-3">
            <div>
              <Label className="text-[10px] font-mono text-zinc-400 mb-1 block">EXPERIMENT NAME *</Label>
              <Input className="h-8 font-mono text-xs" value={form.name}
                onChange={e => set("name", e.target.value)} placeholder="e.g. Bear market 2022 test" />
            </div>
            <div>
              <Label className="text-[10px] font-mono text-zinc-400 mb-1 block">TAGS (comma-separated)</Label>
              <Input className="h-8 font-mono text-xs" value={form.tags}
                onChange={e => set("tags", e.target.value)} placeholder="bear, 2022, 1yr-train" />
            </div>
          </div>

          <div>
            <Label className="text-[10px] font-mono text-zinc-400 mb-1 block">DESCRIPTION (optional)</Label>
            <Input className="h-8 font-mono text-xs" value={form.description}
              onChange={e => set("description", e.target.value)} placeholder="What are you testing?" />
          </div>

          {/* Walk-Forward Config */}
          <div className="grid grid-cols-3 gap-3">
            <div>
              <Label className="text-[10px] font-mono text-zinc-400 mb-1 block">TRAINING PERIOD</Label>
              <Select value={form.train_years} onValueChange={v => set("train_years", v)}>
                <SelectTrigger className="h-8 font-mono text-xs"><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="1">1 year</SelectItem>
                  <SelectItem value="2">2 years</SelectItem>
                  <SelectItem value="3">3 years</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div>
              <Label className="text-[10px] font-mono text-zinc-400 mb-1 block">TEST PERIOD</Label>
              <Select value={form.test_months} onValueChange={v => set("test_months", v)}>
                <SelectTrigger className="h-8 font-mono text-xs"><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="1">1 month</SelectItem>
                  <SelectItem value="3">3 months</SelectItem>
                  <SelectItem value="6">6 months</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div>
              <Label className="text-[10px] font-mono text-zinc-400 mb-1 block">STEP SIZE</Label>
              <Select value={form.step_months} onValueChange={v => set("step_months", v)}>
                <SelectTrigger className="h-8 font-mono text-xs"><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="1">1 month</SelectItem>
                  <SelectItem value="3">3 months</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>

          {/* Date Range */}
          <div className="grid grid-cols-2 gap-3">
            <div>
              <Label className="text-[10px] font-mono text-zinc-400 mb-1 block">START DATE (optional, YYYY-MM-DD)</Label>
              <Input className="h-8 font-mono text-xs" value={form.start_date}
                onChange={e => set("start_date", e.target.value)} placeholder="e.g. 2021-10-01" />
            </div>
            <div>
              <Label className="text-[10px] font-mono text-zinc-400 mb-1 block">END DATE (optional, YYYY-MM-DD)</Label>
              <Input className="h-8 font-mono text-xs" value={form.end_date}
                onChange={e => set("end_date", e.target.value)} placeholder="e.g. 2023-03-31" />
            </div>
          </div>

          {/* Advanced */}
          <div className="grid grid-cols-4 gap-3">
            <div>
              <Label className="text-[10px] font-mono text-zinc-400 mb-1 block">MAX HOLD (days)</Label>
              <Input className="h-8 font-mono text-xs" value={form.max_holding_days}
                onChange={e => set("max_holding_days", e.target.value)} />
            </div>
            <div>
              <Label className="text-[10px] font-mono text-zinc-400 mb-1 block">UNIVERSE SIZE (0=all)</Label>
              <Input className="h-8 font-mono text-xs" value={form.universe_size}
                onChange={e => set("universe_size", e.target.value)} />
            </div>
            <div>
              <Label className="text-[10px] font-mono text-zinc-400 mb-1 block">INTRABAR RULE</Label>
              <Select value={form.intrabar_rule} onValueChange={v => set("intrabar_rule", v)}>
                <SelectTrigger className="h-8 font-mono text-xs"><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="conservative">Conservative</SelectItem>
                  <SelectItem value="optimistic">Optimistic</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div>
              <Label className="text-[10px] font-mono text-zinc-400 mb-1 block">MIN CONFIDENCE %</Label>
              <Input className="h-8 font-mono text-xs" value={form.min_confidence_execute}
                onChange={e => set("min_confidence_execute", e.target.value)} />
            </div>
          </div>

          <div className="flex justify-end gap-2 pt-1">
            <Button variant="outline" size="sm" className="font-mono text-xs" onClick={() => setOpen(false)}>
              Cancel
            </Button>
            <Button
              size="sm"
              className="font-mono text-xs bg-emerald-600 hover:bg-emerald-500 text-white"
              onClick={handleSubmit}
              disabled={submitting}
            >
              {submitting ? <><Loader2 className="h-3.5 w-3.5 mr-1.5 animate-spin" />Submitting…</> : <><Plus className="h-3.5 w-3.5 mr-1.5" />Queue Experiment</>}
            </Button>
          </div>
        </CardContent>
      )}
    </Card>
  );
}

// ── Experiment Queue Card ──────────────────────────────────────────────────

function ExperimentCard({ exp, onRun, onDelete }: {
  exp: Experiment;
  onRun: (id: string) => void;
  onDelete: (id: string) => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const cs = exp.config_summary;
  const prog = exp.wf_progress;

  return (
    <div className={cn(
      "rounded-md border p-3 space-y-2 transition-colors",
      exp.status === "running" ? "border-sky-500/40 bg-sky-500/5"
        : exp.status === "completed" ? "border-zinc-700 bg-zinc-800/20"
        : exp.status === "rejected" ? "border-amber-500/30 bg-amber-500/5"
        : exp.status === "failed" ? "border-red-500/30 bg-red-500/5"
        : "border-zinc-700 bg-zinc-800/20",
    )}>
      <div className="flex items-start gap-2 flex-wrap">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            {statusBadge(exp.status)}
            <span className="text-xs font-mono font-semibold truncate">{exp.name}</span>
            {exp.tags?.map(t => (
              <Badge key={t} variant="outline" className="text-[9px] font-mono text-zinc-500 border-zinc-700 px-1">{t}</Badge>
            ))}
            {exp.auto_rejected && (
              <Badge variant="outline" className="text-amber-400 border-amber-600 text-[9px] font-mono">AUTO-REJECTED</Badge>
            )}
          </div>
          {exp.description && (
            <p className="text-[10px] font-mono text-zinc-500 mt-0.5">{exp.description}</p>
          )}
          {cs && (
            <p className="text-[10px] font-mono text-zinc-500 mt-0.5">
              {cs.train_years}yr train · {cs.test_months}mo test · {cs.step_months}mo step
              {cs.start_date ? ` · ${cs.start_date}–${cs.end_date || "now"}` : " · all available history"}
              {cs.intrabar_rule === "optimistic" ? " · optimistic" : ""}
              {" · "}{timeAgo(exp.created_at)}
            </p>
          )}
        </div>
        <div className="flex items-center gap-1.5 flex-shrink-0">
          {exp.verdict && verdictBadge(exp.verdict)}
          {exp.score != null && (
            <span className="text-[10px] font-mono text-zinc-300 bg-zinc-800 border border-zinc-700 rounded px-1.5 py-0.5">
              {exp.score.toFixed(1)}/100
            </span>
          )}
          {exp.status === "queued" && (
            <Button size="sm" className="h-6 px-2 font-mono text-[11px] bg-sky-600 hover:bg-sky-500 text-white"
              onClick={() => onRun(exp.id)}>
              <Play className="h-3 w-3 mr-1" /> Run
            </Button>
          )}
          {exp.status !== "running" && (
            <Button size="sm" variant="ghost" className="h-6 w-6 p-0 text-zinc-500 hover:text-red-400"
              onClick={() => onDelete(exp.id)}>
              <Trash2 className="h-3.5 w-3.5" />
            </Button>
          )}
          {(exp.status === "completed" || exp.status === "rejected" || exp.status === "failed") && (
            <button className="text-zinc-500 hover:text-zinc-300" onClick={() => setExpanded(e => !e)}>
              {expanded ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}
            </button>
          )}
        </div>
      </div>

      {/* Running progress */}
      {exp.status === "running" && prog && (
        <div className="space-y-1">
          <div className="flex justify-between text-[10px] font-mono text-zinc-400">
            <span>{prog.phase || "Initializing…"}</span>
            <span>{prog.progress_pct != null ? `${prog.progress_pct}%` : "…"}</span>
          </div>
          {prog.progress_pct != null && (
            <div className="h-1 bg-zinc-700 rounded-full">
              <div className="h-full bg-sky-500 rounded-full transition-all" style={{ width: `${prog.progress_pct}%` }} />
            </div>
          )}
          {prog.logs?.length > 0 && (
            <p className="text-[9px] font-mono text-zinc-500 truncate">{prog.logs[prog.logs.length - 1]}</p>
          )}
        </div>
      )}

      {/* Overfitting flags */}
      {exp.auto_rejected && exp.overfitting_flags && exp.overfitting_flags.length > 0 && (
        <div className="text-[10px] font-mono text-amber-400 bg-amber-500/10 border border-amber-500/30 rounded px-2 py-1.5">
          <span className="font-semibold">Auto-rejected — overfitting flags:</span>
          <ul className="mt-0.5 space-y-0.5">
            {exp.overfitting_flags.map(f => <li key={f}>• {f}</li>)}
          </ul>
        </div>
      )}

      {/* Failed error */}
      {exp.status === "failed" && exp.error && (
        <div className="text-[10px] font-mono text-red-400 bg-red-500/10 border border-red-500/30 rounded px-2 py-1.5">
          {exp.error.slice(0, 300)}
        </div>
      )}

      {/* Expanded metrics */}
      {expanded && exp.metrics && (
        <div className="pt-1 border-t border-zinc-800">
          <div className="grid grid-cols-4 gap-x-4 gap-y-1 text-[10px] font-mono">
            {[
              ["Trades", exp.metrics.total_trades],
              ["Return", fmtPct(exp.metrics.total_return_pct)],
              ["Net P&L", fmtINR(exp.metrics.net_pnl)],
              ["Win Rate", fmtPct(exp.metrics.win_rate)],
              ["Profit Factor", fmtNum(exp.metrics.profit_factor)],
              ["Expectancy", fmtINR(exp.metrics.expectancy)],
              ["Sharpe", fmtNum(exp.metrics.sharpe)],
              ["Drawdown", fmtPct(exp.metrics.max_drawdown_pct)],
              ["Brier", fmtNum(exp.metrics.brier_score, 4)],
              ["ECE", fmtNum(exp.metrics.ece, 4)],
              ["Evidence", exp.metrics.ev_verdict ?? "—"],
              ["OOS Trades", exp.metrics.ev_trades ?? "—"],
            ].map(([lbl, val]) => (
              <div key={String(lbl)}>
                <span className="text-zinc-500">{lbl} </span>
                <span className="text-zinc-200">{String(val ?? "—")}</span>
              </div>
            ))}
          </div>
          {exp.score_breakdown && (
            <div className="mt-2">
              <ScoreBar score={exp.score ?? 0} breakdown={exp.score_breakdown} />
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ── Leaderboard Entry ──────────────────────────────────────────────────────

function LeaderboardCard({ entry, rank, onDelete }: {
  entry: LeaderboardEntry;
  rank: number;
  onDelete: (id: string) => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const m = entry.metrics ?? {};

  return (
    <div className={cn(
      "rounded-md border p-3 space-y-2 transition-colors",
      entry.auto_rejected
        ? "border-amber-500/20 bg-amber-500/5 opacity-70"
        : rank === 1 ? "border-yellow-500/40 bg-yellow-500/5"
        : rank === 2 ? "border-zinc-400/30 bg-zinc-400/5"
        : rank === 3 ? "border-amber-700/30 bg-amber-700/5"
        : "border-zinc-700 bg-zinc-800/20"
    )}>
      <div className="flex items-start gap-3 flex-wrap">
        <div className="flex-shrink-0 w-8 text-center pt-0.5">{rankMedal(rank)}</div>
        <div className="flex-1 min-w-0 space-y-1">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-xs font-mono font-semibold">{entry.name}</span>
            {entry.tags?.map(t => (
              <Badge key={t} variant="outline" className="text-[9px] font-mono text-zinc-500 border-zinc-700 px-1">{t}</Badge>
            ))}
            {verdictBadge(entry.verdict)}
            {entry.metrics?.ev_verdict && (
              <Badge variant="outline" className="text-[9px] font-mono text-sky-400 border-sky-700 px-1">
                Ev: {entry.metrics.ev_verdict}
              </Badge>
            )}
            {entry.auto_rejected && (
              <Badge variant="outline" className="text-amber-400 border-amber-600 text-[9px] font-mono">AUTO-REJECTED</Badge>
            )}
          </div>
          <ScoreBar score={entry.score} breakdown={entry.score_breakdown} />
          <div className="flex flex-wrap gap-x-4 gap-y-0.5 text-[10px] font-mono text-zinc-400">
            <span>PF <span className="text-zinc-200">{fmtNum(m.profit_factor)}</span></span>
            <span>Exp <span className="text-zinc-200">{fmtINR(m.expectancy)}</span></span>
            <span>Sharpe <span className="text-zinc-200">{fmtNum(m.sharpe)}</span></span>
            <span>DD <span className="text-zinc-200">{fmtPct(m.max_drawdown_pct)}</span></span>
            <span>WR <span className="text-zinc-200">{fmtPct(m.win_rate)}</span></span>
            <span>ECE <span className="text-zinc-200">{fmtNum(m.ece, 4)}</span></span>
            <span>Trades <span className="text-zinc-200">{m.total_trades ?? "—"}</span></span>
            <span>Win <span className="text-zinc-200">{m.windows ?? "—"} windows</span></span>
          </div>
          {entry.config_summary && (
            <p className="text-[10px] font-mono text-zinc-500">
              {entry.config_summary.train_years}yr / {entry.config_summary.test_months}mo test
              {entry.config_summary.start_date ? ` · ${entry.config_summary.start_date}–${entry.config_summary.end_date || "now"}` : ""}
              {" · "}{timeAgo(entry.completed_at)}
            </p>
          )}
          {entry.auto_rejected && entry.overfitting_flags && (
            <p className="text-[10px] font-mono text-amber-400">
              ⚠ {entry.overfitting_flags[0]}
              {entry.overfitting_flags.length > 1 ? ` +${entry.overfitting_flags.length - 1} more` : ""}
            </p>
          )}
        </div>
        <div className="flex-shrink-0 flex gap-1">
          <button className="text-zinc-500 hover:text-zinc-300" onClick={() => setExpanded(e => !e)}>
            {expanded ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
          </button>
          <Button size="sm" variant="ghost" className="h-6 w-6 p-0 text-zinc-500 hover:text-red-400"
            onClick={() => onDelete(entry.id)}>
            <Trash2 className="h-3.5 w-3.5" />
          </Button>
        </div>
      </div>

      {expanded && (
        <div className="pt-2 border-t border-zinc-800 grid grid-cols-3 gap-x-4 gap-y-1 text-[10px] font-mono">
          {[
            ["Score", `${entry.score.toFixed(1)}/100`],
            ["Trades", m.total_trades],
            ["Return %", fmtPct(m.total_return_pct)],
            ["Net P&L", fmtINR(m.net_pnl)],
            ["Win Rate", fmtPct(m.win_rate)],
            ["Profit Factor", fmtNum(m.profit_factor)],
            ["Expectancy", fmtINR(m.expectancy)],
            ["Sharpe Ratio", fmtNum(m.sharpe)],
            ["Max Drawdown", fmtPct(m.max_drawdown_pct)],
            ["Brier Score", fmtNum(m.brier_score, 4)],
            ["ECE", fmtNum(m.ece, 4)],
            ["Evidence Verdict", m.ev_verdict ?? "—"],
            ["Evidence Trades", m.ev_trades],
            ["Windows", m.windows],
            ["Universe", m.universe_size ? `${m.universe_size} stocks` : "NIFTY 50"],
          ].map(([lbl, val]) => (
            <div key={String(lbl)}>
              <span className="text-zinc-500">{lbl} </span>
              <span className="text-zinc-200">{String(val ?? "—")}</span>
            </div>
          ))}
          {entry.overfitting_flags && entry.overfitting_flags.length > 0 && (
            <div className="col-span-3 text-amber-400 mt-1">
              Flags: {entry.overfitting_flags.join(" · ")}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ── Main Page ──────────────────────────────────────────────────────────────

export default function ExperimentManager() {
  const { toast } = useToast();
  const [experiments, setExperiments] = useState<Experiment[]>([]);
  const [leaderboard, setLeaderboard] = useState<LeaderboardEntry[]>([]);
  const [activeTab, setActiveTab] = useState<"queue" | "leaderboard">("queue");
  const [runningId, setRunningId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const hasRunning = experiments.some(e => e.status === "running");
  const queuedCount = experiments.filter(e => e.status === "queued").length;
  const completedCount = experiments.filter(e => e.status === "completed" || e.status === "rejected").length;

  const fetchExperiments = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/experiments`);
      const data = await res.json();
      if (data.experiments) setExperiments(data.experiments);
    } catch { /* silent */ }
  }, []);

  const fetchLeaderboard = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/experiments/leaderboard`);
      const data = await res.json();
      if (data.entries) setLeaderboard(data.entries);
    } catch { /* silent */ }
  }, []);

  async function fetchAll() {
    setLoading(true);
    await Promise.all([fetchExperiments(), fetchLeaderboard()]);
    setLoading(false);
  }

  // Initial load + poll while running
  useEffect(() => {
    fetchAll();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!hasRunning) return;
    const timer = setInterval(async () => {
      await fetchExperiments();
      // Refresh leaderboard when a run just finished
      const wasRunning = hasRunning;
      if (wasRunning) fetchLeaderboard();
    }, 4000);
    return () => clearInterval(timer);
  }, [hasRunning, fetchExperiments, fetchLeaderboard]);

  // Watch for transition out of running → refresh leaderboard
  useEffect(() => {
    if (!hasRunning) {
      fetchLeaderboard();
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [hasRunning]);

  async function handleRun(id: string) {
    if (hasRunning) {
      toast({ title: "Already running", description: "One experiment is already in progress. Wait for it to finish.", variant: "destructive" });
      return;
    }
    setRunningId(id);
    try {
      const res = await fetch(`${API_BASE}/experiments/${id}/run`, { method: "POST" });
      const data = await res.json();
      if (!res.ok || data.error) throw new Error(data.error || `HTTP ${res.status}`);
      toast({ title: "Experiment started", description: "Walk-forward validation is now running." });
      await fetchExperiments();
    } catch (e) {
      toast({ title: "Failed to start", description: String(e), variant: "destructive" });
    } finally {
      setRunningId(null);
    }
  }

  async function handleDelete(id: string) {
    try {
      const res = await fetch(`${API_BASE}/experiments/${id}`, { method: "DELETE" });
      const data = await res.json();
      if (!res.ok || data.error) throw new Error(data.error || `HTTP ${res.status}`);
      toast({ title: "Deleted", description: "Experiment removed." });
      await fetchAll();
    } catch (e) {
      toast({ title: "Delete failed", description: String(e), variant: "destructive" });
    }
  }

  return (
    <div className="space-y-4 max-w-5xl mx-auto">
      {/* Header */}
      <div className="flex items-start justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-xl font-mono font-bold flex items-center gap-2">
            <FlaskConical className="h-5 w-5 text-violet-400" />
            Research Factory
          </h1>
          <p className="text-sm font-mono text-muted-foreground mt-1">
            Queue and compare walk-forward experiments · ranked leaderboard · auto-reject overfitting
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Badge variant="outline" className="text-[10px] font-mono text-violet-300 border-violet-500/40">
            PAPER · RESEARCH ONLY
          </Badge>
          <Button size="sm" variant="outline" className="font-mono text-xs gap-1.5"
            onClick={fetchAll} disabled={loading}>
            <RefreshCw className={cn("h-3.5 w-3.5", loading && "animate-spin")} />
            Refresh
          </Button>
        </div>
      </div>

      {/* Safety banner */}
      <div className="rounded-md border border-amber-500/30 bg-amber-500/5 px-3 py-2 text-[11px] font-mono text-amber-400">
        ⚠ Out-of-sample historical performance does not guarantee future results.
        Every experiment uses strict train/test splits with no look-ahead bias.
        Paper trading and research only.
      </div>

      {/* Submit form */}
      <SubmitForm onSubmitted={fetchAll} />

      {/* Tabs */}
      <div className="flex gap-0 border border-zinc-700 rounded-md overflow-hidden w-fit">
        {[
          { id: "queue" as const, label: `Queue (${experiments.length})`, icon: Clock },
          { id: "leaderboard" as const, label: `Leaderboard (${completedCount})`, icon: Trophy },
        ].map(({ id, label, icon: Icon }) => (
          <button
            key={id}
            onClick={() => setActiveTab(id)}
            className={cn(
              "px-4 py-2 text-xs font-mono flex items-center gap-1.5 transition-colors",
              activeTab === id ? "bg-zinc-700 text-zinc-100" : "text-zinc-400 hover:text-zinc-200 hover:bg-zinc-800"
            )}
          >
            <Icon className="h-3.5 w-3.5" />
            {label}
            {id === "queue" && hasRunning && (
              <span className="w-1.5 h-1.5 rounded-full bg-sky-400 animate-pulse ml-0.5" />
            )}
          </button>
        ))}
      </div>

      {/* Queue tab */}
      {activeTab === "queue" && (
        <div className="space-y-2">
          {loading && experiments.length === 0 && (
            <div className="text-center py-10 text-sm font-mono text-muted-foreground">
              <Loader2 className="h-5 w-5 animate-spin mx-auto mb-2 text-zinc-600" />
              Loading experiments…
            </div>
          )}
          {!loading && experiments.length === 0 && (
            <Card>
              <CardContent className="py-10 text-center">
                <FlaskConical className="h-8 w-8 mx-auto mb-3 text-zinc-700" />
                <p className="text-sm font-mono text-muted-foreground">No experiments yet.</p>
                <p className="text-xs font-mono text-zinc-600 mt-1">Click <strong>New Experiment</strong> above to queue your first run.</p>
              </CardContent>
            </Card>
          )}
          {experiments.map(exp => (
            <ExperimentCard
              key={exp.id}
              exp={exp}
              onRun={handleRun}
              onDelete={handleDelete}
            />
          ))}
          {queuedCount > 0 && !hasRunning && (
            <p className="text-[10px] font-mono text-zinc-500 text-center py-1">
              {queuedCount} experiment{queuedCount !== 1 ? "s" : ""} queued — click <strong>Run</strong> to execute one at a time.
            </p>
          )}
        </div>
      )}

      {/* Leaderboard tab */}
      {activeTab === "leaderboard" && (
        <div className="space-y-2">
          {leaderboard.length === 0 && (
            <Card>
              <CardContent className="py-10 text-center">
                <Trophy className="h-8 w-8 mx-auto mb-3 text-zinc-700" />
                <p className="text-sm font-mono text-muted-foreground">No completed experiments yet.</p>
                <p className="text-xs font-mono text-zinc-600 mt-1">Run an experiment to see it ranked here.</p>
              </CardContent>
            </Card>
          )}
          {leaderboard.length > 0 && (
            <div className="flex items-center gap-2 text-[10px] font-mono text-zinc-500 pb-1">
              <BarChart3 className="h-3.5 w-3.5" />
              Scored 0–100: profit factor (25) + expectancy (20) + Sharpe (20) + drawdown (15) + calibration (10) + evidence (10)
              · Auto-rejected if overfitting hard-flags triggered
            </div>
          )}
          {(() => {
            let rank = 0;
            return leaderboard.map(entry => {
              if (!entry.auto_rejected) rank++;
              return (
                <LeaderboardCard
                  key={entry.id}
                  entry={entry}
                  rank={entry.auto_rejected ? leaderboard.length : rank}
                  onDelete={handleDelete}
                />
              );
            });
          })()}
        </div>
      )}

      {/* Safety footer */}
      <p className="text-[10px] font-mono text-zinc-600 text-center border-t border-zinc-800 pt-3">
        All experiments share the NIFTY 50 universe · ₹5,000 capital · strict no-look-ahead train/test splits ·
        live paper-trading behaviour unchanged by experiments
      </p>
    </div>
  );
}
