/**
 * ErrorState.tsx — DS Phase 9.7
 * Standardised error state — network, permission, unavailable, offline.
 * READ-ONLY · UI ONLY
 */
import React from "react";
import { WifiOff, ShieldOff, ServerCrash, AlertOctagon, RefreshCw } from "lucide-react";
import { TEXT, SURFACE, FONT_SIZE, FONT_WEIGHT, STATUS_COLORS } from "@/lib/designTokens";
import { useLocation } from "wouter";

export type ErrorKind = "network" | "permission" | "unavailable" | "offline" | "unknown";

const ICON_MAP: Record<ErrorKind, React.ElementType> = {
  network:     WifiOff,
  permission:  ShieldOff,
  unavailable: ServerCrash,
  offline:     WifiOff,
  unknown:     AlertOctagon,
};

const TITLE_MAP: Record<ErrorKind, string> = {
  network:     "Network Error",
  permission:  "Permission Denied",
  unavailable: "Data Unavailable",
  offline:     "Provider Offline",
  unknown:     "Something went wrong",
};

const DESC_MAP: Record<ErrorKind, string> = {
  network:     "Could not reach the API server. Check your network connection.",
  permission:  "You do not have permission to view this data.",
  unavailable: "The data source is currently unavailable. This is usually temporary.",
  offline:     "The data provider is offline. Data will refresh when connectivity is restored.",
  unknown:     "An unexpected error occurred. Use the retry button or check Observability.",
};

interface ErrorStateProps {
  kind?:        ErrorKind;
  title?:       string;
  description?: string;
  error?:       Error | string;
  onRetry?:     () => void;
  diagnosticsHref?: string;
  compact?:     boolean;
  style?:       React.CSSProperties;
}

export function ErrorState({
  kind = "unknown", title, description, error, onRetry, diagnosticsHref, compact, style,
}: ErrorStateProps) {
  const [, navigate] = useLocation();
  const IconC  = ICON_MAP[kind];
  const ttl    = title       ?? TITLE_MAP[kind];
  const desc   = description ?? DESC_MAP[kind];
  const errMsg = error instanceof Error ? error.message : error;

  return (
    <div
      role="alert"
      aria-live="polite"
      style={{
        display:        "flex",
        flexDirection:  "column",
        alignItems:     "center",
        justifyContent: "center",
        padding:        compact ? "28px 20px" : "48px 32px",
        textAlign:      "center",
        ...style,
      }}
    >
      <div
        style={{
          width:        compact ? 44 : 60,
          height:       compact ? 44 : 60,
          borderRadius: "50%",
          background:   "rgba(239,68,68,0.10)",
          border:       `1px solid rgba(239,68,68,0.28)`,
          display:      "flex",
          alignItems:   "center",
          justifyContent: "center",
          marginBottom: 14,
        }}
        aria-hidden="true"
      >
        <IconC size={compact ? 20 : 26} color={STATUS_COLORS.error} />
      </div>

      <h3 style={{ fontSize: FONT_SIZE.lg, fontWeight: FONT_WEIGHT.semibold, color: TEXT.primary, margin: "0 0 6px" }}>
        {ttl}
      </h3>

      <p style={{ fontSize: FONT_SIZE.sm, color: TEXT.muted, maxWidth: 360, lineHeight: 1.6, margin: "0 0 12px" }}>
        {desc}
      </p>

      {errMsg && (
        <div
          style={{
            background:   SURFACE.card,
            border:       `1px solid ${SURFACE.border}`,
            borderRadius: 6,
            padding:      "8px 14px",
            maxWidth:     380,
            marginBottom: 14,
          }}
        >
          <code style={{ fontSize: FONT_SIZE.xs, color: STATUS_COLORS.error, fontFamily: "monospace" }}>
            {errMsg}
          </code>
        </div>
      )}

      <div style={{ display: "flex", gap: 8, flexWrap: "wrap", justifyContent: "center" }}>
        {onRetry && (
          <button
            onClick={onRetry}
            style={{
              display:      "flex",
              alignItems:   "center",
              gap:          6,
              padding:      "7px 16px",
              borderRadius: 6,
              fontSize:     FONT_SIZE.sm,
              fontWeight:   FONT_WEIGHT.medium,
              cursor:       "pointer",
              border:       "none",
              background:   "#6366F1",
              color:        "#fff",
            }}
            aria-label="Retry loading data"
          >
            <RefreshCw size={13} aria-hidden="true" /> Retry
          </button>
        )}
        {diagnosticsHref && (
          <button
            onClick={() => navigate(diagnosticsHref)}
            style={{
              padding:      "7px 16px",
              borderRadius: 6,
              fontSize:     FONT_SIZE.sm,
              fontWeight:   FONT_WEIGHT.medium,
              cursor:       "pointer",
              border:       `1px solid ${SURFACE.border}`,
              background:   SURFACE.card,
              color:        TEXT.secondary,
            }}
            aria-label="Open diagnostics page"
          >
            Diagnostics
          </button>
        )}
      </div>
    </div>
  );
}
