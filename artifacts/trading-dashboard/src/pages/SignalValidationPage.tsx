/**
 * SignalValidationPage.tsx — Phase 5C
 *
 * Intraday Signal Outcome Validation & Strategy Attribution.
 * 9 summary cards, signal funnel, 16-column signal table,
 * signal detail drawer, Strategy Comparison tab.
 *
 * PAPER TRADING / ADVISORY ONLY.
 * No order submission. No strategy modification.
 */
import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  BarChart3, TrendingUp, TrendingDown, AlertTriangle,
  RefreshCw, ChevronRight, Search, Activity, Target,
  Brain, Sun, ShieldAlert, Info, CheckCircle2, XCircle,
  Clock, Filter, Download,
} from "lucide-react";
import { apiJson } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import {
  Sheet, SheetContent, SheetHeader, SheetTitle,
} from "@/components/ui/sheet";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { useToast } from "@/hooks/use-toast";

// ── Types ────────────────────────────────────────────────────────────────────

interface SVStatus {
  status: string;
  trading_date?: string;
  scheduler?: {
    active_phase?: string;
    next_phase?: string;
    phases_done?: string[];
    session_id?: string;
    ist_time?: string;
    enabled?: boolean;
  };
  latest_session?: {
    win_rate?: number;
    signals_generated?: number;
  };
}

interface SVSummary {
  trading_date?: string;
  sample_size?: number;
  summary?: {
    signals_generated?: number;
    signals_approved?: number;
    paper_trades?: number;
    risk_rejections?: number;
    win_rate?: number;
    expectancy?: number;
    false_positives?: number;
    missed_opportunities?: number;
    data_completeness_pct?: number;
  };
  funnel?: Record<string, { count: number; pct: number }>;
  label?: string;
}

interface SVSignal {
  validation_id?: string;
  signal_id?: string;
  symbol?: string;
  strategy_name?: string;
  strategy_id?: string;
  signal_direction?: string;
  signal_type?: string;
  signal_timestamp_ist?: string;
  signal_price?: string;
  signal_strength?: string;
  ai_recommendation?: string;
  ai_confidence?: string;
  ai_agreement?: string;
  market_regime?: string;
  validation_status?: string;
  outcome_class?: string;
  entry_price?: string;
  exit_price?: string;
  realised_pnl?: string;
  r_multiple?: string;
  stop_loss?: string;
  target_price?: string;
  sector?: string;
  risk_decision?: string;
  risk_rejection_reason?: string;
  preopen_rank?: number;
  preopen_opportunity_score?: string;
  is_hypothetical?: boolean;
  hypothetical_label?: string;
  max_favourable_excursion?: string;
  max_adverse_excursion?: string;
  data_quality_status?: string;
}

interface SVStrategy {
  strategy_id?: string;
  strategy_name?: string;
  signals_generated?: number;
  paper_trades?: number;
  closed_trades?: number;
  win_rate?: number;
  expectancy?: number;
  avg_r_multiple?: number;
  profit_factor?: number;
  false_positive_rate?: number;
  sample_size?: number;
  confidence_level?: string;
}

// ── Helpers ──────────────────────────────────────────────────────────────────

const pct = (v?: number | null) =>
  v == null ? "—" : `${(v * 100).toFixed(1)}%`;

const dec = (v?: string | number | null, dp = 2) =>
  v == null ? "—" : Number(v).toFixed(dp);

const clamp = (v: number, lo: number, hi: number) =>
  Math.min(Math.max(v, lo), hi);

function outcomeColor(cls?: string): string {
  if (!cls) return "text-muted-foreground";
  if (cls.includes("STRONG_SUCCESS") || cls === "TARGET_REACHED") return "text-emerald-500";
  if (cls.includes("SUCCESS") || cls === "FLAT") return "text-green-400";
  if (cls.includes("STRONG_FAILURE") || cls === "STOPPED_OUT") return "text-red-500";
  if (cls.includes("FAILURE")) return "text-rose-400";
  if (cls.includes("REVERSAL") || cls.includes("BREAKOUT")) return "text-amber-400";
  if (cls.includes("REJECT")) return "text-orange-400";
  if (cls.includes("EXPIRED") || cls.includes("DATA")) return "text-slate-400";
  return "text-slate-400";
}

function statusBadge(status?: string) {
  switch (status) {
    case "CLOSED_POSITION":   return <Badge variant="outline" className="text-slate-400">Closed</Badge>;
    case "OPEN_POSITION":     return <Badge className="bg-blue-600">Open</Badge>;
    case "PAPER_ORDER_FILLED":return <Badge className="bg-blue-500">Filled</Badge>;
    case "RISK_REJECTED":     return <Badge className="bg-orange-700">Rejected</Badge>;
    case "APPROVED":          return <Badge className="bg-indigo-600">Approved</Badge>;
    case "GENERATED":         return <Badge variant="secondary">Generated</Badge>;
    case "MISSED":            return <Badge variant="secondary" className="text-slate-400">Missed</Badge>;
    case "EXPIRED":           return <Badge variant="secondary" className="text-slate-400">Expired</Badge>;
    default:                  return <Badge variant="secondary">{status ?? "—"}</Badge>;
  }
}

function dirBadge(dir?: string) {
  if (!dir) return null;
  const isBuy = dir.includes("BUY");
  return (
    <span className={`font-semibold ${isBuy ? "text-emerald-400" : "text-rose-400"}`}>
      {dir}
    </span>
  );
}

const FUNNEL_ORDER = [
  "generated", "ai_reviewed", "risk_approved", "paper_order", "filled", "closed", "successful",
];

// ── Summary cards ─────────────────────────────────────────────────────────────

function SummaryCards({ summary, isDisabled }: { summary?: SVSummary["summary"]; isDisabled: boolean }) {
  if (isDisabled) {
    return (
      <div className="col-span-full flex items-center gap-2 text-muted-foreground text-sm">
        <Info className="h-4 w-4" />
        Signal Validation is disabled. Set{" "}
        <code className="font-mono bg-muted px-1 rounded">SIGNAL_VALIDATION_ENABLED=true</code>
        {" "}to enable Phase 5C.
      </div>
    );
  }

  const cards = [
    {
      label: "Signals Generated",
      value: summary?.signals_generated ?? 0,
      icon: Activity,
      color: "text-blue-400",
    },
    {
      label: "Signals Approved",
      value: summary?.signals_approved ?? 0,
      icon: CheckCircle2,
      color: "text-indigo-400",
    },
    {
      label: "Paper Trades",
      value: summary?.paper_trades ?? 0,
      icon: TrendingUp,
      color: "text-emerald-400",
    },
    {
      label: "Risk Rejections",
      value: summary?.risk_rejections ?? 0,
      icon: ShieldAlert,
      color: "text-orange-400",
    },
    {
      label: "Win Rate",
      value: pct(summary?.win_rate),
      icon: Target,
      color: "text-green-400",
    },
    {
      label: "Expectancy",
      value: summary?.expectancy != null ? `₹${Number(summary.expectancy).toFixed(0)}` : "—",
      icon: BarChart3,
      color: Number(summary?.expectancy ?? 0) >= 0 ? "text-emerald-400" : "text-rose-400",
    },
    {
      label: "False Positives",
      value: summary?.false_positives ?? 0,
      icon: XCircle,
      color: "text-rose-400",
    },
    {
      label: "Missed Opps",
      value: summary?.missed_opportunities ?? 0,
      icon: AlertTriangle,
      color: "text-amber-400",
    },
    {
      label: "Data Complete",
      value: `${(summary?.data_completeness_pct ?? 0).toFixed(0)}%`,
      icon: CheckCircle2,
      color: (summary?.data_completeness_pct ?? 0) >= 80 ? "text-emerald-400" : "text-amber-400",
    },
  ];

  return (
    <>
      {cards.map((c) => (
        <Card key={c.label} className="border-border/50">
          <CardContent className="p-4">
            <div className="flex items-center justify-between mb-1">
              <span className="text-xs text-muted-foreground">{c.label}</span>
              <c.icon className={`h-4 w-4 ${c.color}`} />
            </div>
            <div className={`text-2xl font-bold ${c.color}`}>{c.value}</div>
          </CardContent>
        </Card>
      ))}
    </>
  );
}

// ── Funnel bar ────────────────────────────────────────────────────────────────

function FunnelBar({ funnel }: { funnel?: SVSummary["funnel"] }) {
  if (!funnel) return null;
  const steps = FUNNEL_ORDER.map((k) => ({
    key: k,
    label: k.replace(/_/g, " "),
    count: funnel[k]?.count ?? 0,
    pctv:  funnel[k]?.pct  ?? 0,
  }));
  return (
    <div className="flex items-end gap-1 h-20">
      {steps.map((s, i) => (
        <Tooltip key={s.key}>
          <TooltipTrigger asChild>
            <div className="flex flex-col items-center flex-1 gap-1">
              <div
                className="w-full rounded-t bg-blue-600/80 transition-all"
                style={{ height: `${clamp(s.pctv, 2, 100)}%` }}
              />
              <span className="text-[9px] text-muted-foreground truncate w-full text-center">
                {s.label}
              </span>
            </div>
          </TooltipTrigger>
          <TooltipContent>
            <p className="font-semibold">{s.label}</p>
            <p>{s.count} signals ({s.pctv.toFixed(1)}%)</p>
          </TooltipContent>
        </Tooltip>
      ))}
    </div>
  );
}

// ── Signal detail drawer ──────────────────────────────────────────────────────

function SignalDetailDrawer({
  signalId, tradingDate, open, onClose,
}: {
  signalId?: string;
  tradingDate?: string;
  open: boolean;
  onClose: () => void;
}) {
  const { data } = useQuery<{
    signal?: SVSignal;
    timeline?: Array<{ from_state: string; to_state: string; reason?: string; timestamp_ist?: string }>;
    price_checkpoints?: Array<{ checkpoint_type: string; price?: string; return_pct?: string }>;
  }>({
    queryKey: ["sv-detail", signalId, tradingDate],
    queryFn: () =>
      apiJson(`signal-validation/signals/${signalId}${tradingDate ? `?date=${tradingDate}` : ""}`),
    enabled: open && !!signalId,
  });

  const sig = data?.signal;

  return (
    <Sheet open={open} onOpenChange={(o) => !o && onClose()}>
      <SheetContent className="w-[480px] sm:max-w-[480px] overflow-y-auto">
        <SheetHeader>
          <SheetTitle>
            {sig?.symbol ?? "Signal"} — {sig?.strategy_name ?? ""}
            {sig?.is_hypothetical && (
              <Badge variant="outline" className="ml-2 text-amber-400 border-amber-400/50">
                HYPOTHETICAL
              </Badge>
            )}
          </SheetTitle>
        </SheetHeader>

        {sig && (
          <div className="mt-4 space-y-4 text-sm">
            {/* Core signal info */}
            <div className="grid grid-cols-2 gap-2">
              <InfoRow label="Direction">{dirBadge(sig.signal_direction)}</InfoRow>
              <InfoRow label="Signal Price">₹{dec(sig.signal_price)}</InfoRow>
              <InfoRow label="Entry Price">₹{dec(sig.entry_price)}</InfoRow>
              <InfoRow label="Exit Price">₹{dec(sig.exit_price)}</InfoRow>
              <InfoRow label="Stop Loss">₹{dec(sig.stop_loss)}</InfoRow>
              <InfoRow label="Target">₹{dec(sig.target_price)}</InfoRow>
              <InfoRow label="Realised P&L">
                <span className={Number(sig.realised_pnl ?? 0) >= 0 ? "text-emerald-400" : "text-rose-400"}>
                  ₹{dec(sig.realised_pnl)}
                </span>
              </InfoRow>
              <InfoRow label="R Multiple">{dec(sig.r_multiple)}</InfoRow>
              <InfoRow label="MFE">{dec(sig.max_favourable_excursion, 4)}</InfoRow>
              <InfoRow label="MAE">{dec(sig.max_adverse_excursion, 4)}</InfoRow>
            </div>

            {/* AI */}
            <div className="border-t border-border/40 pt-3">
              <p className="text-xs font-medium text-muted-foreground mb-2 uppercase tracking-wide">
                AI Attribution
              </p>
              <div className="grid grid-cols-2 gap-2">
                <InfoRow label="AI Recommendation">{sig.ai_recommendation ?? "—"}</InfoRow>
                <InfoRow label="AI Agreement">{sig.ai_agreement ?? "—"}</InfoRow>
                <InfoRow label="AI Confidence">{pct(Number(sig.ai_confidence ?? 0) / 100)}</InfoRow>
                <InfoRow label="Regime">{sig.market_regime ?? "—"}</InfoRow>
              </div>
            </div>

            {/* Pre-open */}
            {sig.preopen_rank != null && (
              <div className="border-t border-border/40 pt-3">
                <p className="text-xs font-medium text-muted-foreground mb-2 uppercase tracking-wide">
                  Pre-Open Context
                </p>
                <div className="grid grid-cols-2 gap-2">
                  <InfoRow label="Pre-Open Rank">#{sig.preopen_rank}</InfoRow>
                  <InfoRow label="Opp Score">{dec(sig.preopen_opportunity_score)}</InfoRow>
                </div>
              </div>
            )}

            {/* Outcome */}
            <div className="border-t border-border/40 pt-3">
              <p className="text-xs font-medium text-muted-foreground mb-2 uppercase tracking-wide">
                Outcome
              </p>
              <div className="grid grid-cols-2 gap-2">
                <InfoRow label="Status">{statusBadge(sig.validation_status)}</InfoRow>
                <InfoRow label="Outcome">
                  <span className={outcomeColor(sig.outcome_class)}>
                    {sig.outcome_class?.replace(/_/g, " ") ?? "—"}
                  </span>
                </InfoRow>
                {sig.risk_rejection_reason && (
                  <InfoRow label="Rejection Reason">{sig.risk_rejection_reason}</InfoRow>
                )}
              </div>
            </div>

            {/* Price checkpoints */}
            {(data?.price_checkpoints?.length ?? 0) > 0 && (
              <div className="border-t border-border/40 pt-3">
                <p className="text-xs font-medium text-muted-foreground mb-2 uppercase tracking-wide">
                  Price Checkpoints
                </p>
                <div className="space-y-1">
                  {data!.price_checkpoints!.map((cp) => (
                    <div key={cp.checkpoint_type} className="flex justify-between text-xs">
                      <span className="text-muted-foreground">{cp.checkpoint_type}</span>
                      <span>₹{dec(cp.price)} {cp.return_pct ? `(${dec(cp.return_pct, 2)}%)` : ""}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Timeline */}
            {(data?.timeline?.length ?? 0) > 0 && (
              <div className="border-t border-border/40 pt-3">
                <p className="text-xs font-medium text-muted-foreground mb-2 uppercase tracking-wide">
                  Lifecycle
                </p>
                <div className="space-y-2">
                  {data!.timeline!.map((e, i) => (
                    <div key={i} className="flex items-center gap-2 text-xs">
                      <span className="text-muted-foreground w-28 shrink-0 truncate">
                        {e.timestamp_ist ? new Date(e.timestamp_ist).toLocaleTimeString("en-IN") : ""}
                      </span>
                      <ChevronRight className="h-3 w-3 shrink-0 text-muted-foreground" />
                      <span className="font-medium">{e.to_state}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {sig.is_hypothetical && (
              <p className="text-xs text-amber-400/80 border border-amber-400/20 rounded p-2">
                {sig.hypothetical_label ?? "HYPOTHETICAL — NOT A TRADE"}.
                Hypothetical P&L is excluded from paper portfolio statistics.
              </p>
            )}
          </div>
        )}
      </SheetContent>
    </Sheet>
  );
}

function InfoRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <p className="text-muted-foreground text-[10px] uppercase tracking-wide">{label}</p>
      <p className="font-medium">{children}</p>
    </div>
  );
}

// ── Signals table ─────────────────────────────────────────────────────────────

function SignalsTable({
  signals, onSelect,
}: {
  signals?: SVSignal[];
  onSelect: (s: SVSignal) => void;
}) {
  return (
    <div className="overflow-x-auto">
      <Table>
        <TableHeader>
          <TableRow className="border-border/40">
            <TableHead className="w-24">Symbol</TableHead>
            <TableHead>Strategy</TableHead>
            <TableHead>Direction</TableHead>
            <TableHead>Regime</TableHead>
            <TableHead>AI</TableHead>
            <TableHead>Pre-Open</TableHead>
            <TableHead>Status</TableHead>
            <TableHead>Outcome</TableHead>
            <TableHead className="text-right">Entry</TableHead>
            <TableHead className="text-right">Exit</TableHead>
            <TableHead className="text-right">P&L</TableHead>
            <TableHead className="text-right">R×</TableHead>
            <TableHead>Stop</TableHead>
            <TableHead>Target</TableHead>
            <TableHead>Data Quality</TableHead>
            <TableHead>Action</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {!signals?.length && (
            <TableRow>
              <TableCell colSpan={16} className="text-center text-muted-foreground py-8">
                No signals for this session. Signals are ingested between 09:00–09:30 IST.
              </TableCell>
            </TableRow>
          )}
          {signals?.map((s) => (
            <TableRow
              key={s.validation_id ?? s.signal_id}
              className="border-border/20 hover:bg-muted/30 cursor-pointer"
              onClick={() => onSelect(s)}
            >
              <TableCell className="font-medium">{s.symbol}</TableCell>
              <TableCell className="text-xs text-muted-foreground max-w-[120px] truncate">
                {s.strategy_name ?? s.strategy_id}
              </TableCell>
              <TableCell>{dirBadge(s.signal_direction)}</TableCell>
              <TableCell className="text-xs">{s.market_regime ?? "—"}</TableCell>
              <TableCell>
                <span className={
                  s.ai_agreement === "AGREE"    ? "text-emerald-400" :
                  s.ai_agreement === "DISAGREE" ? "text-rose-400"   :
                  s.ai_agreement === "WATCH"    ? "text-amber-400"  :
                  "text-muted-foreground"
                }>
                  {s.ai_agreement ?? "—"}
                </span>
              </TableCell>
              <TableCell className="text-xs">
                {s.preopen_rank != null ? `#${s.preopen_rank}` : "—"}
              </TableCell>
              <TableCell>{statusBadge(s.validation_status)}</TableCell>
              <TableCell>
                <span className={`text-xs ${outcomeColor(s.outcome_class)}`}>
                  {s.outcome_class?.replace(/_/g, " ") ?? "—"}
                </span>
              </TableCell>
              <TableCell className="text-right text-xs">
                {s.entry_price ? `₹${dec(s.entry_price)}` : "—"}
              </TableCell>
              <TableCell className="text-right text-xs">
                {s.exit_price ? `₹${dec(s.exit_price)}` : "—"}
              </TableCell>
              <TableCell className="text-right text-xs">
                <span className={Number(s.realised_pnl ?? 0) >= 0 ? "text-emerald-400" : "text-rose-400"}>
                  {s.realised_pnl ? `₹${dec(s.realised_pnl, 0)}` : "—"}
                  {s.is_hypothetical && (
                    <Tooltip>
                      <TooltipTrigger><Info className="inline h-3 w-3 ml-1 text-amber-400" /></TooltipTrigger>
                      <TooltipContent>Hypothetical — Not a Trade</TooltipContent>
                    </Tooltip>
                  )}
                </span>
              </TableCell>
              <TableCell className="text-right text-xs">
                {s.r_multiple ? dec(s.r_multiple) : "—"}
              </TableCell>
              <TableCell className="text-xs">
                {s.stop_loss ? `₹${dec(s.stop_loss)}` : "—"}
              </TableCell>
              <TableCell className="text-xs">
                {s.target_price ? `₹${dec(s.target_price)}` : "—"}
              </TableCell>
              <TableCell>
                <Badge
                  variant="outline"
                  className={
                    s.data_quality_status === "STALE" ? "text-amber-400 border-amber-400/50" :
                    s.data_quality_status === "FRESH" ? "text-emerald-400 border-emerald-400/50" :
                    "text-muted-foreground"
                  }
                >
                  {s.data_quality_status ?? "—"}
                </Badge>
              </TableCell>
              <TableCell>
                <Button
                  variant="ghost"
                  size="sm"
                  className="h-6 px-2"
                  onClick={(e) => { e.stopPropagation(); onSelect(s); }}
                >
                  <ChevronRight className="h-3 w-3" />
                </Button>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}

// ── Strategy comparison tab ───────────────────────────────────────────────────

function StrategyComparison({ strategies }: { strategies?: SVStrategy[] }) {
  return (
    <div className="overflow-x-auto">
      <Table>
        <TableHeader>
          <TableRow className="border-border/40">
            <TableHead>Strategy</TableHead>
            <TableHead className="text-right">Signals</TableHead>
            <TableHead className="text-right">Trades</TableHead>
            <TableHead className="text-right">Closed</TableHead>
            <TableHead className="text-right">Win Rate</TableHead>
            <TableHead className="text-right">Expectancy</TableHead>
            <TableHead className="text-right">Avg R×</TableHead>
            <TableHead className="text-right">Profit Factor</TableHead>
            <TableHead className="text-right">FP Rate</TableHead>
            <TableHead>Confidence</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {!strategies?.length && (
            <TableRow>
              <TableCell colSpan={10} className="text-center text-muted-foreground py-8">
                No strategy metrics yet — needs ≥5 closed trades per strategy.
              </TableCell>
            </TableRow>
          )}
          {strategies?.map((s) => (
            <TableRow key={s.strategy_id} className="border-border/20">
              <TableCell className="font-medium">{s.strategy_name ?? s.strategy_id}</TableCell>
              <TableCell className="text-right text-xs">{s.signals_generated ?? 0}</TableCell>
              <TableCell className="text-right text-xs">{s.paper_trades ?? 0}</TableCell>
              <TableCell className="text-right text-xs">{s.closed_trades ?? 0}</TableCell>
              <TableCell className="text-right text-xs">
                <span className={(s.win_rate ?? 0) >= 0.5 ? "text-emerald-400" : "text-rose-400"}>
                  {pct(s.win_rate)}
                </span>
              </TableCell>
              <TableCell className="text-right text-xs">
                <span className={(s.expectancy ?? 0) >= 0 ? "text-emerald-400" : "text-rose-400"}>
                  ₹{dec(s.expectancy, 0)}
                </span>
              </TableCell>
              <TableCell className="text-right text-xs">{dec(s.avg_r_multiple)}</TableCell>
              <TableCell className="text-right text-xs">{dec(s.profit_factor)}</TableCell>
              <TableCell className="text-right text-xs">{pct(s.false_positive_rate)}</TableCell>
              <TableCell>
                <Badge
                  variant="outline"
                  className={
                    s.confidence_level === "SUFFICIENT"       ? "text-emerald-400 border-emerald-400/40" :
                    s.confidence_level === "LOW_SAMPLE"       ? "text-amber-400 border-amber-400/40" :
                    "text-slate-400 border-slate-400/40"
                  }
                >
                  {s.confidence_level === "INSUFFICIENT_DATA" ? "LOW DATA" :
                   s.confidence_level ?? "—"}
                </Badge>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function SignalValidationPage() {
  const qc = useQueryClient();
  const { toast } = useToast();
  const [selectedDate, setSelectedDate] = useState<string>("");
  const [selectedSignal, setSelectedSignal] = useState<SVSignal | null>(null);
  const [filterStatus, setFilterStatus] = useState("all");

  const today = new Date().toLocaleDateString("sv-SE", {
    timeZone: "Asia/Kolkata",
  });

  const activeDate = selectedDate || today;

  // Status
  const statusQ = useQuery<SVStatus>({
    queryKey: ["sv-status"],
    queryFn: () => apiJson("signal-validation/status"),
    refetchInterval: 60_000,
  });

  const isDisabled = statusQ.data?.status === "DISABLED";

  // Summary
  const summaryQ = useQuery<SVSummary>({
    queryKey: ["sv-summary", activeDate],
    queryFn: () => apiJson(`signal-validation/summary?date=${activeDate}`),
    refetchInterval: 60_000,
    enabled: !isDisabled,
  });

  // Signals
  const signalsQ = useQuery<{ signals?: SVSignal[] }>({
    queryKey: ["sv-signals", activeDate, filterStatus],
    queryFn: () =>
      apiJson(`signal-validation/signals?date=${activeDate}&limit=200`),
    refetchInterval: 90_000,
    enabled: !isDisabled,
  });

  // Strategies
  const strategiesQ = useQuery<{ strategies?: SVStrategy[] }>({
    queryKey: ["sv-strategies", activeDate],
    queryFn: () => apiJson(`signal-validation/strategies?date=${activeDate}`),
    refetchInterval: 120_000,
    enabled: !isDisabled,
  });

  // Manual run mutation
  const runNow = useMutation({
    mutationFn: () =>
      apiJson("signal-validation/run-now", { method: "POST", body: JSON.stringify({ date: activeDate }) }),
    onSuccess: (data: unknown) => {
      const d = data as Record<string, unknown>;
      if (d?.status === "RATE_LIMITED") {
        toast({ title: "Rate limited", description: "Try again in 30 seconds." });
      } else {
        toast({ title: "Signal ingest triggered", description: "Refreshing data…" });
        void qc.invalidateQueries({ queryKey: ["sv-signals"] });
        void qc.invalidateQueries({ queryKey: ["sv-summary"] });
      }
    },
    onError: () => toast({ title: "Error", description: "Manual run failed.", variant: "destructive" }),
  });

  const scheduler = statusQ.data?.scheduler;

  // Filter signals client-side
  const allSignals = signalsQ.data?.signals ?? [];
  const signals = filterStatus === "all"
    ? allSignals
    : allSignals.filter((s) => s.validation_status === filterStatus);

  return (
    <div className="space-y-6 p-6">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-bold">Signal Outcome Validation</h1>
          <p className="text-sm text-muted-foreground mt-1">
            Phase 5C — Track every intraday signal from creation to final outcome.
            <span className="ml-2 text-amber-400/80">
              PAPER TRADING / ADVISORY ONLY
            </span>
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={() => {
              void qc.invalidateQueries({ queryKey: ["sv-status"] });
              void qc.invalidateQueries({ queryKey: ["sv-summary"] });
              void qc.invalidateQueries({ queryKey: ["sv-signals"] });
            }}
          >
            <RefreshCw className="h-3 w-3 mr-1" />
            Refresh
          </Button>
          <Button
            variant="outline"
            size="sm"
            disabled={isDisabled || runNow.isPending}
            onClick={() => runNow.mutate()}
          >
            <Activity className="h-3 w-3 mr-1" />
            Ingest Now
          </Button>
        </div>
      </div>

      {/* Scheduler status bar */}
      <div className="flex items-center gap-3 text-xs bg-muted/30 rounded-lg px-4 py-2 border border-border/30">
        <Clock className="h-4 w-4 text-muted-foreground" />
        <span className="text-muted-foreground">Scheduler:</span>
        {scheduler ? (
          <>
            <span className={scheduler.enabled ? "text-emerald-400" : "text-amber-400"}>
              {scheduler.enabled ? "● ENABLED" : "● DISABLED"}
            </span>
            <span className="text-muted-foreground">·</span>
            <span className="font-mono">{scheduler.ist_time ?? "—"} IST</span>
            {scheduler.active_phase && (
              <>
                <span className="text-muted-foreground">·</span>
                <span className="text-blue-400">Active: {scheduler.active_phase}</span>
              </>
            )}
            {scheduler.next_phase && !scheduler.active_phase && (
              <>
                <span className="text-muted-foreground">· Next:</span>
                <span>{scheduler.next_phase}</span>
              </>
            )}
            {(scheduler.phases_done?.length ?? 0) > 0 && (
              <>
                <span className="text-muted-foreground">· Done:</span>
                <span>{scheduler.phases_done?.join(", ")}</span>
              </>
            )}
          </>
        ) : (
          <span className="text-muted-foreground">—</span>
        )}
        <span className="ml-auto text-muted-foreground">Session: {scheduler?.session_id ?? "—"}</span>
      </div>

      {/* Date picker */}
      <div className="flex items-center gap-3">
        <span className="text-sm text-muted-foreground">Date:</span>
        <input
          type="date"
          value={selectedDate || today}
          onChange={(e) => setSelectedDate(e.target.value)}
          className="bg-muted border border-border rounded px-3 py-1 text-sm"
        />
        {selectedDate && selectedDate !== today && (
          <Button variant="ghost" size="sm" onClick={() => setSelectedDate("")}>
            Today
          </Button>
        )}
      </div>

      {/* 9 Summary cards */}
      <div className="grid grid-cols-3 md:grid-cols-5 lg:grid-cols-9 gap-3">
        <SummaryCards summary={summaryQ.data?.summary} isDisabled={isDisabled} />
      </div>

      {/* Funnel */}
      {!isDisabled && summaryQ.data?.funnel && (
        <Card className="border-border/50">
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium flex items-center gap-2">
              <BarChart3 className="h-4 w-4" />
              Signal Funnel
              <span className="text-xs text-muted-foreground font-normal ml-auto">
                {summaryQ.data.sample_size ?? 0} signals today
              </span>
            </CardTitle>
          </CardHeader>
          <CardContent>
            <FunnelBar funnel={summaryQ.data.funnel} />
          </CardContent>
        </Card>
      )}

      {/* Tabs: Signals / Strategy Comparison */}
      <Tabs defaultValue="signals">
        <TabsList>
          <TabsTrigger value="signals">
            <Activity className="h-3 w-3 mr-1" />
            Signals ({allSignals.length})
          </TabsTrigger>
          <TabsTrigger value="strategies">
            <BarChart3 className="h-3 w-3 mr-1" />
            Strategy Comparison
          </TabsTrigger>
        </TabsList>

        <TabsContent value="signals" className="mt-4">
          {/* Filter bar */}
          <div className="flex items-center gap-3 mb-3">
            <Filter className="h-4 w-4 text-muted-foreground" />
            <Select value={filterStatus} onValueChange={setFilterStatus}>
              <SelectTrigger className="w-44 h-8">
                <SelectValue placeholder="All statuses" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">All Statuses</SelectItem>
                <SelectItem value="GENERATED">Generated</SelectItem>
                <SelectItem value="APPROVED">Approved</SelectItem>
                <SelectItem value="OPEN_POSITION">Open Position</SelectItem>
                <SelectItem value="CLOSED_POSITION">Closed</SelectItem>
                <SelectItem value="RISK_REJECTED">Risk Rejected</SelectItem>
                <SelectItem value="MISSED">Missed</SelectItem>
                <SelectItem value="EXPIRED">Expired</SelectItem>
              </SelectContent>
            </Select>
            <span className="text-xs text-muted-foreground">
              Showing {signals.length} of {allSignals.length}
            </span>
          </div>

          {isDisabled ? (
            <div className="text-center text-muted-foreground py-12 text-sm">
              <Info className="h-8 w-8 mx-auto mb-3 opacity-40" />
              Signal Validation is disabled.
              Set <code className="font-mono bg-muted px-1 rounded">SIGNAL_VALIDATION_ENABLED=true</code> to enable.
            </div>
          ) : signalsQ.isLoading ? (
            <div className="text-center text-muted-foreground py-12">Loading signals…</div>
          ) : (
            <Card className="border-border/50">
              <CardContent className="p-0">
                <SignalsTable signals={signals} onSelect={setSelectedSignal} />
              </CardContent>
            </Card>
          )}
        </TabsContent>

        <TabsContent value="strategies" className="mt-4">
          <div className="mb-3 text-xs text-muted-foreground flex items-center gap-2">
            <Info className="h-3 w-3" />
            Metrics require ≥10 closed trades per strategy. Confidence flags indicate sample adequacy.
            Strategy parameters are not modified by Phase 5C.
          </div>
          {isDisabled ? (
            <div className="text-center text-muted-foreground py-12 text-sm">
              Signal Validation disabled.
            </div>
          ) : strategiesQ.isLoading ? (
            <div className="text-center text-muted-foreground py-12">Loading strategy metrics…</div>
          ) : (
            <Card className="border-border/50">
              <CardContent className="p-0">
                <StrategyComparison strategies={strategiesQ.data?.strategies} />
              </CardContent>
            </Card>
          )}
        </TabsContent>
      </Tabs>

      {/* Signal detail drawer */}
      <SignalDetailDrawer
        signalId={selectedSignal?.signal_id}
        tradingDate={activeDate}
        open={!!selectedSignal}
        onClose={() => setSelectedSignal(null)}
      />
    </div>
  );
}
