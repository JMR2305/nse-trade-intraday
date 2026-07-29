/**
 * MarketIntelligenceHub.tsx — Phase 7.1
 * Unified Market Intelligence Hub dashboard page.
 *
 * Sections:
 *   1. Market Overview (regime, indices, VIX)
 *   2. Market Health Score (ring + grade)
 *   3. Multi-Timeframe Analysis
 *   4. Sector Intelligence (heat + ranking)
 *   5. Market Breadth (advancers / decliners)
 *   6. Volatility Analysis
 *   7. Watchlist Intelligence (ranked table)
 *   8. Top Opportunities
 *   9. Daily Intelligence Summary (evidence + outlook)
 *
 * READ-ONLY. ADVISORY-ONLY.
 */
import { useQuery } from "@tanstack/react-query";
import { apiJson } from "@/lib/api";

const Q = { refetchInterval: 30_000, retry: 1 } as const;

function useSummary()   { return useQuery({ queryKey: ["mi-summary"],   queryFn: () => apiJson("market-intelligence/summary"),   ...Q }); }
function useOverview()  { return useQuery({ queryKey: ["mi-overview"],  queryFn: () => apiJson("market-intelligence/overview"),  ...Q }); }
function useSectors()   { return useQuery({ queryKey: ["mi-sectors"],   queryFn: () => apiJson("market-intelligence/sectors"),   ...Q }); }
function useBreadth()   { return useQuery({ queryKey: ["mi-breadth"],   queryFn: () => apiJson("market-intelligence/breadth"),   ...Q }); }
function useWatchlist() { return useQuery({ queryKey: ["mi-watchlist"], queryFn: () => apiJson("market-intelligence/watchlist"), ...Q }); }

// ── Helpers ──────────────────────────────────────────────────────────────────

function fmt(n: number | undefined | null, dec = 2) {
  if (n == null) return "—";
  return n.toFixed(dec);
}
function fmtPct(n: number | undefined | null, dec = 2) {
  if (n == null) return "—";
  return `${n >= 0 ? "+" : ""}${(n * 100).toFixed(dec)}%`;
}
function fmtInr(n: number | undefined | null) {
  if (n == null) return "—";
  return `₹${n.toLocaleString("en-IN", { maximumFractionDigits: 0 })}`;
}

function regimeCls(r: string) {
  const m: Record<string, string> = {
    BULL: "text-emerald-400", BEAR: "text-rose-400", SIDEWAYS: "text-zinc-400",
    TRENDING: "text-sky-400", HIGH_VOLATILITY: "text-orange-400",
    LOW_VOLATILITY: "text-teal-400", BREAKOUT: "text-violet-400",
    REVERSAL: "text-amber-400", TRANSITION: "text-yellow-400",
  };
  return m[r] ?? "text-zinc-300";
}

function trendArrow(t: string) {
  if (t === "UP") return <span className="text-emerald-400">▲</span>;
  if (t === "DOWN") return <span className="text-rose-400">▼</span>;
  return <span className="text-zinc-500">—</span>;
}

function changeCls(n: number) { return n >= 0 ? "text-emerald-400" : "text-rose-400"; }

function actionBadge(a: string) {
  const cls: Record<string, string> = {
    STRONG_BUY: "bg-emerald-600/25 text-emerald-300 border-emerald-700",
    BUY:        "bg-sky-600/25 text-sky-300 border-sky-700",
    WATCH:      "bg-amber-600/25 text-amber-300 border-amber-700",
    IGNORE:     "bg-zinc-700/40 text-zinc-500 border-zinc-600",
  };
  return (
    <span className={`px-1.5 py-0.5 rounded border text-xs font-semibold ${cls[a] ?? "bg-zinc-700/30 text-zinc-400 border-zinc-600"}`}>
      {a.replace("_", " ")}
    </span>
  );
}

function heatCls(h: string) {
  const m: Record<string, string> = {
    HOT: "text-rose-400", WARM: "text-orange-400", NEUTRAL: "text-zinc-300",
    COOL: "text-sky-400", COLD: "text-blue-500",
  };
  return m[h] ?? "text-zinc-400";
}

function ScoreBar({ score, color = "bg-sky-500" }: { score: number; color?: string }) {
  const pct = Math.min(100, Math.max(0, score ?? 0));
  return (
    <div className="w-full bg-zinc-800 rounded-full h-1.5">
      <div className={`${color} h-1.5 rounded-full transition-all`} style={{ width: `${pct}%` }} />
    </div>
  );
}

function Card({ title, children, className = "" }: { title: string; children: React.ReactNode; className?: string }) {
  return (
    <div className={`bg-zinc-900 border border-zinc-800 rounded-xl p-4 ${className}`}>
      <h3 className="text-xs font-semibold text-zinc-400 uppercase tracking-widest mb-3">{title}</h3>
      {children}
    </div>
  );
}

function Loading() {
  return <div className="text-zinc-600 text-sm animate-pulse">Loading…</div>;
}

function Disabled() {
  return (
    <div className="bg-zinc-800 border border-zinc-700 rounded-xl p-5 text-zinc-400 text-sm">
      Market Intelligence Hub is disabled. Set{" "}
      <code className="text-amber-400 bg-zinc-900 px-1 rounded">MARKET_INTELLIGENCE_HUB_ENABLED=true</code>{" "}
      to enable.
    </div>
  );
}

function gradeColor(g: string) {
  return { "A+": "text-emerald-400", A: "text-emerald-400", B: "text-sky-400", C: "text-amber-400", D: "text-rose-400" }[g] ?? "text-zinc-300";
}

function TrendBadge({ trend }: { trend: string }) {
  if (trend === "IMPROVING") return <span className="bg-emerald-600/20 text-emerald-400 border border-emerald-700 text-xs px-2 py-0.5 rounded">↑ Improving</span>;
  if (trend === "WEAKENING") return <span className="bg-rose-600/20 text-rose-400 border border-rose-700 text-xs px-2 py-0.5 rounded">↓ Weakening</span>;
  return <span className="bg-zinc-700/30 text-zinc-400 border border-zinc-600 text-xs px-2 py-0.5 rounded">→ Stable</span>;
}

function TfTrend({ t }: { t: string }) {
  const cls: Record<string, string> = { UP: "text-emerald-400", DOWN: "text-rose-400", NEUTRAL: "text-zinc-500", UNAVAILABLE: "text-zinc-700" };
  return <span className={cls[t] ?? "text-zinc-400"}>{t === "UNAVAILABLE" ? "N/A" : t}</span>;
}

function RotationTag({ r }: { r: string }) {
  if (r === "INFLOW")  return <span className="text-emerald-400 text-xs">↑ Inflow</span>;
  if (r === "OUTFLOW") return <span className="text-rose-400 text-xs">↓ Outflow</span>;
  return <span className="text-zinc-600 text-xs">→ Stable</span>;
}

function EvidenceWeight({ w }: { w: string }) {
  if (w === "+") return <span className="text-emerald-400 font-bold w-3 flex-shrink-0">+</span>;
  if (w === "-") return <span className="text-rose-400 font-bold w-3 flex-shrink-0">−</span>;
  return <span className="text-zinc-500 w-3 flex-shrink-0">~</span>;
}

// ── Page ─────────────────────────────────────────────────────────────────────

export default function MarketIntelligenceHub() {
  const { data: summary, isLoading: sumLoad }  = useSummary();
  const { data: overview, isLoading: ovLoad }  = useOverview();
  const { data: sectors, isLoading: secLoad }  = useSectors();
  const { data: breadth, isLoading: brLoad }   = useBreadth();
  const { data: watchlist, isLoading: wlLoad } = useWatchlist();

  const s  = summary  as any;
  const ov = overview as any;
  const sc = sectors  as any;
  const br = breadth  as any;
  const wl = watchlist as any;

  if (s?.status === "DISABLED") return <div className="p-6"><Disabled /></div>;

  const regime     = ov?.regime ?? {};
  const mtf        = ov?.multi_timeframe ?? {};
  const vol        = ov?.volatility ?? {};
  const sectorHeat = ov?.sector_heat ?? {};

  return (
    <div className="p-4 space-y-4 text-zinc-100 max-w-screen-xl mx-auto">

      {/* ── Header ─────────────────────────────────────────────────────── */}
      <div className="flex items-center justify-between flex-wrap gap-2">
        <div>
          <h1 className="text-xl font-bold text-white">Market Intelligence Hub</h1>
          <p className="text-xs text-zinc-500 mt-0.5">Advisory-only · Read-only · Auto-refreshes every 30 s</p>
        </div>
        {s && (
          <div className="flex items-center gap-3">
            <TrendBadge trend={s.trend ?? "STABLE"} />
            <span className="text-xs text-zinc-600">{s.total_symbols_analysed ?? 0} symbols analysed</span>
          </div>
        )}
      </div>

      {/* ── 1. Market Overview (4-column) ─────────────────────────────── */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <Card title="Regime" className="col-span-2 lg:col-span-1">
          {ovLoad ? <Loading /> : (
            <>
              <div className={`text-2xl font-bold ${regimeCls(regime.regime ?? "")}`}>
                {regime.regime ?? "—"}
              </div>
              <div className="text-xs text-zinc-500 mt-0.5">{regime.sub_regime ?? ""}</div>
              <div className="text-xs text-zinc-400 mt-2 line-clamp-3">{regime.description ?? ""}</div>
            </>
          )}
        </Card>

        <Card title="NIFTY 50">
          {ovLoad ? <Loading /> : (
            <>
              <div className="text-xl font-bold text-white">{fmtInr(regime.nifty_price)}</div>
              <div className={`flex items-center gap-1 mt-1 text-sm ${changeCls(regime.nifty_change_pct ?? 0)}`}>
                {trendArrow(regime.nifty_trend ?? "")} {fmtPct(regime.nifty_change_pct)}
              </div>
            </>
          )}
        </Card>

        <Card title="Bank NIFTY">
          {ovLoad ? <Loading /> : (
            <>
              <div className="text-xl font-bold text-white">{fmtInr(regime.banknifty_price)}</div>
              <div className={`flex items-center gap-1 mt-1 text-sm ${changeCls(regime.banknifty_change_pct ?? 0)}`}>
                {trendArrow(regime.banknifty_trend ?? "")} {fmtPct(regime.banknifty_change_pct)}
              </div>
            </>
          )}
        </Card>

        <Card title="India VIX">
          {ovLoad ? <Loading /> : (
            <>
              <div className="text-xl font-bold text-white">{fmt(vol.vix_value)}</div>
              <div className={`text-xs font-semibold mt-1 ${
                vol.vix_status === "LOW" ? "text-emerald-400" :
                vol.vix_status === "HIGH" ? "text-orange-400" :
                vol.vix_status === "EXTREME" ? "text-rose-400" : "text-zinc-400"
              }`}>{vol.vix_status ?? "—"}</div>
              <div className="text-xs text-zinc-500 mt-1">{vol.gap_risk ?? "—"} gap risk</div>
            </>
          )}
        </Card>
      </div>

      {/* ── 2. Market Health Score ─────────────────────────────────────── */}
      <Card title="Market Health">
        {sumLoad ? <Loading /> : s ? (
          <div className="flex items-center gap-6">
            {/* Radial ring */}
            <div className="relative w-20 h-20 flex-shrink-0">
              <svg viewBox="0 0 80 80" className="w-20 h-20 -rotate-90">
                <circle cx="40" cy="40" r="32" fill="none" stroke="#27272a" strokeWidth="8" />
                <circle
                  cx="40" cy="40" r="32" fill="none"
                  stroke={s.market_health_score >= 75 ? "#34d399" : s.market_health_score >= 55 ? "#38bdf8" : "#f87171"}
                  strokeWidth="8"
                  strokeDasharray={`${s.market_health_score * 2.01} 201`}
                  strokeLinecap="round"
                />
              </svg>
              <div className="absolute inset-0 flex flex-col items-center justify-center">
                <span className={`text-lg font-bold leading-none ${gradeColor(s.grade)}`}>{s.grade}</span>
                <span className="text-xs text-zinc-500">{fmt(s.market_health_score, 0)}</span>
              </div>
            </div>
            <div className="flex-1 space-y-2">
              <div className="flex items-center gap-2">
                <TrendBadge trend={s.trend ?? "STABLE"} />
                <span className="text-xs text-zinc-500">Score: {fmt(s.market_health_score)}%</span>
              </div>
              <p className="text-xs text-zinc-400 leading-relaxed">{s.overall_outlook}</p>
              {(s.strongest_sectors?.length ?? 0) > 0 && (
                <div className="flex gap-1.5 flex-wrap items-center">
                  <span className="text-xs text-zinc-600">Leaders:</span>
                  {(s.strongest_sectors ?? []).map((sec: string) => (
                    <span key={sec} className="bg-emerald-900/30 text-emerald-400 text-xs px-1.5 py-0.5 rounded border border-emerald-900">{sec}</span>
                  ))}
                </div>
              )}
            </div>
          </div>
        ) : null}
      </Card>

      {/* ── 3. Multi-Timeframe Analysis ────────────────────────────────── */}
      <Card title="Multi-Timeframe Analysis">
        {ovLoad ? <Loading /> : (
          <>
            <div className="flex items-center gap-4 mb-3 flex-wrap text-sm">
              <span className="text-zinc-500 text-xs">Alignment
                <span className="text-white font-bold ml-1">{fmt(mtf.alignment_score)}%</span>
              </span>
              <span className={`text-xs font-semibold ${
                (mtf.agreement ?? "").includes("BULLISH") ? "text-emerald-400" :
                (mtf.agreement ?? "").includes("BEARISH") ? "text-rose-400" : "text-zinc-400"
              }`}>{mtf.agreement ?? "—"}</span>
              <span className="text-zinc-600 text-xs">▲{mtf.up_count ?? 0} ▼{mtf.down_count ?? 0} —{mtf.neutral_count ?? 0}</span>
            </div>
            <ScoreBar score={mtf.alignment_score ?? 50} />
            <div className="mt-3 grid grid-cols-3 sm:grid-cols-4 lg:grid-cols-7 gap-2">
              {(mtf.timeframes ?? []).map((tf: any) => (
                <div key={tf.key} className="bg-zinc-800/60 rounded-lg p-2 text-center">
                  <div className="text-xs text-zinc-500 mb-1">{tf.label}</div>
                  <TfTrend t={tf.trend} />
                  <div className="text-xs text-zinc-700 mt-0.5">{fmt(tf.strength, 0)}%</div>
                </div>
              ))}
            </div>
          </>
        )}
      </Card>

      {/* ── 4. Sector Intelligence ─────────────────────────────────────── */}
      <Card title="Sector Intelligence">
        {secLoad ? <Loading /> : (
          <>
            <div className="flex gap-4 mb-3 text-xs text-zinc-500 flex-wrap">
              <span>Leader: <span className="text-emerald-400 font-semibold">{sc?.strongest_sector ?? "—"}</span></span>
              <span>Weakest: <span className="text-rose-400 font-semibold">{sc?.weakest_sector ?? "—"}</span></span>
              <span>Avg: <span className="text-white">{fmt(sc?.avg_sector_strength ?? 0)}%</span></span>
              {(sc?.rotation_leaders?.length ?? 0) > 0 && (
                <span>Inflow: <span className="text-emerald-400">{sc?.rotation_leaders?.join(", ")}</span></span>
              )}
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead>
                  <tr className="text-zinc-500 text-left border-b border-zinc-800">
                    {["#", "Sector", "Strength", "Momentum", "Stocks", "Heat", "Rotation"].map(h => (
                      <th key={h} className="pb-2 pr-3 font-medium">{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {(sc?.sectors ?? []).map((s: any) => (
                    <tr key={s.sector} className="border-b border-zinc-800/40 hover:bg-zinc-800/30 transition-colors">
                      <td className="py-2 pr-3 text-zinc-600">{s.rank}</td>
                      <td className="py-2 pr-3 font-medium text-zinc-200">
                        {s.leadership && <span className="text-amber-400 mr-1">★</span>}{s.sector}
                      </td>
                      <td className="py-2 pr-3">
                        <div className="flex items-center gap-2">
                          <div className="w-14"><ScoreBar score={s.relative_strength} /></div>
                          <span className="text-zinc-300 w-7">{fmt(s.relative_strength, 0)}</span>
                        </div>
                      </td>
                      <td className={`py-2 pr-3 font-medium ${s.momentum >= 0 ? "text-emerald-400" : "text-rose-400"}`}>
                        {s.momentum >= 0 ? "+" : ""}{fmt(s.momentum, 0)}
                      </td>
                      <td className="py-2 pr-3 text-zinc-400">{s.participation}</td>
                      <td className={`py-2 pr-3 font-semibold ${heatCls(s.heat)}`}>{s.heat}</td>
                      <td className="py-2"><RotationTag r={s.rotation_signal} /></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}
      </Card>

      {/* ── 5. Breadth + Sector Participation ────────────────────────── */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        <Card title="Market Breadth">
          {brLoad ? <Loading /> : (
            <>
              <div className="flex items-center justify-around mb-3">
                {[
                  { val: br?.advancers ?? 0, label: "Advancing", cls: "text-emerald-400" },
                  { val: br?.neutral ?? 0,   label: "Neutral",   cls: "text-zinc-500" },
                  { val: br?.decliners ?? 0, label: "Declining", cls: "text-rose-400" },
                ].map(({ val, label, cls }) => (
                  <div key={label} className="text-center">
                    <div className={`text-2xl font-bold ${cls}`}>{val}</div>
                    <div className="text-xs text-zinc-600">{label}</div>
                  </div>
                ))}
              </div>
              {/* A/D bar */}
              <div className="flex h-2.5 rounded-full overflow-hidden mb-2">
                <div className="bg-emerald-500 transition-all" style={{ width: `${(br?.advancers ?? 0) / Math.max(br?.total ?? 1, 1) * 100}%` }} />
                <div className="bg-zinc-600 transition-all" style={{ width: `${(br?.neutral ?? 0) / Math.max(br?.total ?? 1, 1) * 100}%` }} />
                <div className="bg-rose-500 transition-all flex-1" />
              </div>
              <div className="flex justify-between text-xs text-zinc-500">
                <span>Breadth: <span className="text-white font-medium">{br?.breadth_label ?? "—"}</span></span>
                <span className={br?.breadth_momentum === "IMPROVING" ? "text-emerald-400" : br?.breadth_momentum === "WORSENING" ? "text-rose-400" : "text-zinc-400"}>
                  {br?.breadth_momentum ?? "STABLE"}
                </span>
                <span>A/D: <span className="text-white">{fmt(br?.advance_decline_ratio ?? 0.5)}</span></span>
              </div>
            </>
          )}
        </Card>

        <Card title="Sector Participation">
          {brLoad ? <Loading /> : (
            <>
              <div className="text-xs text-zinc-500 mb-2">
                {br?.participating_sectors ?? 0} of {br?.total_sectors_scanned ?? 0} sectors participating
              </div>
              <div className="space-y-1.5 max-h-44 overflow-y-auto pr-1">
                {(br?.sector_participation ?? []).slice(0, 8).map((sp: any) => (
                  <div key={sp.sector} className="flex items-center gap-2">
                    <span className="text-xs text-zinc-400 w-24 truncate">{sp.sector}</span>
                    <div className="flex-1 bg-zinc-800 rounded-full h-1.5">
                      <div
                        className={`h-1.5 rounded-full ${sp.participating ? "bg-emerald-500" : "bg-zinc-600"}`}
                        style={{ width: `${sp.participation_rate * 100}%` }}
                      />
                    </div>
                    <span className={`text-xs w-7 text-right ${sp.participating ? "text-emerald-400" : "text-zinc-600"}`}>
                      {Math.round(sp.participation_rate * 100)}%
                    </span>
                  </div>
                ))}
              </div>
            </>
          )}
        </Card>
      </div>

      {/* ── 6. Volatility ─────────────────────────────────────────────── */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
        <Card title="Volatility Regime">
          {ovLoad ? <Loading /> : (
            <>
              <div className={`text-base font-bold mb-1 ${
                (vol.volatility_regime ?? "").includes("HIGH") ? "text-orange-400" :
                (vol.volatility_regime ?? "").includes("LOW") ? "text-emerald-400" : "text-sky-400"
              }`}>{(vol.volatility_regime ?? "—").replace(/_/g, " ")}</div>
              <ScoreBar score={vol.volatility_score ?? 50} color="bg-teal-500" />
              <div className="mt-2 grid grid-cols-2 gap-x-3 text-xs">
                <div className="text-zinc-500">ATR Trend <span className="text-zinc-300 font-medium">{vol.atr_trend ?? "—"}</span></div>
                <div className="text-zinc-500">Expansion <span className="text-zinc-300 font-medium">{vol.expansion ?? "—"}</span></div>
                <div className="text-zinc-500 mt-1">Avg ATR <span className="text-zinc-300 font-medium">{fmt(vol.atr_avg ?? 0)}</span></div>
                <div className="text-zinc-500 mt-1">Gap Risk <span className={`font-medium ${
                  vol.gap_risk === "HIGH" ? "text-orange-400" : vol.gap_risk === "LOW" ? "text-emerald-400" : "text-amber-400"
                }`}>{vol.gap_risk ?? "—"}</span></div>
              </div>
            </>
          )}
        </Card>

        <Card title="High Volatility Symbols" className="md:col-span-2">
          {ovLoad ? <Loading /> : (
            <>
              <div className="text-xs text-zinc-500 mb-2">
                {vol.high_vol_symbols ?? 0} high-vol symbols of {vol.symbol_volatility?.length ?? 0} analysed
              </div>
              <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-1.5">
                {(vol.symbol_volatility ?? []).filter((s: any) => s.vol_level === "HIGH").slice(0, 8).map((sv: any) => (
                  <div key={sv.symbol} className="bg-zinc-800/60 rounded p-2 text-xs">
                    <div className="font-medium text-orange-300">{sv.symbol}</div>
                    <div className="text-zinc-500">ATR {fmt(sv.atr)} ({fmt(sv.atr_pct * 100, 2)}%)</div>
                  </div>
                ))}
                {(vol.symbol_volatility ?? []).filter((s: any) => s.vol_level === "HIGH").length === 0 && (
                  <div className="text-zinc-600 text-xs col-span-4">No high-volatility symbols — favourable conditions.</div>
                )}
              </div>
            </>
          )}
        </Card>
      </div>

      {/* ── 7. Watchlist Intelligence ──────────────────────────────────── */}
      <Card title="Watchlist Intelligence — Regime-Adjusted Rankings">
        {wlLoad ? <Loading /> : (
          <>
            <div className="flex items-center gap-4 mb-3 text-xs text-zinc-500 flex-wrap">
              <span>Regime: <span className="text-sky-400 font-semibold">{wl?.regime ?? "—"}</span></span>
              <span>Adjusted: <span className={wl?.regime_adjusted ? "text-emerald-400" : "text-zinc-500"}>{wl?.regime_adjusted ? "Yes ✦" : "No"}</span></span>
              <span>Avg composite: <span className="text-white font-medium">{fmt(wl?.avg_composite_score ?? 0)}</span></span>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead>
                  <tr className="text-zinc-500 text-left border-b border-zinc-800">
                    {["#", "Symbol", "Sector", "Action", "Priority", "Opportunity", "Risk", "Composite", "Reason"].map(h => (
                      <th key={h} className="pb-2 pr-3 font-medium">{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {(wl?.watchlist ?? []).slice(0, 15).map((w: any) => (
                    <tr key={w.symbol} className="border-b border-zinc-800/40 hover:bg-zinc-800/30 transition-colors">
                      <td className="py-1.5 pr-3 text-zinc-600">{w.rank}</td>
                      <td className="py-1.5 pr-3 font-semibold text-zinc-200">
                        {w.symbol}{w.regime_adjusted && <span className="text-amber-500 ml-0.5">✦</span>}
                      </td>
                      <td className="py-1.5 pr-3 text-zinc-500">{w.sector}</td>
                      <td className="py-1.5 pr-3">{actionBadge(w.final_action)}</td>
                      <td className="py-1.5 pr-3">
                        <div className="flex items-center gap-1">
                          <div className="w-10"><ScoreBar score={w.priority_score} color="bg-violet-500" /></div>
                          <span className="text-zinc-300 w-5">{Math.round(w.priority_score)}</span>
                        </div>
                      </td>
                      <td className="py-1.5 pr-3 text-sky-300">{fmt(w.opportunity_score, 0)}</td>
                      <td className={`py-1.5 pr-3 ${w.risk_score > 60 ? "text-rose-400" : w.risk_score > 30 ? "text-amber-400" : "text-emerald-400"}`}>
                        {fmt(w.risk_score, 0)}
                      </td>
                      <td className="py-1.5 pr-3 font-bold text-white">{fmt(w.composite_score, 0)}</td>
                      <td className="py-1.5 text-zinc-500 max-w-[160px] truncate">{w.reason}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="text-xs text-zinc-700 mt-2">✦ Score regime-adjusted · Advisory only — not a trade recommendation</p>
          </>
        )}
      </Card>

      {/* ── 8. Top Opportunities ───────────────────────────────────────── */}
      <Card title="Top Opportunities">
        {sumLoad ? <Loading /> : (
          <>
            {(s?.top_opportunities?.length ?? 0) === 0 ? (
              <div className="text-zinc-500 text-sm">No active opportunities — scan data pending or all signals are WATCH/IGNORE.</div>
            ) : (
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
                {(s?.top_opportunities ?? []).map((opp: any) => (
                  <div key={opp.symbol} className="bg-zinc-800/60 border border-zinc-700 rounded-lg p-3">
                    <div className="flex items-start justify-between mb-2">
                      <div>
                        <div className="font-bold text-white">{opp.symbol}</div>
                        <div className="text-xs text-zinc-500">{opp.sector}</div>
                      </div>
                      {actionBadge(opp.final_action)}
                    </div>
                    <p className="text-xs text-zinc-400 mb-2 line-clamp-2">{opp.reason}</p>
                    <div className="grid grid-cols-3 gap-1 text-xs">
                      <div><div className="text-zinc-600">Priority</div><div className="text-violet-300 font-medium">{fmt(opp.priority_score, 0)}</div></div>
                      <div><div className="text-zinc-600">Opportunity</div><div className="text-sky-300 font-medium">{fmt(opp.opportunity_score, 0)}</div></div>
                      <div><div className="text-zinc-600">Composite</div><div className="text-white font-bold">{fmt(opp.composite_score, 0)}</div></div>
                    </div>
                    <div className="mt-2 text-xs text-zinc-600">{fmtInr(opp.price)}</div>
                  </div>
                ))}
              </div>
            )}
          </>
        )}
      </Card>

      {/* ── 9. Daily Intelligence Summary ─────────────────────────────── */}
      <Card title="Daily Intelligence Summary">
        {sumLoad ? <Loading /> : s ? (
          <>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div>
                <div className="text-xs text-zinc-500 mb-1">Market Outlook</div>
                <p className="text-sm text-zinc-300 leading-relaxed">{s.overall_outlook}</p>
                <div className="mt-3 flex flex-wrap gap-1.5 items-center">
                  <span className="text-xs text-zinc-600">Strongest:</span>
                  {(s.strongest_sectors ?? []).map((sec: string) => (
                    <span key={sec} className="bg-emerald-900/25 text-emerald-400 text-xs px-1.5 py-0.5 rounded border border-emerald-900">{sec}</span>
                  ))}
                  {(s.strongest_sectors ?? []).length === 0 && <span className="text-zinc-600 text-xs">Scan pending</span>}
                </div>
                <div className="mt-1 flex flex-wrap gap-1.5 items-center">
                  <span className="text-xs text-zinc-600">Weakest:</span>
                  {(s.weakest_sectors ?? []).map((sec: string) => (
                    <span key={sec} className="bg-rose-900/25 text-rose-400 text-xs px-1.5 py-0.5 rounded border border-rose-900">{sec}</span>
                  ))}
                </div>
              </div>
              <div>
                <div className="text-xs text-zinc-500 mb-2">Signal Evidence</div>
                <div className="space-y-1.5">
                  {(s.evidence ?? []).map((ev: any, i: number) => (
                    <div key={i} className="flex items-start gap-1.5 text-xs">
                      <EvidenceWeight w={ev.weight} />
                      <div>
                        <span className="text-zinc-400 font-medium mr-1">{ev.label.replace(/_/g, " ")}</span>
                        <span className="text-zinc-500">{ev.detail}</span>
                      </div>
                    </div>
                  ))}
                  {(s.evidence ?? []).length === 0 && (
                    <div className="text-zinc-600 text-xs">Insufficient data for evidence analysis — run a scan first.</div>
                  )}
                </div>
              </div>
            </div>
            <div className="mt-4 pt-3 border-t border-zinc-800 text-xs text-zinc-600">
              ⚠️ Advisory only — all market intelligence is read-only and does not trigger any trades.
              ApexQuant AI uses this data for situational awareness only.
            </div>
          </>
        ) : null}
      </Card>

    </div>
  );
}
