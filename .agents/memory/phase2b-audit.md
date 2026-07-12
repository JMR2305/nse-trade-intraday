---
name: Phase 2B strategy audit conventions
description: Durable rules for the analysis-only strategy audit bolted onto walk-forward validation.
---

**Rule 1 — analysis only, explicit failure.** The strategy audit runs after all main-run aggregation, wrapped so a failure stores an explicit `{"error": ...}` in the payload instead of crashing or silently dropping the section. Never feed audit output back into ranking or execution.

**Rule 2 — two A–x namespaces.** The main run's internal variants are A–E (E = strict gates). The audit's model-comparison table is A–F per the Phase 2B spec (E = best variants, F = variants + regime gate + cash). They are separate namespaces; the audit reuses the main run's A–D metrics rather than recomputing them.

**Rule 3 — aggregates-only payload.** Audit trades carry internal `_spec`/`snapshot` keys (including a non-serializable signal-date set) that must never be emitted; tests assert `json.dumps` works and no `_spec`/`snapshot` strings appear in the payload.

**Rule 4 — isolate one factor per robustness check.** When re-walking exits for a robustness check (e.g. intrabar rule flip), pass through the original signal-exit dates so only the factor under test changes.
**Why:** an early version passed an empty signal set, so the "intrabar flip" check also silently removed signal exits, conflating two effects (caught in code review).

**How to apply:** any new audit-style replay or stress check should perturb exactly one input and keep every other exit pathway identical to baseline.
