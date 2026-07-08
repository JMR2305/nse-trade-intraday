import React, { useState } from "react";
import {
  useGetSignals,
  useRunScan,
  getGetPortfolioQueryKey,
  getGetSignalsQueryKey
} from "@workspace/api-client-react";
import { useQueryClient } from "@tanstack/react-query";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Progress } from "@/components/ui/progress";
import { formatCurrency, formatTime } from "@/lib/format";
import { Play, ChevronDown, ChevronUp, AlertTriangle, TrendingUp, TrendingDown } from "lucide-react";
import { useToast } from "@/hooks/use-toast";

const SIGNAL_CONFIG: Record<string, { label: string; color: string; icon: React.ReactNode }> = {
  STRONG_BUY:  { label: "STRONG BUY",  color: "bg-emerald-500/20 text-emerald-400 border-emerald-500/50", icon: <TrendingUp className="h-3 w-3" /> },
  BUY:         { label: "BUY",         color: "bg-green-500/20 text-green-400 border-green-500/50",       icon: <TrendingUp className="h-3 w-3" /> },
  WATCH:       { label: "WATCH",       color: "bg-yellow-500/20 text-yellow-400 border-yellow-500/50",    icon: null },
  SELL:        { label: "SELL",        color: "bg-red-500/20 text-red-400 border-red-500/50",             icon: <TrendingDown className="h-3 w-3" /> },
  STRONG_SELL: { label: "STRONG SELL", color: "bg-rose-500/20 text-rose-400 border-rose-500/50",          icon: <TrendingDown className="h-3 w-3" /> },
  NO_TRADE:    { label: "NO TRADE",    color: "bg-muted/50 text-muted-foreground border-border",          icon: null },
};

const RISK_CONFIG: Record<string, { color: string; label: string }> = {
  LOW:    { color: "text-green-400",  label: "LOW" },
  MEDIUM: { color: "text-yellow-400", label: "MED" },
  HIGH:   { color: "text-red-400",    label: "HIGH" },
};

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
    pct >= 80 ? "bg-emerald-500" :
    pct >= 65 ? "bg-green-500"   :
    pct >= 50 ? "bg-yellow-500"  : "bg-muted";
  return (
    <div className="flex items-center gap-2 min-w-[120px]">
      <div className="flex-1 h-1.5 rounded-full bg-muted overflow-hidden">
        <div className={`h-full rounded-full ${color}`} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-xs font-mono text-muted-foreground w-8 text-right">{pct}</span>
    </div>
  );
}

function ReasonsPopover({ reasons }: { reasons: string[] | undefined }) {
  const [open, setOpen] = useState(false);
  const safeReasons = Array.isArray(reasons) ? reasons : [];
  const preview = safeReasons[0] ?? "—";
  return (
    <div>
      <button
        onClick={() => setOpen(o => !o)}
        className="text-left text-xs text-muted-foreground flex items-center gap-1 hover:text-foreground transition-colors"
      >
        <span className="truncate max-w-[220px]">{preview}</span>
        {safeReasons.length > 1 && (
          open ? <ChevronUp className="h-3 w-3 flex-shrink-0" /> : <ChevronDown className="h-3 w-3 flex-shrink-0" />
        )}
      </button>
      {open && (
        <ul className="mt-2 space-y-1 pl-2 border-l border-border">
          {safeReasons.map((r, i) => (
            <li key={i} className="text-[11px] text-muted-foreground leading-tight">{r}</li>
          ))}
        </ul>
      )}
    </div>
  );
}

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
        toast({ title: "Scan Complete", description: "Signals updated and paper trades executed." });
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
            Professional rule-based engine · EMA · RSI · MACD · VWAP · Supertrend · ATR
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

      {/* Summary pills */}
      {signals && signals.length > 0 && (
        <div className="flex gap-2 flex-wrap flex-shrink-0">
          {actionable.filter(s => s.signal === "STRONG_BUY").length > 0 && (
            <span className="text-xs font-mono px-2 py-0.5 rounded-full bg-emerald-500/15 text-emerald-400 border border-emerald-500/30">
              {actionable.filter(s => s.signal === "STRONG_BUY").length} STRONG BUY
            </span>
          )}
          {actionable.filter(s => s.signal === "BUY").length > 0 && (
            <span className="text-xs font-mono px-2 py-0.5 rounded-full bg-green-500/15 text-green-400 border border-green-500/30">
              {actionable.filter(s => s.signal === "BUY").length} BUY
            </span>
          )}
          {actionable.filter(s => s.signal === "SELL").length > 0 && (
            <span className="text-xs font-mono px-2 py-0.5 rounded-full bg-red-500/15 text-red-400 border border-red-500/30">
              {actionable.filter(s => s.signal === "SELL").length} SELL
            </span>
          )}
          {actionable.filter(s => s.signal === "STRONG_SELL").length > 0 && (
            <span className="text-xs font-mono px-2 py-0.5 rounded-full bg-rose-500/15 text-rose-400 border border-rose-500/30">
              {actionable.filter(s => s.signal === "STRONG_SELL").length} STRONG SELL
            </span>
          )}
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
          </CardTitle>
        </CardHeader>
        <CardContent className="p-0 flex-1 overflow-auto">
          {isLoading && !signals ? (
            <div className="p-12 text-center text-muted-foreground font-mono">LOADING SIGNALS...</div>
          ) : signals && signals.length > 0 ? (
            <table className="w-full text-sm">
              <thead className="bg-muted/40 sticky top-0 z-10 backdrop-blur">
                <tr className="border-b border-border/50">
                  <th className="font-mono text-[11px] uppercase text-muted-foreground text-left px-4 py-2.5 whitespace-nowrap">Stock</th>
                  <th className="font-mono text-[11px] uppercase text-muted-foreground text-center px-3 py-2.5">Signal</th>
                  <th className="font-mono text-[11px] uppercase text-muted-foreground text-right px-3 py-2.5">Price</th>
                  <th className="font-mono text-[11px] uppercase text-muted-foreground text-right px-3 py-2.5">Qty</th>
                  <th className="font-mono text-[11px] uppercase text-muted-foreground px-3 py-2.5">Confidence</th>
                  <th className="font-mono text-[11px] uppercase text-muted-foreground text-center px-3 py-2.5">Risk</th>
                  <th className="font-mono text-[11px] uppercase text-muted-foreground text-right px-3 py-2.5">Stop Loss</th>
                  <th className="font-mono text-[11px] uppercase text-muted-foreground text-right px-3 py-2.5">Target</th>
                  <th className="font-mono text-[11px] uppercase text-muted-foreground px-4 py-2.5">Reasons</th>
                  <th className="font-mono text-[11px] uppercase text-muted-foreground text-right px-4 py-2.5 whitespace-nowrap">Time</th>
                </tr>
              </thead>
              <tbody>
                {signals.map((signal, i) => {
                  const riskCfg = RISK_CONFIG[signal.risk_level] ?? RISK_CONFIG.HIGH;
                  const isBullish = ["STRONG_BUY", "BUY"].includes(signal.signal);
                  const isBearish = ["STRONG_SELL", "SELL"].includes(signal.signal);
                  return (
                    <tr
                      key={`${signal.stock}-${i}`}
                      className="border-b border-border/30 hover:bg-muted/20 transition-colors"
                    >
                      <td className="px-4 py-3 font-bold font-mono">{signal.stock}</td>
                      <td className="px-3 py-3 text-center">
                        <SignalBadge signal={signal.signal} />
                      </td>
                      <td className="px-3 py-3 text-right font-mono text-sm">
                        {formatCurrency(signal.price)}
                      </td>
                      <td className="px-3 py-3 text-right font-mono text-sm">
                        {signal.quantity}
                      </td>
                      <td className="px-3 py-3">
                        <ConfidenceBar value={signal.confidence} />
                      </td>
                      <td className="px-3 py-3 text-center">
                        <span className={`text-xs font-mono font-bold ${riskCfg.color}`}>
                          {riskCfg.label}
                        </span>
                      </td>
                      <td className={`px-3 py-3 text-right font-mono text-xs ${isBullish ? "text-red-400" : isBearish ? "text-red-400" : "text-muted-foreground"}`}>
                        {signal.stop_loss > 0 ? formatCurrency(signal.stop_loss) : "—"}
                      </td>
                      <td className={`px-3 py-3 text-right font-mono text-xs ${isBullish ? "text-green-400" : isBearish ? "text-green-400" : "text-muted-foreground"}`}>
                        {signal.target > 0 ? formatCurrency(signal.target) : "—"}
                      </td>
                      <td className="px-4 py-3 max-w-[280px]">
                        <ReasonsPopover reasons={signal.reasons} />
                      </td>
                      <td className="px-4 py-3 text-right text-muted-foreground font-mono text-xs whitespace-nowrap">
                        {formatTime(signal.time)}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          ) : (
            <div className="p-12 text-center flex flex-col items-center gap-3 text-muted-foreground">
              <div className="h-12 w-12 rounded-full bg-muted flex items-center justify-center border border-dashed border-border">
                <Play className="h-5 w-5 text-muted-foreground/50" />
              </div>
              <p className="font-mono text-sm">NO SIGNALS GENERATED</p>
              <p className="text-xs max-w-sm text-center">
                Run a scan to analyse your watchlist using EMA, RSI, MACD, VWAP, Supertrend and more.
              </p>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
