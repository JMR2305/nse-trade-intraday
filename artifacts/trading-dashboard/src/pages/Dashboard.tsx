import React, { useMemo, useState } from "react";
import {
  useGetPortfolio,
  getGetPortfolioQueryKey,
  useRunScan,
  getGetSignalsQueryKey
} from "@workspace/api-client-react";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { useQueryClient, useQuery } from "@tanstack/react-query";
import { PaperAutomationBanner, Phase22DashboardStatus, Phase22DailyReportPanel } from "@/components/Phase22Panels";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { formatCurrency, formatPercentage, formatTime } from "@/lib/format";
import { Play, ArrowUpRight, ArrowDownRight, RefreshCcw, TrendingUp, Trophy, BarChart2, Target } from "lucide-react";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  ReferenceLine
} from "recharts";
import { useToast } from "@/hooks/use-toast";
import DataFreshnessBar from "@/components/DataFreshnessBar";
import { API_BASE } from "@/lib/api";

interface RollingPerfPoint {
  trade_no: number;
  symbol: string;
  exit_time: string;
  rolling_win_rate: number;
  rolling_avg_return_pct: number;
  window_trades: number;
  window_full: boolean;
}

interface StrategyPerf {
  total_trades: number;
  winning_trades: number;
  losing_trades: number;
  win_rate: number;
  avg_profit: number;
  avg_loss: number;
  avg_return_pct: number;
  sharpe: number;
  profit_factor: number;
  total_pnl: number;
  best_stock: string;
  worst_stock: string;
  best_regime: string;
  rolling_performance?: RollingPerfPoint[];
}

export default function Dashboard() {
  const queryClient = useQueryClient();
  const { toast } = useToast();
  
  const { data: portfolio, isLoading: isPortfolioLoading } = useGetPortfolio({
    query: { queryKey: getGetPortfolioQueryKey(), refetchInterval: 30000 },
  });

  const { data: stratPerf, isLoading: isPerfLoading } = useQuery<StrategyPerf>({
    queryKey: ["strategy-performance"],
    queryFn: async () => {
      const res = await fetch(`${API_BASE}/strategy-performance`);
      if (!res.ok) throw new Error("Failed to load strategy performance");
      return res.json();
    },
    refetchInterval: 60_000,
    staleTime: 30_000,
  });

  const runScan = useRunScan();

  const handleRunScan = () => {
    runScan.mutate(undefined, {
      onSuccess: () => {
        queryClient.invalidateQueries({ queryKey: getGetPortfolioQueryKey() });
        queryClient.invalidateQueries({ queryKey: getGetSignalsQueryKey() });
        toast({
          title: "Scan Complete",
          description: "New signals processed and portfolio updated.",
        });
      },
      onError: () => {
        toast({
          title: "Scan Failed",
          description: "Could not complete the market scan.",
          variant: "destructive",
        });
      }
    });
  };

  const [resetDialogOpen, setResetDialogOpen] = useState(false);
  const [isResetting, setIsResetting] = useState(false);

  const handleConfirmedReset = async () => {
    setIsResetting(true);
    try {
      const res = await fetch(`${API_BASE}/portfolio/reset`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ confirmation: "RESET PORTFOLIO" }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body?.error || `Reset failed (${res.status})`);
      }
      queryClient.invalidateQueries({ queryKey: getGetPortfolioQueryKey() });
      toast({
        title: "Portfolio Reset",
        description: "Cash restored to ₹5,000. Past trades were archived, not deleted.",
      });
      setResetDialogOpen(false);
    } catch (err) {
      toast({
        title: "Reset Failed",
        description: err instanceof Error ? err.message : "Could not reset the portfolio.",
        variant: "destructive",
      });
    } finally {
      setIsResetting(false);
    }
  };

  const isPositivePnl = (portfolio?.total_pnl ?? 0) >= 0;

  const chartData = useMemo(() => {
    if (!portfolio?.pnl_history) return [];
    return portfolio.pnl_history.map(point => ({
      time: formatTime(point.timestamp),
      value: point.value
    }));
  }, [portfolio?.pnl_history]);

  if (isPortfolioLoading && !portfolio) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="animate-pulse flex flex-col items-center gap-4">
          <div className="h-8 w-8 border-4 border-primary border-t-transparent rounded-full animate-spin"></div>
          <p className="text-muted-foreground font-mono">LOADING TERMINAL...</p>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6 max-w-7xl mx-auto">
      <PaperAutomationBanner />
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold tracking-tight">Portfolio Overview</h1>
        <div className="flex items-center gap-3">
          <Button 
            variant="outline" 
            size="sm" 
            onClick={() => setResetDialogOpen(true)}
            disabled={isResetting}
            data-testid="button-reset-portfolio"
            className="text-muted-foreground hover:text-destructive hover:bg-destructive/10"
          >
            <RefreshCcw className="h-4 w-4 mr-2" />
            Reset
          </Button>
          <AlertDialog open={resetDialogOpen} onOpenChange={(open) => { if (!isResetting) setResetDialogOpen(open); }}>
            <AlertDialogContent>
              <AlertDialogHeader>
                <AlertDialogTitle>Reset paper portfolio?</AlertDialogTitle>
                <AlertDialogDescription asChild>
                  <div className="space-y-2 text-sm">
                    <p>This will:</p>
                    <ul className="list-disc pl-5 space-y-1">
                      <li>Restore cash to the initial <span className="font-mono">₹5,000</span></li>
                      <li>Close and clear all open paper positions</li>
                      <li>Archive (not delete) all completed trades — they remain in all-time history</li>
                    </ul>
                    <p className="text-muted-foreground">
                      Performance metrics and charts for the current session will start over.
                      This cannot be undone from the dashboard.
                    </p>
                  </div>
                </AlertDialogDescription>
              </AlertDialogHeader>
              <AlertDialogFooter>
                <AlertDialogCancel disabled={isResetting}>Cancel</AlertDialogCancel>
                <AlertDialogAction
                  onClick={(e) => { e.preventDefault(); handleConfirmedReset(); }}
                  disabled={isResetting}
                  data-testid="button-confirm-reset"
                  className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
                >
                  {isResetting ? "Resetting..." : "Yes, reset portfolio"}
                </AlertDialogAction>
              </AlertDialogFooter>
            </AlertDialogContent>
          </AlertDialog>
          <Button 
            onClick={handleRunScan} 
            disabled={runScan.isPending}
            className="font-mono bg-primary text-primary-foreground shadow-lg hover:shadow-primary/25 transition-all"
            data-testid="button-run-scan"
          >
            <Play className={`mr-2 h-4 w-4 ${runScan.isPending ? "animate-pulse" : ""}`} />
            {runScan.isPending ? "SCANNING..." : "RUN SCAN"}
          </Button>
        </div>
      </div>

      <DataFreshnessBar variant="scan" />

      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
        <Card className="bg-card/50 backdrop-blur border-border/50">
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground uppercase">Total Value</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold font-mono" data-testid="text-total-value">
              {formatCurrency(portfolio?.total_value ?? 0)}
            </div>
          </CardContent>
        </Card>
        
        <Card className="bg-card/50 backdrop-blur border-border/50">
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground uppercase">Total P&L</CardTitle>
            {isPositivePnl ? (
              <ArrowUpRight className="h-4 w-4 text-green-500" />
            ) : (
              <ArrowDownRight className="h-4 w-4 text-red-500" />
            )}
          </CardHeader>
          <CardContent>
            <div className={`text-2xl font-bold font-mono ${isPositivePnl ? "text-green-500" : "text-red-500"}`} data-testid="text-total-pnl">
              {isPositivePnl ? "+" : ""}{formatCurrency(portfolio?.total_pnl ?? 0)}
            </div>
            <p className={`text-xs font-mono mt-1 ${isPositivePnl ? "text-green-500/80" : "text-red-500/80"}`}>
              {isPositivePnl ? "+" : ""}{formatPercentage(portfolio?.total_pnl_pct ?? 0)}
            </p>
          </CardContent>
        </Card>

        <Card className="bg-card/50 backdrop-blur border-border/50">
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground uppercase">Invested Value</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold font-mono text-muted-foreground" data-testid="text-invested-value">
              {formatCurrency(portfolio?.invested_value ?? 0)}
            </div>
          </CardContent>
        </Card>

        <Card className="bg-card/50 backdrop-blur border-border/50">
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground uppercase">Available Cash</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold font-mono text-primary" data-testid="text-available-cash">
              {formatCurrency(portfolio?.cash ?? 0)}
            </div>
          </CardContent>
        </Card>
      </div>

      <div className="grid gap-6 md:grid-cols-3">
        <Card className="md:col-span-2 bg-card/50 backdrop-blur border-border/50">
          <CardHeader>
            <CardTitle className="font-mono text-sm uppercase tracking-wider text-muted-foreground">P&L History</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="h-[300px] w-full">
              {chartData.length > 0 ? (
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart data={chartData} margin={{ top: 5, right: 10, left: 20, bottom: 5 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" vertical={false} />
                    <XAxis 
                      dataKey="time" 
                      stroke="hsl(var(--muted-foreground))" 
                      fontSize={12} 
                      tickLine={false} 
                      axisLine={false} 
                    />
                    <YAxis 
                      stroke="hsl(var(--muted-foreground))" 
                      fontSize={12} 
                      tickFormatter={(value) => `₹${value}`} 
                      tickLine={false} 
                      axisLine={false}
                      domain={['auto', 'auto']}
                    />
                    <Tooltip 
                      contentStyle={{ backgroundColor: 'hsl(var(--card))', borderColor: 'hsl(var(--border))', borderRadius: '8px' }}
                      itemStyle={{ color: 'hsl(var(--foreground))', fontFamily: 'monospace' }}
                      formatter={(value: number) => [formatCurrency(value), 'P&L']}
                      labelStyle={{ color: 'hsl(var(--muted-foreground))', marginBottom: '4px' }}
                    />
                    <ReferenceLine y={0} stroke="hsl(var(--muted-foreground))" strokeDasharray="3 3" />
                    <Line 
                      type="stepAfter" 
                      dataKey="value" 
                      stroke="hsl(var(--primary))" 
                      strokeWidth={2} 
                      dot={false}
                      activeDot={{ r: 4, fill: "hsl(var(--primary))" }}
                    />
                  </LineChart>
                </ResponsiveContainer>
              ) : (
                <div className="h-full w-full flex items-center justify-center text-muted-foreground font-mono text-sm border border-dashed border-border rounded-md">
                  NO P&L DATA YET
                </div>
              )}
            </div>
          </CardContent>
        </Card>

        <Card className="bg-card/50 backdrop-blur border-border/50 flex flex-col h-full overflow-hidden">
          <CardHeader>
            <CardTitle className="font-mono text-sm uppercase tracking-wider text-muted-foreground">Open Positions</CardTitle>
          </CardHeader>
          <CardContent className="flex-1 overflow-auto p-0">
            {portfolio?.positions && portfolio.positions.length > 0 ? (
              <Table>
                <TableHeader className="bg-muted/50 sticky top-0">
                  <TableRow>
                    <TableHead className="font-mono text-xs uppercase">Symbol</TableHead>
                    <TableHead className="font-mono text-xs uppercase text-right">Qty</TableHead>
                    <TableHead className="font-mono text-xs uppercase text-right">P&L</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {portfolio.positions.map((pos) => {
                    const posPnlPositive = pos.pnl >= 0;
                    return (
                      <TableRow key={pos.symbol}>
                        <TableCell className="font-bold">{pos.symbol}</TableCell>
                        <TableCell className="text-right font-mono">{pos.quantity}</TableCell>
                        <TableCell className={`text-right font-mono ${posPnlPositive ? "text-green-500" : "text-red-500"}`}>
                          <div>{posPnlPositive ? "+" : ""}{formatCurrency(pos.pnl)}</div>
                          <div className="text-[10px] opacity-80">{posPnlPositive ? "+" : ""}{formatPercentage(pos.pnl_pct)}</div>
                        </TableCell>
                      </TableRow>
                    );
                  })}
                </TableBody>
              </Table>
            ) : (
              <div className="p-6 text-center text-muted-foreground font-mono text-sm">
                NO OPEN POSITIONS
              </div>
            )}
          </CardContent>
        </Card>
      </div>

      {/* Strategy Performance — auto-updated after every scheduled scan */}
      <Card className="bg-card/50 backdrop-blur border-border/50">
        <CardHeader className="pb-2">
          <div className="flex items-center justify-between">
            <CardTitle className="font-mono text-sm uppercase tracking-wider text-muted-foreground flex items-center gap-2">
              <BarChart2 className="h-4 w-4" />
              Strategy Performance
            </CardTitle>
            {stratPerf && stratPerf.total_trades > 0 && (
              <Badge variant="outline" className="text-xs font-mono">
                {stratPerf.total_trades} completed trades
              </Badge>
            )}
          </div>
        </CardHeader>
        <CardContent>
          {isPerfLoading ? (
            <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
              {[...Array(4)].map((_, i) => (
                <div key={i} className="h-16 rounded-md bg-muted/30 animate-pulse" />
              ))}
            </div>
          ) : !stratPerf || stratPerf.total_trades === 0 ? (
            <div className="py-6 text-center text-muted-foreground font-mono text-sm border border-dashed border-border rounded-md">
              NO COMPLETED TRADES YET — performance metrics will appear after the algo closes its first position
            </div>
          ) : (
            <>
              <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
                {/* Win Rate */}
                <div className="rounded-lg border border-border/50 bg-background/40 p-4">
                  <div className="flex items-center gap-2 mb-1">
                    <Trophy className="h-3.5 w-3.5 text-muted-foreground" />
                    <span className="text-xs font-mono uppercase text-muted-foreground">Win Rate</span>
                  </div>
                  <div className={`text-2xl font-bold font-mono ${stratPerf.win_rate >= 55 ? "text-green-500" : stratPerf.win_rate >= 45 ? "text-amber-400" : "text-red-500"}`}>
                    {stratPerf.win_rate.toFixed(1)}%
                  </div>
                  <div className="text-xs text-muted-foreground mt-1">
                    {stratPerf.winning_trades}W / {stratPerf.losing_trades}L
                  </div>
                </div>

                {/* Avg Return per Trade */}
                <div className="rounded-lg border border-border/50 bg-background/40 p-4">
                  <div className="flex items-center gap-2 mb-1">
                    <TrendingUp className="h-3.5 w-3.5 text-muted-foreground" />
                    <span className="text-xs font-mono uppercase text-muted-foreground">Avg Return / Trade</span>
                  </div>
                  <div className={`text-2xl font-bold font-mono ${stratPerf.avg_return_pct >= 0 ? "text-green-500" : "text-red-500"}`}>
                    {stratPerf.avg_return_pct >= 0 ? "+" : ""}{stratPerf.avg_return_pct.toFixed(2)}%
                  </div>
                  <div className="text-xs text-muted-foreground mt-1">
                    per closed trade
                  </div>
                </div>

                {/* Sharpe Ratio */}
                <div className="rounded-lg border border-border/50 bg-background/40 p-4">
                  <div className="flex items-center gap-2 mb-1">
                    <Target className="h-3.5 w-3.5 text-muted-foreground" />
                    <span className="text-xs font-mono uppercase text-muted-foreground">Sharpe Ratio</span>
                  </div>
                  <div className={`text-2xl font-bold font-mono ${stratPerf.sharpe >= 1.0 ? "text-green-500" : stratPerf.sharpe >= 0 ? "text-amber-400" : "text-red-500"}`}>
                    {stratPerf.sharpe.toFixed(2)}
                  </div>
                  <div className="text-xs text-muted-foreground mt-1">
                    {stratPerf.sharpe >= 1.5 ? "excellent" : stratPerf.sharpe >= 1.0 ? "good" : stratPerf.sharpe >= 0.5 ? "moderate" : "needs improvement"}
                  </div>
                </div>

                {/* Profit Factor */}
                <div className="rounded-lg border border-border/50 bg-background/40 p-4">
                  <div className="flex items-center gap-2 mb-1">
                    <ArrowUpRight className="h-3.5 w-3.5 text-muted-foreground" />
                    <span className="text-xs font-mono uppercase text-muted-foreground">Profit Factor</span>
                  </div>
                  <div className={`text-2xl font-bold font-mono ${stratPerf.profit_factor >= 1.5 ? "text-green-500" : stratPerf.profit_factor >= 1.0 ? "text-amber-400" : "text-red-500"}`}>
                    {stratPerf.profit_factor >= 100 ? "—" : stratPerf.profit_factor.toFixed(2)}x
                  </div>
                  <div className="text-xs text-muted-foreground mt-1">
                    gross profit / gross loss
                  </div>
                </div>
              </div>

              {/* Rolling performance trend (10-trade window) */}
              {(stratPerf.rolling_performance?.length ?? 0) >= 2 && (
                <div className="mt-4 rounded-lg border border-border/50 bg-background/40 p-4">
                  <div className="flex items-center justify-between mb-2">
                    <span className="text-xs font-mono uppercase text-muted-foreground">
                      Rolling Trend — last 10 trades window
                    </span>
                    <span className="text-[10px] font-mono text-muted-foreground">
                      per closed trade, chronological
                    </span>
                  </div>
                  <div className="h-56">
                    <ResponsiveContainer width="100%" height="100%">
                      <LineChart
                        data={stratPerf.rolling_performance}
                        margin={{ top: 5, right: 10, left: 0, bottom: 5 }}
                      >
                        <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" opacity={0.3} />
                        <XAxis
                          dataKey="trade_no"
                          tick={{ fontSize: 10, fontFamily: "monospace" }}
                          stroke="hsl(var(--muted-foreground))"
                          label={{ value: "Closed trade #", position: "insideBottom", offset: -2, fontSize: 10 }}
                        />
                        <YAxis
                          yAxisId="wr"
                          domain={[0, 100]}
                          tick={{ fontSize: 10, fontFamily: "monospace" }}
                          stroke="hsl(var(--muted-foreground))"
                          tickFormatter={(v) => `${v}%`}
                          width={42}
                        />
                        <YAxis
                          yAxisId="ret"
                          orientation="right"
                          tick={{ fontSize: 10, fontFamily: "monospace" }}
                          stroke="hsl(var(--muted-foreground))"
                          tickFormatter={(v) => `${v}%`}
                          width={42}
                        />
                        <Tooltip
                          contentStyle={{
                            backgroundColor: "hsl(var(--card))",
                            border: "1px solid hsl(var(--border))",
                            borderRadius: 6,
                            fontSize: 11,
                            fontFamily: "monospace",
                          }}
                          formatter={(value: number, name: string) =>
                            name === "Win rate"
                              ? [`${value.toFixed(1)}%`, "Win rate"]
                              : [`${value >= 0 ? "+" : ""}${value.toFixed(2)}%`, "Avg return"]
                          }
                          labelFormatter={(label: number) => {
                            const p = stratPerf.rolling_performance?.[Number(label) - 1];
                            return p
                              ? `Trade #${label} · ${p.symbol}${p.window_full ? "" : ` (only ${p.window_trades} trades in window)`}`
                              : `Trade #${label}`;
                          }}
                        />
                        <ReferenceLine yAxisId="wr" y={50} stroke="hsl(var(--muted-foreground))" strokeDasharray="4 4" opacity={0.5} />
                        <ReferenceLine yAxisId="ret" y={0} stroke="hsl(var(--muted-foreground))" strokeDasharray="2 2" opacity={0.35} />
                        <Line
                          yAxisId="wr"
                          type="monotone"
                          dataKey="rolling_win_rate"
                          name="Win rate"
                          stroke="#22c55e"
                          strokeWidth={2}
                          dot={false}
                          activeDot={{ r: 3 }}
                        />
                        <Line
                          yAxisId="ret"
                          type="monotone"
                          dataKey="rolling_avg_return_pct"
                          name="Avg return"
                          stroke="#38bdf8"
                          strokeWidth={2}
                          strokeDasharray="6 3"
                          dot={false}
                          activeDot={{ r: 3 }}
                        />
                      </LineChart>
                    </ResponsiveContainer>
                  </div>
                  <div className="mt-2 flex gap-4 text-[10px] font-mono text-muted-foreground">
                    <span className="flex items-center gap-1">
                      <span className="inline-block h-0.5 w-4 bg-green-500" /> Rolling win rate % (left axis)
                    </span>
                    <span className="flex items-center gap-1">
                      <span className="inline-block h-0.5 w-4 bg-sky-400" style={{ borderTop: "2px dashed #38bdf8", background: "transparent" }} /> Rolling avg return % (right axis)
                    </span>
                  </div>
                </div>
              )}

              {/* Secondary stats row */}
              <div className="mt-3 flex flex-wrap gap-x-6 gap-y-1 text-xs font-mono text-muted-foreground">
                <span>Best stock: <span className="text-foreground">{stratPerf.best_stock}</span></span>
                <span>Worst stock: <span className="text-foreground">{stratPerf.worst_stock}</span></span>
                <span>Best regime: <span className="text-foreground">{stratPerf.best_regime}</span></span>
                <span>Total P&amp;L: <span className={stratPerf.total_pnl >= 0 ? "text-green-500" : "text-red-500"}>{stratPerf.total_pnl >= 0 ? "+" : ""}{formatCurrency(stratPerf.total_pnl)}</span></span>
              </div>
            </>
          )}
        </CardContent>
      </Card>

      {/* Phase 22: paper automation status + daily close report */}
      <Phase22DashboardStatus />
      <Phase22DailyReportPanel />
    </div>
  );
}
