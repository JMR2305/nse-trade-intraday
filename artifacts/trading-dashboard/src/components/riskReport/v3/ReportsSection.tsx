/** Sections 11 (Weekly Report) + 12 (Monthly Report) */
import { useState } from "react";
import { Calendar, TrendingUp, TrendingDown } from "lucide-react";

const fmt1 = (n?: number | null) => n != null ? n.toFixed(1) : "—";
const fmtCur = (n?: number | null) => n != null ? `₹${Number(n).toLocaleString("en-IN", { maximumFractionDigits: 0 })}` : "—";

// ── Section 11: Weekly Optimization Report ────────────────────────────────────
export function WeeklyReportSection({ data }: { data: Record<string, unknown> }) {
  if (!data || Object.keys(data).length === 0) {
    return (
      <div className="text-center py-10 text-slate-500 text-sm">
        <div className="text-3xl mb-2">📅</div>
        <div className="font-medium text-slate-400">Weekly report not yet generated</div>
        <div className="text-xs mt-1 text-slate-600">Reports accumulate after 7 days of evaluation history.</div>
      </div>
    );
  }

  const d = data as Record<string, unknown>;
  const reviewItems = (d.review_items as string[] | undefined) ?? [];
  const missed = d.largest_missed_opportunity as { symbol?: string; gain_pct?: number } | undefined;
  const avoided = d.largest_avoided_loss as { symbol?: string; loss_pct?: number } | undefined;

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2 text-sm text-slate-400">
        <Calendar className="w-4 h-4 text-purple-400" />
        <span>Period: Last 7 Days</span>
        {Boolean(d.generated_at) && (
          <span className="text-xs text-slate-600 ml-auto">
            Generated: {new Date(d.generated_at as string).toLocaleString("en-IN", { timeZone: "Asia/Kolkata", hour12: false, month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" })}
          </span>
        )}
      </div>

      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        {[
          { label: "Total Rejected",      value: d.total_rejected,       color: "text-slate-300" },
          { label: "False Rejections",    value: d.false_rejections,     color: "text-red-400" },
          { label: "Correct Rejections",  value: d.correct_rejections,   color: "text-emerald-400" },
          { label: "Avg Blocked/Scan",    value: fmt1(d.avg_blocked_per_scan as number), color: "text-amber-400" },
        ].map(({ label, value, color }) => (
          <div key={label} className="bg-slate-800/40 border border-slate-700/40 rounded-xl px-4 py-3 text-center">
            <div className={`text-2xl font-bold ${color}`}>{value as string | number ?? "—"}</div>
            <div className="text-xs text-slate-500 mt-0.5">{label}</div>
          </div>
        ))}
      </div>

      <div className="grid sm:grid-cols-2 gap-3">
        <div className="bg-slate-800/30 border border-slate-700/40 rounded-xl p-4 space-y-2">
          <div className="text-xs font-semibold text-slate-400 uppercase tracking-wide">Gate Highlights</div>
          <div className="space-y-1.5 text-sm">
            <div className="flex justify-between">
              <span className="text-slate-500">Most Restrictive</span>
              <span className="text-red-400 font-medium">{(d.most_restrictive_gate as string) ?? "—"}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-slate-500">Most Accurate</span>
              <span className="text-emerald-400 font-medium">{(d.most_accurate_gate as string) ?? "—"}</span>
            </div>
          </div>
        </div>

        <div className="bg-slate-800/30 border border-slate-700/40 rounded-xl p-4 space-y-2">
          <div className="text-xs font-semibold text-slate-400 uppercase tracking-wide">Extremes</div>
          <div className="space-y-1.5 text-sm">
            <div className="flex justify-between">
              <span className="text-slate-500 flex items-center gap-1"><TrendingUp className="w-3 h-3 text-red-400" /> Largest Missed</span>
              <span className="text-red-400 font-medium">
                {missed?.symbol ? `${missed.symbol} (+${fmt1(missed.gain_pct)}%)` : "—"}
              </span>
            </div>
            <div className="flex justify-between">
              <span className="text-slate-500 flex items-center gap-1"><TrendingDown className="w-3 h-3 text-emerald-400" /> Largest Avoided</span>
              <span className="text-emerald-400 font-medium">
                {avoided?.symbol ? `${avoided.symbol} (-${fmt1(avoided.loss_pct)}%)` : "—"}
              </span>
            </div>
          </div>
        </div>
      </div>

      {reviewItems.length > 0 && (
        <div className="bg-amber-900/15 border border-amber-700/30 rounded-xl p-4">
          <div className="text-xs font-semibold text-amber-300 mb-2">Suggested Review Items</div>
          <div className="flex flex-wrap gap-2">
            {reviewItems.map((item, i) => (
              <span key={i} className="text-xs bg-amber-900/30 border border-amber-700/40 text-amber-300 px-2 py-0.5 rounded-full">
                {item}
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

// ── Section 12: Monthly Report ────────────────────────────────────────────────
export function MonthlyReportSection({ data }: { data: Record<string, unknown> }) {
  if (!data || Object.keys(data).length === 0) {
    return (
      <div className="text-center py-10 text-slate-500 text-sm">
        <div className="text-3xl mb-2">📆</div>
        <div className="font-medium text-slate-400">Monthly report not yet generated</div>
        <div className="text-xs mt-1 text-slate-600">Reports accumulate after 30 days of evaluation history.</div>
      </div>
    );
  }

  const d = data as Record<string, unknown>;
  type GateTrend = { gate_id: string; label: string; weekly_counts: number[] };
  type StratTrend = { strategy: string; rejections: number };
  type RegimeDist = { regime: string; count: number };
  type PassRate   = { week: string; pass_rate: number | null; scans: number };

  const gateTrends    = (d.gate_trends        as GateTrend[] | undefined) ?? [];
  const stratTrends   = (d.strategy_trends    as StratTrend[] | undefined) ?? [];
  const regimeDist    = (d.regime_distribution as RegimeDist[] | undefined) ?? [];
  const passRateTrend = (d.pass_rate_trend    as PassRate[]  | undefined) ?? [];

  return (
    <div className="space-y-5">
      <div className="flex items-center gap-2 text-sm text-slate-400">
        <Calendar className="w-4 h-4 text-purple-400" />
        <span>Period: Last 30 Days · Total Rejected: {d.total_rejected as number ?? "—"}</span>
      </div>

      {/* Gate trends */}
      {gateTrends.length > 0 && (
        <div>
          <div className="text-xs font-semibold text-slate-400 mb-2 uppercase tracking-wide">Gate Rejection Trends (4 Weekly Buckets)</div>
          <div className="space-y-1.5">
            {gateTrends.slice(0, 6).map(gt => {
              const total = gt.weekly_counts.reduce((s, n) => s + n, 0);
              const maxW  = Math.max(...gt.weekly_counts, 1);
              return (
                <div key={gt.gate_id} className="flex items-center gap-3">
                  <div className="text-xs text-slate-400 w-40 shrink-0 truncate">{gt.label}</div>
                  <div className="flex gap-1 flex-1">
                    {gt.weekly_counts.map((n, i) => (
                      <div key={i} className="flex-1 flex flex-col items-center gap-0.5">
                        <div className="w-full bg-slate-700/40 rounded-sm overflow-hidden" style={{ height: "28px" }}>
                          <div className="bg-purple-600/60 rounded-sm w-full transition-all"
                            style={{ height: `${Math.round(n / maxW * 100)}%`, marginTop: `${100 - Math.round(n / maxW * 100)}%` }} />
                        </div>
                        <div className="text-xs text-slate-600">{n}</div>
                      </div>
                    ))}
                  </div>
                  <div className="text-xs text-slate-500 w-8 text-right">{total}</div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      <div className="grid sm:grid-cols-3 gap-4">
        {/* Strategy trends */}
        {stratTrends.length > 0 && (
          <div>
            <div className="text-xs font-semibold text-slate-400 mb-2 uppercase tracking-wide">Strategy Rejections</div>
            <div className="space-y-1.5">
              {stratTrends.map(s => (
                <div key={s.strategy} className="flex justify-between text-xs">
                  <span className="text-slate-400 truncate">{s.strategy}</span>
                  <span className="text-slate-300 font-semibold ml-2">{s.rejections}</span>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Regime distribution */}
        {regimeDist.length > 0 && (
          <div>
            <div className="text-xs font-semibold text-slate-400 mb-2 uppercase tracking-wide">Regime Distribution</div>
            <div className="space-y-1.5">
              {regimeDist.map(r => (
                <div key={r.regime} className="flex justify-between text-xs">
                  <span className="text-slate-400 truncate">{r.regime}</span>
                  <span className="text-slate-300 font-semibold ml-2">{r.count}</span>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Pass rate trend */}
        {passRateTrend.length > 0 && (
          <div>
            <div className="text-xs font-semibold text-slate-400 mb-2 uppercase tracking-wide">Weekly Pass Rate</div>
            <div className="space-y-1.5">
              {passRateTrend.map(p => (
                <div key={p.week} className="flex items-center gap-2">
                  <span className="text-xs text-slate-500 w-14 shrink-0">{p.week}</span>
                  <div className="flex-1 h-2 bg-slate-700/40 rounded overflow-hidden">
                    <div className={`h-full rounded ${(p.pass_rate ?? 0) >= 50 ? "bg-emerald-500/60" : "bg-amber-500/60"}`}
                      style={{ width: `${p.pass_rate ?? 0}%` }} />
                  </div>
                  <span className="text-xs text-slate-400 w-8 text-right">{p.pass_rate != null ? `${fmt1(p.pass_rate)}%` : "—"}</span>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

export function ReportsTab({ s11, s12 }: { s11: Record<string, unknown>; s12: Record<string, unknown> }) {
  const [sub, setSub] = useState<"s11" | "s12">("s11");
  return (
    <div className="space-y-4">
      <div className="flex gap-1.5">
        {[{ key: "s11" as const, label: "Weekly Report" }, { key: "s12" as const, label: "Monthly Report" }].map(({ key, label }) => (
          <button key={key} onClick={() => setSub(key)}
            className={`text-xs px-3 py-1.5 rounded-lg border transition ${sub === key ? "bg-slate-700 border-slate-600 text-white" : "border-slate-700/40 text-slate-400 hover:border-slate-600"}`}>
            {label}
          </button>
        ))}
      </div>
      {sub === "s11" && <WeeklyReportSection data={s11} />}
      {sub === "s12" && <MonthlyReportSection data={s12} />}
    </div>
  );
}
