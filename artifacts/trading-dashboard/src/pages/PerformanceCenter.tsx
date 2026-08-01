import { useQuery } from "@tanstack/react-query";
import { apiJson } from "@/lib/api";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Badge } from "@/components/ui/badge";
import { Alert, AlertDescription } from "@/components/ui/alert";
import {
  Zap, Database, BarChart2, Clock, Cpu, Monitor, Activity,
  TrendingUp, Lightbulb, Scale, Download, AlertTriangle, CheckCircle2,
} from "lucide-react";

const q = (path: string, ms = 30_000) => ({
  queryKey: ["perf", path],
  queryFn: () => apiJson("performance/" + path),
  refetchInterval: ms,
  retry: 1,
});

function DisabledState({ module }: { module: string }) {
  return (
    <div className="flex flex-col items-center justify-center py-20 text-muted-foreground gap-3">
      <Zap className="w-12 h-12 opacity-30" />
      <p>Set PERFORMANCE_CENTER_ENABLED=true to enable the {module}.</p>
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

function MetricRow({ label, value, unit = "", note }: { label: string; value: any; unit?: string; note?: string }) {
  return (
    <div className="flex items-center justify-between py-2 border-b border-border/50 last:border-0">
      <span className="text-muted-foreground text-sm">{label}</span>
      <span className="font-mono text-sm font-medium">
        {value == null ? "—" : `${value}${unit}`}
        {note && <span className="text-xs text-muted-foreground ml-2">({note})</span>}
      </span>
    </div>
  );
}

function StatusDot({ status }: { status: string }) {
  const map: Record<string, string> = {
    HEALTHY:  "bg-emerald-500",
    DEGRADED: "bg-amber-400",
    DOWN:     "bg-red-500",
    UNKNOWN:  "bg-gray-400",
  };
  return <span className={`inline-block w-2 h-2 rounded-full ${map[status] ?? "bg-gray-400"}`} />;
}

// ── Overview tab ──────────────────────────────────────────────────────────────
function OverviewTab() {
  const { data: d, isLoading } = useQuery({ ...q("summary", 20_000) });
  if (isLoading) return <p className="p-6 text-muted-foreground text-sm">Loading…</p>;
  if ((d as any)?.status === "DISABLED") return <DisabledState module="Performance Centre" />;
  const r = d as any;
  const scores = r?.component_scores ?? {};
  return (
    <div className="space-y-6 p-1">
      <div className="flex flex-wrap items-center gap-4">
        {r?.performance_score != null && (
          <ScoreChip score={r.performance_score} grade={r.grade} />
        )}
        {r?.trend && <TrendBadge trend={r.trend} />}
        {r?.status && (
          <Badge variant="outline" className="gap-1.5">
            <StatusDot status={r.status} /> {r.status}
          </Badge>
        )}
      </div>

      {r?.top_bottlenecks?.length > 0 && (
        <Alert className="border-amber-500/40 bg-amber-500/5">
          <AlertTriangle className="w-4 h-4 text-amber-500" />
          <AlertDescription className="text-sm text-amber-200">
            {r.top_bottlenecks.map((b: string, i: number) => <div key={i}>{b}</div>)}
          </AlertDescription>
        </Alert>
      )}

      <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
        {Object.entries(scores).map(([key, val]: [string, any]) => (
          <div key={key} className="bg-card rounded-lg border border-border p-3">
            <p className="text-xs text-muted-foreground capitalize mb-1">{key}</p>
            <p className="text-lg font-semibold">{val?.toFixed(1) ?? "—"}</p>
          </div>
        ))}
      </div>

      <div className="text-xs text-muted-foreground">
        {r?.obs_score != null && <>Observability score: {r.obs_score} · </>}
        {r?.obs_grade && <>Grade: {r.obs_grade}</>}
      </div>
    </div>
  );
}

// ── API tab ───────────────────────────────────────────────────────────────────
function ApiTab() {
  const { data: d, isLoading } = useQuery({ ...q("api", 20_000) });
  if (isLoading) return <p className="p-6 text-muted-foreground text-sm">Loading…</p>;
  if ((d as any)?.status === "DISABLED") return <DisabledState module="Performance Centre" />;
  const r = d as any;
  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3">
        {r?.performance_score != null && <ScoreChip score={r.performance_score} grade={r.grade} />}
        <Badge variant="outline" className="gap-1"><StatusDot status={r?.status ?? "UNKNOWN"} />{r?.status}</Badge>
      </div>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <div className="bg-card rounded-lg border p-3">
          <p className="text-xs text-muted-foreground">Requests</p>
          <p className="text-xl font-semibold">{r?.request_count ?? 0}</p>
        </div>
        <div className="bg-card rounded-lg border p-3">
          <p className="text-xs text-muted-foreground">Avg Latency</p>
          <p className="text-xl font-semibold">{r?.avg_latency_ms ?? 0} ms</p>
        </div>
        <div className="bg-card rounded-lg border p-3">
          <p className="text-xs text-muted-foreground">P95 Latency</p>
          <p className="text-xl font-semibold">{r?.p95_latency_ms ?? 0} ms</p>
        </div>
        <div className="bg-card rounded-lg border p-3">
          <p className="text-xs text-muted-foreground">Error Rate</p>
          <p className="text-xl font-semibold">{r?.error_rate_pct ?? 0}%</p>
        </div>
      </div>
      {r?.slow_endpoints?.length > 0 && (
        <div>
          <p className="text-sm font-medium mb-2">Slow Endpoints</p>
          <div className="space-y-1">
            {r.slow_endpoints.map((ep: any, i: number) => (
              <div key={i} className="flex justify-between text-sm bg-card border rounded px-3 py-2">
                <span className="font-mono text-xs truncate max-w-[50%]">{ep.endpoint}</span>
                <span className="text-amber-400">{ep.avg_latency_ms} ms</span>
              </div>
            ))}
          </div>
        </div>
      )}
      {r?.note && <p className="text-xs text-muted-foreground">{r.note}</p>}
    </div>
  );
}

// ── Database tab ──────────────────────────────────────────────────────────────
function DatabaseTab() {
  const { data: d, isLoading } = useQuery({ ...q("database", 30_000) });
  if (isLoading) return <p className="p-6 text-muted-foreground text-sm">Loading…</p>;
  if ((d as any)?.status === "DISABLED") return <DisabledState module="Performance Centre" />;
  const r = d as any;
  const conn = r?.connection ?? {};
  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3">
        {r?.performance_score != null && <ScoreChip score={r.performance_score} grade={r.grade} />}
        <Badge variant="outline" className="gap-1"><StatusDot status={r?.status ?? "UNKNOWN"} />{r?.status}</Badge>
      </div>
      <div className="bg-card rounded-lg border p-4 space-y-1">
        <MetricRow label="Connected"     value={conn.connected ? "Yes" : "No"} />
        <MetricRow label="Latency"       value={conn.latency_ms}   unit=" ms" />
        <MetricRow label="URL configured" value={conn.url_set ? "Yes" : "No"} />
        <MetricRow label="Health Score"  value={r?.health_score}              />
        <MetricRow label="Slow Query Threshold" value={r?.targets?.slow_query_ms} unit=" ms" />
      </div>
      {conn.error && (
        <Alert className="border-red-500/40 bg-red-500/5">
          <AlertTriangle className="w-4 h-4 text-red-400" />
          <AlertDescription className="text-sm text-red-300">{conn.error}</AlertDescription>
        </Alert>
      )}
    </div>
  );
}

// ── Cache tab ─────────────────────────────────────────────────────────────────
function CacheTab() {
  const { data: d, isLoading } = useQuery({ ...q("cache", 30_000) });
  if (isLoading) return <p className="p-6 text-muted-foreground text-sm">Loading…</p>;
  if ((d as any)?.status === "DISABLED") return <DisabledState module="Performance Centre" />;
  const r = d as any;
  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3">
        {r?.performance_score != null && <ScoreChip score={r.performance_score} grade={r.grade} />}
      </div>
      <div className="bg-card rounded-lg border p-4 space-y-1">
        <MetricRow label="Hit Rate (est.)"     value={r?.cache_hit_rate_est_pct} unit="%" />
        <MetricRow label="Total Entries"       value={r?.total_entries} />
        <MetricRow label="Stale Entries"       value={r?.stale_entries} />
        <MetricRow label="Memory (est.)"       value={r?.memory_est_kb} unit=" KB" />
        <MetricRow label="Stale Threshold"     value={r?.stale_threshold_s} unit=" s" />
      </div>
      {r?.caches?.length > 0 && (
        <div>
          <p className="text-sm font-medium mb-2">Monitored Caches</p>
          <div className="space-y-1">
            {r.caches.map((c: any, i: number) => (
              <div key={i} className="flex justify-between text-sm bg-card border rounded px-3 py-2">
                <span className="text-xs text-muted-foreground">{c.label}</span>
                <span>{c.entries} entries {c.stale_entries > 0 && <span className="text-amber-400">({c.stale_entries} stale)</span>}</span>
              </div>
            ))}
          </div>
        </div>
      )}
      {r?.note && <p className="text-xs text-muted-foreground">{r.note}</p>}
    </div>
  );
}

// ── Scheduler tab ─────────────────────────────────────────────────────────────
function SchedulerTab() {
  const { data: d, isLoading } = useQuery({ ...q("scheduler", 20_000) });
  if (isLoading) return <p className="p-6 text-muted-foreground text-sm">Loading…</p>;
  if ((d as any)?.status === "DISABLED") return <DisabledState module="Performance Centre" />;
  const r = d as any;
  const timing = r?.scan_timing ?? {};
  const last   = r?.last_scan ?? {};
  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3">
        {r?.performance_score != null && <ScoreChip score={r.performance_score} grade={r.grade} />}
        <Badge variant="outline" className="gap-1"><StatusDot status={r?.scheduler_status ?? "UNKNOWN"} />{r?.scheduler_status}</Badge>
      </div>
      <div className="bg-card rounded-lg border p-4 space-y-1">
        <MetricRow label="Scan Interval"  value={r?.scan_interval_min} unit=" min" />
        <MetricRow label="Running Jobs"   value={r?.running_count} />
        <MetricRow label="Failed Jobs"    value={r?.failed_count} />
        <MetricRow label="Last Scan Age"  value={last.age_min != null ? last.age_min?.toFixed(1) : null} unit=" min" />
        <MetricRow label="Avg Duration"   value={timing.avg_duration_s} unit=" s" />
        <MetricRow label="Max Duration"   value={timing.max_duration_s} unit=" s" />
        <MetricRow label="Total Runs"     value={timing.run_count} />
      </div>
    </div>
  );
}

// ── Resources tab ─────────────────────────────────────────────────────────────
function ResourcesTab() {
  const { data: d, isLoading } = useQuery({ ...q("resources", 15_000) });
  if (isLoading) return <p className="p-6 text-muted-foreground text-sm">Loading…</p>;
  if ((d as any)?.status === "DISABLED") return <DisabledState module="Performance Centre" />;
  const r = d as any;
  const mem  = r?.memory  ?? {};
  const cpu  = r?.cpu     ?? {};
  const disk = r?.disk    ?? {};
  const proc = r?.process ?? {};
  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3">
        {r?.performance_score != null && <ScoreChip score={r.performance_score} grade={r.grade} />}
        <Badge variant="outline" className="gap-1"><StatusDot status={r?.overall_status ?? "UNKNOWN"} />{r?.overall_status}</Badge>
      </div>
      <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
        <div className="bg-card rounded-lg border p-4 space-y-1">
          <p className="text-sm font-medium mb-2 flex items-center gap-1"><Cpu className="w-3.5 h-3.5" /> Memory</p>
          <MetricRow label="Usage" value={mem.usage_pct} unit="%" />
          <MetricRow label="Used"  value={mem.used_mb}   unit=" MB" />
          <MetricRow label="Free"  value={mem.free_mb}   unit=" MB" />
        </div>
        <div className="bg-card rounded-lg border p-4 space-y-1">
          <p className="text-sm font-medium mb-2 flex items-center gap-1"><Activity className="w-3.5 h-3.5" /> CPU</p>
          <MetricRow label="Load 1m"  value={cpu.load_1m}  />
          <MetricRow label="Load 5m"  value={cpu.load_5m}  />
          <MetricRow label="Load 15m" value={cpu.load_15m} />
        </div>
        <div className="bg-card rounded-lg border p-4 space-y-1">
          <p className="text-sm font-medium mb-2 flex items-center gap-1"><Database className="w-3.5 h-3.5" /> Disk</p>
          <MetricRow label="Usage" value={disk.usage_pct} unit="%" />
          <MetricRow label="Used"  value={disk.used_gb}   unit=" GB" />
          <MetricRow label="Free"  value={disk.free_gb}   unit=" GB" />
        </div>
      </div>
      <div className="bg-card rounded-lg border p-4 space-y-1">
        <p className="text-sm font-medium mb-2">Python Worker Process</p>
        <MetricRow label="PID"     value={proc.pid} />
        <MetricRow label="RSS"     value={proc.rss_mb} unit=" MB" />
        <MetricRow label="VM Size" value={proc.vm_mb}  unit=" MB" />
        <MetricRow label="Threads" value={proc.threads} />
        <MetricRow label="Node Processes" value={r?.node_processes?.count} />
      </div>
    </div>
  );
}

// ── Frontend tab ──────────────────────────────────────────────────────────────
function FrontendTab() {
  const { data: d, isLoading } = useQuery({ ...q("frontend", 60_000) });
  if (isLoading) return <p className="p-6 text-muted-foreground text-sm">Loading…</p>;
  if ((d as any)?.status === "DISABLED") return <DisabledState module="Performance Centre" />;
  const r = d as any;
  const bundle  = r?.bundle    ?? {};
  const pl      = r?.page_load ?? {};
  const feats   = r?.dashboard_features ?? {};
  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3">
        {r?.performance_score != null && <ScoreChip score={r.performance_score} grade={r.grade} />}
      </div>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        <div className="bg-card rounded-lg border p-4 space-y-1">
          <p className="text-sm font-medium mb-2">Bundle</p>
          <MetricRow label="Total Size"    value={bundle.total_kb} unit=" KB" />
          <MetricRow label="Warn Threshold" value={bundle.warn_threshold_kb} unit=" KB" />
          <MetricRow label="Built"         value={bundle.built ? "Yes" : "Dev mode"} />
        </div>
        <div className="bg-card rounded-lg border p-4 space-y-1">
          <p className="text-sm font-medium mb-2">Page Load</p>
          <MetricRow label="Estimated Load" value={pl.estimated_ms} unit=" ms" note={pl.estimated_ms ? "heuristic" : undefined} />
          <MetricRow label="Target"         value={pl.target_ms} unit=" ms" />
        </div>
      </div>
      <div className="bg-card rounded-lg border p-4">
        <p className="text-sm font-medium mb-2">Dashboard Features</p>
        <div className="grid grid-cols-2 gap-2 text-sm">
          {Object.entries(feats).map(([k, v]: [string, any]) => (
            <div key={k} className="flex items-center gap-2">
              {v ? <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400" /> : <AlertTriangle className="w-3.5 h-3.5 text-amber-400" />}
              <span className="text-muted-foreground capitalize">{k.replace(/_/g, " ")}</span>
            </div>
          ))}
        </div>
      </div>
      {r?.note && <p className="text-xs text-muted-foreground">{r.note}</p>}
    </div>
  );
}

// ── Benchmark tab ─────────────────────────────────────────────────────────────
function BenchmarkTab() {
  const { data: d, isLoading } = useQuery({ ...q("benchmark", 30_000) });
  if (isLoading) return <p className="p-6 text-muted-foreground text-sm">Loading…</p>;
  if ((d as any)?.status === "DISABLED") return <DisabledState module="Performance Centre" />;
  const r = d as any;
  const comp = r?.comparison ?? {};
  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3">
        {r?.trend && <TrendBadge trend={r.trend} />}
        {r?.performance_score_baseline != null && (
          <span className="text-sm text-muted-foreground">Obs baseline: {r.performance_score_baseline}</span>
        )}
      </div>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        {Object.entries(comp).map(([label, val]: [string, any]) => (
          <div key={label} className="bg-card rounded-lg border p-3">
            <p className="text-xs text-muted-foreground capitalize mb-1">{label.replace(/_/g, " ")}</p>
            {Object.entries(val ?? {}).map(([k2, v2]: [string, any]) => (
              <p key={k2} className="text-xs">{k2}: <span className="font-mono">{v2 ?? "—"}</span></p>
            ))}
          </div>
        ))}
      </div>
      {r?.recent_runs?.length > 0 && (
        <div>
          <p className="text-sm font-medium mb-2">Recent Scan Runs</p>
          <div className="space-y-1">
            {r.recent_runs.map((run: any, i: number) => (
              <div key={i} className="flex justify-between text-xs bg-card border rounded px-3 py-2">
                <span className="text-muted-foreground truncate max-w-[40%]">{run.scan_id ?? "—"}</span>
                <span>{run.duration_s != null ? `${run.duration_s}s` : "—"}</span>
                <span>{run.status ?? "—"}</span>
              </div>
            ))}
          </div>
        </div>
      )}
      {r?.note && <p className="text-xs text-muted-foreground">{r.note}</p>}
    </div>
  );
}

// ── Recommendations tab ───────────────────────────────────────────────────────
function RecommendationsTab() {
  const { data: d, isLoading } = useQuery({ ...q("recommendations", 30_000) });
  if (isLoading) return <p className="p-6 text-muted-foreground text-sm">Loading…</p>;
  if ((d as any)?.status === "DISABLED") return <DisabledState module="Performance Centre" />;
  const r = d as any;
  const sevColors: Record<string, string> = {
    CRITICAL: "border-red-500/60 bg-red-500/5",
    WARNING:  "border-amber-500/60 bg-amber-500/5",
    INFO:     "border-blue-500/40 bg-blue-500/5",
  };
  return (
    <div className="space-y-4">
      <div className="flex gap-3 text-sm">
        {r?.critical_count > 0 && <Badge variant="destructive">{r.critical_count} critical</Badge>}
        {r?.warning_count  > 0 && <Badge className="bg-amber-500">{r.warning_count} warning</Badge>}
        <Badge variant="outline">{r?.info_count ?? 0} info</Badge>
      </div>
      {r?.recommendations?.map((rec: any, i: number) => (
        <Alert key={i} className={`${sevColors[rec.severity] ?? ""}`}>
          <Lightbulb className="w-4 h-4" />
          <AlertDescription>
            <div className="flex items-center gap-2 mb-1">
              <span className="font-medium text-sm">{rec.title}</span>
              <Badge variant="outline" className="text-xs">{rec.domain}</Badge>
              <span className="text-xs text-muted-foreground">{rec.severity}</span>
            </div>
            <p className="text-xs text-muted-foreground">{rec.detail}</p>
          </AlertDescription>
        </Alert>
      ))}
      {r?.note && <p className="text-xs text-muted-foreground">{r.note}</p>}
    </div>
  );
}

// ── Scalability tab ───────────────────────────────────────────────────────────
function ScalabilityTab() {
  const { data: d, isLoading } = useQuery({ ...q("scalability", 60_000) });
  if (isLoading) return <p className="p-6 text-muted-foreground text-sm">Loading…</p>;
  if ((d as any)?.status === "DISABLED") return <DisabledState module="Performance Centre" />;
  const r = d as any;
  const cur = r?.current_capacity  ?? {};
  const rec = r?.recommended_capacity ?? {};
  const ma  = r?.multi_agent_readiness ?? {};
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        <div className="bg-card rounded-lg border p-4 space-y-1">
          <p className="text-sm font-medium mb-2">Current Capacity</p>
          <MetricRow label="Max Symbols/Scan"  value={cur.max_symbols_per_scan} />
          <MetricRow label="Concurrent Users"  value={cur.concurrent_users} />
          <MetricRow label="Scheduler Slots"   value={cur.scheduler_slots} />
          <MetricRow label="Scheduler Load"    value={cur.scheduler_load_pct} unit="%" />
          <MetricRow label="Mem Headroom"      value={cur.mem_headroom_pct} unit="%" />
        </div>
        <div className="bg-card rounded-lg border p-4 space-y-1">
          <p className="text-sm font-medium mb-2">Recommended Capacity</p>
          <MetricRow label="Max Symbols/Scan"  value={rec.max_symbols_per_scan} />
          <MetricRow label="Concurrent Users"  value={rec.concurrent_users} />
          <MetricRow label="Scheduler Slots"   value={rec.scheduler_slots} />
          {rec.note && <p className="text-xs text-muted-foreground mt-2">{rec.note}</p>}
        </div>
      </div>
      <div className="bg-card rounded-lg border p-4">
        <p className="text-sm font-medium mb-2">Future Multi-Agent Readiness</p>
        <p className="text-xs text-muted-foreground mb-3">
          Possible agents: <strong>{ma.agents_possible}</strong>
        </p>
        <div className="grid grid-cols-2 md:grid-cols-3 gap-1.5">
          {ma.agents?.map((a: any) => (
            <div key={a.name} className="text-xs bg-card border rounded px-2 py-1 text-muted-foreground">
              {a.name}
            </div>
          ))}
        </div>
        {ma.note && <p className="text-xs text-muted-foreground mt-3">{ma.note}</p>}
      </div>
      {r?.note && <p className="text-xs text-muted-foreground">{r.note}</p>}
    </div>
  );
}

// ── Export tab ────────────────────────────────────────────────────────────────
function ExportTab() {
  const handleDownload = async (fmt: "json" | "csv") => {
    const base = import.meta.env.BASE_URL.replace(/\/$/, "");
    const url = `${base}/api/performance/export?format=${fmt}`;
    const res  = await fetch(url);
    const blob = await res.blob();
    const a    = document.createElement("a");
    a.href     = URL.createObjectURL(blob);
    a.download = `performance_export.${fmt}`;
    a.click();
  };
  return (
    <div className="space-y-6">
      <Alert className="border-blue-500/30 bg-blue-500/5">
        <Download className="w-4 h-4 text-blue-400" />
        <AlertDescription className="text-sm">
          All exports are advisory only. No live values are modified. No secrets are included.
        </AlertDescription>
      </Alert>
      <div className="grid grid-cols-2 gap-4">
        <button
          onClick={() => handleDownload("json")}
          className="flex flex-col items-center gap-2 p-6 border rounded-lg hover:bg-card transition-colors text-sm"
        >
          <Download className="w-6 h-6 text-blue-400" />
          <span className="font-medium">Export JSON</span>
          <span className="text-xs text-muted-foreground">Full performance report</span>
        </button>
        <button
          onClick={() => handleDownload("csv")}
          className="flex flex-col items-center gap-2 p-6 border rounded-lg hover:bg-card transition-colors text-sm"
        >
          <Download className="w-6 h-6 text-emerald-400" />
          <span className="font-medium">Export CSV</span>
          <span className="text-xs text-muted-foreground">Key metrics spreadsheet</span>
        </button>
      </div>
    </div>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────
export default function PerformanceCenter() {
  return (
    <div className="p-6 space-y-4 max-w-6xl mx-auto">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Zap className="w-6 h-6 text-primary" />
          <div>
            <h1 className="text-xl font-semibold">Performance Optimisation Centre</h1>
            <p className="text-sm text-muted-foreground">Phase 8.7 · Read-only performance analysis & scalability framework</p>
          </div>
        </div>
      </div>

      <Alert className="border-primary/30 bg-primary/5">
        <Zap className="w-4 h-4 text-primary" />
        <AlertDescription className="text-sm text-muted-foreground">
          READ-ONLY · ADVISORY-ONLY — monitors, profiles, benchmarks and recommends.
          Never modifies algorithms, strategies, models, configuration, orders, or portfolio.
        </AlertDescription>
      </Alert>

      <Tabs defaultValue="overview" className="space-y-4">
        <TabsList className="flex flex-wrap h-auto gap-1">
          <TabsTrigger value="overview">Overview</TabsTrigger>
          <TabsTrigger value="api">API</TabsTrigger>
          <TabsTrigger value="database">Database</TabsTrigger>
          <TabsTrigger value="cache">Cache</TabsTrigger>
          <TabsTrigger value="scheduler">Scheduler</TabsTrigger>
          <TabsTrigger value="resources">Resources</TabsTrigger>
          <TabsTrigger value="frontend">Frontend</TabsTrigger>
          <TabsTrigger value="benchmark">Benchmark</TabsTrigger>
          <TabsTrigger value="recommendations">Recommendations</TabsTrigger>
          <TabsTrigger value="scalability">Scalability</TabsTrigger>
          <TabsTrigger value="export">Export</TabsTrigger>
        </TabsList>

        <TabsContent value="overview">       <OverviewTab />       </TabsContent>
        <TabsContent value="api">           <ApiTab />            </TabsContent>
        <TabsContent value="database">      <DatabaseTab />       </TabsContent>
        <TabsContent value="cache">         <CacheTab />          </TabsContent>
        <TabsContent value="scheduler">     <SchedulerTab />      </TabsContent>
        <TabsContent value="resources">     <ResourcesTab />      </TabsContent>
        <TabsContent value="frontend">      <FrontendTab />       </TabsContent>
        <TabsContent value="benchmark">     <BenchmarkTab />      </TabsContent>
        <TabsContent value="recommendations"><RecommendationsTab /></TabsContent>
        <TabsContent value="scalability">   <ScalabilityTab />    </TabsContent>
        <TabsContent value="export">        <ExportTab />         </TabsContent>
      </Tabs>
    </div>
  );
}
