# RTV-3D — Runtime Identity, Safety, Portfolio, and Kite

**Date:** 2026-08-25 (Asia/Kolkata)  
**Verification mode:** Read-only production checks  
**Result:** **PASS**

## Runtime identity

| Field | Value |
|---|---|
| Environment | `production` |
| Git commit | `9f83f6764e3861e351e6334070d4031a85818876` |
| Build ID | `apexquant-9f83f6764e38` |
| Deployment ID | `0d018179-abe0-42c2-a554-dbb19d11341f` |
| Runtime timestamp | `2026-08-25T04:37:06.962Z` |

## Safety settings

Source: read-only `/api/phase20/settings`,
`/api/phase20/bootstrap-status`, `/api/controlled-paper-entry/status`,
`/api/broker/status`, and `/api/phase20/capital-migration/status`.

| Requirement | Observed value | Result |
|---|---|---|
| Active universe | `CUSTOM_LOW_PRICE_SECTOR` | PASS |
| Active universe count | `23` | PASS |
| Automatic paper entries | `false` | PASS |
| Entry confirmation timestamp | `null` | PASS |
| Bootstrap | `false` | PASS |
| Automatic exits | `true` | PASS |
| Live broker orders | `false` / disabled | PASS |
| Controlled paper execution | `DISABLED`, execution not allowed | PASS |
| Paper-only mode | `PAPER_TRADING` / research-only | PASS |

The settings response includes a generic explanatory `confirmation_text`
describing the paper-trading safety policy. It is not an operator confirmation
timestamp and does not enable automatic entries.

## Active instrument mappings

The custom-universe status and symbols endpoints reported 26 total candidates,
of which 23 are active. All 23 active rows had non-null:

- Kite symbol;
- instrument token;
- instrument trading symbol;
- exchange;
- instrument cache date.

Active mapping completeness was therefore **23/23**. The active symbols were:

```text
BANKBARODA BANKINDIA CANBK COALINDIA FEDERALBNK GAIL HUDCO IDFCFIRSTB
IRCON IRFC KTKBANK MAHABANK MRPL NBCC NMDC NTPC PFC PNB RECLTD RVNL SAIL
UNIONBANK WIPRO
```

## Portfolio and ledger

Source: canonical `phase20_ledger` portfolio endpoints.

| Requirement | Observed value | Result |
|---|---:|---|
| Initial capital | ₹100,000 | PASS |
| Cash | ₹99,721.26 | PASS |
| Equity | ₹99,721.26 | PASS |
| Realized P&L | −₹278.74 | PASS |
| Unrealized P&L | ₹0 | PASS |
| Open positions | `0` | PASS |
| `EXIT_PENDING` positions | `0` | PASS |
| Closed ledger rows | `6` | PASS |
| Portfolio source | `phase20_ledger` | PASS |
| Equity completeness | `true` | PASS |

Canonical parity holds because equity equals cash with no open or unrealized
exposure, and ₹100,000 − ₹278.74 = ₹99,721.26.

The all-trades presentation endpoint returns 12 closed buy/sell line items;
the authoritative capital-migration/ledger summary returns six closed
round-trip trades. No discrepancy was found in the required six-row ledger
baseline or P&L.

## Kite status

Source: read-only `/api/kite/diagnostics`, `/api/kite/status`, and
`/api/broker/status`.

| Requirement | Observed value | Result |
|---|---|---|
| Credentials present | `true` | PASS |
| Token stored | `true` | PASS |
| Token status | `VALID` | PASS |
| Token expired | `false` | PASS |
| Connected | `true` | PASS |
| Authenticated probe | Successful live probe | PASS |
| Connection state | `CONNECTED` | PASS |
| Daily login required | `false` | PASS |
| Mock mode | `false` | PASS |
| Live order placement | `false` | PASS |

Credentials and personal identity fields were not exposed in this report. No
manual login, token refresh, or credential creation was performed.

## Preserved failed evidence

The original failed evidence remains unchanged:

- `RTV3_NATURAL_SESSION_CERTIFICATION.md`
  - SHA-256:
    `8339f6a48a4f2eac2f172868e35759511ed66f060ddd956dfff931019999f7cf`
- `RTV3_PREOPEN_BATCH_EVIDENCE.csv`
  - SHA-256:
    `c7e06a59cacd17b0b552365e753948db0b2bdecbab6df4d5fbccfb29fb699270`

Original identifiers:

```text
session = preopen-2026-08-25-9b8340
batch   = collection-6073abbd096c44e7b4e4b51a205696ba
```