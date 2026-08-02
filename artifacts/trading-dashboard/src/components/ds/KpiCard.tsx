/**
 * KpiCard.tsx — DS Phase 9.7
 * Standardised KPI metric card used across the platform.
 * READ-ONLY · UI ONLY
 */
import React from "react";
import { scoreColor, scoreBg, pnlColor, SURFACE, TEXT, FONT_SIZE, FONT_WEIGHT } from "@/lib/designTokens";

interface KpiCardProps {
  label:       string;
  value:       string | number;
  /** Secondary line (e.g. "vs yesterday +2.3%") */
  sub?:        string;
  /** Icon component */
  icon?:       React.ElementType;
  iconColor?:  string;
  /** Treat value as a 0–100 score and colour accordingly */
  scoreMode?:  boolean;
  /** Treat value as a currency P&L number */
  pnlMode?:    boolean;
  pnlValue?:   number;
  /** Custom override colour */
  color?:      string;
  /** Tooltip / accessible description */
  description?: string;
  onClick?:    () => void;
  style?:      React.CSSProperties;
}

export function KpiCard({
  label, value, sub, icon: IconC, iconColor, scoreMode, pnlMode, pnlValue,
  color, description, onClick, style,
}: KpiCardProps) {
  const numericValue = typeof value === "number" ? value : parseFloat(String(value));

  let displayColor = color ?? TEXT.secondary;
  if (scoreMode) displayColor = scoreColor(numericValue);
  if (pnlMode && pnlValue !== undefined) displayColor = pnlColor(pnlValue);

  const bgColor = scoreMode ? scoreBg(numericValue) : `${displayColor}10`;

  return (
    <div
      style={{
        background:   bgColor,
        border:       `1px solid ${displayColor}22`,
        borderRadius: 10,
        padding:      "12px 16px",
        minWidth:     110,
        flex:         "1 1 110px",
        cursor:       onClick ? "pointer" : "default",
        transition:   "all 150ms ease",
        ...style,
      }}
      onClick={onClick}
      role={onClick ? "button" : undefined}
      tabIndex={onClick ? 0 : undefined}
      onKeyDown={onClick ? (e) => { if (e.key === "Enter" || e.key === " ") onClick(); } : undefined}
      title={description}
      aria-label={`${label}: ${value}${description ? `. ${description}` : ""}`}
      onMouseEnter={onClick ? (e) => { (e.currentTarget as HTMLDivElement).style.background = `${displayColor}18`; } : undefined}
      onMouseLeave={onClick ? (e) => { (e.currentTarget as HTMLDivElement).style.background = bgColor; } : undefined}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 6 }}>
        {IconC && <IconC size={13} color={iconColor ?? displayColor} aria-hidden="true" />}
        <span
          style={{
            fontSize:      FONT_SIZE["2xs"],
            color:         TEXT.muted,
            letterSpacing: "0.04em",
            fontWeight:    FONT_WEIGHT.semibold,
            textTransform: "uppercase",
          }}
        >
          {label}
        </span>
      </div>
      <div
        style={{
          fontSize:   FONT_SIZE["2xl"],
          fontWeight: FONT_WEIGHT.bold,
          color:      displayColor,
          lineHeight: 1,
        }}
      >
        {scoreMode
          ? <>
              {typeof value === "number" ? Math.round(numericValue) : value}
              <span style={{ fontSize: FONT_SIZE.sm, fontWeight: FONT_WEIGHT.normal, color: TEXT.muted }}>/100</span>
            </>
          : value
        }
      </div>
      {sub && (
        <div style={{ fontSize: FONT_SIZE.xs, color: TEXT.muted, marginTop: 4 }}>{sub}</div>
      )}
    </div>
  );
}
