/**
 * AiCopilot.tsx — Phase 9: AI Copilot hub.
 * Sections: Daily Briefing (voice-ready), Trade Explanations, Why Not Buy?,
 * Watchlist Insights, AI Confidence History charts, Export, verification summary.
 */

import { useState, useEffect, useCallback } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import {
  Bot, Sunrise, RefreshCw, Loader2, Download, Search,
  AlertTriangle, CheckCircle2, XCircle, TrendingUp, TrendingDown,
  HelpCircle, Eye, LineChart as LineChartIcon, Volume2, ShieldCheck,
  ChevronDown, ChevronUp, Minus,
} from "lucide-react";
import {
  ResponsiveContainer, LineChart, Line, XAxis, YAxis, Tooltip,
  CartesianGrid, Legend,
} from "recharts";
import { cn } from "@/lib/utils";
import { API_BASE } from "@/lib/api";
import { useToast } from "@/hooks/use-toast";
import DataFreshnessBar from "@/components/DataFreshnessBar";

/* eslint-disable @typescript-eslint/no-explicit-any */

async function api(path: string): Promise<any> {
  const r = await fetch(`${API_BASE}${path}`);
  const t = await r.text();
  const d = JSON.parse(t);
  if (!r.ok || d.error) throw new Error(d.error ?? `HTTP ${r.status}`);
  return d;
}

const RISK_COLOR: Record<string, string> = {
  LOW: "text-emerald-400", MEDIUM: "text-amber-400", HIGH: "text-red-400",
};
const TREND_ICON: Record<string, any> = { UP: TrendingUp, DOWN: TrendingDown, MIXED: Minus };

function SectionTitle({ children, icon }: { children: React.ReactNode; icon: React.ReactNode }) {
  return (
    <h2 className="mb-3 flex items-center gap-2 font-mono text-sm font-bold uppercase tracking-widest text-zinc-300">
      {icon}{children}
    </h2>
  );
}

export default function AiCopilot() {
  const { toast } = useToast();
  const [briefing, setBriefing] = useState<any>(null);
  const [explanations, setExplanations] = useState<any[]>([]);
  const [insights, setInsights] = useState<any[]>([]);
  const [history, setHistory] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [whyNotSymbol, setWhyNotSymbol] = useState("");
  const [whyNot, setWhyNot] = useState<any>(null);
  const [whyNotLoading, setWhyNotLoading] = useState(false);
  const [expandedExpl, setExpandedExpl] = useState<string | null>(null);
  const [showVerify, setShowVerify] = useState(false);

  const load = useCallback(async () => {
    setLoading(true); setError(null);
    try {
      const [b, e, w, h] = await Promise.all([
        api("/copilot/briefing"),
        api("/copilot/explanations?limit=10"),
        api("/copilot/watchlist-insights"),
        api("/copilot/confidence-history"),
      ]);
      setBriefing(b);
      setExplanations(e.explanations ?? []);
      setInsights(w.insights ?? []);
      setHistory(h);
    } catch (e: any) {
      setError(e.message ?? "Failed to load copilot data");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const lookupWhyNot = async () => {
    if (!whyNotSymbol.trim()) return;
    setWhyNotLoading(true); setWhyNot(null);
    try {
      const d = await api(`/copilot/why-not/${encodeURIComponent(whyNotSymbol.trim().toUpperCase())}`);
      if (!d.success) throw new Error(d.error ?? "Lookup failed");
      setWhyNot(d);
    } catch (e: any) {
      toast({ title: "Lookup failed", description: e.message, variant: "destructive" });
    } finally {
      setWhyNotLoading(false);
    }
  };

  const doExport = async (kind: "json" | "csv") => {
    try {
      const resp = await fetch(`${API_BASE}/copilot/export?kind=${kind}`);
      if (!resp.ok) throw new Error(`Export failed (HTTP ${resp.status})`);
      const blob = await resp.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url; a.download = kind === "csv" ? "phase9_alerts.csv" : "phase9_export.json";
      document.body.appendChild(a); a.click(); document.body.removeChild(a);
      URL.revokeObjectURL(url);
      toast({ title: "Export downloaded" });
    } catch (e: any) {
      toast({ title: "Export failed", description: e.message, variant: "destructive" });
    }
  };

  if (loading) return (
    <div className="flex h-64 items-center justify-center gap-3 font-mono text-zinc-500">
      <Loader2 className="h-5 w-5 animate-spin" />Loading AI Copilot…
    </div>
  );

  if (error) return (
    <div className="rounded-lg border border-red-800 bg-red-950/30 p-6 font-mono text-sm text-red-300">
      <AlertTriangle className="mr-2 inline h-4 w-4" />{error}
      <Button size="sm" variant="outline" className="ml-4" onClick={load}>Retry</Button>
    </div>
  );

  const series = (history?.series ?? []).map((s: any, i: number) => ({
    ...s, idx: i + 1,
    scan: (s.scan_id ?? "").slice(0, 6),
  }));

  return (
    <div className="space-y-6 font-mono">
      {/* Header */}
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <div className="mb-1 flex items-center gap-3">
            <Bot className="h-5 w-5 text-primary" />
            <h1 className="text-xl font-bold text-foreground">AI Copilot</h1>
            <Badge variant="outline" className="text-[10px] text-amber-400 border-amber-700">
              PAPER / LIVE DATA VALIDATION
            </Badge>
          </div>
          <p className="text-xs text-zinc-500">
            Rule-based AI assistant — briefings, explanations, and insights from cached scans. Research only.
          </p>
        </div>
        <div className="flex gap-2">
          <Button size="sm" variant="outline" onClick={load} className="gap-2 text-xs">
            <RefreshCw className="h-3.5 w-3.5" />Refresh
          </Button>
          <Button size="sm" variant="outline" onClick={() => doExport("json")} className="gap-2 text-xs">
            <Download className="h-3.5 w-3.5" />JSON
          </Button>
          <Button size="sm" variant="outline" onClick={() => doExport("csv")} className="gap-2 text-xs">
            <Download className="h-3.5 w-3.5" />CSV
          </Button>
        </div>
      </div>

      <DataFreshnessBar variant="scan" />

      {/* ── Daily Briefing ─────────────────────────────────────────────────── */}
      {briefing && (
        <Card className="border-zinc-800 bg-zinc-900/60">
          <CardHeader className="px-5 pb-2 pt-4">
            <SectionTitle icon={<Sunrise className="h-4 w-4 text-primary" />}>
              Daily Briefing — {briefing.date}
            </SectionTitle>
          </CardHeader>
          <CardContent className="px-5 pb-5">
            <div className="mb-4 rounded-lg border border-primary/30 bg-primary/5 p-4">
              <div className="mb-2 text-sm font-bold text-primary">{briefing.greeting}</div>
              {(briefing.briefing_lines ?? []).slice(1).map((l: string, i: number) => (
                <div key={i} className="py-0.5 text-xs text-zinc-300">{l}</div>
              ))}
            </div>
            <div className="grid grid-cols-4 gap-3 text-xs">
              <div className="rounded-md border border-zinc-700/50 bg-zinc-800/50 p-3">
                <div className="mb-1 text-[10px] text-zinc-500">Top Sectors</div>
                {(briefing.top_sectors ?? []).map((s: any) => (
                  <div key={s.sector} className="flex justify-between py-0.5">
                    <span className="text-emerald-400">{s.sector}</span>
                    <span className="text-zinc-500">{s.score}</span>
                  </div>
                ))}
                {(briefing.top_sectors ?? []).length === 0 && <span className="text-zinc-600">—</span>}
              </div>
              <div className="rounded-md border border-zinc-700/50 bg-zinc-800/50 p-3">
                <div className="mb-1 text-[10px] text-zinc-500">Weak Sectors</div>
                {(briefing.weak_sectors ?? []).map((s: any) => (
                  <div key={s.sector} className="flex justify-between py-0.5">
                    <span className="text-red-400">{s.sector}</span>
                    <span className="text-zinc-500">{s.score}</span>
                  </div>
                ))}
                {(briefing.weak_sectors ?? []).length === 0 && <span className="text-zinc-600">—</span>}
              </div>
              <div className="rounded-md border border-zinc-700/50 bg-zinc-800/50 p-3">
                <div className="mb-1 text-[10px] text-zinc-500">Today's Opportunities</div>
                {(briefing.opportunities ?? []).slice(0, 3).map((o: any) => (
                  <div key={o.symbol} className="flex justify-between py-0.5">
                    <span className="text-zinc-200">{o.symbol}</span>
                    <span className="text-zinc-500">{o.opportunity_score}</span>
                  </div>
                ))}
              </div>
              <div className="rounded-md border border-zinc-700/50 bg-zinc-800/50 p-3">
                <div className="mb-1 text-[10px] text-zinc-500">Risk & Volatility</div>
                <div className="py-0.5">
                  Risk: <span className={RISK_COLOR[briefing.risk_assessment] ?? ""}>{briefing.risk_assessment}</span>
                </div>
                <div className="py-0.5 text-zinc-400">
                  VIX {briefing.expected_volatility?.vix} ({briefing.expected_volatility?.category})
                </div>
                <div className="py-0.5 text-[10px] text-zinc-600">
                  Econ events: {briefing.economic_events?.[0]?.status}
                </div>
              </div>
            </div>
            <div className="mt-3 rounded-md border border-zinc-800 bg-zinc-900/40 p-3">
              <div className="mb-1 flex items-center gap-1.5 text-[10px] text-zinc-500">
                <Volume2 className="h-3 w-3" />VOICE-READY BRIEFING
              </div>
              <p className="text-[10px] italic leading-relaxed text-zinc-400">"{briefing.voice_text}"</p>
            </div>
          </CardContent>
        </Card>
      )}

      {/* ── Confidence History Charts ──────────────────────────────────────── */}
      <Card className="border-zinc-800 bg-zinc-900/60">
        <CardHeader className="px-5 pb-2 pt-4">
          <SectionTitle icon={<LineChartIcon className="h-4 w-4 text-primary" />}>
            AI Confidence History <span className="ml-1 text-xs normal-case text-zinc-500">({history?.snapshots ?? 0} snapshots)</span>
          </SectionTitle>
        </CardHeader>
        <CardContent className="px-5 pb-5">
          {series.length < 2 ? (
            <div className="py-6 text-center text-xs text-zinc-500">
              {series.length === 0
                ? "No snapshots recorded yet — snapshots are captured automatically per scan."
                : "One snapshot recorded. Charts appear after the next scan creates a second point."}
              {series.length === 1 && (
                <div className="mx-auto mt-4 grid max-w-lg grid-cols-4 gap-3">
                  {[
                    { label: "Avg Confidence", v: series[0].avg_confidence },
                    { label: "Avg Opp. Score", v: series[0].avg_opportunity_score },
                    { label: "Trade Quality %", v: series[0].trade_quality_pct },
                    { label: "Buy Signals", v: series[0].buy_count },
                  ].map(({ label, v }) => (
                    <div key={label} className="rounded-md border border-zinc-700/50 bg-zinc-800/50 p-3">
                      <div className="text-lg font-bold text-primary">{v}</div>
                      <div className="text-[10px] text-zinc-500">{label}</div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          ) : (
            <div className="grid grid-cols-2 gap-4">
              <div className="h-56">
                <div className="mb-1 text-[10px] text-zinc-500">Confidence & Opportunity Score Evolution</div>
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart data={series}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#27272a" />
                    <XAxis dataKey="scan" tick={{ fontSize: 9, fill: "#71717a" }} />
                    <YAxis tick={{ fontSize: 9, fill: "#71717a" }} />
                    <Tooltip contentStyle={{ background: "#18181b", border: "1px solid #3f3f46", fontSize: 11 }} />
                    <Legend wrapperStyle={{ fontSize: 10 }} />
                    <Line type="monotone" dataKey="avg_confidence" name="Avg Confidence" stroke="#38bdf8" strokeWidth={2} dot={{ r: 2 }} />
                    <Line type="monotone" dataKey="avg_opportunity_score" name="Avg Opp. Score" stroke="#a78bfa" strokeWidth={2} dot={{ r: 2 }} />
                  </LineChart>
                </ResponsiveContainer>
              </div>
              <div className="h-56">
                <div className="mb-1 text-[10px] text-zinc-500">Trade Quality & Signal Evolution</div>
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart data={series}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#27272a" />
                    <XAxis dataKey="scan" tick={{ fontSize: 9, fill: "#71717a" }} />
                    <YAxis tick={{ fontSize: 9, fill: "#71717a" }} />
                    <Tooltip contentStyle={{ background: "#18181b", border: "1px solid #3f3f46", fontSize: 11 }} />
                    <Legend wrapperStyle={{ fontSize: 10 }} />
                    <Line type="monotone" dataKey="trade_quality_pct" name="Trade Quality %" stroke="#34d399" strokeWidth={2} dot={{ r: 2 }} />
                    <Line type="monotone" dataKey="buy_count" name="Buy Signals" stroke="#fbbf24" strokeWidth={2} dot={{ r: 2 }} />
                    <Line type="monotone" dataKey="watch_count" name="Watch Signals" stroke="#f472b6" strokeWidth={2} dot={{ r: 2 }} />
                  </LineChart>
                </ResponsiveContainer>
              </div>
            </div>
          )}
        </CardContent>
      </Card>

      {/* ── Trade Explanations ─────────────────────────────────────────────── */}
      <Card className="border-zinc-800 bg-zinc-900/60">
        <CardHeader className="px-5 pb-2 pt-4">
          <SectionTitle icon={<Eye className="h-4 w-4 text-primary" />}>
            Trade Explanations <span className="ml-1 text-xs normal-case text-zinc-500">(top {explanations.length} by opportunity)</span>
          </SectionTitle>
        </CardHeader>
        <CardContent className="px-5 pb-5">
          <div className="space-y-2">
            {explanations.map((e: any) => {
              const open = expandedExpl === e.symbol;
              return (
                <div key={e.symbol} className="rounded-lg border border-zinc-700/60 bg-zinc-900/70">
                  <button className="flex w-full items-center gap-3 px-4 py-2.5 text-left"
                    onClick={() => setExpandedExpl(open ? null : e.symbol)}>
                    <span className="w-24 text-sm font-bold text-zinc-100">{e.symbol}</span>
                    <Badge variant="outline" className={cn("text-[10px]",
                      e.action === "BUY" || e.action === "STRONG_BUY" ? "border-emerald-700 text-emerald-400"
                        : e.action === "WATCH" ? "border-amber-700 text-amber-400"
                        : "border-zinc-600 text-zinc-400")}>
                      {e.action}
                    </Badge>
                    <span className="text-xs text-zinc-500">Conf {Math.round(e.confidence ?? 0)}</span>
                    <span className="text-xs text-zinc-500">Score {e.opportunity_score}</span>
                    <span className={cn("text-xs", RISK_COLOR[e.risk])}>Risk {e.risk}</span>
                    <span className="ml-auto text-[10px] text-zinc-600">
                      {e.indicators_supporting.length} for / {e.indicators_against.length} against
                    </span>
                    {open ? <ChevronUp className="h-4 w-4 text-zinc-500" /> : <ChevronDown className="h-4 w-4 text-zinc-500" />}
                  </button>
                  {open && (
                    <div className="border-t border-zinc-800 px-4 py-3 text-xs">
                      <div className="grid grid-cols-2 gap-4">
                        <div>
                          <div className="mb-1.5 text-[10px] font-bold text-emerald-500">INDICATORS SUPPORTING</div>
                          {e.indicators_supporting.map((s: string, i: number) => (
                            <div key={i} className="flex items-start gap-1.5 py-0.5 text-zinc-300">
                              <CheckCircle2 className="mt-0.5 h-3 w-3 flex-shrink-0 text-emerald-400" />{s}
                            </div>
                          ))}
                          {e.indicators_supporting.length === 0 && <span className="text-zinc-600">None</span>}
                        </div>
                        <div>
                          <div className="mb-1.5 text-[10px] font-bold text-red-500">INDICATORS AGAINST</div>
                          {e.indicators_against.map((s: string, i: number) => (
                            <div key={i} className="flex items-start gap-1.5 py-0.5 text-zinc-300">
                              <XCircle className="mt-0.5 h-3 w-3 flex-shrink-0 text-red-400" />{s}
                            </div>
                          ))}
                          {e.indicators_against.length === 0 && <span className="text-zinc-600">None</span>}
                        </div>
                      </div>
                      <div className="mt-3 grid grid-cols-5 gap-2">
                        {[
                          ["Expected Hold", e.expected_holding_period_days != null ? `${e.expected_holding_period_days} days` : "—"],
                          ["Historical Win Rate", e.historical_win_rate != null ? `${Math.round(e.historical_win_rate)}%` : "—"],
                          ["Expected Reward", e.expected_reward_pct != null ? `+${e.expected_reward_pct}%` : "—"],
                          ["R/R Ratio", e.rr_ratio ?? "—"],
                          ["Profit Factor", e.profit_factor ?? "—"],
                        ].map(([k, v]) => (
                          <div key={k as string} className="rounded border border-zinc-700/40 bg-zinc-800/40 p-2">
                            <div className="text-[9px] text-zinc-500">{k}</div>
                            <div className="mt-0.5 font-bold text-zinc-200">{v}</div>
                          </div>
                        ))}
                      </div>
                      <div className="mt-2 rounded border border-zinc-800 bg-zinc-900/50 p-2">
                        <div className="mb-0.5 flex items-center gap-1 text-[9px] text-zinc-500">
                          <Volume2 className="h-2.5 w-2.5" />VOICE-READY
                        </div>
                        <p className="text-[10px] italic text-zinc-400">"{e.voice_text}"</p>
                      </div>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </CardContent>
      </Card>

      {/* ── Why Not Buy? ───────────────────────────────────────────────────── */}
      <Card className="border-zinc-800 bg-zinc-900/60">
        <CardHeader className="px-5 pb-2 pt-4">
          <SectionTitle icon={<HelpCircle className="h-4 w-4 text-primary" />}>Why Not Buy?</SectionTitle>
        </CardHeader>
        <CardContent className="px-5 pb-5">
          <div className="mb-3 flex gap-2">
            <input value={whyNotSymbol} onChange={e => setWhyNotSymbol(e.target.value)}
              onKeyDown={e => e.key === "Enter" && lookupWhyNot()}
              placeholder="Enter symbol (e.g. ICICIBANK)"
              className="w-64 rounded border border-zinc-700 bg-zinc-800 px-3 py-1.5 text-xs text-zinc-200 focus:border-primary focus:outline-none" />
            <Button size="sm" onClick={lookupWhyNot} disabled={whyNotLoading} className="gap-2 text-xs">
              {whyNotLoading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Search className="h-3.5 w-3.5" />}
              Explain
            </Button>
          </div>
          {whyNot && (
            <div className="rounded-lg border border-zinc-700 bg-zinc-800/50 p-4 text-xs">
              <div className="mb-2 flex items-center gap-3">
                <span className="text-sm font-bold text-zinc-100">{whyNot.symbol}</span>
                <Badge variant="outline" className="border-zinc-600 text-[10px] text-zinc-300">{whyNot.final_action}</Badge>
                <span className="text-zinc-500">Confidence {Math.round(whyNot.confidence ?? 0)}</span>
                <span className="text-zinc-500">Score {whyNot.opportunity_score}</span>
                {whyNot.confidence_lost_to_history != null && (
                  <span className="text-red-400">−{whyNot.confidence_lost_to_history} pts (history)</span>
                )}
              </div>
              <div className="grid grid-cols-3 gap-4">
                <div>
                  <div className="mb-1 text-[10px] font-bold text-red-500">REASONS</div>
                  {whyNot.reasons.map((r: string, i: number) => (
                    <div key={i} className="py-0.5 text-zinc-300">• {r}</div>
                  ))}
                </div>
                <div>
                  <div className="mb-1 text-[10px] font-bold text-amber-500">MISSING CONFIRMATIONS</div>
                  {whyNot.missing_confirmations.map((r: string, i: number) => (
                    <div key={i} className="py-0.5 text-zinc-300">• {r}</div>
                  ))}
                  {whyNot.missing_confirmations.length === 0 && <span className="text-zinc-600">None</span>}
                </div>
                <div>
                  <div className="mb-1 text-[10px] font-bold text-zinc-500">FAILED RULES</div>
                  {whyNot.failed_rules.map((r: string, i: number) => (
                    <div key={i} className="py-0.5 text-zinc-300">• {r}</div>
                  ))}
                  {whyNot.failed_rules.length === 0 && <span className="text-zinc-600">All gates passed</span>}
                </div>
              </div>
              <div className="mt-2 rounded border border-zinc-800 bg-zinc-900/50 p-2">
                <p className="text-[10px] italic text-zinc-400">"{whyNot.voice_text}"</p>
              </div>
            </div>
          )}
        </CardContent>
      </Card>

      {/* ── Watchlist Insights ─────────────────────────────────────────────── */}
      <Card className="border-zinc-800 bg-zinc-900/60">
        <CardHeader className="px-5 pb-2 pt-4">
          <SectionTitle icon={<Eye className="h-4 w-4 text-primary" />}>
            Watchlist Insights <span className="ml-1 text-xs normal-case text-zinc-500">({insights.length} stocks)</span>
          </SectionTitle>
        </CardHeader>
        <CardContent className="px-5 pb-5">
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-zinc-800 text-zinc-500">
                  {["Symbol","Action","Trend","Momentum","Strength","Confidence","Upside","Downside","Risk","Hold (days)"].map(h => (
                    <th key={h} className="py-2 pr-4 text-left font-medium">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {insights.map((s: any) => {
                  if (!s.available) return (
                    <tr key={s.symbol} className="border-b border-zinc-800/50 text-zinc-600">
                      <td className="py-2 pr-4 font-bold">{s.symbol}</td>
                      <td colSpan={9} className="py-2 pr-4">{s.note}</td>
                    </tr>
                  );
                  const TIcon = TREND_ICON[s.trend] ?? Minus;
                  return (
                    <tr key={s.symbol} className="border-b border-zinc-800/50 hover:bg-zinc-800/30">
                      <td className="py-2 pr-4 font-bold text-zinc-100">{s.symbol}</td>
                      <td className="py-2 pr-4 text-zinc-400">{s.action}</td>
                      <td className={cn("py-2 pr-4", s.trend === "UP" ? "text-emerald-400" : s.trend === "DOWN" ? "text-red-400" : "text-amber-400")}>
                        <TIcon className="mr-1 inline h-3 w-3" />{s.trend}
                      </td>
                      <td className={cn("py-2 pr-4", s.momentum === "STRONG" ? "text-emerald-400" : s.momentum === "WEAK" ? "text-red-400" : "text-zinc-400")}>{s.momentum}</td>
                      <td className={cn("py-2 pr-4", s.strength === "STRONG" ? "text-emerald-400" : s.strength === "WEAK" ? "text-red-400" : "text-zinc-400")}>{s.strength}</td>
                      <td className="py-2 pr-4 text-zinc-200">{Math.round(s.confidence ?? 0)}</td>
                      <td className="py-2 pr-4 text-emerald-400">{s.estimated_upside_pct != null ? `+${s.estimated_upside_pct}%` : "—"}</td>
                      <td className="py-2 pr-4 text-red-400">{s.estimated_downside_pct != null ? `−${s.estimated_downside_pct}%` : "—"}</td>
                      <td className={cn("py-2 pr-4", RISK_COLOR[s.risk])}>{s.risk}</td>
                      <td className="py-2 pr-4 text-zinc-400">{s.holding_period_days ?? "—"}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </CardContent>
      </Card>

      {/* ── Phase 9 Verification Summary ───────────────────────────────────── */}
      <Card className="border-zinc-800 bg-zinc-900/60">
        <CardHeader className="cursor-pointer px-5 pb-2 pt-4" onClick={() => setShowVerify(v => !v)}>
          <div className="flex items-center justify-between">
            <SectionTitle icon={<ShieldCheck className="h-4 w-4 text-primary" />}>
              Phase 9 Verification Summary
            </SectionTitle>
            {showVerify ? <ChevronUp className="h-4 w-4 text-zinc-500" /> : <ChevronDown className="h-4 w-4 text-zinc-500" />}
          </div>
        </CardHeader>
        {showVerify && (
          <CardContent className="px-5 pb-5">
            <div className="grid grid-cols-2 gap-3 text-xs">
              {[
                { label: "copilot_engine.py", detail: "Copilot summary, smart alerts (13 types), daily briefing, trade explanations, why-not, watchlist insights, confidence history, CSV/JSON export" },
                { label: "test_phase9.py", detail: "93 tests all passing — alerts dedup, sections, briefing, explanations, history, exports, read-only safety" },
                { label: "AI Copilot panel", detail: "Collapsible floating panel on every page — regime, sentiment, portfolio health, risks, best opportunity, avoid list, voice-ready text" },
                { label: "Smart alerts", detail: "BUY/SELL/SL/target/volume breakout/momentum/weakening/volatility/risk limit/regime change/sector rotation/confidence ±. Each has timestamp, reason, confidence, severity, stock, action" },
                { label: "Notification Center", detail: "Sections: Today, Unread, Trade, Risk, AI Suggestions, Market. Mark read single/all. CSV export" },
                { label: "No look-ahead", detail: "All analysis bound to cached scan snapshot (scan_id + snapshot_ts). Confidence history append-only, one snapshot per scan" },
                { label: "Safety preserved", detail: "Read-only engine — never mutates scan cache, paper state, or broker config. No auto-trading. Manual confirmation still required (Phase 8)" },
                { label: "Voice-ready", detail: "voice_text field on copilot summary, briefing, every explanation and why-not response — ready for future TTS" },
              ].map(({ label, detail }) => (
                <div key={label} className="rounded-md border border-emerald-900/40 bg-emerald-950/10 p-3">
                  <div className="mb-1 flex items-center gap-2">
                    <CheckCircle2 className="h-3.5 w-3.5 text-emerald-400" />
                    <span className="font-bold text-emerald-300">{label}</span>
                  </div>
                  <p className="pl-5 text-[10px] text-zinc-500">{detail}</p>
                </div>
              ))}
            </div>
          </CardContent>
        )}
      </Card>
    </div>
  );
}
