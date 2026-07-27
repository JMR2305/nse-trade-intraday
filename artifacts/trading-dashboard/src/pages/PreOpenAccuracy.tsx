/**
 * PreOpenAccuracy.tsx — Phase 5B Pre-Open Prediction Validation & Accuracy Analytics
 *
 * PAPER TRADING / ADVISORY ONLY — No trade decisions derived from this page.
 */
import React, { useState, useMemo } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiJson } from "@/lib/api";
import {
  BarChart3, TrendingUp, TrendingDown, Target, AlertTriangle,
  ChevronRight, RefreshCw, Filter, X, ChevronDown, ChevronUp,
  Activity, Wifi, WifiOff, Clock,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

// ── Types ─────────────────────────────────────────────────────────────────────

interface Candidate {
  validation_id: string;
  symbol: string;
  sector: string;
  preopen_rank: number | null;
  opportunity_score: number;
  classification: string;
  gap_percent: number | null;
  imbalance_percent: number;
  executed_quantity: number;
  actual_open: number | null;
  price_0930: number | null;
  price_1030: number | null;
  intraday_high: number | null;
  intraday_low: number | null;
  return_0930: number | null;
  return_1000: number | null;
  return_1030: number | null;
  closing_return: number | null;
  max_favourable_excursion: number | null;
  max_adverse_excursion: number | null;
  prediction_result: string;
  validation_status: string;
  data_quality_status: string;
  open_error_percent: number | null;
  indicative_price: number | null;
  final_preopen_price: number | null;
  previous_close: number | null;
  price_0920: number | null;
  price_1000: number | null;
  closing_price: number | null;
  liquidity_score: number;
  vix_context: number | null;
  trading_date: string;
  continuation_flag: boolean;
  reversal_flag: boolean;
}

interface SessionMetrics {
  total_candidates: number;
  valid_candidates: number;
  confirmed_candidates: number;
  continuation_rate: number | null;
  reversal_rate: number | null;
  top5_accuracy: number | null;
  top10_accuracy: number | null;
  avg_return_0930: number | null;
  avg_return_1030: number | null;
  data_completeness_pct: number;
  sample_size_warning: boolean;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function fmt(v: number | null | undefined, decimals = 2): string {
  if (v == null) return "—";
  return `${v >= 0 ? "+" : ""}${Number(v).toFixed(decimals)}%`;
}

function fmtPrice(v: number | null | undefined): string {
  if (v == null) return "—";
  return `₹${Number(v).toFixed(2)}`;
}

function outcomeColor(o: string): string {
  if (o === "STRONG_CONTINUATION")   return "text-green-600 dark:text-green-400";
  if (o === "MODERATE_CONTINUATION") return "text-emerald-500";
  if (o === "EARLY_REVERSAL")        return "text-red-600 dark:text-red-400";
  if (o === "LATE_REVERSAL")         return "text-orange-500";
  if (o === "FALSE_BREAKOUT")        return "text-amber-500";
  if (o === "FLAT")                  return "text-muted-foreground";
  if (o === "NO_LIQUIDITY")          return "text-slate-500";
  return "text-muted-foreground";
}

function returnColor(v: number | null): string {
  if (v == null) return "";
  return v > 0 ? "text-green-600 dark:text-green-400" : v < 0 ? "text-red-500" : "";
}

// ── Summary Card ─────────────────────────────────────────────────────────────

function SummaryCard({ label, value, sub, icon: Icon, highlight }: {
  label: string; value: string; sub?: string;
  icon?: React.ElementType; highlight?: "green" | "red" | "amber" | "default";
}) {
  const colors: Record<string, string> = {
    green:   "border-green-500/30 bg-green-500/5",
    red:     "border-red-500/30   bg-red-500/5",
    amber:   "border-amber-500/30 bg-amber-500/5",
    default: "border-border/60",
  };
  return (
    <div className={cn(
      "rounded-xl border bg-card p-4 flex flex-col gap-1",
      colors[highlight || "default"]
    )}>
      <div className="flex items-center gap-2 text-muted-foreground text-[11px] font-semibold uppercase tracking-wide">
        {Icon && <Icon className="h-3.5 w-3.5" />}
        {label}
      </div>
      <div className="text-2xl font-bold">{value}</div>
      {sub && <div className="text-[11px] text-muted-foreground">{sub}</div>}
    </div>
  );
}

// ── Outcome Badge ─────────────────────────────────────────────────────────────

function OutcomeBadge({ outcome }: { outcome: string }) {
  const colors: Record<string, string> = {
    STRONG_CONTINUATION:   "bg-green-500/15 text-green-700 dark:text-green-400 border-green-500/30",
    MODERATE_CONTINUATION: "bg-emerald-500/15 text-emerald-700 dark:text-emerald-400 border-emerald-500/30",
    EARLY_REVERSAL:        "bg-red-500/15 text-red-700 dark:text-red-400 border-red-500/30",
    LATE_REVERSAL:         "bg-orange-500/15 text-orange-700 dark:text-orange-400 border-orange-500/30",
    FALSE_BREAKOUT:        "bg-amber-500/15 text-amber-700 dark:text-amber-400 border-amber-500/30",
    FLAT:                  "bg-slate-500/15 text-slate-600 dark:text-slate-400 border-slate-500/30",
    NO_LIQUIDITY:          "bg-zinc-500/15 text-zinc-600 dark:text-zinc-400 border-zinc-500/30",
    DATA_INCOMPLETE:       "bg-muted/40 text-muted-foreground border-border/40",
    INVALID_SIGNAL:        "bg-muted/40 text-muted-foreground border-border/40",
  };
  const label = outcome.replace(/_/g, " ");
  return (
    <span className={cn(
      "inline-flex items-center rounded-full border px-2 py-0.5 text-[10px] font-semibold whitespace-nowrap",
      colors[outcome] || "bg-muted/40 text-muted-foreground border-border/40"
    )}>
      {label}
    </span>
  );
}

// ── Detail Drawer ─────────────────────────────────────────────────────────────

function DetailDrawer({ candidate, onClose }: { candidate: Candidate; onClose: () => void }) {
  const checkpoints = [
    { label: "Prev Close",   price: candidate.previous_close,   ret: null },
    { label: "Indicative",   price: candidate.indicative_price,  ret: null },
    { label: "Pre-Open Final",price: candidate.final_preopen_price, ret: null },
    { label: "Actual Open",  price: candidate.actual_open,       ret: 0 },
    { label: "09:20",        price: candidate.price_0920,        ret: candidate.return_0930 },
    { label: "09:30",        price: candidate.price_0930,        ret: candidate.return_0930 },
    { label: "10:00",        price: candidate.price_1000,        ret: candidate.return_1000 },
    { label: "10:30",        price: candidate.price_1030,        ret: candidate.return_1030 },
    { label: "Day High",     price: candidate.intraday_high,     ret: null },
    { label: "Day Low",      price: candidate.intraday_low,      ret: null },
    { label: "Close",        price: candidate.closing_price,     ret: candidate.closing_return },
  ];
  return (
    <div className="fixed inset-0 z-50 flex">
      <div className="flex-1 bg-foreground/20 backdrop-blur-sm" onClick={onClose} />
      <aside className="w-[440px] flex flex-col bg-background border-l border-border overflow-y-auto">
        <div className="flex items-center justify-between px-5 py-4 border-b border-border">
          <div>
            <div className="font-bold text-lg">{candidate.symbol}</div>
            <div className="text-[11px] text-muted-foreground">{candidate.sector} · Rank #{candidate.preopen_rank ?? "—"}</div>
          </div>
          <button onClick={onClose} className="grid h-7 w-7 place-items-center rounded-lg hover:bg-muted">
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="px-5 py-4 space-y-5">
          {/* Outcome */}
          <div>
            <div className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground mb-2">Outcome</div>
            <OutcomeBadge outcome={candidate.prediction_result} />
            <div className="mt-1 text-[11px] text-muted-foreground">
              Data quality: <span className="font-medium">{candidate.data_quality_status}</span>
            </div>
          </div>

          {/* Price timeline */}
          <div>
            <div className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground mb-2">Price Timeline</div>
            <div className="space-y-1">
              {checkpoints.map(({ label, price, ret }) => (
                <div key={label} className="flex items-center justify-between text-[12px] py-0.5">
                  <span className="text-muted-foreground w-28">{label}</span>
                  <span className="font-mono">{fmtPrice(price)}</span>
                  {ret !== null && <span className={cn("font-mono text-[11px]", returnColor(ret))}>{fmt(ret)}</span>}
                </div>
              ))}
            </div>
          </div>

          {/* Excursions */}
          <div>
            <div className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground mb-2">Excursions (vs Open)</div>
            <div className="grid grid-cols-2 gap-2">
              <div className="rounded-lg border border-green-500/20 bg-green-500/5 p-2.5">
                <div className="text-[10px] text-muted-foreground">Max Favourable</div>
                <div className="font-bold text-green-600 dark:text-green-400">
                  {fmt(candidate.max_favourable_excursion)}
                </div>
              </div>
              <div className="rounded-lg border border-red-500/20 bg-red-500/5 p-2.5">
                <div className="text-[10px] text-muted-foreground">Max Adverse</div>
                <div className="font-bold text-red-500">
                  {fmt(candidate.max_adverse_excursion)}
                </div>
              </div>
            </div>
          </div>

          {/* Pre-open factors */}
          <div>
            <div className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground mb-2">Pre-Open Factors</div>
            <div className="space-y-1.5 text-[12px]">
              {[
                ["Gap %",       fmt(candidate.gap_percent)],
                ["Imbalance %", fmt(candidate.imbalance_percent)],
                ["Opp Score",   `${candidate.opportunity_score.toFixed(1)}/100`],
                ["Liquidity",   `${candidate.liquidity_score.toFixed(1)}/100`],
                ["Exec Qty",    candidate.executed_quantity.toLocaleString()],
                ["VIX",         candidate.vix_context != null ? candidate.vix_context.toFixed(1) : "—"],
                ["Open Error",  candidate.open_error_percent != null ? `${candidate.open_error_percent.toFixed(2)}%` : "—"],
              ].map(([k, v]) => (
                <div key={k} className="flex justify-between">
                  <span className="text-muted-foreground">{k}</span>
                  <span className="font-mono font-medium">{v}</span>
                </div>
              ))}
            </div>
          </div>

          {/* Data quality warnings */}
          {candidate.data_quality_status !== "COMPLETE" && (
            <div className="rounded-lg border border-amber-500/30 bg-amber-500/8 p-3">
              <div className="flex items-center gap-1.5 text-amber-600 dark:text-amber-400 text-[11px] font-semibold mb-1">
                <AlertTriangle className="h-3.5 w-3.5" />
                Data Quality Warning
              </div>
              <div className="text-[11px] text-muted-foreground">
                Status: {candidate.data_quality_status}
                {candidate.validation_status === "EXCLUDED" && " — excluded from accuracy metrics"}
              </div>
            </div>
          )}

          <div className="text-[10px] text-muted-foreground border-t border-border pt-3">
            PAPER / ADVISORY ONLY — No trade decisions derived from pre-open validation data.
          </div>
        </div>
      </aside>
    </div>
  );
}

// ── Disabled State ────────────────────────────────────────────────────────────

function DisabledState() {
  return (
    <div className="flex flex-col items-center justify-center py-24 gap-4">
      <WifiOff className="h-12 w-12 text-muted-foreground/40" />
      <div className="text-xl font-semibold">Pre-Open Accuracy Disabled</div>
      <div className="text-sm text-muted-foreground max-w-sm text-center">
        Set <code className="bg-muted px-1 rounded">PREOPEN_VALIDATION_ENABLED=true</code> to enable prediction validation.
      </div>
      <Badge variant="outline" className="text-[10px] font-semibold uppercase tracking-widest">
        PAPER / ADVISORY ONLY
      </Badge>
    </div>
  );
}

// ── Main Page ─────────────────────────────────────────────────────────────────

export default function PreOpenAccuracy() {
  const qc = useQueryClient();

  // Filters
  const [dateFilter,         setDateFilter]         = useState("");
  const [sectorFilter,       setSectorFilter]       = useState("");
  const [outcomeFilter,      setOutcomeFilter]      = useState("");
  const [classificationFilter, setClassificationFilter] = useState("");
  const [gapFilter,          setGapFilter]          = useState("");    // "up"|"down"|""
  const [imbalanceFilter,    setImbalanceFilter]    = useState("");    // "buy"|"sell"|""
  const [scoreMin,           setScoreMin]           = useState("");
  const [scoreMax,           setScoreMax]           = useState("");
  const [sortKey,            setSortKey]            = useState<keyof Candidate>("preopen_rank");
  const [sortDir,            setSortDir]            = useState<"asc"|"desc">("asc");
  const [selected,           setSelected]           = useState<Candidate | null>(null);
  const [activeTab,          setActiveTab]          = useState<"candidates"|"daily"|"score-bands"|"factors">("candidates");

  // Queries
  const statusQ = useQuery({
    queryKey: ["pv-status"],
    queryFn: () => apiJson<any>("/preopen-validation/status"),
    refetchInterval: 60_000,
  });

  const candidatesQ = useQuery({
    queryKey: ["pv-candidates", dateFilter],
    queryFn: () => apiJson<any>(`/preopen-validation/candidates${dateFilter ? `?date=${dateFilter}` : ""}`),
    refetchInterval: 90_000,
  });

  const dailyQ = useQuery({
    queryKey: ["pv-daily", dateFilter],
    queryFn: () => apiJson<any>(`/preopen-validation/daily${dateFilter ? `?date=${dateFilter}` : ""}`),
    refetchInterval: 120_000,
  });

  const scoreBandsQ = useQuery({
    queryKey: ["pv-score-bands", dateFilter],
    queryFn: () => apiJson<any>(`/preopen-validation/score-bands${dateFilter ? `?date=${dateFilter}` : ""}`),
  });

  const factorsQ = useQuery({
    queryKey: ["pv-factors", dateFilter],
    queryFn: () => apiJson<any>(`/preopen-validation/factors${dateFilter ? `?date=${dateFilter}` : ""}`),
  });

  const runMut = useMutation({
    mutationFn: () => apiJson<any>("/preopen-validation/run", { method: "POST" }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["pv-status"] });
      qc.invalidateQueries({ queryKey: ["pv-candidates"] });
      qc.invalidateQueries({ queryKey: ["pv-daily"] });
    },
  });

  const disabled = statusQ.data?.status === "DISABLED";

  if (disabled) return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">Pre-Open Accuracy</h1>
          <p className="text-sm text-muted-foreground mt-0.5">PAPER / ADVISORY ONLY</p>
        </div>
      </div>
      <DisabledState />
    </div>
  );

  // ── Data extraction ─────────────────────────────────────────────────────────

  const candidates: Candidate[] = candidatesQ.data?.candidates || [];
  const metrics: SessionMetrics | null = dailyQ.data?.metrics || null;
  const scoreBands: any[] = scoreBandsQ.data?.score_bands || [];
  const factors: any[] = factorsQ.data?.factors || [];
  const tradingDate: string = dailyQ.data?.trading_date || candidatesQ.data?.trading_date || "—";

  // ── Filter + sort candidates ────────────────────────────────────────────────

  const filtered = useMemo(() => {
    let rows = [...candidates];
    if (sectorFilter)        rows = rows.filter(r => r.sector?.toLowerCase().includes(sectorFilter.toLowerCase()));
    if (outcomeFilter)       rows = rows.filter(r => r.prediction_result === outcomeFilter);
    if (classificationFilter) rows = rows.filter(r => r.classification === classificationFilter);
    if (gapFilter === "up")  rows = rows.filter(r => (r.gap_percent || 0) > 0);
    if (gapFilter === "down") rows = rows.filter(r => (r.gap_percent || 0) < 0);
    if (imbalanceFilter === "buy")  rows = rows.filter(r => (r.imbalance_percent || 0) > 10);
    if (imbalanceFilter === "sell") rows = rows.filter(r => (r.imbalance_percent || 0) < -10);
    if (scoreMin) rows = rows.filter(r => r.opportunity_score >= Number(scoreMin));
    if (scoreMax) rows = rows.filter(r => r.opportunity_score <= Number(scoreMax));

    rows.sort((a, b) => {
      const va = a[sortKey] ?? (sortDir === "asc" ? Infinity : -Infinity);
      const vb = b[sortKey] ?? (sortDir === "asc" ? Infinity : -Infinity);
      if (va < vb) return sortDir === "asc" ? -1 : 1;
      if (va > vb) return sortDir === "asc" ? 1 : -1;
      return 0;
    });
    return rows;
  }, [candidates, sectorFilter, outcomeFilter, classificationFilter,
      gapFilter, imbalanceFilter, scoreMin, scoreMax, sortKey, sortDir]);

  function toggleSort(key: keyof Candidate) {
    if (sortKey === key) setSortDir(d => d === "asc" ? "desc" : "asc");
    else { setSortKey(key); setSortDir("asc"); }
  }

  function SortIcon({ k }: { k: string }) {
    if (sortKey !== k) return <ChevronDown className="h-3 w-3 opacity-30" />;
    return sortDir === "asc"
      ? <ChevronUp className="h-3 w-3 text-primary" />
      : <ChevronDown className="h-3 w-3 text-primary" />;
  }

  const uniqueSectors  = [...new Set(candidates.map(c => c.sector).filter(Boolean))];
  const uniqueOutcomes = [...new Set(candidates.map(c => c.prediction_result).filter(Boolean))];

  // ── Summary cards ───────────────────────────────────────────────────────────

  const summaryCards = [
    { label: "Sessions Analysed",  value: dailyQ.data?.sessions_available?.length ?? "—",  icon: Activity },
    { label: "Candidates",         value: metrics?.total_candidates ?? candidates.length,    icon: Target },
    { label: "Top-10 Accuracy",    value: metrics?.top10_accuracy != null ? `${metrics.top10_accuracy}%` : "—",
                                   icon: BarChart3, highlight: (metrics?.top10_accuracy ?? 0) >= 55 ? "green" as const : undefined },
    { label: "Continuation Rate",  value: metrics?.continuation_rate != null ? `${metrics.continuation_rate}%` : "—",
                                   icon: TrendingUp, highlight: (metrics?.continuation_rate ?? 0) >= 55 ? "green" as const : "default" as const },
    { label: "Reversal Rate",      value: metrics?.reversal_rate != null ? `${metrics.reversal_rate}%` : "—",
                                   icon: TrendingDown, highlight: (metrics?.reversal_rate ?? 0) >= 50 ? "red" as const : undefined },
    { label: "Avg 09:30 Return",   value: metrics?.avg_return_0930 != null ? fmt(metrics.avg_return_0930) : "—",
                                   icon: Clock, highlight: (metrics?.avg_return_0930 ?? 0) > 0 ? "green" as const : undefined },
    { label: "Avg 10:30 Return",   value: metrics?.avg_return_1030 != null ? fmt(metrics.avg_return_1030) : "—",
                                   icon: Clock },
    { label: "Data Completeness",  value: metrics?.data_completeness_pct != null ? `${metrics.data_completeness_pct}%` : "—",
                                   icon: Wifi, highlight: (metrics?.data_completeness_pct ?? 0) >= 80 ? "green" as const : "amber" as const },
  ];

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold">Pre-Open Accuracy</h1>
          <p className="text-sm text-muted-foreground mt-0.5">
            {tradingDate !== "—" ? `Trading date: ${tradingDate}` : "Pre-Open Prediction Validation"}
            {" · "}
            <span className="text-amber-600 dark:text-amber-400 font-medium">PAPER / ADVISORY ONLY</span>
          </p>
        </div>
        <div className="flex items-center gap-2">
          {metrics?.sample_size_warning && (
            <span className="inline-flex items-center gap-1 text-[11px] text-amber-600 dark:text-amber-400 bg-amber-500/10 border border-amber-500/30 rounded-lg px-2.5 py-1">
              <AlertTriangle className="h-3 w-3" />
              Small sample — treat as inconclusive
            </span>
          )}
          <Button size="sm" variant="outline" onClick={() => runMut.mutate()} disabled={runMut.isPending}>
            <RefreshCw className={cn("h-3.5 w-3.5 mr-1.5", runMut.isPending && "animate-spin")} />
            Run Validation
          </Button>
        </div>
      </div>

      {/* Summary cards */}
      <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-8 gap-3">
        {summaryCards.map(c => (
          <SummaryCard key={c.label} label={c.label} value={String(c.value)}
            icon={c.icon} highlight={c.highlight} />
        ))}
      </div>

      {/* Tab bar */}
      <div className="flex gap-1 border-b border-border">
        {(["candidates", "daily", "score-bands", "factors"] as const).map(tab => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab)}
            className={cn(
              "px-3 py-2 text-[13px] font-medium border-b-2 transition-colors -mb-px",
              activeTab === tab
                ? "border-primary text-foreground"
                : "border-transparent text-muted-foreground hover:text-foreground"
            )}
          >
            {tab === "candidates" ? "Candidates" :
             tab === "daily"      ? "Daily Summary" :
             tab === "score-bands"? "Score Bands" : "Factor Analysis"}
          </button>
        ))}
      </div>

      {/* ── Candidates tab ───────────────────────────────────────────────────── */}
      {activeTab === "candidates" && (
        <div className="space-y-3">
          {/* Filters */}
          <div className="flex flex-wrap gap-2 items-center">
            <Filter className="h-3.5 w-3.5 text-muted-foreground" />
            <input value={sectorFilter} onChange={e => setSectorFilter(e.target.value)}
              placeholder="Sector…" className="h-7 rounded-lg border border-border bg-card/60 px-2.5 text-[12px] w-28 focus:outline-none focus:ring-1 focus:ring-primary/30" />
            <select value={outcomeFilter} onChange={e => setOutcomeFilter(e.target.value)}
              className="h-7 rounded-lg border border-border bg-card/60 px-2 text-[12px] focus:outline-none">
              <option value="">All outcomes</option>
              {uniqueOutcomes.map(o => <option key={o} value={o}>{o.replace(/_/g," ")}</option>)}
            </select>
            <select value={gapFilter} onChange={e => setGapFilter(e.target.value)}
              className="h-7 rounded-lg border border-border bg-card/60 px-2 text-[12px] focus:outline-none">
              <option value="">Gap dir.</option>
              <option value="up">Gap Up</option>
              <option value="down">Gap Down</option>
            </select>
            <select value={imbalanceFilter} onChange={e => setImbalanceFilter(e.target.value)}
              className="h-7 rounded-lg border border-border bg-card/60 px-2 text-[12px] focus:outline-none">
              <option value="">Imbalance</option>
              <option value="buy">Buy</option>
              <option value="sell">Sell</option>
            </select>
            <input value={scoreMin} onChange={e => setScoreMin(e.target.value)}
              type="number" placeholder="Score ≥" className="h-7 w-20 rounded-lg border border-border bg-card/60 px-2 text-[12px] focus:outline-none" />
            <input value={scoreMax} onChange={e => setScoreMax(e.target.value)}
              type="number" placeholder="Score ≤" className="h-7 w-20 rounded-lg border border-border bg-card/60 px-2 text-[12px] focus:outline-none" />
            {(sectorFilter || outcomeFilter || gapFilter || imbalanceFilter || scoreMin || scoreMax) && (
              <button onClick={() => { setSectorFilter(""); setOutcomeFilter(""); setGapFilter(""); setImbalanceFilter(""); setScoreMin(""); setScoreMax(""); }}
                className="h-7 flex items-center gap-1 rounded-lg border border-border px-2 text-[12px] text-muted-foreground hover:text-foreground">
                <X className="h-3 w-3" /> Clear
              </button>
            )}
            <span className="ml-auto text-[11px] text-muted-foreground">{filtered.length} candidates</span>
          </div>

          {/* Table */}
          <div className="overflow-x-auto rounded-xl border border-border">
            <table className="w-full text-[12px]">
              <thead>
                <tr className="border-b border-border bg-muted/30">
                  {([
                    ["preopen_rank", "Rank"],
                    ["symbol", "Symbol"],
                    ["sector", "Sector"],
                    ["opportunity_score", "Score"],
                    ["classification", "Classification"],
                    ["gap_percent", "Gap %"],
                    ["imbalance_percent", "Imbalance %"],
                    ["executed_quantity", "Exec Qty"],
                    ["actual_open", "Open"],
                    ["price_0930", "09:30"],
                    ["price_1030", "10:30"],
                    ["intraday_high", "High"],
                    ["intraday_low", "Low"],
                    ["return_0930", "Return"],
                    ["prediction_result", "Outcome"],
                  ] as [keyof Candidate, string][]).map(([k, label]) => (
                    <th key={k} onClick={() => toggleSort(k)}
                      className="px-3 py-2.5 text-left font-semibold text-muted-foreground cursor-pointer hover:text-foreground whitespace-nowrap select-none">
                      <span className="flex items-center gap-1">{label}<SortIcon k={k} /></span>
                    </th>
                  ))}
                  <th className="px-3 py-2.5" />
                </tr>
              </thead>
              <tbody>
                {filtered.length === 0 && (
                  <tr>
                    <td colSpan={16} className="text-center py-12 text-muted-foreground">
                      {candidatesQ.isLoading ? "Loading…" : "No candidates"}
                    </td>
                  </tr>
                )}
                {filtered.map(c => (
                  <tr key={c.validation_id || c.symbol}
                    onClick={() => setSelected(c)}
                    className="border-b border-border/40 hover:bg-muted/30 cursor-pointer transition-colors">
                    <td className="px-3 py-2 font-mono text-center text-muted-foreground">{c.preopen_rank ?? "—"}</td>
                    <td className="px-3 py-2 font-bold">{c.symbol}</td>
                    <td className="px-3 py-2 text-muted-foreground">{c.sector || "—"}</td>
                    <td className="px-3 py-2 font-mono">{c.opportunity_score.toFixed(1)}</td>
                    <td className="px-3 py-2 text-muted-foreground text-[11px]">{c.classification?.replace(/_/g," ") || "—"}</td>
                    <td className={cn("px-3 py-2 font-mono", returnColor(c.gap_percent))}>{fmt(c.gap_percent)}</td>
                    <td className={cn("px-3 py-2 font-mono", returnColor(c.imbalance_percent))}>{fmt(c.imbalance_percent)}</td>
                    <td className="px-3 py-2 font-mono text-muted-foreground">{c.executed_quantity.toLocaleString()}</td>
                    <td className="px-3 py-2 font-mono">{fmtPrice(c.actual_open)}</td>
                    <td className={cn("px-3 py-2 font-mono", returnColor(c.return_0930))}>{fmtPrice(c.price_0930)}</td>
                    <td className={cn("px-3 py-2 font-mono", returnColor(c.return_1030))}>{fmtPrice(c.price_1030)}</td>
                    <td className="px-3 py-2 font-mono text-green-600 dark:text-green-400">{fmtPrice(c.intraday_high)}</td>
                    <td className="px-3 py-2 font-mono text-red-500">{fmtPrice(c.intraday_low)}</td>
                    <td className={cn("px-3 py-2 font-mono font-semibold", returnColor(c.return_0930))}>{fmt(c.return_0930)}</td>
                    <td className="px-3 py-2"><OutcomeBadge outcome={c.prediction_result} /></td>
                    <td className="px-3 py-2 text-muted-foreground"><ChevronRight className="h-4 w-4" /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* ── Daily Summary tab ────────────────────────────────────────────────── */}
      {activeTab === "daily" && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          <div className="rounded-xl border border-border bg-card p-5 space-y-3">
            <div className="font-semibold text-[13px]">Session Metrics</div>
            {metrics ? (
              <div className="space-y-2 text-[12px]">
                {[
                  ["Total candidates", metrics.total_candidates],
                  ["Valid candidates", metrics.valid_candidates],
                  ["Continuation rate", metrics.continuation_rate != null ? `${metrics.continuation_rate}%` : "—"],
                  ["Reversal rate",     metrics.reversal_rate != null     ? `${metrics.reversal_rate}%`     : "—"],
                  ["Top-5 accuracy",   metrics.top5_accuracy != null     ? `${metrics.top5_accuracy}%`     : "—"],
                  ["Top-10 accuracy",  metrics.top10_accuracy != null    ? `${metrics.top10_accuracy}%`    : "—"],
                  ["Avg 09:30 return", metrics.avg_return_0930 != null   ? fmt(metrics.avg_return_0930)    : "—"],
                  ["Avg 10:30 return", metrics.avg_return_1030 != null   ? fmt(metrics.avg_return_1030)    : "—"],
                  ["Data completeness",`${metrics.data_completeness_pct}%`],
                ].map(([k, v]) => (
                  <div key={k} className="flex justify-between border-b border-border/40 pb-1">
                    <span className="text-muted-foreground">{k}</span>
                    <span className="font-medium">{v}</span>
                  </div>
                ))}
                {metrics.sample_size_warning && (
                  <div className="flex items-center gap-1.5 text-amber-600 dark:text-amber-400 text-[11px] pt-1">
                    <AlertTriangle className="h-3 w-3" />
                    Small sample — treat results as inconclusive
                  </div>
                )}
              </div>
            ) : (
              <div className="text-muted-foreground text-[12px]">No metrics available for this date.</div>
            )}
          </div>
          <div className="rounded-xl border border-border bg-card p-5">
            <div className="font-semibold text-[13px] mb-3">Available Sessions</div>
            <div className="space-y-1.5">
              {(dailyQ.data?.sessions_available || []).map((d: string) => (
                <button key={d} onClick={() => setDateFilter(d)}
                  className={cn("w-full text-left px-3 py-1.5 rounded-lg text-[12px] transition-colors",
                    dateFilter === d ? "bg-primary/10 text-primary font-semibold" : "hover:bg-muted/50 text-muted-foreground")}>
                  {d}
                </button>
              ))}
              {(!dailyQ.data?.sessions_available?.length) && (
                <div className="text-[12px] text-muted-foreground">No sessions recorded yet.</div>
              )}
            </div>
          </div>
        </div>
      )}

      {/* ── Score Bands tab ──────────────────────────────────────────────────── */}
      {activeTab === "score-bands" && (
        <div className="overflow-x-auto rounded-xl border border-border">
          <table className="w-full text-[12px]">
            <thead>
              <tr className="border-b border-border bg-muted/30">
                {["Band","Candidates","Continuation","Reversal","Avg 09:30","Avg 10:30","Avg Close","Avg MFE","Avg MAE","Note"].map(h => (
                  <th key={h} className="px-4 py-3 text-left font-semibold text-muted-foreground whitespace-nowrap">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {scoreBands.length === 0 && (
                <tr><td colSpan={10} className="text-center py-10 text-muted-foreground">No score-band data available.</td></tr>
              )}
              {scoreBands.map((b: any) => (
                <tr key={b.band} className="border-b border-border/40">
                  <td className="px-4 py-2.5 font-bold">{b.band}</td>
                  <td className="px-4 py-2.5 text-center">{b.candidates}</td>
                  <td className={cn("px-4 py-2.5 text-center font-mono", b.continuation_rate >= 55 ? "text-green-600 dark:text-green-400" : "")}>
                    {b.continuation_rate != null ? `${b.continuation_rate}%` : "—"}
                  </td>
                  <td className={cn("px-4 py-2.5 text-center font-mono", b.reversal_rate >= 50 ? "text-red-500" : "")}>
                    {b.reversal_rate != null ? `${b.reversal_rate}%` : "—"}
                  </td>
                  <td className={cn("px-4 py-2.5 font-mono", returnColor(b.avg_return_0930))}>{b.avg_return_0930 != null ? fmt(b.avg_return_0930) : "—"}</td>
                  <td className={cn("px-4 py-2.5 font-mono", returnColor(b.avg_return_1030))}>{b.avg_return_1030 != null ? fmt(b.avg_return_1030) : "—"}</td>
                  <td className={cn("px-4 py-2.5 font-mono", returnColor(b.avg_closing_return))}>{b.avg_closing_return != null ? fmt(b.avg_closing_return) : "—"}</td>
                  <td className="px-4 py-2.5 font-mono text-green-600 dark:text-green-400">{b.avg_mfe != null ? fmt(b.avg_mfe) : "—"}</td>
                  <td className="px-4 py-2.5 font-mono text-red-500">{b.avg_mae != null ? fmt(b.avg_mae) : "—"}</td>
                  <td className="px-4 py-2.5 text-[11px] text-muted-foreground">
                    {b.inconclusive ? "Inconclusive" : b.candidates < 5 ? "Low sample" : ""}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* ── Factor Analysis tab ──────────────────────────────────────────────── */}
      {activeTab === "factors" && (
        <div className="overflow-x-auto rounded-xl border border-border">
          <table className="w-full text-[12px]">
            <thead>
              <tr className="border-b border-border bg-muted/30">
                {["Factor","Sample","Success Rate","Avg Return","Failure Rate","Reliability","Note"].map(h => (
                  <th key={h} className="px-4 py-3 text-left font-semibold text-muted-foreground whitespace-nowrap">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {factors.length === 0 && (
                <tr><td colSpan={7} className="text-center py-10 text-muted-foreground">No factor data available.</td></tr>
              )}
              {factors.map((f: any) => (
                <tr key={f.factor} className="border-b border-border/40">
                  <td className="px-4 py-2.5 font-semibold capitalize">{f.factor.replace(/_/g," ")}</td>
                  <td className="px-4 py-2.5 text-center text-muted-foreground">{f.sample_size}</td>
                  <td className={cn("px-4 py-2.5 font-mono", (f.factor_success_rate ?? 0) >= 55 ? "text-green-600 dark:text-green-400" : "")}>
                    {f.factor_success_rate != null ? `${f.factor_success_rate}%` : "—"}
                  </td>
                  <td className={cn("px-4 py-2.5 font-mono", returnColor(f.factor_avg_return))}>
                    {f.factor_avg_return != null ? fmt(f.factor_avg_return) : "—"}
                  </td>
                  <td className={cn("px-4 py-2.5 font-mono", (f.factor_failure_rate ?? 0) >= 40 ? "text-red-500" : "")}>
                    {f.factor_failure_rate != null ? `${f.factor_failure_rate}%` : "—"}
                  </td>
                  <td className="px-4 py-2.5 font-mono">
                    {f.factor_reliability_score != null ? f.factor_reliability_score : "—"}
                  </td>
                  <td className="px-4 py-2.5 text-[11px] text-muted-foreground">
                    {f.inconclusive ? "Insufficient data — inconclusive" : f.note || ""}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="px-4 py-2.5 border-t border-border/40 text-[10px] text-muted-foreground">
            Factor analysis is observational only. Do not infer causality. Low-sample results are marked inconclusive.
          </div>
        </div>
      )}

      {/* Detail drawer */}
      {selected && <DetailDrawer candidate={selected} onClose={() => setSelected(null)} />}
    </div>
  );
}
