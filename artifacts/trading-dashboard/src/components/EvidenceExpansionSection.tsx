/**
 * EvidenceExpansionSection.tsx — Phase 3A.5 Evidence Expansion display.
 *
 * ANALYSIS ONLY — never changes live decisions, thresholds, or portfolio
 * behaviour. Displays evidence quantity, regime coverage, stability checks,
 * calibration comparison, and pass/inconclusive/fail verdict.
 */
import { useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  ShieldCheck, AlertTriangle, XCircle, Download,
  FlaskConical, ChevronDown, ChevronRight, Info,
} from "lucide-react";
import { cn } from "@/lib/utils";

/* ── types ──────────────────────────────────────────────────────────────── */
interface EvidenceReport {
  phase: string;
  phase_label: string;
  n_trades: number;
  n_windows: number;
  date_coverage: {
    earliest_test_date: string | null;
    latest_test_date: string | null;
    years_covered: number | null;
  };
  total_pnl: number;
  expectancy_per_trade: number;
  verdict: {
    verdict: "PASS" | "INCONCLUSIVE" | "FAIL" | "INSUFFICIENT_EVIDENCE";
    summary: string;
    criteria: Array<{
      name: string;
      threshold: number;
      preferred: number;
      observed: number;
      passed: boolean;
    }>;
  };
  regime_coverage: {
    by_regime: Array<{
      regime: string;
      trades: number;
      pct_of_total: number;
      underrepresented: boolean;
    }>;
    regimes_covered: number;
    regimes_total_canonical: number;
    warnings: string[];
  };
  stability: {
    window_count: number;
    profitable_windows: number;
    profitable_windows_pct: number;
    median_return_pct: number | null;
    median_profit_factor: number | null;
    best_window: { label: string; test_start: string; test_end: string; return_pct: number; trades: number } | null;
    worst_window: { label: string; test_start: string; test_end: string; return_pct: number; trades: number } | null;
    return_dispersion: number | null;
    windows: Array<{
      label: string; test_start: string; test_end: string;
      trades: number; return_pct: number; profit_factor: number; profitable: boolean;
    }>;
  };
  by_strategy: Array<{ group: string; trades: number; net_pnl: number; win_rate: number; expectancy: number; median_return_pct: number }>;
  by_year: Array<{ group: string; trades: number; net_pnl: number; win_rate: number; expectancy: number; median_return_pct: number }>;
  by_sector: Array<{ group: string; trades: number; net_pnl: number; win_rate: number; expectancy: number; median_return_pct: number }>;
  by_holding_period: Array<{ group: string; trades: number; net_pnl: number; win_rate: number; expectancy: number; median_return_pct: number }>;
  window_regime_map: Array<{ label: string; test_start: string; test_end: string; trades: number; dominant_regime: string; return_pct: number }>;
  calibration_comparison: {
    available: boolean;
    reason?: string;
    n_trades?: number;
    raw_brier_score?: number;
    calibrated_brier_score?: number;
    brier_improvement?: number;
    raw_ece?: number;
    calibrated_ece?: number;
    ece_improvement?: number;
    raw_log_loss?: number;
    calibrated_log_loss?: number;
    log_loss_improvement?: number;
    calibration_helps?: boolean;
    note?: string;
  };
  concentration_flags: string[];
  recommended_config_for_pass: { train_years: number; test_months: number; step_months: number; guidance: string };
  safety: string;
  error?: string;
}

interface Props {
  data: EvidenceReport | null | undefined;
  onDownload: (kind: string) => void;
}

/* ── small helpers ───────────────────────────────────────────────────────── */
const fmtINR = (v: number | null | undefined) =>
  v === undefined || v === null ? "—"
    : `₹${Number(v).toLocaleString("en-IN", { maximumFractionDigits: 0 })}`;
const fmtPct = (v: number | null | undefined, d = 1) =>
  v === undefined || v === null ? "—" : `${Number(v).toFixed(d)}%`;
const fmtN = (v: number | null | undefined, d = 2) =>
  v === undefined || v === null ? "—" : Number(v).toFixed(d);
const pnlCls = (v: number) => v > 0 ? "text-emerald-400" : v < 0 ? "text-red-400" : "";

const VERDICT_META: Record<string, { label: string; icon: React.ReactNode; cls: string; bg: string }> = {
  PASS: {
    label: "PASS",
    icon: <ShieldCheck className="h-4 w-4" />,
    cls: "text-emerald-300",
    bg: "bg-emerald-500/10 border-emerald-500/30",
  },
  INCONCLUSIVE: {
    label: "INCONCLUSIVE",
    icon: <Info className="h-4 w-4" />,
    cls: "text-amber-300",
    bg: "bg-amber-500/10 border-amber-500/30",
  },
  FAIL: {
    label: "FAIL",
    icon: <XCircle className="h-4 w-4" />,
    cls: "text-red-300",
    bg: "bg-red-500/10 border-red-500/30",
  },
  INSUFFICIENT_EVIDENCE: {
    label: "INSUFFICIENT EVIDENCE",
    icon: <AlertTriangle className="h-4 w-4" />,
    cls: "text-orange-300",
    bg: "bg-orange-500/10 border-orange-500/30",
  },
};

function Collapsible({ title, children, defaultOpen = true }: {
  title: string; children: React.ReactNode; defaultOpen?: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className="border border-zinc-700 rounded-md overflow-hidden">
      <button
        className="w-full flex items-center gap-2 px-3 py-2 text-xs font-mono font-semibold uppercase tracking-wide text-zinc-300 bg-zinc-800/60 hover:bg-zinc-800 transition-colors"
        onClick={() => setOpen(!open)}
      >
        {open ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
        {title}
      </button>
      {open && <div className="p-3">{children}</div>}
    </div>
  );
}

function MiniTable({
  cols, rows,
}: { cols: string[]; rows: Array<(string | number | React.ReactNode)[]> }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-[11px] font-mono">
        <thead>
          <tr>
            {cols.map((c) => (
              <th key={c} className="text-left text-[10px] text-muted-foreground uppercase tracking-wide pb-1 pr-3 border-b border-zinc-700">
                {c}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr key={i} className="border-b border-zinc-800 last:border-0">
              {row.map((cell, j) => (
                <td key={j} className="py-1 pr-3 align-top">{cell}</td>
              ))}
            </tr>
          ))}
          {rows.length === 0 && (
            <tr><td colSpan={cols.length} className="py-2 text-muted-foreground italic">No data</td></tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

function DistTable({ rows }: { rows: EvidenceReport["by_strategy"] }) {
  return (
    <MiniTable
      cols={["Group", "Trades", "Net P&L", "Win %", "Expect.", "Med Ret%"]}
      rows={rows.map((r) => [
        r.group,
        r.trades,
        <span className={pnlCls(r.net_pnl)}>{fmtINR(r.net_pnl)}</span>,
        fmtPct(r.win_rate),
        <span className={pnlCls(r.expectancy)}>{fmtINR(r.expectancy)}</span>,
        <span className={pnlCls(r.median_return_pct)}>{fmtPct(r.median_return_pct)}</span>,
      ])}
    />
  );
}

function ImprovementBadge({ val }: { val: number | undefined }) {
  if (val === undefined) return <span className="text-muted-foreground">—</span>;
  const better = val > 0;
  return (
    <span className={better ? "text-emerald-400" : val < 0 ? "text-red-400" : "text-zinc-400"}>
      {better ? "▼" : val < 0 ? "▲" : "="} {Math.abs(val).toFixed(4)}
    </span>
  );
}

/* ── main component ──────────────────────────────────────────────────────── */
export default function EvidenceExpansionSection({ data, onDownload }: Props) {
  if (!data) return null;

  if (data.error) {
    return (
      <Card>
        <CardHeader className="py-3">
          <CardTitle className="text-sm font-mono flex items-center gap-2">
            <FlaskConical className="h-4 w-4 text-orange-400" />
            Phase 3A.5 — Evidence Expansion
          </CardTitle>
        </CardHeader>
        <CardContent className="pt-0">
          <div className="text-xs font-mono text-red-400 bg-red-500/10 border border-red-500/30 rounded p-3">
            {data.error}
          </div>
        </CardContent>
      </Card>
    );
  }

  const vm = VERDICT_META[data.verdict?.verdict] ?? VERDICT_META["INCONCLUSIVE"];
  const cov = data.date_coverage;
  const stab = data.stability;
  const cal = data.calibration_comparison;

  return (
    <Card>
      <CardHeader className="py-3">
        <CardTitle className="text-sm font-mono flex items-center gap-2 flex-wrap">
          <FlaskConical className="h-4 w-4 text-violet-400" />
          Phase 3A.5 — Evidence Expansion
          <Badge variant="outline" className="text-[10px] font-mono text-violet-300 border-violet-500/40">
            ANALYSIS ONLY
          </Badge>
        </CardTitle>
      </CardHeader>
      <CardContent className="pt-0 space-y-4">

        {/* ── Verdict banner ─────────────────────────────────────────────── */}
        <div className={cn("flex items-start gap-3 rounded-md border p-3", vm.bg)}>
          <span className={cn("mt-0.5 flex-shrink-0", vm.cls)}>{vm.icon}</span>
          <div className="min-w-0">
            <div className={cn("text-xs font-mono font-bold mb-0.5", vm.cls)}>
              {vm.label}
            </div>
            <div className="text-[11px] font-mono text-zinc-300 leading-relaxed">
              {data.verdict?.summary}
            </div>
          </div>
        </div>

        {/* ── Key numbers ────────────────────────────────────────────────── */}
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
          {[
            ["OOS Trades", data.n_trades, ""],
            ["Windows", data.n_windows, ""],
            ["Date Range",
              cov.years_covered != null ? `${cov.years_covered}y` : "—", ""],
            ["Expectancy", fmtINR(data.expectancy_per_trade), pnlCls(data.expectancy_per_trade ?? 0)],
          ].map(([label, value, cls]) => (
            <div key={label as string} className="bg-zinc-800/50 rounded-md p-2.5">
              <div className="text-[10px] text-muted-foreground font-mono uppercase tracking-wide mb-0.5">{label}</div>
              <div className={cn("text-sm font-mono font-bold", cls as string || "text-foreground")}>{value as string}</div>
            </div>
          ))}
        </div>

        {cov.earliest_test_date && (
          <div className="text-[11px] font-mono text-muted-foreground">
            Test period: {cov.earliest_test_date} → {cov.latest_test_date}
          </div>
        )}

        {/* ── Sample adequacy criteria ───────────────────────────────────── */}
        <Collapsible title="Sample Adequacy Criteria">
          <div className="space-y-1">
            {(data.verdict?.criteria ?? []).map((c) => (
              <div
                key={c.name}
                className={cn(
                  "flex items-center gap-2 rounded px-2 py-1 text-[11px] font-mono",
                  c.passed ? "bg-emerald-500/8 text-zinc-300" : "bg-red-500/8 text-zinc-300"
                )}
              >
                {c.passed
                  ? <ShieldCheck className="h-3 w-3 text-emerald-400 flex-shrink-0" />
                  : <XCircle className="h-3 w-3 text-red-400 flex-shrink-0" />
                }
                <span className="flex-1">{c.name}</span>
                <span className={c.passed ? "text-emerald-400" : "text-red-400"}>
                  {c.observed}
                </span>
                <span className="text-muted-foreground text-[10px]">
                  (need ≥{c.threshold})
                </span>
              </div>
            ))}
          </div>
          {data.verdict?.verdict === "INSUFFICIENT_EVIDENCE" && (
            <div className="mt-3 bg-orange-500/8 border border-orange-500/30 rounded p-2.5 text-[11px] font-mono text-orange-300 space-y-1">
              <div className="font-semibold">Recommended config for 10-12 windows:</div>
              <div>train_years = {data.recommended_config_for_pass.train_years} · test_months = {data.recommended_config_for_pass.test_months} · step_months = {data.recommended_config_for_pass.step_months}</div>
              <div className="text-zinc-400">{data.recommended_config_for_pass.guidance}</div>
            </div>
          )}
        </Collapsible>

        {/* ── Regime coverage ────────────────────────────────────────────── */}
        <Collapsible title="Market Regime Coverage">
          {(data.regime_coverage?.warnings ?? []).length > 0 && (
            <div className="space-y-1 mb-3">
              {data.regime_coverage.warnings.map((w, i) => (
                <div key={i} className="flex items-start gap-2 text-[11px] font-mono text-amber-400 bg-amber-500/10 border border-amber-500/30 rounded px-2 py-1.5">
                  <AlertTriangle className="h-3 w-3 mt-0.5 flex-shrink-0" /> {w}
                </div>
              ))}
            </div>
          )}
          <div className="space-y-1.5">
            {(data.regime_coverage?.by_regime ?? []).map((r) => {
              const w = Math.max(1, r.pct_of_total);
              return (
                <div key={r.regime} className="flex items-center gap-2">
                  <div className="w-28 text-[11px] font-mono text-zinc-300 flex-shrink-0">{r.regime}</div>
                  <div className="flex-1 bg-zinc-800 rounded-full h-2 overflow-hidden">
                    <div
                      className={cn("h-2 rounded-full transition-all", r.underrepresented ? "bg-amber-500" : "bg-violet-500")}
                      style={{ width: `${Math.min(w, 100)}%` }}
                    />
                  </div>
                  <div className="w-12 text-right text-[11px] font-mono text-muted-foreground">{r.trades}</div>
                  <div className="w-10 text-right text-[11px] font-mono text-zinc-400">{r.pct_of_total}%</div>
                  {r.underrepresented && r.trades > 0 && (
                    <AlertTriangle className="h-3 w-3 text-amber-400 flex-shrink-0" />
                  )}
                  {r.trades === 0 && (
                    <XCircle className="h-3 w-3 text-red-500/50 flex-shrink-0" />
                  )}
                </div>
              );
            })}
          </div>
          <div className="mt-2 text-[10px] font-mono text-muted-foreground">
            {data.regime_coverage.regimes_covered} of {data.regime_coverage.regimes_total_canonical} canonical regimes covered
          </div>
        </Collapsible>

        {/* ── Stability checks ───────────────────────────────────────────── */}
        <Collapsible title="Stability Checks (Per-Window)">
          <div className="grid grid-cols-2 sm:grid-cols-3 gap-2 mb-3">
            {[
              ["Median Return", stab.median_return_pct != null ? fmtPct(stab.median_return_pct) : "—",
               pnlCls(stab.median_return_pct ?? 0)],
              ["Median Profit Factor", stab.median_profit_factor != null ? fmtN(stab.median_profit_factor, 3) : "—",
               pnlCls((stab.median_profit_factor ?? 1) - 1)],
              ["Profitable Windows", `${stab.profitable_windows}/${stab.window_count} (${fmtPct(stab.profitable_windows_pct)})`,
               pnlCls((stab.profitable_windows_pct ?? 0) - 50)],
              ["Return Dispersion", stab.return_dispersion != null ? fmtPct(stab.return_dispersion) : "—", ""],
              stab.best_window
                ? ["Best Window", `${stab.best_window.label} (${fmtPct(stab.best_window.return_pct)})`, "text-emerald-400"]
                : ["Best Window", "—", ""],
              stab.worst_window
                ? ["Worst Window", `${stab.worst_window.label} (${fmtPct(stab.worst_window.return_pct)})`, "text-red-400"]
                : ["Worst Window", "—", ""],
            ].map(([label, value, cls]) => (
              <div key={label as string} className="bg-zinc-800/50 rounded p-2">
                <div className="text-[10px] text-muted-foreground font-mono uppercase tracking-wide mb-0.5">{label}</div>
                <div className={cn("text-xs font-mono font-semibold", cls as string || "text-foreground")}>{value as string}</div>
              </div>
            ))}
          </div>
          {stab.windows.length > 0 && (
            <MiniTable
              cols={["Window", "Test Period", "Trades", "Return%", "Prof.Factor", "Profitable"]}
              rows={stab.windows.map((w) => [
                w.label,
                `${w.test_start}–${w.test_end}`,
                w.trades,
                <span className={pnlCls(w.return_pct)}>{fmtPct(w.return_pct)}</span>,
                <span className={pnlCls(w.profit_factor - 1)}>{fmtN(w.profit_factor, 3)}</span>,
                w.profitable
                  ? <span className="text-emerald-400">✓</span>
                  : <span className="text-red-400">✗</span>,
              ])}
            />
          )}
        </Collapsible>

        {/* ── Window → Regime map ────────────────────────────────────────── */}
        {data.window_regime_map.length > 0 && (
          <Collapsible title="Window → Dominant Regime" defaultOpen={false}>
            <MiniTable
              cols={["Window", "Test Period", "Trades", "Return%", "Dominant Regime"]}
              rows={data.window_regime_map.map((w) => [
                w.label,
                `${w.test_start}–${w.test_end}`,
                w.trades,
                <span className={pnlCls(w.return_pct)}>{fmtPct(w.return_pct)}</span>,
                w.dominant_regime,
              ])}
            />
          </Collapsible>
        )}

        {/* ── Trade distributions ────────────────────────────────────────── */}
        <Collapsible title="Trade Distributions" defaultOpen={false}>
          <div className="space-y-4">
            {(
              [
                ["By Strategy", data.by_strategy],
                ["By Year", data.by_year],
                ["By Sector", data.by_sector],
                ["By Holding Period", data.by_holding_period],
              ] as Array<[string, EvidenceReport["by_strategy"]]>
            ).map(([title, rows]) => (
              <div key={title}>
                <div className="text-[10px] font-mono uppercase tracking-wide text-muted-foreground mb-1.5">{title}</div>
                <DistTable rows={rows} />
              </div>
            ))}
          </div>
        </Collapsible>

        {/* ── Calibration comparison ─────────────────────────────────────── */}
        <Collapsible title="Calibration Comparison (Raw vs Calibrated)" defaultOpen={false}>
          {!cal.available ? (
            <div className="text-[11px] font-mono text-muted-foreground">{cal.reason}</div>
          ) : (
            <>
              {cal.calibration_helps === false && (
                <div className="mb-2 flex items-center gap-2 text-[11px] font-mono text-amber-400 bg-amber-500/10 border border-amber-500/30 rounded px-2 py-1.5">
                  <AlertTriangle className="h-3 w-3 flex-shrink-0" />
                  Calibration does not improve Brier score on this evidence set — consider re-fitting calibrator with more data
                </div>
              )}
              {cal.calibration_helps === true && (
                <div className="mb-2 flex items-center gap-2 text-[11px] font-mono text-emerald-400 bg-emerald-500/10 border border-emerald-500/30 rounded px-2 py-1.5">
                  <ShieldCheck className="h-3 w-3 flex-shrink-0" />
                  Calibration reduces prediction error on {cal.n_trades} OOS trades
                </div>
              )}
              <MiniTable
                cols={["Metric", "Raw", "Calibrated", "Improvement"]}
                rows={[
                  ["Brier Score ↓",
                   fmtN(cal.raw_brier_score, 4),
                   fmtN(cal.calibrated_brier_score, 4),
                   <ImprovementBadge val={cal.brier_improvement} />],
                  ["ECE ↓",
                   fmtN(cal.raw_ece, 4),
                   fmtN(cal.calibrated_ece, 4),
                   <ImprovementBadge val={cal.ece_improvement} />],
                  ["Log Loss ↓",
                   fmtN(cal.raw_log_loss, 4),
                   fmtN(cal.calibrated_log_loss, 4),
                   <ImprovementBadge val={cal.log_loss_improvement} />],
                ]}
              />
              <div className="mt-2 text-[10px] font-mono text-muted-foreground">{cal.note}</div>
            </>
          )}
        </Collapsible>

        {/* ── Concentration flags ────────────────────────────────────────── */}
        <Collapsible title="Concentration & Small-Sample Warnings" defaultOpen={data.concentration_flags.length > 0}>
          {data.concentration_flags.length === 0 ? (
            <div className="flex items-center gap-2 text-[11px] font-mono text-emerald-400">
              <ShieldCheck className="h-3.5 w-3.5" /> No excessive profit concentration detected.
            </div>
          ) : (
            <div className="space-y-1">
              {data.concentration_flags.map((f, i) => (
                <div key={i} className="flex items-start gap-2 text-[11px] font-mono text-amber-400 bg-amber-500/10 border border-amber-500/30 rounded px-2 py-1.5">
                  <AlertTriangle className="h-3 w-3 mt-0.5 flex-shrink-0" /> {f}
                </div>
              ))}
            </div>
          )}
        </Collapsible>

        {/* ── CSV exports ────────────────────────────────────────────────── */}
        <div>
          <div className="text-[10px] font-mono uppercase tracking-wide text-muted-foreground mb-2">
            Phase 3A.5 CSV Exports
          </div>
          <div className="flex flex-wrap gap-2">
            {([
              ["evidence_report", "Evidence report"],
              ["evidence_trades", "All evidence trades"],
            ] as [string, string][]).map(([kind, label]) => (
              <Button
                key={kind}
                variant="outline"
                size="sm"
                className="font-mono text-xs"
                data-testid={`button-export-${kind}`}
                onClick={() => onDownload(kind)}
              >
                <Download className="h-3.5 w-3.5 mr-1.5" /> {label}
              </Button>
            ))}
          </div>
        </div>

        {/* ── Safety disclaimer ──────────────────────────────────────────── */}
        <div className="text-[10px] font-mono text-muted-foreground border-t border-zinc-800 pt-2">
          {data.safety}
        </div>
      </CardContent>
    </Card>
  );
}
