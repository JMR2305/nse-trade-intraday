---
name: Backtest scheduler cold-start fix
description: bt_queue_tick_cmd.py replaces main.py for scheduler ticks; scan time is the irreducible floor; perf telemetry now stored in metrics.
---

## Rule
The backtest queue scheduler (`backtestScheduler.ts`) must spawn `bt_queue_tick_cmd.py`, never `main.py bt_queue_tick`.

**Why:** `main.py` imports pandas (~9s), yfinance (~2.6s), sqlalchemy (~1.5s) at top level regardless of the command. On Autoscale cold instances this totals 25–35s — past the 30s `TICK_TIMEOUT_MS` — causing the scheduler to SIGKILL the Python process before a single DB query runs. `bt_queue_tick_cmd.py` imports only `backtest_portfolio` (psycopg2-only), cold-starting in ~116ms.

**How to apply:** Any new lightweight command added to `main.py` that only needs DB access (not pandas/yfinance) should get a dedicated `*_cmd.py` entry point following the same pattern. Workers spawned by the scheduler still use `main.py backtest_exec` (the full entry point).

## Scan time floor (5-symbol 15m 30-day)
- `_scan_one` per symbol takes ~134ms (indicators + research + MI + strategy + risk + AI decision)
- 551 ticks × 5 symbols = 2,755 scans × 134ms = **~370s irreducible floor**
- DB writes (after event-buffering fix): ~11s total (2.8%)
- Event flush: ~10s total (2.6%)
- Total typical wall time: **~397s (~6.6 min)** — not reducible below ~370s without parallelising `_scan_one` across symbols

## Performance telemetry
Every completed run stores `metrics["perf"]` with: `total_runtime_s`, `data_phase_s`, `replay_phase_s`, `ticks_per_second`, `avg_ms_per_tick`, `p95_ms_per_tick`, `max_ms_per_tick`, `scan_ms_total`, `event_ms_total`, `db_ms_total`, `progress_updates`.

Queue timeout count / worker restart count are scheduler-level (not per-run) — visible via `GET /api/backtest/scheduler/status` (`consecutiveFailures`, `lastError`).

## Production Neon latency pattern
Production Neon Autoscale adds 1–5s per `psycopg2.connect()` on a cold wake-up. Old code: 5–6 connections/tick → 15–18s/tick in production. After event-buffering fix: ~2 connections/tick → ~2–4s/tick in production.
