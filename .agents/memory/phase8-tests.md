---
name: Phase 8 test pattern
description: How test_phase8.py is structured and what it covers
---
test_phase8.py has 95 assertions, all passing. Run: python3 test_phase8.py

8 mocked broker scenarios via MockBrokerClient(scenario=...):
  ok, expired_token, insufficient_funds, disconnected, rejected, partial_fill.
Stale data tested via data_quality="STALE" param in build_preview().
Duplicate order tested via manually appending to audit log before preview.
Kill switch tested by toggle_kill_switch(True) then checking preview status + step2 block.

Additional tests:
  safety_defaults, credential_masking, charge_estimator, mode_transitions,
  audit_log events, readiness_checker (READY/NOT_READY/LOCKED), order_preview_completeness.

MockBrokerClient scenarios available:
  "ok" — connected, VALID token, ₹5000 cash, WIPRO holding
  "expired_token" — connected=False, token_status=EXPIRED
  "insufficient_funds" — cash=0, margin=0
  "disconnected" — connected=False, error="Connection refused"
  "rejected" — place_order_live returns REJECTED
  "partial_fill" — place_order_live returns PARTIALLY_FILLED, filled_qty=1
