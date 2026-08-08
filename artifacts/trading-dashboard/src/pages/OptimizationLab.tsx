/**
 * OptimizationLab.tsx — Phase 23 Part 6: AI Strategy Optimization Lab.
 *
 * Every section is ADVISORY and READ-ONLY. It reads from the canonical
 * backtest store via /api/lab/* endpoints and never mutates a recorded run,
 * live settings or the learning engine. Derived simulations (what-if,
 * walk-forward, Monte-Carlo) are recomputed on demand and never persisted.
 *
 * When an endpoint returns verdict === "INSUFFICIENT_EVIDENCE" the relevant
 * analytic renders an intentional amber notice instead of an empty/broken
 * state (a run with a single closed trade is a normal, expected case).
 */

import { Fragment, useMemo, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { apiJson, API_BASE } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { PageHeader } from "@/components/ds";
import {
  AlertTriangle, BarChart3, FlaskConical, GitCompare, Layers,
  Lightbulb, Printer, Repeat, ShieldCheck, Sparkles, Download,
} from "lucide-react";
import {
  Bar, BarChart, CartesianGrid, Line, LineChart, ResponsiveContainer,
  Tooltip, XAxis, YAxis,
} from "recharts";

// ── Types (mapped to lab.ts / strategy_lab.py shapes) ────────────────────────

interface BacktestRun {
  run_id: string;
  status: string;
  config?: { start?: string; end?: string; interval?: string };
  metrics?: Record<string, unknown> | null;
}

interface RunMetricRow {
  ok?: boolean; error?: string;
  run_id: string; status?: string; period?: string; interval?: string;
  capital?: number | null; trades?: number; win_rate?: number; pnl?: number;
  net_return_pct?: number | null; sharpe?: number; sortino?: number;
  max_drawdown_pct?: number; profit_factor?: number; expectancy?: number;
  avg_hold_days?: number | null; recovery_factor?: number;
  capital_growth_pct?: number | null; max_exposure?: number;
  equity_curve?: Array<{ ts?: string; equity?: number; value?: number }>;
}

interface WhatIfResult {
  ok?: boolean; label?: string; verdict?: string; error?: string;
  trades_kept?: number; trades_dropped?: number;
  dropped?: Array<{ trade_id?: string; symbol?: string; reason?: string }>;
  pnl?: number; resimulated_exits?: boolean; resim_failures?: number;
  metrics?: {
    win_rate?: number; expectancy?: number; profit_factor?: number;
  } & Record<string, unknown>;
}

interface WalkForward {
  ok?: boolean; verdict?: string; reason?: string;
  folds?: Array<{
    fold: number; train_trades: number; validate_trades: number;
    train_expectancy: number; validate_expectancy: number;
    train_win_rate: number; validate_win_rate: number;
  }>;
  generalization_score?: number | null; consistency?: number | null;
  overfitting_risk?: string;
}

interface MonteCarlo {
  ok?: boolean; verdict?: string; reason?: string;
  probability_of_profit?: number; probability_drawdown_gt_10pct?: number;
  expected_return_range_pct?: { p5: number; p50: number; p95: number };
  confidence_interval_95_pct?: number[]; worst_expected_drawdown_pct?: number;
  best_expected_outcome_pct?: number; capital_survival_probability?: number;
  risk_of_ruin_pct?: number;
  return_histogram?: Array<{ bucket: number; count: number }>;
  drawdown_histogram?: Array<{ bucket: number; count: number }>;
  sample_paths?: number[][];
}

interface RunDiff {
  ok?: boolean; error?: string;
  run_a?: RunMetricRow; run_b?: RunMetricRow;
  trades_added?: Array<{ symbol?: string; fill_ts?: string; pnl?: number }>;
  trades_removed?: Array<{ symbol?: string; fill_ts?: string; pnl?: number }>;
  pnl_difference?: number; drawdown_difference?: number;
  strategy_difference?: { only_a?: string[]; only_b?: string[] };
  confidence_difference?: { a?: number | null; b?: number | null };
  risk_difference?: { a_max_exposure?: number; b_max_exposure?: number };
}

interface Recommendations {
  ok?: boolean; verdict?: string; reason?: string;
  recommendations?: Array<{
    kind: string; text: string; evidence_trades?: number; advisory?: boolean;
  }>;
}

interface Verify {
  ok?: boolean; verdict?: string;
  checks?: Array<{ check: string; status: string; detail: string }>;
}

interface ConfigForm {
  label: string;
  min_confidence: string; stop_mult: string; target_mult: string;
  trailing_mult: string; risk_scale: string; max_open_trades: string;
  regime_filter: string; sector_filter: string; min_volume_ratio: string;
}

// ── Palette for per-run chart lines ──────────────────────────────────────────

const LINE_COLORS = ["#6366F1", "#10B981", "#F59E0B", "#EF4444", "#06B6D4", "#8B5CF6"];

const EXAMPLE_CONFIGS: ConfigForm[] = [
  { label: "A", min_confidence: "60", stop_mult: "2", target_mult: "1",
    trailing_mult: "", risk_scale: "1.0", max_open_trades: "", regime_filter: "",
    sector_filter: "", min_volume_ratio: "" },
  { label: "B", min_confidence: "55", stop_mult: "2.5", target_mult: "1",
    trailing_mult: "", risk_scale: "1.0", max_open_trades: "", regime_filter: "",
    sector_filter: "", min_volume_ratio: "" },
  { label: "C", min_confidence: "50", stop_mult: "3", target_mult: "1",
    trailing_mult: "", risk_scale: "0.75", max_open_trades: "", regime_filter: "",
    sector_filter: "", min_volume_ratio: "" },
];

// ── Small shared UI pieces ───────────────────────────────────────────────────

function InsufficientEvidence({ reason }: { reason?: string }) {
  return (
    <div
      data-testid="insufficient-evidence"
      className="flex items-start gap-2 rounded-md border border-amber-500/40 bg-amber-500/10 p-3 text-sm text-amber-400"
    >
      <AlertTriangle className="mt-0.5 h-4 w-4 flex-shrink-0" />
      <div>
        <div className="font-semibold">INSUFFICIENT_EVIDENCE</div>
        <div className="text-amber-400/80">
          {reason || "Not enough closed trades to compute this analytic. This is expected for very small runs."}
        </div>
      </div>
    </div>
  );
}

function RiskBadge({ level }: { level?: string }) {
  const l = (level || "UNKNOWN").toUpperCase();
  const cls =
    l === "LOW" ? "bg-emerald-500/15 text-emerald-400 border-emerald-500/40"
    : l === "MEDIUM" ? "bg-amber-500/15 text-amber-400 border-amber-500/40"
    : l === "HIGH" ? "bg-red-500/15 text-red-400 border-red-500/40"
    : "bg-muted text-muted-foreground border-border";
  return <Badge variant="outline" className={cls}>{l}</Badge>;
}

function num(v: unknown, dp = 2): string {
  if (v === null || v === undefined || v === "") return "—";
  const n = typeof v === "number" ? v : Number(v);
  return Number.isFinite(n) ? n.toFixed(dp) : "—";
}

// ── Page ─────────────────────────────────────────────────────────────────────

export default function OptimizationLab() {
  const [selectedRuns, setSelectedRuns] = useState<string[]>([]);
  const [source, setSource] = useState<"backtest" | "paper">("backtest");
  const [configs, setConfigs] = useState<ConfigForm[]>(EXAMPLE_CONFIGS);
  const [folds, setFolds] = useState(4);
  const [expandedDropped, setExpandedDropped] = useState<Record<number, boolean>>({});
  const [diffA, setDiffA] = useState<string>("");
  const [diffB, setDiffB] = useState<string>("");

  const activeRun = selectedRuns[0];

  // Run list for pickers (COMPLETED only)
  const runsQuery = useQuery({
    queryKey: ["lab", "runs"],
    queryFn: () => apiJson<{ runs: BacktestRun[] }>("/backtest/runs", undefined, 60_000),
    staleTime: 30_000,
  });
  const completedRuns = useMemo(
    () => (runsQuery.data?.runs ?? []).filter((r) => r.status === "COMPLETED"),
    [runsQuery.data],
  );

  // ── Section 2: Multi-run comparison ──
  const compareRuns = useMutation({
    mutationFn: (run_ids: string[]) =>
      apiJson<{ ok: boolean; rows: RunMetricRow[] }>(
        "/lab/compare-runs",
        { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ run_ids }) },
        120_000,
      ),
  });

  // ── Section 3: Compare configs ──
  const compareConfigs = useMutation({
    mutationFn: (payload: { run_id: string; configs: Array<{ label: string; params: Record<string, unknown> }> }) =>
      apiJson<{ ok: boolean; rows: WhatIfResult[] }>(
        "/lab/compare-configs",
        { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) },
        180_000,
      ),
  });

  // ── Section 4: Walk-forward ──
  const walkForward = useMutation({
    mutationFn: (args: { run_id: string; folds: number }) =>
      apiJson<WalkForward>(`/lab/walk-forward/${encodeURIComponent(args.run_id)}?folds=${args.folds}`, undefined, 180_000),
  });

  // ── Section 5: Monte Carlo ──
  const monteCarlo = useMutation({
    mutationFn: (args: { source: string; run_id?: string }) =>
      apiJson<MonteCarlo>(
        `/lab/monte-carlo?source=${args.source}${args.run_id ? `&run_id=${encodeURIComponent(args.run_id)}` : ""}`,
        undefined, 180_000,
      ),
  });

  // ── Section 6: Diff ──
  const diff = useMutation({
    mutationFn: (args: { a: string; b: string }) =>
      apiJson<RunDiff>(`/lab/diff?a=${encodeURIComponent(args.a)}&b=${encodeURIComponent(args.b)}`, undefined, 120_000),
  });

  // ── Section 7: Recommendations ──
  const recommendations = useMutation({
    mutationFn: (args: { source: string; run_id?: string }) =>
      apiJson<Recommendations>(
        `/lab/recommendations?source=${args.source}${args.run_id ? `&run_id=${encodeURIComponent(args.run_id)}` : ""}`,
        undefined, 180_000,
      ),
  });

  // ── Section 9: Verify ──
  const verify = useMutation({
    mutationFn: (run_id?: string) =>
      apiJson<Verify>(`/lab/verify${run_id ? `?run_id=${encodeURIComponent(run_id)}` : ""}`, undefined, 180_000),
  });

  const toggleRun = (id: string) => {
    setSelectedRuns((prev) =>
      prev.includes(id) ? prev.filter((r) => r !== id) : [...prev, id],
    );
  };

  const paramsFromConfig = (c: ConfigForm): Record<string, unknown> => {
    const p: Record<string, unknown> = {};
    if (c.min_confidence !== "") p.min_confidence = Number(c.min_confidence);
    if (c.stop_mult !== "") p.stop_mult = Number(c.stop_mult);
    if (c.target_mult !== "") p.target_mult = Number(c.target_mult);
    if (c.trailing_mult !== "") p.trailing_mult = Number(c.trailing_mult);
    if (c.risk_scale !== "") p.risk_scale = Number(c.risk_scale);
    if (c.max_open_trades !== "") p.max_open_trades = Number(c.max_open_trades);
    if (c.regime_filter.trim() !== "") p.regime_filter = c.regime_filter.trim();
    if (c.sector_filter.trim() !== "") p.sector_filter = c.sector_filter.trim();
    if (c.min_volume_ratio !== "") p.min_volume_ratio = Number(c.min_volume_ratio);
    return p;
  };

  const updateConfig = (idx: number, field: keyof ConfigForm, value: string) => {
    setConfigs((prev) => prev.map((c, i) => (i === idx ? { ...c, [field]: value } : c)));
  };

  const exportHref = (fmt: string) =>
    `${API_BASE}/lab/export?source=${source}${activeRun ? `&run_id=${encodeURIComponent(activeRun)}` : ""}&fmt=${fmt}`;

  // ── equity overlay data (merged by index) ──
  const equityOverlay = useMemo(() => {
    const rows = compareRuns.data?.rows ?? [];
    const maxLen = Math.max(0, ...rows.map((r) => (r.equity_curve?.length ?? 0)));
    const out: Array<Record<string, number | string>> = [];
    for (let i = 0; i < maxLen; i++) {
      const point: Record<string, number | string> = { i };
      rows.forEach((r) => {
        const pt = r.equity_curve?.[i];
        const v = pt ? Number(pt.equity ?? pt.value ?? 0) : undefined;
        if (v !== undefined) point[r.run_id] = v;
      });
      out.push(point);
    }
    return out;
  }, [compareRuns.data]);

  // ── monte-carlo spaghetti data ──
  const spaghetti = useMemo(() => {
    const paths = monteCarlo.data?.sample_paths ?? [];
    const maxLen = Math.max(0, ...paths.map((p) => p.length));
    const out: Array<Record<string, number>> = [];
    for (let i = 0; i < maxLen; i++) {
      const point: Record<string, number> = { i };
      paths.forEach((p, pi) => { if (p[i] !== undefined) point[`p${pi}`] = p[i]; });
      out.push(point);
    }
    return { data: out, count: paths.length };
  }, [monteCarlo.data]);

  return (
    <div className="space-y-6 p-4">
      <PageHeader
        title="Strategy Optimization Lab"
        subtitle="Derived what-if, walk-forward, Monte-Carlo, comparison and recommendation analytics over recorded backtest runs."
        icon={FlaskConical}
        agentId="strategy"
        agentName="Strategy"
        advisory
        readOnly
      />

      {/* ── Section 1: Run picker ────────────────────────────────────────── */}
      <Card data-testid="card-run-picker">
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Layers className="h-4 w-4" /> Run Picker
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex items-center gap-2 text-sm">
            <span className="text-muted-foreground">Source:</span>
            <Button
              size="sm"
              variant={source === "backtest" ? "default" : "outline"}
              data-testid="button-source-backtest"
              onClick={() => setSource("backtest")}
            >Backtest</Button>
            <Button
              size="sm"
              variant={source === "paper" ? "default" : "outline"}
              data-testid="button-source-paper"
              onClick={() => setSource("paper")}
            >Paper</Button>
          </div>

          {runsQuery.isLoading && <div className="text-sm text-muted-foreground">Loading runs…</div>}
          {runsQuery.isError && (
            <div className="text-sm text-red-400">Failed to load runs: {String((runsQuery.error as Error)?.message)}</div>
          )}
          {!runsQuery.isLoading && completedRuns.length === 0 && (
            <div className="text-sm text-muted-foreground">No COMPLETED backtest runs available.</div>
          )}

          <div className="grid grid-cols-1 gap-2 md:grid-cols-2">
            {completedRuns.map((r) => (
              <label
                key={r.run_id}
                className="flex cursor-pointer items-center gap-3 rounded-md border border-border p-2 hover:bg-muted/40"
              >
                <Checkbox
                  checked={selectedRuns.includes(r.run_id)}
                  onCheckedChange={() => toggleRun(r.run_id)}
                  data-testid={`checkbox-run-${r.run_id}`}
                />
                <div className="min-w-0 flex-1">
                  <div className="truncate font-mono text-sm">{r.run_id}</div>
                  <div className="text-xs text-muted-foreground">
                    {r.config?.start} → {r.config?.end} · {r.config?.interval}
                  </div>
                </div>
                {selectedRuns[0] === r.run_id && (
                  <Badge variant="outline" className="border-indigo-500/40 text-indigo-400">active</Badge>
                )}
              </label>
            ))}
          </div>
          {activeRun && (
            <div className="text-xs text-muted-foreground">
              Active run: <span className="font-mono text-foreground">{activeRun}</span>
            </div>
          )}
        </CardContent>
      </Card>

      {/* ── Section 2: Multi-run comparison ──────────────────────────────── */}
      <Card data-testid="card-compare-runs">
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <BarChart3 className="h-4 w-4" /> Multi-Run Comparison
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <Button
            data-testid="button-compare-runs"
            disabled={selectedRuns.length === 0 || compareRuns.isPending}
            onClick={() => compareRuns.mutate(selectedRuns)}
          >
            {compareRuns.isPending ? "Comparing…" : `Compare ${selectedRuns.length || ""} runs`}
          </Button>
          {compareRuns.isError && (
            <div className="text-sm text-red-400">{String((compareRuns.error as Error)?.message)}</div>
          )}
          {compareRuns.data?.rows && compareRuns.data.rows.length > 0 && (
            <>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead className="text-xs text-muted-foreground">
                    <tr className="border-b border-border">
                      {["Run", "Period", "Trades", "Win %", "PnL", "Sharpe", "Sortino",
                        "Max DD %", "PF", "Expectancy", "Avg Hold", "Recovery",
                        "Cap Growth %", "Max Exposure"].map((h) => (
                        <th key={h} className="whitespace-nowrap px-2 py-1 text-left">{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {compareRuns.data.rows.map((r) => (
                      <tr key={r.run_id} className="border-b border-border/50">
                        <td className="whitespace-nowrap px-2 py-1 font-mono text-xs">{r.run_id}</td>
                        <td className="whitespace-nowrap px-2 py-1 text-xs">{r.period ?? "—"}</td>
                        <td className="px-2 py-1">{r.trades ?? "—"}</td>
                        <td className="px-2 py-1">{num(r.win_rate, 1)}</td>
                        <td className="px-2 py-1">{num(r.pnl)}</td>
                        <td className="px-2 py-1">{num(r.sharpe)}</td>
                        <td className="px-2 py-1">{num(r.sortino)}</td>
                        <td className="px-2 py-1">{num(r.max_drawdown_pct)}</td>
                        <td className="px-2 py-1">{num(r.profit_factor)}</td>
                        <td className="px-2 py-1">{num(r.expectancy)}</td>
                        <td className="px-2 py-1">{num(r.avg_hold_days)}</td>
                        <td className="px-2 py-1">{num(r.recovery_factor)}</td>
                        <td className="px-2 py-1">{num(r.capital_growth_pct)}</td>
                        <td className="px-2 py-1">{num(r.max_exposure)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {equityOverlay.length > 0 && (
                <div className="h-64">
                  <ResponsiveContainer width="100%" height="100%">
                    <LineChart data={equityOverlay}>
                      <CartesianGrid strokeDasharray="3 3" stroke="#333" />
                      <XAxis dataKey="i" tick={{ fontSize: 10, fill: "#888" }} />
                      <YAxis tick={{ fontSize: 10, fill: "#888" }} width={60} />
                      <Tooltip contentStyle={{ background: "#111", border: "1px solid #333", fontSize: 12 }} />
                      {compareRuns.data.rows.map((r, i) => (
                        <Line key={r.run_id} type="monotone" dataKey={r.run_id}
                          stroke={LINE_COLORS[i % LINE_COLORS.length]} dot={false} strokeWidth={1.5} />
                      ))}
                    </LineChart>
                  </ResponsiveContainer>
                </div>
              )}
            </>
          )}
        </CardContent>
      </Card>

      {/* ── Section 3: Config comparison / what-if ───────────────────────── */}
      <Card data-testid="card-compare-configs">
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Sparkles className="h-4 w-4" /> Config Comparison / What-If
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="rounded-md border border-indigo-500/40 bg-indigo-500/10 p-3 text-sm text-indigo-300">
            Derived simulations over the recorded run — the base run is never modified.
          </div>
          {!activeRun && (
            <div className="text-sm text-muted-foreground">Select at least one run above to enable what-if comparison.</div>
          )}

          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            {configs.map((c, idx) => (
              <div key={idx} className="space-y-2 rounded-md border border-border p-3" data-testid={`config-${idx}`}>
                <div className="flex items-center gap-2">
                  <Label className="text-xs">Label</Label>
                  <Input
                    value={c.label}
                    onChange={(e) => updateConfig(idx, "label", e.target.value)}
                    className="h-7 w-24 text-sm"
                    data-testid={`input-config-label-${idx}`}
                  />
                  {configs.length > 1 && (
                    <Button
                      size="sm" variant="ghost" className="ml-auto text-xs text-red-400"
                      onClick={() => setConfigs((p) => p.filter((_, i) => i !== idx))}
                    >Remove</Button>
                  )}
                </div>
                <div className="grid grid-cols-2 gap-2 text-xs">
                  {([
                    ["min_confidence", "Min confidence"],
                    ["stop_mult", "Stop mult (ATR×)"],
                    ["target_mult", "Target mult"],
                    ["trailing_mult", "Trailing mult"],
                    ["risk_scale", "Risk scale"],
                    ["max_open_trades", "Max open trades"],
                    ["min_volume_ratio", "Min volume ratio"],
                  ] as Array<[keyof ConfigForm, string]>).map(([field, label]) => (
                    <div key={field} className="space-y-1">
                      <Label className="text-[10px] text-muted-foreground">{label}</Label>
                      <Input
                        value={c[field]}
                        onChange={(e) => updateConfig(idx, field, e.target.value)}
                        className="h-7 text-sm"
                        inputMode="decimal"
                      />
                    </div>
                  ))}
                  <div className="space-y-1">
                    <Label className="text-[10px] text-muted-foreground">Regime filter</Label>
                    <Input value={c.regime_filter} onChange={(e) => updateConfig(idx, "regime_filter", e.target.value)} className="h-7 text-sm" />
                  </div>
                  <div className="space-y-1">
                    <Label className="text-[10px] text-muted-foreground">Sector filter</Label>
                    <Input value={c.sector_filter} onChange={(e) => updateConfig(idx, "sector_filter", e.target.value)} className="h-7 text-sm" />
                  </div>
                </div>
              </div>
            ))}
          </div>

          <div className="flex gap-2">
            {configs.length < 4 && (
              <Button
                size="sm" variant="outline"
                onClick={() => setConfigs((p) => [...p, {
                  label: String.fromCharCode(65 + p.length), min_confidence: "", stop_mult: "",
                  target_mult: "", trailing_mult: "", risk_scale: "1.0", max_open_trades: "",
                  regime_filter: "", sector_filter: "", min_volume_ratio: "",
                }])}
              >Add configuration</Button>
            )}
            <Button
              data-testid="button-compare-configs"
              disabled={!activeRun || compareConfigs.isPending}
              onClick={() => compareConfigs.mutate({
                run_id: activeRun,
                configs: configs.map((c) => ({ label: c.label, params: paramsFromConfig(c) })),
              })}
            >
              {compareConfigs.isPending ? "Simulating…" : "Compare configurations"}
            </Button>
          </div>

          {compareConfigs.isError && (
            <div className="text-sm text-red-400">{String((compareConfigs.error as Error)?.message)}</div>
          )}

          {compareConfigs.data?.rows && (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="text-xs text-muted-foreground">
                  <tr className="border-b border-border">
                    {["Config", "Kept", "Dropped", "PnL", "Win %", "Expectancy", "PF", "Verdict"].map((h) => (
                      <th key={h} className="px-2 py-1 text-left">{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {compareConfigs.data.rows.map((row, i) => (
                    <Fragment key={i}>
                      <tr className="border-b border-border/50">
                        <td className="px-2 py-1 font-semibold">{row.label}</td>
                        <td className="px-2 py-1">{row.trades_kept ?? "—"}</td>
                        <td className="px-2 py-1">
                          {row.trades_dropped ?? 0}
                          {(row.dropped?.length ?? 0) > 0 && (
                            <button
                              className="ml-2 text-xs text-indigo-400 underline"
                              onClick={() => setExpandedDropped((p) => ({ ...p, [i]: !p[i] }))}
                            >{expandedDropped[i] ? "hide" : "reasons"}</button>
                          )}
                        </td>
                        <td className="px-2 py-1">{num(row.pnl)}</td>
                        <td className="px-2 py-1">{num(row.metrics?.win_rate, 1)}</td>
                        <td className="px-2 py-1">{num(row.metrics?.expectancy)}</td>
                        <td className="px-2 py-1">{num(row.metrics?.profit_factor)}</td>
                        <td className="px-2 py-1">
                          {row.verdict === "INSUFFICIENT_EVIDENCE"
                            ? <Badge variant="outline" className="border-amber-500/40 text-amber-400">INSUFFICIENT</Badge>
                            : <Badge variant="outline" className="border-emerald-500/40 text-emerald-400">{row.verdict ?? "—"}</Badge>}
                        </td>
                      </tr>
                      {expandedDropped[i] && (row.dropped?.length ?? 0) > 0 && (
                        <tr>
                          <td colSpan={8} className="bg-muted/30 px-2 py-2">
                            <div className="space-y-1 text-xs text-muted-foreground">
                              {row.dropped!.map((d, di) => (
                                <div key={di}>
                                  <span className="font-mono">{d.symbol}</span> — {d.reason}
                                </div>
                              ))}
                            </div>
                          </td>
                        </tr>
                      )}
                    </Fragment>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>

      {/* ── Section 4: Walk-forward ──────────────────────────────────────── */}
      <Card data-testid="card-walk-forward">
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Repeat className="h-4 w-4" /> Walk-Forward Validation
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex items-center gap-2 text-sm">
            <Label className="text-muted-foreground">Folds:</Label>
            <select
              value={folds}
              onChange={(e) => setFolds(Number(e.target.value))}
              className="rounded-md border border-border bg-background px-2 py-1 text-sm"
              data-testid="select-folds"
            >
              {[3, 4, 5, 6].map((f) => <option key={f} value={f}>{f}</option>)}
            </select>
            <Button
              data-testid="button-walk-forward"
              disabled={!activeRun || walkForward.isPending}
              onClick={() => walkForward.mutate({ run_id: activeRun, folds })}
            >
              {walkForward.isPending ? "Running…" : "Run walk-forward"}
            </Button>
          </div>
          {walkForward.isError && (
            <div className="text-sm text-red-400">{String((walkForward.error as Error)?.message)}</div>
          )}
          {walkForward.data && (
            walkForward.data.verdict === "INSUFFICIENT_EVIDENCE" || !walkForward.data.folds?.length
              ? <InsufficientEvidence reason={walkForward.data.reason} />
              : <>
                  <div className="flex flex-wrap gap-4 text-sm">
                    <div>Generalization score: <span className="font-semibold">{num(walkForward.data.generalization_score)}</span></div>
                    <div>Consistency: <span className="font-semibold">{num(walkForward.data.consistency, 1)}</span></div>
                    <div className="flex items-center gap-2">Overfitting risk: <RiskBadge level={walkForward.data.overfitting_risk} /></div>
                  </div>
                  <div className="overflow-x-auto">
                    <table className="w-full text-sm">
                      <thead className="text-xs text-muted-foreground">
                        <tr className="border-b border-border">
                          {["Fold", "Train trades", "Validate trades", "Train exp", "Validate exp", "Train win %", "Validate win %"].map((h) => (
                            <th key={h} className="px-2 py-1 text-left">{h}</th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {walkForward.data.folds!.map((f) => (
                          <tr key={f.fold} className="border-b border-border/50">
                            <td className="px-2 py-1">{f.fold}</td>
                            <td className="px-2 py-1">{f.train_trades}</td>
                            <td className="px-2 py-1">{f.validate_trades}</td>
                            <td className="px-2 py-1">{num(f.train_expectancy)}</td>
                            <td className="px-2 py-1">{num(f.validate_expectancy)}</td>
                            <td className="px-2 py-1">{num(f.train_win_rate, 1)}</td>
                            <td className="px-2 py-1">{num(f.validate_win_rate, 1)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                  <div className="h-56">
                    <ResponsiveContainer width="100%" height="100%">
                      <BarChart data={walkForward.data.folds}>
                        <CartesianGrid strokeDasharray="3 3" stroke="#333" />
                        <XAxis dataKey="fold" tick={{ fontSize: 10, fill: "#888" }} />
                        <YAxis tick={{ fontSize: 10, fill: "#888" }} />
                        <Tooltip contentStyle={{ background: "#111", border: "1px solid #333", fontSize: 12 }} />
                        <Bar dataKey="train_expectancy" fill="#6366F1" name="Train exp" />
                        <Bar dataKey="validate_expectancy" fill="#10B981" name="Validate exp" />
                      </BarChart>
                    </ResponsiveContainer>
                  </div>
                </>
          )}
        </CardContent>
      </Card>

      {/* ── Section 5: Monte Carlo ───────────────────────────────────────── */}
      <Card data-testid="card-monte-carlo">
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <BarChart3 className="h-4 w-4" /> Monte-Carlo Simulation
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <Button
            data-testid="button-monte-carlo"
            disabled={(source === "backtest" && !activeRun) || monteCarlo.isPending}
            onClick={() => monteCarlo.mutate({ source, run_id: source === "backtest" ? activeRun : undefined })}
          >
            {monteCarlo.isPending ? "Simulating…" : "Run Monte-Carlo"}
          </Button>
          {monteCarlo.isError && (
            <div className="text-sm text-red-400">{String((monteCarlo.error as Error)?.message)}</div>
          )}
          {monteCarlo.data && (
            monteCarlo.data.verdict === "INSUFFICIENT_EVIDENCE"
              ? <InsufficientEvidence reason={monteCarlo.data.reason} />
              : <>
                  <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
                    {[
                      ["Prob. of profit", num(monteCarlo.data.probability_of_profit, 1) + "%"],
                      ["Prob. DD > 10%", num(monteCarlo.data.probability_drawdown_gt_10pct, 1) + "%"],
                      ["Capital survival", num(monteCarlo.data.capital_survival_probability, 1) + "%"],
                      ["Risk of ruin", num(monteCarlo.data.risk_of_ruin_pct) + "%"],
                      ["Return p5", num(monteCarlo.data.expected_return_range_pct?.p5) + "%"],
                      ["Return p50", num(monteCarlo.data.expected_return_range_pct?.p50) + "%"],
                      ["Return p95", num(monteCarlo.data.expected_return_range_pct?.p95) + "%"],
                      ["Worst DD", num(monteCarlo.data.worst_expected_drawdown_pct) + "%"],
                      ["Best outcome", num(monteCarlo.data.best_expected_outcome_pct) + "%"],
                      ["95% CI", (monteCarlo.data.confidence_interval_95_pct ?? []).map((v) => num(v)).join(" … ")],
                    ].map(([label, value]) => (
                      <div key={label} className="rounded-md border border-border p-2">
                        <div className="text-xs text-muted-foreground">{label}</div>
                        <div className="text-lg font-semibold">{value}</div>
                      </div>
                    ))}
                  </div>
                  <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
                    <div>
                      <div className="mb-1 text-xs text-muted-foreground">Return distribution</div>
                      <div className="h-48">
                        <ResponsiveContainer width="100%" height="100%">
                          <BarChart data={monteCarlo.data.return_histogram}>
                            <CartesianGrid strokeDasharray="3 3" stroke="#333" />
                            <XAxis dataKey="bucket" tick={{ fontSize: 9, fill: "#888" }} />
                            <YAxis tick={{ fontSize: 9, fill: "#888" }} />
                            <Tooltip contentStyle={{ background: "#111", border: "1px solid #333", fontSize: 12 }} />
                            <Bar dataKey="count" fill="#6366F1" />
                          </BarChart>
                        </ResponsiveContainer>
                      </div>
                    </div>
                    <div>
                      <div className="mb-1 text-xs text-muted-foreground">Drawdown distribution</div>
                      <div className="h-48">
                        <ResponsiveContainer width="100%" height="100%">
                          <BarChart data={monteCarlo.data.drawdown_histogram}>
                            <CartesianGrid strokeDasharray="3 3" stroke="#333" />
                            <XAxis dataKey="bucket" tick={{ fontSize: 9, fill: "#888" }} />
                            <YAxis tick={{ fontSize: 9, fill: "#888" }} />
                            <Tooltip contentStyle={{ background: "#111", border: "1px solid #333", fontSize: 12 }} />
                            <Bar dataKey="count" fill="#F59E0B" />
                          </BarChart>
                        </ResponsiveContainer>
                      </div>
                    </div>
                  </div>
                  {spaghetti.data.length > 0 && (
                    <div>
                      <div className="mb-1 text-xs text-muted-foreground">Sample equity paths ({spaghetti.count})</div>
                      <div className="h-56">
                        <ResponsiveContainer width="100%" height="100%">
                          <LineChart data={spaghetti.data}>
                            <CartesianGrid strokeDasharray="3 3" stroke="#222" />
                            <XAxis dataKey="i" tick={{ fontSize: 9, fill: "#888" }} />
                            <YAxis tick={{ fontSize: 9, fill: "#888" }} />
                            {Array.from({ length: spaghetti.count }).map((_, pi) => (
                              <Line key={pi} type="monotone" dataKey={`p${pi}`} stroke="#6366F1"
                                strokeOpacity={0.15} strokeWidth={0.8} dot={false} isAnimationActive={false} />
                            ))}
                          </LineChart>
                        </ResponsiveContainer>
                      </div>
                    </div>
                  )}
                </>
          )}
        </CardContent>
      </Card>

      {/* ── Section 6: Compare any two runs ──────────────────────────────── */}
      <Card data-testid="card-diff">
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <GitCompare className="h-4 w-4" /> Compare Any Two Runs
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex flex-wrap items-center gap-2 text-sm">
            <select
              value={diffA} onChange={(e) => setDiffA(e.target.value)}
              className="rounded-md border border-border bg-background px-2 py-1 text-sm"
              data-testid="select-diff-a"
            >
              <option value="">Run A…</option>
              {completedRuns.map((r) => <option key={r.run_id} value={r.run_id}>{r.run_id}</option>)}
            </select>
            <span className="text-muted-foreground">vs</span>
            <select
              value={diffB} onChange={(e) => setDiffB(e.target.value)}
              className="rounded-md border border-border bg-background px-2 py-1 text-sm"
              data-testid="select-diff-b"
            >
              <option value="">Run B…</option>
              {completedRuns.map((r) => <option key={r.run_id} value={r.run_id}>{r.run_id}</option>)}
            </select>
            <Button
              data-testid="button-diff"
              disabled={!diffA || !diffB || diff.isPending}
              onClick={() => diff.mutate({ a: diffA, b: diffB })}
            >
              {diff.isPending ? "Diffing…" : "Compare"}
            </Button>
          </div>
          {diff.isError && <div className="text-sm text-red-400">{String((diff.error as Error)?.message)}</div>}
          {diff.data?.ok && diff.data.run_a && diff.data.run_b && (
            <>
              <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                {[diff.data.run_a, diff.data.run_b].map((r, i) => (
                  <div key={i} className="rounded-md border border-border p-3 text-sm">
                    <div className="mb-2 font-mono text-xs">{r.run_id}</div>
                    <div className="grid grid-cols-2 gap-1">
                      <div>PnL: {num(r.pnl)}</div>
                      <div>Win %: {num(r.win_rate, 1)}</div>
                      <div>Sharpe: {num(r.sharpe)}</div>
                      <div>Max DD %: {num(r.max_drawdown_pct)}</div>
                      <div>Expectancy: {num(r.expectancy)}</div>
                      <div>Max exposure: {num(r.max_exposure)}</div>
                    </div>
                  </div>
                ))}
              </div>
              <div className="flex flex-wrap gap-4 text-sm">
                <div>PnL diff: <span className="font-semibold">{num(diff.data.pnl_difference)}</span></div>
                <div>Drawdown diff: <span className="font-semibold">{num(diff.data.drawdown_difference)}</span></div>
                <div>Confidence: A {num(diff.data.confidence_difference?.a, 1)} / B {num(diff.data.confidence_difference?.b, 1)}</div>
              </div>
              <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                <div>
                  <div className="mb-1 text-xs text-emerald-400">Trades added ({diff.data.trades_added?.length ?? 0})</div>
                  <div className="max-h-40 space-y-1 overflow-y-auto text-xs">
                    {(diff.data.trades_added ?? []).map((t, i) => (
                      <div key={i}><span className="font-mono">{t.symbol}</span> {t.fill_ts} · {num(t.pnl)}</div>
                    ))}
                  </div>
                </div>
                <div>
                  <div className="mb-1 text-xs text-red-400">Trades removed ({diff.data.trades_removed?.length ?? 0})</div>
                  <div className="max-h-40 space-y-1 overflow-y-auto text-xs">
                    {(diff.data.trades_removed ?? []).map((t, i) => (
                      <div key={i}><span className="font-mono">{t.symbol}</span> {t.fill_ts} · {num(t.pnl)}</div>
                    ))}
                  </div>
                </div>
              </div>
            </>
          )}
        </CardContent>
      </Card>

      {/* ── Section 7: Recommendations ───────────────────────────────────── */}
      <Card data-testid="card-recommendations">
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Lightbulb className="h-4 w-4" /> Recommendations
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="rounded-md border border-amber-500/40 bg-amber-500/10 p-2 text-xs text-amber-400">
            Auto-apply is disabled — advisory only. Nothing is changed automatically.
          </div>
          <Button
            data-testid="button-recommendations"
            disabled={(source === "backtest" && !activeRun) || recommendations.isPending}
            onClick={() => recommendations.mutate({ source, run_id: source === "backtest" ? activeRun : undefined })}
          >
            {recommendations.isPending ? "Analyzing…" : "Generate recommendations"}
          </Button>
          {recommendations.isError && (
            <div className="text-sm text-red-400">{String((recommendations.error as Error)?.message)}</div>
          )}
          {recommendations.data && (
            recommendations.data.verdict === "INSUFFICIENT_EVIDENCE" || !recommendations.data.recommendations?.length
              ? <InsufficientEvidence reason={recommendations.data.reason} />
              : <div className="space-y-2">
                  {recommendations.data.recommendations!.map((r, i) => (
                    <div key={i} className="flex items-start gap-3 rounded-md border border-border p-3">
                      <Badge variant="outline" className="border-indigo-500/40 text-indigo-400">{r.kind}</Badge>
                      <div className="flex-1 text-sm">{r.text}</div>
                      <span className="whitespace-nowrap text-xs text-muted-foreground">{r.evidence_trades ?? 0} trades</span>
                    </div>
                  ))}
                </div>
          )}
        </CardContent>
      </Card>

      {/* ── Section 8: Export ────────────────────────────────────────────── */}
      <Card data-testid="card-export">
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Download className="h-4 w-4" /> Export
          </CardTitle>
        </CardHeader>
        <CardContent className="flex flex-wrap gap-2">
          <a href={exportHref("json")} download data-testid="button-export-json">
            <Button variant="outline" size="sm">JSON</Button>
          </a>
          <a href={exportHref("csv")} download data-testid="button-export-csv">
            <Button variant="outline" size="sm">CSV</Button>
          </a>
          <a href={exportHref("markdown")} download data-testid="button-export-markdown">
            <Button variant="outline" size="sm">Markdown</Button>
          </a>
          <Button variant="outline" size="sm" data-testid="button-print" onClick={() => window.print()}>
            <Printer className="mr-1 h-4 w-4" /> Print / PDF
          </Button>
        </CardContent>
      </Card>

      {/* ── Section 9: Validation ────────────────────────────────────────── */}
      <Card data-testid="card-verify">
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <ShieldCheck className="h-4 w-4" /> Validation
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <Button
            data-testid="button-verify"
            disabled={verify.isPending}
            onClick={() => verify.mutate(activeRun)}
          >
            {verify.isPending ? "Verifying…" : "Run validation"}
          </Button>
          {verify.isError && <div className="text-sm text-red-400">{String((verify.error as Error)?.message)}</div>}
          {verify.data && (
            <>
              <div className="flex items-center gap-2 text-sm">
                Verdict:
                {verify.data.verdict === "PASS"
                  ? <Badge variant="outline" className="border-emerald-500/40 text-emerald-400">PASS</Badge>
                  : <Badge variant="outline" className="border-red-500/40 text-red-400">FAIL</Badge>}
              </div>
              <div className="space-y-1">
                {(verify.data.checks ?? []).map((c, i) => (
                  <div key={i} className="flex items-start gap-2 rounded-md border border-border p-2 text-sm">
                    {c.status === "PASS"
                      ? <Badge variant="outline" className="border-emerald-500/40 text-emerald-400">PASS</Badge>
                      : <Badge variant="outline" className="border-red-500/40 text-red-400">FAIL</Badge>}
                    <div>
                      <div className="font-medium">{c.check}</div>
                      <div className="text-xs text-muted-foreground">{c.detail}</div>
                    </div>
                  </div>
                ))}
              </div>
            </>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
