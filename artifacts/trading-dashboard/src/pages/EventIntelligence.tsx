/**
 * EventIntelligence.tsx — Phase 7.2
 * Event & Corporate Intelligence Hub dashboard.
 *
 * READ-ONLY · ADVISORY-ONLY · PAPER TRADING
 */
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "wouter";
import {
  AlertCircle, AlertTriangle, ArrowDownRight, ArrowUpRight,
  BarChart3, BookOpen, Brain, Building2, CalendarDays, CheckCircle,
  ChevronDown, ChevronRight, Clock, Download, ExternalLink,
  FileText, Globe2, Info, Minus, Newspaper, RefreshCw,
  Shield, ShieldAlert, Sparkles, TrendingDown, TrendingUp,
  TriangleAlert, Zap,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { apiJson } from "@/lib/api";

// ── Types ─────────────────────────────────────────────────────────────────────

interface EventItem {
  event_id:           string;
  event_type:         string;
  sub_type:           string;
  title:              string;
  description:        string;
  symbol?:            string;
  sector?:            string;
  event_date?:        string;
  importance_score:   number;
  confidence_score:   number;
  impact_direction:   string;
  expected_volatility: number;
  expected_duration:  string;
  priority:           string;
  affected_stocks:    string[];
  affected_sectors:   string[];
  trading_risk?:      string;
  opportunity?:       string;
  source:             string;
}

interface Summary {
  status:              string;
  available:           boolean;
  intelligence_score:  number;
  grade:               string;
  trend:               string;
  total_events:        number;
  corporate_count:     number;
  regulatory_count:    number;
  news_count:          number;
  high_priority_count: number;
  today_events:        number;
  upcoming_events:     number;
  advisory_only:       boolean;
  top_events:          EventItem[];
  impact?: {
    total_events:      number;
    direction_counts:  Record<string, number>;
    top_risks:         Array<{ symbol?: string; title: string; risk?: string }>;
    top_opportunities: Array<{ symbol?: string; title: string; opportunity?: string }>;
    sector_heat:       Record<string, number>;
    high_importance_count: number;
  };
}

interface Brief {
  status:              string;
  available:           boolean;
  date:                string;
  intelligence_score:  number;
  grade:               string;
  market_tone:         string;
  summary:             string;
  today_event_count:   number;
  today_important_events: EventItem[];
  stocks_requiring_attention: Array<{ symbol: string; event_count: number; top_event?: string }>;
  high_risk_stocks:    Array<{ symbol: string; sector?: string; risk: string; score: number; direction: string }>;
  high_opportunity_stocks: Array<{ symbol: string; sector?: string; opportunity: string; score: number }>;
  sector_highlights:   Array<{ sector: string; max_importance: number; event_count: number; top_event: string }>;
  volatility_events:   Array<{ symbol?: string; title: string; expected_volatility: number; priority: string }>;
  critical_alerts:     Array<{ title: string; symbol?: string; event_date?: string; risk?: string }>;
}

interface Timeline {
  available:           boolean;
  today:               EventItem[];
  today_count:         number;
  past_7_days:         EventItem[];
  past_7_count:        number;
  upcoming:            EventItem[];
  upcoming_count:      number;
  daily_calendar:      Record<string, Array<{ title: string; symbol?: string; priority: string }>>;
}

// ── Small helpers ─────────────────────────────────────────────────────────────

const fmt1 = (n?: number) => (n ?? 0).toFixed(1);

function gradeColor(g: string) {
  if (g === "A+") return "text-emerald-400";
  if (g === "A")  return "text-green-400";
  if (g === "B")  return "text-blue-400";
  if (g === "C")  return "text-amber-400";
  return "text-red-400";
}

function scoreColor(s: number) {
  if (s >= 80) return "text-emerald-400";
  if (s >= 60) return "text-blue-400";
  if (s >= 45) return "text-amber-400";
  return "text-red-400";
}

function impactColor(dir: string) {
  if (dir === "BULLISH")  return "text-emerald-400";
  if (dir === "BEARISH")  return "text-red-400";
  if (dir === "VOLATILE") return "text-amber-400";
  return "text-slate-400";
}

function impactBg(dir: string) {
  if (dir === "BULLISH")  return "bg-emerald-500/10 border-emerald-500/30";
  if (dir === "BEARISH")  return "bg-red-500/10 border-red-500/30";
  if (dir === "VOLATILE") return "bg-amber-500/10 border-amber-500/30";
  return "bg-slate-700/30 border-slate-600/30";
}

function ImpactIcon({ dir }: { dir: string }) {
  if (dir === "BULLISH")  return <ArrowUpRight   className="w-3.5 h-3.5 text-emerald-400" />;
  if (dir === "BEARISH")  return <ArrowDownRight  className="w-3.5 h-3.5 text-red-400" />;
  if (dir === "VOLATILE") return <TriangleAlert   className="w-3.5 h-3.5 text-amber-400" />;
  return                         <Minus           className="w-3.5 h-3.5 text-slate-400" />;
}

function priorityDot(priority: string) {
  const c = priority === "CRITICAL" ? "bg-red-500"
          : priority === "HIGH"     ? "bg-amber-500"
          : priority === "MEDIUM"   ? "bg-blue-500"
          :                           "bg-slate-500";
  return <span className={cn("w-2 h-2 rounded-full inline-block shrink-0 mt-1.5", c)} />;
}

function ToneTag({ tone }: { tone: string }) {
  const [color, bg] =
    tone.includes("BULLISH")  ? ["text-emerald-300", "bg-emerald-500/15 border-emerald-500/30"]
  : tone.includes("BEARISH")  ? ["text-red-300",     "bg-red-500/15 border-red-500/30"]
  : tone.includes("VOLATILE") ? ["text-amber-300",   "bg-amber-500/15 border-amber-500/30"]
  :                              ["text-slate-300",   "bg-slate-700/30 border-slate-600/30"];
  return (
    <span className={cn("px-2.5 py-1 rounded-full border text-xs font-semibold", bg, color)}>
      {tone}
    </span>
  );
}

// ── Section card ──────────────────────────────────────────────────────────────

function SectionCard({
  title, icon, children, className,
}: {
  title: string; icon: React.ReactNode; children: React.ReactNode; className?: string;
}) {
  const [open, setOpen] = useState(true);
  return (
    <div className={cn("bg-slate-900/70 border border-slate-700/50 rounded-xl overflow-hidden", className)}>
      <button
        onClick={() => setOpen(o => !o)}
        className="w-full flex items-center justify-between px-4 py-3 hover:bg-slate-800/40 transition-colors"
      >
        <div className="flex items-center gap-2 text-sm font-semibold text-slate-200">
          {icon}{title}
        </div>
        <ChevronDown className={cn("w-4 h-4 text-slate-400 transition-transform", open && "rotate-180")} />
      </button>
      {open && <div className="px-4 pb-4">{children}</div>}
    </div>
  );
}

// ── KPI card ──────────────────────────────────────────────────────────────────

function KpiCard({ label, value, sub, color }: {
  label: string; value: React.ReactNode; sub?: string; color?: string;
}) {
  return (
    <div className="bg-slate-800/60 border border-slate-700/50 rounded-lg p-3 space-y-0.5">
      <p className="text-xs text-slate-400">{label}</p>
      <p className={cn("text-lg font-bold text-slate-100", color)}>{value}</p>
      {sub && <p className="text-xs text-slate-500">{sub}</p>}
    </div>
  );
}

// ── Score ring ────────────────────────────────────────────────────────────────

function ScoreRing({ score, label }: { score: number; label: string }) {
  const r    = 52;
  const circ = 2 * Math.PI * r;
  const fill = (Math.min(score, 100) / 100) * circ;
  const color = score >= 80 ? "#34d399" : score >= 60 ? "#3b82f6" : score >= 45 ? "#f59e0b" : "#f87171";
  return (
    <div className="flex flex-col items-center gap-1">
      <svg width="120" height="120" viewBox="0 0 120 120">
        <circle cx="60" cy="60" r={r} fill="none" stroke="#1e293b" strokeWidth="10" />
        <circle cx="60" cy="60" r={r} fill="none" stroke={color} strokeWidth="10"
          strokeDasharray={`${fill} ${circ - fill}`} strokeLinecap="round"
          transform="rotate(-90 60 60)"
          style={{ transition: "stroke-dasharray 0.5s ease" }} />
        <text x="60" y="56" textAnchor="middle" fill={color} fontSize="22" fontWeight="bold">
          {Math.round(score)}
        </text>
        <text x="60" y="72" textAnchor="middle" fill="#94a3b8" fontSize="11">/100</text>
      </svg>
      <p className="text-xs text-slate-400 font-medium">{label}</p>
    </div>
  );
}

// ── Event row ─────────────────────────────────────────────────────────────────

function EventRow({ e, showDate }: { e: EventItem; showDate?: boolean }) {
  return (
    <div className={cn(
      "flex items-start gap-2.5 p-2.5 rounded-lg border text-sm",
      impactBg(e.impact_direction)
    )}>
      {priorityDot(e.priority)}
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-1.5 flex-wrap">
          <ImpactIcon dir={e.impact_direction} />
          <span className="font-medium text-slate-100 line-clamp-1">{e.title}</span>
          {e.symbol && (
            <span className="text-xs px-1.5 py-0.5 rounded bg-slate-700 text-slate-300">{e.symbol}</span>
          )}
        </div>
        <p className="text-xs text-slate-400 mt-0.5 line-clamp-2">{e.description}</p>
        <div className="flex items-center gap-3 mt-1 flex-wrap">
          {showDate && e.event_date && (
            <span className="text-xs text-slate-500"><Clock className="w-3 h-3 inline mr-0.5" />{e.event_date}</span>
          )}
          <span className={cn("text-xs font-medium", scoreColor(e.importance_score))}>
            Score {fmt1(e.importance_score)}
          </span>
          <span className="text-xs text-slate-500">{e.sub_type.replace(/_/g, " ")}</span>
          {e.opportunity && (
            <span className="text-xs text-emerald-400 truncate max-w-[200px]">💡 {e.opportunity}</span>
          )}
        </div>
      </div>
    </div>
  );
}

// ── Disabled state ────────────────────────────────────────────────────────────

function DisabledState() {
  return (
    <div className="flex flex-col items-center justify-center py-20 text-center gap-4">
      <CalendarDays className="w-12 h-12 text-slate-600" />
      <div>
        <h2 className="text-lg font-semibold text-slate-400 mb-2">Event Intelligence Disabled</h2>
        <p className="text-sm text-slate-500">
          Set{" "}
          <code className="bg-slate-800 px-1.5 py-0.5 rounded text-amber-300 text-xs">
            EVENT_INTELLIGENCE_ENABLED=true
          </code>{" "}
          to enable.
        </p>
      </div>
    </div>
  );
}

// ── Overview section ──────────────────────────────────────────────────────────

function OverviewSection({ data }: { data: Summary }) {
  const impact = data.impact;
  return (
    <div className="space-y-4">
      {/* Score + KPIs */}
      <div className="flex flex-col md:flex-row items-center gap-6 bg-slate-800/40 border border-slate-700/40 rounded-xl p-4">
        <ScoreRing score={data.intelligence_score} label="Event Intelligence" />
        <div className="flex-1 grid grid-cols-2 md:grid-cols-4 gap-3 w-full">
          <KpiCard label="Grade"         value={<span className={gradeColor(data.grade)}>{data.grade}</span>} sub={`Trend: ${data.trend}`} />
          <KpiCard label="Total Events"  value={data.total_events} />
          <KpiCard label="High Priority" value={data.high_priority_count} color={(data.high_priority_count ?? 0) > 0 ? "text-amber-400" : "text-emerald-400"} />
          <KpiCard label="Today"         value={data.today_events} sub={`${data.upcoming_events} upcoming`} />
        </div>
      </div>

      {/* Category counts */}
      <div className="grid grid-cols-3 gap-3">
        <KpiCard label="Corporate Events" value={data.corporate_count} color="text-blue-400" />
        <KpiCard label="Regulatory Events" value={data.regulatory_count} color="text-amber-400" />
        <KpiCard label="News & Market" value={data.news_count} color="text-purple-400" />
      </div>

      {/* Impact breakdown */}
      {impact && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <KpiCard label="Bullish Events"  value={impact.direction_counts["BULLISH"]  ?? 0} color="text-emerald-400" />
          <KpiCard label="Bearish Events"  value={impact.direction_counts["BEARISH"]  ?? 0} color="text-red-400" />
          <KpiCard label="Volatile Events" value={impact.direction_counts["VOLATILE"] ?? 0} color="text-amber-400" />
          <KpiCard label="High Importance" value={impact.high_importance_count ?? 0}         color="text-blue-400" />
        </div>
      )}

      {/* Top events */}
      {data.top_events?.length > 0 && (
        <div>
          <p className="text-xs text-slate-400 uppercase tracking-wider font-semibold mb-2">Top Events Today</p>
          <div className="space-y-2">
            {data.top_events.slice(0, 4).map(e => (
              <EventRow key={e.event_id} e={e} showDate />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

// ── Brief section ─────────────────────────────────────────────────────────────

function BriefSection({ data }: { data: Brief }) {
  if (!data.available) return <p className="text-slate-500 text-sm">Brief unavailable.</p>;
  return (
    <div className="space-y-4">
      <div className="flex items-start gap-3 flex-wrap">
        <ToneTag tone={data.market_tone} />
        <p className="text-sm text-slate-300 flex-1">{data.summary}</p>
      </div>

      {data.critical_alerts?.length > 0 && (
        <div className="space-y-2">
          <p className="text-xs text-red-400 uppercase tracking-wider font-semibold">Critical Alerts</p>
          {data.critical_alerts.map((a, i) => (
            <div key={i} className="flex items-start gap-2 bg-red-900/20 border border-red-700/40 rounded-lg px-3 py-2">
              <AlertCircle className="w-4 h-4 text-red-400 mt-0.5 shrink-0" />
              <div>
                <p className="text-sm text-red-300 font-medium">{a.title}</p>
                {a.risk && <p className="text-xs text-red-400/70 mt-0.5">{a.risk}</p>}
              </div>
            </div>
          ))}
        </div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {/* High-risk stocks */}
        {data.high_risk_stocks?.length > 0 && (
          <div>
            <p className="text-xs text-amber-400 uppercase tracking-wider font-semibold mb-2 flex items-center gap-1.5">
              <ShieldAlert className="w-3.5 h-3.5" /> High Risk
            </p>
            <div className="space-y-1.5">
              {data.high_risk_stocks.map((s, i) => (
                <div key={i} className="flex items-start gap-2 bg-amber-900/15 border border-amber-700/30 rounded-lg px-3 py-2">
                  <ArrowDownRight className="w-3.5 h-3.5 text-amber-400 mt-0.5 shrink-0" />
                  <div>
                    <p className="text-sm font-medium text-slate-200">{s.symbol} <span className="text-amber-400 text-xs">({s.direction})</span></p>
                    <p className="text-xs text-slate-400 mt-0.5">{s.risk}</p>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* High-opportunity stocks */}
        {data.high_opportunity_stocks?.length > 0 && (
          <div>
            <p className="text-xs text-emerald-400 uppercase tracking-wider font-semibold mb-2 flex items-center gap-1.5">
              <Sparkles className="w-3.5 h-3.5" /> Opportunities
            </p>
            <div className="space-y-1.5">
              {data.high_opportunity_stocks.map((s, i) => (
                <div key={i} className="flex items-start gap-2 bg-emerald-900/15 border border-emerald-700/30 rounded-lg px-3 py-2">
                  <ArrowUpRight className="w-3.5 h-3.5 text-emerald-400 mt-0.5 shrink-0" />
                  <div>
                    <p className="text-sm font-medium text-slate-200">{s.symbol}</p>
                    <p className="text-xs text-slate-400 mt-0.5 line-clamp-2">{s.opportunity}</p>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>

      {/* Sector highlights */}
      {data.sector_highlights?.length > 0 && (
        <div>
          <p className="text-xs text-slate-400 uppercase tracking-wider font-semibold mb-2">Sector Highlights</p>
          <div className="grid grid-cols-2 md:grid-cols-3 gap-2">
            {data.sector_highlights.map(s => (
              <div key={s.sector} className="bg-slate-800/50 border border-slate-700/40 rounded-lg p-2.5">
                <p className="text-xs font-semibold text-slate-200">{s.sector}</p>
                <p className={cn("text-sm font-bold mt-0.5", scoreColor(s.max_importance))}>{fmt1(s.max_importance)}/100</p>
                <p className="text-xs text-slate-500 mt-0.5">{s.event_count} event{s.event_count !== 1 ? "s" : ""}</p>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Volatility events */}
      {data.volatility_events?.length > 0 && (
        <div>
          <p className="text-xs text-amber-400 uppercase tracking-wider font-semibold mb-2">Volatility Alerts</p>
          <div className="space-y-1.5">
            {data.volatility_events.map((v, i) => (
              <div key={i} className="flex items-center gap-2 bg-amber-900/10 border border-amber-700/30 rounded-lg px-3 py-2">
                <TriangleAlert className="w-3.5 h-3.5 text-amber-400 shrink-0" />
                <span className="text-sm text-slate-300 flex-1 line-clamp-1">{v.title}</span>
                <span className="text-xs font-semibold text-amber-400 shrink-0">±{v.expected_volatility.toFixed(1)}%</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

// ── Timeline section ──────────────────────────────────────────────────────────

function TimelineSection({ data }: { data: Timeline }) {
  if (!data.available) return <p className="text-slate-500 text-sm">Timeline unavailable.</p>;

  const buckets: Array<{ label: string; events: EventItem[]; color: string }> = [
    { label: `Today (${data.today_count})`,            events: data.today,      color: "text-emerald-400" },
    { label: `Past 7 Days (${data.past_7_count})`,     events: data.past_7_days, color: "text-blue-400" },
    { label: `Upcoming (${data.upcoming_count})`,      events: data.upcoming,   color: "text-amber-400" },
  ];

  return (
    <div className="space-y-4">
      {/* 7-day calendar strip */}
      {Object.keys(data.daily_calendar).length > 0 && (
        <div>
          <p className="text-xs text-slate-400 uppercase tracking-wider font-semibold mb-2">7-Day Calendar</p>
          <div className="flex gap-2 overflow-x-auto pb-1">
            {Object.entries(data.daily_calendar).map(([date, items]) => (
              <div key={date} className="shrink-0 bg-slate-800/50 border border-slate-700/40 rounded-lg p-2.5 min-w-[120px]">
                <p className="text-xs font-semibold text-slate-300">{date.slice(5)}</p>
                {items.slice(0, 2).map((item, i) => (
                  <p key={i} className="text-xs text-slate-500 mt-0.5 line-clamp-1">{item.symbol || "—"} {item.title.slice(0, 20)}</p>
                ))}
                {items.length > 2 && <p className="text-xs text-slate-600">+{items.length - 2} more</p>}
              </div>
            ))}
          </div>
        </div>
      )}

      {buckets.map(b => b.events.length > 0 && (
        <div key={b.label}>
          <p className={cn("text-xs uppercase tracking-wider font-semibold mb-2", b.color)}>{b.label}</p>
          <div className="space-y-2">
            {b.events.slice(0, 5).map(e => (
              <EventRow key={e.event_id} e={e} showDate />
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}

// ── Corporate / Regulatory / News list sections ────────────────────────────────

function EventListSection({ events, emptyMsg }: { events: EventItem[]; emptyMsg?: string }) {
  if (!events?.length) {
    return <p className="text-slate-500 text-sm py-2">{emptyMsg ?? "No events."}</p>;
  }
  return (
    <div className="space-y-2">
      {events.slice(0, 8).map(e => <EventRow key={e.event_id} e={e} showDate />)}
    </div>
  );
}

// ── Export bar ────────────────────────────────────────────────────────────────

function ExportBar() {
  return (
    <div className="flex items-center gap-2 flex-wrap">
      <a
        href={`${import.meta.env.BASE_URL}api/event-intelligence/export/csv`}
        className="flex items-center gap-1.5 px-3 py-1.5 bg-slate-800 border border-slate-700/50 rounded-lg text-slate-300 text-xs hover:bg-slate-700 transition-colors"
        download
      >
        <Download className="w-3.5 h-3.5" /> Export CSV
      </a>
      <a
        href={`${import.meta.env.BASE_URL}api/event-intelligence/export/json`}
        className="flex items-center gap-1.5 px-3 py-1.5 bg-slate-800 border border-slate-700/50 rounded-lg text-slate-300 text-xs hover:bg-slate-700 transition-colors"
        download
      >
        <Download className="w-3.5 h-3.5" /> Export JSON
      </a>
    </div>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function EventIntelligence() {
  const [activeTab, setActiveTab] = useState<"overview"|"brief"|"corporate"|"news"|"regulatory"|"timeline">("overview");

  const { data: summary, isLoading: loadSummary, refetch: refetchSummary } = useQuery<Summary>({
    queryKey: ["ei-summary"],
    queryFn: () => apiJson<Summary>("event-intelligence/summary"),
    refetchInterval: 90_000,
    staleTime: 60_000,
  });

  const { data: brief, isLoading: loadBrief } = useQuery<Brief>({
    queryKey: ["ei-brief"],
    queryFn: () => apiJson<Brief>("event-intelligence/brief"),
    refetchInterval: 120_000,
    staleTime: 90_000,
    enabled: activeTab === "brief",
  });

  const { data: corporateData, isLoading: loadCorp } = useQuery<{ events: EventItem[] }>({
    queryKey: ["ei-corporate"],
    queryFn: () => apiJson("event-intelligence/corporate"),
    refetchInterval: 120_000,
    staleTime: 90_000,
    enabled: activeTab === "corporate",
  });

  const { data: newsData, isLoading: loadNews } = useQuery<{ events: EventItem[] }>({
    queryKey: ["ei-news"],
    queryFn: () => apiJson("event-intelligence/news"),
    refetchInterval: 120_000,
    staleTime: 90_000,
    enabled: activeTab === "news",
  });

  const { data: regulatoryData, isLoading: loadReg } = useQuery<{ events: EventItem[]; asm_watch: string[]; fo_ban: string[] }>({
    queryKey: ["ei-regulatory"],
    queryFn: () => apiJson("event-intelligence/regulatory"),
    refetchInterval: 120_000,
    staleTime: 90_000,
    enabled: activeTab === "regulatory",
  });

  const { data: timelineData, isLoading: loadTimeline } = useQuery<Timeline>({
    queryKey: ["ei-timeline"],
    queryFn: () => apiJson("event-intelligence/timeline"),
    refetchInterval: 120_000,
    staleTime: 90_000,
    enabled: activeTab === "timeline",
  });

  // Feature disabled
  if (!loadSummary && summary?.status === "DISABLED") {
    return <DisabledState />;
  }

  const isLoading = loadSummary && !summary;

  const tabs: Array<{ id: typeof activeTab; label: string; icon: React.ReactNode }> = [
    { id: "overview",   label: "Overview",    icon: <BarChart3    className="w-3.5 h-3.5" /> },
    { id: "brief",      label: "Daily Brief", icon: <FileText     className="w-3.5 h-3.5" /> },
    { id: "corporate",  label: "Corporate",   icon: <Building2    className="w-3.5 h-3.5" /> },
    { id: "news",       label: "News",        icon: <Newspaper    className="w-3.5 h-3.5" /> },
    { id: "regulatory", label: "Regulatory",  icon: <Shield       className="w-3.5 h-3.5" /> },
    { id: "timeline",   label: "Timeline",    icon: <CalendarDays className="w-3.5 h-3.5" /> },
  ];

  return (
    <div className="p-4 md:p-6 max-w-[1400px] mx-auto space-y-4">
      {/* Header */}
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <div className="flex items-center gap-2.5">
            <CalendarDays className="w-6 h-6 text-blue-400" />
            <h1 className="text-xl font-bold text-slate-100">Event & Corporate Intelligence</h1>
            <span className="px-2 py-0.5 rounded-full border border-amber-700/50 bg-amber-900/20 text-amber-300 text-xs font-semibold">
              ADVISORY ONLY
            </span>
          </div>
          <p className="text-sm text-slate-400 mt-1">
            Corporate actions · Regulatory alerts · News intelligence · Event impact analysis
          </p>
        </div>
        <div className="flex items-center gap-2">
          <ExportBar />
          <button
            onClick={() => refetchSummary()}
            className="flex items-center gap-1.5 px-3 py-1.5 bg-slate-800 border border-slate-700/50 rounded-lg text-slate-300 text-xs hover:bg-slate-700 transition-colors"
          >
            <RefreshCw className={cn("w-3.5 h-3.5", isLoading && "animate-spin")} />
            Refresh
          </button>
        </div>
      </div>

      {/* Score header strip */}
      {summary?.available && (
        <div className="grid grid-cols-2 md:grid-cols-6 gap-3">
          <div className="md:col-span-2 bg-slate-900/80 border border-blue-800/40 rounded-xl p-3 flex items-center gap-3">
            <div className="text-center">
              <p className={cn("text-3xl font-bold", scoreColor(summary.intelligence_score))}>
                {Math.round(summary.intelligence_score)}
              </p>
              <p className="text-xs text-slate-400">/100</p>
            </div>
            <div>
              <p className={cn("text-xl font-bold", gradeColor(summary.grade))}>{summary.grade}</p>
              <p className="text-xs text-slate-400">{summary.trend}</p>
            </div>
          </div>
          <KpiCard label="Corporate"  value={summary.corporate_count}  color="text-blue-400" />
          <KpiCard label="Regulatory" value={summary.regulatory_count} color="text-amber-400" />
          <KpiCard label="News"       value={summary.news_count}        color="text-purple-400" />
          <KpiCard label="🚨 High Priority" value={summary.high_priority_count}
            color={(summary.high_priority_count ?? 0) > 0 ? "text-red-400" : "text-emerald-400"} />
        </div>
      )}

      {/* Loading */}
      {isLoading && (
        <div className="flex items-center justify-center h-32 gap-3 text-slate-400">
          <RefreshCw className="w-5 h-5 animate-spin" />
          <span>Loading Event Intelligence…</span>
        </div>
      )}

      {/* Tab bar */}
      <div className="flex gap-1 flex-wrap">
        {tabs.map(tab => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            className={cn(
              "flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm font-medium transition-colors",
              activeTab === tab.id
                ? "bg-blue-600/20 border border-blue-600/50 text-blue-300"
                : "bg-slate-800/50 border border-slate-700/40 text-slate-400 hover:text-slate-300 hover:bg-slate-700/40"
            )}
          >
            {tab.icon}{tab.label}
          </button>
        ))}
      </div>

      {/* Tab content */}
      {activeTab === "overview" && summary?.available && (
        <SectionCard title="Event Intelligence Overview" icon={<BarChart3 className="w-4 h-4 text-blue-400" />}>
          <OverviewSection data={summary} />
        </SectionCard>
      )}

      {activeTab === "brief" && (
        loadBrief ? (
          <div className="flex items-center gap-2 text-slate-400 py-8"><RefreshCw className="w-4 h-4 animate-spin" /> Loading brief…</div>
        ) : brief?.available ? (
          <SectionCard title={`Daily Intelligence Brief — ${brief.date}`} icon={<FileText className="w-4 h-4 text-teal-400" />}>
            <BriefSection data={brief} />
          </SectionCard>
        ) : (
          <p className="text-slate-500 text-sm py-4">Brief not available.</p>
        )
      )}

      {activeTab === "corporate" && (
        <SectionCard title="Corporate Events" icon={<Building2 className="w-4 h-4 text-blue-400" />}>
          {loadCorp ? (
            <div className="flex items-center gap-2 text-slate-400 py-4"><RefreshCw className="w-4 h-4 animate-spin" /> Loading…</div>
          ) : (
            <EventListSection events={corporateData?.events ?? []} emptyMsg="No corporate events detected." />
          )}
        </SectionCard>
      )}

      {activeTab === "news" && (
        <SectionCard title="News Intelligence" icon={<Newspaper className="w-4 h-4 text-purple-400" />}>
          {loadNews ? (
            <div className="flex items-center gap-2 text-slate-400 py-4"><RefreshCw className="w-4 h-4 animate-spin" /> Loading…</div>
          ) : (
            <EventListSection events={newsData?.events ?? []} emptyMsg="No news events available." />
          )}
        </SectionCard>
      )}

      {activeTab === "regulatory" && (
        <div className="space-y-4">
          {regulatoryData?.asm_watch?.length ? (
            <div className="flex items-center gap-2 bg-amber-900/20 border border-amber-700/40 rounded-xl px-4 py-2.5 flex-wrap">
              <AlertTriangle className="w-4 h-4 text-amber-400" />
              <span className="text-sm text-amber-300 font-semibold">ASM Watch:</span>
              {regulatoryData.asm_watch.map(s => (
                <span key={s} className="px-2 py-0.5 bg-amber-900/30 border border-amber-700/40 rounded text-xs text-amber-300">{s}</span>
              ))}
            </div>
          ) : null}
          {regulatoryData?.fo_ban?.length ? (
            <div className="flex items-center gap-2 bg-red-900/20 border border-red-700/40 rounded-xl px-4 py-2.5 flex-wrap">
              <ShieldAlert className="w-4 h-4 text-red-400" />
              <span className="text-sm text-red-300 font-semibold">F&O Ban:</span>
              {regulatoryData.fo_ban.map(s => (
                <span key={s} className="px-2 py-0.5 bg-red-900/30 border border-red-700/40 rounded text-xs text-red-300">{s}</span>
              ))}
            </div>
          ) : null}
          <SectionCard title="Regulatory Events" icon={<Shield className="w-4 h-4 text-amber-400" />}>
            {loadReg ? (
              <div className="flex items-center gap-2 text-slate-400 py-4"><RefreshCw className="w-4 h-4 animate-spin" /> Loading…</div>
            ) : (
              <EventListSection events={regulatoryData?.events ?? []} emptyMsg="No regulatory events detected." />
            )}
          </SectionCard>
        </div>
      )}

      {activeTab === "timeline" && (
        <SectionCard title="Event Timeline" icon={<CalendarDays className="w-4 h-4 text-teal-400" />}>
          {loadTimeline ? (
            <div className="flex items-center gap-2 text-slate-400 py-4"><RefreshCw className="w-4 h-4 animate-spin" /> Loading…</div>
          ) : timelineData?.available ? (
            <TimelineSection data={timelineData} />
          ) : (
            <p className="text-slate-500 text-sm py-4">Timeline unavailable.</p>
          )}
        </SectionCard>
      )}

      <p className="text-xs text-slate-600 text-center pb-2">
        Event Intelligence · Read-only · Advisory Only · Paper Trading · ApexQuant AI
      </p>
    </div>
  );
}
