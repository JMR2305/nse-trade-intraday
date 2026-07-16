import React from "react";
import {
  useGetMarketOverview,
  getGetMarketOverviewQueryKey,
} from "@workspace/api-client-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { formatCurrency, formatTime } from "@/lib/format";
import DataFreshnessBar from "@/components/DataFreshnessBar";
import {
  TrendingUp, TrendingDown, Minus, Activity, Zap,
  BarChart2, AlertTriangle, RefreshCcw,
} from "lucide-react";

// ── Config maps ───────────────────────────────────────────────────────────────

const REGIME_CONFIG: Record<string, { color: string; bg: string; label: string; icon: React.ReactNode }> = {
  BULLISH:         { color: "text-emerald-400", bg: "bg-emerald-500/10 border-emerald-500/30", label: "BULLISH",         icon: <TrendingUp className="h-4 w-4" /> },
  BEARISH:         { color: "text-red-400",     bg: "bg-red-500/10 border-red-500/30",         label: "BEARISH",         icon: <TrendingDown className="h-4 w-4" /> },
  SIDEWAYS:        { color: "text-yellow-400",  bg: "bg-yellow-500/10 border-yellow-500/30",   label: "SIDEWAYS",        icon: <Minus className="h-4 w-4" /> },
  HIGH_VOLATILITY: { color: "text-orange-400",  bg: "bg-orange-500/10 border-orange-500/30",   label: "HIGH VOLATILITY", icon: <AlertTriangle className="h-4 w-4" /> },
  LOW_VOLATILITY:  { color: "text-blue-400",    bg: "bg-blue-500/10 border-blue-500/30",       label: "LOW VOLATILITY",  icon: <Activity className="h-4 w-4" /> },
};

const VIX_CONFIG: Record<string, { color: string; label: string }> = {
  LOW:      { color: "text-emerald-400", label: "LOW — Calm market" },
  MODERATE: { color: "text-yellow-400",  label: "MODERATE — Normal" },
  HIGH:     { color: "text-orange-400",  label: "HIGH — Elevated fear" },
  EXTREME:  { color: "text-red-400",     label: "EXTREME — Panic" },
};

const TREND_ICON: Record<string, React.ReactNode> = {
  UP:      <TrendingUp className="h-4 w-4 text-emerald-400" />,
  DOWN:    <TrendingDown className="h-4 w-4 text-red-400" />,
  SIDEWAYS:<Minus className="h-4 w-4 text-yellow-400" />,
};

const SIGNAL_COLORS: Record<string, string> = {
  STRONG_BUY:  "text-emerald-400",
  BUY:         "text-green-400",
  WATCH:       "text-yellow-400",
  SELL:        "text-red-400",
  STRONG_SELL: "text-rose-400",
  NO_TRADE:    "text-muted-foreground",
};

// ── Sub-components ────────────────────────────────────────────────────────────

function IndexCard({
  name, price, changePct, trend,
}: { name: string; price: number; changePct: number; trend: string }) {
  const isUp = changePct >= 0;
  return (
    <Card className="bg-card/50 backdrop-blur border-border/50">
      <CardContent className="p-4">
        <div className="flex items-center justify-between mb-2">
          <span className="text-xs font-mono uppercase text-muted-foreground tracking-wider">{name}</span>
          {TREND_ICON[trend] ?? TREND_ICON["SIDEWAYS"]}
        </div>
        <div className="text-xl font-bold font-mono">
          {price > 0 ? formatCurrency(price) : "—"}
        </div>
        <div className={`text-sm font-mono mt-1 ${isUp ? "text-emerald-400" : "text-red-400"}`}>
          {isUp ? "+" : ""}{changePct.toFixed(2)}% (5-day)
        </div>
      </CardContent>
    </Card>
  );
}

function MarketScoreGauge({ score }: { score: number }) {
  const color =
    score >= 70 ? "text-emerald-400" :
    score >= 55 ? "text-yellow-400"  : "text-red-400";
  const barColor =
    score >= 70 ? "bg-emerald-500" :
    score >= 55 ? "bg-yellow-500"  : "bg-red-500";
  const label =
    score >= 70 ? "STRONG" :
    score >= 55 ? "NEUTRAL" : "WEAK";

  return (
    <div className="flex flex-col items-center gap-2 p-2">
      <div className={`text-4xl font-bold font-mono ${color}`}>{score.toFixed(0)}</div>
      <div className="text-xs text-muted-foreground font-mono">/ 100</div>
      <div className="w-full h-2 bg-muted rounded-full overflow-hidden">
        <div className={`h-full rounded-full transition-all ${barColor}`} style={{ width: `${score}%` }} />
      </div>
      <Badge variant="outline" className={`font-mono text-xs ${color}`}>
        {label} MARKET
      </Badge>
    </div>
  );
}

function StockRankRow({
  rank, symbol, price, signal, confidence, isStrong,
}: {
  rank: number; symbol: string; price: number;
  signal: string; confidence: number; isStrong: boolean;
}) {
  const signalColor = SIGNAL_COLORS[signal] ?? "text-muted-foreground";
  return (
    <div className="flex items-center justify-between py-2 px-3 rounded hover:bg-muted/20 transition-colors">
      <div className="flex items-center gap-3">
        <span className="text-xs text-muted-foreground font-mono w-4">{rank}</span>
        <span className="font-bold font-mono text-sm">{symbol}</span>
      </div>
      <div className="flex items-center gap-4">
        <span className="text-sm font-mono text-muted-foreground">
          {price > 0 ? `₹${price.toLocaleString("en-IN", { maximumFractionDigits: 0 })}` : "—"}
        </span>
        <div className="flex items-center gap-1.5">
          <div className="w-16 h-1.5 bg-muted rounded-full overflow-hidden">
            <div
              className={`h-full rounded-full ${isStrong ? "bg-emerald-500" : "bg-red-500"}`}
              style={{ width: `${confidence}%` }}
            />
          </div>
          <span className={`text-xs font-mono font-bold w-24 ${signalColor}`}>
            {signal.replace(/_/g, " ")}
          </span>
        </div>
      </div>
    </div>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function MarketOverview() {
  const { data: overview, isLoading, refetch, isFetching } = useGetMarketOverview({
    query: {
      queryKey: getGetMarketOverviewQueryKey(),
      refetchInterval: 5 * 60 * 1000,
    },
  });

  const regimeCfg = REGIME_CONFIG[overview?.regime ?? "SIDEWAYS"] ?? REGIME_CONFIG["SIDEWAYS"];
  const vixCfg = VIX_CONFIG[overview?.vix_status ?? "MODERATE"] ?? VIX_CONFIG["MODERATE"];

  if (isLoading && !overview) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="flex flex-col items-center gap-4">
          <div className="h-8 w-8 border-4 border-primary border-t-transparent rounded-full animate-spin" />
          <p className="text-muted-foreground font-mono text-sm">LOADING MARKET DATA...</p>
          <p className="text-muted-foreground/60 text-xs">Fetching NIFTY · BANKNIFTY · VIX — may take 30–60 s</p>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-5 max-w-7xl mx-auto">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Market Intelligence</h1>
          <p className="text-muted-foreground text-sm mt-0.5">
            NSE regime analysis · NIFTY · BANKNIFTY · VIX · Market breadth
          </p>
        </div>
        <div className="flex items-center gap-3">
          {overview?.scanned_at && (
            <span className="text-xs text-muted-foreground font-mono">
              Last scan: {formatTime(overview.scanned_at)}
            </span>
          )}
          <button
            onClick={() => refetch()}
            disabled={isFetching}
            className="flex items-center gap-2 text-xs font-mono px-3 py-1.5 rounded border border-border hover:bg-muted/40 transition-colors text-muted-foreground hover:text-foreground disabled:opacity-50"
          >
            <RefreshCcw className={`h-3 w-3 ${isFetching ? "animate-spin" : ""}`} />
            Refresh
          </button>
        </div>
      </div>

      <DataFreshnessBar variant="quotes" quoteTimestamp={overview?.scanned_at} />

      {/* Index + VIX + Score cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <IndexCard
          name="NIFTY 50"
          price={overview?.nifty_price ?? 0}
          changePct={overview?.nifty_change_pct ?? 0}
          trend={overview?.nifty_trend ?? "SIDEWAYS"}
        />
        <IndexCard
          name="BANK NIFTY"
          price={overview?.banknifty_price ?? 0}
          changePct={overview?.banknifty_change_pct ?? 0}
          trend={overview?.banknifty_trend ?? "SIDEWAYS"}
        />

        <Card className="bg-card/50 backdrop-blur border-border/50">
          <CardContent className="p-4">
            <div className="flex items-center justify-between mb-2">
              <span className="text-xs font-mono uppercase text-muted-foreground tracking-wider">INDIA VIX</span>
              <Zap className="h-4 w-4 text-muted-foreground" />
            </div>
            <div className="text-xl font-bold font-mono">{(overview?.vix_value ?? 0).toFixed(1)}</div>
            <div className={`text-xs font-mono mt-1 ${vixCfg.color}`}>{vixCfg.label}</div>
          </CardContent>
        </Card>

        <Card className="bg-card/50 backdrop-blur border-border/50">
          <CardContent className="p-3">
            <div className="text-xs font-mono uppercase text-muted-foreground tracking-wider text-center mb-1">
              MARKET SCORE
            </div>
            <MarketScoreGauge score={overview?.market_score ?? 50} />
          </CardContent>
        </Card>
      </div>

      {/* Regime banner */}
      <Card className={`border ${regimeCfg.bg}`}>
        <CardContent className="p-4">
          <div className="flex items-start gap-3">
            <div className={`mt-0.5 ${regimeCfg.color}`}>{regimeCfg.icon}</div>
            <div>
              <div className="flex items-center gap-2 mb-1">
                <span className={`font-mono font-bold text-sm ${regimeCfg.color}`}>
                  {regimeCfg.label} REGIME
                </span>
                <BarChart2 className="h-3.5 w-3.5 text-muted-foreground" />
              </div>
              <p className="text-sm text-muted-foreground leading-relaxed">
                {overview?.regime_description ?? "Analysing market conditions..."}
              </p>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Top 5 Strong / Weak */}
      <div className="grid md:grid-cols-2 gap-4">
        <Card className="bg-card/50 backdrop-blur border-border/50">
          <CardHeader className="py-3 px-4 border-b border-border/50">
            <CardTitle className="font-mono text-xs uppercase tracking-wider text-muted-foreground flex items-center gap-2">
              <TrendingUp className="h-3.5 w-3.5 text-emerald-400" />
              Top 5 Strongest Stocks
            </CardTitle>
          </CardHeader>
          <CardContent className="p-2">
            {overview?.top_strong && overview.top_strong.length > 0 ? (
              overview.top_strong.map((stock, i) => (
                <StockRankRow
                  key={stock.symbol}
                  rank={i + 1}
                  symbol={stock.symbol}
                  price={stock.price}
                  signal={stock.signal}
                  confidence={stock.confidence}
                  isStrong
                />
              ))
            ) : (
              <div className="py-8 text-center text-muted-foreground text-sm font-mono">
                Refresh to scan watchlist rankings
              </div>
            )}
          </CardContent>
        </Card>

        <Card className="bg-card/50 backdrop-blur border-border/50">
          <CardHeader className="py-3 px-4 border-b border-border/50">
            <CardTitle className="font-mono text-xs uppercase tracking-wider text-muted-foreground flex items-center gap-2">
              <TrendingDown className="h-3.5 w-3.5 text-red-400" />
              Top 5 Weakest Stocks
            </CardTitle>
          </CardHeader>
          <CardContent className="p-2">
            {overview?.top_weak && overview.top_weak.length > 0 ? (
              overview.top_weak.map((stock, i) => (
                <StockRankRow
                  key={stock.symbol}
                  rank={i + 1}
                  symbol={stock.symbol}
                  price={stock.price}
                  signal={stock.signal}
                  confidence={stock.confidence}
                  isStrong={false}
                />
              ))
            ) : (
              <div className="py-8 text-center text-muted-foreground text-sm font-mono">
                Refresh to scan watchlist rankings
              </div>
            )}
          </CardContent>
        </Card>
      </div>

      {/* How regime affects signals */}
      <Card className="bg-card/30 border-border/30">
        <CardContent className="p-4">
          <p className="text-xs text-muted-foreground font-mono uppercase tracking-wider mb-3">
            How Regime Affects Signal Confidence
          </p>
          <div className="grid grid-cols-2 md:grid-cols-5 gap-2 text-xs">
            {[
              { regime: "BULLISH",         effect: "SELL score −20" },
              { regime: "BEARISH",         effect: "BUY score −20" },
              { regime: "SIDEWAYS",        effect: "Both sides −10" },
              { regime: "HIGH VOLATILITY", effect: "Risk level ↑" },
              { regime: "LOW VOLATILITY",  effect: "No adjustment" },
            ].map(({ regime, effect }) => (
              <div key={regime} className="flex flex-col gap-0.5 p-2 rounded bg-muted/20 border border-border/30">
                <span className="font-mono font-bold text-foreground/80">{regime}</span>
                <span className="text-muted-foreground">{effect}</span>
              </div>
            ))}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
