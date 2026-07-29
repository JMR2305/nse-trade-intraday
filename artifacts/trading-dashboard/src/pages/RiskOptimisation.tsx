/**
 * RiskOptimisation.tsx — Phase 6.4
 * Risk Optimisation & Capital Allocation Intelligence dashboard.
 *
 * Sections:
 *   1. Risk Health (Score ring + grade + component scores)
 *   2. Capital Allocation (utilisation, idle capital, Kelly fraction)
 *   3. Position Sizing (avg, largest, recommended, max safe)
 *   4. Sector Diversification (concentration, HHI, correlation risk)
 *   5. Drawdown Analysis (max DD, avg DD, recovery, equity curve)
 *   6. Stop Loss Analysis (SL rate, avg loss, premature/late exits)
 *   7. Target Analysis (R:R, win rate, target hits, early exits)
 *   8. Stress Testing (7 advisory scenarios)
 *   9. Recommendations (explainable advisory cards, priority-sorted)
 *  10. Historical Risk Trend (future Monte Carlo hook note)
 *
 * READ-ONLY. ADVISORY-ONLY.
 */
import { useQuery } from "@tanstack/react-query";
import { apiJson } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  ShieldCheck, RefreshCw, Download, AlertTriangle, TrendingDown,
  TrendingUp, Minus, Info, ChevronRight, Activity,
} from "lucide-react";

// ---------------------------------------------------------------------------
// API helpers
// ---------------------------------------------------------------------------

const ENABLED_5MIN = { staleTime: 5 * 60 * 1000, retry: 1 };

function useSummary() {
  return useQuery({ queryKey: ["ro-summary"], queryFn: () => apiJson("risk-optimisation/summary"), ...ENABLED_5MIN });
}
function useCapital() {
  return useQuery({ queryKey: ["ro-capital"], queryFn: () => apiJson("risk-optimisation/capital"), ...ENABLED_5MIN });
}
function useDrawdown() {
  return useQuery({ queryKey: ["ro-drawdown"], queryFn: () => apiJson("risk-optimisation/drawdown"), ...ENABLED_5MIN });
}
function useStress() {
  return useQuery({ queryKey: ["ro-stress"], queryFn: () => apiJson("risk-optimisation/stress"), ...ENABLED_5MIN });
}
function useRecommendations() {
  return useQuery({ queryKey: ["ro-recs"], queryFn: () => apiJson("risk-optimisation/recommendations"), ...ENABLED_5MIN });
}

// ---------------------------------------------------------------------------
// Tiny helpers
// ---------------------------------------------------------------------------

function pct(v: number | undefined, decimals = 1) {
  if (v == null) return "0.0%";
  return `${(v * 100).toFixed(decimals)}%`;
}
function inr(v: number | undefined) {
  if (v == null) return "₹0";
  return `₹${Math.abs(v).toLocaleString("en-IN", { maximumFractionDigits: 0 })}`;
}
function fmt(v: number | undefined, d = 2) {
  if (v == null) return "0.00";
  return v.toFixed(d);
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function ScoreRing({ score, grade }: { score: number; grade: string }) {
  const r = 42;
  const circ = 2 * Math.PI * r;
  const dash = (score / 100) * circ;
  const gradeColor =
    grade === "A+" ? "#22c55e" :
    grade === "A"  ? "#4ade80" :
    grade === "B"  ? "#facc15" :
    grade === "C"  ? "#fb923c" : "#f87171";

  return (
    <div className="relative inline-flex items-center justify-center w-28 h-28">
      <svg className="absolute inset-0 -rotate-90" width="112" height="112" viewBox="0 0 100 100">
        <circle cx="50" cy="50" r={r} fill="none" stroke="currentColor" strokeWidth="8" className="text-border/30" />
        <circle
          cx="50" cy="50" r={r} fill="none"
          stroke={gradeColor} strokeWidth="8"
          strokeDasharray={`${dash} ${circ}`}
          strokeLinecap="round"
          style={{ transition: "stroke-dasharray 0.6s ease" }}
        />
      </svg>
      <div className="flex flex-col items-center z-10">
        <span className="text-2xl font-bold tabular-nums leading-none" style={{ color: gradeColor }}>
          {score.toFixed(0)}
        </span>
        <span className="text-[10px] text-muted-foreground">/&nbsp;100</span>
        <span className="mt-0.5 rounded-full px-2 py-0.5 text-[10px] font-bold"
          style={{ background: gradeColor + "22", color: gradeColor }}>
          Grade&nbsp;{grade}
        </span>
      </div>
    </div>
  );
}

function Stat({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="flex flex-col gap-0.5 p-3 rounded-lg border border-border bg-card/50">
      <span className="text-[10px] uppercase tracking-wide text-muted-foreground">{label}</span>
      <span className="text-sm font-semibold tabular-nums">{value}</span>
      {sub && <span className="text-[10px] text-muted-foreground">{sub}</span>}
    </div>
  );
}

function SevBadge({ sev }: { sev: string }) {
  const cls =
    sev === "CRITICAL" ? "bg-red-500/15 text-red-400 border-red-500/30" :
    sev === "HIGH"     ? "bg-orange-500/15 text-orange-400 border-orange-500/30" :
    sev === "MEDIUM"   ? "bg-yellow-500/15 text-yellow-400 border-yellow-500/30" :
                         "bg-green-500/15 text-green-400 border-green-500/30";
  return <span className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[10px] font-bold uppercase ${cls}`}>{sev}</span>;
}

function PriBadge({ pri }: { pri: string }) {
  const cls =
    pri === "HIGH"   ? "bg-red-500/15 text-red-400 border-red-500/30" :
    pri === "MEDIUM" ? "bg-yellow-500/15 text-yellow-400 border-yellow-500/30" :
                       "bg-blue-500/15 text-blue-400 border-blue-500/30";
  return <span className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[10px] font-bold uppercase ${cls}`}>{pri}</span>;
}

function TrendIcon({ trend }: { trend: string }) {
  if (trend === "IMPROVING") return <TrendingUp className="h-3.5 w-3.5 text-green-400" />;
  if (trend === "DECLINING") return <TrendingDown className="h-3.5 w-3.5 text-red-400" />;
  return <Minus className="h-3.5 w-3.5 text-muted-foreground" />;
}

function SectionCard({ title, children, className = "" }: { title: string; children: React.ReactNode; className?: string }) {
  return (
    <div className={`rounded-xl border border-border bg-card/60 p-5 space-y-4 ${className}`}>
      <h3 className="text-sm font-semibold text-foreground flex items-center gap-2">{title}</h3>
      {children}
    </div>
  );
}

function DisabledState() {
  return (
    <div className="rounded-xl border border-border bg-card/50 p-8 text-center space-y-2">
      <ShieldCheck className="h-8 w-8 mx-auto text-muted-foreground/40" />
      <p className="text-sm font-medium text-muted-foreground">Risk Optimisation is disabled</p>
      <p className="text-xs text-muted-foreground/60">Set <code className="bg-border/40 px-1 rounded">RISK_OPTIMISATION_ENABLED=true</code> to enable.</p>
    </div>
  );
}

function EmptyState() {
  return (
    <p className="text-xs text-muted-foreground/60 py-2">
      No trades recorded yet — complete paper trades to generate risk optimisation insights.
    </p>
  );
}

// ---------------------------------------------------------------------------
// Sections
// ---------------------------------------------------------------------------

function Section1RiskHealth({ summary }: { summary: any }) {
  const score = summary?.risk_optimisation_score ?? 0;
  const grade = summary?.grade ?? "D";
  const trend = summary?.trend ?? "STABLE";
  const n = summary?.total_trades ?? 0;

  return (
    <SectionCard title="🛡️ Risk Health">
      <div className="flex flex-col md:flex-row gap-6 items-start">
        <ScoreRing score={score} grade={grade} />
        <div className="flex flex-col gap-1.5 flex-1">
          <div className="flex items-center gap-2 text-xs text-muted-foreground">
            <span>Trend</span>
            <TrendIcon trend={trend} />
            <span className="font-medium text-foreground">{trend}</span>
            <span>·</span>
            <span>{n} trades analysed</span>
          </div>
          {n === 0 && <EmptyState />}
          <div className="grid grid-cols-2 sm:grid-cols-3 gap-2 mt-2">
            <Stat label="Diversification" value={pct(summary?.diversification_score)} />
            <Stat label="Drawdown Severity" value={pct(summary?.drawdown_severity)} />
            <Stat label="Capital Efficiency" value={pct(summary?.capital_efficiency)} />
            <Stat label="Position Sizing" value={pct(summary?.position_sizing_score)} />
            <Stat label="SL Quality" value={pct(summary?.stop_loss_quality_score)} />
            <Stat label="Correlation Risk" value={summary?.correlation_risk ?? "—"} />
          </div>
        </div>
      </div>
    </SectionCard>
  );
}

function Section2CapitalAllocation({ capital }: { capital: any }) {
  const ca = capital?.capital_allocation ?? {};
  const n = capital?.total_trades ?? 0;
  return (
    <SectionCard title="💰 Capital Allocation">
      {n === 0 ? <EmptyState /> : (
        <div className="space-y-3">
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
            <Stat label="Avg Usage" value={inr(ca.avg_capital_usage)} />
            <Stat label="Utilisation" value={pct(ca.capital_utilisation_rate)} />
            <Stat label="Idle Capital" value={inr(ca.idle_capital)} />
            <Stat label="Capital Efficiency" value={pct(ca.capital_efficiency)} />
            <Stat label="Capital Turnover" value={fmt(ca.capital_turnover) + "×"} />
            <Stat label="Kelly Fraction" value={pct(ca.kelly_fraction)} />
            <Stat label="Recommended" value={inr(ca.recommended_allocation)} sub="per trade" />
            <Stat label="Alloc Stability" value={pct(ca.allocation_stability)} />
          </div>
          <div className="rounded-lg border border-border bg-muted/20 p-3 text-xs text-muted-foreground space-y-1">
            <div className="flex gap-4">
              <span>Win Rate: <strong className="text-foreground">{pct(ca.win_rate)}</strong></span>
              <span>Avg Win: <strong className="text-green-400">{inr(ca.avg_win_inr)}</strong></span>
              <span>Avg Loss: <strong className="text-red-400">{inr(ca.avg_loss_inr)}</strong></span>
              <span>R:R: <strong className="text-foreground">{fmt(ca.reward_risk_ratio)}</strong></span>
            </div>
          </div>
        </div>
      )}
    </SectionCard>
  );
}

function Section3PositionSizing({ capital }: { capital: any }) {
  const ps = capital?.position_sizing ?? {};
  const n = capital?.total_trades ?? 0;
  return (
    <SectionCard title="📐 Position Sizing">
      {n === 0 ? <EmptyState /> : (
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
          <Stat label="Avg Position" value={inr(ps.avg_position_size)} />
          <Stat label="Largest" value={inr(ps.largest_position)} sub={pct(ps.largest_position_pct_of_capital) + " of capital"} />
          <Stat label="Smallest" value={inr(ps.smallest_position)} />
          <Stat label="Recommended" value={inr(ps.recommended_position_size)} />
          <Stat label="Max Safe" value={inr(ps.max_safe_position)} sub="2% rule" />
          <Stat label="Risk/Trade" value={pct(ps.avg_risk_per_trade_pct)} />
          <Stat label="Avg Win Position" value={inr(ps.avg_winning_position)} />
          <Stat label="Avg Loss Position" value={inr(ps.avg_losing_position)} />
        </div>
      )}
    </SectionCard>
  );
}

function Section4SectorDiversification({ capital }: { capital: any }) {
  const conc = capital?.portfolio_concentration ?? {};
  const sectors = conc.sector_exposure ?? {};
  const strategies = conc.strategy_exposure ?? {};
  const n = capital?.total_trades ?? 0;
  return (
    <SectionCard title="🗺️ Sector Diversification">
      {n === 0 ? <EmptyState /> : (
        <div className="space-y-4">
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
            <Stat label="Diversification" value={fmt(conc.diversification_score, 2) + "/1"} />
            <Stat label="HHI Sector" value={fmt(conc.hhi_sector, 2)} sub="0=diverse, 1=concentrated" />
            <Stat label="HHI Strategy" value={fmt(conc.hhi_strategy, 2)} />
            <Stat label="Corr Risk" value={conc.correlation_risk ?? "—"} />
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {/* Sector table */}
            <div>
              <p className="text-[10px] uppercase tracking-wide text-muted-foreground mb-2">Sector Exposure</p>
              <div className="rounded-lg border border-border overflow-hidden">
                <table className="w-full text-xs">
                  <thead className="bg-muted/30">
                    <tr>
                      <th className="text-left px-3 py-2 text-muted-foreground font-medium">Sector</th>
                      <th className="text-right px-3 py-2 text-muted-foreground font-medium">Trades</th>
                      <th className="text-right px-3 py-2 text-muted-foreground font-medium">%</th>
                    </tr>
                  </thead>
                  <tbody>
                    {Object.entries(sectors).map(([sec, v]: [string, any]) => (
                      <tr key={sec} className="border-t border-border/50">
                        <td className="px-3 py-1.5">{sec}</td>
                        <td className="text-right px-3 py-1.5 tabular-nums">{v.count}</td>
                        <td className="text-right px-3 py-1.5 tabular-nums text-muted-foreground">
                          {pct(v.pct_of_trades)}
                        </td>
                      </tr>
                    ))}
                    {Object.keys(sectors).length === 0 && (
                      <tr><td colSpan={3} className="px-3 py-2 text-muted-foreground/60">No data</td></tr>
                    )}
                  </tbody>
                </table>
              </div>
            </div>
            {/* Strategy table */}
            <div>
              <p className="text-[10px] uppercase tracking-wide text-muted-foreground mb-2">Strategy Exposure</p>
              <div className="rounded-lg border border-border overflow-hidden">
                <table className="w-full text-xs">
                  <thead className="bg-muted/30">
                    <tr>
                      <th className="text-left px-3 py-2 text-muted-foreground font-medium">Strategy</th>
                      <th className="text-right px-3 py-2 text-muted-foreground font-medium">Trades</th>
                      <th className="text-right px-3 py-2 text-muted-foreground font-medium">%</th>
                    </tr>
                  </thead>
                  <tbody>
                    {Object.entries(strategies).map(([strat, v]: [string, any]) => (
                      <tr key={strat} className="border-t border-border/50">
                        <td className="px-3 py-1.5">{strat}</td>
                        <td className="text-right px-3 py-1.5 tabular-nums">{v.count}</td>
                        <td className="text-right px-3 py-1.5 tabular-nums text-muted-foreground">
                          {pct(v.pct_of_trades)}
                        </td>
                      </tr>
                    ))}
                    {Object.keys(strategies).length === 0 && (
                      <tr><td colSpan={3} className="px-3 py-2 text-muted-foreground/60">No data</td></tr>
                    )}
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        </div>
      )}
    </SectionCard>
  );
}

function Section5DrawdownAnalysis({ dd }: { dd: any }) {
  const n = dd?.total_trades ?? 0;
  const equityCurve: number[] = dd?.equity_curve_head ?? [];
  return (
    <SectionCard title="📉 Drawdown Analysis">
      {n === 0 ? <EmptyState /> : (
        <div className="space-y-4">
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
            <Stat label="Max Drawdown" value={pct(dd?.max_drawdown)} />
            <Stat label="Avg Drawdown" value={pct(dd?.avg_drawdown)} />
            <Stat label="DD Frequency" value={fmt(dd?.drawdown_frequency_per_10) + "/10 trades"} />
            <Stat label="Recovery Eff." value={pct(dd?.recovery_efficiency)} />
            <Stat label="Avg Recovery" value={fmt(dd?.avg_recovery_trades, 1) + " trades"} />
            <Stat label="Total P&L" value={inr(dd?.total_pnl)} />
            <Stat label="Final Equity" value={inr(dd?.final_equity)} />
            <Stat label="DD Severity" value={pct(dd?.drawdown_severity)} />
          </div>

          {/* Equity curve sparkline */}
          {equityCurve.length > 1 && (
            <div>
              <p className="text-[10px] uppercase tracking-wide text-muted-foreground mb-1.5">Equity Curve (first 20 points)</p>
              <div className="h-14 flex items-end gap-px">
                {equityCurve.map((v, i) => {
                  const mn = Math.min(...equityCurve);
                  const mx = Math.max(...equityCurve);
                  const range = mx - mn || 1;
                  const h = Math.round(((v - mn) / range) * 48) + 4;
                  const col = v >= equityCurve[0] ? "#4ade80" : "#f87171";
                  return (
                    <div key={i} title={`₹${v.toLocaleString("en-IN", { maximumFractionDigits: 0 })}`}
                      style={{ height: h, background: col, flex: 1, borderRadius: 2, opacity: 0.85 }} />
                  );
                })}
              </div>
            </div>
          )}

          {/* Worst drawdown period */}
          {dd?.worst_drawdown_period && (
            <div className="rounded-lg border border-red-500/20 bg-red-500/5 p-3 text-xs space-y-1">
              <p className="font-medium text-red-400">Worst Drawdown Period</p>
              <div className="flex flex-wrap gap-4 text-muted-foreground">
                <span>Drawdown: <strong className="text-red-400">{pct(dd.worst_drawdown_period.drawdown_pct)}</strong></span>
                <span>Duration: <strong className="text-foreground">{dd.worst_drawdown_period.duration_trades} trades</strong></span>
                <span>Trough: <strong className="text-foreground">{inr(dd.worst_drawdown_period.trough_equity)}</strong></span>
                {dd.worst_drawdown_period.recovery_trades != null
                  ? <span>Recovery: <strong className="text-green-400">{dd.worst_drawdown_period.recovery_trades} trades</strong></span>
                  : <span className="text-orange-400">Still in drawdown</span>
                }
              </div>
            </div>
          )}
        </div>
      )}
    </SectionCard>
  );
}

function Section6StopLossAnalysis({ capital }: { capital: any }) {
  const sl = capital?.stop_loss_analysis ?? {};
  const n = capital?.total_trades ?? 0;
  return (
    <SectionCard title="🛑 Stop Loss Analysis">
      {n === 0 ? <EmptyState /> : (
        <div className="space-y-3">
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
            <Stat label="SL Hits" value={String(sl.stop_loss_hits ?? 0)} sub={`${pct(sl.stop_loss_rate)} of trades`} />
            <Stat label="Avg Loss on SL" value={inr(sl.avg_loss_on_sl)} sub={pct(sl.avg_loss_pct_on_sl)} />
            <Stat label="Avg Stop Dist." value={pct(sl.avg_stop_distance_pct)} />
            <Stat label="SL Quality" value={pct(sl.stop_loss_quality_score)} />
            <Stat label="Premature Exits" value={String(sl.premature_exits ?? 0)} />
            <Stat label="Late Exits" value={String(sl.late_exits ?? 0)} />
            <Stat label="Trailing Stops" value={String(sl.trailing_stop_count ?? 0)} />
            <Stat label="Target Exits" value={String(sl.target_exits ?? 0)} />
          </div>
          {sl.advisory && (
            <div className="flex items-start gap-2 rounded-lg border border-border bg-muted/20 p-3 text-xs text-muted-foreground">
              <Info className="h-3.5 w-3.5 shrink-0 mt-0.5" />
              <span>{sl.advisory}</span>
            </div>
          )}
        </div>
      )}
    </SectionCard>
  );
}

function Section7TargetAnalysis({ capital }: { capital: any }) {
  const tgt = capital?.target_analysis ?? {};
  const n = capital?.total_trades ?? 0;
  return (
    <SectionCard title="🎯 Target Analysis">
      {n === 0 ? <EmptyState /> : (
        <div className="space-y-3">
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
            <Stat label="Win Rate" value={pct(tgt.win_rate)} />
            <Stat label="Reward/Risk" value={fmt(tgt.reward_risk_ratio)} />
            <Stat label="Target Hits" value={String(tgt.target_hits ?? 0)} sub={pct(tgt.target_hit_rate)} />
            <Stat label="Avg Reward" value={inr(tgt.avg_reward_inr)} />
            <Stat label="Avg Win %" value={pct(tgt.avg_win_pct)} />
            <Stat label="Early Booking" value={String(tgt.early_profit_booking ?? 0)} />
            <Stat label="Extended Winners" value={String(tgt.extended_winners ?? 0)} />
            <Stat label="Missed Profit" value={String(tgt.missed_profit_count ?? 0)} />
          </div>
          {tgt.advisory && (
            <div className="flex items-start gap-2 rounded-lg border border-border bg-muted/20 p-3 text-xs text-muted-foreground">
              <Info className="h-3.5 w-3.5 shrink-0 mt-0.5" />
              <span>{tgt.advisory}</span>
            </div>
          )}
        </div>
      )}
    </SectionCard>
  );
}

function Section8StressTesting({ stress }: { stress: any }) {
  const scenarios = stress?.scenarios ?? [];
  return (
    <SectionCard title="⚡ Stress Testing">
      <div className="flex items-center gap-2 mb-1">
        <Badge variant="outline" className="text-[10px] font-bold text-amber-400 border-amber-500/30 bg-amber-500/10">
          ADVISORY — HYPOTHETICAL SCENARIOS
        </Badge>
      </div>
      {scenarios.length === 0 ? <EmptyState /> : (
        <div className="rounded-lg border border-border overflow-hidden">
          <table className="w-full text-xs">
            <thead className="bg-muted/30">
              <tr>
                <th className="text-left px-3 py-2 text-muted-foreground font-medium">Scenario</th>
                <th className="text-right px-3 py-2 text-muted-foreground font-medium">Impact %</th>
                <th className="text-right px-3 py-2 text-muted-foreground font-medium">Est. P&L</th>
                <th className="text-center px-3 py-2 text-muted-foreground font-medium">Severity</th>
              </tr>
            </thead>
            <tbody>
              {scenarios.map((s: any) => (
                <tr key={s.scenario_type} className="border-t border-border/50">
                  <td className="px-3 py-2">
                    <div className="font-medium text-foreground">{s.name}</div>
                    <div className="text-muted-foreground/70 mt-0.5 max-w-xs">{s.advisory}</div>
                  </td>
                  <td className={`text-right px-3 py-2 tabular-nums font-medium ${s.estimated_portfolio_pnl_pct < 0 ? "text-red-400" : "text-green-400"}`}>
                    {pct(s.estimated_portfolio_pnl_pct)}
                  </td>
                  <td className={`text-right px-3 py-2 tabular-nums ${s.estimated_portfolio_pnl < 0 ? "text-red-400" : "text-green-400"}`}>
                    {s.estimated_portfolio_pnl < 0 ? "−" : "+"}{inr(Math.abs(s.estimated_portfolio_pnl))}
                  </td>
                  <td className="text-center px-3 py-2"><SevBadge sev={s.severity} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {stress?.monte_carlo_simulation?.enabled === false && (
        <div className="flex items-start gap-2 rounded-lg border border-dashed border-border bg-muted/10 p-3 text-xs text-muted-foreground">
          <Info className="h-3.5 w-3.5 shrink-0 mt-0.5" />
          <span>
            <strong>Monte Carlo Simulation</strong> — future-ready hook.{" "}
            {stress.monte_carlo_simulation.note}
          </span>
        </div>
      )}
    </SectionCard>
  );
}

function Section9Recommendations({ recs }: { recs: any }) {
  const explanations: any[] = recs?.explanations ?? [];
  const total = recs?.total_recommendations ?? 0;
  const high = recs?.high_priority ?? 0;
  const medium = recs?.medium_priority ?? 0;
  const low = recs?.low_priority ?? 0;

  return (
    <SectionCard title="📋 Recommendations">
      {total === 0 ? (
        <p className="text-xs text-muted-foreground/60">No recommendations generated yet — complete paper trades to receive advisory guidance.</p>
      ) : (
        <div className="space-y-3">
          {/* Priority summary */}
          <div className="flex gap-3 text-xs text-muted-foreground">
            <span>{total} recommendations</span>
            {high > 0 && <span className="text-red-400 font-medium">{high} HIGH</span>}
            {medium > 0 && <span className="text-yellow-400 font-medium">{medium} MEDIUM</span>}
            {low > 0 && <span className="text-blue-400 font-medium">{low} LOW</span>}
          </div>

          {/* Advisory banner */}
          <div className="flex items-center gap-2 rounded-lg border border-border bg-muted/20 p-2.5 text-[10px] text-muted-foreground">
            <Activity className="h-3.5 w-3.5 shrink-0 text-primary" />
            <span>All recommendations are <strong>advisory-only</strong>. No risk parameters are automatically modified.</span>
          </div>

          {/* Cards */}
          <div className="space-y-2">
            {explanations.map((ex: any, i: number) => (
              <div key={i} className="rounded-lg border border-border bg-card/40 p-3 space-y-2">
                <div className="flex items-start justify-between gap-2">
                  <div className="space-y-0.5 flex-1">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="text-[10px] uppercase tracking-wide text-muted-foreground">{ex.category}</span>
                      <PriBadge pri={ex.priority} />
                      <Badge variant="outline" className="text-[9px] text-muted-foreground/60">
                        {ex.confidence} confidence
                      </Badge>
                    </div>
                    <p className="text-xs font-medium text-foreground">{ex.recommendation}</p>
                  </div>
                  <ChevronRight className="h-3.5 w-3.5 text-muted-foreground/40 shrink-0 mt-1" />
                </div>
                <p className="text-[11px] text-muted-foreground leading-relaxed">{ex.reason}</p>
                <div className="flex flex-wrap gap-x-4 gap-y-1 text-[10px] text-muted-foreground">
                  {ex.suggested_action && (
                    <span>Suggested: <strong className="text-foreground">{ex.suggested_action}</strong></span>
                  )}
                  {ex.expected_benefit && (
                    <span>Benefit: <strong className="text-green-400">{ex.expected_benefit}</strong></span>
                  )}
                  {ex.risk_reduction && (
                    <span>Risk reduction: <strong className="text-blue-400">{ex.risk_reduction}</strong></span>
                  )}
                </div>
                <p className="text-[10px] text-muted-foreground/50">{ex.historical_evidence}</p>
              </div>
            ))}
          </div>
        </div>
      )}
    </SectionCard>
  );
}

function Section10HistoricalTrend({ summary }: { summary: any }) {
  const n = summary?.total_trades ?? 0;
  return (
    <SectionCard title="📈 Historical Risk Trend">
      <div className="space-y-3">
        {n === 0 ? <EmptyState /> : (
          <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
            <Stat label="Risk Score" value={fmt(summary?.risk_optimisation_score) + "/100"} />
            <Stat label="Grade" value={summary?.grade ?? "—"} />
            <Stat label="Trend" value={summary?.trend ?? "STABLE"} />
            <Stat label="Max Drawdown" value={pct(summary?.max_drawdown)} />
            <Stat label="Capital Util." value={pct(summary?.capital_utilisation_rate)} />
            <Stat label="Win Rate" value={pct(summary?.win_rate)} />
          </div>
        )}
        {/* Future hook explanation */}
        <div className="flex items-start gap-2 rounded-lg border border-dashed border-border bg-muted/10 p-3 text-xs text-muted-foreground">
          <Info className="h-3.5 w-3.5 shrink-0 mt-0.5" />
          <div className="space-y-1">
            <p><strong>Rolling Historical Trend</strong> — future enhancement.</p>
            <p>
              A time-series risk score chart will display here once 30+ paper trades are recorded.
              Future integration with Monte Carlo simulation will provide confidence intervals
              for drawdown projections and capital-at-risk estimates.
            </p>
          </div>
        </div>
      </div>
    </SectionCard>
  );
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

export default function RiskOptimisation() {
  const summary = useSummary();
  const capital = useCapital();
  const drawdown = useDrawdown();
  const stress = useStress();
  const recs = useRecommendations();

  const isLoading = summary.isLoading || capital.isLoading || drawdown.isLoading;
  const summaryData: any = summary.data;
  const capitalData: any = capital.data;
  const drawdownData: any = drawdown.data;
  const stressData: any = stress.data;
  const recsData: any = recs.data;

  const isDisabled =
    summaryData?.status === "DISABLED" ||
    capitalData?.status === "DISABLED";

  function refetchAll() {
    summary.refetch();
    capital.refetch();
    drawdown.refetch();
    stress.refetch();
    recs.refetch();
  }

  function handleExportCSV() {
    window.open(
      (import.meta.env.BASE_URL ?? "/").replace(/\/$/, "") + "/api/risk-optimisation/export/csv",
      "_blank"
    );
  }
  function handleExportJSON() {
    window.open(
      (import.meta.env.BASE_URL ?? "/").replace(/\/$/, "") + "/api/risk-optimisation/export/json",
      "_blank"
    );
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center gap-3 justify-between">
        <div className="flex items-center gap-3">
          <ShieldCheck className="h-6 w-6 text-primary" />
          <div>
            <h1 className="text-xl font-bold">Risk Optimisation</h1>
            <p className="text-xs text-muted-foreground">Capital Allocation & Risk Intelligence</p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <Badge variant="outline" className="text-[10px] font-bold text-amber-400 border-amber-500/30 bg-amber-500/10">
            RISK OPTIMISATION — ADVISORY ONLY — NO PARAMETERS AUTO-MODIFIED
          </Badge>
          <Button variant="outline" size="sm" className="h-7 gap-1.5 text-xs" onClick={refetchAll} disabled={isLoading}>
            <RefreshCw className={`h-3.5 w-3.5 ${isLoading ? "animate-spin" : ""}`} />
            Refresh
          </Button>
          <Button variant="outline" size="sm" className="h-7 gap-1.5 text-xs" onClick={handleExportCSV}>
            <Download className="h-3.5 w-3.5" />
            Export CSV
          </Button>
          <Button variant="outline" size="sm" className="h-7 gap-1.5 text-xs" onClick={handleExportJSON}>
            <Download className="h-3.5 w-3.5" />
            Export JSON
          </Button>
        </div>
      </div>

      {/* Loading */}
      {isLoading && (
        <div className="rounded-xl border border-border bg-card/50 p-8 text-center">
          <RefreshCw className="h-6 w-6 mx-auto text-muted-foreground animate-spin mb-2" />
          <p className="text-sm text-muted-foreground">Loading risk optimisation data…</p>
        </div>
      )}

      {/* Disabled */}
      {!isLoading && isDisabled && <DisabledState />}

      {/* Content */}
      {!isLoading && !isDisabled && (
        <div className="space-y-5">
          {/* Section 1: Risk Health */}
          <Section1RiskHealth summary={summaryData} />

          {/* Sections 2 + 3 side-by-side on wide screens */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
            <Section2CapitalAllocation capital={capitalData} />
            <Section3PositionSizing capital={capitalData} />
          </div>

          {/* Section 4: Sector Diversification */}
          <Section4SectorDiversification capital={capitalData} />

          {/* Section 5: Drawdown */}
          <Section5DrawdownAnalysis dd={drawdownData} />

          {/* Sections 6 + 7 side-by-side */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
            <Section6StopLossAnalysis capital={capitalData} />
            <Section7TargetAnalysis capital={capitalData} />
          </div>

          {/* Section 8: Stress Testing */}
          <Section8StressTesting stress={stressData} />

          {/* Section 9: Recommendations */}
          <Section9Recommendations recs={recsData} />

          {/* Section 10: Historical Risk Trend */}
          <Section10HistoricalTrend summary={summaryData} />
        </div>
      )}
    </div>
  );
}
