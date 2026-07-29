/**
 * LiveReadiness.tsx — Phase 6.5
 * Live Readiness & Operational Validation dashboard.
 *
 * Sections:
 *   1. Overall Readiness (Score ring, grade, GO/NO-GO verdict, category scores)
 *   2. System Health (checks table with PASS/WARN/FAIL)
 *   3. Data Quality (checks + record counts)
 *   4. Recovery (checks + recovery health)
 *   5. API Health (endpoint probe results)
 *   6. Broker Readiness (paper trading only — never live)
 *   7. Configuration (feature flags, env vars, checksum)
 *   8. Security (checks + security level)
 *   9. Go / No-Go Summary (strengths, weaknesses, recommendations)
 *  10. Future Integration Hooks (CI/CD, deployment checklist stub)
 *
 * READ-ONLY. ADVISORY-ONLY.
 * This page NEVER enables live trading.
 */
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";
import { apiJson } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  ShieldCheck, RefreshCw, Download, CheckCircle2,
  AlertTriangle, XCircle, Minus, Info, ChevronRight,
  Rocket,
} from "lucide-react";
import { SSE_STREAM_URL } from "@/lib/apiConfig";

// ---------------------------------------------------------------------------
// API hooks
// ---------------------------------------------------------------------------

// Data Quality and summary scores are invalidated immediately when a new paper
// trade is recorded — staleTime kept at 60 s as a safety-net fallback only.
const Q = { staleTime: 60 * 1000, retry: 1 };

function useSummary()  { return useQuery({ queryKey: ["rd-summary"],  queryFn: () => apiJson("readiness/summary"),  ...Q }); }
function useSystem()   { return useQuery({ queryKey: ["rd-system"],   queryFn: () => apiJson("readiness/system"),   ...Q }); }
function useData()     { return useQuery({ queryKey: ["rd-data"],     queryFn: () => apiJson("readiness/data"),     ...Q }); }
function useRecovery() { return useQuery({ queryKey: ["rd-recovery"], queryFn: () => apiJson("readiness/recovery"), ...Q }); }
function useSecurity() { return useQuery({ queryKey: ["rd-security"], queryFn: () => apiJson("readiness/security"), ...Q }); }

/**
 * Subscribe to the SSE stream and invalidate the Data Quality and Summary
 * queries the moment a `paper.trade.recorded` event arrives.  No polling
 * loop: the event is pushed by the server's paper-trade write path.
 */
function usePaperTradeInvalidation() {
  const qc = useQueryClient();
  useEffect(() => {
    let es: EventSource | null = null;
    let closed = false;

    const connect = () => {
      if (closed) return;
      es = new EventSource(SSE_STREAM_URL);

      es.addEventListener("paper.trade.recorded", () => {
        // A paper trade was just written — refresh the two score-bearing queries.
        void qc.invalidateQueries({ queryKey: ["rd-data"] });
        void qc.invalidateQueries({ queryKey: ["rd-summary"] });
      });

      es.onerror = () => {
        es?.close();
        if (!closed) setTimeout(connect, 5_000);
      };
    };

    connect();
    return () => {
      closed = true;
      es?.close();
    };
  }, [qc]);
}

// ---------------------------------------------------------------------------
// Shared helpers
// ---------------------------------------------------------------------------

function pct(v: number | undefined, d = 1) { return v == null ? "0.0%" : `${(v * 100).toFixed(d)}%`; }
function fmt(v: number | undefined, d = 1) { return v == null ? "—" : v.toFixed(d); }

function StatusIcon({ status }: { status: string }) {
  if (status === "PASS") return <CheckCircle2 className="h-4 w-4 text-green-400 shrink-0" />;
  if (status === "WARN") return <AlertTriangle className="h-4 w-4 text-yellow-400 shrink-0" />;
  return <XCircle className="h-4 w-4 text-red-400 shrink-0" />;
}

function StatusBadge({ status }: { status: string }) {
  const cls =
    status === "PASS" ? "bg-green-500/15 text-green-400 border-green-500/30" :
    status === "WARN" ? "bg-yellow-500/15 text-yellow-400 border-yellow-500/30" :
                        "bg-red-500/15 text-red-400 border-red-500/30";
  return <span className={`inline-flex rounded-full border px-2 py-0.5 text-[10px] font-bold ${cls}`}>{status}</span>;
}

function ScoreBar({ score, label }: { score: number; label: string }) {
  const colour =
    score >= 80 ? "#4ade80" :
    score >= 60 ? "#facc15" : "#f87171";
  return (
    <div className="space-y-1">
      <div className="flex justify-between text-[11px]">
        <span className="text-muted-foreground">{label}</span>
        <span className="font-medium tabular-nums" style={{ color: colour }}>{score.toFixed(0)}</span>
      </div>
      <div className="h-1.5 rounded-full bg-border/40 overflow-hidden">
        <div className="h-full rounded-full transition-all" style={{ width: `${score}%`, background: colour }} />
      </div>
    </div>
  );
}

function ScoreRing({ score, grade }: { score: number; grade: string }) {
  const r = 44;
  const circ = 2 * Math.PI * r;
  const dash = (score / 100) * circ;
  const col = score >= 80 ? "#4ade80" : score >= 60 ? "#facc15" : "#f87171";
  return (
    <div className="relative inline-flex items-center justify-center w-28 h-28">
      <svg className="absolute inset-0 -rotate-90" width="112" height="112" viewBox="0 0 100 100">
        <circle cx="50" cy="50" r={r} fill="none" stroke="currentColor" strokeWidth="7" className="text-border/30" />
        <circle cx="50" cy="50" r={r} fill="none" stroke={col} strokeWidth="7"
          strokeDasharray={`${dash} ${circ}`} strokeLinecap="round"
          style={{ transition: "stroke-dasharray 0.6s ease" }} />
      </svg>
      <div className="flex flex-col items-center z-10">
        <span className="text-2xl font-bold tabular-nums" style={{ color: col }}>{score.toFixed(0)}</span>
        <span className="text-[10px] text-muted-foreground">/ 100</span>
        <span className="mt-0.5 rounded-full px-2 py-0.5 text-[10px] font-bold"
          style={{ background: col + "22", color: col }}>Grade {grade}</span>
      </div>
    </div>
  );
}

function SectionCard({ title, children, className = "" }: { title: string; children: React.ReactNode; className?: string }) {
  return (
    <div className={`rounded-xl border border-border bg-card/60 p-5 space-y-4 ${className}`}>
      <h3 className="text-sm font-semibold">{title}</h3>
      {children}
    </div>
  );
}

function ChecksTable({ checks }: { checks: any[] }) {
  if (!checks?.length) return <p className="text-xs text-muted-foreground/60">No checks available.</p>;
  return (
    <div className="rounded-lg border border-border overflow-hidden">
      <table className="w-full text-xs">
        <thead className="bg-muted/30">
          <tr>
            <th className="text-left px-3 py-2 text-muted-foreground font-medium w-6"></th>
            <th className="text-left px-3 py-2 text-muted-foreground font-medium">Check</th>
            <th className="text-left px-3 py-2 text-muted-foreground font-medium hidden md:table-cell">Detail</th>
            <th className="text-center px-3 py-2 text-muted-foreground font-medium">Status</th>
          </tr>
        </thead>
        <tbody>
          {checks.map((c: any, i: number) => (
            <tr key={i} className="border-t border-border/50">
              <td className="px-3 py-2"><StatusIcon status={c.status} /></td>
              <td className="px-3 py-2 font-medium text-foreground">{c.label}</td>
              <td className="px-3 py-2 text-muted-foreground hidden md:table-cell max-w-xs truncate">{c.detail}</td>
              <td className="px-3 py-2 text-center"><StatusBadge status={c.status} /></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function DisabledState() {
  return (
    <div className="rounded-xl border border-border bg-card/50 p-8 text-center space-y-2">
      <ShieldCheck className="h-8 w-8 mx-auto text-muted-foreground/40" />
      <p className="text-sm font-medium text-muted-foreground">Live Readiness Validation is disabled</p>
      <p className="text-xs text-muted-foreground/60">
        Set <code className="bg-border/40 px-1 rounded">READINESS_VALIDATION_ENABLED=true</code> to enable.
      </p>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Verdict banner
// ---------------------------------------------------------------------------

function VerdictBanner({ verdict, score }: { verdict: string; score: number }) {
  const isReady  = verdict?.includes("READY FOR EXTENDED");
  const isWarn   = verdict?.includes("WITH OBSERVATIONS");
  const bg = isReady ? "border-green-500/30 bg-green-500/10" :
             isWarn  ? "border-yellow-500/30 bg-yellow-500/10" :
                       "border-red-500/30 bg-red-500/10";
  const textCol = isReady ? "text-green-400" : isWarn ? "text-yellow-400" : "text-red-400";
  const Icon = isReady ? Rocket : isWarn ? AlertTriangle : XCircle;

  return (
    <div className={`flex items-center gap-3 rounded-xl border p-4 ${bg}`}>
      <Icon className={`h-5 w-5 shrink-0 ${textCol}`} />
      <div>
        <p className={`text-sm font-bold ${textCol}`}>{verdict ?? "UNKNOWN"}</p>
        <p className="text-xs text-muted-foreground mt-0.5">
          Operational Readiness Score: <strong className={textCol}>{score?.toFixed(0)}/100</strong>
        </p>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Section 1 — Overall Readiness
// ---------------------------------------------------------------------------

function Section1Overall({ summary }: { summary: any }) {
  const score   = summary?.readiness_score ?? 0;
  const grade   = summary?.grade ?? "D";
  const verdict = summary?.verdict ?? "NOT READY";
  const cats    = summary?.category_scores ?? {};

  return (
    <SectionCard title="🚦 Overall Readiness">
      <VerdictBanner verdict={verdict} score={score} />
      <div className="flex flex-col md:flex-row gap-6 items-start">
        <ScoreRing score={score} grade={grade} />
        <div className="flex-1 space-y-3">
          <div className="grid grid-cols-2 gap-x-6 gap-y-2">
            {Object.entries(cats).map(([cat, s]: [string, any]) => (
              <ScoreBar key={cat} score={s} label={cat.replace(/([A-Z])/g, " $1").trim()} />
            ))}
          </div>
          <div className="flex flex-wrap gap-3 text-xs text-muted-foreground pt-1">
            <span>{summary?.total_checks ?? 0} total checks</span>
            <span className="text-green-400">✓ {summary?.passed_checks ?? 0} passed</span>
            <span className="text-yellow-400">⚠ {summary?.warning_count ?? 0} warnings</span>
            <span className="text-red-400">✕ {summary?.critical_failure_count ?? 0} critical</span>
          </div>
        </div>
      </div>
    </SectionCard>
  );
}

// ---------------------------------------------------------------------------
// Section 2 — System Health
// ---------------------------------------------------------------------------

function Section2SystemHealth({ system }: { system: any }) {
  const sh = system?.system_health ?? {};
  return (
    <SectionCard title="⚙️ System Health">
      <div className="flex flex-wrap gap-4 text-xs text-muted-foreground mb-2">
        <span>Score: <strong className="text-foreground">{sh.score?.toFixed(0) ?? "—"}</strong></span>
        <span>Latency: <strong className="text-foreground">{sh.latency_ms?.toFixed(0) ?? "—"}ms</strong></span>
        <span>DB: <strong className={sh.db_accessible ? "text-green-400" : "text-red-400"}>
          {sh.db_accessible ? "Connected" : "Unavailable"}
        </strong></span>
      </div>
      <ChecksTable checks={sh.checks ?? []} />
    </SectionCard>
  );
}

// ---------------------------------------------------------------------------
// Section 3 — Data Quality
// ---------------------------------------------------------------------------

function Section3DataQuality({ data }: { data: any }) {
  const dq = data?.data_quality ?? {};
  return (
    <SectionCard title="📊 Data Quality">
      <div className="flex flex-wrap gap-4 text-xs text-muted-foreground mb-2">
        <span>Score: <strong className="text-foreground">{dq.score?.toFixed(0) ?? "—"}</strong></span>
        <span>Records: <strong className="text-foreground">{dq.total_records ?? 0}</strong></span>
        <span className="text-green-400">✓ {dq.passed ?? 0}</span>
        <span className="text-yellow-400">⚠ {dq.warnings ?? 0}</span>
        <span className="text-red-400">✕ {dq.failures ?? 0}</span>
      </div>
      <ChecksTable checks={dq.checks ?? []} />
    </SectionCard>
  );
}

// ---------------------------------------------------------------------------
// Section 4 — Recovery
// ---------------------------------------------------------------------------

function Section4Recovery({ recovery }: { recovery: any }) {
  const health = recovery?.recovery_health ?? "UNKNOWN";
  const healthCol =
    health === "STRONG" ? "text-green-400" :
    health === "ADEQUATE" ? "text-yellow-400" : "text-red-400";
  return (
    <SectionCard title="🔁 Recovery Capability">
      <div className="flex flex-wrap gap-4 text-xs text-muted-foreground mb-2">
        <span>Score: <strong className="text-foreground">{recovery?.score?.toFixed(0) ?? "—"}</strong></span>
        <span>Health: <strong className={healthCol}>{health}</strong></span>
      </div>
      <ChecksTable checks={recovery?.checks ?? []} />
    </SectionCard>
  );
}

// ---------------------------------------------------------------------------
// Section 5 — API Health
// ---------------------------------------------------------------------------

function Section5APIHealth({ data }: { data: any }) {
  const api = data?.api_health ?? {};
  return (
    <SectionCard title="🔌 API Health">
      <div className="flex flex-wrap gap-4 text-xs text-muted-foreground mb-2">
        <span>Score: <strong className="text-foreground">{api.score?.toFixed(0) ?? "—"}</strong></span>
        <span>Error Rate: <strong className="text-foreground">{pct(api.error_rate)}</strong></span>
      </div>
      <ChecksTable checks={api.checks ?? []} />
    </SectionCard>
  );
}

// ---------------------------------------------------------------------------
// Section 6 — Broker Readiness
// ---------------------------------------------------------------------------

function Section6BrokerReadiness({ system }: { system: any }) {
  const broker = system?.broker_readiness ?? {};
  return (
    <SectionCard title="🏦 Broker Readiness">
      <div className="flex items-start gap-2 rounded-lg border border-amber-500/20 bg-amber-500/5 p-3 text-xs">
        <AlertTriangle className="h-3.5 w-3.5 shrink-0 mt-0.5 text-amber-400" />
        <span className="text-amber-300 font-medium">
          {broker.advisory ?? "Paper trading only. Live orders are never placed."}
        </span>
      </div>
      <div className="grid grid-cols-2 sm:grid-cols-3 gap-2 text-xs">
        {[
          ["Credentials Present", broker.credentials_present ? "Yes" : "No",
            broker.credentials_present ? "text-green-400" : "text-yellow-400"],
          ["Module Available",    broker.module_available ? "Yes" : "No",
            broker.module_available ? "text-green-400" : "text-yellow-400"],
          ["Paper Trading Only",  "Always", "text-green-400"],
          ["Live Orders",         "Never placed", "text-green-400"],
        ].map(([label, val, col]) => (
          <div key={label as string} className="flex flex-col gap-0.5 p-2.5 rounded-lg border border-border bg-card/50">
            <span className="text-[10px] uppercase tracking-wide text-muted-foreground">{label}</span>
            <span className={`text-sm font-semibold ${col}`}>{val}</span>
          </div>
        ))}
      </div>
      <p className="text-xs text-muted-foreground">{broker.detail}</p>
    </SectionCard>
  );
}

// ---------------------------------------------------------------------------
// Section 7 — Configuration
// ---------------------------------------------------------------------------

function Section7Config({ security }: { security: any }) {
  const cfg   = security?.configuration ?? {};
  const flags = cfg.feature_flags ?? {};
  return (
    <SectionCard title="⚙️ Configuration">
      <div className="flex flex-wrap gap-4 text-xs text-muted-foreground mb-2">
        <span>Score: <strong className="text-foreground">{cfg.score?.toFixed(0) ?? "—"}</strong></span>
        <span>Checksum: <code className="bg-border/40 px-1 rounded text-foreground">{cfg.config_checksum ?? "—"}</code></span>
      </div>

      {/* Feature flags */}
      <div>
        <p className="text-[10px] uppercase tracking-wide text-muted-foreground mb-2">Phase 6.x Feature Flags</p>
        <div className="flex flex-wrap gap-2">
          {Object.entries(flags).map(([k, v]: [string, any]) => (
            <span key={k}
              className={`inline-flex items-center rounded-full border px-2.5 py-1 text-[10px] font-medium gap-1
                ${v ? "bg-green-500/10 border-green-500/30 text-green-400"
                    : "bg-muted/30 border-border text-muted-foreground"}`}>
              <span className={`h-1.5 w-1.5 rounded-full ${v ? "bg-green-400" : "bg-muted-foreground/40"}`} />
              {k.replace(/_/g, " ")}
            </span>
          ))}
        </div>
      </div>
      <ChecksTable checks={cfg.checks ?? []} />
    </SectionCard>
  );
}

// ---------------------------------------------------------------------------
// Section 8 — Security
// ---------------------------------------------------------------------------

function Section8Security({ security }: { security: any }) {
  const sec = security?.security ?? {};
  const level = sec.security_level ?? "UNKNOWN";
  const levelCol = level === "STRONG" ? "text-green-400" : level === "ADEQUATE" ? "text-yellow-400" : "text-red-400";
  return (
    <SectionCard title="🔒 Security">
      <div className="flex flex-wrap gap-4 text-xs text-muted-foreground mb-2">
        <span>Score: <strong className="text-foreground">{sec.score?.toFixed(0) ?? "—"}</strong></span>
        <span>Level: <strong className={levelCol}>{level}</strong></span>
        <span>Critical Failures: <strong className={sec.critical_failures > 0 ? "text-red-400" : "text-green-400"}>
          {sec.critical_failures ?? 0}
        </strong></span>
      </div>
      <ChecksTable checks={sec.checks ?? []} />
    </SectionCard>
  );
}

// ---------------------------------------------------------------------------
// Section 9 — Go / No-Go Summary
// ---------------------------------------------------------------------------

function Section9GoNoGo({ summary }: { summary: any }) {
  const strengths    = summary?.strengths ?? [];
  const weaknesses   = summary?.weaknesses ?? [];
  const observations = summary?.observations ?? [];
  const blocking     = summary?.blocking_issues ?? [];
  const verdict      = summary?.verdict ?? "NOT READY";

  return (
    <SectionCard title="✅ Go / No-Go Summary">
      <VerdictBanner verdict={verdict} score={summary?.readiness_score ?? 0} />

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4 text-xs">
        {/* Strengths */}
        <div className="space-y-1.5">
          <p className="text-[10px] uppercase tracking-wide text-green-400 font-medium">Strengths</p>
          {strengths.length > 0
            ? strengths.map((s: string) => (
                <div key={s} className="flex items-center gap-1.5 text-muted-foreground">
                  <CheckCircle2 className="h-3 w-3 text-green-400 shrink-0" />
                  <span>{s.replace(/([A-Z])/g, " $1").trim()}</span>
                </div>
              ))
            : <span className="text-muted-foreground/50">—</span>
          }
        </div>

        {/* Observations */}
        <div className="space-y-1.5">
          <p className="text-[10px] uppercase tracking-wide text-yellow-400 font-medium">Observations</p>
          {observations.length > 0
            ? observations.map((s: string) => (
                <div key={s} className="flex items-center gap-1.5 text-muted-foreground">
                  <AlertTriangle className="h-3 w-3 text-yellow-400 shrink-0" />
                  <span>{s.replace(/([A-Z])/g, " $1").trim()}</span>
                </div>
              ))
            : <span className="text-muted-foreground/50">—</span>
          }
        </div>

        {/* Weaknesses */}
        <div className="space-y-1.5">
          <p className="text-[10px] uppercase tracking-wide text-red-400 font-medium">Weaknesses</p>
          {weaknesses.length > 0
            ? weaknesses.map((s: string) => (
                <div key={s} className="flex items-center gap-1.5 text-muted-foreground">
                  <XCircle className="h-3 w-3 text-red-400 shrink-0" />
                  <span>{s.replace(/([A-Z])/g, " $1").trim()}</span>
                </div>
              ))
            : <span className="text-muted-foreground/50">—</span>
          }
        </div>
      </div>

      {/* Blocking issues */}
      {blocking.length > 0 && (
        <div className="space-y-2">
          <p className="text-[10px] uppercase tracking-wide text-red-400 font-medium">Required Actions</p>
          {blocking.map((b: string, i: number) => (
            <div key={i} className="flex items-start gap-2 rounded-lg border border-red-500/20 bg-red-500/5 p-2.5 text-xs">
              <XCircle className="h-3.5 w-3.5 text-red-400 shrink-0 mt-0.5" />
              <span className="text-muted-foreground">{b}</span>
            </div>
          ))}
        </div>
      )}

      {/* Advisory-only reminder */}
      <div className="flex items-start gap-2 rounded-lg border border-dashed border-border bg-muted/10 p-3 text-xs text-muted-foreground">
        <Info className="h-3.5 w-3.5 shrink-0 mt-0.5" />
        <span>
          This assessment is <strong>advisory-only</strong>. Phase 6.5 never enables live trading,
          places orders, or modifies any trading engine, portfolio, strategies, or risk parameters.
        </span>
      </div>
    </SectionCard>
  );
}

// ---------------------------------------------------------------------------
// Section 10 — Future Integration Hooks
// ---------------------------------------------------------------------------

function Section10FutureHooks({ system }: { system: any }) {
  return (
    <SectionCard title="🔮 Future Integration Hooks">
      <div className="space-y-3">
        <div className="flex items-start gap-2 rounded-lg border border-dashed border-border bg-muted/10 p-3 text-xs text-muted-foreground">
          <Info className="h-3.5 w-3.5 shrink-0 mt-0.5" />
          <div className="space-y-2">
            <p><strong>CI/CD Integration</strong> — future-ready hook.</p>
            <p>
              When <code className="bg-border/40 px-1 rounded">CI_CD_READINESS_GATE=true</code> is set,
              the <code className="bg-border/40 px-1 rounded">/api/readiness/report</code> endpoint can
              be consumed by a deployment pipeline to gate production releases. The report includes
              a <code className="bg-border/40 px-1 rounded">deployment_checklist_stub</code> with
              the gate criteria.
            </p>
            <p><strong>Automated smoke testing hook:</strong> Phase 17 QA engine can be wired to
              trigger a full suite run from the readiness report — disabled by default.</p>
            <p><strong>Production monitoring:</strong> The readiness snapshot
              (<code className="bg-border/40 px-1 rounded">get_readiness_snapshot()</code>) is the
              stable downstream interface for any future production health monitoring system.</p>
          </div>
        </div>

        {/* Phase 6.x snapshot summary */}
        <div>
          <p className="text-[10px] uppercase tracking-wide text-muted-foreground mb-2">Phase 6.x Module Status</p>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
            {[
              ["6.1 Validation",      system?.feature_flags?.STRATEGY_OPTIMISATION_ENABLED],
              ["6.2 Strategy Opt.",   system?.feature_flags?.STRATEGY_OPTIMISATION_ENABLED],
              ["6.3 AI Opt.",         system?.feature_flags?.AI_OPTIMISATION_ENABLED],
              ["6.4 Risk Opt.",       system?.feature_flags?.RISK_OPTIMISATION_ENABLED],
              ["6.5 Readiness",       system?.feature_flags?.READINESS_VALIDATION_ENABLED],
            ].map(([label, enabled]) => (
              <div key={label as string}
                className={`flex items-center gap-2 rounded-lg border p-2.5 text-[11px]
                  ${enabled ? "border-green-500/20 bg-green-500/5" : "border-border bg-muted/10"}`}>
                <span className={`h-2 w-2 rounded-full shrink-0 ${enabled ? "bg-green-400" : "bg-muted-foreground/30"}`} />
                <span className={enabled ? "text-green-400" : "text-muted-foreground"}>{label}</span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </SectionCard>
  );
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

export default function LiveReadiness() {
  // Invalidate Data Quality + Summary the moment a paper trade is recorded.
  usePaperTradeInvalidation();

  const summary  = useSummary();
  const system   = useSystem();
  const data     = useData();
  const recovery = useRecovery();
  const security = useSecurity();

  const isLoading = summary.isLoading || system.isLoading;
  const summaryData: any  = summary.data;
  const systemData: any   = system.data;
  const dataData: any     = data.data;
  const recoveryData: any = recovery.data;
  const securityData: any = security.data;

  const isDisabled = summaryData?.status === "DISABLED";

  function refetchAll() {
    [summary, system, data, recovery, security].forEach(q => q.refetch());
  }

  function handleExportCSV() {
    window.open((import.meta.env.BASE_URL ?? "/").replace(/\/$/, "") + "/api/readiness/export/csv", "_blank");
  }
  function handleExportJSON() {
    window.open((import.meta.env.BASE_URL ?? "/").replace(/\/$/, "") + "/api/readiness/export/json", "_blank");
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center gap-3 justify-between">
        <div className="flex items-center gap-3">
          <Rocket className="h-6 w-6 text-primary" />
          <div>
            <h1 className="text-xl font-bold">Live Readiness</h1>
            <p className="text-xs text-muted-foreground">Operational Validation Framework</p>
          </div>
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          <Badge variant="outline" className="text-[10px] font-bold text-amber-400 border-amber-500/30 bg-amber-500/10">
            ADVISORY ONLY — LIVE TRADING NEVER ENABLED
          </Badge>
          <Button variant="outline" size="sm" className="h-7 gap-1.5 text-xs" onClick={refetchAll} disabled={isLoading}>
            <RefreshCw className={`h-3.5 w-3.5 ${isLoading ? "animate-spin" : ""}`} />
            Refresh
          </Button>
          <Button variant="outline" size="sm" className="h-7 gap-1.5 text-xs" onClick={handleExportCSV}>
            <Download className="h-3.5 w-3.5" />
            CSV
          </Button>
          <Button variant="outline" size="sm" className="h-7 gap-1.5 text-xs" onClick={handleExportJSON}>
            <Download className="h-3.5 w-3.5" />
            JSON
          </Button>
        </div>
      </div>

      {isLoading && (
        <div className="rounded-xl border border-border bg-card/50 p-8 text-center">
          <RefreshCw className="h-6 w-6 mx-auto text-muted-foreground animate-spin mb-2" />
          <p className="text-sm text-muted-foreground">Running readiness validation…</p>
        </div>
      )}

      {!isLoading && isDisabled && <DisabledState />}

      {!isLoading && !isDisabled && (
        <div className="space-y-5">
          <Section1Overall    summary={summaryData} />

          <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
            <Section2SystemHealth  system={systemData} />
            <Section3DataQuality   data={dataData} />
          </div>

          <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
            <Section4Recovery      recovery={recoveryData} />
            <Section5APIHealth     data={dataData} />
          </div>

          <Section6BrokerReadiness system={systemData} />

          <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
            <Section7Config    security={securityData} />
            <Section8Security  security={securityData} />
          </div>

          <Section9GoNoGo summary={summaryData} />
          <Section10FutureHooks system={systemData} />
        </div>
      )}
    </div>
  );
}
