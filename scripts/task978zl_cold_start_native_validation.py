"""Task978ZL - native disposable PG16 validation of the cold-start authority binding.

Applies the reviewed TASK978ZA standalone clean-authority bootstrap (canonical
CUSTOM_LOW_PRICE_SECTOR universe id=3 version=1, 23 symbols, exact hash), then
proves check_cold_cache_on_startup resolves exactly that authority (never
NIFTY_50) and emits bounded failure evidence when the provider fails.
No external provider calls are made: the yfinance layer is stubbed.
"""
import os
import sys

os.environ["DATABASE_URL"] = "postgresql://task967:task967@127.0.0.1:5432/task978za_disposable_authority"
os.environ["OHLCV_CACHE_ENABLED"] = "true"
# Mirror the deployed commissioning configuration: the operator-selected
# durable universe mode is CUSTOM_LOW_PRICE_SECTOR (verified on Zeabur).
os.environ["ACTIVE_INTRADAY_UNIVERSE"] = "CUSTOM_LOW_PRICE_SECTOR"

PY = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "artifacts", "api-server", "src", "python")
sys.path.insert(0, os.path.abspath(PY))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import psycopg2

DB = os.environ["DATABASE_URL"]
conn = psycopg2.connect(DB)
conn.autocommit = True
cur = conn.cursor()
cur.execute("SELECT current_database(), current_user, version();")
row = cur.fetchone()
assert row[2].startswith("PostgreSQL 16"), row[2]
print("PG identity:", row[0], row[1], row[2][:31])

import task978r_clean_authority as authority

res = authority.bootstrap(
    DB,
    purpose="TASK978ZA_NATIVE_PG16",
    acknowledgement="TASK978ZA_DISPOSABLE_AUTHORITY",
)
assert res.get("success", res.get("status")) in (True, "PASS"), res
print("bootstrap ok:", res.get("status"))

cur.execute(
    """SELECT universe_key, version, status, exact_set_hash, enabled_symbol_count
       FROM trading_universes WHERE id = 3"""
)
uk, ver, status, eh, cnt = cur.fetchone()
assert (uk, ver, status, cnt) == ("CUSTOM_LOW_PRICE_SECTOR", 1, "ACTIVE", 23), (uk, ver, status, cnt)
assert eh == "22e5751f25686718f5572041834ce998b7c5ce9844d3b573bc3841749fe77016"
print("fixture: id=3 key=%s v=%d %s count=%d hash-verified" % (uk, ver, status, cnt))

import phase20_scheduler as sched

resolved = sched._resolve_cold_start_universe()
assert len(resolved["symbols"]) == 23
assert resolved["universe_key"] == "CUSTOM_LOW_PRICE_SECTOR"
assert resolved["universe_id"] == 3
assert resolved["universe_version"] == 1
assert resolved["exact_set_hash"] == "22e5751f25686718f5572041834ce998b7c5ce9844d3b573bc3841749fe77016"
cur.execute("SELECT symbol FROM trading_universe_members WHERE universe_id=3 AND enabled ORDER BY symbol")
db_symbols = sorted(r[0] for r in cur.fetchall())
assert sorted(resolved["symbols"]) == db_symbols
print("resolver: 23/23 symbols exactly match durable authority (no NIFTY_50)")

# Full cold-start run with the yfinance provider stubbed (no network).
from unittest.mock import patch

import pandas as pd
import numpy as np


def _fake_bulk(tickers, **kwargs):
    idx = pd.date_range(end=pd.Timestamp.today().normalize(), periods=130, freq="B")
    data = {}
    for t in tickers:
        for c in ("open", "high", "low", "close"):
            data[(t, c)] = np.linspace(10, 20, 130)
        data[(t, "volume")] = np.full(130, 1000)
    cols = pd.MultiIndex.from_product(
        [tickers, ["open", "high", "low", "close", "volume"]]
    )
    return pd.DataFrame(data, index=idx, columns=cols)


import yfinance

with patch.object(yfinance, "download", _fake_bulk):
    result = sched.check_cold_cache_on_startup()

print("cold-start result:")
for k in ("ran", "action", "role", "status", "total_symbols", "resolved_symbol_count",
          "universe_key", "universe_id", "universe_version", "symbols_updated",
          "symbols_failed", "failure_class", "authority_source"):
    print("  %s = %s" % (k, result.get(k)))
assert result.get("total_symbols") == 23
assert result.get("resolved_symbol_count") == 23
assert result.get("universe_key") == "CUSTOM_LOW_PRICE_SECTOR"
assert result.get("universe_id") == 3
assert result.get("universe_version") == 1
assert result.get("symbols_updated") == 23 and result.get("symbols_failed") == 0

cur.execute("SELECT count(DISTINCT symbol) FROM daily_ohlcv_cache")
n = cur.fetchone()[0]
assert n == 23, n
print("durable cache: 23/23 canonical symbols warmed, 0 substitutions")


def _boom(tickers, **kwargs):
    raise RuntimeError("provider unreachable")


# Reset the coordination keys and the cache so a second owner run can execute
# against a cold cache, then prove the bounded provider-failure evidence payload.
for prefix in ("ohlcv_cold_start_backfill:", "ohlcv_cold_start_backfill_done:",
               "ohlcv_cold_start_lease_started:", "ohlcv_cold_start_takeover:"):
    cur.execute("DELETE FROM phase20_kv WHERE key LIKE %s", (prefix + "%",))
cur.execute("DELETE FROM daily_ohlcv_cache")
cur.execute("DELETE FROM daily_ohlcv_refresh_state")
conn.commit()

with patch.object(yfinance, "download", _boom):
    fail = sched.check_cold_cache_on_startup()

print("provider-failure evidence:")
for k in ("action", "status", "symbols_failed", "failed_symbol_count",
          "failure_reason_counts", "first_n_failures", "failure_class"):
    print("  %s = %s" % (k, fail.get(k)))
assert fail.get("symbols_failed") == 23
assert fail.get("failure_class") == "PROVIDER_BACKFILL_FAILURE"
assert fail.get("failed_symbol_count") == 23
assert fail.get("failure_reason_counts")
assert 0 < len(fail.get("first_n_failures") or []) <= 5

print("TASK978ZL NATIVE PG16 COLD-START AUTHORITY VALIDATION: PASS")
