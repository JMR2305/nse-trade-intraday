---
name: EOD square-off KV claim + import bug
description: kv_claim_once writes atomically before any logic runs — a crash after the claim silently consumes the daily retry slot; and phase20_scheduler had a bad import that caused exactly this.
---

# EOD square-off: KV claim consumed before logic runs

## The rule
`kv_claim_once` in the CLOSED-state handler writes the claim **before** importing the close modules. If any import fails, the claim is consumed and the close never runs. The scheduler's outer `except` records `{"error": ...}` silently — no pipeline events, no notifications.

**Why:** This is what happened on 2026-08-18 when `from phase20_settings import load_settings` raised `ModuleNotFoundError`. The KV claim for `eod_squareoff:2026-08-18` was taken at 17:12:31 IST. DRREDDY (P20-3468fb2a24) was never closed by the normal path.

**How to apply:** Any import inside a `kv_claim_once` block must be verified to actually exist. Put imports before the claim, or release the claim on ImportError/AttributeError (setup errors, not business failures).

## Recovery pattern
A bypass endpoint was added: `POST /api/phase20/force-eod-close` → `phase20_force_eod_close_now` in `main.py`. It calls `eod_force_close_open_positions(get_settings())` directly, skipping the KV guard. Use this whenever today's claim is consumed but the close did not run.

## runPython stdout noise
`paper_trader` prints structured log lines to stdout (e.g. `position_closed`). `runPython` used `JSON.parse(stdout.trim())` which fails on multi-line output. Fixed in both `trading.ts` and `scanScheduler.ts` to scan for the **last valid JSON line** from the end of stdout. The Python regex replacement used by the dev session wrote a literal newline instead of `\n` — always verify TypeScript string literals after regex-based bulk edits.

## The correct import (confirmed)
```python
# CORRECT — use this everywhere in phase20_scheduler.py
from phase20_store import get_settings as _ls

# WRONG — module does not exist
from phase20_settings import load_settings as _ls
```
