---
name: Learning-data eligibility gate
description: Rule for what trade data the adaptive learning engine may learn from
---

**Rule:** A completed trade is `learn_eligible` only if verified live (yfinance) data backs the FULL lifecycle: the BUY prediction snapshot, the sell-time fetch, and the evaluation-time excursion-verification fetch. Any "mock" or "unknown" source anywhere → excluded (stored for transparency, never learned from).

**Why:** The v2 spec's hard invariant is "never learn from mock data". An architect review caught that gating on the BUY snapshot alone let a live-entry/mock-exit trade poison learning. Old backfilled trades whose sell source can't be verified are conservatively excluded — that is intended, not a bug.

**How to apply:** Any future change to trade evaluation or learning eligibility must preserve all three source checks and surface the offending source in `data_source` so the UI explains the exclusion.
