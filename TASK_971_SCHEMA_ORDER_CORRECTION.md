# Task971 — canonical audit unique-key ordering

## Source of truth

GitHub Actions [Run #7](https://github.com/JMR2305/nse-trade-intraday/actions/runs/33587948514), HEAD `db3c2f4c0278d6f034dddf1d47c99e287368b8b7`, proved the disposable historical catalog has `UNIQUE (correlation_id, action)`. It inspected pg_constraint.conkey with ordered pg_attribute columns and stopped before applying either migration. Exact pre-Task964 source: `865210ebc282a997ed1157515682faca21839912`.

## Authorized correction

Only the fresh-table declarations in these files change:

- `lib/db/migrations/0002_universe_authority_schema_parity.sql`
- `artifacts/api-server/src/python/universe_version_store.py`

Both now declare `UNIQUE (correlation_id, action)`. This does not alter an existing constraint or modify any rows. No DROP, constraint recreation, universe change, production operation, merge or deploy is authorized. Universe authority tables are Python-owned and excluded from Drizzle's managed-table filter; no Drizzle model/snapshot change is required.

The migration guard's pinned fingerprint for that one complete CREATE TABLE declaration is replaced:

- Previous: `200fae443c28f58cae39e754795adc1eb48c194002a79a59c6c964207215f8a8`
- Corrected: `b5cdba323db2ebbd425ed525142276a8f4ae6f6ec172d28e1a127680ae5bd6b9`

No parser rule, protected-table rule, procedural-body approval or other fingerprint changes. The old mismatching declaration loses approval; arbitrary alterations remain blocked. The registry's original comment and all historical certification files remain unchanged; this document records the subsequent single-fingerprint review.

## Identity and regression gates

The historical reviewed Task967 tree remains `c0653b1d0f26a9869bc86d70240cd96a2e54128c`. The identity check permits exactly the two order substitutions and one fixed fingerprint substitution, comparing raw file contents to that tree. It rejects any extra source edits rather than broadly allowlisting those files. Validation-only helpers, this record, and workflow changes are listed separately. The new proof records before/after Git blob IDs and current SHA-256 values.

`python3 -m unittest discover -s scripts -p test_task971_schema_order.py -v` verifies historical/candidate/fixture ordering, exact source boundaries, single-fingerprint replacement, and fail-closed rejection of tampered declarations. The existing 968-test guard suite remains mandatory and unchanged.

## Release status

This is a new candidate, not a recertification of historical Task967/969 results. Run the existing PostgreSQL16 workflow on the review branch. Its ordering check remains unchanged; subsequent preservation, exact catalog, second-application idempotency and full application gates must actually pass before release review. A failure must be reported, not bypassed. No PASS is claimed by this source correction record.
