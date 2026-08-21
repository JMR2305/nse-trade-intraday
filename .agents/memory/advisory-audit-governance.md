---
name: Advisory audit governance
description: Safety rule for append-only advisory bot evidence and supervisor approval.
---

Never treat a caller-provided supervisor verdict as authority to persist advisory evidence. Recompute the supervisor result from the exact subject outputs, read-only settings, and validated universe health immediately before any insert; prevalidate the complete batch before the first write.

**Why:** A forged but contract-valid stored approval can otherwise make a blocked universe or unsafe configuration appear approved in the immutable audit trail, even when no trade is executed.

**How to apply:** Any future advisory API, UI, job, or bulk-import path must supply the original read-only inputs to the persistence boundary. The storage layer must retain its table allow-list, advisory/paper-only checks, deterministic idempotency, and no update/delete interface.