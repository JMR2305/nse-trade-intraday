/**
 * PreOpenIntelligence — Phase 5A Pre-Open Intelligence page.
 *
 * Shows NSE pre-open session data (09:00–09:15 IST):
 *  - Status summary bar
 *  - Six highlight cards
 *  - Filterable ranked table (15 columns)
 *  - Detail drawer
 *
 * PAPER TRADING / ADVISORY ONLY. No trade entries from this page.
 */
import React, { useState, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  TrendingUp, TrendingDown, Activity, BarChart3, Wifi, WifiOff,
  ChevronDown, ChevronUp, RefreshCw, AlertTriangle, Clock,
  ArrowUpRight, ArrowDownRight, Minus, Filter, X, Eye,
  CheckCircle2, Target, Percent, BarChart2,
} from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { apiJson } from "@/lib/api";
import { cn } from "@/lib/utils";

// ── Types ─────────────────────────────────────────────────────────────────────

interface Snapshot {
  symbol: string;
  sector: string;
  previous_close: number;
  indicative_open_price: number | null;
  gap_percent: number | null;
  total_buy_quantity: number;
  total_sell_quantity: number;
  imbalance_percent: number;
  final_executed_quantity: number;
  opportunity_score: number;
  classification: string;
  is_stale: boolean;
  source_status: string;
  data_freshness_seconds: number;
  factor_scores: Record<string, number>;
  liquidity_score: number;
  buy_sell_imbalance: number;
  validation_status: string;
  data_source: string;                      // "nse_official" | "zerodha_kite" | "yfinance" | "mock"
  provider_label: string;                   // human-readable provider name
  order_book_available: boolean;            // true only when auction buy/sell qty are real
}

interface SnapshotResponse {
  success: boolean;
  trading_date: string;
  session: { status?: string; provider_status?: string; provider_label?: string; frozen_at?: string } | null;
  snapshots: Snapshot[];
  valid_count: number;
  stale_count: number;
  label: string;
  status?: string;
  message?: string;
  provider_label?: string;                  // active provider label from the engine
}

interface AccuracyResponse {
  success?: boolean;
  status?: string;
  available: boolean;
  trading_date?: string;
  session_id?: string;
  reconciled_at?: string;
  symbols_reconciled?: number;
  with_error_count?: number;
  with_direction_count?: number;
  watchlist_total?: number;
  watchlist_confirmed_count?: number;
  avg_indicative_to_open_error_pct?: number | null;
  hit_rate_pct?: number | null;
  confirmation_rate_pct?: number | null;
  false_positive_rate_pct?: number | null;
  continuation_rate_pct?: number | null;
  reversal_rate_pct?: number | null;
  grade?: string;
  grade_label?: string;
  message?: string;
  symbols?: Array<{
    symbol: string;
    indicative_price: number | null;
    actual_open: number | null;
    price_at_0920: number | null;
    price_at_0930: number | null;
    error_pct: number | null;
    direction_correct: boolean | null;
    was_in_watchlist: boolean;
    watchlist_confirmed: boolean | null;
  }>;
  label?: string;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function gapColor(gap: number | null) {
  if (gap === null) return "text-muted-foreground";
  if (gap > 1.5) return "text-emerald-600 dark:text-emerald-400";
  if (gap > 0.5) return "text-green-600 dark:text-green-400";
  if (gap < -1.5) return "text-red-600 dark:text-red-400";
  if (gap < -0.5) return "text-orange-600 dark:text-orange-400";
  return "text-muted-foreground";
}

function gapIcon(gap: number | null) {
  if (gap === null) return <Minus className="h-3 w-3" />;
  if (gap > 0.3) return <ArrowUpRight className="h-3 w-3" />;
  if (gap < -0.3) return <ArrowDownRight className="h-3 w-3" />;
  return <Minus className="h-3 w-3" />;
}

function classLabel(cls: string) {
  const map: Record<string, { label: string; color: string }> = {
    STRONG_GAP_UP:      { label: "Strong ↑",      color: "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/30 dark:text-emerald-300" },
    MODERATE_GAP_UP:    { label: "Moderate ↑",    color: "bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-300" },
    FLAT_OPEN:          { label: "Flat",           color: "bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300" },
    MODERATE_GAP_DOWN:  { label: "Moderate ↓",    color: "bg-orange-100 text-orange-800 dark:bg-orange-900/30 dark:text-orange-300" },
    STRONG_GAP_DOWN:    { label: "Strong ↓",      color: "bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-300" },
    BUY_IMBALANCE:      { label: "Buy Pressure",  color: "bg-blue-100 text-blue-800 dark:bg-blue-900/30 dark:text-blue-300" },
    SELL_IMBALANCE:     { label: "Sell Pressure", color: "bg-purple-100 text-purple-800 dark:bg-purple-900/30 dark:text-purple-300" },
    HIGH_PARTICIPATION: { label: "High Vol",      color: "bg-cyan-100 text-cyan-800 dark:bg-cyan-900/30 dark:text-cyan-300" },
    LOW_LIQUIDITY:      { label: "Low Liq",       color: "bg-yellow-100 text-yellow-800 dark:bg-yellow-900/30 dark:text-yellow-300" },
    DATA_INCOMPLETE:    { label: "No Data",       color: "bg-slate-100 text-slate-500 dark:bg-slate-800 dark:text-slate-400" },
    WATCH_AFTER_OPEN:   { label: "Watch",         color: "bg-amber-100 text-amber-800 dark:bg-amber-900/30 dark:text-amber-300" },
    AVOID_AT_OPEN:      { label: "Avoid",         color: "bg-rose-100 text-rose-800 dark:bg-rose-900/30 dark:text-rose-300" },
  };
  const entry = map[cls] ?? { label: cls, color: "bg-slate-100 text-slate-600" };
  return (
    <span className={cn("inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-semibold", entry.color)}>
      {entry.label}
    </span>
  );
}

/** Maps data_source → short display label for the "Provider" column badge. */
function providerName(dataSource: string | undefined, providerLabel?: string): string {
  if (providerLabel) return providerLabel;
  const map: Record<string, string> = {
    nse_official: "NSE Official",
    zerodha_kite: "Zerodha Kite",
    yfinance:     "Yahoo Finance (Fallback)",
    mock:         "Mock Data",
  };
  return map[dataSource ?? ""] ?? dataSource ?? "Unknown";
}

function providerBadge(status: string, dataSource?: string, label?: string) {
  const colors: Record<string, string> = {
    LIVE: "bg-emerald-500", DELAYED: "bg-amber-500",
    STALE: "bg-orange-500", UNAVAILABLE: "bg-red-500", PARTIAL: "bg-yellow-500",
  };
  const display = label ?? providerName(dataSource);
  return (
    <span className="flex items-center gap-1.5">
      <span className={cn("h-2 w-2 rounded-full flex-shrink-0", colors[status] ?? "bg-slate-400")} />
      <span className="text-xs font-medium">{display}</span>
    </span>
  );
}

function fmt(n: number | null | undefined, decimals = 2): string {
  if (n == null) return "—";
  return n.toFixed(decimals);
}

function fmtQty(n: number | undefined): string {
  if (!n) return "—";
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(0)}K`;
  return String(n);
}

// ── Highlight cards ───────────────────────────────────────────────────────────

function HighlightCard({
  title, icon: Icon, snap, metric,
}: {
  title: string;
  icon: React.ElementType;
  snap: Snapshot | undefined;
  metric: (s: Snapshot) => React.ReactNode;
}) {
  return (
    <Card className="relative overflow-hidden">
      <CardHeader className="pb-2 pt-4 px-4">
        <div className="flex items-center gap-2">
          <Icon className="h-4 w-4 text-muted-foreground" />
          <CardTitle className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
            {title}
          </CardTitle>
        </div>
      </CardHeader>
      <CardContent className="px-4 pb-4">
        {snap ? (
          <>
            <div className="text-lg font-bold tracking-tight">{snap.symbol}</div>
            <div className="text-xs text-muted-foreground">{snap.sector}</div>
            <div className="mt-1">{metric(snap)}</div>
          </>
        ) : (
          <div className="text-sm text-muted-foreground">No data</div>
        )}
      </CardContent>
    </Card>
  );
}

// ── Detail drawer ─────────────────────────────────────────────────────────────

function DetailDrawer({ snap, onClose }: { snap: Snapshot; onClose: () => void }) {
  return (
    <div className="fixed inset-y-0 right-0 z-50 w-full max-w-md shadow-xl bg-card border-l border-border overflow-y-auto">
      <div className="flex items-center justify-between p-4 border-b border-border sticky top-0 bg-card z-10">
        <div>
          <div className="font-bold text-lg">{snap.symbol}</div>
          <div className="text-xs text-muted-foreground">{snap.sector}</div>
        </div>
        <Button variant="ghost" size="icon" onClick={onClose}><X className="h-4 w-4" /></Button>
      </div>

      <div className="p-4 space-y-4">
        {/* Classification + advisory note */}
        <div className="flex items-center gap-2 flex-wrap">
          {classLabel(snap.classification)}
          <span className="text-[10px] text-muted-foreground italic">
            Advisory only — no trade signals
          </span>
        </div>

        {/* Price grid */}
        <Card>
          <CardHeader className="pb-2 pt-3 px-4">
            <CardTitle className="text-xs uppercase tracking-wider text-muted-foreground">Price</CardTitle>
          </CardHeader>
          <CardContent className="px-4 pb-3 grid grid-cols-2 gap-3 text-sm">
            <div>
              <div className="text-xs text-muted-foreground">Prev Close</div>
              <div className="font-semibold">₹{fmt(snap.previous_close)}</div>
            </div>
            <div>
              <div className="text-xs text-muted-foreground">Indicative Open</div>
              <div className={cn("font-semibold", gapColor(snap.gap_percent))}>
                {snap.indicative_open_price ? `₹${fmt(snap.indicative_open_price)}` : "—"}
              </div>
            </div>
            <div>
              <div className="text-xs text-muted-foreground">Gap %</div>
              <div className={cn("font-bold flex items-center gap-1", gapColor(snap.gap_percent))}>
                {gapIcon(snap.gap_percent)}
                {snap.gap_percent !== null ? `${fmt(snap.gap_percent)}%` : "—"}
              </div>
            </div>
          </CardContent>
        </Card>

        {/* Order book */}
        <Card>
          <CardHeader className="pb-2 pt-3 px-4">
            <div className="flex items-center justify-between">
              <CardTitle className="text-xs uppercase tracking-wider text-muted-foreground">Order Book</CardTitle>
              {!snap.order_book_available && (
                <span className="text-[10px] text-amber-600 bg-amber-50 dark:bg-amber-900/20 px-2 py-0.5 rounded-full font-medium">
                  Not supplied by provider
                </span>
              )}
            </div>
          </CardHeader>
          <CardContent className="px-4 pb-3 grid grid-cols-3 gap-3 text-sm">
            <div>
              <div className="text-xs text-muted-foreground">Buy Qty</div>
              {snap.order_book_available
                ? <div className="font-semibold text-emerald-600">{fmtQty(snap.total_buy_quantity)}</div>
                : <div className="text-xs text-muted-foreground italic">Not supplied by provider</div>}
            </div>
            <div>
              <div className="text-xs text-muted-foreground">Sell Qty</div>
              {snap.order_book_available
                ? <div className="font-semibold text-red-600">{fmtQty(snap.total_sell_quantity)}</div>
                : <div className="text-xs text-muted-foreground italic">Not supplied by provider</div>}
            </div>
            <div>
              <div className="text-xs text-muted-foreground">Imbalance</div>
              {snap.order_book_available
                ? <div className={cn("font-bold", snap.imbalance_percent > 0 ? "text-emerald-600" : "text-red-600")}>
                    {fmt(snap.imbalance_percent)}%
                  </div>
                : <div className="text-xs text-muted-foreground italic">Not supplied by provider</div>}
            </div>
            <div>
              <div className="text-xs text-muted-foreground">Executed Qty</div>
              <div className="font-semibold">{fmtQty(snap.final_executed_quantity)}</div>
            </div>
            <div>
              <div className="text-xs text-muted-foreground">Liquidity</div>
              <div className="font-semibold">{fmt(snap.liquidity_score, 1)}/100</div>
            </div>
          </CardContent>
        </Card>

        {/* Opportunity score + factors */}
        <Card>
          <CardHeader className="pb-2 pt-3 px-4">
            <CardTitle className="text-xs uppercase tracking-wider text-muted-foreground">
              Opportunity Score — {fmt(snap.opportunity_score, 1)}/100
            </CardTitle>
          </CardHeader>
          <CardContent className="px-4 pb-3 space-y-2">
            {Object.entries(snap.factor_scores || {}).map(([factor, score]) => (
              <div key={factor} className="flex items-center gap-2">
                <div className="w-32 text-xs text-muted-foreground capitalize">{factor.replace(/_/g, " ")}</div>
                <div className="flex-1 bg-muted rounded-full h-1.5 overflow-hidden">
                  <div
                    className="h-full bg-primary rounded-full"
                    style={{ width: `${Math.min((score / 25) * 100, 100)}%` }}
                  />
                </div>
                <div className="w-8 text-right text-xs font-mono">{fmt(score, 1)}</div>
              </div>
            ))}
          </CardContent>
        </Card>

        {/* Data quality */}
        <Card>
          <CardHeader className="pb-2 pt-3 px-4">
            <CardTitle className="text-xs uppercase tracking-wider text-muted-foreground">Data Quality</CardTitle>
          </CardHeader>
          <CardContent className="px-4 pb-3 space-y-1 text-sm">
            <div className="flex justify-between">
              <span className="text-muted-foreground">Provider</span>
              {providerBadge(snap.source_status, snap.data_source, snap.provider_label)}
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground">Freshness</span>
              <span className="font-mono text-xs">{snap.data_freshness_seconds}s ago</span>
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground">Validation</span>
              <span className="text-xs">{snap.validation_status}</span>
            </div>
            {snap.is_stale && (
              <div className="flex items-center gap-1 text-amber-600 dark:text-amber-400 text-xs font-medium mt-1">
                <AlertTriangle className="h-3 w-3" />
                Stale data — no actionable recommendation
              </div>
            )}
          </CardContent>
        </Card>

        {/* Post-open confirmation requirements */}
        <Card>
          <CardHeader className="pb-2 pt-3 px-4">
            <CardTitle className="text-xs uppercase tracking-wider text-muted-foreground">
              Required Post-Open Confirmation
            </CardTitle>
          </CardHeader>
          <CardContent className="px-4 pb-3">
            <ul className="space-y-1">
              {[
                "First 5-minute candle close",
                "Opening range breakout",
                "Live relative volume ≥ 0.8×",
                "Spread & liquidity check",
                "NIFTY direction",
                "Sector direction",
                "India VIX < 25",
                "VWAP relationship",
                "Stale-data gate",
                "Risk engine approval",
              ].map((item) => (
                <li key={item} className="flex items-center gap-2 text-xs text-muted-foreground">
                  <span className="h-1 w-1 rounded-full bg-muted-foreground/50 shrink-0" />
                  {item}
                </li>
              ))}
            </ul>
            <p className="mt-2 text-[10px] text-muted-foreground/70 italic">
              Pre-open intelligence is advisory only. All criteria must pass before any paper entry.
            </p>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

// ── Session Accuracy card ─────────────────────────────────────────────────────

function gradeColor(grade: string | undefined): string {
  switch (grade) {
    case "A": return "text-emerald-600 dark:text-emerald-400";
    case "B": return "text-green-600 dark:text-green-400";
    case "C": return "text-amber-600 dark:text-amber-400";
    case "D": return "text-red-600 dark:text-red-400";
    default:  return "text-muted-foreground";
  }
}

function rateBar(value: number | null | undefined, colorClass: string) {
  if (value == null) return <span className="text-xs text-muted-foreground">N/A</span>;
  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 bg-muted rounded-full h-1.5 min-w-[60px]">
        <div
          className={cn("h-full rounded-full", colorClass)}
          style={{ width: `${Math.min(value, 100)}%` }}
        />
      </div>
      <span className="text-xs font-mono w-12 text-right">{value.toFixed(1)}%</span>
    </div>
  );
}

function SessionAccuracyCard({ accuracy }: { accuracy: AccuracyResponse | undefined }) {
  // Not yet loaded or disabled
  if (!accuracy) return null;
  if (accuracy.status === "DISABLED") return null;

  // No reconciliation data yet — show a pending note
  if (!accuracy.available) {
    return (
      <Card>
        <CardHeader className="pb-2 pt-4 px-4">
          <div className="flex items-center gap-2">
            <Target className="h-4 w-4 text-muted-foreground" />
            <CardTitle className="text-sm font-semibold">Session Accuracy</CardTitle>
            <span className="text-[10px] text-muted-foreground ml-auto">Available post-09:30 IST</span>
          </div>
        </CardHeader>
        <CardContent className="px-4 pb-4">
          <p className="text-sm text-muted-foreground">
            {accuracy.message ?? "Reconciliation runs automatically after market open (09:20–09:30 IST). Check back after the session."}
          </p>
        </CardContent>
      </Card>
    );
  }

  const {
    trading_date, symbols_reconciled, with_error_count, with_direction_count,
    watchlist_total, watchlist_confirmed_count,
    avg_indicative_to_open_error_pct, hit_rate_pct, confirmation_rate_pct,
    false_positive_rate_pct, grade, grade_label, reconciled_at, symbols,
  } = accuracy;

  return (
    <Card>
      <CardHeader className="pb-2 pt-4 px-4">
        <div className="flex items-start justify-between gap-2 flex-wrap">
          <div className="flex items-center gap-2">
            <Target className="h-4 w-4 text-muted-foreground" />
            <CardTitle className="text-sm font-semibold">Session Accuracy</CardTitle>
            <Badge variant="outline" className="text-[10px]">ADVISORY ONLY</Badge>
          </div>
          <div className="flex items-center gap-2 text-xs text-muted-foreground">
            {trading_date && <span>{trading_date}</span>}
            {reconciled_at && (
              <span className="font-mono">
                Reconciled {new Date(reconciled_at).toLocaleTimeString("en-IN", {
                  hour: "2-digit", minute: "2-digit", timeZone: "Asia/Kolkata",
                })} IST
              </span>
            )}
          </div>
        </div>
      </CardHeader>
      <CardContent className="px-4 pb-4 space-y-4">
        {/* Grade + summary stats */}
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
          <div className="space-y-0.5">
            <div className="text-xs text-muted-foreground flex items-center gap-1">
              <BarChart2 className="h-3 w-3" /> Grade
            </div>
            <div className={cn("text-2xl font-bold", gradeColor(grade))}>{grade}</div>
            <div className="text-xs text-muted-foreground">{grade_label}</div>
          </div>
          <div className="space-y-0.5">
            <div className="text-xs text-muted-foreground flex items-center gap-1">
              <Percent className="h-3 w-3" /> Mean Abs Error
            </div>
            <div className="text-xl font-bold">
              {avg_indicative_to_open_error_pct != null
                ? `${avg_indicative_to_open_error_pct.toFixed(2)}%`
                : "N/A"}
            </div>
            <div className="text-xs text-muted-foreground">{with_error_count ?? 0} of {symbols_reconciled} symbols</div>
          </div>
          <div className="space-y-0.5">
            <div className="text-xs text-muted-foreground flex items-center gap-1">
              <CheckCircle2 className="h-3 w-3" /> Hit Rate
            </div>
            <div className={cn("text-xl font-bold", hit_rate_pct != null && hit_rate_pct >= 60 ? "text-emerald-600 dark:text-emerald-400" : hit_rate_pct != null && hit_rate_pct >= 45 ? "text-amber-600 dark:text-amber-400" : "text-red-600 dark:text-red-400")}>
              {hit_rate_pct != null ? `${hit_rate_pct.toFixed(1)}%` : "N/A"}
            </div>
            <div className="text-xs text-muted-foreground">Correct direction calls</div>
          </div>
          <div className="space-y-0.5">
            <div className="text-xs text-muted-foreground flex items-center gap-1">
              <Activity className="h-3 w-3" /> Confirmation Rate
            </div>
            <div className={cn("text-xl font-bold", confirmation_rate_pct != null && confirmation_rate_pct >= 60 ? "text-emerald-600 dark:text-emerald-400" : "text-amber-600 dark:text-amber-400")}>
              {confirmation_rate_pct != null ? `${confirmation_rate_pct.toFixed(1)}%` : "N/A"}
            </div>
            <div className="text-xs text-muted-foreground">
              {watchlist_confirmed_count ?? 0} of {watchlist_total ?? 0} watchlist candidates
            </div>
          </div>
        </div>

        {/* Rate bars */}
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          <div className="space-y-1">
            <div className="flex items-center justify-between">
              <span className="text-xs text-muted-foreground">Direction Hit Rate</span>
              <span className="text-xs text-muted-foreground">{with_direction_count ?? 0} symbols</span>
            </div>
            {rateBar(hit_rate_pct, "bg-emerald-500")}
          </div>
          <div className="space-y-1">
            <div className="flex items-center justify-between">
              <span className="text-xs text-muted-foreground">Watchlist Confirmation</span>
              <span className="text-xs text-muted-foreground">{watchlist_total ?? 0} candidates</span>
            </div>
            {rateBar(confirmation_rate_pct, "bg-primary")}
          </div>
          <div className="space-y-1">
            <span className="text-xs text-muted-foreground">False Positive Rate</span>
            {rateBar(false_positive_rate_pct, "bg-red-500")}
          </div>
          <div className="space-y-1">
            <span className="text-xs text-muted-foreground">Reversal Rate (all symbols)</span>
            {rateBar(accuracy.reversal_rate_pct, "bg-orange-400")}
          </div>
        </div>

        {/* Per-symbol table (collapsed at >10 rows) */}
        {symbols && symbols.length > 0 && (
          <div>
            <div className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-2">
              Per-Symbol Detail
            </div>
            <div className="overflow-x-auto rounded-md border border-border">
              <table className="w-full text-xs">
                <thead>
                  <tr className="border-b border-border bg-muted/40">
                    <th className="px-3 py-2 text-left font-semibold text-muted-foreground">Symbol</th>
                    <th className="px-3 py-2 text-right font-semibold text-muted-foreground">Indicative</th>
                    <th className="px-3 py-2 text-right font-semibold text-muted-foreground">Actual Open</th>
                    <th className="px-3 py-2 text-right font-semibold text-muted-foreground">Error %</th>
                    <th className="px-3 py-2 text-center font-semibold text-muted-foreground">Direction</th>
                    <th className="px-3 py-2 text-center font-semibold text-muted-foreground">Watchlist</th>
                  </tr>
                </thead>
                <tbody>
                  {symbols.slice(0, 20).map((s) => (
                    <tr key={s.symbol} className="border-b border-border/50 hover:bg-muted/20">
                      <td className="px-3 py-1.5 font-bold">{s.symbol}</td>
                      <td className="px-3 py-1.5 text-right font-mono">
                        {s.indicative_price != null ? `₹${s.indicative_price.toFixed(2)}` : "—"}
                      </td>
                      <td className="px-3 py-1.5 text-right font-mono">
                        {s.actual_open != null ? `₹${s.actual_open.toFixed(2)}` : "—"}
                      </td>
                      <td className={cn(
                        "px-3 py-1.5 text-right font-mono",
                        s.error_pct == null ? "text-muted-foreground" :
                        s.error_pct < 0.3 ? "text-emerald-600 dark:text-emerald-400" :
                        s.error_pct < 0.8 ? "text-amber-600 dark:text-amber-400" :
                        "text-red-600 dark:text-red-400"
                      )}>
                        {s.error_pct != null ? `${s.error_pct.toFixed(2)}%` : "—"}
                      </td>
                      <td className="px-3 py-1.5 text-center">
                        {s.direction_correct == null ? (
                          <Minus className="h-3.5 w-3.5 mx-auto text-muted-foreground" />
                        ) : s.direction_correct ? (
                          <CheckCircle2 className="h-3.5 w-3.5 mx-auto text-emerald-500" />
                        ) : (
                          <AlertTriangle className="h-3.5 w-3.5 mx-auto text-red-500" />
                        )}
                      </td>
                      <td className="px-3 py-1.5 text-center">
                        {s.was_in_watchlist ? (
                          s.watchlist_confirmed ? (
                            <span className="inline-flex items-center rounded-full px-1.5 py-0.5 text-[10px] font-semibold bg-emerald-100 text-emerald-800 dark:bg-emerald-900/30 dark:text-emerald-300">
                              ✓
                            </span>
                          ) : (
                            <span className="inline-flex items-center rounded-full px-1.5 py-0.5 text-[10px] font-semibold bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-300">
                              ✗
                            </span>
                          )
                        ) : (
                          <span className="text-muted-foreground">—</span>
                        )}
                      </td>
                    </tr>
                  ))}
                  {symbols.length > 20 && (
                    <tr>
                      <td colSpan={6} className="px-3 py-2 text-center text-xs text-muted-foreground">
                        +{symbols.length - 20} more symbols not shown
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>
        )}

        <p className="text-[10px] text-muted-foreground/70 italic">
          Accuracy metrics are retrospective and advisory only. They measure indicative pre-open price quality,
          not trade performance. No paper entries are created from pre-open data.
        </p>
      </CardContent>
    </Card>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function PreOpenIntelligence() {
  const [filterGap, setFilterGap] = useState<"all" | "up" | "down">("all");
  const [filterImbalance, setFilterImbalance] = useState<"all" | "buy" | "sell">("all");
  const [filterSector, setFilterSector] = useState("all");
  const [filterWatchlistOnly, setFilterWatchlistOnly] = useState(false);
  const [minScore, setMinScore] = useState(0);
  const [selectedSnap, setSelectedSnap] = useState<Snapshot | null>(null);
  const [sortKey, setSortKey] = useState<keyof Snapshot>("opportunity_score");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("desc");
  const [refreshing, setRefreshing] = useState(false);

  const { data, isLoading, error, refetch } = useQuery<SnapshotResponse>({
    queryKey: ["preopen-snapshot"],
    queryFn: () => apiJson("/preopen/snapshot"),
    refetchInterval: 30_000,
    retry: 1,
  });

  const { data: watchlistData } = useQuery<{ watchlists?: Record<string, any[]>; status?: string }>({
    queryKey: ["preopen-watchlist"],
    queryFn: () => apiJson("/preopen/watchlist"),
    refetchInterval: 60_000,
    retry: 1,
  });

  const { data: accuracyData } = useQuery<AccuracyResponse>({
    queryKey: ["preopen-accuracy"],
    queryFn: () => apiJson("/preopen/accuracy"),
    refetchInterval: 60_000,
    retry: 1,
  });

  // Watchlist symbols set for quick lookup
  const watchlistSymbols = useMemo(() => {
    const syms = new Set<string>();
    if (watchlistData && "watchlists" in watchlistData) {
      for (const items of Object.values(watchlistData.watchlists ?? {})) {
        for (const item of items) {
          if (item?.symbol) syms.add(item.symbol);
        }
      }
    }
    return syms;
  }, [watchlistData]);

  const sectors = useMemo(() => {
    if (!data?.snapshots) return [];
    return Array.from(new Set(data.snapshots.map((s) => s.sector).filter(Boolean))).sort();
  }, [data]);

  const filtered = useMemo(() => {
    let snaps = data?.snapshots ?? [];
    if (filterGap === "up")   snaps = snaps.filter((s) => (s.gap_percent ?? 0) > 0);
    if (filterGap === "down") snaps = snaps.filter((s) => (s.gap_percent ?? 0) < 0);
    if (filterImbalance === "buy")  snaps = snaps.filter((s) => s.imbalance_percent > 10);
    if (filterImbalance === "sell") snaps = snaps.filter((s) => s.imbalance_percent < -10);
    if (filterSector !== "all") snaps = snaps.filter((s) => s.sector === filterSector);
    if (filterWatchlistOnly) snaps = snaps.filter((s) => watchlistSymbols.has(s.symbol));
    if (minScore > 0) snaps = snaps.filter((s) => s.opportunity_score >= minScore);

    // Sort
    return [...snaps].sort((a, b) => {
      const av = (a as any)[sortKey] ?? 0;
      const bv = (b as any)[sortKey] ?? 0;
      const cmp = typeof av === "string" ? av.localeCompare(bv) : av - bv;
      return sortDir === "asc" ? cmp : -cmp;
    });
  }, [data, filterGap, filterImbalance, filterSector, filterWatchlistOnly, minScore, sortKey, sortDir, watchlistSymbols]);

  function toggleSort(key: keyof Snapshot) {
    if (sortKey === key) {
      setSortDir((d) => d === "asc" ? "desc" : "asc");
    } else {
      setSortKey(key);
      setSortDir("desc");
    }
  }

  function SortIcon({ col }: { col: keyof Snapshot }) {
    if (sortKey !== col) return null;
    return sortDir === "desc"
      ? <ChevronDown className="h-3 w-3 inline ml-0.5" />
      : <ChevronUp className="h-3 w-3 inline ml-0.5" />;
  }

  async function handleRefresh() {
    setRefreshing(true);
    try {
      await fetch(`${(window as any).__API_BASE_URL__ ?? ""}/api/preopen/refresh`, { method: "POST", credentials: "include" });
      await refetch();
    } finally {
      setRefreshing(false);
    }
  }

  const session = data?.session;
  const snapshots = data?.snapshots ?? [];

  // Disabled state
  if (data && "status" in data && (data as any).status === "DISABLED") {
    return (
      <div className="flex flex-col items-center justify-center min-h-[60vh] gap-4">
        <WifiOff className="h-12 w-12 text-muted-foreground/40" />
        <h1 className="text-xl font-bold">Pre-Open Intelligence Disabled</h1>
        <p className="text-muted-foreground text-sm text-center max-w-md">
          {(data as any).message ?? "Set PREOPEN_INTELLIGENCE_ENABLED=true to enable this module."}
        </p>
        <Badge variant="outline" className="text-xs">PAPER / ADVISORY ONLY</Badge>
      </div>
    );
  }

  // Highlight card data
  const validSnaps = snapshots.filter((s) => !s.is_stale);
  const topGapUp    = validSnaps.filter((s) => (s.gap_percent ?? 0) > 0).sort((a, b) => (b.gap_percent ?? 0) - (a.gap_percent ?? 0))[0];
  const topGapDown  = validSnaps.filter((s) => (s.gap_percent ?? 0) < 0).sort((a, b) => (a.gap_percent ?? 0) - (b.gap_percent ?? 0))[0];
  const topBuyImb   = validSnaps.filter((s) => s.imbalance_percent > 10).sort((a, b) => b.imbalance_percent - a.imbalance_percent)[0];
  const topSellImb  = validSnaps.filter((s) => s.imbalance_percent < -10).sort((a, b) => a.imbalance_percent - b.imbalance_percent)[0];
  const topExecQty  = validSnaps.sort((a, b) => b.final_executed_quantity - a.final_executed_quantity)[0];
  const sectorMap: Record<string, number[]> = {};
  for (const s of validSnaps) {
    if (s.gap_percent !== null) (sectorMap[s.sector] ??= []).push(s.gap_percent);
  }
  const leadingSector = Object.entries(sectorMap)
    .map(([sector, gaps]) => ({ sector, avg: gaps.reduce((a, b) => a + b, 0) / gaps.length }))
    .sort((a, b) => Math.abs(b.avg) - Math.abs(a.avg))[0];
  const leadingSectorSnap = leadingSector
    ? validSnaps.filter((s) => s.sector === leadingSector.sector).sort((a, b) => b.opportunity_score - a.opportunity_score)[0]
    : undefined;

  return (
    <div className="space-y-6 pb-10">
      {/* Page header */}
      <div className="flex flex-col sm:flex-row sm:items-start sm:justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Pre-Open Intelligence</h1>
          <p className="text-sm text-muted-foreground mt-0.5">
            NSE pre-open session · 09:00–09:15 IST · Advisory only
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Badge variant="outline" className="text-xs border-amber-300 text-amber-700 dark:text-amber-400">
            PAPER / ADVISORY ONLY
          </Badge>
          <Button
            variant="outline"
            size="sm"
            onClick={handleRefresh}
            disabled={refreshing || isLoading}
          >
            <RefreshCw className={cn("h-3.5 w-3.5 mr-1.5", refreshing && "animate-spin")} />
            Refresh
          </Button>
        </div>
      </div>

      {/* Status summary bar */}
      <Card>
        <CardContent className="px-4 py-3">
          <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-7 gap-4">
            <div>
              <div className="text-xs text-muted-foreground">Module Status</div>
              <div className="font-semibold text-sm mt-0.5">
                {isLoading ? "Loading…" : error ? "Error" : session?.status ?? "Unknown"}
              </div>
            </div>
            <div>
              <div className="text-xs text-muted-foreground">Last Updated</div>
              <div className="font-mono text-xs mt-0.5 text-muted-foreground">
                {data?.trading_date ?? "—"}
              </div>
            </div>
            <div>
              <div className="text-xs text-muted-foreground">Symbols</div>
              <div className="font-semibold text-sm mt-0.5">{snapshots.length}</div>
            </div>
            <div>
              <div className="text-xs text-muted-foreground">Valid</div>
              <div className="font-semibold text-sm mt-0.5 text-emerald-600">{data?.valid_count ?? 0}</div>
            </div>
            <div>
              <div className="text-xs text-muted-foreground">Stale</div>
              <div className="font-semibold text-sm mt-0.5 text-amber-600">{data?.stale_count ?? 0}</div>
            </div>
            <div>
              <div className="text-xs text-muted-foreground">Provider</div>
              <div className="mt-0.5">
                {providerBadge(
                  session?.provider_status ?? "UNKNOWN",
                  undefined,
                  data?.provider_label ?? session?.provider_label,
                )}
              </div>
            </div>
            <div>
              <div className="text-xs text-muted-foreground">Session</div>
              <div className="flex items-center gap-1 mt-0.5">
                <Clock className="h-3 w-3 text-muted-foreground" />
                <span className="text-xs">{session?.frozen_at ? "Frozen" : "Live"}</span>
              </div>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Highlight cards */}
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3">
        <HighlightCard
          title="Top Gap Up"
          icon={TrendingUp}
          snap={topGapUp}
          metric={(s) => (
            <span className={cn("text-sm font-bold", gapColor(s.gap_percent))}>
              {fmt(s.gap_percent)}%
            </span>
          )}
        />
        <HighlightCard
          title="Top Gap Down"
          icon={TrendingDown}
          snap={topGapDown}
          metric={(s) => (
            <span className={cn("text-sm font-bold", gapColor(s.gap_percent))}>
              {fmt(s.gap_percent)}%
            </span>
          )}
        />
        <HighlightCard
          title="Buy Imbalance"
          icon={Activity}
          snap={topBuyImb}
          metric={(s) => (
            <span className="text-sm font-bold text-emerald-600">
              +{fmt(s.imbalance_percent)}%
            </span>
          )}
        />
        <HighlightCard
          title="Sell Imbalance"
          icon={Activity}
          snap={topSellImb}
          metric={(s) => (
            <span className="text-sm font-bold text-red-600">
              {fmt(s.imbalance_percent)}%
            </span>
          )}
        />
        <HighlightCard
          title="Highest Exec Qty"
          icon={BarChart3}
          snap={topExecQty}
          metric={(s) => (
            <span className="text-sm font-bold">{fmtQty(s.final_executed_quantity)}</span>
          )}
        />
        <HighlightCard
          title="Leading Sector"
          icon={BarChart3}
          snap={leadingSectorSnap}
          metric={(s) => (
            <span className="text-xs font-semibold text-muted-foreground">
              {s.sector} · {leadingSector ? fmt(leadingSector.avg) : "—"}% avg
            </span>
          )}
        />
      </div>

      {/* Filters */}
      <Card>
        <CardContent className="px-4 py-3">
          <div className="flex flex-wrap items-center gap-3">
            <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
              <Filter className="h-3.5 w-3.5" />
              <span>Filters:</span>
            </div>
            {/* Gap filter */}
            <div className="flex items-center gap-1">
              {(["all", "up", "down"] as const).map((v) => (
                <button
                  key={v}
                  onClick={() => setFilterGap(v)}
                  className={cn(
                    "rounded-md px-2.5 py-1 text-xs font-medium transition",
                    filterGap === v
                      ? "bg-primary text-primary-foreground"
                      : "bg-muted text-muted-foreground hover:text-foreground",
                  )}
                >
                  {v === "all" ? "All Gaps" : v === "up" ? "Gap Up" : "Gap Down"}
                </button>
              ))}
            </div>
            {/* Imbalance filter */}
            <div className="flex items-center gap-1">
              {(["all", "buy", "sell"] as const).map((v) => (
                <button
                  key={v}
                  onClick={() => setFilterImbalance(v)}
                  className={cn(
                    "rounded-md px-2.5 py-1 text-xs font-medium transition",
                    filterImbalance === v
                      ? "bg-primary text-primary-foreground"
                      : "bg-muted text-muted-foreground hover:text-foreground",
                  )}
                >
                  {v === "all" ? "All Orders" : v === "buy" ? "Buy Imb" : "Sell Imb"}
                </button>
              ))}
            </div>
            {/* Sector */}
            <select
              value={filterSector}
              onChange={(e) => setFilterSector(e.target.value)}
              className="rounded-md border border-border bg-background px-2 py-1 text-xs"
            >
              <option value="all">All Sectors</option>
              {sectors.map((s) => <option key={s} value={s}>{s}</option>)}
            </select>
            {/* Min score */}
            <label className="flex items-center gap-1.5 text-xs">
              <span className="text-muted-foreground">Min Score</span>
              <input
                type="range" min={0} max={80} step={10} value={minScore}
                onChange={(e) => setMinScore(Number(e.target.value))}
                className="w-20"
              />
              <span className="w-6 text-right font-mono">{minScore}</span>
            </label>
            {/* Watchlist only */}
            <label className="flex items-center gap-1.5 text-xs cursor-pointer">
              <input
                type="checkbox"
                checked={filterWatchlistOnly}
                onChange={(e) => setFilterWatchlistOnly(e.target.checked)}
                className="rounded"
              />
              <span>Watchlist only</span>
            </label>
            {/* Clear */}
            {(filterGap !== "all" || filterImbalance !== "all" || filterSector !== "all" || filterWatchlistOnly || minScore > 0) && (
              <button
                onClick={() => { setFilterGap("all"); setFilterImbalance("all"); setFilterSector("all"); setFilterWatchlistOnly(false); setMinScore(0); }}
                className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
              >
                <X className="h-3 w-3" />Clear
              </button>
            )}
          </div>
        </CardContent>
      </Card>

      {/* Ranked table */}
      <Card>
        <CardHeader className="pb-2 pt-4 px-4">
          <div className="flex items-center justify-between">
            <CardTitle className="text-sm font-semibold">
              Ranked Symbols ({filtered.length})
            </CardTitle>
            {isLoading && <span className="text-xs text-muted-foreground animate-pulse">Loading…</span>}
          </div>
        </CardHeader>
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-border bg-muted/40">
                {[
                  ["#", null],
                  ["Symbol", "symbol"],
                  ["Sector", "sector"],
                  ["Prev Close", "previous_close"],
                  ["Indicative", "indicative_open_price"],
                  ["Gap %", "gap_percent"],
                  ["Buy Qty", "total_buy_quantity"],
                  ["Sell Qty", "total_sell_quantity"],
                  ["Imb %", "imbalance_percent"],
                  ["Exec Qty", "final_executed_quantity"],
                  ["Score", "opportunity_score"],
                  ["Class", "classification"],
                  ["Status", "source_status"],
                  ["Action", null],
                ].map(([label, key]) => (
                  <th
                    key={String(label)}
                    onClick={() => key && toggleSort(key as keyof Snapshot)}
                    className={cn(
                      "px-3 py-2 text-left font-semibold text-muted-foreground whitespace-nowrap",
                      key && "cursor-pointer hover:text-foreground select-none",
                    )}
                  >
                    {label}
                    {key && <SortIcon col={key as keyof Snapshot} />}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {filtered.length === 0 && (
                <tr>
                  <td colSpan={14} className="px-4 py-8 text-center text-muted-foreground">
                    {isLoading ? "Loading pre-open data…" : "No symbols match the current filters."}
                  </td>
                </tr>
              )}
              {filtered.map((s, i) => (
                <tr
                  key={s.symbol + i}
                  className={cn(
                    "border-b border-border/50 hover:bg-muted/30 transition",
                    s.is_stale && "opacity-50",
                    selectedSnap?.symbol === s.symbol && "bg-primary/5",
                  )}
                >
                  <td className="px-3 py-2 text-muted-foreground font-mono">{i + 1}</td>
                  <td className="px-3 py-2 font-bold">{s.symbol}</td>
                  <td className="px-3 py-2 text-muted-foreground">{s.sector}</td>
                  <td className="px-3 py-2 font-mono">₹{fmt(s.previous_close)}</td>
                  <td className="px-3 py-2 font-mono">
                    {s.indicative_open_price ? `₹${fmt(s.indicative_open_price)}` : "—"}
                  </td>
                  <td className={cn("px-3 py-2 font-bold flex items-center gap-0.5", gapColor(s.gap_percent))}>
                    {gapIcon(s.gap_percent)}
                    {s.gap_percent !== null ? `${fmt(s.gap_percent)}%` : "—"}
                  </td>
                  <td className="px-3 py-2 text-emerald-600">
                    {s.order_book_available ? fmtQty(s.total_buy_quantity) : <span className="text-muted-foreground text-xs">—</span>}
                  </td>
                  <td className="px-3 py-2 text-red-600">
                    {s.order_book_available ? fmtQty(s.total_sell_quantity) : <span className="text-muted-foreground text-xs">—</span>}
                  </td>
                  <td className={cn("px-3 py-2 font-bold", s.order_book_available ? (s.imbalance_percent > 0 ? "text-emerald-600" : "text-red-600") : "text-muted-foreground")}>
                    {s.order_book_available ? `${fmt(s.imbalance_percent)}%` : <span className="text-xs font-normal">—</span>}
                  </td>
                  <td className="px-3 py-2 font-mono">{fmtQty(s.final_executed_quantity)}</td>
                  <td className="px-3 py-2">
                    <div className="flex items-center gap-1.5">
                      <div className="flex-1 min-w-[40px] bg-muted rounded-full h-1.5">
                        <div
                          className="h-full bg-primary rounded-full"
                          style={{ width: `${Math.min(s.opportunity_score, 100)}%` }}
                        />
                      </div>
                      <span className="font-mono text-xs w-8 text-right">{fmt(s.opportunity_score, 0)}</span>
                    </div>
                  </td>
                  <td className="px-3 py-2">{classLabel(s.classification)}</td>
                  <td className="px-3 py-2">{providerBadge(s.source_status, s.data_source, s.provider_label)}</td>
                  <td className="px-3 py-2">
                    <Button
                      variant="ghost"
                      size="icon"
                      className="h-6 w-6"
                      onClick={() => setSelectedSnap(s)}
                    >
                      <Eye className="h-3.5 w-3.5" />
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      {/* Session Accuracy — visible once reconciliation data is available */}
      <SessionAccuracyCard accuracy={accuracyData} />

      {/* Advisory footer */}
      <p className="text-[11px] text-muted-foreground/60 text-center pb-2">
        Pre-Open Intelligence is advisory only. Classifications are not BUY/SELL signals.
        All candidates require post-open confirmation before any paper entry.
      </p>

      {/* Detail drawer */}
      {selectedSnap && (
        <>
          <div
            className="fixed inset-0 z-40 bg-foreground/10 backdrop-blur-sm"
            onClick={() => setSelectedSnap(null)}
          />
          <DetailDrawer snap={selectedSnap} onClose={() => setSelectedSnap(null)} />
        </>
      )}
    </div>
  );
}
