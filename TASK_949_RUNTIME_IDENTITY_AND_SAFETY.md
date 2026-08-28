# Task 949 — Runtime Identity and Safety

## Approved release identity

- `APPROVED_RELEASE_COMMIT = 68f18b078fe9de37da175480d40d4d42ae727830`
- `EXPECTED_BUILD_ID = apexquant-68f18b078fe9`
- Release branch: `release/task949-clean`
- Verified production parent: `c8b2a08bf14f227a38c8cdb6f9a75c223f7893bc`

Only the approved release commit may be published. The mixed audited head `194972de208fc7ef4aa2073637219f7523ff580b` must not be published.

## Task 947 preservation

Task 938 does not change any Task 947 pre-open source or test file. Exact source comparison confirms no semantic conflict with:

- automatic collection from 09:00 IST until, but not including, 09:12 IST;
- the 09:08–09:12 IST naturally scheduled final-proof window;
- 09:15 IST exact-batch freeze authority;
- `SCHEDULED` versus `MANUAL` origin semantics;
- strict freshness where age `< 300` seconds is fresh and age `>= 300` seconds is stale;
- provider scope `ALL`;
- active-universe authority.

## Task 938 behavior

After a successful versioned universe activation, the server invalidates scanner coverage cache state and advances its generation. A delayed pre-activation response may still complete for its original caller, but it cannot become the next cached result for the newly active universe.

Failed activation responses do not invalidate coverage. Retired universe mutation routes remain unable to change coverage state.

## Exact runtime delta from production

- `artifacts/api-server/src/routes/universe-management.ts`

The accompanying test file is not runtime code.

## Safety invariants

Release preparation did not:

- trigger Phase 5A, Phase 5B, or Phase 5C;
- trigger a market scan;
- collect or freeze pre-open evidence manually;
- activate or edit a universe;
- enable automatic entries;
- enable bootstrap mode;
- enable controlled execution;
- enable live broker orders;
- change settings;
- mutate portfolio or ledger state;
- publish or deploy.

## Post-publish read-only verification

This section remains a gate, not pre-deployment evidence. After the user publishes the approved commit, read-only checks must confirm:

- `environment = production`;
- `git_commit = 68f18b078fe9de37da175480d40d4d42ae727830`;
- `build_id = apexquant-68f18b078fe9`;
- `deployment_id` is present;
- active universe is `CUSTOM_LOW_PRICE_SECTOR`;
- active count is 23 and mappings are 23/23;
- automatic entries are false;
- bootstrap is false;
- controlled execution is disabled;
- live broker orders are disabled;
- portfolio and ledger are unchanged.

No natural-session certification may start until this identity and safety gate passes.