# RTV-2B — Runtime Identity and Safety

**Date:** 2026-08-24  
**Status:** Blocked before publish

## Current production identity

`GET https://nse-trade-intraday.replit.app/api/health/details` returned HTTP
200 with:

| Field | Observed value |
| --- | --- |
| environment | `production` |
| git commit | `393747a8102ee3fc8adaa36d60b6ed8db18bc4b8` |
| build ID | `apexquant-393747a8102e` |
| deployment ID | present |
| runtime timestamp | present/current at query time |

## Candidate identity

| Field | Candidate value |
| --- | --- |
| approved deploy commit | Not authorized |
| candidate HEAD | `253c687bb76d29bb09638bb0bddf00ff5e84fee7` |
| expected build ID | `apexquant-253c687bb76d2` |

Because the source gate failed, the candidate was not published and exact
candidate-to-production identity matching was not attempted.

## Read-only production observations

The production health response reported:

- active universe: `CUSTOM_LOW_PRICE_SECTOR`
- active count: 23
- valid token count: 23
- symbols on Kite: 23
- token stored: true
- token expired: false
- Kite currently connected: false
- live data readiness: not ready for the current session because the cached
  scan was stale

These observations were read-only and did not trigger scans or lifecycle work.

## Safety gate result

The source candidate changes:

```text
auto_paper_entries: false -> true
auto_paper_entries_confirmed_at: null -> 2026-08-24T03:33:38Z
```

This is a **SAFETY REGRESSION** and violates the required state:

- automatic entries disabled;
- bootstrap disabled;
- paper-only execution;
- live broker execution disabled.

No publish was performed. No trading or broker activity was performed.

## Required rerun after repair

After the source settings regression is resolved, recheck the full safety
matrix, including ₹100,000 initial capital, cash/equity, realized P&L, zero open
positions, automatic entries disabled, bootstrap disabled, automatic exits
enabled, live broker orders disabled, and 23/23 universe and token mappings.
