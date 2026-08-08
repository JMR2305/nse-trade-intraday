/**
 * Phase4ASession.tsx — Phase 4A Controlled Paper Trading Operations dashboard.
 *
 * PAPER TRADING / RESEARCH ONLY — no live broker execution.
 *
 * Panels:
 *   1. Pre-Market Status Strip  — 15-check grid, last run, READY/WARN/FAIL
 *   2. Live Monitor Panel       — 14 metric cards, polling every 30s
 *   3. Trade Journal Table      — 13-field rows + accounting consistency
 *   4. Risk Metrics Panel       — all 15 metrics
 *   5. AI Performance Panel     — BUY/WATCH/NO_TRADE breakdown
 *   6. Session Reports          — download buttons for 7 report types
 */

import { useState, useCallback } from "react";
import { useQuery, useMutation } from "@tanstack/react-query";
import {
  RefreshCw, Shield, Activity, BookOpen, BarChart2,
  Brain, FileText, CheckCircle, XCircle, AlertTriangle,
  TrendingUp, TrendingDown, Download, Play, Zap,
  ChevronDown, ChevronUp, Clock
} from "lucide-react";
import { buildApiUrl } from "@/lib/apiConfig";
import DataFreshnessBar from "@/components/DataFreshnessBar";
import { useLiveStream } from "@/hooks/useLiveStream";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import { useToast } from "@/hooks/use-toast";

const LABEL = "PAPER TRADING / RESEARCH ONLY";

async function apiJson(path: string): Promise<unknown> {
  const res = await fetch(buildApiUrl(path));
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

// ── Verdict badge ─────────────────────────────────────────────────────────────

function VerdictBadge({ verdict }: { verdict: string }) {
  if (verdict === "PASS" || verdict === "READY") {
    return (
      <Badge className="bg-emerald-600/20 text-emerald-400 border-emerald-600/30 text-xs gap-1">
        <CheckCircle className="h-3 w-3" /> {verdict}
      </Badge>
    );
  }
  if (verdict === "WARN" || verdict === "READY_WITH_WARNINGS") {
    return (
      <Badge className="bg-amber-600/20 text-amber-400 border-amber-600/30 text-xs gap-1">
        <AlertTriangle className="h-3 w-3" /> {verdict}
      </Badge>
    );
  }
  return (
    <Badge className="bg-red-600/20 text-red-400 border-red-600/30 text-xs gap-1">
      <XCircle className="h-3 w-3" /> {verdict}
    </Badge>
  );
}

// ── Section 1: Pre-Market Strip ───────────────────────────────────────────────

function PreMarketStrip() {
  const { toast } = useToast();
  const { data, isLoading, refetch, isFetching } = useQuery<any>({
    queryKey: ["phase4a", "premarket"],
    queryFn: () => apiJson("/phase4a/premarket"),
    staleTime: 5 * 60_000,
    refetchOnWindowFocus: false,
  });

  const runMut = useMutation({
    mutationFn: () => apiJson("/phase4a/premarket?run=1"),
    onSuccess: () => { refetch(); toast({ title: "Pre-market checks complete" }); },
    onError: (e: any) => toast({ title: "Error", description: e.message, variant: "destructive" }),
  });

  const checks: any[] = data?.checks ?? [];
  const overall = data?.overall ?? "—";
  const ts = data?.generated_at?.slice(0, 19).replace("T", " ") ?? "—";

  return (
    <Card className="bg-[#0d1829] border-slate-700">
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Shield className="h-5 w-5 text-teal-400" />
            <CardTitle className="text-slate-100 text-base">Pre-Market Readiness</CardTitle>
            {data && <VerdictBadge verdict={overall} />}
          </div>
          <div className="flex items-center gap-2">
            <span className="text-xs text-slate-500">{ts}</span>
            <Button
              size="sm" variant="outline"
              className="border-slate-700 text-xs gap-1"
              onClick={() => runMut.mutate()}
              disabled={runMut.isPending || isFetching}
            >
              <Play className="h-3 w-3" />
              {runMut.isPending ? "Running…" : "Run Now"}
            </Button>
          </div>
        </div>
        <p className="text-xs text-amber-400 mt-1">⚠️ {LABEL}</p>
      </CardHeader>
      <CardContent>
        {isLoading ? (
          <div className="text-slate-500 text-sm">Loading pre-market checks…</div>
        ) : checks.length === 0 ? (
          <div className="text-slate-500 text-sm">No check data. Click "Run Now" to execute.</div>
        ) : (
          <div className="grid grid-cols-3 gap-2 sm:grid-cols-5">
            {checks.map((c: any, i: number) => (
              <div
                key={i}
                className={`rounded-lg p-2 text-xs border ${
                  c.verdict === "PASS"
                    ? "bg-emerald-950/30 border-emerald-700/30 text-emerald-400"
                    : c.verdict === "WARN"
                    ? "bg-amber-950/30 border-amber-700/30 text-amber-400"
                    : "bg-red-950/30 border-red-700/30 text-red-400"
                }`}
              >
                <div className="font-medium truncate">{c.name}</div>
                <div className="text-[10px] opacity-70 truncate">{c.category}</div>
                {c.latency_ms && (
                  <div className="text-[10px] opacity-60">{c.latency_ms}ms</div>
                )}
              </div>
            ))}
          </div>
        )}
        {data && (
          <div className="mt-3 flex gap-4 text-xs text-slate-400">
            <span className="text-emerald-400">✓ {data.passed} PASS</span>
            <span className="text-amber-400">⚠ {data.warned} WARN</span>
            <span className="text-red-400">✗ {data.failed} FAIL</span>
            <span className="ml-auto">{data.total}/15 checks</span>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

// ── Section 2: Live Monitor Panel ─────────────────────────────────────────────

function MetricCard({
  label, value, unit = "", icon, color = "text-slate-300", trend
}: {
  label: string; value: string | number | null | undefined;
  unit?: string; icon?: React.ReactNode; color?: string; trend?: "up" | "down" | null;
}) {
  const display = value === null || value === undefined ? "—" : `${value}${unit}`;
  return (
    <div className="bg-slate-800/40 rounded-lg p-3 border border-slate-700/50">
      <div className="flex items-center gap-1 text-xs text-slate-500 mb-1">
        {icon}
        <span className="truncate">{label}</span>
      </div>
      <div className={`text-lg font-semibold ${color} flex items-center gap-1`}>
        {display}
        {trend === "up" && <TrendingUp className="h-3 w-3 text-emerald-400" />}
        {trend === "down" && <TrendingDown className="h-3 w-3 text-red-400" />}
      </div>
    </div>
  );
}

function MonitorPanel() {
  const { data, isLoading, dataUpdatedAt } = useQuery<any>({
    queryKey: ["phase4a", "monitor", "tick"],
    queryFn: () => apiJson("/phase4a/monitor/tick"),
    refetchInterval: 30_000,
    staleTime: 25_000,
  });
  const stream = useLiveStream();
  const { data: dash } = useOpsDashboard();
  const mon = dash?.monitor ?? {};
  const ts = dataUpdatedAt ? new Date(dataUpdatedAt).toLocaleTimeString("en-IN") : "—";
  const recs = data?.ai_recommendations ?? {};
  const freshness = data?.market_data_freshness_s ?? mon.freshness_s;
  const scannerLatencyMs = data?.scanner_latency_ms ??
    (mon.scanner_latency_s != null ? Math.round(mon.scanner_latency_s * 1000) : null);
  const realisedPnl = data?.realised_pnl ?? mon.realized_pnl_today;
  // Prefer the API server's own rolling p95 (real request durations) over the
  // tick's scan-provider latency, which measures data-provider fetch time.
  const apiMs = mon.api_response_ms != null ? Math.round(mon.api_response_ms) : data?.api_latency_ms ?? null;
  const paperOrders = data?.paper_orders ?? mon.paper_orders_today;
  const riskBlocks = data?.risk_blocks ?? mon.risk_blocks;
  const memMb = data?.memory_rss_mb ?? mon.memory_used_mb;
  const cpuPct = data?.cpu_pct ?? mon.cpu_pct;

  return (
    <Card className="bg-[#0d1829] border-slate-700">
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Activity className="h-5 w-5 text-teal-400" />
            <CardTitle className="text-slate-100 text-base">Live Session Monitor</CardTitle>
            {!isLoading && (
              <Badge className="bg-teal-600/20 text-teal-400 border-teal-600/30 text-[10px]">
                Auto-refresh 30s
              </Badge>
            )}
          </div>
          <div className="flex items-center gap-2">
            <Clock className="h-3 w-3 text-slate-500" />
            <span className="text-xs text-slate-500">{ts}</span>
            {stream.connection === "connected" && (
              <Badge className="bg-emerald-600/20 text-emerald-400 border-emerald-600/30 text-[10px]">
                SSE ●
              </Badge>
            )}
          </div>
        </div>
      </CardHeader>
      <CardContent>
        <DataFreshnessBar variant="scan" />
        <div className="grid grid-cols-2 gap-2 mt-3 sm:grid-cols-4 lg:grid-cols-7">
          <MetricCard
            label="Freshness"
            value={freshness != null ? `${freshness}s` : null}
            icon={<Clock className="h-3 w-3" />}
            color={
              freshness != null
                ? freshness < 300 ? "text-emerald-400" : "text-amber-400"
                : "text-slate-400"
            }
          />
          <MetricCard
            label="Scanner Latency"
            value={scannerLatencyMs}
            unit="ms"
            icon={<Zap className="h-3 w-3" />}
            color={
              scannerLatencyMs != null
                ? scannerLatencyMs < 30000 ? "text-emerald-400" : "text-amber-400"
                : "text-slate-400"
            }
          />
          <MetricCard
            label="Signals"
            value={data?.signals_generated ?? mon.signals_generated}
            icon={<BarChart2 className="h-3 w-3" />}
            color="text-sky-400"
          />
          <MetricCard
            label="BUY / WATCH"
            value={
              data?.ai_recommendations
                ? `${recs.BUY ?? 0} / ${recs.WATCH ?? 0}`
                : dash?.decision_distribution
                ? `${dash.decision_distribution.buy ?? 0} / ${dash.decision_distribution.watch ?? 0}`
                : null
            }
            icon={<Brain className="h-3 w-3" />}
            color="text-violet-400"
          />
          <MetricCard
            label="Portfolio ₹"
            value={
              (data?.portfolio_value ?? mon.portfolio_value) != null
                ? `₹${Number(data?.portfolio_value ?? mon.portfolio_value).toFixed(0)}`
                : null
            }
            icon={<TrendingUp className="h-3 w-3" />}
            color="text-teal-400"
          />
          <MetricCard
            label="Realised P&L"
            value={realisedPnl != null ? `₹${Number(realisedPnl).toFixed(2)}` : null}
            icon={<BarChart2 className="h-3 w-3" />}
            color={
              realisedPnl != null
                ? realisedPnl >= 0 ? "text-emerald-400" : "text-red-400"
                : "text-slate-400"
            }
          />
          <MetricCard
            label="API Response"
            value={apiMs}
            unit="ms"
            icon={<Activity className="h-3 w-3" />}
            color={
              apiMs != null
                ? apiMs < 200 ? "text-emerald-400" : "text-amber-400"
                : "text-slate-400"
            }
          />
        </div>
        <div className="grid grid-cols-2 gap-2 mt-2 sm:grid-cols-4 lg:grid-cols-7">
          <MetricCard label="Paper Orders" value={paperOrders} icon={<BookOpen className="h-3 w-3" />} />
          <MetricCard label="Risk Blocks" value={riskBlocks}
            color={riskBlocks ? "text-red-400" : "text-emerald-400"} />
          <MetricCard label="Memory" value={memMb} unit="MB" />
          <MetricCard label="CPU" value={cpuPct} unit="%" />
          <MetricCard label="Queue Depth" value={mon.queue_depth} />
          <MetricCard label="Decision Time" value={mon.decision_time_s} unit="s" />
          <MetricCard label="Execution Time" value={mon.execution_time_s} unit="s" />
        </div>
        {data && (
          <div className="mt-2 text-xs text-slate-500 flex gap-4">
            <span>SSE reconnects: {data.sse_reconnect_count ?? "—"}</span>
            <span>Errors: {data.errors ?? 0}</span>
            <span>Warnings: {data.warnings ?? 0}</span>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

// ── Section 3: Trade Journal ──────────────────────────────────────────────────

function TradeJournalTable() {
  const { data, isLoading } = useQuery<any>({
    queryKey: ["phase4a", "trade-journal"],
    queryFn: () => apiJson("/phase4a/trade-journal"),
    staleTime: 60_000,
    refetchInterval: 60_000,
  });

  const trades: any[] = data?.trades ?? [];

  return (
    <Card className="bg-[#0d1829] border-slate-700">
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <BookOpen className="h-5 w-5 text-teal-400" />
            <CardTitle className="text-slate-100 text-base">Trade Journal</CardTitle>
            {data && (
              <Badge className="bg-slate-700/50 text-slate-300 text-xs">
                {data.trade_count} trades
              </Badge>
            )}
          </div>
          {data && (
            <Badge
              className={`text-xs ${
                data.portfolio_accounting_consistent
                  ? "bg-emerald-600/20 text-emerald-400 border-emerald-600/30"
                  : "bg-amber-600/20 text-amber-400 border-amber-600/30"
              }`}
            >
              {data.portfolio_accounting_consistent ? "✓ Accounting OK" : "⚠ Drift Detected"}
            </Badge>
          )}
        </div>
        {data?.audit_id && (
          <p className="text-[10px] text-slate-600 font-mono mt-1">
            Audit ID: {data.audit_id}
          </p>
        )}
      </CardHeader>
      <CardContent className="p-0">
        {isLoading ? (
          <div className="p-4 text-slate-500 text-sm">Loading trade journal…</div>
        ) : trades.length === 0 ? (
          <div className="p-4 text-slate-500 text-sm">No trades recorded today.</div>
        ) : (
          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow className="border-slate-700/50 hover:bg-transparent">
                  {["Symbol", "Signal", "Conf", "Risk", "Entry", "Exit", "Stop", "Target",
                    "Hold", "P&L", "Exit Reason", "Journal ID"].map((h) => (
                    <TableHead key={h} className="text-slate-400 text-xs py-2">{h}</TableHead>
                  ))}
                </TableRow>
              </TableHeader>
              <TableBody>
                {trades.map((t: any, i: number) => {
                  const pnl = t.pnl;
                  return (
                    <TableRow key={i} className="border-slate-700/30 hover:bg-slate-800/30">
                      <TableCell className="text-slate-200 font-medium text-xs py-2">{t.symbol}</TableCell>
                      <TableCell className="text-xs py-2">
                        <Badge className={`text-[10px] ${
                          t.signal?.includes("BUY") ? "bg-emerald-600/20 text-emerald-400"
                          : t.signal?.includes("WATCH") ? "bg-amber-600/20 text-amber-400"
                          : "bg-slate-700/50 text-slate-400"
                        }`}>{t.signal || "—"}</Badge>
                      </TableCell>
                      <TableCell className="text-slate-300 text-xs py-2">{t.ai_confidence?.toFixed(1)}%</TableCell>
                      <TableCell className="text-xs py-2">
                        <Badge className={`text-[10px] ${
                          t.risk_decision === "ALLOW"
                            ? "bg-emerald-600/20 text-emerald-400"
                            : "bg-red-600/20 text-red-400"
                        }`}>{t.risk_decision}</Badge>
                      </TableCell>
                      <TableCell className="text-slate-300 text-xs py-2 font-mono">₹{t.entry?.toFixed(2)}</TableCell>
                      <TableCell className="text-slate-300 text-xs py-2 font-mono">
                        {t.exit != null ? `₹${t.exit.toFixed(2)}` : "—"}
                      </TableCell>
                      <TableCell className="text-slate-400 text-xs py-2 font-mono">₹{t.stop?.toFixed(2)}</TableCell>
                      <TableCell className="text-slate-400 text-xs py-2 font-mono">₹{t.target?.toFixed(2)}</TableCell>
                      <TableCell className="text-slate-400 text-xs py-2">{t.holding_time || "—"}</TableCell>
                      <TableCell className={`text-xs py-2 font-medium font-mono ${
                        pnl == null ? "text-slate-500"
                        : pnl >= 0 ? "text-emerald-400" : "text-red-400"
                      }`}>
                        {pnl != null ? `₹${pnl.toFixed(2)}` : "OPEN"}
                      </TableCell>
                      <TableCell className="text-slate-400 text-[10px] py-2">{t.exit_reason || "—"}</TableCell>
                      <TableCell className="text-slate-600 text-[10px] py-2 font-mono">{t.journal_id}</TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

// ── Section 4: Risk Metrics ───────────────────────────────────────────────────

function RiskMetricsPanel() {
  const { data, isLoading } = useQuery<any>({
    queryKey: ["phase4a", "risk-metrics"],
    queryFn: () => apiJson("/phase4a/risk-metrics"),
    staleTime: 2 * 60_000,
    refetchInterval: 2 * 60_000,
  });

  const m = data ?? {};
  const pf = m.profit_factor;

  return (
    <Card className="bg-[#0d1829] border-slate-700">
      <CardHeader className="pb-3">
        <div className="flex items-center gap-2">
          <BarChart2 className="h-5 w-5 text-teal-400" />
          <CardTitle className="text-slate-100 text-base">Risk Validation</CardTitle>
          {data && (
            <Badge className="bg-slate-700/50 text-slate-300 text-xs">
              {m.closed_trades ?? 0} closed trades
            </Badge>
          )}
        </div>
      </CardHeader>
      <CardContent>
        {isLoading ? (
          <div className="text-slate-500 text-sm">Computing risk metrics…</div>
        ) : (
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
            {[
              { label: "Win Rate", value: m.win_rate_pct != null ? `${m.win_rate_pct?.toFixed(1)}%` : "—", color: m.win_rate_pct >= 50 ? "text-emerald-400" : "text-red-400" },
              { label: "Profit Factor", value: pf != null ? `${pf}` : "—", color: pf >= 1 ? "text-emerald-400" : "text-red-400" },
              { label: "Expectancy", value: m.expectancy != null ? `₹${m.expectancy?.toFixed(2)}` : "—", color: (m.expectancy ?? 0) >= 0 ? "text-emerald-400" : "text-red-400" },
              { label: "Max Drawdown", value: m.max_drawdown_pct != null ? `${m.max_drawdown_pct?.toFixed(2)}%` : "—", color: (m.max_drawdown_pct ?? 0) < 5 ? "text-emerald-400" : "text-amber-400" },
              { label: "Avg R/R", value: m.avg_reward_risk_ratio ?? "—" },
              { label: "Largest Win", value: m.largest_win != null ? `₹${m.largest_win?.toFixed(2)}` : "—", color: "text-emerald-400" },
              { label: "Largest Loss", value: m.largest_loss != null ? `₹${m.largest_loss?.toFixed(2)}` : "—", color: "text-red-400" },
              { label: "Daily Risk", value: m.daily_risk_pct != null ? `${m.daily_risk_pct?.toFixed(4)}%` : "—", color: (m.daily_risk_pct ?? 0) < 3 ? "text-emerald-400" : "text-red-400" },
              { label: "Capital Usage", value: m.capital_usage_pct != null ? `${m.capital_usage_pct?.toFixed(1)}%` : "—" },
              { label: "Open Pos Limit", value: m.open_position_limit_usage_pct != null ? `${m.open_position_limit_usage_pct?.toFixed(1)}%` : "—" },
              { label: "Kill Switch", value: m.kill_switch_events ?? 0, color: m.kill_switch_events > 0 ? "text-red-400" : "text-emerald-400" },
              { label: "Circuit Breaker", value: m.circuit_breaker_events ?? 0, color: m.circuit_breaker_events > 0 ? "text-amber-400" : "text-emerald-400" },
            ].map((item, i) => (
              <div key={i} className="bg-slate-800/40 rounded-lg p-3 border border-slate-700/50">
                <div className="text-xs text-slate-500 mb-1">{item.label}</div>
                <div className={`text-base font-semibold ${item.color ?? "text-slate-200"}`}>
                  {String(item.value)}
                </div>
              </div>
            ))}
          </div>
        )}
        {m.sector_exposure && Object.keys(m.sector_exposure).length > 0 && (
          <div className="mt-4">
            <p className="text-xs text-slate-500 mb-2">Sector Exposure</p>
            <div className="flex flex-wrap gap-2">
              {Object.entries(m.sector_exposure as Record<string, number>).map(([sector, pct]) => (
                <Badge key={sector} className="bg-slate-700/50 text-slate-300 text-xs">
                  {sector}: {pct?.toFixed(1)}%
                </Badge>
              ))}
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

// ── Section 5: AI Performance ─────────────────────────────────────────────────

function AiPerformancePanel() {
  const { data, isLoading } = useQuery<any>({
    queryKey: ["phase4a", "ai-metrics"],
    queryFn: () => apiJson("/phase4a/ai-metrics"),
    staleTime: 2 * 60_000,
    refetchInterval: 2 * 60_000,
  });

  const m = data ?? {};
  const total = m.total_recommendations ?? 0;

  return (
    <Card className="bg-[#0d1829] border-slate-700">
      <CardHeader className="pb-3">
        <div className="flex items-center gap-2">
          <Brain className="h-5 w-5 text-teal-400" />
          <CardTitle className="text-slate-100 text-base">AI Performance</CardTitle>
          <Badge className="bg-amber-600/20 text-amber-400 border-amber-600/30 text-[10px]">
            Advisory Only
          </Badge>
        </div>
      </CardHeader>
      <CardContent>
        {isLoading ? (
          <div className="text-slate-500 text-sm">Computing AI metrics…</div>
        ) : (
          <>
            {/* Recommendation breakdown */}
            {total > 0 && (
              <div className="mb-4">
                <p className="text-xs text-slate-500 mb-2">Recommendation Split</p>
                <div className="flex h-4 rounded-full overflow-hidden gap-0.5">
                  {m.buy_count > 0 && (
                    <div
                      className="bg-emerald-500"
                      style={{ width: `${m.buy_pct}%` }}
                      title={`BUY: ${m.buy_count} (${m.buy_pct}%)`}
                    />
                  )}
                  {m.watch_count > 0 && (
                    <div
                      className="bg-amber-500"
                      style={{ width: `${m.watch_pct}%` }}
                      title={`WATCH: ${m.watch_count} (${m.watch_pct}%)`}
                    />
                  )}
                  {m.no_trade_count > 0 && (
                    <div
                      className="bg-slate-600"
                      style={{ width: `${m.no_trade_pct}%` }}
                      title={`NO_TRADE: ${m.no_trade_count} (${m.no_trade_pct}%)`}
                    />
                  )}
                </div>
                <div className="flex gap-4 text-xs mt-1">
                  <span className="text-emerald-400">BUY {m.buy_count ?? 0} ({m.buy_pct ?? 0}%)</span>
                  <span className="text-amber-400">WATCH {m.watch_count ?? 0} ({m.watch_pct ?? 0}%)</span>
                  <span className="text-slate-400">NO_TRADE {m.no_trade_count ?? 0} ({m.no_trade_pct ?? 0}%)</span>
                </div>
              </div>
            )}
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
              <MetricCard label="Avg Confidence" value={m.avg_confidence != null ? `${m.avg_confidence}%` : "—"}
                color={m.avg_confidence >= 65 ? "text-emerald-400" : m.avg_confidence >= 50 ? "text-amber-400" : "text-red-400"} />
              <MetricCard label="Agreement Rate" value={m.agreement_rate_pct != null ? `${m.agreement_rate_pct}%` : "—"}
                color={m.agreement_rate_pct >= 70 ? "text-emerald-400" : "text-amber-400"} />
              <MetricCard label="False Positives" value={m.false_positives ?? 0}
                color={(m.false_positives ?? 0) === 0 ? "text-emerald-400" : "text-red-400"} />
              <MetricCard label="False Negatives" value={m.false_negatives ?? 0}
                color={(m.false_negatives ?? 0) === 0 ? "text-emerald-400" : "text-amber-400"} />
            </div>
            {m.avg_explanation_latency_ms != null && (
              <p className="text-xs text-slate-500 mt-2">
                Avg explanation latency: {m.avg_explanation_latency_ms}ms
                {m.latency_samples > 0 ? ` (${m.latency_samples} samples)` : ""}
              </p>
            )}
          </>
        )}
      </CardContent>
    </Card>
  );
}

// ── Section 6: Session Reports ────────────────────────────────────────────────

const REPORT_TYPES = [
  { key: "daily_summary", label: "Daily Summary" },
  { key: "trade_summary", label: "Trade Summary" },
  { key: "risk_report", label: "Risk Report" },
  { key: "performance_report", label: "Performance Report" },
  { key: "system_health", label: "System Health" },
  { key: "ai_report", label: "AI Report" },
  { key: "portfolio_report", label: "Portfolio Report" },
];

function SessionReportsPanel() {
  const { toast } = useToast();
  const [generating, setGenerating] = useState(false);

  const finalReportQuery = useQuery<any>({
    queryKey: ["phase4a", "final-report"],
    queryFn: () => apiJson("/phase4a/final-report"),
    staleTime: 5 * 60_000,
    retry: false,
  });

  const generateMut = useMutation({
    mutationFn: async (type: string) => {
      const r = await fetch(buildApiUrl(`/phase4a/reports/generate?type=${type}`), { method: "POST" });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      return r.json();
    },
    onSuccess: () => toast({ title: "Reports generated" }),
    onError: (e: any) => toast({ title: "Error", description: e.message, variant: "destructive" }),
  });

  const generateFinal = useMutation({
    mutationFn: async () => {
      const r = await fetch(buildApiUrl("/phase4a/final-report"), { method: "POST" });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      return r.json();
    },
    onSuccess: () => {
      toast({ title: "Final report generated" });
      finalReportQuery.refetch();
    },
    onError: (e: any) => toast({ title: "Error", description: e.message, variant: "destructive" }),
  });

  const fr = finalReportQuery.data;
  const score = fr?.readiness_score;
  const grade = fr?.readiness_grade;
  const gradeColor =
    grade === "EXCELLENT" ? "text-emerald-400"
    : grade === "GOOD" ? "text-teal-400"
    : grade === "ACCEPTABLE" ? "text-amber-400"
    : "text-red-400";

  return (
    <Card className="bg-[#0d1829] border-slate-700">
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <FileText className="h-5 w-5 text-teal-400" />
            <CardTitle className="text-slate-100 text-base">Session Reports</CardTitle>
          </div>
          <Button
            size="sm" variant="outline"
            className="border-slate-700 text-xs gap-1"
            onClick={() => generateMut.mutate("all")}
            disabled={generateMut.isPending}
          >
            <Download className="h-3 w-3" />
            {generateMut.isPending ? "Generating…" : "Generate All"}
          </Button>
        </div>
      </CardHeader>
      <CardContent>
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4 lg:grid-cols-7 mb-4">
          {REPORT_TYPES.map((rt) => (
            <Button
              key={rt.key}
              variant="outline"
              size="sm"
              className="text-xs border-slate-700 hover:border-teal-600 h-auto py-2 flex-col gap-1"
              onClick={() => generateMut.mutate(rt.key)}
              disabled={generateMut.isPending}
            >
              <FileText className="h-3.5 w-3.5 text-teal-400" />
              <span className="truncate max-w-full">{rt.label}</span>
            </Button>
          ))}
        </div>

        <Separator className="bg-slate-700/50 my-4" />

        {/* Final Report */}
        <div className="flex items-center justify-between mb-3">
          <p className="text-sm font-medium text-slate-200">Final Report &amp; Readiness Score</p>
          <Button
            size="sm" variant="outline"
            className="border-slate-700 text-xs gap-1"
            onClick={() => generateFinal.mutate()}
            disabled={generateFinal.isPending}
          >
            <RefreshCw className="h-3 w-3" />
            {generateFinal.isPending ? "Running…" : "Generate Final"}
          </Button>
        </div>

        {fr ? (
          <div className="bg-slate-800/40 rounded-lg p-4 border border-slate-700/50">
            <div className="flex items-center gap-4 mb-3">
              <div>
                <p className="text-xs text-slate-500">Readiness Score</p>
                <p className={`text-4xl font-bold ${gradeColor}`}>{score}</p>
              </div>
              <div>
                <p className="text-xs text-slate-500">Grade</p>
                <p className={`text-lg font-semibold ${gradeColor}`}>{grade}</p>
              </div>
              <div className="ml-auto grid grid-cols-2 gap-2 text-xs">
                {Object.entries(fr.component_scores ?? {}).map(([k, v]: [string, any]) => (
                  <div key={k} className="text-right">
                    <span className="text-slate-500 capitalize">{k}:</span>
                    <span className="text-slate-200 ml-1">{v}/100</span>
                  </div>
                ))}
              </div>
            </div>
            {fr.remaining_issues?.length > 0 && (
              <div className="mb-2">
                <p className="text-xs text-slate-500 mb-1">Issues</p>
                <ul className="text-xs text-amber-400 space-y-0.5">
                  {fr.remaining_issues.slice(0, 5).map((issue: string, i: number) => (
                    <li key={i}>• {issue}</li>
                  ))}
                </ul>
              </div>
            )}
            {fr.recommendations?.length > 0 && (
              <div>
                <p className="text-xs text-slate-500 mb-1">Recommendations</p>
                <ul className="text-xs text-slate-300 space-y-0.5">
                  {fr.recommendations.map((rec: string, i: number) => (
                    <li key={i}>→ {rec}</li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        ) : (
          <div className="text-slate-500 text-sm">
            No final report yet. Click "Generate Final" to compute the readiness score.
          </div>
        )}
      </CardContent>
    </Card>
  );
}

// ── Safety Validation Strip ───────────────────────────────────────────────────

function SafetyValidationStrip() {
  const { data, isLoading, refetch, isFetching } = useQuery<any>({
    queryKey: ["phase4a", "validate"],
    queryFn: () => apiJson("/phase4a/validate"),
    staleTime: 2 * 60_000,
    refetchInterval: 2 * 60_000,
  });

  const invariants: any[] = data?.invariants ?? [];

  return (
    <Card className="bg-[#0d1829] border-slate-700">
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Shield className="h-5 w-5 text-teal-400" />
            <CardTitle className="text-slate-100 text-base">Safety Invariants</CardTitle>
            {data && <VerdictBadge verdict={data.production_ready ? "PASS" : "FAIL"} />}
          </div>
          <Button
            size="sm" variant="ghost"
            className="text-xs gap-1 text-slate-400"
            onClick={() => refetch()}
            disabled={isFetching}
          >
            <RefreshCw className={`h-3 w-3 ${isFetching ? "animate-spin" : ""}`} />
          </Button>
        </div>
      </CardHeader>
      <CardContent>
        {isLoading ? (
          <div className="text-slate-500 text-sm">Checking safety invariants…</div>
        ) : invariants.length === 0 ? (
          <div className="text-slate-500 text-sm">No validation data. Checking…</div>
        ) : (
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
            {invariants.map((inv: any, i: number) => (
              <div
                key={i}
                className={`rounded-lg p-2 text-xs border ${
                  inv.verdict === "PASS"
                    ? "bg-emerald-950/30 border-emerald-700/30"
                    : inv.verdict === "WARN"
                    ? "bg-amber-950/30 border-amber-700/30"
                    : "bg-red-950/30 border-red-700/30"
                }`}
              >
                <div className="flex items-center gap-1 mb-0.5">
                  {inv.verdict === "PASS" ? (
                    <CheckCircle className="h-3 w-3 text-emerald-400 shrink-0" />
                  ) : inv.verdict === "WARN" ? (
                    <AlertTriangle className="h-3 w-3 text-amber-400 shrink-0" />
                  ) : (
                    <XCircle className="h-3 w-3 text-red-400 shrink-0" />
                  )}
                  <span className={`font-medium truncate ${
                    inv.verdict === "PASS" ? "text-emerald-300"
                    : inv.verdict === "WARN" ? "text-amber-300"
                    : "text-red-300"
                  }`}>{inv.invariant}</span>
                </div>
                {inv.detail && (
                  <p className="text-[10px] text-slate-500 truncate" title={inv.detail}>
                    {inv.detail}
                  </p>
                )}
              </div>
            ))}
          </div>
        )}
        {data && (
          <div className="mt-2 text-xs text-slate-500 flex gap-4">
            <span className="text-emerald-400">✓ {data.passed} PASS</span>
            <span className="text-amber-400">⚠ {data.warned} WARN</span>
            <span className="text-red-400">✗ {data.failed} FAIL</span>
            <span className="ml-auto">{data.total_checked}/{data.total_invariants} checked</span>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

// ── Operations Dashboard (scanner / market data / risk / positions / pending /
//    previous session tiles + pipeline summary) — GET /phase4a/dashboard ───────

function useOpsDashboard() {
  return useQuery<any>({
    queryKey: ["phase4a", "dashboard"],
    queryFn: () => apiJson("/phase4a/dashboard"),
    refetchInterval: 60_000,
    staleTime: 55_000,
  });
}

function TileRow({ label, value, cls }: { label: string; value: any; cls?: string }) {
  const display = value === null || value === undefined || value === "" ? "—" : String(value);
  return (
    <div className="flex justify-between gap-2 text-xs py-0.5">
      <span className="text-slate-500">{label}</span>
      <span className={`font-mono text-right ${cls ?? "text-slate-200"}`}>{display}</span>
    </div>
  );
}

function Tile({ title, icon, children }: { title: string; icon?: React.ReactNode; children: React.ReactNode }) {
  return (
    <Card className="bg-[#0d1829] border-slate-700">
      <CardHeader className="py-2.5">
        <CardTitle className="text-slate-200 text-sm flex items-center gap-2">
          {icon} {title}
        </CardTitle>
      </CardHeader>
      <CardContent className="pb-3">{children}</CardContent>
    </Card>
  );
}

function fmtAge(s: number) {
  return s < 120 ? `${Math.round(s)}s` : `${Math.round(s / 60)}m`;
}

function OperationsDashboard() {
  const { data, isLoading, error } = useOpsDashboard();
  if (isLoading) {
    return <div className="text-slate-500 text-sm p-2">Loading operations dashboard…</div>;
  }
  if (error || !data) {
    return (
      <div className="text-red-400 text-sm p-2 border border-red-800/40 rounded bg-red-950/20">
        Operations dashboard failed to load: {(error as any)?.message ?? "no data"}
      </div>
    );
  }
  const sc = data.scanner ?? {};
  const md = data.market_data ?? {};
  const re = data.risk_engine ?? {};
  const op = data.open_positions ?? {};
  const pt = data.pending_trades ?? {};
  const ps = data.previous_session ?? {};
  const dd = data.decision_distribution ?? {};
  const pipeline: any[] = data.pipeline ?? [];
  const rupee = (v: any) => (v === null || v === undefined ? "—" : `₹${Number(v).toFixed(0)}`);

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
        <Tile title="Scanner" icon={<Zap className="h-4 w-4 text-teal-400" />}>
          <TileRow label="Universe Source" value={sc.universe_source} />
          <TileRow label="Symbols Loaded" value={sc.symbols_loaded} />
          <TileRow label="Symbols Scanned" value={sc.symbols_scanned} />
          <TileRow label="Symbols Passed" value={sc.symbols_passed} cls="text-emerald-400" />
          <TileRow label="Symbols Rejected" value={sc.symbols_rejected} cls="text-amber-400" />
          <TileRow label="Scan Duration" value={sc.scan_duration_s != null ? `${sc.scan_duration_s}s` : null} />
          <TileRow label="Scan Timestamp" value={sc.scan_timestamp} />
          <TileRow label="Data Freshness" value={sc.data_freshness_s != null ? `${Math.round(sc.data_freshness_s / 60)}m ago` : null}
            cls={sc.data_freshness_s != null && sc.data_freshness_s < 3600 ? "text-emerald-400" : "text-amber-400"} />
        </Tile>

        <Tile title="Market Data" icon={<Activity className="h-4 w-4 text-teal-400" />}>
          <TileRow label="Zerodha Status" value={md.zerodha_status}
            cls={md.zerodha_status === "CONNECTED" ? "text-emerald-400" : "text-amber-400"} />
          <TileRow label="Yahoo Status" value={md.yahoo_status}
            cls={md.yahoo_status === "OK" ? "text-emerald-400" : "text-amber-400"} />
          <TileRow label="NSE Status" value={md.nse_status} />
          <TileRow label="Missing Symbols" value={md.missing_symbols}
            cls={md.missing_symbols ? "text-amber-400" : "text-emerald-400"} />
          <TileRow label="Failed Requests" value={md.failed_requests}
            cls={md.failed_requests ? "text-amber-400" : "text-emerald-400"} />
          <TileRow label="Last Tick Age" value={md.last_tick_age_s != null ? `${Math.round(md.last_tick_age_s / 60)}m` : null} />
          <TileRow label="Data Latency" value={md.data_latency_ms != null ? `${Math.round(md.data_latency_ms)}ms avg` : null} />
          <TileRow label="Coverage" value={md.symbol_coverage_pct != null ? `${md.symbol_coverage_pct}%` : null} />
        </Tile>

        <Tile title="Risk Engine" icon={<Shield className="h-4 w-4 text-teal-400" />}>
          <TileRow label="Candidates Received" value={re.candidates_received} />
          <TileRow label="Candidates Approved" value={re.candidates_approved} cls="text-emerald-400" />
          <TileRow label="Candidates Rejected" value={re.candidates_rejected} cls="text-amber-400" />
          <TileRow label="Top Rejection Reason" value={re.top_rejection_reason} />
          <TileRow label="Avg R:R Ratio" value={re.avg_rr_ratio} />
          <TileRow label="Avg Opportunity Score" value={re.avg_opportunity_score} />
          <TileRow label="Risk Processing Time" value={re.processing_time_s != null ? `${re.processing_time_s}s` : null} />
        </Tile>

        <Tile title="Open Positions" icon={<BookOpen className="h-4 w-4 text-teal-400" />}>
          <TileRow label="Open Positions" value={op.count} />
          <TileRow label="Exposure" value={rupee(op.exposure)} />
          <TileRow label="Capital Used" value={op.capital_used_pct != null ? `${op.capital_used_pct}%` : null} />
          <TileRow label="Largest Position" value={op.largest_position} />
          <TileRow label="Unrealized P&L" value={op.unrealized_pnl != null ? `₹${Number(op.unrealized_pnl).toFixed(2)}` : op.unrealized_note}
            cls={op.unrealized_pnl != null ? (op.unrealized_pnl >= 0 ? "text-emerald-400" : "text-red-400") : "text-amber-400"} />
          {op.sector_exposure && Object.keys(op.sector_exposure).length > 0 && (
            <div className="mt-1 pt-1 border-t border-slate-800">
              <div className="text-[10px] text-slate-500 uppercase mb-0.5">Sector Exposure</div>
              {Object.entries(op.sector_exposure).map(([k, v]: any) => (
                <TileRow key={k} label={k} value={rupee(v)} />
              ))}
            </div>
          )}
          {op.mark_source && (
            <div className={`text-[10px] mt-1 ${op.mark_stale ? "text-amber-400" : "text-slate-600"}`}>
              marks: {op.mark_source}
              {op.live_mark_age_s != null && op.scan_mark_age_s != null && op.mark_source?.includes("+") ? (
                <> · live {fmtAge(op.live_mark_age_s)} / scan {fmtAge(op.scan_mark_age_s)} old</>
              ) : op.mark_age_s != null ? (
                <> · {fmtAge(op.mark_age_s)} old</>
              ) : null}
              {op.mark_stale && <> · STALE</>}
            </div>
          )}
          {op.mark_note && <div className="text-[10px] text-amber-400/80 mt-0.5">{op.mark_note}</div>}
        </Tile>

        <Tile title="Pending Trades" icon={<Clock className="h-4 w-4 text-teal-400" />}>
          <TileRow label="BUY Pending" value={pt.buy_pending} cls={pt.buy_pending ? "text-sky-400" : undefined} />
          <TileRow label="SELL Pending" value={pt.sell_pending} cls={pt.sell_pending ? "text-amber-400" : undefined} />
          <TileRow label="Cancelled" value={pt.cancelled} />
          <TileRow label="Expired" value={pt.expired} />
          <TileRow label="Rejected" value={pt.rejected} cls={pt.rejected ? "text-red-400" : undefined} />
          {pt.buy_pending_note && <div className="text-[10px] text-slate-600 mt-1">{pt.buy_pending_note}</div>}
          {(pt.rejected_detail ?? []).slice(0, 3).map((b: any) => (
            <div key={b.symbol} className="text-[10px] text-red-400/80 mt-0.5">
              {b.symbol}: {(b.reasons ?? []).join(", ")}
            </div>
          ))}
        </Tile>

        <Tile title="Previous Session" icon={<BarChart2 className="h-4 w-4 text-teal-400" />}>
          <TileRow label="Yesterday" value={ps.date ?? ps.note} />
          <TileRow label="Trades" value={ps.trades} />
          <TileRow label="Win Rate" value={ps.win_rate_pct != null ? `${ps.win_rate_pct}%` : ps.exits === 0 ? "no exits" : null} />
          <TileRow label="Net P&L" value={ps.net_pnl != null ? `₹${Number(ps.net_pnl).toFixed(2)}` : null}
            cls={ps.net_pnl > 0 ? "text-emerald-400" : ps.net_pnl < 0 ? "text-red-400" : undefined} />
          <TileRow label="Largest Winner" value={ps.largest_winner != null ? `₹${ps.largest_winner}` : "none closed"} />
          <TileRow label="Largest Loser" value={ps.largest_loser != null ? `₹${ps.largest_loser}` : "none closed"} />
          <TileRow label="Average Hold Time" value={ps.avg_hold_minutes != null ? `${ps.avg_hold_minutes}m` : "no exits"} />
        </Tile>
      </div>

      {/* Decision distribution */}
      <Card className="bg-[#0d1829] border-slate-700">
        <CardHeader className="py-2.5">
          <CardTitle className="text-slate-200 text-sm flex items-center gap-2">
            <Brain className="h-4 w-4 text-violet-400" /> Decision Distribution — scan {data.scan_id}
          </CardTitle>
        </CardHeader>
        <CardContent className="pb-3">
          <div className="grid grid-cols-5 gap-2">
            <MetricCard label="BUY" value={dd.buy} color="text-emerald-400" />
            <MetricCard label="WATCH" value={dd.watch} color="text-sky-400" />
            <MetricCard label="SELL" value={dd.sell} color="text-amber-400" />
            <MetricCard label="AVOID" value={dd.avoid} color="text-red-400" />
            <MetricCard label="TOTAL" value={dd.total} color="text-slate-200" />
          </div>
          {dd.sell_note && <div className="text-[10px] text-slate-600 mt-1">SELL = {dd.sell_note}</div>}
        </CardContent>
      </Card>

      {/* Pipeline summary */}
      <Card className="bg-[#0d1829] border-slate-700">
        <CardHeader className="py-2.5">
          <CardTitle className="text-slate-200 text-sm flex items-center gap-2">
            <Zap className="h-4 w-4 text-teal-400" /> Pipeline Summary
          </CardTitle>
        </CardHeader>
        <CardContent className="pb-3 overflow-x-auto">
          {pipeline.length === 0 ? (
            <div className="text-slate-500 text-xs">No replay snapshot available for the current scan.</div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow className="border-slate-800">
                  <TableHead className="text-slate-400 text-xs">Stage</TableHead>
                  <TableHead className="text-slate-400 text-xs text-right">Input</TableHead>
                  <TableHead className="text-slate-400 text-xs text-right">Passed</TableHead>
                  <TableHead className="text-slate-400 text-xs text-right">Rejected</TableHead>
                  <TableHead className="text-slate-400 text-xs text-right">Pending</TableHead>
                  <TableHead className="text-slate-400 text-xs text-right">Cancelled</TableHead>
                  <TableHead className="text-slate-400 text-xs text-right">Processing Time</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {pipeline.map((s) => (
                  <TableRow key={s.id} className="border-slate-800/60">
                    <TableCell className="text-slate-200 text-xs py-1.5">{s.label}</TableCell>
                    <TableCell className="text-right font-mono text-xs py-1.5 text-slate-300">{s.input}</TableCell>
                    <TableCell className="text-right font-mono text-xs py-1.5 text-emerald-400">{s.passed}</TableCell>
                    <TableCell className="text-right font-mono text-xs py-1.5 text-amber-400">{s.rejected}</TableCell>
                    <TableCell className="text-right font-mono text-xs py-1.5 text-slate-300">{s.pending}</TableCell>
                    <TableCell className="text-right font-mono text-xs py-1.5 text-slate-300">{s.cancelled}</TableCell>
                    <TableCell className="text-right font-mono text-xs py-1.5 text-slate-400">
                      {s.processing_time_s != null ? `${s.processing_time_s}s` : "—"}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

// ── Main Page ─────────────────────────────────────────────────────────────────

export default function Phase4ASession() {
  return (
    <div className="min-h-screen bg-[#060e1a] text-slate-100 p-4 space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-slate-100 flex items-center gap-2">
            <Zap className="h-5 w-5 text-teal-400" />
            Phase 4A — Controlled Paper Trading Operations
          </h1>
          <p className="text-xs text-amber-400 mt-0.5">⚠️ {LABEL}</p>
        </div>
        <Badge className="bg-teal-600/20 text-teal-400 border-teal-600/30">
          Paper Session Active
        </Badge>
      </div>

      {/* Section 1: Pre-Market */}
      <PreMarketStrip />

      {/* Section 7: Safety (shown near top for visibility) */}
      <SafetyValidationStrip />

      {/* Section 2: Live Monitor */}
      <MonitorPanel />

      {/* Section 2b: Operations Dashboard tiles + decision distribution + pipeline */}
      <OperationsDashboard />

      {/* Section 3: Trade Journal */}
      <TradeJournalTable />

      {/* Sections 4 & 5 side by side on large screens */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <RiskMetricsPanel />
        <AiPerformancePanel />
      </div>

      {/* Section 6: Reports */}
      <SessionReportsPanel />
    </div>
  );
}
