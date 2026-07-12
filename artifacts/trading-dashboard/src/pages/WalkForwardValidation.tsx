import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import {
  useGetWalkForwardStatus,
  getGetWalkForwardStatusQueryKey,
  useGetWalkForwardResult,
  getGetWalkForwardResultQueryKey,
  useRunWalkForwardValidation,
} from "@workspace/api-client-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  LineChart, Line, AreaChart, Area, XAxis, YAxis, Tooltip,
  ResponsiveContainer, Legend, CartesianGrid,
} from "recharts";
import {
  ShieldCheck, Loader2, Play, AlertTriangle, Download, ChevronDown,
  ChevronRight, Scale, Route,
} from "lucide-react";
import { cn } from "@/lib/utils";
import StrategyAuditSection from "@/components/StrategyAuditSection";
import MacdOptimizationSection from "@/components/MacdOptimizationSection";
import MacdRobustnessSection from "@/components/MacdRobustnessSection";

/* eslint-disable @typescript-eslint/no-explicit-any */

const API_BASE = `${import.meta.env.BASE_URL}api`;

const fmtINR = (v: number | undefined | null) =>
  v === undefined || v === null ? "—" : `₹${Number(v).toLocaleString("en-IN", { maximumFractionDigits: 0 })}`;
const fmtPct = (v: number | undefined | null, signed = true) =>
  v === undefined || v === null ? "—" : `${signed && Number(v) > 0 ? "+" : ""}${Number(v).toFixed(2)}%`;
const fmtNum = (v: number | undefined | null, d = 2) =>
  v === undefined || v === null ? "—" : Number(v).toFixed(d);

function Stat({ label, value, valueClass }: { label: string; value: string; valueClass?: string }) {
  return (
    <div className="bg-zinc-800/50 rounded-md p-3">
      <div className="text-[10px] text-muted-foreground font-mono mb-1 uppercase tracking-wide">{label}</div>
      <div className={cn("text-base font-mono font-bold", valueClass ?? "text-foreground")}>{value}</div>
    </div>
  );
}

function Section({ title, children, defaultOpen = true }: {
  title: string; children: React.ReactNode; defaultOpen?: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <Card>
      <CardHeader
        className="cursor-pointer select-none py-3"
        onClick={() => setOpen(!open)}
        data-testid={`section-${title.toLowerCase().replace(/[^a-z0-9]+/g, "-")}`}
      >
        <CardTitle className="text-sm font-mono flex items-center gap-2">
          {open ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
          {title}
        </CardTitle>
      </CardHeader>
      {open && <CardContent className="pt-0">{children}</CardContent>}
    </Card>
  );
}

function NumField({ label, value, onChange, step = "0.01" }: {
  label: string; value: number; onChange: (v: number) => void; step?: string;
}) {
  return (
    <label className="flex flex-col gap-1 text-[10px] font-mono uppercase tracking-wide text-muted-foreground">
      {label}
      <input
        type="number"
        step={step}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        className="bg-zinc-800 border border-zinc-700 rounded px-2 py-1.5 text-sm font-mono text-foreground w-full"
        data-testid={`input-${label.toLowerCase().replace(/[^a-z0-9]+/g, "-")}`}
      />
    </label>
  );
}

function Select<T extends string | number>({ label, value, options, onChange }: {
  label: string; value: T; options: { v: T; l: string }[]; onChange: (v: T) => void;
}) {
  return (
    <label className="flex flex-col gap-1 text-[10px] font-mono uppercase tracking-wide text-muted-foreground">
      {label}
      <select
        value={String(value)}
        onChange={(e) => {
          const raw = e.target.value;
          const match = options.find((o) => String(o.v) === raw);
          if (match) onChange(match.v);
        }}
        className="bg-zinc-800 border border-zinc-700 rounded px-2 py-1.5 text-sm font-mono text-foreground w-full"
        data-testid={`select-${label.toLowerCase().replace(/[^a-z0-9]+/g, "-")}`}
      >
        {options.map((o) => <option key={String(o.v)} value={String(o.v)}>{o.l}</option>)}
      </select>
    </label>
  );
}

const VERDICT_STYLES: Record<string, string> = {
  "PASSED": "bg-emerald-500/15 border-emerald-500/40 text-emerald-400",
  "PASSED WITH CAUTION": "bg-amber-500/15 border-amber-500/40 text-amber-400",
  "FAILED": "bg-red-500/15 border-red-500/40 text-red-400",
  "INSUFFICIENT DATA": "bg-zinc-500/15 border-zinc-500/40 text-zinc-300",
};

function Tbl({ cols, rows, testId }: { cols: string[]; rows: (string | number | React.ReactNode)[][]; testId?: string }) {
  return (
    <div className="overflow-x-auto" data-testid={testId}>
      <table className="w-full text-xs font-mono">
        <thead>
          <tr className="text-left text-muted-foreground border-b border-zinc-800">
            {cols.map((c) => <th key={c} className="py-1.5 pr-3 font-normal uppercase text-[10px] tracking-wide whitespace-nowrap">{c}</th>)}
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i} className="border-b border-zinc-800/50">
              {r.map((cell, j) => <td key={j} className="py-1.5 pr-3 whitespace-nowrap">{cell}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

const pnlClass = (v: number | undefined | null) =>
  v === undefined || v === null ? "" : Number(v) > 0 ? "text-emerald-400" : Number(v) < 0 ? "text-red-400" : "";

export default function WalkForwardValidation() {
  const queryClient = useQueryClient();
  const [pollUntil, setPollUntil] = useState(0);

  // ── Config state ──────────────────────────────────────────────────────
  const [trainYears, setTrainYears] = useState<number>(1);
  const [testMonths, setTestMonths] = useState<number>(3);
  const [stepMonths, setStepMonths] = useState<number>(3);
  const [capital, setCapital] = useState<number>(5000);
  const [universeSize, setUniverseSize] = useState<number>(50);
  const [intrabarRule, setIntrabarRule] = useState<string>("conservative");
  const [maxHolding, setMaxHolding] = useState<number>(20);
  const [slippage, setSlippage] = useState<number>(0.05);
  const [spread, setSpread] = useState<number>(0.05);
  const [stt, setStt] = useState<number>(0.1);
  const [brokerageFlat, setBrokerageFlat] = useState<number>(0);
  const [maxGap, setMaxGap] = useState<number>(3);
  const [volPart, setVolPart] = useState<number>(5);
  const [minPf, setMinPf] = useState<number>(1.15);
  const [maxDd, setMaxDd] = useState<number>(20);
  const [minTrades, setMinTrades] = useState<number>(100);

  // ── Data ──────────────────────────────────────────────────────────────
  const { data: status } = useGetWalkForwardStatus({
    query: {
      queryKey: getGetWalkForwardStatusQueryKey(),
      refetchInterval: (q) =>
        (q.state.data as any)?.status === "running" || Date.now() < pollUntil ? 3000 : false,
    },
  });
  const running = (status as any)?.status === "running";

  const { data: result } = useGetWalkForwardResult({
    query: {
      queryKey: getGetWalkForwardResultQueryKey(),
      refetchInterval: running ? 5000 : false,
    },
  });

  const run = useRunWalkForwardValidation({
    mutation: {
      onSuccess: () => {
        setPollUntil(Date.now() + 20000);
        queryClient.invalidateQueries({ queryKey: getGetWalkForwardStatusQueryKey() });
      },
    },
  });

  const startRun = () => {
    run.mutate({
      data: {
        train_years: trainYears as 1 | 2 | 3,
        test_months: testMonths as 1 | 3 | 6,
        step_months: stepMonths as 1 | 3,
        initial_capital: capital,
        universe_size: universeSize >= 50 ? 0 : universeSize,
        max_holding_days: maxHolding,
        intrabar_rule: intrabarRule as "conservative" | "optimistic",
        cost_model: {
          slippage_pct: slippage,
          spread_pct: spread,
          stt_pct: stt,
          brokerage_flat: brokerageFlat,
          max_entry_gap_pct: maxGap,
          volume_participation_pct: volPart,
        },
        verdict_criteria: {
          min_profit_factor: minPf,
          max_drawdown_pct: maxDd,
          min_trades: minTrades,
        },
      } as any,
    });
  };

  const r = result as any;
  const hasResult = r?.available === true;
  const verdict = r?.verdict;
  const full = r?.overall?.full_metrics;
  const base = r?.overall?.base_metrics;

  return (
    <div className="p-4 space-y-4 max-w-[1200px]">
      {/* Header */}
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <h1 className="text-xl font-mono font-bold flex items-center gap-2">
            <Route className="h-5 w-5 text-primary" />
            Walk-Forward Validation
          </h1>
          <p className="text-xs text-muted-foreground font-mono mt-1 max-w-2xl">
            Tests the complete decision engine on unseen historical periods with realistic
            execution costs. Training and testing data never overlap.
          </p>
        </div>
        <Badge variant="outline" className="font-mono text-[10px] border-amber-500/40 text-amber-400">
          PAPER TRADING · RESEARCH ONLY
        </Badge>
      </div>

      {/* Safety */}
      <div className="flex items-center gap-2 text-[11px] font-mono text-amber-400/90 bg-amber-500/10 border border-amber-500/30 rounded-md px-3 py-2">
        <AlertTriangle className="h-3.5 w-3.5 flex-shrink-0" />
        Out-of-sample historical performance does not guarantee future results. Paper trading and research only.
      </div>

      {/* Configuration */}
      <Section title="Run Configuration">
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-3">
          <Select label="Training period" value={trainYears} onChange={(v) => setTrainYears(Number(v))}
            options={[{ v: 1, l: "1 year" }, { v: 2, l: "2 years" }, { v: 3, l: "3 years" }]} />
          <Select label="Testing period" value={testMonths} onChange={(v) => setTestMonths(Number(v))}
            options={[{ v: 1, l: "1 month" }, { v: 3, l: "3 months" }, { v: 6, l: "6 months" }]} />
          <Select label="Step size" value={stepMonths} onChange={(v) => setStepMonths(Number(v))}
            options={[{ v: 1, l: "1 month" }, { v: 3, l: "3 months" }]} />
          <NumField label="Capital (₹)" value={capital} onChange={setCapital} step="500" />
          <NumField label="Max holding days" value={maxHolding} onChange={setMaxHolding} step="1" />
          <Select label="Same-candle rule" value={intrabarRule} onChange={(v) => setIntrabarRule(String(v))}
            options={[
              { v: "conservative", l: "Conservative (stop first)" },
              { v: "optimistic", l: "Optimistic (target first)" },
            ]} />
          <Select label="Slippage" value={slippage} onChange={(v) => setSlippage(Number(v))}
            options={[{ v: 0, l: "0%" }, { v: 0.05, l: "0.05%" }, { v: 0.1, l: "0.10%" }, { v: 0.2, l: "0.20%" }]} />
          <Select label="Stocks to test" value={universeSize} onChange={(v) => setUniverseSize(Number(v))}
            options={[{ v: 10, l: "First 10 (quick)" }, { v: 25, l: "First 25" }, { v: 50, l: "Full NIFTY 50" }]} />
        </div>

        <div className="grid grid-cols-2 sm:grid-cols-5 gap-3 mb-3">
          <NumField label="Spread %" value={spread} onChange={setSpread} />
          <NumField label="STT % / side" value={stt} onChange={setStt} />
          <NumField label="Brokerage ₹/side" value={brokerageFlat} onChange={setBrokerageFlat} step="1" />
          <NumField label="Max entry gap %" value={maxGap} onChange={setMaxGap} step="0.5" />
          <NumField label="Volume particip. %" value={volPart} onChange={setVolPart} step="1" />
        </div>

        <div className="grid grid-cols-2 sm:grid-cols-3 gap-3 mb-4">
          <NumField label="Verdict: min profit factor" value={minPf} onChange={setMinPf} step="0.05" />
          <NumField label="Verdict: max drawdown %" value={maxDd} onChange={setMaxDd} step="1" />
          <NumField label="Verdict: min trades" value={minTrades} onChange={setMinTrades} step="10" />
        </div>

        <div className="flex items-center gap-3 flex-wrap">
          <Button
            onClick={startRun}
            disabled={running || run.isPending}
            className="font-mono"
            data-testid="button-run-validation"
          >
            {running || run.isPending
              ? <><Loader2 className="h-4 w-4 mr-2 animate-spin" /> Validation running…</>
              : <><Play className="h-4 w-4 mr-2" /> Run Walk-Forward Validation</>}
          </Button>
          {(run.error as any) && (
            <span className="text-xs font-mono text-red-400">
              {(run.error as any)?.response?.data?.error ?? "Failed to start run"}
            </span>
          )}
          <span className="text-[10px] font-mono text-muted-foreground">
            Full NIFTY 50 · GST, SEBI &amp; stamp duty applied automatically · takes several minutes
          </span>
        </div>
      </Section>

      {/* Progress */}
      {(status as any)?.status === "running" && (
        <Card data-testid="card-progress">
          <CardContent className="py-4 space-y-2">
            <div className="flex items-center gap-2 text-sm font-mono">
              <Loader2 className="h-4 w-4 animate-spin text-primary" />
              {(status as any)?.phase ?? "running…"}
            </div>
            <div className="h-2 bg-zinc-800 rounded overflow-hidden">
              <div
                className="h-full bg-primary transition-all"
                style={{ width: `${(status as any)?.progress_pct ?? 0}%` }}
              />
            </div>
            <div className="text-[10px] font-mono text-muted-foreground">
              {((status as any)?.logs ?? []).slice(-3).map((l: string, i: number) => <div key={i}>{l}</div>)}
            </div>
          </CardContent>
        </Card>
      )}
      {(status as any)?.status === "failed" && (
        <div className="flex items-center gap-2 text-xs font-mono text-red-400 bg-red-500/10 border border-red-500/30 rounded-md px-3 py-2" data-testid="text-run-error">
          <AlertTriangle className="h-3.5 w-3.5" />
          {(status as any)?.error ?? "The last validation run failed."}
        </div>
      )}

      {/* ── Results ── */}
      {hasResult && (
        <>
          {/* Verdict */}
          <div
            className={cn("border rounded-md px-4 py-3 space-y-1",
              VERDICT_STYLES[verdict?.verdict] ?? VERDICT_STYLES["INSUFFICIENT DATA"])}
            data-testid="banner-verdict"
          >
            <div className="flex items-center gap-2 font-mono font-bold text-base">
              <Scale className="h-4 w-4" /> {verdict?.verdict}
            </div>
            <div className="text-xs font-mono opacity-90">{verdict?.summary}</div>
            <div className="text-[10px] font-mono opacity-60">
              Generated {r.generated_at} · {r.run_seconds}s · {r.universe_size} stocks ·
              adaptive model v{r.adaptive_model_version} · Lookahead audit:{" "}
              {r.lookahead_audit?.violations === 0
                ? `clean (${r.lookahead_audit?.decisions_logged} decisions checked)`
                : `${r.lookahead_audit?.violations} VIOLATIONS`}
            </div>
          </div>

          {/* Verdict checks */}
          <Section title="Verdict Criteria (configurable)" defaultOpen={false}>
            <Tbl
              cols={["Check", "Observed", "Requirement", "Result"]}
              rows={(verdict?.checks ?? []).map((c: any) => [
                c.name, String(c.observed), `${c.direction} ${c.threshold}`,
                c.passed
                  ? <span className="text-emerald-400">PASS</span>
                  : <span className="text-red-400">FAIL</span>,
              ])}
              testId="table-verdict-checks"
            />
          </Section>

          {/* Headline metrics */}
          <Section title="Full Model — Out-of-Sample Performance (net of all costs)">
            <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-6 gap-2">
              <Stat label="Net return" value={fmtPct(full?.total_return_pct)} valueClass={pnlClass(full?.total_return_pct)} />
              <Stat label="Annualized" value={fmtPct(full?.annualized_return_pct)} valueClass={pnlClass(full?.annualized_return_pct)} />
              <Stat label="Net profit" value={fmtINR(full?.net_profit)} valueClass={pnlClass(full?.net_profit)} />
              <Stat label="Trades" value={String(full?.total_trades ?? "—")} />
              <Stat label="Win rate" value={`${fmtNum(full?.win_rate, 1)}%`} />
              <Stat label="Expectancy / trade" value={fmtINR(full?.expectancy)} valueClass={pnlClass(full?.expectancy)} />
              <Stat label="Profit factor" value={fmtNum(full?.profit_factor)} />
              <Stat label="Sharpe" value={fmtNum(full?.sharpe_ratio)} />
              <Stat label="Sortino" value={fmtNum(full?.sortino_ratio)} />
              <Stat label="Max drawdown" value={`${fmtNum(full?.max_drawdown_pct)}%`} valueClass="text-red-400" />
              <Stat label="Calmar" value={fmtNum(full?.calmar_ratio)} />
              <Stat label="Recovery factor" value={fmtNum(full?.recovery_factor)} />
              <Stat label="Avg hold (days)" value={fmtNum(full?.avg_holding_days, 1)} />
              <Stat label="Exposure" value={`${fmtNum(full?.exposure_pct, 1)}%`} />
              <Stat label="Turnover ×" value={fmtNum(full?.turnover)} />
              <Stat label="Total costs" value={fmtINR(full?.total_costs)} valueClass="text-amber-400" />
              <Stat label="Avg win / loss" value={`${fmtINR(full?.avg_win)} / ${fmtINR(full?.avg_loss)}`} />
              <Stat label="Max consec. losses" value={String(full?.max_consecutive_losses ?? "—")} />
            </div>
            <div className="text-[10px] font-mono text-muted-foreground mt-2">
              {r.intrabar_rule_label}
            </div>
          </Section>

          {/* Equity + drawdown */}
          <Section title="Equity Curve (chained across test windows)">
            <div className="h-64">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={r.equity_curve ?? []}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#27272a" />
                  <XAxis dataKey="date" tick={{ fontSize: 9, fontFamily: "monospace" }} minTickGap={40} />
                  <YAxis tick={{ fontSize: 9, fontFamily: "monospace" }} domain={["auto", "auto"]} />
                  <Tooltip contentStyle={{ background: "#18181b", border: "1px solid #3f3f46", fontSize: 11, fontFamily: "monospace" }} />
                  <Legend wrapperStyle={{ fontSize: 10, fontFamily: "monospace" }} />
                  <Line type="monotone" dataKey="full_model" name="Full model (C)" stroke="#10b981" dot={false} strokeWidth={1.6} />
                  <Line type="monotone" dataKey="base_model" name="Base (technical only)" stroke="#818cf8" dot={false} strokeWidth={1.2} />
                  <Line type="monotone" dataKey="gated_model" name="Gated (D, Phase 2A)" stroke="#22d3ee" dot={false} strokeWidth={1.2} />
                  <Line type="monotone" dataKey="strict_model" name="Strict gates (E)" stroke="#c084fc" dot={false} strokeWidth={1} strokeDasharray="4 3" />
                  <Line type="monotone" dataKey="nifty" name="NIFTY 50" stroke="#f59e0b" dot={false} strokeWidth={1.2} />
                </LineChart>
              </ResponsiveContainer>
            </div>
            <div className="h-32 mt-2">
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={r.drawdown_curve ?? []}>
                  <XAxis dataKey="date" tick={{ fontSize: 9, fontFamily: "monospace" }} minTickGap={40} />
                  <YAxis tick={{ fontSize: 9, fontFamily: "monospace" }} reversed />
                  <Tooltip contentStyle={{ background: "#18181b", border: "1px solid #3f3f46", fontSize: 11, fontFamily: "monospace" }} />
                  <Area type="monotone" dataKey="drawdown_pct" name="Drawdown %" stroke="#ef4444" fill="#ef444433" />
                </AreaChart>
              </ResponsiveContainer>
            </div>
          </Section>

          {/* Layer comparison */}
          <Section title="Model Layer Comparison (A–E on identical data)">
            <Tbl
              cols={["Variant", "Net return", "Expectancy", "Profit factor", "Max DD", "Sharpe", "Trades", "Win rate", "Costs", "Cash time", "vs previous layer"]}
              rows={(r.layer_comparison ?? []).map((row: any) => [
                row.label,
                <span className={pnlClass(row.net_return_pct)}>{fmtPct(row.net_return_pct)}</span>,
                <span className={pnlClass(row.expectancy)}>{fmtINR(row.expectancy)}</span>,
                fmtNum(row.profit_factor),
                `${fmtNum(row.max_drawdown_pct)}%`,
                fmtNum(row.sharpe_ratio),
                row.total_trades,
                `${fmtNum(row.win_rate, 1)}%`,
                fmtINR(row.total_costs),
                row.cash_time_pct === null || row.cash_time_pct === undefined ? "—" : `${fmtNum(row.cash_time_pct, 1)}%`,
                row.vs_previous,
              ])}
              testId="table-layer-comparison"
            />
            <div className="text-[10px] font-mono text-muted-foreground mt-2">
              If a layer does not improve results out-of-sample, it is not adding value — this table shows that honestly.
              Variants D and E are Phase 2A analysis-only policies (corrected gated ranking); the live system still runs variant C.
            </div>
          </Section>

          {/* Phase 2A — corrected ranking analysis */}
          {r.phase2a && (
            <Section title="Phase 2A — Corrected Ranking & Allocation (Analysis Only)">
              <div className="space-y-4" data-testid="phase2a-report">
                <div className="text-xs font-mono text-muted-foreground whitespace-normal">
                  {r.phase2a.description}
                </div>
                <Tbl
                  cols={["Policy", "Net return", "PF", "Expectancy", "Win rate", "Max DD", "Sharpe", "Trades", "Cash time", "Fully-in-cash days"]}
                  rows={[
                    ["C — legacy (live)", r.phase2a.comparison?.legacy_C],
                    ["D — gated (default)", r.phase2a.comparison?.gated_D],
                    ["E — strict gates", r.phase2a.comparison?.strict_E],
                  ].map(([label, m]: any) => [
                    label,
                    <span className={pnlClass(m?.net_return_pct)}>{fmtPct(m?.net_return_pct)}</span>,
                    fmtNum(m?.profit_factor),
                    <span className={pnlClass(m?.expectancy)}>{fmtINR(m?.expectancy)}</span>,
                    `${fmtNum(m?.win_rate, 1)}%`,
                    `${fmtNum(m?.max_drawdown_pct)}%`,
                    fmtNum(m?.sharpe_ratio),
                    m?.total_trades ?? "—",
                    m?.cash_time_pct === null || m?.cash_time_pct === undefined ? "—" : `${fmtNum(m.cash_time_pct, 1)}%`,
                    m?.full_cash_days_pct === null || m?.full_cash_days_pct === undefined ? "—" : `${fmtNum(m.full_cash_days_pct, 1)}%`,
                  ])}
                  testId="table-phase2a-comparison"
                />

                <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                  <Stat label="Trades rejected by gates (D)" value={String(r.phase2a.rejected_trades_summary?.total_rejected ?? 0)} />
                  <Stat label="Rejections that saved money" value={String(r.phase2a.rejected_trades_summary?.rejections_that_saved_money ?? 0)} valueClass="text-emerald-400" />
                  <Stat label="Rejections that cost money" value={String(r.phase2a.rejected_trades_summary?.rejections_that_cost_money ?? 0)} valueClass="text-red-400" />
                  <Stat
                    label="Gate precision"
                    value={r.phase2a.rejected_trades_summary?.gate_precision_pct === null || r.phase2a.rejected_trades_summary?.gate_precision_pct === undefined
                      ? "—" : `${fmtNum(r.phase2a.rejected_trades_summary.gate_precision_pct, 1)}%`}
                  />
                </div>

                {(r.phase2a.rejected_trades ?? []).length > 0 && (
                  <div>
                    <div className="text-[10px] font-mono uppercase tracking-wide text-muted-foreground mb-1">
                      Rejected trades (first {Math.min((r.phase2a.rejected_trades ?? []).length, 50)} shown) — outcome computed after the fact, never fed back into decisions
                    </div>
                    <Tbl
                      cols={["Date", "Stock", "Strategy", "Regime", "Status", "PF (raw→adj)", "Sample", "What would have happened"]}
                      rows={(r.phase2a.rejected_trades ?? []).slice(0, 50).map((t: any) => [
                        t.proposed_date,
                        t.symbol,
                        t.strategy_id,
                        t.regime,
                        <span className="text-red-400 text-[10px]">{t.status}</span>,
                        `${fmtNum(t.raw_profit_factor, 2)} → ${fmtNum(t.adjusted_profit_factor, 2)}`,
                        t.sample ?? "—",
                        <span className="whitespace-normal text-[10px]">{t.would_be_outcome}</span>,
                      ])}
                      testId="table-phase2a-rejected"
                    />
                  </div>
                )}

                <div className="text-xs font-mono whitespace-normal bg-zinc-800/60 border border-zinc-700 rounded px-3 py-2" data-testid="text-phase2a-recommendation">
                  {r.phase2a.recommendation}
                </div>
                <div className="text-[10px] font-mono text-amber-400 whitespace-normal">
                  {r.phase2a.deployment_note}
                </div>
              </div>
            </Section>
          )}

          {/* Phase 2B — strategy audit (analysis only) */}
          {r.strategy_audit && <StrategyAuditSection audit={r.strategy_audit} />}

          {/* Phase 3 — MACD optimization (analysis only) */}
          {r.macd_optimization && <MacdOptimizationSection opt={r.macd_optimization} />}

          {/* Phase 4 — MACD robustness analysis (analysis only) */}
          {r.macd_robustness && <MacdRobustnessSection rob={r.macd_robustness} />}

          {/* Benchmarks */}
          <Section title="Benchmarks">
            <Tbl
              cols={["Benchmark", "Return"]}
              rows={[
                ["Full model (compounded)", <span className={pnlClass(r.benchmarks?.full_model_pct)}>{fmtPct(r.benchmarks?.full_model_pct)}</span>],
                ["NIFTY 50 buy & hold", <span className={pnlClass(r.benchmarks?.nifty_buy_hold_pct)}>{fmtPct(r.benchmarks?.nifty_buy_hold_pct)}</span>],
                ["Equal-weight universe buy & hold", <span className={pnlClass(r.benchmarks?.equal_weight_pct)}>{fmtPct(r.benchmarks?.equal_weight_pct)}</span>],
                ["Rule engine (no learning, every BUY)", <span className={pnlClass(r.benchmarks?.rule_engine_pct)}>{fmtPct(r.benchmarks?.rule_engine_pct)}</span>],
                ["Technical-confidence-only model", <span className={pnlClass(r.benchmarks?.technical_confidence_only_pct)}>{fmtPct(r.benchmarks?.technical_confidence_only_pct)}</span>],
                ["Random stock selection (seeded)", <span className={pnlClass(r.benchmarks?.random_selection_pct)}>{fmtPct(r.benchmarks?.random_selection_pct)}</span>],
                ["Cash (no trading)", fmtPct(0)],
              ]}
              testId="table-benchmarks"
            />
            <div className="text-[10px] font-mono text-muted-foreground mt-2">{r.benchmarks?.note}</div>
          </Section>

          {/* Windows */}
          <Section title={`Test Windows (${(r.windows ?? []).length})`}>
            <Tbl
              cols={["Window", "Train", "Test", "Trades", "Net P&L", "Return", "PF", "Max DD", "NIFTY", "Status"]}
              rows={(r.windows ?? []).map((w: any) => [
                w.label,
                `${w.train_start} → ${w.train_end}`,
                `${w.test_start} → ${w.test_end}`,
                w.full_metrics?.total_trades ?? "—",
                <span className={pnlClass(w.full_metrics?.net_profit)}>{fmtINR(w.full_metrics?.net_profit)}</span>,
                <span className={pnlClass(w.full_metrics?.total_return_pct)}>{fmtPct(w.full_metrics?.total_return_pct)}</span>,
                fmtNum(w.full_metrics?.profit_factor),
                w.full_metrics ? `${fmtNum(w.full_metrics?.max_drawdown_pct)}%` : "—",
                fmtPct(w.benchmarks?.nifty_buy_hold_pct),
                w.failed
                  ? <span className="text-red-400" title={w.failure_reason}>FAILED</span>
                  : <span className="text-emerald-400">OK</span>,
              ])}
              testId="table-windows"
            />
          </Section>

          {/* Calibration report (Phase 1) */}
          <Section title="Confidence Calibration Report">
            {r.calibration_report && (r.calibration_report.samples ?? 0) > 0 ? (
              <div className="space-y-4" data-testid="calibration-report">
                <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                  <Stat label="Method" value={String(r.calibration_report.calibration_method ?? "—")} />
                  <Stat label="Calibrator version" value={`v${r.calibration_report.calibration_version ?? 0}`} />
                  <Stat label="Trades evaluated" value={String(r.calibration_report.samples ?? 0)} />
                  <Stat label="Execution floor" value={`≥${((r.calibration_report.min_calibrated_prob ?? 0) * 100).toFixed(0)}% win prob`} />
                </div>

                <Tbl
                  cols={["Metric", "Before (raw confidence)", "After (calibrated)", "Change"]}
                  rows={[
                    ["Brier score (lower = better)", "brier_score"],
                    ["Expected Calibration Error (lower = better)", "ece"],
                    ["Log loss (lower = better)", "log_loss"],
                  ].map(([label, key]) => {
                    const before = r.calibration_report?.before?.[key as string];
                    const after = r.calibration_report?.after?.[key as string];
                    const diff = before !== undefined && after !== undefined ? after - before : undefined;
                    return [
                      label,
                      fmtNum(before, 4),
                      fmtNum(after, 4),
                      diff === undefined ? "—" : (
                        <span className={diff < 0 ? "text-emerald-400" : diff > 0 ? "text-red-400" : ""}>
                          {diff > 0 ? "+" : ""}{diff.toFixed(4)} {diff < 0 ? "(improved)" : diff > 0 ? "(worse)" : ""}
                        </span>
                      ),
                    ];
                  })}
                  testId="table-calibration"
                />

                <div>
                  <div className="text-[10px] font-mono uppercase tracking-wide text-muted-foreground mb-1">
                    Reliability diagram — predicted win probability vs what actually happened
                  </div>
                  <div className="h-56">
                    <ResponsiveContainer width="100%" height="100%">
                      <LineChart
                        data={(r.calibration_report.reliability_calibrated ?? []).map((b: any, i: number) => {
                          const rawBin = (r.calibration_report.reliability_raw ?? [])[i];
                          const mid = ((b.bin_low + b.bin_high) / 2) * 100;
                          return {
                            mid: `${mid.toFixed(0)}%`,
                            perfect: mid,
                            calibrated: b.count > 0 ? b.observed_rate * 100 : null,
                            raw: rawBin && rawBin.count > 0 ? rawBin.observed_rate * 100 : null,
                          };
                        })}
                      >
                        <CartesianGrid strokeDasharray="3 3" stroke="#3f3f46" />
                        <XAxis dataKey="mid" tick={{ fontSize: 10, fill: "#a1a1aa" }} label={{ value: "Predicted win probability", position: "insideBottom", offset: -2, fontSize: 10, fill: "#71717a" }} />
                        <YAxis tick={{ fontSize: 10, fill: "#a1a1aa" }} domain={[0, 100]} unit="%" />
                        <Tooltip
                          contentStyle={{ background: "#18181b", border: "1px solid #3f3f46", fontSize: 11, fontFamily: "monospace" }}
                          formatter={(v: any, name: any) => [v === null || v === undefined ? "—" : `${Number(v).toFixed(1)}%`, name]}
                        />
                        <Legend wrapperStyle={{ fontSize: 11, fontFamily: "monospace" }} />
                        <Line type="monotone" dataKey="perfect" name="Perfect calibration" stroke="#52525b" strokeDasharray="6 4" dot={false} strokeWidth={1} />
                        <Line type="monotone" dataKey="raw" name="Raw confidence" stroke="#f59e0b" dot={{ r: 2 }} strokeWidth={1.5} connectNulls />
                        <Line type="monotone" dataKey="calibrated" name="Calibrated" stroke="#34d399" dot={{ r: 2 }} strokeWidth={1.5} connectNulls />
                      </LineChart>
                    </ResponsiveContainer>
                  </div>
                  <div className="text-[10px] font-mono text-muted-foreground mt-1">
                    Closer to the dashed line = better. Points show the actual win rate of trades in each predicted-probability bucket.
                  </div>
                </div>

                <div>
                  <div className="text-[10px] font-mono uppercase tracking-wide text-muted-foreground mb-1">
                    Per-window calibrators (each fitted only on trades exited before its test window — no lookahead)
                  </div>
                  <Tbl
                    cols={["Window", "Test start", "Method", "Training samples", "Version"]}
                    rows={(r.calibration_report.windows ?? []).map((w: any) => [
                      w.window, w.test_start, w.method, w.training_samples, `v${w.version}`,
                    ])}
                    testId="table-calibration-windows"
                  />
                </div>
                <div className="text-[10px] font-mono text-muted-foreground">{r.calibration_report.safety}</div>
              </div>
            ) : (
              <div className="text-xs font-mono text-muted-foreground" data-testid="text-no-calibration">
                No calibration data — run a validation to generate the calibration report.
              </div>
            )}
          </Section>

          {/* Phase 2 — Adaptive strategy selection */}
          <Section title="Strategy Intelligence — Adaptive Strategy Selection">
            {r.strategy_intelligence && (r.strategy_intelligence.ranking ?? []).length > 0 ? (
              <div className="space-y-4" data-testid="strategy-intelligence">
                <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                  <Stat label="Current regime" value={String(r.strategy_intelligence.current_regime ?? "—")} />
                  <Stat label="Completed trades learned from" value={String(r.strategy_intelligence.total_completed_trades ?? 0)} />
                  <Stat label="Strategies enabled" value={`${(r.strategy_intelligence.ranking ?? []).filter((x: any) => x.enabled).length} of ${(r.strategy_intelligence.ranking ?? []).length}`} />
                  <Stat label="Max per strategy" value="40% of allocation" />
                </div>

                <div>
                  <div className="text-[10px] font-mono uppercase tracking-wide text-muted-foreground mb-1">
                    Strategy ranking for the current regime ({String(r.strategy_intelligence.current_regime ?? "")}) — losers are disabled with a reason
                  </div>
                  <Tbl
                    cols={["#", "Strategy", "Status", "Score", "Allocation", "Rolling PF", "Rolling expectancy", "Win rate", "Trades", "Why"]}
                    rows={(r.strategy_intelligence.ranking ?? []).map((s: any) => [
                      s.rank,
                      s.strategy_id,
                      s.enabled ? (
                        <span className="text-emerald-400">ENABLED</span>
                      ) : (
                        <span className="text-red-400">DISABLED</span>
                      ),
                      fmtNum(s.score, 1),
                      s.enabled ? `${fmtNum(s.allocation_pct, 1)}%` : "0%",
                      fmtNum(s.rolling_profit_factor, 2),
                      s.rolling_expectancy_pct === null || s.rolling_expectancy_pct === undefined ? "—" : `${Number(s.rolling_expectancy_pct) > 0 ? "+" : ""}${Number(s.rolling_expectancy_pct).toFixed(2)}%`,
                      s.overall?.win_rate === null || s.overall?.win_rate === undefined ? "—" : `${Number(s.overall.win_rate).toFixed(0)}%`,
                      s.overall?.trade_count ?? 0,
                      <span className="whitespace-normal text-[10px]">{s.reason}</span>,
                    ])}
                    testId="table-strategy-ranking"
                  />
                </div>

                <div>
                  <div className="text-[10px] font-mono uppercase tracking-wide text-muted-foreground mb-1">
                    Strategy × regime matrix — profit factor (trades) per market regime, from completed trades only
                  </div>
                  <Tbl
                    cols={["Strategy", ...["Bullish", "Bearish", "Neutral Bullish", "Neutral Bearish", "High Volatility", "Low Volatility", "Sideways"]]}
                    rows={Object.entries(r.strategy_intelligence.matrix ?? {}).map(([sid, m]: [string, any]) => [
                      sid,
                      ...["Bullish", "Bearish", "Neutral Bullish", "Neutral Bearish", "High Volatility", "Low Volatility", "Sideways"].map((reg) => {
                        const rm = m?.by_regime?.[reg];
                        if (!rm || !rm.trade_count) return "—";
                        const pf = rm.profit_factor;
                        return (
                          <span className={pf !== null && pf !== undefined ? (pf >= 1 ? "text-emerald-400" : "text-red-400") : ""}>
                            {pf === null || pf === undefined ? "—" : Number(pf).toFixed(2)} ({rm.trade_count})
                          </span>
                        );
                      }),
                    ])}
                    testId="table-strategy-regime-matrix"
                  />
                </div>

                <div>
                  <div className="text-[10px] font-mono uppercase tracking-wide text-muted-foreground mb-1">
                    Per-window selection (each window learns only from trades completed before it; selection adapts as out-of-sample trades close)
                  </div>
                  <Tbl
                    cols={["Window", "Dominant regime", "OOS trades learned", "Enabled strategies (rank order)", "Disabled", "Eligible under Phase 2A gates"]}
                    rows={(r.strategy_intelligence.windows ?? []).map((w: any) => [
                      w.window,
                      w.dominant_regime,
                      w.oos_trades_learned,
                      (w.ranking ?? []).filter((x: any) => x.enabled).map((x: any) => x.strategy_id).join(", ") || "—",
                      (w.ranking ?? []).filter((x: any) => !x.enabled).map((x: any) => x.strategy_id).join(", ") || "—",
                      w.gated_cash_only
                        ? <span className="text-amber-400">CASH ONLY</span>
                        : ((w.gated_ranking ?? []).filter((x: any) => x.eligible).map((x: any) => x.strategy_id).join(", ") || "—"),
                    ])}
                    testId="table-strategy-windows"
                  />
                </div>

                {r.strategy_intelligence.gated && (
                  <div>
                    <div className="text-[10px] font-mono uppercase tracking-wide text-muted-foreground mb-1">
                      Phase 2A corrected policy (analysis only) — hard gates, shrunk metrics, edge-proportional allocation; unallocated capital stays in cash
                    </div>
                    <Tbl
                      cols={["#", "Strategy", "Status", "PF (raw→adj)", "Expectancy (raw→adj)", "Sample", "Evidence", "Allocation", "Why"]}
                      rows={(r.strategy_intelligence.gated.ranking ?? []).map((s: any) => [
                        s.rank,
                        s.strategy_id,
                        s.eligible
                          ? <span className="text-emerald-400 text-[10px]">{s.status}</span>
                          : <span className={`text-[10px] ${s.status === "WATCHLIST" ? "text-amber-400" : "text-red-400"}`}>{s.status}</span>,
                        `${fmtNum(s.raw_profit_factor, 2)} → ${fmtNum(s.adjusted_profit_factor, 2)}`,
                        `${fmtNum(s.raw_expectancy_pct, 2)}% → ${fmtNum(s.adjusted_expectancy_pct, 2)}%`,
                        s.sample ?? 0,
                        <span className="text-[10px]">{s.evidence_level}</span>,
                        s.eligible ? `${fmtNum(s.final_allocation_pct, 1)}%` : "0%",
                        <span className="whitespace-normal text-[10px]">{s.reason}</span>,
                      ])}
                      testId="table-strategy-gated-ranking"
                    />
                    <div className="text-[10px] font-mono text-muted-foreground mt-1">
                      {r.strategy_intelligence.gated.cash_only
                        ? "No strategy passes the gates in the current regime — the corrected policy would hold 100% cash."
                        : `Cash under the corrected policy: ${fmtNum(r.strategy_intelligence.gated.cash_pct, 1)}% (per-strategy cap 40%, never relaxed).`}
                    </div>
                  </div>
                )}

                <div className="text-[10px] font-mono text-muted-foreground">{r.strategy_intelligence.note}</div>
              </div>
            ) : (
              <div className="text-xs font-mono text-muted-foreground" data-testid="text-no-strategy-intelligence">
                No strategy intelligence data — run a validation to generate the adaptive strategy selection report.
              </div>
            )}
          </Section>

          {/* Recommendation outcomes */}
          <Section title={`Recommendation Outcomes (${r.recommendations_issued ?? 0} issued)`}>
            <Tbl
              cols={["Type", "Issued", "1d", "3d", "5d", "10d", "20d", "Success", "Losses prevented", "Avg MAE", "Avg MFE"]}
              rows={(r.recommendation_outcomes ?? []).map((o: any) => [
                o.recommendation, o.issued,
                fmtPct(o.fwd_return_1d), fmtPct(o.fwd_return_3d), fmtPct(o.fwd_return_5d),
                fmtPct(o.fwd_return_10d), fmtPct(o.fwd_return_20d),
                `${fmtNum(o.win_rate, 1)}%`,
                o.losses_prevented === null || o.losses_prevented === undefined
                  ? "—"
                  : `${o.losses_prevented} (${fmtNum(o.loss_prevention_rate, 1)}%)`,
                fmtPct(o.avg_mae_pct), fmtPct(o.avg_mfe_pct),
              ])}
              testId="table-outcomes"
            />
            <div className="text-[10px] font-mono text-muted-foreground mt-2">
              Forward returns measured 1–20 trading days after each recommendation. For WATCH/AVOID,
              "success" means the stock did NOT rise (the model correctly kept you out).
            </div>
          </Section>

          {/* Cost breakdown */}
          <Section title="Execution Cost Impact" defaultOpen={false}>
            <Tbl
              cols={["Component", "Amount"]}
              rows={Object.entries(r.cost_breakdown ?? {})
                .filter(([k]) => !["gross_pnl", "net_pnl", "cost_drag"].includes(k))
                .map(([k, v]) => [k.replace(/_/g, " "), fmtINR(v as number)])}
              testId="table-costs"
            />
            <div className="text-xs font-mono mt-2">
              Gross P&amp;L {fmtINR(r.cost_breakdown?.gross_pnl)} → Net {fmtINR(r.cost_breakdown?.net_pnl)}{" "}
              <span className="text-amber-400">(costs &amp; slippage: {fmtINR(r.cost_breakdown?.cost_drag)})</span>
            </div>
          </Section>

          {/* Stability */}
          <Section title="Stability & Concentration" defaultOpen={false}>
            {(r.stability?.concentration_flags ?? []).length > 0 ? (
              <div className="space-y-1 mb-3">
                {(r.stability.concentration_flags as string[]).map((f, i) => (
                  <div key={i} className="flex items-center gap-2 text-xs font-mono text-amber-400 bg-amber-500/10 border border-amber-500/30 rounded px-2 py-1.5">
                    <AlertTriangle className="h-3 w-3 flex-shrink-0" /> {f}
                  </div>
                ))}
              </div>
            ) : (
              <div className="text-xs font-mono text-emerald-400 mb-3 flex items-center gap-2">
                <ShieldCheck className="h-3.5 w-3.5" /> No excessive profit concentration detected.
              </div>
            )}
            <div className="grid md:grid-cols-2 gap-4">
              {[["By market regime", r.stability?.by_regime], ["By year", r.stability?.by_year],
                ["By strategy", r.stability?.by_strategy], ["By holding period", r.stability?.by_holding_period]]
                .map(([title, groups]: any) => (
                  <div key={title}>
                    <div className="text-[10px] font-mono uppercase tracking-wide text-muted-foreground mb-1">{title}</div>
                    <Tbl
                      cols={["Group", "Trades", "Net P&L", "Win rate"]}
                      rows={(groups ?? []).map((g: any) => [
                        g.group, g.trades,
                        <span className={pnlClass(g.net_pnl)}>{fmtINR(g.net_pnl)}</span>,
                        `${fmtNum(g.win_rate, 1)}%`,
                      ])}
                    />
                  </div>
                ))}
            </div>
          </Section>

          {/* Exports */}
          <Section title="CSV Exports" defaultOpen={false}>
            <div className="flex flex-wrap gap-2">
              {[
                ["report", "Complete validation report"],
                ["trades", "All simulated trades"],
                ["windows", "Window-by-window metrics"],
                ["calibration", "Confidence calibration"],
                ["costs", "Cost breakdown"],
              ].map(([kind, label]) => (
                <a key={kind} href={`${API_BASE}/walk-forward/export/${kind}`} download>
                  <Button variant="outline" size="sm" className="font-mono text-xs" data-testid={`button-export-${kind}`}>
                    <Download className="h-3.5 w-3.5 mr-1.5" /> {label}
                  </Button>
                </a>
              ))}
            </div>
          </Section>
        </>
      )}

      {!hasResult && !running && (
        <Card>
          <CardContent className="py-10 text-center text-sm font-mono text-muted-foreground" data-testid="text-no-result">
            No validation results yet. Configure a run above and press
            &nbsp;<span className="text-foreground">Run Walk-Forward Validation</span>.
          </CardContent>
        </Card>
      )}
    </div>
  );
}
