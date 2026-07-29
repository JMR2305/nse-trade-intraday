/**
 * ResearchLab.tsx — Phase 7.5
 * Research, Simulation & Innovation Lab dashboard
 * READ-ONLY · ADVISORY-ONLY
 */
import { useState } from "react";
import { useQuery }  from "@tanstack/react-query";
import {
  FlaskConical, TrendingUp, TrendingDown, BarChart2,
  AlertTriangle, CheckCircle, Clock, Lightbulb,
  BookOpen, FileText, Activity, Layers, Beaker,
  ChevronRight, Star,
} from "lucide-react";
import {
  Card, CardContent, CardHeader, CardTitle,
} from "@/components/ui/card";
import { Badge }  from "@/components/ui/badge";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { apiJson } from "@/lib/api";

// ── Data fetching ─────────────────────────────────────────────────────────────

const BASE = "research-lab";
const OPTS = { refetchInterval: 60_000 };

function useRL(key: string) {
  return useQuery({ queryKey: [BASE, key], queryFn: () => apiJson(`${BASE}/${key}`), ...OPTS });
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function Loading() {
  return (
    <div className="flex items-center justify-center py-16">
      <FlaskConical className="h-8 w-8 text-teal-400 animate-pulse" />
    </div>
  );
}

function GradeBadge({ grade }: { grade: string }) {
  const colours: Record<string, string> = {
    "A+": "bg-emerald-500/20 text-emerald-300 border-emerald-600/40",
    "A":  "bg-teal-500/20 text-teal-300 border-teal-600/40",
    "B":  "bg-blue-500/20 text-blue-300 border-blue-600/40",
    "C":  "bg-yellow-500/20 text-yellow-300 border-yellow-600/40",
    "D":  "bg-red-500/20 text-red-300 border-red-600/40",
  };
  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-bold border ${colours[grade] ?? colours["C"]}`}>
      {grade}
    </span>
  );
}

function TrendBadge({ trend }: { trend: string }) {
  if (trend === "IMPROVING") return <span className="text-emerald-400 text-xs flex items-center gap-1"><TrendingUp className="h-3 w-3" />Improving</span>;
  if (trend === "WEAKENING") return <span className="text-red-400 text-xs flex items-center gap-1"><TrendingDown className="h-3 w-3" />Weakening</span>;
  return <span className="text-slate-400 text-xs">Stable</span>;
}

function ImpactBadge({ label }: { label: string }) {
  if (label === "IMPROVED") return <Badge className="bg-emerald-500/20 text-emerald-300 text-xs">Improved</Badge>;
  if (label === "DEGRADED") return <Badge className="bg-red-500/20 text-red-300 text-xs">Degraded</Badge>;
  return <Badge className="bg-slate-500/20 text-slate-300 text-xs">Neutral</Badge>;
}

function ScoreRing({ score, label }: { score: number; label: string }) {
  const r = 36, circ = 2 * Math.PI * r;
  const filled = (score / 100) * circ;
  const colour = score >= 70 ? "#2dd4bf" : score >= 50 ? "#60a5fa" : "#f87171";
  return (
    <div className="flex flex-col items-center gap-1">
      <svg width="88" height="88" viewBox="0 0 88 88">
        <circle cx="44" cy="44" r={r} fill="none" stroke="#1e293b" strokeWidth="8" />
        <circle cx="44" cy="44" r={r} fill="none" stroke={colour} strokeWidth="8"
          strokeDasharray={`${filled} ${circ - filled}`}
          strokeLinecap="round"
          transform="rotate(-90 44 44)" />
        <text x="44" y="48" textAnchor="middle" fill={colour} fontSize="18" fontWeight="700">{Math.round(score)}</text>
      </svg>
      <span className="text-xs text-slate-400">{label}</span>
    </div>
  );
}

// ── Overview tab ──────────────────────────────────────────────────────────────

function OverviewTab({ data: raw }: { data: any }) {
  const d = raw?.data ?? raw;
  if (!d || d.status === "DISABLED") return (
    <Card className="bg-slate-800/50 border-slate-700">
      <CardContent className="pt-6 text-center text-slate-400 py-12 text-sm">
        Research Lab is disabled. Set <code className="text-teal-400">RESEARCH_LAB_ENABLED=true</code>.
      </CardContent>
    </Card>
  );

  const kpis = [
    { label: "Research Score", value: `${d.research_score ?? 0}/100` },
    { label: "Grade",          value: d.grade ?? "N/A" },
    { label: "Trend",          value: d.trend ?? "STABLE" },
    { label: "Strategies",     value: d.total_strategies ?? 0 },
    { label: "Scenarios",      value: d.total_scenarios ?? 0 },
    { label: "Experiments",    value: d.total_experiments ?? 0 },
    { label: "Live Signals",   value: d.total_signals ?? 0 },
    { label: "Benchmark Alpha", value: d.benchmark_alpha != null ? `${d.benchmark_alpha > 0 ? "+" : ""}${d.benchmark_alpha?.toFixed(1)}` : "—" },
  ];

  return (
    <div className="space-y-4">
      {/* Score ring + executive summary */}
      <div className="grid md:grid-cols-4 gap-4">
        <Card className="bg-teal-900/20 border-teal-700/40 flex items-center justify-center py-4">
          <CardContent className="pt-0 flex flex-col items-center gap-2">
            <ScoreRing score={d.research_score ?? 0} label="Research Score" />
            <GradeBadge grade={d.grade ?? "N/A"} />
            <TrendBadge trend={d.trend ?? "STABLE"} />
          </CardContent>
        </Card>
        <Card className="bg-slate-800/50 border-slate-700 md:col-span-3">
          <CardHeader className="pb-2">
            <CardTitle className="text-xs text-teal-400 uppercase tracking-wide flex items-center gap-2">
              <Lightbulb className="h-4 w-4" /> Executive Summary
            </CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-sm text-slate-300 leading-relaxed">{d.executive_summary}</p>
            {d.top_strategy && (
              <div className="mt-3 flex items-center gap-2">
                <Star className="h-3.5 w-3.5 text-teal-400" />
                <span className="text-xs text-teal-300">Top strategy: {d.top_strategy.label}</span>
                <GradeBadge grade={d.top_strategy.grade} />
              </div>
            )}
          </CardContent>
        </Card>
      </div>

      {/* KPI grid */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        {kpis.map(k => (
          <Card key={k.label} className="bg-slate-800/60 border-slate-700">
            <CardContent className="pt-3 pb-3 text-center">
              <p className="text-lg font-bold text-white">{k.value}</p>
              <p className="text-xs text-slate-400 mt-0.5">{k.label}</p>
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  );
}

// ── Strategy comparison tab ───────────────────────────────────────────────────

function StrategyTab({ data: raw }: { data: any }) {
  const d = raw?.data ?? raw;
  const strategies = d?.strategies ?? [];

  if (!strategies.length) return (
    <Card className="bg-slate-800/50 border-slate-700">
      <CardContent className="pt-6 text-center text-slate-400 py-12 text-sm">
        No strategy data. Run a scan first.
      </CardContent>
    </Card>
  );

  const metrics = [
    { key: "performance_score", label: "Performance", colour: "bg-teal-500" },
    { key: "win_rate",          label: "Win Rate",    colour: "bg-blue-500", scale: 100 },
    { key: "consistency",       label: "Consistency", colour: "bg-violet-500" },
    { key: "risk_score",        label: "Risk Score",  colour: "bg-orange-500" },
  ];

  return (
    <div className="space-y-3">
      {strategies.map((s: any, i: number) => (
        <Card key={s.strategy_type} className="bg-slate-800/50 border-slate-700">
          <CardContent className="pt-4 pb-4">
            <div className="flex items-start justify-between mb-3">
              <div className="flex items-center gap-2">
                {i === 0 && <Star className="h-4 w-4 text-amber-400" />}
                <div>
                  <p className="text-sm font-semibold text-white">{s.label}</p>
                  <p className="text-xs text-slate-400">{s.description}</p>
                </div>
              </div>
              <div className="flex items-center gap-2">
                <GradeBadge grade={s.grade} />
                <span className="text-xs text-slate-400">{s.signal_count} signals</span>
              </div>
            </div>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
              {metrics.map(m => {
                const raw_val = s[m.key] ?? 0;
                const pct = m.scale ? raw_val * m.scale : raw_val;
                return (
                  <div key={m.key}>
                    <div className="flex justify-between text-xs text-slate-400 mb-1">
                      <span>{m.label}</span><span>{Math.round(pct)}</span>
                    </div>
                    <div className="h-1.5 bg-slate-700 rounded-full overflow-hidden">
                      <div className={`h-full ${m.colour} rounded-full`} style={{ width: `${Math.min(100, pct)}%` }} />
                    </div>
                  </div>
                );
              })}
            </div>
            <p className="text-xs text-slate-400 mt-2 italic">{s.recommendation}</p>
            <div className="flex gap-4 mt-1 text-xs text-slate-500">
              <span>Best: <span className="text-emerald-400">{s.best_regime}</span></span>
              <span>Worst: <span className="text-red-400">{s.worst_regime}</span></span>
              <span>Drawdown: ~{s.avg_drawdown?.toFixed(1)}%</span>
            </div>
          </CardContent>
        </Card>
      ))}
    </div>
  );
}

// ── Scenario simulator tab ────────────────────────────────────────────────────

function ScenarioTab({ data: raw }: { data: any }) {
  const d = raw?.data ?? raw;
  const scenarios = d?.scenarios ?? [];
  const impactColour: Record<string, string> = {
    POSITIVE: "border-emerald-700/40",
    NEGATIVE: "border-red-700/40",
    NEUTRAL:  "border-slate-700",
  };
  const riskColour: Record<string, string> = {
    LOW: "text-emerald-400", MEDIUM: "text-yellow-400",
    HIGH: "text-red-400", VERY_HIGH: "text-red-500",
  };

  return (
    <div className="grid md:grid-cols-2 gap-4">
      {scenarios.map((s: any) => (
        <Card key={s.scenario_type} className={`bg-slate-800/50 border ${impactColour[s.market_impact] ?? "border-slate-700"}`}>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm text-white flex items-center justify-between">
              {s.label}
              <span className={`text-xs font-semibold ${riskColour[s.risk_level] ?? "text-slate-400"}`}>
                {s.risk_level} RISK
              </span>
            </CardTitle>
            <p className="text-xs text-slate-400">{s.description}</p>
          </CardHeader>
          <CardContent className="space-y-2">
            <div className="flex gap-4 text-xs">
              <div>
                <span className="text-slate-500">Opportunity </span>
                <span className="text-emerald-400 font-semibold">{s.opportunity_score}/100</span>
              </div>
              <div>
                <span className="text-slate-500">Threat </span>
                <span className="text-red-400 font-semibold">{s.threat_score}/100</span>
              </div>
              <div>
                <span className="text-slate-500">Est. Signals </span>
                <span className="text-white font-semibold">{s.expected_signals}</span>
              </div>
            </div>
            <p className="text-xs text-slate-400 italic">{s.signal_shift}</p>
            <div className="text-xs text-slate-400">
              <span className="text-slate-500">Actions: </span>
              {s.recommended_actions?.slice(0, 2).join(" · ")}
            </div>
          </CardContent>
        </Card>
      ))}
    </div>
  );
}

// ── Historical replay tab ─────────────────────────────────────────────────────

function ReplayTab({ data: raw }: { data: any }) {
  const d   = raw?.data ?? raw;
  const frames  = d?.frames  ?? [];
  const summary = d?.summary ?? {};
  const outcomeColour: Record<string, string> = {
    WIN: "text-emerald-400", LOSS: "text-red-400", UNKNOWN: "text-slate-500",
  };

  return (
    <div className="space-y-4">
      {/* Summary */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        {[
          { label: "Total Frames",   value: summary.total_frames ?? 0 },
          { label: "Win Rate",       value: `${((summary.win_rate ?? 0)*100).toFixed(0)}%` },
          { label: "Avg Confidence", value: `${((summary.avg_confidence ?? 0)*100).toFixed(0)}%` },
          { label: "Symbols",        value: summary.symbols_covered ?? 0 },
        ].map(k => (
          <Card key={k.label} className="bg-slate-800/60 border-slate-700">
            <CardContent className="pt-3 pb-3 text-center">
              <p className="text-lg font-bold text-white">{k.value}</p>
              <p className="text-xs text-slate-400">{k.label}</p>
            </CardContent>
          </Card>
        ))}
      </div>

      {frames.length === 0 ? (
        <Card className="bg-slate-800/50 border-slate-700">
          <CardContent className="py-10 text-center text-slate-400 text-sm">
            No historical frames available. Signal history builds up after multiple scans.
          </CardContent>
        </Card>
      ) : (
        <Card className="bg-slate-800/50 border-slate-700">
          <CardContent className="pt-4">
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead>
                  <tr className="border-b border-slate-700 text-slate-400">
                    <th className="text-left py-2 pr-3">Symbol</th>
                    <th className="text-left py-2 pr-3">Signal</th>
                    <th className="text-left py-2 pr-3">Confidence</th>
                    <th className="text-left py-2 pr-3">Regime</th>
                    <th className="text-left py-2 pr-3">Outcome</th>
                    <th className="text-left py-2">Timestamp</th>
                  </tr>
                </thead>
                <tbody>
                  {frames.slice(0, 30).map((f: any) => (
                    <tr key={f.frame_id} className="border-b border-slate-800 hover:bg-slate-700/20">
                      <td className="py-1.5 pr-3 font-medium text-white">{f.symbol}</td>
                      <td className="py-1.5 pr-3">
                        <span className={f.signal_type?.includes("BUY") ? "text-emerald-400" :
                          f.signal_type?.includes("SELL") ? "text-red-400" : "text-slate-400"}>
                          {f.signal_type}
                        </span>
                      </td>
                      <td className="py-1.5 pr-3 text-slate-300">{((f.confidence ?? 0)*100).toFixed(0)}%</td>
                      <td className="py-1.5 pr-3 text-slate-400">{f.regime}</td>
                      <td className={`py-1.5 pr-3 font-semibold ${outcomeColour[f.outcome] ?? "text-slate-400"}`}>{f.outcome}</td>
                      <td className="py-1.5 text-slate-500 text-xs">{f.timestamp?.slice(0, 16)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}

// ── Parameter experiments tab ─────────────────────────────────────────────────

function ParamsTab({ data: raw }: { data: any }) {
  const d   = raw?.data ?? raw;
  const params = d?.experiments ?? [];

  const grouped: Record<string, any[]> = {};
  for (const p of params) {
    if (!grouped[p.parameter_name]) grouped[p.parameter_name] = [];
    grouped[p.parameter_name].push(p);
  }

  return (
    <div className="space-y-4">
      {Object.entries(grouped).map(([param, variants]) => (
        <Card key={param} className="bg-slate-800/50 border-slate-700">
          <CardHeader className="pb-2">
            <CardTitle className="text-xs text-teal-400 uppercase tracking-wide">
              {param.replace(/_/g, " ")}
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-2">
              {(variants as any[]).map((v: any) => (
                <div key={v.experiment_id} className="flex items-center justify-between py-1.5 border-b border-slate-800 last:border-0">
                  <div className="flex items-center gap-3">
                    <span className="text-xs text-slate-500">baseline {v.baseline_value}</span>
                    <ChevronRight className="h-3 w-3 text-slate-600" />
                    <span className="text-xs text-white font-medium">{v.test_value}</span>
                    <ImpactBadge label={v.impact_label} />
                  </div>
                  <div className="flex gap-4 text-xs text-slate-400">
                    <span>Signals {v.signal_count_delta > 0 ? "+" : ""}{v.signal_count_delta}</span>
                    <span>Conf {v.confidence_delta > 0 ? "+" : ""}{v.confidence_delta?.toFixed(1)}%</span>
                    <span>WR {v.win_rate_delta > 0 ? "+" : ""}{(v.win_rate_delta*100)?.toFixed(1)}pp</span>
                  </div>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      ))}
    </div>
  );
}

// ── Risk simulation tab ───────────────────────────────────────────────────────

function RiskSimTab({ data: raw }: { data: any }) {
  const d    = raw?.data ?? raw;
  const sim  = d?.benchmark?.risk_simulation ?? null;
  // risk_simulation is returned in summary
  const sum  = raw?._summary;

  const expectedDD  = sim?.expected_drawdown       ?? 8;
  const maxDD       = sim?.max_drawdown_estimate    ?? 15;
  const capUsage    = sim?.capital_usage_pct        ?? 60;
  const volExposure = sim?.volatility_exposure      ?? 80;
  const stress      = sim?.stress_scenarios         ?? [];
  const mcNote      = sim?.monte_carlo_note ?? "Full Monte Carlo is a future capability.";

  return (
    <div className="space-y-4">
      <div className="grid md:grid-cols-2 gap-4">
        {/* Core estimates */}
        <Card className="bg-slate-800/50 border-slate-700">
          <CardHeader className="pb-2">
            <CardTitle className="text-xs text-teal-400 uppercase tracking-wide">Core Risk Estimates</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            {[
              { label: "Expected Drawdown",    value: `${expectedDD?.toFixed(1)}%`,  bar: Math.min(100, expectedDD * 4), colour: "bg-yellow-500" },
              { label: "Max Drawdown Estimate",value: `${maxDD?.toFixed(1)}%`,        bar: Math.min(100, maxDD * 3),      colour: "bg-red-500" },
              { label: "Capital Usage",         value: `${capUsage?.toFixed(0)}%`,   bar: capUsage,                       colour: "bg-blue-500" },
              { label: "Volatility Exposure",   value: `${volExposure?.toFixed(0)}/100`, bar: volExposure,                colour: "bg-orange-500" },
            ].map(row => (
              <div key={row.label}>
                <div className="flex justify-between text-xs mb-1">
                  <span className="text-slate-400">{row.label}</span>
                  <span className="text-white font-semibold">{row.value}</span>
                </div>
                <div className="h-1.5 bg-slate-700 rounded-full">
                  <div className={`h-full ${row.colour} rounded-full`} style={{ width: `${row.bar}%` }} />
                </div>
              </div>
            ))}
          </CardContent>
        </Card>

        {/* Stress scenarios */}
        <Card className="bg-slate-800/50 border-slate-700">
          <CardHeader className="pb-2">
            <CardTitle className="text-xs text-red-400 uppercase tracking-wide">Stress Scenarios</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-2">
              {stress.slice(0, 5).map((s: any) => (
                <div key={s.name} className="flex items-center justify-between text-xs py-1 border-b border-slate-800 last:border-0">
                  <span className="text-slate-300">{s.name}</span>
                  <div className="flex gap-3">
                    <span className="text-slate-500">{(s.probability * 100).toFixed(0)}% prob</span>
                    <span className="text-red-400 font-medium">-{s.drawdown_est_pct?.toFixed(1)}%</span>
                  </div>
                </div>
              ))}
            </div>
            <p className="text-xs text-slate-500 mt-3 italic">{mcNote}</p>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

// ── Performance benchmark tab ─────────────────────────────────────────────────

function BenchmarkTab({ data: raw }: { data: any }) {
  const d   = raw?.data ?? raw;
  const bm  = d?.benchmark;
  const reg = d?.regimes ?? [];

  if (!bm) return (
    <Card className="bg-slate-800/50 border-slate-700">
      <CardContent className="py-10 text-center text-slate-400 text-sm">
        No benchmark data available.
      </CardContent>
    </Card>
  );

  const scores = [
    { label: "Research",        value: bm.research_score,  colour: "bg-teal-500" },
    { label: "NIFTY Baseline",  value: bm.baseline_score,  colour: "bg-blue-500" },
    { label: "Market",          value: bm.market_score,    colour: "bg-violet-500" },
    { label: "Paper Trading",   value: bm.paper_score,     colour: "bg-amber-500" },
  ];

  return (
    <div className="space-y-4">
      {/* Score bars */}
      <Card className="bg-slate-800/50 border-slate-700">
        <CardHeader className="pb-2">
          <CardTitle className="text-xs text-teal-400 uppercase tracking-wide">Performance Comparison</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          {scores.map(s => (
            <div key={s.label}>
              <div className="flex justify-between text-xs mb-1">
                <span className="text-slate-300">{s.label}
                  {bm.winner === s.label && <span className="ml-1 text-amber-400">★ Leader</span>}
                </span>
                <span className="text-white font-semibold">{s.value?.toFixed(1)}</span>
              </div>
              <div className="h-2 bg-slate-700 rounded-full">
                <div className={`h-full ${s.colour} rounded-full`} style={{ width: `${Math.min(100, s.value ?? 0)}%` }} />
              </div>
            </div>
          ))}
          <div className="flex gap-4 text-xs mt-2">
            <span className="text-slate-400">Alpha: <span className={`font-semibold ${bm.relative_alpha >= 0 ? "text-emerald-400" : "text-red-400"}`}>{bm.relative_alpha > 0 ? "+" : ""}{bm.relative_alpha?.toFixed(1)}</span></span>
            <span className="text-slate-400">Risk-Adj: <span className="text-white font-semibold">{bm.risk_adj_return?.toFixed(0)}/100</span></span>
            <span className="text-slate-400">Consistency: <span className="text-white font-semibold">{bm.consistency?.toFixed(0)}/100</span></span>
          </div>
          <p className="text-xs text-slate-400 mt-2 italic">{bm.narrative}</p>
        </CardContent>
      </Card>

      {/* Regime profiles */}
      {reg.length > 0 && (
        <Card className="bg-slate-800/50 border-slate-700">
          <CardHeader className="pb-2">
            <CardTitle className="text-xs text-teal-400 uppercase tracking-wide">Performance by Regime</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead>
                  <tr className="border-b border-slate-700 text-slate-400">
                    <th className="text-left py-2 pr-3">Regime</th>
                    <th className="text-left py-2 pr-3">Signals</th>
                    <th className="text-left py-2 pr-3">Win Rate</th>
                    <th className="text-left py-2 pr-3">Avg Confidence</th>
                    <th className="text-left py-2 pr-3">Drawdown</th>
                    <th className="text-left py-2 pr-3">Best Strategy</th>
                    <th className="text-left py-2">VIX Range</th>
                  </tr>
                </thead>
                <tbody>
                  {reg.map((r: any) => (
                    <tr key={r.regime} className="border-b border-slate-800">
                      <td className="py-1.5 pr-3 font-medium text-white">{r.regime}</td>
                      <td className="py-1.5 pr-3 text-slate-300">{r.signal_count}</td>
                      <td className="py-1.5 pr-3 text-slate-300">{((r.win_rate ?? 0)*100).toFixed(0)}%</td>
                      <td className="py-1.5 pr-3 text-slate-300">{r.avg_confidence?.toFixed(0)}</td>
                      <td className="py-1.5 pr-3 text-red-400">~{r.avg_drawdown?.toFixed(1)}%</td>
                      <td className="py-1.5 pr-3 text-teal-400">{r.best_strategy?.replace(/_/g, " ")}</td>
                      <td className="py-1.5 text-slate-400">{r.vix_range}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}

// ── Innovation workspace tab ──────────────────────────────────────────────────

const STATUS_COLOUR: Record<string, string> = {
  COMPLETE:  "bg-emerald-500/20 text-emerald-300",
  RUNNING:   "bg-blue-500/20 text-blue-300",
  DRAFT:     "bg-slate-500/20 text-slate-400",
  ARCHIVED:  "bg-slate-700/20 text-slate-500",
};

function WorkspaceTab({ data: raw }: { data: any }) {
  const d    = raw?.data ?? raw;
  const exps = d?.innovations ?? [];

  return (
    <div className="space-y-3">
      {exps.map((e: any) => (
        <Card key={e.experiment_id} className="bg-slate-800/50 border-slate-700">
          <CardContent className="pt-4 pb-4">
            <div className="flex items-start justify-between mb-2">
              <div>
                <p className="text-sm font-semibold text-white">{e.title}</p>
                <p className="text-xs text-slate-400 mt-0.5">{e.objective}</p>
              </div>
              <div className="flex items-center gap-2">
                <span className={`text-xs px-2 py-0.5 rounded ${STATUS_COLOUR[e.status] ?? STATUS_COLOUR.DRAFT}`}>{e.status}</span>
                <span className="text-xs text-slate-500">v{e.version}</span>
              </div>
            </div>
            <div className="flex flex-wrap gap-1 mb-2">
              {(e.tags ?? []).map((t: string) => (
                <span key={t} className="text-xs px-1.5 py-0.5 bg-teal-900/30 text-teal-400 rounded">{t}</span>
              ))}
            </div>
            <p className="text-xs text-slate-400"><span className="text-slate-500">Hypothesis: </span>{e.hypothesis}</p>
            <p className="text-xs text-slate-300 mt-1"><span className="text-slate-500">Result: </span>{e.result_summary}</p>
          </CardContent>
        </Card>
      ))}
    </div>
  );
}

// ── Research reports tab ──────────────────────────────────────────────────────

function ReportsTab({ data: raw }: { data: any }) {
  const d      = raw?.data ?? raw;
  const report = d?.report;

  if (!report) return (
    <Card className="bg-slate-800/50 border-slate-700">
      <CardContent className="py-10 text-center text-slate-400 text-sm">
        No report generated. Enable RESEARCH_LAB_ENABLED and run a scan.
      </CardContent>
    </Card>
  );

  return (
    <div className="space-y-4">
      {/* Header */}
      <Card className="bg-teal-900/20 border-teal-700/40">
        <CardContent className="pt-4 pb-4">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm font-semibold text-teal-300">Research Report #{report.report_id}</p>
              <p className="text-xs text-slate-400 mt-0.5">{report.executive_summary}</p>
            </div>
            <div className="flex items-center gap-2">
              <ScoreRing score={report.research_score} label="" />
              <GradeBadge grade={report.grade} />
            </div>
          </div>
        </CardContent>
      </Card>

      <div className="grid md:grid-cols-2 gap-4">
        {/* Key findings */}
        <Card className="bg-slate-800/50 border-slate-700">
          <CardHeader className="pb-2">
            <CardTitle className="text-xs text-teal-400 uppercase tracking-wide">Key Findings</CardTitle>
          </CardHeader>
          <CardContent>
            <ol className="space-y-2">
              {(report.key_findings ?? []).map((f: string, i: number) => (
                <li key={i} className="flex items-start gap-2 text-xs text-slate-300">
                  <span className="text-teal-400 font-bold w-4">{i + 1}.</span>
                  {f}
                </li>
              ))}
            </ol>
          </CardContent>
        </Card>

        {/* Recommendations */}
        <Card className="bg-slate-800/50 border-emerald-900/30 border">
          <CardHeader className="pb-2">
            <CardTitle className="text-xs text-emerald-400 uppercase tracking-wide">Recommendations</CardTitle>
          </CardHeader>
          <CardContent>
            <ul className="space-y-2">
              {(report.recommendations ?? []).map((r: string, i: number) => (
                <li key={i} className="flex items-start gap-2 text-xs text-emerald-300">
                  <CheckCircle className="h-3 w-3 text-emerald-400 mt-0.5 flex-shrink-0" />
                  {r}
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>

        {/* Risk analysis */}
        <Card className="bg-slate-800/50 border-red-900/30 border">
          <CardHeader className="pb-2">
            <CardTitle className="text-xs text-red-400 uppercase tracking-wide">Risk Analysis</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-xs text-slate-300 leading-relaxed">{report.risk_analysis}</p>
          </CardContent>
        </Card>

        {/* Limitations */}
        <Card className="bg-slate-800/50 border-yellow-900/30 border">
          <CardHeader className="pb-2">
            <CardTitle className="text-xs text-yellow-400 uppercase tracking-wide">Known Limitations</CardTitle>
          </CardHeader>
          <CardContent>
            <ul className="space-y-1">
              {(report.limitations ?? []).map((l: string, i: number) => (
                <li key={i} className="flex items-start gap-2 text-xs text-slate-400">
                  <AlertTriangle className="h-3 w-3 text-yellow-500 mt-0.5 flex-shrink-0" />
                  {l}
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>
      </div>

      {/* Methodology */}
      <Card className="bg-slate-800/50 border-slate-700">
        <CardHeader className="pb-2">
          <CardTitle className="text-xs text-slate-400 uppercase tracking-wide">Methodology</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-xs text-slate-400 leading-relaxed">{report.methodology}</p>
        </CardContent>
      </Card>
    </div>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function ResearchLab() {
  const [tab, setTab] = useState("overview");

  const summaryQ    = useRL("summary");
  const strategiesQ = useRL("strategies");
  const simulQ      = useRL("simulations");
  const replayQ     = useRL("replay");
  const benchmarkQ  = useRL("benchmark");
  const reportsQ    = useRL("reports");

  const tabs = [
    ["overview",   "Overview",       BarChart2,     summaryQ],
    ["strategies", "Strategies",     TrendingUp,    strategiesQ],
    ["scenarios",  "Scenarios",      Layers,        simulQ],
    ["replay",     "Replay",         Clock,         replayQ],
    ["params",     "Parameters",     Beaker,        benchmarkQ],
    ["risk",       "Risk Sim",       AlertTriangle, benchmarkQ],
    ["benchmark",  "Benchmark",      Activity,      benchmarkQ],
    ["workspace",  "Workspace",      BookOpen,      reportsQ],
    ["reports",    "Reports",        FileText,      reportsQ],
  ] as const;

  return (
    <div className="p-4 md:p-6 space-y-6 max-w-7xl mx-auto">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <FlaskConical className="h-7 w-7 text-teal-400" />
          <div>
            <h1 className="text-xl font-bold text-white">Research Lab</h1>
            <p className="text-xs text-slate-400">Phase 7.5 · Read-only · Advisory-only</p>
          </div>
        </div>
        <Badge className="bg-teal-900/30 text-teal-400 border border-teal-700/40">
          Research &amp; Simulation
        </Badge>
      </div>

      <Tabs value={tab} onValueChange={setTab}>
        <TabsList className="flex flex-wrap gap-1 h-auto bg-slate-800/50 p-1 rounded-lg">
          {tabs.map(([value, label, Icon]) => (
            <TabsTrigger
              key={value}
              value={value}
              className="flex items-center gap-1.5 px-3 py-1.5 text-xs data-[state=active]:bg-teal-900/40 data-[state=active]:text-teal-300"
            >
              <Icon className="h-3.5 w-3.5" />
              {label}
            </TabsTrigger>
          ))}
        </TabsList>

        <TabsContent value="overview"   className="mt-4">{summaryQ.isLoading    ? <Loading /> : <OverviewTab   data={summaryQ.data} />}</TabsContent>
        <TabsContent value="strategies" className="mt-4">{strategiesQ.isLoading ? <Loading /> : <StrategyTab   data={strategiesQ.data} />}</TabsContent>
        <TabsContent value="scenarios"  className="mt-4">{simulQ.isLoading      ? <Loading /> : <ScenarioTab   data={simulQ.data} />}</TabsContent>
        <TabsContent value="replay"     className="mt-4">{replayQ.isLoading     ? <Loading /> : <ReplayTab     data={replayQ.data} />}</TabsContent>
        <TabsContent value="params"     className="mt-4">{benchmarkQ.isLoading  ? <Loading /> : <ParamsTab     data={benchmarkQ.data} />}</TabsContent>
        <TabsContent value="risk"       className="mt-4">{benchmarkQ.isLoading  ? <Loading /> : <RiskSimTab    data={benchmarkQ.data} />}</TabsContent>
        <TabsContent value="benchmark"  className="mt-4">{benchmarkQ.isLoading  ? <Loading /> : <BenchmarkTab  data={benchmarkQ.data} />}</TabsContent>
        <TabsContent value="workspace"  className="mt-4">{reportsQ.isLoading    ? <Loading /> : <WorkspaceTab  data={reportsQ.data} />}</TabsContent>
        <TabsContent value="reports"    className="mt-4">{reportsQ.isLoading    ? <Loading /> : <ReportsTab    data={reportsQ.data} />}</TabsContent>
      </Tabs>
    </div>
  );
}
