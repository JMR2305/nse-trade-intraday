/**
 * AlertCard.tsx — DS Phase 9.7
 * Standardised alert / notification card.
 * READ-ONLY · UI ONLY
 */
import React from "react";
import { AlertTriangle, XCircle, Info, CheckCircle2, AlertOctagon } from "lucide-react";
import { SEVERITY_COLORS, SEVERITY_BG, SEVERITY_BORDER, TEXT, FONT_SIZE, FONT_WEIGHT } from "@/lib/designTokens";

export type AlertSeverity = "critical" | "high" | "medium" | "low" | "info" | "success";

const ICON_MAP: Record<AlertSeverity, React.ElementType> = {
  critical: AlertOctagon,
  high:     XCircle,
  medium:   AlertTriangle,
  low:      Info,
  info:     Info,
  success:  CheckCircle2,
};

const COLOR_MAP: Record<AlertSeverity, string> = {
  critical: SEVERITY_COLORS.critical,
  high:     SEVERITY_COLORS.high,
  medium:   SEVERITY_COLORS.medium,
  low:      SEVERITY_COLORS.low,
  info:     SEVERITY_COLORS.info,
  success:  "#10B981",
};

const BG_MAP: Record<AlertSeverity, string> = {
  critical: SEVERITY_BG.critical,
  high:     SEVERITY_BG.high,
  medium:   SEVERITY_BG.medium,
  low:      SEVERITY_BG.low,
  info:     SEVERITY_BG.info,
  success:  "rgba(16,185,129,0.10)",
};

const BORDER_MAP: Record<AlertSeverity, string> = {
  critical: SEVERITY_BORDER.critical,
  high:     SEVERITY_BORDER.high,
  medium:   SEVERITY_BORDER.medium,
  low:      SEVERITY_BORDER.low,
  info:     SEVERITY_BORDER.info,
  success:  "rgba(16,185,129,0.28)",
};

interface AlertCardProps {
  severity:    AlertSeverity;
  title:       string;
  body?:       string;
  timestamp?:  string;
  actions?:    React.ReactNode;
  compact?:    boolean;
  style?:      React.CSSProperties;
}

export function AlertCard({ severity, title, body, timestamp, actions, compact, style }: AlertCardProps) {
  const IconC   = ICON_MAP[severity];
  const color   = COLOR_MAP[severity];
  const bg      = BG_MAP[severity];
  const border  = BORDER_MAP[severity];

  return (
    <div
      role="alert"
      aria-live={severity === "critical" ? "assertive" : "polite"}
      style={{
        display:      "flex",
        alignItems:   compact ? "center" : "flex-start",
        gap:          10,
        padding:      compact ? "7px 12px" : "12px 14px",
        background:   bg,
        border:       `1px solid ${border}`,
        borderRadius: 8,
        ...style,
      }}
    >
      <IconC
        size={compact ? 14 : 16}
        color={color}
        style={{ marginTop: compact ? 0 : 1, flexShrink: 0 }}
        aria-hidden="true"
      />
      <div style={{ flex: 1, minWidth: 0 }}>
        <div
          style={{
            fontSize:   compact ? FONT_SIZE.sm : FONT_SIZE.md,
            fontWeight: FONT_WEIGHT.semibold,
            color:      color,
            lineHeight: 1.3,
          }}
        >
          {title}
        </div>
        {body && !compact && (
          <p style={{ fontSize: FONT_SIZE.sm, color: TEXT.secondary, margin: "4px 0 0", lineHeight: 1.5 }}>
            {body}
          </p>
        )}
        {timestamp && !compact && (
          <span style={{ fontSize: FONT_SIZE.xs, color: TEXT.muted, marginTop: 4, display: "block" }}>
            {timestamp}
          </span>
        )}
      </div>
      {actions && <div style={{ flexShrink: 0 }}>{actions}</div>}
    </div>
  );
}
