---
name: Pre-open final-proof window
description: Phase-aware rule for NSE pre-open freeze certification.
---

Freeze authority is a naturally scheduled collection captured from 09:08:00
inclusive through 09:12:00 exclusive (Asia/Kolkata), with exact durable
snapshot/outcome parity and each row live at ingestion. Manual, cross-day,
malformed, future, mixed-batch, stale, or out-of-window evidence blocks
freeze.

**Why:** NSE order collection has a system-driven random close between the
seventh and eighth minute, followed by matching and a silent transition. A
legitimate auction timestamp can be static after collection closes; continuing
collection into that interval can replace a valid proof batch with rows that
correctly fail the normal five-minute ingestion freshness test.

**How to apply:** Preserve the strict `age < 300 seconds` rule when collecting
data. Stop automatic collection before the matching interval and freeze the
same approved batch at 09:15 rather than re-evaluating its timestamp against
the freeze clock or accepting arbitrary historical evidence.