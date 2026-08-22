# ApexQuant AI — Phase 2D Advisory Bot Merge-Readiness Package

**Controlling report:** `APEXQUANT_PHASE2C_ADVISORY_BOT_SAFETY_REVIEW_REPORT.md`
**Branch:** `phase2a-advisory-multi-bot-logic`
**Mode:** PAPER ONLY / ADVISORY ONLY
**Package scope:** Review and merge-readiness documentation only

## 1. Merge-readiness verdict

**SAFE FOR LATER MERGE REVIEW**

The independent Phase 2C safety review passed after the exact-universe,
intraday-evidence, fixed-risk-limit, atomic-persistence, and report-formatting
findings were resolved.

This is not approval to merge or deploy. A later merge can only be considered
after the conditions in Section 14 are satisfied and an operator separately
approves it.

## 2. Branch and scope

- Reviewed branch: `phase2a-advisory-multi-bot-logic`
- Base branch: `main`
- The branch is not merged into `main`.
- The branch contains advisory bot logic, advisory tests, additive advisory
  storage, and supporting documentation only.
- No production migration was applied or deployed.
- No production endpoint, scheduler hook, or UI route was added.

## 3. File-by-file diff summary against `main`

Every committed changed file is classified below. No changed file falls under
the `other` category.

| File | Classification | Summary |
| --- | --- | --- |
| `.agents/memory/MEMORY.md` | documentation/report only | Adds the advisory audit-governance pointer. |
| `.agents/memory/advisory-audit-governance.md` | documentation/report only | Records the durable rule to recompute supervisor approval and persist a complete batch transactionally. |
| `APEXQUANT_PHASE2A_ADVISORY_MULTI_BOT_BRANCH_PLAN.md` | documentation/report only | Records the approved advisory-only architecture and safety boundaries. |
| `APEXQUANT_PHASE2B_ADVISORY_MULTI_BOT_IMPLEMENTATION_REPORT.md` | documentation/report only | Reports the Phase 2B implementation and validation. |
| `APEXQUANT_PHASE2C_ADVISORY_BOT_SAFETY_REVIEW_REPORT.md` | documentation/report only | Records the independent Phase 2C safety review and PASS verdict. |
| `APEXQUANT_PHASE2D_ADVISORY_BOT_MERGE_READINESS_PACKAGE.md` | documentation/report only | This merge-readiness package. |
| `attached_assets/Pasted-PHASE-2B-IMPLEMENT-ADVISORY-MULTI-BOT-LOGIC-ON-SEPARATE_1787349511581.txt` | documentation/report only | Source instruction attachment for the Phase 2B advisory branch work. |
| `attached_assets/Pasted-PHASE-2C-INDEPENDENT-SAFETY-REVIEW-AND-MERGE-READINESS-_1787399046869.txt` | documentation/report only | Source instruction attachment for the Phase 2C safety review. |
| `artifacts/api-server/src/python/advisory_bots/__init__.py` | advisory bot logic | Defines the package boundary and advisory contract exports. |
| `artifacts/api-server/src/python/advisory_bots/contracts.py` | advisory bot logic | Defines allowed advisory decisions and rejects executable/order/broker fields and terms. |
| `artifacts/api-server/src/python/advisory_bots/universe_bot.py` | advisory bot logic | Validates the exact approved 23-symbol custom universe and fails closed on substitutions or missing members. |
| `artifacts/api-server/src/python/advisory_bots/data_quality_bot.py` | advisory bot logic | Validates price, volume, freshness, supported intraday evidence, candle count, and OHLC invariants. |
| `artifacts/api-server/src/python/advisory_bots/regime_bot.py` | advisory bot logic | Classifies market regime as read-only advisory output. |
| `artifacts/api-server/src/python/advisory_bots/strategies.py` | advisory bot logic | Produces VWAP, opening-range, and EMA advisory scores only after the evidence gate. |
| `artifacts/api-server/src/python/advisory_bots/risk_gate_bot.py` | advisory bot logic | Applies fixed internal ₹100k/₹25k/₹1k/₹3k advisory limits without caller override. |
| `artifacts/api-server/src/python/advisory_bots/decision_bot.py` | advisory bot logic | Combines explainable advisory scores and ranks decisions. |
| `artifacts/api-server/src/python/advisory_bots/supervisor_bot.py` | advisory bot logic | Blocks unsafe settings, unhealthy universes, prohibited output, and contract violations. |
| `artifacts/api-server/src/python/advisory_bots/audit_bot.py` | advisory bot logic | Recomputes supervisor approval, validates the complete batch, and writes only allow-listed advisory evidence. |
| `artifacts/api-server/src/python/advisory_bots/orchestrator.py` | advisory bot logic | Provides manual, caller-supplied, read-only orchestration with `persist=False` by default. |
| `artifacts/api-server/src/python/phase24_store.py` | additive advisory storage | Adds four isolated advisory tables and the append-only PostgreSQL/JSON persistence boundary. |
| `artifacts/api-server/src/python/tests/unit/test_advisory_bots.py` | advisory bot tests | Covers contract isolation, universe/data gates, fixed risk limits, supervisor recomputation, rollback, and storage constraints. |

**Other classification:** none.

## 4. Files confirmed untouched

The committed branch diff contains no changes to:

- `phase20_executor.py`
- `phase20_scheduler.py`
- `phase20_exits.py`
- `phase20_eod_outcomes.py`
- `phase20_eod_status.py`
- `paper_trader.py`
- `broker_client.py`
- Kite or other live-order modules
- settings write handlers
- deployment configuration
- workflows
- production endpoint files
- UI route files
- `artifact.toml`

The protected-file scan was empty.

## 5. Migration and storage readiness review

The review covers exactly these four advisory tables:

- `advisory_bot_outputs`
- `advisory_strategy_scores`
- `advisory_decision_audit`
- `advisory_universe_health`

### Storage controls

**Additive only:** The advisory schema creates only the four new
`advisory_*` tables. It does not alter Phase 20 tables or trading settings.

**Append only:** Advisory writes are inserts only. The public advisory storage
surface has no update or delete operation.

**Idempotent:** Each insert uses `ON CONFLICT DO NOTHING` and stable advisory
record IDs.

**Contract flags:** Each table requires:

- `advisory_only IS TRUE`
- `paper_only IS TRUE`

Existing tables are upgraded only after invalid rows are checked. The migration
refuses to add a safety constraint if existing data violates it.

**No Phase 20 foreign keys or triggers:** The advisory schema has no foreign key
to trade, position, portfolio, or settings tables and no trigger touching Phase
20 tables.

**No shared Phase 20 mutation path:** The advisory writer is allow-listed to
the four advisory tables and does not import or call execution, broker,
scheduler, paper-trading, settings-write, or live-order code.

**Complete-batch validation:** All records are validated before the first write.
Supervisor approval is recomputed from the actual outputs, settings, and
universe health immediately before persistence.

**PostgreSQL atomicity:** When PostgreSQL is configured, one transaction covers
schema readiness and all advisory inserts. A later insert failure rolls back
the complete batch.

**Local JSON fallback:** When `DATABASE_URL` is absent, the local development
fallback stages all changed advisory files and restores replaced files if a
later replacement fails. This is not a production persistence mode.

**Configured database failure:** If `DATABASE_URL` is configured but the
database connection fails, the writer raises and does not silently switch to a
different store. This is intentional fail-closed behavior; operators must not
interpret a disconnected configured database as successful persistence.

**Migration action:** No production migration was applied or deployed as part
of this package.

## 6. Manual-only development runbook

There is currently no production endpoint or standard application command for
this pipeline. An operator may invoke it manually in an isolated development
checkout only, using caller-supplied read-only fixtures.

### Preconditions

1. Confirm the current branch is `phase2a-advisory-multi-bot-logic`.
2. Use a development database or no `DATABASE_URL` at all so the local JSON
   fallback is used.
3. Keep `auto_paper_entries=false` and `bootstrap_paper_enabled=false`.
4. Prepare a read-only fixture containing the exact approved custom universe,
   scan items with valid supported intraday candles, market context, settings,
   and optional risk inputs.
5. Do not use a production database, broker credentials, scheduler process, or
   live market execution process.

### Manual invocation

From the repository root:

```bash
cd artifacts/api-server/src/python
python3 - <<'PY'
from advisory_bots.orchestrator import run_advisory_analysis

# Replace these with an isolated development fixture. Do not load production
# trading state or broker objects into this call.
universe_rows = DEV_UNIVERSE_ROWS
scan_items = DEV_SCAN_ITEMS

result = run_advisory_analysis(
    scan_id="DEV-MANUAL-REVIEW-001",
    universe_rows=universe_rows,
    scan_items=scan_items,
    settings={
        "auto_paper_entries": False,
        "bootstrap_paper_enabled": False,
        "auto_paper_exits": True,
    },
    market_context=DEV_MARKET_CONTEXT,
    risk_inputs=DEV_RISK_INPUTS,
    build_id="phase2d-dev",
    config_hash="phase2d-dev-fixture",
    persist=False,
)

print(result)
PY
```

The names beginning with `DEV_` are deliberate placeholders for a local
fixture; this package does not provide a production data loader or endpoint.
The invocation is read-input-only and returns advisory evidence in memory.

### Optional local advisory persistence

`persist=False` is the default and is the required first run. If an operator
later needs append-only advisory evidence in an isolated development
environment, they may explicitly change only `persist=False` to `persist=True`
after confirming:

- the database is development-only, or `DATABASE_URL` is absent for local JSON;
- no production migration is being applied;
- the supervisor result is approved; and
- the output remains advisory-only and paper-only.

Persistence still cannot create trades, positions, orders, broker requests, or
settings changes. There is no scheduler hook. There is no production endpoint.

### Runbook prohibitions

- No scheduler hook exists.
- No production endpoint exists.
- No UI route exists.
- `persist=False` is the default.
- Outputs are advisory only and paper only.
- No trade creation is possible.
- No broker order is possible.
- No settings mutation is possible.
- No auto-entry or bootstrap enablement is possible through this pipeline.

## 7. Rollback plan

### Before merge: abandon the branch

1. Preserve any review notes that must be retained.
2. Confirm the branch has not been merged or deployed:

   ```bash
   git branch --show-current
   git merge-base --is-ancestor HEAD main
   ```

   The second command must return non-zero for this branch.

3. Switch to `main`.
4. If the operator has decided to abandon the work, delete the local advisory
   branch only after confirming the desired commits are preserved elsewhere:

   ```bash
   git switch main
   git branch -D phase2a-advisory-multi-bot-logic
   ```

This package does not perform that deletion.

### After a future merge: revert advisory files

If a later approved merge must be undone:

1. Identify the merge commit in the normal repository history.
2. Use the repository’s reviewed revert process, normally:

   ```bash
   git revert -m 1 <advisory-merge-commit>
   ```

3. Review the resulting diff and rerun the safety suites before any deployment.
4. Do not manually revert unrelated Phase 20 files; the expected revert scope is
   the advisory package, additive advisory storage, advisory tests, and
   documentation.

### Disable advisory storage usage

In the current branch there is no endpoint or scheduler caller to disable.
Keep all manual calls at `persist=False` and do not call
`persist_advisory_run`. If a future integration adds a feature flag, its safe
default must be disabled and it must not be wired to Phase 20 execution.

Do not delete advisory records as a rollback mechanism: the advisory store is
append-only by design. Disable future writes and preserve the audit trail.

### Verify Phase 20 remains unaffected

After any future merge or revert, confirm:

```bash
git diff --name-only <known-good-phase20-commit>..HEAD
git diff --check HEAD^..HEAD
```

Then confirm no changed file is a Phase 20 executor, scheduler, exit/EOD,
paper-trader, broker, settings writer, workflow, deployment, endpoint, or UI
route file. Rerun the Phase 0C safety suite.

### Confirm no trades, positions, or orders were touched

- Confirm no broker/order call appears in the advisory AST/import scan.
- Confirm no Phase 20 trade, position, portfolio, or settings writer was
  modified.
- For any future environment-level verification, use an authorized,
  read-only audit query against the relevant environment and compare counts
  before and after the advisory review.
- This branch’s manual runbook invokes only in-memory analysis by default and
  has created no trades, closed no positions, and submitted no orders.

## 8. Test re-run results

The required commands completed successfully:

| Command | Result |
| --- | --- |
| `python3 -m pytest tests/unit/test_advisory_bots.py -v` | 22 passed, 1 subtest passed |
| `python3 -m pytest tests/unit/test_phase0c_safety_fixes.py -v` | 22 passed; one existing datetime deprecation warning |
| `python3 -m pytest tests/unit/test_custom_universe_store.py -v` | 20 passed |
| `python3 -m py_compile advisory_bots/*.py phase24_store.py` | Passed |
| `git diff --check main...HEAD` | Passed |

Additional final checks passed:

- branch is not merged into `main`;
- protected-file diff scan is empty;
- advisory AST import/call deny-list is clean; and
- advisory storage allow-list/no-FK/no-trigger guard is clean.

## 9. Explicit safety confirmations

- **No merge:** confirmed. The branch remains isolated.
- **No deployment:** confirmed. No production deployment or migration was
  performed.
- **No scheduler hook:** confirmed. The pipeline is manually invoked only.
- **No endpoint/UI route:** confirmed. No API endpoint or UI route was added.
- **No trades/positions/live orders:** confirmed. No trade was created, no
  position was closed or changed, and no broker/live-order API was called.
- **Paper only:** confirmed.
- **Advisory only:** confirmed.
- **Auto paper entries:** remain disabled.
- **Bootstrap:** remains disabled.

## 10. Conditions for any later merge consideration

Final merge consideration is blocked until all of the following are true:

1. The Phase 1H Monday market-session watch passes.
2. An operator explicitly approves the merge.
3. The operator separately approves any future production deployment.

Even after those conditions pass, any future endpoint, scheduler integration,
UI route, broker integration, settings integration, auto-entry enablement, or
production migration requires its own independent review and approval.