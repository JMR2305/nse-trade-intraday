# NSE Trader Intraday — Phase 0 Isolation Checklist

**Version:** 1.0  
**Date:** 2026-07-18  
**Status:** Documentation Only — No code modified  
**Purpose:** Verify that the Intraday project is fully isolated from the Swing project before any development begins.

---

## How to Use This Checklist

Each item has one of four statuses:

| Status | Meaning |
|---|---|
| `[ ]` | Not yet verified |
| `[x]` | Verified — confirmed by inspection or test |
| `[!]` | Cannot be verified yet — reason documented |
| `[~]` | Partially met — gaps documented |

Sign off the checklist by recording **who verified** each item and **how** (command run, URL checked, screenshot taken, etc.).

---

## Section 1 — Environment Isolation

### 1.1 Separate Replit Project

```
[ ] 1.1.1  A separate Replit repl has been created for the Intraday project.
            Intraday repl name: ___________________________
            Intraday repl URL:  ___________________________
            Verified by: ____________  Method: ____________

[ ] 1.1.2  The Intraday repl has a separate container (separate filesystem, 
            separate process namespace, separate port allocation).
            Verified by: ____________  Method: Confirm different REPL_ID env var

[ ] 1.1.3  The Swing repl URL is NOT referenced anywhere in the Intraday 
            codebase (search: grep -r "swing" . --include="*.ts" --include="*.py").
            Verified by: ____________  Command result: ___________
```

### 1.2 Separate Repository / Branch

```
[ ] 1.2.1  A baseline Git tag has been created before any Intraday code is written.
            Tag name:   intraday-baseline-v0.0
            Commit SHA: ___________________________
            Verified by: ____________  Method: git tag --list

[ ] 1.2.2  The Intraday codebase lives in a separate Git repository OR a 
            protected branch with merge gates that block merging into Swing main.
            Repository/branch: ___________________________
            Merge protection rule: ___________________________
            Verified by: ____________  Method: ____________

[ ] 1.2.3  No Intraday branch has been merged into the Swing main branch.
            Verified by: ____________  Method: git log --oneline main
```

---

## Section 2 — Secret and Credential Isolation

### 2.1 Separate Environment Variables

```
[ ] 2.1.1  The Intraday Replit Secrets store contains NO secrets copied from
            the Swing secrets store without an INTRADAY_ prefix.
            Verified by: ____________  Method: Replit Secrets UI inspection

[ ] 2.1.2  INTRADAY_DATABASE_URL is set and points to a database that is 
            NOT the same as the Swing DATABASE_URL.
            Intraday DB host: ___________________________
            Swing DB host:    ___________________________
            Same instance?    YES / NO
            Verified by: ____________  Method: compare connection strings (host/dbname only)

[ ] 2.1.3  ZERODHA_API_KEY and ZERODHA_API_SECRET in the Intraday repl 
            have been reviewed for session collision risk.
            Decision recorded: ___________________________
            (See unresolved decision §20.1 in MASTER_ARCHITECTURE.md)
            Verified by: ____________  Method: ____________

[ ] 2.1.4  No hardcoded credentials exist in any Intraday source file.
            Command: grep -rn "api_key\s*=\s*['\"]" . --include="*.py"
            Command: grep -rn "apiKey\s*:\s*['\"]" . --include="*.ts"
            Result: ___________________________
            Verified by: ____________
```

---

## Section 3 — Database Isolation

### 3.1 Separate Database Confirmed

```
[ ] 3.1.1  The Intraday project connects to a separate PostgreSQL database 
            (separate database name OR separate Replit DB instance).
            Intraday database name: ___________________________
            Swing database name:    ___________________________
            Verified by: ____________  Method: psql -c "\l"

[ ] 3.1.2  The Intraday database role does NOT have CONNECT privilege on 
            the Swing database.
            Command: psql -c "\du" and review privileges
            Verified by: ____________  Result: ____________

[ ] 3.1.3  The Swing database role does NOT have CONNECT privilege on 
            the Intraday database.
            Verified by: ____________  Method: ____________
```

### 3.2 No Shared Tables

```
[ ] 3.2.1  The Intraday codebase contains no SQL queries that reference 
            Swing table names: paper_portfolio, paper_trades, signals_cache,
            signal_snapshots, scan_state, scan_lock, portfolio_decisions,
            hypotheses, alert_deliveries, push_subscriptions, phase22_evidence.
            Command: grep -rn "paper_portfolio\|paper_trades\|signals_cache\|scan_state" . \
                       --include="*.py" --include="*.ts" --include="*.sql"
            Result: ___________________________
            Verified by: ____________

[ ] 3.2.2  The Intraday database migration history table is separate from
            the Swing migration history (different table name or different DB).
            Intraday migration table: ___________________________
            Verified by: ____________

[ ] 3.2.3  No cross-database foreign keys exist between the Intraday and 
            Swing databases.
            Verified by: ____________  (by design — no FK across databases in PostgreSQL)
```

### 3.3 Swing Database Cannot Be Written

```
[!] 3.3.1  CANNOT BE VERIFIED UNTIL: Intraday code is written and the
            database connection string is confirmed separate.
            Pre-condition: Item 3.1.1 must be verified first.
            
            When verifiable: Run the Intraday engine against a test session
            and confirm that no rows appear in any Swing database table.
            Method: SELECT COUNT(*) on Swing tables before and after an 
            Intraday test run; counts must not change.
```

---

## Section 4 — Scheduler and Job Isolation

### 4.1 Separate Scheduler

```
[ ] 4.1.1  The Intraday project does NOT import or call scanScheduler.ts 
            from the Swing platform.
            Command: grep -rn "scanScheduler" . --include="*.ts"
            Result: ___________________________
            Verified by: ____________

[ ] 4.1.2  The Intraday project does NOT import or call phase20_scheduler.py
            from the Swing platform.
            Command: grep -rn "phase20_scheduler" . --include="*.py"
            Result: ___________________________
            Verified by: ____________

[ ] 4.1.3  The Intraday scheduler (when implemented) uses a separate process
            and writes only to the Intraday database.
            [!] Cannot be verified until Phase A implementation is complete.
```

### 4.2 No Shared Cron Jobs

```
[ ] 4.2.1  The Replit repl for the Intraday project has no workflows that 
            invoke Swing platform code.
            Verified by: ____________  Method: Review artifact.toml / .replit workflows

[ ] 4.2.2  The Swing repl workflows have not been modified to accommodate 
            Intraday functionality.
            Verified by: ____________  Method: git diff HEAD --name-only on Swing main
```

---

## Section 5 — Code Isolation

### 5.1 No Real Order Route Reachable

```
[ ] 5.1.1  The Intraday API server has NO endpoint that submits a real 
            (non-paper) order to Zerodha.
            Command: grep -rn "place_order\|submit_order\|kite.order" . \
                       --include="*.py" | grep -v "paper\|mock\|test"
            Result: ___________________________
            Verified by: ____________

[ ] 5.1.2  The Intraday BrokerInterface.submit_order method in v1 is 
            connected ONLY to the Paper Execution Simulator and never 
            calls kite.place_order() with real credentials.
            [!] Cannot be verified until Phase A implementation is complete.
            Pre-condition: Broker adapter (Layer 1) implemented.

[ ] 5.1.3  The Phase 0 codebase (before Phase A) contains no order 
            placement code at all.
            Command: grep -rn "place_order\|order_type.*MARKET\|order_type.*LIMIT" . \
                       --include="*.py" | grep -v "#"
            Result: ___________________________
            Verified by: ____________
```

### 5.2 Swing API Cannot Be Triggered

```
[ ] 5.2.1  The Intraday frontend makes NO fetch calls to the Swing API 
            server URL.
            Command: grep -rn "trading-dashboard\|swing.*api\|/api/run-scan\|/api/portfolio" . \
                       --include="*.ts" --include="*.tsx"
            Result: ___________________________
            Verified by: ____________

[ ] 5.2.2  The Intraday Node.js API server does NOT proxy or forward 
            requests to the Swing API server.
            Command: grep -rn "proxy\|forward" src/routes/ --include="*.ts"
            Result: ___________________________
            Verified by: ____________

[ ] 5.2.3  The Intraday Python engine does NOT import main.py, config.py, 
            or any other module from the Swing Python engine path.
            Command: grep -rn "from.*swing\|import.*swing\|sys.path.*swing" . \
                       --include="*.py"
            Result: ___________________________
            Verified by: ____________
```

### 5.3 Swing Alerts Cannot Be Triggered

```
[ ] 5.3.1  The Intraday alert system uses a separate database table 
            (intraday_alert_deliveries) and does NOT write to the Swing 
            alert_deliveries table.
            [!] Cannot be verified until Phase A implementation is complete.

[ ] 5.3.2  The Intraday push notification system uses a separate database 
            table (intraday_push_subscriptions) and does NOT write to the 
            Swing push_subscriptions table.
            [!] Cannot be verified until Phase A implementation is complete.

[ ] 5.3.3  The Intraday codebase does NOT import alertQueue.ts from the 
            Swing platform.
            Command: grep -rn "alertQueue" . --include="*.ts" | grep -v "intraday"
            Result: ___________________________
            Verified by: ____________
```

---

## Section 6 — Model Isolation

### 6.1 Separate Model Directory

```
[ ] 6.1.1  The Intraday model directory intraday_models/ exists and is 
            separate from the Swing models/ directory.
            Verified by: ____________  Method: ls -la

[ ] 6.1.2  The Intraday calibration service is configured to load ONLY 
            from intraday_models/ and has no code path that loads from 
            the Swing models/ directory.
            [!] Cannot be verified until Phase A implementation is complete.

[ ] 6.1.3  No Swing calibration model artifact (e.g., Swing_Calibration_vN.pkl) 
            exists in the Intraday repl's model directory.
            Command: find . -name "*.pkl" | grep -v intraday
            Result: ___________________________
            Verified by: ____________
```

---

## Section 7 — Baseline State Recording

### 7.1 Baseline Commit / Tag

```
[ ] 7.1.1  A baseline Git commit or tag (intraday-baseline-v0.0) has been 
            created in the Intraday repository before any feature code is added.
            Tag SHA: ___________________________
            Verified by: ____________  Method: git show intraday-baseline-v0.0

[ ] 7.1.2  The baseline commit message describes the isolation state and 
            references this checklist.
            Commit message: ___________________________
            Verified by: ____________
```

### 7.2 Existing Tests and Health Status

```
[!] 7.2.1  The Swing platform's existing test suite status has been 
            recorded BEFORE any Intraday work begins.
            [!] Cannot be verified until a test suite is run on the Swing 
            platform baseline. This is a pre-condition, not a Phase 0 task.
            
            Action required: Run the Swing test suite and save the results 
            to docs/SWING_BASELINE_TEST_RESULTS.md before Phase A begins.
            Last known status: ___________________________

[ ] 7.2.2  The Swing platform API health check passes before any Intraday 
            development begins.
            Command: curl -s http://localhost:[SWING_PORT]/api/health | jq .
            Result: ___________________________
            Verified by: ____________  Date: ____________

[ ] 7.2.3  The Swing platform has been confirmed to NOT be modified by 
            any Intraday Phase 0 activity.
            Command: git status (on Swing main branch)
            Result: ___________________________
            Verified by: ____________
```

---

## Section 8 — Items That Cannot Yet Be Verified

The following items require Phase A implementation before they can be verified. They are listed here so they appear in the Phase A completion gate.

| Item | Pre-condition | Verification Method |
|---|---|---|
| 3.3.1 — Swing DB not written by Intraday engine | Item 3.1.1 verified; Phase A complete | Compare Swing DB row counts before and after Intraday test run |
| 4.1.3 — Intraday scheduler writes only to Intraday DB | Phase A scheduler implemented | Inspect scheduler DB connection string |
| 5.1.2 — submit_order is paper-only | Phase A broker adapter implemented | Code review; grep for kite.place_order() |
| 5.3.1 — Intraday alerts use separate table | Phase A alert queue implemented | Check DB writes after alert event |
| 5.3.2 — Intraday push uses separate table | Phase A push implemented | Check DB writes after push registration |
| 6.1.2 — Calibration loads from intraday_models/ only | Phase A calibration service implemented | Code review + integration test |

---

## Sign-Off Summary

| Section | Status | Verified By | Date |
|---|---|---|---|
| 1 — Environment Isolation | `[ ]` | | |
| 2 — Secret and Credential Isolation | `[ ]` | | |
| 3 — Database Isolation | `[ ]` | | |
| 4 — Scheduler and Job Isolation | `[ ]` | | |
| 5 — Code Isolation | `[ ]` | | |
| 6 — Model Isolation | `[ ]` | | |
| 7 — Baseline State Recording | `[ ]` | | |

**Phase 0 is complete when:** All items marked `[ ]` are changed to `[x]`, and all items marked `[!]` have a documented plan and owner for post-Phase-A verification.

---

*End of Phase 0 Isolation Checklist*  
*Version 1.0 — July 18, 2026 — Documentation only. No code was modified.*
