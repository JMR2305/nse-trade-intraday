/**
 * RiskManagement.tsx — Phase 11 Institutional Risk Engine dashboard.
 * Portfolio risk overview, pre-trade assessment tool, position sizing,
 * risk alerts, kill switch controls and downloadable risk reports.
 * PAPER TRADING / RESEARCH ONLY — values are honest, "Not Available" when
 * they cannot be computed from real data.
 */

import { useCallback, useEffect, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import {
  Shield, ShieldAlert, ShieldCheck, AlertTriangle, Loader2, Download,
  Power, Play, Gauge, Scale, Bell, RefreshCw,
} from "lucide-react";
import { API_BASE } from "@/lib/api";
import { useToast } from "@/hooks/use-toast";

/* eslint-disable @typescript-eslint/no-explicit-any */

const na = (v: any, suffix = "") =>
  v === null || v === undefined ? "Not Available" : `${v}${suffix}`;

const REPORTS = [
  { kind: "risk_summary", label: "Risk Summary" },
  { kind: "exposure", label: "Exposure" },
  { kind: "correlation", label: "Correlation" },
  { kind: "position_sizing", label: "Position Sizing" },
  { kind: "drawdown", label: "Drawdown" },
];

const verdictColor: Record<string, string> = {
  APPROVE: "text-emerald-400 border-emerald-700",
  APPROVE_WITH_WARNINGS: "text-amber-400 border-amber-700",
  REDUCE: "text-amber-400 border-amber-700",
  REJECT: "text-red-400 border-red-700",
};

const statusColor: Record<string, string> = {
  PASS: "text-emerald-400",
  WARN: "text-amber-400",
  FAIL: "text-red-400",
};

export default function RiskManagement() {
  const { toast } = useToast();
  const [dash, setDash] = useState<any>(null);
  const [alerts, setAlerts] = useState<any>(null);
  const [loading, setLoading] = useState(true);

  // assessment form
  const [form, setForm] = useState({ symbol: "", quantity: "", price: "", stop_loss: "", confidence: "" });
  const [assessing, setAssessing] = useState(false);
  const [assessment, setAssessment] = useState<any>(null);
  const [ksBusy, setKsBusy] = useState(false);
  const [downloading, setDownloading] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [d, a] = await Promise.all([
        fetch(`${API_BASE}/risk/dashboard`).then((r) => r.json()),
        fetch(`${API_BASE}/risk/alerts`).then((r) => r.json()),
      ]);
      setDash(d);
      setAlerts(a);
    } catch (e: any) {
      toast({ title: "Failed to load risk data", description: e.message, variant: "destructive" });
    } finally {
      setLoading(false);
    }
  }, [toast]);

  useEffect(() => { load(); }, [load]);

  const assess = async () => {
    if (!form.symbol || !form.quantity || !form.price) {
      toast({ title: "Symbol, quantity and price are required", variant: "destructive" });
      return;
    }
    setAssessing(true);
    setAssessment(null);
    try {
      const body: any = {
        symbol: form.symbol.trim().toUpperCase(),
        quantity: Number(form.quantity),
        price: Number(form.price),
      };
      if (form.stop_loss) body.stop_loss = Number(form.stop_loss);
      if (form.confidence) body.confidence = Number(form.confidence);
      const r = await fetch(`${API_BASE}/risk/assess`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const d = await r.json();
      if (!r.ok || d.error) throw new Error(d.error ?? `HTTP ${r.status}`);
      setAssessment(d);
    } catch (e: any) {
      toast({ title: "Assessment failed", description: e.message, variant: "destructive" });
    } finally {
      setAssessing(false);
    }
  };

  const killSwitch = async (action: "trigger" | "resume") => {
    if (action === "trigger" && !window.confirm(
      "Trigger the kill switch? All paper buys will be blocked until you explicitly acknowledge and resume.")) return;
    if (action === "resume" && !window.confirm(
      "Acknowledge the risk event and resume paper trading? This confirms you have reviewed the trigger reason.")) return;
    setKsBusy(true);
    try {
      const r = await fetch(`${API_BASE}/risk/kill-switch/${action}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(action === "resume" ? { acknowledge: true } : { reason: "Manual trigger from Risk Management page" }),
      });
      const d = await r.json();
      if (!r.ok || d.error) throw new Error(d.error ?? `HTTP ${r.status}`);
      toast({ title: action === "trigger" ? "Kill switch ACTIVE — paper trading halted (simulated)" : "Trading resumed" });
      await load();
    } catch (e: any) {
      toast({ title: "Kill switch action failed", description: e.message, variant: "destructive" });
    } finally {
      setKsBusy(false);
    }
  };

  const download = async (kind: string) => {
    setDownloading(kind);
    try {
      const r = await fetch(`${API_BASE}/risk/report/${kind}`);
      if (!r.ok) {
        const d = await r.json().catch(() => ({}));
        throw new Error(d.error ?? `HTTP ${r.status}`);
      }
      const blob = await r.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `phase11_${kind}_report.csv`;
      document.body.appendChild(a); a.click(); document.body.removeChild(a);
      URL.revokeObjectURL(url);
    } catch (e: any) {
      toast({ title: "Report download failed", description: e.message, variant: "destructive" });
    } finally {
      setDownloading(null);
    }
  };

  const ksActive = dash?.kill_switch?.active;

  return (
    <div className="space-y-6 font-mono">
      <div className="flex flex-wrap items-center gap-3">
        <Shield className="h-5 w-5 text-primary" />
        <h1 className="text-xl font-bold text-foreground">Risk Management</h1>
        <Badge variant="outline" className="text-[10px] text-amber-400 border-amber-700">
          PAPER TRADING / RESEARCH ONLY
        </Badge>
        <Button size="sm" variant="outline" className="ml-auto gap-2" onClick={load} disabled={loading}>
          {loading ? <Loader2 className="h-3 w-3 animate-spin" /> : <RefreshCw className="h-3 w-3" />}Refresh
        </Button>
      </div>

      {/* Kill switch banner */}
      <Card className={`border ${ksActive ? "border-red-700 bg-red-950/30" : "border-zinc-800 bg-zinc-900/60"}`}>
        <CardContent className="flex flex-wrap items-center gap-4 px-5 py-4">
          {ksActive
            ? <ShieldAlert className="h-6 w-6 text-red-400" />
            : <ShieldCheck className="h-6 w-6 text-emerald-400" />}
          <div className="min-w-0 flex-1">
            <div className="text-sm font-bold">
              Kill Switch: {ksActive
                ? <span className="text-red-400">ACTIVE — all paper buys blocked (simulated halt)</span>
                : <span className="text-emerald-400">Inactive — trading allowed</span>}
            </div>
            {ksActive && (
              <div className="mt-1 text-xs text-zinc-400">
                Reason: {dash?.kill_switch?.reason ?? "Not Available"} · Triggered {dash?.kill_switch?.triggered_at ?? ""} by {dash?.kill_switch?.triggered_by ?? "?"}
              </div>
            )}
          </div>
          {ksActive ? (
            <Button size="sm" variant="outline" className="gap-2 border-emerald-700 text-emerald-400" disabled={ksBusy}
              onClick={() => killSwitch("resume")}>
              {ksBusy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
              Acknowledge &amp; Resume
            </Button>
          ) : (
            <Button size="sm" variant="outline" className="gap-2 border-red-700 text-red-400" disabled={ksBusy}
              onClick={() => killSwitch("trigger")}>
              {ksBusy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Power className="h-4 w-4" />}
              Trigger Kill Switch
            </Button>
          )}
        </CardContent>
      </Card>

      {/* Portfolio risk overview */}
      <div className="grid gap-4 md:grid-cols-4">
        {[
          { label: "Portfolio Value", value: dash ? `₹${na(dash.portfolio_value)}` : "…" },
          { label: "Portfolio Heat", value: dash ? na(dash.portfolio_heat_pct, "%") : "…",
            sub: dash ? `of ${dash.risk_budget?.max_heat_pct}% budget` : "" },
          { label: "Diversification", value: dash ? na(dash.diversification_score, " / 100") : "…" },
          { label: "Cash Allocation", value: dash ? na(dash.cash_allocation_pct, "%") : "…" },
        ].map((m) => (
          <Card key={m.label} className="border-zinc-800 bg-zinc-900/60">
            <CardContent className="px-5 py-4">
              <div className="text-[10px] uppercase tracking-widest text-zinc-500">{m.label}</div>
              <div className="mt-1 text-lg font-bold text-foreground">{m.value}</div>
              {m.sub && <div className="text-[10px] text-zinc-500">{m.sub}</div>}
            </CardContent>
          </Card>
        ))}
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        {/* Sector allocation + exposures */}
        <Card className="border-zinc-800 bg-zinc-900/60">
          <CardHeader className="px-5 pb-2 pt-4">
            <h2 className="flex items-center gap-2 text-sm font-bold uppercase tracking-widest text-zinc-300">
              <Gauge className="h-4 w-4 text-primary" />Exposure
            </h2>
          </CardHeader>
          <CardContent className="space-y-3 px-5 pb-5 text-xs">
            {dash?.sector_allocation?.length ? dash.sector_allocation.map((s: any) => (
              <div key={s.sector} className="flex items-center justify-between">
                <span className="text-zinc-400">{s.sector}</span>
                <span>₹{s.value} · {s.pct_of_portfolio}%</span>
              </div>
            )) : <div className="text-zinc-500">No open positions</div>}
            {dash?.unbounded_risk_positions?.length > 0 && (
              <div className="rounded border border-amber-800 bg-amber-950/30 p-2 text-amber-400">
                <AlertTriangle className="mr-1 inline h-3 w-3" />
                {dash.unbounded_risk_positions.length} position(s) without stop-loss — risk unbounded, excluded from heat:{" "}
                {dash.unbounded_risk_positions.map((u: any) => u.symbol).join(", ")}
              </div>
            )}
            <div className="border-t border-zinc-800 pt-2 text-zinc-500">
              Drawdowns — daily: {na(dash?.drawdowns?.daily?.drawdown_pct, "%")} · weekly: {na(dash?.drawdowns?.weekly?.drawdown_pct, "%")} · monthly: {na(dash?.drawdowns?.monthly?.drawdown_pct, "%")}
            </div>
            <div className="text-zinc-600">
              Correlation method: {dash?.correlation_matrix?.method ?? "Not Available"}
            </div>
          </CardContent>
        </Card>

        {/* Alerts */}
        <Card className="border-zinc-800 bg-zinc-900/60">
          <CardHeader className="px-5 pb-2 pt-4">
            <h2 className="flex items-center gap-2 text-sm font-bold uppercase tracking-widest text-zinc-300">
              <Bell className="h-4 w-4 text-primary" />Risk Alerts
            </h2>
          </CardHeader>
          <CardContent className="max-h-64 space-y-2 overflow-y-auto px-5 pb-5 text-xs">
            {alerts?.alerts?.length ? alerts.alerts.map((a: any) => (
              <div key={a.key} className="flex items-start gap-2 rounded border border-zinc-800 p-2">
                <AlertTriangle className={`mt-0.5 h-3 w-3 shrink-0 ${a.severity === "CRITICAL" ? "text-red-400" : "text-amber-400"}`} />
                <div>
                  <span className={a.severity === "CRITICAL" ? "text-red-400" : "text-amber-400"}>[{a.severity}] {a.type}</span>
                  <div className="text-zinc-400">{a.message}</div>
                  <div className="text-[10px] text-zinc-600">{a.ts}</div>
                </div>
              </div>
            )) : <div className="text-zinc-500">No alerts</div>}
          </CardContent>
        </Card>
      </div>

      {/* Pre-trade assessment tool */}
      <Card className="border-zinc-800 bg-zinc-900/60">
        <CardHeader className="px-5 pb-2 pt-4">
          <h2 className="flex items-center gap-2 text-sm font-bold uppercase tracking-widest text-zinc-300">
            <Scale className="h-4 w-4 text-primary" />Pre-Trade Risk Assessment (8 checks)
          </h2>
        </CardHeader>
        <CardContent className="space-y-4 px-5 pb-5">
          <div className="grid gap-2 sm:grid-cols-5">
            {(["symbol", "quantity", "price", "stop_loss", "confidence"] as const).map((k) => (
              <Input key={k} placeholder={k === "stop_loss" ? "stop loss (opt)" : k === "confidence" ? "confidence % (opt)" : k}
                value={form[k]} className="text-xs"
                onChange={(e) => setForm({ ...form, [k]: e.target.value })} />
            ))}
          </div>
          <Button size="sm" onClick={assess} disabled={assessing} className="gap-2">
            {assessing ? <Loader2 className="h-4 w-4 animate-spin" /> : <Shield className="h-4 w-4" />}Assess Trade
          </Button>

          {assessment && (
            <div className="space-y-3 rounded border border-zinc-800 p-4 text-xs">
              <div className="flex flex-wrap items-center gap-3">
                <Badge variant="outline" className={verdictColor[assessment.verdict] ?? ""}>{assessment.verdict}</Badge>
                <span className="text-zinc-400">
                  Requested {assessment.requested_quantity} · Recommended {assessment.recommended_quantity}
                </span>
              </div>
              {assessment.reason && <div className="text-red-400">{assessment.reason}</div>}
              {assessment.checks?.map((c: any) => (
                <div key={c.check} className="flex items-start justify-between gap-3 border-t border-zinc-800/60 pt-2">
                  <div>
                    <span className={statusColor[c.status] ?? ""}>[{c.status}]</span>{" "}
                    <span className="text-zinc-300">{c.check}</span>
                    <div className="text-zinc-500">{c.detail}</div>
                  </div>
                  <div className="shrink-0 text-zinc-500">{na(c.value)} / {na(c.limit)}</div>
                </div>
              ))}
              {assessment.sizing?.audit_steps && (
                <details className="text-zinc-500">
                  <summary className="cursor-pointer text-zinc-400">Position sizing audit trail</summary>
                  <ul className="mt-1 list-inside list-disc">
                    {assessment.sizing.audit_steps.map((s: string, i: number) => <li key={i}>{s}</li>)}
                  </ul>
                </details>
              )}
            </div>
          )}
        </CardContent>
      </Card>

      {/* Reports */}
      <Card className="border-zinc-800 bg-zinc-900/60">
        <CardHeader className="px-5 pb-2 pt-4">
          <h2 className="flex items-center gap-2 text-sm font-bold uppercase tracking-widest text-zinc-300">
            <Download className="h-4 w-4 text-primary" />Risk Reports (CSV)
          </h2>
        </CardHeader>
        <CardContent className="flex flex-wrap gap-2 px-5 pb-5">
          {REPORTS.map((r) => (
            <Button key={r.kind} size="sm" variant="outline" className="gap-2" disabled={downloading === r.kind}
              onClick={() => download(r.kind)}>
              {downloading === r.kind ? <Loader2 className="h-3 w-3 animate-spin" /> : <Download className="h-3 w-3" />}
              {r.label}
            </Button>
          ))}
        </CardContent>
      </Card>

      <p className="text-[10px] text-zinc-600">
        All values computed from real paper-trading state and cached scan data. Correlation is a
        sector-proxy estimate (no OHLC history cached). ATR is Not Available — sizing uses actual
        stop-loss distance. No real-money execution exists in this system.
      </p>
    </div>
  );
}
