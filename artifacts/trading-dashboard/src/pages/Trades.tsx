import React from "react";
import { useGetTrades } from "@workspace/api-client-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { formatCurrency, formatDate } from "@/lib/format";

export default function Trades() {
  const { data: trades, isLoading } = useGetTrades({
    query: { refetchInterval: 30000 },
  });

  return (
    <div className="space-y-6 max-w-7xl mx-auto h-full flex flex-col">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Trade History</h1>
        <p className="text-muted-foreground text-sm mt-1">Complete log of all algorithmic paper trades.</p>
      </div>

      <Card className="flex-1 overflow-hidden flex flex-col bg-card/50 backdrop-blur border-border/50">
        <CardHeader className="border-b border-border/50 bg-muted/20">
          <CardTitle className="font-mono text-sm uppercase tracking-wider text-muted-foreground">
            Executed Orders
          </CardTitle>
        </CardHeader>
        <CardContent className="p-0 flex-1 overflow-auto">
          {isLoading && !trades ? (
            <div className="p-12 text-center text-muted-foreground font-mono">LOADING LEDGER...</div>
          ) : trades && trades.length > 0 ? (
            <Table>
              <TableHeader className="bg-muted/50 sticky top-0 z-10 backdrop-blur">
                <TableRow>
                  <TableHead className="font-mono text-xs uppercase">Time</TableHead>
                  <TableHead className="font-mono text-xs uppercase">Symbol</TableHead>
                  <TableHead className="font-mono text-xs uppercase">Action</TableHead>
                  <TableHead className="font-mono text-xs uppercase text-right">Price</TableHead>
                  <TableHead className="font-mono text-xs uppercase text-right">Qty</TableHead>
                  <TableHead className="font-mono text-xs uppercase text-right">Total</TableHead>
                  <TableHead className="font-mono text-xs uppercase">Reason</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {trades.map((trade) => {
                  const isBuy = trade.action === "BUY";
                  return (
                    <TableRow key={trade.id}>
                      <TableCell className="text-muted-foreground font-mono whitespace-nowrap text-sm">
                        {formatDate(trade.timestamp)}
                      </TableCell>
                      <TableCell className="font-bold">{trade.symbol}</TableCell>
                      <TableCell>
                         <Badge 
                           variant="outline" 
                           className={isBuy 
                             ? "border-green-500/50 text-green-600 dark:text-green-400 bg-green-500/10" 
                             : "border-red-500/50 text-red-600 dark:text-red-400 bg-red-500/10"
                           }
                         >
                           {trade.action}
                         </Badge>
                      </TableCell>
                      <TableCell className="text-right font-mono">{formatCurrency(trade.price)}</TableCell>
                      <TableCell className="text-right font-mono">{trade.quantity}</TableCell>
                      <TableCell className="text-right font-mono font-bold">
                        {formatCurrency(trade.total)}
                      </TableCell>
                      <TableCell className="text-muted-foreground text-sm max-w-sm truncate" title={trade.reason}>
                        {trade.reason}
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          ) : (
            <div className="p-12 text-center flex flex-col items-center gap-3 text-muted-foreground">
               <p className="font-mono text-sm">NO TRADE HISTORY</p>
               <p className="text-xs">No paper trades have been executed yet.</p>
             </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
