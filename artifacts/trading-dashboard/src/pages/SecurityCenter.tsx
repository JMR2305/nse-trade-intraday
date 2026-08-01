/**
 * SecurityCenter.tsx — Phase 8.6
 * Security & Compliance Centre for ApexQuant AI.
 *
 * READ-ONLY. ADVISORY-ONLY.
 * Monitors, validates, scores and reports security posture.
 * NEVER modifies secrets, credentials, feature flags, config, orders, or portfolio.
 */
import { useQuery }   from "@tanstack/react-query";
import { apiJson }    from "@/lib/api";
import { Badge }      from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  Shield, ShieldCheck, ShieldAlert, ShieldX,
  Lock, Unlock, Key, KeyRound,
  AlertTriangle, CheckCircle2, XCircle, AlertCircle,
  RefreshCw, Info, Download, Eye, EyeOff,
  Server, Database, Globe, Package,
  Clock, Activity, FileText, Settings,
  TrendingUp, BarChart3, Gauge,
} from "lucide-react";

// ── API helpers ────────────────────────────────────────────────────────────────
const q = (path: string, ms = 30_000) => ({
  queryKey:        ["sec", path],
  queryFn:         () => apiJson(`security/${path}`),
  refetchInterval:  ms,
  retry: 1,
});

// ── Sub-components ─────────────────────────────────────────────────────────────

function GradeBadge({ score, grade }: { score: number; grade: string }) {
  const cls =
    grade === "A+" ? "bg-emerald-500/20 text-emerald-400 border-emerald-500/30" :
    grade === "A"  ? "bg-green-500/20  text-green-400  border-green-500/30"  :
    grade === "B"  ? "bg-yellow-500/20 text-yellow-400 border-yellow-500/30" :
    grade === "C"  ? "bg-orange-500/20 text-orange-400 border-orange-500/30" :
                     "bg-red-500/20    text-red-400    border-red-500/30";
  return (
    <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-semibold border ${cls}`}>
      {grade} · {score}
    </span>
  );
}

function RiskBadge({ level }: { level: string }) {
  const cls =
    level === "LOW"      ? "bg-emerald-500/20 text-emerald-400 border-emerald-500/30" :
    level === "MEDIUM"   ? "bg-yellow-500/20  text-yellow-400  border-yellow-500/30"  :
    level === "HIGH"     ? "bg-orange-500/20  text-orange-400  border-orange-500/30"  :
                           "bg-red-500/20     text-red-400     border-red-500/30";
  return <span className={`px-2 py-0.5 rounded text-xs font-semibold border ${cls}`}>{level} RISK</span>;
}

function SeverityBadge({ severity }: { severity: string }) {
  const cls =
    severity === "CRITICAL" ? "bg-red-500/20 text-red-400 border-red-500/30" :
    severity === "WARNING"  ? "bg-yellow-500/20 text-yellow-400 border-yellow-500/30" :
                              "bg-blue-500/20 text-blue-400 border-blue-500/30";
  return <span className={`px-1.5 py-0.5 rounded text-[11px] font-medium border ${cls}`}>{severity}</span>;
}

function PresenceBadge({ presence }: { presence: string }) {
  const map: Record<string, string> = {
    PRESENT: "bg-emerald-500/20 text-emerald-400 border-emerald-500/30",
    MISSING: "bg-red-500/20 text-red-400 border-red-500/30",
    WEAK:    "bg-yellow-500/20 text-yellow-400 border-yellow-500/30",
  };
  return <span className={`px-1.5 py-0.5 rounded text-[11px] font-medium border ${map[presence] ?? ""}`}>{presence}</span>;
}

function StatusDot({ status }: { status: string }) {
  const cls =
    ["OK", "SECURE", "HEALTHY"].includes(status)    ? "bg-emerald-400" :
    ["DEGRADED", "WARNING", "WEAK"].includes(status) ? "bg-yellow-400"  :
    ["AT_RISK", "CRITICAL", "MISSING"].includes(status) ? "bg-red-400"  : "bg-zinc-500";
  return <span className={`inline-block w-2 h-2 rounded-full ${cls}`} />;
}

function MetricRow({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between py-1.5 border-b border-border/30 last:border-0">
      <span className="text-sm text-muted-foreground">{label}</span>
      <span className="text-sm font-medium">{value}</span>
    </div>
  );
}

function DisabledCard({ message }: { message?: string }) {
  return (
    <Card className="border-border/40">
      <CardContent className="py-12 text-center text-muted-foreground">
        <Shield className="w-8 h-8 mx-auto mb-3 opacity-40" />
        <p className="text-sm">{message ?? "Set SECURITY_CENTER_ENABLED=true to enable"}</p>
      </CardContent>
    </Card>
  );
}

function LoadingCard() {
  return (
    <Card className="border-border/40">
      <CardContent className="py-12 text-center text-muted-foreground">
        <RefreshCw className="w-6 h-6 mx-auto mb-3 animate-spin opacity-40" />
        <p className="text-sm">Loading…</p>
      </CardContent>
    </Card>
  );
}

function ScoreBar({ score }: { score: number }) {
  const colour = score >= 80 ? "bg-emerald-500" : score >= 60 ? "bg-yellow-500" : "bg-red-500";
  return (
    <div className="w-full bg-border/30 rounded-full h-1.5">
      <div className={`h-1.5 rounded-full ${colour}`} style={{ width: `${score}%` }} />
    </div>
  );
}

function AdvisoryBanner() {
  return (
    <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-red-500/10 border border-red-500/20 text-red-400 text-xs mb-4">
      <Lock className="w-3.5 h-3.5 shrink-0" />
      READ-ONLY · ADVISORY-ONLY — monitors and reports security posture only. Never modifies secrets, credentials, flags, config, orders, or portfolio.
    </div>
  );
}

// ── Overview Tab ───────────────────────────────────────────────────────────────
function OverviewTab() {
  const { data, isLoading } = useQuery(q("summary", 20_000));
  if (isLoading) return <LoadingCard />;
  if (!data?.available) return <DisabledCard message={data?.message} />;

  const statusIcon =
    data.security_status === "SECURE"   ? <ShieldCheck className="w-6 h-6 text-emerald-400" /> :
    data.security_status === "DEGRADED" ? <ShieldAlert className="w-6 h-6 text-yellow-400" />  :
                                          <ShieldX className="w-6 h-6 text-red-400" />;

  const scoreItems = [
    { label: "Secrets",      score: data.secrets_score,    icon: <Key className="w-4 h-4" /> },
    { label: "Session",      score: data.session_score,    icon: <Lock className="w-4 h-4" /> },
    { label: "Configuration",score: data.config_score,     icon: <Settings className="w-4 h-4" /> },
    { label: "API Security", score: data.api_score,        icon: <Server className="w-4 h-4" /> },
    { label: "Dependencies", score: data.dependency_score, icon: <Package className="w-4 h-4" /> },
  ];

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <Card className="md:col-span-1 border-border/40 bg-gradient-to-br from-primary/5 to-transparent">
          <CardContent className="pt-6 text-center">
            <div className="flex justify-center mb-2">{statusIcon}</div>
            <div className="text-5xl font-bold text-primary mb-1">{data.security_score}</div>
            <div className="text-sm text-muted-foreground mb-3">Security Score</div>
            <GradeBadge score={data.security_score} grade={data.grade} />
            <div className="mt-2"><RiskBadge level={data.risk_level} /></div>
          </CardContent>
        </Card>

        <Card className="md:col-span-2 border-border/40">
          <CardContent className="pt-6">
            <div className="grid grid-cols-2 gap-4">
              <div>
                <p className="text-xs text-muted-foreground mb-1">Security Status</p>
                <p className="text-sm font-semibold flex items-center gap-1.5">
                  <StatusDot status={data.security_status} /> {data.security_status}
                </p>
              </div>
              <div>
                <p className="text-xs text-muted-foreground mb-1">Risk Level</p>
                <RiskBadge level={data.risk_level} />
              </div>
              <div>
                <p className="text-xs text-muted-foreground mb-1">Critical Alerts</p>
                <p className={`text-lg font-bold ${data.critical_alerts > 0 ? "text-red-400" : "text-emerald-400"}`}>
                  {data.critical_alerts}
                </p>
              </div>
              <div>
                <p className="text-xs text-muted-foreground mb-1">Warnings</p>
                <p className={`text-lg font-bold ${data.warning_alerts > 0 ? "text-yellow-400" : "text-zinc-400"}`}>
                  {data.warning_alerts}
                </p>
              </div>
            </div>
          </CardContent>
        </Card>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        {[
          { label: "Missing Secrets",   value: data.missing_secrets,   colour: data.missing_secrets > 0 ? "text-red-400" : "text-emerald-400" },
          { label: "Weak Secrets",      value: data.weak_secrets,      colour: data.weak_secrets > 0 ? "text-yellow-400" : "text-emerald-400" },
          { label: "Config Issues",     value: data.config_issues,     colour: data.config_issues > 0 ? "text-yellow-400" : "text-emerald-400" },
          { label: "Dep. Advisories",   value: data.dep_advisories,    colour: data.dep_advisories > 0 ? "text-yellow-400" : "text-emerald-400" },
        ].map(({ label, value, colour }) => (
          <Card key={label} className="border-border/40">
            <CardContent className="pt-4 text-center">
              <div className={`text-2xl font-bold ${colour}`}>{value ?? 0}</div>
              <div className="text-xs text-muted-foreground">{label}</div>
            </CardContent>
          </Card>
        ))}
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {scoreItems.map(({ label, score, icon }) => (
          <div key={label}>
            <div className="flex items-center justify-between text-sm mb-1">
              <span className="flex items-center gap-2 text-muted-foreground">{icon}{label}</span>
              <GradeBadge score={score} grade={score >= 92 ? "A+" : score >= 80 ? "A" : score >= 68 ? "B" : score >= 50 ? "C" : "D"} />
            </div>
            <ScoreBar score={score} />
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Auth Tab ───────────────────────────────────────────────────────────────────
function AuthTab() {
  const { data, isLoading } = useQuery(q("auth", 20_000));
  if (isLoading) return <LoadingCard />;
  if (!data?.available) return <DisabledCard message={data?.message} />;
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        {[
          { label: "Zerodha Mode",   value: data.zerodha_mode_enabled ? "LIVE" : "DISABLED",  colour: data.zerodha_mode_enabled ? "text-blue-400" : "text-zinc-400" },
          { label: "API Key",        value: data.zerodha_key_present ? "PRESENT" : "MISSING",   colour: data.zerodha_key_present ? "text-emerald-400" : "text-red-400" },
          { label: "API Secret",     value: data.zerodha_secret_present ? "PRESENT" : "MISSING",colour: data.zerodha_secret_present ? "text-emerald-400" : "text-red-400" },
          { label: "Auth Score",     value: data.score,  colour: "text-primary" },
        ].map(({ label, value, colour }) => (
          <Card key={label} className="border-border/40">
            <CardContent className="pt-4 text-center">
              <div className={`text-base font-bold ${colour}`}>{value}</div>
              <div className="text-xs text-muted-foreground">{label}</div>
            </CardContent>
          </Card>
        ))}
      </div>
      <Card className="border-border/40">
        <CardHeader className="pb-2"><CardTitle className="text-sm">Authentication Details</CardTitle></CardHeader>
        <CardContent>
          <MetricRow label="Zerodha Live Mode"       value={data.zerodha_mode_enabled ? <span className="text-blue-400">ENABLED</span> : "DISABLED"} />
          <MetricRow label="API Key Present"         value={data.zerodha_key_present ? <span className="text-emerald-400">✓ PRESENT</span> : <span className="text-red-400">✗ MISSING</span>} />
          <MetricRow label="API Secret Present"      value={data.zerodha_secret_present ? <span className="text-emerald-400">✓ PRESENT</span> : <span className="text-red-400">✗ MISSING</span>} />
          <MetricRow label="API Status"              value={<span className="flex items-center gap-1.5"><StatusDot status={data.api_status} />{data.api_status}</span>} />
          <MetricRow label="Database Status"         value={<span className="flex items-center gap-1.5"><StatusDot status={data.db_status} />{data.db_status}</span>} />
          <MetricRow label="Authentication Score"    value={<GradeBadge score={data.score} grade={data.score >= 92 ? "A+" : data.score >= 80 ? "A" : data.score >= 68 ? "B" : data.score >= 50 ? "C" : "D"} />} />
        </CardContent>
      </Card>
      {data.alerts?.length > 0 && (
        <Card className="border-border/40">
          <CardHeader className="pb-2"><CardTitle className="text-sm text-red-400">Authentication Alerts</CardTitle></CardHeader>
          <CardContent>
            {data.alerts.map((a: any, i: number) => (
              <div key={i} className="flex items-start gap-2 py-2 border-b border-border/30 last:border-0">
                <SeverityBadge severity={a.severity} />
                <div><p className="text-sm font-medium">{a.title}</p><p className="text-xs text-muted-foreground">{a.detail}</p></div>
              </div>
            ))}
          </CardContent>
        </Card>
      )}
    </div>
  );
}

// ── Sessions Tab ───────────────────────────────────────────────────────────────
function SessionsTab() {
  const { data, isLoading } = useQuery(q("sessions", 20_000));
  if (isLoading) return <LoadingCard />;
  if (!data?.available) return <DisabledCard message={data?.message} />;
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-3 gap-4">
        <Card className="border-border/40">
          <CardContent className="pt-4 text-center">
            <Lock className="w-5 h-5 mx-auto mb-1 text-primary" />
            <div className={`text-sm font-bold ${data.session_secret_present ? "text-emerald-400" : "text-red-400"}`}>
              {data.session_secret_present ? "PRESENT" : "MISSING"}
            </div>
            <div className="text-xs text-muted-foreground">Session Secret</div>
          </CardContent>
        </Card>
        <Card className="border-border/40">
          <CardContent className="pt-4 text-center">
            <ShieldCheck className="w-5 h-5 mx-auto mb-1 text-blue-400" />
            <div className={`text-sm font-bold ${data.session_secret_strong ? "text-emerald-400" : "text-yellow-400"}`}>
              {data.session_secret_strong ? "STRONG" : "WEAK"}
            </div>
            <div className="text-xs text-muted-foreground">Secret Strength</div>
          </CardContent>
        </Card>
        <Card className="border-border/40">
          <CardContent className="pt-4 text-center">
            <Gauge className="w-5 h-5 mx-auto mb-1 text-purple-400" />
            <div className="text-2xl font-bold">{data.score}</div>
            <div className="text-xs text-muted-foreground">Session Score</div>
          </CardContent>
        </Card>
      </div>
      <Card className="border-border/40">
        <CardHeader className="pb-2"><CardTitle className="text-sm">Session Configuration</CardTitle></CardHeader>
        <CardContent>
          <MetricRow label="SESSION_SECRET Present"  value={data.session_secret_present ? <span className="text-emerald-400">✓ Yes</span> : <span className="text-red-400">✗ No</span>} />
          <MetricRow label="SESSION_SECRET Strength" value={data.session_secret_strong  ? <span className="text-emerald-400">Strong (≥32 chars)</span> : <span className="text-yellow-400">Weak</span>} />
          <MetricRow label="Kite Token Present"      value={data.kite_token_present ? <span className="text-emerald-400">✓ Yes</span> : <span className="text-zinc-400">No"</span>} />
          <MetricRow label="Kite Token Valid"        value={data.kite_token_valid ? <span className="text-emerald-400">✓ Valid</span> : <span className="text-zinc-400">N/A</span>} />
          <MetricRow label="Kite Note"               value={<span className="text-xs text-muted-foreground">{data.kite_token_note}</span>} />
          <MetricRow label="Session Score"           value={<GradeBadge score={data.score} grade={data.score >= 92 ? "A+" : data.score >= 80 ? "A" : data.score >= 68 ? "B" : data.score >= 50 ? "C" : "D"} />} />
        </CardContent>
      </Card>
      {data.alerts?.length > 0 && (
        <Card className="border-border/40">
          <CardHeader className="pb-2"><CardTitle className="text-sm text-yellow-400">Session Alerts</CardTitle></CardHeader>
          <CardContent>
            {data.alerts.map((a: any, i: number) => (
              <div key={i} className="flex items-start gap-2 py-2 border-b border-border/30 last:border-0">
                <SeverityBadge severity={a.severity} />
                <div><p className="text-sm font-medium">{a.title}</p><p className="text-xs text-muted-foreground">{a.detail}</p></div>
              </div>
            ))}
          </CardContent>
        </Card>
      )}
    </div>
  );
}

// ── Secrets Tab ────────────────────────────────────────────────────────────────
function SecretsTab() {
  const { data, isLoading } = useQuery(q("secrets", 60_000));
  if (isLoading) return <LoadingCard />;
  if (!data?.available) return <DisabledCard message={data?.message} />;
  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2 px-3 py-2 rounded-lg bg-amber-500/10 border border-amber-500/20 text-amber-400 text-xs">
        <EyeOff className="w-3.5 h-3.5 shrink-0" />
        Presence validation only — secret values are NEVER displayed, logged, or transmitted.
      </div>
      <div className="grid grid-cols-3 gap-4">
        <Card className="border-border/40">
          <CardContent className="pt-4 text-center">
            <CheckCircle2 className="w-5 h-5 mx-auto mb-1 text-emerald-400" />
            <div className="text-2xl font-bold text-emerald-400">{data.present_count}</div>
            <div className="text-xs text-muted-foreground">Present</div>
          </CardContent>
        </Card>
        <Card className="border-border/40">
          <CardContent className="pt-4 text-center">
            <XCircle className="w-5 h-5 mx-auto mb-1 text-red-400" />
            <div className="text-2xl font-bold text-red-400">{data.missing_count}</div>
            <div className="text-xs text-muted-foreground">Missing</div>
          </CardContent>
        </Card>
        <Card className="border-border/40">
          <CardContent className="pt-4 text-center">
            <AlertTriangle className="w-5 h-5 mx-auto mb-1 text-yellow-400" />
            <div className="text-2xl font-bold text-yellow-400">{data.weak_count}</div>
            <div className="text-xs text-muted-foreground">Weak</div>
          </CardContent>
        </Card>
      </div>
      <Card className="border-border/40">
        <CardHeader className="pb-2">
          <CardTitle className="text-sm flex items-center justify-between">
            Secret Checks
            <GradeBadge score={data.score} grade={data.score >= 92 ? "A+" : data.score >= 80 ? "A" : data.score >= 68 ? "B" : data.score >= 50 ? "C" : "D"} />
          </CardTitle>
        </CardHeader>
        <CardContent>
          {(data.checks ?? []).map((c: any) => (
            <div key={c.name} className="flex items-start justify-between py-2.5 border-b border-border/30 last:border-0">
              <div>
                <p className="text-sm font-mono text-xs font-medium">{c.name}</p>
                <p className="text-xs text-muted-foreground">{c.description}</p>
                <p className="text-xs text-muted-foreground/60 mt-0.5">{c.detail}</p>
              </div>
              <div className="flex flex-col items-end gap-1 shrink-0 ml-4">
                <PresenceBadge presence={c.presence} />
                {c.critical && <Badge variant="outline" className="text-xs text-red-400 border-red-500/30">CRITICAL</Badge>}
              </div>
            </div>
          ))}
        </CardContent>
      </Card>
    </div>
  );
}

// ── Config Tab ─────────────────────────────────────────────────────────────────
function ConfigTab() {
  const { data, isLoading } = useQuery(q("config", 60_000));
  if (isLoading) return <LoadingCard />;
  if (!data?.available) return <DisabledCard message={data?.message} />;
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-3 gap-4">
        <Card className="border-border/40"><CardContent className="pt-4 text-center">
          <CheckCircle2 className="w-5 h-5 mx-auto mb-1 text-emerald-400" />
          <div className="text-2xl font-bold text-emerald-400">{data.ok_count}</div>
          <div className="text-xs text-muted-foreground">OK</div>
        </CardContent></Card>
        <Card className="border-border/40"><CardContent className="pt-4 text-center">
          <XCircle className="w-5 h-5 mx-auto mb-1 text-red-400" />
          <div className="text-2xl font-bold text-red-400">{data.missing_count}</div>
          <div className="text-xs text-muted-foreground">Missing</div>
        </CardContent></Card>
        <Card className="border-border/40"><CardContent className="pt-4 text-center">
          <AlertTriangle className="w-5 h-5 mx-auto mb-1 text-yellow-400" />
          <div className="text-2xl font-bold text-yellow-400">{data.invalid_count}</div>
          <div className="text-xs text-muted-foreground">Invalid</div>
        </CardContent></Card>
      </div>
      <Card className="border-border/40">
        <CardHeader className="pb-2">
          <CardTitle className="text-sm flex items-center justify-between">
            Configuration Checks
            <GradeBadge score={data.score} grade={data.score >= 92 ? "A+" : data.score >= 80 ? "A" : data.score >= 68 ? "B" : data.score >= 50 ? "C" : "D"} />
          </CardTitle>
        </CardHeader>
        <CardContent>
          {(data.checks ?? []).map((c: any) => (
            <div key={c.name} className="flex items-start justify-between py-2 border-b border-border/30 last:border-0">
              <div>
                <p className="text-xs font-mono font-medium">{c.name}</p>
                <p className="text-xs text-muted-foreground">{c.description}</p>
                <p className="text-xs text-muted-foreground/60 mt-0.5">{c.detail}</p>
              </div>
              <span className={`text-xs font-medium ml-4 shrink-0 ${c.status === "OK" ? "text-emerald-400" : c.status === "MISSING" ? "text-red-400" : "text-yellow-400"}`}>{c.status}</span>
            </div>
          ))}
        </CardContent>
      </Card>
    </div>
  );
}

// ── API Security Tab ───────────────────────────────────────────────────────────
function ApiSecTab() {
  const { data, isLoading } = useQuery(q("api", 30_000));
  if (isLoading) return <LoadingCard />;
  if (!data?.available) return <DisabledCard message={data?.message} />;
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        {[
          { label: "HTTPS",       value: data.https_enabled ? "ENABLED" : "NOT CONFIRMED", ok: data.https_enabled },
          { label: "Node Env",    value: data.node_env ?? "UNKNOWN",                        ok: data.node_env === "production" || data.node_env === "development" },
          { label: "Checks OK",   value: data.ok_count,                                    ok: true },
          { label: "API Score",   value: data.score,                                        ok: data.score >= 80 },
        ].map(({ label, value, ok }) => (
          <Card key={label} className="border-border/40">
            <CardContent className="pt-4 text-center">
              <div className={`text-sm font-bold ${ok ? "text-emerald-400" : "text-yellow-400"}`}>{value}</div>
              <div className="text-xs text-muted-foreground">{label}</div>
            </CardContent>
          </Card>
        ))}
      </div>
      <Card className="border-border/40">
        <CardHeader className="pb-2">
          <CardTitle className="text-sm flex items-center justify-between">
            API Security Checks
            <GradeBadge score={data.score} grade={data.score >= 92 ? "A+" : data.score >= 80 ? "A" : data.score >= 68 ? "B" : data.score >= 50 ? "C" : "D"} />
          </CardTitle>
        </CardHeader>
        <CardContent>
          {(data.checks ?? []).map((c: any, i: number) => (
            <div key={i} className="flex items-center justify-between py-2 border-b border-border/30 last:border-0">
              <div>
                <p className="text-sm font-medium">{c.check?.replace(/_/g, " ").replace(/\b\w/g, (l: string) => l.toUpperCase())}</p>
                <p className="text-xs text-muted-foreground">{c.detail}</p>
              </div>
              <span className={`text-xs font-semibold ml-4 shrink-0 ${c.status === "OK" ? "text-emerald-400" : c.status === "CRITICAL" ? "text-red-400" : c.status === "WARNING" ? "text-yellow-400" : "text-blue-400"}`}>{c.status}</span>
            </div>
          ))}
        </CardContent>
      </Card>
    </div>
  );
}

// ── Dependencies Tab ───────────────────────────────────────────────────────────
function DependenciesTab() {
  const { data, isLoading } = useQuery(q("dependencies", 120_000));
  if (isLoading) return <LoadingCard />;
  if (!data?.available) return <DisabledCard message={data?.message} />;
  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2 px-3 py-2 rounded-lg bg-blue-500/10 border border-blue-500/20 text-blue-400 text-xs">
        <Info className="w-3.5 h-3.5 shrink-0" />
        Advisory only — {data.note ?? "do not auto-update packages from this console."}
      </div>
      <div className="grid grid-cols-3 gap-4">
        <Card className="border-border/40"><CardContent className="pt-4 text-center">
          <Package className="w-5 h-5 mx-auto mb-1 text-blue-400" />
          <div className="text-2xl font-bold">{data.python_package_count}</div>
          <div className="text-xs text-muted-foreground">Python Packages</div>
        </CardContent></Card>
        <Card className="border-border/40"><CardContent className="pt-4 text-center">
          <Package className="w-5 h-5 mx-auto mb-1 text-green-400" />
          <div className="text-2xl font-bold">{data.node_package_count}</div>
          <div className="text-xs text-muted-foreground">Node Packages</div>
        </CardContent></Card>
        <Card className="border-border/40"><CardContent className="pt-4 text-center">
          <AlertTriangle className="w-5 h-5 mx-auto mb-1 text-yellow-400" />
          <div className="text-2xl font-bold text-yellow-400">{data.advisory_count}</div>
          <div className="text-xs text-muted-foreground">Advisories</div>
        </CardContent></Card>
      </div>
      {data.python_advisories?.length > 0 ? (
        <Card className="border-border/40">
          <CardHeader className="pb-2"><CardTitle className="text-sm text-yellow-400">Python Dependency Advisories</CardTitle></CardHeader>
          <CardContent>
            {data.python_advisories.map((a: any, i: number) => (
              <div key={i} className="py-2.5 border-b border-border/30 last:border-0">
                <div className="flex items-center justify-between">
                  <p className="text-sm font-medium font-mono">{a.package} v{a.installed}</p>
                  <SeverityBadge severity={a.severity ?? "WARNING"} />
                </div>
                <p className="text-xs text-muted-foreground mt-0.5">{a.advisory}</p>
                <p className="text-xs text-muted-foreground/60">Upgrade to ≥ {a.vulnerable_below}</p>
              </div>
            ))}
          </CardContent>
        </Card>
      ) : (
        <Card className="border-border/40">
          <CardContent className="py-8 text-center text-muted-foreground">
            <CheckCircle2 className="w-8 h-8 mx-auto mb-3 text-emerald-400 opacity-60" />
            <p className="text-sm">No dependency advisories found</p>
          </CardContent>
        </Card>
      )}
    </div>
  );
}

// ── Audit Log Tab ──────────────────────────────────────────────────────────────
function AuditTab() {
  const { data, isLoading } = useQuery(q("audit", 30_000));
  if (isLoading) return <LoadingCard />;
  if (!data?.available) return <DisabledCard message={data?.message} />;
  return (
    <div className="space-y-2">
      <div className="text-xs text-muted-foreground mb-3">{data.total} events · latest first</div>
      {(data.events ?? []).length === 0 ? (
        <Card className="border-border/40"><CardContent className="py-12 text-center text-muted-foreground">
          <FileText className="w-8 h-8 mx-auto mb-3 opacity-40" />
          <p className="text-sm">No audit events yet</p>
        </CardContent></Card>
      ) : (
        (data.events ?? []).map((e: any, i: number) => (
          <Card key={e.event_id ?? i} className="border-border/30">
            <CardContent className="py-2 px-4">
              <div className="flex items-start justify-between gap-2">
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-medium">{e.event_type?.replace(/_/g, " ")}</p>
                  <p className="text-xs text-muted-foreground truncate">{e.detail}</p>
                </div>
                <div className="shrink-0 text-right">
                  <Badge variant="outline" className="text-xs">{e.category}</Badge>
                  <p className="text-xs text-muted-foreground mt-1">{e.timestamp ? new Date(e.timestamp).toLocaleTimeString() : ""}</p>
                </div>
              </div>
            </CardContent>
          </Card>
        ))
      )}
    </div>
  );
}

// ── Compliance Tab ─────────────────────────────────────────────────────────────
function ComplianceTab() {
  const { data, isLoading } = useQuery(q("compliance", 60_000));
  if (isLoading) return <LoadingCard />;
  if (!data?.available) return <DisabledCard message={data?.message} />;
  const domains = [
    { label: "Secrets Security",  score: data.security_score,   weight: "30%" },
    { label: "Session Management",score: data.session_score,    weight: "20%" },
    { label: "Configuration",     score: data.config_score,     weight: "20%" },
    { label: "API Security",      score: data.api_score,        weight: "15%" },
    { label: "Dependencies",      score: data.dependency_score, weight: "15%" },
  ];
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <Card className="border-border/40 bg-gradient-to-br from-primary/5 to-transparent">
          <CardContent className="pt-6 text-center">
            <div className="text-5xl font-bold text-primary mb-1">{data.overall_score}</div>
            <div className="text-sm text-muted-foreground mb-3">Compliance Score</div>
            <GradeBadge score={data.overall_score} grade={data.grade} />
            <div className="mt-2"><RiskBadge level={data.risk_level} /></div>
          </CardContent>
        </Card>
        <Card className="md:col-span-2 border-border/40">
          <CardHeader className="pb-2"><CardTitle className="text-sm">Score Breakdown</CardTitle></CardHeader>
          <CardContent>
            {domains.map(({ label, score, weight }) => (
              <div key={label} className="mb-3">
                <div className="flex justify-between text-sm mb-1">
                  <span className="text-muted-foreground">{label}</span>
                  <span className="font-medium">{score} <span className="text-xs text-muted-foreground">({weight})</span></span>
                </div>
                <ScoreBar score={score} />
              </div>
            ))}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

// ── Alerts Tab ─────────────────────────────────────────────────────────────────
function AlertsTab() {
  const { data, isLoading } = useQuery(q("alerts", 15_000));
  if (isLoading) return <LoadingCard />;
  if (!data?.available) return <DisabledCard message={data?.message} />;
  const all = [...(data.critical ?? []), ...(data.warnings ?? []), ...(data.info ?? [])];
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-3 gap-4">
        <Card className="border-border/40"><CardContent className="pt-4 text-center">
          <XCircle className="w-5 h-5 mx-auto mb-1 text-red-400" />
          <div className="text-2xl font-bold text-red-400">{data.critical_count}</div>
          <div className="text-xs text-muted-foreground">Critical</div>
        </CardContent></Card>
        <Card className="border-border/40"><CardContent className="pt-4 text-center">
          <AlertTriangle className="w-5 h-5 mx-auto mb-1 text-yellow-400" />
          <div className="text-2xl font-bold text-yellow-400">{data.warning_count}</div>
          <div className="text-xs text-muted-foreground">Warnings</div>
        </CardContent></Card>
        <Card className="border-border/40"><CardContent className="pt-4 text-center">
          <Info className="w-5 h-5 mx-auto mb-1 text-blue-400" />
          <div className="text-2xl font-bold text-blue-400">{data.info_count}</div>
          <div className="text-xs text-muted-foreground">Info</div>
        </CardContent></Card>
      </div>
      {all.length === 0 ? (
        <Card className="border-border/40"><CardContent className="py-12 text-center text-muted-foreground">
          <ShieldCheck className="w-8 h-8 mx-auto mb-3 text-emerald-400 opacity-60" />
          <p className="text-sm">No active security alerts</p>
        </CardContent></Card>
      ) : (
        <Card className="border-border/40">
          <CardHeader className="pb-2"><CardTitle className="text-sm">Active Security Alerts</CardTitle></CardHeader>
          <CardContent>
            {all.map((a: any, i: number) => (
              <div key={a.alert_id ?? i} className="flex items-start gap-3 py-2.5 border-b border-border/30 last:border-0">
                <SeverityBadge severity={a.severity} />
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-medium">{a.title}</p>
                  <p className="text-xs text-muted-foreground">{a.detail}</p>
                  <p className="text-xs text-muted-foreground/60 mt-0.5 capitalize">{a.category?.replace(/_/g, " ")}</p>
                </div>
              </div>
            ))}
          </CardContent>
        </Card>
      )}
    </div>
  );
}

// ── Export Tab ─────────────────────────────────────────────────────────────────
function ExportTab() {
  const { data: summary } = useQuery(q("summary", 60_000));
  const handleExport = async (format: "json" | "csv") => {
    try {
      const base = import.meta.env.BASE_URL.replace(/\/$/, "");
      const res = await fetch(`${base}/api/security/export?format=${format}`);
      if (!res.ok) throw new Error(await res.text());
      const blob = await res.blob();
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = `security_${new Date().toISOString().slice(0, 10)}.${format}`;
      a.click();
    } catch (e: any) { alert(`Export failed: ${e.message}`); }
  };
  return (
    <div className="space-y-4">
      <Card className="border-border/40">
        <CardHeader className="pb-2"><CardTitle className="text-sm">Export Security Report</CardTitle></CardHeader>
        <CardContent className="space-y-3">
          <p className="text-sm text-muted-foreground">Export a full security audit snapshot. Never includes secret values — presence status only.</p>
          <div className="flex gap-3">
            <button onClick={() => handleExport("json")}
              className="flex items-center gap-2 px-4 py-2 rounded-lg bg-primary/10 hover:bg-primary/20 border border-primary/20 text-sm transition-colors">
              <Download className="w-4 h-4" />JSON Report
            </button>
            <button onClick={() => handleExport("csv")}
              className="flex items-center gap-2 px-4 py-2 rounded-lg bg-secondary hover:bg-secondary/80 border border-border/40 text-sm transition-colors">
              <Download className="w-4 h-4" />CSV Report
            </button>
          </div>
        </CardContent>
      </Card>
      {summary && (
        <Card className="border-border/40">
          <CardHeader className="pb-2"><CardTitle className="text-sm">Current Security Snapshot</CardTitle></CardHeader>
          <CardContent>
            <MetricRow label="Security Score"   value={<GradeBadge score={summary.security_score} grade={summary.grade} />} />
            <MetricRow label="Risk Level"       value={<RiskBadge level={summary.risk_level} />} />
            <MetricRow label="Security Status"  value={summary.security_status} />
            <MetricRow label="Critical Alerts"  value={<span className={summary.critical_alerts > 0 ? "text-red-400 font-semibold" : ""}>{summary.critical_alerts}</span>} />
            <MetricRow label="Missing Secrets"  value={<span className={summary.missing_secrets > 0 ? "text-red-400 font-semibold" : ""}>{summary.missing_secrets}</span>} />
            <MetricRow label="Generated"        value={summary.generated_at ? new Date(summary.generated_at).toLocaleTimeString() : "—"} />
          </CardContent>
        </Card>
      )}
    </div>
  );
}

// ── Main page ──────────────────────────────────────────────────────────────────
export default function SecurityCenter() {
  const { data: summary } = useQuery({ ...q("summary", 20_000), enabled: true });
  const criticalCount = summary?.critical_alerts ?? 0;

  return (
    <div className="p-4 md:p-6 max-w-7xl mx-auto space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold flex items-center gap-2">
            <Shield className="w-5 h-5 text-primary" />
            Security & Compliance Centre
          </h1>
          <p className="text-sm text-muted-foreground mt-0.5">Phase 8.6 · Read-only security audit console</p>
        </div>
        <div className="flex items-center gap-2">
          {criticalCount > 0 && (
            <Badge variant="destructive" className="text-xs">
              {criticalCount} critical
            </Badge>
          )}
          {summary && <GradeBadge score={summary.security_score} grade={summary.grade} />}
          {summary && <RiskBadge level={summary.risk_level} />}
        </div>
      </div>

      <AdvisoryBanner />

      <Tabs defaultValue="overview">
        <TabsList className="flex flex-wrap gap-1 h-auto">
          {[
            { value: "overview",      label: "Overview" },
            { value: "auth",          label: "Authentication" },
            { value: "sessions",      label: "Sessions" },
            { value: "secrets",       label: "Secrets" },
            { value: "config",        label: "Configuration" },
            { value: "api",           label: "API Security" },
            { value: "dependencies",  label: "Dependencies" },
            { value: "audit",         label: "Audit Log" },
            { value: "compliance",    label: "Compliance" },
            { value: "alerts",        label: `Alerts${criticalCount > 0 ? ` (${criticalCount})` : ""}` },
            { value: "export",        label: "Export" },
          ].map(({ value, label }) => (
            <TabsTrigger key={value} value={value} className="text-xs px-3">{label}</TabsTrigger>
          ))}
        </TabsList>

        <TabsContent value="overview"     className="mt-4"><OverviewTab /></TabsContent>
        <TabsContent value="auth"         className="mt-4"><AuthTab /></TabsContent>
        <TabsContent value="sessions"     className="mt-4"><SessionsTab /></TabsContent>
        <TabsContent value="secrets"      className="mt-4"><SecretsTab /></TabsContent>
        <TabsContent value="config"       className="mt-4"><ConfigTab /></TabsContent>
        <TabsContent value="api"          className="mt-4"><ApiSecTab /></TabsContent>
        <TabsContent value="dependencies" className="mt-4"><DependenciesTab /></TabsContent>
        <TabsContent value="audit"        className="mt-4"><AuditTab /></TabsContent>
        <TabsContent value="compliance"   className="mt-4"><ComplianceTab /></TabsContent>
        <TabsContent value="alerts"       className="mt-4"><AlertsTab /></TabsContent>
        <TabsContent value="export"       className="mt-4"><ExportTab /></TabsContent>
      </Tabs>
    </div>
  );
}
