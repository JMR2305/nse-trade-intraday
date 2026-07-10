---
name: Expectancy learning conventions
description: Canonical conventions for the adaptive-learning / scanner ranking system after the Expectancy Engine sprint.
---

**Rule:** All learning/ranking logic is expectancy-based, not win-rate-based. Scanner opportunity score blend = 40% technical + 30% historical expectancy + 15% profit factor + 10% risk (drawdown-based) + 5% sector strength. Rating thresholds: Excellent ≥1.5, Good ≥0.5, Neutral ≥−0.2, Poor ≥−1.0, else Negative.

**Why:** Win rate alone misled ranking (high win-rate patterns with poor payoff outranked genuinely profitable ones). The user mandated expectancy everywhere and that existing pages are never removed — only extended.

**How to apply:**
- New learning features must rank/score by expectancy (with PF/Sharpe/Kelly as secondary), never plain win rate.
- When the OpportunityBreakdown shape changes, the dashboard UI must coalesce breakdown fields (`Number(x ?? 0)`) because React Query can serve stale pre-change cached payloads — `.toFixed` on a missing key crashes the row expansion.
- Never delete or replace existing dashboard pages; add new pages/sections alongside.
