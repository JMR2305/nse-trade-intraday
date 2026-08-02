---
name: Phase 9.5 Trading Timeline
description: Architecture decisions for the Trading Day Timeline page — event model, milestone dedup, data sources.
---

## Rule
Milestone markers in the timeline feed must use a `Set<string>` (`insertedMilestones`) to track which milestones have already been rendered. Using only `lastTime < m.time` is insufficient because multiple events can share the same `timeLabel`, triggering the same milestone repeatedly and producing duplicate React keys.

**Why:** The first implementation compared `lastTime < m.time && t <= m.time` — this inserts the same milestone once per event at that timestamp, generating React key collision warnings and duplicate UI elements.

**How to apply:** Any time-ordered feed that injects synthetic dividers must guard each divider with a Set, not just a sliding-window string compare.

## Data Sources
- `command-center/timeline` → scan + notification events `{time, ts_iso, event, category, status}`
- `command-center/alerts` → `{alerts: [{id, severity, category, title, body, timestamp}]}`
- `copilot/alerts` → AI signals `{alerts, sections}`
- `phase20/positions` → paper trades as portfolio events

All normalised into a single `TimelineEvent` model client-side via `useMemo`.

## localStorage Keys
- `apexquant_timeline_annotations` — array of Annotation objects
- `apexquant_timeline_checklist` — array of ChecklistItem objects with done state

## 15 Event Categories
Market · Research · AI · Strategy · Risk · Portfolio · Execution · Learning · Operations · Security · Performance · Deployment · System · Scan · Platform

## 10 IST Session Milestones
08:00 · 08:30 · 08:45 · 08:50 · 09:00 · 09:08 · 09:15 (open) · 15:30 (close) · 15:45 · 16:00
