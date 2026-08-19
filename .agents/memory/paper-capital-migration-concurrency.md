---
name: Paper-capital migration concurrency
description: Why a paper-capital rebase and automatic entry admission must share one PostgreSQL advisory gate.
---

A paper-capital migration must serialize with automatic OPEN-entry admission on one PostgreSQL advisory gate. Entry admission must re-read the confirmed auto-entry state while holding that gate immediately before its authoritative ledger insert, and must fail closed if PostgreSQL is unavailable.

**Why:** A ledger table lock alone only makes a concurrent INSERT wait. An entry that passed eligibility before migration can resume after the migration commits and create an OPEN row against the rebased capital unless settings are rechecked after the wait.

**How to apply:** For any capital reset, ledger rebase, or entry-admission change, test both lock orderings with two database sessions: entry first must make migration observe and block on the row; migration first must make the waiting entry observe the paused state and insert nothing.