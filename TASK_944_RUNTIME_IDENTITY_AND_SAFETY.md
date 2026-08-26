# Task #944 — Runtime Identity and Safety

## Pre-publish production identity

The public deployment is healthy but is currently serving the source state
published before Task #941/#942:

| Field | Current production value |
|---|---|
| Environment | `production` |
| Git commit | `fa612a219c2ca2aa682e5af58b051e2da4425c16` |
| Build ID | `apexquant-fa612a219c2c` |
| Deployment ID | `0d018179-abe0-42c2-a554-dbb19d11341f` |
| Runtime identity endpoint | `/api/health/details` |
| Deployment health | successful build, public autoscale deployment |

The approved source candidate is:

```text
APPROVED_DEPLOY_COMMIT = 356da659ea636a1c39dc8a379bbb5947ce492ac7
EXPECTED_BUILD_ID      = apexquant-356da659ea63
```

Therefore the current pre-publish identity result is:

```text
DEPLOYMENT_IDENTITY = NOT_YET_MATCHED
```

This is expected before the controlled publish. It is a stop condition for
claiming final deployment success, not a source, safety, or schema failure.

## Production schema state

Production does not yet contain `preopen_collection_outcomes`; development
does. The publish-time schema diff is additive only and is documented in
`TASK_944_DEPLOYMENT_SCOPE_AND_TEST_REPORT.md`.

The table must be created by the Publish flow alongside the approved source
commit. No manual production DDL is permitted.

## Read-only production safety baseline

The following values were obtained without invoking a collection, scan,
execution, or setting mutation.

| Safety/control | Result |
|---|---|
| Active universe | `CUSTOM_LOW_PRICE_SECTOR` |
| Active universe count | 23 |
| Mappings/token coverage | 23 of 23 / 100% |
| Automatic paper entries | `false` |
| Automatic-entry confirmation timestamp | `null` |
| Bootstrap paper mode | `false` |
| Automatic paper exits | `true` |
| Paper mode | `true` |
| Portfolio activation status | `DISABLED` |
| Open positions | 0 |
| `EXIT_PENDING` positions | 0 |
| Portfolio health | `HEALTHY` |
| Unresolved portfolio discrepancies | 0 |
| Live broker order calls in observed ledger evidence | `false` |

The canonical portfolio snapshot reports:

```text
position_source = phase20_ledger
open_position_count = 0
equity_complete = true
paper_mode = true
status = DISABLED
```

The historical paper-trade ledger contains six `BUY` rows and six matching
`SELL` rows, representing six closed historical paper trades. No open or
exit-pending position is present.

## Pre-open historical safety baseline

The historical August 26 session remains:

```text
status                    = PARTIAL_COVERAGE
expected_count            = 23
persisted_count           = 3
verified_collection_batch = null
frozen_collection_batch   = null
```

It remains incomplete, uncertified evidence.

## Required post-publish read-only identity checks

After the user publishes the approved source commit, verify:

1. `environment = production`
2. `git_commit = 356da659ea636a1c39dc8a379bbb5947ce492ac7`
3. `build_id = apexquant-356da659ea63`
4. `deployment_id` is non-empty
5. `runtime_timestamp` is current for the new process
6. `preopen_collection_outcomes` exists in production
7. The source/runtime safety baseline above is unchanged
8. The historical August 26 session remains incomplete and untouched

Any identity mismatch is a stop condition.