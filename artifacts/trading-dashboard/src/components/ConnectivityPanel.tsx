/**
 * ConnectivityPanel — development-only diagnostics overlay.
 *
 * Rendered only when import.meta.env.DEV is true.
 * Shows API origin, SSE origin, connectivity latency, and last response
 * timestamp so developers can verify connectivity at a glance without
 * opening DevTools.
 *
 * Hidden in production builds via tree-shaking (dead code elimination
 * removes the component body when import.meta.env.DEV is false).
 */

import { useEffect, useRef, useState } from "react";
import { ChevronDown, ChevronUp, Wifi, WifiOff, AlertCircle } from "lucide-react";
import { API_BASE_URL, SSE_STREAM_URL } from "@/lib/apiConfig";
import { healthJson } from "@/lib/api";

interface HealthPing {
  latencyMs: number | null;
  lastSuccessAt: string | null;
  error: string | null;
}

const MODE = import.meta.env.MODE ?? "unknown";
const IS_DEV = import.meta.env.DEV;

export function ConnectivityPanel() {
  // Tree-shake in production
  if (!IS_DEV) return null;

  return <ConnectivityPanelInner />;
}

function ConnectivityPanelInner() {
  const [open, setOpen] = useState(false);
  const [ping, setPing] = useState<HealthPing>({
    latencyMs: null,
    lastSuccessAt: null,
    error: null,
  });
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const runPing = async () => {
    const start = performance.now();
    try {
      await healthJson("/health/live");
      const latencyMs = Math.round(performance.now() - start);
      setPing({
        latencyMs,
        lastSuccessAt: new Date().toLocaleTimeString(),
        error: null,
      });
    } catch (err) {
      setPing((prev) => ({
        latencyMs: null,
        lastSuccessAt: prev.lastSuccessAt,
        error: err instanceof Error ? err.message : String(err),
      }));
    }
  };

  useEffect(() => {
    void runPing();
    intervalRef.current = setInterval(() => void runPing(), 30_000);
    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const connected = ping.error === null && ping.latencyMs !== null;

  return (
    <div className="fixed bottom-3 right-3 z-50 font-mono text-xs">
      {/* Toggle button */}
      <button
        onClick={() => setOpen((o) => !o)}
        className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg border border-border/60 bg-background/90 backdrop-blur shadow-sm hover:bg-muted/80 transition-colors"
        title="Toggle connectivity diagnostics"
      >
        {connected ? (
          <Wifi className="w-3 h-3 text-green-500" />
        ) : ping.error ? (
          <WifiOff className="w-3 h-3 text-destructive" />
        ) : (
          <AlertCircle className="w-3 h-3 text-yellow-500" />
        )}
        <span className="text-muted-foreground">
          {connected
            ? `API ${ping.latencyMs}ms`
            : ping.error
              ? "API unreachable"
              : "…pinging"}
        </span>
        {open ? (
          <ChevronDown className="w-3 h-3 text-muted-foreground" />
        ) : (
          <ChevronUp className="w-3 h-3 text-muted-foreground" />
        )}
      </button>

      {/* Expanded panel */}
      {open && (
        <div className="mt-1.5 p-3 rounded-lg border border-border/60 bg-background/95 backdrop-blur shadow-lg min-w-[280px] space-y-1.5">
          <div className="text-muted-foreground font-semibold text-[10px] uppercase tracking-wider mb-2">
            Connectivity Diagnostics
          </div>

          <Row label="Mode" value={MODE} />
          <Row
            label="API origin"
            value={API_BASE_URL || "/api (relative)"}
            mono
          />
          <Row
            label="SSE endpoint"
            value={SSE_STREAM_URL || "/api/stream (relative)"}
            mono
          />
          <Row
            label="Last ping"
            value={
              ping.latencyMs !== null
                ? `${ping.latencyMs} ms`
                : ping.error
                  ? "—"
                  : "pending…"
            }
            valueClass={
              connected
                ? "text-green-500"
                : ping.error
                  ? "text-destructive"
                  : "text-yellow-500"
            }
          />
          <Row
            label="Last success"
            value={ping.lastSuccessAt ?? "—"}
          />

          {ping.error && (
            <div className="mt-2 p-2 rounded bg-destructive/10 text-destructive text-[10px] break-all">
              {ping.error}
            </div>
          )}

          <div className="pt-1.5 border-t border-border/40 text-[10px] text-muted-foreground/60">
            Refreshes every 30 s · Dev only · Hidden in production
          </div>
        </div>
      )}
    </div>
  );
}

function Row({
  label,
  value,
  mono = false,
  valueClass = "",
}: {
  label: string;
  value: string;
  mono?: boolean;
  valueClass?: string;
}) {
  return (
    <div className="flex justify-between gap-3">
      <span className="text-muted-foreground shrink-0">{label}</span>
      <span
        className={`text-right break-all ${mono ? "font-mono" : ""} ${valueClass || "text-foreground"}`}
      >
        {value}
      </span>
    </div>
  );
}
