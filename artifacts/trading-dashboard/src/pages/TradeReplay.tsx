import { useState } from "react";
import {
  useGetTradeReplay,
  useGetStrategyPerformance,
  useGetLearningSummary,
  type TradeReplayItem,
  type StrategyLearning,
} from "@workspace/api-client-react";
import { formatCurrency } from "@/lib/format";
import {
  RotateCcw,
  ChevronDown,
  ChevronRight,
  TrendingUp,
  TrendingDown,
  Target,
  ShieldOff,
  Clock,
  Brain,
  Trophy,
  AlertCircle,
  BarChart2,
  Percent,
  GraduationCap,
  ArrowUpRight,
  ArrowDownRight,
  Minus,
} from "lucide-react";

// ── Helpers ────────────────────────────────────────────────────────────────────

function formatDate(iso: string): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return d.toLocaleDateString("en-IN", { day: "2-digit", month: "short" }) +
    " " + d.toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit" });
}

const EXIT_META: Record<string, { label: string; color: string; icon: typeof Target }> = {
  TARGET_HIT:  { label: "Target Hit",  color: "text-emerald-400 bg-emerald-400/10 border-emerald-500/30", icon: Target },
  STOP_HIT:    { label: "Stop Hit",    color: "text-red-400 bg-red-400/10 border-red-500/30",             icon: ShieldOff },
  SIGNAL_EXIT: { label: "Signal Exit", color: "text-yellow-400 bg-yellow-400/10 border-yellow-500/30",    icon: TrendingDown },
  MANUAL:      { label: "Manual",      color: "text-zinc-400 bg-zinc-800 border-zinc-700",                icon: Clock },
};

function ExitBadge({ type }: { type: string }) {
  const m = EXIT_META[type] ?? EXIT_META.MANUAL;
  const Icon = m.icon;
  return (
    <span className={`inline-flex items-center gap-1 font-mono text-xs px-2 py-0.5 rounded border ${m.color}`}>
      <Icon className="h-3 w-3" />
      {m.label}
    </span>
  );
}

const OUTCOME_META: Record<string, { color: string }> = {
  Excellent:   { color: "text-emerald-400 bg-emerald-400/10 border-emerald-500/30" },
  Good:        { color: "text-lime-400 bg-lime-400/10 border-lime-500/30" },
  Weak:        { color: "text-yellow-400 bg-yellow-400/10 border-yellow-500/30" },
  "Small Loss": { color: "text-orange-400 bg-orange-400/10 border-orange-500/30" },
  Failed:      { color: "text-red-400 bg-red-400/10 border-red-500/30" },
};

function OutcomeBadge({ label }: { label: string }) {
  const m = OUTCOME_META[label] ?? OUTCOME_META.Weak;
  return (
    <span className={`inline-flex items-center font-mono text-xs px-2 py-0.5 rounded border ${m.color}`}>
      {label}
    </span>
  );
}

function PnlDisplay({ pnl, pnl_pct }: { pnl: number; pnl_pct: number }) {
  const pos = pnl >= 0;
  return (
    <div className={`flex flex-col ${pos ? "text-emerald-400" : "text-red-400"}`}>
      <span className="font-mono font-bold text-sm">
        {pos ? "+" : ""}{formatCurrency(pnl)}
      </span>
      <span className="font-mono text-xs opacity-70">
        {pos ? "+" : ""}{pnl_pct.toFixed(2)}%
      </span>
    </div>
  );
}

// ── Strategy Performance Section ───────────────────────────────────────────────

function PerformanceSection() {
  const { data: perf, isLoading } = useGetStrategyPerformance();

  if (isLoading) {
    return (
      <div className="rounded-lg border border-border bg-card p-6 text-center text-muted-foreground text-sm font-mono">
        Computing performance…
      </div>
    );
  }

  if (!perf || perf.total_trades === 0) {
    return (
      <div className="rounded-lg border border-border bg-card p-6 text-center space-y-2">
        <BarChart2 className="h-8 w-8 text-muted-foreground/30 mx-auto" />
        <p className="text-sm text-muted-foreground font-mono">No completed trades yet</p>
        <p className="text-xs text-muted-foreground/60">
          Complete a BUY → SELL cycle to see performance metrics
        </p>
      </div>
    );
  }

  const pnlColor = perf.total_pnl >= 0 ? "text-emerald-400" : "text-red-400";
  const winColor = perf.win_rate >= 60 ? "text-emerald-400" : perf.win_rate >= 40 ? "text-yellow-400" : "text-red-400";
  const pfColor  = perf.profit_factor >= 1.5 ? "text-emerald-400" : perf.profit_factor >= 1 ? "text-yellow-400" : "text-red-400";

  const cards = [
    {
      label: "Total Trades",
      value: perf.total_trades.toString(),
      sub: `${perf.winning_trades}W / ${perf.losing_trades}L`,
      icon: BarChart2,
      color: "text-primary",
      bg: "bg-primary/10",
    },
    {
      label: "Win Rate",
      value: `${perf.win_rate.toFixed(1)}%`,
      sub: `${perf.winning_trades} of ${perf.total_trades} trades`,
      icon: Percent,
      color: winColor,
      bg: perf.win_rate >= 60 ? "bg-emerald-400/10" : "bg-yellow-400/10",
    },
    {
      label: "Profit Factor",
      value: perf.profit_factor >= 999 ? "∞" : perf.profit_factor.toFixed(2),
      sub: "Total profit / Total loss",
      icon: TrendingUp,
      color: pfColor,
      bg: perf.profit_factor >= 1 ? "bg-emerald-400/10" : "bg-red-400/10",
    },
    {
      label: "Total P&L",
      value: `${perf.total_pnl >= 0 ? "+" : ""}${formatCurrency(perf.total_pnl)}`,
      sub: `Avg win ${formatCurrency(perf.avg_profit)} / loss ${formatCurrency(perf.avg_loss)}`,
      icon: perf.total_pnl >= 0 ? TrendingUp : TrendingDown,
      color: pnlColor,
      bg: perf.total_pnl >= 0 ? "bg-emerald-400/10" : "bg-red-400/10",
    },
    {
      label: "Best Stock",
      value: perf.best_stock,
      sub: "Highest total P&L",
      icon: Trophy,
      color: "text-emerald-400",
      bg: "bg-emerald-400/10",
    },
    {
      label: "Worst Stock",
      value: perf.worst_stock,
      sub: "Lowest total P&L",
      icon: AlertCircle,
      color: "text-red-400",
      bg: "bg-red-400/10",
    },
    {
      label: "Best Regime",
      value: perf.best_regime.replace("_", " "),
      sub: "Highest win rate regime",
      icon: Target,
      color: "text-primary",
      bg: "bg-primary/10",
    },
  ];

  return (
    <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-3">
      {cards.map(({ label, value, sub, icon: Icon, color, bg }) => (
        <div key={label} className="rounded-lg border border-border bg-card p-4 space-y-2">
          <div className="flex items-center justify-between">
            <span className="text-xs font-mono text-muted-foreground uppercase tracking-wide">{label}</span>
            <div className={`p-1.5 rounded-md ${bg}`}>
              <Icon className={`h-3.5 w-3.5 ${color}`} />
            </div>
          </div>
          <div className={`font-mono font-bold text-xl ${color}`}>{value}</div>
          <div className="text-xs text-muted-foreground/60 font-mono">{sub}</div>
        </div>
      ))}
    </div>
  );
}

// ── Learning Summary Section ────────────────────────────────────────────────────

const DIRECTION_META: Record<string, { icon: typeof ArrowUpRight; color: string; label: string }> = {
  increase: { icon: ArrowUpRight,   color: "text-emerald-400", label: "Increase weight" },
  decrease: { icon: ArrowDownRight, color: "text-red-400",     label: "Decrease weight" },
  hold:     { icon: Minus,          color: "text-muted-foreground", label: "Hold weight" },
};

function StrategyLearningCard({ s }: { s: StrategyLearning }) {
  const dm = DIRECTION_META[s.direction] ?? DIRECTION_META.hold;
  const DirIcon = dm.icon;
  return (
    <div className="rounded-lg border border-border bg-card p-4 space-y-3" data-testid={`learning-card-${s.strategy_id}`}>
      <div className="flex items-start justify-between gap-2">
        <div>
          <div className="font-mono font-bold text-sm">{s.strategy_name}</div>
          <div className="text-xs text-muted-foreground/60 font-mono">{s.total_trades} completed trades</div>
        </div>
        <span className={`inline-flex items-center gap-1 font-mono text-xs px-2 py-0.5 rounded border border-border ${dm.color}`}>
          <DirIcon className="h-3 w-3" />
          {dm.label}
        </span>
      </div>

      <div className="grid grid-cols-3 gap-2 text-center">
        <div>
          <div className="text-xs text-muted-foreground font-mono">WIN RATE</div>
          <div className="font-mono font-bold text-sm">{s.win_rate.toFixed(0)}%</div>
        </div>
        <div>
          <div className="text-xs text-muted-foreground font-mono">PROFIT FACTOR</div>
          <div className="font-mono font-bold text-sm">{s.profit_factor >= 99 ? "∞" : s.profit_factor.toFixed(2)}</div>
        </div>
        <div>
          <div className="text-xs text-muted-foreground font-mono">EXPECTANCY</div>
          <div className={`font-mono font-bold text-sm ${s.expectancy >= 0 ? "text-emerald-400" : "text-red-400"}`}>
            {formatCurrency(s.expectancy)}
          </div>
        </div>
      </div>

      <div className="flex items-center justify-between text-xs font-mono bg-muted/20 rounded px-2 py-1.5">
        <span className="text-muted-foreground">Weight {s.current_weight.toFixed(2)}×</span>
        <span className="text-muted-foreground/40">→</span>
        <span className={dm.color}>{s.recommended_weight.toFixed(2)}×</span>
      </div>

      <p className="text-xs text-foreground/70 leading-relaxed">{s.reason}</p>

      {s.reliability_warning && (
        <div className="flex gap-1.5 text-xs text-yellow-400/90 bg-yellow-400/5 border border-yellow-500/20 rounded px-2 py-1.5">
          <AlertCircle className="h-3.5 w-3.5 shrink-0 mt-0.5" />
          <span>{s.reliability_warning}</span>
        </div>
      )}
    </div>
  );
}

function LearningSection() {
  const { data: learning, isLoading } = useGetLearningSummary();

  if (isLoading) {
    return (
      <div className="rounded-lg border border-border bg-card p-6 text-center text-muted-foreground text-sm font-mono">
        Computing strategy learning…
      </div>
    );
  }

  if (!learning) {
    return null;
  }

  return (
    <div className="space-y-4">
      <div className="flex gap-2 text-sm text-foreground/70 bg-primary/5 border border-primary/20 rounded-lg p-3">
        <GraduationCap className="h-4 w-4 text-primary mt-0.5 shrink-0" />
        <p className="leading-relaxed">
          The Learning Engine only <strong>recommends</strong> allocation weight changes based on paper trading
          history — it never places or resizes real orders automatically.
        </p>
      </div>

      {learning.overall_warning && (
        <div className="flex gap-2 text-sm text-yellow-400/90 bg-yellow-400/5 border border-yellow-500/20 rounded-lg p-3">
          <AlertCircle className="h-4 w-4 mt-0.5 shrink-0" />
          <p className="leading-relaxed">{learning.overall_warning}</p>
        </div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
        {learning.strategies.map((s) => (
          <StrategyLearningCard key={s.strategy_id} s={s} />
        ))}
      </div>
    </div>
  );
}

// ── Expanded Trade Detail ──────────────────────────────────────────────────────

function TradeDetail({ t }: { t: TradeReplayItem }) {
  return (
    <div className="bg-zinc-900/60 border border-zinc-800 rounded-lg p-4 space-y-4">
      {/* Price levels */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <div className="bg-zinc-800/50 rounded-lg p-3 text-center">
          <div className="text-xs text-muted-foreground font-mono mb-1">ENTRY PRICE</div>
          <div className="font-mono font-bold text-sm">{formatCurrency(t.entry_price)}</div>
          <div className="text-xs text-muted-foreground/50 mt-0.5">{formatDate(t.entry_time)}</div>
        </div>
        <div className="bg-zinc-800/50 rounded-lg p-3 text-center">
          <div className="text-xs text-muted-foreground font-mono mb-1">EXIT PRICE</div>
          <div className="font-mono font-bold text-sm">{formatCurrency(t.exit_price)}</div>
          <div className="text-xs text-muted-foreground/50 mt-0.5">{formatDate(t.exit_time)}</div>
        </div>
        <div className="bg-red-500/10 border border-red-500/20 rounded-lg p-3 text-center">
          <div className="text-xs text-red-400 font-mono mb-1">STOP LOSS</div>
          <div className="font-mono font-bold text-sm text-red-400">{formatCurrency(t.stop_loss)}</div>
        </div>
        <div className="bg-emerald-500/10 border border-emerald-500/20 rounded-lg p-3 text-center">
          <div className="text-xs text-emerald-400 font-mono mb-1">TARGET</div>
          <div className="font-mono font-bold text-sm text-emerald-400">{formatCurrency(t.target)}</div>
        </div>
      </div>

      {/* Signal context */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-sm">
        <div className="space-y-0.5">
          <div className="text-xs text-muted-foreground font-mono">AI DECISION</div>
          <div className="font-mono text-foreground">{t.ai_decision}</div>
        </div>
        <div className="space-y-0.5">
          <div className="text-xs text-muted-foreground font-mono">REGIME</div>
          <div className="font-mono text-foreground">{t.regime}</div>
        </div>
        <div className="space-y-0.5">
          <div className="text-xs text-muted-foreground font-mono">CONFIDENCE</div>
          <div className="font-mono text-foreground">{t.signal_confidence.toFixed(0)}/100</div>
        </div>
        <div className="space-y-0.5">
          <div className="text-xs text-muted-foreground font-mono">RR RATIO</div>
          <div className="font-mono text-foreground">{t.rr_ratio.toFixed(1)}:1</div>
        </div>
      </div>

      {/* Strategy + outcome classification */}
      <div className="flex flex-wrap items-center gap-3 text-sm">
        <div className="flex items-center gap-1.5">
          <span className="text-xs text-muted-foreground font-mono">STRATEGY</span>
          <span className="font-mono text-foreground">{t.strategy_name}</span>
        </div>
        <OutcomeBadge label={t.outcome_classification} />
      </div>

      {/* Entry reason / AI explanation */}
      {t.plain_english && (
        <div className="flex gap-2 text-sm text-foreground/70 bg-primary/5 border border-primary/20 rounded-lg p-3">
          <Brain className="h-4 w-4 text-primary mt-0.5 shrink-0" />
          <p className="leading-relaxed">{t.plain_english}</p>
        </div>
      )}

      {/* Exit reason */}
      {t.reason_exit && (
        <div className="space-y-1">
          <div className="text-xs font-mono text-muted-foreground uppercase">Exit reason</div>
          <p className="text-sm text-foreground/70">{t.reason_exit}</p>
        </div>
      )}
    </div>
  );
}

// ── Main Page ──────────────────────────────────────────────────────────────────

type TabType = "replay" | "performance" | "learning";

export default function TradeReplayPage() {
  const { data: trades = [], isLoading } = useGetTradeReplay();
  const [expandedRow, setExpandedRow] = useState<string | null>(null);
  const [tab, setTab] = useState<TabType>("replay");

  const winners = trades.filter((t) => t.pnl > 0).length;
  const losers  = trades.filter((t) => t.pnl < 0).length;

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold tracking-tight flex items-center gap-2">
          <RotateCcw className="h-6 w-6 text-primary" />
          Trade Replay
        </h1>
        <p className="text-sm text-muted-foreground mt-1">
          Completed round trips · P&L · Exit type · Original signal explanation
        </p>
      </div>

      {/* Tabs */}
      <div className="flex gap-1 border-b border-border">
        {(["replay", "performance", "learning"] as TabType[]).map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`px-4 py-2 text-sm font-mono capitalize transition-colors border-b-2 -mb-px ${
              tab === t
                ? "border-primary text-primary"
                : "border-transparent text-muted-foreground hover:text-foreground"
            }`}
            data-testid={`tab-${t}`}
          >
            {t === "replay" ? "Trade Replay" : t === "performance" ? "Strategy Performance" : "Learning Summary"}
          </button>
        ))}
      </div>

      {tab === "learning" ? (
        <LearningSection />
      ) : tab === "performance" ? (
        <PerformanceSection />
      ) : (
        <div className="space-y-4">
          {/* Summary bar */}
          {trades.length > 0 && (
            <div className="flex gap-3 text-xs font-mono flex-wrap">
              <span className="px-2.5 py-1 rounded-full bg-zinc-800 text-foreground/70">
                {trades.length} total
              </span>
              <span className="px-2.5 py-1 rounded-full bg-emerald-500/10 text-emerald-400">
                {winners} winning
              </span>
              <span className="px-2.5 py-1 rounded-full bg-red-500/10 text-red-400">
                {losers} losing
              </span>
            </div>
          )}

          {/* Trade table */}
          <div className="rounded-lg border border-border bg-card overflow-hidden">
            {/* Table header */}
            <div className="hidden md:grid grid-cols-[1fr_1fr_1fr_1fr_1fr_1.2fr_32px] gap-3 px-4 py-2.5 border-b border-border bg-muted/30">
              {["STOCK", "ENTRY → EXIT", "QTY", "P&L", "EXIT TYPE", "REGIME / AI DEC", ""].map(
                (h) => (
                  <div key={h} className="text-xs font-mono text-muted-foreground uppercase tracking-wider">
                    {h}
                  </div>
                )
              )}
            </div>

            {isLoading ? (
              <div className="py-16 text-center text-muted-foreground text-sm font-mono">
                Loading trade replay…
              </div>
            ) : trades.length === 0 ? (
              <div className="py-16 text-center space-y-2">
                <RotateCcw className="h-10 w-10 text-muted-foreground/30 mx-auto" />
                <p className="text-muted-foreground text-sm font-mono">No completed trades</p>
                <p className="text-xs text-muted-foreground/60">
                  Once a position is opened and closed, it appears here
                </p>
              </div>
            ) : (
              <div>
                {trades.map((t) => {
                  const key = `${t.symbol}-${t.exit_time}`;
                  const isExpanded = expandedRow === key;
                  const isProfitable = t.pnl >= 0;
                  return (
                    <div key={key} className="border-b border-border/50 last:border-0">
                      <button
                        className={`w-full text-left hover:bg-muted/20 transition-colors ${
                          isProfitable ? "border-l-2 border-l-emerald-500/50" : "border-l-2 border-l-red-500/50"
                        }`}
                        onClick={() => setExpandedRow(isExpanded ? null : key)}
                        data-testid={`row-trade-${t.symbol}`}
                      >
                        <div className="grid grid-cols-2 md:grid-cols-[1fr_1fr_1fr_1fr_1fr_1.2fr_32px] gap-3 px-4 py-3 items-center">
                          {/* Stock */}
                          <div className="flex items-center gap-2">
                            {isProfitable ? (
                              <TrendingUp className="h-3.5 w-3.5 text-emerald-500 shrink-0" />
                            ) : (
                              <TrendingDown className="h-3.5 w-3.5 text-red-500 shrink-0" />
                            )}
                            <span className="font-mono font-bold text-sm">{t.symbol}</span>
                          </div>

                          {/* Entry → Exit */}
                          <div className="flex flex-col gap-0.5">
                            <span className="font-mono text-xs text-foreground/70">
                              {formatCurrency(t.entry_price)}
                              <span className="text-muted-foreground/40 mx-1">→</span>
                              {formatCurrency(t.exit_price)}
                            </span>
                            <span className="text-xs text-muted-foreground/50 font-mono">
                              {formatDate(t.exit_time)}
                            </span>
                          </div>

                          {/* Qty */}
                          <div className="font-mono text-sm text-foreground/80 hidden md:block">
                            ×{t.quantity}
                          </div>

                          {/* P&L */}
                          <div className="hidden md:block">
                            <PnlDisplay pnl={t.pnl} pnl_pct={t.pnl_pct} />
                          </div>

                          {/* Exit type */}
                          <div className="hidden md:block">
                            <ExitBadge type={t.exit_type} />
                          </div>

                          {/* Regime + AI dec */}
                          <div className="hidden md:flex flex-col gap-0.5">
                            <span className="text-xs font-mono text-muted-foreground/70">{t.regime}</span>
                            <span className="text-xs font-mono text-foreground/50">{t.ai_decision}</span>
                          </div>

                          {/* Expand */}
                          <div className="hidden md:flex justify-end text-muted-foreground">
                            {isExpanded ? (
                              <ChevronDown className="h-4 w-4" />
                            ) : (
                              <ChevronRight className="h-4 w-4" />
                            )}
                          </div>
                        </div>
                      </button>

                      {isExpanded && (
                        <div className="px-4 pb-4">
                          <TradeDetail t={t} />
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
