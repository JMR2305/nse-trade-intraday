---
name: Cross-process alert dedup in the KV store
description: Concurrency decision — exactly-once scheduler alerts need atomic claims and one shared lock for all file-backed KV writes.
---

- **Rule:** never dedup scheduler notifications with kv_get→kv_set — concurrent Autoscale ticks double-fire, and a "last signature" key re-alerts on A→B→A. Use an atomic first-claimant-wins claim keyed by incident identity (day + shortfall signature).
- **Why:** duplicate CRITICAL alerts also mean duplicate operator emails; a review round rejected the read-then-write version twice for exactly these races.
- **How to apply:** every mutation of the KV fallback file must hold the same exclusive lock — a single unlocked kv_set can erase a claim another process just made. When a one-time "recovered" follow-up must re-arm per incident, claim `resolved:<alert-claim-key>`.
