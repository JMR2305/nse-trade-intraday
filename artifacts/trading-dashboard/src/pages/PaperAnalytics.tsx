/**
 * PaperAnalytics.tsx — Phase 8.2
 * Advanced Paper Trading Analytics Dashboard
 * READ-ONLY · ADVISORY-ONLY
 */
import { useState } from "react";
import { useQuery }  from "@tanstack/react-query";
import {
  BarChart3, TrendingUp, TrendingDown, Minus, Activity, Shield,
  Target, Clock, Layers, Globe, Zap, BookOpen, Brain, Download,
  RefreshCw, AlertTriangle, CheckCircle2, Info, Award, PieChart,
  FileText,
} from "lucide-react";
import { apiJson } from "@/lib/api";

// ── Types ──────────────────────────────────────────────────────────────────────
type Grade = "A+" | "A" | "B" | "C" | "D" | string;

// ── Colour helpers ────────────────────────────────────────────────────────────
function gradeColor(g: Grade) {
  if (g === "A+") return "text-emerald-400";
  if (g === "A")  return "text-teal-400";
  if (g === "B")  return "text-sky-400";
  if (g === "C")  return "text-amber-400";
  return "text-rose-400";
}
function pnlColor(v: number) { return v >= 0 ? "text-emerald-400" : "text-rose-400"; }

// ── Formatters ────────────────────────────────────────────────────────────────
function fmt(v: unknown, dp = 2): string {
  if (v == null) return "—";
  const n = Number(v);
  if (isNaN(n)) return String(v);
  return n.toLocaleString("en-IN", { maximumFractionDigits: dp, minimumFractionDigits: dp });
}
function fmtPct(v: unknown, dp = 2): string { return v == null ? "—" : fmt(v, dp) + "%"; }
function fmtRs(v: unknown): string { return v == null ? "—" : "₹" + fmt(v, 0); }
function fmtDays(n: number): string {
  if (n < 0)  return "In recovery";
  if (n === 0) return "Fully recovered";
  return `${n} day${n === 1 ? "" : "s"}`;
}

// ── SVG sparkline (mini line chart) ──────────────────────────────────────────
function SparkLine({
  data,
  color = "#14b8a6",
  fillColor,
  height = 56,
  width = 200,
  showArea = false,
}: {
  data: number[];
  color?: string;
  fillColor?: string;
  height?: number;
  width?: number;
  showArea?: boolean;
}) {
  if (!data || data.length < 2) {
    return (
      <div style={{ width, height }} className="flex items-center justify-center">
        <span className="text-xs text-slate-600">No data</span>
      </div>
    );
  }
  const min  = Math.min(...data);
  const max  = Math.max(...data);
  const rng  = max - min || 1;
  const pad  = 4;
  const w    = width - pad * 2;
  const h    = height - pad * 2;
  const pts  = data.map((v, i) => {
    const x = pad + (i / (data.length - 1)) * w;
    const y = pad + h - ((v - min) / rng) * h;
    return `${x},${y}`;
  });
  const polyline = pts.join(" ");
  const fill = fillColor ?? (showArea ? `${color}22` : "none");
  const areaPath = showArea
    ? `M${pts[0]} L${pts.join(" L")} L${pad + w},${pad + h} L${pad},${pad + h} Z`
    : "";

  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`}>
      {showArea && areaPath && <path d={areaPath} fill={fill} />}
      <polyline
        points={polyline}
        fill="none"
        stroke={color}
        strokeWidth="1.5"
        strokeLinejoin="round"
        strokeLinecap="round"
      />
      {/* Last point dot */}
      {(() => {
        const [x, y] = pts[pts.length - 1].split(",").map(Number);
        return <circle cx={x} cy={y} r="2.5" fill={color} />;
      })()}
    </svg>
  );
}

// ── Score ring ────────────────────────────────────────────────────────────────
function ScoreRing({ score, grade }: { score: number; grade: string }) {
  const r = 42; const circ = 2 * Math.PI * r;
  const dash = ((Math.min(100, Math.max(0, score)) / 100) * circ).toFixed(1);
  const color = score >= 80 ? "#10b981" : score >= 60 ? "#f59e0b" : "#ef4444";
  return (
    <svg viewBox="0 0 100 100" className="w-24 h-24">
      <circle cx="50" cy="50" r={r} fill="none" stroke="#1e293b" strokeWidth="10" />
      <circle cx="50" cy="50" r={r} fill="none" stroke={color} strokeWidth="10"
        strokeDasharray={`${dash} ${circ.toFixed(1)}`}
        strokeLinecap="round" transform="rotate(-90 50 50)" />
      <text x="50" y="47" textAnchor="middle" fill={color} fontSize="18" fontWeight="700">
        {score.toFixed(0)}
      </text>
      <text x="50" y="63" textAnchor="middle" fill="#94a3b8" fontSize="12">{grade}</text>
    </svg>
  );
}

// ── Shared UI atoms ───────────────────────────────────────────────────────────
function KpiCard({ label, value, sub }: { label: string; value: React.ReactNode; sub?: string }) {
  return (
    <div className="bg-slate-800/60 border border-slate-700/50 rounded-xl p-4">
      <p className="text-xs text-slate-500 mb-1">{label}</p>
      <p className="text-lg font-semibold text-slate-100 leading-tight">{value}</p>
      {sub && <p className="text-xs text-slate-500 mt-0.5">{sub}</p>}
    </div>
  );
}
function SectionHeader({ icon, title, sub }: { icon: React.ReactNode; title: string; sub?: string }) {
  return (
    <div className="flex items-center gap-2 mb-4">
      <div className="p-2 bg-teal-500/10 rounded-lg">{icon}</div>
      <div>
        <h2 className="text-base font-semibold text-slate-100">{title}</h2>
        {sub && <p className="text-xs text-slate-500">{sub}</p>}
      </div>
    </div>
  );
}
function Badge({ label, cls }: { label: string; cls?: string }) {
  return (
    <span className={`text-xs px-2 py-0.5 rounded-full border font-medium ${cls ?? "bg-slate-700/40 text-slate-400 border-slate-700/50"}`}>
      {label}
    </span>
  );
}
function InfoCard({ title, icon, children }: { title: string; icon?: React.ReactNode; children: React.ReactNode }) {
  return (
    <div className="bg-slate-800/40 border border-slate-700/40 rounded-xl p-4">
      {(title || icon) && (
        <div className="flex items-center gap-1.5 mb-3 text-slate-400 text-xs font-medium uppercase tracking-wide">
          {icon}{title}
        </div>
      )}
      {children}
    </div>
  );
}
function DisabledView({ msg }: { msg?: string }) {
  return (
    <div className="flex flex-col items-center justify-center py-20 text-center gap-3">
      <AlertTriangle className="w-10 h-10 text-slate-600 mx-auto mb-3" />
      <p className="text-slate-400 font-medium">Analytics Disabled</p>
      <p className="text-slate-500 text-sm max-w-xs">{msg ?? "Set PAPER_ANALYTICS_ENABLED=true to enable."}</p>
    </div>
  );
}
function Loading() {
  return (
    <div className="flex items-center justify-center py-20">
      <RefreshCw className="w-6 h-6 text-slate-600 animate-spin" />
    </div>
  );
}
function NoData({ msg }: { msg?: string }) {
  return <p className="text-slate-500 text-sm py-4 text-center">{msg ?? "No data yet — complete some paper trades first."}</p>;
}
function ChartCard({ title, icon, children }: { title: string; icon?: React.ReactNode; children: React.ReactNode }) {
  return (
    <div className="bg-slate-800/40 border border-slate-700/40 rounded-xl p-4">
      <div className="flex items-center gap-1.5 mb-3 text-slate-400 text-xs font-medium uppercase tracking-wide">
        {icon}{title}
      </div>
      {children}
    </div>
  );
}

// ── Equity mini-chart (full-width responsive) ─────────────────────────────────
function EquityCurveChart({
  points,
  color = "#14b8a6",
  label = "Equity",
  height = 80,
}: {
  points: { equity?: number; value?: number; timestamp?: string }[];
  color?: string;
  label?: string;
  height?: number;
}) {
  const vals = points.map(p => p.equity ?? p.value ?? 0).filter(v => isFinite(v));
  if (vals.length < 2) return <NoData />;
  return (
    <div>
      <div className="flex justify-between text-xs text-slate-500 mb-1">
        <span>{label}</span>
        <span className={vals[vals.length - 1] >= vals[0] ? "text-emerald-400" : "text-rose-400"}>
          {fmtRs(vals[vals.length - 1])}
        </span>
      </div>
      <div className="w-full" style={{ height }}>
        <svg width="100%" height={height} viewBox={`0 0 400 ${height}`} preserveAspectRatio="none">
          {(() => {
            const min = Math.min(...vals);
            const max = Math.max(...vals);
            const rng = max - min || 1;
            const pad = 4;
            const w = 400 - pad * 2;
            const h = height - pad * 2;
            const ptStr = vals.map((v, i) => {
              const x = pad + (i / (vals.length - 1)) * w;
              const y = pad + h - ((v - min) / rng) * h;
              return `${x},${y}`;
            }).join(" ");
            const [lastX, lastY] = ptStr.split(" ").pop()!.split(",").map(Number);
            const areaPath = `M${pad},${pad + h} L${ptStr.split(" ").map(p => `${p}`).join(" L")} L${pad + w},${pad + h} Z`;
            return (
              <>
                <path d={areaPath} fill={`${color}18`} />
                <polyline points={ptStr} fill="none" stroke={color} strokeWidth="1.5" strokeLinejoin="round" />
                <circle cx={lastX} cy={lastY} r="3" fill={color} />
              </>
            );
          })()}
        </svg>
      </div>
    </div>
  );
}

// ── Drawdown mini-chart ───────────────────────────────────────────────────────
function DrawdownChart({ points, height = 60 }: { points: { drawdown_pct: number }[]; height?: number }) {
  const vals = points.map(p => -(p.drawdown_pct ?? 0)).filter(v => isFinite(v));
  if (vals.length < 2) return <NoData />;
  return (
    <div className="w-full" style={{ height }}>
      <svg width="100%" height={height} viewBox={`0 0 400 ${height}`} preserveAspectRatio="none">
        {(() => {
          const min = Math.min(...vals);
          const max = Math.max(...vals);
          const rng = max - min || 1;
          const pad = 2;
          const w = 400 - pad * 2;
          const h = height - pad * 2;
          const ptStr = vals.map((v, i) => {
            const x = pad + (i / (vals.length - 1)) * w;
            const y = pad + h - ((v - min) / rng) * h;
            return `${x},${y}`;
          }).join(" ");
          const areaPath = `M${pad},${pad + h} L${ptStr.split(" ").map(p => p).join(" L")} L${pad + w},${pad + h} Z`;
          return (
            <>
              <path d={areaPath} fill="#ef444428" />
              <polyline points={ptStr} fill="none" stroke="#ef4444" strokeWidth="1.5" strokeLinejoin="round" />
            </>
          );
        })()}
      </svg>
    </div>
  );
}

// ── Tabs ──────────────────────────────────────────────────────────────────────
const TABS = [
  { id: "overview",    label: "Overview",    icon: <BarChart3 className="w-4 h-4" /> },
  { id: "trades",      label: "Trades",      icon: <Activity  className="w-4 h-4" /> },
  { id: "strategies",  label: "Strategies",  icon: <Layers    className="w-4 h-4" /> },
  { id: "risk",        label: "Risk",        icon: <Shield    className="w-4 h-4" /> },
  { id: "portfolio",   label: "Portfolio",   icon: <PieChart  className="w-4 h-4" /> },
  { id: "time",        label: "Time",        icon: <Clock     className="w-4 h-4" /> },
  { id: "sectors",     label: "Sectors",     icon: <Globe     className="w-4 h-4" /> },
  { id: "preopen",     label: "Pre-Open",    icon: <Zap       className="w-4 h-4" /> },
  { id: "execution",   label: "Execution",   icon: <Target    className="w-4 h-4" /> },
  { id: "learning",    label: "Learning",    icon: <BookOpen  className="w-4 h-4" /> },
  { id: "ai",          label: "AI Insights", icon: <Brain     className="w-4 h-4" /> },
  { id: "export",      label: "Export",      icon: <Download  className="w-4 h-4" /> },
] as const;

type TabId = (typeof TABS)[number]["id"];

// ── Main Component ────────────────────────────────────────────────────────────
export default function PaperAnalytics() {
  const [tab, setTab] = useState<TabId>("overview");

  const POLL = 60_000;

  const summary    = useQuery({ queryKey: ["pa-summary"],    queryFn: () => apiJson("paper-analytics/summary"),    refetchInterval: POLL });
  const trades     = useQuery({ queryKey: ["pa-trades"],     queryFn: () => apiJson("paper-analytics/trades"),     refetchInterval: POLL, enabled: tab === "trades" || tab === "overview" });
  const strategies = useQuery({ queryKey: ["pa-strategies"], queryFn: () => apiJson("paper-analytics/strategies"), refetchInterval: POLL, enabled: tab === "strategies" });
  const risk       = useQuery({ queryKey: ["pa-risk"],       queryFn: () => apiJson("paper-analytics/risk"),       refetchInterval: POLL, enabled: tab === "risk" });
  const portfolio  = useQuery({ queryKey: ["pa-portfolio"],  queryFn: () => apiJson("paper-analytics/portfolio"),  refetchInterval: POLL, enabled: tab === "portfolio" });
  const learning   = useQuery({ queryKey: ["pa-learning"],   queryFn: () => apiJson("paper-analytics/learning"),   refetchInterval: POLL, enabled: tab === "learning" || tab === "ai" || tab === "time" || tab === "sectors" || tab === "execution" });
  const preopen    = useQuery({ queryKey: ["pa-preopen"],    queryFn: () => apiJson("paper-analytics/preopen"),    refetchInterval: POLL, enabled: tab === "preopen" });

  const S  = summary.data    as any;
  const T  = trades.data     as any;
  const St = strategies.data as any;
  const R  = risk.data       as any;
  const Po = portfolio.data  as any;
  const L  = learning.data   as any;
  const Pr = preopen.data    as any;

  const isDisabled = S?.status === "DISABLED";

  // ── Overview ─────────────────────────────────────────────────────────────────
  function renderOverview() {
    if (summary.isLoading) return <Loading />;
    if (isDisabled) return <DisabledView msg={S?.message} />;
    if (!S) return <NoData />;

    // Mini equity spark from trades data
    const dailyPts: any[] = T?.equity_curves?.daily ?? [];
    const equityVals = dailyPts.map((p: any) => p.equity ?? p.value ?? 0).filter(Number.isFinite);

    return (
      <div className="space-y-6">
        {/* Score header */}
        <div className="bg-gradient-to-br from-slate-800/80 to-slate-900/80 border border-slate-700/50 rounded-2xl p-6 flex flex-col sm:flex-row items-center gap-6">
          <ScoreRing score={S.analytics_score ?? 0} grade={S.grade ?? "—"} />
          <div className="flex-1 w-full">
            <div className="flex items-center gap-2 mb-1 flex-wrap">
              <h2 className="text-xl font-bold text-slate-100">Analytics Score</h2>
              <span className={`text-2xl font-bold ${gradeColor(S.grade)}`}>{S.grade}</span>
              <Badge label="ADVISORY ONLY" cls="bg-amber-500/10 text-amber-400 border-amber-500/30 text-xs" />
            </div>
            <p className="text-slate-400 text-sm mb-4">Paper Trading · Advisory Only · No live orders</p>
            {equityVals.length >= 2 && (
              <div className="mb-4">
                <EquityCurveChart points={dailyPts} color="#14b8a6" label="Portfolio equity" height={60} />
              </div>
            )}
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
              <KpiCard label="Total Trades"  value={S.total_trades ?? 0} />
              <KpiCard label="Win Rate"      value={fmtPct(S.win_rate)} />
              <KpiCard label="Profit Factor" value={fmt(S.profit_factor)} />
              <KpiCard label="Expectancy"    value={<span className={pnlColor(S.expectancy ?? 0)}>{fmtRs(S.expectancy)}</span>} />
            </div>
          </div>
        </div>

        {/* KPI row */}
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          <KpiCard label="Total PnL"      value={<span className={pnlColor(S.total_pnl ?? 0)}>{fmtRs(S.total_pnl)}</span>} />
          <KpiCard label="Sharpe Ratio"   value={fmt(S.sharpe_ratio)} />
          <KpiCard label="Max Drawdown"   value={<span className="text-rose-400">{fmtPct(S.max_drawdown_pct)}</span>} />
          <KpiCard label="Volatility"     value={fmtPct(S.volatility_pct)} />
        </div>

        {/* Insights row */}
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
          <InfoCard title="Best Strategy"  icon={<Award className="w-3.5 h-3.5" />}>
            <p className="text-slate-100 font-semibold text-lg">{S.best_strategy ?? "N/A"}</p>
          </InfoCard>
          <InfoCard title="Best Sector"    icon={<Globe className="w-3.5 h-3.5" />}>
            <p className="text-slate-100 font-semibold text-lg">{S.best_sector ?? "N/A"}</p>
          </InfoCard>
          <InfoCard title="Best Condition" icon={<TrendingUp className="w-3.5 h-3.5" />}>
            <p className="text-slate-100 font-semibold text-lg">{S.best_market_condition ?? "N/A"}</p>
          </InfoCard>
        </div>
      </div>
    );
  }

  // ── Trades ───────────────────────────────────────────────────────────────────
  function renderTrades() {
    if (trades.isLoading) return <Loading />;
    if (!T?.available) return <DisabledView msg={T?.message} />;

    const dailyPts:   any[] = T.equity_curves?.daily   ?? [];
    const weeklyPts:  any[] = T.equity_curves?.weekly  ?? [];
    const monthlyPts: any[] = T.equity_curves?.monthly ?? [];
    const ddCurve:    any[] = T.drawdown_curve          ?? [];
    const rollingRet: any[] = T.rolling_returns         ?? [];

    return (
      <div className="space-y-5">
        <SectionHeader icon={<Activity className="w-5 h-5 text-teal-400" />} title="Trade Analytics" sub="All completed paper trades" />

        {/* Core KPIs */}
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          <KpiCard label="Total Trades"  value={T.total_trades ?? 0} />
          <KpiCard label="Winning"       value={<span className="text-emerald-400">{T.winning_trades ?? 0}</span>} />
          <KpiCard label="Losing"        value={<span className="text-rose-400">{T.losing_trades ?? 0}</span>} />
          <KpiCard label="Win Rate"      value={fmtPct(T.win_rate)} />
          <KpiCard label="Avg Winner"    value={<span className="text-emerald-400">{fmtRs(T.avg_winner)}</span>} />
          <KpiCard label="Avg Loser"     value={<span className="text-rose-400">{fmtRs(T.avg_loser)}</span>} />
          <KpiCard label="Profit Factor" value={fmt(T.profit_factor)} />
          <KpiCard label="Expectancy"    value={<span className={pnlColor(T.expectancy ?? 0)}>{fmtRs(T.expectancy)}</span>} />
          <KpiCard label="Avg Hold"      value={T.avg_holding_human ?? "—"} />
          <KpiCard label="Win Streak"    value={<span className="text-emerald-400">{T.longest_win_streak ?? 0}</span>} />
          <KpiCard label="Loss Streak"   value={<span className="text-rose-400">{T.longest_loss_streak ?? 0}</span>} />
          <KpiCard label="Total PnL"     value={<span className={pnlColor(T.total_pnl ?? 0)}>{fmtRs(T.total_pnl)}</span>} />
        </div>

        {/* Equity Curves */}
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
          <ChartCard title="Daily Equity" icon={<TrendingUp className="w-3.5 h-3.5 text-teal-400" />}>
            {dailyPts.length >= 2
              ? <EquityCurveChart points={dailyPts} color="#14b8a6" height={70} />
              : <NoData />}
          </ChartCard>
          <ChartCard title="Weekly Equity" icon={<TrendingUp className="w-3.5 h-3.5 text-sky-400" />}>
            {weeklyPts.length >= 2
              ? <EquityCurveChart points={weeklyPts} color="#38bdf8" height={70} />
              : <NoData />}
          </ChartCard>
          <ChartCard title="Monthly Equity" icon={<TrendingUp className="w-3.5 h-3.5 text-violet-400" />}>
            {monthlyPts.length >= 2
              ? <EquityCurveChart points={monthlyPts} color="#a78bfa" height={70} />
              : <NoData />}
          </ChartCard>
        </div>

        {/* Drawdown + Recovery Curves */}
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          {ddCurve.length >= 2 && (
            <ChartCard title="Drawdown Curve" icon={<Shield className="w-3.5 h-3.5 text-rose-400" />}>
              <div className="flex justify-between text-xs text-slate-500 mb-1">
                <span>Drawdown % over time</span>
                <span className="text-rose-400">{fmtPct(T.max_drawdown_pct)} max</span>
              </div>
              <DrawdownChart points={ddCurve} height={64} />
            </ChartCard>
          )}
          {(T.recovery_curve ?? []).length >= 2 && (
            <ChartCard title="Recovery Curve" icon={<TrendingUp className="w-3.5 h-3.5 text-teal-400" />}>
              <div className="flex justify-between text-xs text-slate-500 mb-1">
                <span>Equity from drawdown trough</span>
                <span className="text-teal-400">
                  {fmt((T.recovery_curve as any[]).slice(-1)[0]?.pct_recovered)}% recovered
                </span>
              </div>
              <EquityCurveChart
                points={(T.recovery_curve as any[]).map((p: any) => ({ equity: p.equity }))}
                color="#14b8a6"
                label="Recovery equity"
                height={64}
              />
            </ChartCard>
          )}
        </div>

        {/* Rolling returns */}
        {rollingRet.length > 0 && (
          <InfoCard title="Rolling 5-Day Returns" icon={<BarChart3 className="w-3.5 h-3.5 text-sky-400" />}>
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead><tr className="text-slate-500 border-b border-slate-700/40">
                  <th className="pb-1.5 text-left px-1">Date</th>
                  <th className="pb-1.5 text-right px-1">5-Day Return</th>
                </tr></thead>
                <tbody>
                  {rollingRet.slice(-10).map((r: any, i: number) => (
                    <tr key={i} className="border-b border-slate-800/40">
                      <td className="py-1 px-1 text-slate-400">{r.date}</td>
                      <td className={`py-1 px-1 text-right font-medium ${pnlColor(r.return_pct ?? 0)}`}>
                        {fmtPct(r.return_pct, 3)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </InfoCard>
        )}

        {/* Drawdown summary */}
        <InfoCard title="Drawdown Summary" icon={<Shield className="w-3.5 h-3.5 text-rose-400" />}>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            <KpiCard label="Max Drawdown"   value={<span className="text-rose-400">{fmtRs(T.max_drawdown)}</span>} />
            <KpiCard label="Max DD %"       value={<span className="text-rose-400">{fmtPct(T.max_drawdown_pct)}</span>} />
            <KpiCard label="Current DD"     value={<span className="text-amber-400">{fmtRs(T.current_drawdown)}</span>} />
            <KpiCard label="Recovery"       value={fmtPct(T.recovery_pct)} />
          </div>
        </InfoCard>

        {/* Largest winner / loser */}
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <InfoCard title="Largest Winner" icon={<TrendingUp className="w-3.5 h-3.5 text-emerald-400" />}>
            {T.largest_winner
              ? <div className="space-y-1 text-sm">
                  <p className="text-slate-100 font-bold text-base">{T.largest_winner.symbol}</p>
                  <p className="text-emerald-400 font-semibold">{fmtRs(T.largest_winner.pnl)} ({fmtPct(T.largest_winner.pnl_pct)})</p>
                  <p className="text-slate-500 text-xs">{T.largest_winner.strategy} · {(T.largest_winner.exit_ts ?? "").slice(0, 10)}</p>
                </div>
              : <NoData />}
          </InfoCard>
          <InfoCard title="Largest Loser" icon={<TrendingDown className="w-3.5 h-3.5 text-rose-400" />}>
            {T.largest_loser
              ? <div className="space-y-1 text-sm">
                  <p className="text-slate-100 font-bold text-base">{T.largest_loser.symbol}</p>
                  <p className="text-rose-400 font-semibold">{fmtRs(T.largest_loser.pnl)} ({fmtPct(T.largest_loser.pnl_pct)})</p>
                  <p className="text-slate-500 text-xs">{T.largest_loser.strategy} · {(T.largest_loser.exit_ts ?? "").slice(0, 10)}</p>
                </div>
              : <NoData />}
          </InfoCard>
        </div>
      </div>
    );
  }

  // ── Strategies ───────────────────────────────────────────────────────────────
  function renderStrategies() {
    if (strategies.isLoading) return <Loading />;
    if (!St?.available) return <DisabledView />;
    const rows: any[] = St.strategies ?? [];
    return (
      <div className="space-y-5">
        <SectionHeader icon={<Layers className="w-5 h-5 text-teal-400" />} title="Strategy Analytics"
          sub={`${rows.length} strategy${rows.length !== 1 ? "ies" : "y"} tracked`} />

        <div className="grid grid-cols-2 sm:grid-cols-3 gap-3 mb-2">
          <KpiCard label="Best Strategy"  value={<span className="text-emerald-400">{St.best_strategy ?? "N/A"}</span>} />
          <KpiCard label="Worst Strategy" value={<span className="text-rose-400">{St.worst_strategy ?? "N/A"}</span>} />
          <KpiCard label="Total Tracked"  value={St.total_strategies ?? 0} />
        </div>

        {rows.length === 0 ? <NoData /> : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm border-collapse">
              <thead>
                <tr className="border-b border-slate-700/50 text-slate-400 text-xs uppercase tracking-wide">
                  {["Strategy","Trades","Win Rate","Avg Return","Profit Factor","Expectancy","Max DD","Contribution","Confidence"].map(h => (
                    <th key={h} className="pb-2 px-2 text-left font-medium whitespace-nowrap">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {rows.map((r: any, i: number) => (
                  <tr key={i} className="border-b border-slate-800/50 hover:bg-slate-800/30">
                    <td className="py-2 px-2 text-slate-100 font-medium whitespace-nowrap">{r.strategy_name}</td>
                    <td className="py-2 px-2 text-slate-300">{r.total_trades}</td>
                    <td className="py-2 px-2">
                      <span className={r.win_rate >= 50 ? "text-emerald-400" : "text-rose-400"}>
                        {fmtPct(r.win_rate)}
                      </span>
                    </td>
                    <td className="py-2 px-2">
                      <span className={pnlColor(r.avg_return ?? 0)}>{fmtRs(r.avg_return)}</span>
                    </td>
                    <td className="py-2 px-2 text-sky-400">{fmt(r.profit_factor)}</td>
                    <td className="py-2 px-2">
                      <span className={pnlColor(r.expectancy ?? 0)}>{fmtRs(r.expectancy)}</span>
                    </td>
                    <td className="py-2 px-2 text-rose-400">{fmtRs(r.max_drawdown)}</td>
                    <td className="py-2 px-2 text-violet-400">{fmtPct(r.contribution_pct)}</td>
                    <td className="py-2 px-2">
                      {r.confidence != null
                        ? <span className={r.confidence >= 60 ? "text-emerald-400" : "text-amber-400"}>{fmtPct(r.confidence)}</span>
                        : <span className="text-slate-600">—</span>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {/* Regime matrix */}
        {St.regime_matrix?.matrix && Object.keys(St.regime_matrix.matrix).length > 0 && (
          <InfoCard title="Strategy by Market Regime" icon={<Globe className="w-3.5 h-3.5 text-sky-400" />}>
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
              {Object.entries(St.regime_matrix.matrix as Record<string, any>).map(([regime, data]) => (
                <div key={regime} className="bg-slate-800/60 rounded-lg p-3">
                  <p className="text-xs text-slate-500 uppercase mb-0.5">{regime}</p>
                  <p className={`text-sm font-semibold ${pnlColor(data.net_pnl ?? 0)}`}>{fmtRs(data.net_pnl)}</p>
                  <p className="text-xs text-slate-500">{data.trade_count ?? 0} trades</p>
                </div>
              ))}
            </div>
          </InfoCard>
        )}
      </div>
    );
  }

  // ── Risk ─────────────────────────────────────────────────────────────────────
  function renderRisk() {
    if (risk.isLoading) return <Loading />;
    if (!R?.available) return <DisabledView />;

    const ddCurve: any[]  = R.drawdown_curve      ?? [];
    const retSeries: any[] = R.daily_return_series ?? [];

    return (
      <div className="space-y-5">
        <SectionHeader icon={<Shield className="w-5 h-5 text-teal-400" />} title="Risk Analytics" />

        <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
          <KpiCard label="Sharpe Ratio"      value={fmt(R.sharpe_ratio)}   sub="Risk-adjusted return" />
          <KpiCard label="Sortino Ratio"     value={fmt(R.sortino_ratio)}  sub="Downside-adjusted" />
          <KpiCard label="Calmar Ratio"      value={fmt(R.calmar_ratio)}   sub="Return / max DD" />
          <KpiCard label="Volatility"        value={fmtPct(R.volatility_pct)} sub="Annualised" />
          <KpiCard label="Total Return"      value={<span className={pnlColor(R.total_return_pct ?? 0)}>{fmtPct(R.total_return_pct)}</span>} />
          <KpiCard label="Risk-Free Rate"    value={fmtPct(R.risk_free_rate ? R.risk_free_rate * 100 : null)} sub="Annualised hurdle" />
          <KpiCard label="Max Drawdown"      value={<span className="text-rose-400">{fmtPct(R.max_drawdown_pct)}</span>} />
          <KpiCard label="Avg Drawdown"      value={<span className="text-amber-400">{fmtRs(R.avg_drawdown)}</span>} />
          <KpiCard label="Recovery Time"     value={fmtDays(R.recovery_time_days ?? 0)} />
          <KpiCard label="Recovery %"        value={fmtPct(R.recovery_pct)} />
          <KpiCard label="Profit Factor"     value={fmt(R.profit_factor)} />
          <KpiCard label="Risk/Reward"       value={fmt(R.risk_reward_ratio)} />
        </div>

        {/* Drawdown curve chart */}
        {ddCurve.length >= 2 && (
          <ChartCard title="Drawdown % Over Time" icon={<Shield className="w-3.5 h-3.5 text-rose-400" />}>
            <div className="flex justify-between text-xs text-slate-500 mb-1">
              <span>All-time drawdown profile</span>
              <span className="text-rose-400">{fmtPct(R.max_drawdown_pct)} peak</span>
            </div>
            <DrawdownChart points={ddCurve} height={80} />
          </ChartCard>
        )}

        {/* Daily returns sparkline */}
        {retSeries.length >= 2 && (
          <ChartCard title="Daily Returns" icon={<Activity className="w-3.5 h-3.5 text-sky-400" />}>
            <div className="flex justify-between text-xs text-slate-500 mb-1">
              <span>Daily % return history</span>
              <span>{R.daily_returns_count} sessions</span>
            </div>
            {(() => {
              const vals = retSeries.map((r: any) => r.return_pct ?? 0);
              const lastVal = vals[vals.length - 1];
              return (
                <>
                  <EquityCurveChart
                    points={retSeries.map((r: any) => ({ equity: r.return_pct ?? 0 }))}
                    color={lastVal >= 0 ? "#10b981" : "#ef4444"}
                    label="Daily return %"
                    height={60}
                  />
                </>
              );
            })()}
          </ChartCard>
        )}

        {/* Reward / Loss distributions */}
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <InfoCard title="Reward Distribution" icon={<TrendingUp className="w-3.5 h-3.5 text-emerald-400" />}>
            {(R.reward_distribution ?? []).length === 0 ? <NoData /> : (
              <div className="space-y-1">
                {R.reward_distribution.map((b: any, i: number) => (
                  <div key={i} className="flex justify-between items-center text-xs">
                    <span className="text-slate-400 w-24 shrink-0">{b.bucket}</span>
                    <div className="flex-1 mx-2 bg-slate-700/40 rounded-full h-1.5">
                      <div className="bg-emerald-500 h-1.5 rounded-full"
                        style={{ width: `${Math.min(100, (b.count / Math.max(...R.reward_distribution.map((x: any) => x.count))) * 100)}%` }} />
                    </div>
                    <span className="text-emerald-400 font-medium w-6 text-right">{b.count}</span>
                  </div>
                ))}
              </div>
            )}
          </InfoCard>
          <InfoCard title="Loss Distribution" icon={<TrendingDown className="w-3.5 h-3.5 text-rose-400" />}>
            {(R.loss_distribution ?? []).length === 0 ? <NoData /> : (
              <div className="space-y-1">
                {R.loss_distribution.map((b: any, i: number) => (
                  <div key={i} className="flex justify-between items-center text-xs">
                    <span className="text-slate-400 w-24 shrink-0">{b.bucket}</span>
                    <div className="flex-1 mx-2 bg-slate-700/40 rounded-full h-1.5">
                      <div className="bg-rose-500 h-1.5 rounded-full"
                        style={{ width: `${Math.min(100, (b.count / Math.max(...R.loss_distribution.map((x: any) => x.count))) * 100)}%` }} />
                    </div>
                    <span className="text-rose-400 font-medium w-6 text-right">{b.count}</span>
                  </div>
                ))}
              </div>
            )}
          </InfoCard>
        </div>
      </div>
    );
  }

  // ── Portfolio ─────────────────────────────────────────────────────────────────
  function renderPortfolio() {
    if (portfolio.isLoading) return <Loading />;
    if (!Po?.available) return <DisabledView />;

    const growthPts: any[] = Po.capital_growth_series ?? [];

    return (
      <div className="space-y-5">
        <SectionHeader icon={<PieChart className="w-5 h-5 text-teal-400" />} title="Portfolio Analytics" />

        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          <KpiCard label="Total Value"        value={fmtRs(Po.total_value)} />
          <KpiCard label="Initial Capital"    value={fmtRs(Po.initial_capital)} />
          <KpiCard label="Cash Available"     value={fmtRs(Po.cash)} />
          <KpiCard label="Invested"           value={fmtRs(Po.invested)} />
          <KpiCard label="Total Return"       value={<span className={pnlColor(Po.total_return_pct ?? 0)}>{fmtPct(Po.total_return_pct)}</span>} />
          <KpiCard label="Cash Utilisation"   value={fmtPct(Po.cash_utilisation_pct)} />
          <KpiCard label="Max Position Wt"    value={fmtPct(Po.position_concentration_pct)} />
          <KpiCard label="Diversification"    value={fmt(Po.diversification_score)} sub="0–100 (higher = better)" />
        </div>

        {/* Capital Growth Chart */}
        {growthPts.length >= 2 && (
          <ChartCard title="Capital Growth" icon={<TrendingUp className="w-3.5 h-3.5 text-teal-400" />}>
            <EquityCurveChart
              points={growthPts}
              color="#14b8a6"
              label="Portfolio value over time"
              height={90}
            />
            <div className="flex justify-between text-xs text-slate-500 mt-1">
              <span>{fmtRs(Po.initial_capital)} start</span>
              <span className={pnlColor(Po.total_return_pct ?? 0)}>
                {fmtPct(Po.total_return_pct)} return
              </span>
              <span>{fmtRs(Po.total_value)} now</span>
            </div>
          </ChartCard>
        )}

        {/* Open positions */}
        {(Po.open_positions ?? []).length > 0 && (
          <InfoCard title="Open Positions" icon={<Layers className="w-3.5 h-3.5 text-sky-400" />}>
            <table className="w-full text-sm">
              <thead><tr className="text-slate-500 text-xs uppercase border-b border-slate-700/40">
                {["Symbol","Strategy","Qty","Entry Price","Unrealised PnL"].map(h =>
                  <th key={h} className="pb-2 px-1 text-left">{h}</th>
                )}
              </tr></thead>
              <tbody>
                {(Po.open_positions as any[]).map((p: any, i: number) => (
                  <tr key={i} className="border-b border-slate-800/40">
                    <td className="py-1.5 px-1 text-slate-100 font-medium">{p.symbol}</td>
                    <td className="py-1.5 px-1 text-slate-400">{p.strategy_name}</td>
                    <td className="py-1.5 px-1 text-slate-300">{p.quantity}</td>
                    <td className="py-1.5 px-1 text-slate-300">{fmtRs(p.entry_price)}</td>
                    <td className="py-1.5 px-1">
                      <span className={pnlColor(p.unrealised_pnl ?? 0)}>{fmtRs(p.unrealised_pnl)}</span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </InfoCard>
        )}

        {/* Allocations */}
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <InfoCard title="Sector Allocation" icon={<Globe className="w-3.5 h-3.5 text-sky-400" />}>
            {(Po.sector_allocation ?? []).length === 0 ? <NoData /> : (
              <div className="space-y-2">
                {(Po.sector_allocation as any[]).slice(0, 8).map((s: any, i: number) => (
                  <div key={i} className="space-y-0.5">
                    <div className="flex justify-between text-xs">
                      <span className="text-slate-300">{s.sector}</span>
                      <span className="text-sky-400 font-medium">{fmtPct(s.pct)}</span>
                    </div>
                    <div className="bg-slate-700/40 rounded-full h-1">
                      <div className="bg-sky-500 h-1 rounded-full" style={{ width: `${Math.min(100, s.pct ?? 0)}%` }} />
                    </div>
                  </div>
                ))}
              </div>
            )}
          </InfoCard>
          <InfoCard title="Strategy Allocation" icon={<Layers className="w-3.5 h-3.5 text-violet-400" />}>
            {(Po.strategy_allocation ?? []).length === 0 ? <NoData /> : (
              <div className="space-y-1.5">
                {(Po.strategy_allocation as any[]).slice(0, 8).map((s: any, i: number) => (
                  <div key={i} className="flex justify-between text-xs">
                    <span className="text-slate-300">{s.strategy_name}</span>
                    <span className={`font-medium ${pnlColor(s.total_pnl ?? 0)}`}>{fmtRs(s.total_pnl)}</span>
                  </div>
                ))}
              </div>
            )}
          </InfoCard>
        </div>
      </div>
    );
  }

  // ── Time ─────────────────────────────────────────────────────────────────────
  function renderTime() {
    if (learning.isLoading) return <Loading />;
    const time = L?.time_analytics as any;
    if (!time?.available) return <DisabledView />;

    const sessions: any[] = time.sessions ?? [];
    const hours:    any[] = time.hours    ?? [];

    return (
      <div className="space-y-5">
        <SectionHeader icon={<Clock className="w-5 h-5 text-teal-400" />} title="Time Analytics" sub="Performance by trading session and hour" />

        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          <KpiCard label="Best Session"       value={<span className="text-emerald-400">{time.best_session   ?? "—"}</span>} />
          <KpiCard label="Worst Session"      value={<span className="text-rose-400">{time.worst_session     ?? "—"}</span>} />
          <KpiCard label="Best Hour"          value={<span className="text-emerald-400">{time.best_hour      ?? "—"}</span>} />
          <KpiCard label="Worst Hour"         value={<span className="text-rose-400">{time.worst_hour        ?? "—"}</span>} />
          <KpiCard label="Avg Hold"           value={`${((time.avg_hold_seconds ?? 0) / 60).toFixed(0)} min`} />
        </div>

        {/* Session table */}
        <InfoCard title="Session Performance" icon={<Clock className="w-3.5 h-3.5 text-sky-400" />}>
          {sessions.length === 0 ? <NoData /> : (
            <table className="w-full text-sm">
              <thead><tr className="text-slate-500 text-xs uppercase border-b border-slate-700/40">
                {["Session","Trades","Win Rate","Avg Return","Total PnL","Avg Hold"].map(h =>
                  <th key={h} className="pb-2 px-1 text-left">{h}</th>
                )}
              </tr></thead>
              <tbody>
                {sessions.map((s: any, i: number) => (
                  <tr key={i} className={`border-b border-slate-800/50 ${s.session === time.best_session ? "bg-emerald-500/5" : ""}`}>
                    <td className="py-1.5 px-1 text-slate-200 font-medium">{s.session}</td>
                    <td className="py-1.5 px-1 text-slate-300">{s.trade_count}</td>
                    <td className="py-1.5 px-1">
                      <span className={s.win_rate >= 50 ? "text-emerald-400" : "text-rose-400"}>{fmtPct(s.win_rate)}</span>
                    </td>
                    <td className="py-1.5 px-1"><span className={pnlColor(s.avg_return ?? 0)}>{fmtRs(s.avg_return)}</span></td>
                    <td className="py-1.5 px-1"><span className={pnlColor(s.total_pnl ?? 0)}>{fmtRs(s.total_pnl)}</span></td>
                    <td className="py-1.5 px-1 text-slate-400">{((s.avg_hold_seconds ?? 0) / 60).toFixed(0)}m</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </InfoCard>

        {/* Hourly performance */}
        {hours.length > 0 && (
          <InfoCard title="Hourly Performance" icon={<BarChart3 className="w-3.5 h-3.5 text-violet-400" />}>
            <table className="w-full text-sm">
              <thead><tr className="text-slate-500 text-xs uppercase border-b border-slate-700/40">
                {["Hour","Trades","Win Rate","Avg Return"].map(h =>
                  <th key={h} className="pb-2 px-1 text-left">{h}</th>
                )}
              </tr></thead>
              <tbody>
                {hours.map((h: any, i: number) => (
                  <tr key={i} className={`border-b border-slate-800/40 ${h.label === time.best_hour ? "bg-emerald-500/5" : h.label === time.worst_hour ? "bg-rose-500/5" : ""}`}>
                    <td className="py-1 px-1 text-slate-200 font-medium">{h.label}</td>
                    <td className="py-1 px-1 text-slate-300">{h.trade_count}</td>
                    <td className="py-1 px-1">
                      <span className={h.win_rate >= 50 ? "text-emerald-400" : "text-rose-400"}>{fmtPct(h.win_rate)}</span>
                    </td>
                    <td className="py-1 px-1"><span className={pnlColor(h.avg_return ?? 0)}>{fmtRs(h.avg_return)}</span></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </InfoCard>
        )}
      </div>
    );
  }

  // ── Sectors ──────────────────────────────────────────────────────────────────
  function renderSectors() {
    if (learning.isLoading) return <Loading />;
    const sec = L?.sector_analytics as any;
    if (!sec?.available) return <DisabledView />;
    const sectors: any[] = sec.sectors ?? [];

    return (
      <div className="space-y-5">
        <SectionHeader icon={<Globe className="w-5 h-5 text-teal-400" />} title="Sector Analytics" sub={`${sec.total_sectors_traded ?? 0} sectors traded`} />

        <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
          <KpiCard label="Best Sector"        value={<span className="text-emerald-400">{sec.best_sector ?? "—"}</span>} />
          <KpiCard label="Worst Sector"       value={<span className="text-rose-400">{sec.worst_sector ?? "—"}</span>} />
          <KpiCard label="Best Win Rate"      value={sec.best_win_rate_sector ?? "—"} />
        </div>

        {sectors.length === 0 ? <NoData /> : (
          <>
            {/* Bar-like contribution chart */}
            <InfoCard title="PnL Contribution by Sector" icon={<BarChart3 className="w-3.5 h-3.5 text-sky-400" />}>
              <div className="space-y-2">
                {sectors.map((s: any, i: number) => {
                  const maxPnl = Math.max(...sectors.map((x: any) => Math.abs(x.total_pnl ?? 0))) || 1;
                  const pct    = Math.abs(s.total_pnl ?? 0) / maxPnl * 100;
                  return (
                    <div key={i} className="space-y-0.5">
                      <div className="flex justify-between text-xs">
                        <span className="text-slate-300 font-medium">{s.sector}</span>
                        <span className={pnlColor(s.total_pnl ?? 0)}>{fmtRs(s.total_pnl)}</span>
                      </div>
                      <div className="bg-slate-700/40 rounded-full h-1.5">
                        <div className={`h-1.5 rounded-full ${(s.total_pnl ?? 0) >= 0 ? "bg-emerald-500" : "bg-rose-500"}`}
                          style={{ width: `${pct}%` }} />
                      </div>
                    </div>
                  );
                })}
              </div>
            </InfoCard>

            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead><tr className="text-slate-500 text-xs uppercase border-b border-slate-700/40">
                  {["Sector","Trades","Win Rate","Avg Return","Total PnL","Contribution"].map(h =>
                    <th key={h} className="pb-2 px-2 text-left">{h}</th>
                  )}
                </tr></thead>
                <tbody>
                  {sectors.map((s: any, i: number) => (
                    <tr key={i} className="border-b border-slate-800/50 hover:bg-slate-800/20">
                      <td className="py-1.5 px-2 text-slate-200 font-medium">{s.sector}</td>
                      <td className="py-1.5 px-2 text-slate-300">{s.trade_count}</td>
                      <td className="py-1.5 px-2">
                        <span className={s.win_rate >= 50 ? "text-emerald-400" : "text-rose-400"}>{fmtPct(s.win_rate)}</span>
                      </td>
                      <td className="py-1.5 px-2"><span className={pnlColor(s.avg_return ?? 0)}>{fmtRs(s.avg_return)}</span></td>
                      <td className="py-1.5 px-2"><span className={pnlColor(s.total_pnl ?? 0)}>{fmtRs(s.total_pnl)}</span></td>
                      <td className="py-1.5 px-2 text-violet-400">{fmtPct(s.contribution_pct)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}
      </div>
    );
  }

  // ── Pre-Open ─────────────────────────────────────────────────────────────────
  function renderPreopen() {
    if (preopen.isLoading) return <Loading />;
    if (!Pr?.available) return <DisabledView msg={Pr?.message} />;

    const ls      = Pr.latest_session      ?? {};
    const bands:  any[] = Pr.score_band_accuracy  ?? [];
    const trend         = Pr.trend_classification  ?? {};
    const history: any[] = Pr.history             ?? [];
    const symbols: any[] = (Pr.symbols ?? []).slice(0, 10);  // Top-10

    return (
      <div className="space-y-5">
        <SectionHeader icon={<Zap className="w-5 h-5 text-teal-400" />} title="Pre-Open Analytics" sub={`Latest session: ${ls.trading_date ?? "N/A"}`} />

        {/* Core session metrics */}
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          <KpiCard label="Hit Rate"          value={ls.hit_rate_pct != null ? fmtPct(ls.hit_rate_pct) : "—"} />
          <KpiCard label="Continuation"      value={ls.continuation_rate_pct != null ? fmtPct(ls.continuation_rate_pct) : "—"} />
          <KpiCard label="Reversal Rate"     value={ls.reversal_rate_pct != null ? fmtPct(ls.reversal_rate_pct) : "—"} />
          <KpiCard label="Grade"             value={<span className={gradeColor(ls.grade ?? "")}>{ls.grade ?? "N/A"}</span>} sub={ls.grade_label} />
          <KpiCard label="Symbols"           value={ls.symbols_reconciled ?? 0} />
          <KpiCard label="Confirmation"      value={ls.confirmation_rate_pct != null ? fmtPct(ls.confirmation_rate_pct) : "—"} />
          <KpiCard label="False Positive"    value={ls.false_positive_rate_pct != null ? fmtPct(ls.false_positive_rate_pct) : "—"} />
          <KpiCard label="MAE %"             value={ls.mae_pct != null ? fmtPct(ls.mae_pct, 4) : "—"} sub="Avg indicative error" />
        </div>

        {/* Trend classification — only render fields available from the data source */}
        {Object.keys(trend).length > 0 && (
          <div className="space-y-2">
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
              {/* gap_and_go is always available (from direction_correct) */}
              <KpiCard
                label="Gap-and-Go"
                value={trend.gap_and_go_count ?? 0}
                sub={trend.gap_and_go_rate != null ? fmtPct(trend.gap_and_go_rate) + " rate" : "—"}
              />
              {/* Gap Fill — only show when upstream supplies opening_reversal */}
              {trend.gap_fill_available
                ? <KpiCard label="Gap Fill" value={trend.gap_fill_count ?? 0} sub={trend.gap_fill_rate != null ? fmtPct(trend.gap_fill_rate) + " rate" : "—"} />
                : <div className="rounded-xl border border-slate-700/50 bg-slate-800/40 p-3 flex flex-col gap-0.5">
                    <p className="text-xs text-slate-500 uppercase tracking-wide">Gap Fill</p>
                    <p className="text-sm font-semibold text-slate-500">Unavailable</p>
                    <p className="text-xs text-slate-600">Needs opening_reversal field</p>
                  </div>
              }
              {/* Early Reversal — only show when upstream supplies session_minutes */}
              {trend.early_reversal_available
                ? <KpiCard label="Early Reversal" value={trend.early_reversal_count ?? 0} sub={trend.early_reversal_rate != null ? fmtPct(trend.early_reversal_rate) + " rate" : "—"} />
                : <div className="rounded-xl border border-slate-700/50 bg-slate-800/40 p-3 flex flex-col gap-0.5">
                    <p className="text-xs text-slate-500 uppercase tracking-wide">Early Reversal</p>
                    <p className="text-sm font-semibold text-slate-500">Unavailable</p>
                    <p className="text-xs text-slate-600">Needs session_minutes field</p>
                  </div>
              }
              {/* Late Reversal */}
              {trend.late_reversal_available
                ? <KpiCard label="Late Reversal" value={trend.late_reversal_count ?? 0} sub={trend.late_reversal_rate != null ? fmtPct(trend.late_reversal_rate) + " rate" : "—"} />
                : <div className="rounded-xl border border-slate-700/50 bg-slate-800/40 p-3 flex flex-col gap-0.5">
                    <p className="text-xs text-slate-500 uppercase tracking-wide">Late Reversal</p>
                    <p className="text-sm font-semibold text-slate-500">Unavailable</p>
                    <p className="text-xs text-slate-600">Needs opening_reversal field</p>
                  </div>
              }
            </div>
            {/* Range-day / Trend-day — require intraday OHLC */}
            {(!trend.range_day_available || !trend.trend_day_available) && (
              <p className="text-xs text-slate-600 italic px-1">
                Range-day and trend-day classifications require intraday OHLC data not available from the pre-open source.
              </p>
            )}
          </div>
        )}

        {/* Score-band accuracy */}
        {bands.length > 0 && (
          <InfoCard title="Score-Band Accuracy" icon={<Target className="w-3.5 h-3.5 text-violet-400" />}>
            <div className="space-y-2">
              {bands.map((b: any, i: number) => (
                <div key={i} className="space-y-0.5">
                  <div className="flex justify-between text-xs">
                    <span className="text-slate-300">{b.band}</span>
                    <span className="text-slate-500">{b.count} symbols</span>
                    <span className={b.accuracy >= 60 ? "text-emerald-400 font-medium" : "text-rose-400 font-medium"}>
                      {fmtPct(b.accuracy)}
                    </span>
                  </div>
                  <div className="bg-slate-700/40 rounded-full h-1.5">
                    <div className={`h-1.5 rounded-full ${b.accuracy >= 60 ? "bg-emerald-500" : "bg-rose-500"}`}
                      style={{ width: `${Math.min(100, b.accuracy ?? 0)}%` }} />
                  </div>
                </div>
              ))}
            </div>
          </InfoCard>
        )}

        {/* Historical sessions */}
        {history.length > 0 && (
          <InfoCard title="Historical Session Accuracy" icon={<BarChart3 className="w-3.5 h-3.5 text-sky-400" />}>
            <table className="w-full text-xs">
              <thead><tr className="text-slate-500 uppercase border-b border-slate-700/40">
                {["Date","Symbols","Hit Rate","Continuation","Reversal","Grade"].map(h =>
                  <th key={h} className="pb-1.5 px-1 text-left">{h}</th>
                )}
              </tr></thead>
              <tbody>
                {history.slice(0, 10).map((s: any, i: number) => (
                  <tr key={i} className="border-b border-slate-800/40 hover:bg-slate-800/20">
                    <td className="py-1 px-1 text-slate-400">{s.trading_date}</td>
                    <td className="py-1 px-1 text-slate-300">{s.symbols_count ?? "—"}</td>
                    <td className="py-1 px-1">
                      <span className={s.hit_rate_pct >= 50 ? "text-emerald-400" : "text-rose-400"}>
                        {s.hit_rate_pct != null ? fmtPct(s.hit_rate_pct) : "—"}
                      </span>
                    </td>
                    <td className="py-1 px-1 text-slate-300">{s.continuation_pct != null ? fmtPct(s.continuation_pct) : "—"}</td>
                    <td className="py-1 px-1 text-slate-300">{s.reversal_pct     != null ? fmtPct(s.reversal_pct)     : "—"}</td>
                    <td className="py-1 px-1">
                      <span className={gradeColor(s.grade ?? "")}>{s.grade ?? "—"}</span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </InfoCard>
        )}

        {/* Top-10 symbols */}
        {symbols.length > 0 && (
          <InfoCard title="Top-10 Symbol Accuracy (Latest)" icon={<Award className="w-3.5 h-3.5 text-teal-400" />}>
            <table className="w-full text-xs">
              <thead><tr className="text-slate-500 uppercase border-b border-slate-700/40">
                {["Symbol","Score","Direction","Error %","Result"].map(h =>
                  <th key={h} className="pb-1.5 px-1 text-left">{h}</th>
                )}
              </tr></thead>
              <tbody>
                {symbols.map((s: any, i: number) => (
                  <tr key={i} className="border-b border-slate-800/40">
                    <td className="py-1 px-1 text-slate-200 font-medium">{s.symbol}</td>
                    <td className="py-1 px-1 text-sky-400">{s.preopen_score ?? s.score ?? "—"}</td>
                    <td className="py-1 px-1 text-slate-300">{s.direction ?? "—"}</td>
                    <td className="py-1 px-1 text-slate-400">{s.error_pct != null ? fmtPct(s.error_pct, 3) : "—"}</td>
                    <td className="py-1 px-1">
                      {s.direction_correct === true
                        ? <span className="text-emerald-400 font-medium">✓ Hit</span>
                        : s.direction_correct === false
                          ? <span className="text-rose-400 font-medium">✗ Miss</span>
                          : <span className="text-slate-600">—</span>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </InfoCard>
        )}
      </div>
    );
  }

  // ── Execution ─────────────────────────────────────────────────────────────────
  function renderExecution() {
    if (learning.isLoading) return <Loading />;
    const Ex = L?.execution_analytics as any;

    if (!Ex?.available) {
      return (
        <div className="space-y-5">
          <SectionHeader icon={<Target className="w-5 h-5 text-teal-400" />} title="Execution Quality" sub="Entry/exit quality, slippage, capture" />
          <InfoCard title="">
            <div className="text-center py-6 space-y-2">
              <AlertTriangle className="w-8 h-8 text-amber-500 mx-auto" />
              <p className="text-slate-300 font-medium">Execution data not yet available</p>
              <p className="text-slate-500 text-sm max-w-sm mx-auto">
                {Ex?.message ?? "Execution metrics require completed paper trades with recorded entry and exit prices via the Execution Quality module."}
              </p>
              {Ex?.error && <p className="text-rose-400 text-xs font-mono mt-2">{Ex.error}</p>}
            </div>
          </InfoCard>
        </div>
      );
    }

    return (
      <div className="space-y-5">
        <SectionHeader icon={<Target className="w-5 h-5 text-teal-400" />} title="Execution Quality"
          sub={`${Ex.total_records ?? 0} records · ${Ex.completed_records ?? 0} completed`} />

        {/* Core KPIs */}
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          <KpiCard label="Total Records"    value={Ex.total_records ?? 0} />
          <KpiCard label="Completed"        value={<span className="text-emerald-400">{Ex.completed_records ?? 0}</span>} />
          <KpiCard label="Avg Quality Score" value={<span className={gradeColor(Ex.overall_grade ?? "D")}>{fmt(Ex.avg_quality_score)}</span>} sub="/ 100" />
          <KpiCard label="Overall Grade"    value={<span className={gradeColor(Ex.overall_grade ?? "D")}>{Ex.overall_grade ?? "—"}</span>} />
          <KpiCard label="Avg Entry Slippage" value={Ex.avg_entry_slippage_pct != null ? fmtPct(Ex.avg_entry_slippage_pct, 4) : "—"}
            sub="Entry quality" />
          <KpiCard label="Avg Exit Slippage"  value={Ex.avg_exit_slippage_pct  != null ? fmtPct(Ex.avg_exit_slippage_pct,  4) : "—"}
            sub="Exit quality" />
          <KpiCard label="Avg Capture %"    value={Ex.avg_capture_pct != null ? fmtPct(Ex.avg_capture_pct) : "—"}
            sub="Potential captured" />
        </div>

        {/* Best / worst execution */}
        {Ex.best_execution && (
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <InfoCard title="Best Execution" icon={<CheckCircle2 className="w-3.5 h-3.5 text-emerald-400" />}>
              <p className="text-slate-100 font-bold">{Ex.best_execution.symbol ?? "—"}</p>
              <p className="text-emerald-400 text-sm">{fmt(Ex.best_execution.score)} quality score</p>
              <p className="text-slate-500 text-xs">{Ex.best_execution.strategy}</p>
            </InfoCard>
            {Ex.worst_execution && (
              <InfoCard title="Worst Execution" icon={<AlertTriangle className="w-3.5 h-3.5 text-rose-400" />}>
                <p className="text-slate-100 font-bold">{Ex.worst_execution.symbol ?? "—"}</p>
                <p className="text-rose-400 text-sm">{fmt(Ex.worst_execution.score)} quality score</p>
                <p className="text-slate-500 text-xs">{Ex.worst_execution.strategy}</p>
              </InfoCard>
            )}
          </div>
        )}

        {/* Grade distribution */}
        {Ex.grade_distribution && Object.keys(Ex.grade_distribution).length > 0 && (
          <InfoCard title="Grade Distribution" icon={<Award className="w-3.5 h-3.5 text-violet-400" />}>
            <div className="flex flex-wrap gap-2">
              {Object.entries(Ex.grade_distribution as Record<string, number>).map(([grade, count]) => (
                <span key={grade}
                  className={`text-sm px-3 py-1 rounded-full border font-medium ${gradeColor(grade)} bg-slate-800/60 border-slate-700/50`}>
                  {grade}: {count}
                </span>
              ))}
            </div>
          </InfoCard>
        )}

        {/* Per-strategy quality */}
        {(Ex.strategy_quality ?? []).length > 0 && (
          <InfoCard title="Quality by Strategy" icon={<Layers className="w-3.5 h-3.5 text-sky-400" />}>
            <table className="w-full text-sm">
              <thead><tr className="text-slate-500 text-xs uppercase border-b border-slate-700/40">
                {["Strategy","Records","Avg Score","Avg Entry Slippage"].map(h =>
                  <th key={h} className="pb-2 px-1 text-left">{h}</th>
                )}
              </tr></thead>
              <tbody>
                {(Ex.strategy_quality as any[]).map((s: any, i: number) => (
                  <tr key={i} className="border-b border-slate-800/50">
                    <td className="py-1.5 px-1 text-slate-200 font-medium">{s.strategy}</td>
                    <td className="py-1.5 px-1 text-slate-300">{s.count}</td>
                    <td className="py-1.5 px-1">
                      <span className={s.avg_score >= 70 ? "text-emerald-400" : s.avg_score >= 50 ? "text-amber-400" : "text-rose-400"}>
                        {fmt(s.avg_score)}
                      </span>
                    </td>
                    <td className="py-1.5 px-1 text-slate-400">{fmtPct(s.avg_slippage_pct, 4)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </InfoCard>
        )}
      </div>
    );
  }

  // ── Learning ──────────────────────────────────────────────────────────────────
  function renderLearning() {
    if (learning.isLoading) return <Loading />;
    const ld = L as any;
    if (!ld?.available) return <DisabledView />;
    if (!ld.has_data) return <NoData msg="No completed trades yet — run paper trades to generate learning insights." />;

    return (
      <div className="space-y-5">
        <SectionHeader icon={<BookOpen className="w-5 h-5 text-teal-400" />} title="Learning Insights" sub="Auto-identified from all paper trades" />

        <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
          <KpiCard label="Best Strategy"           value={<span className="text-emerald-400">{ld.best_strategy    ?? "N/A"}</span>} />
          <KpiCard label="Worst Strategy"          value={<span className="text-rose-400">{ld.worst_strategy      ?? "N/A"}</span>} />
          <KpiCard label="Most Consistent"         value={ld.most_consistent_strategy ?? "N/A"} />
          <KpiCard label="Best Sector"             value={<span className="text-emerald-400">{ld.best_sector     ?? "N/A"}</span>} />
          <KpiCard label="Worst Sector"            value={<span className="text-rose-400">{ld.worst_sector        ?? "N/A"}</span>} />
          <KpiCard label="Highest-Risk Strategy"   value={<span className="text-amber-400">{ld.highest_risk_strategy ?? "N/A"}</span>} />
          <KpiCard label="Best Market Condition"   value={<span className="text-sky-400">{ld.best_market_condition ?? "N/A"}</span>} />
          <KpiCard label="Worst Condition"         value={<span className="text-rose-400">{ld.worst_market_condition ?? "N/A"}</span>} />
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <InfoCard title="Common Winning Characteristics" icon={<CheckCircle2 className="w-3.5 h-3.5 text-emerald-400" />}>
            {(ld.winning_characteristics ?? []).length === 0 ? <NoData /> :
              (ld.winning_characteristics as string[]).map((c, i) => (
                <p key={i} className="text-sm text-slate-300 py-0.5 border-b border-slate-800/40 last:border-0">{c}</p>
              ))}
          </InfoCard>
          <InfoCard title="Common Losing Characteristics" icon={<AlertTriangle className="w-3.5 h-3.5 text-rose-400" />}>
            {(ld.losing_characteristics ?? []).length === 0 ? <NoData /> :
              (ld.losing_characteristics as string[]).map((c, i) => (
                <p key={i} className="text-sm text-slate-300 py-0.5 border-b border-slate-800/40 last:border-0">{c}</p>
              ))}
          </InfoCard>
        </div>

        {/* Per-strategy metrics */}
        {ld.strategy_metrics && Object.keys(ld.strategy_metrics).length > 0 && (
          <InfoCard title="Strategy Metrics Detail" icon={<Layers className="w-3.5 h-3.5 text-violet-400" />}>
            <table className="w-full text-xs">
              <thead><tr className="text-slate-500 uppercase border-b border-slate-700/40">
                {["Strategy","Trades","Win Rate","Profit Factor","Consistency","Max DD"].map(h =>
                  <th key={h} className="pb-1.5 px-1 text-left">{h}</th>
                )}
              </tr></thead>
              <tbody>
                {Object.entries(ld.strategy_metrics as Record<string, any>).map(([name, m]) => (
                  <tr key={name} className="border-b border-slate-800/40">
                    <td className="py-1 px-1 text-slate-200 font-medium">{name}</td>
                    <td className="py-1 px-1 text-slate-300">{m.trade_count}</td>
                    <td className="py-1 px-1">
                      <span className={(m.win_rate ?? 0) >= 50 ? "text-emerald-400" : "text-rose-400"}>
                        {fmtPct(m.win_rate)}
                      </span>
                    </td>
                    <td className="py-1 px-1 text-sky-400">{fmt(m.profit_factor)}</td>
                    <td className="py-1 px-1 text-slate-300">{fmt(m.consistency)}</td>
                    <td className="py-1 px-1 text-rose-400">{fmtRs(m.max_drawdown)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </InfoCard>
        )}
      </div>
    );
  }

  // ── AI Insights ───────────────────────────────────────────────────────────────
  function renderAI() {
    if (learning.isLoading) return <Loading />;
    const ai = (L as any)?.ai_insights as any;
    if (!ai?.available) return <DisabledView />;

    return (
      <div className="space-y-5">
        <SectionHeader icon={<Brain className="w-5 h-5 text-teal-400" />} title="AI Insights" sub="Informational only · Advisory" />

        <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
          <KpiCard label="Best Trading Window"    value={ai.most_profitable_window     ?? "N/A"} />
          <KpiCard label="Top Regime"             value={ai.highest_performing_regime  ?? "N/A"} />
          <KpiCard label="Most Reliable Strategy" value={ai.most_reliable_strategy     ?? "N/A"} />
          <KpiCard label="Best Pre-Open Band"     value={ai.most_reliable_preopen_band ?? "N/A"} />
          <KpiCard label="Advisory Confidence"    value={
            <span className={ai.confidence_score >= 60 ? "text-emerald-400" : "text-amber-400"}>
              {fmt(ai.confidence_score)} / 100
            </span>
          } />
          <KpiCard label="AI Health"              value={
            <span className={(ai.ai_health_score ?? 0) >= 70 ? "text-emerald-400" : "text-amber-400"}>
              {ai.ai_health_label ?? "—"}
            </span>
          } sub={ai.ai_health_score != null ? `Score: ${fmt(ai.ai_health_score)}` : undefined} />
        </div>

        {/* AI metrics */}
        {(ai.ai_prediction_accuracy != null || ai.ai_trend_direction) && (
          <div className="grid grid-cols-2 gap-3">
            {ai.ai_prediction_accuracy != null && (
              <KpiCard label="Prediction Accuracy" value={fmtPct(ai.ai_prediction_accuracy)} />
            )}
            {ai.ai_trend_direction && (
              <KpiCard label="AI Trend" value={ai.ai_trend_direction} />
            )}
          </div>
        )}

        <InfoCard title="Recommended Research Areas" icon={<Info className="w-3.5 h-3.5 text-sky-400" />}>
          {(ai.recommended_research_areas ?? []).map((area: string, i: number) => (
            <p key={i} className="text-sm text-slate-300 py-1 border-b border-slate-800/40 last:border-0 flex items-start gap-2">
              <span className="text-sky-500 mt-0.5">›</span>{area}
            </p>
          ))}
        </InfoCard>

        <p className="text-xs text-slate-600 text-center italic">{ai.note}</p>
      </div>
    );
  }

  // ── Export ────────────────────────────────────────────────────────────────────
  async function handleExport(format: "json" | "csv") {
    try {
      const d = await apiJson(`paper-analytics/export?format=${format}`) as any;
      const content = format === "csv" ? (d.csv ?? "") : JSON.stringify(d, null, 2);
      const mime    = format === "csv" ? "text/csv" : "application/json";
      const blob    = new Blob([content], { type: mime });
      const url     = URL.createObjectURL(blob);
      const a       = document.createElement("a");
      a.href = url; a.download = `paper-analytics.${format}`; a.click();
      URL.revokeObjectURL(url);
    } catch (e) { console.error("Export failed", e); }
  }

  function renderExport() {
    return (
      <div className="space-y-5">
        <SectionHeader icon={<Download className="w-5 h-5 text-teal-400" />} title="Export Data" sub="Paper trading analytics" />
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <InfoCard title="JSON Export" icon={<FileText className="w-3.5 h-3.5 text-sky-400" />}>
            <p className="text-slate-400 text-sm mb-3">Full analytics payload — all sections.</p>
            <button onClick={() => handleExport("json")}
              className="px-4 py-2 bg-sky-600/80 hover:bg-sky-500/80 text-white rounded-lg text-sm font-medium transition-colors">
              Download JSON
            </button>
          </InfoCard>
          <InfoCard title="CSV Export" icon={<FileText className="w-3.5 h-3.5 text-teal-400" />}>
            <p className="text-slate-400 text-sm mb-3">Summary KPIs in CSV format.</p>
            <button onClick={() => handleExport("csv")}
              className="px-4 py-2 bg-teal-600/80 hover:bg-teal-500/80 text-white rounded-lg text-sm font-medium transition-colors">
              Download CSV
            </button>
          </InfoCard>
        </div>
        <InfoCard title="">
          <p className="text-xs text-slate-600 text-center">
            Advisory / Paper Trading only · PDF export planned for a future phase
          </p>
        </InfoCard>
      </div>
    );
  }

  // ── Router ────────────────────────────────────────────────────────────────────
  const tabContent: Record<TabId, () => React.ReactNode> = {
    overview:   renderOverview,
    trades:     renderTrades,
    strategies: renderStrategies,
    risk:       renderRisk,
    portfolio:  renderPortfolio,
    time:       renderTime,
    sectors:    renderSectors,
    preopen:    renderPreopen,
    execution:  renderExecution,
    learning:   renderLearning,
    ai:         renderAI,
    export:     renderExport,
  };

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 p-4 sm:p-6">
      {/* Header */}
      <div className="mb-6 flex items-center justify-between flex-wrap gap-2">
        <div>
          <h1 className="text-2xl font-bold text-slate-100 flex items-center gap-2">
            <BarChart3 className="w-7 h-7 text-teal-400" />
            Paper Analytics
          </h1>
          <p className="text-slate-500 text-sm mt-0.5">
            Advanced Paper Trading Analytics · Phase 8.2 · Advisory Only
          </p>
        </div>
        <Badge label="PAPER TRADING / ADVISORY ONLY" cls="bg-amber-500/10 text-amber-400 border-amber-500/30" />
      </div>

      {/* Tabs */}
      <div className="flex flex-wrap gap-1 mb-6 border-b border-slate-800/50 pb-2">
        {TABS.map(t => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm font-medium transition-colors ${
              tab === t.id
                ? "bg-teal-500/20 text-teal-400 border border-teal-500/30"
                : "text-slate-500 hover:text-slate-300 hover:bg-slate-800/50"
            }`}
          >
            {t.icon}{t.label}
          </button>
        ))}
      </div>

      {/* Tab content */}
      <div>{tabContent[tab]()}</div>
    </div>
  );
}
