---
name: Walk-forward run performance
description: Why long experiment runs got slow/OOM-killed and the invariants of the vectorized similarity path
---

# Walk-forward similarity performance

- Bottleneck pattern: any per-decision scan over the full historical knowledge base (~3.3k rows) in pure Python explodes on runs whose test windows postdate most knowledge exits (the as_of filter keeps everything). Bear-era windows look fast only because the lookahead filter drops nearly all evidence — do not use them to judge performance.
- `similarity_engine.find_matches` has a numpy fast path (`_prep_vectors`/`_scores_vectorized`) that must stay byte-identical to `similarity_score` semantics: missing feature ⇒ 0 contribution, regime family 0.5, vol adjacency 0.5, linear numeric scales, ema 3 sub-checks, round(·,2), sort (-sim, exit_date asc, id asc), MIN_SIMILARITY/MAX_MATCHES. The slow loop remains as fallback — any scoring change must be applied to BOTH paths and re-checked with an equivalence sweep (fast vs `_np=None`).
- `get_active_weights()` was the hidden hot spot: it opened sqlite + ensure_tables per call (~7ms). It now has a 10s TTL cache. Weight updates are gated/rare so staleness is acceptable; for strict reproducibility consider freezing weights at run start.
- `walk_forward_validator._ADJ_CACHE` memoizes pattern/similarity adjustments per (day, symbol) across variants B–E (identical inputs), cleared at each window start. Valid only while item construction is variant-independent — if variants ever alter item features, drop the cache.
- Profiling recipe that worked: `py-spy dump --pid <runner pid>` (pid is in the experiment's heartbeat.json, which also carries rss_mb); stage logs include `[mem N MB]`.
- **Why:** the "Bull Market" experiment took ~15 min/window then got SIGKILLed; after vectorization + caches it completes 7 windows in ~2.5 min at ~200MB RSS.
