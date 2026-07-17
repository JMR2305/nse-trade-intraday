/**
 * Phase22Panels.tsx — shared Phase 22 widgets embedded into existing pages.
 * PAPER / RESEARCH ONLY — controlled auto paper trading & evidence.
 */
import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiJson } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

const mono = "text-[11px] font-mono";
const label = "text-[10px] uppercase tracking-wider text-zinc-500";

function Section({ title, children, tone = "amber" }: {
  title: string; children: React.ReactNode; tone?: "amber" | "emerald";
}) {
  const cls = tone === "emerald"
    ? "text-emerald-400 border-emerald-700" : "text-amber-400 border-amber-700";
  return (
    <div className="rounded-lg border border-zinc-800 bg-zinc-900/40 p-4 space-y-3">
      <div className="flex items-center gap-2">
        <h3 className="text-xs font-semibold text-zinc-200">{title}</h3>
        <Badge variant="outline" className={`text-[9px] ${cls}`}>PAPER ONLY</Badge>
      </div>
      {children}
    </div>
  );
}

const fmt = (v: unknown, suffix = "") =>
  v === null || v === undefined ? "—" : `${v}${suffix}`;

/* ── Activation banner + control (Dashboard, Broker & Execution) ─────────── */

export function PaperAutomationBanner() {
  const { data } = useQuery({
    queryKey: ["/api/phase22/activation"],
    queryFn: () => apiJson<any>("/phase22/activation"),
    refetchInterval: 60_000,
  });
  const qc = useQueryClient();
  const disable = useMutation({
    mutationFn: () => apiJson<any>("/phase22/disable", {
      method: "POST", body: JSON.stringify({}) }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["/api/phase22/activation"] }),
  });
  if (!data?.paper_automation_active) return null;
  return (
    <div className="flex items-center justify-between rounded-lg border border-emerald-700 bg-emerald-950/40 px-4 py-2">
      <div className="flex items-center gap-2">
        <span className="h-2 w-2 rounded-full bg-emerald-400 animate-pulse" />
        <span className="text-xs font-semibold text-emerald-300">
          PAPER AUTOMATION ACTIVE
        </span>
        <span className={`${mono} text-zinc-400`}>
          simulated trades only — no real Zerodha orders
        </span>
      </div>
      <Button size="sm" variant="destructive" className="h-6 text-[10px]"
        onClick={() => disable.mutate()} disabled={disable.isPending}>
        Disable
      </Button>
    </div>
  );
}

export function PaperAutomationControl() {
  const qc = useQueryClient();
  const { data: act } = useQuery({
    queryKey: ["/api/phase22/activation"],
    queryFn: () => apiJson<any>("/phase22/activation"),
  });
  const { data: ready, refetch: recheck, isFetching } = useQuery({
    queryKey: ["/api/phase22/readiness"],
    queryFn: () => apiJson<any>("/phase22/readiness"),
    staleTime: 30_000,
  });
  const [typed, setTyped] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const enable = useMutation({
    mutationFn: () => apiJson<any>("/phase22/enable", {
      method: "POST",
      body: JSON.stringify({ confirmation_text: typed }),
    }),
    onSuccess: () => {
      setErr(null); setTyped("");
      qc.invalidateQueries({ queryKey: ["/api/phase22/activation"] });
    },
    onError: (e: any) => setErr(String(e?.message || e)),
  });
  const disable = useMutation({
    mutationFn: () => apiJson<any>("/phase22/disable", {
      method: "POST", body: JSON.stringify({}) }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["/api/phase22/activation"] }),
  });

  const active = !!act?.paper_automation_active;
  const checks: any[] = ready?.checks || [];
  const failed: string[] = ready?.failed_checks || [];

  return (
    <Section title="Paper Automation (Phase 22)" tone={active ? "emerald" : "amber"}>
      {active ? (
        <div className="space-y-2">
          <p className={`${mono} text-emerald-400`}>
            ACTIVE since {act?.activation_record?.activated_at} (config{" "}
            {act?.activation_record?.config_hash})
          </p>
          <Button size="sm" variant="destructive" className="h-7 text-[11px]"
            onClick={() => disable.mutate()} disabled={disable.isPending}>
            Disable auto paper entries
          </Button>
        </div>
      ) : (
        <div className="space-y-3">
          <p className={`${mono} text-zinc-400`}>
            Auto paper entries are OFF (default after every deployment).
          </p>
          <div>
            <div className="flex items-center gap-2">
              <p className={label}>Readiness checklist</p>
              <Button size="sm" variant="outline" className="h-5 text-[9px]"
                onClick={() => recheck()} disabled={isFetching}>
                {isFetching ? "Checking…" : "Re-check"}
              </Button>
            </div>
            <ul className="mt-1 grid gap-x-4 md:grid-cols-2">
              {checks.map((c) => (
                <li key={c.check} className={`${mono} ${c.passed ? "text-emerald-500" : "text-red-400"}`}>
                  {c.passed ? "✓" : "✗"} {c.check}
                </li>
              ))}
            </ul>
            {failed.length > 0 && (
              <p className={`${mono} text-red-400 mt-1`}>
                Activation blocked — failed: {failed.join(", ")}
              </p>
            )}
          </div>
          <div className="rounded border border-amber-800 bg-amber-950/30 p-3 space-y-2">
            <p className="text-[11px] text-amber-200">
              {act?.acknowledgement_statement ||
                "I understand this enables automatic simulated paper trades only. " +
                "No real Zerodha orders will be placed. Paper trades can gain or " +
                "lose simulated capital."}
            </p>
            <p className={label}>Type ENABLE PAPER ONLY to confirm</p>
            <div className="flex gap-2">
              <Input value={typed} onChange={(e) => setTyped(e.target.value)}
                placeholder="ENABLE PAPER ONLY"
                className="h-7 text-[11px] font-mono bg-zinc-950" />
              <Button size="sm" className="h-7 text-[11px]"
                disabled={typed.trim() !== "ENABLE PAPER ONLY"
                  || !ready?.all_passed || enable.isPending}
                onClick={() => enable.mutate()}>
                Enable
              </Button>
            </div>
            {err && <p className={`${mono} text-red-400`}>{err}</p>}
            <p className={`${mono} text-zinc-500`}>
              This confirmation is never reused for live trading. Live-order
              write paths remain disabled.
            </p>
          </div>
        </div>
      )}
    </Section>
  );
}

/* ── Dashboard status strip ──────────────────────────────────────────────── */

export function Phase22DashboardStatus() {
  const { data: act } = useQuery({
    queryKey: ["/api/phase22/activation"],
    queryFn: () => apiJson<any>("/phase22/activation"),
    refetchInterval: 60_000,
  });
  const { data: sched } = useQuery({
    queryKey: ["/api/phase20/scheduler/health"],
    queryFn: () => apiJson<any>("/phase20/scheduler/health"),
    refetchInterval: 60_000,
  });
  const { data: report } = useQuery({
    queryKey: ["/api/phase22/daily-report"],
    queryFn: () => apiJson<any>("/phase22/daily-report"),
    staleTime: 120_000,
  });
  const { data: prog } = useQuery({
    queryKey: ["/api/phase22/progress"],
    queryFn: () => apiJson<any>("/phase22/progress"),
    staleTime: 120_000,
  });
  const done = prog?.completed_paper_trades ?? 0;
  const targets = [30, 50, 100];
  return (
    <Section title="Paper Automation Status (Phase 22)">
      <div className="grid gap-3 md:grid-cols-4">
        <div>
          <p className={label}>Automation</p>
          <p className={`${mono} ${act?.paper_automation_active ? "text-emerald-400" : "text-zinc-400"}`}>
            {act?.paper_automation_active ? "ACTIVE (paper only)" : "OFF (default)"}
          </p>
        </div>
        <div>
          <p className={label}>Next scheduled scan</p>
          <p className={`${mono} text-zinc-300`}>
            {fmt(sched?.scheduler?.next_due_at?.replace?.("T", " ")?.slice?.(0, 19))}
          </p>
        </div>
        <div>
          <p className={label}>Trades today</p>
          <p className={`${mono} text-zinc-300`}>
            {fmt(report?.paper_entries_opened)} opened · {fmt(report?.exits_completed)} exits
          </p>
        </div>
        <div>
          <p className={label}>Daily simulated P&L</p>
          <p className={`${mono} ${(report?.realized_pnl ?? 0) >= 0 ? "text-emerald-400" : "text-red-400"}`}>
            ₹{fmt(report?.realized_pnl)} realized / ₹{fmt(report?.unrealized_pnl)} unrealized
          </p>
        </div>
      </div>
      <div>
        <p className={label}>Progress toward 30 / 50 / 100 completed trades</p>
        <div className="flex gap-3 mt-1">
          {targets.map((t) => (
            <div key={t} className="flex-1">
              <div className="h-1.5 rounded bg-zinc-800 overflow-hidden">
                <div className="h-full bg-sky-500"
                  style={{ width: `${Math.min(100, (done / t) * 100)}%` }} />
              </div>
              <p className={`${mono} text-zinc-500 mt-0.5`}>{done}/{t}</p>
            </div>
          ))}
        </div>
      </div>
    </Section>
  );
}

/* ── Evidence progress (Learning & Governance) ───────────────────────────── */

export function EvidenceProgressPanel() {
  const { data } = useQuery({
    queryKey: ["/api/phase22/progress"],
    queryFn: () => apiJson<any>("/phase22/progress"),
    staleTime: 120_000,
  });
  if (!data) return null;
  const rc = data.regime_trade_counts || {};
  return (
    <Section title="Evidence Progress (Phase 22)">
      <div className="grid gap-3 md:grid-cols-4">
        {[
          ["Completed paper trades", data.completed_paper_trades],
          ["Open paper trades", data.open_paper_trades],
          ["Blocked candidates", data.blocked_candidates],
          ["Total evaluated", data.total_evaluated_candidates],
          ["Distinct trading days", data.distinct_trading_days],
          ["Bullish / Bearish", `${rc.bullish ?? 0} / ${rc.bearish ?? 0}`],
          ["Range-bound", rc.range_bound],
          ["High vol / Low vol", `${rc.high_volatility ?? 0} / ${rc.low_volatility ?? 0}`],
        ].map(([k, v]) => (
          <div key={String(k)}>
            <p className={label}>{k}</p>
            <p className={`${mono} text-zinc-200`}>{fmt(v)}</p>
          </div>
        ))}
      </div>
      <div>
        <p className={label}>Milestones</p>
        <div className="flex flex-wrap gap-2 mt-1">
          {(data.milestones || []).map((m: any) => (
            <Badge key={m.trades} variant="outline"
              className={`text-[9px] ${m.reached ? "text-emerald-400 border-emerald-700" : "text-zinc-500 border-zinc-700"}`}>
              {m.trades}: {m.label}{m.reached ? " ✓" : ` (${m.remaining} to go)`}
            </Badge>
          ))}
        </div>
      </div>
      <div className="grid gap-3 md:grid-cols-2">
        <div>
          <p className={label}>Strategy coverage</p>
          <p className={`${mono} text-zinc-400`}>
            {(data.strategy_coverage || []).join(", ") || "None yet"}
          </p>
        </div>
        <div>
          <p className={label}>Sector coverage</p>
          <p className={`${mono} text-zinc-400`}>
            {(data.sector_coverage || []).join(", ") || "None yet"}
          </p>
        </div>
      </div>
      <p className={`${mono} text-amber-500`}>{data.validation_note}</p>
    </Section>
  );
}

/* ── Daily close report + exports ────────────────────────────────────────── */

export function Phase22DailyReportPanel() {
  const qc = useQueryClient();
  const { data } = useQuery({
    queryKey: ["/api/phase22/daily-report"],
    queryFn: () => apiJson<any>("/phase22/daily-report"),
    staleTime: 120_000,
  });
  const build = useMutation({
    mutationFn: () => apiJson<any>("/phase22/export", {
      method: "POST", body: JSON.stringify({}) }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["/api/phase22/daily-report"] }),
  });
  if (!data) return null;
  const d = data.report_date;
  const files = ["json", "csv", "pdf"].map(
    (ext) => `Phase22_Daily_${d}.${ext}`);
  return (
    <Section title={`Daily Close Report — ${d} (Phase 22)`}>
      <div className="grid gap-3 md:grid-cols-4">
        {[
          ["Scheduled scans", data.scheduled_scans_completed],
          ["Failed scans", data.failed_scans],
          ["Candidates evaluated", data.candidates_evaluated],
          ["Entries opened", data.paper_entries_opened],
          ["Entries blocked", data.entries_blocked],
          ["Exits completed", data.exits_completed],
          ["Pending-data actions", data.pending_data_actions],
          ["Daily drawdown", `₹${fmt(data.daily_drawdown)}`],
        ].map(([k, v]) => (
          <div key={String(k)}>
            <p className={label}>{k}</p>
            <p className={`${mono} text-zinc-200`}>{fmt(v)}</p>
          </div>
        ))}
      </div>
      <p className={`${mono} ${data.live_order_disabled_verification?.verified ? "text-emerald-400" : "text-red-400"}`}>
        Live-order write paths:{" "}
        {data.live_order_disabled_verification?.verified ? "DISABLED ✓ (verified)" : "VERIFICATION FAILED"}
      </p>
      <div className="flex items-center gap-2">
        <Button size="sm" variant="outline" className="h-7 text-[11px]"
          onClick={() => build.mutate()} disabled={build.isPending}>
          {build.isPending ? "Building…" : "Build JSON / CSV / PDF"}
        </Button>
        {files.map((f) => (
          <a key={f} href={`/api/phase22/export/${f}`}
            className={`${mono} text-sky-400 hover:underline`}>
            {f.split(".").pop()?.toUpperCase()}
          </a>
        ))}
      </div>
    </Section>
  );
}

/* ── Paper eligibility (Trade Decisions) ─────────────────────────────────── */

export function PaperEligibilityPanel({ symbol }: { symbol: string }) {
  const { data } = useQuery({
    queryKey: ["/api/phase20/evaluation"],
    queryFn: () => apiJson<any>("/phase20/evaluation"),
    staleTime: 60_000,
  });
  const { data: ev } = useQuery({
    queryKey: ["/api/phase22/evidence", symbol],
    queryFn: () => apiJson<any>("/phase22/evidence?limit=200"),
    staleTime: 60_000,
  });
  if (!data) return null;
  const cand = (data.candidates || []).find(
    (c: any) => String(c.symbol).toUpperCase() === symbol.toUpperCase());
  if (!cand) return null;
  const evRow = (ev?.rows || []).find(
    (r: any) => String(r.symbol).toUpperCase() === symbol.toUpperCase());
  return (
    <Section title={`Paper Eligibility — ${symbol} (Phase 22)`}>
      <p className={`${mono} ${cand.eligible ? "text-emerald-400" : "text-red-400"}`}>
        {cand.eligible ? "ELIGIBLE for simulated paper entry" : "BLOCKED"}
      </p>
      {!cand.eligible && (
        <div>
          <p className={label}>Blocked gates</p>
          <ul className="mt-1 space-y-0.5">
            {(cand.failed_gates || []).map((g: string) => (
              <li key={g} className={`${mono} text-red-400`}>✗ {g}</li>
            ))}
          </ul>
        </div>
      )}
      {evRow?.paper_trade_id && (
        <p className={`${mono} text-zinc-400`}>
          Linked paper trade: <span className="text-sky-400">{evRow.paper_trade_id}</span>
        </p>
      )}
    </Section>
  );
}

/* ── Trade Replay evidence (MAE/MFE + fills) ─────────────────────────────── */

export function Phase22ReplayEvidence({ tradeId }: { tradeId?: string }) {
  const { data } = useQuery({
    queryKey: ["/api/phase22/evidence-replay"],
    queryFn: () => apiJson<any>("/phase22/evidence?limit=500"),
    staleTime: 120_000,
  });
  if (!tradeId || !data) return null;
  const row = (data.rows || []).find((r: any) => r.paper_trade_id === tradeId);
  if (!row) return null;
  return (
    <Section title={`Phase 22 Evidence — ${row.symbol}`}>
      <div className="grid gap-3 md:grid-cols-4">
        {[
          ["Decision", row.decision],
          ["Signal price", row.signal_price],
          ["MAE %", row.mae_pct],
          ["MFE %", row.mfe_pct],
          ["15m return %", row.ret_15m],
          ["60m return %", row.ret_60m],
          ["EOD return %", row.ret_eod],
          ["Final outcome", row.final_outcome || "OPEN / pending"],
        ].map(([k, v]) => (
          <div key={String(k)}>
            <p className={label}>{k}</p>
            <p className={`${mono} text-zinc-200`}>{fmt(v)}</p>
          </div>
        ))}
      </div>
      <p className={`${mono} text-zinc-500`}>
        Returns are recorded only after each horizon has actually elapsed —
        never from future or fabricated data. Append-only dataset.
      </p>
    </Section>
  );
}

/* ── Evidence table (Trade Replay) ───────────────────────────────────────── */

export function Phase22EvidenceTable() {
  const { data } = useQuery({
    queryKey: ["/api/phase22/evidence-table"],
    queryFn: () => apiJson<any>("/phase22/evidence?limit=50"),
    staleTime: 120_000,
  });
  const rows: any[] = data?.rows || [];
  return (
    <Section title="Phase 22 Evidence Dataset (append-only)">
      <p className={`${mono} text-zinc-500`}>
        Every evaluated candidate — opened AND blocked — with returns recorded
        only after each horizon actually elapsed. MAE/MFE from observed quotes
        only. Deterministic replay: decision context is immutable.
      </p>
      {rows.length === 0 ? (
        <p className={`${mono} text-zinc-500`}>
          No evidence rows yet. Rows accumulate automatically with each fresh
          scheduled scan.
        </p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-left">
            <thead>
              <tr>
                {["Time", "Symbol", "Decision", "Eligibility", "Trade", "15m%",
                  "60m%", "EOD%", "1d%", "MAE%", "MFE%", "Outcome"].map((h) => (
                  <th key={h} className={`${label} pr-3 pb-1`}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.evidence_id} className="border-t border-zinc-800/60">
                  <td className={`${mono} text-zinc-500 pr-3 py-1`}>
                    {String(r.recorded_at || "").slice(5, 16).replace("T", " ")}
                  </td>
                  <td className={`${mono} text-zinc-200 pr-3`}>{r.symbol}</td>
                  <td className={`${mono} text-zinc-300 pr-3`}>{fmt(r.decision)}</td>
                  <td className={`${mono} pr-3 ${r.eligibility_result === "ELIGIBLE" ? "text-emerald-400" : "text-red-400"}`}>
                    {r.eligibility_result}
                  </td>
                  <td className={`${mono} text-sky-400 pr-3`}>
                    {r.paper_trade_id || "—"}
                  </td>
                  {[r.ret_15m, r.ret_60m, r.ret_eod, r.ret_1d, r.mae_pct, r.mfe_pct].map((v, i) => (
                    <td key={i} className={`${mono} pr-3 ${v === null || v === undefined ? "text-zinc-600" : Number(v) >= 0 ? "text-emerald-400" : "text-red-400"}`}>
                      {v === null || v === undefined ? "…" : v}
                    </td>
                  ))}
                  <td className={`${mono} text-zinc-400`}>{r.final_outcome || "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Section>
  );
}

/* ── Engine health (Live Data Health) ────────────────────────────────────── */

export function Phase22HealthPanel() {
  const { data: sched } = useQuery({
    queryKey: ["/api/phase20/scheduler/health"],
    queryFn: () => apiJson<any>("/phase20/scheduler/health"),
    refetchInterval: 60_000,
  });
  const { data: act } = useQuery({
    queryKey: ["/api/phase22/activation"],
    queryFn: () => apiJson<any>("/phase22/activation"),
  });
  const { data: ev } = useQuery({
    queryKey: ["/api/phase22/evidence-health"],
    queryFn: () => apiJson<any>("/phase22/evidence?limit=1"),
    staleTime: 120_000,
  });
  const { data: bundle } = useQuery({
    queryKey: ["/api/phase22/bundle"],
    queryFn: () => apiJson<any>("/phase22/bundle"),
    refetchInterval: 60_000,
  });
  const ok = (b: boolean) => (b ? "text-emerald-400" : "text-red-400");
  const evOk = !!ev?.summary?.append_only;
  const s = sched?.scheduler;
  const ts = (v: any) =>
    typeof v === "string" ? v.replace("T", " ").slice(0, 19) : v;
  const pub = bundle?.published_bundle;
  const attempt = bundle?.last_attempt;
  return (
    <Section title="Paper Engine Health (Phase 22)">
      <div className="grid gap-3 md:grid-cols-4">
        <div>
          <p className={label}>Scheduler</p>
          <p className={`${mono} ${ok(["HEALTHY", "DEGRADED"].includes(s?.health))}`}>
            {fmt(s?.health)}
          </p>
        </div>
        <div>
          <p className={label}>Paper engine</p>
          <p className={`${mono} ${act?.paper_automation_active ? "text-emerald-400" : "text-zinc-400"}`}>
            {act?.paper_automation_active ? "ACTIVE (auto entries ON)" : "STANDBY (auto entries OFF)"}
          </p>
        </div>
        <div>
          <p className={label}>Evidence writer</p>
          <p className={`${mono} ${ok(evOk)}`}>
            {evOk ? `HEALTHY (${ev?.summary?.total_rows} rows)` : "UNAVAILABLE"}
          </p>
        </div>
        <div>
          <p className={label}>Live-order write paths</p>
          <p className={`${mono} text-emerald-400`}>DISABLED</p>
        </div>
        <div>
          <p className={label}>Last trigger</p>
          <p className={`${mono} text-zinc-300`}>{fmt(s?.last_trigger)}</p>
        </div>
        <div>
          <p className={label}>Scheduler heartbeat</p>
          <p className={`${mono} text-zinc-300`}>{fmt(ts(s?.heartbeat_at))}</p>
        </div>
        <div>
          <p className={label}>Last scheduled scan</p>
          <p className={`${mono} text-zinc-300`}>{fmt(ts(s?.last_success_at))}</p>
        </div>
        <div>
          <p className={label}>Next scan due</p>
          <p className={`${mono} text-zinc-300`}>{fmt(ts(s?.next_due_at))}</p>
        </div>
        <div>
          <p className={label}>Missed scans</p>
          <p className={`${mono} ${(s?.missed_count ?? 0) > 0 ? "text-amber-400" : "text-zinc-300"}`}>
            {fmt(s?.missed_count)}
          </p>
        </div>
        <div>
          <p className={label}>Scheduler owner</p>
          <p className={`${mono} text-zinc-300`}>{fmt(s?.owner)}</p>
        </div>
        <div>
          <p className={label}>Scan lock</p>
          <p className={`${mono} text-zinc-300`}>
            {s?.lock
              ? `${s.lock.holder ?? "-"} (expires ${ts(s.lock.expires_at) ?? "-"})`
              : "free"}
          </p>
        </div>
        <div>
          <p className={label}>Last scheduler error</p>
          <p className={`${mono} ${s?.last_error ? "text-red-400" : "text-zinc-500"}`}>
            {s?.last_error ? String(s.last_error).slice(0, 80) : "none"}
          </p>
        </div>
      </div>
      <div className="mt-3 rounded border border-zinc-800 bg-zinc-950/40 p-3">
        <p className="text-[11px] font-semibold text-zinc-300 mb-2">
          Scan bundle (all pages regenerated from one scan)
        </p>
        <div className="grid gap-3 md:grid-cols-4">
          <div>
            <p className={label}>Published bundle</p>
            <p className={`${mono} ${pub?.status === "SYNCHRONIZED" ? "text-emerald-400" : "text-amber-400"}`}>
              {fmt(pub?.status)}
            </p>
          </div>
          <div>
            <p className={label}>Bundle scan id</p>
            <p className={`${mono} text-zinc-300`}>{fmt(pub?.scan_id)}</p>
          </div>
          <div>
            <p className={label}>Matches canonical scan</p>
            <p className={`${mono} ${ok(!!bundle?.bundle_matches_canonical_scan)}`}>
              {bundle?.bundle_matches_canonical_scan ? "YES" : "NO"}
            </p>
          </div>
          <div>
            <p className={label}>Hard mismatches</p>
            <p className={`${mono} ${(pub?.consistency?.hard_mismatch_count ?? 0) === 0 ? "text-emerald-400" : "text-red-400"}`}>
              {fmt(pub?.consistency?.hard_mismatch_count)}
            </p>
          </div>
          <div>
            <p className={label}>Out-of-sync values</p>
            <p className={`${mono} ${(pub?.consistency?.stale_source_count ?? 0) === 0 ? "text-emerald-400" : "text-amber-400"}`}>
              {fmt(pub?.consistency?.stale_source_count)}
            </p>
          </div>
          <div>
            <p className={label}>Model / rule version</p>
            <p className={`${mono} text-zinc-300`}>
              {fmt(pub?.model_version)} / {fmt(pub?.rule_version)}
            </p>
          </div>
          <div>
            <p className={label}>Full-scan provider</p>
            <p className={`${mono} text-zinc-300`}>{fmt(pub?.providers?.full_scan_provider)}</p>
          </div>
          <div>
            <p className={label}>Last attempt</p>
            <p className={`${mono} ${attempt?.status === "SYNCHRONIZED" ? "text-emerald-400" : "text-amber-400"}`}>
              {fmt(attempt?.status)}
              {attempt?.failed_modules?.length
                ? ` (failed: ${attempt.failed_modules.join(", ")})` : ""}
            </p>
          </div>
        </div>
      </div>
    </Section>
  );
}

/* ── Broker vs simulated execution distinction ───────────────────────────── */

export function ExecutionModeCard() {
  return (
    <Section title="Execution Modes" tone="emerald">
      <div className="grid gap-3 md:grid-cols-2">
        <div className="rounded border border-sky-800 bg-sky-950/30 p-3">
          <p className="text-[11px] font-semibold text-sky-300">
            Real market-data connection
          </p>
          <p className={`${mono} text-zinc-400 mt-1`}>
            Zerodha/NSE data is used ONLY for quotes and session validation.
            No order write APIs are called.
          </p>
        </div>
        <div className="rounded border border-amber-800 bg-amber-950/30 p-3">
          <p className="text-[11px] font-semibold text-amber-300">
            Simulated paper execution
          </p>
          <p className={`${mono} text-zinc-400 mt-1`}>
            All fills are simulated (SLIPPAGE_ADJUSTED_NEXT_QUOTE model) against
            simulated capital. This is NOT a real broker connection.
          </p>
        </div>
      </div>
    </Section>
  );
}
