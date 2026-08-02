---
name: Phase 9.7 Design System
description: Canonical design token file + 15 DS components + gallery page; key pitfall — Babel rejects generic-JSX syntax.
---

## Rule
All colour, spacing, typography, and semantic values live in `src/lib/designTokens.ts`. Component files must import from there — never hard-code hex strings.

## Components
`src/components/ds/` — 15 components (StatusBadge, PageHeader, HelpPanel, KpiCard, MetricTile, AgentBadge, AlertCard, SectionHeader, EmptyState, ErrorState, LoadingSkeleton, RecommendationCard, HealthCard, StatCard, SummaryCard, DataTable) + `index.ts` barrel.

## PageHeader convention
Applied to TradingTimeline and ExecutiveReports as the canonical page-top pattern. Callers pass `helpTitle`, `faqs[]`, `relatedPages[]`; HelpPanel is internal to PageHeader.

## CSS keyframe naming
Skeleton shimmer animation is `aq-skeleton-shimmer` (prefixed) to avoid collision with the existing `shimmer` keyframe already in `index.css`.

## Critical pitfall — Babel generic-JSX
`<Component<T> ...>` is valid TypeScript JSX but Vite's Babel transform rejects it at runtime with "Unexpected token". `tsc --noEmit` passes fine, masking the issue until the browser loads the page. **Always drop explicit type parameters** and let TypeScript infer from props.

**Why:** Vite uses Babel for JSX transformation, not tsc; Babel's JSX parser does not support TypeScript generics in the tag position.

**How to apply:** Any time you write a generic component usage in JSX, write `<DataTable ...>` not `<DataTable<Row> ...>`. The type is inferred from the `data` and `columns` props.

## Agent colour sync
`AGENT_COLORS` in `designTokens.ts` must mirror `AgentConfig.ts`. There is no runtime link — keep them in sync manually when adding agents.
