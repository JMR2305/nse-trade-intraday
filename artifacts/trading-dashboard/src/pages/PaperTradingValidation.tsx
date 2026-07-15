/**
 * PaperTradingValidation.tsx — Phase 16: Paper Trading Validation & Strategy Proving
 *
 * Read-only validation dashboard: overall validation score, strategy scorecard,
 * confidence/regime/sector/AI validation, trade review, weekly & monthly reports,
 * advisory recommendations, failure/success analysis, validation timeline,
 * automated bug detection, and export downloads.
 *
 * PAPER TRADING / RESEARCH ONLY. All recommendations are advisory —
 * nothing is ever auto-applied. Honest "Insufficient Data" markers throughout.
 */
import { useState, useEffect, useCallback } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Loader2, RefreshCw, Download, ShieldCheck, AlertTriangle, CheckCircle2,
  XCircle, ClipboardCheck, TrendingUp, TrendingDown, Bug, FileText, Brain,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { API_BASE } from "@/lib/api";
import { useToast } from "@/hooks/use-toast";

/* eslint-disable @typescript-eslint/no-explicit-any */

const LABEL = "PAPER TRADING VALIDATION — RESEARCH ONLY";

async function safeJson(path: string, init?: RequestInit): Promise<any> {
  const resp = await fetch(`${API_BASE}${path}`, init);
  const text = await resp.text();
  if (!text.trim()) throw new Error(`Empty response from ${path} (HTTP ${resp.status})`);
  let data: any;
  try { data = JSON.parse(text); } catch { throw new Error(`Invalid JSON from ${path}`); }
  if (!resp.ok) throw new Error(String(data?.error ?? `HTTP ${resp.status}`));
  return data;
}

function na(v: any, suffix = "") {
  if (v === null || v === undefined || v === "") return "Insufficient Data";
  if (typeof v === "number" && (!isFinite(v) || isNaN(v))) return "Insufficient Data";
  if (typeof v === "number") return `${+v.toFixed(2)}${suffix}`;
  return String(v);
}

const STATUS_CLS: Record<string, string> = {
  PROVEN: "text-emerald-400 border-emerald-700",
  PROMISING: "text-sky-400 border-sky-700",
  NEUTRAL: "text-zinc-400 border-zinc-700",
  UNDERPERFORMING: "text-amber-400 border-amber-700",
  FAILING: "text-red-400 border-red-700",
  "INSUFFICIENT DATA": "text-zinc-500 border-zinc-700",
};

function Stat({ label, value, cls }: { label: string; value: any; cls?: string }) {
  return (
    <div className="rounded border border-zinc-800 bg-zinc-900/50 p-2">
      <div className="text-[10px] uppercase tracking-wide text-zinc-500">{label}</div>
      <div className={cn("text-sm font-mono", cls ?? "text-zinc-200")}>{value}</div>
    </div>
  );
}

function SectionCard({ title, icon: Icon, children }: any) {
  return (
    <Card className="border-zinc-800 bg-zinc-950">
      <CardHeader className="py-3">
        <CardTitle className="flex items-center gap-2 text-sm text-zinc-200">
          <Icon className="h-4 w-4 text-sky-400" /> {title}
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-2 text-xs">{children}</CardContent>
    </Card>
  );
}

function MiniTable({ headers, rows }: { headers: string[]; rows: any[][] }) {
  if (!rows.length) return <div className="text-zinc-500 font-mono text-[11px]">Insufficient Data</div>;
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

const EXPORT_FILES = [
  "Validation_Report.pdf", "Validation_Report.xlsx", "Validation_Report.csv",
  "Strategy_Scorecard.csv", "Trade_Review.csv", "AI_Recommendations.csv",
];

export default function PaperTradingValidation() {
  const { toast } = useToast();
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [d, setD] = useState<Record<string, any>>({});
  const [exporting, setExporting] = useState(false);
  const [exportReady, setExportReady] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const all = await safeJson("/phase16/all");
      setD(all);
    } catch (e: any) {
      setError(e?.message ?? String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  const runExport = async () => {
    setExporting(true);
    try {
      const r = await safeJson("/phase16/export", { method: "POST" });
      setExportReady(true);
      toast({ title: "Exports generated", description: `${r.files?.length ?? 0} files ready to download.` });
      if (r.warnings?.length) toast({ title: "Export warnings", description: r.warnings.join("; ") });
    } catch (e: any) {
      toast({ title: "Export failed", description: e?.message ?? String(e), variant: "destructive" });
    } finally {
      setExporting(false);
    }
  };

  const o = d.overview, t = d.timeline, ai = d.ai, bugs = d.bugs;

  return (
    <div className="space-y-4 p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h1 className="text-lg font-semibold text-zinc-100 flex items-center gap-2">
            <ClipboardCheck className="h-5 w-5 text-sky-400" /> Paper Trading Validation
          </h1>
          <Badge variant="outline" className="mt-1 text-[10px] text-amber-400 border-amber-700">{LABEL}</Badge>
        </div>
        <div className="flex gap-2">
          <Button size="sm" variant="outline" onClick={() => void load()} disabled={loading}>
            {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
            <span className="ml-1">Refresh</span>
          </Button>
          <Button size="sm" onClick={() => void runExport()} disabled={exporting}>
            {exporting ? <Loader2 className="h-4 w-4 animate-spin" /> : <Download className="h-4 w-4" />}
            <span className="ml-1">Generate Exports</span>
          </Button>
        </div>
      </div>

      {error && (
        <div className="flex items-start gap-2 rounded border border-red-800 bg-red-950/40 p-2 text-xs text-red-300">
          <AlertTriangle className="h-4 w-4 shrink-0 mt-0.5" /> {error}
        </div>
      )}

      {loading && !o ? (
        <div className="flex items-center gap-2 text-zinc-400 text-sm p-8 justify-center">
          <Loader2 className="h-5 w-5 animate-spin" /> Loading validation data…
        </div>
      ) : (
        <>
          {o && (
            <SectionCard title="Validation Overview" icon={ShieldCheck}>
              <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-6 gap-2">
                <Stat label="Validation Score" value={na(o.overall_validation_score, "/100")} cls="text-sky-300" />
                <Stat label="Maturity" value={na(o.maturity)} />
                <Stat label="Trading Days" value={na(o.trading_days_completed)} />
                <Stat label="Completed Trades" value={na(o.completed_trades)} />
                <Stat label="Win Rate" value={na(o.win_rate_pct, "%")} />
                <Stat label="Profit Factor" value={na(o.profit_factor)} />
                <Stat label="Expectancy" value={na(o.expectancy)} />
                <Stat label="Max Drawdown" value={na(o.max_drawdown_pct, "%")} />
                <Stat label="Sharpe" value={na(o.sharpe_ratio)} />
                <Stat label="Avg Hold (days)" value={na(o.avg_holding_days)} />
                <Stat label="Capital Now" value={`₹${na(o.capital_now)}`} />
                <Stat label="Growth" value={na(o.capital_growth_pct, "%")}
                  cls={(o.capital_growth_pct ?? 0) >= 0 ? "text-emerald-400" : "text-red-400"} />
              </div>
              {o.note && <div className="text-[11px] text-amber-400">{o.note}</div>}
            </SectionCard>
          )}

          {d.scorecard && (
            <SectionCard title="Strategy Scorecard (advisory — nothing is auto-disabled)" icon={TrendingUp}>
              <MiniTable
                headers={["Strategy", "Trades", "Win %", "PF", "Avg Ret %", "Status", "Recommendation"]}
                rows={(d.scorecard.strategies ?? []).map((s: any) => [
                  s.strategy, s.trades, na(s.win_rate_pct), na(s.profit_factor), na(s.avg_return_pct),
                  <Badge key="b" variant="outline" className={cn("text-[10px]", STATUS_CLS[s.status] ?? "")}>{s.status}</Badge>,
                  s.recommendation,
                ])}
              />
              {d.scorecard.note && <div className="text-[11px] text-amber-400">{d.scorecard.note}</div>}
            </SectionCard>
          )}

          <div className="grid gap-4 lg:grid-cols-2">
            {d.confidence && (
              <SectionCard title="Confidence Validation" icon={Brain}>
                <MiniTable
                  headers={["Band", "Trades", "Win %", "Avg Ret %"]}
                  rows={(d.confidence.bands ?? []).map((b: any) => [b.band, b.trades, na(b.win_rate_pct), na(b.avg_return_pct)])}
                />
                <div className="text-[11px] text-zinc-400">Verdict: {na(d.confidence.verdict)}</div>
              </SectionCard>
            )}
            {d.regimes && (
              <SectionCard title="Market Regime Validation" icon={TrendingUp}>
                <MiniTable
                  headers={["Regime", "Trades", "Win %", "Avg Ret %", "Verdict"]}
                  rows={(d.regimes.regimes ?? []).map((r: any) => [r.regime, r.trades, na(r.win_rate_pct), na(r.avg_return_pct), r.verdict])}
                />
              </SectionCard>
            )}
            {d.sectors && (
              <SectionCard title="Sector Validation" icon={TrendingUp}>
                <MiniTable
                  headers={["Sector", "Trades", "Win %", "Avg Ret %"]}
                  rows={(d.sectors.sectors ?? []).filter((s: any) => s.trades > 0)
                    .map((s: any) => [s.sector, s.trades, na(s.win_rate_pct), na(s.avg_return_pct)])}
                />
              </SectionCard>
            )}
            {ai && (
              <SectionCard title="AI Decision Validation" icon={Brain}>
                <div className="grid grid-cols-3 gap-2">
                  <Stat label="BUY recs" value={na(ai.buy_recommendations)} />
                  <Stat label="WATCH recs" value={na(ai.watch_recommendations)} />
                  <Stat label="IGNORE recs" value={na(ai.ignore_recommendations)} />
                  <Stat label="Executed" value={na(ai.executed_recommendations)} />
                  <Stat label="Correct BUY %" value={na(ai.correct_buy_pct)} />
                  <Stat label="Correct EXIT %" value={na(ai.correct_exit_pct)} />
                </div>
                {ai.note && <div className="text-[11px] text-amber-400">{ai.note}</div>}
              </SectionCard>
            )}
          </div>

          {d.trades && (
            <SectionCard title={`Trade Review (${d.trades.count ?? 0} completed)`} icon={FileText}>
              {(d.trades.trades ?? []).map((tr: any, i: number) => (
                <div key={i} className="rounded border border-zinc-800 p-2 space-y-1">
                  <div className="flex flex-wrap items-center gap-2 font-mono text-[11px]">
                    <span className="text-zinc-100 font-semibold">{tr.symbol}</span>
                    <span className={cn(tr.pnl >= 0 ? "text-emerald-400" : "text-red-400")}>
                      {tr.pnl >= 0 ? "+" : ""}{na(tr.pnl)} ({na(tr.pnl_pct, "%")})
                    </span>
                    <Badge variant="outline" className="text-[10px]">{tr.strategy}</Badge>
                    <Badge variant="outline" className="text-[10px]">{tr.market_regime}</Badge>
                    <span className="text-zinc-500">conf {na(tr.confidence)}</span>
                    <span className="text-zinc-500">exit: {tr.exit_reason}</span>
                    <span className="text-zinc-500">{na(tr.holding_period_days)}d</span>
                  </div>
                  <div className="text-[11px] text-zinc-400">{tr.ai_explanation}</div>
                  {tr.lessons_learned?.length > 0 && (
                    <div className="text-[11px] text-sky-300">Lessons: {tr.lessons_learned.join("; ")}</div>
                  )}
                </div>
              ))}
              {!(d.trades.trades ?? []).length && <div className="text-zinc-500">No completed trades yet.</div>}
            </SectionCard>
          )}

          <div className="grid gap-4 lg:grid-cols-2">
            {d.weekly && (
              <SectionCard title="Weekly Report" icon={FileText}>
                <MiniTable headers={["Metric", "Value"]}
                  rows={Object.entries(d.weekly.stats ?? {}).map(([k, v]) => [k, na(v)])} />
                <div className="text-[11px] text-zinc-400">
                  Best strategy: {na(d.weekly.best_strategy)} · Worst: {na(d.weekly.worst_strategy)} ·
                  Best sector: {na(d.weekly.best_sector)}
                </div>
                {d.weekly.note && <div className="text-[11px] text-amber-400">{d.weekly.note}</div>}
              </SectionCard>
            )}
            {d.monthly && (
              <SectionCard title="Monthly Report" icon={FileText}>
                <MiniTable headers={["Metric", "Value"]}
                  rows={Object.entries(d.monthly.stats ?? {}).map(([k, v]) => [k, na(v)])} />
                <div className="text-[11px] text-zinc-400">
                  Best strategy: {na(d.monthly.best_strategy)} · Worst: {na(d.monthly.worst_strategy)} ·
                  Best sector: {na(d.monthly.best_sector)}
                </div>
                {d.monthly.note && <div className="text-[11px] text-amber-400">{d.monthly.note}</div>}
              </SectionCard>
            )}
            {d.successes && (
              <SectionCard title="Success Analysis" icon={CheckCircle2}>
                <div className="grid grid-cols-2 gap-2">
                  <Stat label="Winning Trades" value={na(d.successes.winning_trades)} cls="text-emerald-400" />
                  <Stat label="Best Confidence Range" value={na(d.successes.best_confidence_range)} />
                </div>
                <div className="text-[11px] text-zinc-400">
                  Common regimes: {(d.successes.common_regimes ?? []).join(", ") || "Insufficient Data"}
                </div>
                <div className="text-[11px] text-zinc-400">
                  Common indicators: {(d.successes.common_indicators ?? []).join(", ") || "Insufficient Data"}
                </div>
              </SectionCard>
            )}
            {d.failures && (
              <SectionCard title="Failure Analysis" icon={TrendingDown}>
                <div className="grid grid-cols-2 gap-2">
                  <Stat label="Losing Trades" value={na(d.failures.losing_trades)} cls="text-red-400" />
                  <Stat label="Common Exit" value={na(d.failures.most_common_exit)} />
                </div>
                <MiniTable headers={["Group", "Losses", "Total PnL"]}
                  rows={[
                    ...(d.failures.by_strategy ?? []).map((g: any) => [`strategy: ${g.group}`, na(g.losses), na(g.total_pnl)]),
                    ...(d.failures.by_sector ?? []).map((g: any) => [`sector: ${g.group}`, na(g.losses), na(g.total_pnl)]),
                  ]} />
              </SectionCard>
            )}
          </div>

          {d.recommendations && (
            <SectionCard title="AI Improvement Recommendations (advisory only — never auto-applied)" icon={Brain}>
              {(d.recommendations.recommendations ?? []).map((r: any, i: number) => (
                <div key={i} className="rounded border border-zinc-800 p-2 text-[11px]">
                  <span className="text-sky-300 font-mono">[{r.type}] {r.target}</span>
                  <div className="text-zinc-300">{r.detail}</div>
                  <div className="text-zinc-500">Suggestion: {r.suggestion}</div>
                </div>
              ))}
              {d.recommendations.note && <div className="text-[11px] text-amber-400">{d.recommendations.note}</div>}
            </SectionCard>
          )}

          <div className="grid gap-4 lg:grid-cols-2">
            {t && (
              <SectionCard title="Validation Timeline" icon={ShieldCheck}>
                <div className="grid grid-cols-2 gap-2">
                  <Stat label="Trading Days" value={`${na(t.trading_days)} / ${na(t.trading_days_goal)}`} />
                  <Stat label="Completed Trades" value={`${na(t.completed_trades)} / ${na(t.completed_trades_goal)}`} />
                  <Stat label="Confidence Calibration" value={na(t.confidence_calibration_pct)} />
                  <Stat label="Strategy Stability" value={na(t.strategy_stability_pct)} />
                  <Stat label="Production Readiness" value={na(t.production_readiness_pct, "%")} cls="text-sky-300" />
                  <Stat label="Maturity" value={na(t.maturity)} />
                </div>
              </SectionCard>
            )}
            {bugs && (
              <SectionCard title="Automated Bug Detection" icon={Bug}>
                <div className="flex items-center gap-2 text-[11px]">
                  {bugs.verdict === "PASS" || bugs.verdict === "HEALTHY"
                    ? <CheckCircle2 className="h-4 w-4 text-emerald-400" />
                    : <XCircle className="h-4 w-4 text-amber-400" />}
                  <span className="text-zinc-200 font-mono">{bugs.verdict}</span>
                  <span className="text-zinc-500">({bugs.checks_performed} checks)</span>
                </div>
                {(bugs.issues ?? []).map((i: any, k: number) => (
                  <div key={k} className="text-[11px] text-amber-300 font-mono">[{i.severity}] {i.check}: {i.detail}</div>
                ))}
                {(bugs.not_checkable ?? []).length > 0 && (
                  <div className="text-[11px] text-zinc-500">
                    Not checkable server-side: {(bugs.not_checkable ?? []).join(", ")}
                  </div>
                )}
              </SectionCard>
            )}
          </div>

          <SectionCard title="Exports" icon={Download}>
            <div className="text-[11px] text-zinc-400">
              Click "Generate Exports" above, then download. Files: PDF / XLSX / CSV validation report,
              strategy scorecard, trade review, and AI recommendations.
            </div>
            <div className="flex flex-wrap gap-2">
              {EXPORT_FILES.map((f) => (
                <Button key={f} size="sm" variant="outline" disabled={!exportReady}
                  onClick={() => window.open(`${API_BASE}/phase16/export/${f}`, "_blank")}>
                  <Download className="h-3 w-3 mr-1" /> {f}
                </Button>
              ))}
            </div>
          </SectionCard>
        </>
      )}
    </div>
  );
}
