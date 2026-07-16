/**
 * Notifications.tsx — Phase 9: Notification Center.
 * Sections: Today's Alerts, Unread, Trade Alerts (incl. executed), Risk Alerts,
 * AI Suggestions, Market Alerts. Mark read (single/all), regenerate, CSV export.
 */

import { useState, useEffect, useCallback } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import {
  Bell, BellRing, RefreshCw, Loader2, Download, CheckCheck,
  AlertTriangle, TrendingUp, Bot, Globe2, ShieldAlert, Inbox,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { API_BASE } from "@/lib/api";
import { useToast } from "@/hooks/use-toast";
import DataFreshnessBar from "@/components/DataFreshnessBar";

/* eslint-disable @typescript-eslint/no-explicit-any */

const SEVERITY_STYLE: Record<string, string> = {
  INFO: "text-sky-400 border-sky-800 bg-sky-950/30",
  WARNING: "text-amber-400 border-amber-800 bg-amber-950/30",
  CRITICAL: "text-red-400 border-red-800 bg-red-950/30",
};

const TABS = [
  { key: "today",         label: "Today's Alerts", icon: Bell },
  { key: "unread",        label: "Unread",         icon: BellRing },
  { key: "trade_alerts",  label: "Trade Alerts",   icon: TrendingUp },
  { key: "risk_alerts",   label: "Risk Alerts",    icon: ShieldAlert },
  { key: "ai_suggestions",label: "AI Suggestions", icon: Bot },
  { key: "market_alerts", label: "Market Alerts",  icon: Globe2 },
] as const;

export default function Notifications() {
  const { toast } = useToast();
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<string>("today");
  const [generating, setGenerating] = useState(false);

  const load = useCallback(async () => {
    setLoading(true); setError(null);
    try {
      const r = await fetch(`${API_BASE}/copilot/alerts?limit=200`);
      const d = JSON.parse(await r.text());
      if (!r.ok || d.error) throw new Error(d.error ?? `HTTP ${r.status}`);
      setData(d);
    } catch (e: any) {
      setError(e.message ?? "Failed to load alerts");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const regenerate = async () => {
    setGenerating(true);
    try {
      const r = await fetch(`${API_BASE}/copilot/alerts/generate`, { method: "POST" });
      const d = JSON.parse(await r.text());
      if (!r.ok || d.error) throw new Error(d.error ?? `HTTP ${r.status}`);
      toast({ title: "Alerts refreshed", description: `${d.new_alerts} new alert(s) from scan ${d.scan_id ?? ""}` });
      await load();
    } catch (e: any) {
      toast({ title: "Generation failed", description: e.message, variant: "destructive" });
    } finally {
      setGenerating(false);
    }
  };

  const markRead = async (alertId: string) => {
    try {
      await fetch(`${API_BASE}/copilot/alerts/read`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ alert_id: alertId }),
      });
      await load();
    } catch (e: any) {
      toast({ title: "Mark read failed", description: e.message, variant: "destructive" });
    }
  };

  const exportCsv = async () => {
    try {
      const resp = await fetch(`${API_BASE}/copilot/export?kind=csv`);
      if (!resp.ok) throw new Error(`Export failed (HTTP ${resp.status})`);
      const blob = await resp.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url; a.download = "phase9_alerts.csv";
      document.body.appendChild(a); a.click(); document.body.removeChild(a);
      URL.revokeObjectURL(url);
      toast({ title: "CSV downloaded", description: "phase9_alerts.csv" });
    } catch (e: any) {
      toast({ title: "Export failed", description: e.message, variant: "destructive" });
    }
  };

  const sections = data?.sections ?? {};
  const list: any[] = sections[tab] ?? [];

  if (loading && !data) return (
    <div className="flex h-64 items-center justify-center gap-3 font-mono text-zinc-500">
      <Loader2 className="h-5 w-5 animate-spin" />Loading notifications…
    </div>
  );

  return (
    <div className="space-y-5 font-mono">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <div className="mb-1 flex items-center gap-3">
            <Bell className="h-5 w-5 text-primary" />
            <h1 className="text-xl font-bold text-foreground">Notification Center</h1>
            <Badge variant="outline" className="text-[10px] text-amber-400 border-amber-700">
              PAPER / LIVE DATA VALIDATION
            </Badge>
            {data?.unread_count > 0 && (
              <Badge className="bg-red-600 text-white text-[10px]">{data.unread_count} unread</Badge>
            )}
          </div>
          <p className="text-xs text-zinc-500">
            Smart alerts generated from the latest cached scan — research only, no auto-trading.
          </p>
        </div>
        <div className="flex gap-2">
          <Button size="sm" variant="outline" onClick={regenerate} disabled={generating} className="gap-2 text-xs">
            {generating ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="h-3.5 w-3.5" />}
            Generate New
          </Button>
          <Button size="sm" variant="outline" onClick={() => markRead("all")} className="gap-2 text-xs">
            <CheckCheck className="h-3.5 w-3.5" />Mark All Read
          </Button>
          <Button size="sm" variant="outline" onClick={exportCsv} className="gap-2 text-xs">
            <Download className="h-3.5 w-3.5" />Export CSV
          </Button>
        </div>
      </div>

      <DataFreshnessBar variant="none" />

      {error && (
        <div className="rounded-md border border-red-800 bg-red-950/30 p-3 text-xs text-red-300">
          <AlertTriangle className="mr-1 inline h-3.5 w-3.5" />{error}
        </div>
      )}

      {/* Tabs */}
      <div className="flex flex-wrap gap-1.5">
        {TABS.map(({ key, label, icon: Icon }) => {
          const count = (sections[key] ?? []).length;
          return (
            <button key={key} onClick={() => setTab(key)}
              className={cn(
                "flex items-center gap-1.5 rounded-md border px-3 py-1.5 text-xs transition-colors",
                tab === key
                  ? "border-primary/60 bg-primary/10 text-primary"
                  : "border-zinc-700 bg-zinc-900 text-zinc-400 hover:border-zinc-500"
              )}>
              <Icon className="h-3.5 w-3.5" />{label}
              <span className="text-[10px] opacity-60">({count})</span>
            </button>
          );
        })}
      </div>

      {/* Alert list */}
      {list.length === 0 ? (
        <Card className="border-zinc-800 bg-zinc-900/60">
          <CardContent className="flex flex-col items-center gap-2 py-12 text-zinc-500">
            <Inbox className="h-8 w-8" />
            <div className="text-sm">No alerts in this section</div>
            <div className="text-xs">Click "Generate New" to analyze the latest scan</div>
          </CardContent>
        </Card>
      ) : (
        <div className="space-y-2">
          {list.map((a: any) => (
            <div key={a.alert_id}
              className={cn(
                "rounded-lg border p-3.5 transition-colors",
                a.read ? "border-zinc-800 bg-zinc-900/40 opacity-70" : "border-zinc-700 bg-zinc-900/80"
              )}>
              <div className="flex flex-wrap items-center gap-2">
                <Badge variant="outline" className={cn("text-[10px]", SEVERITY_STYLE[a.severity] ?? "")}>
                  {a.severity}
                </Badge>
                <span className="text-xs font-bold text-zinc-200">{String(a.type).replace(/_/g, " ")}</span>
                {a.symbol && <Badge variant="outline" className="text-[10px] text-zinc-300 border-zinc-600">{a.symbol}</Badge>}
                {a.confidence != null && (
                  <span className="text-[10px] text-zinc-500">Confidence {Math.round(a.confidence)}</span>
                )}
                <span className="ml-auto text-[10px] text-zinc-600">{a.ts}</span>
                {!a.read && (
                  <button onClick={() => markRead(a.alert_id)}
                    className="text-[10px] text-sky-400 hover:text-sky-300">mark read</button>
                )}
              </div>
              <div className="mt-1.5 text-xs text-zinc-400">{a.reason}</div>
              {a.action_recommendation && (
                <div className="mt-1 text-[10px] text-emerald-400/80">→ {a.action_recommendation}</div>
              )}
            </div>
          ))}
        </div>
      )}

      <div className="text-center text-[10px] text-zinc-600">
        {data?.total ?? 0} total alerts stored · deduplicated per scan · max 500 retained
      </div>
    </div>
  );
}
