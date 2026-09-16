# Task978R/S Clean Application Authority Reconstruction Design

Status: approved for review-faithful functional reconstruction
Base: `2c4dd3722b56f2e5b1ec01b14798ea2981d4650b`

## Classification

The resulting database is `CLEAN_RECONSTRUCTED_AUTHORITY` and is
`NOT_HISTORICALLY_EQUIVALENT_TO_REPLIT_DB`.

## Architecture

The bootstrap is a standalone Python CLI under `scripts/`. It imports only the
Python standard library and the PostgreSQL driver at execution time. It never
imports application modules, routers, schedulers, scanners, providers, brokers,
notification workers, portfolio code, ledger code, or order code.

Two checked-in, independently reviewable artifacts define its authority:

1. an additive PostgreSQL 16 SQL manifest containing the three reviewed SQL
   migrations followed by the PostgreSQL runtime-owned declarations needed to
   eliminate first-start lazy schema mutation; and
2. a JSON provenance/seed manifest mapping every object to its declaring source,
   dependencies, constraints, indexes, uniqueness, and clean-state policy.

Offline drift tests parse the exact source tree without importing it and fail if
a PostgreSQL lazy-created object is missing from the checked-in manifests.

## Identity gate

The CLI requires an explicit target contract: expected host, database, user,
purpose, and acknowledgement. It parses the supplied URL, rejects credentials
from output, connects read-only to establish `current_database`, `current_user`,
server address, and server major, and compares all available identity fields
before beginning a mutating transaction.

The checked-in policy always rejects `postgres16-benchmark`,
`apexquant_disposable`, `task967_disposable_task968`, unknown hosts, unknown
databases, and unknown purposes. Disposable CI allows only an explicitly named
`task978za_disposable_authority` target on loopback with the exact test user and
acknowledgement. Future Zeabur execution requires an explicit application
contract for `postgres16-apexquant-app` / `apexquant_app`; that contract is not
used in Task978ZA.

No bootstrap SQL is sent before identity verification succeeds.

## Schema and transaction behavior

The bootstrap applies statements in deterministic dependency order inside one
transaction. SQL is additive only: `CREATE TABLE IF NOT EXISTS`, compatible
`ALTER TABLE ... ADD COLUMN IF NOT EXISTS`, `CREATE INDEX IF NOT EXISTS`, and
evidence-backed upserts for approved current state. It contains no `DROP`,
`TRUNCATE`, destructive reset, destructive `ALTER`, replacement, schema cleanup,
or database recreation.

The three migration files remain canonical for their objects. Runtime-owned
declarations are copied exactly where already PostgreSQL-native, or normalized
only where the runtime path itself uses PostgreSQL compatibility semantics.
The manifest includes `phase20_kv (key TEXT PRIMARY KEY, value JSONB,
updated_at TIMESTAMPTZ DEFAULT NOW())` so `kite_token_store.save_token()` can use
`phase20_store.kv_set_durable()` without lazy DDL.

The protected chain is preserved exactly, including
`UNIQUE (correlation_id, action)` in that column order.

## Clean-state policy

The only seedable values are explicit current-state controls and the exact
canonical universe. Generated reconstruction metadata is visibly new and may
not impersonate historical records.

The bootstrap never inserts historical trades, realized-P&L rows, cash/equity
ledger rows, scheduler history, certification history, session pins, Kite
tokens, validation history, or historical audit events. Approximate historical
aggregates are external evidence only.

## Native PostgreSQL validation

Task969 validation creates a separate disposable database named
`task978za_disposable_authority` on its PostgreSQL 16 service. The validator:

1. captures an empty catalog snapshot;
2. runs the standalone bootstrap once;
3. verifies catalog, constraints, indexes, protected tables, Phase20 KV,
   clean seed data, and absence of prohibited history;
4. captures catalog and content fingerprints;
5. runs the bootstrap again;
6. proves identical fingerprints and zero unexpected mutation; and
7. removes the disposable validation database after evidence capture.

The bootstrap itself never contains or executes database-drop SQL.

## Runtime isolation

Static and subprocess tests fail if bootstrap execution imports application
modules, opens sockets before the identity gate, starts a scheduler/scanner,
invokes provider/broker/order code, writes notifications, resets portfolio or
ledger state, or contains synthetic historical records.

## Stop boundary

Task978ZA ends after exact-source CI passes. It never connects to
`postgres16-apexquant-app` / `apexquant_app`, never accesses TASK976, never
persists a real Kite token, never disables `HEALTH_ONLY_NO_SCHEDULERS`, and never
starts normal runtime or natural-session certification.
