---
name: Python package install workaround
description: How to install python packages in this project when the standard tools fail
---

**Rule:** To install a Python package in this workspace, use:
`python3 -m pip install --break-system-packages --prefix /home/runner/workspace/.pythonlibs <pkg>`

**Why:** Both the `installLanguagePackages` tool and `uv` failed when installing pytest (July 2026). The pip `--prefix .pythonlibs` route is the only path that worked; packages land where the project's python resolves them.

**How to apply:** Any time a new python dependency is needed for `artifacts/api-server/src/python`. Note: `pyproject.toml` is not automatically updated — add the dependency there manually if it must persist for deploys.
