---
name: Watchlist default fallback
description: watchlist.json is optional; readers must fall back to config.DEFAULT_WATCHLIST
---

Rule: any module reading the watchlist must fall back to `config.DEFAULT_WATCHLIST` when `watchlist.json` does not exist, matching `main.py._load_watchlist()`.

**Why:** watchlist.json is only written on first user modification. A reader that defaults to an empty list (as copilot_engine originally did) silently returns zero results (watchlist insights showed 0 despite the CLI listing 10 symbols).

**How to apply:** when loading watchlist data outside main.py, mirror the fallback: file → DEFAULT_WATCHLIST → [].
