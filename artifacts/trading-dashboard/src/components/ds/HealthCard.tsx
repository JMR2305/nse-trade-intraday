/**
 * HealthCard.tsx — DS Phase 9.7
 * Standardised health / system-status card.
 * READ-ONLY · UI ONLY
 */
import React from "react";
import { CheckCircle2, AlertTriangle, XCircle, HelpCircle } from "lucide-react";
import { scoreColor, scoreBg, TEXT, SURFACE, FONT_SIZE, FONT_WEIGHT } from "@/lib/designTokens";

export type HealthStatus = "healthy" | "degraded" | "critical" | "unknown" | "disabled";

const STATUS_CONFIG: Record<HealthStatus, { label: string; color: string; Icon: React.ElementType }> = {
  healthy:  { label: "Healthy",  color: "#10B981", Icon: CheckCircle2  },
  degraded: { label: "Degraded", color: "#F59E0B", Icon: AlertTriangle  },
  critical: { label: "Critical", color: "#EF4444", Icon: XCircle        },
  unknown:  { label: "Unknown",  color: "#6B7280", Icon: HelpCircle     },
  disabled: { label: "Disabled", color: "#4B5563", Icon: HelpCircle     },
};

interface HealthCardProps {
  label:      string;
  status:     HealthStatus;
  score?:     number;    // 0–100
  details?:   string;
  icon?:      React.ElementType;
  compact?:   boolean;
  style?:     React.CSSProperties;
}

export function HealthCard({ label, status, score, details, icon: IconC, compact, style }: HealthCardProps) {
  const cfg = STATUS_CONFIG[status];
  const StatusIcon = cfg.Icon;

  return (
    <div
      style={{
        background:   score !== undefined ? scoreBg(score) : `${cfg.color}10`,
        border:       `1px solid ${cfg.color}25`,
        borderRadius: 10,
        padding:      compact ? "10px 14px" : "14px 16px",
        display:      "flex",
        alignItems:   "center",
        gap:          12,
        ...style,
      }}
      role="status"
      aria-label={`${label}: ${cfg.label}${score !== undefined ? `, score ${score}/100` : ""}`}
    >
      {/* Custom icon or status icon */}
      <div
        style={{
          width:        compact ? 32 : 38,
          height:       compact ? 32 : 38,
          borderRadius: 8,
          background:   `${cfg.color}20`,
          display:      "flex",
          alignItems:   "center",
          justifyContent: "center",
          flexShrink:   0,
        }}
        aria-hidden="true"
      >
        {IconC
          ? <IconC size={compact ? 15 : 18} color={cfg.color} />
          : <StatusIcon size={compact ? 15 : 18} color={cfg.color} />
        }
      </div>

      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontSize: FONT_SIZE.xs, color: TEXT.muted, marginBottom: 2 }}>{label}</div>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <span style={{ fontSize: FONT_SIZE.md, fontWeight: FONT_WEIGHT.semibold, color: cfg.color }}>
            {cfg.label}
          </span>
          {score !== undefined && (
            <span style={{ fontSize: FONT_SIZE.sm, color: scoreColor(score), fontWeight: FONT_WEIGHT.medium }}>
              {Math.round(score)}/100
            </span>
          )}
        </div>
        {details && !compact && (
          <div style={{ fontSize: FONT_SIZE.xs, color: TEXT.muted, marginTop: 3 }}>{details}</div>
        )}
      </div>
    </div>
  );
}
