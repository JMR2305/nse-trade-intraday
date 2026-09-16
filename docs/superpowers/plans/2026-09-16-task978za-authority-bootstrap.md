# Task978ZA Application Authority Bootstrap Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and validate a deterministic, additive, non-runtime PostgreSQL 16 authority bootstrap without touching either Zeabur database.

**Architecture:** A standard-library CLI executes a checked-in SQL manifest only after an exact database-identity gate. A checked-in JSON provenance/seed manifest and source-drift tests prove coverage and forbid historical fabrication; Task969 creates a separate disposable database for native first/second-run validation.

**Tech Stack:** Python 3.12, unittest, psycopg 3.3.5 in CI, PostgreSQL 16, GitHub Actions Task969.

**Spec:** `TASK978R_CLEAN_APPLICATION_AUTHORITY_RECONSTRUCTION_DESIGN.md`

## Global Constraints

- Base and remote branch must remain `2c4dd3722b56f2e5b1ec01b14798ea2981d4650b` until the reconstruction commit.
- No application runtime module imports in bootstrap code.
- No `DROP`, `TRUNCATE`, destructive reset/alter, historical fabrication, TASK976 access, Zeabur DB access, deployment, runtime activation, or token persistence.
- Tests precede implementation and each new behavior must be observed failing before it passes.
- Stage exact files only; never use `git add .`.

---

### Task 1: Offline contract and fail-closed identity gate

**Files:**
- Create: `scripts/test_task978r_clean_authority.py`
- Create: `scripts/task978r_clean_authority.py`

**Interfaces:**
- Produces: `TargetIdentity`, `parse_target_identity()`, `authorize_target()`, `bootstrap()` and CLI `main()`.

- [ ] Write tests for exact disposable identity, prohibited identities, unknown identities, and rejection-before-connect/SQL.
- [ ] Run the focused tests and confirm missing-module/behavior failures.
- [ ] Implement strict parsing, redaction, allowlist contracts, and pre-SQL identity verification.
- [ ] Run focused tests and confirm green.

### Task 2: Deterministic schema and provenance manifests

**Files:**
- Create: `scripts/task978r_application_authority_schema.sql`
- Create: `scripts/task978r_clean_authority_manifest.json`
- Modify: `scripts/test_task978r_clean_authority.py`
- Create: `scripts/test_task978s_bootstrap_review.py`

**Interfaces:**
- Consumes: exact migration and PostgreSQL lazy-creator declarations.
- Produces: ordered additive SQL and object/source/dependency/constraint/index manifest.

- [ ] Add failing coverage, Phase20 KV, protected-chain, audit-order, prohibited-SQL, runtime-import, and no-history tests.
- [ ] Run tests and confirm failures identify missing manifests.
- [ ] Extract and normalize the exact PostgreSQL authority declarations into deterministic order.
- [ ] Add source-drift comparison and reject unresolved dynamic PostgreSQL DDL.
- [ ] Run both offline suites and confirm green.

### Task 3: Clean current-state seed contract

**Files:**
- Modify: `scripts/task978r_clean_authority.py`
- Modify: `scripts/task978r_clean_authority_manifest.json`
- Modify: `scripts/test_task978r_clean_authority.py`

**Interfaces:**
- Produces: canonical universe rows and fail-closed runtime safety settings with explicit reconstruction provenance.

- [ ] Add failing tests for exact 23 symbols/hash and absence of every prohibited historical domain.
- [ ] Run tests and confirm failure.
- [ ] Implement only evidence-backed current-state seed statements.
- [ ] Run tests and confirm green.

### Task 4: Native disposable PostgreSQL 16 validator

**Files:**
- Create: `scripts/task978za_postgres_validation.py`
- Modify: `scripts/task969_postgres_validation.py`
- Modify: `scripts/test_task978r_clean_authority.py`

**Interfaces:**
- Produces: isolated `task978za_disposable_authority` lifecycle and first/second-run evidence.

- [ ] Add failing orchestration tests proving separate disposable identity and no prohibited target.
- [ ] Implement disposable database creation, bootstrap invocation, catalog/content fingerprinting, idempotency checks, and cleanup in validation tooling only.
- [ ] Run offline orchestration tests.
- [ ] Run Task969 in GitHub and require native PostgreSQL 16 PASS.

### Task 5: Full offline regression and review

**Files:** all Task978ZA files only.

- [ ] Run Task978R/S offline suites, AST/compile checks, migration/identity tests, and `git diff --check`.
- [ ] Run relevant existing suites available in the locked environment.
- [ ] Review complete diff and confirm no production runtime or migration file changed.
- [ ] Record exact counts and any environment-limited gate.

### Task 6: Reconstruction commit, exact-source authorization, and authoritative CI

**Files:**
- Modify only if CI rejects exact reviewed blobs: `scripts/task969_ci_report.py`, `scripts/test_task971_schema_order.py`.

- [ ] Stage exact reconstruction files and commit `Task978ZA add deterministic application authority bootstrap`.
- [ ] Push only to `origin/task967-migration-guard-hardening`.
- [ ] Observe Task969 for that exact SHA.
- [ ] If and only if identity alone rejects reviewed blobs, add exact path+blob pins and negative regressions.
- [ ] Commit separately as `Task978ZA authorize reviewed bootstrap blobs`, push, and rerun Task969.
- [ ] Stop on any non-identity failure.
- [ ] Report final exact SHA and leave Zeabur application DB apply not performed.
