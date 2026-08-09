# Phase 27E — Verification

Date: 2026-08-09 (weekend; stale-scan banner is environmental)

## 1. Canonical-source map (duplicate-source audit)

| Metric | Source used | Duplicates avoided |
|---|---|---|
| Per-stage in/out/rejected/pending | `replay_engine.build_replay()` stages | did NOT recount from events or scan caches |
| Stage timing | `pipeline_events.query_events(scan_id=…)` gaps | same gap definition as `stage_summary`; no second timing pipeline |
| Rejection reasons | event payload keys (`error` / `failed_gates` / `reasons`) | codes verbatim; no re-derivation from scan snapshot |
| Decision splits | canonical snapshot `recommendations[].final_action` | omitted (flagged) when snapshot scan ≠ replay scan |
| Session list | `get_replay_sessions()` | no bespoke session table |
| Performance / time-of-day | existing `/paper-analytics/*` endpoints, client-side | zero recomputation in 27E |

Bounded fetches only: one ≤2000-event fetch for the current scan; ≤1000 per
scan for the 5-scan trend window. No full-event-history queries.

## 2. Unit tests
```
cd artifacts/api-server/src/python
python -m pytest test_phase27_operator_analytics.py -q   → 21 passed
```
Covers: rejected-event vs reason-occurrence accounting (multi-gate events), evidence states (SOURCE_UNAVAILABLE / PARTIAL / VERIFIED_EMPTY), funnel conversion math, empty/partial telemetry (insufficient flags,
unparseable timestamps), rejection determinism, per-event-type reason
extraction, risk intervention no-evidence handling, scan isolation
(different-scan snapshot omitted; trends keyed per scan_id), hermetic
end-to-end report, replay-failure survival.

## 3. Typecheck
`pnpm --filter trading-dashboard exec tsc --noEmit` → clean.

## 4. Live endpoint
`GET /api/operator-analytics/report` → 200; `ok:true`,
scan `4915c8df904f`, 341 events, 10 funnel stages, all 4 sources available/untruncated, 2 rejected events = 2 reason occurrences
(real yfinance "no data" errors for LTIM/TATAMOTORS), decisions
IGNORE:15/WATCH:27/BUY:6 matching the canonical snapshot
(WATCH 27 / IGNORE 17 / BUY 5 / STRONG BUY 1), risk 48 approved / 0 blocked,
5 trend points with per-point evidence (current OK, older intel scans VERIFIED_EMPTY). Second call served from the 30s cache.

## 5. Browser
`/operator-analytics` screenshotted at 1440px: all seven cards render with
source labels; INSUFFICIENT TELEMETRY badges show on stages without gap
samples; NO EVENTS FOR SCAN badge on portfolio pre-check (no auto entries
this scan); rejection rows expand to symbols + event ids; current scan
highlighted in trends + session summary. Timing rows showing 0ms with 48
samples are honest telemetry (events for a symbol are batch-emitted with
identical timestamps), not fabrication.

## 6. Safety
Module is read-only end to end: no writes to any store, no order/portfolio/
strategy/risk mutation paths imported. Advisory labels on API payload and page.

## 7. Architect review
An architect review flagged four issues, all fixed and re-verified:
1. Multi-reason rejection events were double-counted in the total — now
   rejected EVENTS and reason OCCURRENCES are separate fields, % labelled as
   share of occurrences.
2. Bounded fetches could silently truncate — `truncated` flag now returned
   and surfaced as a PARTIAL evidence state + page banner.
3. Source read failures were rendered as empty data — per-source
   availability now propagates (`sources` map) and the UI distinguishes
   SOURCE UNAVAILABLE / PARTIAL / VERIFIED EMPTY.
4. Synthetic `demo` replay sessions could enter session summary/trends —
   now excluded at the reader.
