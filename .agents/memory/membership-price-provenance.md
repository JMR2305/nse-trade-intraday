---
name: Membership-price provenance
description: Separates durable custom-universe membership price evidence from current scan quote provenance.
---

## Rule
Custom-universe membership rows describe the price evidence used at the last
membership refresh. They must never be presented as the current market quote,
Kite connection state, or execution-grade price provenance.

**Why:** A single “Kite LTP” status on the universe builder conflated durable
eligibility metadata with live scan data, which could make a Yahoo-derived or
stale membership value appear to be an authenticated current Kite quote.

**How to apply:** Use the durable custom-universe status only for membership
and mapping coverage. Derive current provider, freshness, fallback, synthetic,
and unavailable state from the read-only canonical live-data health contract;
keep Kite connection status separate from both.