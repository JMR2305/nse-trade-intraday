---
name: Phase 0B post-cutoff entry root cause
description: Why two paper trades were admitted after the 15:15 IST cutoff on 2026-08-20, and why same-day EOD failed to close them.
---

## The rule

Any future work on `_manage_paper()`, `run_auto_entries()`, `run_bootstrap_auto_entry()`, or `_insert_row()` must treat the PAPER_ENTRY_CUTOFF guard as a two-layer requirement: one check INSIDE `_insert_row()` (current code), and one check at the TOP of `_manage_paper()` before either the auto or bootstrap entry path is called.

**Why:** The exits-before-entries design of `_manage_paper()` is an architectural race: exits can clear the `no_open_duplicate` gate, and entries immediately re-use the cleared gate on the same tick. Without a pre-entry window check in `_manage_paper()` itself, a post-cutoff tick will still reach `_insert_row()` with a now-eligible candidate.

**How to apply:** Before `run_auto_entries()` and `run_bootstrap_auto_entry()` are called in `_manage_paper()`, call `automatic_paper_entry_status()` and short-circuit if `allowed=False`. This is in addition to, not instead of, the guards inside `_insert_row()`.

## Root cause chain (2026-08-20 incident)

1. Scan `052a7098b14d` completed at 14:49:55 IST. DRREDDY signal: eligible but blocked by `no_open_duplicate` (P20-cfd2e587aa was OPEN).
2. At ~15:24:01 IST: `manage_open_positions()` closed P20-cfd2e587aa via MARKET_CLOSE_EXIT on a scheduler tick. IST timezone was working correctly (proved by the 15:24 exit time).
3. On the SAME `_manage_paper()` call: `run_auto_entries()` ran, DRREDDY now passed `no_open_duplicate`, and `_insert_row()` was called. **The deployed production code at 15:25 IST lacked the `PAPER_ENTRY_CUTOFF` guard** — entries were admitted at 15:25:10 IST (DRREDDY, AUTO) and 15:26:22 IST (TRENT, BOOTSTRAP_AUTO), both using the stale 14:49 IST snapshot.
4. Both trades carry `config_hash=39dc33e1e29440e9`. The before-state config was `7d842d4e59648fe7`. Settings (and likely code) changed between entry time and next-day capture — consistent with the cutoff guard being added in the same code deployment.

## EOD miss chain

- Server shut down at ~15:26 IST (immediately after the entries — likely a redeployment).
- No POST_CLOSE tick ran (15:30–16:00 IST). `eod_squareoff:2026-08-20` KV claim never set.
- Cold-start on 2026-08-21 00:05 IST detected unclaimed EOD key and force-closed both trades at fill price (`realized_pnl=0`, `exit_price_source=null` in EOD summary due to observability gap).

## Required fixes (not yet implemented as of 2026-08-21)

1. `_manage_paper()` pre-entry window guard (short-circuit after exits if cutoff passed)
2. Stale signal rejection: reject entries from snapshots > 20 min old
3. Dedicated 15:20 and 15:30 EOD jobs independent of scan cadence
4. `build_id` + `entry_market_state` stored in every ledger row
5. EOD exit price from yfinance prev-session close (not fill price) when no live data
