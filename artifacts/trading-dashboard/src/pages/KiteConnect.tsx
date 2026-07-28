import { useEffect, useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiJson } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Input } from "@/components/ui/input";
import DataFreshnessBar from "@/components/DataFreshnessBar";
import {
  Radio,
  RefreshCw,
  Wifi,
  WifiOff,
  AlertTriangle,
  CheckCircle,
  Clock,
  TrendingUp,
  TrendingDown,
  DollarSign,
  FileText,
  Search,
  Info,
  Lock,
  ShieldCheck,
  ExternalLink,
  Copy,
  Terminal,
} from "lucide-react";

const API = (path: string) => `/api${path}`;

// ── helpers ──────────────────────────────────────────────────────────────────

function fmt(v: number | null | undefined, decimals = 2, prefix = "₹"): string {
  if (v == null || isNaN(Number(v))) return "—";
  return `${prefix}${Number(v).toLocaleString("en-IN", { minimumFractionDigits: decimals, maximumFractionDigits: decimals })}`;
}

function pct(v: number | null | undefined): string {
  if (v == null || isNaN(Number(v))) return "—";
  const n = Number(v);
  return `${n >= 0 ? "+" : ""}${n.toFixed(2)}%`;
}

function StateBadge({ state }: { state: string }) {
  const map: Record<string, string> = {
    CONNECTED:      "bg-green-500/15 text-green-400 border-green-500/30",
    AUTHENTICATING: "bg-blue-500/15 text-blue-400 border-blue-500/30",
    LOGIN_REQUIRED: "bg-warn-surface text-warn border-warn",
    TOKEN_EXPIRED:  "bg-red-500/15 text-red-400 border-red-500/30",
    AUTH_FAILED:    "bg-red-500/15 text-red-400 border-red-500/30",
    API_ERROR:      "bg-orange-500/15 text-orange-400 border-orange-500/30",
    NOT_CONFIGURED: "bg-muted/50 text-muted-foreground border-border",
  };
  return (
    <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-mono border ${map[state] ?? map["NOT_CONFIGURED"]}`}>
      {state.replace(/_/g, " ")}
    </span>
  );
}

function TokenBadge({ status }: { status: string }) {
  const map: Record<string, { color: string; icon: React.ReactElement }> = {
    VALID:   { color: "bg-green-500/15 text-green-400 border-green-500/30", icon: <CheckCircle className="h-3 w-3" /> },
    WARNING: { color: "bg-warn-surface text-warn border-warn", icon: <AlertTriangle className="h-3 w-3" /> },
    EXPIRED: { color: "bg-red-500/15 text-red-400 border-red-500/30", icon: <AlertTriangle className="h-3 w-3" /> },
    MISSING: { color: "bg-muted/50 text-muted-foreground border-border", icon: <WifiOff className="h-3 w-3" /> },
    ERROR:   { color: "bg-red-500/15 text-red-400 border-red-500/30", icon: <AlertTriangle className="h-3 w-3" /> },
  };
  const s = map[status] ?? map["MISSING"];
  return (
    <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-mono border ${s.color}`}>
      {s.icon} {status}
    </span>
  );
}

// ── sub-components ────────────────────────────────────────────────────────────

function fmtTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  try { return new Date(iso).toLocaleString(); } catch { return "—"; }
}

function SessionCard({ status, onRefresh, onInvalidate, invalidating, onDisconnect, disconnecting, authResult }: any) {
  const connected = status?.connected;
  const tokenSt   = status?.token_status ?? "MISSING";
  const connState = status?.connection_state ?? (connected ? "CONNECTED" : "NOT_CONFIGURED");
  const [confirmDisconnect, setConfirmDisconnect] = useState(false);

  return (
    <Card className="border-border">
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between flex-wrap gap-2">
          <CardTitle className="text-base flex items-center gap-2">
            {connected ? <Wifi className="h-4 w-4 text-green-400" /> : <WifiOff className="h-4 w-4 text-muted-foreground" />}
            Connection Status
          </CardTitle>
          <div className="flex items-center gap-2">
            <StateBadge state={connState} />
            <TokenBadge status={tokenSt} />
            <Button size="sm" variant="outline" onClick={onRefresh} className="h-7 text-xs gap-1">
              <RefreshCw className="h-3 w-3" /> Refresh
            </Button>
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* Login result banner */}
        {authResult === "success" && (
          <div className="flex items-center gap-2 p-3 bg-green-500/10 border border-green-500/20 rounded-lg text-sm text-green-400">
            <CheckCircle className="h-4 w-4 flex-shrink-0" />
            Zerodha login successful. Session connected.
          </div>
        )}
        {authResult === "failed" && (
          <div className="flex items-center gap-2 p-3 bg-red-500/10 border border-red-500/20 rounded-lg text-sm text-red-300">
            <AlertTriangle className="h-4 w-4 flex-shrink-0" />
            Zerodha login failed. Please try again.
          </div>
        )}

        {/* Daily login required banner */}
        {status?.daily_login_required && connState !== "CONNECTED" && (
          <div className="flex items-center gap-2 p-3 bg-warn-surface border border-warn rounded-lg text-sm text-warn">
            <AlertTriangle className="h-4 w-4 flex-shrink-0" />
            {status?.token_expired
              ? `Daily Zerodha login required — the previous session expired${status?.token_expires_at ? ` at ${fmtTime(status.token_expires_at)}` : ""} (tokens expire at 06:00 IST every day).`
              : "Daily Zerodha login required — no active session. Use \"Login with Zerodha\" below."}
          </div>
        )}

        {/* Login / Disconnect actions */}
        <div className="flex items-center gap-2 flex-wrap">
          <Button asChild size="sm" className="h-8 gap-1.5">
            <a href="/api/kite/login">
              <ExternalLink className="h-3.5 w-3.5" /> Login with Zerodha
            </a>
          </Button>
          {status?.token_stored && !confirmDisconnect && (
            <Button size="sm" variant="outline" className="h-8 text-xs" onClick={() => setConfirmDisconnect(true)}>
              Disconnect Session
            </Button>
          )}
          {confirmDisconnect && (
            <div className="flex items-center gap-2 text-xs">
              <span className="text-muted-foreground">Remove the stored session token?</span>
              <Button size="sm" variant="destructive" className="h-7 text-xs" disabled={disconnecting}
                onClick={() => { onDisconnect(); setConfirmDisconnect(false); }}>
                Yes, disconnect
              </Button>
              <Button size="sm" variant="ghost" className="h-7 text-xs" onClick={() => setConfirmDisconnect(false)}>
                Cancel
              </Button>
            </div>
          )}
        </div>

        {/* Connection summary */}
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          {[
            { label: "Provider", value: "Zerodha Kite" },
            { label: "User (masked)", value: status?.user_id_masked || "—" },
            { label: "Latency", value: status?.latency_ms != null ? `${status.latency_ms}ms` : (status?.last_latency_ms != null ? `${status.last_latency_ms}ms` : "—") },
            { label: "Token Age", value: status?.token_age_hours != null ? `${status.token_age_hours.toFixed(1)}h` : "—" },
            { label: "Connected At", value: fmtTime(status?.token_created_at) },
            { label: "Last Successful Call", value: fmtTime(status?.last_success_at) },
          ].map(({ label, value }) => (
            <div key={label} className="bg-muted/30 rounded-lg p-3">
              <div className="text-xs text-muted-foreground mb-1">{label}</div>
              <div className="text-sm font-mono font-semibold truncate">{value}</div>
            </div>
          ))}
        </div>

        {/* Error */}
        {status?.error && (
          <div className="flex items-start gap-2 p-3 bg-red-500/10 border border-red-500/20 rounded-lg text-sm">
            <AlertTriangle className="h-4 w-4 text-red-400 flex-shrink-0 mt-0.5" />
            <span className="text-red-300 break-all">{status.error}</span>
          </div>
        )}

        {/* Credentials display */}
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 text-xs font-mono">
          <div className="flex items-center gap-2 p-2 bg-muted/20 rounded">
            <Lock className="h-3 w-3 text-muted-foreground" />
            <span className="text-muted-foreground">API Key:</span>
            <span className="text-foreground">{status?.api_key_masked ?? "(not set)"}</span>
          </div>
          <div className="flex items-center gap-2 p-2 bg-muted/20 rounded">
            <Lock className="h-3 w-3 text-muted-foreground" />
            <span className="text-muted-foreground">Token:</span>
            <span className="text-foreground">{status?.access_token_masked ?? "(not set)"}</span>
          </div>
        </div>

        {/* Expiry note */}
        <div className="flex items-start gap-2 p-3 bg-muted/20 rounded-lg text-xs text-muted-foreground">
          <Clock className="h-3.5 w-3.5 flex-shrink-0 mt-0.5" />
          <span>{status?.token_expiry_note}</span>
        </div>

        {/* Daily refresh note */}
        <div className="p-3 bg-muted/20 rounded text-xs text-muted-foreground leading-relaxed">
          Kite sessions expire at 06:00 IST daily. Use the "Login with Zerodha" button above to
          reconnect — the token exchange happens securely on the backend.
        </div>

        {/* Zerodha Developer Console setup — callback URL */}
        {status?.expected_callback_url && (
          <div className="rounded-lg border border-blue-500/30 bg-blue-500/5 p-3 space-y-2">
            <div className="flex items-center gap-2 text-xs font-semibold text-blue-400">
              <Terminal className="h-3.5 w-3.5 flex-shrink-0" />
              Zerodha Developer Console — Required Redirect URL
            </div>
            <p className="text-xs text-muted-foreground leading-relaxed">
              In your Zerodha Kite Connect app, set <strong>Redirect URL</strong> to exactly:
            </p>
            <div className="flex items-center gap-2">
              <code className="flex-1 text-xs font-mono bg-muted/40 rounded px-2 py-1.5 text-blue-300 break-all select-all">
                {status.expected_callback_url}
              </code>
              <Button
                size="sm"
                variant="ghost"
                className="h-7 w-7 p-0 flex-shrink-0"
                onClick={() => navigator.clipboard.writeText(status.expected_callback_url)}
                title="Copy to clipboard"
              >
                <Copy className="h-3.5 w-3.5" />
              </Button>
            </div>
            <p className="text-xs text-muted-foreground">
              Go to{" "}
              <a
                href="https://developers.kite.trade/apps"
                target="_blank"
                rel="noopener noreferrer"
                className="text-blue-400 underline underline-offset-2"
              >
                developers.kite.trade/apps
              </a>{" "}
              → Edit app → Redirect URL field.
            </p>
          </div>
        )}

        {/* Safety notice */}
        <div className="flex items-center gap-2 p-2 bg-green-500/10 border border-green-500/20 rounded text-xs text-green-400">
          <ShieldCheck className="h-3.5 w-3.5 flex-shrink-0" />
          Paper trading active · Live order placement disabled · Read-only data only
        </div>

        {/* Invalidate cache */}
        <div className="flex justify-end">
          <Button
            size="sm"
            variant="ghost"
            onClick={onInvalidate}
            disabled={invalidating}
            className="h-7 text-xs text-muted-foreground"
          >
            <RefreshCw className={`h-3 w-3 mr-1 ${invalidating ? "animate-spin" : ""}`} />
            Clear probe cache
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}

function QuotesPanel() {
  const [symbols, setSymbols] = useState("RELIANCE,TCS,INFY,HDFC,ICICIBANK");
  const [query, setQuery] = useState(symbols);

  const { data, isFetching, refetch } = useQuery({
    queryKey: ["kite-quotes", symbols],
    queryFn: () => fetch(API(`/kite/quote?symbols=${encodeURIComponent(symbols)}`)).then(r => r.json()),
    enabled: !!symbols,
    staleTime: 30_000,
  });

  const quotes = data?.quotes ?? {};

  return (
    <Card className="border-border">
      <CardHeader className="pb-3">
        <CardTitle className="text-base flex items-center gap-2">
          <TrendingUp className="h-4 w-4 text-primary" />
          Live Quotes
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="flex gap-2">
          <Input
            className="h-8 text-xs font-mono"
            placeholder="RELIANCE,TCS,INFY..."
            value={query}
            onChange={e => setQuery(e.target.value)}
            onKeyDown={e => e.key === "Enter" && setSymbols(query)}
          />
          <Button size="sm" className="h-8 gap-1" onClick={() => { setSymbols(query); setTimeout(() => refetch(), 0); }}>
            <Search className="h-3 w-3" /> Fetch
          </Button>
        </div>

        {data?.provider && (
          <p className="text-xs text-muted-foreground">Provider: {data.provider}</p>
        )}

        {isFetching && <p className="text-xs text-muted-foreground">Loading…</p>}

        {Object.keys(quotes).length === 0 && !isFetching && (
          <p className="text-xs text-muted-foreground">
            {data?.error ?? "No quotes returned. Kite credentials required for live data."}
          </p>
        )}

        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-border text-muted-foreground">
                <th className="text-left py-2 px-2">Symbol</th>
                <th className="text-right py-2 px-2">LTP</th>
                <th className="text-right py-2 px-2">Open</th>
                <th className="text-right py-2 px-2">High</th>
                <th className="text-right py-2 px-2">Low</th>
                <th className="text-right py-2 px-2">Change</th>
                <th className="text-right py-2 px-2 hidden sm:table-cell">Source</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(quotes).map(([sym, q]: any) => (
                <tr key={sym} className="border-b border-border/50 hover:bg-muted/20">
                  <td className="py-2 px-2 font-mono font-semibold">{sym}</td>
                  <td className="py-2 px-2 text-right font-mono">{fmt(q.ltp)}</td>
                  <td className="py-2 px-2 text-right font-mono text-muted-foreground">{fmt(q.open)}</td>
                  <td className="py-2 px-2 text-right font-mono text-green-400">{fmt(q.high)}</td>
                  <td className="py-2 px-2 text-right font-mono text-red-400">{fmt(q.low)}</td>
                  <td className={`py-2 px-2 text-right font-mono ${(q.net_change ?? 0) >= 0 ? "text-green-400" : "text-red-400"}`}>
                    {q.net_change != null ? `${q.net_change >= 0 ? "+" : ""}${q.net_change.toFixed(2)}` : "—"}
                  </td>
                  <td className="py-2 px-2 text-right hidden sm:table-cell">
                    <Badge variant="outline" className="text-[10px] py-0">
                      {q.data_source === "kite_live" ? "Kite Live" : "Yahoo"}
                    </Badge>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </CardContent>
    </Card>
  );
}

function HoldingsPanel() {
  const { data, isFetching, refetch } = useQuery({
    queryKey: ["kite-holdings"],
    queryFn: () => fetch(API("/kite/holdings")).then(r => r.json()),
    staleTime: 60_000,
  });

  const holdings = data?.holdings ?? [];

  return (
    <Card className="border-border">
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between flex-wrap gap-2">
          <CardTitle className="text-base flex items-center gap-2">
            <FileText className="h-4 w-4 text-primary" />
            Holdings <span className="text-muted-foreground font-normal text-sm">(read-only)</span>
          </CardTitle>
          <div className="flex items-center gap-2">
            {data?.is_mock && <Badge variant="secondary" className="text-xs">Mock</Badge>}
            <Button size="sm" variant="outline" onClick={() => refetch()} className="h-7 text-xs gap-1">
              <RefreshCw className="h-3 w-3" />
            </Button>
          </div>
        </div>
      </CardHeader>
      <CardContent>
        {isFetching && <p className="text-xs text-muted-foreground">Loading…</p>}
        {holdings.length === 0 && !isFetching && (
          <p className="text-xs text-muted-foreground">{data?.error ?? "No holdings found."}</p>
        )}
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-border text-muted-foreground">
                <th className="text-left py-2 px-2">Symbol</th>
                <th className="text-right py-2 px-2">Qty</th>
                <th className="text-right py-2 px-2">Avg</th>
                <th className="text-right py-2 px-2">LTP</th>
                <th className="text-right py-2 px-2">P&L</th>
                <th className="text-right py-2 px-2 hidden sm:table-cell">P&L %</th>
              </tr>
            </thead>
            <tbody>
              {holdings.map((h: any) => (
                <tr key={h.symbol} className="border-b border-border/50 hover:bg-muted/20">
                  <td className="py-2 px-2 font-mono font-semibold">{h.symbol}</td>
                  <td className="py-2 px-2 text-right font-mono">{h.quantity}</td>
                  <td className="py-2 px-2 text-right font-mono text-muted-foreground">{fmt(h.avg_price)}</td>
                  <td className="py-2 px-2 text-right font-mono">{fmt(h.ltp)}</td>
                  <td className={`py-2 px-2 text-right font-mono ${h.pnl >= 0 ? "text-green-400" : "text-red-400"}`}>
                    {fmt(h.pnl)}
                  </td>
                  <td className={`py-2 px-2 text-right hidden sm:table-cell ${h.pnl_pct >= 0 ? "text-green-400" : "text-red-400"}`}>
                    {pct(h.pnl_pct)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="text-xs text-muted-foreground mt-3 flex items-center gap-1">
          <Lock className="h-3 w-3" /> {data?.note}
        </p>
      </CardContent>
    </Card>
  );
}

function PositionsPanel() {
  const { data, isFetching, refetch } = useQuery({
    queryKey: ["kite-positions"],
    queryFn: () => fetch(API("/kite/positions")).then(r => r.json()),
    staleTime: 30_000,
  });

  const positions = data?.positions ?? [];

  return (
    <Card className="border-border">
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between flex-wrap gap-2">
          <CardTitle className="text-base flex items-center gap-2">
            <TrendingUp className="h-4 w-4 text-primary" />
            Positions <span className="text-muted-foreground font-normal text-sm">(read-only)</span>
          </CardTitle>
          <div className="flex items-center gap-2">
            {data?.is_mock && <Badge variant="secondary" className="text-xs">Mock</Badge>}
            <Button size="sm" variant="outline" onClick={() => refetch()} className="h-7 text-xs gap-1">
              <RefreshCw className="h-3 w-3" />
            </Button>
          </div>
        </div>
      </CardHeader>
      <CardContent>
        {isFetching && <p className="text-xs text-muted-foreground">Loading…</p>}
        {positions.length === 0 && !isFetching && (
          <p className="text-xs text-muted-foreground">{data?.error ?? "No open positions."}</p>
        )}
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-border text-muted-foreground">
                <th className="text-left py-2 px-2">Symbol</th>
                <th className="text-right py-2 px-2">Qty</th>
                <th className="text-right py-2 px-2">Avg</th>
                <th className="text-right py-2 px-2">LTP</th>
                <th className="text-right py-2 px-2">P&L</th>
                <th className="text-right py-2 px-2 hidden sm:table-cell">Product</th>
              </tr>
            </thead>
            <tbody>
              {positions.map((p: any, i: number) => (
                <tr key={i} className="border-b border-border/50 hover:bg-muted/20">
                  <td className="py-2 px-2 font-mono font-semibold">{p.symbol}</td>
                  <td className="py-2 px-2 text-right font-mono">{p.quantity}</td>
                  <td className="py-2 px-2 text-right font-mono text-muted-foreground">{fmt(p.avg_price)}</td>
                  <td className="py-2 px-2 text-right font-mono">{fmt(p.ltp)}</td>
                  <td className={`py-2 px-2 text-right font-mono ${p.pnl >= 0 ? "text-green-400" : "text-red-400"}`}>
                    {fmt(p.pnl)}
                  </td>
                  <td className="py-2 px-2 text-right hidden sm:table-cell">
                    <Badge variant="outline" className="text-[10px] py-0">{p.product}</Badge>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="text-xs text-muted-foreground mt-3 flex items-center gap-1">
          <Lock className="h-3 w-3" /> {data?.note}
        </p>
      </CardContent>
    </Card>
  );
}

function MarginsPanel() {
  const { data, isFetching, refetch } = useQuery({
    queryKey: ["kite-margins"],
    queryFn: () => fetch(API("/kite/margins")).then(r => r.json()),
    staleTime: 60_000,
  });

  const m = data?.margins;

  return (
    <Card className="border-border">
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between flex-wrap gap-2">
          <CardTitle className="text-base flex items-center gap-2">
            <DollarSign className="h-4 w-4 text-primary" />
            Margins <span className="text-muted-foreground font-normal text-sm">(read-only)</span>
          </CardTitle>
          <div className="flex items-center gap-2">
            {data?.is_mock && <Badge variant="secondary" className="text-xs">Mock</Badge>}
            <Button size="sm" variant="outline" onClick={() => refetch()} className="h-7 text-xs gap-1">
              <RefreshCw className="h-3 w-3" />
            </Button>
          </div>
        </div>
      </CardHeader>
      <CardContent>
        {isFetching && <p className="text-xs text-muted-foreground">Loading…</p>}
        {!m && !isFetching && <p className="text-xs text-muted-foreground">No margin data available.</p>}
        {m && (
          <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
            {[
              { label: "Available Cash",     value: fmt(m.available_cash)  },
              { label: "Available Margin",   value: fmt(m.available_margin) },
              { label: "Used Margin",        value: fmt(m.used_margin)     },
              { label: "Net",                value: fmt(m.net)             },
              { label: "Collateral",         value: fmt(m.collateral)      },
              { label: "Intraday Payin",     value: fmt(m.intraday_payin)  },
            ].map(({ label, value }) => (
              <div key={label} className="bg-muted/30 rounded-lg p-3">
                <div className="text-xs text-muted-foreground mb-1">{label}</div>
                <div className="text-sm font-mono font-semibold">{value}</div>
              </div>
            ))}
          </div>
        )}
        <p className="text-xs text-muted-foreground mt-3 flex items-center gap-1">
          <Lock className="h-3 w-3" /> {data?.note}
        </p>
      </CardContent>
    </Card>
  );
}

function OrdersPanel() {
  const { data, isFetching, refetch } = useQuery({
    queryKey: ["kite-orders"],
    queryFn: () => fetch(API("/kite/orders?limit=50")).then(r => r.json()),
    staleTime: 30_000,
  });

  const orders = data?.orders ?? [];

  return (
    <Card className="border-border">
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between flex-wrap gap-2">
          <CardTitle className="text-base flex items-center gap-2">
            <FileText className="h-4 w-4 text-primary" />
            Order History Sync <span className="text-muted-foreground font-normal text-sm">(read-only)</span>
          </CardTitle>
          <div className="flex items-center gap-2">
            {data?.is_mock && <Badge variant="secondary" className="text-xs">Mock</Badge>}
            <Button size="sm" variant="outline" onClick={() => refetch()} className="h-7 text-xs gap-1">
              <RefreshCw className="h-3 w-3" />
            </Button>
          </div>
        </div>
      </CardHeader>
      <CardContent>
        {isFetching && <p className="text-xs text-muted-foreground">Loading…</p>}
        {orders.length === 0 && !isFetching && (
          <p className="text-xs text-muted-foreground">{data?.error ?? "No order history found."}</p>
        )}
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-border text-muted-foreground">
                <th className="text-left py-2 px-2">Symbol</th>
                <th className="text-right py-2 px-2">Side</th>
                <th className="text-right py-2 px-2">Qty</th>
                <th className="text-right py-2 px-2">Price</th>
                <th className="text-right py-2 px-2">Status</th>
                <th className="text-right py-2 px-2 hidden sm:table-cell">Type</th>
              </tr>
            </thead>
            <tbody>
              {orders.map((o: any, i: number) => (
                <tr key={i} className="border-b border-border/50 hover:bg-muted/20">
                  <td className="py-2 px-2 font-mono font-semibold">{o.symbol}</td>
                  <td className={`py-2 px-2 text-right ${o.transaction_type === "BUY" ? "text-green-400" : "text-red-400"}`}>
                    {o.transaction_type}
                  </td>
                  <td className="py-2 px-2 text-right font-mono">{o.quantity}</td>
                  <td className="py-2 px-2 text-right font-mono">{fmt(o.price)}</td>
                  <td className="py-2 px-2 text-right">
                    <Badge variant="outline" className="text-[10px] py-0">{o.status}</Badge>
                  </td>
                  <td className="py-2 px-2 text-right hidden sm:table-cell font-mono text-muted-foreground">{o.order_type}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="text-xs text-muted-foreground mt-3 flex items-center gap-1">
          <Lock className="h-3 w-3" /> {data?.note}
        </p>
      </CardContent>
    </Card>
  );
}

function InstrumentSearch() {
  const [q, setQ] = useState("");
  const [searchQ, setSearchQ] = useState("");

  const { data, isFetching } = useQuery({
    queryKey: ["kite-instruments", searchQ],
    queryFn: () => fetch(API(`/kite/instruments/search?q=${encodeURIComponent(searchQ)}&limit=20`)).then(r => r.json()),
    enabled: searchQ.length >= 1,
    staleTime: 300_000,
  });

  return (
    <Card className="border-border">
      <CardHeader className="pb-3">
        <CardTitle className="text-base flex items-center gap-2">
          <Search className="h-4 w-4 text-primary" />
          Instrument Search
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="flex gap-2">
          <Input
            className="h-8 text-xs font-mono"
            placeholder="Search by symbol or name (e.g. RELI, Tata)…"
            value={q}
            onChange={e => setQ(e.target.value)}
            onKeyDown={e => e.key === "Enter" && setSearchQ(q)}
          />
          <Button size="sm" className="h-8 gap-1" onClick={() => setSearchQ(q)}>
            <Search className="h-3 w-3" /> Search
          </Button>
        </div>
        {data?.cache_date && (
          <p className="text-xs text-muted-foreground">
            Cache: {data.cache_count?.toLocaleString()} instruments from {data.cache_date}
          </p>
        )}
        {!data?.cache_date && searchQ && !isFetching && (
          <p className="text-xs text-muted-foreground">
            Instrument cache empty — requires Kite credentials to populate (refreshes daily).
          </p>
        )}
        {isFetching && <p className="text-xs text-muted-foreground">Searching…</p>}
        {(data?.results ?? []).length > 0 && (
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-border text-muted-foreground">
                  <th className="text-left py-2 px-2">Symbol</th>
                  <th className="text-left py-2 px-2">Name</th>
                  <th className="text-right py-2 px-2 hidden sm:table-cell">Token</th>
                  <th className="text-right py-2 px-2 hidden sm:table-cell">Type</th>
                </tr>
              </thead>
              <tbody>
                {(data?.results ?? []).map((r: any, i: number) => (
                  <tr key={i} className="border-b border-border/50 hover:bg-muted/20">
                    <td className="py-2 px-2 font-mono font-semibold">{r.symbol}</td>
                    <td className="py-2 px-2 text-muted-foreground truncate max-w-[120px]">{r.name}</td>
                    <td className="py-2 px-2 text-right font-mono hidden sm:table-cell text-muted-foreground">{r.token}</td>
                    <td className="py-2 px-2 text-right hidden sm:table-cell">
                      <Badge variant="outline" className="text-[10px] py-0">{r.instrument_type}</Badge>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function DiagnosticsPanel() {
  const { data, isFetching, refetch } = useQuery({
    queryKey: ["kite-diagnostics"],
    queryFn: () => fetch(API("/kite/diagnostics")).then(r => r.json()),
    staleTime: 60_000,
  });

  return (
    <Card className="border-border">
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between flex-wrap gap-2">
          <CardTitle className="text-base flex items-center gap-2">
            <Info className="h-4 w-4 text-primary" />
            Diagnostics
          </CardTitle>
          <Button size="sm" variant="outline" onClick={() => refetch()} className="h-7 text-xs gap-1">
            <RefreshCw className={`h-3 w-3 ${isFetching ? "animate-spin" : ""}`} /> Refresh
          </Button>
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        {isFetching && <p className="text-xs text-muted-foreground">Loading diagnostics…</p>}
        {data && (
          <>
            <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
              {[
                { label: "Kite Available",         value: data.kite_available ? "Yes" : "No",        ok: data.kite_available },
                { label: "Paper Trading Active",   value: data.paper_trading_active ? "Yes" : "No",  ok: data.paper_trading_active },
                { label: "Live Orders Enabled",    value: data.live_order_placement_enabled ? "Yes" : "No", ok: !data.live_order_placement_enabled },
                { label: "Connected",             value: data.connection?.connected ? "Yes" : "No",  ok: data.connection?.connected },
                { label: "Token Status",           value: data.session?.token_status ?? "—",         ok: data.session?.token_status === "VALID" },
                { label: "Is Mock",               value: data.connection?.is_mock ? "Yes" : "No",    ok: !data.connection?.is_mock },
              ].map(({ label, value, ok }) => (
                <div key={label} className="bg-muted/30 rounded-lg p-3">
                  <div className="text-xs text-muted-foreground mb-1">{label}</div>
                  <div className={`text-sm font-mono font-semibold ${ok ? "text-green-400" : "text-warn"}`}>{value}</div>
                </div>
              ))}
            </div>
            <div className="p-3 bg-muted/20 rounded">
              <p className="text-xs font-medium mb-1">Provider</p>
              <p className="text-xs text-muted-foreground font-mono">{data.provider_label}</p>
            </div>
            <div className="p-3 bg-muted/20 rounded">
              <p className="text-xs font-medium mb-1">Instrument Cache</p>
              <p className="text-xs text-muted-foreground">
                {data.instrument_cache?.count?.toLocaleString() ?? 0} instruments ·{" "}
                {data.instrument_cache?.is_fresh ? "Fresh" : "Stale or empty"} ·{" "}
                Date: {data.instrument_cache?.date ?? "not cached"}
              </p>
            </div>
            <p className="text-xs text-muted-foreground">{data.note}</p>
          </>
        )}
      </CardContent>
    </Card>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function KiteConnect() {
  const qc = useQueryClient();
  const [authResult, setAuthResult] = useState<string | null>(null);

  useEffect(() => {
    // Read ?auth=success|failed set by the backend callback redirect,
    // then scrub it from the URL so refreshes don't re-show the banner.
    const params = new URLSearchParams(window.location.search);
    const auth = params.get("auth");
    if (auth) {
      setAuthResult(auth);
      params.delete("auth");
      params.delete("reason");
      const qs = params.toString();
      window.history.replaceState({}, "", window.location.pathname + (qs ? `?${qs}` : ""));
    }
  }, []);

  const { data: status, isLoading, refetch: refetchStatus } = useQuery({
    queryKey: ["kite-status"],
    queryFn: () => fetch(API("/kite/status")).then(r => r.json()),
    staleTime: 30_000,
    refetchInterval: 60_000,
  });

  const invalidateMutation = useMutation({
    mutationFn: () => apiJson("/kite/invalidate", { method: "POST" }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["kite-status"] });
      qc.invalidateQueries({ queryKey: ["kite-diagnostics"] });
    },
  });

  const disconnectMutation = useMutation({
    mutationFn: () => apiJson("/kite/disconnect", { method: "POST" }),
    onSuccess: () => {
      setAuthResult(null);
      qc.invalidateQueries({ queryKey: ["kite-status"] });
      qc.invalidateQueries({ queryKey: ["kite-diagnostics"] });
    },
  });

  return (
    <div className="space-y-6">
      {/* Page header */}
      <div className="flex items-start justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-2xl font-bold flex items-center gap-2">
            <Radio className="h-6 w-6 text-primary" />
            Kite Connect
          </h1>
          <p className="text-muted-foreground text-sm mt-1">
            Zerodha live-data integration · Phase 19 · Read-only
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Badge variant="outline" className="text-xs gap-1 border-green-500/30 text-green-400">
            <ShieldCheck className="h-3 w-3" /> Paper Trading Active
          </Badge>
          <Badge variant="outline" className="text-xs gap-1 border-red-500/30 text-red-400">
            <Lock className="h-3 w-3" /> Live Orders Disabled
          </Badge>
        </div>
      </div>

      <DataFreshnessBar variant="none" />

      {/* Session / connection card always at top */}
      {isLoading ? (
        <Card className="border-border">
          <CardContent className="p-6 text-sm text-muted-foreground">Loading session status…</CardContent>
        </Card>
      ) : (
        <SessionCard
          status={status}
          onRefresh={() => { refetchStatus(); }}
          onInvalidate={() => invalidateMutation.mutate()}
          invalidating={invalidateMutation.isPending}
          onDisconnect={() => disconnectMutation.mutate()}
          disconnecting={disconnectMutation.isPending}
          authResult={authResult}
        />
      )}

      {/* Tabbed panels */}
      <Tabs defaultValue="quotes">
        <TabsList className="flex-wrap h-auto gap-1">
          <TabsTrigger value="quotes" className="text-xs">Live Quotes</TabsTrigger>
          <TabsTrigger value="holdings" className="text-xs">Holdings</TabsTrigger>
          <TabsTrigger value="positions" className="text-xs">Positions</TabsTrigger>
          <TabsTrigger value="margins" className="text-xs">Margins</TabsTrigger>
          <TabsTrigger value="orders" className="text-xs">Orders</TabsTrigger>
          <TabsTrigger value="instruments" className="text-xs">Instruments</TabsTrigger>
          <TabsTrigger value="diagnostics" className="text-xs">Diagnostics</TabsTrigger>
        </TabsList>

        <TabsContent value="quotes" className="mt-4"><QuotesPanel /></TabsContent>
        <TabsContent value="holdings" className="mt-4"><HoldingsPanel /></TabsContent>
        <TabsContent value="positions" className="mt-4"><PositionsPanel /></TabsContent>
        <TabsContent value="margins" className="mt-4"><MarginsPanel /></TabsContent>
        <TabsContent value="orders" className="mt-4"><OrdersPanel /></TabsContent>
        <TabsContent value="instruments" className="mt-4"><InstrumentSearch /></TabsContent>
        <TabsContent value="diagnostics" className="mt-4"><DiagnosticsPanel /></TabsContent>
      </Tabs>
    </div>
  );
}
