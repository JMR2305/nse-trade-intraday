/**
 * InstitutionalAnalytics.tsx — Phase 23 Part 7: Institutional Analytics.
 *
 * A read-only, ADVISORY dashboard over the Strategy Optimization Lab bundle
 * (/api/lab/*). Every endpoint is derived from the canonical stores; nothing
 * on this page changes live settings, base runs, or the paper ledger.
 *
 * Data sources (all advisory):
 *   GET /lab/dashboard    — Part K primary bundle (180s)
 *   GET /lab/leaderboard  — Part I strategy leaderboard (lazy)
 *   GET /lab/calibration  — Part J confidence calibration (lazy)
 *   GET /lab/monte-carlo   — Part E Monte Carlo (lazy, 180s)
 *   GET /lab/buckets      — Parts F/G/H hour/weekday/month buckets (lazy)
 *   GET /backtest/runs    — completed-run picker
 *
 * Sections show a clear amber INSUFFICIENT_EVIDENCE state whenever the API
 * verdict (or a per-row insufficient_evidence flag) says so — that state is
 * intentional, not an error.
 */
import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { apiJson } from "@/lib/api";
import { PageHeader } from "@/components/ds";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import {
  Tabs, TabsList, TabsTrigger, TabsContent,
} from "@/components/ui/tabs";
import {
  ResponsiveContainer, AreaChart, Area, BarChart, Bar, LineChart, Line,
  ScatterChart, Scatter, XAxis, YAxis, CartesianGrid, Tooltip, Legend,
  ReferenceLine, Cell,
} from "recharts";
import {
  BarChart3, AlertTriangle, TrendingUp, TrendingDown, Layers, Clock,
  Target, Trophy, Grid3x3, Percent, Dices, Activity,
} from "lucide-react";

// ── Types ─────────────────────────────────────────────────────────────────

const SLOW = 180_000;

type Verdict = "OK" | "INSUFFICIENT_EVIDENCE" | string;

interface DashSummary {
  trades: number; win_rate: number; profit_factor: number; expectancy: number;
  sharpe: number; sortino: number; max_drawdown: number; recovery_factor: number;
}
interface BucketRow {
  bucket: string; trades: number; win_rate: number; pnl: number;
  expectancy: number; best_strategy?: string | null;
  worst_strategy?: string | null; avg_hold_days?: number | null;
  insufficient_evidence: boolean;
}
interface DashboardBundle {
  ok: boolean; source: string; run_id?: string | null;
  capital?: number | null; summary: DashSummary; total_pnl: number;
  equity_curve: Array<{ ts: string; equity: number }>;
  drawdown_curve: Array<{ ts: string; drawdown_pct: number }>;
  monthly_returns: Array<{ month: string; pnl: number }>;
  rolling: Array<{ trade_index: number; sharpe: number; win_rate: number; profit_factor: number }>;
  strategy_comparison: BucketRow[];
  sector_comparison: BucketRow[];
  regime_comparison: BucketRow[];
  calibration: CalibrationBundle;
  risk_heatmap: Array<{ sector: string; cells: Array<{ regime: string; pnl: number }> }>;
  capital_utilization: Array<{ ts: string; utilization_pct: number }>;
  verdict: Verdict;
}
interface LeaderboardRow {
  strategy: string; trades: number; win_rate: number; pnl: number;
  max_drawdown_pct: number; profit_factor: number; expectancy: number;
  sharpe: number; sortino: number; recovery_factor: number;
  avg_hold_days?: number | null; confidence_accuracy?: number | null;
  capital_efficiency_pct?: number | null; insufficient_evidence: boolean;
}
interface CalibrationBundle {
  reliability_curve: Array<{
    bucket: string; trades: number; predicted_win_rate: number;
    observed_win_rate: number; calibration_error: number;
    insufficient_evidence?: boolean;
  }>;
  brier_score?: number | null;
  mean_abs_calibration_error?: number | null;
  confidence_distribution: Array<{ bucket: number; count: number }>;
  verdict: Verdict;
}
interface MonteCarloBundle {
  probability_of_profit?: number; probability_drawdown_gt_10pct?: number;
  expected_return_range_pct?: { p5: number; p50: number; p95: number };
  confidence_interval_95_pct?: number[];
  worst_expected_drawdown_pct?: number; best_expected_outcome_pct?: number;
  capital_survival_probability?: number; risk_of_ruin_pct?: number;
  return_histogram?: Array<{ bucket: number; count: number }>;
  verdict: Verdict; reason?: string;
}
interface BucketsBundle {
  hour: BucketRow[]; weekday: BucketRow[]; month: BucketRow[]; verdict: Verdict;
}
interface RunRow {
  run_id: string; status: string;
  config?: { start?: string; end?: string; interval?: string };
}

// ── Helpers ─────────────────────────────────────────────────────────────────

function inr(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  const s = v < 0 ? "-" : "";
  return `${s}₹${Math.abs(v).toLocaleString("en-IN", { maximumFractionDigits: 2 })}`;
}
function num(v: number | null | undefined, dec = 2): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  return v.toFixed(dec);
}
function pctStr(v: number | null | undefined, dec = 1): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  return `${v.toFixed(dec)}%`;
}
function pnlColor(v: number): string {
  if (v > 0) return "text-emerald-400";
  if (v < 0) return "text-red-400";
  return "text-muted-foreground";
}
function shortTs(ts: string | null | undefined): string {
  if (!ts) return "";
  const s = String(ts);
  return s.length >= 10 ? s.slice(0, 10) : s;
}
function isInsufficient(v?: Verdict): boolean {
  return v === "INSUFFICIENT_EVIDENCE";
}

const CHART_MARGIN = { top: 8, right: 12, left: 0, bottom: 4 };

// ── Reusable amber "insufficient evidence" panel ─────────────────────────────

function InsufficientEvidence({ reason, compact }: { reason?: string; compact?: boolean }) {
  return (
    <div
      className="flex items-start gap-3 rounded-md border border-amber-500/40 bg-amber-500/10 px-4 py-3 text-amber-300"
      data-testid="insufficient-evidence"
    >
      <AlertTriangle className="mt-0.5 h-4 w-4 flex-shrink-0" />
      <div className={compact ? "text-xs" : "text-sm"}>
        <div className="font-medium">Insufficient evidence</div>
        <div className="text-amber-300/80">
          {reason ||
            "Not enough completed trades to compute this analytic reliably. This is expected for very small runs — it is not an error."}
        </div>
      </div>
    </div>
  );
}

function InsufficientBadge() {
  return (
    <Badge
      variant="outline"
      className="border-amber-500/50 bg-amber-500/10 text-amber-300"
    >
      INSUFFICIENT_EVIDENCE
    </Badge>
  );
}

// ── KPI strip ────────────────────────────────────────────────────────────────

function Kpi({ label, value, tone }: { label: string; value: string; tone?: string }) {
  return (
    <div className="rounded-lg border border-border bg-card px-4 py-3">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className={`mt-1 text-lg font-semibold ${tone || "text-foreground"}`}>{value}</div>
    </div>
  );
}

// ── Heatmap cell colour by pnl intensity ─────────────────────────────────────

function heatStyle(pnl: number, max: number): React.CSSProperties {
  if (max <= 0 || pnl === 0) return {};
  const intensity = Math.min(1, Math.abs(pnl) / max);
  const alpha = 0.12 + intensity * 0.55;
  const color = pnl > 0 ? `rgba(16,185,129,${alpha})` : `rgba(239,68,68,${alpha})`;
  return { backgroundColor: color };
}

// ── Page ─────────────────────────────────────────────────────────────────────

export default function InstitutionalAnalytics() {
  const [source, setSource] = useState<"paper" | "backtest">("paper");
  const [runId, setRunId] = useState<string>("");

  const isBacktest = source === "backtest";
  const query = useMemo(() => {
    const p = new URLSearchParams();
    p.set("source", source);
    if (isBacktest && runId) p.set("run_id", runId);
    return p.toString();
  }, [source, runId, isBacktest]);

  // completed runs for the picker (only when backtest is selected)
  const runsQ = useQuery({
    queryKey: ["backtest", "runs"],
    queryFn: () =>
      apiJson<{ runs: RunRow[] }>("/backtest/runs", undefined, 30_000),
    staleTime: 60_000,
    enabled: isBacktest,
  });
  const completedRuns = (runsQ.data?.runs || []).filter((r) => r.status === "COMPLETED");

  // when backtest is selected we require a chosen run before firing data queries
  const ready = !isBacktest || !!runId;

  const dashQ = useQuery({
    queryKey: ["lab", "dashboard", source, runId],
    queryFn: () =>
      apiJson<DashboardBundle>(`/lab/dashboard?${query}`, undefined, SLOW),
    staleTime: 60_000,
    enabled: ready,
  });

  const leaderQ = useQuery({
    queryKey: ["lab", "leaderboard", source, runId],
    queryFn: () =>
      apiJson<{ rows: LeaderboardRow[] }>(`/lab/leaderboard?${query}`, undefined, SLOW),
    staleTime: 60_000,
    enabled: ready,
  });

  const calibQ = useQuery({
    queryKey: ["lab", "calibration", source, runId],
    queryFn: () =>
      apiJson<CalibrationBundle>(`/lab/calibration?${query}`, undefined, SLOW),
    staleTime: 60_000,
    enabled: ready,
  });

  const mcQ = useQuery({
    queryKey: ["lab", "monte-carlo", source, runId],
    queryFn: () =>
      apiJson<MonteCarloBundle>(`/lab/monte-carlo?${query}`, undefined, SLOW),
    staleTime: 60_000,
    enabled: ready,
  });

  const bucketsQ = useQuery({
    queryKey: ["lab", "buckets", source, runId],
    queryFn: () =>
      apiJson<BucketsBundle>(`/lab/buckets?${query}`, undefined, SLOW),
    staleTime: 60_000,
    enabled: ready,
  });

  const d = dashQ.data;
  const dashInsufficient = isInsufficient(d?.verdict);

  return (
    <div className="space-y-5 p-1" data-testid="page-institutional-analytics">
      <PageHeader
        title="Institutional Analytics"
        subtitle="Advisory only — nothing is changed automatically. Read-only analytics over the Strategy Lab bundle."
        icon={BarChart3}
        agentId="operations"
        agentName="Operations"
        advisory
        readOnly
      />

      {/* ── Top controls ── */}
      <Card data-testid="analytics-controls">
        <CardContent className="flex flex-wrap items-center gap-4 pt-6">
          <div className="flex items-center gap-2">
            <span className="text-xs uppercase tracking-wide text-muted-foreground">Source</span>
            <div className="flex overflow-hidden rounded-md border border-border">
              <Button
                variant={source === "paper" ? "default" : "ghost"}
                size="sm"
                className="rounded-none"
                onClick={() => setSource("paper")}
                data-testid="source-paper"
              >
                Paper Trading
              </Button>
              <Button
                variant={source === "backtest" ? "default" : "ghost"}
                size="sm"
                className="rounded-none"
                onClick={() => setSource("backtest")}
                data-testid="source-backtest"
              >
                Backtest Run
              </Button>
            </div>
          </div>

          {isBacktest && (
            <div className="flex items-center gap-2">
              <span className="text-xs uppercase tracking-wide text-muted-foreground">Run</span>
              <select
                className="rounded-md border border-border bg-background px-3 py-1.5 text-sm text-foreground"
                value={runId}
                onChange={(e) => setRunId(e.target.value)}
                data-testid="run-select"
              >
                <option value="">
                  {runsQ.isLoading ? "Loading runs…" : "Select a completed run…"}
                </option>
                {completedRuns.map((r) => (
                  <option key={r.run_id} value={r.run_id}>
                    {r.run_id} · {shortTs(r.config?.start)}→{shortTs(r.config?.end)} · {r.config?.interval || ""}
                  </option>
                ))}
              </select>
              {isBacktest && !runsQ.isLoading && completedRuns.length === 0 && (
                <span className="text-xs text-amber-300">No completed runs available.</span>
              )}
            </div>
          )}

          <a
            className="ml-auto text-xs text-muted-foreground underline underline-offset-2 hover:text-foreground"
            href={`/api/lab/export?${query}&fmt=markdown`}
            data-testid="export-link"
          >
            Export report (markdown)
          </a>
        </CardContent>
      </Card>

      {isBacktest && !runId && (
        <Card>
          <CardContent className="pt-6">
            <div className="text-sm text-muted-foreground">
              Select a completed backtest run above to load its analytics.
            </div>
          </CardContent>
        </Card>
      )}

      {ready && dashQ.isError && (
        <Card>
          <CardContent className="pt-6">
            <div className="flex items-center gap-2 text-sm text-red-400">
              <AlertTriangle className="h-4 w-4" />
              Failed to load dashboard: {(dashQ.error as Error)?.message || "unknown error"}
            </div>
          </CardContent>
        </Card>
      )}

      {ready && dashQ.isLoading && (
        <Card>
          <CardContent className="pt-6 text-sm text-muted-foreground">Loading analytics bundle…</CardContent>
        </Card>
      )}

      {ready && d && (
        <>
          {/* ── 1. KPI strip ── */}
          <Card data-testid="kpi-strip">
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-base">
                <Target className="h-4 w-4" /> Key Metrics
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              {dashInsufficient && <InsufficientEvidence />}
              <div className="grid grid-cols-2 gap-3 md:grid-cols-3 lg:grid-cols-5">
                <Kpi label="Trades" value={String(d.summary.trades)} />
                <Kpi label="Win Rate" value={pctStr(d.summary.win_rate)} />
                <Kpi label="Total PnL" value={inr(d.total_pnl)} tone={pnlColor(d.total_pnl)} />
                <Kpi label="Profit Factor" value={num(d.summary.profit_factor)} />
                <Kpi label="Expectancy" value={num(d.summary.expectancy)} />
                <Kpi label="Sharpe" value={num(d.summary.sharpe)} />
                <Kpi label="Sortino" value={num(d.summary.sortino)} />
                <Kpi label="Max Drawdown" value={pctStr(d.summary.max_drawdown)} tone="text-red-400" />
                <Kpi label="Recovery Factor" value={num(d.summary.recovery_factor)} />
              </div>
            </CardContent>
          </Card>

          {/* ── 2. Equity + Drawdown curves ── */}
          <div className="grid gap-5 lg:grid-cols-2">
            <Card data-testid="equity-curve">
              <CardHeader>
                <CardTitle className="flex items-center gap-2 text-base">
                  <TrendingUp className="h-4 w-4" /> Portfolio Growth / Equity Curve
                </CardTitle>
              </CardHeader>
              <CardContent>
                {d.equity_curve.length === 0 ? (
                  <InsufficientEvidence reason="No equity curve data for this source/run." compact />
                ) : (
                  <ResponsiveContainer width="100%" height={260}>
                    <AreaChart data={d.equity_curve} margin={CHART_MARGIN}>
                      <defs>
                        <linearGradient id="eqFill" x1="0" y1="0" x2="0" y2="1">
                          <stop offset="0%" stopColor="#10B981" stopOpacity={0.5} />
                          <stop offset="100%" stopColor="#10B981" stopOpacity={0} />
                        </linearGradient>
                      </defs>
                      <CartesianGrid strokeDasharray="3 3" stroke="#27272a" />
                      <XAxis dataKey="ts" tickFormatter={shortTs} tick={{ fontSize: 10, fill: "#71717a" }} minTickGap={40} />
                      <YAxis tick={{ fontSize: 10, fill: "#71717a" }} width={64} />
                      <Tooltip
                        contentStyle={{ background: "#18181b", border: "1px solid #27272a", fontSize: 12 }}
                        formatter={(v: number) => inr(v)}
                        labelFormatter={shortTs}
                      />
                      <Area type="monotone" dataKey="equity" stroke="#10B981" fill="url(#eqFill)" strokeWidth={2} />
                    </AreaChart>
                  </ResponsiveContainer>
                )}
              </CardContent>
            </Card>

            <Card data-testid="drawdown-curve">
              <CardHeader>
                <CardTitle className="flex items-center gap-2 text-base">
                  <TrendingDown className="h-4 w-4" /> Drawdown Curve
                </CardTitle>
              </CardHeader>
              <CardContent>
                {d.drawdown_curve.length === 0 ? (
                  <InsufficientEvidence reason="No drawdown data for this source/run." compact />
                ) : (
                  <ResponsiveContainer width="100%" height={260}>
                    <AreaChart data={d.drawdown_curve} margin={CHART_MARGIN}>
                      <defs>
                        <linearGradient id="ddFill" x1="0" y1="0" x2="0" y2="1">
                          <stop offset="0%" stopColor="#EF4444" stopOpacity={0.5} />
                          <stop offset="100%" stopColor="#EF4444" stopOpacity={0} />
                        </linearGradient>
                      </defs>
                      <CartesianGrid strokeDasharray="3 3" stroke="#27272a" />
                      <XAxis dataKey="ts" tickFormatter={shortTs} tick={{ fontSize: 10, fill: "#71717a" }} minTickGap={40} />
                      <YAxis reversed tick={{ fontSize: 10, fill: "#71717a" }} width={48} tickFormatter={(v) => `${v}%`} />
                      <Tooltip
                        contentStyle={{ background: "#18181b", border: "1px solid #27272a", fontSize: 12 }}
                        formatter={(v: number) => pctStr(v)}
                        labelFormatter={shortTs}
                      />
                      <Area type="monotone" dataKey="drawdown_pct" stroke="#EF4444" fill="url(#ddFill)" strokeWidth={2} />
                    </AreaChart>
                  </ResponsiveContainer>
                )}
              </CardContent>
            </Card>
          </div>

          {/* ── 3. Monthly returns ── */}
          <Card data-testid="monthly-returns">
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-base">
                <BarChart3 className="h-4 w-4" /> Monthly Returns
              </CardTitle>
            </CardHeader>
            <CardContent>
              {d.monthly_returns.length === 0 ? (
                <InsufficientEvidence reason="No monthly return data yet." compact />
              ) : (
                <ResponsiveContainer width="100%" height={240}>
                  <BarChart data={d.monthly_returns} margin={CHART_MARGIN}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#27272a" />
                    <XAxis dataKey="month" tick={{ fontSize: 10, fill: "#71717a" }} />
                    <YAxis tick={{ fontSize: 10, fill: "#71717a" }} width={64} />
                    <Tooltip
                      contentStyle={{ background: "#18181b", border: "1px solid #27272a", fontSize: 12 }}
                      formatter={(v: number) => inr(v)}
                    />
                    <ReferenceLine y={0} stroke="#52525b" />
                    <Bar dataKey="pnl">
                      {d.monthly_returns.map((m, i) => (
                        <Cell key={i} fill={m.pnl >= 0 ? "#10B981" : "#EF4444"} />
                      ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              )}
            </CardContent>
          </Card>

          {/* ── 4. Rolling metrics ── */}
          <RollingMetrics rolling={d.rolling} />

          {/* ── 5. Strategy leaderboard ── */}
          <Leaderboard
            loading={leaderQ.isLoading}
            error={leaderQ.error as Error | null}
            rows={leaderQ.data?.rows}
          />

          {/* ── 6. Regime / Sector / Time analysis ── */}
          <div className="grid gap-5 lg:grid-cols-2">
            <BucketTable
              title="Regime Analysis"
              icon={<Activity className="h-4 w-4" />}
              rows={d.regime_comparison}
              testid="regime-analysis"
            />
            <BucketTable
              title="Sector Analysis"
              icon={<Layers className="h-4 w-4" />}
              rows={d.sector_comparison}
              testid="sector-analysis"
            />
          </div>

          <TimeAnalysis
            loading={bucketsQ.isLoading}
            error={bucketsQ.error as Error | null}
            data={bucketsQ.data}
          />

          {/* ── 7. Confidence calibration ── */}
          <Calibration
            loading={calibQ.isLoading}
            error={calibQ.error as Error | null}
            data={calibQ.data ?? d.calibration}
          />

          {/* ── 8. Risk heatmap ── */}
          <RiskHeatmap heatmap={d.risk_heatmap} />

          {/* ── 9. Capital utilization ── */}
          <Card data-testid="capital-utilization">
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-base">
                <Percent className="h-4 w-4" /> Capital Utilization
              </CardTitle>
            </CardHeader>
            <CardContent>
              {d.capital_utilization.length === 0 ? (
                <InsufficientEvidence reason="No capital utilization data (requires known starting capital and closed trades)." compact />
              ) : (
                <ResponsiveContainer width="100%" height={240}>
                  <AreaChart data={d.capital_utilization} margin={CHART_MARGIN}>
                    <defs>
                      <linearGradient id="utilFill" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="0%" stopColor="#6366F1" stopOpacity={0.5} />
                        <stop offset="100%" stopColor="#6366F1" stopOpacity={0} />
                      </linearGradient>
                    </defs>
                    <CartesianGrid strokeDasharray="3 3" stroke="#27272a" />
                    <XAxis dataKey="ts" tickFormatter={shortTs} tick={{ fontSize: 10, fill: "#71717a" }} minTickGap={40} />
                    <YAxis tick={{ fontSize: 10, fill: "#71717a" }} width={48} tickFormatter={(v) => `${v}%`} />
                    <Tooltip
                      contentStyle={{ background: "#18181b", border: "1px solid #27272a", fontSize: 12 }}
                      formatter={(v: number) => pctStr(v)}
                      labelFormatter={shortTs}
                    />
                    <Area type="monotone" dataKey="utilization_pct" stroke="#6366F1" fill="url(#utilFill)" strokeWidth={2} />
                  </AreaChart>
                </ResponsiveContainer>
              )}
            </CardContent>
          </Card>

          {/* ── 10. Monte Carlo ── */}
          <MonteCarlo
            loading={mcQ.isLoading}
            error={mcQ.error as Error | null}
            data={mcQ.data}
          />
        </>
      )}
    </div>
  );
}

// ── 4. Rolling metrics (toggleable series) ───────────────────────────────────

function RollingMetrics({ rolling }: { rolling: DashboardBundle["rolling"] }) {
  const [series, setSeries] = useState<{ sharpe: boolean; win_rate: boolean; profit_factor: boolean }>({
    sharpe: true, win_rate: true, profit_factor: true,
  });
  const toggle = (k: keyof typeof series) => setSeries((s) => ({ ...s, [k]: !s[k] }));

  return (
    <Card data-testid="rolling-metrics">
      <CardHeader>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <CardTitle className="flex items-center gap-2 text-base">
            <Activity className="h-4 w-4" /> Rolling Metrics (10-trade window)
          </CardTitle>
          <div className="flex gap-2">
            {([
              ["sharpe", "Sharpe", "#3B82F6"],
              ["win_rate", "Win Rate", "#10B981"],
              ["profit_factor", "Profit Factor", "#F59E0B"],
            ] as const).map(([k, label, color]) => (
              <button
                key={k}
                onClick={() => toggle(k)}
                className={`rounded border px-2 py-1 text-xs transition ${
                  series[k]
                    ? "border-transparent text-white"
                    : "border-border text-muted-foreground opacity-50"
                }`}
                style={series[k] ? { backgroundColor: color } : undefined}
                data-testid={`rolling-toggle-${k}`}
              >
                {label}
              </button>
            ))}
          </div>
        </div>
      </CardHeader>
      <CardContent>
        {rolling.length === 0 ? (
          <InsufficientEvidence reason="Rolling metrics need at least a full 10-trade window." compact />
        ) : (
          <ResponsiveContainer width="100%" height={260}>
            <LineChart data={rolling} margin={CHART_MARGIN}>
              <CartesianGrid strokeDasharray="3 3" stroke="#27272a" />
              <XAxis dataKey="trade_index" tick={{ fontSize: 10, fill: "#71717a" }} />
              <YAxis tick={{ fontSize: 10, fill: "#71717a" }} width={48} />
              <Tooltip contentStyle={{ background: "#18181b", border: "1px solid #27272a", fontSize: 12 }} />
              <Legend wrapperStyle={{ fontSize: 12 }} />
              {series.sharpe && <Line type="monotone" dataKey="sharpe" stroke="#3B82F6" dot={false} strokeWidth={2} />}
              {series.win_rate && <Line type="monotone" dataKey="win_rate" stroke="#10B981" dot={false} strokeWidth={2} />}
              {series.profit_factor && <Line type="monotone" dataKey="profit_factor" stroke="#F59E0B" dot={false} strokeWidth={2} />}
            </LineChart>
          </ResponsiveContainer>
        )}
      </CardContent>
    </Card>
  );
}

// ── 5. Strategy leaderboard ──────────────────────────────────────────────────

function Leaderboard({
  loading, error, rows,
}: { loading: boolean; error: Error | null; rows?: LeaderboardRow[] }) {
  return (
    <Card data-testid="strategy-leaderboard">
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <Trophy className="h-4 w-4" /> Strategy Leaderboard
        </CardTitle>
      </CardHeader>
      <CardContent>
        {loading && <div className="text-sm text-muted-foreground">Loading leaderboard…</div>}
        {error && <div className="text-sm text-red-400">Failed to load leaderboard: {error.message}</div>}
        {!loading && !error && (!rows || rows.length === 0) && (
          <InsufficientEvidence reason="No strategies with closed trades." compact />
        )}
        {!loading && !error && rows && rows.length > 0 && (
          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="w-10">#</TableHead>
                  <TableHead>Strategy</TableHead>
                  <TableHead className="text-right">Trades</TableHead>
                  <TableHead className="text-right">Win %</TableHead>
                  <TableHead className="text-right">PnL</TableHead>
                  <TableHead className="text-right">Max DD %</TableHead>
                  <TableHead className="text-right">PF</TableHead>
                  <TableHead className="text-right">Expectancy</TableHead>
                  <TableHead className="text-right">Sharpe</TableHead>
                  <TableHead className="text-right">Sortino</TableHead>
                  <TableHead className="text-right">Recovery</TableHead>
                  <TableHead className="text-right">Avg Hold</TableHead>
                  <TableHead className="text-right">Conf. Acc.</TableHead>
                  <TableHead className="text-right">Cap. Eff. %</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {rows.map((r, i) => (
                  <TableRow key={r.strategy} className={r.insufficient_evidence ? "opacity-50" : ""}>
                    <TableCell className="text-muted-foreground">{i + 1}</TableCell>
                    <TableCell className="font-medium">
                      <div className="flex items-center gap-2">
                        {r.strategy}
                        {r.insufficient_evidence && <InsufficientBadge />}
                      </div>
                    </TableCell>
                    <TableCell className="text-right">{r.trades}</TableCell>
                    <TableCell className="text-right">{pctStr(r.win_rate)}</TableCell>
                    <TableCell className={`text-right ${pnlColor(r.pnl)}`}>{inr(r.pnl)}</TableCell>
                    <TableCell className="text-right text-red-400">{pctStr(r.max_drawdown_pct)}</TableCell>
                    <TableCell className="text-right">{num(r.profit_factor)}</TableCell>
                    <TableCell className="text-right">{num(r.expectancy)}</TableCell>
                    <TableCell className="text-right">{num(r.sharpe)}</TableCell>
                    <TableCell className="text-right">{num(r.sortino)}</TableCell>
                    <TableCell className="text-right">{num(r.recovery_factor)}</TableCell>
                    <TableCell className="text-right">{num(r.avg_hold_days, 1)}</TableCell>
                    <TableCell className="text-right">{num(r.confidence_accuracy, 1)}</TableCell>
                    <TableCell className="text-right">{pctStr(r.capital_efficiency_pct, 2)}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

// ── 6. Bucket table (regime / sector) ────────────────────────────────────────

function BucketTable({
  title, icon, rows, testid,
}: { title: string; icon: React.ReactNode; rows: BucketRow[]; testid: string }) {
  return (
    <Card data-testid={testid}>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">{icon} {title}</CardTitle>
      </CardHeader>
      <CardContent>
        {rows.length === 0 ? (
          <InsufficientEvidence reason="No bucketed trades yet." compact />
        ) : (
          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Bucket</TableHead>
                  <TableHead className="text-right">Trades</TableHead>
                  <TableHead className="text-right">Win %</TableHead>
                  <TableHead className="text-right">PnL</TableHead>
                  <TableHead>Best</TableHead>
                  <TableHead>Worst</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {rows.map((r) => (
                  <TableRow key={r.bucket} className={r.insufficient_evidence ? "opacity-50" : ""}>
                    <TableCell className="font-medium">
                      <div className="flex items-center gap-2">
                        {r.bucket}
                        {r.insufficient_evidence && <InsufficientBadge />}
                      </div>
                    </TableCell>
                    <TableCell className="text-right">{r.trades}</TableCell>
                    <TableCell className="text-right">{pctStr(r.win_rate)}</TableCell>
                    <TableCell className={`text-right ${pnlColor(r.pnl)}`}>{inr(r.pnl)}</TableCell>
                    <TableCell className="text-emerald-400">{r.best_strategy || "—"}</TableCell>
                    <TableCell className="text-red-400">{r.worst_strategy || "—"}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

// ── 6b. Time analysis (hour / weekday / month tabs) ──────────────────────────

function TimeAnalysis({
  loading, error, data,
}: { loading: boolean; error: Error | null; data?: BucketsBundle }) {
  const rows = (arr?: BucketRow[]) => arr || [];
  const renderTab = (arr: BucketRow[]) =>
    arr.length === 0 ? (
      <InsufficientEvidence reason="No trades in this time dimension yet." compact />
    ) : (
      <div className="overflow-x-auto">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Bucket</TableHead>
              <TableHead className="text-right">Trades</TableHead>
              <TableHead className="text-right">Win %</TableHead>
              <TableHead className="text-right">PnL</TableHead>
              <TableHead className="text-right">Expectancy</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {arr.map((r) => (
              <TableRow key={r.bucket} className={r.insufficient_evidence ? "opacity-50" : ""}>
                <TableCell className="font-medium">
                  <div className="flex items-center gap-2">
                    {r.bucket}
                    {r.insufficient_evidence && <InsufficientBadge />}
                  </div>
                </TableCell>
                <TableCell className="text-right">{r.trades}</TableCell>
                <TableCell className="text-right">{pctStr(r.win_rate)}</TableCell>
                <TableCell className={`text-right ${pnlColor(r.pnl)}`}>{inr(r.pnl)}</TableCell>
                <TableCell className="text-right">{num(r.expectancy)}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
    );

  return (
    <Card data-testid="time-analysis">
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <Clock className="h-4 w-4" /> Time Analysis
        </CardTitle>
      </CardHeader>
      <CardContent>
        {loading && <div className="text-sm text-muted-foreground">Loading time buckets…</div>}
        {error && <div className="text-sm text-red-400">Failed to load buckets: {error.message}</div>}
        {!loading && !error && (
          <>
            {isInsufficient(data?.verdict) && <div className="mb-3"><InsufficientEvidence compact /></div>}
            <Tabs defaultValue="hour">
              <TabsList>
                <TabsTrigger value="hour" data-testid="time-tab-hour">Hour</TabsTrigger>
                <TabsTrigger value="weekday" data-testid="time-tab-weekday">Weekday</TabsTrigger>
                <TabsTrigger value="month" data-testid="time-tab-month">Month</TabsTrigger>
              </TabsList>
              <TabsContent value="hour">{renderTab(rows(data?.hour))}</TabsContent>
              <TabsContent value="weekday">{renderTab(rows(data?.weekday))}</TabsContent>
              <TabsContent value="month">{renderTab(rows(data?.month))}</TabsContent>
            </Tabs>
          </>
        )}
      </CardContent>
    </Card>
  );
}

// ── 7. Confidence calibration ────────────────────────────────────────────────

function Calibration({
  loading, error, data,
}: { loading: boolean; error: Error | null; data?: CalibrationBundle }) {
  const scatter = (data?.reliability_curve || []).map((r) => ({
    predicted: r.predicted_win_rate,
    observed: r.observed_win_rate,
    bucket: r.bucket,
  }));
  const insufficient = isInsufficient(data?.verdict);

  return (
    <Card data-testid="confidence-calibration">
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <Target className="h-4 w-4" /> Confidence Calibration
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        {loading && <div className="text-sm text-muted-foreground">Loading calibration…</div>}
        {error && <div className="text-sm text-red-400">Failed to load calibration: {error.message}</div>}
        {!loading && !error && data && (
          <>
            {insufficient && <InsufficientEvidence />}
            <div className="grid gap-3 sm:grid-cols-3">
              <Kpi label="Brier Score" value={num(data.brier_score, 4)} />
              <Kpi label="Mean Abs Calibration Error" value={pctStr(data.mean_abs_calibration_error, 1)} />
              <Kpi label="Buckets" value={String(data.reliability_curve.length)} />
            </div>

            <div className="grid gap-5 lg:grid-cols-2">
              <div>
                <div className="mb-2 text-sm font-medium">Reliability Curve</div>
                {scatter.length === 0 ? (
                  <InsufficientEvidence reason="No confidence buckets available." compact />
                ) : (
                  <ResponsiveContainer width="100%" height={240}>
                    <ScatterChart margin={CHART_MARGIN}>
                      <CartesianGrid strokeDasharray="3 3" stroke="#27272a" />
                      <XAxis
                        type="number" dataKey="predicted" name="Predicted"
                        domain={[0, 100]} tick={{ fontSize: 10, fill: "#71717a" }}
                        tickFormatter={(v) => `${v}%`}
                      />
                      <YAxis
                        type="number" dataKey="observed" name="Observed"
                        domain={[0, 100]} tick={{ fontSize: 10, fill: "#71717a" }}
                        width={44} tickFormatter={(v) => `${v}%`}
                      />
                      <Tooltip
                        contentStyle={{ background: "#18181b", border: "1px solid #27272a", fontSize: 12 }}
                        formatter={(v: number) => pctStr(v)}
                      />
                      <ReferenceLine segment={[{ x: 0, y: 0 }, { x: 100, y: 100 }]} stroke="#52525b" strokeDasharray="4 4" />
                      <Scatter data={scatter} fill="#6366F1" />
                    </ScatterChart>
                  </ResponsiveContainer>
                )}
              </div>

              <div>
                <div className="mb-2 text-sm font-medium">Confidence Distribution</div>
                {data.confidence_distribution.length === 0 ? (
                  <InsufficientEvidence reason="No confidence distribution." compact />
                ) : (
                  <ResponsiveContainer width="100%" height={240}>
                    <BarChart data={data.confidence_distribution} margin={CHART_MARGIN}>
                      <CartesianGrid strokeDasharray="3 3" stroke="#27272a" />
                      <XAxis dataKey="bucket" tick={{ fontSize: 10, fill: "#71717a" }} />
                      <YAxis tick={{ fontSize: 10, fill: "#71717a" }} width={40} allowDecimals={false} />
                      <Tooltip contentStyle={{ background: "#18181b", border: "1px solid #27272a", fontSize: 12 }} />
                      <Bar dataKey="count" fill="#8B5CF6" />
                    </BarChart>
                  </ResponsiveContainer>
                )}
              </div>
            </div>

            {data.reliability_curve.length > 0 && (
              <div className="overflow-x-auto">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Bucket</TableHead>
                      <TableHead className="text-right">Trades</TableHead>
                      <TableHead className="text-right">Predicted</TableHead>
                      <TableHead className="text-right">Observed</TableHead>
                      <TableHead className="text-right">Calibration Error</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {data.reliability_curve.map((r) => (
                      <TableRow key={r.bucket} className={r.insufficient_evidence ? "opacity-50" : ""}>
                        <TableCell className="font-medium">
                          <div className="flex items-center gap-2">
                            {r.bucket}
                            {r.insufficient_evidence && <InsufficientBadge />}
                          </div>
                        </TableCell>
                        <TableCell className="text-right">{r.trades}</TableCell>
                        <TableCell className="text-right">{pctStr(r.predicted_win_rate)}</TableCell>
                        <TableCell className="text-right">{pctStr(r.observed_win_rate)}</TableCell>
                        <TableCell className={`text-right ${r.calibration_error >= 0 ? "text-emerald-400" : "text-red-400"}`}>
                          {r.calibration_error > 0 ? "+" : ""}{num(r.calibration_error, 1)}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
            )}
          </>
        )}
      </CardContent>
    </Card>
  );
}

// ── 8. Risk heatmap ──────────────────────────────────────────────────────────

function RiskHeatmap({ heatmap }: { heatmap: DashboardBundle["risk_heatmap"] }) {
  const regimes = useMemo(() => {
    const set = new Set<string>();
    heatmap.forEach((row) => row.cells.forEach((c) => set.add(c.regime)));
    return Array.from(set).sort();
  }, [heatmap]);

  const maxAbs = useMemo(() => {
    let m = 0;
    heatmap.forEach((row) => row.cells.forEach((c) => { m = Math.max(m, Math.abs(c.pnl)); }));
    return m;
  }, [heatmap]);

  const lookup = (sector: string, regime: string): number | null => {
    const row = heatmap.find((r) => r.sector === sector);
    const cell = row?.cells.find((c) => c.regime === regime);
    return cell ? cell.pnl : null;
  };

  return (
    <Card data-testid="risk-heatmap">
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <Grid3x3 className="h-4 w-4" /> Risk Heatmap (Sector × Regime PnL)
        </CardTitle>
      </CardHeader>
      <CardContent>
        {heatmap.length === 0 || regimes.length === 0 ? (
          <InsufficientEvidence reason="No sector × regime PnL grid available." compact />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full border-collapse text-sm">
              <thead>
                <tr>
                  <th className="px-3 py-2 text-left text-xs text-muted-foreground">Sector \ Regime</th>
                  {regimes.map((rg) => (
                    <th key={rg} className="px-3 py-2 text-right text-xs text-muted-foreground">{rg}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {heatmap.map((row) => (
                  <tr key={row.sector}>
                    <td className="px-3 py-2 font-medium">{row.sector}</td>
                    {regimes.map((rg) => {
                      const v = lookup(row.sector, rg);
                      return (
                        <td
                          key={rg}
                          className="px-3 py-2 text-right tabular-nums"
                          style={v !== null ? heatStyle(v, maxAbs) : undefined}
                        >
                          {v === null ? <span className="text-muted-foreground">—</span> : inr(v)}
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

// ── 10. Monte Carlo ──────────────────────────────────────────────────────────

function MonteCarlo({
  loading, error, data,
}: { loading: boolean; error: Error | null; data?: MonteCarloBundle }) {
  const insufficient = isInsufficient(data?.verdict);
  return (
    <Card data-testid="monte-carlo">
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <Dices className="h-4 w-4" /> Monte Carlo Simulation
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        {loading && <div className="text-sm text-muted-foreground">Loading Monte Carlo…</div>}
        {error && <div className="text-sm text-red-400">Failed to load Monte Carlo: {error.message}</div>}
        {!loading && !error && data && (
          <>
            {insufficient ? (
              <InsufficientEvidence reason={data.reason} />
            ) : (
              <>
                <div className="grid grid-cols-2 gap-3 md:grid-cols-3 lg:grid-cols-4">
                  <Kpi label="Prob. of Profit" value={pctStr(data.probability_of_profit)} tone="text-emerald-400" />
                  <Kpi label="Prob. DD > 10%" value={pctStr(data.probability_drawdown_gt_10pct)} tone="text-amber-300" />
                  <Kpi label="Median Return" value={pctStr(data.expected_return_range_pct?.p50, 2)} />
                  <Kpi label="P5 – P95 Return" value={`${num(data.expected_return_range_pct?.p5, 1)}% – ${num(data.expected_return_range_pct?.p95, 1)}%`} />
                  <Kpi label="Worst Exp. Drawdown" value={pctStr(data.worst_expected_drawdown_pct, 2)} tone="text-red-400" />
                  <Kpi label="Best Exp. Outcome" value={pctStr(data.best_expected_outcome_pct, 2)} tone="text-emerald-400" />
                  <Kpi label="Capital Survival" value={pctStr(data.capital_survival_probability)} />
                  <Kpi label="Risk of Ruin" value={pctStr(data.risk_of_ruin_pct, 2)} tone="text-red-400" />
                </div>

                <div>
                  <div className="mb-2 text-sm font-medium">Return Distribution</div>
                  {(data.return_histogram || []).length === 0 ? (
                    <InsufficientEvidence reason="No return histogram." compact />
                  ) : (
                    <ResponsiveContainer width="100%" height={240}>
                      <BarChart data={data.return_histogram} margin={CHART_MARGIN}>
                        <CartesianGrid strokeDasharray="3 3" stroke="#27272a" />
                        <XAxis dataKey="bucket" tick={{ fontSize: 10, fill: "#71717a" }} tickFormatter={(v) => `${v}%`} />
                        <YAxis tick={{ fontSize: 10, fill: "#71717a" }} width={40} allowDecimals={false} />
                        <Tooltip contentStyle={{ background: "#18181b", border: "1px solid #27272a", fontSize: 12 }} />
                        <Bar dataKey="count" fill="#3B82F6" />
                      </BarChart>
                    </ResponsiveContainer>
                  )}
                </div>
              </>
            )}
          </>
        )}
      </CardContent>
    </Card>
  );
}
