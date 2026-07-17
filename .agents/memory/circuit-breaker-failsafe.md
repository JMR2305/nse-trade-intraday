---
name: Entry circuit breaker fail-safe
description: Corrupted/unreadable safety state must block entries, never auto-clear
---

Rule: any safety-critical persisted state (e.g. the paper-entry circuit
breaker kv) that is missing-vs-corrupted must be distinguished: missing →
default clear, but corrupted/unreadable (wrong type, read error) → treated as
TRIPPED/blocking, and the stored value must never be overwritten from an
unreadable read.

**Why:** normalizing corrupted state to `{}` silently reads as "not tripped"
and re-enables entries after a storage fault — architect review flagged this
as a blocking safety gap.

**How to apply:** in state readers return an explicit fail-safe blocking
state (`tripped: True, unreadable: True`); gates/executors treat it like a
trip; only a manual-review resume writes a fresh clear state. The breaker
never auto-resumes even after metrics recover.

Also: gate test `provider_zerodha` failures in dev are environmental (no live
Kite session in the latest snapshot) — verify against HEAD before blaming a
diff.
