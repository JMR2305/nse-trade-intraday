/**
 * PageHeader.tsx — DS Phase 9.7
 * Standardised page header for every page on the ApexQuant AI platform.
 *
 * Provides: title · subtitle · agent badge · last-updated · status badge ·
 *           advisory mode badge · action slot · breadcrumb · help button.
 *
 * READ-ONLY · UI ONLY
 */
import React, { useState } from "react";
import { HelpCircle, ChevronRight, Clock }  from "lucide-react";
import { AGENT_COLORS, AgentId, TEXT, SURFACE, FONT_SIZE, FONT_WEIGHT } from "@/lib/designTokens";
import { StatusBadge, StatusBadgeVariant }  from "./StatusBadge";
import { HelpPanel }                        from "./HelpPanel";

export interface BreadcrumbItem {
  label: string;
  href?: string;
}

export interface PageHeaderProps {
  /** Primary page title */
  title:       string;
  /** One-line description shown below title */
  subtitle?:   string;
  /** Icon component (e.g. from lucide-react) */
  icon?:       React.ElementType;
  /** Agent this page belongs to */
  agentId?:    AgentId;
  agentName?:  string;
  /** Live / stale / error / disabled */
  status?:     StatusBadgeVariant;
  /** ISO timestamp of last data refresh */
  lastUpdated?: string;
  /** Whether the page is advisory-only (shows badge) */
  advisory?:   boolean;
  /** Whether the page is read-only (shows badge) */
  readOnly?:   boolean;
  /** Breadcrumb trail */
  breadcrumbs?: BreadcrumbItem[];
  /** Slot for action buttons (right-aligned) */
  actions?:    React.ReactNode;
  /** Help system */
  helpTitle?:  string;
  helpContent?: React.ReactNode;
  faqs?:       { q: string; a: string }[];
  relatedPages?: { label: string; href: string }[];
}

function fmtUpdated(iso: string | undefined): string {
  if (!iso) return "";
  try {
    const d = new Date(iso);
    return d.toLocaleTimeString("en-IN", { timeZone: "Asia/Kolkata", hour12: false, hour: "2-digit", minute: "2-digit" });
  } catch { return ""; }
}

export function PageHeader({
  title, subtitle, icon: IconC, agentId, agentName, status,
  lastUpdated, advisory, readOnly, breadcrumbs, actions,
  helpTitle, helpContent, faqs, relatedPages,
}: PageHeaderProps) {
  const [helpOpen, setHelpOpen] = useState(false);
  const agentColor = agentId ? AGENT_COLORS[agentId] : "#6B7280";
  const showHelp   = !!(helpTitle || helpContent || faqs?.length || relatedPages?.length);
  const updatedStr = fmtUpdated(lastUpdated);

  return (
    <>
      <div
        style={{
          marginBottom:   20,
          paddingBottom:  16,
          borderBottom:   `1px solid ${SURFACE.border}`,
        }}
        role="banner"
      >
        {/* Breadcrumbs */}
        {breadcrumbs && breadcrumbs.length > 0 && (
          <nav
            aria-label="Breadcrumb"
            style={{ display: "flex", alignItems: "center", gap: 4, marginBottom: 8 }}
          >
            {breadcrumbs.map((crumb, i) => (
              <React.Fragment key={i}>
                {i > 0 && <ChevronRight size={11} color={TEXT.muted} aria-hidden="true" />}
                <span
                  style={{
                    fontSize:   FONT_SIZE.xs,
                    color:      i === breadcrumbs.length - 1 ? TEXT.tertiary : TEXT.muted,
                    fontWeight: i === breadcrumbs.length - 1 ? FONT_WEIGHT.medium : FONT_WEIGHT.normal,
                    cursor:     crumb.href ? "pointer" : "default",
                  }}
                  onClick={crumb.href ? () => { window.location.href = crumb.href!; } : undefined}
                  role={crumb.href ? "link" : undefined}
                  tabIndex={crumb.href ? 0 : undefined}
                  onKeyDown={crumb.href ? (e) => { if (e.key === "Enter") window.location.href = crumb.href!; } : undefined}
                >
                  {crumb.label}
                </span>
              </React.Fragment>
            ))}
          </nav>
        )}

        {/* Main header row */}
        <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 12 }}>
          <div style={{ display: "flex", alignItems: "flex-start", gap: 12, minWidth: 0, flex: 1 }}>
            {/* Icon */}
            {IconC && (
              <div
                style={{
                  width:          40,
                  height:         40,
                  borderRadius:   10,
                  background:     `${agentColor}18`,
                  border:         `1px solid ${agentColor}30`,
                  display:        "flex",
                  alignItems:     "center",
                  justifyContent: "center",
                  flexShrink:     0,
                  marginTop:      2,
                }}
                aria-hidden="true"
              >
                <IconC size={20} color={agentColor} />
              </div>
            )}

            {/* Title group */}
            <div style={{ minWidth: 0 }}>
              <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                <h1
                  style={{
                    fontSize:   FONT_SIZE["2xl"],
                    fontWeight: FONT_WEIGHT.bold,
                    color:      TEXT.primary,
                    margin:     0,
                    lineHeight: 1.2,
                  }}
                >
                  {title}
                </h1>

                {/* Mode badges */}
                {advisory && (
                  <span
                    style={{
                      fontSize:     FONT_SIZE.xs,
                      color:        "#9CA3AF",
                      border:       "1px solid #374151",
                      borderRadius: 4,
                      padding:      "2px 7px",
                      lineHeight:   1.5,
                    }}
                    aria-label="Advisory only — no execution"
                  >
                    Advisory only
                  </span>
                )}
                {readOnly && (
                  <span
                    style={{
                      fontSize:     FONT_SIZE.xs,
                      color:        "#9CA3AF",
                      border:       "1px solid #374151",
                      borderRadius: 4,
                      padding:      "2px 7px",
                      lineHeight:   1.5,
                    }}
                    aria-label="Read-only — no configuration changes"
                  >
                    Read-only
                  </span>
                )}
                {status && <StatusBadge variant={status} size="sm" />}
              </div>

              {/* Subtitle row */}
              {(subtitle || agentName || updatedStr) && (
                <div
                  style={{
                    display:    "flex",
                    alignItems: "center",
                    gap:        10,
                    marginTop:  4,
                    flexWrap:   "wrap",
                  }}
                >
                  {subtitle && (
                    <span style={{ fontSize: FONT_SIZE.sm, color: TEXT.muted, lineHeight: 1.5 }}>
                      {subtitle}
                    </span>
                  )}
                  {agentName && (
                    <span
                      style={{
                        fontSize:     FONT_SIZE.xs,
                        color:        agentColor,
                        background:   `${agentColor}15`,
                        border:       `1px solid ${agentColor}25`,
                        borderRadius: 4,
                        padding:      "1px 7px",
                        lineHeight:   1.6,
                        fontWeight:   FONT_WEIGHT.medium,
                      }}
                      aria-label={`Managed by ${agentName}`}
                    >
                      {agentName}
                    </span>
                  )}
                  {updatedStr && (
                    <span
                      style={{ display: "flex", alignItems: "center", gap: 4, fontSize: FONT_SIZE.xs, color: TEXT.muted }}
                      aria-label={`Last updated ${updatedStr} IST`}
                    >
                      <Clock size={10} aria-hidden="true" />
                      {updatedStr} IST
                    </span>
                  )}
                </div>
              )}
            </div>
          </div>

          {/* Actions slot + help button */}
          <div style={{ display: "flex", alignItems: "center", gap: 8, flexShrink: 0 }}>
            {actions}
            {showHelp && (
              <button
                onClick={() => setHelpOpen(true)}
                aria-label="Open help panel"
                title="Help & documentation"
                style={{
                  display:        "flex",
                  alignItems:     "center",
                  justifyContent: "center",
                  width:          32,
                  height:         32,
                  borderRadius:   6,
                  background:     "transparent",
                  border:         `1px solid ${SURFACE.border}`,
                  cursor:         "pointer",
                  color:          TEXT.muted,
                  transition:     "all 150ms ease",
                }}
                onMouseEnter={e => { (e.currentTarget as HTMLButtonElement).style.background = SURFACE.card; }}
                onMouseLeave={e => { (e.currentTarget as HTMLButtonElement).style.background = "transparent"; }}
              >
                <HelpCircle size={15} aria-hidden="true" />
              </button>
            )}
          </div>
        </div>
      </div>

      {/* Help panel */}
      {showHelp && (
        <HelpPanel
          open={helpOpen}
          onClose={() => setHelpOpen(false)}
          title={helpTitle ?? title}
          content={helpContent}
          faqs={faqs}
          relatedPages={relatedPages}
        />
      )}
    </>
  );
}
