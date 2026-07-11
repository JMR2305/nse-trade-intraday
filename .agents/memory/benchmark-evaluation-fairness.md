---
name: Benchmark evaluation fairness
description: Rules for fair self-evaluation of allocation decisions vs benchmarks in the learning loop.
---

Rule: when persisting a decision for later benchmark evaluation, store the FULL
qualifying candidate set — never a list that was truncated for UI display. And
measure returns from entry close to the first close ON/AFTER `created_at +
horizon_days`, deferring (return None) if that horizon close does not exist yet.

**Why:** A UI-capped skipped list silently shrank the equal-weight benchmark,
biasing alpha; and "latest close at evaluation time" stretched the window when
the evaluator ran late, making horizon labels (e.g. 7d) misleading. Architect
review flagged both as blocking.

**How to apply:** Keep display truncation only at the API-response layer (e.g.
a private untruncated field consumed by persistence and popped before the
payload is returned). Any `_symbol_return`-style helper must take an explicit
horizon and defer rather than approximate.
