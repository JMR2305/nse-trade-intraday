---
name: Append-only evidence datasets
description: Write-once enforcement and evaluation-payload provenance for research evidence tables (Phase 22 pattern).
---

Rule 1: Write-once must be enforced in the persistence layer, not just in
application memory. For outcome columns use per-column
`col = COALESCE(col, %s)` plus a `WHERE ... AND outcome_complete IS NOT TRUE`
guard; mirror the same null-guard in any file fallback. Only genuinely
cumulative fields (observations, MAE/MFE) may be re-written until the outcome
is complete.
**Why:** concurrent scheduler ticks / API-triggered updates raced and could
overwrite already-recorded horizon returns, breaking the audit guarantee.
**How to apply:** any table advertised as append-only or write-once.

Rule 2: Evidence rows must be built from the EXACT evaluation payload the
executor consumed (pass it through in the return value), never from a second
`evaluate_entries()` call — context can drift between calls and the recorded
decision set would no longer match the trades actually created.
