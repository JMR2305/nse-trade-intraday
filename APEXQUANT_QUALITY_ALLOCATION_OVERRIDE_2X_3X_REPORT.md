# ApexQuant AI — Controlled Quality Allocation Override 2x/3x Report

**Report date:** 19 August 2026  
**Scope:** Paper-entry quality tiers, authoritative exposure caps, durable
settings, immutable evidence, audit events, and dashboard visibility  
**Trading mode:** Paper only. No live broker order API is called by this
feature.

## 1. Executive result

Controlled quality allocation overrides are implemented and verified for the
development paper-trading workflow.

- Normal candidates retain 1x sizing.
- High-quality candidates may request 2x sizing.
- Exceptional candidates may request 3x sizing only after two distinct valid
  scans.
- Bootstrap entries keep their existing separate sizing path and never receive
  2x/3x overrides.
- Missing, stale, contradictory, malformed, or untrusted quality evidence
  falls back to NORMAL 1x.
- A risk-validator outage blocks a 2x/3x request.
- Final quantity is recomputed from authoritative PostgreSQL ledger state while
  the paper-entry admission lock is held.
- Automatic paper entries remain **OFF**.
- Development paper capital remains ₹100,000.
- No production setting, position, ledger row, or capital value was changed.

Development runtime state verified after implementation:

| Check | Result |
|---|---:|
| Paper capital | ₹100,000 |
| Open paper positions | 0 |
| Automatic paper entries | Off |
| Quality allocation policy | On |
| 2x tier | On |
| 3x tier | On |
| 3x sector-cap override | Off |
| Live broker order path | Not introduced |

## 2. Tier policy

### NORMAL — 1x

NORMAL remains the default and fallback tier. The normal quantity is not
increased when any required quality evidence is absent, inconsistent, stale,
or untrusted.

Bootstrap-triggered entries always remain on their existing bootstrap sizing
path, even when their scores would otherwise meet 2x or 3x thresholds.

### HIGH_QUALITY_2X

A candidate may request 2x only when all existing entry gates pass and the
following additional requirements are satisfied:

| Requirement | Minimum / required state |
|---|---:|
| Confidence | 85 |
| Opportunity score | 80 |
| Trade-quality score | 80 |
| Reward:risk | 2.5 |
| Risk budget | 1.5% of capital |
| Kite session | Verified |
| Execution price | Trusted Kite live LTP |
| Quote | Reliable |
| Data quality | Live |
| Local OHLCV cache | Hit and fresh |
| Realized P&L today | No daily loss |
| Existing gates | All passed |

### EXCEPTIONAL_QUALITY_3X

A candidate may request 3x only when all 2x requirements pass plus:

| Requirement | Minimum / required state |
|---|---:|
| Confidence | 90 |
| Opportunity score | 85 |
| Trade-quality score | 88 |
| Reward:risk | 3.0 |
| Risk budget | 2.0% of capital |
| ATR | At or below 3.0% |
| Stop distance | At or below 2.5% |
| Stale/blocked-close warning | None |
| Scan continuity | Same symbol valid in prior distinct scan |

Reprocessing the same scan replaces its history record. It cannot qualify
itself for the two-scan rule. A risk rejection, PostgreSQL admission rejection,
duplicate-position rejection, or failed paper BUY marks the scan outcome
ineligible for future 3x continuity.

## 3. Final sizing constraints

The requested multiplier is only an upper bound. Final quantity is constrained
by every existing or new cap:

1. Available paper cash.
2. Per-stock exposure cap: 25% of paper capital.
3. Sector exposure cap: 40% by default.
4. Portfolio deployed-capital cap: 80%.
5. Tier risk budget: 1.5% for 2x and 2.0% for 3x.
6. Absolute quality-override cap: ₹30,000.
7. Whole-share rounding.
8. The downstream Risk Agent result.
9. The existing duplicate-position and PostgreSQL OPEN-row constraints.

The optional 3x sector-cap override is a separate setting and remains OFF. If
explicitly enabled later, it can raise the 3x sector cap only to the configured
limit and never above 50%.

### Authoritative locked revalidation

The first architecture review identified that a gate-time portfolio snapshot
could become stale when multiple paper entries contended concurrently.

This was corrected before sign-off:

- Capital migration and every OPEN-entry admission use the same PostgreSQL
  transaction advisory lock.
- Under that lock, entry admission re-reads:
  - current settings,
  - every OPEN and EXIT_PENDING ledger row,
  - realized P&L from CLOSED rows.
- It recomputes cash, stock, sector, portfolio, tier-risk, absolute, and
  whole-share limits immediately before INSERT.
- A smaller still-safe override is persisted with the reduced quantity.
- If the original NORMAL quantity no longer fits, the entry is blocked rather
  than silently admitted below its evaluated baseline.
- Malformed or unreadable authoritative ledger state fails closed.
- The final admitted quantity, charges, risk amount, sizing, evidence, and
  event payloads all use the locked result.

A real isolated-schema PostgreSQL test proves that a second 3x request for 30
shares is reduced to 10 shares when an earlier committed same-sector position
has already consumed ₹39,000 of the ₹40,000 default sector capacity.

## 4. Safety preservation

The override evaluator runs only after the existing Phase 20 eligibility gates
have passed. It does not replace or bypass:

- scan freshness,
- snapshot consistency,
- circuit breaker,
- duplicate-position prevention,
- daily trade limit,
- cash availability,
- stock exposure,
- sector exposure,
- portfolio deployed-capital limit,
- local-cache readiness,
- Kite session verification,
- quote reliability,
- downstream Risk Agent validation,
- PostgreSQL entry admission.

Risk Agent rejection blocks the paper entry. A Risk Agent exception blocks a
2x/3x entry and records `RISK_VALIDATOR_UNAVAILABLE`; it does not degrade to an
approved warning for exceptional sizing.

The feature calls only the existing paper-trading BUY function. No live broker
client, live order method, or Zerodha order endpoint is introduced.

## 5. Durable settings

The Phase 20 settings store now owns and validates:

- policy enabled state,
- independent 2x and 3x enabled states,
- all score and reward:risk thresholds,
- 2x and 3x risk budgets,
- 3x ATR and stop-distance limits,
- absolute override cap,
- optional 3x sector override and its bounded cap.

Validation enforces numeric ranges and relational ordering: 3x thresholds and
risk budgets cannot be weaker than their corresponding 2x values.

Existing partial settings rows are merged with current defaults before
relational validation, preserving compatibility with older stored settings.

## 6. Evidence and audit trail

Each admitted paper position stores immutable quality-allocation evidence:

- tier and approval state,
- requested and effective multiplier,
- base, requested, and final quantity/notional,
- confidence, opportunity, and trade-quality scores,
- reward:risk and trusted-source evidence,
- tier risk budget and final risk,
- limiting caps,
- post-trade stock, sector, and portfolio exposure,
- sector-override state,
- scan and settings provenance,
- downstream risk result,
- locked authoritative admission state.

Pipeline events include:

- allocation evaluated,
- override approved 2x,
- override approved 3x,
- override rejected,
- sector override applied,
- locked authoritative resize,
- final order submitted/cancelled.

Approval events are emitted only after PostgreSQL admission succeeds. The final
event quantity and notional match the admitted ledger row.

## 7. Dashboard visibility

The AI Paper Trader page displays:

- a persistent policy strip,
- exact backend thresholds and risk budgets,
- ATR and stop-distance constraints,
- the two-scan 3x requirement,
- the ₹30,000 absolute cap,
- sector override ON/OFF state and configured cap,
- tier badges, multipliers, notional, risk, limiting caps, and post-trade
  exposure on recommendations and holdings.

Recommendation values are explicitly labelled:

> PREVIEW · NOT EXECUTED

A recommendation preview is joined only when its scan ID, snapshot timestamp,
and settings hash match the current canonical recommendation source. Stale
symbol-only previews are suppressed. Open positions continue to display their
immutable executed ledger evidence.

Mission Control recognizes both canonical allocation-event fields and
order-prefixed allocation fields and shows tier, multiplier, final notional,
reason, and limiting caps.

## 8. Validation evidence

Final focused validation:

- Allocation policy and executor tests: **47 passed**
- Capital migration and locked PostgreSQL admission tests: **14 passed**
- Circuit-breaker regression: **17 passed**
- Consecutive-block regression: **13 passed**
- Portfolio pre-check event regression: **19 passed**
- Phase 20 allocation settings/preview tests: **2 passed**
- Phase 11 allocation evidence/preview tests: **3 passed**
- Dashboard allocation and Mission Control component tests: **11 passed**
- Shared libraries, API server, dashboard, and mobile TypeScript checks: passed
- Python compilation for changed backend modules: passed
- Git whitespace validation: passed
- Paper analytics smoke: **5 passed, 9 subtests passed**
- Publish-image size: **4.2 GiB**, below the 8 GiB limit
- Desktop and mobile browser verification: passed
- Mobile horizontal-overflow check: passed
- Relevant browser console/API errors: none observed
- API server workflow: running
- Trading dashboard workflow: running
- Fresh architecture and safety re-review: **PASS**

Two broader legacy files remain non-green outside the allocation scope:

- `test_phase20.py`: 53 passed and four existing date-sensitive
  EXIT_PENDING timeout/fallback assertions failed.
- `test_phase11.py`: 76 passed and two existing closed-position/state-isolation
  assertions failed.

The allocation-focused tests in both files pass. These six failures were
present before the final allocation safety fixes and do not exercise the
quality-allocation path.

## 9. Final sign-off

**Code status:** Implemented and verified.  
**Development policy:** Active, with automatic entries still OFF.  
**Bootstrap behavior:** Preserved; no 2x/3x override.  
**Concurrent admission safety:** Authoritatively revalidated under PostgreSQL
lock.  
**Production mutation:** None.  
**Live-order risk:** None introduced; the feature is paper-only.