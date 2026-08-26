# Task 940 — Phase 5A 3/23 root-cause report

**Investigation date:** 2026-08-26  
**Affected immutable session:** `preopen-2026-08-26-ccb21a`  
**Verdict:** **A — provider/filter scope defect**, with a secondary **F — per-symbol evidence-accounting gap**.

## Evidence-led conclusion

The pre-open collector resolved the 23-symbol `CUSTOM_LOW_PRICE_SECTOR`
universe, but the NSE provider source used a hard-coded request:

```text
/api/market-data-pre-open?key=NIFTY
```

That request is limited to the NIFTY feed. It cannot be a complete source for
an arbitrary custom universe. The preserved session produced three snapshot
rows (`COALINDIA`, `GAIL`, and `NTPC`) and 20 expected symbols had no snapshot.
Those three symbols are consistent with the limited NIFTY source scope.

The collector and persistence layer correctly recorded the aggregate failure:
`provider_collected_count=3`, `persisted_count=3`, `expected_count=23`,
`failed_count=20`, no verified batch, and no frozen batch. It did **not** create
fake zero-price rows or bypass the freeze gate.

## Historical evidence boundary

The historical collection did not persist:

- the exact provider query key/request URL;
- the raw NSE response count or raw symbol set;
- a per-symbol request/response/normalization outcome; or
- a reason distinguishing provider omission from normalization rejection.

Therefore, the historical raw response cannot be reconstructed honestly. The
source-level `NIFTY` scope is the proven defect and the 3/23 result is
consistent with it, but the exact historical raw row count is **not proven**.
The symbol matrix records this as `NOT_DURABLY_RECORDED`, rather than assuming
missing symbols were absent from NSE.

## Rejected alternatives

| Candidate | Finding |
|---|---|
| Active-universe resolution failure | Rejected. The custom universe was resolved as 23 valid symbols. |
| Kite mapping failure | Rejected as the primary cause. Post-open audit showed 23/23 valid mappings; the NSE source path does not depend on Kite mapping to filter rows. |
| Persistence-only failure | Rejected. Provider-collected and persisted counts were both 3, so the divergence occurred before persistence. |
| Freeze/certification bypass | Rejected. No verified or frozen batch was created. |
| Historical timing-only failure | Not proven. The missing raw provider evidence prevents ruling this in or out as a contributing condition. |

## Minimal correction

1. Force NSE `key=ALL` for this custom-universe collection path. A restricted
   index key cannot override it.
2. Scope the in-memory provider cache by that query key.
3. Persist one immutable outcome for every expected symbol in every collection
   batch. Outcomes are metadata, not snapshot substitutes.
4. Keep `MATCH` and freeze dependent on complete, explicitly proven
   non-stale, valid live snapshot coverage. Missing liveness metadata blocks.
   Explicit no-data or provider-failure outcomes improve observability but do
   **not** make a partial batch freezeable.

## Safety result

The August 26 session remains untouched. No retry, replay, backfill, mutation,
or freeze action was performed against it. Automatic paper entry, bootstrap,
controlled execution, and live orders remain outside this change.

See:

- `TASK_940_SYMBOL_OUTCOME_MATRIX.csv`
- `TASK_940_PROVIDER_ELIGIBILITY_CONTRACT.md`
- `TASK_940_FIX_AND_TEST_REPORT.md`
- `TASK_940_NEXT_NATURAL_SESSION_GATE.md`