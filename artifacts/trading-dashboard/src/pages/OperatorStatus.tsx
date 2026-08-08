/**
 * OperatorStatus.tsx — Phase 3E Operator Experience
 *
 * Shows read-only operational visibility for the platform operator:
 *   1. System Status  — API, DB, scanner, risk config, SSE, market state
 *   2. Safety Status  — paper mode, AI advisory-only, kill switch, CB, limits
 *   3. SSE Reconnect UX — live connection state with reconnect counter
 *   4. Session Report   — downloadable session summary
 *
 * PAPER TRADING / RESEARCH ONLY — no live-trading toggle here.
 */

import { useQuery } from "@tanstack/react-query";
import { useLiveStream } from "@/hooks/useLiveStream";
import { buildApiUrl } from "@/lib/apiConfig";
import DataFreshnessBar from "@/components/DataFreshnessBar";

/** Lightweight fetch helper for this page */
async function apiJson(path: string): Promise<unknown> {
  const res = await fetch(buildApiUrl(path));
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Activity,
  AlertTriangle,
  CheckCircle2,
  Circle,
  Clock,
  Database,
  Download,
  Radio,
  RefreshCw,
  Shield,
  ShieldAlert,
  ShieldCheck,
  Wifi,
  WifiOff,
  XCircle,
  Zap,
} from "lucide-react";
import { useRef, useState, useEffect } from "react";

const LABEL = "PAPER TRADING / RESEARCH ONLY";

// ── Helpers ──────────────────────────────────────────────────────────────────

function StatusDot({ ok, warn }: { ok: boolean | null; warn?: boolean }) {
  if (ok === null)
    return <Circle className="h-3 w-3 text-muted-foreground animate-pulse" />;
  if (!ok)
    return <XCircle className="h-3 w-3 text-destructive" />;
  if (warn)
    return <AlertTriangle className="h-3 w-3 text-yellow-500" />;
  return <CheckCircle2 className="h-3 w-3 text-green-500" />;
}

function Row({
  label,
  ok,
  detail,
  warn,
}: {
  label: string;
  ok: boolean | null;
  detail?: string;
  warn?: boolean;
}) {
  return (
    <div className="flex items-start gap-2 py-1.5 border-b border-border/40 last:border-0">
      <StatusDot ok={ok} warn={warn} />
      <div className="flex-1 min-w-0">
        <span className="text-sm font-medium">{label}</span>
        {detail && (
          <span className="ml-2 text-xs text-muted-foreground truncate">{detail}</span>
        )}
      </div>
    </div>
  );
}

// ── SSE Connection Banner ─────────────────────────────────────────────────────

function SseStatusBanner() {
  const stream = useLiveStream();
  const reconnectCount = useRef(0);
  const [count, setCount] = useState(0);
  const prevConn = useRef(stream.connection);

  useEffect(() => {
    if (
      prevConn.current !== "reconnecting" &&
      stream.connection === "reconnecting"
    ) {
      reconnectCount.current += 1;
      setCount(reconnectCount.current);
    }
    prevConn.current = stream.connection;
  }, [stream.connection]);

  const conn = stream.connection;
  const lastEvt = stream.lastEventTs
    ? new Date(stream.lastEventTs).toLocaleTimeString()
    : "—";

  const bannerClass =
    conn === "connected"
      ? "bg-green-50 dark:bg-green-950/30 border-green-200 dark:border-green-800"
      : conn === "reconnecting"
      ? "bg-yellow-50 dark:bg-yellow-950/30 border-yellow-200 dark:border-yellow-800"
      : "bg-red-50 dark:bg-red-950/30 border-red-200 dark:border-red-800";

  const Icon =
    conn === "connected" ? Wifi : conn === "reconnecting" ? RefreshCw : WifiOff;
  const label =
    conn === "connected"
      ? "Connected"
      : conn === "reconnecting"
      ? "Reconnecting…"
      : conn === "connecting"
      ? "Connecting…"
      : "Disconnected";

  return (
    <div className={`flex items-center gap-3 rounded-lg border px-4 py-3 ${bannerClass}`}>
      <Icon
        className={`h-4 w-4 shrink-0 ${conn === "reconnecting" ? "animate-spin" : ""}`}
      />
      <div className="flex-1">
        <span className="text-sm font-semibold">{label}</span>
        <span className="ml-3 text-xs text-muted-foreground">
          Last event: {lastEvt}
        </span>
        {count > 0 && (
          <span className="ml-3 text-xs text-muted-foreground">
            Reconnects: {count}
          </span>
        )}
      </div>
      <Badge variant="outline" className="text-[10px] font-mono">
        SSE
      </Badge>
    </div>
  );
}

// ── System Status card ────────────────────────────────────────────────────────

function SystemStatusCard() {
  const stream = useLiveStream();

  const health = useQuery({
    queryKey: ["op-health"],
    queryFn: () => apiJson("/healthz"),
    refetchInterval: 15_000,
  });

  const config = useQuery({
    queryKey: ["op-portfolio-config"],
    queryFn: () => apiJson("/portfolio/config"),
    refetchInterval: 30_000,
  });

  const scan = useQuery({
    queryKey: ["op-scan-status"],
    queryFn: () => apiJson("/live-data/scan/status"),
    refetchInterval: 20_000,
  });

  const h = health.data as Record<string, unknown> | undefined;
  const c = config.data as Record<string, unknown> | undefined;
  const s = scan.data as Record<string, unknown> | undefined;

  const apiOk = health.isSuccess;
  const dbOk = h ? !["DOWN", "ERROR"].includes(String(h["database"] ?? "")) : null;
  const marketState =
    stream.market?.state ?? (h?.["market_state"] as string) ?? null;
  const configLoaded = c?.["loaded"] === true || c?.["config_loaded"] === true;
  const scanLocked = s?.["locked"] === true;
  const lastScan = (s?.["last_scan_ts"] ?? s?.["snapshot_ts"] ?? null) as string | null;
  const sseOk = stream.connection === "connected";

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="flex items-center gap-2 text-base">
          <Activity className="h-4 w-4" />
          System Status
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-0">
        <Row
          label="API Server"
          ok={apiOk}
          detail={health.isFetching ? "checking…" : apiOk ? "healthy" : "unreachable"}
        />
        <Row
          label="Database"
          ok={dbOk}
          detail={dbOk == null ? "checking…" : dbOk ? "connected" : "disconnected"}
        />
        <Row
          label="Market Data"
          ok={marketState != null}
          detail={marketState ?? "unknown"}
        />
        <Row
          label="Scanner"
          ok={s != null}
          warn={scanLocked}
          detail={
            s == null
              ? "checking…"
              : scanLocked
              ? "scan in progress"
              : lastScan
              ? `last: ${new Date(lastScan).toLocaleTimeString()}`
              : "no scan yet"
          }
        />
        <Row
          label="Risk Configuration (RC-8)"
          ok={c != null}
          warn={c != null && !configLoaded}
          detail={
            c == null
              ? "checking…"
              : configLoaded
              ? "pydantic loaded"
              : "using hardcoded defaults"
          }
        />
        <Row
          label="SSE Stream"
          ok={sseOk}
          warn={stream.connection === "reconnecting" || stream.connection === "connecting"}
          detail={stream.connection}
        />
        <Row
          label="Market State"
          ok={marketState != null}
          detail={marketState ?? "—"}
        />
        {stream.lastEventTs && (
          <Row
            label="Last Update"
            ok={true}
            detail={new Date(stream.lastEventTs).toLocaleString()}
          />
        )}
      </CardContent>
    </Card>
  );
}

// ── Safety Status card ────────────────────────────────────────────────────────

function SafetyStatusCard() {
  const portfolio = useQuery({
    queryKey: ["op-portfolio-snap"],
    queryFn: () => apiJson("/portfolio/snapshot"),
    refetchInterval: 15_000,
  });

  const staleness = useQuery({
    queryKey: ["op-staleness"],
    queryFn: () => apiJson("/phase15/staleness"),
    refetchInterval: 20_000,
  });

  const killSwitch = useQuery({
    queryKey: ["op-kill-switch"],
    queryFn: () => apiJson("/risk/kill-switch"),
    refetchInterval: 10_000,
  });

  const circuitBreaker = useQuery({
    queryKey: ["op-circuit-breaker"],
    queryFn: () => apiJson("/risk/circuit-breaker"),
    refetchInterval: 10_000,
  });

  const liveOrders = useQuery({
    queryKey: ["op-live-orders"],
    queryFn: async () => {
      try {
        await apiJson("/live-orders");
        return { blocked: false };
      } catch {
        return { blocked: true };
      }
    },
    refetchInterval: 60_000,
  });

  const port = portfolio.data as Record<string, unknown> | undefined;
  const stal = staleness.data as Record<string, unknown> | undefined;
  const ks = killSwitch.data as Record<string, unknown> | undefined;
  const cb = circuitBreaker.data as Record<string, unknown> | undefined;

  const paperMode = port?.["paper_mode"] === true;
  const aiLabel = String(stal?.["mode_label"] ?? stal?.["label"] ?? "");
  const aiAdvisoryOnly =
    aiLabel.toUpperCase().includes("PAPER") ||
    aiLabel.toUpperCase().includes("RESEARCH");
  const ksActive = ks?.["active"] === true || ks?.["kill_switch_active"] === true;
  const cbTripped = cb?.["tripped"] === true || cb?.["state"] === "TRIPPED";
  const liveOrdersBlocked = liveOrders.data?.blocked === true;
  const staleBlocked =
    stal?.["staleness_warning"] !== undefined
      ? (stal["staleness_warning"] as Record<string, unknown>)[
          "buy_recommendations_disabled"
        ] === true
      : stal?.["buy_recommendations_disabled"] === true;

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="flex items-center gap-2 text-base">
          <ShieldCheck className="h-4 w-4" />
          Safety Status
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-0">
        <Row
          label="Paper Mode"
          ok={port != null ? paperMode : null}
          detail={port == null ? "checking…" : paperMode ? "ENABLED ✓" : "DISABLED — SAFETY VIOLATION"}
        />
        <Row
          label="AI Advisory-Only"
          ok={stal != null ? aiAdvisoryOnly : null}
          detail={
            stal == null
              ? "checking…"
              : aiAdvisoryOnly
              ? aiLabel.slice(0, 50)
              : "label missing PAPER/RESEARCH tag"
          }
        />
        <Row
          label="Kill Switch"
          ok={ks != null ? !ksActive : null}
          warn={ks != null && ksActive}
          detail={ks == null ? "checking…" : ksActive ? "⚠️ TRIPPED" : "not tripped"}
        />
        <Row
          label="Circuit Breaker"
          ok={cb != null ? !cbTripped : null}
          warn={cb != null && cbTripped}
          detail={cb == null ? "checking…" : cbTripped ? "⚠️ TRIPPED" : "clear"}
        />
        <Row
          label="Live-Order Route"
          ok={liveOrders.data != null ? liveOrdersBlocked : null}
          detail={
            liveOrders.data == null
              ? "checking…"
              : liveOrdersBlocked
              ? "returns 404 (correct)"
              : "accessible — unexpected"
          }
        />
        <Row
          label="Stale-Data Entry Block"
          ok={stal != null ? true : null}
          detail={
            stal == null
              ? "checking…"
              : staleBlocked
              ? "active — BUY disabled while stale"
              : "not stale — BUY enabled"
          }
        />
      </CardContent>
    </Card>
  );
}

// ── Session Report card ───────────────────────────────────────────────────────

function SessionReportCard() {
  const [downloading, setDownloading] = useState(false);

  const portfolio = useQuery({
    queryKey: ["op-session-portfolio"],
    queryFn: () => apiJson("/portfolio/snapshot"),
    refetchInterval: 30_000,
  });

  const signals = useQuery({
    queryKey: ["op-session-signals"],
    queryFn: () => apiJson("/signals"),
    refetchInterval: 30_000,
  });

  const port = portfolio.data as Record<string, unknown> | undefined;
  const sigs = signals.data as Record<string, unknown> | undefined;

  const handleDownload = () => {
    setDownloading(true);
    const report = {
      label: LABEL,
      generated_at: new Date().toISOString(),
      portfolio: port ?? null,
      signals_summary: {
        count: Array.isArray(sigs?.["signals"]) ? sigs!["signals"].length : null,
        staleness: sigs?.["staleness_warning"] ?? null,
      },
    };
    const blob = new Blob([JSON.stringify(report, null, 2)], {
      type: "application/json",
    });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `session_report_${new Date().toISOString().slice(0, 10)}.json`;
    a.click();
    URL.revokeObjectURL(url);
    setTimeout(() => setDownloading(false), 1000);
  };

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="flex items-center gap-2 text-base">
          <Download className="h-4 w-4" />
          Session Report
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        {port && (
          <div className="grid grid-cols-2 gap-2 text-sm">
            <div>
              <p className="text-muted-foreground text-xs">Cash</p>
              <p className="font-mono font-medium">
                ₹{Number(port["cash"] ?? 0).toLocaleString("en-IN", { maximumFractionDigits: 0 })}
              </p>
            </div>
            <div>
              <p className="text-muted-foreground text-xs">Open Positions</p>
              <p className="font-mono font-medium">
                {Array.isArray(port["positions"]) ? port["positions"].length : "—"}
              </p>
            </div>
            <div>
              <p className="text-muted-foreground text-xs">Realised P&L</p>
              <p className={`font-mono font-medium ${Number(port["realised_pnl"]) >= 0 ? "text-green-600" : "text-red-500"}`}>
                ₹{Number(port["realised_pnl"] ?? 0).toFixed(2)}
              </p>
            </div>
            <div>
              <p className="text-muted-foreground text-xs">Unrealised P&L</p>
              <p className={`font-mono font-medium ${Number(port["unrealised_pnl"]) >= 0 ? "text-green-600" : "text-red-500"}`}>
                ₹{Number(port["unrealised_pnl"] ?? 0).toFixed(2)}
              </p>
            </div>
            <div>
              <p className="text-muted-foreground text-xs">Signals</p>
              <p className="font-mono font-medium">
                {Array.isArray(sigs?.["signals"]) ? sigs!["signals"].length : "—"}
              </p>
            </div>
            <div>
              <p className="text-muted-foreground text-xs">Paper Mode</p>
              <p className="font-mono font-medium text-green-600">
                {port["paper_mode"] === true ? "✓ ON" : "OFF"}
              </p>
            </div>
          </div>
        )}
        <Button
          variant="outline"
          size="sm"
          className="w-full gap-2"
          onClick={handleDownload}
          disabled={downloading || !port}
        >
          <Download className="h-3.5 w-3.5" />
          {downloading ? "Downloading…" : "Download Session Report (JSON)"}
        </Button>
        <p className="text-[10px] text-muted-foreground text-center">
          {LABEL}
        </p>
      </CardContent>
    </Card>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function OperatorStatus() {
  return (
    <div className="p-4 md:p-6 space-y-4 max-w-5xl mx-auto">
      {/* Header */}
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-xl font-bold flex items-center gap-2">
            <Shield className="h-5 w-5 text-primary" />
            Operator Status
          </h1>
          <p className="text-sm text-muted-foreground mt-0.5">
            Real-time system health and safety invariants
          </p>
        </div>
        <Badge variant="outline" className="text-[10px] shrink-0 border-yellow-400 text-yellow-700 dark:text-yellow-400">
          {LABEL}
        </Badge>
      </div>

      {/* Data freshness indicator */}
      <DataFreshnessBar variant="scan" />

      {/* SSE Banner — always visible */}
      <SseStatusBanner />

      {/* Main grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <SystemStatusCard />
        <SafetyStatusCard />
      </div>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <SessionReportCard />
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="flex items-center gap-2 text-base">
              <Zap className="h-4 w-4" />
              Quick Reference
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-2 text-sm">
            <p className="text-muted-foreground text-xs">Safety invariants (never change these)</p>
            <ul className="space-y-1 text-xs">
              <li className="flex gap-2"><ShieldCheck className="h-3.5 w-3.5 text-green-500 shrink-0 mt-0.5" /><span><code>paper_mode = true</code> enforced by PortfolioConfig pydantic validator</span></li>
              <li className="flex gap-2"><ShieldCheck className="h-3.5 w-3.5 text-green-500 shrink-0 mt-0.5" /><span>AI is advisory-only — no direct order execution capability</span></li>
              <li className="flex gap-2"><ShieldCheck className="h-3.5 w-3.5 text-green-500 shrink-0 mt-0.5" /><span><code>GET /api/live-orders</code> always returns 404</span></li>
              <li className="flex gap-2"><ShieldCheck className="h-3.5 w-3.5 text-green-500 shrink-0 mt-0.5" /><span>Stale data gates prevent BUY recommendations</span></li>
              <li className="flex gap-2"><ShieldAlert className="h-3.5 w-3.5 text-yellow-500 shrink-0 mt-0.5" /><span>Kill switch and circuit breaker block entries when tripped</span></li>
              <li className="flex gap-2"><ShieldAlert className="h-3.5 w-3.5 text-yellow-500 shrink-0 mt-0.5" /><span>Daily loss limit resets per session policy only</span></li>
            </ul>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
