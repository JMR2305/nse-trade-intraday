/**
 * StatCard.tsx — DS Phase 9.7
 * Statistic card — label, primary value, optional change indicator, optional mini chart.
 * READ-ONLY · UI ONLY
 */
import React from "react";
import { TrendingUp, TrendingDown, Minus } from "lucide-react";
import { pnlColor, TEXT, SURFACE, FONT_SIZE, FONT_WEIGHT } from "@/lib/designTokens";

interface StatCardProps {
  label:      string;
  value:      string | number;
  /** Percentage change (positive = up, negative = down) */
  change?:    number;
  changeLabel?: string;
  icon?:      React.ElementType;
  iconColor?: string;
  /** Compact single-line layout */
  compact?:   boolean;
  style?:     React.CSSProperties;
  onClick?:   () => void;
}

export function StatCard({ label, value, change, changeLabel, icon: IconC, iconColor = "#6B7280", compact, style, onClick }: StatCardProps) {
  const changeColor = change === undefined ? TEXT.muted : pnlColor(change);
  const ChangeIcon  = change === undefined ? Minus : change > 0 ? TrendingUp : change < 0 ? TrendingDown : Minus;

  return (
    <div
      style={{
        background:   SURFACE.card,
        border:       `1px solid ${SURFACE.border}`,
        borderRadius: 10,
        padding:      compact ? "10px 14px" : "14px 18px",
        cursor:       onClick ? "pointer" : "default",
        transition:   "all 150ms ease",
        ...style,
      }}
      onClick={onClick}
      role={onClick ? "button" : undefined}
      tabIndex={onClick ? 0 : undefined}
      onKeyDown={onClick ? (e) => { if (e.key === "Enter") onClick(); } : undefined}
      aria-label={`${label}: ${value}${change !== undefined ? `, change ${change > 0 ? "+" : ""}${change}%` : ""}`}
    >
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 8 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
          {IconC && <IconC size={13} color={iconColor} aria-hidden="true" />}
          <span style={{ fontSize: FONT_SIZE.xs, color: TEXT.muted, fontWeight: FONT_WEIGHT.medium, letterSpacing: "0.03em" }}>
            {label}
          </span>
        </div>
        {change !== undefined && (
          <div style={{ display: "flex", alignItems: "center", gap: 3 }}>
            <ChangeIcon size={11} color={changeColor} aria-hidden="true" />
            <span style={{ fontSize: FONT_SIZE.xs, color: changeColor, fontWeight: FONT_WEIGHT.medium }}>
              {change > 0 ? "+" : ""}{changeLabel ?? `${change.toFixed(1)}%`}
            </span>
          </div>
        )}
      </div>
      <div style={{ fontSize: compact ? FONT_SIZE.xl : FONT_SIZE["2xl"], fontWeight: FONT_WEIGHT.bold, color: TEXT.primary, lineHeight: 1 }}>
        {value}
      </div>
    </div>
  );
}
