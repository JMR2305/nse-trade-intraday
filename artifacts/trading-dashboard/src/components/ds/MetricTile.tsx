/**
 * MetricTile.tsx — DS Phase 9.7
 * Compact metric tile — smaller footprint than KpiCard.
 * READ-ONLY · UI ONLY
 */
import React from "react";
import { pnlColor, TEXT, SURFACE, FONT_SIZE, FONT_WEIGHT } from "@/lib/designTokens";

interface MetricTileProps {
  label:      string;
  value:      string | number;
  sub?:       string;
  color?:     string;
  /** Auto-colour by sign */
  pnl?:       boolean;
  icon?:      React.ElementType;
  style?:     React.CSSProperties;
}

export function MetricTile({ label, value, sub, color, pnl, icon: IconC, style }: MetricTileProps) {
  const num    = typeof value === "number" ? value : parseFloat(String(value));
  const clr    = color ?? (pnl ? pnlColor(isNaN(num) ? 0 : num) : TEXT.secondary);

  return (
    <div
      style={{
        background:   SURFACE.card,
        border:       `1px solid ${SURFACE.border}`,
        borderRadius: 8,
        padding:      "10px 14px",
        minWidth:     100,
        flex:         "1 1 100px",
        ...style,
      }}
      aria-label={`${label}: ${value}`}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 5, marginBottom: 3 }}>
        {IconC && <IconC size={11} color={TEXT.muted} aria-hidden="true" />}
        <span style={{ fontSize: FONT_SIZE.xs, color: TEXT.muted, letterSpacing: "0.03em", fontWeight: FONT_WEIGHT.medium }}>
          {label}
        </span>
      </div>
      <div style={{ fontSize: FONT_SIZE.xl, fontWeight: FONT_WEIGHT.bold, color: clr, lineHeight: 1 }}>
        {value}
      </div>
      {sub && <div style={{ fontSize: FONT_SIZE.xs, color: TEXT.muted, marginTop: 3 }}>{sub}</div>}
    </div>
  );
}
