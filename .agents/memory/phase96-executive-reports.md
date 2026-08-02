---
name: Phase 9.6 Executive Reports
description: Architecture decisions for the Executive Reports & AI Briefings page — report types, KPI scores, data sources, known placeholders.
---

## Architecture
Pure frontend — 1 new file (`ExecutiveReports.tsx`), no new API endpoints, no new DB tables.

## Data Sources
- `command-center/summary` — regime, market status, platform health score
- `command-center/alerts` — alert events (severity, category, title)
- `copilot/alerts` — AI advisory signals
- `phase20/positions` — paper trade positions for P&L, win rate, portfolio metrics

All 4 queries share 30 s staleTime and are deduplicated by query key.

## 7 Report Types
morning · open · midday · close · eod · weekly · monthly

Each has: Executive Summary · Key Metrics · Highlights · Recommendations · Warnings · Next Steps

## KPI Score Placeholders
Security (70), Performance (75), and Deployment (80) scores are static placeholders.
**Why:** `security-center/summary`, `performance-center/summary`, and `deployment-center/summary` endpoints exist but their response shapes weren't verified for score fields. Replace with live queries once confirmed.
**How to apply:** When wiring real scores, add three `useQuery` calls for those endpoints and extract their score fields.

## Report Library
localStorage key: `apexquant_report_library` (max 100 entries).
Entries: `{id, type, label, generatedAt, starred}`.

## Weekly/Monthly Reports
These show current-session data only with an advisory note about multi-session storage.
Full weekly/monthly analytics require persistent multi-session storage (Phase 10+).
