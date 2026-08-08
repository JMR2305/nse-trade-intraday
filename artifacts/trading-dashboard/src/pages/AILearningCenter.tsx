/**
 * AILearningCenter.tsx — Phase 24: AI Learning & Continuous Improvement Engine.
 *
 * READ-ONLY · ADVISORY-ONLY dashboard over the permanent Trade Intelligence
 * store: lessons, mistakes/improvements, best/worst trades, confidence
 * calibration, risk-rule learning, strategy/sector rankings, time & regime
 * analysis, capital efficiency, the daily AI scorecard, recommendations
 * (manual approve/dismiss — intent only), and automated reports.
 */
import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Brain, RefreshCw, AlertTriangle, TrendingUp, TrendingDown, Shield,
  Award, Clock, FileText, CheckCircle2, XCircle, Lightbulb, Target,
} from "lucide-react";
import { apiJson } from "@/lib/api";

// ── Types (subset of the overview payload) ───────────────────────────────────
interface GroupStats {
  trades: number;
  win_rate: number | null;
  total_pnl: number | null;
  avg_return_pct: number | null;
  max_drawdown: number | null;
  profit_factor: number | null;
  expectancy: number | null;
  sharpe: number | null;
  sortino: number | null;
  capital_efficiency: number | null;
  avg_holding_minutes: number | null;
  confidence_accuracy: number | null;
  rank?: number;
  strategy?: string;
  sector?: string;
  bucket?: string;
}
interface Lessons {
  period: string;
  trades: number;
  stats: GroupStats | null;
  mistakes: string[];
  improvements: string[];
}
interface TradeSlim {
  trade_id: string; symbol: string; strategy: string | null; date: string | null;
  entry_price: number | null; exit_price: number | null; quantity: number | null;
  realized_pnl: number | null; exit_reason: string | null; confidence: number | null;
  mfe: number | null; mae: number | null;
}
interface RiskRule {
  rule: string; rejections: number; evaluated: number;
  correct_rejections: number; blocked_profitable: number;
  avg_later_move_pct: number | null; effectiveness: number | null; verdict: string;
}
interface CalBucket {
  bucket: string; predicted_confidence: number; trades: number;
  win_rate: number | null; calibration_error: number | null; status: string;
}
interface Overview {
  generated_at: string;
  trade_records: number;
  daily_lessons: Lessons; weekly_lessons: Lessons; monthly_lessons: Lessons;
  best_worst: { best: TradeSlim[]; worst: TradeSlim[] };
  calibration: { buckets: CalBucket[]; overall_calibration_error: number | null; total_trades: number };
  risk_learning: { rules: RiskRule[]; records_analysed: number };
  strategy_ranking: { items: GroupStats[] };
  sector_ranking: { items: GroupStats[]; summary: Record<string, string | undefined> };
  time_analysis: {
    hours: GroupStats[]; weekdays: GroupStats[]; regimes: GroupStats[];
    volatility_bands: GroupStats[];
    summary: Record<string, { best: string | null; worst: string | null }>;
  };
  scorecard: {
    date: string; scores: Record<string, number | null>; overall: number | null;
    strengths: string[]; weaknesses: string[]; trades_analysed: number;
  };
  capital_efficiency: number | null;
}
interface Recommendation {
  id: string; rec_date: string; status: string; decided_at: string | null;
  decision_note: string | null;
  record: { kind: string; title: string; detail: string };
}
interface Report {
  id: string; period: string; period_key: string;
  record: {
    performance: GroupStats | null; trades: number;
    mistakes: string[]; improvements: string[];
    expected_improvements: string[];
    scorecard: { overall: number | null };
  };
}

// ── Formatters ────────────────────────────────────────────────────────────────
const fmt = (v: unknown, dp = 2) =>
  v == null || isNaN(Number(v)) ? "—"
    : Number(v).toLocaleString("en-IN", { maximumFractionDigits: dp });
const fmtPct01 = (v: number | null) => (v == null ? "—" : `${(v * 100).toFixed(1)}%`);
const fmtRs = (v: number | null) => (v == null ? "—" : `₹${fmt(v, 0)}`);
const pnlColor = (v: number | null | undefined) =>
  (v ?? 0) >= 0 ? "text-emerald-400" : "text-rose-400";

// ── Small building blocks ─────────────────────────────────────────────────────
function Card({ title, icon, children }: { title: string; icon?: React.ReactNode; children: React.ReactNode }) {
  return (
    <div className="rounded-lg border border-slate-800 bg-slate-900/50 p-4">
      <div className="mb-3 flex items-center gap-2 text-sm font-semibold text-slate-200">
        {icon}{title}
      </div>
      {children}
    </div>
  );
}

function StatRow({ label, value, cls }: { label: string; value: string; cls?: string }) {
  return (
    <div className="flex justify-between py-0.5 text-xs">
      <span className="text-slate-400">{label}</span>
      <span className={cls ?? "text-slate-200"}>{value}</span>
    </div>
  );
}

function StatsBlock({ s }: { s: GroupStats | null }) {
  if (!s || !s.trades) return <div className="text-xs text-slate-500">No trades in this period yet.</div>;
  return (
    <div className="grid grid-cols-2 gap-x-6">
      <StatRow label="Trades" value={String(s.trades)} />
      <StatRow label="Win rate" value={fmtPct01(s.win_rate)} />
      <StatRow label="Total P&L" value={fmtRs(s.total_pnl)} cls={pnlColor(s.total_pnl)} />
      <StatRow label="Expectancy" value={fmtRs(s.expectancy)} cls={pnlColor(s.expectancy)} />
      <StatRow label="Profit factor" value={fmt(s.profit_factor)} />
      <StatRow label="Max drawdown" value={fmtRs(s.max_drawdown)} cls="text-rose-400" />
      <StatRow label="Sharpe" value={fmt(s.sharpe)} />
      <StatRow label="Sortino" value={fmt(s.sortino)} />
      <StatRow label="Capital efficiency" value={fmt(s.capital_efficiency, 3)} />
      <StatRow label="Confidence accuracy" value={fmtPct01(s.confidence_accuracy)} />
    </div>
  );
}

function RankTable({ items, nameKey }: { items: GroupStats[]; nameKey: "strategy" | "sector" | "bucket" }) {
  if (!items.length) return <div className="text-xs text-slate-500">No data yet.</div>;
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-xs">
        <thead>
          <tr className="border-b border-slate-800 text-left text-slate-400">
            <th className="py-1 pr-2">#</th><th className="py-1 pr-2 capitalize">{nameKey}</th>
            <th className="py-1 pr-2">Trades</th><th className="py-1 pr-2">Win %</th>
            <th className="py-1 pr-2">P&L</th><th className="py-1 pr-2">PF</th>
            <th className="py-1 pr-2">Expect.</th><th className="py-1 pr-2">Sharpe</th>
            <th className="py-1 pr-2">Conf. acc.</th>
          </tr>
        </thead>
        <tbody>
          {items.map((s, i) => (
            <tr key={String(s[nameKey]) + i} className="border-b border-slate-800/50 text-slate-200">
              <td className="py-1 pr-2">{s.rank ?? i + 1}</td>
              <td className="py-1 pr-2">{s[nameKey]}</td>
              <td className="py-1 pr-2">{s.trades}</td>
              <td className="py-1 pr-2">{fmtPct01(s.win_rate)}</td>
              <td className={`py-1 pr-2 ${pnlColor(s.total_pnl)}`}>{fmtRs(s.total_pnl)}</td>
              <td className="py-1 pr-2">{fmt(s.profit_factor)}</td>
              <td className="py-1 pr-2">{fmt(s.expectancy)}</td>
              <td className="py-1 pr-2">{fmt(s.sharpe)}</td>
              <td className="py-1 pr-2">{fmtPct01(s.confidence_accuracy)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function TradeList({ trades }: { trades: TradeSlim[] }) {
  if (!trades.length) return <div className="text-xs text-slate-500">No completed trades captured yet.</div>;
  return (
    <div className="space-y-1">
      {trades.map((t) => (
        <div key={t.trade_id} className="flex items-center justify-between rounded bg-slate-800/40 px-2 py-1 text-xs">
          <span className="text-slate-200">{t.symbol} <span className="text-slate-500">· {t.strategy ?? "—"} · {t.date ?? "—"}</span></span>
          <span className={pnlColor(t.realized_pnl)}>{fmtRs(t.realized_pnl)}</span>
        </div>
      ))}
    </div>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────
export default function AILearningCenter() {
  const qc = useQueryClient();
  const [note, setNote] = useState("");

  const overview = useQuery<Overview>({
    queryKey: ["phase24-overview"],
    queryFn: () => apiJson<Overview>("/phase24/overview", undefined, 130_000),
    staleTime: 60_000,
  });
  const recs = useQuery<{ items: Recommendation[] }>({
    queryKey: ["phase24-recs"],
    queryFn: () => apiJson("/phase24/recommendations", undefined, 60_000),
  });
  const reports = useQuery<{ items: Report[] }>({
    queryKey: ["phase24-reports"],
    queryFn: () => apiJson("/phase24/reports", undefined, 60_000),
  });

  const decide = useMutation({
    mutationFn: ({ id, decision }: { id: string; decision: "approve" | "dismiss" }) =>
      apiJson(`/phase24/recommendations/${id}/decide`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ decision, note }),
      }, 60_000),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["phase24-recs"] }),
  });
  const capture = useMutation({
    mutationFn: () => apiJson("/phase24/capture", { method: "POST" }, 160_000),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["phase24-overview"] }),
  });
  const genRecs = useMutation({
    mutationFn: () => apiJson("/phase24/recommendations/generate", { method: "POST" }, 160_000),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["phase24-recs"] }),
  });

  const o = overview.data;

  return (
    <div className="space-y-4 p-4">
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h1 className="flex items-center gap-2 text-xl font-bold text-slate-100">
            <Brain className="h-6 w-6 text-cyan-400" /> AI Learning Center
          </h1>
          <p className="text-xs text-slate-400">
            Phase 24 · Advisory only — the engine never modifies trading rules, thresholds, or strategies.
          </p>
        </div>
        <div className="flex gap-2">
          <button
            onClick={() => capture.mutate()}
            disabled={capture.isPending}
            className="flex items-center gap-1 rounded border border-slate-700 px-3 py-1.5 text-xs text-slate-200 hover:bg-slate-800"
            data-testid="button-capture-trades"
          >
            <RefreshCw className={`h-3 w-3 ${capture.isPending ? "animate-spin" : ""}`} />
            Capture closed trades
          </button>
          <button
            onClick={() => genRecs.mutate()}
            disabled={genRecs.isPending}
            className="flex items-center gap-1 rounded border border-slate-700 px-3 py-1.5 text-xs text-slate-200 hover:bg-slate-800"
            data-testid="button-generate-recs"
          >
            <Lightbulb className="h-3 w-3" /> Generate recommendations
          </button>
        </div>
      </div>

      {overview.isLoading && <div className="text-sm text-slate-400">Loading learning analytics… (aggregates can take up to a minute)</div>}
      {overview.isError && (
        <div className="flex items-center gap-2 rounded border border-rose-800 bg-rose-950/40 p-3 text-sm text-rose-300">
          <AlertTriangle className="h-4 w-4" /> {(overview.error as Error).message}
          <button onClick={() => overview.refetch()} className="ml-auto rounded border border-rose-700 px-2 py-0.5 text-xs">Retry</button>
        </div>
      )}

      {o && (
        <>
          {/* Scorecard */}
          <Card title={`Daily AI Scorecard — ${o.scorecard.date} (overall ${o.scorecard.overall ?? "—"}/10)`} icon={<Award className="h-4 w-4 text-amber-400" />}>
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-4 lg:grid-cols-8">
              {Object.entries(o.scorecard.scores).map(([k, v]) => (
                <div key={k} className="rounded bg-slate-800/40 p-2 text-center" data-testid={`score-${k}`}>
                  <div className="text-[10px] uppercase tracking-wide text-slate-400">{k.replace(/_/g, " ")}</div>
                  <div className={`text-lg font-bold ${v == null ? "text-slate-600" : v >= 7 ? "text-emerald-400" : v >= 5 ? "text-amber-400" : "text-rose-400"}`}>
                    {v == null ? "—" : v.toFixed(1)}
                  </div>
                </div>
              ))}
            </div>
            <div className="mt-2 flex flex-wrap gap-4 text-xs">
              <span className="text-emerald-400">Strengths: {o.scorecard.strengths.join(", ") || "—"}</span>
              <span className="text-rose-400">Weaknesses: {o.scorecard.weaknesses.join(", ") || "—"}</span>
              <span className="text-slate-400">{o.trade_records} permanent trade records</span>
            </div>
          </Card>

          {/* Lessons */}
          <div className="grid gap-4 lg:grid-cols-3">
            {[o.daily_lessons, o.weekly_lessons, o.monthly_lessons].map((l) => (
              <Card key={l.period} title={`${l.period[0].toUpperCase()}${l.period.slice(1)} lessons (${l.trades} trades)`} icon={<Clock className="h-4 w-4 text-sky-400" />}>
                <StatsBlock s={l.stats} />
                {l.mistakes.length > 0 && (
                  <div className="mt-2 space-y-1">
                    {l.mistakes.map((m, i) => (
                      <div key={i} className="flex items-start gap-1 text-xs text-rose-300"><TrendingDown className="mt-0.5 h-3 w-3 shrink-0" />{m}</div>
                    ))}
                  </div>
                )}
                {l.improvements.length > 0 && (
                  <div className="mt-2 space-y-1">
                    {l.improvements.map((m, i) => (
                      <div key={i} className="flex items-start gap-1 text-xs text-emerald-300"><TrendingUp className="mt-0.5 h-3 w-3 shrink-0" />{m}</div>
                    ))}
                  </div>
                )}
              </Card>
            ))}
          </div>

          {/* Best / worst trades */}
          <div className="grid gap-4 lg:grid-cols-2">
            <Card title="Best trades" icon={<TrendingUp className="h-4 w-4 text-emerald-400" />}>
              <TradeList trades={o.best_worst.best} />
            </Card>
            <Card title="Worst trades" icon={<TrendingDown className="h-4 w-4 text-rose-400" />}>
              <TradeList trades={o.best_worst.worst} />
            </Card>
          </div>

          {/* Calibration + Risk learning */}
          <div className="grid gap-4 lg:grid-cols-2">
            <Card title={`Confidence calibration (${o.calibration.total_trades} trades, overall error ${o.calibration.overall_calibration_error ?? "—"})`} icon={<Target className="h-4 w-4 text-violet-400" />}>
              <div className="overflow-x-auto">
                <table className="w-full text-xs">
                  <thead><tr className="border-b border-slate-800 text-left text-slate-400">
                    <th className="py-1 pr-2">Bucket</th><th className="py-1 pr-2">Predicted</th>
                    <th className="py-1 pr-2">Observed win %</th><th className="py-1 pr-2">Trades</th>
                    <th className="py-1 pr-2">Error</th><th className="py-1 pr-2">Status</th>
                  </tr></thead>
                  <tbody>
                    {o.calibration.buckets.map((b) => (
                      <tr key={b.bucket} className="border-b border-slate-800/50 text-slate-200">
                        <td className="py-1 pr-2">{b.bucket}</td>
                        <td className="py-1 pr-2">{b.predicted_confidence}%</td>
                        <td className="py-1 pr-2">{fmtPct01(b.win_rate)}</td>
                        <td className="py-1 pr-2">{b.trades}</td>
                        <td className="py-1 pr-2">{b.calibration_error ?? "—"}</td>
                        <td className={`py-1 pr-2 ${b.status === "OK" ? "text-emerald-400" : "text-slate-500"}`}>{b.status}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Card>
            <Card title={`Risk-rule learning (${o.risk_learning.records_analysed} rejection records)`} icon={<Shield className="h-4 w-4 text-orange-400" />}>
              {o.risk_learning.rules.length === 0 ? (
                <div className="text-xs text-slate-500">No rejection evidence stored yet — runs automatically after each session.</div>
              ) : (
                <div className="space-y-1">
                  {o.risk_learning.rules.map((r) => (
                    <div key={r.rule} className="flex items-center justify-between rounded bg-slate-800/40 px-2 py-1 text-xs">
                      <span className="text-slate-200">{r.rule} <span className="text-slate-500">· {r.rejections} rejections</span></span>
                      <span className={
                        r.verdict === "SAVES_MONEY" ? "text-emerald-400"
                          : r.verdict === "BLOCKS_PROFITS" ? "text-rose-400"
                            : "text-slate-400"}>
                        {r.verdict}{r.effectiveness != null ? ` (${(r.effectiveness * 100).toFixed(0)}%)` : ""}
                      </span>
                    </div>
                  ))}
                </div>
              )}
            </Card>
          </div>

          {/* Rankings */}
          <div className="grid gap-4 lg:grid-cols-2">
            <Card title="Strategy ranking" icon={<Award className="h-4 w-4 text-cyan-400" />}>
              <RankTable items={o.strategy_ranking.items} nameKey="strategy" />
            </Card>
            <Card title="Sector ranking" icon={<Award className="h-4 w-4 text-teal-400" />}>
              <RankTable items={o.sector_ranking.items} nameKey="sector" />
              {o.sector_ranking.summary?.best_sector && (
                <div className="mt-2 text-xs text-slate-400">
                  Best: <span className="text-emerald-400">{o.sector_ranking.summary.best_sector}</span> ·
                  Worst: <span className="text-rose-400"> {o.sector_ranking.summary.worst_sector}</span>
                </div>
              )}
            </Card>
          </div>

          {/* Time & regime */}
          <Card title="Time, weekday, regime & volatility analysis" icon={<Clock className="h-4 w-4 text-sky-400" />}>
            <div className="mb-3 grid grid-cols-2 gap-2 text-xs sm:grid-cols-4">
              {Object.entries(o.time_analysis.summary).map(([k, v]) => (
                <div key={k} className="rounded bg-slate-800/40 p-2">
                  <div className="uppercase tracking-wide text-slate-400">{k}</div>
                  <div className="text-emerald-400">Best: {v.best ?? "—"}</div>
                  <div className="text-rose-400">Worst: {v.worst ?? "—"}</div>
                </div>
              ))}
            </div>
            <div className="grid gap-4 lg:grid-cols-2">
              <RankTable items={o.time_analysis.regimes} nameKey="bucket" />
              <RankTable items={o.time_analysis.weekdays} nameKey="bucket" />
            </div>
          </Card>
        </>
      )}

      {/* Recommendations */}
      <Card title="AI improvement recommendations (manual approval required)" icon={<Lightbulb className="h-4 w-4 text-amber-400" />}>
        <p className="mb-2 text-xs text-slate-500">
          Approving records intent only — no threshold, strategy, or risk rule is ever changed automatically.
        </p>
        {recs.data?.items?.length ? (
          <div className="space-y-2">
            <input
              value={note}
              onChange={(e) => setNote(e.target.value)}
              placeholder="Optional decision note…"
              className="w-full rounded border border-slate-700 bg-slate-900 px-2 py-1 text-xs text-slate-200"
              data-testid="input-decision-note"
            />
            {recs.data.items.map((r) => (
              <div key={r.id} className="rounded border border-slate-800 bg-slate-800/30 p-2" data-testid={`rec-${r.id}`}>
                <div className="flex items-center justify-between gap-2">
                  <div className="text-xs">
                    <span className="mr-2 rounded bg-slate-700 px-1.5 py-0.5 text-[10px] text-slate-300">{r.record.kind}</span>
                    <span className="font-medium text-slate-200">{r.record.title}</span>
                    <div className="mt-0.5 text-slate-400">{r.record.detail}</div>
                  </div>
                  {r.status === "PROPOSED" ? (
                    <div className="flex shrink-0 gap-1">
                      <button
                        onClick={() => decide.mutate({ id: r.id, decision: "approve" })}
                        className="flex items-center gap-1 rounded border border-emerald-700 px-2 py-1 text-xs text-emerald-400 hover:bg-emerald-950"
                        data-testid={`button-approve-${r.id}`}
                      ><CheckCircle2 className="h-3 w-3" /> Approve</button>
                      <button
                        onClick={() => decide.mutate({ id: r.id, decision: "dismiss" })}
                        className="flex items-center gap-1 rounded border border-rose-700 px-2 py-1 text-xs text-rose-400 hover:bg-rose-950"
                        data-testid={`button-dismiss-${r.id}`}
                      ><XCircle className="h-3 w-3" /> Dismiss</button>
                    </div>
                  ) : (
                    <span className={`text-xs ${r.status === "APPROVED" ? "text-emerald-400" : "text-slate-500"}`}>{r.status}</span>
                  )}
                </div>
              </div>
            ))}
          </div>
        ) : (
          <div className="text-xs text-slate-500">No recommendations yet — generated automatically after each session.</div>
        )}
      </Card>

      {/* Reports */}
      <Card title="Automated AI reports" icon={<FileText className="h-4 w-4 text-slate-400" />}>
        {reports.data?.items?.length ? (
          <div className="space-y-2">
            {reports.data.items.map((r) => (
              <details key={r.id} className="rounded border border-slate-800 bg-slate-800/30 p-2 text-xs">
                <summary className="cursor-pointer text-slate-200">
                  <span className="capitalize">{r.period}</span> report · {r.period_key} ·
                  overall score {r.record.scorecard?.overall ?? "—"} · {r.record.trades} trades
                </summary>
                <div className="mt-2 grid gap-3 lg:grid-cols-2">
                  <div><div className="mb-1 font-semibold text-slate-300">Performance</div><StatsBlock s={r.record.performance} /></div>
                  <div>
                    <div className="mb-1 font-semibold text-slate-300">Mistakes & expected improvements</div>
                    {r.record.mistakes?.map((m, i) => <div key={i} className="text-rose-300">• {m}</div>)}
                    {r.record.expected_improvements?.map((m, i) => <div key={i} className="text-emerald-300">• {m}</div>)}
                    {!r.record.mistakes?.length && !r.record.expected_improvements?.length && <div className="text-slate-500">None recorded.</div>}
                  </div>
                </div>
                <a
                  className="mt-2 inline-block text-cyan-400 underline"
                  href={`data:application/json,${encodeURIComponent(JSON.stringify(r.record, null, 1))}`}
                  download={`ai-report-${r.period}-${r.period_key}.json`}
                >Download JSON</a>
              </details>
            ))}
          </div>
        ) : (
          <div className="text-xs text-slate-500">No reports yet — daily/weekly/monthly/quarterly reports generate automatically after market close.</div>
        )}
      </Card>
    </div>
  );
}
