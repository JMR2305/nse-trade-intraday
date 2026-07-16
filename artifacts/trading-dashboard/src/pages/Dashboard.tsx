import React, { useMemo } from "react";
import {
  useGetPortfolio,
  getGetPortfolioQueryKey,
  useRunScan,
  getGetSignalsQueryKey,
  useResetPortfolio
} from "@workspace/api-client-react";
import { useQueryClient } from "@tanstack/react-query";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { formatCurrency, formatPercentage, formatTime } from "@/lib/format";
import { Play, ArrowUpRight, ArrowDownRight, RefreshCcw } from "lucide-react";
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

export default function Dashboard() {
  const queryClient = useQueryClient();
  const { toast } = useToast();
  
  const { data: portfolio, isLoading: isPortfolioLoading } = useGetPortfolio({
    query: { queryKey: getGetPortfolioQueryKey(), refetchInterval: 30000 },
  });

  const runScan = useRunScan();
  const resetPortfolio = useResetPortfolio();

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

  const handleReset = () => {
    if (!confirm("Are you sure you want to reset your paper portfolio back to ₹5,000? All positions will be closed.")) return;
    
    resetPortfolio.mutate(undefined, {
      onSuccess: () => {
        queryClient.invalidateQueries({ queryKey: getGetPortfolioQueryKey() });
        toast({
          title: "Portfolio Reset",
          description: "Portfolio successfully reset to initial capital.",
        });
      }
    });
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
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold tracking-tight">Portfolio Overview</h1>
        <div className="flex items-center gap-3">
          <Button 
            variant="outline" 
            size="sm" 
            onClick={handleReset}
            disabled={resetPortfolio.isPending}
            className="text-muted-foreground hover:text-destructive hover:bg-destructive/10"
          >
            <RefreshCcw className="h-4 w-4 mr-2" />
            Reset
          </Button>
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
    </div>
  );
}
