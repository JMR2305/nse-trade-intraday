/**
 * CommandCenter.tsx — Phase 9.1
 * ApexQuant AI Unified Command Centre — Default Home Page
 *
 * READ-ONLY · ADVISORY-ONLY
 * Aggregates snapshot data from all existing modules. Zero new calculations.
 */
import { useQuery } from "@tanstack/react-query";
import { apiJson } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { useState } from "react";
import {
  TrendingUp, TrendingDown, Minus, AlertTriangle, CheckCircle2,
  Activity, Shield, Zap, Rocket, BarChart2, Brain, Monitor,
  Download, Clock, ArrowUpRight, ArrowDownRight, FlaskConical, Bot,
} from "lucide-react";

// ── query helpers ──────────────────────────────────────────────────────────────
const REFETCH = 30_000;
const q = (path: string) => ({
  queryKey:  ["cc", path],
  queryFn:   () => apiJson("command-center/" + path),
  refetchInterval: REFETCH,
  retry: 1,
  staleTime: 15_000,
});

// ── sub-components ─────────────────────────────────────────────────────────────
function GradeChip({ grade, score }: { grade: string; score: number }) {
  const bg =
    grade === "A+" || grade === "A" ? "bg-emerald-600" :
    grade === "B" ? "bg-blue-600"   :
    grade === "C" ? "bg-amber-500"  : "bg-red-600";
  return (
    <span className={`inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-white text-xs font-semibold ${bg}`}>
      {score?.toFixed(1)} <span className="opacity-75">/ 100</span>
      <span className="ml-1 bg-white/20 px-1 rounded">{grade}</span>
    </span>
  );
}

function StatusDot({ status }: { status: string }) {
  const c: Record<string, string> = {
    HEALTHY: "bg-emerald-400", DEGRADED: "bg-amber-400",
    CRITICAL: "bg-red-500", UNKNOWN: "bg-gray-400",
    READY: "bg-emerald-400", NOT_READY: "bg-red-500", RUNNING: "bg-emerald-400",
  };
  return <span className={`inline-block w-2 h-2 rounded-full ${c[status] ?? "bg-gray-400"}`} />;
}

function Trend({ dir }: { dir: string }) {
  if (dir === "UPTREND" || dir === "Improving") return <ArrowUpRight className="w-4 h-4 text-emerald-400 inline" />;
  if (dir === "DOWNTREND" || dir === "Degrading") return <ArrowDownRight className="w-4 h-4 text-red-400 inline" />;
  return <Minus className="w-4 h-4 text-slate-400 inline" />;
}

function KpiCard({ label, value, unit = "", sub, color = "" }: { label: string; value: any; unit?: string; sub?: string; color?: string }) {
  return (
    <div className="bg-card rounded-xl border border-border p-4 flex flex-col gap-1">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className={`text-2xl font-bold ${color}`}>
        {value == null ? "—" : `${value}${unit}`}
      </p>
      {sub && <p className="text-xs text-muted-foreground">{sub}</p>}
    </div>
  );
}

function SectionHeader({ icon: Icon, title, sub }: { icon: any; title: string; sub?: string }) {
  return (
    <div className="flex items-center gap-2 mb-3">
      <Icon className="w-4 h-4 text-teal-400" />
      <h2 className="font-semibold text-sm tracking-wide uppercase text-muted-foreground">{title}</h2>
      {sub && <span className="text-xs text-muted-foreground ml-auto">{sub}</span>}
    </div>
  );
}

function ScoreBar({ score }: { score: number }) {
  const color = score >= 80 ? "bg-emerald-500" : score >= 60 ? "bg-amber-400" : "bg-red-500";
  return (
    <div className="h-1.5 w-full rounded-full bg-muted">
      <div className={`h-1.5 rounded-full ${color} transition-all`} style={{ width: `${Math.min(100, score)}%` }} />
    </div>
  );
}

function DisabledBanner() {
  return (
    <Alert className="border-teal-500/30 bg-teal-500/5 mb-6">
      <AlertDescription className="text-sm text-teal-200">
        Set <code className="text-teal-300">COMMAND_CENTER_ENABLED=true</code> to enable the Unified Command Centre.
      </AlertDescription>
    </Alert>
  );
}

// ── Section 1 — Platform Header ────────────────────────────────────────────────
function PlatformHeader({ summary }: { summary: any }) {
  const ps = summary?.platform_score ?? 0;
  const pg = summary?.platform_grade ?? "D";
  const pst = summary?.platform_status ?? "UNKNOWN";
  const sched = summary?.scheduler_status ?? "UNKNOWN";
  return (
    <div className="bg-card border border-border rounded-xl p-4 flex flex-wrap items-center gap-4">
      <div className="flex items-center gap-3">
        <div className={`w-3 h-3 rounded-full ${pst === "HEALTHY" ? "bg-emerald-400" : pst === "DEGRADED" ? "bg-amber-400" : "bg-red-500"} animate-pulse`} />
        <span className="font-semibold text-sm">Platform {pst}</span>
        <GradeChip grade={pg} score={ps} />
      </div>
      <div className="flex items-center gap-2 text-xs text-muted-foreground">
        <Clock className="w-3 h-3" />
        {summary?.current_time ?? "—"}
      </div>
      <Badge variant="outline" className="text-xs gap-1">
        <StatusDot status={sched} /> Scheduler: {sched}
      </Badge>
      <Badge variant="outline" className="text-xs border-amber-500/40 text-amber-300">
        📋 {summary?.execution_mode ?? "PAPER_TRADING"}
      </Badge>
      <span className="text-xs text-muted-foreground ml-auto">
        {summary?.generated_at?.slice(0, 19)?.replace("T", " ")} UTC
      </span>
    </div>
  );
}

// ── Section 2 — Market Overview ────────────────────────────────────────────────
function MarketOverviewSection({ market }: { market: any }) {
  if (!market) return null;
  const { nifty50, bank_nifty, india_vix } = market;
  const sentimentColor = (market.regime ?? "").includes("BULL") ? "text-emerald-400"
    : (market.regime ?? "").includes("BEAR") ? "text-red-400" : "text-slate-300";
  return (
    <div className="bg-card border border-border rounded-xl p-4">
      <SectionHeader icon={TrendingUp} title="Market Overview"
        sub={`Regime: ${market.regime ?? "UNKNOWN"} · Trend: ${market.strongest_sector ?? "—"} leads`} />

      {/* Index cards */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-4">
        <div className="bg-muted/30 rounded-lg p-3">
          <p className="text-xs text-muted-foreground">NIFTY 50</p>
          <p className="text-lg font-bold">
            {nifty50?.price ? nifty50.price.toLocaleString("en-IN", { maximumFractionDigits: 0 }) : "—"}
          </p>
          <p className={`text-xs ${(nifty50?.change_pct ?? 0) >= 0 ? "text-emerald-400" : "text-red-400"}`}>
            {(nifty50?.change_pct ?? 0) >= 0 ? "▲" : "▼"} {Math.abs(nifty50?.change_pct ?? 0).toFixed(2)}%
          </p>
        </div>
        <div className="bg-muted/30 rounded-lg p-3">
          <p className="text-xs text-muted-foreground">BANK NIFTY</p>
          <p className="text-lg font-bold">
            {bank_nifty?.price ? bank_nifty.price.toLocaleString("en-IN", { maximumFractionDigits: 0 }) : "—"}
          </p>
          <p className={`text-xs ${(bank_nifty?.change_pct ?? 0) >= 0 ? "text-emerald-400" : "text-red-400"}`}>
            {(bank_nifty?.change_pct ?? 0) >= 0 ? "▲" : "▼"} {Math.abs(bank_nifty?.change_pct ?? 0).toFixed(2)}%
          </p>
        </div>
        <div className="bg-muted/30 rounded-lg p-3">
          <p className="text-xs text-muted-foreground">India VIX</p>
          <p className="text-lg font-bold">{india_vix?.value?.toFixed(2) ?? "—"}</p>
          <p className="text-xs text-muted-foreground">{india_vix?.status ?? "—"}</p>
        </div>
        <div className="bg-muted/30 rounded-lg p-3">
          <p className="text-xs text-muted-foreground">Breadth</p>
          <p className="text-lg font-bold text-emerald-400">{market.advance ?? 0}</p>
          <p className="text-xs">
            <span className="text-emerald-400">▲{market.advance ?? 0}</span>
            {" / "}
            <span className="text-red-400">▼{market.decline ?? 0}</span>
          </p>
        </div>
      </div>

      {/* Regime + sectors */}
      <div className="flex flex-wrap gap-3 text-xs">
        <span className="text-muted-foreground">
          Strongest: <b className="text-emerald-400">{market.strongest_sector ?? "N/A"}</b>
        </span>
        <span className="text-muted-foreground">
          Weakest: <b className="text-red-400">{market.weakest_sector ?? "N/A"}</b>
        </span>
        <span className={`font-medium ${sentimentColor}`}>● {market.regime ?? "UNKNOWN"}</span>
        {market.high_volatility && (
          <Badge variant="outline" className="border-red-500/40 text-red-300 text-xs">HIGH VOL</Badge>
        )}
      </div>
    </div>
  );
}

// ── Section 3 — Portfolio Snapshot ─────────────────────────────────────────────
function PortfolioSection({ portfolio }: { portfolio: any }) {
  if (!portfolio) return null;
  const pnlColor = (portfolio.net_pnl ?? 0) >= 0 ? "text-emerald-400" : "text-red-400";
  return (
    <div className="bg-card border border-border rounded-xl p-4">
      <SectionHeader icon={BarChart2} title="Portfolio Snapshot"
        sub={portfolio.analytics_grade ? `Grade ${portfolio.analytics_grade}` : undefined} />
      <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
        <KpiCard label="Portfolio Value" value={`₹${(portfolio.portfolio_value ?? 0).toLocaleString("en-IN", { maximumFractionDigits: 0 })}`} />
        <KpiCard label="Net P&L" value={`${portfolio.net_pnl >= 0 ? "+" : ""}₹${(portfolio.net_pnl ?? 0).toLocaleString("en-IN", { maximumFractionDigits: 0 })}`} color={pnlColor} />
        <KpiCard label="Open Positions" value={portfolio.open_positions ?? 0} />
        <KpiCard label="Win Rate" value={(portfolio.win_rate ?? 0).toFixed(1)} unit="%" />
        <KpiCard label="Sharpe Ratio" value={(portfolio.sharpe_ratio ?? 0).toFixed(2)} />
        <KpiCard label="Best Strategy" value={portfolio.best_strategy ?? "N/A"} />
      </div>
    </div>
  );
}

// ── Section 4 — Today's Trading ────────────────────────────────────────────────
function TradingSection({ trading }: { trading: any }) {
  if (!trading) return null;
  return (
    <div className="bg-card border border-border rounded-xl p-4">
      <SectionHeader icon={Activity} title="Today's Trading" sub="Paper mode" />
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <KpiCard label="Trades" value={trading.total_trades ?? 0} />
        <KpiCard label="Win Rate" value={(trading.win_rate ?? 0).toFixed(1)} unit="%" color={(trading.win_rate ?? 0) >= 55 ? "text-emerald-400" : "text-amber-400"} />
        <KpiCard label="Profit Factor" value={(trading.profit_factor ?? 0).toFixed(2)} color={(trading.profit_factor ?? 0) >= 1.5 ? "text-emerald-400" : ""} />
        <KpiCard label="Expectancy" value={`₹${(trading.expectancy ?? 0).toFixed(0)}`} color={(trading.expectancy ?? 0) >= 0 ? "text-emerald-400" : "text-red-400"} />
      </div>
    </div>
  );
}

// ── Section 5 — AI Summary ─────────────────────────────────────────────────────
function AiSection({ ai }: { ai: any }) {
  if (!ai) return null;
  const healthColor = (ai.health_score ?? 0) >= 70 ? "text-emerald-400" : (ai.health_score ?? 0) >= 50 ? "text-amber-400" : "text-red-400";
  return (
    <div className="bg-card border border-border rounded-xl p-4">
      <SectionHeader icon={Brain} title="AI Summary" />
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-3">
        <KpiCard label="AI Health" value={(ai.health_score ?? 0).toFixed(1)} unit="/100" color={healthColor} />
        <KpiCard label="Accuracy" value={(ai.prediction_accuracy ?? 0).toFixed(1)} unit="%" />
        <KpiCard label="Confidence" value={(ai.avg_confidence ?? 0).toFixed(1)} unit="%" />
        <KpiCard label="Signals" value={ai.total_signals ?? 0} />
      </div>
      <div className="flex flex-wrap gap-3 text-xs text-muted-foreground">
        <span>Calibration: <b className="text-foreground">{ai.calibration_quality ?? "N/A"}</b></span>
        <span>Trend: <b className="text-foreground">{ai.trend_direction ?? "Stable"}</b> <Trend dir={ai.trend_direction} /></span>
        <span>F1 Score: <b className="text-foreground">{(ai.f1_score ?? 0).toFixed(3)}</b></span>
      </div>
    </div>
  );
}

// ── Section 6 — Risk Summary ───────────────────────────────────────────────────
function RiskSection({ risk }: { risk: any }) {
  if (!risk) return null;
  const riskColor = (risk.risk_score ?? 0) >= 65 ? "text-emerald-400" : (risk.risk_score ?? 0) >= 45 ? "text-amber-400" : "text-red-400";
  return (
    <div className="bg-card border border-border rounded-xl p-4">
      <SectionHeader icon={Shield} title="Risk Summary"
        sub={`Grade ${risk.grade ?? "D"}`} />
      <div className="flex items-center gap-4 mb-4">
        <div>
          <p className="text-xs text-muted-foreground mb-1">Risk Score</p>
          <p className={`text-3xl font-bold ${riskColor}`}>{(risk.risk_score ?? 0).toFixed(1)}</p>
        </div>
        <div className="flex-1">
          <ScoreBar score={risk.risk_score ?? 0} />
          <div className="flex justify-between text-xs text-muted-foreground mt-1">
            <span>0</span><span>100</span>
          </div>
        </div>
      </div>
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 text-xs">
        {[
          ["Portfolio Heat", risk.portfolio_heat],
          ["Tail Risk",      risk.tail_risk],
          ["Exposure",       risk.exposure],
          ["Correlation",    risk.correlation],
        ].map(([label, val]) => (
          <div key={label} className="bg-muted/30 rounded p-2">
            <p className="text-muted-foreground">{label}</p>
            <p className="font-semibold">{(val as number)?.toFixed(1) ?? "—"}</p>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Section 7 — System Health ──────────────────────────────────────────────────
function SystemHealthSection({ systemHealth }: { systemHealth: any }) {
  if (!systemHealth) return null;
  const { modules = [], platform_score = 0, platform_grade: pg = "D", platform_status: ps = "UNKNOWN" } = systemHealth;
  return (
    <div className="bg-card border border-border rounded-xl p-4">
      <SectionHeader icon={Monitor} title="System Health" />
      <div className="flex items-center gap-4 mb-4">
        <div>
          <p className="text-xs text-muted-foreground mb-1">Platform Health</p>
          <GradeChip grade={pg} score={platform_score} />
        </div>
        <Badge variant="outline" className="gap-1">
          <StatusDot status={ps} /> {ps}
        </Badge>
        <div className="flex-1"><ScoreBar score={platform_score} /></div>
      </div>
      <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
        {modules.map((mod: any) => (
          <div key={mod.id} className="flex items-center justify-between bg-muted/30 rounded p-2.5">
            <span className="text-xs text-muted-foreground">{mod.label}</span>
            <div className="flex items-center gap-1.5">
              <span className="text-xs font-medium">{mod.score?.toFixed(0)}</span>
              <StatusDot status={mod.available ? (mod.score >= 70 ? "HEALTHY" : "DEGRADED") : "UNKNOWN"} />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Section 8 — Market Intelligence ───────────────────────────────────────────
function MarketIntelSection({ mi }: { mi: any }) {
  if (!mi) return null;
  return (
    <div className="bg-card border border-border rounded-xl p-4">
      <SectionHeader icon={TrendingUp} title="Market Intelligence" />
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <KpiCard label="Market Health" value={(mi.market_health_score ?? 0).toFixed(1)} unit="/100" />
        <KpiCard label="Grade" value={mi.grade ?? "—"} />
        <KpiCard label="Trend" value={mi.trend ?? "—"} />
        <KpiCard label="Top Pick" value={mi.top_opportunity ?? "—"} />
      </div>
      {mi.overall_outlook && (
        <p className="text-xs text-muted-foreground mt-3 italic">{mi.overall_outlook}</p>
      )}
    </div>
  );
}

// ── Section 9 — Alert Centre ───────────────────────────────────────────────────
function AlertCentreSection() {
  const { data: d, isLoading } = useQuery({ ...q("alerts"), staleTime: 10_000 });
  if (isLoading) return <div className="bg-card border border-border rounded-xl p-4 animate-pulse h-32" />;
  const r = d as any;
  if (!r?.available) return null;
  const alerts: any[] = (r?.alerts ?? []).slice(0, 8);
  const severityColor: Record<string, string> = {
    CRITICAL: "text-red-300 border-red-500/30 bg-red-500/10",
    WARNING:  "text-amber-300 border-amber-500/30 bg-amber-500/10",
    INFO:     "text-slate-300 border-slate-500/30 bg-slate-500/10",
  };
  return (
    <div className="bg-card border border-border rounded-xl p-4">
      <SectionHeader icon={AlertTriangle} title="Alert Centre"
        sub={`${r.critical_count ?? 0} critical · ${r.warning_count ?? 0} warnings`} />
      {alerts.length === 0 ? (
        <div className="flex items-center gap-2 text-sm text-emerald-400">
          <CheckCircle2 className="w-4 h-4" /> No active alerts
        </div>
      ) : (
        <div className="space-y-2">
          {alerts.map((a: any, i: number) => (
            <div key={i} className={`flex items-start gap-3 p-2.5 rounded border text-xs ${severityColor[a.severity] ?? severityColor.INFO}`}>
              <span className="font-bold flex-shrink-0 mt-0.5 uppercase">{a.severity}</span>
              <div className="min-w-0">
                <p className="font-medium">{a.title}</p>
                {a.body && <p className="opacity-70 mt-0.5 truncate">{a.body}</p>}
              </div>
              <span className="ml-auto text-muted-foreground flex-shrink-0">{a.category}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ── Section 10 — AI Daily Briefing ────────────────────────────────────────────
function BriefingSection() {
  const { data: d, isLoading } = useQuery({ ...q("briefing"), staleTime: 60_000, refetchInterval: 60_000 });
  if (isLoading) return <div className="bg-card border border-border rounded-xl p-4 animate-pulse h-28" />;
  const r = d as any;
  if (!r?.available) return null;
  return (
    <div className="bg-card border border-border rounded-xl p-4">
      <SectionHeader icon={Brain} title="AI Daily Briefing"
        sub={r.generated_at?.slice(0, 16)?.replace("T", " ")} />
      <div className="space-y-2">
        {(r.briefing_lines ?? []).map((line: string, i: number) => (
          <p key={i} className="text-sm text-muted-foreground leading-relaxed">
            {i === 0 ? <b className="text-foreground">📊 </b> : <span className="text-teal-500">› </span>}
            {line}
          </p>
        ))}
      </div>
    </div>
  );
}

// ── Section 11 — Quick Actions ─────────────────────────────────────────────────
function QuickActionsSection({ actions }: { actions: any[] }) {
  const iconMap: Record<string, any> = {
    TrendingUp: TrendingUp, BarChart2: BarChart2, Shield: Shield,
    Brain: Brain, FlaskConical: FlaskConical, Monitor: Monitor,
    Zap: Zap, Rocket: Rocket,
  };
  if (!actions?.length) return null;
  return (
    <div className="bg-card border border-border rounded-xl p-4">
      <SectionHeader icon={Zap} title="Quick Actions" />
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
        {actions.map((a: any) => {
          const Icon = iconMap[a.icon] ?? Activity;
          return (
            <a key={a.href} href={a.href}
              className="flex items-center gap-2 p-3 rounded-lg bg-muted/30 hover:bg-muted/60 text-sm font-medium transition-colors group">
              <Icon className="w-4 h-4 text-teal-400 group-hover:text-teal-300" />
              <span className="truncate">{a.label}</span>
            </a>
          );
        })}
      </div>
    </div>
  );
}

// ── Section 12 — Session Timeline ─────────────────────────────────────────────
function TimelineSection() {
  const { data: d, isLoading } = useQuery({ ...q("timeline") });
  if (isLoading) return <div className="bg-card border border-border rounded-xl p-4 animate-pulse h-40" />;
  const r = d as any;
  if (!r?.available) return null;
  const events: any[] = (r?.events ?? []).slice(0, 12);
  const statusColor: Record<string, string> = {
    success: "bg-emerald-500", warning: "bg-amber-400",
    critical: "bg-red-500", info: "bg-blue-400",
  };
  return (
    <div className="bg-card border border-border rounded-xl p-4">
      <SectionHeader icon={Clock} title="Session Timeline"
        sub={`${r.event_count ?? 0} events`} />
      <div className="relative pl-4">
        <div className="absolute left-0 top-0 bottom-0 w-px bg-border" />
        <div className="space-y-3">
          {events.map((ev: any, i: number) => (
            <div key={i} className="relative flex items-start gap-3">
              <div className={`absolute -left-4 top-1.5 w-2 h-2 rounded-full ${statusColor[ev.status] ?? "bg-gray-400"} -translate-x-[3px]`} />
              <span className="text-xs text-muted-foreground w-11 flex-shrink-0 font-mono">{ev.time}</span>
              <div>
                <span className="text-xs font-medium">{ev.event}</span>
                <span className="text-xs text-muted-foreground ml-2">[{ev.category}]</span>
              </div>
            </div>
          ))}
          {events.length === 0 && (
            <p className="text-xs text-muted-foreground">No session events recorded yet.</p>
          )}
        </div>
      </div>
    </div>
  );
}

// ── Section 13 — Watchlist ────────────────────────────────────────────────────
function WatchlistSection({ watchlist }: { watchlist: any }) {
  if (!watchlist) return null;
  const topPicks: any[]  = watchlist.top_ai_picks    ?? [];
  const momentum: any[]  = watchlist.momentum         ?? [];
  const breakouts: any[] = watchlist.breakouts        ?? [];
  if (!topPicks.length && !momentum.length && !breakouts.length) return null;
  const renderList = (items: any[], nameKey = "symbol") =>
    items.slice(0, 5).map((item: any, i: number) => (
      <div key={i} className="flex items-center justify-between py-1.5 border-b border-border/30 last:border-0">
        <span className="text-sm font-medium">{item[nameKey] ?? item.symbol ?? "—"}</span>
        {item.opportunity_score != null && (
          <span className="text-xs text-teal-400">{item.opportunity_score?.toFixed(0)}</span>
        )}
      </div>
    ));
  return (
    <div className="bg-card border border-border rounded-xl p-4">
      <SectionHeader icon={TrendingUp} title="Watchlist" sub={`${watchlist.total_symbols ?? 0} symbols`} />
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        {topPicks.length > 0 && (
          <div>
            <p className="text-xs font-semibold text-teal-400 mb-2">Top AI Picks</p>
            {renderList(topPicks)}
          </div>
        )}
        {momentum.length > 0 && (
          <div>
            <p className="text-xs font-semibold text-blue-400 mb-2">Momentum</p>
            {renderList(momentum)}
          </div>
        )}
        {breakouts.length > 0 && (
          <div>
            <p className="text-xs font-semibold text-emerald-400 mb-2">Breakouts</p>
            {renderList(breakouts)}
          </div>
        )}
      </div>
    </div>
  );
}

// ── Export button ──────────────────────────────────────────────────────────────
function ExportButton() {
  const [busy, setBusy] = useState(false);
  const base = import.meta.env.BASE_URL.replace(/\/$/, "");
  async function dl(fmt: "json" | "csv") {
    setBusy(true);
    try {
      const resp = await fetch(`${base}/api/command-center/export?format=${fmt}`);
      const blob = await resp.blob();
      const url  = URL.createObjectURL(blob);
      const a    = document.createElement("a");
      a.href = url; a.download = `command_center_export.${fmt}`; a.click();
      URL.revokeObjectURL(url);
    } finally { setBusy(false); }
  }
  return (
    <div className="flex gap-2">
      <button onClick={() => dl("json")} disabled={busy}
        className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-teal-600 hover:bg-teal-500 text-white text-xs font-medium disabled:opacity-50 transition-colors">
        <Download className="w-3 h-3" /> JSON
      </button>
      <button onClick={() => dl("csv")} disabled={busy}
        className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-muted hover:bg-muted/70 text-xs font-medium disabled:opacity-50 transition-colors">
        <Download className="w-3 h-3" /> CSV
      </button>
    </div>
  );
}

// ── Main page ──────────────────────────────────────────────────────────────────
export default function CommandCenter() {
  const { data: d, isLoading, error } = useQuery({ ...q("summary") });
  const r = d as any;
  const isDisabled = r?.available === false && !isLoading;

  return (
    <div className="max-w-7xl mx-auto px-4 py-6 space-y-4">

      {/* Page header */}
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div className="flex items-center gap-3">
          <div className="p-2 rounded-xl bg-teal-500/10 border border-teal-500/20">
            <svg className="w-6 h-6 text-teal-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5}
                d="M3 9.5L12 4l9 5.5V19a1 1 0 01-1 1H4a1 1 0 01-1-1V9.5z" />
            </svg>
          </div>
          <div>
            <h1 className="text-xl font-bold">Unified Command Centre</h1>
            <p className="text-xs text-muted-foreground">
              Phase 9.1 · Real-time platform snapshot · Read-only · Advisory-only
            </p>
          </div>
        </div>
        <ExportButton />
      </div>

      {/* Disabled banner */}
      {isDisabled && <DisabledBanner />}

      {/* Loading skeleton */}
      {isLoading && (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {[...Array(6)].map((_, i) => (
            <div key={i} className="bg-card border border-border rounded-xl p-4 animate-pulse h-40" />
          ))}
        </div>
      )}

      {/* Error state */}
      {error && !isLoading && (
        <Alert className="border-red-500/40 bg-red-500/5">
          <AlertTriangle className="w-4 h-4 text-red-400" />
          <AlertDescription className="text-sm text-red-200">
            Failed to load Command Centre data. Ensure COMMAND_CENTER_ENABLED=true and the API server is running.
          </AlertDescription>
        </Alert>
      )}

      {/* Content */}
      {!isLoading && r && (
        <>
          {/* Platform header bar */}
          <PlatformHeader summary={r} />

          {/* Primary 2-col grid */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            <MarketOverviewSection market={r.market} />
            <PortfolioSection portfolio={r.portfolio} />
            <TradingSection trading={r.trading} />
            <AiSection ai={r.ai} />
            <RiskSection risk={r.risk} />
            <MarketIntelSection mi={r.market_intelligence} />
          </div>

          {/* Analysis Layer (Phase 10B) — full width */}
          <AnalysisLayerCard />

          {/* System Health — full width */}
          <SystemHealthSection systemHealth={r.system_health} />

          {/* Watchlist */}
          <WatchlistSection watchlist={r.watchlist} />

          {/* Alerts + Briefing side-by-side */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            <AlertCentreSection />
            <BriefingSection />
          </div>

          {/* Quick Actions + Timeline */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            <QuickActionsSection actions={r.quick_actions ?? []} />
            <TimelineSection />
          </div>

          {/* Advisory footer */}
          <p className="text-xs text-center text-muted-foreground pb-2">
            READ-ONLY · ADVISORY-ONLY · No orders placed · No calculations performed · Snapshot data only
          </p>
        </>
      )}
    </div>
  );
}

// ── Analysis Layer Card (Phase 10B) ───────────────────────────────────────────

const RISK_CHIP: Record<string, string> = {
  LOW: "bg-emerald-600", MODERATE: "bg-amber-500",
  HIGH: "bg-orange-600", CRITICAL: "bg-red-700", UNKNOWN: "bg-gray-600",
};

function AnalysisLayerCard() {
  const { data, isLoading } = useQuery({
    queryKey:  ["cc", "analysis-summary"],
    queryFn:   () => apiJson("analysis-agents/summary"),
    refetchInterval: 45_000,
    retry: 1,
    staleTime: 20_000,
  });

  if (isLoading) {
    return (
      <div className="bg-card border border-border rounded-xl p-4">
        <SectionHeader icon={Bot} title="Analysis Layer" />
        <div className="animate-pulse h-16 bg-muted rounded-lg" />
      </div>
    );
  }

  if (!data?.available) {
    return (
      <div className="bg-card border border-border rounded-xl p-4">
        <SectionHeader icon={Bot} title="Analysis Layer" />
        <p className="text-xs text-muted-foreground">Analysis agents not yet initialised.</p>
      </div>
    );
  }

  const riskLevel: string = (data.risk_level as string) ?? "UNKNOWN";
  const regime: string    = (data.market_regime as string) ?? "—";
  const momentum: string  = (data.momentum_state as string) ?? "—";
  const topStrategy: string = (data.top_strategy as string) ?? "—";
  const highestScore: number  = (data.highest_score as number) ?? 0;
  const breakoutsFound: number = (data.breakouts_found as number) ?? 0;
  const riskScore: number = (data.risk_score as number) ?? 0;
  const symbolsMonitored: number = (data.symbols_monitored as number) ?? 0;

  return (
    <div className="bg-card border border-border rounded-xl p-4">
      <SectionHeader icon={Bot} title="Phase 10B — Analysis Layer"
        sub={`${symbolsMonitored} symbols monitored`} />
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
        <KpiCard label="Market Regime"  value={regime}       color="text-teal-400" />
        <KpiCard label="Momentum"       value={momentum}     color="text-blue-400" />
        <KpiCard label="Breakouts"      value={breakoutsFound}  color="text-emerald-400" />
        <KpiCard label="Top Strategy"   value={topStrategy}  color="text-violet-400" />
        <KpiCard label="Best Score"     value={`${highestScore.toFixed(0)}/100`} />
        <div className="bg-card rounded-xl border border-border p-3 flex flex-col gap-1">
          <p className="text-xs text-muted-foreground">Portfolio Risk</p>
          <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-white text-xs font-semibold self-start ${RISK_CHIP[riskLevel] ?? "bg-gray-600"}`}>
            {riskLevel}
          </span>
          <p className="text-xs text-muted-foreground">Score {riskScore.toFixed(0)}/100</p>
        </div>
      </div>
      <p className="text-xs text-muted-foreground mt-3">
        READ-ONLY · ADVISORY-ONLY · 4 agents · 6 strategies · 9 risk dimensions · 12 event types
      </p>
    </div>
  );
}
