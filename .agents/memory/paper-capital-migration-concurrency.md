---
name: Paper-capital migration concurrency
description: Why a paper-capital rebase and automatic entry admission must share one PostgreSQL advisory gate.
---

A paper-capital migration must serialize with automatic OPEN-entry admission on one PostgreSQL advisory gate. Entry admission must re-read the confirmed auto-entry state while holding that gate immediately before its authoritative ledger insert, and must fail closed if PostgreSQL is unavailable.

Any sizing override must also recompute its final cash, stock, sector, portfolio, risk, absolute, and whole-share constraints from authoritative ledger state while holding this same gate. Gate-time snapshots are advisory only; another committed entry may have consumed their apparent capacity.

**Why:** A ledger table lock alone only makes a concurrent INSERT wait. An entry that passed eligibility before migration can resume after the migration commits and create an OPEN row against the rebased capital unless settings are rechecked after the wait. Likewise, concurrent candidates can each pass against one stale portfolio snapshot and cumulatively breach exposure limits unless final sizing is recomputed at admission.

**How to apply:** For any capital reset, ledger rebase, sizing override, or entry-admission change, test both lock orderings with two database sessions. Also test sequential/concurrent candidates that contend for the same cap: the later admission must resize from current committed exposure or fail closed.