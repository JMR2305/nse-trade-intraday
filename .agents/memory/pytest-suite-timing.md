---
name: Pytest suite timing
description: Why full-suite pytest runs time out in this workspace and how to run them
---

Running `python3 -m pytest tests/ -q` from `artifacts/api-server/src/python` exceeds the 2-minute bash tool timeout and dies with exit code -1 and no output.

**Why:** one test file (hypothesis-based engine tests) alone takes ~45s; the whole suite plus collection pushes past the limit intermittently.

**How to apply:** run test files individually (`for f in tests/test_*.py; do timeout 60 python3 -m pytest "$f" -q; done`) and sum the results, or target only the affected files. An exit code of -1 with no output means the tool killed the run — it is not a test failure.
