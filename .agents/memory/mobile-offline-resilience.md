---
name: Mobile offline resilience
description: How the trading mobile app survives a slow/offline API server
---
Screens must never dead-end on "Could not load" when the API server is cold-starting.

**Rule:** wrap each screen's query data in `useOfflineSnapshot(key, data, isError, dataUpdatedAt)` from `lib/offlineCache.ts`. It persists the last successful payload to AsyncStorage and, on error, returns it with the capture timestamp so the UI can show a `StaleBanner` ("data from X ago"). Full-screen error is reserved for error + no snapshot at all.

**Why:** the Python scanner backend cold-starts slowly; traders need last-known data plus its age, not a blank error.

**How to apply:** any new mobile screen fetching server data should follow the same pattern: skeleton shimmer (`components/Skeleton.tsx`) while loading with no data, `StaleBanner` when showing snapshot data, offline-specific error copy only when nothing cached exists. Snapshot keys are per-dataset strings (e.g. "portfolio", "signals").
