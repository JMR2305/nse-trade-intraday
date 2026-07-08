import React from "react";
import {
  useGetSignals,
  useRunScan,
  getGetPortfolioQueryKey,
  getGetSignalsQueryKey
} from "@workspace/api-client-react";
import { useQueryClient } from "@tanstack/react-query";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { Progress } from "@/components/ui/progress";
import { formatCurrency, formatTime } from "@/lib/format";
import { Play } from "lucide-react";
import { useToast } from "@/hooks/use-toast";

export default function Signals() {
  const queryClient = useQueryClient();
  const { toast } = useToast();
  
  const { data: signals, isLoading } = useGetSignals({
    query: { refetchInterval: 30000 },
  });

  const runScan = useRunScan();

  const handleRunScan = () => {
    runScan.mutate(undefined, {
      onSuccess: () => {
        queryClient.invalidateQueries({ queryKey: getGetPortfolioQueryKey() });
        queryClient.invalidateQueries({ queryKey: getGetSignalsQueryKey() });
        toast({
          title: "Scan Complete",
          description: "New signals retrieved successfully.",
        });
      },
    });
  };

  const getSignalBadge = (signalStr: string) => {
    switch (signalStr) {
      case "BUY":
        return <Badge className="bg-green-500/20 text-green-500 hover:bg-green-500/30 border-green-500/50">BUY</Badge>;
      case "SELL":
        return <Badge className="bg-red-500/20 text-red-500 hover:bg-red-500/30 border-red-500/50">SELL</Badge>;
      case "HOLD":
        return <Badge className="bg-yellow-500/20 text-yellow-600 dark:text-yellow-400 hover:bg-yellow-500/30 border-yellow-500/50">HOLD</Badge>;
      default:
        return <Badge variant="outline">{signalStr}</Badge>;
    }
  };

  return (
    <div className="space-y-6 max-w-7xl mx-auto h-full flex flex-col">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Active Signals</h1>
          <p className="text-muted-foreground text-sm mt-1">Algorithmic scan results from tracked watchlist.</p>
        </div>
        <Button 
          onClick={handleRunScan} 
          disabled={runScan.isPending}
          className="font-mono bg-primary text-primary-foreground"
        >
          <Play className={`mr-2 h-4 w-4 ${runScan.isPending ? "animate-pulse" : ""}`} />
          {runScan.isPending ? "SCANNING..." : "RUN SCAN"}
        </Button>
      </div>

      <Card className="flex-1 overflow-hidden flex flex-col bg-card/50 backdrop-blur border-border/50">
        <CardHeader className="border-b border-border/50 bg-muted/20">
          <CardTitle className="font-mono text-sm uppercase tracking-wider text-muted-foreground">
            Latest Scan Results
          </CardTitle>
        </CardHeader>
        <CardContent className="p-0 flex-1 overflow-auto">
          {isLoading && !signals ? (
            <div className="p-12 text-center text-muted-foreground font-mono">LOADING SIGNALS...</div>
          ) : signals && signals.length > 0 ? (
            <Table>
              <TableHeader className="bg-muted/50 sticky top-0 z-10 backdrop-blur">
                <TableRow>
                  <TableHead className="font-mono text-xs uppercase">Time</TableHead>
                  <TableHead className="font-mono text-xs uppercase">Stock</TableHead>
                  <TableHead className="font-mono text-xs uppercase text-center">Signal</TableHead>
                  <TableHead className="font-mono text-xs uppercase text-right">Price</TableHead>
                  <TableHead className="font-mono text-xs uppercase text-right">Qty</TableHead>
                  <TableHead className="font-mono text-xs uppercase">Confidence</TableHead>
                  <TableHead className="font-mono text-xs uppercase">Reason</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {signals.map((signal, i) => (
                  <TableRow key={`${signal.stock}-${i}`}>
                    <TableCell className="text-muted-foreground font-mono whitespace-nowrap">
                      {formatTime(signal.time)}
                    </TableCell>
                    <TableCell className="font-bold">{signal.stock}</TableCell>
                    <TableCell className="text-center">{getSignalBadge(signal.signal)}</TableCell>
                    <TableCell className="text-right font-mono">{formatCurrency(signal.price)}</TableCell>
                    <TableCell className="text-right font-mono">{signal.quantity}</TableCell>
                    <TableCell className="w-[150px]">
                      <div className="flex items-center gap-2">
                        <Progress value={signal.confidence * 100} className="h-2 flex-1 bg-muted" />
                        <span className="text-xs font-mono text-muted-foreground w-9 text-right">
                          {Math.round(signal.confidence * 100)}%
                        </span>
                      </div>
                    </TableCell>
                    <TableCell className="text-muted-foreground text-sm max-w-xs truncate">
                      {signal.reason}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          ) : (
             <div className="p-12 text-center flex flex-col items-center gap-3 text-muted-foreground">
               <div className="h-12 w-12 rounded-full bg-muted flex items-center justify-center border border-border border-dashed">
                 <Play className="h-5 w-5 text-muted-foreground/50" />
               </div>
               <p className="font-mono text-sm">NO SIGNALS GENERATED</p>
               <p className="text-xs max-w-sm text-center">Run a scan to analyze your watchlist for trading opportunities.</p>
             </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
