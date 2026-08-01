/**
 * OperationsCenter.tsx — Phase 8.5
 * Operational Control Centre for ApexQuant AI.
 *
 * READ-ONLY. ADVISORY-ONLY.
 * Monitors and coordinates — never places orders, modifies portfolio,
 * strategies, AI models, risk parameters, feature flags, or restarts services.
 */
import { useQuery } from "@tanstack/react-query";
import { apiJson } from "@/lib/api";
import { Badge }   from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  AlertTriangle, CheckCircle2, XCircle, Clock, Activity,
  TrendingUp, TrendingDown, Minus, Shield, Database, Cpu,
  Globe, BarChart3, ToggleLeft, ToggleRight, List,
  Calendar, Download, AlertCircle, RefreshCw, Zap,
  Timer, Monitor, ChevronRight, Info,
} from "lucide-react";

// ── API helpers ────────────────────────────────────────────────────────────────
const q = (path: string, ms = 30_000) => ({
  queryKey:       ["ops", path],
  queryFn:        () => apiJson(`operations/${path}`),
  refetchInterval: ms,
  retry: 1,
});

// ── Sub-components ─────────────────────────────────────────────────────────────

function ScoreBadge({ score, grade }: { score: number; grade: string }) {
  const colour =
    grade === "A+" ? "bg-emerald-500/20 text-emerald-400 border-emerald-500/30" :
    grade === "A"  ? "bg-green-500/20  text-green-400  border-green-500/30"  :
    grade === "B"  ? "bg-yellow-500/20 text-yellow-400 border-yellow-500/30" :
    grade === "C"  ? "bg-orange-500/20 text-orange-400 border-orange-500/30" :
                     "bg-red-500/20    text-red-400    border-red-500/30";
  return (
    <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-semibold border ${colour}`}>
      {grade} · {score}
    </span>
  );
}

function StatusDot({ status }: { status: string }) {
  const colour =
    ["OPERATIONAL", "HEALTHY", "OK", "RUNNING"].includes(status)  ? "bg-emerald-400" :
    ["DEGRADED", "WARNING"].includes(status)                        ? "bg-yellow-400"  :
    ["DOWN", "FAILED", "ERROR"].includes(status)                    ? "bg-red-400"     :
                                                                      "bg-zinc-500";
  return <span className={`inline-block w-2 h-2 rounded-full ${colour}`} />;
}

function SeverityBadge({ severity }: { severity: string }) {
  const cls =
    severity === "CRITICAL" ? "bg-red-500/20 text-red-400 border-red-500/30" :
    severity === "WARNING"  ? "bg-yellow-500/20 text-yellow-400 border-yellow-500/30" :
                              "bg-blue-500/20 text-blue-400 border-blue-500/30";
  return (
    <span className={`px-1.5 py-0.5 rounded text-[11px] font-medium border ${cls}`}>
      {severity}
    </span>
  );
}

function MetricRow({ label, value, sub }: { label: string; value: React.ReactNode; sub?: string }) {
  return (
    <div className="flex items-center justify-between py-1.5 border-b border-border/30 last:border-0">
      <span className="text-sm text-muted-foreground">{label}</span>
      <span className="text-sm font-medium flex items-center gap-1">
        {value}
        {sub && <span className="text-xs text-muted-foreground">{sub}</span>}
      </span>
    </div>
  );
}

function DisabledCard({ message }: { message?: string }) {
  return (
    <Card className="border-border/40">
      <CardContent className="py-12 text-center text-muted-foreground">
        <ToggleLeft className="w-8 h-8 mx-auto mb-3 opacity-40" />
        <p className="text-sm">{message ?? "Module not enabled"}</p>
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

// ── Advisory banner ────────────────────────────────────────────────────────────
function AdvisoryBanner() {
  return (
    <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-blue-500/10 border border-blue-500/20 text-blue-400 text-xs mb-4">
      <Info className="w-3.5 h-3.5 shrink-0" />
      READ-ONLY · ADVISORY-ONLY — this console monitors and coordinates only. It never places orders, modifies portfolio, strategies, AI models, or configuration.
    </div>
  );
}

// ── Overview Tab ───────────────────────────────────────────────────────────────
function OverviewTab() {
  const { data, isLoading } = useQuery(q("summary", 20_000));
  if (isLoading) return <LoadingCard />;
  if (!data?.available) return <DisabledCard message={data?.message} />;

  const statusColour =
    data.platform_status === "OPERATIONAL" ? "text-emerald-400" :
    data.platform_status === "DEGRADED"    ? "text-yellow-400"  : "text-red-400";

  const trendIcon =
    data.trend === "IMPROVING" ? <TrendingUp className="w-4 h-4 text-emerald-400" /> :
    data.trend === "DEGRADING" ? <TrendingDown className="w-4 h-4 text-red-400" />  :
                                 <Minus className="w-4 h-4 text-zinc-400" />;

  return (
    <div className="space-y-4">
      {/* Hero score */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <Card className="md:col-span-1 border-border/40 bg-gradient-to-br from-primary/5 to-transparent">
          <CardContent className="pt-6 text-center">
            <div className="text-5xl font-bold text-primary mb-1">{data.operations_score}</div>
            <div className="text-sm text-muted-foreground mb-3">Operations Score</div>
            <ScoreBadge score={data.operations_score} grade={data.grade} />
            <div className="flex items-center justify-center gap-1 mt-2 text-xs text-muted-foreground">
              {trendIcon}<span>{data.trend}</span>
            </div>
          </CardContent>
        </Card>
        <Card className="md:col-span-2 border-border/40">
          <CardContent className="pt-6">
            <div className="grid grid-cols-2 gap-3">
              <div>
                <p className="text-xs text-muted-foreground mb-1">Platform Status</p>
                <p className={`text-lg font-semibold ${statusColour}`}>{data.platform_status}</p>
              </div>
              <div>
                <p className="text-xs text-muted-foreground mb-1">Trading Session</p>
                <p className="text-sm font-medium">{data.trading_session?.replace(/_/g, " ")}</p>
              </div>
              <div>
                <p className="text-xs text-muted-foreground mb-1">System Health</p>
                <p className="text-sm font-medium flex items-center gap-1.5">
                  <StatusDot status={data.system_health} /> {data.system_health}
                </p>
              </div>
              <div>
                <p className="text-xs text-muted-foreground mb-1">Market</p>
                <p className="text-sm font-medium">
                  {data.market_open ? <span className="text-emerald-400">● OPEN</span> : <span className="text-zinc-400">● CLOSED</span>}
                </p>
              </div>
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Score breakdown */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {[
          { label: "Observability",  score: data.observability_score, icon: <Monitor className="w-4 h-4" /> },
          { label: "Data Quality",   score: data.quality_score,       icon: <Database className="w-4 h-4" /> },
          { label: "Risk Validation",score: data.validation_score,    icon: <Shield className="w-4 h-4" /> },
        ].map(({ label, score, icon }) => (
          <Card key={label} className="border-border/40">
            <CardContent className="pt-4 pb-4">
              <div className="flex items-center justify-between mb-2">
                <div className="flex items-center gap-2 text-sm text-muted-foreground">{icon}{label}</div>
                <ScoreBadge score={score} grade={score >= 92 ? "A+" : score >= 80 ? "A" : score >= 68 ? "B" : score >= 50 ? "C" : "D"} />
              </div>
              <div className="w-full bg-border/30 rounded-full h-1.5">
                <div
                  className={`h-1.5 rounded-full ${score >= 80 ? "bg-emerald-500" : score >= 60 ? "bg-yellow-500" : "bg-red-500"}`}
                  style={{ width: `${score}%` }}
                />
              </div>
            </CardContent>
          </Card>
        ))}
      </div>

      {/* Status grid */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <Card className="border-border/40">
          <CardContent className="pt-4 text-center">
            <AlertTriangle className="w-5 h-5 mx-auto mb-1 text-red-400" />
            <div className="text-2xl font-bold text-red-400">{data.outstanding_alerts}</div>
            <div className="text-xs text-muted-foreground">Outstanding Alerts</div>
          </CardContent>
        </Card>
        <Card className="border-border/40">
          <CardContent className="pt-4 text-center">
            <Activity className="w-5 h-5 mx-auto mb-1 text-primary" />
            <div className="text-2xl font-bold">{data.active_modules?.length ?? 0}</div>
            <div className="text-xs text-muted-foreground">Active Modules</div>
          </CardContent>
        </Card>
        <Card className="border-border/40">
          <CardContent className="pt-4 text-center">
            <Shield className="w-5 h-5 mx-auto mb-1 text-blue-400" />
            <div className="text-sm font-semibold mt-1">{data.risk_level}</div>
            <div className="text-xs text-muted-foreground">Risk Level</div>
          </CardContent>
        </Card>
        <Card className="border-border/40">
          <CardContent className="pt-4 text-center">
            <Database className="w-5 h-5 mx-auto mb-1 text-purple-400" />
            <div className="text-sm font-semibold mt-1">{data.data_quality_grade}</div>
            <div className="text-xs text-muted-foreground">Data Quality</div>
          </CardContent>
        </Card>
      </div>

      {data.active_modules?.length > 0 && (
        <Card className="border-border/40">
          <CardHeader className="pb-2"><CardTitle className="text-sm">Active Modules</CardTitle></CardHeader>
          <CardContent>
            <div className="flex flex-wrap gap-2">
              {data.active_modules.map((m: string) => (
                <Badge key={m} variant="secondary" className="text-xs">{m}</Badge>
              ))}
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}

// ── Market Tab ─────────────────────────────────────────────────────────────────
function MarketTab() {
  const { data, isLoading } = useQuery(q("market", 15_000));
  if (isLoading) return <LoadingCard />;
  if (!data?.available) return <DisabledCard message={data?.message} />;

  const sessionColour =
    data.session === "NORMAL_SESSION"       ? "text-emerald-400" :
    data.session === "CLOSING_SESSION"      ? "text-yellow-400"  :
    data.session?.includes("AUCTION")       ? "text-blue-400"    :
    data.session?.includes("PRE")           ? "text-purple-400"  : "text-zinc-400";

  const regimeColour =
    data.regime === "TRENDING"              ? "text-emerald-400" :
    data.regime === "MEAN_REVERTING"        ? "text-blue-400"    :
    data.regime === "VOLATILE"              ? "text-red-400"     : "text-zinc-400";

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <Card className="border-border/40">
          <CardContent className="pt-4 text-center">
            <Globe className="w-5 h-5 mx-auto mb-1 text-primary" />
            <div className={`text-lg font-bold ${data.market_open ? "text-emerald-400" : "text-zinc-400"}`}>
              {data.market_open ? "OPEN" : "CLOSED"}
            </div>
            <div className="text-xs text-muted-foreground">Market Status</div>
          </CardContent>
        </Card>
        <Card className="border-border/40">
          <CardContent className="pt-4 text-center">
            <Clock className="w-5 h-5 mx-auto mb-1 text-blue-400" />
            <div className="text-base font-mono font-semibold">{data.ist_time}</div>
            <div className="text-xs text-muted-foreground">IST · {data.weekday}</div>
          </CardContent>
        </Card>
        <Card className="border-border/40">
          <CardContent className="pt-4 text-center">
            <BarChart3 className="w-5 h-5 mx-auto mb-1 text-yellow-400" />
            <div className="text-base font-semibold">{data.india_vix ?? "—"}</div>
            <div className="text-xs text-muted-foreground">India VIX</div>
          </CardContent>
        </Card>
        <Card className="border-border/40">
          <CardContent className="pt-4 text-center">
            <Activity className="w-5 h-5 mx-auto mb-1 text-purple-400" />
            <div className={`text-sm font-semibold ${regimeColour}`}>{data.regime}</div>
            <div className="text-xs text-muted-foreground">Market Regime</div>
          </CardContent>
        </Card>
      </div>

      <Card className="border-border/40">
        <CardHeader className="pb-2"><CardTitle className="text-sm">Session Details</CardTitle></CardHeader>
        <CardContent>
          <MetricRow label="Current Session" value={<span className={sessionColour}>{data.session?.replace(/_/g, " ")}</span>} />
          <MetricRow label="Data Provider"   value={data.data_provider ?? "UNKNOWN"} />
          <MetricRow label="Market Regime"   value={<span className={regimeColour}>{data.regime}</span>} />
          <MetricRow label="India VIX"       value={data.india_vix ?? "—"} />
          <MetricRow label="IST Time"        value={<span className="font-mono">{data.ist_time}</span>} />
          <MetricRow label="Day"             value={data.weekday} />
        </CardContent>
      </Card>

      <Card className="border-border/40">
        <CardHeader className="pb-2"><CardTitle className="text-sm">Session Timeline (IST)</CardTitle></CardHeader>
        <CardContent>
          {[
            { time: "09:00",  label: "Pre-Market",           active: data.session?.includes("PRE_MARKET") },
            { time: "09:00–09:15", label: "Pre-Open Call Auction", active: data.session === "PRE_OPEN_CALL_AUCTION" },
            { time: "09:15–09:30", label: "Price Discovery",  active: data.session === "PRICE_DISCOVERY" },
            { time: "09:30–15:30", label: "Normal Session",   active: data.session === "NORMAL_SESSION" },
            { time: "15:00–15:30", label: "Closing Session",  active: data.session === "CLOSING_SESSION" },
            { time: "15:30+",  label: "After Hours",          active: data.session === "AFTER_HOURS" },
          ].map(({ time, label, active }) => (
            <div key={label} className={`flex items-center gap-3 py-1.5 ${active ? "text-primary" : "text-muted-foreground"}`}>
              <span className="text-xs font-mono w-28 shrink-0">{time}</span>
              <ChevronRight className="w-3 h-3 shrink-0" />
              <span className="text-sm">{label}</span>
              {active && <Badge variant="secondary" className="text-xs ml-auto">CURRENT</Badge>}
            </div>
          ))}
        </CardContent>
      </Card>
    </div>
  );
}

// ── Paper Trading Tab ──────────────────────────────────────────────────────────
function PaperTradingTab() {
  const { data, isLoading } = useQuery(q("paper", 15_000));
  if (isLoading) return <LoadingCard />;
  if (!data?.available) return <DisabledCard message={data?.message} />;

  const pnlColour = data.current_pnl >= 0 ? "text-emerald-400" : "text-red-400";

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        {[
          { label: "Open Positions", value: data.open_positions, icon: <Activity className="w-4 h-4" /> },
          { label: "Today's Trades", value: data.todays_trades,  icon: <BarChart3 className="w-4 h-4" /> },
          { label: "Capital",        value: `₹${data.capital?.toLocaleString("en-IN")}`, icon: <TrendingUp className="w-4 h-4" /> },
          { label: "Cash",           value: `₹${data.cash?.toLocaleString("en-IN")}`,    icon: <Database className="w-4 h-4" /> },
        ].map(({ label, value, icon }) => (
          <Card key={label} className="border-border/40">
            <CardContent className="pt-4">
              <div className="flex items-center gap-2 text-muted-foreground mb-2">{icon}<span className="text-xs">{label}</span></div>
              <div className="text-xl font-bold">{value ?? "—"}</div>
            </CardContent>
          </Card>
        ))}
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <Card className="border-border/40">
          <CardHeader className="pb-2"><CardTitle className="text-sm">Portfolio Metrics</CardTitle></CardHeader>
          <CardContent>
            <MetricRow label="Capital"        value={`₹${data.capital?.toLocaleString("en-IN")}`} />
            <MetricRow label="Cash"           value={`₹${data.cash?.toLocaleString("en-IN")}`} />
            <MetricRow label="Exposure"       value={`₹${data.exposure?.toLocaleString("en-IN")}`} />
            <MetricRow label="Current P&L"    value={<span className={pnlColour}>₹{data.current_pnl?.toLocaleString("en-IN")}</span>} />
            <MetricRow label="Open Positions" value={data.open_positions} />
            <MetricRow label="Today's Trades" value={data.todays_trades} />
          </CardContent>
        </Card>
        <Card className="border-border/40">
          <CardHeader className="pb-2"><CardTitle className="text-sm">P&L Summary</CardTitle></CardHeader>
          <CardContent className="pt-4">
            <div className="text-center">
              <div className={`text-4xl font-bold ${pnlColour}`}>
                ₹{data.current_pnl?.toLocaleString("en-IN")}
              </div>
              <div className="text-xs text-muted-foreground mt-1">Current P&L</div>
              <div className="mt-4 text-sm text-muted-foreground">
                Exposure: ₹{data.exposure?.toLocaleString("en-IN")}
              </div>
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

// ── Risk Tab ───────────────────────────────────────────────────────────────────
function RiskTab() {
  const { data, isLoading } = useQuery(q("risk", 30_000));
  if (isLoading) return <LoadingCard />;
  if (!data?.available) return <DisabledCard message={data?.message ?? "Risk Validation (Phase 8.4) not enabled"} />;

  const domains = [
    { key: "portfolio_score",    label: "Portfolio",    w: "30%" },
    { key: "sector_score",       label: "Sector",       w: "15%" },
    { key: "correlation_score",  label: "Correlation",  w: "10%" },
    { key: "stress_score",       label: "Stress",       w: "10%" },
    { key: "tail_risk_score",    label: "Tail Risk",    w: "10%" },
    { key: "execution_score",    label: "Execution",    w: "10%" },
    { key: "market_risk_score",  label: "Market Risk",  w: "10%" },
    { key: "drift_score",        label: "Drift",        w: "5%"  },
  ];

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <Card className="border-border/40">
          <CardContent className="pt-4 text-center">
            <Shield className="w-5 h-5 mx-auto mb-1 text-primary" />
            <div className="text-2xl font-bold">{data.validation_score ?? "—"}</div>
            <div className="text-xs text-muted-foreground">Risk Score</div>
          </CardContent>
        </Card>
        <Card className="border-border/40">
          <CardContent className="pt-4 text-center">
            <AlertTriangle className="w-5 h-5 mx-auto mb-1 text-yellow-400" />
            <div className="text-2xl font-bold">{data.tail_risk?.var_95 ?? "—"}</div>
            <div className="text-xs text-muted-foreground">VaR 95%</div>
          </CardContent>
        </Card>
        <Card className="border-border/40">
          <CardContent className="pt-4 text-center">
            <Activity className="w-5 h-5 mx-auto mb-1 text-blue-400" />
            <div className="text-2xl font-bold">{data.correlation?.max_pair_correlation ?? "—"}</div>
            <div className="text-xs text-muted-foreground">Max Correlation</div>
          </CardContent>
        </Card>
        <Card className="border-border/40">
          <CardContent className="pt-4 text-center">
            <BarChart3 className="w-5 h-5 mx-auto mb-1 text-red-400" />
            <div className="text-2xl font-bold">{data.stress?.worst_scenario_loss ?? "—"}</div>
            <div className="text-xs text-muted-foreground">Worst Stress Loss</div>
          </CardContent>
        </Card>
      </div>

      <Card className="border-border/40">
        <CardHeader className="pb-2">
          <CardTitle className="text-sm flex items-center justify-between">
            Domain Scores
            {data.grade && <ScoreBadge score={data.validation_score} grade={data.grade} />}
          </CardTitle>
        </CardHeader>
        <CardContent>
          {domains.map(({ key, label, w }) => {
            const score = data[key] ?? data.domains?.[key.replace("_score", "")]?.score ?? null;
            if (score === null) return null;
            return (
              <div key={key} className="mb-3">
                <div className="flex justify-between text-sm mb-1">
                  <span className="text-muted-foreground">{label}</span>
                  <span className="font-medium">{score} <span className="text-xs text-muted-foreground">({w})</span></span>
                </div>
                <div className="w-full bg-border/30 rounded-full h-1.5">
                  <div
                    className={`h-1.5 rounded-full ${score >= 80 ? "bg-emerald-500" : score >= 60 ? "bg-yellow-500" : "bg-red-500"}`}
                    style={{ width: `${score}%` }}
                  />
                </div>
              </div>
            );
          })}
        </CardContent>
      </Card>

      {data.alerts?.length > 0 && (
        <Card className="border-border/40">
          <CardHeader className="pb-2"><CardTitle className="text-sm">Risk Alerts</CardTitle></CardHeader>
          <CardContent>
            {data.alerts.slice(0, 8).map((a: any, i: number) => (
              <div key={i} className="flex items-start gap-2 py-2 border-b border-border/30 last:border-0">
                <SeverityBadge severity={a.severity} />
                <div>
                  <p className="text-sm font-medium">{a.title}</p>
                  <p className="text-xs text-muted-foreground">{a.detail}</p>
                </div>
              </div>
            ))}
          </CardContent>
        </Card>
      )}
    </div>
  );
}

// ── Data Quality Tab ───────────────────────────────────────────────────────────
function DataQualityTab() {
  const { data, isLoading } = useQuery(q("data-quality", 30_000));
  if (isLoading) return <LoadingCard />;
  if (!data?.available) return <DisabledCard message={data?.message ?? "Data Quality (Phase 8.3) not enabled"} />;

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-3 gap-4">
        <Card className="border-border/40">
          <CardContent className="pt-4 text-center">
            <Database className="w-5 h-5 mx-auto mb-1 text-primary" />
            <div className="text-2xl font-bold">{data.quality_score ?? "—"}</div>
            <div className="text-xs text-muted-foreground">Quality Score</div>
            {data.grade && <div className="mt-1"><ScoreBadge score={data.quality_score} grade={data.grade} /></div>}
          </CardContent>
        </Card>
        <Card className="border-border/40">
          <CardContent className="pt-4 text-center">
            <XCircle className="w-5 h-5 mx-auto mb-1 text-red-400" />
            <div className="text-2xl font-bold text-red-400">{data.critical_count ?? 0}</div>
            <div className="text-xs text-muted-foreground">Critical Issues</div>
          </CardContent>
        </Card>
        <Card className="border-border/40">
          <CardContent className="pt-4 text-center">
            <AlertTriangle className="w-5 h-5 mx-auto mb-1 text-yellow-400" />
            <div className="text-2xl font-bold text-yellow-400">{data.warning_count ?? 0}</div>
            <div className="text-xs text-muted-foreground">Warnings</div>
          </CardContent>
        </Card>
      </div>

      <Card className="border-border/40">
        <CardHeader className="pb-2"><CardTitle className="text-sm">Quality Details</CardTitle></CardHeader>
        <CardContent>
          <MetricRow label="Overall Score"    value={<ScoreBadge score={data.quality_score} grade={data.grade} />} />
          <MetricRow label="Critical Issues"  value={<span className="text-red-400 font-semibold">{data.critical_count ?? 0}</span>} />
          <MetricRow label="Warnings"         value={<span className="text-yellow-400">{data.warning_count ?? 0}</span>} />
          <MetricRow label="Total Issues"     value={data.total_issues ?? 0} />
          {data.generated_at && <MetricRow label="Generated"   value={new Date(data.generated_at).toLocaleTimeString()} />}
        </CardContent>
      </Card>

      {data.provider_status && (
        <Card className="border-border/40">
          <CardHeader className="pb-2"><CardTitle className="text-sm">Provider Status</CardTitle></CardHeader>
          <CardContent>
            {Object.entries(data.provider_status).map(([provider, status]: [string, any]) => (
              <div key={provider} className="flex items-center justify-between py-1.5 border-b border-border/30 last:border-0">
                <span className="text-sm text-muted-foreground">{provider}</span>
                <div className="flex items-center gap-1.5">
                  <StatusDot status={String(status?.status ?? status)} />
                  <span className="text-sm">{status?.status ?? String(status)}</span>
                </div>
              </div>
            ))}
          </CardContent>
        </Card>
      )}
    </div>
  );
}

// ── Observability Tab ──────────────────────────────────────────────────────────
function ObservabilityTab() {
  const { data, isLoading } = useQuery(q("observability", 20_000));
  if (isLoading) return <LoadingCard />;
  if (!data?.available) return <DisabledCard message={data?.message ?? "Observability Center (Phase 8.1) not enabled"} />;

  const metrics = [
    { label: "API Health",      key: "api_status",      icon: <Cpu className="w-4 h-4" /> },
    { label: "Database",        key: "db_status",       icon: <Database className="w-4 h-4" /> },
    { label: "Scheduler",       key: "scheduler_status",icon: <Clock className="w-4 h-4" /> },
    { label: "System",          key: "system_status",   icon: <Monitor className="w-4 h-4" /> },
  ];

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        {metrics.map(({ label, key, icon }) => (
          <Card key={key} className="border-border/40">
            <CardContent className="pt-4">
              <div className="flex items-center gap-2 text-muted-foreground mb-2">{icon}<span className="text-xs">{label}</span></div>
              <div className="flex items-center gap-1.5">
                <StatusDot status={data[key] ?? "UNKNOWN"} />
                <span className="text-sm font-medium">{data[key] ?? "UNKNOWN"}</span>
              </div>
            </CardContent>
          </Card>
        ))}
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <Card className="border-border/40">
          <CardHeader className="pb-2"><CardTitle className="text-sm">Performance</CardTitle></CardHeader>
          <CardContent>
            <MetricRow label="Observability Score" value={<ScoreBadge score={data.observability_score} grade={data.grade} />} />
            <MetricRow label="Availability"        value={`${data.availability_pct ?? "—"}%`} />
            <MetricRow label="Performance Score"   value={data.performance_score ?? "—"} />
            <MetricRow label="Error Rate"          value={`${data.error_rate_per_h ?? "—"}/h`} />
            <MetricRow label="Uptime"              value={`${data.uptime_hours ?? "—"}h`} />
          </CardContent>
        </Card>
        <Card className="border-border/40">
          <CardHeader className="pb-2"><CardTitle className="text-sm">System Status</CardTitle></CardHeader>
          <CardContent>
            {["system_status", "db_status", "scheduler_status"].map((k) => (
              <div key={k} className="flex items-center justify-between py-1.5 border-b border-border/30 last:border-0">
                <span className="text-sm text-muted-foreground">{k.replace("_status", "").replace("_", " ").toUpperCase()}</span>
                <div className="flex items-center gap-1.5">
                  <StatusDot status={data[k] ?? "UNKNOWN"} />
                  <span className="text-sm">{data[k] ?? "UNKNOWN"}</span>
                </div>
              </div>
            ))}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

// ── Feature Flags Tab ──────────────────────────────────────────────────────────
function FlagsTab() {
  const { data, isLoading } = useQuery(q("flags", 60_000));
  if (isLoading) return <LoadingCard />;
  if (!data?.available) return <DisabledCard message={data?.message} />;

  const categories = [...new Set((data.flags ?? []).map((f: any) => f.category))] as string[];

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2 px-3 py-2 rounded-lg bg-amber-500/10 border border-amber-500/20 text-amber-400 text-xs">
        <Info className="w-3.5 h-3.5 shrink-0" />
        READ-ONLY — feature flags cannot be modified from this console.
      </div>
      <div className="grid grid-cols-3 gap-4">
        <Card className="border-border/40">
          <CardContent className="pt-4 text-center">
            <ToggleRight className="w-5 h-5 mx-auto mb-1 text-emerald-400" />
            <div className="text-2xl font-bold text-emerald-400">{data.enabled?.length ?? 0}</div>
            <div className="text-xs text-muted-foreground">Enabled</div>
          </CardContent>
        </Card>
        <Card className="border-border/40">
          <CardContent className="pt-4 text-center">
            <ToggleLeft className="w-5 h-5 mx-auto mb-1 text-zinc-400" />
            <div className="text-2xl font-bold">{data.disabled?.length ?? 0}</div>
            <div className="text-xs text-muted-foreground">Disabled</div>
          </CardContent>
        </Card>
        <Card className="border-border/40">
          <CardContent className="pt-4 text-center">
            <Zap className="w-5 h-5 mx-auto mb-1 text-purple-400" />
            <div className="text-2xl font-bold">{data.experimental?.length ?? 0}</div>
            <div className="text-xs text-muted-foreground">Experimental</div>
          </CardContent>
        </Card>
      </div>

      {categories.map((cat) => {
        const catFlags = (data.flags ?? []).filter((f: any) => f.category === cat);
        return (
          <Card key={cat} className="border-border/40">
            <CardHeader className="pb-2">
              <CardTitle className="text-sm capitalize">{cat}</CardTitle>
            </CardHeader>
            <CardContent>
              {catFlags.map((flag: any) => (
                <div key={flag.name} className="flex items-center justify-between py-1.5 border-b border-border/30 last:border-0">
                  <div>
                    <p className="text-sm font-mono text-xs">{flag.name}</p>
                    <p className="text-xs text-muted-foreground">{flag.description}</p>
                  </div>
                  {flag.enabled
                    ? <Badge variant="secondary" className="text-emerald-400 bg-emerald-500/10 border-emerald-500/20 text-xs">ON</Badge>
                    : <Badge variant="outline" className="text-zinc-500 text-xs">OFF</Badge>
                  }
                </div>
              ))}
            </CardContent>
          </Card>
        );
      })}
    </div>
  );
}

// ── Jobs Tab ───────────────────────────────────────────────────────────────────
function JobsTab() {
  const { data, isLoading } = useQuery(q("jobs", 15_000));
  if (isLoading) return <LoadingCard />;
  if (!data?.available) return <DisabledCard message={data?.message} />;

  return (
    <div className="space-y-4">
      <Card className="border-border/40">
        <CardHeader className="pb-2">
          <CardTitle className="text-sm flex items-center justify-between">
            Scheduler
            <div className="flex items-center gap-1.5">
              <StatusDot status={data.scheduler_status} />
              <span className="text-xs">{data.scheduler_status}</span>
            </div>
          </CardTitle>
        </CardHeader>
        <CardContent>
          {data.upcoming_jobs?.length > 0 && (
            <div className="mb-4">
              <p className="text-xs text-muted-foreground mb-2">Upcoming</p>
              {data.upcoming_jobs.map((j: any, i: number) => (
                <div key={i} className="flex items-center gap-2 py-1">
                  <Timer className="w-3.5 h-3.5 text-blue-400" />
                  <span className="text-sm">{j.type}</span>
                  <span className="text-xs text-muted-foreground ml-auto">{j.scheduled_at ? new Date(j.scheduled_at).toLocaleTimeString() : "—"}</span>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      {data.current_jobs?.length > 0 && (
        <Card className="border-border/40">
          <CardHeader className="pb-2"><CardTitle className="text-sm text-blue-400">Running</CardTitle></CardHeader>
          <CardContent>
            {data.current_jobs.map((j: any, i: number) => (
              <div key={i} className="flex items-center gap-2 py-1.5">
                <RefreshCw className="w-3.5 h-3.5 text-blue-400 animate-spin" />
                <span className="text-sm">{j.type}</span>
                <Badge variant="secondary" className="ml-auto text-xs">{j.status}</Badge>
              </div>
            ))}
          </CardContent>
        </Card>
      )}

      {data.failed_jobs?.length > 0 && (
        <Card className="border-border/40">
          <CardHeader className="pb-2"><CardTitle className="text-sm text-red-400">Failed Jobs</CardTitle></CardHeader>
          <CardContent>
            {data.failed_jobs.map((j: any, i: number) => (
              <div key={i} className="flex items-center gap-2 py-1.5 border-b border-border/30 last:border-0">
                <XCircle className="w-3.5 h-3.5 text-red-400" />
                <div>
                  <p className="text-sm">{j.type} — {j.status}</p>
                  <p className="text-xs text-muted-foreground">{j.started_at ? new Date(j.started_at).toLocaleString() : ""}</p>
                </div>
              </div>
            ))}
          </CardContent>
        </Card>
      )}

      {data.recent_jobs?.length > 0 && (
        <Card className="border-border/40">
          <CardHeader className="pb-2"><CardTitle className="text-sm">Recent Jobs</CardTitle></CardHeader>
          <CardContent>
            {data.recent_jobs.slice(0, 10).map((j: any, i: number) => (
              <div key={i} className="flex items-center gap-2 py-1.5 border-b border-border/30 last:border-0">
                <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400" />
                <span className="text-sm">{j.type}</span>
                <span className="text-xs text-muted-foreground ml-auto">{j.duration_s ? `${j.duration_s}s` : ""}</span>
              </div>
            ))}
          </CardContent>
        </Card>
      )}
    </div>
  );
}

// ── Alerts Tab ─────────────────────────────────────────────────────────────────
function AlertsTab() {
  const { data, isLoading } = useQuery(q("alerts", 15_000));
  if (isLoading) return <LoadingCard />;
  if (!data?.available) return <DisabledCard message={data?.message} />;

  const allActive = [...(data.critical ?? []), ...(data.warnings ?? []), ...(data.info ?? [])];

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-3 gap-4">
        <Card className="border-border/40">
          <CardContent className="pt-4 text-center">
            <XCircle className="w-5 h-5 mx-auto mb-1 text-red-400" />
            <div className="text-2xl font-bold text-red-400">{data.critical_count}</div>
            <div className="text-xs text-muted-foreground">Critical</div>
          </CardContent>
        </Card>
        <Card className="border-border/40">
          <CardContent className="pt-4 text-center">
            <AlertTriangle className="w-5 h-5 mx-auto mb-1 text-yellow-400" />
            <div className="text-2xl font-bold text-yellow-400">{data.warning_count}</div>
            <div className="text-xs text-muted-foreground">Warnings</div>
          </CardContent>
        </Card>
        <Card className="border-border/40">
          <CardContent className="pt-4 text-center">
            <Info className="w-5 h-5 mx-auto mb-1 text-blue-400" />
            <div className="text-2xl font-bold text-blue-400">{data.info_count}</div>
            <div className="text-xs text-muted-foreground">Info</div>
          </CardContent>
        </Card>
      </div>

      {allActive.length === 0 ? (
        <Card className="border-border/40">
          <CardContent className="py-12 text-center text-muted-foreground">
            <CheckCircle2 className="w-8 h-8 mx-auto mb-3 text-emerald-400 opacity-60" />
            <p className="text-sm">No active alerts</p>
          </CardContent>
        </Card>
      ) : (
        <Card className="border-border/40">
          <CardHeader className="pb-2"><CardTitle className="text-sm">Active Alerts</CardTitle></CardHeader>
          <CardContent>
            {allActive.map((a: any, i: number) => (
              <div key={a.alert_id ?? i} className="flex items-start gap-3 py-2.5 border-b border-border/30 last:border-0">
                <SeverityBadge severity={a.severity} />
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-medium truncate">{a.title}</p>
                  <p className="text-xs text-muted-foreground">{a.detail}</p>
                  <p className="text-xs text-muted-foreground/60 mt-0.5">{a.source} · {a.generated_at ? new Date(a.generated_at).toLocaleTimeString() : ""}</p>
                </div>
              </div>
            ))}
          </CardContent>
        </Card>
      )}

      {data.resolved?.length > 0 && (
        <Card className="border-border/40">
          <CardHeader className="pb-2"><CardTitle className="text-sm text-muted-foreground">Recently Resolved</CardTitle></CardHeader>
          <CardContent>
            {data.resolved.slice(0, 5).map((a: any, i: number) => (
              <div key={i} className="flex items-center gap-2 py-1.5 opacity-60">
                <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400" />
                <span className="text-sm">{a.title}</span>
              </div>
            ))}
          </CardContent>
        </Card>
      )}
    </div>
  );
}

// ── Checklist Tab ──────────────────────────────────────────────────────────────
function ChecklistTab() {
  const { data, isLoading } = useQuery(q("checklist", 30_000));
  if (isLoading) return <LoadingCard />;
  if (!data?.available) return <DisabledCard message={data?.message} />;

  const phaseLabel: Record<string, string> = {
    MORNING:     "Morning",
    PRE_OPEN:    "Pre-Open",
    MARKET_OPEN: "Market Open",
    MID_SESSION: "Mid-Session",
    CLOSING:     "Closing",
    END_OF_DAY:  "End of Day",
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-sm font-semibold">Daily Operator Checklist</h3>
          <p className="text-xs text-muted-foreground">{phaseLabel[data.phase] ?? data.phase} phase</p>
        </div>
        <div className="text-right">
          <div className="text-2xl font-bold text-primary">{data.completion_pct}%</div>
          <div className="text-xs text-muted-foreground">{data.ok_count}/{data.total} complete</div>
        </div>
      </div>

      <div className="w-full bg-border/30 rounded-full h-2">
        <div
          className={`h-2 rounded-full transition-all ${data.completion_pct >= 80 ? "bg-emerald-500" : data.completion_pct >= 50 ? "bg-yellow-500" : "bg-red-500"}`}
          style={{ width: `${data.completion_pct}%` }}
        />
      </div>

      <Card className="border-border/40">
        <CardContent className="pt-4">
          {(data.items ?? []).map((item: any) => (
            <div key={item.item_id} className="flex items-start gap-3 py-2.5 border-b border-border/30 last:border-0">
              {item.status === "OK"
                ? <CheckCircle2 className="w-4 h-4 text-emerald-400 mt-0.5 shrink-0" />
                : item.status === "WARNING"
                ? <AlertTriangle className="w-4 h-4 text-yellow-400 mt-0.5 shrink-0" />
                : <AlertCircle className="w-4 h-4 text-zinc-500 mt-0.5 shrink-0" />
              }
              <div className="flex-1">
                <p className="text-sm font-medium">{item.title}</p>
                <p className="text-xs text-muted-foreground">{item.description}</p>
                {item.detail && item.detail !== "Manual verification required" && (
                  <p className="text-xs text-muted-foreground/70 mt-0.5">{item.detail}</p>
                )}
              </div>
              <Badge
                variant="outline"
                className={`text-xs shrink-0 ${item.status === "OK" ? "text-emerald-400 border-emerald-500/30" : item.status === "WARNING" ? "text-yellow-400 border-yellow-500/30" : "text-zinc-500"}`}
              >
                {item.status}
              </Badge>
            </div>
          ))}
        </CardContent>
      </Card>
    </div>
  );
}

// ── Timeline Tab ───────────────────────────────────────────────────────────────
function TimelineTab() {
  const { data, isLoading } = useQuery(q("timeline", 30_000));
  if (isLoading) return <LoadingCard />;
  if (!data?.available) return <DisabledCard message={data?.message} />;

  const catIcon: Record<string, React.ReactNode> = {
    SCHEDULER:    <Timer className="w-3.5 h-3.5" />,
    NOTIFICATION: <AlertCircle className="w-3.5 h-3.5" />,
    PLATFORM:     <Activity className="w-3.5 h-3.5" />,
    MARKET:       <Globe className="w-3.5 h-3.5" />,
    DEPLOYMENT:   <Zap className="w-3.5 h-3.5" />,
  };

  return (
    <div className="space-y-2">
      <div className="text-xs text-muted-foreground mb-3">{data.total} events · latest first</div>
      {(data.events ?? []).length === 0 ? (
        <Card className="border-border/40">
          <CardContent className="py-12 text-center text-muted-foreground">
            <Clock className="w-8 h-8 mx-auto mb-3 opacity-40" />
            <p className="text-sm">No timeline events yet</p>
          </CardContent>
        </Card>
      ) : (
        <div className="relative">
          <div className="absolute left-5 top-0 bottom-0 w-px bg-border/40" />
          {(data.events ?? []).map((e: any, i: number) => (
            <div key={e.event_id ?? i} className="flex gap-4 mb-3 relative">
              <div className={`z-10 flex items-center justify-center w-10 h-10 rounded-full border shrink-0
                ${e.severity === "CRITICAL" ? "bg-red-500/10 border-red-500/30 text-red-400" :
                  e.severity === "WARNING"  ? "bg-yellow-500/10 border-yellow-500/30 text-yellow-400" :
                                             "bg-border/30 border-border/40 text-muted-foreground"}`}>
                {catIcon[e.category] ?? <Clock className="w-3.5 h-3.5" />}
              </div>
              <Card className="flex-1 border-border/30">
                <CardContent className="py-2 px-3">
                  <div className="flex items-start justify-between gap-2">
                    <div>
                      <p className="text-sm font-medium">{e.title}</p>
                      {e.detail && <p className="text-xs text-muted-foreground mt-0.5">{e.detail}</p>}
                    </div>
                    <div className="text-right shrink-0">
                      <Badge variant="outline" className="text-xs">{e.category}</Badge>
                      <p className="text-xs text-muted-foreground mt-1">
                        {e.timestamp ? new Date(e.timestamp).toLocaleTimeString() : ""}
                      </p>
                    </div>
                  </div>
                </CardContent>
              </Card>
            </div>
          ))}
        </div>
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
      const url = `${base}/api/operations/export?format=${format}`;
      const res = await fetch(url);
      if (!res.ok) throw new Error(await res.text());
      const blob = await res.blob();
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = `operations_${new Date().toISOString().slice(0, 10)}.${format}`;
      a.click();
    } catch (e: any) {
      alert(`Export failed: ${e.message}`);
    }
  };

  return (
    <div className="space-y-4">
      <Card className="border-border/40">
        <CardHeader className="pb-2"><CardTitle className="text-sm">Export Operations Data</CardTitle></CardHeader>
        <CardContent className="space-y-3">
          <p className="text-sm text-muted-foreground">
            Export a snapshot of all operational data. Exports are advisory-only and do not modify any system state.
          </p>
          <div className="flex gap-3">
            <button
              onClick={() => handleExport("json")}
              className="flex items-center gap-2 px-4 py-2 rounded-lg bg-primary/10 hover:bg-primary/20 border border-primary/20 text-sm transition-colors"
            >
              <Download className="w-4 h-4" />JSON Export
            </button>
            <button
              onClick={() => handleExport("csv")}
              className="flex items-center gap-2 px-4 py-2 rounded-lg bg-secondary hover:bg-secondary/80 border border-border/40 text-sm transition-colors"
            >
              <Download className="w-4 h-4" />CSV Export
            </button>
          </div>
        </CardContent>
      </Card>

      {summary && (
        <Card className="border-border/40">
          <CardHeader className="pb-2"><CardTitle className="text-sm">Current Snapshot</CardTitle></CardHeader>
          <CardContent>
            <MetricRow label="Operations Score" value={<ScoreBadge score={summary.operations_score} grade={summary.grade} />} />
            <MetricRow label="Platform Status"  value={summary.platform_status} />
            <MetricRow label="Outstanding Alerts" value={summary.outstanding_alerts} />
            <MetricRow label="Market"           value={summary.market_open ? "OPEN" : "CLOSED"} />
            <MetricRow label="Session"          value={summary.trading_session?.replace(/_/g, " ")} />
            <MetricRow label="Generated"        value={summary.generated_at ? new Date(summary.generated_at).toLocaleTimeString() : "—"} />
          </CardContent>
        </Card>
      )}
    </div>
  );
}

// ── Main page ──────────────────────────────────────────────────────────────────
export default function OperationsCenter() {
  const { data: summary } = useQuery({ ...q("summary", 20_000), enabled: true });

  const criticalCount = summary?.outstanding_alerts ?? 0;

  return (
    <div className="p-4 md:p-6 max-w-7xl mx-auto space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold flex items-center gap-2">
            <Monitor className="w-5 h-5 text-primary" />
            Operational Control Centre
          </h1>
          <p className="text-sm text-muted-foreground mt-0.5">Phase 8.5 · Read-only operations console</p>
        </div>
        <div className="flex items-center gap-2">
          {criticalCount > 0 && (
            <Badge variant="destructive" className="text-xs">
              {criticalCount} alert{criticalCount !== 1 ? "s" : ""}
            </Badge>
          )}
          {summary && (
            <ScoreBadge score={summary.operations_score} grade={summary.grade} />
          )}
        </div>
      </div>

      <AdvisoryBanner />

      <Tabs defaultValue="overview">
        <TabsList className="flex flex-wrap gap-1 h-auto">
          {[
            { value: "overview",     label: "Overview"    },
            { value: "market",       label: "Market"      },
            { value: "paper",        label: "Paper Trading"},
            { value: "risk",         label: "Risk"        },
            { value: "data-quality", label: "Data Quality"},
            { value: "observability",label: "Observability"},
            { value: "jobs",         label: "Jobs"        },
            { value: "alerts",       label: `Alerts${criticalCount > 0 ? ` (${criticalCount})` : ""}` },
            { value: "checklist",    label: "Checklist"   },
            { value: "timeline",     label: "Timeline"    },
            { value: "export",       label: "Export"      },
          ].map(({ value, label }) => (
            <TabsTrigger key={value} value={value} className="text-xs px-3">
              {label}
            </TabsTrigger>
          ))}
        </TabsList>

        <TabsContent value="overview"      className="mt-4"><OverviewTab /></TabsContent>
        <TabsContent value="market"        className="mt-4"><MarketTab /></TabsContent>
        <TabsContent value="paper"         className="mt-4"><PaperTradingTab /></TabsContent>
        <TabsContent value="risk"          className="mt-4"><RiskTab /></TabsContent>
        <TabsContent value="data-quality"  className="mt-4"><DataQualityTab /></TabsContent>
        <TabsContent value="observability" className="mt-4"><ObservabilityTab /></TabsContent>
        <TabsContent value="jobs"          className="mt-4"><JobsTab /></TabsContent>
        <TabsContent value="alerts"        className="mt-4"><AlertsTab /></TabsContent>
        <TabsContent value="checklist"     className="mt-4"><ChecklistTab /></TabsContent>
        <TabsContent value="timeline"      className="mt-4"><TimelineTab /></TabsContent>
        <TabsContent value="export"        className="mt-4"><ExportTab /></TabsContent>
      </Tabs>
    </div>
  );
}
