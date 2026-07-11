---
name: Analyst reasoning layer invariants
description: Rules the v2.3 analyst reasoning / decision invalidation layer must always satisfy
---

The analyst layer (sections A–D, decision_state, conflicts, summary) must remain:

- **Deterministic:** same decision + item + regime + `now` always produces identical output; time comes from an injectable `now` parameter, never implicit clock reads inside text builders.
- **Single-source attributed:** section B (historical assessment) uses similarity-evidence stats only — pattern-knowledge numbers must never appear there. Every confidence adjustment named in section C traces to exactly one evidence source; pattern knowledge is descriptive-only.
- **Non-causal:** generated text may report associations ("associated factors — probable contributors, not proven causes") but never causal or predictive claims ("will rise", "proves", "caused").
- **Fail-visible:** the merge into decisions is wrapped in try/except with an explicit degraded fallback dict (DATA_LIMITED-style), never a silent omission.
- **EXIT validity:** EXIT decisions always have `valid_until=null` with note "Valid until the position is closed or superseded", regardless of position state.

**Why:** the product promise to a non-technical user is auditable, honest reasoning; leaking a second data source into a section or adding predictive language silently breaks that trust and its tests.

**How to apply:** any change to analyst text builders or new evidence sources must preserve these rules; tests in `test_analyst_reasoning.py` assert them.
