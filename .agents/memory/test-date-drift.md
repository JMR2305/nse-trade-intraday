---
name: Test date drift
description: Hardcoded "recent" timestamps in tests rot when logic compares against now.
---
Rule: tests exercising age-based logic (e.g. phase20 TIME_EXIT after max_holding_days) must compute fixture timestamps relative to `datetime.now()`, never hardcode a calendar date.

**Why:** TestExitsSafety used a fixed fill_ts that aged past the 10-day holding window, so TIME_EXIT fired and masked trailing-stop assertions — 3 "mystery" failures on a clean tree.

**How to apply:** when a test fails only weeks after it was written and the failure involves TIME_EXIT/staleness/expiry rules, check for hardcoded dates first before suspecting the production logic.
