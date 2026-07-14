---
name: Phase 8 broker safety design
description: Key safety invariants for broker integration that must be preserved in all future phases
---
## Credential handling
- ONLY from env vars ZERODHA_API_KEY + ZERODHA_ACCESS_TOKEN. Never written to disk.
- Always masked via broker_client._mask() in all API responses and UI.
- masked_creds() returns {api_key_masked, access_token_masked, api_key_set, access_token_set}.
- Factory: get_broker_client() → ZerodhaClient if creds present, else MockBrokerClient.

## No-auto-execution guarantee
- ExecutionEngine.step2_submit() is the ONLY path to real order placement.
- step2 requires: step1 completed first + kill switch re-checked immediately before submit.
- All 17 pre-trade checks in PreTradeValidator.run() must pass before step1 can succeed.
- Confirmation tokens: step1=REVIEW-{preview_id[:6]}, step2=CONFIRM-LIVE-{preview_id}.
- Preview expires after 5 minutes — must rebuild after expiry.

## Safety controls persist across restarts
- phase8_config.json stores: execution_mode, safety_controls dict, kill_switch_changed_at.
- Default mode: PAPER_TRADING (set in _load_config if key missing).
- KillSwitch state in safety_controls.kill_switch in config file.

## Audit log
- phase8_audit.json in Python dir. Max 500 entries (oldest dropped).
- Every PREVIEW_CREATED, CONFIRM_STEP1_OK/FAILED, ORDER_SUBMITTED/REJECTED/BLOCKED,
  KILL_SWITCH_TOGGLED gets an entry with audit_id (uuid hex[:10]) + ts + symbol + mode.

## Charges estimate
- _estimate_charges(value, side) in execution_engine.py.
- Brokerage: min(0.03% × value, ₹20). STT: 0.1% on SELL only. Exchange: 0.00345%.
- GST: 18% on (brokerage + exchange). SEBI: 0.0001%.

**Why:** All safety must be in one place (ExecutionEngine) and tested explicitly.
MockBrokerClient must always be the fallback so the system works without real creds.

**How to apply:** Any new Phase that adds execution paths must go through ExecutionEngine.
Never add a shortcut that calls BrokerClient.place_order_live() directly.
