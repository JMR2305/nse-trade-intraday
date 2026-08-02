/**
 * RecommendationCard.tsx — DS Phase 9.7
 * Advisory recommendation card — always marked advisory-only.
 * READ-ONLY · UI ONLY · ADVISORY-ONLY
 */
import React from "react";
import { Lightbulb, ChevronRight } from "lucide-react";
import { TEXT, SURFACE, FONT_SIZE, FONT_WEIGHT } from "@/lib/designTokens";

export type RecommendationPriority = "urgent" | "high" | "medium" | "low";

const PRIORITY_COLOR: Record<RecommendationPriority, string> = {
  urgent: "#EF4444",
  high:   "#F97316",
  medium: "#F59E0B",
  low:    "#6366F1",
};

interface RecommendationCardProps {
  title:       string;
  description: string;
  priority?:   RecommendationPriority;
  source?:     string;          // e.g. "AI Decision Agent"
  actionLabel?: string;
  onAction?:   () => void;
  compact?:    boolean;
  style?:      React.CSSProperties;
}

export function RecommendationCard({
  title, description, priority = "medium", source, actionLabel, onAction, compact, style,
}: RecommendationCardProps) {
  const color = PRIORITY_COLOR[priority];

  return (
    <div
      style={{
        background:   SURFACE.card,
        border:       `1px solid ${SURFACE.border}`,
        borderLeft:   `3px solid ${color}`,
        borderRadius: 8,
        padding:      compact ? "10px 14px" : "14px 16px",
        ...style,
      }}
      role="article"
      aria-label={`Recommendation: ${title}`}
    >
      <div style={{ display: "flex", alignItems: "flex-start", gap: 10 }}>
        <Lightbulb size={14} color={color} style={{ marginTop: 2, flexShrink: 0 }} aria-hidden="true" />
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8, marginBottom: 4 }}>
            <span style={{ fontSize: FONT_SIZE.sm, fontWeight: FONT_WEIGHT.semibold, color: TEXT.primary }}>
              {title}
            </span>
            <span
              style={{
                fontSize:     FONT_SIZE.xs,
                color,
                background:   `${color}15`,
                border:       `1px solid ${color}30`,
                borderRadius: 4,
                padding:      "1px 6px",
                flexShrink:   0,
                fontWeight:   FONT_WEIGHT.medium,
              }}
            >
              {priority}
            </span>
          </div>
          <p style={{ fontSize: FONT_SIZE.sm, color: TEXT.secondary, margin: 0, lineHeight: 1.5 }}>
            {description}
          </p>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginTop: 8 }}>
            {source && (
              <span style={{ fontSize: FONT_SIZE.xs, color: TEXT.muted }}>
                {source} · Advisory only
              </span>
            )}
            {actionLabel && onAction && (
              <button
                onClick={onAction}
                style={{
                  display:    "flex",
                  alignItems: "center",
                  gap:        4,
                  fontSize:   FONT_SIZE.xs,
                  color,
                  background: "none",
                  border:     "none",
                  cursor:     "pointer",
                  padding:    0,
                  fontWeight: FONT_WEIGHT.medium,
                }}
                aria-label={actionLabel}
              >
                {actionLabel} <ChevronRight size={11} />
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
