/**
 * Phase21Panels.tsx — shared Phase 21 widgets embedded into existing pages.
 * PAPER / RESEARCH ONLY — everything shown here is advisory.
 */
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiJson } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";

const mono = "text-[11px] font-mono";
const label = "text-[10px] uppercase tracking-wider text-zinc-500";

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="rounded-lg border border-zinc-800 bg-zinc-900/40 p-4 space-y-3">
      <div className="flex items-center gap-2">
        <h3 className="text-xs font-semibold text-zinc-200">{title}</h3>
        <Badge variant="outline" className="text-[9px] text-amber-400 border-amber-700">
          ADVISORY · PAPER ONLY
        </Badge>
      </div>
      {children}
    </div>
  );
}

const fmt = (v: unknown, suffix = "") =>
  v === null || v === undefined ? "—" : `${v}${suffix}`;

/* ── Why this trade? (AI Decision, Trade Decisions) ─────────────────────── */

export function WhyThisTrade({ symbol }: { symbol: string }) {
  const { data } = useQuery({
    queryKey: ["/api/phase21/explain", symbol],
    queryFn: () => apiJson<any>(`/phase21/explain/${symbol}`),
    enabled: !!symbol,
    staleTime: 60_000,
  });
  if (!data) return null;
  if (!data.available) return null;
  const conf = data.confidence_reliability || {};
  const reg = data.regime_compatibility || {};
  return (
    <Section title={`Why this trade? — ${data.symbol}`}>
      <div className="grid gap-3 md:grid-cols-2">
        <div>
          <p className={label}>Supporting evidence</p>
          {(data.reasons || []).length === 0 && (
            <p className={`${mono} text-zinc-500`}>No supporting factors in canonical scan.</p>
          )}
          <ul className="space-y-1 mt-1">
            {(data.reasons || []).map((r: any, i: number) => (
              <li key={i} className={`${mono} text-emerald-400`}>+ {r.text}</li>
            ))}
          </ul>
        </div>
        <div>
          <p className={label}>Risks / blockers</p>
          {(data.risks || []).length === 0 && (
            <p className={`${mono} text-zinc-500`}>No flagged risks.</p>
          )}
          <ul className="space-y-1 mt-1">
            {(data.risks || []).map((r: any, i: number) => (
              <li key={i} className={`${mono} text-rose-400`}>− {r.text}</li>
            ))}
          </ul>
        </div>
      </div>
      <div className={`grid gap-x-6 gap-y-1 md:grid-cols-2 ${mono} text-zinc-400`}>
        <span>Regime: {fmt(reg.regime)} · strategy {fmt(reg.strategy)} · {fmt(reg.classification)}</span>
        <span>
          Confidence: raw {fmt(conf.raw_confidence)} · calibrated (advisory) {fmt(conf.calibrated_advisory)}
          {" "}· bucket {fmt(conf.bucket)} ({fmt(conf.bucket_status)})
        </span>
        {data.stop_target_rationale && (
          <span className="md:col-span-2">Stop/target: {data.stop_target_rationale}</span>
        )}
        {(data.failed_gates || []).length > 0 && (
          <span className="md:col-span-2 text-rose-400">
            Failed gates: {data.failed_gates.join(", ")}
          </span>
        )}
      </div>
      <p className="text-[9px] text-zinc-600">
        Rule-based, evidence-backed explanation from canonical scan {data.scan_id}. No LLM-generated content.
      </p>
    </Section>
  );
}

/* ── Ranking breakdown (AI Decision) ────────────────────────────────────── */

export function RankingBreakdown({ symbol }: { symbol?: string }) {
  const { data } = useQuery({
    queryKey: ["/api/phase21/ranking"],
    queryFn: () => apiJson<any>("/phase21/ranking"),
    staleTime: 60_000,
  });
  if (!data?.available) return null;
  const items: any[] = data.items || [];
  const shown = symbol
    ? items.filter((i) => i.symbol === symbol.toUpperCase())
    : items.slice(0, 10);
  if (shown.length === 0) return null;
  return (
    <Section title={symbol ? `Ranking breakdown — ${symbol}` : "Opportunity ranking (top 10)"}>
      <div className="overflow-x-auto">
        <table className={`w-full ${mono}`}>
          <thead>
            <tr className="text-zinc-500 border-b border-zinc-800">
              <th className="text-left py-1 pr-3">#</th>
              <th className="text-left py-1 pr-3">Symbol</th>
              <th className="text-right py-1 pr-3">Score</th>
              <th className="text-right py-1 pr-3">Raw</th>
              <th className="text-left py-1 pr-3">Penalties</th>
              <th className="text-right py-1 pr-3">Raw conf</th>
              <th className="text-right py-1 pr-3">Calibrated*</th>
              <th className="text-left py-1">Regime fit</th>
            </tr>
          </thead>
          <tbody>
            {shown.map((i) => (
              <tr key={i.symbol} className="border-b border-zinc-800/50 text-zinc-300">
                <td className="py-1 pr-3">{i.rank}</td>
                <td className="py-1 pr-3">{i.symbol}</td>
                <td className="py-1 pr-3 text-right text-cyan-400">{i.rank_score}</td>
                <td className="py-1 pr-3 text-right">{i.raw_score}</td>
                <td className="py-1 pr-3 text-rose-400">
                  {Object.keys(i.penalties || {}).length
                    ? Object.keys(i.penalties).join(", ")
                    : "—"}
                </td>
                <td className="py-1 pr-3 text-right">{fmt(i.raw_confidence)}</td>
                <td className="py-1 pr-3 text-right">{fmt(i.calibrated_confidence_advisory)}</td>
                <td className="py-1">{fmt(i.regime_classification)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="text-[9px] text-zinc-600">
        Deterministic for scan {data.scan_id} ({data.ranking_config_version}). *Calibrated confidence
        is advisory only — raw confidence and BUY safety gates are unchanged.
      </p>
    </Section>
  );
}

/* ── Calibration curve + buckets (Performance Analytics) ────────────────── */

export function CalibrationPanel() {
  const { data } = useQuery({
    queryKey: ["/api/phase21/calibration"],
    queryFn: () => apiJson<any>("/phase21/calibration"),
    staleTime: 120_000,
  });
  if (!data) return null;
  const buckets: any[] = data.buckets || [];
  return (
    <Section title="Confidence calibration (Phase 21)">
      <div className="flex items-end gap-2 h-28">
        {buckets.map((b) => {
          const pred = b.predicted_confidence ?? 0;
          const obs = b.win_rate !== null && b.win_rate !== undefined ? b.win_rate * 100 : null;
          return (
            <div key={b.bucket} className="flex-1 flex flex-col items-center gap-1">
              <div className="w-full flex items-end justify-center gap-0.5 h-20">
                <div className="w-2 bg-zinc-600" style={{ height: `${pred * 0.8}%` }} title={`Predicted ${pred}`} />
                <div
                  className={`w-2 ${b.status === "OK" ? "bg-cyan-500" : "bg-zinc-800"}`}
                  style={{ height: `${(obs ?? 0) * 0.8}%` }}
                  title={obs === null ? "No data" : `Observed ${obs.toFixed(0)}%`}
                />
              </div>
              <span className="text-[9px] text-zinc-500">{b.bucket}</span>
              {b.status === "INSUFFICIENT" && (
                <span className="text-[8px] text-amber-500">INSUF.</span>
              )}
            </div>
          );
        })}
      </div>
      <div className="overflow-x-auto">
        <table className={`w-full ${mono}`}>
          <thead>
            <tr className="text-zinc-500 border-b border-zinc-800">
              <th className="text-left py-1 pr-3">Bucket</th>
              <th className="text-right py-1 pr-3">Trades</th>
              <th className="text-right py-1 pr-3">Win rate</th>
              <th className="text-right py-1 pr-3">Expectancy</th>
              <th className="text-right py-1 pr-3">Cal. error</th>
              <th className="text-right py-1 pr-3">Calibrated*</th>
              <th className="text-left py-1">Status</th>
            </tr>
          </thead>
          <tbody>
            {buckets.map((b) => (
              <tr key={b.bucket} className="border-b border-zinc-800/50 text-zinc-300">
                <td className="py-1 pr-3">{b.bucket}</td>
                <td className="py-1 pr-3 text-right">{b.trades}</td>
                <td className="py-1 pr-3 text-right">{b.win_rate === null ? "—" : `${(b.win_rate * 100).toFixed(0)}%`}</td>
                <td className="py-1 pr-3 text-right">{fmt(b.expectancy)}</td>
                <td className="py-1 pr-3 text-right">{fmt(b.calibration_error)}</td>
                <td className="py-1 pr-3 text-right">{fmt(b.calibrated_confidence_advisory)}</td>
                <td className="py-1">
                  <span className={b.status === "OK" ? "text-emerald-400" : "text-amber-500"}>{b.status}</span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="text-[9px] text-zinc-600">
        Grey = predicted, cyan = observed. Overall calibration error {fmt(data.overall_calibration_error)} over{" "}
        {data.total_trades} completed trades (shrinkage prior {data.shrinkage_prior_weight}). *Advisory — raw
        confidence is never modified; only trades closed before the evaluation date are used.
      </p>
    </Section>
  );
}

/* ── Strategy × regime matrix (Performance Analytics) ───────────────────── */

export function RegimeMatrixPanel() {
  const { data } = useQuery({
    queryKey: ["/api/phase21/regime-matrix"],
    queryFn: () => apiJson<any>("/phase21/regime-matrix"),
    staleTime: 120_000,
  });
  if (!data) return null;
  const pairs: any[] = data.pairs || [];
  if (pairs.length === 0) return null;
  const color = (c: string) =>
    c === "ELIGIBLE" ? "text-emerald-400"
      : c === "CONDITIONAL" ? "text-cyan-400"
      : c === "WATCHLIST" ? "text-amber-400"
      : c === "DISABLED" ? "text-rose-400"
      : "text-zinc-500";
  return (
    <Section title="Strategy × regime performance (Phase 21)">
      <div className="overflow-x-auto">
        <table className={`w-full ${mono}`}>
          <thead>
            <tr className="text-zinc-500 border-b border-zinc-800">
              <th className="text-left py-1 pr-3">Strategy</th>
              <th className="text-left py-1 pr-3">Regime</th>
              <th className="text-right py-1 pr-3">Trades</th>
              <th className="text-right py-1 pr-3">Win rate</th>
              <th className="text-right py-1 pr-3">PF</th>
              <th className="text-right py-1 pr-3">Expectancy</th>
              <th className="text-left py-1 pr-3">Reliability</th>
              <th className="text-left py-1">Recommendation</th>
            </tr>
          </thead>
          <tbody>
            {pairs.map((p, i) => (
              <tr key={i} className="border-b border-zinc-800/50 text-zinc-300">
                <td className="py-1 pr-3">{p.strategy}</td>
                <td className="py-1 pr-3">{p.regime}</td>
                <td className="py-1 pr-3 text-right">{p.sample_size}</td>
                <td className="py-1 pr-3 text-right">{p.win_rate === null || p.win_rate === undefined ? "—" : `${(p.win_rate * 100).toFixed(0)}%`}</td>
                <td className="py-1 pr-3 text-right">{fmt(p.profit_factor)}</td>
                <td className="py-1 pr-3 text-right">{fmt(p.expectancy)}</td>
                <td className="py-1 pr-3">{p.reliability_status}</td>
                <td className={`py-1 ${color(p.classification)}`}>{p.classification}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="text-[9px] text-zinc-600">
        Recommendations only — no strategy is enabled or disabled automatically.
      </p>
    </Section>
  );
}

/* ── Baseline vs challenger comparison (Performance Analytics, Trade Decisions) ── */

export function ChallengerComparisonPanel() {
  const { data } = useQuery({
    queryKey: ["/api/phase21/registry"],
    queryFn: () => apiJson<any>("/phase21/registry"),
    staleTime: 60_000,
  });
  if (!data) return null;
  const chals: any[] = data.challengers || [];
  return (
    <Section title="Champion vs challengers (Phase 21)">
      <p className={`${mono} text-zinc-400`}>
        Champion: <span className="text-cyan-400">{data.champion?.model_version}</span> (unchanged) ·
        baseline {data.champion?.baseline_version}
      </p>
      <div className="overflow-x-auto">
        <table className={`w-full ${mono}`}>
          <thead>
            <tr className="text-zinc-500 border-b border-zinc-800">
              <th className="text-left py-1 pr-3">Challenger</th>
              <th className="text-left py-1 pr-3">Status</th>
              <th className="text-right py-1 pr-3">Overlap</th>
              <th className="text-right py-1 pr-3">Added</th>
              <th className="text-right py-1 pr-3">Removed</th>
              <th className="text-right py-1 pr-3">Δ PnL</th>
              <th className="text-left py-1">Review</th>
            </tr>
          </thead>
          <tbody>
            {chals.map((c) => {
              const cmp = c.comparison || {};
              return (
                <tr key={c.challenger_id} className="border-b border-zinc-800/50 text-zinc-300">
                  <td className="py-1 pr-3">{c.name}</td>
                  <td className="py-1 pr-3">{cmp.evaluable ? "EVALUATED" : "INSUFFICIENT DATA"}</td>
                  <td className="py-1 pr-3 text-right">{fmt(cmp.trade_overlap)}</td>
                  <td className="py-1 pr-3 text-right">{fmt(cmp.added_trades)}</td>
                  <td className="py-1 pr-3 text-right">{fmt(cmp.removed_trades)}</td>
                  <td className="py-1 pr-3 text-right">{fmt(cmp.performance_difference)}</td>
                  <td className="py-1">{c.approval_status}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <p className="text-[9px] text-zinc-600">
        Challengers never affect live recommendations. Evaluation uses the unseen, time-ordered
        test window only. No automatic promotion.
      </p>
    </Section>
  );
}

/* ── Challenger registry with approval workflow (Learning & Governance) ── */

export function Phase21GovernancePanel() {
  const qc = useQueryClient();
  const { data } = useQuery({
    queryKey: ["/api/phase21/registry"],
    queryFn: () => apiJson<any>("/phase21/registry"),
    staleTime: 30_000,
  });
  const { data: thresholds } = useQuery({
    queryKey: ["/api/phase21/thresholds"],
    queryFn: () => apiJson<any>("/phase21/thresholds"),
    staleTime: 120_000,
  });
  const review = useMutation({
    mutationFn: ({ id, action }: { id: string; action: "APPROVE" | "REJECT" }) =>
      apiJson(`/phase21/review/${id}`, {
        method: "POST",
        body: JSON.stringify({ action, approver: "dashboard-user" }),
        headers: { "Content-Type": "application/json" },
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["/api/phase21/registry"] }),
  });
  const rebuild = useMutation({
    mutationFn: () => apiJson("/phase21/challengers/build", { method: "POST" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["/api/phase21/registry"] }),
  });
  if (!data) return null;
  const chals: any[] = data.challengers || [];
  return (
    <Section title="Phase 21 challenger registry & approvals">
      <div className="flex items-center justify-between">
        <p className={`${mono} text-zinc-400`}>
          Champion {data.champion?.model_version} · {chals.length} challengers · auto-promotion:{" "}
          <span className="text-emerald-400">DISABLED</span>
        </p>
        <Button size="sm" variant="outline" className="h-6 text-[10px]"
          disabled={rebuild.isPending}
          onClick={() => rebuild.mutate()}>
          {rebuild.isPending ? "Rebuilding…" : "Re-evaluate challengers"}
        </Button>
      </div>
      <div className="space-y-2">
        {chals.map((c) => {
          const cmp = c.comparison || {};
          return (
            <div key={c.challenger_id}
              className="rounded border border-zinc-800 p-2 flex flex-wrap items-center gap-2 justify-between">
              <div className={`${mono} text-zinc-300`}>
                <span className="text-zinc-100">{c.name}</span>{" "}
                <span className="text-zinc-500">— {c.description}</span>
                <div className="text-zinc-500">
                  {cmp.evaluable
                    ? `test trades ${cmp.test_trades} · changed ${cmp.changed_decisions} · Δ PnL ${cmp.performance_difference}`
                    : `not evaluable: ${cmp.reason || "insufficient data"}`}
                </div>
              </div>
              <div className="flex items-center gap-2">
                <Badge variant="outline" className={`text-[9px] ${
                  c.approval_status === "APPROVED" ? "text-emerald-400 border-emerald-700"
                    : c.approval_status === "REJECTED" ? "text-rose-400 border-rose-700"
                    : "text-amber-400 border-amber-700"}`}>
                  {c.approval_status}
                </Badge>
                {c.approval_status === "PENDING_REVIEW" && (
                  <>
                    <Button size="sm" className="h-6 text-[10px]" disabled={review.isPending}
                      onClick={() => review.mutate({ id: c.challenger_id, action: "APPROVE" })}>
                      Approve
                    </Button>
                    <Button size="sm" variant="destructive" className="h-6 text-[10px]" disabled={review.isPending}
                      onClick={() => review.mutate({ id: c.challenger_id, action: "REJECT" })}>
                      Reject
                    </Button>
                  </>
                )}
              </div>
            </div>
          );
        })}
      </div>
      {thresholds && (
        <div className={`${mono} text-zinc-400`}>
          Proposed threshold change:{" "}
          {thresholds.recommended
            ? <span className="text-amber-400">BUY ≥ {thresholds.recommended.buy} (pending human approval)</span>
            : <span className="text-zinc-500">{thresholds.status === "INSUFFICIENT_EVIDENCE"
                ? "insufficient evidence for any recommendation"
                : "no change recommended"}</span>}
        </div>
      )}
      <p className="text-[9px] text-zinc-600">
        Approval marks a challenger as reviewed. The champion model is never changed automatically;
        applying any change is a separate explicit step. All actions are audit-logged.
      </p>
    </Section>
  );
}

/* ── Stop/target quality (Trade Replay) ─────────────────────────────────── */

export function StopTargetPanel() {
  const { data } = useQuery({
    queryKey: ["/api/phase21/stop-target"],
    queryFn: () => apiJson<any>("/phase21/stop-target"),
    staleTime: 120_000,
  });
  if (!data) return null;
  const trades: any[] = data.per_trade || [];
  const summary = data.summary || {};
  const flagsOf = (t: any) => {
    const f: string[] = [];
    if (t.stop_too_tight === true) f.push("stop too tight");
    if (t.stop_too_loose === true) f.push("stop too loose");
    if (t.target_realistic === false) f.push("unrealistic target");
    if (t.target_reached_after_early_exit === true) f.push("premature exit");
    return f;
  };
  const hasExcursion = (t: any) => t.mae !== null && t.mae !== undefined;
  return (
    <Section title="Stop & target quality (Phase 21)">
      <div className={`grid grid-cols-2 md:grid-cols-4 gap-2 ${mono} text-zinc-300`}>
        <span>Analyzed: {fmt(data.total_trades)}</span>
        <span>Stops too tight: {fmt(summary.stop_too_tight_count)}</span>
        <span>Stops too loose: {fmt(summary.stop_too_loose_count)}</span>
        <span>Unrealistic targets: {fmt(summary.unrealistic_target_count)}</span>
      </div>
      {trades.length > 0 && (
        <div className="overflow-x-auto">
          <table className={`w-full ${mono}`}>
            <thead>
              <tr className="text-zinc-500 border-b border-zinc-800">
                <th className="text-left py-1 pr-3">Symbol</th>
                <th className="text-left py-1 pr-3">Exit</th>
                <th className="text-right py-1 pr-3">PnL %</th>
                <th className="text-left py-1">Quality flags</th>
              </tr>
            </thead>
            <tbody>
              {trades.slice(0, 15).map((t, i) => {
                const f = flagsOf(t);
                return (
                  <tr key={i} className="border-b border-zinc-800/50 text-zinc-300">
                    <td className="py-1 pr-3">{t.symbol}</td>
                    <td className="py-1 pr-3">{fmt(t.exit_reason)}</td>
                    <td className={`py-1 pr-3 text-right ${(t.return_pct ?? 0) >= 0 ? "text-emerald-400" : "text-rose-400"}`}>
                      {fmt(t.return_pct, "%")}
                    </td>
                    <td className="py-1">
                      {f.length ? (
                        <span className="text-amber-400">{f.join(", ")}</span>
                      ) : hasExcursion(t) ? (
                        <span className="text-zinc-500">clean</span>
                      ) : (
                        <span className="text-zinc-600">no MAE/MFE data — not scoreable</span>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
      <p className="text-[9px] text-zinc-600">
        {data.trades_with_full_excursion_data === 0
          ? "Alternative stop/target models are registered but not scored — MAE/MFE excursion history is not yet captured, so counterfactuals would be guesses."
          : "Counterfactual comparisons use recorded MAE/MFE excursions only."}{" "}
        Validation: {data.validation}. Historical trades rewritten: {String(data.historical_trades_rewritten)}.
        Advisory analysis of completed paper trades — stops and targets are not changed automatically.
      </p>
    </Section>
  );
}

/* ── Phase 21 validation rows (Live Data Health / Validation) ───────────── */

export function Phase21ValidationPanel() {
  const { data } = useQuery({
    queryKey: ["/api/phase21/scorecard"],
    queryFn: () => apiJson<any>("/phase21/scorecard"),
    staleTime: 120_000,
  });
  if (!data) return null;
  const rows: [string, string, boolean][] = [
    ["Reproducibility", String(data.reproducibility_result || "—"), String(data.reproducibility_result || "").startsWith("PASS")],
    ["No-look-ahead", String(data.no_look_ahead_result || "—"), String(data.no_look_ahead_result || "").startsWith("PASS")],
    ["Ranking stability", String(data.ranking_stability || "—"), data.ranking_stability === "DETERMINISTIC"],
    ["Model/config versions", `baseline ${data.baseline_model_version || "—"} · champion ${data.champion_version || "—"}`, !!data.baseline_model_version],
    ["Auto paper entries", String(data.auto_paper_entries), data.auto_paper_entries === "OFF"],
    ["Live orders", String(data.live_orders), data.live_orders === "DISABLED"],
  ];
  return (
    <Section title="Phase 21 validation">
      <div className="space-y-1">
        {rows.map(([k, v, ok]) => (
          <div key={k} className={`flex justify-between ${mono}`}>
            <span className="text-zinc-500">{k}</span>
            <span className={ok ? "text-emerald-400" : "text-amber-400"}>{v}</span>
          </div>
        ))}
        <div className={`flex justify-between ${mono}`}>
          <span className="text-zinc-500">Readiness</span>
          <span className="text-cyan-400">{data.readiness_status}</span>
        </div>
      </div>
      <p className="text-[9px] text-zinc-600">
        APPROVED_FOR_PAPER_TEST never means live-trading approval.
      </p>
    </Section>
  );
}
