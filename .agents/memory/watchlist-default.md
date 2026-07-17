---
name: Watchlist persistence & default fallback
description: watchlist lives in Postgres (signals_store key "watchlist"); readers fall back file → DEFAULT_WATCHLIST
---

Rule: the watchlist is persisted in Postgres via `signals_store.save_watchlist()/load_watchlist()` (key `watchlist` in signals_cache). `watchlist.json` is only a warm cache / local-dev fallback. Any module reading the watchlist must try `signals_store.load_watchlist()` first, then the file, then `config.DEFAULT_WATCHLIST`.

**Why:** watchlist.json is ephemeral on Autoscale — custom watchlists silently reverted to the 50-symbol default on container restart. Also, a reader that defaults to an empty list (as copilot_engine originally did) silently returns zero results.

**How to apply:** loading order everywhere: Postgres (signals_store) → watchlist.json → DEFAULT_WATCHLIST. Never write watchlist.json directly as the primary store.
