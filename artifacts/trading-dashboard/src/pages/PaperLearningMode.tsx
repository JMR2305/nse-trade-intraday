/**
 * PaperLearningMode.tsx
 * Paper Intraday Learning / Exploration Mode dashboard.
 *
 * Shows the operator:
 *  - Toggle to enable exploration mode (SIZE_REDUCED_TO_CAP + EXPERIMENTAL_BUY_FROM_WATCH)
 *  - Daily budget usage bars
 *  - Config sliders for all 5 exploration parameters
 *  - Experimental trades table (read-only, separate from canonical portfolio)
 *  - Blocked candidates panel (why didn't the engine enter?)
 *  - Learning observations card (per-rule win rates, MFE/MAE)
 *  - Daily report download button
 *
 * SAFETY: exploration trades live in experimental_paper_trades only.
 * They never touch the canonical phase20_paper_trades table, portfolio cash,
 * positions, or the daily trade counter. LIVE_EXECUTION_ENABLED remains false.
 */

import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiJson } from "@/lib/api";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import { Label } from "@/components/ui/label";
import { Slider } from "@/components/ui/slider";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { useToast } from "@/hooks/use-toast";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  FlaskConical,
  TrendingUp,
  TrendingDown,
  RefreshCw,
  Download,
  Info,
  AlertTriangle,
  CheckCircle,
  XCircle,
  Clock,
  Shield,
} from "lucide-react";

// ── Types ─────────────────────────────────────────────────────────────────────

interface ExplorationBudget {
  trades_used: number;
  trades_remaining: number;
  exposure_used_pct: number;
  exposure_remaining_pct: number;
  max_trades_per_day: number;
  max_total_exposure_pct: number;
}

interface ExplorationCandidate {
  symbol: string;
  rule_type: "SIZE_REDUCED_TO_CAP" | "EXPERIMENTAL_BUY_FROM_WATCH";
  price: number;
  confidence: number;
  rr_ratio: number;
  quantity: number;
  blocked_reason?: string;
  eligible: boolean;
}

interface LearningObs {
  rule_type: string;
  trades: number;
  win_rate_pct: number;
  avg_mfe_pct: number;
  avg_mae_pct: number;
  observation: string;
}

interface ExplorationStatus {
  success: boolean;
  enabled: boolean;
  settings: Record<string, number | boolean | string>;
  budget: ExplorationBudget;
  candidates: ExplorationCandidate[];
  open_trades: ExperimentalTrade[];
  learning_summary: LearningObs[];
  hard_gates_blocked: string[];
  last_tick_at?: string;
  error?: string;
}

interface ExperimentalTrade {
  id: number;
  symbol: string;
  rule_type: string;
  quantity: number;
  entry_price: number;
  stop_price: number;
  target_price: number;
  entry_ts: string;
  exit_ts?: string;
  exit_price?: number;
  status: "OPEN" | "CLOSED" | "STOPPED_OUT";
  realized_pnl?: number;
  mfe_pct?: number;
  mae_pct?: number;
  confidence: number;
  rr_ratio: number;
  notes?: string;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function fmtPct(v?: number | null) {
  if (v == null) return "—";
  const sign = v >= 0 ? "+" : "";
  return `${sign}${v.toFixed(2)}%`;
}

function fmtPrice(v?: number | null) {
  if (v == null) return "—";
  return `₹${Number(v).toLocaleString("en-IN", { maximumFractionDigits: 2 })}`;
}

function fmtTs(ts?: string | null) {
  if (!ts) return "—";
  try {
    return new Date(ts).toLocaleString("en-IN", {
      timeZone: "Asia/Kolkata",
      dateStyle: "short",
      timeStyle: "short",
    });
  } catch {
    return ts;
  }
}

function StatusBadge({ status }: { status: string }) {
  const map: Record<string, string> = {
    OPEN: "bg-blue-500/20 text-blue-400 border-blue-500/30",
    CLOSED: "bg-green-500/20 text-green-400 border-green-500/30",
    STOPPED_OUT: "bg-red-500/20 text-red-400 border-red-500/30",
  };
  return (
    <span
      className={`px-2 py-0.5 rounded text-xs font-medium border ${map[status] ?? "bg-slate-500/20 text-slate-300 border-slate-500/30"}`}
    >
      {status.replace("_", " ")}
    </span>
  );
}

function RuleTypeBadge({ rule }: { rule: string }) {
  if (rule === "SIZE_REDUCED_TO_CAP")
    return (
      <span className="px-2 py-0.5 rounded text-xs font-medium bg-violet-500/20 text-violet-300 border border-violet-500/30">
        SIZE REDUCED
      </span>
    );
  return (
    <span className="px-2 py-0.5 rounded text-xs font-medium bg-amber-500/20 text-amber-300 border border-amber-500/30">
      WATCH PROBE
    </span>
  );
}

function BudgetBar({
  used,
  total,
  label,
  unit,
}: {
  used: number;
  total: number;
  label: string;
  unit: string;
}) {
  const pct = total > 0 ? Math.min((used / total) * 100, 100) : 0;
  const color = pct >= 90 ? "bg-red-500" : pct >= 60 ? "bg-amber-500" : "bg-teal-500";
  return (
    <div className="space-y-1">
      <div className="flex justify-between text-xs text-slate-400">
        <span>{label}</span>
        <span>
          {unit === "%"
            ? `${used.toFixed(1)}% / ${total}%`
            : `${used} / ${total}`}
        </span>
      </div>
      <div className="h-1.5 rounded-full bg-slate-700 overflow-hidden">
        <div
          className={`h-full rounded-full ${color} transition-all`}
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}

// ── Config Panel ──────────────────────────────────────────────────────────────

function ConfigPanel({
  settings,
  onSave,
  saving,
}: {
  settings: Record<string, number | boolean | string>;
  onSave: (patch: Record<string, number | boolean>) => void;
  saving: boolean;
}) {
  const [local, setLocal] = React.useState<Record<string, number>>({
    exploration_max_pct_per_trade: Number(settings.exploration_max_pct_per_trade ?? 5),
    exploration_max_trades_per_day: Number(settings.exploration_max_trades_per_day ?? 2),
    exploration_max_total_exposure_pct: Number(
      settings.exploration_max_total_exposure_pct ?? 10
    ),
    exploration_min_rr: Number(settings.exploration_min_rr ?? 1.2),
    exploration_min_confidence: Number(settings.exploration_min_confidence ?? 60),
  });

  return (
    <div className="space-y-5 mt-2">
      <div className="space-y-2">
        <Label className="text-xs text-slate-400">
          Max % per trade:{" "}
          <span className="text-white font-medium">
            {local.exploration_max_pct_per_trade}%
          </span>
        </Label>
        <Slider
          min={1}
          max={20}
          step={0.5}
          value={[local.exploration_max_pct_per_trade]}
          onValueChange={([v]) =>
            setLocal((p) => ({ ...p, exploration_max_pct_per_trade: v }))
          }
        />
        <p className="text-[11px] text-slate-500">
          Max portfolio allocation per experimental trade (cap is also bounded by
          the 20% pre-trade hard limit).
        </p>
      </div>

      <div className="space-y-2">
        <Label className="text-xs text-slate-400">
          Max trades / day:{" "}
          <span className="text-white font-medium">
            {local.exploration_max_trades_per_day}
          </span>
        </Label>
        <Slider
          min={1}
          max={10}
          step={1}
          value={[local.exploration_max_trades_per_day]}
          onValueChange={([v]) =>
            setLocal((p) => ({ ...p, exploration_max_trades_per_day: v }))
          }
        />
      </div>

      <div className="space-y-2">
        <Label className="text-xs text-slate-400">
          Max total exposure:{" "}
          <span className="text-white font-medium">
            {local.exploration_max_total_exposure_pct}%
          </span>
        </Label>
        <Slider
          min={1}
          max={50}
          step={1}
          value={[local.exploration_max_total_exposure_pct]}
          onValueChange={([v]) =>
            setLocal((p) => ({
              ...p,
              exploration_max_total_exposure_pct: v,
            }))
          }
        />
      </div>

      <div className="space-y-2">
        <Label className="text-xs text-slate-400">
          Min Risk:Reward:{" "}
          <span className="text-white font-medium">
            {local.exploration_min_rr.toFixed(1)}
          </span>
        </Label>
        <Slider
          min={0.5}
          max={5}
          step={0.1}
          value={[local.exploration_min_rr]}
          onValueChange={([v]) =>
            setLocal((p) => ({
              ...p,
              exploration_min_rr: Math.round(v * 10) / 10,
            }))
          }
        />
      </div>

      <div className="space-y-2">
        <Label className="text-xs text-slate-400">
          Min confidence:{" "}
          <span className="text-white font-medium">
            {local.exploration_min_confidence}%
          </span>
        </Label>
        <Slider
          min={40}
          max={95}
          step={1}
          value={[local.exploration_min_confidence]}
          onValueChange={([v]) =>
            setLocal((p) => ({ ...p, exploration_min_confidence: v }))
          }
        />
      </div>

      <Button
        size="sm"
        onClick={() => onSave(local)}
        disabled={saving}
        className="w-full bg-teal-600 hover:bg-teal-700"
      >
        {saving ? "Saving…" : "Save Configuration"}
      </Button>
    </div>
  );
}

// ── Main Page ─────────────────────────────────────────────────────────────────

import React, { useState } from "react";

export default function PaperLearningMode() {
  const queryClient = useQueryClient();
  const { toast } = useToast();
  const [showConfig, setShowConfig] = useState(false);

  // ── Data ──────────────────────────────────────────────────────────────────

  const { data: status, isLoading, refetch } = useQuery<ExplorationStatus>({
    queryKey: ["exploration-status"],
    queryFn: () => apiJson("paper/exploration/status"),
    refetchInterval: 30_000,
    staleTime: 15_000,
  });

  const { data: tradesData } = useQuery<{ success: boolean; trades: ExperimentalTrade[] }>(
    {
      queryKey: ["exploration-trades"],
      queryFn: () => apiJson("paper/exploration/trades?limit=100"),
      refetchInterval: 60_000,
      staleTime: 30_000,
    }
  );

  // ── Mutations ─────────────────────────────────────────────────────────────

  const toggleMutation = useMutation({
    mutationFn: (enabled: boolean) =>
      apiJson("paper/exploration/settings", {
        method: "PUT",
        body: JSON.stringify({ patch: { paper_exploration_mode: enabled } }),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["exploration-status"] });
      toast({ title: "Exploration mode updated" });
    },
    onError: (e: Error) =>
      toast({ title: "Error", description: e.message, variant: "destructive" }),
  });

  const configMutation = useMutation({
    mutationFn: (patch: Record<string, number | boolean>) =>
      apiJson("paper/exploration/settings", {
        method: "PUT",
        body: JSON.stringify({ patch }),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["exploration-status"] });
      setShowConfig(false);
      toast({ title: "Configuration saved" });
    },
    onError: (e: Error) =>
      toast({ title: "Error", description: e.message, variant: "destructive" }),
  });

  const downloadReport = async () => {
    try {
      const data = await apiJson("paper/exploration/report");
      const text = data?.markdown ?? JSON.stringify(data, null, 2);
      const blob = new Blob([text], { type: "text/markdown" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `exploration_report_${new Date().toISOString().slice(0, 10)}.md`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (e: unknown) {
      toast({
        title: "Report failed",
        description: e instanceof Error ? e.message : String(e),
        variant: "destructive",
      });
    }
  };

  // ── Derived ───────────────────────────────────────────────────────────────

  const enabled = status?.enabled ?? false;
  const budget = status?.budget;
  const candidates = status?.candidates ?? [];
  const learning = status?.learning_summary ?? [];
  const hardBlocked = status?.hard_gates_blocked ?? [];
  const allTrades = tradesData?.trades ?? [];
  const closedTrades = allTrades.filter((t) => t.status !== "OPEN");

  // ── Render ────────────────────────────────────────────────────────────────

  return (
    <div className="min-h-screen bg-slate-950 text-white p-6 space-y-6">
      {/* ── Header ────────────────────────────────────────────────────────── */}
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div className="flex items-center gap-3">
          <div className="p-2 bg-violet-500/20 rounded-lg border border-violet-500/30">
            <FlaskConical className="w-5 h-5 text-violet-400" />
          </div>
          <div>
            <h1 className="text-xl font-bold text-white">
              Paper Intraday Learning Mode
            </h1>
            <p className="text-xs text-slate-400 mt-0.5">
              Risk-taking exploration in a sandboxed portfolio — never touches
              the canonical phase20 positions or live orders
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <Button
            variant="ghost"
            size="sm"
            onClick={() => refetch()}
            className="text-slate-400 hover:text-white"
          >
            <RefreshCw className="w-3.5 h-3.5 mr-1" />
            Refresh
          </Button>
          <Button
            variant="outline"
            size="sm"
            onClick={downloadReport}
            className="border-slate-600 text-slate-300 hover:text-white"
          >
            <Download className="w-3.5 h-3.5 mr-1" />
            Download Report
          </Button>
        </div>
      </div>

      {/* ── Safety banner ─────────────────────────────────────────────────── */}
      <Alert className="border-violet-500/30 bg-violet-950/30">
        <Shield className="w-4 h-4 text-violet-400" />
        <AlertDescription className="text-xs text-slate-300 ml-2">
          <strong className="text-violet-300">Exploration sandbox:</strong>{" "}
          Experimental trades live in <code>experimental_paper_trades</code> only.
          Hard safety gates (market closed, stale data &gt;15 min, circuit
          breaker, data quality UNAVAILABLE) are always enforced.{" "}
          <strong>LIVE_EXECUTION_ENABLED remains false.</strong>
        </AlertDescription>
      </Alert>

      {/* ── Hard gate alerts ──────────────────────────────────────────────── */}
      {hardBlocked.length > 0 && (
        <Alert className="border-amber-500/30 bg-amber-950/30">
          <AlertTriangle className="w-4 h-4 text-amber-400" />
          <AlertDescription className="text-xs text-slate-300 ml-2">
            <strong className="text-amber-300">Hard gates active:</strong>{" "}
            {hardBlocked.join(" · ")} — no new exploration entries until
            resolved.
          </AlertDescription>
        </Alert>
      )}

      {isLoading && (
        <div className="text-center text-slate-500 py-12">Loading…</div>
      )}

      {status?.error && (
        <Alert className="border-red-500/30 bg-red-950/30">
          <XCircle className="w-4 h-4 text-red-400" />
          <AlertDescription className="text-xs text-red-300 ml-2">
            {status.error}
          </AlertDescription>
        </Alert>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* ── Left column: toggle + config + budget ─────────────────────── */}
        <div className="space-y-4">
          {/* Toggle card */}
          <Card className="bg-slate-900 border-slate-700">
            <CardHeader className="pb-3">
              <CardTitle className="text-sm font-medium flex items-center gap-2">
                <FlaskConical className="w-4 h-4 text-violet-400" />
                Exploration Mode
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm text-white font-medium">
                    {enabled ? "Enabled" : "Disabled"}
                  </p>
                  <p className="text-xs text-slate-500 mt-0.5">
                    {enabled
                      ? "Scheduler will probe exploration candidates every tick"
                      : "Enable to let the AI take calculated risks in sandbox"}
                  </p>
                </div>
                <Switch
                  checked={enabled}
                  onCheckedChange={(v) => toggleMutation.mutate(v)}
                  disabled={toggleMutation.isPending}
                />
              </div>

              {status?.last_tick_at && (
                <div className="flex items-center gap-1.5 text-xs text-slate-500">
                  <Clock className="w-3 h-3" />
                  Last tick: {fmtTs(status.last_tick_at)}
                </div>
              )}

              <Button
                variant="ghost"
                size="sm"
                className="w-full text-slate-400 hover:text-white text-xs"
                onClick={() => setShowConfig((s) => !s)}
              >
                {showConfig ? "Hide" : "Show"} Configuration
              </Button>

              {showConfig && status?.settings && (
                <ConfigPanel
                  settings={status.settings}
                  onSave={(patch) => configMutation.mutate(patch)}
                  saving={configMutation.isPending}
                />
              )}
            </CardContent>
          </Card>

          {/* Budget card */}
          {budget && (
            <Card className="bg-slate-900 border-slate-700">
              <CardHeader className="pb-3">
                <CardTitle className="text-sm font-medium">
                  Daily Budget
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
                <BudgetBar
                  used={budget.trades_used}
                  total={budget.max_trades_per_day}
                  label="Trades used"
                  unit="count"
                />
                <BudgetBar
                  used={budget.exposure_used_pct}
                  total={budget.max_total_exposure_pct}
                  label="Exposure"
                  unit="%"
                />
                <div className="pt-1 grid grid-cols-2 gap-2 text-center">
                  <div className="bg-slate-800 rounded p-2">
                    <div className="text-base font-bold text-teal-400">
                      {budget.trades_remaining}
                    </div>
                    <div className="text-[10px] text-slate-500">
                      Trades left
                    </div>
                  </div>
                  <div className="bg-slate-800 rounded p-2">
                    <div className="text-base font-bold text-teal-400">
                      {budget.exposure_remaining_pct.toFixed(1)}%
                    </div>
                    <div className="text-[10px] text-slate-500">
                      Exposure left
                    </div>
                  </div>
                </div>
              </CardContent>
            </Card>
          )}
        </div>

        {/* ── Centre + Right: candidates + learning ─────────────────────── */}
        <div className="lg:col-span-2 space-y-4">
          {/* Candidates panel */}
          <Card className="bg-slate-900 border-slate-700">
            <CardHeader className="pb-3">
              <CardTitle className="text-sm font-medium flex items-center gap-2">
                <Info className="w-4 h-4 text-sky-400" />
                Current Candidates
                <Badge
                  variant="secondary"
                  className="ml-auto text-xs bg-slate-800 text-slate-300"
                >
                  {candidates.length} found
                </Badge>
              </CardTitle>
            </CardHeader>
            <CardContent>
              {candidates.length === 0 ? (
                <p className="text-xs text-slate-500 text-center py-4">
                  {enabled
                    ? "No candidates at this scan. Waiting for next tick."
                    : "Enable exploration mode to see candidates."}
                </p>
              ) : (
                <div className="space-y-2">
                  {candidates.map((c, i) => (
                    <div
                      key={i}
                      className={`flex items-center justify-between p-3 rounded-lg border text-sm ${
                        c.eligible
                          ? "bg-slate-800 border-slate-600"
                          : "bg-slate-900 border-slate-700 opacity-60"
                      }`}
                    >
                      <div className="flex items-center gap-2">
                        {c.eligible ? (
                          <CheckCircle className="w-3.5 h-3.5 text-teal-400 shrink-0" />
                        ) : (
                          <XCircle className="w-3.5 h-3.5 text-red-400 shrink-0" />
                        )}
                        <div>
                          <div className="flex items-center gap-1.5">
                            <span className="font-medium text-white">
                              {c.symbol}
                            </span>
                            <RuleTypeBadge rule={c.rule_type} />
                          </div>
                          {c.blocked_reason && (
                            <p className="text-[10px] text-red-400 mt-0.5">
                              {c.blocked_reason}
                            </p>
                          )}
                        </div>
                      </div>
                      <div className="text-right text-xs text-slate-400 space-y-0.5">
                        <div>
                          {fmtPrice(c.price)} · {c.confidence.toFixed(0)}% conf
                        </div>
                        <div>
                          RR {c.rr_ratio.toFixed(1)} · qty {c.quantity}
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </CardContent>
          </Card>

          {/* Learning observations */}
          {learning.length > 0 && (
            <Card className="bg-slate-900 border-slate-700">
              <CardHeader className="pb-3">
                <CardTitle className="text-sm font-medium flex items-center gap-2">
                  <TrendingUp className="w-4 h-4 text-amber-400" />
                  Learning Observations
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-3">
                {learning.map((obs, i) => (
                  <div
                    key={i}
                    className="p-3 bg-slate-800 rounded-lg border border-slate-700"
                  >
                    <div className="flex items-start justify-between gap-2">
                      <div>
                        <RuleTypeBadge rule={obs.rule_type} />
                        <p className="text-xs text-slate-300 mt-2">
                          {obs.observation}
                        </p>
                      </div>
                      <div className="text-right text-xs text-slate-400 shrink-0 space-y-1">
                        <div>
                          Win rate:{" "}
                          <span
                            className={
                              obs.win_rate_pct >= 50
                                ? "text-teal-400"
                                : "text-red-400"
                            }
                          >
                            {obs.win_rate_pct.toFixed(0)}%
                          </span>
                        </div>
                        <div>
                          MFE:{" "}
                          <span className="text-teal-400">
                            {fmtPct(obs.avg_mfe_pct)}
                          </span>
                        </div>
                        <div>
                          MAE:{" "}
                          <span className="text-red-400">
                            {fmtPct(-Math.abs(obs.avg_mae_pct))}
                          </span>
                        </div>
                        <div className="text-slate-500">{obs.trades} trades</div>
                      </div>
                    </div>
                  </div>
                ))}
              </CardContent>
            </Card>
          )}
        </div>
      </div>

      {/* ── Open experimental trades ─────────────────────────────────────── */}
      {(status?.open_trades?.length ?? 0) > 0 && (
        <Card className="bg-slate-900 border-slate-700">
          <CardHeader className="pb-3">
            <CardTitle className="text-sm font-medium flex items-center gap-2">
              <Clock className="w-4 h-4 text-blue-400" />
              Open Experimental Positions
              <Badge
                variant="secondary"
                className="ml-auto text-xs bg-slate-800 text-slate-300"
              >
                {status!.open_trades.length} open
              </Badge>
            </CardTitle>
          </CardHeader>
          <CardContent>
            <Table>
              <TableHeader>
                <TableRow className="border-slate-700">
                  <TableHead className="text-slate-400 text-xs">Symbol</TableHead>
                  <TableHead className="text-slate-400 text-xs">Rule</TableHead>
                  <TableHead className="text-slate-400 text-xs">Entry</TableHead>
                  <TableHead className="text-slate-400 text-xs">Stop</TableHead>
                  <TableHead className="text-slate-400 text-xs">Target</TableHead>
                  <TableHead className="text-slate-400 text-xs">Qty</TableHead>
                  <TableHead className="text-slate-400 text-xs">MFE</TableHead>
                  <TableHead className="text-slate-400 text-xs">MAE</TableHead>
                  <TableHead className="text-slate-400 text-xs">Entered</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {status!.open_trades.map((t) => (
                  <TableRow key={t.id} className="border-slate-800 hover:bg-slate-800/50">
                    <TableCell className="font-medium text-white text-sm">
                      {t.symbol}
                    </TableCell>
                    <TableCell>
                      <RuleTypeBadge rule={t.rule_type} />
                    </TableCell>
                    <TableCell className="text-xs">{fmtPrice(t.entry_price)}</TableCell>
                    <TableCell className="text-xs text-red-400">
                      {fmtPrice(t.stop_price)}
                    </TableCell>
                    <TableCell className="text-xs text-teal-400">
                      {fmtPrice(t.target_price)}
                    </TableCell>
                    <TableCell className="text-xs">{t.quantity}</TableCell>
                    <TableCell className="text-xs text-teal-400">
                      {fmtPct(t.mfe_pct)}
                    </TableCell>
                    <TableCell className="text-xs text-red-400">
                      {t.mae_pct != null ? fmtPct(-Math.abs(t.mae_pct)) : "—"}
                    </TableCell>
                    <TableCell className="text-xs text-slate-400">
                      {fmtTs(t.entry_ts)}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      )}

      {/* ── Trade history ─────────────────────────────────────────────────── */}
      <Card className="bg-slate-900 border-slate-700">
        <CardHeader className="pb-3">
          <CardTitle className="text-sm font-medium flex items-center gap-2">
            <TrendingDown className="w-4 h-4 text-slate-400" />
            Experimental Trade History
            <Badge
              variant="secondary"
              className="ml-auto text-xs bg-slate-800 text-slate-300"
            >
              {closedTrades.length} closed
            </Badge>
          </CardTitle>
        </CardHeader>
        <CardContent>
          {closedTrades.length === 0 ? (
            <p className="text-xs text-slate-500 text-center py-8">
              No closed experimental trades yet. Enable exploration mode and wait
              for the scheduler to run a tick.
            </p>
          ) : (
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow className="border-slate-700">
                    <TableHead className="text-slate-400 text-xs">Symbol</TableHead>
                    <TableHead className="text-slate-400 text-xs">Rule</TableHead>
                    <TableHead className="text-slate-400 text-xs">Status</TableHead>
                    <TableHead className="text-slate-400 text-xs">Entry</TableHead>
                    <TableHead className="text-slate-400 text-xs">Exit</TableHead>
                    <TableHead className="text-slate-400 text-xs">Qty</TableHead>
                    <TableHead className="text-slate-400 text-xs">P&amp;L</TableHead>
                    <TableHead className="text-slate-400 text-xs">MFE</TableHead>
                    <TableHead className="text-slate-400 text-xs">MAE</TableHead>
                    <TableHead className="text-slate-400 text-xs">Conf</TableHead>
                    <TableHead className="text-slate-400 text-xs">Notes</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {closedTrades.slice(0, 50).map((t) => (
                    <TableRow
                      key={t.id}
                      className="border-slate-800 hover:bg-slate-800/50"
                    >
                      <TableCell className="font-medium text-white text-sm">
                        {t.symbol}
                      </TableCell>
                      <TableCell>
                        <RuleTypeBadge rule={t.rule_type} />
                      </TableCell>
                      <TableCell>
                        <StatusBadge status={t.status} />
                      </TableCell>
                      <TableCell className="text-xs">
                        {fmtPrice(t.entry_price)}
                      </TableCell>
                      <TableCell className="text-xs">
                        {fmtPrice(t.exit_price)}
                      </TableCell>
                      <TableCell className="text-xs">{t.quantity}</TableCell>
                      <TableCell
                        className={`text-xs font-medium ${
                          (t.realized_pnl ?? 0) >= 0
                            ? "text-teal-400"
                            : "text-red-400"
                        }`}
                      >
                        {t.realized_pnl != null
                          ? `₹${t.realized_pnl.toFixed(0)}`
                          : "—"}
                      </TableCell>
                      <TableCell className="text-xs text-teal-400">
                        {fmtPct(t.mfe_pct)}
                      </TableCell>
                      <TableCell className="text-xs text-red-400">
                        {t.mae_pct != null
                          ? fmtPct(-Math.abs(t.mae_pct))
                          : "—"}
                      </TableCell>
                      <TableCell className="text-xs">
                        {t.confidence.toFixed(0)}%
                      </TableCell>
                      <TableCell className="text-xs text-slate-500 max-w-[160px] truncate">
                        {t.notes ?? "—"}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
