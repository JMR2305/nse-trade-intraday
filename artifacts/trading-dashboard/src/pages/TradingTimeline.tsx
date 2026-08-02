/**
 * Phase 9.5 — Trading Day Timeline & Intelligent Session Assistant
 * READ-ONLY · ADVISORY-ONLY · No business logic changes
 *
 * 9 tabs: Timeline · Playback · AI Summary · Decision Trace ·
 *         Highlights · Notes · Comparison · Checklist · Export
 */
import React, { useState, useEffect, useRef, useCallback, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { apiJson } from "@/lib/api";
import { cn } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import {
  Clock, Play, Pause, SkipForward, SkipBack, FastForward,
  TrendingUp, TrendingDown, AlertTriangle, Activity, Brain,
  Shield, Zap, BookOpen, Settings2, Search, Filter, Download,
  ChevronRight, CheckSquare, Square, Star, Bookmark, Tag,
  BarChart2, ArrowUpDown, Target, RefreshCw, Info, XCircle,
  ChevronDown, SlidersHorizontal, Calendar, Eye, FileText,
  MessageSquare, Layers, Cpu, Globe, FlaskConical,
} from "lucide-react";

// ── Types ─────────────────────────────────────────────────────────────────────

type EventCategory =
  | "Market" | "Research" | "AI" | "Strategy" | "Risk"
  | "Portfolio" | "Execution" | "Learning" | "Operations"
  | "Security" | "Performance" | "Deployment" | "System" | "Scan" | "Platform";

type EventPriority = "critical" | "high" | "medium" | "low" | "info";

interface TimelineEvent {
  id: string;
  timestamp: string;       // ISO
  timeLabel: string;       // "09:15"
  agent: string;
  category: EventCategory;
  priority: EventPriority;
  description: string;
  symbol?: string;
  strategy?: string;
  confidence?: number;
  riskLevel?: "low" | "medium" | "high" | "critical";
  detailLink?: string;
  // Decision trace
  marketContext?: string;
  strategyScore?: number;
  finalRecommendation?: string;
  rawData?: Record<string, unknown>;
}

interface Annotation {
  id: string;
  eventId?: string;
  type: "note" | "tag" | "bookmark" | "lesson";
  text: string;
  tag?: string;
  createdAt: string;
}

interface ChecklistItem {
  id: string;
  label: string;
  section: string;
  done: boolean;
}

type Tab =
  | "timeline" | "playback" | "summary" | "trace"
  | "highlights" | "notes" | "comparison" | "checklist" | "export";

// ── Constants ─────────────────────────────────────────────────────────────────

const TABS: { id: Tab; label: string; icon: React.ElementType }[] = [
  { id: "timeline",    label: "Timeline",       icon: Clock },
  { id: "playback",    label: "Playback",        icon: Play },
  { id: "summary",     label: "AI Summary",      icon: Brain },
  { id: "trace",       label: "Decision Trace",  icon: Eye },
  { id: "highlights",  label: "Highlights",      icon: Star },
  { id: "notes",       label: "Notes",           icon: MessageSquare },
  { id: "comparison",  label: "Comparison",      icon: Layers },
  { id: "checklist",   label: "Checklist",       icon: CheckSquare },
  { id: "export",      label: "Export",          icon: Download },
];

const CATEGORY_META: Record<string, { color: string; icon: React.ElementType; agent: string }> = {
  Market:      { color: "text-blue-400",    icon: Globe,        agent: "Market Data Agent" },
  Research:    { color: "text-violet-400",  icon: FlaskConical, agent: "Research Agent" },
  AI:          { color: "text-cyan-400",    icon: Brain,        agent: "AI Decision Agent" },
  Strategy:    { color: "text-indigo-400",  icon: Target,       agent: "Strategy Agent" },
  Risk:        { color: "text-red-400",     icon: Shield,       agent: "Risk Agent" },
  Portfolio:   { color: "text-emerald-400", icon: TrendingUp,   agent: "Execution Agent" },
  Execution:   { color: "text-amber-400",   icon: Zap,          agent: "Execution Agent" },
  Learning:    { color: "text-pink-400",    icon: BookOpen,     agent: "Learning Agent" },
  Operations:  { color: "text-slate-400",   icon: Settings2,    agent: "Operations Agent" },
  Security:    { color: "text-orange-400",  icon: Shield,       agent: "Operations Agent" },
  Performance: { color: "text-yellow-400",  icon: BarChart2,    agent: "Operations Agent" },
  Deployment:  { color: "text-teal-400",    icon: Cpu,          agent: "Operations Agent" },
  System:      { color: "text-slate-400",   icon: Activity,     agent: "Operations Agent" },
  Scan:        { color: "text-blue-300",    icon: RefreshCw,    agent: "Market Data Agent" },
  Platform:    { color: "text-slate-300",   icon: Info,         agent: "Operations Agent" },
};

const PRIORITY_META: Record<EventPriority, { color: string; bg: string; border: string }> = {
  critical: { color: "text-red-400",    bg: "bg-red-500/10",    border: "border-red-500/30" },
  high:     { color: "text-amber-400",  bg: "bg-amber-500/10",  border: "border-amber-500/30" },
  medium:   { color: "text-blue-400",   bg: "bg-blue-500/10",   border: "border-blue-500/30" },
  low:      { color: "text-slate-400",  bg: "bg-slate-500/10",  border: "border-slate-500/30" },
  info:     { color: "text-slate-500",  bg: "bg-slate-500/5",   border: "border-slate-500/20" },
};

const SESSION_MILESTONES = [
  { time: "08:00", label: "Platform Startup",        icon: Cpu },
  { time: "08:30", label: "System Health Check",     icon: Activity },
  { time: "08:45", label: "Pre-open Intelligence",   icon: Brain },
  { time: "08:50", label: "Research Summary",        icon: FlaskConical },
  { time: "09:00", label: "Market Readiness",        icon: Target },
  { time: "09:08", label: "Auction Monitoring",      icon: BarChart2 },
  { time: "09:15", label: "Market Open",             icon: TrendingUp },
  { time: "15:30", label: "Market Close",            icon: TrendingDown },
  { time: "15:45", label: "Paper Trading Summary",   icon: BookOpen },
  { time: "16:00", label: "Learning Complete",       icon: Star },
];

const DEFAULT_CHECKLIST: Omit<ChecklistItem, "done">[] = [
  { id: "c1",  section: "Morning Preparation", label: "Platform startup confirmed" },
  { id: "c2",  section: "Morning Preparation", label: "System health checks passed" },
  { id: "c3",  section: "Morning Preparation", label: "API connections verified" },
  { id: "c4",  section: "Pre-open Review",     label: "Pre-open intelligence reviewed" },
  { id: "c5",  section: "Pre-open Review",     label: "Watchlist symbols confirmed" },
  { id: "c6",  section: "Pre-open Review",     label: "Research summary read" },
  { id: "c7",  section: "Risk Review",         label: "Risk score reviewed" },
  { id: "c8",  section: "Risk Review",         label: "Exposure limits checked" },
  { id: "c9",  section: "Risk Review",         label: "Capital allocation confirmed" },
  { id: "c10", section: "Trading Review",      label: "AI signals reviewed" },
  { id: "c11", section: "Trading Review",      label: "Strategy performance tracked" },
  { id: "c12", section: "Trading Review",      label: "Open positions monitored" },
  { id: "c13", section: "Closing Review",      label: "Positions reviewed at close" },
  { id: "c14", section: "Closing Review",      label: "Paper trade summary checked" },
  { id: "c15", section: "Closing Review",      label: "Reconciliation verified" },
  { id: "c16", section: "End-of-Day Learning", label: "Session timeline reviewed" },
  { id: "c17", section: "End-of-Day Learning", label: "Lessons learned documented" },
  { id: "c18", section: "End-of-Day Learning", label: "AI performance assessed" },
];

const STORAGE_KEYS = {
  annotations: "apexquant_timeline_annotations",
  checklist:   "apexquant_timeline_checklist",
};

// ── Data normalisation ────────────────────────────────────────────────────────

function normalisePriority(status: string, severity?: string): EventPriority {
  const s = (severity ?? status ?? "").toLowerCase();
  if (s === "critical" || s === "error")   return "critical";
  if (s === "high"    || s === "warning")  return "high";
  if (s === "medium"  || s === "warn")     return "medium";
  if (s === "low"     || s === "success")  return "low";
  return "info";
}

function normaliseCategory(raw: string): EventCategory {
  const c = (raw ?? "").toLowerCase();
  if (c.includes("scan"))        return "Scan";
  if (c.includes("platform"))    return "Platform";
  if (c.includes("system"))      return "System";
  if (c.includes("market"))      return "Market";
  if (c.includes("research"))    return "Research";
  if (c.includes("ai") || c.includes("copilot") || c.includes("signal")) return "AI";
  if (c.includes("risk"))        return "Risk";
  if (c.includes("portfolio"))   return "Portfolio";
  if (c.includes("execution") || c.includes("order") || c.includes("broker")) return "Execution";
  if (c.includes("learning"))    return "Learning";
  if (c.includes("security"))    return "Security";
  if (c.includes("performance")) return "Performance";
  if (c.includes("deploy"))      return "Deployment";
  if (c.includes("operation"))   return "Operations";
  if (c.includes("strategy"))    return "Strategy";
  return "System";
}

function buildEvents(
  timelineData: any,
  alertsData: any,
  copilotData: any,
  positionsData: any,
): TimelineEvent[] {
  const events: TimelineEvent[] = [];
  let idx = 0;

  // ── command-center/timeline events ──
  const tlEvents: any[] = timelineData?.events ?? [];
  for (const e of tlEvents) {
    const cat = normaliseCategory(e.category ?? "");
    const meta = CATEGORY_META[cat] ?? CATEGORY_META.System;
    events.push({
      id:          `tl-${idx++}`,
      timestamp:   e.ts_iso ?? "",
      timeLabel:   e.time ?? "",
      agent:       meta.agent,
      category:    cat,
      priority:    normalisePriority(e.status ?? "info"),
      description: e.event ?? "Platform event",
      rawData:     e,
    });
  }

  // ── command-center/alerts ──
  const ccAlerts: any[] = alertsData?.alerts ?? [];
  for (const a of ccAlerts) {
    const cat = normaliseCategory(a.category ?? "Platform");
    const meta = CATEGORY_META[cat] ?? CATEGORY_META.Platform;
    events.push({
      id:          `cc-${idx++}`,
      timestamp:   a.timestamp ?? "",
      timeLabel:   a.timestamp ? new Date(a.timestamp).toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit", hour12: false }) : "",
      agent:       meta.agent,
      category:    cat,
      priority:    normalisePriority(a.severity ?? "info"),
      description: a.title ?? a.body ?? "Alert",
      rawData:     a,
    });
  }

  // ── copilot/alerts (AI signals & recommendations) ──
  const copilotAlerts: any[] = copilotData?.alerts ?? [];
  for (const a of copilotAlerts) {
    const cat: EventCategory = "AI";
    events.push({
      id:                  `cp-${idx++}`,
      timestamp:           a.ts ?? a.date ?? "",
      timeLabel:           a.ts ? new Date(a.ts).toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit", hour12: false }) : "",
      agent:               "AI Decision Agent",
      category:            cat,
      priority:            normalisePriority("", a.severity ?? a.kind ?? "info"),
      description:         a.title ?? a.body ?? a.message ?? "AI signal",
      confidence:          typeof a.confidence === "number" ? a.confidence : undefined,
      strategy:            a.strategy ?? undefined,
      symbol:              a.symbol ?? undefined,
      // Decision trace fields
      marketContext:       a.market_context ?? undefined,
      strategyScore:       a.strategy_score ?? undefined,
      finalRecommendation: a.recommendation ?? a.action ?? undefined,
      rawData:             a,
    });
  }

  // ── phase20/positions (paper trades as portfolio events) ──
  const positions: any[] = positionsData?.positions ?? [];
  for (const p of positions) {
    events.push({
      id:          `pos-${idx++}`,
      timestamp:   p.entry_time ?? p.created_at ?? "",
      timeLabel:   p.entry_time ? new Date(p.entry_time).toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit", hour12: false }) : "",
      agent:       "Execution Agent",
      category:    "Portfolio",
      priority:    "medium",
      description: `Paper trade opened: ${p.symbol ?? "?"} ${p.direction ?? ""} @ ${p.entry_price ?? "?"}`,
      symbol:      p.symbol ?? undefined,
      strategy:    p.strategy ?? undefined,
      rawData:     p,
    });
  }

  // Sort descending (most recent first)
  events.sort((a, b) => {
    if (!a.timestamp && !b.timestamp) return 0;
    if (!a.timestamp) return 1;
    if (!b.timestamp) return -1;
    return b.timestamp.localeCompare(a.timestamp);
  });

  return events;
}

// ── localStorage helpers ───────────────────────────────────────────────────────

function loadAnnotations(): Annotation[] {
  try { return JSON.parse(localStorage.getItem(STORAGE_KEYS.annotations) ?? "[]"); }
  catch { return []; }
}
function saveAnnotations(a: Annotation[]) {
  localStorage.setItem(STORAGE_KEYS.annotations, JSON.stringify(a));
}
function loadChecklist(): ChecklistItem[] {
  try {
    const saved = JSON.parse(localStorage.getItem(STORAGE_KEYS.checklist) ?? "null");
    if (saved && Array.isArray(saved)) return saved;
  } catch { /* ignore */ }
  return DEFAULT_CHECKLIST.map(item => ({ ...item, done: false }));
}
function saveChecklist(c: ChecklistItem[]) {
  localStorage.setItem(STORAGE_KEYS.checklist, JSON.stringify(c));
}

// ── Sub-components ────────────────────────────────────────────────────────────

function EventCard({
  event, selected, onClick, compact = false,
}: {
  event: TimelineEvent;
  selected?: boolean;
  onClick?: () => void;
  compact?: boolean;
}) {
  const catMeta  = CATEGORY_META[event.category] ?? CATEGORY_META.System;
  const priMeta  = PRIORITY_META[event.priority];
  const Icon     = catMeta.icon;

  return (
    <div
      onClick={onClick}
      className={cn(
        "flex gap-3 p-3 rounded-xl border transition-all cursor-pointer",
        priMeta.border, priMeta.bg,
        selected && "ring-1 ring-primary/40",
        !compact && "hover:border-primary/30",
      )}
    >
      {/* Left: time + dot */}
      <div className="flex flex-col items-center gap-1 shrink-0 w-10">
        <span className="text-[10px] font-mono text-muted-foreground/60 leading-none">{event.timeLabel || "—"}</span>
        <div className={cn("w-5 h-5 rounded-full flex items-center justify-center", priMeta.bg, priMeta.border, "border")}>
          <Icon className={cn("w-2.5 h-2.5", catMeta.color)} />
        </div>
        <div className="w-px flex-1 bg-border/30" />
      </div>

      {/* Right: content */}
      <div className="flex-1 min-w-0">
        <div className="flex items-start justify-between gap-2">
          <p className={cn("text-[12px] font-medium leading-snug", compact ? "line-clamp-1" : "line-clamp-2")}>
            {event.description}
          </p>
          <Badge variant="outline" className={cn("text-[9px] shrink-0 px-1.5 py-0", priMeta.color)}>
            {event.priority}
          </Badge>
        </div>
        <div className="flex flex-wrap gap-x-2 gap-y-0.5 mt-1">
          <span className={cn("text-[10px]", catMeta.color)}>{event.category}</span>
          {event.agent && <span className="text-[10px] text-muted-foreground/50">· {event.agent}</span>}
          {event.symbol && <span className="text-[10px] text-blue-400/70">· {event.symbol}</span>}
          {typeof event.confidence === "number" && (
            <span className="text-[10px] text-cyan-400/70">· {Math.round(event.confidence * 100)}% conf</span>
          )}
        </div>
      </div>
    </div>
  );
}

function MilestoneMarker({ time, label, Icon }: { time: string; label: string; Icon: React.ElementType }) {
  return (
    <div className="flex items-center gap-3 py-1.5 my-1">
      <div className="flex items-center gap-1.5 shrink-0 w-10">
        <span className="text-[9px] font-mono text-muted-foreground/40">{time}</span>
      </div>
      <div className="flex items-center gap-1.5 px-2 py-0.5 rounded-full bg-primary/5 border border-primary/20">
        <Icon className="w-3 h-3 text-primary/60" />
        <span className="text-[10px] text-primary/60 font-medium">{label}</span>
      </div>
      <div className="flex-1 h-px bg-primary/10" />
    </div>
  );
}

// ── Main Page ─────────────────────────────────────────────────────────────────

export default function TradingTimeline() {
  // ── Server data ──
  const { data: timelineData, isLoading: tlLoading } = useQuery({
    queryKey: ["timeline-events"],
    queryFn: () => apiJson<any>("command-center/timeline"),
    staleTime: 30_000, refetchInterval: 60_000, retry: 1,
  });
  const { data: alertsData } = useQuery({
    queryKey: ["timeline-alerts"],
    queryFn: () => apiJson<any>("command-center/alerts"),
    staleTime: 30_000, refetchInterval: 60_000, retry: 1,
  });
  const { data: copilotData } = useQuery({
    queryKey: ["timeline-copilot"],
    queryFn: () => apiJson<any>("copilot/alerts"),
    staleTime: 30_000, refetchInterval: 60_000, retry: 1,
  });
  const { data: positionsData } = useQuery({
    queryKey: ["timeline-positions"],
    queryFn: () => apiJson<any>("phase20/positions"),
    staleTime: 30_000, refetchInterval: 60_000, retry: 1,
  });
  const { data: summaryData } = useQuery({
    queryKey: ["timeline-summary"],
    queryFn: () => apiJson<any>("command-center/summary"),
    staleTime: 60_000, retry: 1,
  });

  // ── Derived events ──
  const allEvents = useMemo(
    () => buildEvents(timelineData, alertsData, copilotData, positionsData),
    [timelineData, alertsData, copilotData, positionsData],
  );

  // ── UI state ──
  const [activeTab, setActiveTab]         = useState<Tab>("timeline");
  const [searchText, setSearchText]       = useState("");
  const [filterCategory, setFilterCategory] = useState<string>("All");
  const [filterPriority, setFilterPriority] = useState<string>("All");
  const [filterAgent, setFilterAgent]     = useState<string>("All");
  const [selectedEvent, setSelectedEvent] = useState<TimelineEvent | null>(null);
  const [showFilters, setShowFilters]     = useState(false);

  // Playback
  const [playbackIdx, setPlaybackIdx]     = useState(0);
  const [isPlaying, setIsPlaying]         = useState(false);
  const [playbackSpeed, setPlaybackSpeed] = useState(1);
  const playbackRef                       = useRef<ReturnType<typeof setInterval> | null>(null);

  // Notes / Annotations
  const [annotations, setAnnotations]     = useState<Annotation[]>(loadAnnotations);
  const [noteText, setNoteText]           = useState("");
  const [noteType, setNoteType]           = useState<Annotation["type"]>("note");
  const [noteTag, setNoteTag]             = useState("");

  // Checklist
  const [checklist, setChecklist]         = useState<ChecklistItem[]>(loadChecklist);

  // Comparison
  const [compLabel, setCompLabel]         = useState<"today" | "yesterday" | "prev-week">("yesterday");

  // ── Filters ──
  const filtered = useMemo(() => {
    let ev = allEvents;
    if (searchText) {
      const q = searchText.toLowerCase();
      ev = ev.filter(e =>
        e.description.toLowerCase().includes(q) ||
        (e.symbol ?? "").toLowerCase().includes(q) ||
        (e.strategy ?? "").toLowerCase().includes(q) ||
        e.category.toLowerCase().includes(q),
      );
    }
    if (filterCategory !== "All") ev = ev.filter(e => e.category === filterCategory);
    if (filterPriority  !== "All") ev = ev.filter(e => e.priority  === filterPriority);
    if (filterAgent     !== "All") ev = ev.filter(e => e.agent      === filterAgent);
    return ev;
  }, [allEvents, searchText, filterCategory, filterPriority, filterAgent]);

  const categories = useMemo(() => ["All", ...Array.from(new Set(allEvents.map(e => e.category)))], [allEvents]);
  const agents     = useMemo(() => ["All", ...Array.from(new Set(allEvents.map(e => e.agent).filter(Boolean)))], [allEvents]);

  // ── Playback engine ──
  const playbackEvents = useMemo(() => [...allEvents].reverse(), [allEvents]);

  const stopPlayback = useCallback(() => {
    if (playbackRef.current) clearInterval(playbackRef.current);
    setIsPlaying(false);
  }, []);

  const startPlayback = useCallback(() => {
    setIsPlaying(true);
    playbackRef.current = setInterval(() => {
      setPlaybackIdx(i => {
        if (i >= playbackEvents.length - 1) { stopPlayback(); return i; }
        return i + 1;
      });
    }, 1500 / playbackSpeed);
  }, [playbackEvents.length, playbackSpeed, stopPlayback]);

  useEffect(() => { return () => { if (playbackRef.current) clearInterval(playbackRef.current); }; }, []);
  useEffect(() => { if (isPlaying) { stopPlayback(); startPlayback(); } }, [playbackSpeed]);

  // ── Highlights ──
  const highlights = useMemo(() => {
    const withConf = allEvents.filter(e => typeof e.confidence === "number");
    const highest  = withConf.reduce((best, e) => (e.confidence! > (best?.confidence ?? -1) ? e : best), null as TimelineEvent | null);
    const criticals = allEvents.filter(e => e.priority === "critical");
    const portfolioEvs = allEvents.filter(e => e.category === "Portfolio");
    const riskEvs    = allEvents.filter(e => e.category === "Risk");
    const aiEvs      = allEvents.filter(e => e.category === "AI");
    const marketEvs  = allEvents.filter(e => e.category === "Market");

    return [
      { label: "Highest Confidence Signal", icon: Brain,        color: "text-cyan-400",    event: highest,                  fallback: "No AI signals yet" },
      { label: "Most Critical Alert",       icon: AlertTriangle, color: "text-red-400",    event: criticals[0] ?? null,     fallback: "No critical alerts" },
      { label: "Latest Portfolio Event",    icon: TrendingUp,   color: "text-emerald-400", event: portfolioEvs[0] ?? null,  fallback: "No portfolio events" },
      { label: "Latest Risk Update",        icon: Shield,       color: "text-amber-400",   event: riskEvs[0] ?? null,       fallback: "No risk events" },
      { label: "Latest AI Decision",        icon: Cpu,          color: "text-violet-400",  event: aiEvs[0] ?? null,         fallback: "No AI events" },
      { label: "Latest Market Event",       icon: Globe,        color: "text-blue-400",    event: marketEvs[0] ?? null,     fallback: "No market events" },
      { label: "Most Active Category",      icon: BarChart2,    color: "text-indigo-400",  event: null,
        extra: (() => {
          const counts: Record<string, number> = {};
          allEvents.forEach(e => { counts[e.category] = (counts[e.category] ?? 0) + 1; });
          const top = Object.entries(counts).sort((a, b) => b[1] - a[1])[0];
          return top ? `${top[0]} (${top[1]} events)` : "—";
        })(),
        fallback: "—" },
    ];
  }, [allEvents]);

  // ── AI Session Summaries (derived, no LLM) ──
  const summaries = useMemo(() => {
    const critical   = allEvents.filter(e => e.priority === "critical").length;
    const aiCount    = allEvents.filter(e => e.category === "AI").length;
    const tradeCount = allEvents.filter(e => e.category === "Portfolio").length;
    const riskCount  = allEvents.filter(e => e.category === "Risk").length;
    const marketName = summaryData?.market_status ?? "NSE";

    return [
      {
        id: "morning",
        label: "Morning Summary",
        icon: "🌅",
        text: `Platform initialised. System health checks ${critical === 0 ? "passed" : `flagged ${critical} critical issue(s)`}. Pre-open intelligence loaded${aiCount > 0 ? ` with ${aiCount} AI signal(s) prepared` : ""}. Watchlist and research summaries are available for review.`,
      },
      {
        id: "midday",
        label: "Midday Summary",
        icon: "☀️",
        text: `${marketName} session active. ${allEvents.length} events recorded so far${tradeCount > 0 ? `, including ${tradeCount} portfolio event(s)` : ""}. ${riskCount > 0 ? `${riskCount} risk update(s) logged.` : "Risk parameters stable."} ${aiCount > 0 ? `AI Decision Agent issued ${aiCount} signal(s).` : "No new AI signals this session."}`,
      },
      {
        id: "closing",
        label: "Closing Summary",
        icon: "🌇",
        text: `Market session closing. ${tradeCount} paper trade event(s) recorded. ${critical > 0 ? `${critical} critical alert(s) require review.` : "No unresolved critical alerts."} Reconciliation and performance analytics are available on their respective pages.`,
      },
      {
        id: "eod",
        label: "End-of-Day Review",
        icon: "📋",
        text: `Session complete. Total events: ${allEvents.length}. Categories covered: ${[...new Set(allEvents.map(e => e.category))].join(", ") || "none"}. ${critical > 0 ? `Action required: review ${critical} critical event(s).` : "No action items outstanding."} Learning review and performance analytics available for post-market analysis.`,
      },
      {
        id: "weekly",
        label: "Weekly Highlights",
        icon: "📊",
        text: `This view shows today's session data. For multi-day trend analysis, the Strategy Intelligence and AI Performance pages provide 7-day and 30-day rolling analytics. Today: ${allEvents.length} events, ${aiCount} AI signals, ${tradeCount} portfolio events, ${critical} critical alerts.`,
      },
    ];
  }, [allEvents, summaryData]);

  // ── Decision Trace events (AI category with enough fields) ──
  const traceEvents = useMemo(
    () => allEvents.filter(e => e.category === "AI"),
    [allEvents],
  );

  // ── Annotations ──
  const addAnnotation = useCallback(() => {
    if (!noteText.trim()) return;
    const a: Annotation = {
      id:        `ann-${Date.now()}`,
      eventId:   selectedEvent?.id,
      type:      noteType,
      text:      noteText.trim(),
      tag:       noteTag.trim() || undefined,
      createdAt: new Date().toISOString(),
    };
    const next = [a, ...annotations];
    setAnnotations(next);
    saveAnnotations(next);
    setNoteText("");
    setNoteTag("");
  }, [noteText, noteType, noteTag, annotations, selectedEvent]);

  const removeAnnotation = useCallback((id: string) => {
    const next = annotations.filter(a => a.id !== id);
    setAnnotations(next);
    saveAnnotations(next);
  }, [annotations]);

  // ── Checklist ──
  const toggleChecklist = useCallback((id: string) => {
    const next = checklist.map(c => c.id === id ? { ...c, done: !c.done } : c);
    setChecklist(next);
    saveChecklist(next);
  }, [checklist]);

  const resetChecklist = useCallback(() => {
    const next = checklist.map(c => ({ ...c, done: false }));
    setChecklist(next);
    saveChecklist(next);
  }, [checklist]);

  const checklistSections = useMemo(() => {
    const sections: Record<string, ChecklistItem[]> = {};
    checklist.forEach(c => {
      sections[c.section] = sections[c.section] ?? [];
      sections[c.section].push(c);
    });
    return sections;
  }, [checklist]);

  const checklistProgress = useMemo(() => ({
    done:  checklist.filter(c => c.done).length,
    total: checklist.length,
  }), [checklist]);

  // ── Export ──
  const exportCSV = useCallback(() => {
    const headers = ["id","timestamp","timeLabel","agent","category","priority","description","symbol","strategy","confidence","riskLevel"];
    const rows = allEvents.map(e => headers.map(h => {
      const v = (e as any)[h] ?? "";
      return `"${String(v).replace(/"/g, '""')}"`;
    }).join(","));
    const csv = [headers.join(","), ...rows].join("\n");
    const blob = new Blob([csv], { type: "text/csv" });
    const url  = URL.createObjectURL(blob);
    const a    = document.createElement("a"); a.href = url;
    a.download = `apexquant-timeline-${new Date().toISOString().slice(0, 10)}.csv`;
    a.click(); URL.revokeObjectURL(url);
  }, [allEvents]);

  const exportJSON = useCallback(() => {
    const payload = { generatedAt: new Date().toISOString(), eventCount: allEvents.length, events: allEvents };
    const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" });
    const url  = URL.createObjectURL(blob);
    const a    = document.createElement("a"); a.href = url;
    a.download = `apexquant-timeline-${new Date().toISOString().slice(0, 10)}.json`;
    a.click(); URL.revokeObjectURL(url);
  }, [allEvents]);

  const exportAnnotations = useCallback(() => {
    const blob = new Blob([JSON.stringify(annotations, null, 2)], { type: "application/json" });
    const url  = URL.createObjectURL(blob);
    const a    = document.createElement("a"); a.href = url;
    a.download = `apexquant-notes-${new Date().toISOString().slice(0, 10)}.json`;
    a.click(); URL.revokeObjectURL(url);
  }, [annotations]);

  // ── Render ────────────────────────────────────────────────────────────────

  return (
    <div className="flex flex-col h-full min-h-0 bg-background">

      {/* ── Header ── */}
      <div className="shrink-0 px-6 pt-5 pb-3 border-b border-border/30">
        <div className="flex items-start justify-between gap-4">
          <div>
            <div className="flex items-center gap-2 mb-1">
              <Clock className="w-5 h-5 text-primary" />
              <h1 className="text-lg font-bold tracking-tight">Trading Day Timeline</h1>
              <Badge variant="outline" className="text-[10px] text-muted-foreground/60 border-border/40">
                Advisory · Read-only
              </Badge>
            </div>
            <p className="text-[12px] text-muted-foreground/60">
              Complete chronological record · {allEvents.length} events across {[...new Set(allEvents.map(e => e.category))].length} categories
            </p>
          </div>
          <div className="flex items-center gap-2 text-[11px] text-muted-foreground/50">
            <div className={cn("w-2 h-2 rounded-full", tlLoading ? "bg-amber-400 animate-pulse" : "bg-emerald-400")} />
            {tlLoading ? "Loading…" : "Live"}
          </div>
        </div>

        {/* Tab bar */}
        <div className="flex gap-1 mt-4 overflow-x-auto scrollbar-hide">
          {TABS.map(t => {
            const TIcon = t.icon;
            return (
              <button
                key={t.id}
                onClick={() => setActiveTab(t.id)}
                className={cn(
                  "flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[11px] font-medium whitespace-nowrap transition-all shrink-0",
                  activeTab === t.id
                    ? "bg-primary/15 text-primary border border-primary/30"
                    : "text-muted-foreground/60 hover:text-foreground/80 hover:bg-muted/20",
                )}
              >
                <TIcon className="w-3 h-3" />
                {t.label}
              </button>
            );
          })}
        </div>
      </div>

      {/* ── Tab Content ── */}
      <div className="flex-1 min-h-0 overflow-y-auto">

        {/* ════════════════════════════════════════════════════════ TIMELINE */}
        {activeTab === "timeline" && (
          <div className="flex h-full min-h-0">

            {/* Sidebar filters */}
            <div className={cn(
              "shrink-0 border-r border-border/30 transition-all overflow-y-auto",
              showFilters ? "w-52" : "w-0 overflow-hidden",
            )}>
              <div className="p-4 space-y-4">
                <p className="text-[11px] font-semibold text-muted-foreground/70 uppercase tracking-wider">Filters</p>

                <div>
                  <p className="text-[10px] text-muted-foreground/50 mb-1.5">Category</p>
                  {categories.map(c => (
                    <button key={c} onClick={() => setFilterCategory(c)}
                      className={cn("block w-full text-left text-[11px] px-2 py-1 rounded-lg mb-0.5 transition-colors",
                        filterCategory === c ? "bg-primary/15 text-primary" : "text-muted-foreground/60 hover:bg-muted/20")}>
                      {c}
                    </button>
                  ))}
                </div>

                <div>
                  <p className="text-[10px] text-muted-foreground/50 mb-1.5">Priority</p>
                  {["All", "critical", "high", "medium", "low", "info"].map(p => (
                    <button key={p} onClick={() => setFilterPriority(p)}
                      className={cn("block w-full text-left text-[11px] px-2 py-1 rounded-lg mb-0.5 transition-colors",
                        filterPriority === p ? "bg-primary/15 text-primary" : "text-muted-foreground/60 hover:bg-muted/20")}>
                      {p.charAt(0).toUpperCase() + p.slice(1)}
                    </button>
                  ))}
                </div>

                <div>
                  <p className="text-[10px] text-muted-foreground/50 mb-1.5">Agent</p>
                  {agents.map(a => (
                    <button key={a} onClick={() => setFilterAgent(a)}
                      className={cn("block w-full text-left text-[10px] px-2 py-1 rounded-lg mb-0.5 transition-colors",
                        filterAgent === a ? "bg-primary/15 text-primary" : "text-muted-foreground/60 hover:bg-muted/20")}>
                      {a === "All" ? "All Agents" : a}
                    </button>
                  ))}
                </div>
              </div>
            </div>

            {/* Main feed */}
            <div className="flex-1 min-w-0 flex flex-col">
              {/* Toolbar */}
              <div className="shrink-0 flex items-center gap-2 px-4 py-3 border-b border-border/20">
                <button onClick={() => setShowFilters(f => !f)}
                  className={cn("p-1.5 rounded-lg border transition-colors text-[11px] flex items-center gap-1.5",
                    showFilters ? "bg-primary/10 border-primary/30 text-primary" : "border-border/30 text-muted-foreground/60 hover:bg-muted/20")}>
                  <SlidersHorizontal className="w-3 h-3" />
                  Filters
                  {(filterCategory !== "All" || filterPriority !== "All" || filterAgent !== "All") && (
                    <span className="w-1.5 h-1.5 rounded-full bg-primary" />
                  )}
                </button>

                <div className="relative flex-1 max-w-xs">
                  <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3 h-3 text-muted-foreground/40" />
                  <input
                    value={searchText}
                    onChange={e => setSearchText(e.target.value)}
                    placeholder="Search events, symbols…"
                    className="w-full pl-7 pr-3 py-1.5 text-[11px] bg-muted/20 border border-border/30 rounded-lg focus:outline-none focus:border-primary/30"
                  />
                </div>

                <span className="text-[10px] text-muted-foreground/40 ml-auto">{filtered.length} event{filtered.length !== 1 ? "s" : ""}</span>
              </div>

              {/* Event list */}
              <div className="flex-1 overflow-y-auto p-4 space-y-1">
                {tlLoading && (
                  <div className="space-y-2">
                    {[...Array(5)].map((_, i) => (
                      <div key={i} className="h-16 rounded-xl bg-muted/20 animate-pulse" />
                    ))}
                  </div>
                )}

                {!tlLoading && filtered.length === 0 && (
                  <div className="flex flex-col items-center justify-center h-40 text-muted-foreground/40">
                    <Clock className="w-8 h-8 mb-2 opacity-30" />
                    <p className="text-[12px]">No events match your filters</p>
                  </div>
                )}

                {!tlLoading && filtered.length > 0 && (() => {
                  const rendered: React.ReactNode[] = [];
                  let lastTime = "";
                  const insertedMilestones = new Set<string>();

                  for (const ev of filtered) {
                    // Insert milestone markers (each milestone inserted at most once)
                    const t = ev.timeLabel;
                    SESSION_MILESTONES.forEach(m => {
                      if (!insertedMilestones.has(m.time) && lastTime < m.time && t <= m.time && t !== "") {
                        insertedMilestones.add(m.time);
                        rendered.push(
                          <MilestoneMarker key={`ms-${m.time}`} time={m.time} label={m.label} Icon={m.icon} />
                        );
                      }
                    });
                    lastTime = t || lastTime;

                    rendered.push(
                      <EventCard
                        key={ev.id}
                        event={ev}
                        selected={selectedEvent?.id === ev.id}
                        onClick={() => setSelectedEvent(s => s?.id === ev.id ? null : ev)}
                      />
                    );

                    // Expanded detail panel
                    if (selectedEvent?.id === ev.id) {
                      rendered.push(
                        <div key={`detail-${ev.id}`}
                          className="mx-1 p-4 rounded-xl bg-muted/10 border border-primary/20 space-y-3 text-[11px]">
                          <p className="font-semibold text-foreground/80">Event Detail</p>
                          <div className="grid grid-cols-2 gap-2">
                            {[
                              ["Agent",    ev.agent],
                              ["Category", ev.category],
                              ["Priority", ev.priority],
                              ["Symbol",   ev.symbol   ?? "—"],
                              ["Strategy", ev.strategy ?? "—"],
                              ["Confidence", typeof ev.confidence === "number" ? `${Math.round(ev.confidence * 100)}%` : "—"],
                            ].map(([k, v]) => (
                              <div key={k}>
                                <p className="text-muted-foreground/50 text-[10px]">{k}</p>
                                <p className="font-medium">{v}</p>
                              </div>
                            ))}
                          </div>
                          {ev.marketContext && (
                            <div>
                              <p className="text-muted-foreground/50 text-[10px] mb-0.5">Market Context</p>
                              <p className="text-foreground/70">{ev.marketContext}</p>
                            </div>
                          )}
                          {ev.finalRecommendation && (
                            <div>
                              <p className="text-muted-foreground/50 text-[10px] mb-0.5">Recommendation</p>
                              <p className="text-cyan-400">{ev.finalRecommendation}</p>
                            </div>
                          )}
                          {ev.timestamp && (
                            <p className="text-muted-foreground/40 text-[9px] font-mono">{ev.timestamp}</p>
                          )}
                        </div>
                      );
                    }
                  }
                  return rendered;
                })()}
              </div>
            </div>
          </div>
        )}

        {/* ════════════════════════════════════════════════════════ PLAYBACK */}
        {activeTab === "playback" && (
          <div className="p-6 space-y-6">
            <div className="flex items-center gap-2 mb-4">
              <Play className="w-4 h-4 text-primary" />
              <h2 className="text-[14px] font-semibold">Session Playback</h2>
              <Badge variant="outline" className="text-[10px] text-muted-foreground/50">Review only · No simulation</Badge>
            </div>

            {/* Progress bar */}
            <div className="space-y-2">
              <div className="flex justify-between text-[10px] text-muted-foreground/50">
                <span>Event {playbackIdx + 1} of {playbackEvents.length}</span>
                <span>{playbackEvents[playbackIdx]?.timeLabel ?? "—"}</span>
              </div>
              <div className="w-full h-1.5 bg-muted/30 rounded-full overflow-hidden">
                <div
                  className="h-full bg-primary/60 rounded-full transition-all"
                  style={{ width: `${playbackEvents.length > 0 ? ((playbackIdx + 1) / playbackEvents.length) * 100 : 0}%` }}
                />
              </div>
            </div>

            {/* Controls */}
            <div className="flex items-center justify-center gap-3">
              <button onClick={() => { stopPlayback(); setPlaybackIdx(0); }}
                className="p-2 rounded-lg border border-border/30 hover:bg-muted/20 transition-colors" title="Jump to start">
                <SkipBack className="w-4 h-4 text-muted-foreground/60" />
              </button>
              <button onClick={() => setPlaybackIdx(i => Math.max(0, i - 1))}
                className="p-2 rounded-lg border border-border/30 hover:bg-muted/20 transition-colors" title="Step back">
                <ChevronRight className="w-4 h-4 text-muted-foreground/60 rotate-180" />
              </button>
              <button
                onClick={() => isPlaying ? stopPlayback() : startPlayback()}
                className="p-3 rounded-xl bg-primary/15 border border-primary/30 hover:bg-primary/20 transition-colors"
              >
                {isPlaying
                  ? <Pause className="w-5 h-5 text-primary" />
                  : <Play  className="w-5 h-5 text-primary" />}
              </button>
              <button onClick={() => setPlaybackIdx(i => Math.min(playbackEvents.length - 1, i + 1))}
                className="p-2 rounded-lg border border-border/30 hover:bg-muted/20 transition-colors" title="Step forward">
                <ChevronRight className="w-4 h-4 text-muted-foreground/60" />
              </button>
              <button onClick={() => { stopPlayback(); setPlaybackIdx(playbackEvents.length - 1); }}
                className="p-2 rounded-lg border border-border/30 hover:bg-muted/20 transition-colors" title="Jump to end">
                <SkipForward className="w-4 h-4 text-muted-foreground/60" />
              </button>
            </div>

            {/* Speed + Jump */}
            <div className="flex items-center justify-center gap-4 text-[11px]">
              <div className="flex items-center gap-2">
                <FastForward className="w-3 h-3 text-muted-foreground/50" />
                <span className="text-muted-foreground/60">Speed:</span>
                {[0.5, 1, 2, 4].map(s => (
                  <button key={s} onClick={() => setPlaybackSpeed(s)}
                    className={cn("px-2 py-0.5 rounded text-[10px] font-medium transition-colors",
                      playbackSpeed === s ? "bg-primary/15 text-primary" : "text-muted-foreground/50 hover:bg-muted/20")}>
                    {s}×
                  </button>
                ))}
              </div>
              <div className="flex items-center gap-2">
                <Clock className="w-3 h-3 text-muted-foreground/50" />
                <span className="text-muted-foreground/60">Jump to event:</span>
                <input
                  type="number"
                  min={1}
                  max={playbackEvents.length}
                  className="w-16 px-2 py-0.5 text-[11px] bg-muted/20 border border-border/30 rounded focus:outline-none focus:border-primary/30"
                  onKeyDown={e => {
                    if (e.key === "Enter") {
                      const v = parseInt((e.target as HTMLInputElement).value, 10);
                      if (!isNaN(v)) setPlaybackIdx(Math.max(0, Math.min(playbackEvents.length - 1, v - 1)));
                    }
                  }}
                  placeholder="#"
                />
              </div>
            </div>

            {/* Current event */}
            {playbackEvents[playbackIdx] ? (
              <div className="max-w-xl mx-auto">
                <p className="text-[10px] text-muted-foreground/40 text-center mb-3">Current event</p>
                <EventCard event={playbackEvents[playbackIdx]} />
              </div>
            ) : (
              <div className="text-center text-muted-foreground/40 text-[12px] py-8">
                No events to replay. Events will appear as the platform generates them.
              </div>
            )}

            {/* Context: surrounding events */}
            {playbackEvents.length > 0 && (
              <div className="max-w-xl mx-auto space-y-1">
                <p className="text-[10px] text-muted-foreground/40 text-center mb-2">Surrounding events</p>
                {[-2, -1, 0, 1, 2].map(offset => {
                  const idx2 = playbackIdx + offset;
                  if (idx2 < 0 || idx2 >= playbackEvents.length || offset === 0) return null;
                  return (
                    <div key={offset} className="opacity-40 hover:opacity-70 transition-opacity">
                      <EventCard event={playbackEvents[idx2]} compact onClick={() => setPlaybackIdx(idx2)} />
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        )}

        {/* ════════════════════════════════════════════════════════ AI SUMMARY */}
        {activeTab === "summary" && (
          <div className="p-6 space-y-4">
            <div className="flex items-center gap-2 mb-2">
              <Brain className="w-4 h-4 text-cyan-400" />
              <h2 className="text-[14px] font-semibold">AI Session Summaries</h2>
              <Badge variant="outline" className="text-[10px] text-muted-foreground/50">Derived · Advisory</Badge>
            </div>
            <p className="text-[11px] text-muted-foreground/50">
              Natural-language summaries generated from today's event data. Updated as new events arrive.
            </p>
            <div className="grid gap-4 max-w-3xl">
              {summaries.map(s => (
                <div key={s.id} className="p-4 rounded-xl border border-border/30 bg-muted/5 hover:border-primary/20 transition-colors">
                  <div className="flex items-center gap-2 mb-2">
                    <span className="text-lg">{s.icon}</span>
                    <p className="text-[13px] font-semibold">{s.label}</p>
                  </div>
                  <p className="text-[12px] text-muted-foreground/70 leading-relaxed">{s.text}</p>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* ════════════════════════════════════════════════════════ DECISION TRACE */}
        {activeTab === "trace" && (
          <div className="p-6 space-y-4">
            <div className="flex items-center gap-2 mb-2">
              <Eye className="w-4 h-4 text-violet-400" />
              <h2 className="text-[14px] font-semibold">Decision Trace</h2>
              <Badge variant="outline" className="text-[10px] text-muted-foreground/50">AI events · Read-only</Badge>
            </div>
            <p className="text-[11px] text-muted-foreground/50">
              For every AI recommendation, the full decision chain: market context → research → strategy score → risk → confidence → final recommendation.
            </p>
            {traceEvents.length === 0 ? (
              <div className="flex flex-col items-center justify-center h-40 text-muted-foreground/40">
                <Brain className="w-8 h-8 mb-2 opacity-30" />
                <p className="text-[12px]">No AI decision events yet this session</p>
              </div>
            ) : (
              <div className="space-y-4 max-w-3xl">
                {traceEvents.map(ev => {
                  const conf = typeof ev.confidence === "number" ? Math.round(ev.confidence * 100) : null;
                  return (
                    <div key={ev.id} className="p-4 rounded-xl border border-violet-500/20 bg-violet-500/5 space-y-3">
                      <div className="flex items-start justify-between gap-2">
                        <div>
                          <p className="text-[12px] font-semibold text-foreground/90">{ev.description}</p>
                          <p className="text-[10px] text-muted-foreground/50 mt-0.5">
                            {ev.timeLabel} · {ev.agent}{ev.symbol ? ` · ${ev.symbol}` : ""}
                          </p>
                        </div>
                        {conf !== null && (
                          <div className="text-center shrink-0">
                            <p className={cn("text-[18px] font-bold", conf >= 70 ? "text-emerald-400" : conf >= 50 ? "text-amber-400" : "text-red-400")}>
                              {conf}%
                            </p>
                            <p className="text-[9px] text-muted-foreground/40">confidence</p>
                          </div>
                        )}
                      </div>

                      <div className="grid grid-cols-2 md:grid-cols-3 gap-3 text-[11px]">
                        {[
                          { label: "Market Context",      value: ev.marketContext          ?? "Derived from scan snapshot" },
                          { label: "Research Inputs",     value: "Copilot alerts engine"                                    },
                          { label: "Strategy",            value: ev.strategy               ?? "—" },
                          { label: "Strategy Score",      value: ev.strategyScore != null ? `${ev.strategyScore}` : "—" },
                          { label: "Risk Level",          value: ev.riskLevel              ?? "—" },
                          { label: "Final Recommendation", value: ev.finalRecommendation   ?? ev.description },
                        ].map(({ label, value }) => (
                          <div key={label} className="p-2 rounded-lg bg-background/40 border border-border/20">
                            <p className="text-muted-foreground/50 text-[9px] mb-0.5">{label}</p>
                            <p className="font-medium line-clamp-2">{value}</p>
                          </div>
                        ))}
                      </div>

                      <div className="flex items-center gap-2 text-[10px] text-muted-foreground/40">
                        <Info className="w-3 h-3" />
                        For full explainability, open the Explainable AI page
                        <ChevronRight className="w-3 h-3 ml-auto" />
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        )}

        {/* ════════════════════════════════════════════════════════ HIGHLIGHTS */}
        {activeTab === "highlights" && (
          <div className="p-6 space-y-4">
            <div className="flex items-center gap-2 mb-2">
              <Star className="w-4 h-4 text-amber-400" />
              <h2 className="text-[14px] font-semibold">Smart Highlights</h2>
              <Badge variant="outline" className="text-[10px] text-muted-foreground/50">Auto-identified</Badge>
            </div>
            <p className="text-[11px] text-muted-foreground/50">
              Automatically identified key moments from today's session.
            </p>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4 max-w-3xl">
              {highlights.map((h, i) => {
                const HIcon = h.icon;
                return (
                  <div key={i} className="p-4 rounded-xl border border-border/30 bg-muted/5 hover:border-primary/20 transition-colors">
                    <div className="flex items-center gap-2 mb-2">
                      <HIcon className={cn("w-4 h-4", h.color)} />
                      <p className={cn("text-[11px] font-semibold", h.color)}>{h.label}</p>
                    </div>
                    {h.event ? (
                      <EventCard event={h.event} compact />
                    ) : (h as any).extra ? (
                      <p className="text-[12px] text-foreground/70 font-medium">{(h as any).extra}</p>
                    ) : (
                      <p className="text-[11px] text-muted-foreground/40 italic">{h.fallback}</p>
                    )}
                  </div>
                );
              })}
            </div>

            {/* Category breakdown */}
            <div className="max-w-3xl mt-6">
              <p className="text-[11px] font-semibold text-muted-foreground/70 mb-3">Event Distribution</p>
              <div className="flex flex-wrap gap-2">
                {Object.entries(
                  allEvents.reduce((acc, e) => { acc[e.category] = (acc[e.category] ?? 0) + 1; return acc; }, {} as Record<string, number>)
                ).sort((a, b) => b[1] - a[1]).map(([cat, count]) => {
                  const meta = CATEGORY_META[cat] ?? CATEGORY_META.System;
                  const CatIcon = meta.icon;
                  return (
                    <div key={cat} className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg border border-border/30 bg-muted/10">
                      <CatIcon className={cn("w-3 h-3", meta.color)} />
                      <span className="text-[11px] font-medium">{cat}</span>
                      <span className="text-[10px] text-muted-foreground/50">{count}</span>
                    </div>
                  );
                })}
              </div>
            </div>
          </div>
        )}

        {/* ════════════════════════════════════════════════════════ NOTES */}
        {activeTab === "notes" && (
          <div className="p-6 space-y-6 max-w-2xl">
            <div className="flex items-center gap-2 mb-2">
              <MessageSquare className="w-4 h-4 text-pink-400" />
              <h2 className="text-[14px] font-semibold">Annotations & Notes</h2>
              <Badge variant="outline" className="text-[10px] text-muted-foreground/50">Local storage</Badge>
            </div>

            {/* Add note form */}
            <div className="p-4 rounded-xl border border-border/30 bg-muted/5 space-y-3">
              <p className="text-[11px] font-semibold text-muted-foreground/70">Add Annotation</p>

              {selectedEvent && (
                <div className="flex items-center gap-2 px-2 py-1.5 rounded-lg bg-primary/5 border border-primary/20 text-[10px]">
                  <Tag className="w-3 h-3 text-primary/60" />
                  <span className="text-primary/70">Linked to: {selectedEvent.description.slice(0, 50)}</span>
                  <button onClick={() => setSelectedEvent(null)} className="ml-auto text-muted-foreground/40 hover:text-muted-foreground/70">
                    <XCircle className="w-3 h-3" />
                  </button>
                </div>
              )}

              <div className="flex gap-2">
                {(["note", "tag", "bookmark", "lesson"] as const).map(t => (
                  <button key={t} onClick={() => setNoteType(t)}
                    className={cn("px-2.5 py-1 rounded-lg text-[10px] font-medium transition-colors",
                      noteType === t ? "bg-primary/15 text-primary border border-primary/30" : "border border-border/30 text-muted-foreground/50 hover:bg-muted/20")}>
                    {t.charAt(0).toUpperCase() + t.slice(1)}
                  </button>
                ))}
              </div>

              <Textarea
                value={noteText}
                onChange={e => setNoteText(e.target.value)}
                placeholder="Your annotation, lesson, or note…"
                className="text-[12px] min-h-[72px] bg-muted/10 border-border/30 resize-none"
              />

              {noteType === "tag" && (
                <Input
                  value={noteTag}
                  onChange={e => setNoteTag(e.target.value)}
                  placeholder="Tag (e.g. volatility, NIFTY, breakout)"
                  className="text-[12px] bg-muted/10 border-border/30"
                />
              )}

              <Button size="sm" onClick={addAnnotation} disabled={!noteText.trim()} className="text-[11px]">
                Save annotation
              </Button>
            </div>

            {/* Saved annotations */}
            {annotations.length === 0 ? (
              <p className="text-[12px] text-muted-foreground/40 text-center py-8 italic">No annotations yet</p>
            ) : (
              <div className="space-y-3">
                <p className="text-[11px] font-semibold text-muted-foreground/70">{annotations.length} annotation{annotations.length !== 1 ? "s" : ""}</p>
                {annotations.map(a => {
                  const typeIcon = a.type === "lesson" ? BookOpen : a.type === "bookmark" ? Bookmark : a.type === "tag" ? Tag : MessageSquare;
                  const TypeIcon = typeIcon;
                  return (
                    <div key={a.id} className="p-3 rounded-xl border border-border/30 bg-muted/5 group">
                      <div className="flex items-start gap-2">
                        <TypeIcon className="w-3.5 h-3.5 text-muted-foreground/50 shrink-0 mt-0.5" />
                        <div className="flex-1 min-w-0">
                          <p className="text-[12px] text-foreground/80">{a.text}</p>
                          {a.tag && (
                            <span className="inline-block mt-1 px-1.5 py-0.5 rounded bg-primary/10 text-primary/70 text-[9px]">#{a.tag}</span>
                          )}
                          <p className="text-[9px] text-muted-foreground/30 mt-1 font-mono">{a.createdAt}</p>
                        </div>
                        <button onClick={() => removeAnnotation(a.id)}
                          className="shrink-0 opacity-0 group-hover:opacity-100 transition-opacity text-muted-foreground/40 hover:text-red-400">
                          <XCircle className="w-3.5 h-3.5" />
                        </button>
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        )}

        {/* ════════════════════════════════════════════════════════ COMPARISON */}
        {activeTab === "comparison" && (
          <div className="p-6 space-y-4">
            <div className="flex items-center gap-2 mb-2">
              <Layers className="w-4 h-4 text-indigo-400" />
              <h2 className="text-[14px] font-semibold">Timeline Comparison</h2>
              <Badge variant="outline" className="text-[10px] text-muted-foreground/50">Today vs reference</Badge>
            </div>

            <div className="flex gap-2 mb-4">
              {(["yesterday", "prev-week"] as const).map(l => (
                <button key={l} onClick={() => setCompLabel(l)}
                  className={cn("px-3 py-1.5 rounded-lg text-[11px] font-medium border transition-colors",
                    compLabel === l ? "bg-primary/15 text-primary border-primary/30" : "border-border/30 text-muted-foreground/60 hover:bg-muted/20")}>
                  {l === "yesterday" ? "vs Yesterday" : "vs Previous Week"}
                </button>
              ))}
            </div>

            <div className="grid grid-cols-2 gap-4">
              {/* Today */}
              <div>
                <div className="flex items-center gap-1.5 mb-3">
                  <Calendar className="w-3.5 h-3.5 text-primary" />
                  <p className="text-[12px] font-semibold">Today</p>
                  <span className="text-[10px] text-muted-foreground/40">({allEvents.length} events)</span>
                </div>
                <div className="space-y-1 max-h-[420px] overflow-y-auto pr-1">
                  {allEvents.slice(0, 15).map(ev => <EventCard key={ev.id} event={ev} compact />)}
                  {allEvents.length === 0 && <p className="text-[11px] text-muted-foreground/40 italic text-center py-4">No events</p>}
                </div>
              </div>

              {/* Reference */}
              <div>
                <div className="flex items-center gap-1.5 mb-3">
                  <Calendar className="w-3.5 h-3.5 text-muted-foreground/50" />
                  <p className="text-[12px] font-semibold text-muted-foreground/70">
                    {compLabel === "yesterday" ? "Yesterday" : "Previous Week"}
                  </p>
                  <Badge variant="outline" className="text-[9px] text-muted-foreground/40">Historical data pending</Badge>
                </div>
                <div className="flex flex-col items-center justify-center h-40 text-muted-foreground/30 border border-dashed border-border/30 rounded-xl">
                  <Layers className="w-8 h-8 mb-2 opacity-30" />
                  <p className="text-[11px]">Historical timeline storage</p>
                  <p className="text-[10px] mt-1">available in a future phase</p>
                </div>
              </div>
            </div>

            {/* Stat comparison */}
            <div className="mt-4 p-4 rounded-xl border border-border/30 bg-muted/5">
              <p className="text-[11px] font-semibold text-muted-foreground/70 mb-3">Today's Session Metrics</p>
              <div className="grid grid-cols-3 md:grid-cols-6 gap-3">
                {[
                  { label: "Total Events", value: allEvents.length },
                  { label: "AI Signals",   value: allEvents.filter(e => e.category === "AI").length },
                  { label: "Portfolio",    value: allEvents.filter(e => e.category === "Portfolio").length },
                  { label: "Risk",         value: allEvents.filter(e => e.category === "Risk").length },
                  { label: "Critical",     value: allEvents.filter(e => e.priority === "critical").length },
                  { label: "Categories",   value: new Set(allEvents.map(e => e.category)).size },
                ].map(({ label, value }) => (
                  <div key={label} className="text-center">
                    <p className="text-[18px] font-bold text-primary">{value}</p>
                    <p className="text-[9px] text-muted-foreground/50">{label}</p>
                  </div>
                ))}
              </div>
            </div>
          </div>
        )}

        {/* ════════════════════════════════════════════════════════ CHECKLIST */}
        {activeTab === "checklist" && (
          <div className="p-6 space-y-4 max-w-xl">
            <div className="flex items-center justify-between mb-2">
              <div className="flex items-center gap-2">
                <CheckSquare className="w-4 h-4 text-emerald-400" />
                <h2 className="text-[14px] font-semibold">Workflow Checklist</h2>
              </div>
              <div className="flex items-center gap-2">
                <span className="text-[11px] text-muted-foreground/60">
                  {checklistProgress.done}/{checklistProgress.total} complete
                </span>
                <button onClick={resetChecklist}
                  className="text-[10px] px-2 py-1 rounded-lg border border-border/30 text-muted-foreground/50 hover:bg-muted/20 transition-colors">
                  Reset
                </button>
              </div>
            </div>

            {/* Progress bar */}
            <div className="w-full h-1.5 bg-muted/30 rounded-full overflow-hidden">
              <div
                className={cn("h-full rounded-full transition-all", checklistProgress.done === checklistProgress.total ? "bg-emerald-500" : "bg-primary")}
                style={{ width: `${(checklistProgress.done / checklistProgress.total) * 100}%` }}
              />
            </div>

            {/* Sections */}
            {Object.entries(checklistSections).map(([section, items]) => {
              const sectionDone = items.filter(c => c.done).length;
              return (
                <div key={section} className="space-y-1">
                  <div className="flex items-center gap-2 py-1.5">
                    <p className="text-[11px] font-semibold text-muted-foreground/70">{section}</p>
                    <span className="text-[9px] text-muted-foreground/40">{sectionDone}/{items.length}</span>
                    {sectionDone === items.length && <span className="text-emerald-400 text-[10px]">✓ Complete</span>}
                  </div>
                  {items.map(item => (
                    <button
                      key={item.id}
                      onClick={() => toggleChecklist(item.id)}
                      className={cn(
                        "w-full flex items-center gap-3 px-3 py-2.5 rounded-xl border text-left transition-all",
                        item.done ? "border-emerald-500/20 bg-emerald-500/5" : "border-border/30 hover:bg-muted/10",
                      )}
                    >
                      {item.done
                        ? <CheckSquare className="w-4 h-4 text-emerald-400 shrink-0" />
                        : <Square className="w-4 h-4 text-muted-foreground/30 shrink-0" />}
                      <span className={cn("text-[12px]", item.done ? "line-through text-muted-foreground/40" : "text-foreground/80")}>
                        {item.label}
                      </span>
                    </button>
                  ))}
                </div>
              );
            })}
          </div>
        )}

        {/* ════════════════════════════════════════════════════════ EXPORT */}
        {activeTab === "export" && (
          <div className="p-6 space-y-6 max-w-xl">
            <div className="flex items-center gap-2 mb-2">
              <Download className="w-4 h-4 text-teal-400" />
              <h2 className="text-[14px] font-semibold">Export</h2>
            </div>

            <div className="space-y-3">
              {/* CSV */}
              <div className="p-4 rounded-xl border border-border/30 bg-muted/5 flex items-center justify-between gap-4">
                <div>
                  <p className="text-[12px] font-semibold">Timeline CSV</p>
                  <p className="text-[10px] text-muted-foreground/50 mt-0.5">
                    All {allEvents.length} events · id, timestamp, agent, category, priority, description, symbol, strategy, confidence
                  </p>
                </div>
                <Button size="sm" variant="outline" onClick={exportCSV} className="text-[11px] shrink-0 gap-1.5">
                  <Download className="w-3 h-3" />CSV
                </Button>
              </div>

              {/* JSON */}
              <div className="p-4 rounded-xl border border-border/30 bg-muted/5 flex items-center justify-between gap-4">
                <div>
                  <p className="text-[12px] font-semibold">Timeline JSON</p>
                  <p className="text-[10px] text-muted-foreground/50 mt-0.5">
                    Full event objects · all fields · machine-readable
                  </p>
                </div>
                <Button size="sm" variant="outline" onClick={exportJSON} className="text-[11px] shrink-0 gap-1.5">
                  <Download className="w-3 h-3" />JSON
                </Button>
              </div>

              {/* Annotations */}
              <div className="p-4 rounded-xl border border-border/30 bg-muted/5 flex items-center justify-between gap-4">
                <div>
                  <p className="text-[12px] font-semibold">Annotations JSON</p>
                  <p className="text-[10px] text-muted-foreground/50 mt-0.5">
                    {annotations.length} annotation{annotations.length !== 1 ? "s" : ""} · notes, tags, bookmarks, lessons
                  </p>
                </div>
                <Button size="sm" variant="outline" onClick={exportAnnotations} disabled={annotations.length === 0} className="text-[11px] shrink-0 gap-1.5">
                  <Download className="w-3 h-3" />JSON
                </Button>
              </div>

              {/* PDF (future) */}
              <div className="p-4 rounded-xl border border-dashed border-border/20 bg-muted/5 flex items-center justify-between gap-4 opacity-50">
                <div>
                  <p className="text-[12px] font-semibold">Timeline Report PDF</p>
                  <p className="text-[10px] text-muted-foreground/50 mt-0.5">
                    Full session report with charts and summaries — planned for a future phase
                  </p>
                </div>
                <Button size="sm" variant="outline" disabled className="text-[11px] shrink-0 gap-1.5">
                  <FileText className="w-3 h-3" />PDF
                </Button>
              </div>
            </div>

            {/* Data summary */}
            <div className="p-4 rounded-xl border border-border/30 bg-muted/5 space-y-3">
              <p className="text-[11px] font-semibold text-muted-foreground/70">Export Summary</p>
              <div className="grid grid-cols-2 gap-3 text-[11px]">
                {[
                  ["Total events",  allEvents.length],
                  ["Annotations",   annotations.length],
                  ["Checklist %",   `${Math.round((checklistProgress.done / checklistProgress.total) * 100)}%`],
                  ["Session date",  new Date().toLocaleDateString("en-IN")],
                ].map(([k, v]) => (
                  <div key={String(k)}>
                    <p className="text-muted-foreground/50 text-[10px]">{k}</p>
                    <p className="font-semibold">{v}</p>
                  </div>
                ))}
              </div>
            </div>
          </div>
        )}

      </div>
    </div>
  );
}
