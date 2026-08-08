/**
 * PaperTradingValidation.tsx — Phase 6.1
 * Paper Trading Validation & Data Collection Framework.
 *
 * Six sections:
 *   1. Today's Session
 *   2. Historical Performance (daily + rolling periods)
 *   3. Data Quality
 *   4. Trade Timeline
 *   5. Validation Statistics
 *   6. Growth of Dataset
 *
 * PAPER TRADING / ADVISORY ONLY.
 * Read-only — never modifies trades, portfolio, strategies, orders, or signals.
 */
import { useState, useEffect, useCallback } from "react";
import { useQuery } from "@tanstack/react-query";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Loader2, RefreshCw, Download, ShieldCheck, AlertTriangle, CheckCircle2,
  XCircle, ClipboardCheck, TrendingUp, TrendingDown, BarChart3, Activity,
  Database, Calendar, FileText, Layers,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { apiJson } from "@/lib/api";

/* eslint-disable @typescript-eslint/no-explicit-any */

const LABEL = "PAPER TRADING VALIDATION — DATA COLLECTION FRAMEWORK — ADVISORY ONLY";
const BASE_URL = import.meta.env.BASE_URL ?? "/trading-dashboard/";

// ---------------------------------------------------------------------------
// Shared UI primitives
// ---------------------------------------------------------------------------

function DisabledBanner({ message }: { message?: string }) {
  return (
    <div className="flex flex-col items-center gap-3 rounded border border-amber-800 bg-amber-950/30 p-8 text-center">
      <ShieldCheck className="h-8 w-8 text-amber-400" />
      <div className="text-amber-400 font-semibold">Paper Trading Validation is disabled</div>
      <code className="rounded bg-zinc-900 px-2 py-1 text-xs text-amber-300">
        {message ?? "Set PAPER_VALIDATION_ENABLED=true to enable."}
      </code>
    </div>
  );
}

function SectionCard({ title, icon: Icon, children, className }: {
  title: string; icon: any; children: React.ReactNode; className?: string;
}) {
  return (
    <Card className={cn("border-zinc-800 bg-zinc-950", className)}>
      <CardHeader className="py-3">
        <CardTitle className="flex items-center gap-2 text-sm text-zinc-200">
          <Icon className="h-4 w-4 text-sky-400" /> {title}
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3 text-xs">{children}</CardContent>
    </Card>
  );
}

function Stat({ label, value, cls }: { label: string; value: any; cls?: string }) {
  const display = (v: any) => {
    if (v === null || v === undefined || v === "") return "—";
    if (typeof v === "number") {
      if (!isFinite(v) || isNaN(v)) return "—";
      return +v.toFixed(2);
    }
    return String(v);
  };
  return (
    <div className="rounded border border-zinc-800 bg-zinc-900/50 p-2">
      <div className="text-[10px] uppercase tracking-wide text-zinc-500">{label}</div>
      <div className={cn("text-sm font-mono", cls ?? "text-zinc-200")}>{display(value)}</div>
    </div>
  );
}

function MiniTable({ headers, rows }: { headers: string[]; rows: any[][] }) {
  if (!rows.length) return (
    <div className="text-zinc-500 font-mono text-[11px] py-2">No data yet.</div>
  );
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-[11px] font-mono">
        <thead>
          <tr className="text-zinc-500 border-b border-zinc-800">
            {headers.map((h) => <th key={h} className="text-left py-1 pr-3 font-normal">{h}</th>)}
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i} className="border-b border-zinc-900 text-zinc-300">
              {r.map((c, j) => <td key={j} className="py-1 pr-3">{c}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function pct(v: any) { return v !== null && v !== undefined ? `${(+v * 100).toFixed(1)}%` : "—"; }
function rs(v: any) { return v !== null && v !== undefined ? `₹${(+v).toFixed(0)}` : "—"; }
function mins(v: any) { return v !== null && v !== undefined ? `${(+v).toFixed(0)}m` : "—"; }
function score(v: any) { return v !== null && v !== undefined ? `${(+v).toFixed(1)}` : "—"; }

// ---------------------------------------------------------------------------
// Data fetching
// ---------------------------------------------------------------------------

async function fetchSection(path: string) {
  return apiJson(path);
}

// ---------------------------------------------------------------------------
// Aggregated validation dashboard (GET /validation/dashboard)
// All values derive from the scan snapshot, phase20 ledger, replay store,
// portfolio store and AI decision cache — see phase4a_dashboard.py.
// ---------------------------------------------------------------------------

function StatusBadge({ status }: { status: string }) {
  const cls = status === "PASS" ? "text-emerald-400 border-emerald-700"
    : status === "WARNING" ? "text-amber-400 border-amber-700"
    : "text-red-400 border-red-700";
  const Icon = status === "PASS" ? CheckCircle2 : status === "WARNING" ? AlertTriangle : XCircle;
  return (
    <Badge variant="outline" className={cn("text-[10px] gap-1", cls)}>
      <Icon className="h-3 w-3" /> {status}
    </Badge>
  );
}

function ValidationDashboardSections() {
  const dashQ = useQuery<any>({
    queryKey: ["validation-dashboard"],
    queryFn: () => fetchSection("/validation/dashboard"),
    refetchInterval: 60_000,
    staleTime: 55_000,
  });

  if (dashQ.isLoading) {
    return (
      <div className="flex items-center gap-2 text-zinc-400 py-6 justify-center">
        <Loader2 className="h-4 w-4 animate-spin" /> Loading validation dashboard…
      </div>
    );
  }
  if (dashQ.isError || !dashQ.data) {
    return (
      <div className="text-red-400 text-[11px] flex gap-1 rounded border border-red-800/40 bg-red-950/20 p-3">
        <AlertTriangle className="h-4 w-4 shrink-0" /> Validation dashboard failed: {String(dashQ.error ?? "no data")}
      </div>
    );
  }
  const d = dashQ.data;
  const s = d.session ?? {};
  const t = d.trading_statistics ?? {};
  const hist = d.historical_performance ?? {};
  const q = d.data_quality ?? {};
  const pipeline: any[] = d.validation_pipeline ?? [];
  const ai = d.ai_validation ?? {};
  const money = (v: any) => (v === null || v === undefined || !isFinite(+v) ? "—" : `₹${(+v).toFixed(2)}`);
  const idx = (price: any, chg: any) =>
    price == null || !isFinite(+price) ? null
      : `${(+price).toLocaleString()}${chg != null && isFinite(+chg) ? ` (${+chg > 0 ? "+" : ""}${chg}%)` : ""}`;
  const periods: [string, string][] = [["7d", "7 Days"], ["30d", "30 Days"], ["90d", "90 Days"], ["180d", "180 Days"], ["all", "All Time"]];

  return (
    <>
      {/* Today's Session */}
      <SectionCard title="Today's Session" icon={Calendar}>
        <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-6 gap-2">
          <Stat label="Market Status" value={s.market_status}
            cls={s.market_status === "OPEN" ? "text-emerald-400" : "text-amber-400"} />
          <Stat label="Market Regime" value={s.market_regime} />
          <Stat label="Nifty" value={idx(s.nifty, s.nifty_change_pct)} />
          <Stat label="Bank Nifty" value={idx(s.bank_nifty, s.bank_nifty_change_pct)} />
          <Stat label="India VIX" value={s.india_vix != null ? `${s.india_vix}${s.vix_category ? ` (${s.vix_category})` : ""}` : null} />
          <Stat label="Bias" value={s.market_bias} />
          <Stat label="Top Sector" value={s.top_sector} cls="text-emerald-400" />
          <Stat label="Worst Sector" value={s.worst_sector} cls="text-red-400" />
          <Stat label="Advance/Decline" value={s.advance_decline} />
          <Stat label="Market Breadth" value={s.market_breadth != null ? `${s.market_breadth}${s.breadth_label ? ` (${s.breadth_label})` : ""}` : null} />
          <Stat label="Gap %" value={s.gap_pct != null ? `${s.gap_pct}%` : null} />
          <Stat label="Leading Theme" value={s.leading_theme} />
        </div>
        <div className="text-[10px] text-zinc-600">
          context computed {s.context_computed_at} · advance/decline = {s.advance_decline_note} · gap = {s.gap_note}
        </div>
      </SectionCard>

      {/* Trading Statistics */}
      <SectionCard title="Trading Statistics (Today)" icon={BarChart3}>
        <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-7 gap-2">
          <Stat label="Trades" value={t.trades} />
          <Stat label="BUY Orders" value={t.buy_orders} cls="text-emerald-400" />
          <Stat label="SELL Orders" value={t.sell_orders} cls="text-amber-400" />
          <Stat label="Cancelled" value={t.cancelled} />
          <Stat label="Rejected" value={t.rejected} cls={t.rejected ? "text-red-400" : undefined} />
          <Stat label="Risk Blocks" value={t.risk_blocks} cls={t.risk_blocks ? "text-red-400" : undefined} />
          <Stat label="Net P&L" value={money(t.net_pnl)} cls={t.net_pnl >= 0 ? "text-emerald-400" : "text-red-400"} />
          <Stat label="Gross P&L" value={money(t.gross_pnl)} />
          <Stat label="Average R:R" value={t.avg_rr ?? (t.buy_orders === 0 ? "no entries today" : null)} />
          <Stat label="Avg Hold Time" value={t.avg_hold_minutes != null ? `${t.avg_hold_minutes}m` : t.sell_orders === 0 ? "no exits today" : null} />
          <Stat label="Largest Winner" value={t.largest_winner != null ? money(t.largest_winner) : "none closed"} cls="text-emerald-400" />
          <Stat label="Largest Loser" value={t.largest_loser != null ? money(t.largest_loser) : "none closed"} cls="text-red-400" />
          <Stat label="Average Winner" value={t.avg_winner != null ? money(t.avg_winner) : "none closed"} />
          <Stat label="Average Loser" value={t.avg_loser != null ? money(t.avg_loser) : "none closed"} />
        </div>
      </SectionCard>

      {/* Historical Performance */}
      <SectionCard title="Historical Performance" icon={TrendingUp}>
        <div className="grid grid-cols-1 sm:grid-cols-3 lg:grid-cols-5 gap-2">
          {periods.map(([key, label]) => {
            const p = hist[key] ?? {};
            const none = !p.trades;
            return (
              <div key={key} className="rounded border border-zinc-800 bg-zinc-900/50 p-2 space-y-1">
                <div className="text-[10px] uppercase tracking-wide text-zinc-400 font-semibold">{label}</div>
                <div className="grid grid-cols-2 gap-1 text-[11px] font-mono">
                  <span className="text-zinc-500">Trades</span><span className="text-zinc-200">{p.trades ?? 0}</span>
                  <span className="text-zinc-500">Win Rate</span>
                  <span className={cn(none ? "text-zinc-500" : (p.win_rate_pct ?? 0) >= 50 ? "text-emerald-400" : "text-red-400")}>
                    {none ? "n/a" : `${p.win_rate_pct}%`}
                  </span>
                  <span className="text-zinc-500">Profit Factor</span><span className="text-zinc-200">{p.profit_factor ?? (none ? "n/a" : "∞")}</span>
                  <span className="text-zinc-500">Expectancy</span><span className="text-zinc-200">{p.expectancy != null ? `₹${p.expectancy}` : "n/a"}</span>
                  <span className="text-zinc-500">Sharpe</span><span className="text-zinc-200">{p.sharpe ?? "n/a"}</span>
                  <span className="text-zinc-500">Sortino</span><span className="text-zinc-200">{p.sortino ?? "n/a"}</span>
                  <span className="text-zinc-500">Recovery</span><span className="text-zinc-200">{p.recovery_factor ?? "n/a"}</span>
                  <span className="text-zinc-500">Max DD</span>
                  <span className={cn(p.max_drawdown ? "text-amber-400" : "text-zinc-200")}>{p.max_drawdown != null ? `₹${p.max_drawdown}` : "n/a"}</span>
                  <span className="text-zinc-500">Avg Return</span><span className="text-zinc-200">{p.avg_return_pct != null ? `${p.avg_return_pct}%` : "n/a"}</span>
                </div>
              </div>
            );
          })}
        </div>
        {hist.note && <div className="text-[10px] text-amber-400/80">{hist.note}</div>}
      </SectionCard>

      {/* Data Quality */}
      <SectionCard title="Data Quality — Ledger & Pipeline Integrity" icon={ShieldCheck}>
        <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-6 gap-2">
          <Stat label="Duplicate Orders" value={q.duplicate_orders} cls={q.duplicate_orders ? "text-red-400" : "text-emerald-400"} />
          <Stat label="Duplicate Trades" value={q.duplicate_trades} cls={q.duplicate_trades ? "text-red-400" : "text-emerald-400"} />
          <Stat label="Duplicate Open Symbols" value={q.duplicate_open_symbols} cls={q.duplicate_open_symbols ? "text-red-400" : "text-emerald-400"} />
          <Stat label="Missing Candles" value={q.missing_candles} cls={q.missing_candles ? "text-amber-400" : "text-emerald-400"} />
          <Stat label="Missing Ticks (Stale)" value={q.missing_ticks} cls={q.missing_ticks ? "text-amber-400" : "text-emerald-400"} />
          <Stat label="API Errors" value={q.api_errors} cls={q.api_errors ? "text-amber-400" : "text-emerald-400"} />
          <Stat label="Replay Integrity" value={q.replay_integrity} cls={q.replay_integrity === "PASS" ? "text-emerald-400" : "text-amber-400"} />
          <Stat label="Execution Integrity" value={q.execution_integrity} cls={String(q.execution_integrity).startsWith("PASS") ? "text-emerald-400" : "text-red-400"} />
          <Stat label="Portfolio Integrity" value={q.portfolio_integrity} cls={String(q.portfolio_integrity).startsWith("PASS") ? "text-emerald-400" : "text-red-400"} />
          <Stat label="Database Consistency" value={q.database_consistency} cls={String(q.database_consistency).startsWith("PASS") ? "text-emerald-400" : "text-red-400"} />
        </div>
        {q.missing_candle_symbols?.length > 0 && (
          <div className="text-[10px] text-amber-400/80">missing candles: {q.missing_candle_symbols.join(", ")}</div>
        )}
        {q.portfolio_cash_check && (
          <div className="text-[10px] text-zinc-600">
            {q.portfolio_cash_check.formula} → ₹{q.portfolio_cash_check.initial} − ₹{q.portfolio_cash_check.deployed} + ₹{q.portfolio_cash_check.realized} = ₹{q.portfolio_cash_check.cash}
          </div>
        )}
      </SectionCard>

      {/* Validation Pipeline */}
      <SectionCard title="Validation Pipeline" icon={Activity}>
        <div className="space-y-1">
          {pipeline.map((st: any) => (
            <div key={st.stage} className="flex items-center gap-3 rounded border border-zinc-800 bg-zinc-900/40 px-2 py-1.5">
              <span className="w-28 shrink-0 text-[11px] font-semibold text-zinc-200">{st.stage}</span>
              <StatusBadge status={st.status} />
              <span className="text-[11px] text-zinc-400 font-mono truncate">{st.reason}</span>
            </div>
          ))}
        </div>
      </SectionCard>

      {/* AI Validation */}
      <SectionCard title="AI Validation" icon={FileText}>
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
          <Stat label="Decisions Analysed" value={ai.decisions_analysed} />
          <Stat label="Average Confidence" value={ai.avg_confidence != null ? `${ai.avg_confidence}%` : null} cls="text-sky-400" />
          <Stat label="Highest Confidence" value={ai.highest_confidence != null ? `${ai.highest_confidence}%` : null} cls="text-emerald-400" />
          <Stat label="Lowest Confidence" value={ai.lowest_confidence != null ? `${ai.lowest_confidence}%` : null} cls="text-amber-400" />
        </div>
        <div className="grid gap-3 lg:grid-cols-3 mt-2">
          <div>
            <div className="text-[10px] text-zinc-500 uppercase tracking-wide mb-1">Confidence Distribution ({ai.confidence_source})</div>
            {Object.entries(ai.confidence_distribution ?? {}).map(([bucket, count]: any) => (
              <div key={bucket} className="flex items-center gap-2 text-[11px] font-mono py-0.5">
                <span className="w-14 text-zinc-500">{bucket}</span>
                <div className="h-2 bg-sky-500/60 rounded" style={{ width: `${Math.min(100, count * 12)}px` }} />
                <span className="text-zinc-300">{count}</span>
              </div>
            ))}
          </div>
          <div>
            <div className="text-[10px] text-zinc-500 uppercase tracking-wide mb-1">Strategy Distribution (latest scan)</div>
            <MiniTable headers={["Strategy", "Count"]}
              rows={Object.entries(ai.strategy_distribution ?? {}).map(([k, v]: any) => [k, v])} />
          </div>
          <div>
            <div className="text-[10px] text-zinc-500 uppercase tracking-wide mb-1">Sector Distribution (latest scan)</div>
            <MiniTable headers={["Sector", "Count"]}
              rows={Object.entries(ai.sector_distribution ?? {}).map(([k, v]: any) => [k, v])} />
          </div>
        </div>
        <div className="grid grid-cols-2 gap-2 mt-2">
          <Stat label="Top Performing Strategy" value={ai.top_strategy} cls="text-emerald-400" />
          <Stat label="Worst Performing Strategy" value={ai.worst_strategy} cls="text-red-400" />
        </div>
        {ai.strategy_performance_source && (
          <div className="text-[10px] text-zinc-600">strategy performance source: {ai.strategy_performance_source}</div>
        )}
      </SectionCard>
    </>
  );
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export default function PaperTradingValidation() {
  const [exporting, setExporting] = useState<"csv" | "json" | null>(null);

  const sessionQ = useQuery({
    queryKey: ["validation-session"],
    queryFn: () => fetchSection("/validation/session"),
    refetchInterval: 60_000,
    staleTime: 30_000,
  });
  const historyQ = useQuery({
    queryKey: ["validation-history"],
    queryFn: () => fetchSection("/validation/history"),
    refetchInterval: 120_000,
    staleTime: 60_000,
  });
  const qualityQ = useQuery({
    queryKey: ["validation-quality"],
    queryFn: () => fetchSection("/validation/quality"),
    refetchInterval: 120_000,
    staleTime: 60_000,
  });
  const statsQ = useQuery({
    queryKey: ["validation-statistics"],
    queryFn: () => fetchSection("/validation/statistics"),
    refetchInterval: 60_000,
    staleTime: 30_000,
  });

  const loading = sessionQ.isLoading || historyQ.isLoading || qualityQ.isLoading || statsQ.isLoading;

  const refetchAll = () => {
    void sessionQ.refetch();
    void historyQ.refetch();
    void qualityQ.refetch();
    void statsQ.refetch();
  };

  const downloadExport = async (fmt: "csv" | "json") => {
    setExporting(fmt);
    try {
      const url = `${BASE_URL}api/validation/export/${fmt}`;
      window.open(url, "_blank");
    } finally {
      setExporting(null);
    }
  };

  // Check if disabled
  const session = sessionQ.data;
  const isDisabled = session?.status === "DISABLED";

  return (
    <div className="space-y-4 p-4">
      {/* Header */}
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <h1 className="text-lg font-semibold text-zinc-100 flex items-center gap-2">
            <ClipboardCheck className="h-5 w-5 text-sky-400" /> Paper Trading Validation
          </h1>
          <Badge variant="outline" className="mt-1 text-[10px] text-amber-400 border-amber-700">
            {LABEL}
          </Badge>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button size="sm" variant="outline" onClick={refetchAll} disabled={loading}>
            {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
            <span className="ml-1">Refresh</span>
          </Button>
          <Button size="sm" variant="outline" onClick={() => downloadExport("csv")} disabled={!!exporting || isDisabled}>
            {exporting === "csv" ? <Loader2 className="h-4 w-4 animate-spin" /> : <Download className="h-4 w-4" />}
            <span className="ml-1">Export CSV</span>
          </Button>
          <Button size="sm" variant="outline" onClick={() => downloadExport("json")} disabled={!!exporting || isDisabled}>
            {exporting === "json" ? <Loader2 className="h-4 w-4 animate-spin" /> : <Download className="h-4 w-4" />}
            <span className="ml-1">Export JSON</span>
          </Button>
        </div>
      </div>

      {/* Aggregated dashboard — always available (canonical stores, not the
          optional validation collector) */}
      <ValidationDashboardSections />

      {isDisabled && <DisabledBanner message={session?.message} />}

      {!isDisabled && (
        <>
          {/* ----------------------------------------------------------------
              Section 1: Today's Session
          ---------------------------------------------------------------- */}
          <SectionCard title="Today's Session" icon={Calendar}>
            {sessionQ.isLoading ? (
              <div className="flex items-center gap-2 text-zinc-400 py-4 justify-center">
                <Loader2 className="h-4 w-4 animate-spin" /> Loading session…
              </div>
            ) : sessionQ.isError ? (
              <div className="text-red-400 text-[11px] flex gap-1">
                <AlertTriangle className="h-4 w-4 shrink-0" /> {String(sessionQ.error)}
              </div>
            ) : (() => {
              const s = sessionQ.data?.session;
              const m = sessionQ.data?.today_metrics;
              if (!s) return <div className="text-zinc-500 text-[11px]">Session data unavailable.</div>;
              return (
                <div className="space-y-3">
                  {/* Session metadata */}
                  <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
                    <Stat label="Date" value={s.trading_date} />
                    <Stat label="Market Status" value={s.market_status}
                      cls={s.market_status === "OPEN" ? "text-emerald-400" : "text-amber-400"} />
                    <Stat label="NIFTY 50" value={s.nifty ? `₹${s.nifty.toLocaleString()}` : "Unavailable"} />
                    <Stat label="BANK NIFTY" value={s.bank_nifty ? `₹${s.bank_nifty.toLocaleString()}` : "Unavailable"} />
                    <Stat label="INDIA VIX" value={s.india_vix ?? "Unavailable"} />
                    <Stat label="Leading Sector" value={s.leading_sector} />
                    <Stat label="Top Gap" value={s.top_gap} />
                    <Stat label="Market Breadth" value={s.market_breadth} />
                  </div>

                  {/* Today's metrics */}
                  {m && (
                    <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-8 gap-2">
                      <Stat label="Trades Today" value={m.trade_count} />
                      <Stat label="Winners" value={m.winning_trades} cls="text-emerald-400" />
                      <Stat label="Losers" value={m.losing_trades} cls="text-red-400" />
                      <Stat label="Win Rate" value={pct(m.win_rate)} cls={m.win_rate >= 0.5 ? "text-emerald-400" : "text-red-400"} />
                      <Stat label="Net P&L" value={rs(m.net_pnl)} cls={m.net_pnl >= 0 ? "text-emerald-400" : "text-red-400"} />
                      <Stat label="Drawdown" value={pct(m.drawdown)} cls="text-amber-400" />
                      <Stat label="Avg Hold" value={mins(m.avg_holding_time_minutes)} />
                      <Stat label="Avg AI Conf" value={score(m.avg_ai_confidence)} />
                    </div>
                  )}

                  {/* Today's trades */}
                  {(sessionQ.data?.today_trades ?? []).length > 0 && (
                    <div className="space-y-1">
                      <div className="text-[10px] uppercase tracking-wide text-zinc-500 mb-1">
                        Completed Trades Today ({sessionQ.data?.trade_count_today})
                      </div>
                      {(sessionQ.data?.today_trades ?? []).map((tr: any, i: number) => (
                        <div key={i} className="rounded border border-zinc-800 bg-zinc-900/40 p-2 font-mono text-[11px] flex flex-wrap items-center gap-2">
                          <span className="text-zinc-100 font-semibold">{tr.symbol}</span>
                          <span className={tr.pnl >= 0 ? "text-emerald-400" : "text-red-400"}>
                            {tr.pnl >= 0 ? "+" : ""}{rs(tr.pnl)} ({tr.pnl_pct > 0 ? "+" : ""}{(+tr.pnl_pct).toFixed(2)}%)
                          </span>
                          <Badge variant="outline" className="text-[10px]">{tr.strategy}</Badge>
                          <Badge variant="outline" className="text-[10px]">{tr.market_regime}</Badge>
                          <span className="text-zinc-500">sector: {tr.sector}</span>
                          <span className="text-zinc-500">conf {score(tr.ai_confidence)}</span>
                          <span className="text-zinc-500">hold {mins(tr.holding_time_minutes)}</span>
                          <span className="text-zinc-500">exit: {tr.exit_reason}</span>
                          <span className="text-zinc-500">EQ {score(tr.execution_quality_score)}</span>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              );
            })()}
          </SectionCard>

          {/* ----------------------------------------------------------------
              Section 2: Historical Performance
          ---------------------------------------------------------------- */}
          <SectionCard title="Historical Performance" icon={TrendingUp}>
            {historyQ.isLoading ? (
              <div className="flex items-center gap-2 text-zinc-400 py-4 justify-center">
                <Loader2 className="h-4 w-4 animate-spin" /> Loading history…
              </div>
            ) : historyQ.isError ? (
              <div className="text-red-400 text-[11px] flex gap-1">
                <AlertTriangle className="h-4 w-4 shrink-0" /> {String(historyQ.error)}
              </div>
            ) : (() => {
              const hist = historyQ.data?.history;
              if (!hist) return <div className="text-zinc-500 text-[11px]">History unavailable.</div>;

              const periods = ["weekly", "monthly", "rolling_30", "rolling_90", "rolling_180"] as const;
              const periodLabels: Record<string, string> = {
                weekly: "This Week", monthly: "This Month",
                rolling_30: "30 Days", rolling_90: "90 Days", rolling_180: "180 Days",
              };

              return (
                <div className="space-y-3">
                  {/* Period roll-ups */}
                  <div className="grid grid-cols-1 sm:grid-cols-3 lg:grid-cols-5 gap-2">
                    {periods.map((p) => {
                      const d = hist[p];
                      if (!d) return null;
                      return (
                        <div key={p} className="rounded border border-zinc-800 bg-zinc-900/50 p-2 space-y-1">
                          <div className="text-[10px] uppercase tracking-wide text-zinc-400 font-semibold">
                            {periodLabels[p]}
                          </div>
                          <div className="grid grid-cols-2 gap-1 text-[11px] font-mono">
                            <span className="text-zinc-500">Trades</span>
                            <span className="text-zinc-200">{d.trade_count ?? "—"}</span>
                            <span className="text-zinc-500">Win%</span>
                            <span className={cn((d.win_rate ?? 0) >= 0.5 ? "text-emerald-400" : "text-red-400")}>
                              {pct(d.win_rate)}
                            </span>
                            <span className="text-zinc-500">P&L</span>
                            <span className={cn((d.net_pnl ?? 0) >= 0 ? "text-emerald-400" : "text-red-400")}>
                              {rs(d.net_pnl)}
                            </span>
                            <span className="text-zinc-500">DD</span>
                            <span className="text-amber-400">{pct(d.drawdown)}</span>
                          </div>
                        </div>
                      );
                    })}
                  </div>

                  {/* Daily history table */}
                  {hist.daily?.length > 0 && (
                    <div>
                      <div className="text-[10px] uppercase tracking-wide text-zinc-500 mb-1">
                        Daily History ({hist.total_trading_days} trading days)
                      </div>
                      <MiniTable
                        headers={["Date", "Trades", "Win%", "Net P&L", "Drawdown", "Avg Hold", "Avg Conf"]}
                        rows={hist.daily.slice(0, 30).map((d: any) => [
                          d.date,
                          d.trade_count,
                          pct(d.win_rate),
                          <span key="pnl" className={d.net_pnl >= 0 ? "text-emerald-400" : "text-red-400"}>
                            {rs(d.net_pnl)}
                          </span>,
                          pct(d.drawdown),
                          mins(d.avg_holding_time_minutes),
                          score(d.avg_ai_confidence),
                        ])}
                      />
                    </div>
                  )}
                  {!hist.daily?.length && (
                    <div className="text-zinc-500 text-[11px]">No historical trade data yet.</div>
                  )}
                </div>
              );
            })()}
          </SectionCard>

          {/* ----------------------------------------------------------------
              Section 3: Data Quality
          ---------------------------------------------------------------- */}
          <SectionCard title="Data Quality" icon={ShieldCheck}>
            {qualityQ.isLoading ? (
              <div className="flex items-center gap-2 text-zinc-400 py-4 justify-center">
                <Loader2 className="h-4 w-4 animate-spin" /> Running quality checks…
              </div>
            ) : qualityQ.isError ? (
              <div className="text-red-400 text-[11px] flex gap-1">
                <AlertTriangle className="h-4 w-4 shrink-0" /> {String(qualityQ.error)}
              </div>
            ) : (() => {
              const q = qualityQ.data?.quality;
              if (!q) return <div className="text-zinc-500 text-[11px]">Quality report unavailable.</div>;
              const verdictCls = q.verdict === "CLEAN" ? "text-emerald-400"
                : q.verdict === "WARNINGS" ? "text-amber-400" : "text-red-400";
              const VerdictIcon = q.verdict === "CLEAN" ? CheckCircle2
                : q.verdict === "WARNINGS" ? AlertTriangle : XCircle;

              const checks = [
                { label: "Missing Values", items: q.missing_values, count: q.missing_values?.length ?? 0 },
                { label: "Duplicate Trades", items: q.duplicate_trades, count: q.duplicate_trades?.length ?? 0 },
                { label: "Invalid Timestamps", items: q.invalid_timestamps, count: q.invalid_timestamps?.length ?? 0 },
                { label: "Negative Quantities", items: q.negative_quantities, count: q.negative_quantities?.length ?? 0 },
                { label: "Impossible Prices", items: q.impossible_prices, count: q.impossible_prices?.length ?? 0 },
                { label: "Incomplete AI Data", items: q.incomplete_ai_data, count: q.incomplete_ai_data?.length ?? 0 },
                { label: "Corrupted Records", items: q.corrupted_records, count: q.corrupted_records?.length ?? 0 },
              ];

              return (
                <div className="space-y-3">
                  <div className="flex flex-wrap items-center gap-4">
                    <div className="flex items-center gap-2">
                      <VerdictIcon className={cn("h-5 w-5", verdictCls)} />
                      <span className={cn("font-mono font-semibold", verdictCls)}>{q.verdict}</span>
                    </div>
                    <div className="text-zinc-400 text-[11px]">
                      Quality Score: <span className="text-zinc-200 font-mono">{q.quality_score?.toFixed(1)}/100</span>
                    </div>
                    <div className="text-zinc-400 text-[11px]">
                      Records Checked: <span className="text-zinc-200 font-mono">{q.total_records}</span>
                    </div>
                    <div className="text-zinc-400 text-[11px]">
                      Total Issues: <span className={cn("font-mono", q.total_issues > 0 ? "text-amber-400" : "text-emerald-400")}>
                        {q.total_issues}
                      </span>
                    </div>
                  </div>

                  <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-7 gap-2">
                    {checks.map((c) => (
                      <div key={c.label} className="rounded border border-zinc-800 bg-zinc-900/50 p-2">
                        <div className="text-[10px] text-zinc-500 truncate">{c.label}</div>
                        <div className={cn("text-sm font-mono", c.count > 0 ? "text-amber-400" : "text-emerald-400")}>
                          {c.count}
                        </div>
                      </div>
                    ))}
                  </div>

                  {q.total_issues > 0 && (
                    <div className="space-y-1">
                      <div className="text-[10px] text-zinc-500 uppercase tracking-wide">Issue Details</div>
                      {checks.filter(c => c.count > 0).map((c) => (
                        <div key={c.label} className="text-[11px] text-amber-300 font-mono">
                          [{c.label}] {Array.isArray(c.items)
                            ? c.items.slice(0, 5).map((i: any) =>
                              typeof i === "object" ? `${i.trade_id}: ${(i.fields ?? []).join(",")}` : String(i)
                            ).join("; ")
                            : ""
                          }
                          {c.count > 5 ? ` … +${c.count - 5} more` : ""}
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              );
            })()}
          </SectionCard>

          {/* ----------------------------------------------------------------
              Section 4: Trade Timeline
          ---------------------------------------------------------------- */}
          <SectionCard title="Trade Timeline" icon={Activity}>
            {statsQ.isLoading ? (
              <div className="flex items-center gap-2 text-zinc-400 py-4 justify-center">
                <Loader2 className="h-4 w-4 animate-spin" /> Loading timeline…
              </div>
            ) : (() => {
              const stats = statsQ.data?.statistics;
              if (!stats || stats.total_trades === 0) {
                return <div className="text-zinc-500 text-[11px]">No completed trades yet. Timeline will appear once trades are recorded.</div>;
              }
              return (
                <div className="space-y-3">
                  <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
                    <Stat label="Total Completed" value={stats.total_trades} />
                    <Stat label="Winners" value={stats.winning_trades} cls="text-emerald-400" />
                    <Stat label="Losers" value={stats.losing_trades} cls="text-red-400" />
                    <Stat label="Best Trade" value={rs(stats.best_trade_pnl)} cls="text-emerald-400" />
                    <Stat label="Worst Trade" value={rs(stats.worst_trade_pnl)} cls="text-red-400" />
                    <Stat label="Avg Hold" value={mins(stats.avg_holding_time_minutes)} />
                    <Stat label="Net P&L" value={rs(stats.net_pnl)} cls={stats.net_pnl >= 0 ? "text-emerald-400" : "text-red-400"} />
                    <Stat label="Max Drawdown" value={pct(stats.max_drawdown)} cls="text-amber-400" />
                  </div>

                  {/* Exit reason breakdown */}
                  {stats.exit_reasons && Object.keys(stats.exit_reasons).length > 0 && (
                    <div>
                      <div className="text-[10px] text-zinc-500 uppercase tracking-wide mb-1">Exit Reason Breakdown</div>
                      <div className="flex flex-wrap gap-2">
                        {Object.entries(stats.exit_reasons as Record<string, number>)
                          .sort(([, a], [, b]) => b - a)
                          .map(([reason, count]) => (
                            <div key={reason} className="rounded border border-zinc-800 bg-zinc-900/50 px-2 py-1 text-[11px] font-mono">
                              <span className="text-zinc-400">{reason}</span>
                              <span className="text-sky-400 ml-2">{count}</span>
                            </div>
                          ))}
                      </div>
                    </div>
                  )}
                </div>
              );
            })()}
          </SectionCard>

          {/* ----------------------------------------------------------------
              Section 5: Validation Statistics
          ---------------------------------------------------------------- */}
          <div className="grid gap-4 lg:grid-cols-2">
            <SectionCard title="Validation Statistics — Strategy Breakdown" icon={BarChart3}>
              {statsQ.isLoading ? (
                <div className="flex items-center gap-2 text-zinc-400 py-4 justify-center">
                  <Loader2 className="h-4 w-4 animate-spin" />
                </div>
              ) : (() => {
                const stats = statsQ.data?.statistics;
                const strategies = stats?.strategies ?? [];
                return (
                  <>
                    <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 mb-3">
                      <Stat label="Avg AI Confidence" value={score(stats?.avg_ai_confidence)} cls="text-sky-400" />
                      <Stat label="Avg Execution Score" value={score(stats?.avg_execution_score)} cls="text-sky-400" />
                      <Stat label="Avg Executive Score" value={score(stats?.avg_executive_score)} cls="text-sky-400" />
                      <Stat label="Overall Win Rate" value={pct(stats?.win_rate)} cls={(stats?.win_rate ?? 0) >= 0.5 ? "text-emerald-400" : "text-red-400"} />
                    </div>
                    <MiniTable
                      headers={["Strategy", "Trades", "Win%", "Net P&L"]}
                      rows={strategies.map((s: any) => [
                        s.strategy,
                        s.trades,
                        pct(s.win_rate),
                        <span key="pnl" className={s.net_pnl >= 0 ? "text-emerald-400" : "text-red-400"}>
                          {rs(s.net_pnl)}
                        </span>,
                      ])}
                    />
                  </>
                );
              })()}
            </SectionCard>

            <SectionCard title="Validation Statistics — Sector Breakdown" icon={Layers}>
              {statsQ.isLoading ? (
                <div className="flex items-center gap-2 text-zinc-400 py-4 justify-center">
                  <Loader2 className="h-4 w-4 animate-spin" />
                </div>
              ) : (() => {
                const sectors = statsQ.data?.statistics?.sectors ?? [];
                return (
                  <MiniTable
                    headers={["Sector", "Trades", "Win%", "Net P&L"]}
                    rows={sectors.map((s: any) => [
                      s.sector,
                      s.trades,
                      pct(s.win_rate),
                      <span key="pnl" className={s.net_pnl >= 0 ? "text-emerald-400" : "text-red-400"}>
                        {rs(s.net_pnl)}
                      </span>,
                    ])}
                  />
                );
              })()}
            </SectionCard>
          </div>

          {/* ----------------------------------------------------------------
              Section 6: Growth of Dataset
          ---------------------------------------------------------------- */}
          <SectionCard title="Growth of Dataset" icon={Database}>
            {historyQ.isLoading ? (
              <div className="flex items-center gap-2 text-zinc-400 py-4 justify-center">
                <Loader2 className="h-4 w-4 animate-spin" /> Loading growth data…
              </div>
            ) : (() => {
              const growth = historyQ.data?.growth;
              if (!growth) return <div className="text-zinc-500 text-[11px]">Growth data unavailable.</div>;

              const rows = growth.growth ?? [];
              if (!rows.length) {
                return (
                  <div className="space-y-2">
                    <div className="text-zinc-500 text-[11px]">Dataset is empty — no completed trades recorded yet.</div>
                    <div className="text-[11px] text-zinc-400">
                      Total Records: <span className="text-zinc-200 font-mono">{growth.total_records ?? 0}</span>
                    </div>
                  </div>
                );
              }

              const last = rows[rows.length - 1];
              const storageEstimateKb = (growth.total_records ?? 0) * 0.5; // ~500 bytes per record

              return (
                <div className="space-y-3">
                  <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
                    <Stat label="Total Records" value={growth.total_records} cls="text-sky-400" />
                    <Stat label="Cumulative P&L" value={rs(last?.cumulative_pnl)} cls={last?.cumulative_pnl >= 0 ? "text-emerald-400" : "text-red-400"} />
                    <Stat label="Est. Storage" value={storageEstimateKb < 1 ? "<1 KB" : `~${storageEstimateKb.toFixed(0)} KB`} />
                    <Stat label="Trading Days" value={rows.length} />
                  </div>

                  <div>
                    <div className="text-[10px] text-zinc-500 uppercase tracking-wide mb-1">
                      Daily Accumulation (last 30 days)
                    </div>
                    <MiniTable
                      headers={["Date", "Day Trades", "Total Trades", "Daily P&L", "Cumulative P&L"]}
                      rows={rows.slice(-30).reverse().map((r: any) => [
                        r.date,
                        r.trades_that_day,
                        r.cumulative_trades,
                        <span key="dpnl" className={r.daily_pnl >= 0 ? "text-emerald-400" : "text-red-400"}>
                          {rs(r.daily_pnl)}
                        </span>,
                        <span key="cpnl" className={r.cumulative_pnl >= 0 ? "text-emerald-400" : "text-red-400"}>
                          {rs(r.cumulative_pnl)}
                        </span>,
                      ])}
                    />
                  </div>

                  <div className="text-[11px] text-zinc-500 border-t border-zinc-800 pt-2">
                    Storage growth estimate: ~500 bytes per completed trade record.
                    At 5 trades/day × 250 trading days = ~625 KB/year.
                    Background collection only — zero impact on paper trading performance.
                  </div>
                </div>
              );
            })()}
          </SectionCard>
        </>
      )}
    </div>
  );
}
