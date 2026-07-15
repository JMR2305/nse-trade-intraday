/**
 * PortfolioRiskAnalytics.tsx — Phase 11b institutional-grade portfolio risk view.
 * Portfolio exposure stats, sector diversification, risk heatmap, charts and
 * trade approval cards with per-stock risk scores + plain-language explanations.
 * PAPER TRADING / RESEARCH ONLY. ATR & event risk are honestly "Not Available";
 * correlation is a sector-proxy estimate.
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import {
  PieChart, Pie, Cell, ResponsiveContainer, BarChart, Bar, XAxis, YAxis,
  Tooltip, AreaChart, Area, CartesianGrid,
} from "recharts";
import {
  ShieldHalf, Loader2, RefreshCw, AlertTriangle, Flame, LayoutGrid,
  PieChart as PieIcon, BarChart3, TrendingUp,
} from "lucide-react";
import { API_BASE } from "@/lib/api";
import { useToast } from "@/hooks/use-toast";

/* eslint-disable @typescript-eslint/no-explicit-any */

const PIE_COLORS = ["#10b981", "#3b82f6", "#f59e0b", "#8b5cf6", "#ef4444", "#14b8a6", "#eab308", "#64748b"];
const HEAT_BG: Record<string, string> = {
  GREEN: "bg-emerald-900/50 border-emerald-700 text-emerald-300",
  YELLOW: "bg-yellow-900/40 border-yellow-700 text-yellow-300",
  ORANGE: "bg-orange-900/40 border-orange-700 text-orange-300",
  RED: "bg-red-900/40 border-red-700 text-red-300",
};
const BAND_COLOR: Record<string, string> = {
  LOW: "text-emerald-400 border-emerald-700",
  MEDIUM: "text-yellow-400 border-yellow-700",
  HIGH: "text-orange-400 border-orange-700",
  EXTREME: "text-red-400 border-red-700",
  "Not Available": "text-zinc-500 border-zinc-700",
};
const VERDICT_COLOR: Record<string, string> = {
  APPROVE: "text-emerald-400 border-emerald-700",
  WATCH: "text-amber-400 border-amber-700",
  REJECT: "text-red-400 border-red-700",
};

const naStr = (v: any, prefix = "") =>
  v === null || v === undefined || v === "Not Available" ? "Not Available" : `${prefix}${v}`;

export default function PortfolioRiskAnalytics() {
  const { toast } = useToast();
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [verdictFilter, setVerdictFilter] = useState<string>("ALL");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await fetch(`${API_BASE}/risk/analytics`);
      const d = await r.json();
      if (!r.ok || d.error) throw new Error(d.error ?? `HTTP ${r.status}`);
      setData(d);
    } catch (e: any) {
      toast({ title: "Failed to load risk analytics", description: e.message, variant: "destructive" });
    } finally {
      setLoading(false);
    }
  }, [toast]);

  useEffect(() => { load(); }, [load]);

  const p = data?.portfolio;
  const cards = useMemo(() => {
    const all = data?.approval_cards ?? [];
    return verdictFilter === "ALL" ? all : all.filter((c: any) => c.verdict === verdictFilter);
  }, [data, verdictFilter]);

  const stats = p ? [
    { label: "Total Capital", value: `₹${p.total_capital}` },
    { label: "Cash Available", value: `₹${p.cash_available}` },
    { label: "Invested", value: `₹${p.invested_amount}` },
    { label: "Utilization", value: `${p.utilization_pct}%` },
    { label: "Open Positions", value: `${p.open_positions}` },
    { label: "Largest Position", value: p.largest_position ? `${p.largest_position.symbol} (${p.largest_position.pct}%)` : "None" },
    { label: "Daily Risk", value: typeof p.daily_risk === "number" ? `₹${p.daily_risk}` : String(p.daily_risk) },
    { label: "Max Possible Loss", value: `₹${p.max_possible_loss}`, sub: p.max_possible_loss_note },
    { label: "Expected Reward", value: naStr(p.expected_portfolio_reward, "₹") },
    { label: "Avg R:R", value: naStr(p.avg_rr) },
  ] : [];

  return (
    <div className="space-y-6 font-mono">
      <div className="flex flex-wrap items-center gap-3">
        <ShieldHalf className="h-5 w-5 text-primary" />
        <h1 className="text-xl font-bold text-foreground">Portfolio Risk Analytics</h1>
        <Badge variant="outline" className="text-[10px] text-amber-400 border-amber-700">
          PAPER TRADING / RESEARCH ONLY
        </Badge>
        <Button size="sm" variant="outline" className="ml-auto gap-2" onClick={load} disabled={loading}>
          {loading ? <Loader2 className="h-3 w-3 animate-spin" /> : <RefreshCw className="h-3 w-3" />}Refresh
        </Button>
      </div>

      {/* Exposure stats */}
      <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
        {stats.map((m) => (
          <Card key={m.label} className="border-zinc-800 bg-zinc-900/60">
            <CardContent className="px-4 py-3">
              <div className="text-[10px] uppercase tracking-widest text-zinc-500">{m.label}</div>
              <div className="mt-1 truncate text-sm font-bold text-foreground" title={String(m.value)}>{m.value}</div>
              {"sub" in m && m.sub && <div className="text-[9px] text-zinc-600">{m.sub}</div>}
            </CardContent>
          </Card>
        ))}
      </div>

      {/* Sector diversification + warnings */}
      <Card className="border-zinc-800 bg-zinc-900/60">
        <CardHeader className="px-5 pb-2 pt-4">
          <h2 className="flex items-center gap-2 text-sm font-bold uppercase tracking-widest text-zinc-300">
            <BarChart3 className="h-4 w-4 text-primary" />Sector Diversification (limit {data?.sector_limit_pct}%)
          </h2>
        </CardHeader>
        <CardContent className="space-y-2 px-5 pb-5 text-xs">
          {data?.sector_allocation?.length ? data.sector_allocation.map((s: any) => (
            <div key={s.sector} className="flex items-center gap-3">
              <span className="w-28 shrink-0 text-zinc-400">{s.sector}</span>
              <div className="h-2 flex-1 rounded bg-zinc-800">
                <div
                  className={`h-2 rounded ${(s.pct_of_portfolio ?? 0) > (data.sector_limit_pct ?? 40) ? "bg-red-500" : "bg-primary"}`}
                  style={{ width: `${Math.min(100, s.pct_of_portfolio ?? 0)}%` }} />
              </div>
              <span className="w-14 text-right">{s.pct_of_portfolio}%</span>
            </div>
          )) : <div className="text-zinc-500">No open positions</div>}
          {data?.sector_warnings?.length > 0 && (
            <div className="mt-2 rounded border border-red-800 bg-red-950/30 p-2 text-red-400">
              <AlertTriangle className="mr-1 inline h-3 w-3" />
              Sector limit exceeded: {data.sector_warnings.join(", ")}
            </div>
          )}
        </CardContent>
      </Card>

      {/* Risk heatmap */}
      <Card className="border-zinc-800 bg-zinc-900/60">
        <CardHeader className="px-5 pb-2 pt-4">
          <h2 className="flex items-center gap-2 text-sm font-bold uppercase tracking-widest text-zinc-300">
            <Flame className="h-4 w-4 text-primary" />Portfolio Risk Heatmap
          </h2>
        </CardHeader>
        <CardContent className="px-5 pb-5">
          {data?.positions?.length ? (
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-4 lg:grid-cols-6">
              {data.positions.map((pos: any) => (
                <div key={pos.symbol} className={`rounded border p-3 text-xs ${HEAT_BG[pos.heat] ?? HEAT_BG.RED}`}>
                  <div className="font-bold">{pos.symbol}</div>
                  <div>₹{pos.value} · {pos.pct_of_portfolio}%</div>
                  <div className="text-[10px] opacity-80">{pos.heat} — {pos.heat_basis}</div>
                </div>
              ))}
            </div>
          ) : <div className="text-xs text-zinc-500">No open positions</div>}
          <div className="mt-3 flex gap-3 text-[10px] text-zinc-500">
            <span className="text-emerald-400">■ Green = Safe</span>
            <span className="text-yellow-400">■ Yellow = Moderate</span>
            <span className="text-orange-400">■ Orange = High</span>
            <span className="text-red-400">■ Red = Extreme / no stop</span>
          </div>
        </CardContent>
      </Card>

      {/* Charts */}
      <div className="grid gap-4 lg:grid-cols-3">
        <Card className="border-zinc-800 bg-zinc-900/60">
          <CardHeader className="px-5 pb-0 pt-4">
            <h2 className="flex items-center gap-2 text-xs font-bold uppercase tracking-widest text-zinc-300">
              <PieIcon className="h-3 w-3 text-primary" />Portfolio Allocation
            </h2>
          </CardHeader>
          <CardContent className="h-56 px-2 pb-2">
            <ResponsiveContainer width="100%" height="100%">
              <PieChart>
                <Pie data={data?.charts?.allocation_pie ?? []} dataKey="value" nameKey="name"
                  outerRadius={70} isAnimationActive={false} label={(e: any) => e.name}>
                  {(data?.charts?.allocation_pie ?? []).map((_: any, i: number) => (
                    <Cell key={i} fill={PIE_COLORS[i % PIE_COLORS.length]} />
                  ))}
                </Pie>
                <Tooltip contentStyle={{ background: "#18181b", border: "1px solid #3f3f46", fontSize: 11 }} />
              </PieChart>
            </ResponsiveContainer>
          </CardContent>
        </Card>

        <Card className="border-zinc-800 bg-zinc-900/60">
          <CardHeader className="px-5 pb-0 pt-4">
            <h2 className="text-xs font-bold uppercase tracking-widest text-zinc-300">Risk Distribution (scan candidates)</h2>
          </CardHeader>
          <CardContent className="h-56 px-2 pb-2">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={data?.charts?.risk_distribution ?? []}>
                <CartesianGrid strokeDasharray="3 3" stroke="#27272a" />
                <XAxis dataKey="band" tick={{ fontSize: 9, fill: "#a1a1aa" }} />
                <YAxis tick={{ fontSize: 9, fill: "#a1a1aa" }} allowDecimals={false} />
                <Tooltip contentStyle={{ background: "#18181b", border: "1px solid #3f3f46", fontSize: 11 }} />
                <Bar dataKey="count" fill="#f59e0b" />
              </BarChart>
            </ResponsiveContainer>
          </CardContent>
        </Card>

        <Card className="border-zinc-800 bg-zinc-900/60">
          <CardHeader className="px-5 pb-0 pt-4">
            <h2 className="text-xs font-bold uppercase tracking-widest text-zinc-300">Confidence Distribution</h2>
          </CardHeader>
          <CardContent className="h-56 px-2 pb-2">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={data?.charts?.confidence_distribution ?? []}>
                <CartesianGrid strokeDasharray="3 3" stroke="#27272a" />
                <XAxis dataKey="bucket" tick={{ fontSize: 9, fill: "#a1a1aa" }} />
                <YAxis tick={{ fontSize: 9, fill: "#a1a1aa" }} allowDecimals={false} />
                <Tooltip contentStyle={{ background: "#18181b", border: "1px solid #3f3f46", fontSize: 11 }} />
                <Bar dataKey="count" fill="#3b82f6" />
              </BarChart>
            </ResponsiveContainer>
          </CardContent>
        </Card>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card className="border-zinc-800 bg-zinc-900/60">
          <CardHeader className="px-5 pb-0 pt-4">
            <h2 className="flex items-center gap-2 text-xs font-bold uppercase tracking-widest text-zinc-300">
              <TrendingUp className="h-3 w-3 text-primary" />Portfolio Exposure Timeline
            </h2>
          </CardHeader>
          <CardContent className="h-56 px-2 pb-2">
            {data?.charts?.exposure_timeline?.length > 1 ? (
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={data.charts.exposure_timeline}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#27272a" />
                  <XAxis dataKey="timestamp" tick={{ fontSize: 8, fill: "#a1a1aa" }}
                    tickFormatter={(t: string) => t?.slice(5, 10)} />
                  <YAxis tick={{ fontSize: 9, fill: "#a1a1aa" }} domain={["auto", "auto"]} />
                  <Tooltip contentStyle={{ background: "#18181b", border: "1px solid #3f3f46", fontSize: 11 }} />
                  <Area type="monotone" dataKey="portfolio_value" stroke="#10b981" fill="#10b98122" />
                </AreaChart>
              </ResponsiveContainer>
            ) : <div className="p-4 text-xs text-zinc-500">Not Available — fewer than 2 equity history points</div>}
          </CardContent>
        </Card>

        <Card className="border-zinc-800 bg-zinc-900/60">
          <CardHeader className="px-5 pb-0 pt-4">
            <h2 className="text-xs font-bold uppercase tracking-widest text-zinc-300">Capital Utilization</h2>
          </CardHeader>
          <CardContent className="flex h-56 flex-col items-center justify-center gap-3 px-5 pb-5">
            <div className="relative h-28 w-28">
              <svg viewBox="0 0 36 36" className="h-full w-full -rotate-90">
                <circle cx="18" cy="18" r="15.9" fill="none" stroke="#27272a" strokeWidth="3.8" />
                <circle cx="18" cy="18" r="15.9" fill="none" stroke="#10b981" strokeWidth="3.8"
                  strokeDasharray={`${data?.charts?.utilization_gauge?.value ?? 0}, 100`} strokeLinecap="round" />
              </svg>
              <div className="absolute inset-0 flex items-center justify-center text-lg font-bold">
                {data?.charts?.utilization_gauge?.value ?? "…"}%
              </div>
            </div>
            <div className="text-[10px] text-zinc-500">Invested % of total capital</div>
          </CardContent>
        </Card>
      </div>

      {/* Trade approval cards */}
      <Card className="border-zinc-800 bg-zinc-900/60">
        <CardHeader className="px-5 pb-2 pt-4">
          <div className="flex flex-wrap items-center gap-3">
            <h2 className="flex items-center gap-2 text-sm font-bold uppercase tracking-widest text-zinc-300">
              <LayoutGrid className="h-4 w-4 text-primary" />Trade Approval Cards
              <span className="text-zinc-500">({cards.length})</span>
            </h2>
            <div className="ml-auto flex gap-1">
              {["ALL", "APPROVE", "WATCH", "REJECT"].map((v) => (
                <Button key={v} size="sm" variant={verdictFilter === v ? "default" : "outline"}
                  className="h-6 px-2 text-[10px]" onClick={() => setVerdictFilter(v)}>{v}</Button>
              ))}
            </div>
          </div>
          {data?.scan_snapshot_ts && (
            <div className="text-[10px] text-zinc-600">Scan snapshot: {data.scan_snapshot_ts}</div>
          )}
        </CardHeader>
        <CardContent className="grid gap-3 px-5 pb-5 md:grid-cols-2 xl:grid-cols-3">
          {cards.length ? cards.map((c: any) => (
            <div key={c.symbol} className="space-y-2 rounded border border-zinc-800 bg-zinc-950/50 p-3 text-xs">
              <div className="flex items-center gap-2">
                <span className="font-bold text-foreground">{c.symbol}</span>
                <span className="text-zinc-500">{c.sector}</span>
                <Badge variant="outline" className={`ml-auto text-[9px] ${VERDICT_COLOR[c.verdict] ?? ""}`}>{c.verdict}</Badge>
                <Badge variant="outline" className={`text-[9px] ${BAND_COLOR[c.risk_band] ?? ""}`}>
                  RISK {c.risk_band}{c.risk_score != null ? ` ${c.risk_score}` : ""}
                </Badge>
              </div>
              <div className="grid grid-cols-2 gap-x-3 gap-y-0.5 text-[11px] text-zinc-400">
                <span>Score: {naStr(c.overall_score)}</span>
                <span>Conf: {naStr(c.confidence)}%</span>
                <span>Entry: ₹{c.entry_price}</span>
                <span>R:R: {naStr(c.rr_ratio)}</span>
                <span>Qty: {c.recommended_quantity}</span>
                <span>Capital: ₹{c.capital_required} ({c.capital_allocation_pct}%)</span>
                <span>Max Risk: {naStr(c.max_risk, "₹")}</span>
                <span>Reward: {naStr(c.expected_reward, "₹")}</span>
                <span>Sector now: {c.sector_weight_now_pct}%</span>
                <span>After: {c.sector_weight_after_pct}%</span>
              </div>
              <div className="border-t border-zinc-800/60 pt-1.5 text-[10px] leading-relaxed text-zinc-500">
                {c.explanation}
              </div>
              <details className="text-[10px] text-zinc-600">
                <summary className="cursor-pointer text-zinc-500">Risk components</summary>
                <ul className="mt-1 space-y-0.5">
                  {Object.entries(c.risk_components ?? {}).map(([k, v]: [string, any]) => (
                    <li key={k}>
                      <span className="text-zinc-400">{k}</span>: {v.score ?? "Not Available"} — {v.basis}
                    </li>
                  ))}
                </ul>
              </details>
            </div>
          )) : <div className="text-xs text-zinc-500">No scan candidates{verdictFilter !== "ALL" ? ` with verdict ${verdictFilter}` : ""}. Run a market scan first.</div>}
        </CardContent>
      </Card>

      <p className="text-[10px] text-zinc-600">
        All values computed from real paper-trading state and the latest market scan. ATR and event
        risk are Not Available (no data source connected) and are excluded from scores rather than
        fabricated. Correlation is a sector-proxy estimate. No real-money execution exists.
      </p>
    </div>
  );
}
