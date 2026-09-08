# RTV-1G Deployed Commit Reconciliation

## Scope and safety boundary

This was a read-only reconciliation of the deployed source identity, Git
ancestry, source diff, schema safety, and production safety state. No publish,
token hydration, scan, universe update, portfolio update, database mutation,
or order placement was performed.

## Task 1 — Commit relationship

| Check | Result |
|---|---|
| Is `1142f07e` an ancestor of `4392f278`? | **YES** |
| Is `4392f278` a descendant of `1142f07e`? | **YES** |
| Number of commits between them | **1** |
| Branches containing `4392f278` | `replit-agent`, `rtv1-market-data-portfolio-truth`, and `gitsafe-backup/main` |
| Commit timestamp | `2026-08-23T21:49:22Z` |
| Commit subject | `Document root cause analysis of RTV 1F publish artifact mismatch` |
| Parent commit | `1142f07e5a616747bbfa60722b6d681f0b03c3c0` |

The deployed commit is a direct descendant of the previous approved candidate,
not a branch fork or unrelated source revision.

## Task 2 — Commit diff

Command equivalent:

```text
git diff --stat 1142f07e...4392f278
```

Result:

```text
RTV1F_PUBLISH_ARTIFACT_ROOT_CAUSE_REPORT.md                         | 168 +++++++++
attached_assets/Pasted-RTV-1F-PRODUCTION-PUBLISH-ARTIFACT-COMMIT-
MISMATCH-DIAG_1787521226240.txt                                    | 351 +++++++++++++++++++++
2 files changed, 519 insertions(+)
```

Complete changed-file list and classification:

| File | Classification | Assessment |
|---|---|---|
| `RTV1F_PUBLISH_ARTIFACT_ROOT_CAUSE_REPORT.md` | Report/evidence only | Documents the earlier identity-injection diagnosis and candidate build proof. No runtime behavior. |
| `attached_assets/Pasted-RTV-1F-PRODUCTION-PUBLISH-ARTIFACT-COMMIT-MISMATCH-DIAG_1787521226240.txt` | Report/evidence only | User-provided RTV-1F control input. No runtime behavior. |

No changed file is an unrelated feature, strategy change, trading behavior
change, universe change, portfolio change, or DB/destructive change.

## Task 3 — Intermediate commit review

There is one intermediate commit after `1142f07e` and up to and including the
deployed commit:

| SHA | Timestamp | Subject | Files changed | Purpose | Classification |
|---|---|---|---|---|---|
| `4392f278ae25562f168f970e2b694f8c3d249d5c` | `2026-08-23T21:49:22Z` | `Document root cause analysis of RTV 1F publish artifact mismatch` | The RTV-1F report and attached RTV-1F control record | Preserve the completed diagnosis and evidence | **SAFE — report/evidence only** |

The commit changes none of the following:

- strategy thresholds or signal logic;
- active universe membership;
- capital or historical ledger;
- automatic entry state or bootstrap state;
- broker order behavior;
- risk limits;
- destructive database schema; or
- production secrets.

## Task 4 — Required RTV-1E content

All required content is present in the deployed tree because the deployed
commit is a direct report-only descendant of the approved candidate.

| Requirement | Result | Evidence |
|---|---|---|
| Runtime identity fix | **PASS** | Runtime identity validates commit-derived production IDs and fails closed for other shapes. |
| Commit-derived build ID | **PASS** | API build derives `apexquant-<12-hex-sha>` from the exact source commit. |
| Non-destructive custom-universe schema contract | **PASS** | Python-managed canonical `CREATE TABLE IF NOT EXISTS` declares the contract; no runtime `ALTER TABLE` migration is used. |
| Protected instrument metadata columns | **PASS** | `custom_universe_master` is protected; canonical schema includes `instrument_token`, `instrument_exchange`, `instrument_tradingsymbol`, `instrument_cache_date`, and `instrument_mapping_at`. |
| Custom-universe token hydration support | **PASS** | Active custom-universe rows support token and instrument metadata hydration. |
| Current-universe readiness logic | **PASS** | Readiness is evaluated against the active universe, token coverage, quote provenance, freshness, and session state. |
| Canonical portfolio snapshot fix | **PASS** | Portfolio snapshot reads the phase20 ledger through the canonical portfolio path. |
| Synthetic/fallback fail-closed logic | **PASS** | Synthetic, stale, unavailable, unknown-provenance, or incomplete data cannot produce `trading_data_ready=true`. |

## Task 5 — Schema safety

The regenerated schema diff returned:

```json
{
  "statementsToExecute": [],
  "columnsToRemove": [],
  "tablesToRemove": [],
  "tablesToTruncate": [],
  "hasStructuralDataLoss": false,
  "hasDiff": false,
  "success": true
}
```

The following columns remain in the Python-managed custom-universe contract:

- `instrument_token`
- `instrument_exchange`
- `instrument_tradingsymbol`
- `instrument_cache_date`
- `instrument_mapping_at`

**Schema safety result: PASS.**

## Task 6 — Production safety regression

Read-only production GET endpoints reported:

| Requirement | Observed value | Result |
|---|---:|---|
| Active universe | `CUSTOM_LOW_PRICE_SECTOR` | **PASS** |
| Active count | `23` | **PASS** |
| Initial capital | `100000` | **PASS** |
| Automatic paper entries | `false` | **PASS** |
| Bootstrap | `false` | **PASS** |
| Automatic exits | `true` | **PASS** |
| Live broker order placement | disabled; `no_live_broker_orders=true`, controlled entry `execution_allowed=false` | **PASS** |
| Historical realized P&L | `-278.74` | **PASS** |
| Open positions | `0` | **PASS** |

Additional observed safety state:

- `paper_mode=true`;
- portfolio source and position source are both `phase20_ledger`;
- `open_positions=[]`;
- controlled paper entry endpoint is `DISABLED`;
- `trading_data_ready=false` because 20 symbols are unavailable, which is
  correct while token hydration remains intentionally blocked.

## Task 7 — Approved commit decision

All acceptance conditions pass:

- deployed commit is a descendant of the previous approved candidate;
- the only intermediate change is report/evidence metadata;
- no unrelated trading change exists;
- schema diff is non-destructive and empty; and
- production safety state is unchanged.

```text
APPROVED_DEPLOY_COMMIT =
4392f278ae25562f168f970e2b694f8c3d249d5c
```

## Task 8 — Final production identity check

The final read-only check of
`https://nse-trade-intraday.replit.app/api/health/details` reported:

```text
environment = production
git_commit = 4392f278ae25562f168f970e2b694f8c3d249d5c
build_id = apexquant-4392f278ae25
deployment_id = 0d018179-abe0-42c2-a554-dbb19d11341f
runtime_timestamp = 2026-08-23T22:04:14.550Z
```

The deployed commit and build ID match the reconciled approved reference
exactly.

## Final verdict

**A. IDENTITY PASS — SAFE DESCENDANT, APPROVED REFERENCE ADVANCED**

Production is already running the exact approved commit. Stop here.

No token hydration, live-session verification, scan, universe operation,
portfolio operation, or order operation was performed.