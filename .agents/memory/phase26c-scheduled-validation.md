---
name: Phase 26C scheduled session validation
description: Cadence design for running the heavy 26C suites automatically at session milestones
---

Rule: the 26C suites (recovery/performance/quality) run from the phase20 scheduler tick at two milestones — "open" (OPEN state, 30 min post-09:15 grace) and "close" (CLOSED state) — with **one kv_claim_once per suite per milestone**, not one shared claim.

**Why:** a shared milestone claim permanently skips a suite that errored while the others passed (code review rejected that design). Per-suite claims let an errored suite release its own claim and retry next tick while completed suites stay deduplicated.

**How to apply:** any new scheduled multi-part validation should claim per part; ERROR releases the claim, FAIL keeps it (it completed). The suite runners swallow persistence failures into `persist_error` while returning a normal verdict — a scheduled runner must treat `persist_error` as ERROR or the day is claimed with nothing persisted. ERROR notifications need their own per-milestone claim key or retries spam operators every tick. FAIL/ERROR raise `VALIDATION_FAILED` (in email_alerts.EMAIL_KINDS). Close milestone triggers at POST_CLOSE (with CLOSED catch-up) so results exist before the 26D daily report. Only ONE automation path may exist — a parallel-merged duplicate (`phase26c_auto`) caused double daily runs and was removed; a wiring test guards against reintroduction.
