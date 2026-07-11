---
name: Learning engine invariants & testing quirks
description: Rules and gotchas for the V2/V2.1 adaptive learning + hypothesis engine in the api-server python backend
---

# Invariants (must hold in any future learning-engine change)
- Never learn from mock data: only `learn_eligible` evaluations feed proposals/hypotheses.
- Bounded updates: ≤3 pts per applied step, ±15 total cap, approval-gated (analysis mode applies nothing).
- A learning adjustment can never create a BUY on its own.
**Why:** paper-trading system for a non-technical user; runaway self-modification is the main risk.

# Hypothesis mining lessons
- Segment-vs-rest mining produces mirror findings (segment A "reduce" ≡ complement "increase" at identical confidence). Any shortlist cap must tiebreak (we favour "reduce" — capital preservation) and diversify per scope type, or one side silently disappears depending on row ordering.
- Confidence gate: each materially different metric must be significant on its own test (min over supporting tests) — `max()` across tests lets a weak test ride along.
- Welch test with zero variance in both groups: return 100 if means differ, else 0 (constant synthetic returns in tests hit this).

# Testing quirks
- Any new learning module reading the intel DB must expose module-level `DB_PATH` and be monkeypatched in the shared tmp_db fixture, or tests write to the real DB.
- SQL that selects newly added columns from `historical_knowledge_trades` must tolerate older DBs/fixtures without them (use PRAGMA table_info to pick available columns).
- Full python suite takes >60s (hypothesis suite ~45s); run test files separately under tight timeouts.
