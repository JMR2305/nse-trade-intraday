/**
 * HelpPanel.tsx — DS Phase 9.7
 * Slide-out help panel with documentation, FAQs, and related page links.
 * READ-ONLY · UI ONLY
 */
import React, { useEffect, useRef } from "react";
import { X, ChevronRight, HelpCircle, FileText, Link2 } from "lucide-react";
import { SURFACE, TEXT, FONT_SIZE, FONT_WEIGHT } from "@/lib/designTokens";
import { useLocation } from "wouter";

interface HelpPanelProps {
  open:          boolean;
  onClose:       () => void;
  title:         string;
  content?:      React.ReactNode;
  faqs?:         { q: string; a: string }[];
  relatedPages?: { label: string; href: string }[];
}

export function HelpPanel({ open, onClose, title, content, faqs, relatedPages }: HelpPanelProps) {
  const [, navigate] = useLocation();
  const firstFocusRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (open) {
      firstFocusRef.current?.focus();
      document.body.style.overflow = "hidden";
    } else {
      document.body.style.overflow = "";
    }
    return () => { document.body.style.overflow = ""; };
  }, [open]);

  // Close on Escape
  useEffect(() => {
    const handler = (e: KeyboardEvent) => { if (e.key === "Escape" && open) onClose(); };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [open, onClose]);

  if (!open) return null;

  return (
    <>
      {/* Backdrop */}
      <div
        style={{
          position: "fixed", inset: 0,
          background: "rgba(0,0,0,0.5)",
          zIndex: 150,
        }}
        onClick={onClose}
        aria-hidden="true"
      />

      {/* Drawer */}
      <aside
        role="complementary"
        aria-label={`Help: ${title}`}
        style={{
          position:   "fixed",
          top:        0,
          right:      0,
          bottom:     0,
          width:      "min(400px, 100vw)",
          background: "#151b2b",
          borderLeft: `1px solid ${SURFACE.border}`,
          zIndex:     160,
          display:    "flex",
          flexDirection: "column",
          boxShadow:  "-8px 0 32px rgba(0,0,0,0.4)",
          overflowY:  "auto",
        }}
      >
        {/* Header */}
        <div
          style={{
            display:        "flex",
            alignItems:     "center",
            justifyContent: "space-between",
            padding:        "16px 20px",
            borderBottom:   `1px solid ${SURFACE.border}`,
            flexShrink:     0,
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <HelpCircle size={16} color="#60A5FA" />
            <span style={{ fontSize: FONT_SIZE.md, fontWeight: FONT_WEIGHT.semibold, color: TEXT.primary }}>
              Help · {title}
            </span>
          </div>
          <button
            ref={firstFocusRef}
            onClick={onClose}
            aria-label="Close help panel"
            style={{
              background: "none", border: "none", cursor: "pointer",
              color: TEXT.muted, padding: 4, borderRadius: 4,
              display: "flex", alignItems: "center",
            }}
          >
            <X size={16} />
          </button>
        </div>

        {/* Content */}
        <div style={{ padding: "20px", flex: 1, overflowY: "auto" }}>

          {/* Custom content */}
          {content && (
            <div style={{ marginBottom: 24 }}>
              <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 10 }}>
                <FileText size={13} color="#60A5FA" />
                <span style={{ fontSize: FONT_SIZE.xs, fontWeight: FONT_WEIGHT.semibold, color: TEXT.tertiary, textTransform: "uppercase", letterSpacing: "0.06em" }}>
                  Documentation
                </span>
              </div>
              <div style={{ color: TEXT.secondary, fontSize: FONT_SIZE.sm, lineHeight: 1.7 }}>
                {content}
              </div>
            </div>
          )}

          {/* FAQs */}
          {faqs && faqs.length > 0 && (
            <div style={{ marginBottom: 24 }}>
              <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 10 }}>
                <HelpCircle size={13} color="#60A5FA" />
                <span style={{ fontSize: FONT_SIZE.xs, fontWeight: FONT_WEIGHT.semibold, color: TEXT.tertiary, textTransform: "uppercase", letterSpacing: "0.06em" }}>
                  Frequently Asked Questions
                </span>
              </div>
              {faqs.map((faq, i) => (
                <details
                  key={i}
                  style={{
                    marginBottom: 8,
                    background:   SURFACE.card,
                    border:       `1px solid ${SURFACE.border}`,
                    borderRadius: 8,
                    overflow:     "hidden",
                  }}
                >
                  <summary
                    style={{
                      padding:    "10px 14px",
                      cursor:     "pointer",
                      fontSize:   FONT_SIZE.sm,
                      fontWeight: FONT_WEIGHT.medium,
                      color:      TEXT.primary,
                      listStyle:  "none",
                      display:    "flex",
                      alignItems: "center",
                      justifyContent: "space-between",
                      userSelect: "none",
                    }}
                  >
                    {faq.q}
                    <ChevronRight size={12} color={TEXT.muted} />
                  </summary>
                  <div style={{ padding: "0 14px 12px", fontSize: FONT_SIZE.sm, color: TEXT.secondary, lineHeight: 1.6 }}>
                    {faq.a}
                  </div>
                </details>
              ))}
            </div>
          )}

          {/* Related pages */}
          {relatedPages && relatedPages.length > 0 && (
            <div>
              <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 10 }}>
                <Link2 size={13} color="#60A5FA" />
                <span style={{ fontSize: FONT_SIZE.xs, fontWeight: FONT_WEIGHT.semibold, color: TEXT.tertiary, textTransform: "uppercase", letterSpacing: "0.06em" }}>
                  Related Pages
                </span>
              </div>
              {relatedPages.map((page, i) => (
                <button
                  key={i}
                  onClick={() => { navigate(page.href); onClose(); }}
                  style={{
                    display:    "flex",
                    alignItems: "center",
                    justifyContent: "space-between",
                    width:      "100%",
                    padding:    "8px 12px",
                    marginBottom: 6,
                    background: SURFACE.card,
                    border:     `1px solid ${SURFACE.border}`,
                    borderRadius: 6,
                    cursor:     "pointer",
                    color:      TEXT.secondary,
                    fontSize:   FONT_SIZE.sm,
                    textAlign:  "left",
                  }}
                  aria-label={`Navigate to ${page.label}`}
                >
                  {page.label}
                  <ChevronRight size={12} color={TEXT.muted} />
                </button>
              ))}
            </div>
          )}
        </div>

        {/* Footer */}
        <div
          style={{
            padding:      "12px 20px",
            borderTop:    `1px solid ${SURFACE.border}`,
            fontSize:     FONT_SIZE.xs,
            color:        TEXT.muted,
            flexShrink:   0,
          }}
        >
          ApexQuant AI · Advisory Only · Read-Only · No Execution
        </div>
      </aside>
    </>
  );
}
