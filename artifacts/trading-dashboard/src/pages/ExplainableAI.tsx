/**
 * Phase 7.4 – Explainable AI & Decision Intelligence Hub
 *
 * 11-tab dashboard:
 *  Overview | Summary | Decision | Contributions | Confidence
 *  Scenarios | History | Market Context | Event Context | Macro Context | Risk
 *
 * Symbol selector drives all 6 symbol-specific queries simultaneously.
 */
import React, { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { apiJson } from "@/lib/api";
import {
  Card, CardContent, CardHeader, CardTitle, CardDescription,
} from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Progress } from "@/components/ui/progress";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import {
  AlertTriangle, CheckCircle, TrendingUp, TrendingDown, Minus,
  Lightbulb, BarChart3, Shield, Globe2, Globe, CalendarDays, Brain,
  RefreshCw,
} from "lucide-react";

// ── helpers ──────────────────────────────────────────────────────────────────

const GRADE_COLOR: Record<string, string> = {
  A: "text-emerald-400", B: "text-green-400", C: "text-yellow-400",
  D: "text-orange-400",  F: "text-red-400",   "N/A": "text-slate-400",
};

function GradeBadge({ grade }: { grade: string }) {
  const color = GRADE_COLOR[grade] ?? "text-slate-400";
  return <span className={`font-bold text-lg ${color}`}>{grade}</span>;
}

function SignalBadge({ signal }: { signal: string }) {
  const map: Record<string, string> = {
    BUY:  "bg-emerald-500/20 text-emerald-300 border-emerald-500/40",
    SELL: "bg-red-500/20 text-red-300 border-red-500/40",
    HOLD: "bg-slate-500/20 text-slate-300 border-slate-500/40",
  };
  return (
    <Badge className={`border ${map[signal] ?? map.HOLD} text-xs font-semibold`}>
      {signal}
    </Badge>
  );
}

function Conf({ value }: { value: number }) {
  const pct = Math.round(value * 100);
  const color = pct >= 70 ? "bg-emerald-500" : pct >= 45 ? "bg-yellow-500" : "bg-red-500";
  return (
    <div className="flex items-center gap-2">
      <div className="relative h-2 flex-1 bg-slate-700 rounded-full overflow-hidden">
        <div className={`absolute inset-y-0 left-0 rounded-full ${color}`} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-xs text-slate-300 w-8">{pct}%</span>
    </div>
  );
}

function DisabledCard() {
  return (
    <Card className="bg-slate-800/50 border-slate-700">
      <CardContent className="pt-6 text-center text-slate-400 py-16">
        <AlertTriangle className="mx-auto mb-3 h-8 w-8 text-yellow-400" />
        <p className="text-sm">Explainable AI is disabled.</p>
        <p className="text-xs mt-1">Set <code>EXPLAINABLE_AI_ENABLED=true</code> to enable.</p>
      </CardContent>
    </Card>
  );
}

// ── symbol selector ───────────────────────────────────────────────────────────

const SYMBOLS = [
  "RELIANCE", "TCS", "INFY", "HDFCBANK", "ICICIBANK",
  "SBIN", "BAJFINANCE", "WIPRO", "AXISBANK", "KOTAKBANK",
];

// ── queries ───────────────────────────────────────────────────────────────────

function useSummary() {
  return useQuery({
    queryKey: ["explainable-ai-summary"],
    queryFn: () => apiJson("/explainable-ai/summary"),
    refetchInterval: 60_000,
  });
}

function useDecision(symbol: string) {
  return useQuery({
    queryKey: ["explainable-ai-decision", symbol],
    queryFn: () => apiJson(`/explainable-ai/decision?symbol=${symbol}`),
    enabled: !!symbol,
    refetchInterval: 60_000,
  });
}

function useContributions(symbol: string) {
  return useQuery({
    queryKey: ["explainable-ai-contributions", symbol],
    queryFn: () => apiJson(`/explainable-ai/contributions?symbol=${symbol}`),
    enabled: !!symbol,
    refetchInterval: 60_000,
  });
}

function useConfidence(symbol: string) {
  return useQuery({
    queryKey: ["explainable-ai-confidence", symbol],
    queryFn: () => apiJson(`/explainable-ai/confidence?symbol=${symbol}`),
    enabled: !!symbol,
    refetchInterval: 60_000,
  });
}

function useScenarios(symbol: string) {
  return useQuery({
    queryKey: ["explainable-ai-scenarios", symbol],
    queryFn: () => apiJson(`/explainable-ai/scenarios?symbol=${symbol}`),
    enabled: !!symbol,
    refetchInterval: 60_000,
  });
}

function useHistory(symbol: string) {
  return useQuery({
    queryKey: ["explainable-ai-history", symbol],
    queryFn: () => apiJson(`/explainable-ai/history?symbol=${symbol}`),
    enabled: !!symbol,
    refetchInterval: 60_000,
  });
}

// ── sub-components ────────────────────────────────────────────────────────────

function OverviewTab({ summary }: { summary: any }) {
  const data = summary?.data ?? summary;
  if (data?.status === "DISABLED") return <DisabledCard />;
  const decisions: any[] = data?.decisions ?? [];

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        {[
          { label: "Total Decisions",  value: data?.total_decisions ?? "—", icon: Brain     },
          { label: "Buy Signals",      value: data?.buy_count  ?? "—",     icon: TrendingUp },
          { label: "Sell Signals",     value: data?.sell_count ?? "—",     icon: TrendingDown },
          { label: "Avg Confidence",   value: data?.avg_confidence != null
            ? `${Math.round(data.avg_confidence * 100)}%` : "—",           icon: BarChart3  },
        ].map(({ label, value, icon: Icon }) => (
          <Card key={label} className="bg-slate-800/60 border-slate-700">
            <CardContent className="pt-4 pb-3">
              <div className="flex items-center gap-2 mb-1">
                <Icon className="h-4 w-4 text-teal-400" />
                <span className="text-xs text-slate-400">{label}</span>
              </div>
              <p className="text-2xl font-bold text-white">{value}</p>
            </CardContent>
          </Card>
        ))}
      </div>

      {decisions.length === 0 ? (
        <Card className="bg-slate-800/50 border-slate-700">
          <CardContent className="pt-6 text-center text-slate-400 py-12 text-sm">
            No explainable decisions available yet. Run a scan to generate signals.
          </CardContent>
        </Card>
      ) : (
        <Card className="bg-slate-800/60 border-slate-700">
          <CardHeader className="pb-2">
            <CardTitle className="text-sm text-slate-300">All Decisions</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead>
                  <tr className="border-b border-slate-700 text-slate-400">
                    <th className="text-left py-2 pr-4">Symbol</th>
                    <th className="text-left py-2 pr-4">Signal</th>
                    <th className="text-left py-2 pr-4">Grade</th>
                    <th className="text-left py-2 pr-4">Confidence</th>
                    <th className="text-left py-2 pr-4">Risk</th>
                    <th className="text-left py-2">Top Reason</th>
                  </tr>
                </thead>
                <tbody>
                  {decisions.map((d: any) => (
                    <tr key={d.symbol} className="border-b border-slate-800 hover:bg-slate-700/30">
                      <td className="py-2 pr-4 font-medium text-white">{d.symbol}</td>
                      <td className="py-2 pr-4"><SignalBadge signal={d.signal_type ?? "HOLD"} /></td>
                      <td className="py-2 pr-4"><GradeBadge grade={d.grade ?? "N/A"} /></td>
                      <td className="py-2 pr-4 w-32"><Conf value={d.confidence ?? 0} /></td>
                      <td className="py-2 pr-4 text-slate-300">{d.risk_level ?? "—"}</td>
                      <td className="py-2 text-slate-400 max-w-xs truncate">
                        {(d.primary_reasons ?? [])[0] ?? "—"}
                      </td>
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

function SummaryTab({ data: raw, symbol }: { data: any; symbol: string }) {
  const data = raw?.data ?? raw;
  const s    = data?.summary;
  const d    = data?.decision;
  if (!s) return (
    <Card className="bg-slate-800/50 border-slate-700">
      <CardContent className="pt-6 text-center text-slate-400 py-12 text-sm">
        No summary available for <strong>{symbol}</strong>. Run a scan first.
      </CardContent>
    </Card>
  );

  return (
    <div className="space-y-4">
      {/* Why card */}
      <Card className="bg-teal-900/20 border-teal-700/40">
        <CardContent className="pt-4 pb-4">
          <div className="flex items-start gap-3">
            <Lightbulb className="h-5 w-5 text-teal-400 mt-0.5 flex-shrink-0" />
            <div>
              <p className="text-xs font-semibold text-teal-400 mb-1 uppercase tracking-wide">Why this signal</p>
              <p className="text-sm text-teal-100 leading-relaxed">{s.why}</p>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Signal badges */}
      {d && (
        <div className="flex flex-wrap gap-3">
          <div className="flex items-center gap-2 px-3 py-1.5 bg-slate-800/60 rounded-lg border border-slate-700">
            <span className="text-xs text-slate-400">Signal</span>
            <SignalBadge signal={d.signal_type ?? "HOLD"} />
          </div>
          <div className="flex items-center gap-2 px-3 py-1.5 bg-slate-800/60 rounded-lg border border-slate-700">
            <span className="text-xs text-slate-400">Grade</span>
            <GradeBadge grade={d.grade ?? "N/A"} />
          </div>
          <div className="flex items-center gap-2 px-3 py-1.5 bg-slate-800/60 rounded-lg border border-slate-700">
            <span className="text-xs text-slate-400">Confidence</span>
            <span className="text-sm font-semibold text-white">
              {Math.round((d.confidence ?? 0) * 100)}%
            </span>
          </div>
          <div className="flex items-center gap-2 px-3 py-1.5 bg-slate-800/60 rounded-lg border border-slate-700">
            <span className="text-xs text-slate-400">Risk</span>
            <span className="text-sm font-semibold text-white">{d.risk_level ?? "—"}</span>
          </div>
        </div>
      )}

      <div className="grid md:grid-cols-3 gap-4">
        {/* Top factors */}
        <Card className="bg-slate-800/60 border-slate-700">
          <CardHeader className="pb-2">
            <CardTitle className="text-xs text-teal-400 uppercase tracking-wide">Top Factors</CardTitle>
          </CardHeader>
          <CardContent>
            {(s.top_factors ?? []).length === 0 ? (
              <p className="text-xs text-slate-500">No factors available.</p>
            ) : (
              <ol className="space-y-2">
                {(s.top_factors ?? []).map((f: string, i: number) => (
                  <li key={i} className="flex items-start gap-2 text-xs text-slate-300">
                    <span className="text-teal-400 font-bold w-4">{i + 1}.</span>
                    <span>{f}</span>
                  </li>
                ))}
              </ol>
            )}
          </CardContent>
        </Card>

        {/* Risks */}
        <Card className="bg-slate-800/60 border-red-900/30 border">
          <CardHeader className="pb-2">
            <CardTitle className="text-xs text-red-400 uppercase tracking-wide">Key Risks</CardTitle>
          </CardHeader>
          <CardContent>
            <ul className="space-y-2">
              {(s.risks ?? []).map((r: string, i: number) => (
                <li key={i} className="flex items-start gap-2 text-xs text-red-300">
                  <AlertTriangle className="h-3 w-3 text-red-400 mt-0.5 flex-shrink-0" />
                  {r}
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>

        {/* Opportunities */}
        <Card className="bg-slate-800/60 border-emerald-900/30 border">
          <CardHeader className="pb-2">
            <CardTitle className="text-xs text-emerald-400 uppercase tracking-wide">Opportunities</CardTitle>
          </CardHeader>
          <CardContent>
            <ul className="space-y-2">
              {(s.opportunities ?? []).map((o: string, i: number) => (
                <li key={i} className="flex items-start gap-2 text-xs text-emerald-300">
                  <TrendingUp className="h-3 w-3 text-emerald-400 mt-0.5 flex-shrink-0" />
                  {o}
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>
      </div>

      {/* Action items */}
      <Card className="bg-slate-800/60 border-teal-700/30 border">
        <CardHeader className="pb-2">
          <CardTitle className="text-xs text-teal-400 uppercase tracking-wide">Action Items</CardTitle>
        </CardHeader>
        <CardContent>
          <ol className="space-y-2">
            {(s.action_items ?? []).map((a: string, i: number) => (
              <li key={i} className="flex items-start gap-2 text-xs text-slate-300">
                <CheckCircle className="h-3 w-3 text-teal-400 mt-0.5 flex-shrink-0" />
                {a}
              </li>
            ))}
          </ol>
        </CardContent>
      </Card>
    </div>
  );
}

function DecisionTab({ data: raw, symbol }: { data: any; symbol: string }) {
  const data = raw?.data ?? raw;
  const d    = data?.decision;
  const s    = data?.summary;
  if (!d) return (
    <Card className="bg-slate-800/50 border-slate-700">
      <CardContent className="pt-6 text-center text-slate-400 py-12 text-sm">
        No signal found for <strong>{symbol}</strong>. Run a scan first.
      </CardContent>
    </Card>
  );

  return (
    <div className="space-y-4">
      {/* Why card */}
      {s?.why && (
        <Card className="bg-teal-900/20 border-teal-700/40">
          <CardContent className="pt-4 pb-3">
            <div className="flex items-start gap-2">
              <Lightbulb className="h-4 w-4 text-teal-400 mt-0.5 flex-shrink-0" />
              <p className="text-sm text-teal-100">{s.why}</p>
            </div>
          </CardContent>
        </Card>
      )}

      <div className="grid md:grid-cols-2 gap-4">
        {/* Decision details */}
        <Card className="bg-slate-800/60 border-slate-700">
          <CardHeader className="pb-2">
            <CardTitle className="text-sm text-slate-300">Decision Details</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3 text-sm">
            {[
              ["Signal",     <SignalBadge signal={d.signal_type ?? "HOLD"} />],
              ["Grade",      <GradeBadge grade={d.grade ?? "N/A"} />],
              ["Tier",       d.tier ?? "—"],
              ["Confidence", <Conf value={d.confidence ?? 0} />],
              ["Risk Level", d.risk_level ?? "—"],
              ["Price",      d.price ? `₹${Number(d.price).toFixed(2)}` : "—"],
              ["Target",     d.target ? `₹${Number(d.target).toFixed(2)}` : "—"],
              ["Stop Loss",  d.stop_loss ? `₹${Number(d.stop_loss).toFixed(2)}` : "—"],
              ["Regime",     d.regime ?? "—"],
            ].map(([k, v]) => (
              <div key={String(k)} className="flex justify-between items-center border-b border-slate-700/50 pb-2">
                <span className="text-slate-400">{k}</span>
                <span className="text-white">{v}</span>
              </div>
            ))}
          </CardContent>
        </Card>

        {/* Operator action items */}
        {s && (
          <div className="space-y-3">
            <Card className="bg-slate-800/60 border-slate-700">
              <CardHeader className="pb-1">
                <CardTitle className="text-xs text-slate-400">Action Items</CardTitle>
              </CardHeader>
              <CardContent>
                <ul className="space-y-1">
                  {(s.action_items ?? []).map((item: string, i: number) => (
                    <li key={i} className="flex items-start gap-2 text-xs text-slate-300">
                      <CheckCircle className="h-3 w-3 text-teal-400 mt-0.5 flex-shrink-0" />
                      {item}
                    </li>
                  ))}
                </ul>
              </CardContent>
            </Card>
            <Card className="bg-slate-800/60 border-slate-700">
              <CardHeader className="pb-1">
                <CardTitle className="text-xs text-slate-400">Key Risks</CardTitle>
              </CardHeader>
              <CardContent>
                <ul className="space-y-1">
                  {(s.risks ?? []).map((r: string, i: number) => (
                    <li key={i} className="flex items-start gap-2 text-xs text-red-300">
                      <AlertTriangle className="h-3 w-3 text-red-400 mt-0.5 flex-shrink-0" />
                      {r}
                    </li>
                  ))}
                </ul>
              </CardContent>
            </Card>
          </div>
        )}
      </div>

      {/* Primary reasons */}
      <Card className="bg-slate-800/60 border-slate-700">
        <CardHeader className="pb-2">
          <CardTitle className="text-sm text-slate-300">Primary Reasons</CardTitle>
        </CardHeader>
        <CardContent>
          <ul className="space-y-2">
            {(d.primary_reasons ?? []).map((r: string, i: number) => (
              <li key={i} className="flex items-start gap-2 text-xs text-slate-300">
                <span className="text-teal-400 font-bold">{i + 1}.</span> {r}
              </li>
            ))}
          </ul>
        </CardContent>
      </Card>
    </div>
  );
}

function ContributionsTab({ data: raw }: { data: any }) {
  const contribs: any[] = (raw?.data ?? raw)?.contributions ?? [];
  if (contribs.length === 0)
    return <Card className="bg-slate-800/50 border-slate-700"><CardContent className="pt-6 text-center text-slate-400 py-12 text-sm">No contribution data available.</CardContent></Card>;

  return (
    <Card className="bg-slate-800/60 border-slate-700">
      <CardHeader>
        <CardTitle className="text-sm text-slate-300">12-Indicator Contribution Breakdown</CardTitle>
        <CardDescription className="text-xs text-slate-500">Weights always sum to 100%</CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        {contribs.map((c: any) => (
          <div key={c.indicator_name}>
            <div className="flex justify-between text-xs mb-1">
              <span className="text-slate-300">{c.indicator_name}</span>
              <span className="text-slate-400">{c.contribution_pct?.toFixed(1)}%</span>
            </div>
            <div className="relative h-3 bg-slate-700 rounded-full overflow-hidden">
              <div
                className="absolute inset-y-0 left-0 rounded-full"
                style={{
                  width: `${c.contribution_pct ?? 0}%`,
                  background: c.direction === "BULLISH" ? "#10b981"
                    : c.direction === "BEARISH" ? "#ef4444" : "#6b7280",
                }}
              />
            </div>
            <p className="text-xs text-slate-500 mt-0.5">{c.explanation}</p>
          </div>
        ))}
      </CardContent>
    </Card>
  );
}

function ConfidenceTab({ data: raw }: { data: any }) {
  const conf = (raw?.data ?? raw)?.confidence;
  if (!conf)
    return <Card className="bg-slate-800/50 border-slate-700"><CardContent className="pt-6 text-center text-slate-400 py-12 text-sm">No confidence data available.</CardContent></Card>;

  return (
    <div className="space-y-4">
      <Card className="bg-teal-900/20 border-teal-700/40">
        <CardContent className="pt-4 pb-3">
          <p className="text-sm text-teal-100">{conf.narrative}</p>
        </CardContent>
      </Card>
      <Card className="bg-slate-800/60 border-slate-700">
        <CardHeader className="pb-2">
          <CardTitle className="text-sm text-slate-300">
            8-Dimension Decomposition
            <span className="ml-2"><GradeBadge grade={conf.reliability_grade ?? "N/A"} /></span>
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          {(conf.dimension_details ?? []).map((d: any) => (
            <div key={d.key}>
              <div className="flex justify-between text-xs mb-1">
                <span className="text-slate-300">{d.label}</span>
                <span className="text-slate-400">{d.score?.toFixed(0)}/100 · {d.weight_pct}% weight</span>
              </div>
              <Progress value={d.score ?? 0} className="h-2" />
              <p className="text-xs text-slate-500 mt-0.5">{d.description}</p>
            </div>
          ))}
        </CardContent>
      </Card>
    </div>
  );
}

function ScenariosTab({ data: raw }: { data: any }) {
  const scenarios: any[] = (raw?.data ?? raw)?.scenarios ?? [];
  if (scenarios.length === 0)
    return <Card className="bg-slate-800/50 border-slate-700"><CardContent className="pt-6 text-center text-slate-400 py-12 text-sm">No scenario data available.</CardContent></Card>;

  const colorMap: Record<string, string> = {
    BULLISH: "border-emerald-600/40 bg-emerald-900/20",
    NEUTRAL: "border-slate-600/40 bg-slate-800/40",
    BEARISH: "border-red-600/40 bg-red-900/20",
  };
  const iconMap: Record<string, React.ReactNode> = {
    BULLISH: <TrendingUp className="h-4 w-4 text-emerald-400" />,
    NEUTRAL: <Minus className="h-4 w-4 text-slate-400" />,
    BEARISH: <TrendingDown className="h-4 w-4 text-red-400" />,
  };

  return (
    <div className="grid md:grid-cols-3 gap-4">
      {scenarios.map((s: any) => (
        <Card key={s.scenario_type} className={`border ${colorMap[s.scenario_type] ?? ""}`}>
          <CardHeader className="pb-2">
            <div className="flex items-center gap-2">
              {iconMap[s.scenario_type]}
              <CardTitle className="text-sm">{s.scenario_type}</CardTitle>
              <Badge className="ml-auto text-xs">{Math.round((s.probability ?? 0) * 100)}%</Badge>
            </div>
          </CardHeader>
          <CardContent className="space-y-3 text-xs text-slate-300">
            <p className="italic text-slate-400">{s.narrative}</p>
            <div>
              <p className="font-semibold text-slate-200 mb-1">Expected return</p>
              <p className={s.expected_return >= 0 ? "text-emerald-400" : "text-red-400"}>
                {s.expected_return >= 0 ? "+" : ""}{s.expected_return?.toFixed(2)}%
              </p>
            </div>
            <div>
              <p className="font-semibold text-slate-200 mb-1">Key conditions</p>
              <ul className="list-disc list-inside space-y-0.5">
                {(s.key_conditions ?? []).map((c: string, i: number) => <li key={i}>{c}</li>)}
              </ul>
            </div>
            <div>
              <p className="font-semibold text-slate-200 mb-1">Risk factors</p>
              <ul className="list-disc list-inside space-y-0.5 text-red-300">
                {(s.risk_factors ?? []).map((r: string, i: number) => <li key={i}>{r}</li>)}
              </ul>
            </div>
          </CardContent>
        </Card>
      ))}
    </div>
  );
}

function HistoryTab({ data: raw, symbol }: { data: any; symbol: string }) {
  const matches: any[] = (raw?.data ?? raw)?.matches ?? [];
  return (
    <Card className="bg-slate-800/60 border-slate-700">
      <CardHeader>
        <CardTitle className="text-sm text-slate-300">Historical Pattern Matches for {symbol}</CardTitle>
        <CardDescription className="text-xs text-slate-500">Up to 5 past setups with ≥50% similarity</CardDescription>
      </CardHeader>
      <CardContent>
        {matches.length === 0 ? (
          <p className="text-center text-slate-400 text-sm py-8">No historical matches found yet.</p>
        ) : (
          <div className="space-y-3">
            {matches.map((m: any, i: number) => (
              <div key={i} className="p-3 bg-slate-700/40 rounded-lg border border-slate-700">
                <div className="flex items-center justify-between mb-1">
                  <span className="text-xs font-medium text-white">{m.date}</span>
                  <Badge className="text-xs">{Math.round((m.similarity_score ?? 0) * 100)}% match</Badge>
                </div>
                <p className="text-xs text-slate-400 mb-2">{m.narrative}</p>
                <div className="flex gap-2 flex-wrap">
                  {(m.match_reasons ?? []).map((r: string, j: number) => (
                    <span key={j} className="text-xs bg-slate-600/40 text-slate-300 px-2 py-0.5 rounded">
                      {r}
                    </span>
                  ))}
                </div>
              </div>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function ContextCard({
  title, icon: Icon, data: raw,
}: {
  title: string;
  icon: React.ComponentType<any>;
  data: any;
}) {
  const d    = raw?.data ?? raw;
  const info = d && !d?.available === false ? d : null;

  return (
    <div className="space-y-4">
      {info?.narrative && (
        <Card className="bg-teal-900/20 border-teal-700/40">
          <CardContent className="pt-4 pb-3">
            <div className="flex items-start gap-2">
              <Icon className="h-4 w-4 text-teal-400 mt-0.5 flex-shrink-0" />
              <p className="text-sm text-teal-100">{info.narrative}</p>
            </div>
          </CardContent>
        </Card>
      )}
      <Card className="bg-slate-800/60 border-slate-700">
        <CardHeader className="pb-2">
          <CardTitle className="text-sm text-slate-300">{title}</CardTitle>
        </CardHeader>
        <CardContent>
          {info?.available === false ? (
            <p className="text-center text-slate-400 text-sm py-6">Data not available.</p>
          ) : (
            <ul className="space-y-2">
              {(info?.bullet_points ?? []).map((b: string, i: number) => (
                <li key={i} className="flex items-start gap-2 text-xs text-slate-300">
                  <span className="text-teal-400">•</span> {b}
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

function RiskTab({ data: raw }: { data: any }) {
  const d = raw?.data ?? raw;
  return (
    <div className="space-y-4">
      {d?.narrative && (
        <Card className="bg-teal-900/20 border-teal-700/40">
          <CardContent className="pt-4 pb-3">
            <div className="flex items-start gap-2">
              <Shield className="h-4 w-4 text-teal-400 mt-0.5 flex-shrink-0" />
              <p className="text-sm text-teal-100">{d.narrative}</p>
            </div>
          </CardContent>
        </Card>
      )}
      <Card className="bg-slate-800/60 border-slate-700">
        <CardHeader className="pb-2">
          <CardTitle className="text-sm text-slate-300">
            Risk Dimensions
            {d?.overall_risk_level && (
              <Badge className="ml-2 text-xs">{d.overall_risk_level}</Badge>
            )}
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          {(d?.dimensions ?? []).map((dim: any) => (
            <div key={dim.key}>
              <div className="flex justify-between text-xs mb-1">
                <span className="text-slate-300">{dim.label}</span>
                <span className="text-slate-400">{dim.score?.toFixed(0)}/100 · {dim.risk_level}</span>
              </div>
              <Progress value={dim.score ?? 0} className="h-2" />
              <p className="text-xs text-slate-500 mt-0.5">{dim.description}</p>
            </div>
          ))}
        </CardContent>
      </Card>
    </div>
  );
}

// ── page ──────────────────────────────────────────────────────────────────────

export default function ExplainableAI() {
  const [symbol, setSymbol] = useState<string>(SYMBOLS[0]);

  const summaryQ       = useSummary();
  const decisionQ      = useDecision(symbol);
  const contributionsQ = useContributions(symbol);
  const confidenceQ    = useConfidence(symbol);
  const scenariosQ     = useScenarios(symbol);
  const historyQ       = useHistory(symbol);

  // Derive market/event/macro/risk context from the decision response (cached upstream snaps)
  const decisionData = decisionQ.data?.data ?? decisionQ.data;
  const d            = decisionData?.decision;

  function Loading() {
    return (
      <div className="flex items-center justify-center py-16 text-slate-400">
        <RefreshCw className="h-5 w-5 animate-spin mr-2" />
        Loading…
      </div>
    );
  }

  return (
    <div className="p-4 md:p-6 space-y-4 max-w-7xl mx-auto">
      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <h1 className="text-xl font-bold text-white flex items-center gap-2">
            <Lightbulb className="h-5 w-5 text-teal-400" />
            Explainable AI
          </h1>
          <p className="text-sm text-slate-400 mt-0.5">
            Understand the reasoning behind every signal — plain language, no black box.
          </p>
        </div>

        {/* Symbol selector */}
        <div className="flex items-center gap-2">
          <span className="text-xs text-slate-400">Symbol:</span>
          <Select value={symbol} onValueChange={setSymbol}>
            <SelectTrigger className="w-40 bg-slate-800 border-slate-700 text-white text-xs h-8">
              <SelectValue />
            </SelectTrigger>
            <SelectContent className="bg-slate-800 border-slate-700">
              {SYMBOLS.map(s => (
                <SelectItem key={s} value={s} className="text-xs text-white hover:bg-slate-700">
                  {s}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </div>

      {/* Tabs */}
      <Tabs defaultValue="overview">
        <TabsList className="flex flex-wrap h-auto gap-1 bg-slate-800/60 p-1">
          {[
            ["overview",      "Overview"],
            ["summary",       "Summary"],
            ["decision",      "Decision"],
            ["contributions", "Contributions"],
            ["confidence",    "Confidence"],
            ["scenarios",     "Scenarios"],
            ["history",       "History"],
            ["market",        "Market"],
            ["events",        "Events"],
            ["macro",         "Macro"],
            ["risk",          "Risk"],
          ].map(([value, label]) => (
            <TabsTrigger key={value} value={value} className="text-xs px-3 py-1.5">
              {label}
            </TabsTrigger>
          ))}
        </TabsList>

        <TabsContent value="overview" className="mt-4">
          {summaryQ.isLoading ? <Loading /> : <OverviewTab summary={summaryQ.data} />}
        </TabsContent>

        <TabsContent value="summary" className="mt-4">
          {decisionQ.isLoading ? <Loading /> : <SummaryTab data={decisionQ.data} symbol={symbol} />}
        </TabsContent>

        <TabsContent value="decision" className="mt-4">
          {decisionQ.isLoading ? <Loading /> : <DecisionTab data={decisionQ.data} symbol={symbol} />}
        </TabsContent>

        <TabsContent value="contributions" className="mt-4">
          {contributionsQ.isLoading ? <Loading /> : <ContributionsTab data={contributionsQ.data} />}
        </TabsContent>

        <TabsContent value="confidence" className="mt-4">
          {confidenceQ.isLoading ? <Loading /> : <ConfidenceTab data={confidenceQ.data} />}
        </TabsContent>

        <TabsContent value="scenarios" className="mt-4">
          {scenariosQ.isLoading ? <Loading /> : <ScenariosTab data={scenariosQ.data} />}
        </TabsContent>

        <TabsContent value="history" className="mt-4">
          {historyQ.isLoading ? <Loading /> : <HistoryTab data={historyQ.data} symbol={symbol} />}
        </TabsContent>

        <TabsContent value="market" className="mt-4">
          <ContextCard
            title="Market Intelligence Context"
            icon={Globe2}
            data={d?.market_context ?? { available: true, narrative: "Select a symbol with a live signal to view market context.", bullet_points: [] }}
          />
        </TabsContent>

        <TabsContent value="events" className="mt-4">
          <ContextCard
            title="Event Intelligence Context"
            icon={CalendarDays}
            data={d?.event_context ?? { available: true, narrative: "Select a symbol with a live signal to view event context.", bullet_points: [] }}
          />
        </TabsContent>

        <TabsContent value="macro" className="mt-4">
          <ContextCard
            title="Macro Intelligence Context"
            icon={Globe}
            data={d?.macro_context ?? { available: true, narrative: "Select a symbol with a live signal to view macro context.", bullet_points: [] }}
          />
        </TabsContent>

        <TabsContent value="risk" className="mt-4">
          <RiskTab data={d?.risk_context ?? { available: true, narrative: "Select a symbol with a live signal to view risk context.", dimensions: [] }} />
        </TabsContent>
      </Tabs>
    </div>
  );
}
