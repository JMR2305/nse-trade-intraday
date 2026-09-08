---
name: RTV-2D test harness
description: Working-directory, isolation, and local-fixture side effects for Phase 20/22 validation scripts.
---

Several legacy Python validation files are script-style tests, not
package-independent pytest modules. They must run from the Python source
directory; invoking them from the artifact root produces false missing-import
or missing-file failures.

**Why:** The scripts open peer files by relative name and rely on top-level
module imports. Combining otherwise independent suites in one interpreter can
also leak mocked `config` state between suites.

**How to apply:** Run the affected files in separate Python processes with the
Python source directory as the current working directory. Treat tracked JSON
notifications, warm-cache settings, and generated validation reports as
test-output fixtures; inspect and restore them after any validation run before
considering the workspace clean.