---
name: Phase 9.4 Personalized Workspace
description: Widget-based customizable workspace with drag-drop grid, profile CRUD, KPI bar, focus mode, smart dashboard, session memory
---

## Architecture

**New package:** `@dnd-kit/core` + `@dnd-kit/sortable` + `@dnd-kit/utilities` installed in `artifacts/trading-dashboard`.

**Files created (workspace system):**
- `src/components/workspace/WorkspaceManager.ts` — all state (profiles CRUD, widget layouts, KPI bar, focus mode, notif prefs, session, undo stack, templates)
- `src/components/workspace/WidgetRegistry.ts` — 21 widget definitions + KPI registry
- `src/components/workspace/SmartDashboard.ts` — pure time-of-day IST session logic (pre-open/market-open/market-hours/closing/after-market/off-hours)
- `src/components/workspace/DashboardGrid.tsx` — @dnd-kit sortable grid; `isWidgetVisibleInFocusMode` imported from WorkspaceManager
- `src/components/workspace/KpiBar.tsx` — 8-12 favourite KPIs, picker dropdown, edit mode
- `src/components/workspace/FocusModeBar.tsx` — FocusModeBar + FocusModeBanner
- `src/components/workspace/WorkspaceSettingsPanel.tsx` — 7-tab drawer (Profiles, Widgets, KPI Bar, Focus, Notifications, Templates, Multi-Monitor)
- `src/components/workspace/widgets/WidgetShell.tsx` — common wrapper with drag handle, collapse, pin, resize, settings dropdown
- 21 widget components in `src/components/workspace/widgets/`
- `src/pages/Workspace.tsx` — main page

**Modified files:**
- `src/App.tsx` — import + Route `/workspace`
- `src/components/layout/AgentConfig.ts` — `/workspace` → "My Workspace" added to Operations agent pages

## Key decisions

**Why `getProfile`/`setProfile` stay in WorkspaceStore.ts:** WorkspaceManager.ts has its own profile management (CRUD, custom profiles) but the nav's active profile still uses WorkspaceStore's 5-enum type for sidebar/QuickSwitcher compatibility. `Workspace.tsx` imports `getProfile`/`setProfile` from `WorkspaceStore`.

**Widget 404s are expected:** Several widget endpoints (`command-center/risk`, `command-center/system`, `portfolio-performance/summary`, `preopen/session`) return 404 — these are Phase 9.1 endpoints not yet registered as sub-paths. Widgets show "unavailable" gracefully. Working endpoints: `phase20/positions`, `command-center/alerts`, `command-center/timeline`, `preopen/watchlist`.

**Grid layout:** CSS Grid with 12 columns; widget sizes map to `col-span-N` via Tailwind classes (`sm`=3, `md`=4, `lg`=6, `xl`=8, `full`=12). Row height uses `min-h-[Npx]` class. @dnd-kit sorts by instanceId; `rectSortingStrategy` handles grid layout.

**Focus mode filtering:** Done at grid level in DashboardGrid.tsx using `isWidgetVisibleInFocusMode(widgetId, focusMode)` imported from WorkspaceManager. `none` mode shows all.

**localStorage keys (new in Phase 9.4):**
- `apexquant_widget_layouts` — layouts per profileId
- `apexquant_custom_profiles` — user-created profiles
- `apexquant_kpi_bar` — KPI bar config
- `apexquant_focus_mode` — active focus mode
- `apexquant_notif_prefs` — notification preferences
- `apexquant_session` — session memory
- `apexquant_layout_undo` — undo stack (max 10 per profile)
- `apexquant_quick_notes` — quick notes widget content

**Zero business logic changes.** No API, no DB, no trading engine changes.
