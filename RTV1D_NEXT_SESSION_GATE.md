# RTV-1D — Next NSE Session Gate

## Current status

**BLOCKED pending exact production runtime identity.**

The approved source commit is:

`3ca36c4847c6309149aaf78a94da87b529034881`

Production currently reports:

- `git_commit=unknown`
- `build_id=apexquant-v1.0.0`
- `deployment_id=0d018179-abe0-42c2-a554-dbb19d11341f`

Do not treat the next-session checks as passed until production reports an
exact commit match.

## Before pre-open

- [ ] Confirm production `git_commit` exactly matches the approved source.
- [ ] Confirm `environment=production` and a non-empty deployment/build identity.
- [ ] Confirm Kite `credentials_present=true`.
- [ ] Confirm Kite `token_status=VALID`.
- [ ] Confirm Kite `token_stored=true`.
- [ ] Confirm Kite `connected=true` and `authenticated=true`.
- [ ] Confirm `login_required=false`.
- [ ] Confirm active universe is `CUSTOM_LOW_PRICE_SECTOR`.
- [ ] Confirm active count is exactly 23.
- [ ] Confirm sectors are BANK 9, INFRA 13, IT 1.
- [ ] Confirm active membership is unchanged and includes WIPRO as IT.
- [ ] Confirm 23/23 valid instrument mappings, zero missing, zero duplicates.
- [ ] Confirm `/api/portfolio` and `/api/portfolio/snapshot` share all canonical
  financial values.
- [ ] Independently reconcile six closed ledger rows to realized P&L `-278.74`
  and cash/equity `99,721.26`.
- [ ] Confirm synthetic symbol count is zero.
- [ ] Confirm automatic entries, bootstrap, and live broker orders remain off.

## During pre-open

- [ ] Observe only the scheduled 5A lifecycle; do not manually trigger it.
- [ ] Compare provider-collected count with persisted count.
- [ ] Require provider count equals persisted count.
- [ ] Verify partial updates preserve omitted fields.
- [ ] Verify terminal-state regression prevention.
- [ ] Verify explicit `NO_CANDIDATES` handling where applicable.
- [ ] Verify explicit `EOD_RETRY_REQUIRED` handling where applicable.
- [ ] Verify 5B and 5C lifecycle states from scheduled execution.

## At and after open

- [ ] Confirm the first canonical scan uses the 23 current active symbols.
- [ ] Prove the scheduler selected `CUSTOM_LOW_PRICE_SECTOR`.
- [ ] Confirm no duplicate legacy 50-symbol scheduled scan ran.
- [ ] Perform read-only Kite quote verification for all 23 active symbols.
- [ ] Confirm each quote has Kite provenance and a valid timestamp.
- [ ] Confirm no Kite-successful quote was replaced by fallback.
- [ ] Confirm no stale historical price is labeled as current live LTP.
- [ ] Confirm `session_fresh=true` only when the session and timestamps justify it.
- [ ] Confirm `trading_data_ready=true` only after every readiness gate passes.
- [ ] Keep automatic paper entries disabled throughout this verification.

## Allowed outcomes

### Closed market

It is acceptable for:

- `service_ready=true`
- `data_ready=true`
- `session_fresh=false`
- `trading_data_ready=false`

This is a health/readiness distinction, not permission to trade.

### Open market

A live-session pass requires fresh timestamps, the current 23-symbol scheduler
universe, successful pre-open lifecycle evidence, complete Kite provenance, and
all readiness gates passing. Do not infer any of these from a closed-market
check or from the legacy 50-symbol scan.

## Stop conditions

Stop and report failure if any of the following occurs:

- runtime commit is missing or does not equal the approved commit;
- an active symbol cannot be mapped uniquely;
- any synthetic or stale quote is classified as execution-grade;
- portfolio endpoints disagree on a canonical financial field;
- any historical ledger row changes;
- any safety flag changes unexpectedly;
- any order endpoint is called;
- provider and persisted pre-open counts differ;
- `trading_data_ready` becomes true without fresh complete evidence.