import React, { useState } from "react";
import {
  useGetWatchlist,
  getGetWatchlistQueryKey,
  useAddToWatchlist,
  useRemoveFromWatchlist,
} from "@workspace/api-client-react";
import { useQueryClient } from "@tanstack/react-query";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Trash2, Plus, TrendingUp } from "lucide-react";
import { useToast } from "@/hooks/use-toast";

export default function Watchlist() {
  const [newSymbol, setNewSymbol] = useState("");
  const queryClient = useQueryClient();
  const { toast } = useToast();

  const { data, isLoading } = useGetWatchlist();
  
  const addMutation = useAddToWatchlist();
  const removeMutation = useRemoveFromWatchlist();

  const handleAdd = (e: React.FormEvent) => {
    e.preventDefault();
    const symbol = newSymbol.trim().toUpperCase();
    if (!symbol) return;

    if (data?.watchlist.includes(symbol)) {
      toast({
        title: "Already in watchlist",
        description: `${symbol} is already being tracked.`,
        variant: "destructive",
      });
      return;
    }

    addMutation.mutate({ data: { symbol } }, {
      onSuccess: () => {
        setNewSymbol("");
        queryClient.invalidateQueries({ queryKey: getGetWatchlistQueryKey() });
        toast({
          title: "Added to watchlist",
          description: `${symbol} is now being tracked.`,
        });
      },
      onError: () => {
        toast({
          title: "Failed to add",
          description: `Could not add ${symbol} to watchlist.`,
          variant: "destructive",
        });
      }
    });
  };

  const handleRemove = (symbol: string) => {
    removeMutation.mutate({ symbol }, {
      onSuccess: () => {
        queryClient.invalidateQueries({ queryKey: getGetWatchlistQueryKey() });
        toast({
          title: "Removed",
          description: `${symbol} removed from watchlist.`,
        });
      }
    });
  };

  const watchlist = data?.watchlist || [];

  return (
    <div className="space-y-6 max-w-4xl mx-auto">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Market Watchlist</h1>
        <p className="text-muted-foreground text-sm mt-1">Manage the NSE symbols your algorithm actively scans.</p>
      </div>

      <Card className="bg-card/50 backdrop-blur border-border/50">
        <CardHeader>
          <CardTitle>Tracked Symbols</CardTitle>
          <CardDescription>
            Add NSE tickers (e.g. RELIANCE, TCS, INFY)
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-6">
          <form onSubmit={handleAdd} className="flex gap-3">
            <Input
              placeholder="Enter NSE Symbol..."
              value={newSymbol}
              onChange={(e) => setNewSymbol(e.target.value.toUpperCase())}
              className="font-mono max-w-xs uppercase bg-background"
              disabled={addMutation.isPending}
            />
            <Button type="submit" disabled={!newSymbol.trim() || addMutation.isPending}>
              <Plus className="h-4 w-4 mr-2" />
              Add Symbol
            </Button>
          </form>

          {isLoading && !data ? (
            <div className="py-8 text-center text-muted-foreground font-mono">LOADING WATCHLIST...</div>
          ) : watchlist.length > 0 ? (
            <div className="grid gap-3 grid-cols-1 sm:grid-cols-2 md:grid-cols-3">
              {watchlist.map((symbol) => (
                <div 
                  key={symbol} 
                  className="flex items-center justify-between p-3 rounded-lg border border-border/60 bg-muted/20 hover:bg-muted/40 transition-colors group"
                >
                  <div className="flex items-center gap-3">
                    <div className="h-8 w-8 rounded-md bg-primary/10 flex items-center justify-center text-primary">
                      <TrendingUp className="h-4 w-4" />
                    </div>
                    <span className="font-bold font-mono text-foreground">{symbol}</span>
                  </div>
                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-8 w-8 text-muted-foreground opacity-0 group-hover:opacity-100 hover:text-destructive hover:bg-destructive/10 transition-all"
                    onClick={() => handleRemove(symbol)}
                    disabled={removeMutation.isPending}
                    title={`Remove ${symbol}`}
                  >
                    <Trash2 className="h-4 w-4" />
                  </Button>
                </div>
              ))}
            </div>
          ) : (
            <div className="py-12 text-center border border-dashed border-border rounded-lg bg-muted/10 flex flex-col items-center gap-3">
               <Eye className="h-6 w-6 text-muted-foreground/50" />
               <p className="font-mono text-sm text-muted-foreground">WATCHLIST EMPTY</p>
               <p className="text-xs text-muted-foreground/80">Add symbols to begin tracking signals.</p>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

// Temporary local import to make the empty state work since Watchlist component doesn't import Eye at the top
import { Eye } from "lucide-react";
