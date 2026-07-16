import React, { useCallback, useEffect, useState } from "react";
import { apiJson } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from "@/components/ui/dialog";
import {
  RefreshCcw,
  ChevronDown,
  ChevronRight,
  CheckCircle2,
  XCircle,
  AlertTriangle,
  History,
  FlaskConical,
} from "lucide-react";

// ── Shared types ────────────────────────────────────────────────────────────

interface Gate {
  gate: string;
  passed: boolean;
  reason: string;
}

interface Sizing {
  quantity: number;
  entry_price: number;
  stop_loss: number;
  target_price: number;
  position_value: number;
  risk_amount: number;
  rr_ratio: number;
}

interface Candidate {
  symbol: string;
  sector: string;
  recommendation: string;
  eligible: boolean;
  failed_gates: string[];
  gates: Gate[];
  sizing: Sizing;
  confidence: number;
  opportunity_score: number;
  trade_quality_score: number;
  strategy_name: string;
  regime: string;
}

interface EvaluationResponse {
  success: boolean;
  evaluated_at: string;
  scan_id: string;
  snapshot_ts: string;
  market_state: string;
  global_gates: Gate[];
  global_pass: boolean;
  candidates: Candidate[];
  eligible_count: number;
  blocked_count: number;
}

interface LedgerRow {
  trade_id: string;
  scan_id: string;
  snapshot_ts: string;
  symbol: string;
  sector: string;
  strategy_name: string;
  side: string;
  signal_ts: string;
  decision_ts: string;
  simulated_order_ts: string;
  fill_ts: string;
  signal_price: number;
  fill_price: number;
  quantity: number;
  stop_loss: number;
  target: number;
  risk_amount: number;
  est_charges: number;
  slippage: number;
  fill_model: string;
  confidence: number;
  opportunity_score: number;
  trade_quality_score: number;
  regime: string;
  model_version: string;
  rule_version: string;
  config_hash: string;
  trigger_source: string;
  status: "OPEN" | "CLOSED" | "EXIT_PENDING";
  exit_ts: string | null;
  exit_price: number | null;
  exit_rule: string | null;
  exit_scan_id: string | null;
  realized_pnl: number | null;
  evidence: any;
}

interface LedgerResponse {
  success: boolean;
  ledger: LedgerRow[];
}

interface PositionRow extends LedgerRow {
  current_price: number;
  unrealized_pnl: number;
}

interface PositionsResponse {
  success: boolean;
  positions: PositionRow[];
}

interface ReplayResponse {
  found: boolean;
  label: string;
  original: Record<string, any>;
  recomputed: {
    gates_failed: string[];
    decision: string;
    fill_price: number;
    quantity: number;
  };
  deterministic_match: boolean;
  config_changed_since: boolean;
  note: string;
}

// ── Helpers ─────────────────────────────────────────────────────────────────

const PAPER_LABEL = "PAPER / RESEARCH ONLY";

function fmt(n: number | null | undefined, digits = 2): string {
  if (n === undefined || n === null || Number.isNaN(n)) return "—";
  return Number(n).toFixed(digits);
}

function rupee(n: number | null | undefined): string {
  if (n === undefined || n === null || Number.isNaN(n)) return "—";
  return `₹${Number(n).toFixed(2)}`;
}

function fmtTime(ts: string | null | undefined): string {
  if (!ts) return "—";
  const d = new Date(ts);
  if (Number.isNaN(d.getTime())) return String(ts);
  return d.toLocaleString();
}

function PaperTag() {
  return (
    <span className="inline-block rounded border border-amber-500/40 bg-amber-500/10 px-1.5 py-0.5 text-[9px] font-mono font-bold text-amber-400 tracking-wider">
      {PAPER_LABEL}
    </span>
  );
}

function GateChip({ gate }: { gate: Gate }) {
  return (
    <TooltipProvider>
      <Tooltip>
        <TooltipTrigger asChild>
          <span
            className={`inline-flex items-center gap-1 rounded border px-2 py-0.5 text-[10px] font-mono font-bold ${
              gate.passed
                ? "text-green-400 border-green-500/30 bg-green-500/10"
                : "text-red-400 border-red-500/30 bg-red-500/10"
            }`}
            data-testid={`chip-gate-${gate.gate}`}
          >
            {gate.passed ? (
              <CheckCircle2 className="h-3 w-3" />
            ) : (
              <XCircle className="h-3 w-3" />
            )}
            {gate.gate.replace(/_/g, " ")}
          </span>
        </TooltipTrigger>
        <TooltipContent className="max-w-xs text-xs">{gate.reason || "—"}</TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}

// ── Entry evaluation panel ──────────────────────────────────────────────────

function CandidateRow({ c }: { c: Candidate }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <tr
        className="border-b border-border/40 hover:bg-accent/30 cursor-pointer"
        onClick={() => setOpen((o) => !o)}
        data-testid={`row-eval-${c.symbol}`}
      >
        <td className="px-3 py-2 font-mono font-bold">
          <span className="flex items-center gap-1">
            {open ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
            {c.symbol}
          </span>
        </td>
        <td className="px-3 py-2 font-mono text-xs">{c.recommendation?.replace(/_/g, " ")}</td>
        <td className="px-3 py-2 font-mono text-right">{fmt(c.confidence, 0)}</td>
        <td className="px-3 py-2 font-mono text-right">{fmt(c.opportunity_score, 0)}</td>
        <td className="px-3 py-2 font-mono text-right">1:{fmt(c.sizing?.rr_ratio, 1)}</td>
        <td className="px-3 py-2 font-mono text-right">{c.sizing?.quantity ?? "—"}</td>
        <td className="px-3 py-2 text-center">
          {c.eligible ? (
            <Badge
              variant="outline"
              className="border-green-500/40 text-green-400 bg-green-500/10 font-mono text-[10px]"
            >
              ELIGIBLE
            </Badge>
          ) : (
            <span className="text-[10px] font-mono text-red-400" title={c.failed_gates?.join(", ")}>
              Blocked
              {c.failed_gates?.length > 0 && (
                <span className="block text-[9px] text-red-400/70">
                  {c.failed_gates.slice(0, 3).map((g) => g.replace(/_/g, " ")).join(", ")}
                  {c.failed_gates.length > 3 ? "…" : ""}
                </span>
              )}
            </span>
          )}
        </td>
      </tr>
      {open && (
        <tr className="border-b border-border/40 bg-accent/10">
          <td colSpan={7} className="px-4 py-3">
            <div className="text-[10px] font-mono uppercase text-muted-foreground mb-2">
              Gate detail · {c.strategy_name || "—"} · {c.sector || "—"} · {c.regime || "—"}
            </div>
            <div className="flex flex-wrap gap-1.5 mb-3">
              {c.gates?.map((g) => (
                <GateChip key={g.gate} gate={g} />
              ))}
            </div>
            <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-7 gap-2 text-[11px] font-mono">
              <div><span className="text-muted-foreground block">Entry</span>{rupee(c.sizing?.entry_price)}</div>
              <div><span className="text-muted-foreground block">Stop</span>{rupee(c.sizing?.stop_loss)}</div>
              <div><span className="text-muted-foreground block">Target</span>{rupee(c.sizing?.target_price)}</div>
              <div><span className="text-muted-foreground block">Qty</span>{c.sizing?.quantity ?? "—"}</div>
              <div><span className="text-muted-foreground block">Position</span>{rupee(c.sizing?.position_value)}</div>
              <div><span className="text-muted-foreground block">Risk</span>{rupee(c.sizing?.risk_amount)}</div>
              <div><span className="text-muted-foreground block">Quality</span>{fmt(c.trade_quality_score, 0)}</div>
            </div>
          </td>
        </tr>
      )}
    </>
  );
}

export function EntryEvaluationPanel() {
  const [data, setData] = useState<EvaluationResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await apiJson<EvaluationResponse>("/phase20/evaluation");
      setData(res);
    } catch (e: any) {
      setError(e?.message ?? "Failed to load evaluation");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  return (
    <Card className="bg-card/50 backdrop-blur border-border/50" data-testid="panel-entry-evaluation">
      <CardHeader className="border-b border-border/50 bg-muted/20 py-3 px-4 flex-row items-center justify-between space-y-0">
        <CardTitle className="font-mono text-xs uppercase tracking-wider text-muted-foreground flex items-center gap-2">
          <FlaskConical className="h-4 w-4 text-primary" />
          Auto Paper-Entry Gate Evaluation
          <PaperTag />
        </CardTitle>
        <Button
          size="sm"
          variant="outline"
          onClick={load}
          disabled={loading}
          className="font-mono text-xs"
          data-testid="button-refresh-evaluation"
        >
          <RefreshCcw className={`mr-1.5 h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} />
          {loading ? "Evaluating…" : "Refresh"}
        </Button>
      </CardHeader>
      <CardContent className="p-4">
        {loading && !data ? (
          <div className="space-y-2" data-testid="loading-evaluation">
            <Skeleton className="h-6 w-64" />
            <Skeleton className="h-4 w-full" />
            <Skeleton className="h-4 w-full" />
            <Skeleton className="h-4 w-3/4" />
            <p className="text-[11px] text-muted-foreground font-mono pt-1">
              Evaluating candidates — this can take a few seconds…
            </p>
          </div>
        ) : error ? (
          <div className="flex items-start gap-2 text-sm text-red-400">
            <AlertTriangle className="h-4 w-4 mt-0.5 flex-shrink-0" />
            <span>{error}</span>
          </div>
        ) : data ? (
          <div className="space-y-4">
            <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-[11px] font-mono text-muted-foreground">
              <span>
                Global gates:{" "}
                <span className={data.global_pass ? "text-green-400 font-bold" : "text-red-400 font-bold"}>
                  {data.global_pass ? "PASS" : "BLOCKED"}
                </span>
              </span>
              <span>Eligible: <span className="text-green-400 font-bold">{data.eligible_count}</span></span>
              <span>Blocked: <span className="text-red-400 font-bold">{data.blocked_count}</span></span>
              <span>Market: {data.market_state || "—"}</span>
              <span>Scan: {data.scan_id || "—"}</span>
              <span>Snapshot: {fmtTime(data.snapshot_ts)}</span>
            </div>

            <div className="flex flex-wrap gap-1.5">
              {data.global_gates?.map((g) => (
                <GateChip key={g.gate} gate={g} />
              ))}
            </div>

            {data.candidates?.length > 0 ? (
              <div className="rounded-md border border-border/50 overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-border/60 text-left text-xs font-mono uppercase text-muted-foreground">
                      <th className="px-3 py-2">Symbol</th>
                      <th className="px-3 py-2">Recommendation</th>
                      <th className="px-3 py-2 text-right">Conf</th>
                      <th className="px-3 py-2 text-right">Opp</th>
                      <th className="px-3 py-2 text-right">R:R</th>
                      <th className="px-3 py-2 text-right">Qty</th>
                      <th className="px-3 py-2 text-center">Status</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.candidates.map((c) => (
                      <CandidateRow key={c.symbol} c={c} />
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <p className="text-sm text-muted-foreground font-mono">No candidates evaluated.</p>
            )}
            <p className="text-[10px] text-muted-foreground font-mono">
              Evaluated at {fmtTime(data.evaluated_at)} · gates and sizing are simulated only —
              no real orders are placed.
            </p>
          </div>
        ) : (
          <p className="text-sm text-muted-foreground font-mono">No evaluation data.</p>
        )}
      </CardContent>
    </Card>
  );
}

// ── Ledger table ────────────────────────────────────────────────────────────

function StatusBadge({ row }: { row: LedgerRow }) {
  if (row.status === "OPEN") {
    return (
      <Badge variant="outline" className="border-blue-500/40 text-blue-400 bg-blue-500/10 font-mono text-[10px]">
        OPEN
      </Badge>
    );
  }
  if (row.status === "EXIT_PENDING") {
    return (
      <Badge variant="outline" className="border-amber-500/40 text-amber-400 bg-amber-500/10 font-mono text-[10px]">
        PENDING DATA
      </Badge>
    );
  }
  const win = (row.realized_pnl ?? 0) >= 0;
  return (
    <Badge
      variant="outline"
      className={`font-mono text-[10px] ${
        win
          ? "border-green-500/40 text-green-400 bg-green-500/10"
          : "border-red-500/40 text-red-400 bg-red-500/10"
      }`}
    >
      CLOSED
    </Badge>
  );
}

function ReplayDialog({
  tradeId,
  open,
  onOpenChange,
}: {
  tradeId: string;
  open: boolean;
  onOpenChange: (o: boolean) => void;
}) {
  const [data, setData] = useState<ReplayResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    setData(null);
    apiJson<ReplayResponse>(`/phase20/replay/${tradeId}`)
      .then((res) => {
        if (!cancelled) setData(res);
      })
      .catch((e: any) => {
        if (!cancelled) setError(e?.message ?? "Failed to load replay");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [open, tradeId]);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle className="font-mono flex items-center gap-2">
            <History className="h-4 w-4 text-primary" />
            Deterministic Replay · {tradeId}
            <PaperTag />
          </DialogTitle>
          <DialogDescription>
            Original decision vs a deterministic recomputation from the stored snapshot.
          </DialogDescription>
        </DialogHeader>
        {loading ? (
          <div className="space-y-2">
            <Skeleton className="h-4 w-full" />
            <Skeleton className="h-4 w-full" />
            <Skeleton className="h-4 w-2/3" />
          </div>
        ) : error ? (
          <div className="flex items-start gap-2 text-sm text-red-400">
            <AlertTriangle className="h-4 w-4 mt-0.5 flex-shrink-0" />
            <span>{error}</span>
          </div>
        ) : data && !data.found ? (
          <p className="text-sm text-muted-foreground font-mono">Trade not found for replay.</p>
        ) : data ? (
          <div className="space-y-4">
            <div className="flex flex-wrap items-center gap-2">
              <Badge
                variant="outline"
                className={`font-mono text-[10px] ${
                  data.deterministic_match
                    ? "border-green-500/40 text-green-400 bg-green-500/10"
                    : "border-red-500/40 text-red-400 bg-red-500/10"
                }`}
              >
                {data.deterministic_match ? "DETERMINISTIC MATCH" : "MISMATCH"}
              </Badge>
              {data.config_changed_since && (
                <Badge variant="outline" className="border-amber-500/40 text-amber-400 bg-amber-500/10 font-mono text-[10px]">
                  CONFIG CHANGED SINCE
                </Badge>
              )}
              <Badge variant="outline" className="border-border font-mono text-[10px]">
                {data.label}
              </Badge>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div className="rounded border border-border/50 p-3">
                <div className="text-[10px] font-mono uppercase text-muted-foreground mb-2">Original</div>
                <div className="space-y-1 text-[11px] font-mono">
                  <div className="flex justify-between"><span className="text-muted-foreground">Decision</span><span>{data.original?.decision ?? data.original?.recommendation ?? "—"}</span></div>
                  <div className="flex justify-between"><span className="text-muted-foreground">Fill price</span><span>{rupee(data.original?.fill_price)}</span></div>
                  <div className="flex justify-between"><span className="text-muted-foreground">Quantity</span><span>{data.original?.quantity ?? "—"}</span></div>
                  <div className="flex justify-between"><span className="text-muted-foreground">Gates failed</span><span>{(data.original?.gates_failed ?? data.original?.failed_gates ?? []).join(", ") || "none"}</span></div>
                </div>
              </div>
              <div className="rounded border border-primary/40 p-3">
                <div className="text-[10px] font-mono uppercase text-primary/80 mb-2">Recomputed</div>
                <div className="space-y-1 text-[11px] font-mono">
                  <div className="flex justify-between"><span className="text-muted-foreground">Decision</span><span>{data.recomputed?.decision ?? "—"}</span></div>
                  <div className="flex justify-between"><span className="text-muted-foreground">Fill price</span><span>{rupee(data.recomputed?.fill_price)}</span></div>
                  <div className="flex justify-between"><span className="text-muted-foreground">Quantity</span><span>{data.recomputed?.quantity ?? "—"}</span></div>
                  <div className="flex justify-between"><span className="text-muted-foreground">Gates failed</span><span>{(data.recomputed?.gates_failed ?? []).join(", ") || "none"}</span></div>
                </div>
              </div>
            </div>

            {data.note && (
              <p className="text-[11px] text-muted-foreground font-mono leading-relaxed">{data.note}</p>
            )}
          </div>
        ) : null}
      </DialogContent>
    </Dialog>
  );
}

export function Phase20LedgerTable({ limit = 200 }: { limit?: number }) {
  const [data, setData] = useState<LedgerResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [replayId, setReplayId] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await apiJson<LedgerResponse>(`/phase20/ledger?limit=${limit}`);
      setData(res);
    } catch (e: any) {
      setError(e?.message ?? "Failed to load ledger");
    } finally {
      setLoading(false);
    }
  }, [limit]);

  useEffect(() => {
    load();
  }, [load]);

  const rows = data?.ledger ?? [];

  return (
    <Card className="bg-card/50 backdrop-blur border-border/50" data-testid="panel-phase20-ledger">
      <CardHeader className="border-b border-border/50 bg-muted/20 py-3 px-4 flex-row items-center justify-between space-y-0">
        <CardTitle className="font-mono text-xs uppercase tracking-wider text-muted-foreground flex items-center gap-2">
          Phase 20 Auto Paper Trades
          <PaperTag />
        </CardTitle>
        <Button
          size="sm"
          variant="outline"
          onClick={load}
          disabled={loading}
          className="font-mono text-xs"
          data-testid="button-refresh-ledger"
        >
          <RefreshCcw className={`mr-1.5 h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} />
          Refresh
        </Button>
      </CardHeader>
      <CardContent className="p-0">
        {loading && !data ? (
          <div className="p-6 space-y-2">
            <Skeleton className="h-4 w-full" />
            <Skeleton className="h-4 w-full" />
            <Skeleton className="h-4 w-3/4" />
          </div>
        ) : error ? (
          <div className="p-6 flex items-start gap-2 text-sm text-red-400">
            <AlertTriangle className="h-4 w-4 mt-0.5 flex-shrink-0" />
            <span>{error}</span>
          </div>
        ) : rows.length > 0 ? (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border/60 text-left text-xs font-mono uppercase text-muted-foreground bg-muted/30">
                  <th className="px-3 py-2 whitespace-nowrap">Time</th>
                  <th className="px-3 py-2">Symbol</th>
                  <th className="px-3 py-2 text-right">Qty</th>
                  <th className="px-3 py-2 text-right">Signal / Fill</th>
                  <th className="px-3 py-2 text-right">Slippage</th>
                  <th className="px-3 py-2 text-right">Charges</th>
                  <th className="px-3 py-2 text-right">Stop / Target</th>
                  <th className="px-3 py-2 text-center">Status</th>
                  <th className="px-3 py-2">Exit rule</th>
                  <th className="px-3 py-2 text-right">Realized P&L</th>
                  <th className="px-3 py-2 text-center">Trigger</th>
                  <th className="px-3 py-2 text-center">Replay</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.trade_id} className="border-b border-border/40 hover:bg-accent/20" data-testid={`row-ledger-${r.trade_id}`}>
                    <td className="px-3 py-2 font-mono text-xs whitespace-nowrap text-muted-foreground">
                      {fmtTime(r.simulated_order_ts)}
                    </td>
                    <td className="px-3 py-2 font-mono font-bold">{r.symbol}</td>
                    <td className="px-3 py-2 font-mono text-right">{r.quantity}</td>
                    <td className="px-3 py-2 font-mono text-right text-xs">
                      {rupee(r.signal_price)} <span className="text-muted-foreground">/</span> {rupee(r.fill_price)}
                    </td>
                    <td className="px-3 py-2 font-mono text-right text-xs">{fmt(r.slippage)}</td>
                    <td className="px-3 py-2 font-mono text-right text-xs">{rupee(r.est_charges)}</td>
                    <td className="px-3 py-2 font-mono text-right text-xs text-muted-foreground">
                      {rupee(r.stop_loss)} / {rupee(r.target)}
                    </td>
                    <td className="px-3 py-2 text-center"><StatusBadge row={r} /></td>
                    <td className="px-3 py-2 font-mono text-xs text-muted-foreground">
                      {r.exit_rule ? r.exit_rule.replace(/_/g, " ") : "—"}
                    </td>
                    <td
                      className={`px-3 py-2 font-mono text-right ${
                        r.realized_pnl == null
                          ? "text-muted-foreground"
                          : r.realized_pnl >= 0
                          ? "text-green-400"
                          : "text-red-400"
                      }`}
                    >
                      {r.realized_pnl == null ? "—" : `${r.realized_pnl >= 0 ? "+" : ""}${fmt(r.realized_pnl)}`}
                    </td>
                    <td className="px-3 py-2 text-center">
                      <span className="text-[10px] font-mono text-muted-foreground">
                        {r.trigger_source === "MANUAL" ? "MANUAL" : "AUTO"}
                      </span>
                    </td>
                    <td className="px-3 py-2 text-center">
                      <Button
                        size="sm"
                        variant="ghost"
                        className="h-7 px-2 font-mono text-[10px]"
                        onClick={() => setReplayId(r.trade_id)}
                        data-testid={`button-replay-${r.trade_id}`}
                      >
                        <History className="h-3 w-3 mr-1" />
                        Replay
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="p-8 text-center text-muted-foreground">
            <p className="font-mono text-sm">NO AUTO PAPER TRADES</p>
            <p className="text-xs mt-1">No Phase 20 simulated trades have been recorded yet.</p>
          </div>
        )}
      </CardContent>
      {replayId && (
        <ReplayDialog
          tradeId={replayId}
          open={!!replayId}
          onOpenChange={(o) => !o && setReplayId(null)}
        />
      )}
    </Card>
  );
}

// ── Open positions ──────────────────────────────────────────────────────────

export function Phase20OpenPositions() {
  const [data, setData] = useState<PositionsResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [ticking, setTicking] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await apiJson<PositionsResponse>("/phase20/positions");
      setData(res);
    } catch (e: any) {
      setError(e?.message ?? "Failed to load positions");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const handleTick = async () => {
    setTicking(true);
    try {
      await apiJson("/phase20/exits/tick", { method: "POST" });
      await load();
    } catch (e: any) {
      setError(e?.message ?? "Failed to evaluate exits");
    } finally {
      setTicking(false);
    }
  };

  const positions = data?.positions ?? [];

  return (
    <Card className="bg-card/50 backdrop-blur border-border/50" data-testid="panel-phase20-positions">
      <CardHeader className="border-b border-border/50 bg-muted/20 py-3 px-4 flex-row items-center justify-between space-y-0">
        <CardTitle className="font-mono text-xs uppercase tracking-wider text-muted-foreground flex items-center gap-2">
          Phase 20 Open Paper Positions
          <PaperTag />
        </CardTitle>
        <div className="flex items-center gap-2">
          <Button
            size="sm"
            variant="outline"
            onClick={handleTick}
            disabled={ticking || loading}
            className="font-mono text-xs"
            data-testid="button-exits-tick"
          >
            <RefreshCcw className={`mr-1.5 h-3.5 w-3.5 ${ticking ? "animate-spin" : ""}`} />
            {ticking ? "Evaluating…" : "Evaluate exits now"}
          </Button>
          <Button
            size="sm"
            variant="ghost"
            onClick={load}
            disabled={loading}
            className="font-mono text-xs"
            data-testid="button-refresh-positions"
          >
            <RefreshCcw className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} />
          </Button>
        </div>
      </CardHeader>
      <CardContent className="p-0">
        {loading && !data ? (
          <div className="p-6 space-y-2">
            <Skeleton className="h-4 w-full" />
            <Skeleton className="h-4 w-full" />
            <Skeleton className="h-4 w-2/3" />
          </div>
        ) : error ? (
          <div className="p-6 flex items-start gap-2 text-sm text-red-400">
            <AlertTriangle className="h-4 w-4 mt-0.5 flex-shrink-0" />
            <span>{error}</span>
          </div>
        ) : positions.length > 0 ? (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border/60 text-left text-xs font-mono uppercase text-muted-foreground bg-muted/30">
                  <th className="px-3 py-2">Symbol</th>
                  <th className="px-3 py-2 text-right">Qty</th>
                  <th className="px-3 py-2 text-right">Fill</th>
                  <th className="px-3 py-2 text-right">Current</th>
                  <th className="px-3 py-2 text-right">Unrealized P&L</th>
                  <th className="px-3 py-2 text-right">Stop / Target</th>
                  <th className="px-3 py-2 whitespace-nowrap">Holding since</th>
                  <th className="px-3 py-2 text-center">State</th>
                </tr>
              </thead>
              <tbody>
                {positions.map((p) => (
                  <tr key={p.trade_id} className="border-b border-border/40 hover:bg-accent/20" data-testid={`row-position-${p.trade_id}`}>
                    <td className="px-3 py-2 font-mono font-bold">{p.symbol}</td>
                    <td className="px-3 py-2 font-mono text-right">{p.quantity}</td>
                    <td className="px-3 py-2 font-mono text-right">{rupee(p.fill_price)}</td>
                    <td className="px-3 py-2 font-mono text-right">{rupee(p.current_price)}</td>
                    <td
                      className={`px-3 py-2 font-mono text-right ${
                        (p.unrealized_pnl ?? 0) >= 0 ? "text-green-400" : "text-red-400"
                      }`}
                    >
                      {(p.unrealized_pnl ?? 0) >= 0 ? "+" : ""}
                      {fmt(p.unrealized_pnl)}
                    </td>
                    <td className="px-3 py-2 font-mono text-right text-xs text-muted-foreground">
                      {rupee(p.stop_loss)} / {rupee(p.target)}
                    </td>
                    <td className="px-3 py-2 font-mono text-xs text-muted-foreground whitespace-nowrap">
                      {fmtTime(p.fill_ts || p.simulated_order_ts)}
                    </td>
                    <td className="px-3 py-2 text-center">
                      {p.status === "EXIT_PENDING" ? (
                        <Badge variant="outline" className="border-amber-500/40 text-amber-400 bg-amber-500/10 font-mono text-[10px]">
                          EXIT PENDING
                        </Badge>
                      ) : (
                        <Badge variant="outline" className="border-blue-500/40 text-blue-400 bg-blue-500/10 font-mono text-[10px]">
                          OPEN
                        </Badge>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="p-8 text-center text-muted-foreground">
            <p className="font-mono text-sm">NO OPEN PAPER POSITIONS</p>
            <p className="text-xs mt-1">No Phase 20 simulated positions are currently open.</p>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
