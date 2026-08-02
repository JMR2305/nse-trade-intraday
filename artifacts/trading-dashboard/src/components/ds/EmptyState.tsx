/**
 * EmptyState.tsx — DS Phase 9.7
 * Standardised empty-state component.
 * Explains: why data is missing · how data appears · what to do next · related links.
 * READ-ONLY · UI ONLY
 */
import React from "react";
import { Inbox } from "lucide-react";
import { TEXT, SURFACE, FONT_SIZE, FONT_WEIGHT } from "@/lib/designTokens";
import { useLocation } from "wouter";

interface EmptyStateAction {
  label:    string;
  href?:    string;
  onClick?: () => void;
  primary?: boolean;
}

interface EmptyStateProps {
  icon?:        React.ElementType;
  iconColor?:   string;
  title:        string;
  description:  string;
  why?:         string;
  howItAppears?: string;
  actions?:     EmptyStateAction[];
  relatedPages?: { label: string; href: string }[];
  compact?:     boolean;
  style?:       React.CSSProperties;
}

export function EmptyState({
  icon: IconC = Inbox, iconColor = "#4B5563",
  title, description, why, howItAppears, actions, relatedPages, compact, style,
}: EmptyStateProps) {
  const [, navigate] = useLocation();

  return (
    <div
      role="status"
      aria-label={title}
      style={{
        display:        "flex",
        flexDirection:  "column",
        alignItems:     "center",
        justifyContent: "center",
        padding:        compact ? "32px 20px" : "56px 32px",
        textAlign:      "center",
        ...style,
      }}
    >
      {/* Icon */}
      <div
        style={{
          width:        compact ? 48 : 64,
          height:       compact ? 48 : 64,
          borderRadius: "50%",
          background:   SURFACE.card,
          border:       `1px solid ${SURFACE.border}`,
          display:      "flex",
          alignItems:   "center",
          justifyContent: "center",
          marginBottom: 16,
        }}
        aria-hidden="true"
      >
        <IconC size={compact ? 22 : 28} color={iconColor} />
      </div>

      {/* Title */}
      <h3 style={{ fontSize: FONT_SIZE.lg, fontWeight: FONT_WEIGHT.semibold, color: TEXT.primary, margin: "0 0 6px" }}>
        {title}
      </h3>

      {/* Description */}
      <p style={{ fontSize: FONT_SIZE.sm, color: TEXT.muted, maxWidth: 360, lineHeight: 1.6, margin: "0 0 12px" }}>
        {description}
      </p>

      {/* Why / How */}
      {(why || howItAppears) && (
        <div
          style={{
            background:   SURFACE.card,
            border:       `1px solid ${SURFACE.border}`,
            borderRadius: 8,
            padding:      "12px 16px",
            maxWidth:     360,
            textAlign:    "left",
            marginBottom: 16,
          }}
        >
          {why && (
            <p style={{ fontSize: FONT_SIZE.sm, color: TEXT.secondary, margin: "0 0 6px", lineHeight: 1.5 }}>
              <strong style={{ color: TEXT.tertiary }}>Why: </strong>{why}
            </p>
          )}
          {howItAppears && (
            <p style={{ fontSize: FONT_SIZE.sm, color: TEXT.secondary, margin: 0, lineHeight: 1.5 }}>
              <strong style={{ color: TEXT.tertiary }}>How data appears: </strong>{howItAppears}
            </p>
          )}
        </div>
      )}

      {/* Actions */}
      {actions && actions.length > 0 && (
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", justifyContent: "center", marginBottom: 12 }}>
          {actions.map((action, i) => (
            <button
              key={i}
              onClick={action.onClick ?? (action.href ? () => navigate(action.href!) : undefined)}
              style={{
                padding:      "7px 16px",
                borderRadius: 6,
                fontSize:     FONT_SIZE.sm,
                fontWeight:   FONT_WEIGHT.medium,
                cursor:       "pointer",
                border:       action.primary ? "none" : `1px solid ${SURFACE.border}`,
                background:   action.primary ? "#6366F1" : SURFACE.card,
                color:        action.primary ? "#fff" : TEXT.secondary,
                transition:   "all 150ms ease",
              }}
              aria-label={action.label}
            >
              {action.label}
            </button>
          ))}
        </div>
      )}

      {/* Related pages */}
      {relatedPages && relatedPages.length > 0 && (
        <div style={{ display: "flex", gap: 6, flexWrap: "wrap", justifyContent: "center" }}>
          {relatedPages.map((page, i) => (
            <button
              key={i}
              onClick={() => navigate(page.href)}
              style={{
                fontSize:   FONT_SIZE.xs,
                color:      TEXT.link,
                background: "none",
                border:     "none",
                cursor:     "pointer",
                padding:    "2px 4px",
                textDecoration: "underline",
              }}
            >
              {page.label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
