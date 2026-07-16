import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiJson, API_BASE } from "@/lib/api";
import { Card, CardContent } from "@/components/ui/card";
import DataFreshnessBar from "@/components/DataFreshnessBar";
import { Phase21GovernancePanel } from "@/components/Phase21Panels";
import { EvidenceProgressPanel } from "@/components/Phase22Panels";
import {
  GraduationCap, Activity, Scale, SlidersHorizontal, Trophy, Radar,
  ScrollText, Download, RefreshCcw, ShieldCheck, AlertTriangle,
} from "lucide-react";

// ── helpers ────────────────────────────────────────────────────────────────────

const REL_COLOR: Record<string, string> = {
  HIGH: "text-emerald-400 border-emerald-500/30 bg-emerald-500/10",
  STRONG: "text-green-400 border-green-500/30 bg-green-500/10",
  MODERATE: "text-yellow-400 border-yellow-500/30 bg-yellow-500/10",
  LOW: "text-orange-400 border-orange-500/30 bg-orange-500/10",
  INSUFFICIENT: "text-red-400 border-red-500/30 bg-red-500/10",
};

function RelBadge({ rel }: { rel?: string }) {
  const r = rel ?? "INSUFFICIENT";
  return (
    <span className={`rounded border px-1.5 py-0.5 text-[9px] font-mono ${REL_COLOR[r] ?? REL_COLOR.INSUFFICIENT}`}>
      {r}
    </span>
  );
}

const fmt = (v: unknown, d = 2) =>
  v === null || v === undefined ? "—" : typeof v === "number" ? v.toFixed(d) : String(v);

function StatCard({ label, value, sub, color }: { label: string; value: React.ReactNode; sub?: string; color?: string }) {
  return (
    <Card className="bg-card/50 border-border/50">
      <CardContent className="p-4">
        <div className="text-[10px] font-mono uppercase tracking-wider text-muted-foreground">{label}</div>
        <div className={`text-xl font-bold font-mono mt-1 ${color ?? ""}`}>{value}</div>
        {sub && <div className="text-[10px] text-muted-foreground font-mono mt-0.5">{sub}</div>}
      </CardContent>
    </Card>
  );
}

function MetricsTable({ table, keyLabel }: { table?: Record<string, any>; keyLabel: string }) {
  const entries = Object.entries(table ?? {});
  if (!entries.length) return <p className="text-xs text-muted-foreground font-mono py-4">No data yet.</p>;
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-[11px] font-mono">
        <thead>
          <tr className="text-muted-foreground border-b border-border/40 text-left">
            <th className="py-1.5 pr-3">{keyLabel}</th>
            <th className="py-1.5 pr-3 text-right">N</th>
            <th className="py-1.5 pr-3">Reliability</th>
            <th className="py-1.5 pr-3 text-right">Win %</th>
            <th className="py-1.5 pr-3 text-right">Expectancy</th>
            <th className="py-1.5 pr-3 text-right">PF</th>
            <th className="py-1.5 pr-3 text-right">Sharpe</th>
            <th className="py-1.5 pr-3 text-right">Max DD</th>
          </tr>
        </thead>
        <tbody>
          {entries.map(([k, m]) => (
            <tr key={k} className="border-b border-border/20">
              <td className="py-1.5 pr-3 font-bold">{k}</td>
              <td className="py-1.5 pr-3 text-right">{m.sample_size}</td>
              <td className="py-1.5 pr-3"><RelBadge rel={m.reliability} /></td>
              <td className="py-1.5 pr-3 text-right">{m.win_rate != null ? (m.win_rate * 100).toFixed(0) + "%" : "—"}</td>
              <td className={`py-1.5 pr-3 text-right ${(m.expectancy ?? 0) >= 0 ? "text-emerald-400" : "text-red-400"}`}>₹{fmt(m.expectancy)}</td>
              <td className="py-1.5 pr-3 text-right">{fmt(m.profit_factor)}</td>
              <td className="py-1.5 pr-3 text-right">{fmt(m.sharpe, 3)}</td>
              <td className="py-1.5 pr-3 text-right text-red-400/80">₹{fmt(m.max_drawdown)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="text-[10px] text-muted-foreground font-mono mt-2">
        Groups below MODERATE reliability must not be treated as conclusions.
      </p>
    </div>
  );
}

// ── tabs ───────────────────────────────────────────────────────────────────────

function OverviewTab() {
  const { data: ver } = useQuery({ queryKey: ["/api/phase14/verification"], queryFn: () => apiJson<any>("/phase14/verification"), staleTime: 60_000 });
  const v = ver?.verification;
  if (!v) return <p className="text-xs text-muted-foreground font-mono py-6">Loading verification…</p>;
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <StatCard label="Learning Rows" value={v.completed_learning_rows} sub={`reliability: ${v.evaluation_reliability}`} />
        <StatCard label="No-Look-Ahead" value={v.no_look_ahead_audit_status} sub={`${v.rows_passing_no_look_ahead} rows pass`} color={v.no_look_ahead_audit_status === "PASS" ? "text-emerald-400" : "text-red-400"} />
        <StatCard label="Champion" value={v.current_champion} sub="model registry" />
        <StatCard label="Calibrator" value={v.active_calibrator} sub={v.calibrator_method} />
        <StatCard label="Drift" value={v.drift_status} color={v.drift_status === "CRITICAL" ? "text-red-400" : v.drift_status === "WARNING" ? "text-yellow-400" : "text-emerald-400"} />
        <StatCard label="Learning Frozen" value={v.learning_frozen?.frozen ? "YES" : "NO"} color={v.learning_frozen?.frozen ? "text-red-400" : "text-emerald-400"} />
        <StatCard label="Active Adjustments" value={v.adjustment_sources_active} sub={`max observed ${v.max_adjustment_observed}`} />
        <StatCard label="Challengers" value={v.challenger_count} sub={`auto-promotion: ${v.automatic_promotion_occurred ? "OCCURRED (bug!)" : "never"}`} />
      </div>
      <LearningQA />
      {v.sample_warning && (
        <div className="flex items-center gap-2 rounded border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-xs font-mono text-amber-400">
          <AlertTriangle className="h-3.5 w-3.5" /> {v.sample_warning}
        </div>
      )}
      <p className="text-[11px] text-muted-foreground font-mono">{v.message}</p>
    </div>
  );
}

const QA_PRESETS = [
  "Why did confidence change?",
  "What has the model learned so far?",
  "Which strategy is strongest?",
  "Which strategy is deteriorating?",
  "Is calibration reliable?",
  "What is required for promotion?",
  "What is the drift status?",
];

function LearningQA() {
  const [question, setQuestion] = useState("");
  const [asked, setAsked] = useState<string | null>(null);
  const { data, isFetching } = useQuery({
    queryKey: ["/api/phase14/qa", asked],
    queryFn: () => apiJson<any>(`/phase14/qa?question=${encodeURIComponent(asked!)}`),
    enabled: !!asked,
  });
  return (
    <Card className="bg-card/40 border-border/40">
      <CardContent className="p-4 space-y-3">
        <div className="text-xs font-mono uppercase text-muted-foreground">Ask the learning copilot</div>
        <div className="flex flex-wrap gap-1.5">
          {QA_PRESETS.map((q) => (
            <button key={q} onClick={() => { setQuestion(q); setAsked(q); }}
              className="text-[10px] font-mono rounded border border-border/50 px-2 py-1 hover:bg-muted/40">
              {q}
            </button>
          ))}
        </div>
        <form className="flex gap-2" onSubmit={(e) => { e.preventDefault(); if (question.trim()) setAsked(question.trim()); }}>
          <input value={question} onChange={(e) => setQuestion(e.target.value)}
            placeholder="e.g. What evidence supports the current adjustments?"
            className="flex-1 rounded border border-border/50 bg-background px-3 py-1.5 text-xs font-mono" />
          <button type="submit" className="text-xs font-mono px-3 py-1.5 rounded border border-purple-500/40 text-purple-400 hover:bg-purple-500/10">
            Ask
          </button>
        </form>
        {isFetching && <p className="text-[11px] font-mono text-muted-foreground">Thinking…</p>}
        {data?.answer && !isFetching && (
          <div className="rounded border border-border/40 bg-background/60 p-3 space-y-1.5">
            <p className="text-xs font-mono leading-relaxed">{data.answer}</p>
            <p className="text-[10px] font-mono text-muted-foreground">
              n={data.sample_size} · <RelBadge rel={data.reliability} /> · {data.disclaimer}
            </p>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function PerformanceTab() {
  const { data } = useQuery({ queryKey: ["/api/phase14/evaluation"], queryFn: () => apiJson<any>("/phase14/evaluation"), staleTime: 60_000 });
  const r = data?.report;
  if (!r) return <p className="text-xs text-muted-foreground font-mono py-6">Loading evaluation…</p>;
  const o = r.overall ?? {};
  return (
    <div className="space-y-5">
      <div className="grid grid-cols-2 md:grid-cols-6 gap-3">
        <StatCard label="Trades" value={r.completed_trades} sub={r.reliability} />
        <StatCard label="Win Rate" value={o.win_rate != null ? (o.win_rate * 100).toFixed(0) + "%" : "—"} />
        <StatCard label="Expectancy" value={`₹${fmt(o.expectancy)}`} color={(o.expectancy ?? 0) >= 0 ? "text-emerald-400" : "text-red-400"} />
        <StatCard label="Profit Factor" value={fmt(o.profit_factor)} />
        <StatCard label="Brier" value={fmt(o.brier, 3)} sub={`ECE ${fmt(o.ece, 3)}`} />
        <StatCard label="BUY Precision" value={fmt(r.signal_quality?.buy_precision, 2)} sub={`FP rate ${fmt(r.signal_quality?.false_positive_rate, 2)}`} />
      </div>
      {[["Strategy", r.by_strategy], ["Regime", r.by_regime], ["Sector", r.by_sector],
        ["Confidence Band", r.by_confidence_band], ["Opportunity Band", r.by_opportunity_band],
        ["Holding Period", r.by_holding_band], ["Quality Grade", r.by_quality_grade]].map(([label, table]: any) => (
        <Card key={label} className="bg-card/40 border-border/40">
          <CardContent className="p-4">
            <div className="text-xs font-mono uppercase tracking-wider text-muted-foreground mb-2">By {label}</div>
            <MetricsTable table={table} keyLabel={label} />
          </CardContent>
        </Card>
      ))}
    </div>
  );
}

function CalibrationTab() {
  const qc = useQueryClient();
  const { data } = useQuery({ queryKey: ["/api/phase14/calibration"], queryFn: () => apiJson<any>("/phase14/calibration"), staleTime: 60_000 });
  const train = useMutation({
    mutationFn: () => apiJson("/phase14/calibration/train", { method: "POST" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["/api/phase14/calibration"] }),
  });
  if (!data) return <p className="text-xs text-muted-foreground font-mono py-6">Loading calibration…</p>;
  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3">
        <StatCard label="Active Calibrator" value={data.active_version ?? "identity"} sub={data.active_method} />
        <StatCard label="Versions" value={data.calibrator_count} sub={`${data.completed_trades} completed trades`} />
        <button onClick={() => train.mutate()} disabled={train.isPending}
          className="ml-auto flex items-center gap-2 text-xs font-mono px-3 py-2 rounded border border-border hover:bg-muted/40 disabled:opacity-50">
          <RefreshCcw className={`h-3 w-3 ${train.isPending ? "animate-spin" : ""}`} />
          Train New Calibrator
        </button>
      </div>
      {data.warning && (
        <div className="rounded border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-xs font-mono text-amber-400">{data.warning}</div>
      )}
      <Card className="bg-card/40 border-border/40">
        <CardContent className="p-4 overflow-x-auto">
          <div className="text-xs font-mono uppercase text-muted-foreground mb-2">Calibrator history (raw → calibrated, OOS)</div>
          <table className="w-full text-[11px] font-mono">
            <thead>
              <tr className="text-muted-foreground border-b border-border/40 text-left">
                <th className="py-1.5 pr-3">Version</th><th className="py-1.5 pr-3">Method</th>
                <th className="py-1.5 pr-3">Status</th><th className="py-1.5 pr-3 text-right">Train N</th>
                <th className="py-1.5 pr-3 text-right">Test N</th>
                <th className="py-1.5 pr-3 text-right">Brier before→after</th>
                <th className="py-1.5 pr-3 text-right">ECE before→after</th>
                <th className="py-1.5 pr-3 text-right">LogLoss before→after</th>
              </tr>
            </thead>
            <tbody>
              {(data.history ?? []).map((c: any) => (
                <tr key={c.version} className="border-b border-border/20">
                  <td className="py-1.5 pr-3 font-bold">{c.version}</td>
                  <td className="py-1.5 pr-3">{c.method}</td>
                  <td className={`py-1.5 pr-3 ${c.status === "ACTIVE" ? "text-emerald-400" : c.status === "REJECTED" ? "text-red-400" : "text-muted-foreground"}`}>{c.status}</td>
                  <td className="py-1.5 pr-3 text-right">{c.train_samples}</td>
                  <td className="py-1.5 pr-3 text-right">{c.test_samples}</td>
                  <td className="py-1.5 pr-3 text-right">{fmt(c.metrics_before?.brier, 3)} → {fmt(c.metrics_after?.brier, 3)}</td>
                  <td className="py-1.5 pr-3 text-right">{fmt(c.metrics_before?.ece, 3)} → {fmt(c.metrics_after?.ece, 3)}</td>
                  <td className="py-1.5 pr-3 text-right">{fmt(c.metrics_before?.log_loss, 3)} → {fmt(c.metrics_after?.log_loss, 3)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </CardContent>
      </Card>
    </div>
  );
}

function AdjustmentsTab() {
  const { data } = useQuery({ queryKey: ["/api/phase14/adjustments"], queryFn: () => apiJson<any>("/phase14/adjustments"), staleTime: 60_000 });
  if (!data) return <p className="text-xs text-muted-foreground font-mono py-6">Loading adjustments…</p>;
  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3 text-xs font-mono">
        <span className="rounded border border-border/40 px-2 py-1">Caps: ±{data.caps?.per_source}/source, ±{data.caps?.total} total</span>
        <span className={`rounded border px-2 py-1 ${data.learning_frozen?.frozen ? "border-red-500/40 text-red-400" : "border-emerald-500/30 text-emerald-400"}`}>
          Learning {data.learning_frozen?.frozen ? "FROZEN" : "active"}
        </span>
      </div>
      {Object.entries(data.sources ?? {}).map(([source, entries]: [string, any]) => (
        <Card key={source} className="bg-card/40 border-border/40">
          <CardContent className="p-4 overflow-x-auto">
            <div className="text-xs font-mono uppercase text-muted-foreground mb-2">{source.replace(/_/g, " ")}</div>
            <table className="w-full text-[11px] font-mono">
              <thead>
                <tr className="text-muted-foreground border-b border-border/40 text-left">
                  <th className="py-1 pr-3">Key</th><th className="py-1 pr-3 text-right">Adj</th>
                  <th className="py-1 pr-3 text-right">N</th><th className="py-1 pr-3">Reliability</th>
                  <th className="py-1 pr-3 text-right">Expectancy</th><th className="py-1 pr-3 text-right">PF</th>
                  <th className="py-1 pr-3">Reason</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(entries).map(([key, e]: [string, any]) => (
                  <tr key={key} className="border-b border-border/20">
                    <td className="py-1 pr-3 font-bold">{key}</td>
                    <td className={`py-1 pr-3 text-right ${e.adjustment > 0 ? "text-emerald-400" : e.adjustment < 0 ? "text-red-400" : "text-muted-foreground"}`}>{e.adjustment > 0 ? "+" : ""}{e.adjustment}</td>
                    <td className="py-1 pr-3 text-right">{e.sample_size}</td>
                    <td className="py-1 pr-3"><RelBadge rel={e.reliability} /></td>
                    <td className="py-1 pr-3 text-right">₹{fmt(e.expectancy)}</td>
                    <td className="py-1 pr-3 text-right">{fmt(e.profit_factor)}</td>
                    <td className="py-1 pr-3 text-muted-foreground max-w-md truncate">{e.reason}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </CardContent>
        </Card>
      ))}
      <p className="text-[10px] text-muted-foreground font-mono">{data.note}</p>
    </div>
  );
}

function RegistryTab() {
  const qc = useQueryClient();
  const { data } = useQuery({ queryKey: ["/api/phase14/registry"], queryFn: () => apiJson<any>("/phase14/registry"), staleTime: 30_000 });
  const [checklistFor, setChecklistFor] = useState<string | null>(null);
  const { data: checklist } = useQuery({
    queryKey: ["/api/phase14/registry/checklist", checklistFor],
    queryFn: () => apiJson<any>(`/phase14/registry/checklist/${checklistFor}`),
    enabled: !!checklistFor,
  });
  const invalidate = () => qc.invalidateQueries({ queryKey: ["/api/phase14/registry"] });
  const createChallenger = useMutation({
    mutationFn: () => apiJson("/phase14/registry/challenger", { method: "POST", body: JSON.stringify({}), headers: { "Content-Type": "application/json" } }),
    onSuccess: invalidate,
  });
  const review = useMutation({
    mutationFn: ({ id, action }: { id: string; action: string }) =>
      apiJson(`/phase14/registry/review/${id}`, { method: "POST", body: JSON.stringify({ action, approver: "dashboard-user" }), headers: { "Content-Type": "application/json" } }),
    onSuccess: invalidate,
  });
  const rollback = useMutation({
    mutationFn: () => apiJson("/phase14/registry/rollback", { method: "POST" }),
    onSuccess: invalidate,
  });
  if (!data) return <p className="text-xs text-muted-foreground font-mono py-6">Loading registry…</p>;
  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3">
        <StatCard label="Champion" value={data.champion_version} sub={`previous: ${data.previous_champion ?? "—"}`} />
        <div className="ml-auto flex gap-2">
          <button onClick={() => createChallenger.mutate()} disabled={createChallenger.isPending}
            className="text-xs font-mono px-3 py-2 rounded border border-border hover:bg-muted/40 disabled:opacity-50">
            Create Challenger
          </button>
          <button onClick={() => rollback.mutate()} disabled={rollback.isPending || !data.previous_champion}
            className="text-xs font-mono px-3 py-2 rounded border border-amber-500/40 text-amber-400 hover:bg-amber-500/10 disabled:opacity-40">
            Rollback Champion
          </button>
        </div>
      </div>
      <Card className="bg-card/40 border-border/40">
        <CardContent className="p-4 overflow-x-auto">
          <table className="w-full text-[11px] font-mono">
            <thead>
              <tr className="text-muted-foreground border-b border-border/40 text-left">
                <th className="py-1.5 pr-3">Model</th><th className="py-1.5 pr-3">Status</th>
                <th className="py-1.5 pr-3 text-right">OOS Trades</th><th className="py-1.5 pr-3 text-right">Expectancy</th>
                <th className="py-1.5 pr-3 text-right">PF</th><th className="py-1.5 pr-3 text-right">Sharpe</th>
                <th className="py-1.5 pr-3 text-right">Brier</th><th className="py-1.5 pr-3">Approval</th>
                <th className="py-1.5 pr-3">Actions</th>
              </tr>
            </thead>
            <tbody>
              {(data.models ?? []).map((m: any) => (
                <tr key={m.model_version} className="border-b border-border/20">
                  <td className="py-1.5 pr-3 font-bold">{m.model_version}</td>
                  <td className={`py-1.5 pr-3 ${m.status === "CHAMPION" ? "text-emerald-400" : m.status === "CHALLENGER" ? "text-blue-400" : m.status === "REJECTED" ? "text-red-400" : "text-muted-foreground"}`}>{m.status}</td>
                  <td className="py-1.5 pr-3 text-right">{m.oos_trades ?? "—"}</td>
                  <td className="py-1.5 pr-3 text-right">₹{fmt(m.expectancy)}</td>
                  <td className="py-1.5 pr-3 text-right">{fmt(m.profit_factor)}</td>
                  <td className="py-1.5 pr-3 text-right">{fmt(m.sharpe, 3)}</td>
                  <td className="py-1.5 pr-3 text-right">{fmt(m.brier, 3)}</td>
                  <td className="py-1.5 pr-3">{m.approval_status}</td>
                  <td className="py-1.5 pr-3">
                    {m.status === "CHALLENGER" && (
                      <span className="flex gap-1">
                        <button onClick={() => setChecklistFor(m.model_version)} className="rounded border border-border/50 px-1.5 py-0.5 hover:bg-muted/40">Checklist</button>
                        <button onClick={() => review.mutate({ id: m.model_version, action: "APPROVE" })} className="rounded border border-emerald-500/40 text-emerald-400 px-1.5 py-0.5 hover:bg-emerald-500/10">Approve</button>
                        <button onClick={() => review.mutate({ id: m.model_version, action: "REJECT" })} className="rounded border border-red-500/40 text-red-400 px-1.5 py-0.5 hover:bg-red-500/10">Reject</button>
                        <button onClick={() => review.mutate({ id: m.model_version, action: "ARCHIVE" })} className="rounded border border-border/50 px-1.5 py-0.5 hover:bg-muted/40">Archive</button>
                      </span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </CardContent>
      </Card>
      {checklist && (
        <Card className="bg-card/40 border-border/40">
          <CardContent className="p-4">
            <div className="text-xs font-mono uppercase text-muted-foreground mb-2">
              Promotion checklist — {checklist.model_version} · {checklist.eligible ? <span className="text-emerald-400">ELIGIBLE</span> : <span className="text-red-400">NOT ELIGIBLE</span>}
            </div>
            <div className="space-y-1">
              {(checklist.checks ?? []).map((c: any, i: number) => (
                <div key={i} className="flex items-center gap-2 text-[11px] font-mono">
                  <span className={c.passed ? "text-emerald-400" : "text-red-400"}>{c.passed ? "✓" : "✗"}</span>
                  <span>{c.check}</span>
                  <span className="text-muted-foreground ml-auto">{String(c.actual ?? "")}</span>
                </div>
              ))}
            </div>
            <p className="text-[10px] text-muted-foreground font-mono mt-2">{checklist.note}</p>
          </CardContent>
        </Card>
      )}
      <p className="text-[10px] text-muted-foreground font-mono">{data.note}</p>

      {/* Phase 21 challenger registry & approvals (advisory) */}
      <Phase21GovernancePanel />
      <EvidenceProgressPanel />
    </div>
  );
}

function DriftTab() {
  const { data } = useQuery({ queryKey: ["/api/phase14/drift"], queryFn: () => apiJson<any>("/phase14/drift"), staleTime: 60_000 });
  const { data: alerts } = useQuery({ queryKey: ["/api/phase14/alerts"], queryFn: () => apiJson<any>("/phase14/alerts"), staleTime: 60_000 });
  if (!data) return <p className="text-xs text-muted-foreground font-mono py-6">Computing drift…</p>;
  const sevColor = (s: string) => s === "CRITICAL" ? "text-red-400" : s === "WARNING" ? "text-yellow-400" : "text-emerald-400";
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
        <StatCard label="Overall Severity" value={data.overall_severity} color={sevColor(data.overall_severity)} />
        <StatCard label="Learning Frozen" value={data.learning_frozen?.frozen ? "YES" : "NO"} color={data.learning_frozen?.frozen ? "text-red-400" : "text-emerald-400"} sub={data.learning_frozen?.reason} />
        <StatCard label="Sample Size" value={data.sample_size} sub="completed trades" />
      </div>
      <Card className="bg-card/40 border-border/40">
        <CardContent className="p-4">
          <div className="text-xs font-mono uppercase text-muted-foreground mb-2">Indicators</div>
          {(data.indicators ?? []).map((i: any, idx: number) => (
            <div key={idx} className="flex items-center gap-3 text-[11px] font-mono border-b border-border/20 py-1.5">
              <span className={`font-bold ${sevColor(i.severity)}`}>{i.severity}</span>
              <span className="font-bold">{i.name}</span>
              <span className="text-muted-foreground">{i.detail}</span>
              <span className="ml-auto">{String(i.value)}</span>
            </div>
          ))}
          <p className="text-[10px] text-muted-foreground font-mono mt-2">Recovery: {data.recovery_criteria}</p>
        </CardContent>
      </Card>
      <Card className="bg-card/40 border-border/40">
        <CardContent className="p-4">
          <div className="text-xs font-mono uppercase text-muted-foreground mb-2">Alerts (informational only — never trigger trades)</div>
          {(alerts?.alerts ?? []).slice().reverse().slice(0, 20).map((a: any) => (
            <div key={a.id} className="flex items-center gap-3 text-[11px] font-mono border-b border-border/20 py-1.5">
              <span className={sevColor(a.severity)}>{a.severity}</span>
              <span className="font-bold">{a.type}</span>
              <span className="text-muted-foreground">{a.message}</span>
              <span className="ml-auto text-muted-foreground">{String(a.ts).slice(0, 19)}</span>
            </div>
          ))}
          {!(alerts?.alerts ?? []).length && <p className="text-xs text-muted-foreground font-mono">No alerts.</p>}
        </CardContent>
      </Card>
    </div>
  );
}

function AuditTab() {
  const { data } = useQuery({ queryKey: ["/api/phase14/audit-log"], queryFn: () => apiJson<any>("/phase14/audit-log"), staleTime: 30_000 });
  return (
    <Card className="bg-card/40 border-border/40">
      <CardContent className="p-4">
        <div className="text-xs font-mono uppercase text-muted-foreground mb-2">Governance audit log</div>
        {(data?.log ?? []).slice().reverse().map((e: any) => (
          <div key={e.id} className="flex items-start gap-3 text-[11px] font-mono border-b border-border/20 py-1.5">
            <span className="text-muted-foreground whitespace-nowrap">{String(e.ts).slice(0, 19)}</span>
            <span className="font-bold">{e.event_type}</span>
            <span className="text-muted-foreground">{e.actor}</span>
            <span className="text-muted-foreground truncate">{typeof e.detail === "string" ? e.detail : JSON.stringify(e.detail)}</span>
          </div>
        ))}
        {!(data?.log ?? []).length && <p className="text-xs text-muted-foreground font-mono">No audit events yet.</p>}
      </CardContent>
    </Card>
  );
}

// ── page ───────────────────────────────────────────────────────────────────────

const TABS = [
  { id: "overview", label: "Overview", icon: Activity },
  { id: "performance", label: "Performance", icon: Scale },
  { id: "calibration", label: "Calibration", icon: SlidersHorizontal },
  { id: "adjustments", label: "Learning Adjustments", icon: GraduationCap },
  { id: "registry", label: "Model Registry", icon: Trophy },
  { id: "drift", label: "Drift Monitor", icon: Radar },
  { id: "audit", label: "Audit Log", icon: ScrollText },
];

export default function LearningGovernance() {
  const [tab, setTab] = useState("overview");
  return (
    <div className="space-y-5 max-w-7xl mx-auto">
      <div className="flex items-start justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-2xl font-bold tracking-tight flex items-center gap-2">
            <GraduationCap className="h-6 w-6 text-purple-400" /> Learning &amp; Governance
          </h1>
          <p className="text-muted-foreground text-sm mt-0.5">
            Adaptive paper-trade learning · calibration · champion–challenger governance —{" "}
            <span className="text-amber-400 font-mono">RESEARCH / PAPER LEARNING ONLY</span>
          </p>
        </div>
        <div className="flex gap-2">
          <a href={`${API_BASE}/phase14/export/evaluation?format=json`} download className="flex items-center gap-1.5 text-xs font-mono px-3 py-2 rounded border border-border hover:bg-muted/40">
            <Download className="h-3 w-3" /> Phase 14 JSON
          </a>
          <a href={`${API_BASE}/phase14/bundle/download?file=csv`} download className="flex items-center gap-1.5 text-xs font-mono px-3 py-2 rounded border border-border hover:bg-muted/40">
            <Download className="h-3 w-3" /> Phase 14 CSV
          </a>
          <a href={`${API_BASE}/phase14/bundle/download?file=json`} download className="flex items-center gap-1.5 text-xs font-mono px-3 py-2 rounded border border-purple-500/40 text-purple-400 hover:bg-purple-500/10">
            <Download className="h-3 w-3" /> Diagnostic Bundle
          </a>
        </div>
      </div>

      <DataFreshnessBar variant="scan" />

      <div className="flex items-center gap-2 rounded border border-border/40 bg-card/30 px-3 py-2 text-[11px] font-mono text-muted-foreground">
        <ShieldCheck className="h-3.5 w-3.5 text-emerald-400 shrink-0" />
        Adaptive learning uses completed historical and paper trades. Findings may be unreliable with limited samples.
        No model, rule, or strategy is promoted automatically. Human approval is required.
      </div>

      <div className="flex gap-1 flex-wrap border-b border-border/40">
        {TABS.map(({ id, label, icon: Icon }) => (
          <button key={id} onClick={() => setTab(id)}
            className={`flex items-center gap-1.5 px-3 py-2 text-xs font-mono border-b-2 transition-colors ${tab === id ? "border-purple-400 text-foreground" : "border-transparent text-muted-foreground hover:text-foreground"}`}>
            <Icon className="h-3.5 w-3.5" /> {label}
          </button>
        ))}
      </div>

      {tab === "overview" && <OverviewTab />}
      {tab === "performance" && <PerformanceTab />}
      {tab === "calibration" && <CalibrationTab />}
      {tab === "adjustments" && <AdjustmentsTab />}
      {tab === "registry" && <RegistryTab />}
      {tab === "drift" && <DriftTab />}
      {tab === "audit" && <AuditTab />}
    </div>
  );
}
