# Phase 9.7 — UX Consolidation & Professional Design System

**Status:** ✅ Complete  
**Date:** 2 August 2026  
**Artifact:** `artifacts/trading-dashboard`

---

## Objective

Establish a canonical, shared design system for the ApexQuant AI trading dashboard so every page speaks the same visual language — consistent tokens, standardised components, and professional page anatomy across all 70+ routes.

---

## Deliverables

### 1. Design Token File
**`src/lib/designTokens.ts`**

Single source of truth for all hard-coded values:

| Token group | Contents |
|---|---|
| `AGENT_COLORS` | One hex per agent (market-data, research, market-intelligence, monitoring, strategy, risk, ai, execution, learning, operations) |
| `STATUS_COLORS` | live / stale / offline / connected / error |
| `SEVERITY_COLORS` | critical / high / medium / low / info / success |
| `PNL_COLORS` | positive / negative / neutral |
| `SURFACE` | page / card / elevated / overlay |
| `TEXT` | primary / secondary / muted / inverse |
| `FONT_SIZE` | xs → 2xl |
| `FONT_WEIGHT` | normal / medium / semibold / bold |
| `SPACE` | 1 → 12 (4px grid) |
| `RADIUS` | sm / md / lg / full |
| `CHART_COLORS` | 10-colour Recharts sequence |
| Helper functions | `scoreColor(n)`, `scoreBg(n)`, `pnlColor(n)` |

### 2. DS Component Library
**`src/components/ds/`** — 15 components + barrel export

| Component | Purpose |
|---|---|
| `StatusBadge` | Unified status/severity pill (live/stale/offline/critical/high/medium/low/info/success) |
| `PageHeader` | Full page header: icon, title, subtitle, agentId, status badges, breadcrumbs, last-updated IST, actions slot, help button |
| `HelpPanel` | Slide-out help drawer: collapsible FAQs, related-page links, Escape to close |
| `KpiCard` | Score-mode (0–100, colour-coded) and P&L-mode KPI card |
| `MetricTile` | Compact metric tile |
| `AgentBadge` | Agent attribution pill with coloured dot |
| `AlertCard` | Severity alert card (critical/high/medium/low/info/success) |
| `SectionHeader` | Section heading with icon, badge, divider, actions slot |
| `EmptyState` | Empty state with why/how/next-steps/related-links |
| `ErrorState` | Error state (network/permission/unavailable/offline/unknown) with retry + diagnostics link |
| `LoadingSkeleton` | `KpiCardSkeleton`, `CardSkeleton`, `TableSkeleton` — shimmer animation (`aq-skeleton-shimmer`) |
| `RecommendationCard` | Advisory recommendation with priority accent bar |
| `HealthCard` | Health/system-status card with score |
| `StatCard` | Stat card with change indicator and trend icons |
| `SummaryCard` | Narrative summary card with keyword highlighting |
| `DataTable` | Full data table: search, sort, pagination, column chooser, CSV export, `aria-sort` |
| `index.ts` | Barrel export for all of the above |

### 3. PageHeader Applied
**`src/pages/TradingTimeline.tsx`** and **`src/pages/ExecutiveReports.tsx`** — inline headers replaced with `<PageHeader>` from the DS library.

### 4. Design System Gallery
**`src/pages/DesignSystem.tsx`**

Live showcase page at `/design-system` (Operations Agent nav):
- Colour swatches (agent colours, chart palette)
- Status/severity badge grid
- Agent badge samples
- KPI card variants (score + P&L)
- Metric tiles
- Stat cards (positive/negative/neutral)
- Health cards
- Alert cards (all severities)
- Recommendation cards
- Summary cards
- Section headers
- Empty and error state variants
- Loading skeleton toggle
- DataTable with sample trade data
- Full design token reference table

---

## Architecture Decisions

- **No hard-coded hex strings in component files** — all colours from `designTokens.ts`.
- **Agent colours in `designTokens.ts` mirror `AgentConfig.ts`** — maintained in sync manually; no circular import.
- **`PageHeader` owns `HelpPanel`** — callers pass `helpTitle`, `faqs[]`, `relatedPages[]`; no separate wiring needed.
- **Skeleton animation** named `aq-skeleton-shimmer` (prefixed to avoid collision with the existing `shimmer` keyframe in `index.css`).
- **Generic-JSX syntax `<Component<T>>` rejected by Vite/Babel** — always drop explicit type parameters and rely on inference. TypeScript accepts it; Babel does not.

---

## TypeScript

`pnpm exec tsc --noEmit` — **0 errors**.

---

## Screenshots (2 Aug 2026)

| Page | Result |
|---|---|
| `/design-system` | ✅ Renders — colour swatches, all component specimens, token reference table |
| `/trading-timeline` | ✅ PageHeader with Advisory only / Read-only / Live badges; 9-tab bar below |
| `/executive-reports` | ✅ PageHeader with Save Report action; KPI score strip; report list + AI Insights |
