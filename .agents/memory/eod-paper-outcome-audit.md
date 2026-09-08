---
name: EOD paper outcome audit
description: Safety rules for auditable paper-position outcomes after market close.
---

Every paper position found open during the EOD close window must end in either
an acknowledged terminal ledger state or one durable, per-trade blocked outcome.
An order result alone is not a close: the ledger must confirm the written
terminal state before the scheduler accepts it as closed.

**Why:** a failed ledger write after a paper sell can otherwise be reported as
closed while the canonical ledger remains OPEN. Re-running all EOD work after
an event-write failure can also issue another sell for positions already closed
or visibly blocked.

**How to apply:** retain the full safety ledger (do not apply dashboard/history
caps to it); deduplicate blocked events by trade and IST session. Persist only
the unresolved audit records for retry, and make the retry path write those
records without re-running price resolution or order execution.