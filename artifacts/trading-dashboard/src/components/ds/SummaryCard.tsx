/**
 * SummaryCard.tsx — DS Phase 9.7
 * Narrative summary card — used for AI briefings, agent summaries, session overviews.
 * READ-ONLY · UI ONLY · ADVISORY-ONLY
 */
import React from "react";
import { FileText } from "lucide-react";
import { TEXT, SURFACE, FONT_SIZE, FONT_WEIGHT } from "@/lib/designTokens";

interface SummaryCardProps {
  title:       string;
  text:        string;
  icon?:       React.ElementType;
  accentColor?: string;
  badge?:      React.ReactNode;
  /** Keyword highlights — will be bolded in the text */
  highlights?: string[];
  footer?:     React.ReactNode;
  style?:      React.CSSProperties;
}

function highlightText(text: string, keywords: string[]): React.ReactNode {
  if (!keywords.length) return text;
  const parts = text.split(new RegExp(`(${keywords.map(k => k.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("|")})`, "gi"));
  return parts.map((part, i) =>
    keywords.some(k => k.toLowerCase() === part.toLowerCase())
      ? <strong key={i} style={{ color: TEXT.primary, fontWeight: FONT_WEIGHT.semibold }}>{part}</strong>
      : part
  );
}

export function SummaryCard({
  title, text, icon: IconC = FileText, accentColor = "#6366F1", badge, highlights = [], footer, style,
}: SummaryCardProps) {
  return (
    <div
      style={{
        background:   SURFACE.card,
        border:       `1px solid ${SURFACE.border}`,
        borderLeft:   `3px solid ${accentColor}`,
        borderRadius: 10,
        padding:      "16px 18px",
        ...style,
      }}
      role="article"
    >
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 10 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <IconC size={15} color={accentColor} aria-hidden="true" />
          <span style={{ fontSize: FONT_SIZE.sm, fontWeight: FONT_WEIGHT.semibold, color: TEXT.primary }}>
            {title}
          </span>
        </div>
        {badge}
      </div>
      <p
        style={{
          color:      TEXT.secondary,
          fontSize:   FONT_SIZE.sm,
          lineHeight: 1.7,
          margin:     0,
        }}
      >
        {highlightText(text, highlights)}
      </p>
      {footer && (
        <div style={{ marginTop: 12, paddingTop: 10, borderTop: `1px solid ${SURFACE.border}` }}>
          {footer}
        </div>
      )}
    </div>
  );
}
