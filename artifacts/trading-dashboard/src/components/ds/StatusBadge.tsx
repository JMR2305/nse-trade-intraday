/**
 * StatusBadge.tsx — DS Phase 9.7
 * Standardised status / severity badge with consistent colours.
 */
import React from "react";
import { SEVERITY_COLORS, SEVERITY_BG, STATUS_COLORS } from "@/lib/designTokens";

export type StatusBadgeVariant =
  | "live" | "stale" | "offline" | "unknown" | "disabled"
  | "success" | "warning" | "error" | "info" | "neutral"
  | "critical" | "high" | "medium" | "low";

const VARIANT_LABEL: Record<StatusBadgeVariant, string> = {
  live:     "Live",
  stale:    "Stale",
  offline:  "Offline",
  unknown:  "Unknown",
  disabled: "Disabled",
  success:  "Success",
  warning:  "Warning",
  error:    "Error",
  info:     "Info",
  neutral:  "—",
  critical: "Critical",
  high:     "High",
  medium:   "Medium",
  low:      "Low",
};

const VARIANT_COLOR: Record<StatusBadgeVariant, string> = {
  live:     STATUS_COLORS.live,
  stale:    STATUS_COLORS.stale,
  offline:  STATUS_COLORS.offline,
  unknown:  STATUS_COLORS.unknown,
  disabled: STATUS_COLORS.disabled,
  success:  STATUS_COLORS.success,
  warning:  STATUS_COLORS.warning,
  error:    STATUS_COLORS.error,
  info:     STATUS_COLORS.info,
  neutral:  STATUS_COLORS.neutral,
  critical: SEVERITY_COLORS.critical,
  high:     SEVERITY_COLORS.high,
  medium:   SEVERITY_COLORS.medium,
  low:      SEVERITY_COLORS.low,
};

const VARIANT_BG: Record<StatusBadgeVariant, string> = {
  live:     "rgba(16,185,129,0.12)",
  stale:    "rgba(245,158,11,0.12)",
  offline:  "rgba(239,68,68,0.12)",
  unknown:  "rgba(107,114,128,0.12)",
  disabled: "rgba(55,65,81,0.20)",
  success:  "rgba(16,185,129,0.12)",
  warning:  "rgba(245,158,11,0.12)",
  error:    "rgba(239,68,68,0.12)",
  info:     "rgba(59,130,246,0.12)",
  neutral:  "rgba(107,114,128,0.12)",
  critical: SEVERITY_BG.critical,
  high:     SEVERITY_BG.high,
  medium:   SEVERITY_BG.medium,
  low:      SEVERITY_BG.low,
};

interface StatusBadgeProps {
  variant:   StatusBadgeVariant;
  label?:    string;
  dot?:      boolean;
  size?:     "xs" | "sm" | "md";
  className?: string;
  style?:    React.CSSProperties;
}

export function StatusBadge({ variant, label, dot = true, size = "sm", className, style }: StatusBadgeProps) {
  const color  = VARIANT_COLOR[variant];
  const bg     = VARIANT_BG[variant];
  const text   = label ?? VARIANT_LABEL[variant];

  const fontSize = size === "xs" ? 10 : size === "sm" ? 11 : 12;
  const px       = size === "xs" ? 6  : size === "sm" ? 8  : 10;
  const py       = size === "xs" ? 2  : size === "sm" ? 3  : 4;
  const dotSize  = size === "xs" ? 5  : size === "sm" ? 6  : 7;

  return (
    <span
      className={className}
      style={{
        display:        "inline-flex",
        alignItems:     "center",
        gap:            5,
        padding:        `${py}px ${px}px`,
        background:     bg,
        border:         `1px solid ${color}30`,
        borderRadius:   99,
        fontSize,
        fontWeight:     600,
        color,
        letterSpacing:  "0.03em",
        lineHeight:     1,
        whiteSpace:     "nowrap",
        ...style,
      }}
      aria-label={`Status: ${text}`}
    >
      {dot && (
        <span
          style={{
            width:        dotSize,
            height:       dotSize,
            borderRadius: "50%",
            background:   color,
            flexShrink:   0,
          }}
          aria-hidden="true"
        />
      )}
      {text}
    </span>
  );
}
