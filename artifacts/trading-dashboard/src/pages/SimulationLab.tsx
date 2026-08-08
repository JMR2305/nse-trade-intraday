/**
 * Phase 23.8A — AI Simulation Laboratory.
 *
 * Scenario builder + isolated what-if runs, append-only run history,
 * portfolio & execution stress tests, risk-rule A/B comparison and an
 * unlimited scenario comparison table. Everything is advisory and derived —
 * live portfolio, ledger, event store and settings are never modified.
 */
import { useMemo, useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  FlaskConical, Play, Loader2, AlertCircle, Download, Shield,
  Zap, GitCompare, History, RefreshCw,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { apiJson } from "@/lib/api";

const SLOW_MS = 300_000;   // sim runs spawn python + resimulate exits
const MED_MS = 120_000;

// ── types (loose — python is the source of truth) ──────────────────────────
type Dict = Record<string, any>;

const PARAM_FIELDS: { key: string; label: string; ph: string }[] = [
  { key: "capital",                 label: "Capital (₹)",            ph: "e.g. 100000" },
  { key: "position_size_scale",     label: "Position size ×",        ph: "e.g. 1.5" },
  { key: "risk_pct",                label: "Risk per trade %",       ph: "e.g. 1" },
  { key: "min_confidence",          label: "Min confidence",         ph: "e.g. 60" },
  { key: "atr_mult",                label: "ATR / stop ×",           ph: "e.g. 1.5" },
  { key: "trailing_mult",           label: "Trailing stop ×",        ph: "e.g. 1" },
  { key: "risk_reward_mult",        label: "Risk:Reward ×",          ph: "e.g. 1.5" },
  { key: "max_sector_exposure_pct", label: "Max sector exposure %",  ph: "e.g. 40" },
  { key: "max_open_trades",         label: "Max open trades",        ph: "e.g. 5" },
  { key: "daily_loss_limit_pct",    label: "Daily loss limit %",     ph: "e.g. 2" },
  { key: "daily_profit_lock_pct",   label: "Daily profit lock %",    ph: "e.g. 3" },
  { key: "min_volume_ratio",        label: "Min volume ratio",       ph: "e.g. 1.2" },
  { key: "min_traded_value",        label: "Min traded value (₹)",   ph: "liquidity" },
];
const TEXT_FIELDS: { key: string; label: string; ph: string }[] = [
  { key: "regime_filter", label: "Regime filter", ph: "e.g. TRENDING_UP" },
  { key: "sector_filter", label: "Sector filter", ph: "e.g. IT" },
];

const COMPARE_COLS: { key: string; label: string }[] = [
  { key: "trades",             label: "Trades" },
  { key: "win_rate",           label: "Win %" },
  { key: "pnl",                label: "PnL ₹" },
  { key: "sharpe",             label: "Sharpe" },
  { key: "sortino",            label: "Sortino" },
  { key: "max_drawdown_pct",   label: "Max DD %" },
  { key: "profit_factor",      label: "PF" },
  { key: "expectancy",         label: "Expectancy" },
  { key: "recovery_factor",    label: "Recovery" },
  { key: "capital_growth_pct", label: "Growth %" },
  { key: "max_exposure_pct",   label: "Max Expo %" },
  { key: "verdict",            label: "Verdict" },
];

function fmtCell(v: any): string {
  if (v === null || v === undefined) return "—";
  if (typeof v === "number") return Math.abs(v) >= 1000 ? v.toFixed(0) : v.toFixed(2);
  return String(v);
}
function pnlCls(v: any): string {
  const n = Number(v);
  if (!Number.isFinite(n) || n === 0) return "text-muted-foreground";
  return n > 0 ? "text-emerald-400" : "text-red-400";
}

function exportCompareCsv(rows: Dict[]) {
  const headers = ["Label", "Sim ID", ...COMPARE_COLS.map(c => c.label)];
  const csv = [headers, ...rows.map(r =>
    [r.label ?? "", r.sim_id, ...COMPARE_COLS.map(c => fmtCell(r[c.key]))],
  )].map(row => row.map(v => `"${String(v).replace(/"/g, '""')}"`).join(",")).join("\n");
  const blob = new Blob([csv], { type: "text/csv" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = "simulation_comparison.csv";
  a.click();
  URL.revokeObjectURL(url);
}

// ── shared bits ─────────────────────────────────────────────────────────────
function Section({ icon: Icon, title, sub, children }: {
  icon: any; title: string; sub?: string; children: React.ReactNode;
}) {
  return (
    <div className="rounded border border-border bg-card p-4 flex flex-col gap-3">
      <div className="flex items-start gap-2">
        <Icon className="h-4 w-4 text-primary mt-0.5 shrink-0" />
        <div>
          <h2 className="text-sm font-mono font-semibold">{title}</h2>
          {sub && <p className="text-xs text-muted-foreground mt-0.5">{sub}</p>}
        </div>
      </div>
      {children}
    </div>
  );
}

function ErrBox({ msg }: { msg: string }) {
  return (
    <div className="flex items-center gap-2 rounded border border-red-500/30 bg-red-500/10 p-3 text-xs text-red-400 font-mono">
      <AlertCircle className="h-4 w-4 shrink-0" />{msg}
    </div>
  );
}

// ── page ────────────────────────────────────────────────────────────────────
export default function SimulationLab() {
  const qc = useQueryClient();

  // completed backtest runs to base scenarios on
  const runsQ = useQuery<Dict>({
    queryKey: ["sim-base-runs"],
    queryFn: () => apiJson("/backtest/runs", undefined, 60_000),
    retry: 1,
  });
  const baseRuns: Dict[] = useMemo(() => {
    const list = Array.isArray(runsQ.data) ? runsQ.data
      : (runsQ.data as Dict)?.runs ?? [];
    return (list as Dict[]).filter(r => r.status === "COMPLETED");
  }, [runsQ.data]);

  const scenariosQ = useQuery<Dict>({
    queryKey: ["sim-scenarios"],
    queryFn: () => apiJson("/simulation/scenarios", undefined, 60_000),
    retry: 1,
  });
  const [historyLimit, setHistoryLimit] = useState(100);
  const historyQ = useQuery<Dict>({
    queryKey: ["sim-runs", historyLimit],
    queryFn: () => apiJson(`/simulation/runs?limit=${historyLimit}`, undefined, 60_000),
    retry: 1,
  });
  const simRuns: Dict[] = historyQ.data?.runs ?? [];

  // ── scenario builder state ──
  const [name, setName] = useState("");
  const [baseRunId, setBaseRunId] = useState("");
  const [params, setParams] = useState<Dict>({});
  const setP = (k: string, v: string) =>
    setParams(p => ({ ...p, [k]: v }));

  function builtParams(): Dict {
    const out: Dict = {};
    for (const f of PARAM_FIELDS) {
      const v = params[f.key];
      if (v !== undefined && v !== "") {
        const n = Number(v);
        if (Number.isFinite(n)) out[f.key] = n;
      }
    }
    for (const f of TEXT_FIELDS) {
      const v = params[f.key];
      if (v) out[f.key] = String(v);
    }
    return out;
  }

  const createScenario = useMutation({
    mutationFn: () => apiJson("/simulation/scenario", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        name: name || "Scenario", base_run_id: baseRunId || undefined,
        params: builtParams(),
      }),
    }, 60_000),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["sim-scenarios"] }),
  });

  const runSim = useMutation({
    mutationFn: (body: Dict) => apiJson("/simulation/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }, SLOW_MS),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["sim-runs"] }),
  });

  // ── stress tests ──
  const [stressOn, setStressOn] = useState(false);
  const portStressQ = useQuery<Dict>({
    queryKey: ["sim-stress-portfolio"],
    queryFn: () => apiJson("/simulation/stress/portfolio", undefined, MED_MS),
    enabled: stressOn, retry: 0, staleTime: 60_000,
  });
  const execStressQ = useQuery<Dict>({
    queryKey: ["sim-stress-execution"],
    queryFn: () => apiJson("/simulation/stress/execution", undefined, MED_MS),
    enabled: stressOn, retry: 0, staleTime: 60_000,
  });

  // ── risk-rule comparison ──
  const [riskRunId, setRiskRunId] = useState("");
  const [rulesA, setRulesA] = useState('{"risk_pct": 1}');
  const [rulesB, setRulesB] = useState('{"risk_pct": 0.5, "max_open_trades": 3}');
  const riskCompare = useMutation({
    mutationFn: () => {
      let a: Dict = {}; let b: Dict = {};
      try { a = JSON.parse(rulesA); } catch { throw new Error("Rules A is not valid JSON"); }
      try { b = JSON.parse(rulesB); } catch { throw new Error("Rules B is not valid JSON"); }
      return apiJson("/simulation/risk-compare", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ run_id: riskRunId, rules_a: a, rules_b: b }),
      }, SLOW_MS);
    },
  });

  // ── comparison selection ──
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const toggle = (id: string) => setSelected(s => {
    const n = new Set(s);
    if (n.has(id)) n.delete(id); else n.add(id);
    return n;
  });
  // Unlimited comparison via the compare endpoint — works for any number of
  // selected runs, including runs older than the history page shown here.
  const selectedIds = useMemo(() => Array.from(selected).sort(), [selected]);
  const compareQ = useQuery<Dict>({
    queryKey: ["sim-compare", selectedIds],
    queryFn: () => apiJson("/simulation/compare", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ sim_ids: selectedIds }),
    }, MED_MS),
    enabled: selectedIds.length > 0,
    retry: 0,
  });
  const compareRows: Dict[] = useMemo(() =>
    ((compareQ.data?.rows ?? []) as Dict[]).filter(r => r.ok),
    [compareQ.data]);

  // Direct sim-ID add: lets operators compare runs older than the history
  // page without paging through it. Validated via /simulation/run/:id.
  const [addId, setAddId] = useState("");
  const [addErr, setAddErr] = useState("");
  const addById = useMutation({
    mutationFn: (id: string) =>
      apiJson(`/simulation/run/${encodeURIComponent(id)}`, undefined, 60_000),
    onSuccess: (data: Dict, id) => {
      if (data?.ok) {
        setSelected(s => new Set(s).add(id));
        setAddId(""); setAddErr("");
      } else {
        setAddErr(data?.error || `Run ${id} not found`);
      }
    },
    onError: (e) => setAddErr((e as Error).message),
  });

  const scenarios: Dict[] = scenariosQ.data?.scenarios ?? [];

  return (
    <div className="flex flex-col gap-6 p-6 max-w-[1400px]">
      {/* header */}
      <div className="flex items-start gap-3">
        <FlaskConical className="mt-0.5 h-6 w-6 text-primary shrink-0" />
        <div>
          <h1 className="text-2xl font-bold font-mono tracking-tight">AI Simulation Lab</h1>
          <p className="text-sm text-muted-foreground mt-0.5">
            Multi-scenario what-if simulations · stress tests · risk-rule comparison —
            advisory only, fully isolated from live trading
          </p>
        </div>
      </div>

      <div className="flex items-center gap-2 rounded border border-primary/30 bg-primary/5 p-3 text-xs font-mono text-muted-foreground">
        <Shield className="h-4 w-4 text-primary shrink-0" />
        Simulations never write to the live portfolio, paper ledger, event store or settings.
        Run history is append-only — historical runs are never overwritten.
      </div>

      {/* ── scenario builder ── */}
      <Section icon={FlaskConical} title="Scenario Builder"
        sub="Define a named scenario over a completed backtest run. Leave fields blank to keep base behaviour.">
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3">
          <div className="flex flex-col gap-1 col-span-2">
            <label className="text-xs font-mono text-muted-foreground uppercase">Name</label>
            <input value={name} onChange={e => setName(e.target.value)}
              placeholder="e.g. Conservative 0.5% risk"
              className="bg-background border border-border rounded px-3 py-1.5 text-sm font-mono focus:outline-none focus:border-primary" />
          </div>
          <div className="flex flex-col gap-1 col-span-2">
            <label className="text-xs font-mono text-muted-foreground uppercase">Base backtest run</label>
            <select value={baseRunId} onChange={e => setBaseRunId(e.target.value)}
              className="bg-background border border-border rounded px-3 py-1.5 text-sm font-mono focus:outline-none focus:border-primary">
              <option value="">— select completed run —</option>
              {baseRuns.map(r => (
                <option key={r.run_id} value={r.run_id}>
                  {r.run_id} · {(r.config?.start || "").slice(0, 10)}→{(r.config?.end || "").slice(0, 10)}
                </option>
              ))}
            </select>
          </div>
          {PARAM_FIELDS.map(f => (
            <div key={f.key} className="flex flex-col gap-1">
              <label className="text-xs font-mono text-muted-foreground uppercase truncate" title={f.label}>{f.label}</label>
              <input value={params[f.key] ?? ""} onChange={e => setP(f.key, e.target.value)}
                placeholder={f.ph} inputMode="decimal"
                className="bg-background border border-border rounded px-3 py-1.5 text-sm font-mono focus:outline-none focus:border-primary" />
            </div>
          ))}
          {TEXT_FIELDS.map(f => (
            <div key={f.key} className="flex flex-col gap-1">
              <label className="text-xs font-mono text-muted-foreground uppercase">{f.label}</label>
              <input value={params[f.key] ?? ""} onChange={e => setP(f.key, e.target.value)}
                placeholder={f.ph}
                className="bg-background border border-border rounded px-3 py-1.5 text-sm font-mono focus:outline-none focus:border-primary" />
            </div>
          ))}
        </div>
        <div className="flex flex-wrap gap-3">
          <button onClick={() => createScenario.mutate()}
            disabled={createScenario.isPending}
            className="flex items-center gap-2 border border-border text-sm font-mono px-4 py-1.5 rounded hover:bg-accent transition-colors disabled:opacity-60">
            {createScenario.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
            Save Scenario
          </button>
          <button
            onClick={() => runSim.mutate({ run_id: baseRunId, params: builtParams(), label: name || "Ad-hoc what-if" })}
            disabled={runSim.isPending || !baseRunId}
            className="flex items-center gap-2 bg-primary text-primary-foreground text-sm font-mono px-5 py-1.5 rounded hover:bg-primary/90 transition-colors disabled:opacity-60">
            {runSim.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
            {runSim.isPending ? "Simulating…" : "Run Simulation"}
          </button>
        </div>
        {createScenario.isError && <ErrBox msg={String((createScenario.error as Error)?.message)} />}
        {runSim.isError && <ErrBox msg={String((runSim.error as Error)?.message)} />}
        {(runSim.data as Dict)?.ok === false && <ErrBox msg={(runSim.data as Dict).error} />}

        {/* saved scenarios */}
        {scenarios.length > 0 && (
          <div className="flex flex-wrap gap-2">
            {scenarios.map(s => (
              <button key={s.scenario_id}
                onClick={() => runSim.mutate({ scenario_id: s.scenario_id })}
                disabled={runSim.isPending}
                title={JSON.stringify(s.params)}
                className="text-xs font-mono border border-border rounded px-2 py-1 hover:bg-accent transition-colors disabled:opacity-60">
                ▶ {s.name}
              </button>
            ))}
          </div>
        )}
      </Section>

      {/* ── run history + comparison ── */}
      <Section icon={History} title="Simulation Run History"
        sub="Append-only — every execution adds a new run. Select any number of runs to compare.">
        <div className="flex items-center gap-2">
          <button onClick={() => historyQ.refetch()}
            className="flex items-center gap-1 text-xs font-mono border border-border rounded px-2 py-1 hover:bg-accent">
            <RefreshCw className={cn("h-3 w-3", historyQ.isFetching && "animate-spin")} /> Refresh
          </button>
          {simRuns.length >= historyLimit && (
            <button onClick={() => setHistoryLimit(l => l + 200)}
              className="text-xs font-mono border border-border rounded px-2 py-1 hover:bg-accent">
              Load more ({historyLimit} shown)
            </button>
          )}
          <div className="flex items-center gap-1 ml-auto">
            <input value={addId} onChange={e => { setAddId(e.target.value); setAddErr(""); }}
              placeholder="Add sim ID (e.g. SIM-abc123) to compare"
              className="bg-background border border-border rounded px-2 py-1 text-xs font-mono w-64 focus:outline-none focus:border-primary" />
            <button onClick={() => addId && addById.mutate(addId.trim())}
              disabled={!addId || addById.isPending}
              className="text-xs font-mono border border-border rounded px-2 py-1 hover:bg-accent disabled:opacity-60">
              {addById.isPending ? "…" : "+ Add"}
            </button>
          </div>
        </div>
        {addErr && <ErrBox msg={addErr} />}
        {simRuns.length === 0 ? (
          <p className="text-xs font-mono text-muted-foreground">No simulation runs yet — run a scenario above.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-xs border-collapse">
              <thead>
                <tr className="border-b border-border text-muted-foreground font-mono uppercase">
                  <th className="px-2 py-2 text-left">Cmp</th>
                  <th className="px-2 py-2 text-left">Label</th>
                  <th className="px-2 py-2 text-left">Created</th>
                  <th className="px-2 py-2 text-left">Base Run</th>
                  {COMPARE_COLS.map(c => (
                    <th key={c.key} className="px-2 py-2 text-right whitespace-nowrap">{c.label}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {simRuns.map(r => {
                  const res = r.result || {};
                  return (
                    <tr key={r.sim_id} className="border-b border-border/50 hover:bg-accent/30 font-mono">
                      <td className="px-2 py-2">
                        <input type="checkbox" checked={selected.has(r.sim_id)}
                          onChange={() => toggle(r.sim_id)} />
                      </td>
                      <td className="px-2 py-2 max-w-[180px] truncate" title={JSON.stringify(r.params)}>{r.label}</td>
                      <td className="px-2 py-2 whitespace-nowrap text-muted-foreground">{String(r.created_at || "").slice(0, 16)}</td>
                      <td className="px-2 py-2 text-muted-foreground">{r.base_run_id}</td>
                      {COMPARE_COLS.map(c => (
                        <td key={c.key} className={cn("px-2 py-2 text-right whitespace-nowrap",
                          c.key === "pnl" ? pnlCls(res[c.key]) :
                          c.key === "verdict" && res[c.key] !== "OK" ? "text-yellow-400" : "")}>
                          {fmtCell(res[c.key])}
                        </td>
                      ))}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
        {/* comparison table — fed by the compare endpoint, so it includes
            runs added by ID that are older than the history page above */}
        {selectedIds.length > 0 && (
          <div className="flex flex-col gap-2 border-t border-border pt-3">
            <div className="flex items-center gap-2">
              <h3 className="text-xs font-mono font-semibold uppercase text-muted-foreground">
                Comparison ({selectedIds.length} selected)
              </h3>
              {compareQ.isFetching && <Loader2 className="h-3 w-3 animate-spin text-primary" />}
              {compareRows.length > 0 && (
                <button onClick={() => exportCompareCsv(compareRows)}
                  className="flex items-center gap-1 text-xs font-mono border border-border rounded px-2 py-1 hover:bg-accent">
                  <Download className="h-3 w-3" /> Export CSV
                </button>
              )}
            </div>
            {compareQ.isError && <ErrBox msg={String((compareQ.error as Error)?.message)} />}
            {compareRows.length > 0 && (
              <div className="overflow-x-auto">
                <table className="w-full text-xs font-mono border-collapse">
                  <thead>
                    <tr className="border-b border-border text-muted-foreground uppercase">
                      <th className="px-2 py-1.5 text-left">Label</th>
                      <th className="px-2 py-1.5 text-left">Sim ID</th>
                      {COMPARE_COLS.map(c => (
                        <th key={c.key} className="px-2 py-1.5 text-right whitespace-nowrap">{c.label}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {compareRows.map(r => (
                      <tr key={r.sim_id} className="border-b border-border/50">
                        <td className="px-2 py-1.5 max-w-[160px] truncate" title={JSON.stringify(r.params)}>{r.label}</td>
                        <td className="px-2 py-1.5 text-muted-foreground">{r.sim_id}</td>
                        {COMPARE_COLS.map(c => (
                          <td key={c.key} className={cn("px-2 py-1.5 text-right whitespace-nowrap",
                            c.key === "pnl" ? pnlCls(r[c.key]) :
                            c.key === "verdict" && r[c.key] !== "OK" ? "text-yellow-400" : "")}>
                            {fmtCell(r[c.key])}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        )}
      </Section>

      {/* ── stress tests ── */}
      <Section icon={Zap} title="Stress Tests"
        sub="Shock transforms over an in-memory copy of the canonical portfolio + fault injection on isolated simulated fills.">
        {!stressOn ? (
          <button onClick={() => setStressOn(true)}
            className="w-fit flex items-center gap-2 bg-primary text-primary-foreground text-sm font-mono px-5 py-1.5 rounded hover:bg-primary/90">
            <Play className="h-4 w-4" /> Run Stress Tests
          </button>
        ) : (
          <div className="grid lg:grid-cols-2 gap-4">
            {/* portfolio stress */}
            <div className="flex flex-col gap-2">
              <h3 className="text-xs font-mono font-semibold uppercase text-muted-foreground">Portfolio Stress</h3>
              {portStressQ.isLoading && <Loader2 className="h-5 w-5 animate-spin text-primary" />}
              {portStressQ.isError && <ErrBox msg={String((portStressQ.error as Error)?.message)} />}
              {portStressQ.data && (portStressQ.data.scenarios?.length ? (
                <div className="overflow-x-auto">
                  <table className="w-full text-xs font-mono border-collapse">
                    <thead>
                      <tr className="border-b border-border text-muted-foreground uppercase">
                        <th className="px-2 py-1.5 text-left">Scenario</th>
                        <th className="px-2 py-1.5 text-right">Loss ₹</th>
                        <th className="px-2 py-1.5 text-right">DD %</th>
                        <th className="px-2 py-1.5 text-right">Capital Left</th>
                        <th className="px-2 py-1.5 text-right">Margin %</th>
                        <th className="px-2 py-1.5 text-right">Recovery (d)</th>
                      </tr>
                    </thead>
                    <tbody>
                      {portStressQ.data.scenarios.map((s: Dict) => (
                        <tr key={s.scenario} className="border-b border-border/50">
                          <td className="px-2 py-1.5" title={s.label}>{s.scenario}</td>
                          <td className={cn("px-2 py-1.5 text-right", pnlCls(-s.portfolio_loss))}>{fmtCell(s.portfolio_loss)}</td>
                          <td className="px-2 py-1.5 text-right">{fmtCell(s.drawdown_pct)}</td>
                          <td className="px-2 py-1.5 text-right">{fmtCell(s.capital_remaining)}</td>
                          <td className="px-2 py-1.5 text-right">{fmtCell(s.margin_utilization_pct)}</td>
                          <td className="px-2 py-1.5 text-right" title={s.recovery_basis}>{fmtCell(s.recovery_time_days)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <p className="text-xs font-mono text-yellow-400">
                  {portStressQ.data.reason || "Insufficient evidence"}
                </p>
              ))}
            </div>

            {/* execution stress */}
            <div className="flex flex-col gap-2">
              <h3 className="text-xs font-mono font-semibold uppercase text-muted-foreground">Execution Stress</h3>
              {execStressQ.isLoading && <Loader2 className="h-5 w-5 animate-spin text-primary" />}
              {execStressQ.isError && <ErrBox msg={String((execStressQ.error as Error)?.message)} />}
              {execStressQ.data && (execStressQ.data.scenarios?.length ? (
                <>
                  <div className="overflow-x-auto">
                    <table className="w-full text-xs font-mono border-collapse">
                      <thead>
                        <tr className="border-b border-border text-muted-foreground uppercase">
                          <th className="px-2 py-1.5 text-left">Scenario</th>
                          <th className="px-2 py-1.5 text-right">In</th>
                          <th className="px-2 py-1.5 text-right">Filled</th>
                          <th className="px-2 py-1.5 text-right">Rej</th>
                          <th className="px-2 py-1.5 text-right">Partial</th>
                          <th className="px-2 py-1.5 text-right">Pending</th>
                          <th className="px-2 py-1.5 text-center">Conserved</th>
                          <th className="px-2 py-1.5 text-left">Recovery</th>
                        </tr>
                      </thead>
                      <tbody>
                        {execStressQ.data.scenarios.map((s: Dict) => (
                          <tr key={s.scenario} className="border-b border-border/50">
                            <td className="px-2 py-1.5" title={s.label}>{s.scenario}</td>
                            <td className="px-2 py-1.5 text-right">{s.orders_in}</td>
                            <td className="px-2 py-1.5 text-right">{s.filled}</td>
                            <td className="px-2 py-1.5 text-right">{s.rejected}</td>
                            <td className="px-2 py-1.5 text-right">{s.partial_fills}</td>
                            <td className="px-2 py-1.5 text-right">{s.pending}</td>
                            <td className={cn("px-2 py-1.5 text-center", s.conservation_ok ? "text-emerald-400" : "text-red-400")}>
                              {s.conservation_ok ? "✓" : "✗"}
                            </td>
                            <td className="px-2 py-1.5 text-muted-foreground">{s.recovery_action}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                  {execStressQ.data.consistency && (
                    <p className={cn("text-xs font-mono",
                      execStressQ.data.consistency.ledger_untouched ? "text-emerald-400" : "text-red-400")}>
                      Live ledger untouched: {String(execStressQ.data.consistency.ledger_untouched)} ·
                      replay store consistent: {execStressQ.data.consistency.replay_store_consistent === null
                        ? "unknown (store unavailable)"
                        : String(execStressQ.data.consistency.replay_store_consistent)} ·
                      conservation: {String(execStressQ.data.consistency.all_conserved)}
                    </p>
                  )}
                </>
              ) : (
                <p className="text-xs font-mono text-yellow-400">
                  {execStressQ.data.reason || "Insufficient evidence"}
                </p>
              ))}
            </div>
          </div>
        )}
      </Section>

      {/* ── risk-rule comparison ── */}
      <Section icon={GitCompare} title="Risk-Rule Comparison"
        sub="Compare two risk-rule versions over the same base run — trades, PnL, drawdown, risk reduction, missed opportunities, capital efficiency.">
        <div className="grid sm:grid-cols-3 gap-3">
          <div className="flex flex-col gap-1">
            <label className="text-xs font-mono text-muted-foreground uppercase">Base run</label>
            <select value={riskRunId} onChange={e => setRiskRunId(e.target.value)}
              className="bg-background border border-border rounded px-3 py-1.5 text-sm font-mono focus:outline-none focus:border-primary">
              <option value="">— select —</option>
              {baseRuns.map(r => <option key={r.run_id} value={r.run_id}>{r.run_id}</option>)}
            </select>
          </div>
          <div className="flex flex-col gap-1">
            <label className="text-xs font-mono text-muted-foreground uppercase">Rules A (JSON)</label>
            <textarea value={rulesA} onChange={e => setRulesA(e.target.value)} rows={3}
              className="bg-background border border-border rounded px-3 py-1.5 text-xs font-mono focus:outline-none focus:border-primary" />
          </div>
          <div className="flex flex-col gap-1">
            <label className="text-xs font-mono text-muted-foreground uppercase">Rules B (JSON)</label>
            <textarea value={rulesB} onChange={e => setRulesB(e.target.value)} rows={3}
              className="bg-background border border-border rounded px-3 py-1.5 text-xs font-mono focus:outline-none focus:border-primary" />
          </div>
        </div>
        <button onClick={() => riskCompare.mutate()}
          disabled={riskCompare.isPending || !riskRunId}
          className="w-fit flex items-center gap-2 bg-primary text-primary-foreground text-sm font-mono px-5 py-1.5 rounded hover:bg-primary/90 disabled:opacity-60">
          {riskCompare.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
          Compare Rules
        </button>
        {riskCompare.isError && <ErrBox msg={String((riskCompare.error as Error)?.message)} />}
        {(riskCompare.data as Dict)?.ok === false && <ErrBox msg={(riskCompare.data as Dict).error} />}
        {(riskCompare.data as Dict)?.ok && (
          <div className="grid sm:grid-cols-3 gap-3 text-xs font-mono">
            {(["rules_a", "rules_b"] as const).map(k => {
              const r = (riskCompare.data as Dict)[k] || {};
              return (
                <div key={k} className="rounded border border-border p-3 flex flex-col gap-1">
                  <span className="font-semibold uppercase text-muted-foreground">{k === "rules_a" ? "Version A" : "Version B"}</span>
                  <span>Trades: {fmtCell(r.trades)} · Win {fmtCell(r.win_rate)}%</span>
                  <span className={pnlCls(r.pnl)}>PnL: {fmtCell(r.pnl)}</span>
                  <span>Max DD: {fmtCell(r.max_drawdown_pct)}% · PF {fmtCell(r.profit_factor)}</span>
                  <span className="text-muted-foreground truncate" title={JSON.stringify(r.params)}>{JSON.stringify(r.params)}</span>
                </div>
              );
            })}
            {(() => {
              const d = (riskCompare.data as Dict).diff || {};
              return (
                <div className="rounded border border-primary/40 bg-primary/5 p-3 flex flex-col gap-1">
                  <span className="font-semibold uppercase text-primary">B vs A</span>
                  <span>Δ Trades: {fmtCell(d.trades)}</span>
                  <span className={pnlCls(d.pnl)}>Δ PnL: {fmtCell(d.pnl)}</span>
                  <span>Risk reduction: {fmtCell(d.risk_reduction_pct)}% DD</span>
                  <span>Missed opportunities: {fmtCell(d.missed_opportunities)} ({fmtCell(d.missed_opportunity_pnl)} ₹)</span>
                  <span>Capital efficiency A/B: {fmtCell(d.capital_efficiency_a)} / {fmtCell(d.capital_efficiency_b)}</span>
                  {(riskCompare.data as Dict).verdict !== "OK" && (
                    <span className="text-yellow-400">{(riskCompare.data as Dict).verdict}</span>
                  )}
                </div>
              );
            })()}
          </div>
        )}
      </Section>

      <p className="text-xs font-mono text-muted-foreground">
        All results are derived simulations over immutable stored runs — advisory only, nothing is applied automatically.
      </p>
    </div>
  );
}
