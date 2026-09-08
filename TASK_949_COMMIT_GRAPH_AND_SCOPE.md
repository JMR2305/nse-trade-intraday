# Task 949 — Commit Graph and Scope

## Identified commits

- `PRODUCTION_COMMIT = c8b2a08bf14f227a38c8cdb6f9a75c223f7893bc`
- `TASK_947_COMMIT = ebe07e5f83405df29bb20e535c968053bb2eedd6`
- `TASK_938_COMMIT = aeb0268598d485f472837be0bbed9d6d7ca9e48b`
- `AUDITED_CURRENT_HEAD = 194972de208fc7ef4aa2073637219f7523ff580b`
- `APPROVED_RELEASE_COMMIT = 68f18b078fe9de37da175480d40d4d42ae727830`

## Ancestry

The approved release has a single, reversible parent:

```text
68f18b078fe9de37da175480d40d4d42ae727830  Fix universe activation coverage cache race
└── c8b2a08bf14f227a38c8cdb6f9a75c223f7893bc  verified production base
    └── ebe07e5f83405df29bb20e535c968053bb2eedd6  Task 947
```

Task 947 is already an ancestor of the verified production base. Its pre-open runtime and test files are byte-identical in production and the approved release. The only tree difference between Task 947 and production is the later Task 948 uploaded runbook.

The audited mixed line after production was:

```text
c8b2a08b production
3007fc59 publish marker
9d93b5e9 Task 948 documentation
aeb02685 Task 938 route/test plus stale generated reports
fbbd133d Task 930 uploaded certification runbook
3c7c4bf8 second Task 930 uploaded certification runbook
194972de Task 949 uploaded release brief
```

## Commit classification

| Commit | Classification | Release treatment |
|---|---|---|
| `3007fc59560bbf7dff35a4213a16214f815015a0` | DOCUMENTATION_ONLY | Empty publish marker; excluded |
| `9d93b5e91d51092a3a5d9386e8d9f03cf08dad37` | DOCUMENTATION_ONLY | Task 948 reports; excluded |
| `aeb0268598d485f472837be0bbed9d6d7ca9e48b` | RUNTIME_REQUIRED + TEST_ONLY + UNSAFE mixed artifact | Route/test patch retained; generated `PreOpenAccuracy_20260827` JSON/Markdown excluded |
| `fbbd133d73ba782a96f38454d60847a487ba996d` | DOCUMENTATION_ONLY | Uploaded Task 930 certification brief; excluded |
| `3c7c4bf81be0b377131f456c50bf803a7ccf620b` | DOCUMENTATION_ONLY | Uploaded Task 930 certification data; excluded |
| `194972de208fc7ef4aa2073637219f7523ff580b` | DOCUMENTATION_ONLY | Uploaded Task 949 brief; excluded |

No unrelated runtime commit was retained. No unsafe runtime change was found.

## Exact approved release scope

Changed versus current production:

- Runtime: `artifacts/api-server/src/routes/universe-management.ts`
- Test only: `artifacts/api-server/src/routes/universe-coverage-cache-invalidation.test.ts`

No pre-open Python file, dashboard runtime file, mobile file, video file, broker/execution file, portfolio file, ledger file, setting, or universe data file changes in the approved release.

## Reversibility

The release is one commit on top of the verified production base. Reverting `68f18b078fe9de37da175480d40d4d42ae727830` restores the exact production tree without rewriting history.