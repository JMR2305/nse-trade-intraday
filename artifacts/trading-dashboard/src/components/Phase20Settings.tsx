/**
 * Phase20Settings.tsx — Automatic Scanning & Paper Trading settings.
 * Auto-scan controls, entry gates, risk caps, execution model, and the
 * safety-gated auto paper ENTRIES toggle (typed confirmation required).
 * PAPER / RESEARCH ONLY — live orders are always disabled.
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from "@/components/ui/dialog";
import {
  Bot, Loader2, RefreshCw, Save, ShieldAlert, ShieldCheck, AlertTriangle,
  Clock, Gauge, Sliders, Cpu, Lock, Mail, Send, Eye,
} from "lucide-react";
import { API_BASE } from "@/lib/api";
import EmailDeliveryHistory from "@/components/EmailDeliveryHistory";
import { useToast } from "@/hooks/use-toast";

/* eslint-disable @typescript-eslint/no-explicit-any */

interface Phase20SettingsData {
  auto_scan_enabled: boolean;
  scan_interval_minutes: number;
  auto_paper_entries: boolean;
  auto_paper_entries_confirmed_at: string | null;
  auto_paper_exits: boolean;
  min_confidence: number;
  min_opportunity_score: number;
  min_trade_quality_score: number;
  min_risk_reward: number;
  max_trades_per_day: number;
  per_stock_exposure_cap_pct: number;
  sector_exposure_cap_pct: number;
  portfolio_deployed_cap_pct: number;
  risk_per_trade_pct: number;
  daily_loss_limit_pct: number;
  circuit_breaker_loss_threshold: number;
  perf_alert_enabled: boolean;
  perf_alert_consecutive_losses: number;
  perf_alert_min_win_rate_pct: number;
  perf_alert_window_trades: number;
  fill_model: "LAST_TRADED_PRICE" | "NEXT_QUOTE" | "SLIPPAGE_ADJUSTED";
  slippage_pct: number;
  charges_pct: number;
  max_holding_days: number;
  square_off_before_close: boolean;
  cooldown_minutes: number;
  email_alerts_enabled: boolean;
  email_alert_address: string;
  daily_summary_email_enabled: boolean;
  high_conf_avoid_gate_min_failures: number;
  config_hash: string;
  confirmation_text: string;
}

const SCAN_INTERVALS = [1, 3, 5, 10, 15];

const FILL_MODELS: { value: string; label: string; explain: string }[] = [
  {
    value: "LAST_TRADED_PRICE",
    label: "Last Traded Price",
    explain: "Fills at the most recent traded price from the snapshot — simplest, no slippage adjustment.",
  },
  {
    value: "NEXT_QUOTE",
    label: "Next Quote",
    explain: "Fills at the next available quote after the signal — models a small realistic delay.",
  },
  {
    value: "SLIPPAGE_ADJUSTED",
    label: "Slippage Adjusted",
    explain: "Applies the configured slippage % to the fill price — most conservative estimate.",
  },
];

const NUMERIC_ENTRY_GATES: { key: keyof Phase20SettingsData; label: string; step?: string }[] = [
  { key: "min_confidence", label: "Min confidence", step: "0.01" },
  { key: "min_opportunity_score", label: "Min opportunity score", step: "0.01" },
  { key: "min_trade_quality_score", label: "Min trade quality score", step: "0.01" },
  { key: "min_risk_reward", label: "Min risk / reward", step: "0.1" },
  { key: "max_trades_per_day", label: "Max trades per day", step: "1" },
  { key: "cooldown_minutes", label: "Cooldown (minutes)", step: "1" },
];

const NUMERIC_PERF_ALERTS: { key: keyof Phase20SettingsData; label: string; step?: string }[] = [
  { key: "perf_alert_consecutive_losses", label: "Alert after consecutive losses", step: "1" },
  { key: "perf_alert_min_win_rate_pct", label: "Alert if win rate below %", step: "1" },
  { key: "perf_alert_window_trades", label: "Win-rate window (last N trades)", step: "1" },
];

const NUMERIC_RISK_CAPS: { key: keyof Phase20SettingsData; label: string; step?: string }[] = [
  { key: "per_stock_exposure_cap_pct", label: "Per-stock exposure cap %", step: "0.1" },
  { key: "sector_exposure_cap_pct", label: "Sector exposure cap %", step: "0.1" },
  { key: "portfolio_deployed_cap_pct", label: "Portfolio deployed cap %", step: "0.1" },
  { key: "risk_per_trade_pct", label: "Risk per trade %", step: "0.1" },
  { key: "daily_loss_limit_pct", label: "Daily loss limit %", step: "0.1" },
  { key: "circuit_breaker_loss_threshold", label: "Circuit breaker: consecutive-loss limit", step: "1" },
  { key: "max_holding_days", label: "Max holding days", step: "1" },
];

function istDateTime(iso?: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (isNaN(d.getTime())) return String(iso);
  return d.toLocaleString("en-IN", {
    day: "2-digit", month: "short", year: "numeric",
    hour: "2-digit", minute: "2-digit", hour12: true,
    timeZone: "Asia/Kolkata",
  }) + " IST";
}

export default function Phase20Settings() {
  const { toast } = useToast();
  const [server, setServer] = useState<Phase20SettingsData | null>(null);
  const [draft, setDraft] = useState<Phase20SettingsData | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  // Email alerts: provider status + test-send state
  type EmailLastSend = {
    ts?: string; kind?: string; sent?: boolean;
    provider?: string | null; reason?: string | null; error?: string | null;
  };
  const [emailStatus, setEmailStatus] = useState<{
    configured: boolean; provider: string | null; hint?: string;
    last_send?: EmailLastSend | null;
  } | null>(null);
  const [sendingTest, setSendingTest] = useState(false);
  const [sendingSummary, setSendingSummary] = useState(false);

  // Daily summary preview dialog state
  const [previewOpen, setPreviewOpen] = useState(false);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [preview, setPreview] = useState<{ subject: string; text: string; html: string } | null>(null);
  const [previewMode, setPreviewMode] = useState<"html" | "text">("html");
  const [previewKind, setPreviewKind] = useState<"summary" | "alert">("summary");
  const [previewAlertLoading, setPreviewAlertLoading] = useState(false);

  // Auto paper entries confirmation dialog state
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [typed, setTyped] = useState("");
  const [confirming, setConfirming] = useState(false);
  const [confirmError, setConfirmError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await fetch(`${API_BASE}/phase20/settings`);
      const d = await r.json();
      if (!r.ok || d.error) throw new Error(d.error ?? `HTTP ${r.status}`);
      const s: Phase20SettingsData = d.settings;
      setServer(s);
      setDraft(s);
    } catch (e: any) {
      toast({ title: "Failed to load Phase 20 settings", description: e.message, variant: "destructive" });
    } finally {
      setLoading(false);
    }
  }, [toast]);

  useEffect(() => { load(); }, [load]);

  const refreshEmailStatus = useCallback(() => {
    fetch(`${API_BASE}/phase20/email/status`)
      .then((r) => r.json())
      .then((d) => setEmailStatus({
        configured: !!d.configured,
        provider: d.provider ?? null,
        hint: d.hint,
        last_send: d.last_send ?? null,
      }))
      .catch(() => setEmailStatus(null));
  }, []);

  useEffect(() => { refreshEmailStatus(); }, [refreshEmailStatus]);

  const sendTestEmail = async () => {
    setSendingTest(true);
    try {
      const r = await fetch(`${API_BASE}/phase20/email/test`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ address: draft?.email_alert_address ?? "" }),
      });
      const d = await r.json().catch(() => ({}));
      if (!r.ok || d.success === false) throw new Error(d.error ?? `HTTP ${r.status}`);
      toast({ title: "Test email sent", description: `Delivered via ${d.provider ?? "configured provider"} — check your inbox.` });
    } catch (e: any) {
      toast({ title: "Test email failed", description: e.message, variant: "destructive" });
    } finally {
      setSendingTest(false);
      refreshEmailStatus();
    }
  };

  const sendDailySummaryNow = async () => {
    setSendingSummary(true);
    try {
      const r = await fetch(`${API_BASE}/phase20/email/send-daily-summary`, { method: "POST" });
      const d = await r.json().catch(() => ({}));
      if (!r.ok || d.success === false) {
        throw new Error(d.error ?? d.reason ?? `HTTP ${r.status}`);
      }
      toast({
        title: "Daily summary sent",
        description: `Today's summary email was delivered via ${d.provider ?? "configured provider"} — check your inbox.`,
      });
    } catch (e: any) {
      toast({ title: "Daily summary email failed", description: e.message, variant: "destructive" });
    } finally {
      setSendingSummary(false);
      refreshEmailStatus();
    }
  };

  const previewDailySummary = async () => {
    setPreviewLoading(true);
    try {
      const r = await fetch(`${API_BASE}/phase20/email/preview-daily-summary`);
      const d = await r.json().catch(() => ({}));
      if (!r.ok || d.success === false) throw new Error(d.error ?? `HTTP ${r.status}`);
      setPreview({
        subject: String(d.subject ?? ""),
        text: String(d.text ?? ""),
        html: String(d.html ?? ""),
      });
      setPreviewMode(d.html ? "html" : "text");
      setPreviewKind("summary");
      setPreviewOpen(true);
    } catch (e: any) {
      toast({ title: "Preview failed", description: e.message, variant: "destructive" });
    } finally {
      setPreviewLoading(false);
    }
  };

  const previewAlertEmail = async () => {
    setPreviewAlertLoading(true);
    try {
      const r = await fetch(`${API_BASE}/phase20/email/preview-alert`);
      const d = await r.json().catch(() => ({}));
      if (!r.ok || d.success === false) throw new Error(d.error ?? `HTTP ${r.status}`);
      setPreview({
        subject: String(d.subject ?? ""),
        text: String(d.text ?? ""),
        html: String(d.html ?? ""),
      });
      setPreviewMode(d.html ? "html" : "text");
      setPreviewKind("alert");
      setPreviewOpen(true);
    } catch (e: any) {
      toast({ title: "Preview failed", description: e.message, variant: "destructive" });
    } finally {
      setPreviewAlertLoading(false);
    }
  };

  const setField = <K extends keyof Phase20SettingsData>(key: K, value: Phase20SettingsData[K]) => {
    setDraft((prev) => (prev ? { ...prev, [key]: value } : prev));
  };

  const setNumberField = (key: keyof Phase20SettingsData, raw: string) => {
    const num = raw === "" ? 0 : Number(raw);
    if (Number.isNaN(num)) return;
    setField(key, num as any);
  };

  // Compute the changed keys (excludes auto_paper_entries which uses its own flow)
  const changedPatch = useMemo(() => {
    if (!server || !draft) return {} as Record<string, any>;
    const patch: Record<string, any> = {};
    (Object.keys(draft) as (keyof Phase20SettingsData)[]).forEach((k) => {
      if (k === "auto_paper_entries" || k === "auto_paper_entries_confirmed_at"
        || k === "config_hash" || k === "confirmation_text") return;
      if (draft[k] !== server[k]) patch[k] = draft[k];
    });
    return patch;
  }, [server, draft]);

  const hasChanges = Object.keys(changedPatch).length > 0;

  const putSettings = async (patch: Record<string, any>, confirmationText?: string) => {
    const body: any = { patch };
    if (confirmationText !== undefined) body.confirmation_text = confirmationText;
    const r = await fetch(`${API_BASE}/phase20/settings`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const d = await r.json().catch(() => ({}));
    if (!r.ok || d.error) throw new Error(d.error ?? `HTTP ${r.status}`);
    return d;
  };

  const saveSettings = async () => {
    if (!hasChanges) return;
    setSaving(true);
    try {
      const d = await putSettings(changedPatch);
      const s: Phase20SettingsData = d.settings ?? { ...server, ...changedPatch };
      setServer(s);
      setDraft(s);
      toast({ title: "Settings saved", description: "Phase 20 configuration updated." });
    } catch (e: any) {
      toast({ title: "Save failed", description: e.message, variant: "destructive" });
    } finally {
      setSaving(false);
    }
  };

  const disableAutoEntries = async () => {
    setSaving(true);
    try {
      const d = await putSettings({ auto_paper_entries: false });
      const s: Phase20SettingsData = d.settings ?? { ...server!, auto_paper_entries: false };
      setServer(s);
      setDraft((prev) => (prev ? { ...prev, auto_paper_entries: false, auto_paper_entries_confirmed_at: s.auto_paper_entries_confirmed_at } : prev));
      toast({ title: "Auto paper entries disabled" });
    } catch (e: any) {
      toast({ title: "Failed to disable", description: e.message, variant: "destructive" });
    } finally {
      setSaving(false);
    }
  };

  const openConfirm = () => {
    setTyped("");
    setConfirmError(null);
    setConfirmOpen(true);
  };

  const requiredText = server?.confirmation_text ?? "";
  const typedMatches = typed === requiredText && requiredText.length > 0;

  const confirmAutoEntries = async () => {
    if (!typedMatches) return;
    setConfirming(true);
    setConfirmError(null);
    try {
      const d = await putSettings({ auto_paper_entries: true }, typed);
      const s: Phase20SettingsData = d.settings ?? { ...server!, auto_paper_entries: true };
      setServer(s);
      setDraft((prev) => (prev ? { ...prev, auto_paper_entries: true, auto_paper_entries_confirmed_at: s.auto_paper_entries_confirmed_at } : prev));
      setConfirmOpen(false);
      toast({ title: "Auto paper ENTRIES enabled", description: "Simulated paper trades only — no real orders." });
    } catch (e: any) {
      setConfirmError(e.message);
    } finally {
      setConfirming(false);
    }
  };

  if (loading || !draft || !server) {
    return (
      <Card className="border-zinc-800 bg-zinc-900/60">
        <CardContent className="flex items-center gap-2 px-5 py-8 text-xs text-zinc-500">
          <Loader2 className="h-4 w-4 animate-spin" />Loading auto-trading settings…
        </CardContent>
      </Card>
    );
  }

  const autoEntriesOn = server.auto_paper_entries;
  const fillModelExplain = FILL_MODELS.find((f) => f.value === draft.fill_model)?.explain ?? "";

  return (
    <Card className="border-zinc-800 bg-zinc-900/60">
      <CardHeader className="px-5 pb-2 pt-4">
        <div className="flex flex-wrap items-center gap-2">
          <h2 className="flex items-center gap-2 font-mono text-sm font-bold uppercase tracking-widest text-zinc-300">
            <Bot className="h-4 w-4 text-primary" />Automatic Scanning &amp; Paper Trading
          </h2>
          <Badge variant="outline" className="text-[10px] text-amber-400 border-amber-700">
            PAPER / RESEARCH ONLY
          </Badge>
          <Button size="sm" variant="outline" className="ml-auto gap-2 text-xs" onClick={load} disabled={loading}>
            <RefreshCw className="h-3 w-3" />Reload
          </Button>
        </div>
      </CardHeader>

      <CardContent className="space-y-6 px-5 pb-5 text-xs">
        {/* Always-on live-orders-disabled notice */}
        <div className="flex items-center gap-2 rounded border border-emerald-800/60 bg-emerald-950/20 px-3 py-2 text-emerald-300">
          <Lock className="h-3.5 w-3.5 shrink-0" />
          Live orders are DISABLED — simulated paper trades only.
        </div>

        {/* ── Auto paper ENTRIES banner (enabled) ── */}
        {autoEntriesOn && (
          <div className="flex flex-wrap items-center gap-3 rounded border border-amber-600 bg-amber-950/40 px-4 py-3">
            <ShieldAlert className="h-5 w-5 shrink-0 text-amber-400" />
            <div className="min-w-0 flex-1">
              <div className="text-sm font-bold text-amber-300">
                Auto paper ENTRIES are ACTIVE — the system will automatically open simulated trades.
              </div>
              <div className="mt-0.5 text-[11px] text-amber-200/80">
                Confirmed at {istDateTime(server.auto_paper_entries_confirmed_at)} · No real orders will be placed.
              </div>
            </div>
            <Button size="sm" variant="outline" className="gap-2 border-amber-600 text-amber-300"
              disabled={saving} onClick={disableAutoEntries}>
              {saving ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <ShieldCheck className="h-3.5 w-3.5" />}
              Disable
            </Button>
          </div>
        )}

        {/* ── 1. Auto-scan controls ── */}
        <section className="space-y-3">
          <h3 className="flex items-center gap-2 text-[11px] font-bold uppercase tracking-widest text-zinc-400">
            <Clock className="h-3.5 w-3.5 text-primary" />Auto-scan controls
          </h3>
          <div className="flex items-center justify-between rounded border border-zinc-800 px-3 py-2">
            <Label htmlFor="auto_scan_enabled" className="text-zinc-300">Automatic scanning enabled</Label>
            <Switch id="auto_scan_enabled" checked={draft.auto_scan_enabled}
              onCheckedChange={(v) => setField("auto_scan_enabled", v)} />
          </div>
          <div className="grid gap-1.5 sm:max-w-xs">
            <Label className="text-zinc-400">Scan interval</Label>
            <Select value={String(draft.scan_interval_minutes)}
              onValueChange={(v) => setField("scan_interval_minutes", Number(v))}>
              <SelectTrigger className="text-xs"><SelectValue /></SelectTrigger>
              <SelectContent>
                {SCAN_INTERVALS.map((m) => (
                  <SelectItem key={m} value={String(m)} className="text-xs">{m} minute{m > 1 ? "s" : ""}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <p className="text-[11px] text-zinc-500">
            Scans only run during NSE market hours (Asia/Kolkata) and are skipped when the latest
            snapshot is still fresh.
          </p>
        </section>

        {/* ── 2. Entry gate thresholds ── */}
        <section className="space-y-3 border-t border-zinc-800 pt-4">
          <h3 className="flex items-center gap-2 text-[11px] font-bold uppercase tracking-widest text-zinc-400">
            <Sliders className="h-3.5 w-3.5 text-primary" />Entry gate thresholds
          </h3>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {NUMERIC_ENTRY_GATES.map((f) => (
              <div key={f.key} className="grid gap-1.5">
                <Label className="text-zinc-400">{f.label}</Label>
                <Input type="number" step={f.step} className="text-xs"
                  value={String(draft[f.key] ?? "")}
                  onChange={(e) => setNumberField(f.key, e.target.value)} />
              </div>
            ))}
          </div>
        </section>

        {/* ── 2b. Decision engine gate calibration ── */}
        <section className="space-y-3 border-t border-zinc-800 pt-4">
          <h3 className="flex items-center gap-2 text-[11px] font-bold uppercase tracking-widest text-zinc-400">
            <Sliders className="h-3.5 w-3.5 text-primary" />Decision engine gate calibration
          </h3>
          <div className="grid gap-1.5 sm:max-w-xs">
            <Label className="text-zinc-400">
              High-confidence filter gate — min failures to force AVOID
            </Label>
            <Input
              type="number"
              step="1"
              min="1"
              max="10"
              className="text-xs"
              value={String(draft.high_conf_avoid_gate_min_failures ?? 2)}
              onChange={(e) => setNumberField("high_conf_avoid_gate_min_failures", e.target.value)}
            />
            <p className="text-[11px] text-zinc-500">
              When a stock's confidence is ≥ 85 (STRONG_BUY range), this is how many
              filter conditions must fail simultaneously before the risk gate forces{" "}
              <span className="font-semibold text-red-400">AVOID</span>.
              Below this count the stock is demoted to{" "}
              <span className="font-semibold text-amber-400">WATCH</span> so operators
              still see it. Raise for illiquid or mid-cap sectors where individual
              filter noise is higher; set to&nbsp;1 for maximum strictness (any single
              failure forces AVOID). Takes effect on the next Trade Decisions refresh —
              no restart required. Default:&nbsp;2.
            </p>
          </div>
        </section>

        {/* ── 3. Risk caps ── */}
        <section className="space-y-3 border-t border-zinc-800 pt-4">
          <h3 className="flex items-center gap-2 text-[11px] font-bold uppercase tracking-widest text-zinc-400">
            <Gauge className="h-3.5 w-3.5 text-primary" />Risk caps
          </h3>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {NUMERIC_RISK_CAPS.map((f) => (
              <div key={f.key} className="grid gap-1.5">
                <Label className="text-zinc-400">{f.label}</Label>
                <Input type="number" step={f.step} className="text-xs"
                  value={String(draft[f.key] ?? "")}
                  onChange={(e) => setNumberField(f.key, e.target.value)} />
              </div>
            ))}
          </div>
          <div className="flex items-center justify-between rounded border border-zinc-800 px-3 py-2">
            <Label htmlFor="square_off_before_close" className="text-zinc-300">
              Square off before market close
            </Label>
            <Switch id="square_off_before_close" checked={draft.square_off_before_close}
              onCheckedChange={(v) => setField("square_off_before_close", v)} />
          </div>
        </section>

        {/* ── 3b. Performance alerts ── */}
        <section className="space-y-3 border-t border-zinc-800 pt-4">
          <h3 className="flex items-center gap-2 text-[11px] font-bold uppercase tracking-widest text-zinc-400">
            <AlertTriangle className="h-3.5 w-3.5 text-primary" />Performance alerts
          </h3>
          <div className="flex items-center justify-between rounded border border-zinc-800 px-3 py-2">
            <div>
              <Label htmlFor="perf_alert_enabled" className="text-zinc-300">Performance degradation alerts</Label>
              <p className="text-[11px] text-zinc-500">
                Adds a notification when the strategy hits a losing streak or the win rate drops,
                so you can intervene early. Advisory only — never blocks trading.
              </p>
            </div>
            <Switch id="perf_alert_enabled" checked={draft.perf_alert_enabled}
              onCheckedChange={(v) => setField("perf_alert_enabled", v)} />
          </div>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {NUMERIC_PERF_ALERTS.map((f) => (
              <div key={f.key} className="grid gap-1.5">
                <Label className="text-zinc-400">{f.label}</Label>
                <Input type="number" step={f.step} className="text-xs"
                  disabled={!draft.perf_alert_enabled}
                  value={String(draft[f.key] ?? "")}
                  onChange={(e) => setNumberField(f.key, e.target.value)} />
              </div>
            ))}
          </div>
          <p className="text-[11px] text-zinc-500">
            The win-rate rule only evaluates once at least the configured number of closed trades
            exists — small samples never trigger an alert.
          </p>
        </section>

        {/* ── 3c. Email alerts ── */}
        <section className="space-y-3 border-t border-zinc-800 pt-4">
          <h3 className="flex items-center gap-2 text-[11px] font-bold uppercase tracking-widest text-zinc-400">
            <Mail className="h-3.5 w-3.5 text-primary" />Email alerts
          </h3>
          <div className="flex items-center justify-between rounded border border-zinc-800 px-3 py-2">
            <div>
              <Label htmlFor="email_alerts_enabled" className="text-zinc-300">
                Email critical alerts
              </Label>
              <p className="text-[11px] text-zinc-500">
                Also send losing-streak / low-win-rate and circuit-breaker alerts to your email,
                so you're reached even when the dashboard isn't open. Opt-in.
              </p>
            </div>
            <Switch id="email_alerts_enabled" checked={draft.email_alerts_enabled}
              onCheckedChange={(v) => setField("email_alerts_enabled", v)} />
          </div>
          <div className="flex items-center justify-between rounded border border-zinc-800 px-3 py-2">
            <div>
              <Label htmlFor="daily_summary_email_enabled" className="text-zinc-300">
                Daily summary email at market close
              </Label>
              <p className="text-[11px] text-zinc-500">
                After the market closes, email a daily digest — trades, P&amp;L, win rate and open
                positions — to the alert address below. Opt-in, sent once per trading day.
              </p>
            </div>
            <Switch id="daily_summary_email_enabled" checked={draft.daily_summary_email_enabled}
              onCheckedChange={(v) => setField("daily_summary_email_enabled", v)} />
          </div>
          <div className="grid gap-1.5 sm:max-w-sm">
            <Label className="text-zinc-400">Alert email address</Label>
            <Input type="email" placeholder="you@example.com" className="text-xs"
              disabled={!draft.email_alerts_enabled && !draft.daily_summary_email_enabled}
              value={draft.email_alert_address ?? ""}
              onChange={(e) => setField("email_alert_address", e.target.value)} />
          </div>
          <div className="flex flex-wrap items-center gap-3">
            <Button size="sm" variant="outline" className="gap-2 text-xs"
              onClick={sendTestEmail}
              disabled={sendingTest || !(draft.email_alert_address ?? "").trim() || !(emailStatus?.configured)}>
              {sendingTest ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Send className="h-3.5 w-3.5" />}
              Send test email
            </Button>
            <Button size="sm" variant="outline" className="gap-2 text-xs"
              onClick={previewAlertEmail} disabled={previewAlertLoading}>
              {previewAlertLoading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Eye className="h-3.5 w-3.5" />}
              Preview alert email
            </Button>
            <Button size="sm" variant="outline" className="gap-2 text-xs"
              onClick={sendDailySummaryNow}
              disabled={sendingSummary || !(draft.email_alert_address ?? "").trim() || !(emailStatus?.configured)}>
              {sendingSummary ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Mail className="h-3.5 w-3.5" />}
              Send today's summary now
            </Button>
            <Button size="sm" variant="outline" className="gap-2 text-xs"
              onClick={previewDailySummary} disabled={previewLoading}>
              {previewLoading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Eye className="h-3.5 w-3.5" />}
              Preview
            </Button>
            {emailStatus && (emailStatus.configured ? (
              <Badge variant="outline" className="text-[10px] text-emerald-400 border-emerald-800">
                Provider: {emailStatus.provider}
              </Badge>
            ) : (
              <span className="text-[11px] text-amber-400">
                No email provider configured yet — {emailStatus.hint ?? "add a RESEND_API_KEY secret to enable delivery."}
              </span>
            ))}
          </div>
          {emailStatus?.last_send && (
            <div className={`rounded border px-3 py-2 text-[11px] ${
              emailStatus.last_send.sent
                ? "border-emerald-900 bg-emerald-950/30 text-emerald-300"
                : "border-red-900 bg-red-950/30 text-red-300"
            }`}>
              <span className="font-semibold">
                Last email {emailStatus.last_send.sent ? "delivered" : "failed"}:
              </span>{" "}
              {({ alert: "critical alert", daily_summary: "daily summary", test: "test email" } as Record<string, string>)[
                emailStatus.last_send.kind ?? ""
              ] ?? emailStatus.last_send.kind ?? "email"}
              {emailStatus.last_send.ts && (
                <> · {new Date(emailStatus.last_send.ts).toLocaleString()}</>
              )}
              {emailStatus.last_send.sent && emailStatus.last_send.provider && (
                <> · via {emailStatus.last_send.provider}</>
              )}
              {!emailStatus.last_send.sent && (
                <> · {emailStatus.last_send.error ?? emailStatus.last_send.reason ?? "unknown error"}</>
              )}
            </div>
          )}
          {emailStatus && !emailStatus.last_send && (
            <p className="text-[11px] text-zinc-500">
              No email has been sent yet — delivery attempts will be reported here.
            </p>
          )}
          <p className="text-[11px] text-zinc-500">
            "Send test email" delivers a sample alert in the new formatted HTML style — the same
            layout used by performance and circuit-breaker alerts — so you can check how it renders
            in your email client. "Preview alert email" shows the same design here without sending.
          </p>
          <p className="text-[11px] text-zinc-500">
            Delivery failures are logged and never interrupt scanning or paper trading. Remember to
            save settings after changing the address or toggle.
          </p>
          <EmailDeliveryHistory />
        </section>

        {/* ── 4. Execution model ── */}
        <section className="space-y-3 border-t border-zinc-800 pt-4">
          <h3 className="flex items-center gap-2 text-[11px] font-bold uppercase tracking-widest text-zinc-400">
            <Cpu className="h-3.5 w-3.5 text-primary" />Execution model
          </h3>
          <div className="grid gap-1.5 sm:max-w-sm">
            <Label className="text-zinc-400">Fill model</Label>
            <Select value={draft.fill_model}
              onValueChange={(v) => setField("fill_model", v as Phase20SettingsData["fill_model"])}>
              <SelectTrigger className="text-xs"><SelectValue /></SelectTrigger>
              <SelectContent>
                {FILL_MODELS.map((f) => (
                  <SelectItem key={f.value} value={f.value} className="text-xs">{f.label}</SelectItem>
                ))}
              </SelectContent>
            </Select>
            <p className="text-[11px] text-zinc-500">{fillModelExplain}</p>
          </div>
          <div className="grid gap-3 sm:grid-cols-2 lg:max-w-md">
            <div className="grid gap-1.5">
              <Label className="text-zinc-400">Slippage %</Label>
              <Input type="number" step="0.01" className="text-xs"
                value={String(draft.slippage_pct ?? "")}
                onChange={(e) => setNumberField("slippage_pct", e.target.value)} />
            </div>
            <div className="grid gap-1.5">
              <Label className="text-zinc-400">Charges %</Label>
              <Input type="number" step="0.01" className="text-xs"
                value={String(draft.charges_pct ?? "")}
                onChange={(e) => setNumberField("charges_pct", e.target.value)} />
            </div>
          </div>
        </section>

        {/* ── 5. Auto paper EXITS ── */}
        <section className="space-y-3 border-t border-zinc-800 pt-4">
          <h3 className="text-[11px] font-bold uppercase tracking-widest text-zinc-400">
            Automated paper exits
          </h3>
          <div className="flex items-center justify-between rounded border border-zinc-800 px-3 py-2">
            <div>
              <Label htmlFor="auto_paper_exits" className="text-zinc-300">Auto paper EXITS</Label>
              <p className="text-[11px] text-zinc-500">
                Automatically close simulated positions when exit rules trigger (recommended on).
              </p>
            </div>
            <Switch id="auto_paper_exits" checked={draft.auto_paper_exits}
              onCheckedChange={(v) => setField("auto_paper_exits", v)} />
          </div>
        </section>

        {/* ── 6. Auto paper ENTRIES (safety-gated) ── */}
        <section className="space-y-3 border-t border-zinc-800 pt-4">
          <h3 className="flex items-center gap-2 text-[11px] font-bold uppercase tracking-widest text-amber-400">
            <ShieldAlert className="h-3.5 w-3.5" />Auto paper ENTRIES — safety-gated
          </h3>
          <div className="flex items-center justify-between rounded border border-amber-800/60 bg-amber-950/10 px-3 py-2">
            <div className="min-w-0 pr-3">
              <Label className="text-amber-300">Auto paper ENTRIES</Label>
              <p className="text-[11px] text-amber-200/70">
                Default OFF. Enabling requires typing an exact confirmation statement. Simulated
                paper trades only — no real orders are ever placed.
              </p>
            </div>
            <Switch
              checked={autoEntriesOn}
              onCheckedChange={(v) => {
                if (v) openConfirm();
                else disableAutoEntries();
              }}
            />
          </div>
        </section>

        {/* ── 7. Save ── */}
        <div className="flex flex-wrap items-center gap-3 border-t border-zinc-800 pt-4">
          <Button size="sm" className="gap-2" onClick={saveSettings} disabled={saving || !hasChanges}>
            {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
            Save settings
          </Button>
          {hasChanges && (
            <span className="text-[11px] text-amber-400">
              {Object.keys(changedPatch).length} unsaved change(s)
            </span>
          )}
          <span className="ml-auto text-[10px] text-zinc-600">config_hash: {server.config_hash || "—"}</span>
        </div>
      </CardContent>

      {/* ── Daily summary email preview dialog ── */}
      <Dialog open={previewOpen} onOpenChange={setPreviewOpen}>
        <DialogContent className="max-w-2xl font-mono">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <Mail className="h-5 w-5 text-primary" />
              {previewKind === "alert" ? "Alert email preview" : "Daily summary email preview"}
            </DialogTitle>
            <DialogDescription className="text-xs text-zinc-400">
              {previewKind === "alert"
                ? "This is the new formatted style used by critical alerts (performance and circuit-breaker). Nothing has been sent."
                : "This is exactly what today's summary email will contain. Nothing has been sent."}
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-3 text-xs">
            <div className="grid gap-1.5">
              <Label className="text-zinc-400">Subject</Label>
              <div className="rounded border border-zinc-800 bg-zinc-950/60 p-2 text-zinc-200">
                {preview?.subject || "—"}
              </div>
            </div>
            <div className="grid gap-1.5">
              <div className="flex items-center justify-between">
                <Label className="text-zinc-400">Body</Label>
                {preview?.html && (
                  <div className="flex gap-1">
                    <Button
                      size="sm"
                      variant={previewMode === "html" ? "secondary" : "ghost"}
                      className="h-6 px-2 text-[10px]"
                      onClick={() => setPreviewMode("html")}
                    >
                      Formatted
                    </Button>
                    <Button
                      size="sm"
                      variant={previewMode === "text" ? "secondary" : "ghost"}
                      className="h-6 px-2 text-[10px]"
                      onClick={() => setPreviewMode("text")}
                    >
                      Plain text
                    </Button>
                  </div>
                )}
              </div>
              {previewMode === "html" && preview?.html ? (
                <iframe
                  title={previewKind === "alert" ? "Alert email preview" : "Daily summary email preview"}
                  sandbox=""
                  srcDoc={preview.html}
                  className="h-[50vh] w-full rounded border border-zinc-800 bg-white"
                />
              ) : (
                <pre className="max-h-[50vh] overflow-auto whitespace-pre-wrap rounded border border-zinc-800 bg-zinc-950/60 p-3 text-[11px] leading-relaxed text-zinc-200">
                  {preview?.text || "—"}
                </pre>
              )}
            </div>
          </div>
          <DialogFooter>
            <Button size="sm" variant="outline" onClick={() => setPreviewOpen(false)}>
              Close
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* ── Confirmation dialog ── */}
      <Dialog open={confirmOpen} onOpenChange={(o) => { if (!confirming) setConfirmOpen(o); }}>
        <DialogContent className="font-mono">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2 text-amber-400">
              <AlertTriangle className="h-5 w-5" />Enable Auto Paper ENTRIES
            </DialogTitle>
            <DialogDescription className="text-xs text-zinc-400">
              This will let the system automatically open simulated paper trades whenever entry
              gates pass. This is a safety-gated control. No real money and no real broker orders
              are ever involved — paper / research only.
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-3 text-xs">
            <div className="rounded border border-amber-800/60 bg-amber-950/20 p-3 text-amber-200">
              Type the following statement EXACTLY to continue:
              <div className="mt-2 select-all rounded bg-zinc-950/60 p-2 font-semibold text-amber-100">
                {requiredText}
              </div>
            </div>
            <Input
              autoFocus
              placeholder="Type the confirmation statement exactly…"
              className="text-xs"
              value={typed}
              onChange={(e) => { setTyped(e.target.value); setConfirmError(null); }}
            />
            {confirmError && (
              <div className="flex items-start gap-1.5 text-red-400">
                <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />{confirmError}
              </div>
            )}
          </div>

          <DialogFooter>
            <Button size="sm" variant="outline" disabled={confirming}
              onClick={() => setConfirmOpen(false)}>
              Cancel
            </Button>
            <Button size="sm" className="gap-2" disabled={!typedMatches || confirming}
              onClick={confirmAutoEntries}>
              {confirming ? <Loader2 className="h-4 w-4 animate-spin" /> : <ShieldAlert className="h-4 w-4" />}
              Confirm &amp; Enable
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </Card>
  );
}
