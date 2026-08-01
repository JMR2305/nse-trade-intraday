import { useQuery } from "@tanstack/react-query";
import { apiJson } from "@/lib/api";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Badge } from "@/components/ui/badge";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { useState } from "react";
import {
  Rocket, ShieldCheck, Database, Server, HardDrive, Activity,
  AlertTriangle, CheckCircle2, Download, RefreshCw, Lightbulb,
  Clock, RotateCcw, Layers, BookOpen,
} from "lucide-react";

// ── query helper ───────────────────────────────────────────────────────────────
const q = (path: string, ms = 30_000) => ({
  queryKey: ["deploy", path],
  queryFn:  () => apiJson("deployment/" + path),
  refetchInterval: ms,
  retry: 1,
});

// ── shared sub-components ─────────────────────────────────────────────────────
function DisabledState() {
  return (
    <div className="flex flex-col items-center justify-center py-20 text-muted-foreground gap-3">
      <Rocket className="w-12 h-12 opacity-30" />
      <p>Set <code className="text-teal-400">DEPLOYMENT_CENTER_ENABLED=true</code> to enable the Deployment &amp; DR Centre.</p>
    </div>
  );
}

function ScoreChip({ score, grade }: { score: number; grade: string }) {
  const color =
    grade === "A+" || grade === "A" ? "bg-emerald-600" :
    grade === "B" ? "bg-blue-600" :
    grade === "C" ? "bg-amber-500" : "bg-red-600";
  return (
    <div className={`inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-white text-sm font-semibold ${color}`}>
      {score.toFixed(1)} <span className="opacity-80">/ 100</span>
      <span className="ml-1 bg-white/20 px-1.5 py-0.5 rounded text-xs">{grade}</span>
    </div>
  );
}

function TrendBadge({ trend }: { trend: string }) {
  const map: Record<string, string> = {
    IMPROVING: "bg-emerald-600",
    STABLE:    "bg-blue-600",
    DEGRADING: "bg-red-600",
  };
  return (
    <span className={`text-xs px-2 py-0.5 rounded text-white ${map[trend] ?? "bg-gray-500"}`}>
      {trend}
    </span>
  );
}

function StatusDot({ status }: { status: string }) {
  const map: Record<string, string> = {
    READY:     "bg-emerald-500",
    DEGRADED:  "bg-amber-400",
    NOT_READY: "bg-red-500",
    UNKNOWN:   "bg-gray-400",
    DISABLED:  "bg-gray-500",
    RUNNING:   "bg-emerald-500",
    AVAILABLE: "bg-emerald-500",
  };
  return <span className={`inline-block w-2 h-2 rounded-full ${map[status] ?? "bg-gray-400"}`} />;
}

function StatusBadge({ status }: { status: string }) {
  const map: Record<string, string> = {
    READY:      "border-emerald-500/40 text-emerald-300",
    DEGRADED:   "border-amber-500/40 text-amber-300",
    NOT_READY:  "border-red-500/40 text-red-300",
    UNKNOWN:    "border-gray-500/40 text-gray-300",
    ACCEPTABLE: "border-emerald-500/40 text-emerald-300",
    NONE:       "border-red-500/40 text-red-300",
  };
  return (
    <Badge variant="outline" className={`gap-1.5 ${map[status] ?? "border-gray-500/40 text-gray-300"}`}>
      <StatusDot status={status} />{status}
    </Badge>
  );
}

function SeverityBadge({ sev }: { sev: string }) {
  const map: Record<string, string> = {
    CRITICAL: "bg-red-500/20 text-red-300 border-red-500/30",
    WARNING:  "bg-amber-500/20 text-amber-300 border-amber-500/30",
    INFO:     "bg-slate-500/20 text-slate-300 border-slate-500/30",
  };
  return (
    <span className={`text-xs px-2 py-0.5 rounded border font-medium ${map[sev] ?? map["INFO"]}`}>
      {sev}
    </span>
  );
}

function DomainCard({ label, score, status }: { label: string; score: number; status: string }) {
  const scoreColor = score >= 80 ? "text-emerald-400" : score >= 60 ? "text-amber-400" : "text-red-400";
  const barColor   = score >= 80 ? "bg-emerald-500"   : score >= 60 ? "bg-amber-400"   : "bg-red-500";
  return (
    <div className="bg-card rounded-lg border border-border p-4 space-y-2">
      <div className="flex items-center justify-between">
        <span className="text-sm text-muted-foreground">{label}</span>
        <StatusBadge status={status} />
      </div>
      <div className="flex items-center gap-3">
        <span className={`text-2xl font-bold ${scoreColor}`}>{score.toFixed(1)}</span>
        <div className="flex-1 h-1.5 rounded-full bg-muted">
          <div className={`h-1.5 rounded-full ${barColor}`} style={{ width: `${Math.min(100, score)}%` }} />
        </div>
      </div>
    </div>
  );
}

function CheckRow({ check }: { check: any }) {
  const name   = check.name ?? check.check ?? "Check";
  const ok     = check.ok !== undefined ? check.ok : check.status === "READY";
  const isInfo = check.status === "INFO";
  return (
    <div className="flex items-start gap-3 py-2.5 border-b border-border/50 last:border-0">
      <span className={`mt-0.5 text-sm font-bold ${isInfo ? "text-muted-foreground" : ok ? "text-emerald-400" : "text-red-400"}`}>
        {isInfo ? "ℹ" : ok ? "✓" : "✗"}
      </span>
      <div className="flex-1 min-w-0">
        <div className="text-sm font-medium">{name}</div>
        {check.detail && <div className="text-xs text-muted-foreground mt-0.5">{check.detail}</div>}
      </div>
    </div>
  );
}

function ChecklistItem({ step }: { step: string }) {
  return (
    <li className="text-sm text-muted-foreground flex items-start gap-2">
      <span className="text-teal-500 mt-0.5 flex-shrink-0">›</span>
      <span>{step}</span>
    </li>
  );
}

// ── Overview tab ───────────────────────────────────────────────────────────────
function OverviewTab() {
  const { data: d, isLoading } = useQuery({ ...q("summary", 20_000) });
  if (isLoading) return <p className="p-6 text-muted-foreground text-sm">Loading…</p>;
  if ((d as any)?.available === false) return <DisabledState />;
  const r = d as any;
  return (
    <div className="space-y-6 p-1">
      <div className="flex flex-wrap items-center gap-4">
        {r?.dr_score != null && <ScoreChip score={r.dr_score} grade={r.grade} />}
        {r?.trend && <TrendBadge trend={r.trend} />}
        {r?.deployment_status && <StatusBadge status={r.deployment_status} />}
        <span className="text-xs text-muted-foreground ml-auto">
          {r?.generated_at?.slice(0, 19)?.replace("T", " ")} UTC
        </span>
      </div>

      {(r?.critical_issues > 0 || r?.warning_issues > 0) && (
        <Alert className="border-amber-500/40 bg-amber-500/5">
          <AlertTriangle className="w-4 h-4 text-amber-500" />
          <AlertDescription className="text-sm text-amber-200">
            {r.critical_issues > 0 && <span className="text-red-300 mr-3">⚠ {r.critical_issues} critical issue{r.critical_issues !== 1 ? "s" : ""}</span>}
            {r.warning_issues  > 0 && <span className="text-amber-300">⚠ {r.warning_issues} warning{r.warning_issues !== 1 ? "s" : ""}</span>}
          </AlertDescription>
        </Alert>
      )}

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
        <DomainCard label="Deployment Readiness" score={r?.readiness_score  ?? 0} status={r?.deployment_status ?? "UNKNOWN"} />
        <DomainCard label="Infrastructure"        score={r?.infra_score      ?? 0} status={r?.infra_status     ?? "UNKNOWN"} />
        <DomainCard label="Backup Validation"     score={r?.backup_score     ?? 0} status={r?.backup_status    ?? "UNKNOWN"} />
        <DomainCard label="Configuration"         score={r?.config_score     ?? 0} status={r?.config_status    ?? "UNKNOWN"} />
        <DomainCard label="Business Continuity"   score={r?.continuity_score ?? 0} status={r?.continuity_status ?? "UNKNOWN"} />
      </div>

      <p className="text-xs text-muted-foreground">
        DR Score = Readiness 25% · Infrastructure 25% · Backup 20% · Config 15% · Continuity 15%
      </p>
    </div>
  );
}

// ── Deployment tab ─────────────────────────────────────────────────────────────
function DeploymentTab() {
  const { data: d, isLoading } = useQuery({ ...q("readiness") });
  if (isLoading) return <p className="p-6 text-muted-foreground text-sm">Loading…</p>;
  if ((d as any)?.available === false) return <DisabledState />;
  const r = d as any;
  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center gap-3">
        {r?.readiness_score != null && <ScoreChip score={r.readiness_score} grade={r.grade} />}
        <StatusBadge status={r?.readiness_status ?? "UNKNOWN"} />
      </div>

      <div className="bg-card rounded-lg border border-border p-4">
        <p className="text-sm font-medium mb-3">Readiness Checks</p>
        <div>
          {(r?.checks ?? []).map((c: any, i: number) => <CheckRow key={i} check={c} />)}
        </div>
      </div>

      {(r?.env_vars ?? []).length > 0 && (
        <div className="bg-card rounded-lg border border-border p-4">
          <p className="text-sm font-medium mb-3">Environment Variables</p>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs text-muted-foreground border-b border-border">
                  <th className="pb-2 pr-4">Variable</th>
                  <th className="pb-2 pr-4">Status</th>
                  <th className="pb-2 pr-4">Required</th>
                  <th className="pb-2">Description</th>
                </tr>
              </thead>
              <tbody>
                {r.env_vars.map((ev: any, i: number) => (
                  <tr key={i} className="border-b border-border/30">
                    <td className="py-2 pr-4 font-mono text-xs">{ev.name}</td>
                    <td className="py-2 pr-4">
                      <span className={`text-xs font-medium ${ev.present ? "text-emerald-400" : "text-red-400"}`}>
                        {ev.present ? "Present" : "Missing"}
                      </span>
                    </td>
                    <td className="py-2 pr-4 text-xs">
                      {ev.critical
                        ? <span className="text-red-400">Critical</span>
                        : <span className="text-muted-foreground">Optional</span>}
                    </td>
                    <td className="py-2 text-xs text-muted-foreground">{ev.description}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}

// ── Config tab ─────────────────────────────────────────────────────────────────
function ConfigTab() {
  const { data: d, isLoading } = useQuery({ ...q("config") });
  if (isLoading) return <p className="p-6 text-muted-foreground text-sm">Loading…</p>;
  if ((d as any)?.available === false) return <DisabledState />;
  const r = d as any;
  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center gap-3">
        {r?.config_score != null && <ScoreChip score={r.config_score} grade={r.grade} />}
        <span className="text-xs text-muted-foreground">
          {r?.critical_issues ?? 0} critical · {r?.warning_issues ?? 0} warnings
        </span>
        <span className="text-xs text-muted-foreground ml-auto">NODE_ENV: <b className="text-foreground">{r?.node_env}</b></span>
      </div>

      <div className="bg-card rounded-lg border border-border p-4">
        <p className="text-sm font-medium mb-3">Feature Flags</p>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
          {(r?.feature_flags ?? []).map((f: any, i: number) => (
            <div key={i} className="flex items-center justify-between px-3 py-2 rounded bg-muted/40">
              <span className="text-xs font-mono text-muted-foreground">{f.flag}</span>
              <span className={`text-xs font-medium ${f.active ? "text-emerald-400" : "text-muted-foreground"}`}>
                {f.active ? "active" : "off"}
              </span>
            </div>
          ))}
        </div>
      </div>

      {(r?.issues ?? []).length > 0 && (
        <div className="bg-card rounded-lg border border-border p-4">
          <p className="text-sm font-medium mb-3">Issues</p>
          <div className="space-y-2">
            {r.issues.map((issue: any, i: number) => (
              <div key={i} className="flex items-center gap-3 py-1.5 border-b border-border/30 last:border-0">
                <SeverityBadge sev={issue.severity} />
                <span className="text-xs font-mono flex-1">{issue.name}</span>
                <span className="text-xs text-muted-foreground">{issue.detail}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

// ── Backups tab ────────────────────────────────────────────────────────────────
function BackupsTab() {
  const { data: d, isLoading } = useQuery({ ...q("backups") });
  if (isLoading) return <p className="p-6 text-muted-foreground text-sm">Loading…</p>;
  if ((d as any)?.available === false) return <DisabledState />;
  const r = d as any;
  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center gap-3">
        {r?.backup_score != null && <ScoreChip score={r.backup_score} grade={r.grade ?? "?"} />}
        <StatusBadge status={r?.backup_status ?? "UNKNOWN"} />
      </div>

      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-3">
        {[
          ["Backup Age",   r?.backup_age_hours != null ? `${r.backup_age_hours.toFixed(1)}h` : "—"],
          ["Backup Count", r?.backup_count ?? 0],
          ["Type",         r?.backup_type ?? "—"],
          ["Integrity",    r?.integrity_status ?? "—"],
          ["Retention",    r?.retention_status ?? "—"],
          ["Location",     r?.backup_location ?? "—"],
        ].map(([label, val]) => (
          <div key={label} className="bg-card rounded-lg border border-border p-3">
            <p className="text-xs text-muted-foreground mb-1">{label}</p>
            <p className="text-sm font-medium truncate">{val}</p>
          </div>
        ))}
      </div>

      {r?.last_backup_time && (
        <p className="text-xs text-muted-foreground">
          Last backup: {r.last_backup_time.slice(0, 19).replace("T", " ")} UTC
        </p>
      )}

      {r?.advisory_note && (
        <Alert className="border-blue-500/30 bg-blue-500/5">
          <AlertDescription className="text-xs text-blue-200">{r.advisory_note}</AlertDescription>
        </Alert>
      )}
    </div>
  );
}

// ── Restore tab ────────────────────────────────────────────────────────────────
function RestoreTab() {
  const { data: d, isLoading } = useQuery({ ...q("restore") });
  if (isLoading) return <p className="p-6 text-muted-foreground text-sm">Loading…</p>;
  if ((d as any)?.available === false) return <DisabledState />;
  const r = d as any;
  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center gap-3">
        {r?.restore_score != null && <ScoreChip score={r.restore_score} grade={r.grade ?? "?"} />}
        <span className="text-xs text-muted-foreground">
          Est. restore time: <b className="text-foreground">{r?.estimated_restore_minutes} min</b>
        </span>
      </div>

      <div className="bg-card rounded-lg border border-border p-4">
        <p className="text-sm font-medium mb-3">Restore Checks</p>
        <div>{(r?.checks ?? []).map((c: any, i: number) => <CheckRow key={i} check={c} />)}</div>
      </div>

      {(r?.recovery_checklist ?? []).length > 0 && (
        <div className="bg-card rounded-lg border border-border p-4">
          <p className="text-sm font-medium mb-3">Recovery Checklist</p>
          <ol className="space-y-2">
            {r.recovery_checklist.map((step: string, i: number) => <ChecklistItem key={i} step={step} />)}
          </ol>
        </div>
      )}
    </div>
  );
}

// ── Rollback tab ───────────────────────────────────────────────────────────────
function RollbackTab() {
  const { data: d, isLoading } = useQuery({ ...q("rollback") });
  if (isLoading) return <p className="p-6 text-muted-foreground text-sm">Loading…</p>;
  if ((d as any)?.available === false) return <DisabledState />;
  const r = d as any;
  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center gap-3">
        {r?.rollback_score != null && <ScoreChip score={r.rollback_score} grade={r.grade ?? "?"} />}
        <span className="text-xs text-muted-foreground">
          Est. time: <b className="text-foreground">{r?.estimated_rollback_minutes} min</b>
        </span>
        <span className="text-xs text-muted-foreground">
          Scan history: <b className="text-foreground">{r?.scan_history_count}</b>
        </span>
      </div>

      <div className="bg-card rounded-lg border border-border p-4">
        <p className="text-sm font-medium mb-3">Rollback Checks</p>
        <div>{(r?.checks ?? []).map((c: any, i: number) => <CheckRow key={i} check={c} />)}</div>
      </div>

      {(r?.rollback_checklist ?? []).length > 0 && (
        <div className="bg-card rounded-lg border border-border p-4">
          <p className="text-sm font-medium mb-3">Rollback Checklist</p>
          <ol className="space-y-2">
            {r.rollback_checklist.map((step: string, i: number) => <ChecklistItem key={i} step={step} />)}
          </ol>
        </div>
      )}
    </div>
  );
}

// ── Infrastructure tab ─────────────────────────────────────────────────────────
function InfrastructureTab() {
  const { data: d, isLoading } = useQuery({ ...q("infrastructure") });
  if (isLoading) return <p className="p-6 text-muted-foreground text-sm">Loading…</p>;
  if ((d as any)?.available === false) return <DisabledState />;
  const r = d as any;
  return (
    <div className="space-y-5">
      <div className="flex items-center gap-3">
        {r?.infra_score != null && <ScoreChip score={r.infra_score} grade={r.grade ?? "?"} />}
        <span className="text-xs text-muted-foreground">Python {r?.python_version}</span>
      </div>

      <div className="bg-card rounded-lg border border-border p-4">
        <p className="text-sm font-medium mb-3">Components</p>
        <div className="divide-y divide-border/50">
          {(r?.components ?? []).map((comp: any, i: number) => (
            <div key={i} className="flex items-center justify-between py-2.5">
              <span className="text-sm">{comp.component}</span>
              <div className="flex items-center gap-3">
                <span className="text-xs text-muted-foreground">{comp.detail}</span>
                <StatusBadge status={comp.status} />
              </div>
            </div>
          ))}
        </div>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
        <div className="bg-card rounded-lg border border-border p-4">
          <p className="text-xs text-muted-foreground mb-2">Memory Usage</p>
          <p className="text-2xl font-bold">{r?.memory?.usage_pct ?? "—"}%</p>
          <p className="text-xs text-muted-foreground mt-1">
            {r?.memory?.used_mb} / {r?.memory?.total_mb} MB
          </p>
        </div>
        <div className="bg-card rounded-lg border border-border p-4">
          <p className="text-xs text-muted-foreground mb-2">CPU Load (1m)</p>
          <p className="text-2xl font-bold">{r?.cpu?.load_1m ?? "—"}</p>
          <p className="text-xs text-muted-foreground mt-1">{r?.cpu?.count} cores</p>
        </div>
        <div className="bg-card rounded-lg border border-border p-4">
          <p className="text-xs text-muted-foreground mb-2">Disk Usage</p>
          <p className="text-2xl font-bold">{r?.disk?.usage_pct ?? "—"}%</p>
          <p className="text-xs text-muted-foreground mt-1">{r?.disk?.free_gb} GB free</p>
        </div>
      </div>
    </div>
  );
}

// ── Business Continuity tab ────────────────────────────────────────────────────
function ContinuityTab() {
  const { data: d, isLoading } = useQuery({ ...q("continuity") });
  if (isLoading) return <p className="p-6 text-muted-foreground text-sm">Loading…</p>;
  if ((d as any)?.available === false) return <DisabledState />;
  const r = d as any;
  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center gap-3">
        {r?.continuity_score != null && <ScoreChip score={r.continuity_score} grade={r.grade ?? "?"} />}
        <Badge variant="outline" className="gap-1">
          <StatusDot status={r?.application_availability === "AVAILABLE" ? "READY" : "DEGRADED"} />
          {r?.application_availability}
        </Badge>
        <span className="text-xs text-muted-foreground">
          Tier-1: <b className="text-foreground">{r?.tier1_services_up}/{r?.tier1_services_total}</b>
        </span>
      </div>

      {(r?.single_points_of_failure ?? []).length > 0 && (
        <Alert className="border-red-500/40 bg-red-500/5">
          <AlertTriangle className="w-4 h-4 text-red-500" />
          <AlertDescription className="text-sm text-red-200">
            <b>Single points of failure:</b> {r.single_points_of_failure.join(", ")}
          </AlertDescription>
        </Alert>
      )}

      <div className="bg-card rounded-lg border border-border p-4">
        <p className="text-sm font-medium mb-3">Critical Services</p>
        <div className="divide-y divide-border/50">
          {(r?.services ?? []).map((svc: any, i: number) => (
            <div key={i} className="flex items-center justify-between py-2.5">
              <div className="flex items-center gap-2">
                <span className="text-sm">{svc.service}</span>
                <span className="text-xs text-muted-foreground bg-muted px-1.5 py-0.5 rounded">
                  Tier {svc.tier}
                </span>
              </div>
              <StatusBadge status={svc.status} />
            </div>
          ))}
        </div>
      </div>

      <div className="flex gap-4 text-sm text-muted-foreground">
        <span>Redundancy: <b className="text-foreground">{r?.redundancy_status}</b></span>
      </div>
    </div>
  );
}

// ── Recommendations tab ────────────────────────────────────────────────────────
function RecommendationsTab() {
  const { data: d, isLoading } = useQuery({ ...q("recommendations") });
  if (isLoading) return <p className="p-6 text-muted-foreground text-sm">Loading…</p>;
  if ((d as any)?.available === false) return <DisabledState />;
  const r = d as any;
  return (
    <div className="space-y-4">
      <div className="flex gap-4 text-sm">
        <span className="text-red-400 font-medium">⚠ {r?.critical_count ?? 0} critical</span>
        <span className="text-amber-400 font-medium">⚠ {r?.warning_count ?? 0} warnings</span>
        <span className="text-muted-foreground">ℹ {r?.info_count ?? 0} info</span>
      </div>
      <div className="space-y-3">
        {(r?.recommendations ?? []).map((rec: any, i: number) => (
          <div key={i} className="bg-card rounded-lg border border-border p-4">
            <div className="flex items-center gap-3 mb-2">
              <SeverityBadge sev={rec.severity} />
              <span className="text-xs text-muted-foreground bg-muted px-2 py-0.5 rounded">
                {rec.category}
              </span>
            </div>
            <p className="text-sm mb-2">{rec.message}</p>
            <p className="text-xs text-teal-400">→ {rec.action}</p>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Export tab ─────────────────────────────────────────────────────────────────
function ExportTab() {
  const [busy, setBusy]     = useState(false);
  const [status, setStatus] = useState("");

  const base = import.meta.env.BASE_URL.replace(/\/$/, "");

  async function download(fmt: "json" | "csv") {
    setBusy(true);
    setStatus("");
    try {
      const resp = await fetch(`${base}/api/deployment/export?format=${fmt}`);
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const blob = await resp.blob();
      const url  = URL.createObjectURL(blob);
      const a    = document.createElement("a");
      a.href = url; a.download = `deployment_export.${fmt}`; a.click();
      URL.revokeObjectURL(url);
      setStatus(`${fmt.toUpperCase()} downloaded.`);
    } catch (e: any) {
      setStatus(`Export failed: ${e.message}`);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-5">
      <div className="bg-card rounded-lg border border-border p-5">
        <p className="text-sm font-medium mb-1">Export Deployment &amp; DR Report</p>
        <p className="text-xs text-muted-foreground mb-4">
          Advisory-only snapshot. Never modifies deployments or infrastructure.
        </p>
        <div className="flex flex-wrap gap-3">
          <button
            onClick={() => download("json")}
            disabled={busy}
            className="flex items-center gap-2 px-4 py-2 rounded-lg bg-teal-600 hover:bg-teal-500 text-white text-sm font-medium disabled:opacity-50 transition-colors"
          >
            <Download className="w-4 h-4" /> Download JSON
          </button>
          <button
            onClick={() => download("csv")}
            disabled={busy}
            className="flex items-center gap-2 px-4 py-2 rounded-lg bg-muted hover:bg-muted/80 text-sm font-medium disabled:opacity-50 transition-colors"
          >
            <Download className="w-4 h-4" /> Download CSV
          </button>
        </div>
        {status && <p className="mt-3 text-sm text-muted-foreground">{status}</p>}
      </div>

      <div className="text-xs text-muted-foreground space-y-1 bg-muted/20 rounded-lg p-4 border border-border/40">
        <p>• <b>JSON</b>: full DR snapshot including all domain assessments and recommendations.</p>
        <p>• <b>CSV</b>: summary metrics table for spreadsheet analysis.</p>
        <p>• Future: PDF export (Phase 8.9+ roadmap).</p>
        <p className="text-teal-600 pt-1">Advisory-only · Read-only · Never executes recovery automatically.</p>
      </div>
    </div>
  );
}

// ── main page ──────────────────────────────────────────────────────────────────
export default function DeploymentCenter() {
  return (
    <div className="max-w-7xl mx-auto px-4 py-8 space-y-6">

      {/* Header */}
      <div className="flex items-start gap-4">
        <div className="p-2.5 rounded-xl bg-teal-500/10 border border-teal-500/20">
          <Rocket className="w-7 h-7 text-teal-400" />
        </div>
        <div>
          <h1 className="text-2xl font-bold">Deployment &amp; DR Centre</h1>
          <p className="text-muted-foreground text-sm mt-0.5">
            Phase 8.8 · Read-only deployment readiness, backup validation &amp; disaster recovery framework
          </p>
        </div>
      </div>

      {/* Advisory banner */}
      <Alert className="border-teal-500/30 bg-teal-500/5">
        <ShieldCheck className="w-4 h-4 text-teal-400" />
        <AlertDescription className="text-sm text-teal-200">
          <span className="font-semibold">READ-ONLY · ADVISORY-ONLY</span> — validates deployment readiness, backup integrity,
          rollback capability and business continuity. Never modifies deployments, restores backups,
          rolls back automatically, or changes infrastructure.
        </AlertDescription>
      </Alert>

      {/* Tabs */}
      <Tabs defaultValue="overview">
        <TabsList className="flex flex-wrap h-auto gap-1 p-1">
          {[
            ["overview",      "Overview"],
            ["deployment",    "Deployment"],
            ["config",        "Configuration"],
            ["backups",       "Backups"],
            ["restore",       "Restore"],
            ["rollback",      "Rollback"],
            ["infra",         "Infrastructure"],
            ["continuity",    "Business Continuity"],
            ["recs",          "Recommendations"],
            ["export",        "Export"],
          ].map(([val, label]) => (
            <TabsTrigger key={val} value={val} className="text-xs">{label}</TabsTrigger>
          ))}
        </TabsList>

        <TabsContent value="overview">     <OverviewTab /></TabsContent>
        <TabsContent value="deployment">   <DeploymentTab /></TabsContent>
        <TabsContent value="config">       <ConfigTab /></TabsContent>
        <TabsContent value="backups">      <BackupsTab /></TabsContent>
        <TabsContent value="restore">      <RestoreTab /></TabsContent>
        <TabsContent value="rollback">     <RollbackTab /></TabsContent>
        <TabsContent value="infra">        <InfrastructureTab /></TabsContent>
        <TabsContent value="continuity">   <ContinuityTab /></TabsContent>
        <TabsContent value="recs">         <RecommendationsTab /></TabsContent>
        <TabsContent value="export">       <ExportTab /></TabsContent>
      </Tabs>
    </div>
  );
}
