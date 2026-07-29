/**
 * MacroIntelligence.tsx — Phase 7.3
 * Economic & Macro Intelligence Hub dashboard.
 *
 * READ-ONLY. ADVISORY-ONLY.
 * This page NEVER places orders, modifies signals, or writes to any trading engine.
 */
import { useQuery } from "@tanstack/react-query";
import { apiJson } from "@/lib/api";
import { cn } from "@/lib/utils";
import {
  Globe, TrendingUp, TrendingDown, Minus, AlertTriangle, CheckCircle,
  BarChart3, DollarSign, Flame, RefreshCw, Download, Calendar,
  ArrowUpRight, ArrowDownRight, Activity, Shield,
} from "lucide-react";

// ── Query helpers ─────────────────────────────────────────────────────────────

const Q = { staleTime: 60_000, retry: 1 } as const;

function useSummary()    { return useQuery({ queryKey: ["macro-summary"],    queryFn: () => apiJson("macro-intelligence/summary"),    ...Q }); }
function useCalendar()   { return useQuery({ queryKey: ["macro-calendar"],   queryFn: () => apiJson("macro-intelligence/calendar"),   ...Q }); }
function useGlobal()     { return useQuery({ queryKey: ["macro-global"],     queryFn: () => apiJson("macro-intelligence/global"),     ...Q }); }
function useFlows()      { return useQuery({ queryKey: ["macro-flows"],      queryFn: () => apiJson("macro-intelligence/flows"),      ...Q }); }
function useCommodities(){ return useQuery({ queryKey: ["macro-commodities"],queryFn: () => apiJson("macro-intelligence/commodities"), ...Q }); }
function useBrief()      { return useQuery({ queryKey: ["macro-brief"],      queryFn: () => apiJson("macro-intelligence/brief"),      ...Q }); }

// ── UI helpers ────────────────────────────────────────────────────────────────

const TABS = [
  { id: "overview",  label: "Overview",          icon: Globe       },
  { id: "brief",     label: "Daily Brief",        icon: Activity    },
  { id: "calendar",  label: "Economic Calendar",  icon: Calendar    },
  { id: "global",    label: "Global Markets",     icon: Globe       },
  { id: "flows",     label: "Market Flows",       icon: TrendingUp  },
  { id: "currency",  label: "Currency",           icon: DollarSign  },
  { id: "commodities",label: "Commodities",       icon: Flame       },
  { id: "vix",       label: "India VIX",          icon: BarChart3   },
  { id: "impact",    label: "Macro Impact",       icon: Shield      },
];

function gradeColor(grade: string) {
  if (grade === "A+" || grade === "A") return "text-emerald-400";
  if (grade === "B") return "text-teal-400";
  if (grade === "C") return "text-amber-400";
  return "text-red-400";
}

function dirIcon(direction: string, size = 16) {
  if (direction === "BULLISH")  return <ArrowUpRight   size={size} className="text-emerald-400" />;
  if (direction === "BEARISH")  return <ArrowDownRight size={size} className="text-red-400" />;
  return <Minus size={size} className="text-slate-400" />;
}

function importanceBadge(score: number) {
  const cls =
    score >= 80 ? "bg-red-500/20 text-red-300 border border-red-500/30" :
    score >= 65 ? "bg-amber-500/20 text-amber-300 border border-amber-500/30" :
    "bg-slate-700/50 text-slate-400 border border-slate-600/30";
  return (
    <span className={cn("px-1.5 py-0.5 rounded text-[10px] font-medium", cls)}>
      {score.toFixed(0)}
    </span>
  );
}

function priorityBadge(priority: string) {
  const cls =
    priority === "CRITICAL" ? "bg-red-500/20 text-red-300 border border-red-500/30" :
    priority === "HIGH"     ? "bg-amber-500/20 text-amber-300 border border-amber-500/30" :
    "bg-slate-700/50 text-slate-400 border border-slate-600/30";
  return <span className={cn("px-1.5 py-0.5 rounded text-[10px] font-semibold", cls)}>{priority}</span>;
}

function changePctColor(pct: number) {
  if (pct > 0.3) return "text-emerald-400";
  if (pct < -0.3) return "text-red-400";
  return "text-slate-400";
}

// ── Score ring ────────────────────────────────────────────────────────────────

function ScoreRing({ score, grade, label }: { score: number; grade: string; label: string }) {
  const r = 36, cx = 44, cy = 44, stroke = 6;
  const circ = 2 * Math.PI * r;
  const dash  = (score / 100) * circ;
  return (
    <div className="flex flex-col items-center gap-1">
      <svg width={88} height={88}>
        <circle cx={cx} cy={cy} r={r} fill="none" stroke="#1e293b" strokeWidth={stroke} />
        <circle cx={cx} cy={cy} r={r} fill="none"
          stroke={grade === "A+" || grade === "A" ? "#34d399" :
                  grade === "B" ? "#2dd4bf" :
                  grade === "C" ? "#fbbf24" : "#f87171"}
          strokeWidth={stroke} strokeLinecap="round"
          strokeDasharray={`${dash} ${circ - dash}`}
          strokeDashoffset={circ / 4}
          transform={`rotate(-90 ${cx} ${cy})`} />
        <text x={cx} y={cy - 6} textAnchor="middle" fill="white" fontSize={18} fontWeight="bold">
          {score.toFixed(0)}
        </text>
        <text x={cx} y={cy + 10} textAnchor="middle" fill="#94a3b8" fontSize={11}>
          {grade}
        </text>
      </svg>
      <span className="text-xs text-slate-400">{label}</span>
    </div>
  );
}

// ── Stat card ─────────────────────────────────────────────────────────────────

function StatCard({ label, value, sub, color }: { label: string; value: string | number; sub?: string; color?: string }) {
  return (
    <div className="bg-slate-800/60 border border-slate-700/50 rounded-lg p-3">
      <p className="text-[11px] text-slate-400 mb-1">{label}</p>
      <p className={cn("text-lg font-semibold", color || "text-white")}>{value}</p>
      {sub && <p className="text-[10px] text-slate-500 mt-0.5 truncate">{sub}</p>}
    </div>
  );
}

// ── Section card ──────────────────────────────────────────────────────────────

function SectionCard({ title, children, className }: { title: string; children: React.ReactNode; className?: string }) {
  return (
    <div className={cn("bg-slate-800/40 border border-slate-700/50 rounded-xl p-4", className)}>
      <h3 className="text-sm font-semibold text-slate-200 mb-3">{title}</h3>
      {children}
    </div>
  );
}

// ── Export bar ────────────────────────────────────────────────────────────────

function ExportBar() {
  const base = (import.meta.env.BASE_URL || "").replace(/\/$/, "");
  return (
    <div className="flex gap-2">
      <a href={`${base}/api/macro-intelligence/export/csv`}
         className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-slate-700/60 hover:bg-slate-700 text-xs text-slate-300 transition-colors">
        <Download size={12} /> Export CSV
      </a>
      <a href={`${base}/api/macro-intelligence/export/json`}
         className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-slate-700/60 hover:bg-slate-700 text-xs text-slate-300 transition-colors">
        <Download size={12} /> Export JSON
      </a>
    </div>
  );
}

// ── Loading state ─────────────────────────────────────────────────────────────

function LoadingState() {
  return (
    <div className="flex items-center justify-center py-12 gap-2 text-slate-400">
      <RefreshCw size={16} className="animate-spin" />
      <span className="text-sm">Loading Macro Intelligence…</span>
    </div>
  );
}

// ── Disabled state ────────────────────────────────────────────────────────────

function DisabledState({ flag }: { flag?: string }) {
  return (
    <div className="flex flex-col items-center justify-center py-16 gap-3 text-slate-500">
      <Shield size={32} />
      <p className="text-sm font-medium">Macro Intelligence is disabled</p>
      <p className="text-xs">Set <code className="bg-slate-800 px-1 rounded">{flag || "MACRO_INTELLIGENCE_ENABLED"}=true</code></p>
    </div>
  );
}

// ── Overview tab ──────────────────────────────────────────────────────────────

function OverviewTab() {
  const { data, isLoading } = useSummary();
  const s = data as Record<string, any> | undefined;

  if (isLoading) return <LoadingState />;
  if (s?.status === "DISABLED") return <DisabledState flag={s.feature_flag} />;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-4 items-center">
        <ScoreRing score={s?.macro_score ?? 0} grade={s?.grade ?? "D"} label="Macro Score" />
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 flex-1">
          <StatCard label="Global Sentiment" value={s?.sentiment_label ?? "—"}
            sub={`Score: ${s?.global_sentiment_score?.toFixed(0) ?? "—"}/100`}
            color={s?.sentiment_label === "RISK_ON" ? "text-emerald-400" :
                   s?.sentiment_label === "RISK_OFF" ? "text-red-400" : "text-amber-400"} />
          <StatCard label="India VIX" value={s?.india_vix?.toFixed(1) ?? "—"}
            sub={s?.vix_regime ?? ""}
            color={s?.vix_risk_level === "EXTREME" ? "text-red-400" :
                   s?.vix_risk_level === "HIGH" ? "text-amber-400" : "text-teal-400"} />
          <StatCard label="FII Posture"
            value={s?.fii_posture?.replace("_", " ") ?? "—"}
            color={s?.fii_posture === "NET_BUYER" ? "text-emerald-400" :
                   s?.fii_posture === "NET_SELLER" ? "text-red-400" : "text-slate-300"} />
          <StatCard label="Inflation Risk" value={s?.inflation_risk ?? "—"}
            sub={`Crude ${s?.crude_change_pct >= 0 ? "+" : ""}${s?.crude_change_pct?.toFixed(2) ?? "0"}%`}
            color={s?.inflation_risk === "HIGH" ? "text-red-400" :
                   s?.inflation_risk === "MEDIUM" ? "text-amber-400" : "text-emerald-400"} />
        </div>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
        <StatCard label="Upcoming Events"   value={s?.upcoming_events ?? 0} />
        <StatCard label="USD/INR Change"    value={`${(s?.usd_inr_change_pct ?? 0) >= 0 ? "+" : ""}${s?.usd_inr_change_pct?.toFixed(3) ?? "0"}%`}
          color={changePctColor(s?.usd_inr_change_pct ?? 0)} />
        <StatCard label="Currency Volatility" value={s?.currency_volatility ?? "—"} />
      </div>

      {s?.next_critical_event && (
        <SectionCard title="⚡ Next Critical Event">
          <div className="flex items-start justify-between gap-2">
            <div>
              <p className="text-sm font-medium text-white">{s.next_critical_event.title}</p>
              <p className="text-xs text-slate-400 mt-0.5">{s.next_critical_event.description}</p>
              {s.next_critical_event.trading_risk && (
                <p className="text-xs text-amber-400 mt-1">⚠ {s.next_critical_event.trading_risk}</p>
              )}
            </div>
            <div className="text-right shrink-0">
              <p className="text-xs text-slate-400">{s.next_critical_event.event_date}</p>
              {priorityBadge(s.next_critical_event.priority)}
            </div>
          </div>
        </SectionCard>
      )}
    </div>
  );
}

// ── Daily Brief tab ───────────────────────────────────────────────────────────

function DailyBriefTab() {
  const { data, isLoading } = useBrief();
  const b = data as Record<string, any> | undefined;

  if (isLoading) return <LoadingState />;
  if (!b || b.status === "DISABLED") return <DisabledState />;

  const outlook = b.market_outlook;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-4">
        <ScoreRing score={b?.brief_score ?? 0} grade={b?.brief_grade ?? "D"} label="Brief Score" />
        <div className="flex-1 bg-slate-800/40 border border-slate-700/50 rounded-xl p-4">
          <div className="flex items-center gap-2 mb-2">
            <span className={cn("text-base font-bold",
              outlook?.label?.includes("BULLISH") ? "text-emerald-400" :
              outlook?.label?.includes("BEARISH") ? "text-red-400" : "text-amber-400")}>
              {outlook?.label?.replace(/_/g, " ") ?? "—"}
            </span>
          </div>
          <p className="text-sm text-slate-300">{outlook?.description}</p>
          {outlook?.notes?.length > 0 && (
            <div className="flex flex-wrap gap-1.5 mt-2">
              {outlook.notes.map((n: string, i: number) => (
                <span key={i} className="px-2 py-0.5 rounded-full bg-slate-700/60 text-[11px] text-slate-300">{n}</span>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Risk Alerts */}
      {b?.risk_alerts?.length > 0 && (
        <SectionCard title="🚨 Risk Alerts">
          <div className="space-y-2">
            {b.risk_alerts.map((a: any, i: number) => (
              <div key={i} className={cn("flex items-start gap-2 p-2.5 rounded-lg text-sm",
                a.severity === "CRITICAL" ? "bg-red-900/30 border border-red-500/30" :
                a.severity === "HIGH"     ? "bg-amber-900/30 border border-amber-500/30" :
                "bg-slate-800/60 border border-slate-700/40")}>
                <AlertTriangle size={14} className={
                  a.severity === "CRITICAL" ? "text-red-400 mt-0.5" :
                  a.severity === "HIGH" ? "text-amber-400 mt-0.5" : "text-slate-400 mt-0.5"} />
                <span className="text-slate-200">{a.message}</span>
              </div>
            ))}
          </div>
        </SectionCard>
      )}

      {/* Summaries grid */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        {b?.global_summary && (
          <SectionCard title="🌐 Global Summary">
            <p className="text-xs text-slate-300">{b.global_summary.detail}</p>
            <p className={cn("text-sm font-semibold mt-1",
              b.global_summary.label === "POSITIVE" ? "text-emerald-400" :
              b.global_summary.label === "NEGATIVE" ? "text-red-400" : "text-amber-400")}>
              {b.global_summary.label}
            </p>
          </SectionCard>
        )}
        {b?.currency_summary && (
          <SectionCard title="💱 Currency Summary">
            <p className="text-xs text-slate-300">{b.currency_summary.impact}</p>
            <p className="text-xs text-slate-400 mt-1">{b.currency_summary.dxy_impact}</p>
          </SectionCard>
        )}
        {b?.commodity_summary && (
          <SectionCard title="🛢 Commodity Summary">
            <p className="text-xs text-slate-300">{b.commodity_summary.crude_impact}</p>
            <p className="text-xs text-slate-400 mt-1">{b.commodity_summary.gold_signal}</p>
          </SectionCard>
        )}
        {b?.fii_dii_summary && (
          <SectionCard title="🏦 FII/DII Summary">
            <div className="flex gap-2">
              <span className={cn("text-xs font-semibold px-2 py-0.5 rounded",
                b.fii_dii_summary.fii_posture === "NET_BUYER" ? "bg-emerald-900/40 text-emerald-300" :
                b.fii_dii_summary.fii_posture === "NET_SELLER" ? "bg-red-900/40 text-red-300" :
                "bg-slate-700 text-slate-300")}>
                FII: {b.fii_dii_summary.fii_posture?.replace("_", " ")}
              </span>
              <span className={cn("text-xs font-semibold px-2 py-0.5 rounded",
                b.fii_dii_summary.dii_posture === "NET_BUYER" ? "bg-emerald-900/40 text-emerald-300" :
                b.fii_dii_summary.dii_posture === "NET_SELLER" ? "bg-red-900/40 text-red-300" :
                "bg-slate-700 text-slate-300")}>
                DII: {b.fii_dii_summary.dii_posture?.replace("_", " ")}
              </span>
            </div>
            {b.fii_dii_summary.top_sectors?.length > 0 && (
              <p className="text-xs text-slate-400 mt-1.5">
                Inflow sectors: {b.fii_dii_summary.top_sectors.join(", ")}
              </p>
            )}
          </SectionCard>
        )}
      </div>

      {/* Trading considerations */}
      {b?.trading_considerations?.length > 0 && (
        <SectionCard title="💡 Trading Considerations">
          <ul className="space-y-1.5">
            {b.trading_considerations.map((c: string, i: number) => (
              <li key={i} className="flex items-start gap-2 text-xs text-slate-300">
                <CheckCircle size={12} className="text-teal-400 mt-0.5 shrink-0" />
                {c}
              </li>
            ))}
          </ul>
        </SectionCard>
      )}
    </div>
  );
}

// ── Economic Calendar tab ─────────────────────────────────────────────────────

function EconomicCalendarTab() {
  const { data, isLoading } = useCalendar();
  const cal = data as Record<string, any> | undefined;

  if (isLoading) return <LoadingState />;
  if (cal?.status === "DISABLED") return <DisabledState />;

  const upcoming = cal?.upcoming || [];

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-3 gap-3">
        <StatCard label="Upcoming Events" value={cal?.upcoming_count ?? 0} />
        <StatCard label="Total Calendar"  value={cal?.total ?? 0} />
        <StatCard label="Categories"      value={cal?.categories?.length ?? 0} />
      </div>

      {cal?.next_critical && (
        <div className="bg-red-900/20 border border-red-500/30 rounded-xl p-3">
          <p className="text-xs text-red-400 font-semibold mb-1">NEXT CRITICAL EVENT</p>
          <p className="text-sm font-medium text-white">{cal.next_critical.title}</p>
          <p className="text-xs text-slate-400">{cal.next_critical.event_date}</p>
        </div>
      )}

      <SectionCard title="Upcoming Events">
        <div className="space-y-2">
          {upcoming.slice(0, 20).map((e: any) => (
            <div key={e.event_id} className="flex items-start justify-between gap-2 p-2.5 rounded-lg bg-slate-800/60 hover:bg-slate-800 transition-colors">
              <div className="flex items-start gap-2 min-w-0">
                {dirIcon(e.direction, 12)}
                <div className="min-w-0">
                  <p className="text-sm text-slate-200 truncate">{e.title}</p>
                  <p className="text-xs text-slate-500 truncate">{e.description?.slice(0, 80)}…</p>
                  {e.affected_sectors?.length > 0 && (
                    <p className="text-[10px] text-slate-500 mt-0.5">
                      {e.affected_sectors.slice(0, 4).join(" · ")}
                    </p>
                  )}
                </div>
              </div>
              <div className="shrink-0 text-right">
                <p className="text-xs text-slate-400">{e.event_date}</p>
                {importanceBadge(e.importance_score)}
              </div>
            </div>
          ))}
          {upcoming.length === 0 && (
            <p className="text-sm text-slate-500 text-center py-4">No upcoming events in range</p>
          )}
        </div>
      </SectionCard>
    </div>
  );
}

// ── Global Markets tab ────────────────────────────────────────────────────────

function GlobalMarketsTab() {
  const { data, isLoading } = useGlobal();
  const g = data as Record<string, any> | undefined;

  if (isLoading) return <LoadingState />;
  if (g?.status === "DISABLED") return <DisabledState />;

  const indices = g?.indices || [];

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <StatCard label="Global Sentiment" value={g?.global_sentiment_score?.toFixed(0) ?? "—"}
          sub={g?.sentiment_label}
          color={g?.sentiment_label === "RISK_ON" ? "text-emerald-400" :
                 g?.sentiment_label === "RISK_OFF" ? "text-red-400" : "text-amber-400"} />
        <StatCard label="Bullish Indices"  value={g?.bullish_count ?? 0} color="text-emerald-400" />
        <StatCard label="Bearish Indices"  value={g?.bearish_count ?? 0} color="text-red-400"     />
        <StatCard label="Neutral Indices"  value={g?.neutral_count ?? 0} color="text-slate-300"   />
      </div>

      {/* Asia / Europe / US sessions */}
      {["Asia", "Europe", "US"].map((session) => {
        const key = session === "Asia" ? "asia_session" : session === "Europe" ? "europe_session" : "us_session";
        const items: any[] = g?.[key] || [];
        if (!items.length) return null;
        return (
          <SectionCard key={session} title={`${session} Session`}>
            <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
              {items.map((idx: any) => (
                <div key={idx.ticker} className="bg-slate-800/60 rounded-lg p-2.5 flex items-center justify-between">
                  <div>
                    <p className="text-xs text-slate-400">{idx.name}</p>
                    <p className="text-sm font-semibold text-white">
                      {idx.price > 0 ? idx.price.toLocaleString() : "N/A"}
                    </p>
                  </div>
                  <div className="text-right">
                    <p className={cn("text-sm font-semibold", changePctColor(idx.change_pct))}>
                      {idx.change_pct >= 0 ? "+" : ""}{idx.change_pct?.toFixed(2)}%
                    </p>
                    {dirIcon(idx.direction, 14)}
                  </div>
                </div>
              ))}
            </div>
          </SectionCard>
        );
      })}

      {/* All indices fallback */}
      {(!g?.asia_session?.length && !g?.us_session?.length) && indices.length > 0 && (
        <SectionCard title="Global Indices">
          <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
            {indices.map((idx: any) => (
              <div key={idx.ticker} className="bg-slate-800/60 rounded-lg p-2.5 flex items-center justify-between">
                <div>
                  <p className="text-xs text-slate-400">{idx.name}</p>
                  <p className="text-sm font-semibold text-white">
                    {idx.price > 0 ? idx.price.toLocaleString() : "N/A"}
                  </p>
                </div>
                <div className="text-right">
                  <p className={cn("text-sm font-semibold", changePctColor(idx.change_pct))}>
                    {idx.change_pct >= 0 ? "+" : ""}{idx.change_pct?.toFixed(2)}%
                  </p>
                </div>
              </div>
            ))}
          </div>
        </SectionCard>
      )}
    </div>
  );
}

// ── Market Flows tab ──────────────────────────────────────────────────────────

function MarketFlowsTab() {
  const { data, isLoading } = useFlows();
  const f = data as Record<string, any> | undefined;

  if (isLoading) return <LoadingState />;
  if (f?.status === "DISABLED") return <DisabledState />;

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
        <div className={cn("rounded-xl p-4 border",
          f?.fii?.flow === "NET_BUYER"  ? "bg-emerald-900/20 border-emerald-500/30" :
          f?.fii?.flow === "NET_SELLER" ? "bg-red-900/20 border-red-500/30" :
          "bg-slate-800/40 border-slate-700/50")}>
          <p className="text-xs text-slate-400 mb-1">FII Activity</p>
          <p className={cn("text-lg font-bold",
            f?.fii?.flow === "NET_BUYER"  ? "text-emerald-400" :
            f?.fii?.flow === "NET_SELLER" ? "text-red-400" : "text-slate-300")}>
            {f?.fii?.flow?.replace("_", " ") ?? "—"}
          </p>
          <p className="text-xs text-slate-400 mt-1">{f?.fii?.description}</p>
        </div>
        <div className={cn("rounded-xl p-4 border",
          f?.dii?.flow === "NET_BUYER"  ? "bg-emerald-900/20 border-emerald-500/30" :
          f?.dii?.flow === "NET_SELLER" ? "bg-red-900/20 border-red-500/30" :
          "bg-slate-800/40 border-slate-700/50")}>
          <p className="text-xs text-slate-400 mb-1">DII Activity</p>
          <p className={cn("text-lg font-bold",
            f?.dii?.flow === "NET_BUYER"  ? "text-emerald-400" :
            f?.dii?.flow === "NET_SELLER" ? "text-red-400" : "text-slate-300")}>
            {f?.dii?.flow?.replace("_", " ") ?? "—"}
          </p>
          <p className="text-xs text-slate-400 mt-1">{f?.dii?.description}</p>
        </div>
        <div className="bg-slate-800/40 border border-slate-700/50 rounded-xl p-4">
          <p className="text-xs text-slate-400 mb-1">Liquidity</p>
          <p className="text-lg font-bold text-slate-200">
            {f?.liquidity?.trend?.replace(/_/g, " ") ?? "—"}
          </p>
          <p className="text-xs text-slate-400 mt-1">{f?.liquidity?.label}</p>
        </div>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <SectionCard title="Top Inflow Sectors">
          <div className="space-y-1">
            {f?.top_inflow_sectors?.map((s: string) => (
              <div key={s} className="flex items-center gap-2 py-1">
                <ArrowUpRight size={12} className="text-emerald-400" />
                <span className="text-sm text-slate-200">{s}</span>
              </div>
            )) ?? <p className="text-xs text-slate-500">No data</p>}
          </div>
        </SectionCard>
        <SectionCard title="Top Outflow Sectors">
          <div className="space-y-1">
            {f?.top_outflow_sectors?.map((s: string) => (
              <div key={s} className="flex items-center gap-2 py-1">
                <ArrowDownRight size={12} className="text-red-400" />
                <span className="text-sm text-slate-200">{s}</span>
              </div>
            )) ?? <p className="text-xs text-slate-500">No data</p>}
          </div>
        </SectionCard>
      </div>

      <SectionCard title="Sector Rotation">
        <div className="space-y-1.5">
          {f?.sector_rotation?.slice(0, 10).map((r: any) => (
            <div key={r.sector} className="flex items-center justify-between py-1">
              <span className="text-sm text-slate-200">{r.sector}</span>
              <div className="flex items-center gap-2">
                <span className="text-xs text-slate-400">{r.avg_score?.toFixed(0)}</span>
                <span className={cn("text-xs font-semibold",
                  r.direction === "INFLOW" ? "text-emerald-400" :
                  r.direction === "OUTFLOW" ? "text-red-400" : "text-slate-400")}>
                  {r.direction}
                </span>
              </div>
            </div>
          ))}
        </div>
      </SectionCard>

      <p className="text-[10px] text-slate-600 text-center">{f?.disclaimer}</p>
    </div>
  );
}

// ── Currency tab ──────────────────────────────────────────────────────────────

function CurrencyTab() {
  const { data, isLoading } = useCommodities();
  const d = data as Record<string, any> | undefined;
  const curr = d?.currency;

  if (isLoading) return <LoadingState />;
  if (d?.status === "DISABLED") return <DisabledState />;

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
        <StatCard label="Currency Volatility" value={curr?.currency_volatility ?? "—"} />
        <StatCard label="Currency Risk Score" value={curr?.currency_risk_score?.toFixed(0) ?? "—"}
          color={curr?.currency_risk_score >= 65 ? "text-red-400" :
                 curr?.currency_risk_score >= 50 ? "text-amber-400" : "text-emerald-400"} />
        <StatCard label="USD/INR"
          value={curr?.usd_inr?.price?.toFixed(3) ?? "—"}
          sub={`${curr?.usd_inr?.change_pct >= 0 ? "+" : ""}${curr?.usd_inr?.change_pct?.toFixed(3)}% today`}
          color={changePctColor(curr?.usd_inr?.change_pct ?? 0)} />
      </div>

      <SectionCard title="Currency Pairs">
        <div className="space-y-2">
          {curr?.pairs?.map((p: any) => (
            <div key={p.ticker} className="flex items-center justify-between py-2 border-b border-slate-700/30 last:border-0">
              <span className="text-sm font-medium text-slate-200">{p.name}</span>
              <div className="flex items-center gap-3">
                <span className="text-sm text-white">{p.price > 0 ? p.price.toFixed(3) : "N/A"}</span>
                <span className={cn("text-sm font-semibold", changePctColor(p.change_pct))}>
                  {p.change_pct >= 0 ? "+" : ""}{p.change_pct?.toFixed(3)}%
                </span>
              </div>
            </div>
          ))}
        </div>
      </SectionCard>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <SectionCard title="USD/INR Impact">
          <p className="text-xs text-slate-300">{curr?.usd_inr_impact}</p>
        </SectionCard>
        <SectionCard title="Dollar Index Impact">
          <p className="text-xs text-slate-300">{curr?.dxy_impact}</p>
        </SectionCard>
      </div>
    </div>
  );
}

// ── Commodities tab ───────────────────────────────────────────────────────────

function CommoditiesTab() {
  const { data, isLoading } = useCommodities();
  const d = data as Record<string, any> | undefined;
  const comm = d?.commodities;

  if (isLoading) return <LoadingState />;
  if (d?.status === "DISABLED") return <DisabledState />;

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <StatCard label="Commodity Risk" value={comm?.commodity_risk_score?.toFixed(0) ?? "—"}
          color={comm?.commodity_risk_score >= 65 ? "text-red-400" : "text-emerald-400"} />
        <StatCard label="Inflation Risk" value={comm?.inflation_risk ?? "—"}
          color={comm?.inflation_risk === "HIGH" ? "text-red-400" :
                 comm?.inflation_risk === "MEDIUM" ? "text-amber-400" : "text-emerald-400"} />
        <StatCard label="Bullish Commodities" value={comm?.bullish_count ?? 0} color="text-emerald-400" />
        <StatCard label="Bearish Commodities" value={comm?.bearish_count ?? 0} color="text-red-400" />
      </div>

      <SectionCard title="Commodity Prices">
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
          {comm?.commodities?.map((c: any) => (
            <div key={c.ticker} className="bg-slate-800/60 rounded-lg p-3 flex items-center justify-between">
              <div>
                <p className="text-sm font-medium text-slate-200">{c.name}</p>
                <p className="text-xs text-slate-500">{c.unit}</p>
                {c.negative_sectors?.length > 0 && (
                  <p className="text-[10px] text-red-400 mt-0.5">⬇ {c.negative_sectors.join(", ")}</p>
                )}
              </div>
              <div className="text-right">
                <p className="text-sm font-semibold text-white">
                  {c.price > 0 ? c.price.toFixed(2) : "N/A"}
                </p>
                <p className={cn("text-xs font-semibold", changePctColor(c.change_pct))}>
                  {c.change_pct >= 0 ? "+" : ""}{c.change_pct?.toFixed(2)}%
                </p>
                <p className={cn("text-[10px] mt-0.5",
                  c.trend === "BULLISH" ? "text-emerald-400" :
                  c.trend === "BEARISH" ? "text-red-400" : "text-slate-400")}>
                  {c.trend} · {c.volatility}
                </p>
              </div>
            </div>
          ))}
        </div>
      </SectionCard>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <SectionCard title="Crude Oil Impact">
          <p className="text-xs text-slate-300">{comm?.crude_impact}</p>
        </SectionCard>
        <SectionCard title="Gold Signal">
          <p className="text-xs text-slate-300">{comm?.gold_signal}</p>
        </SectionCard>
      </div>
    </div>
  );
}

// ── India VIX tab ─────────────────────────────────────────────────────────────

function IndiaVixTab() {
  const { data, isLoading } = useCommodities();
  const d = data as Record<string, any> | undefined;
  const vix = d?.volatility;

  if (isLoading) return <LoadingState />;
  if (d?.status === "DISABLED") return <DisabledState />;

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <StatCard label="India VIX"   value={vix?.india_vix?.current?.toFixed(1) ?? "—"}
          color={vix?.risk_level === "EXTREME" ? "text-red-400" :
                 vix?.risk_level === "HIGH"    ? "text-amber-400" :
                 vix?.risk_level === "MEDIUM"  ? "text-yellow-400" : "text-emerald-400"} />
        <StatCard label="Regime"      value={vix?.regime ?? "—"} />
        <StatCard label="Risk Level"  value={vix?.risk_level ?? "—"}
          color={vix?.risk_level === "EXTREME" ? "text-red-400" :
                 vix?.risk_level === "HIGH"    ? "text-amber-400" : "text-emerald-400"} />
        <StatCard label="Options Env" value={vix?.options_environment ?? "—"}
          color={vix?.options_environment === "EXPENSIVE" ? "text-amber-400" :
                 vix?.options_environment === "CHEAP"     ? "text-emerald-400" : "text-slate-300"} />
      </div>

      <SectionCard title="VIX Interpretation">
        <p className="text-sm text-slate-200">{vix?.interpretation}</p>
        <p className="text-xs text-slate-400 mt-2">{vix?.trading_implication}</p>
      </SectionCard>

      <SectionCard title="VIX Zones">
        {Object.entries(vix?.vix_zones ?? {}).filter(([k]) => k !== "current_zone").map(([label, range]) => (
          <div key={label} className={cn("flex justify-between py-1.5 border-b border-slate-700/30 last:border-0",
            vix?.vix_zones?.current_zone?.toLowerCase() === label ? "text-amber-300 font-semibold" : "text-slate-400")}>
            <span className="text-sm capitalize">{label.replace("_", " ")}</span>
            <span className="text-sm">{String(range)}</span>
          </div>
        ))}
      </SectionCard>

      {vix?.india_vix?.change_pct != null && (
        <SectionCard title="Today's Change">
          <p className={cn("text-2xl font-bold",
            vix.india_vix.change_pct >= 0 ? "text-red-400" : "text-emerald-400")}>
            {vix.india_vix.change_pct >= 0 ? "+" : ""}{vix.india_vix.change_pct?.toFixed(2)}%
          </p>
          <p className="text-xs text-slate-400 mt-1">
            Prev close: {vix.india_vix.prev_close?.toFixed(1)}
          </p>
        </SectionCard>
      )}
    </div>
  );
}

// ── Macro Impact tab ──────────────────────────────────────────────────────────

function MacroImpactTab() {
  const { data: calData, isLoading } = useCalendar();
  const cal = calData as Record<string, any> | undefined;

  if (isLoading) return <LoadingState />;
  if (cal?.status === "DISABLED") return <DisabledState />;

  const highImpact = cal?.high_importance || cal?.upcoming?.filter((e: any) => e.importance_score >= 75) || [];

  return (
    <div className="space-y-4">
      <SectionCard title="High-Impact Upcoming Events">
        <div className="space-y-3">
          {highImpact.slice(0, 10).map((e: any) => (
            <div key={e.event_id} className="p-3 rounded-lg bg-slate-800/60 border border-slate-700/30">
              <div className="flex items-start justify-between gap-2 mb-2">
                <div className="flex items-center gap-2">
                  {dirIcon(e.direction, 14)}
                  <span className="text-sm font-medium text-white">{e.title}</span>
                </div>
                <div className="flex items-center gap-1.5 shrink-0">
                  {priorityBadge(e.priority)}
                  {importanceBadge(e.importance_score)}
                </div>
              </div>
              <p className="text-xs text-slate-400">{e.description?.slice(0, 100)}</p>
              {e.historical_context && (
                <p className="text-xs text-teal-400 mt-1.5">📊 {e.historical_context?.slice(0, 120)}</p>
              )}
              {e.trading_risk && (
                <p className="text-xs text-amber-400 mt-1">⚠ {e.trading_risk?.slice(0, 100)}</p>
              )}
              {e.opportunity && (
                <p className="text-xs text-emerald-400 mt-1">💡 {e.opportunity?.slice(0, 100)}</p>
              )}
              <div className="flex items-center gap-3 mt-2">
                <span className="text-[10px] text-slate-500">{e.event_date}</span>
                {e.affected_sectors?.length > 0 && (
                  <span className="text-[10px] text-slate-500">
                    Sectors: {e.affected_sectors.slice(0, 3).join(", ")}
                  </span>
                )}
              </div>
            </div>
          ))}
          {highImpact.length === 0 && (
            <p className="text-sm text-slate-500 text-center py-4">No high-impact events in range</p>
          )}
        </div>
      </SectionCard>
    </div>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function MacroIntelligence() {
  const [activeTab, setActiveTab] = React.useState("overview");
  const { refetch: refetchSummary }    = useSummary();
  const { refetch: refetchBrief }      = useBrief();
  const { refetch: refetchCalendar }   = useCalendar();
  const { refetch: refetchGlobal }     = useGlobal();
  const { refetch: refetchFlows }      = useFlows();
  const { refetch: refetchCommodities }= useCommodities();

  function refreshAll() {
    refetchSummary(); refetchBrief(); refetchCalendar();
    refetchGlobal(); refetchFlows(); refetchCommodities();
  }

  return (
    <div className="flex flex-col min-h-full">
      {/* Header */}
      <div className="flex flex-wrap items-start justify-between gap-3 px-4 pt-4 pb-3 border-b border-slate-700/50">
        <div>
          <div className="flex items-center gap-2">
            <Globe size={20} className="text-teal-400" />
            <h1 className="text-lg font-bold text-white">Economic & Macro Intelligence</h1>
            <span className="px-2 py-0.5 rounded-full bg-amber-500/20 text-amber-300 border border-amber-500/30 text-[11px] font-semibold">
              ADVISORY ONLY
            </span>
          </div>
          <p className="text-xs text-slate-400 mt-0.5">
            RBI policy · Global markets · FII/DII flows · Currency · Commodities · India VIX
          </p>
        </div>
        <div className="flex items-center gap-2">
          <ExportBar />
          <button onClick={refreshAll}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-teal-700/40 hover:bg-teal-700/60 text-xs text-teal-300 transition-colors">
            <RefreshCw size={12} /> Refresh
          </button>
        </div>
      </div>

      {/* Tabs */}
      <div className="flex gap-1 px-4 pt-3 overflow-x-auto scrollbar-none">
        {TABS.map(({ id, label, icon: Icon }) => (
          <button key={id} onClick={() => setActiveTab(id)}
            className={cn(
              "flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium whitespace-nowrap transition-colors",
              activeTab === id
                ? "bg-teal-600/30 text-teal-300 border border-teal-500/40"
                : "text-slate-400 hover:text-slate-200 hover:bg-slate-700/40",
            )}>
            <Icon size={12} />
            {label}
          </button>
        ))}
      </div>

      {/* Tab content */}
      <div className="flex-1 overflow-y-auto px-4 py-4">
        {activeTab === "overview"    && <OverviewTab />}
        {activeTab === "brief"       && <DailyBriefTab />}
        {activeTab === "calendar"    && <EconomicCalendarTab />}
        {activeTab === "global"      && <GlobalMarketsTab />}
        {activeTab === "flows"       && <MarketFlowsTab />}
        {activeTab === "currency"    && <CurrencyTab />}
        {activeTab === "commodities" && <CommoditiesTab />}
        {activeTab === "vix"         && <IndiaVixTab />}
        {activeTab === "impact"      && <MacroImpactTab />}
      </div>

      {/* Footer */}
      <div className="px-4 py-2 border-t border-slate-700/30 flex justify-center">
        <p className="text-[10px] text-slate-600">
          Macro Intelligence · Read-only · Advisory Only · Paper Trading · ApexQuant AI
        </p>
      </div>
    </div>
  );
}

// React import needed for useState usage at module level
import React from "react";
