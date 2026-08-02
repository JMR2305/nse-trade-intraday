/**
 * LoadingSkeleton.tsx — DS Phase 9.7
 * Standardised skeleton loaders with consistent animation.
 * READ-ONLY · UI ONLY
 */
import React from "react";
import { SURFACE } from "@/lib/designTokens";

interface SkeletonProps {
  width?:       number | string;
  height?:      number | string;
  borderRadius?: number | string;
  style?:       React.CSSProperties;
  "aria-label"?: string;
}

/** Single skeleton line / block */
export function Skeleton({ width = "100%", height = 16, borderRadius = 6, style, ...rest }: SkeletonProps) {
  return (
    <div
      role="status"
      aria-label={rest["aria-label"] ?? "Loading…"}
      style={{
        width,
        height,
        borderRadius,
        background: `linear-gradient(90deg, ${SURFACE.card} 25%, #232a3e 50%, ${SURFACE.card} 75%)`,
        backgroundSize: "200% 100%",
        animation: "aq-skeleton-shimmer 1.5s infinite",
        ...style,
      }}
    />
  );
}

/** Skeleton card — mimics a KpiCard */
export function KpiCardSkeleton({ count = 4 }: { count?: number }) {
  return (
    <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
      {Array.from({ length: count }).map((_, i) => (
        <div
          key={i}
          style={{
            flex:         "1 1 110px",
            minWidth:     110,
            background:   SURFACE.card,
            border:       `1px solid ${SURFACE.border}`,
            borderRadius: 10,
            padding:      "12px 16px",
          }}
          role="status"
          aria-label="Loading metric"
        >
          <Skeleton height={10} width="50%" style={{ marginBottom: 10 }} />
          <Skeleton height={28} width="70%" />
        </div>
      ))}
    </div>
  );
}

/** Skeleton table rows */
export function TableSkeleton({ rows = 5, cols = 4 }: { rows?: number; cols?: number }) {
  return (
    <div role="status" aria-label="Loading table…">
      <div style={{ display: "flex", gap: 12, padding: "8px 12px", marginBottom: 4 }}>
        {Array.from({ length: cols }).map((_, i) => (
          <Skeleton key={i} height={12} width="100%" borderRadius={4} />
        ))}
      </div>
      {Array.from({ length: rows }).map((_, r) => (
        <div key={r} style={{ display: "flex", gap: 12, padding: "10px 12px", borderTop: `1px solid ${SURFACE.borderSub}` }}>
          {Array.from({ length: cols }).map((_, c) => (
            <Skeleton
              key={c}
              height={13}
              width={c === 0 ? "40%" : "100%"}
              borderRadius={4}
            />
          ))}
        </div>
      ))}
    </div>
  );
}

/** Skeleton page header */
export function PageHeaderSkeleton() {
  return (
    <div style={{ marginBottom: 20, paddingBottom: 16, borderBottom: `1px solid ${SURFACE.border}` }}>
      <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
        <Skeleton width={40} height={40} borderRadius={10} />
        <div style={{ flex: 1 }}>
          <Skeleton height={22} width="30%" style={{ marginBottom: 8 }} />
          <Skeleton height={14} width="50%" />
        </div>
      </div>
    </div>
  );
}

/** Card skeleton — generic content card */
export function CardSkeleton({ lines = 3 }: { lines?: number }) {
  return (
    <div
      style={{
        background:   SURFACE.card,
        border:       `1px solid ${SURFACE.border}`,
        borderRadius: 10,
        padding:      "16px 18px",
      }}
      role="status"
      aria-label="Loading card…"
    >
      <Skeleton height={12} width="40%" style={{ marginBottom: 14 }} />
      {Array.from({ length: lines }).map((_, i) => (
        <Skeleton
          key={i}
          height={13}
          width={i === lines - 1 ? "65%" : "100%"}
          style={{ marginBottom: i < lines - 1 ? 8 : 0 }}
        />
      ))}
    </div>
  );
}
