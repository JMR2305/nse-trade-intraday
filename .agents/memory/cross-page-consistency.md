---
name: Cross-page consistency via canonical scan sync
description: How derived caches stay consistent with the canonical scan, and the false-green pitfall in parity checkers
---

# Rule
All pages must read values derived from the single canonical scan. Derived caches must never independently recalculate SL/target/RR/confidence/recommendations — they get overlaid from the canonical scan right after any scan or cache regeneration, with recommendation vocabularies normalized through an explicit action→decision map.

**Why:** Independent recalculation in the intelligence layer produced dozens of hard mismatches across pages (different SL/targets for the same symbol), destroying trust in the research output.

**How to apply:** Any new derived cache or page-facing dataset must be added to the sync overlay and to the consistency checker, and must carry the canonical scan_id per item.

# False-green pitfall
A parity checker that skips comparisons when a field is missing (e.g. `if item.get("scan_id"): compare(...)`) can report PASS without proving anything. Required parity fields (scan_id, decision/status) must treat *absence* as a hard mismatch. Regression tests should tamper a cache (remove the field) and assert the checker flags it.
