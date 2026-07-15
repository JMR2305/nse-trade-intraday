/**
 * useLiveStream — Phase 11 Live Data Foundation.
 * Subscribes to the SSE stream (/api/stream) with automatic reconnect and
 * exposes live index quotes + market status + connection state.
 * Honest values only: nulls are surfaced as-is, never fabricated.
 */
import { useEffect, useRef, useState } from "react";
import { API_BASE } from "@/lib/api";

export interface LiveQuote {
  symbol: string;
  ltp: number | null;
  prev_close: number | null;
  change: number | null;
  change_pct: number | null;
  day_high: number | null;
  day_low: number | null;
  source: string | null;
  fetch_ts: string | null;
  quality: string | null;
  error: string | null;
  from_cache?: boolean;
  cache_age_s?: number | null;
}

export interface MarketStatus {
  state: string;
  is_open: boolean;
  now_ist: string | null;
  holiday_today: string | null;
  next_transition: { event: string; at_ist: string; seconds_until: number } | null;
}

export type StreamConnection = "connecting" | "connected" | "reconnecting" | "disconnected";

interface LiveStreamState {
  connection: StreamConnection;
  quotes: Record<string, LiveQuote>;
  market: MarketStatus | null;
  lastEventTs: string | null;
  lastError: string | null;
  scanEvent: { type: string; data: unknown; ts: string } | null;
}

const MAX_RETRY_MS = 30_000;

export function useLiveStream(enabled = true): LiveStreamState {
  const [state, setState] = useState<LiveStreamState>({
    connection: "connecting",
    quotes: {},
    market: null,
    lastEventTs: null,
    lastError: null,
    scanEvent: null,
  });
  const retryRef = useRef(1000);

  useEffect(() => {
    if (!enabled) return;
    let es: EventSource | null = null;
    let retryTimer: ReturnType<typeof setTimeout> | null = null;
    let closed = false;

    const applyQuotes = (payload: any) => {
      const q = payload?.quotes?.quotes ?? payload?.quotes ?? null;
      const market = payload?.quotes?.market ?? payload?.market ?? null;
      setState((s) => ({
        ...s,
        quotes: q && typeof q === "object" ? { ...s.quotes, ...q } : s.quotes,
        market: market ?? s.market,
        lastEventTs: new Date().toISOString(),
      }));
    };

    const connect = () => {
      if (closed) return;
      es = new EventSource(`${API_BASE}/stream`);

      es.onopen = () => {
        retryRef.current = 1000;
        setState((s) => ({ ...s, connection: "connected", lastError: null }));
      };

      es.addEventListener("snapshot", (e: MessageEvent) => {
        try { applyQuotes(JSON.parse(e.data)); } catch { /* ignore */ }
      });
      es.addEventListener("market.quote", (e: MessageEvent) => {
        try { applyQuotes(JSON.parse(e.data)); } catch { /* ignore */ }
      });
      es.addEventListener("market.status", (e: MessageEvent) => {
        try {
          const m = JSON.parse(e.data);
          setState((s) => ({ ...s, market: m, lastEventTs: new Date().toISOString() }));
        } catch { /* ignore */ }
      });
      for (const t of ["scan.started", "scan.completed", "scan.failed"]) {
        es.addEventListener(t, (e: MessageEvent) => {
          try {
            setState((s) => ({ ...s, scanEvent: { type: t, data: JSON.parse(e.data), ts: new Date().toISOString() } }));
          } catch { /* ignore */ }
        });
      }
      es.addEventListener("market.health", (e: MessageEvent) => {
        try {
          const h = JSON.parse(e.data);
          if (h?.ok === false) setState((s) => ({ ...s, lastError: String(h.error ?? "stream health degraded") }));
        } catch { /* ignore */ }
      });

      es.onerror = () => {
        es?.close();
        if (closed) return;
        setState((s) => ({ ...s, connection: "reconnecting" }));
        retryTimer = setTimeout(connect, retryRef.current);
        retryRef.current = Math.min(retryRef.current * 2, MAX_RETRY_MS);
      };
    };

    connect();
    return () => {
      closed = true;
      if (retryTimer) clearTimeout(retryTimer);
      es?.close();
    };
  }, [enabled]);

  return state;
}
