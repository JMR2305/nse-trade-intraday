# Task 960 — Baseline 23-Symbol Reconciliation

## Approved exact set

1. BANKBARODA
2. BANKINDIA
3. CANBK
4. COALINDIA
5. FEDERALBNK
6. GAIL
7. HUDCO
8. IDFCFIRSTB
9. IRCON
10. IRFC
11. KTKBANK
12. MAHABANK
13. MRPL
14. NBCC
15. NMDC
16. NTPC
17. PFC
18. PNB
19. RECLTD
20. RVNL
21. SAIL
22. UNIONBANK
23. WIPRO

`COUNT = 23`

`EXACT_SET_HASH =
22e5751f25686718f5572041834ce998b7c5ce9844d3b573bc3841749fe77016`

## Reconciliation contract

The candidate is read only from active
`CUSTOM_LOW_PRICE_SECTOR` rows in `custom_universe_master`. The approved set
above is used only as an equality invariant; it is never a runtime fallback.

Migration stops on:

- any missing, added, duplicate, malformed, or substituted symbol;
- any hash or count mismatch;
- stale or unavailable Kite instrument reference;
- missing or duplicate Kite mapping;
- non-NSE exchange;
- non-NSE cash segment;
- non-EQ instrument type;
- non-positive or duplicate instrument token;
- mismatch between persisted source binding and current Kite binding.

The source table is locked in SHARE mode from reconciliation through commit,
preventing a concurrent refresh from creating a phantom membership change.

## Development dry-run evidence

The development database proved the exact candidate count, set, and hash. It
correctly returned `ready=false` because its Kite cache was stale/incomplete
and its configured universe was `NIFTY_50`. No migration was executed and no
data was changed.
