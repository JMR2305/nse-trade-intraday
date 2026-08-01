---
name: Phase 9.2 Multi-Agent Workspace
description: Architecture of the agent-based navigation redesign — files, colour map, localStorage keys, and extension points.
---

## Rule
Phase 9.2 is navigation/layout only. AgentConfig.ts is the single source of truth for agent ↔ page mapping. Never duplicate that data elsewhere.

## Files
- `AgentConfig.ts` — AGENTS array, ALL_PAGES flat list, getAgentForPath(), searchItems()
- `QuickSwitcher.tsx` — Ctrl+K modal, records recent pages in localStorage
- `AppLayout.tsx` — imports both; AgentGroup sub-component renders collapsible groups

## Agent colour map
Blue · Green · Purple · Orange · Red · Amber · Indigo · Teal · Cyan · Grey (in agent order 1–10)

## localStorage keys
- `apexquant_favourites` — string[] of starred hrefs
- `apexquant_agents_expanded` — string[] of expanded agent ids
- `apexquant_recent_pages` — last 8 { href, label, agentColor }

## Extension points
- AgentContextBar in AppLayout already has the shell for showing agent health — just add a useQuery call keyed by activeAgent.id when real-time status is available
- Add new `SearchItem` kinds to QuickSwitcher (symbols, alerts, watchlists) by extending searchItems() in AgentConfig.ts
- ALL_PAGES export gives a programmatic sitemap for breadcrumbs or onboarding tours

**Why:** Keeping all agent data in one file (AgentConfig.ts) means adding/renaming/recolouring agents never requires touching AppLayout or QuickSwitcher.
