import React, { useState } from "react";
import {
  useGetSignals,
  useRunScan,
  getGetPortfolioQueryKey,
  getGetSignalsQueryKey,
  type Signal,
} from "@workspace/api-client-react";
import { useQueryClient } from "@tanstack/react-query";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { formatCurrency, formatTime } from "@/lib/format";
import {
  Play, ChevronDown, ChevronUp, TrendingUp, TrendingDown,
  Clock, Brain, AlertTriangle, Activity,
} from "lucide-react";
import { useToast } from "@/hooks/use-toast";

// ── Config ────────────────────────────────────────────────────────────────────

const SIGNAL_CONFIG: Record<string, { label: string; color: string; icon: React.ReactNode }> = {
  STRONG_BUY:  { label: "STRONG BUY",  color: "bg-emerald-500/20 text-emerald-400 border-emerald-500/50", icon: <TrendingUp className="h-3 w-3" /> },
  BUY:         { label: "BUY",         color: "bg-green-500/20 text-green-400 border-green-500/50",       icon: <TrendingUp className="h-3 w-3" /> },
  WATCH:       { label: "WATCH",       color: "bg-yellow-500/20 text-yellow-400 border-yellow-500/50",    icon: <Activity className="h-3 w-3" /> },
  SELL:        { label: "SELL",        color: "bg-red-500/20 text-red-400 border-red-500/50",             icon: <TrendingDown className="h-3 w-3" /> },
  STRONG_SELL: { label: "STRONG SELL", color: "bg-rose-500/20 text-rose-400 border-rose-500/50",          icon: <TrendingDown className="h-3 w-3" /> },
  NO_TRADE:    { label: "NO TRADE",    color: "bg-muted/50 text-muted-foreground border-border",          icon: null },
};

const RISK_CONFIG: Record<string, { color: string; label: string }> = {
  LOW:    { color: "text-green-400",  label: "LOW" },
  MEDIUM: { color: "text-yellow-400", label: "MED" },
  HIGH:   { color: "text-red-400",    label: "HIGH" },
};

const REGIME_COLORS: Record<string, string> = {
  BULLISH:         "text-emerald-400",
  BEARISH:         "text-red-400",
  SIDEWAYS:        "text-yellow-400",
  HIGH_VOLATILITY: "text-orange-400",
  LOW_VOLATILITY:  "text-blue-400",
};

// ── Sub-components ────────────────────────────────────────────────────────────

function SignalBadge({ signal }: { signal: string }) {
  const cfg = SIGNAL_CONFIG[signal] ?? SIGNAL_CONFIG.NO_TRADE;
  return (
    <Badge variant="outline" className={`gap-1 font-mono text-xs font-bold ${cfg.color}`}>
      {cfg.icon}
      {cfg.label}
    </Badge>
  );
}

function ConfidenceBar({ value }: { value: number }) {
  const pct = Math.round(value);
  const color =
    pct >= 90 ? "bg-emerald-500" :
    pct >= 75 ? "bg-green-500"   :
    pct >= 60 ? "bg-yellow-500"  : "bg-muted";
  return (
    <div className="flex items-center gap-2 min-w-[120px]">
      <div className="flex-1 h-1.5 rounded-full bg-muted overflow-hidden">
        <div className={`h-full rounded-full ${color}`} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-xs font-mono text-muted-foreground w-8 text-right">{pct}</span>
    </div>
  );
}

function TimeframeAlignment({ count }: { count: number }) {
  return (
    <div className="flex items-center gap-0.5" title={`${count}/4 timeframes agree`}>
      {[0, 1, 2, 3].map(i => (
        <div
          key={i}
          className={`w-2.5 h-2.5 rounded-sm ${
            i < count ? "bg-primary" : "bg-muted"
          }`}
        />
      ))}
      <span className="text-[10px] font-mono text-muted-foreground ml-1">{count}/4</span>
    </div>
  );
}

function ExplanationPanel({ signal }: { signal: Signal }) {
  const expl = signal.explanation;
  if (!expl) return null;

  const rows: Array<{ label: string; value: string; icon: React.ReactNode }> = [
    { label: "Trend",        value: expl.trend,            icon: <TrendingUp className="h-3 w-3 text-primary" /> },
    { label: "Momentum",     value: expl.momentum,         icon: <Activity className="h-3 w-3 text-primary" /> },
    { label: "Volume",       value: expl.volume,           icon: <ChevronUp className="h-3 w-3 text-primary" /> },
    { label: "Indicators",   value: expl.indicator_summary,icon: <Brain className="h-3 w-3 text-primary" /> },
    { label: "Regime",       value: expl.regime_impact,    icon: <AlertTriangle className="h-3 w-3 text-orange-400" /> },
  ];

  return (
    <div className="mt-3 mb-1 rounded-lg border border-border/40 bg-muted/10 p-3 space-y-2.5">
      {/* Plain English summary */}
      <div className="flex gap-2 items-start">
        <Brain className="h-3.5 w-3.5 text-primary mt-0.5 flex-shrink-0" />
        <p className="text-xs text-foreground/90 leading-relaxed">{expl.plain_english}</p>
      </div>
      <div className="h-px bg-border/30" />
      <div className="grid grid-cols-1 md:grid-cols-2 gap-1.5">
        {rows.map(({ label, value, icon }) => (
          <div key={label} className="flex gap-2 items-start">
            <div className="mt-0.5 flex-shrink-0">{icon}</div>
            <div>
              <span className="text-[10px] font-mono uppercase text-muted-foreground tracking-wide">{label}: </span>
              <span className="text-[11px] text-foreground/80">{value}</span>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function SignalRow({ signal }: { signal: Signal }) {
  const [expanded, setExpanded] = useState(false);
  const riskCfg = RISK_CONFIG[signal.risk_level] ?? RISK_CONFIG.HIGH;
  const isBullish = ["STRONG_BUY", "BUY"].includes(signal.signal);
  const isBearish = ["STRONG_SELL", "SELL"].includes(signal.signal);
  const hasExplanation = !!signal.explanation;
  const regimeColor = REGIME_COLORS[signal.regime ?? "SIDEWAYS"] ?? "text-muted-foreground";

  return (
    <>
      <tr
        className={`border-b border-border/30 hover:bg-muted/20 transition-colors ${hasExplanation ? "cursor-pointer" : ""}`}
        onClick={() => hasExplanation && setExpanded(e => !e)}
      >
        <td className="px-4 py-3">
          <div className="flex items-center gap-2">
            <span className="font-bold font-mono">{signal.stock}</span>
            {hasExplanation && (
              expanded
                ? <ChevronUp className="h-3 w-3 text-muted-foreground" />
                : <ChevronDown className="h-3 w-3 text-muted-foreground" />
            )}
          </div>
        </td>
        <td className="px-3 py-3 text-center">
          <SignalBadge signal={signal.signal} />
        </td>
        <td className="px-3 py-3 text-right font-mono text-sm">{formatCurrency(signal.price)}</td>
        <td className="px-3 py-3 text-right font-mono text-sm">{signal.quantity}</td>
        <td className="px-3 py-3"><ConfidenceBar value={signal.confidence} /></td>
        <td className="px-3 py-3 text-left max-w-[220px]">
          <span
            className="text-xs text-foreground/80 line-clamp-2"
            title={(signal.reasons ?? []).join("; ") || signal.explanation?.plain_english || ""}
            data-testid={`text-reason-${signal.stock}`}
          >
            {signal.reasons?.[0] ?? signal.explanation?.plain_english ?? "—"}
          </span>
        </td>
        <td className="px-3 py-3 text-center">
          <span className={`text-xs font-mono font-bold ${riskCfg.color}`}>{riskCfg.label}</span>
        </td>
        <td className="px-3 py-3 text-center">
          <TimeframeAlignment count={signal.timeframe_alignment ?? 0} />
        </td>
        <td className="px-3 py-3 text-center">
          <span className={`text-[10px] font-mono font-semibold ${regimeColor}`}>
            {(signal.regime ?? "—").replace(/_/g, " ")}
          </span>
        </td>
        <td className={`px-3 py-3 text-right font-mono text-xs ${isBullish || isBearish ? "text-red-400" : "text-muted-foreground"}`}>
          {signal.stop_loss > 0 ? formatCurrency(signal.stop_loss) : "—"}
        </td>
        <td className={`px-3 py-3 text-right font-mono text-xs ${isBullish ? "text-emerald-400" : isBearish ? "text-emerald-400" : "text-muted-foreground"}`}>
          {signal.target > 0 ? formatCurrency(signal.target) : "—"}
        </td>
        <td className="px-4 py-3 text-right text-muted-foreground font-mono text-xs whitespace-nowrap">
          <div className="flex items-center gap-1 justify-end">
            <Clock className="h-3 w-3" />
            {formatTime(signal.time)}
          </div>
        </td>
      </tr>
      {expanded && hasExplanation && (
        <tr className="bg-muted/5">
          <td colSpan={12} className="px-4 pb-3 pt-0">
            <ExplanationPanel signal={signal} />
          </td>
        </tr>
      )}
    </>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function Signals() {
  const queryClient = useQueryClient();
  const { toast } = useToast();

  const { data: signals, isLoading } = useGetSignals({
    query: { queryKey: getGetSignalsQueryKey(), refetchInterval: 30000 },
  });

  const runScan = useRunScan();

  const handleRunScan = () => {
    runScan.mutate(undefined, {
      onSuccess: () => {
        queryClient.invalidateQueries({ queryKey: getGetPortfolioQueryKey() });
        queryClient.invalidateQueries({ queryKey: getGetSignalsQueryKey() });
        toast({ title: "Scan Complete", description: "Signals updated with regime and MTF analysis." });
      },
      onError: () => {
        toast({ title: "Scan Failed", description: "Could not complete the market scan.", variant: "destructive" });
      },
    });
  };

  const actionable = signals?.filter(s => ["STRONG_BUY", "BUY", "STRONG_SELL", "SELL"].includes(s.signal)) ?? [];
  const watchCount = signals?.filter(s => s.signal === "WATCH").length ?? 0;
  const noTradeCount = signals?.filter(s => s.signal === "NO_TRADE").length ?? 0;

  return (
    <div className="space-y-4 max-w-full mx-auto h-full flex flex-col">
      {/* Header */}
      <div className="flex items-center justify-between flex-shrink-0">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Active Signals</h1>
          <p className="text-muted-foreground text-sm mt-0.5">
            Multi-timeframe · Market regime · EMA · RSI · MACD · VWAP · Supertrend · ATR
          </p>
        </div>
        <Button
          onClick={handleRunScan}
          disabled={runScan.isPending}
          className="font-mono bg-primary text-primary-foreground shadow-lg"
        >
          <Play className={`mr-2 h-4 w-4 ${runScan.isPending ? "animate-pulse" : ""}`} />
          {runScan.isPending ? "SCANNING..." : "RUN SCAN"}
        </Button>
      </div>

      {/* Threshold guide */}
      <div className="flex gap-2 flex-wrap flex-shrink-0 items-center">
        <span className="text-xs text-muted-foreground font-mono">Thresholds:</span>
        {[
          { label: "90-100 = STRONG", color: "bg-emerald-500/15 text-emerald-400 border-emerald-500/30" },
          { label: "75-89 = BUY/SELL", color: "bg-green-500/15 text-green-400 border-green-500/30" },
          { label: "60-74 = WATCH", color: "bg-yellow-500/15 text-yellow-400 border-yellow-500/30" },
          { label: "<60 = NO TRADE", color: "bg-muted/50 text-muted-foreground border-border" },
        ].map(({ label, color }) => (
          <span key={label} className={`text-xs font-mono px-2 py-0.5 rounded-full border ${color}`}>{label}</span>
        ))}
      </div>

      {/* Signal count pills */}
      {signals && signals.length > 0 && (
        <div className="flex gap-2 flex-wrap flex-shrink-0">
          {(["STRONG_BUY", "BUY", "STRONG_SELL", "SELL"] as const).map(type => {
            const count = actionable.filter(s => s.signal === type).length;
            if (!count) return null;
            const cfg = SIGNAL_CONFIG[type];
            return (
              <span key={type} className={`text-xs font-mono px-2 py-0.5 rounded-full border ${cfg.color}`}>
                {count} {cfg.label}
              </span>
            );
          })}
          {watchCount > 0 && (
            <span className="text-xs font-mono px-2 py-0.5 rounded-full bg-yellow-500/15 text-yellow-400 border border-yellow-500/30">
              {watchCount} WATCH
            </span>
          )}
          {noTradeCount > 0 && (
            <span className="text-xs font-mono px-2 py-0.5 rounded-full bg-muted/50 text-muted-foreground border border-border">
              {noTradeCount} NO TRADE
            </span>
          )}
        </div>
      )}

      {/* Table */}
      <Card className="flex-1 overflow-hidden flex flex-col bg-card/50 backdrop-blur border-border/50 min-h-0">
        <CardHeader className="border-b border-border/50 bg-muted/20 py-3 px-4 flex-shrink-0">
          <CardTitle className="font-mono text-xs uppercase tracking-wider text-muted-foreground">
            Latest Scan Results — {signals?.length ?? 0} stocks analysed
            {signals && signals.length > 0 && (
              <span className="ml-2 normal-case text-muted-foreground/60 font-normal">
                · Click a row to expand Signal Explanation
              </span>
            )}
          </CardTitle>
        </CardHeader>
        <CardContent className="p-0 flex-1 overflow-auto">
          {isLoading && !signals ? (
            <div className="p-12 text-center text-muted-foreground font-mono">LOADING SIGNALS...</div>
          ) : signals && signals.length > 0 ? (
            <table className="w-full text-sm">
              <thead className="bg-muted/40 sticky top-0 z-10 backdrop-blur">
                <tr className="border-b border-border/50">
                  <th className="font-mono text-[11px] uppercase text-muted-foreground text-left px-4 py-2.5">Stock</th>
                  <th className="font-mono text-[11px] uppercase text-muted-foreground text-center px-3 py-2.5">Signal</th>
                  <th className="font-mono text-[11px] uppercase text-muted-foreground text-right px-3 py-2.5">Price</th>
                  <th className="font-mono text-[11px] uppercase text-muted-foreground text-right px-3 py-2.5">Qty</th>
                  <th className="font-mono text-[11px] uppercase text-muted-foreground px-3 py-2.5">Confidence</th>
                  <th className="font-mono text-[11px] uppercase text-muted-foreground text-left px-3 py-2.5">Reason</th>
                  <th className="font-mono text-[11px] uppercase text-muted-foreground text-center px-3 py-2.5">Risk</th>
                  <th className="font-mono text-[11px] uppercase text-muted-foreground text-center px-3 py-2.5 whitespace-nowrap">Timeframes</th>
                  <th className="font-mono text-[11px] uppercase text-muted-foreground text-center px-3 py-2.5">Regime</th>
                  <th className="font-mono text-[11px] uppercase text-muted-foreground text-right px-3 py-2.5 whitespace-nowrap">Stop Loss</th>
                  <th className="font-mono text-[11px] uppercase text-muted-foreground text-right px-3 py-2.5">Target</th>
                  <th className="font-mono text-[11px] uppercase text-muted-foreground text-right px-4 py-2.5">Time</th>
                </tr>
              </thead>
              <tbody>
                {signals.map((signal, i) => (
                  <SignalRow key={`${signal.stock}-${i}`} signal={signal} />
                ))}
              </tbody>
            </table>
          ) : (
            <div className="p-12 text-center flex flex-col items-center gap-3 text-muted-foreground">
              <div className="h-12 w-12 rounded-full bg-muted flex items-center justify-center border border-dashed border-border">
                <Play className="h-5 w-5 text-muted-foreground/50" />
              </div>
              <p className="font-mono text-sm">NO SIGNALS GENERATED</p>
              <p className="text-xs max-w-sm text-center">
                Run a scan to analyse your watchlist with multi-timeframe analysis, market regime, EMA, RSI, MACD, VWAP, Supertrend and more.
              </p>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
