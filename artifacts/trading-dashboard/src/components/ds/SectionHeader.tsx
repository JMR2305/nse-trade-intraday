/**
 * SectionHeader.tsx — DS Phase 9.7
 * Standardised section heading with optional icon, badge, and action slot.
 * READ-ONLY · UI ONLY
 */
import React from "react";
import { TEXT, SURFACE, FONT_SIZE, FONT_WEIGHT } from "@/lib/designTokens";

interface SectionHeaderProps {
  title:       string;
  subtitle?:   string;
  icon?:       React.ElementType;
  iconColor?:  string;
  badge?:      React.ReactNode;
  actions?:    React.ReactNode;
  divider?:    boolean;
  style?:      React.CSSProperties;
}

export function SectionHeader({
  title, subtitle, icon: IconC, iconColor = "#6B7280", badge, actions, divider = false, style,
}: SectionHeaderProps) {
  return (
    <div
      style={{
        display:       "flex",
        alignItems:    "center",
        justifyContent:"space-between",
        marginBottom:  12,
        paddingBottom: divider ? 10 : 0,
        borderBottom:  divider ? `1px solid ${SURFACE.border}` : "none",
        ...style,
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        {IconC && <IconC size={15} color={iconColor} aria-hidden="true" />}
        <div>
          <div
            style={{
              fontSize:      FONT_SIZE.xs,
              fontWeight:    FONT_WEIGHT.semibold,
              color:         TEXT.tertiary,
              letterSpacing: "0.06em",
              textTransform: "uppercase",
              lineHeight:    1.4,
            }}
          >
            {title}
          </div>
          {subtitle && (
            <div style={{ fontSize: FONT_SIZE.xs, color: TEXT.muted, marginTop: 1 }}>
              {subtitle}
            </div>
          )}
        </div>
        {badge}
      </div>
      {actions && <div style={{ flexShrink: 0 }}>{actions}</div>}
    </div>
  );
}
