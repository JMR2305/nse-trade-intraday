/**
 * AgentBadge.tsx — DS Phase 9.7
 * Agent attribution badge shown on cards and page headers.
 * READ-ONLY · UI ONLY
 */
import React from "react";
import { AGENT_COLORS, AgentId, FONT_SIZE, FONT_WEIGHT } from "@/lib/designTokens";

interface AgentBadgeProps {
  agentId?:   AgentId;
  agentName:  string;
  agentColor?: string;
  size?:      "xs" | "sm" | "md";
  style?:     React.CSSProperties;
}

export function AgentBadge({ agentId, agentName, agentColor, size = "sm", style }: AgentBadgeProps) {
  const color  = agentColor ?? (agentId ? AGENT_COLORS[agentId] : "#6B7280");
  const fs     = size === "xs" ? FONT_SIZE.xs : size === "sm" ? FONT_SIZE.sm : FONT_SIZE.md;
  const px     = size === "xs" ? 6 : size === "sm" ? 8 : 10;
  const py     = size === "xs" ? 2 : size === "sm" ? 3 : 4;

  return (
    <span
      style={{
        display:      "inline-flex",
        alignItems:   "center",
        gap:          5,
        padding:      `${py}px ${px}px`,
        background:   `${color}15`,
        border:       `1px solid ${color}25`,
        borderRadius: 5,
        fontSize:     fs,
        fontWeight:   FONT_WEIGHT.medium,
        color,
        lineHeight:   1.5,
        whiteSpace:   "nowrap",
        ...style,
      }}
      aria-label={`Managed by ${agentName}`}
    >
      <span
        style={{ width: 6, height: 6, borderRadius: "50%", background: color, flexShrink: 0 }}
        aria-hidden="true"
      />
      {agentName}
    </span>
  );
}
