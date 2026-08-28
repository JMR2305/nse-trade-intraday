"""
kite_instrument_cache.py — Phase 19: Zerodha Kite Instrument Token Cache

Responsibilities
----------------
* Maintain a disk-backed JSON cache of NSE instruments (symbol → token map).
* Refresh the cache once per day (Kite's instrument list changes rarely).
* Provide fuzzy symbol search for the frontend instrument search feature.
* Fall back to bare-symbol lookups gracefully when cache is unavailable.
* Never place or modify orders — read-only.

Kite instrument tokens are required for historical_data() API calls.
For the quote() API, only "NSE:SYMBOL" format is needed (no token required).
This cache is therefore most useful for future historical data integration.

Cache file: data/kite_instruments.json  (alongside other JSON state files)
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import logging
import os
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Dict, Iterator, List, Optional, Sequence, Tuple
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

# ── Paths ─────────────────────────────────────────────────────────────────────

_DIR = os.path.dirname(os.path.abspath(__file__))
_CACHE_PATH = os.path.join(_DIR, "kite_instruments_cache.json")
_LOCK_PATH = os.path.join(_DIR, ".kite_instruments_cache.lock")

# Autoscale filesystems are ephemeral. The durable KV record is authoritative;
# the JSON file is only a warm cache for offline development and process-local
# reads after a successful durable load.
_DURABLE_CACHE_KEY = "kite_instrument_master_v1"
_DURABLE_STATUS_KEY = "kite_instrument_sync_status_v1"
_AUDIT_TABLE = "kite_instrument_sync_audit"
_SYNC_LOCK_NAME = "kite-instrument-master-sync-v1"

# ── Constants ─────────────────────────────────────────────────────────────────

CACHE_TTL_DAYS = 1              # refresh instrument list daily
MAX_SEARCH_RESULTS = 20
MIN_TOTAL_INSTRUMENTS = 5_000
MIN_NSE_EQ_INSTRUMENTS = 1_000
MIN_PREVIOUS_COUNT_RATIO = 0.90
_IST = ZoneInfo("Asia/Kolkata")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _today_iso() -> str:
    return datetime.now(_IST).date().isoformat()


def _read_file_cache() -> Dict[str, Any]:
    try:
        with open(_CACHE_PATH) as f:
            value = json.load(f)
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def _write_file_cache(data: Dict[str, Any]) -> None:
    tmp = _CACHE_PATH + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, separators=(",", ":"))
    os.replace(tmp, _CACHE_PATH)


def _durable_store_available() -> bool:
    try:
        import phase20_store
        return bool(phase20_store.db_available())
    except Exception:
        return False


def _load_durable_cache() -> Tuple[bool, Optional[Dict[str, Any]]]:
    """Return ``(authority_available, cache)``.

    If Postgres is configured but unreadable, propagate the failure so callers
    cannot silently revive a bundled or instance-local cache as authority.
    """
    import phase20_store
    if not phase20_store.db_available():
        return False, None
    value = phase20_store.kv_get_durable(_DURABLE_CACHE_KEY)
    return True, value if isinstance(value, dict) else None


def _load_sync_status() -> Dict[str, Any]:
    try:
        import phase20_store
        if not phase20_store.db_available():
            return {}
        value = phase20_store.kv_get_durable(_DURABLE_STATUS_KEY)
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def _save_sync_status(status: Dict[str, Any]) -> None:
    import phase20_store
    if phase20_store.db_available():
        phase20_store.kv_set_durable(_DURABLE_STATUS_KEY, status)


def _load_cache() -> Dict[str, Any]:
    try:
        durable_available, durable = _load_durable_cache()
    except Exception as exc:
        logger.warning("Durable instrument cache read failed: %s", exc)
        return {}
    if durable_available:
        if durable is None:
            # When shared storage is configured, a bundled/local file is not
            # production authority and must not suppress a durable refresh.
            return {}
        try:
            _write_file_cache(durable)
        except Exception as exc:
            logger.warning("Failed to warm local instrument cache: %s", exc)
        return durable
    return _read_file_cache()


def _save_cache(data: Dict[str, Any]) -> None:
    """Promote a validated candidate durably before warming the local file."""
    import phase20_store
    if phase20_store.db_available():
        phase20_store.kv_set_durable(_DURABLE_CACHE_KEY, data)
        try:
            _write_file_cache(data)
        except Exception as exc:
            logger.warning("Durable instrument cache saved; local warm failed: %s", exc)
        return
    _write_file_cache(data)


def _cache_is_fresh(cache: Dict[str, Any]) -> bool:
    """Return True only for a complete cache populated today."""
    return (
        cache.get("date") == _today_iso()
        and cache.get("complete") is True
        and bool(cache.get("instruments"))
    )


def _normalise_instrument(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Read both legacy Kite-cache rows and the current normalized schema."""
    symbol = str(raw.get("symbol") or raw.get("tradingsymbol") or "").upper().strip()
    return {
        "symbol": symbol,
        "name": str(raw.get("name") or raw.get("company_name") or symbol),
        "token": raw.get("token", raw.get("instrument_token")),
        "exchange": str(raw.get("exchange") or "NSE"),
        "instrument_type": str(raw.get("instrument_type") or ""),
        "lot_size": raw.get("lot_size", 1),
        "tick_size": raw.get("tick_size"),
        "segment": str(raw.get("segment") or ""),
    }


def _candidate_hash(instruments: Sequence[Dict[str, Any]]) -> str:
    canonical = [
        [
            str(row.get("symbol") or ""),
            int(row.get("token") or 0),
            str(row.get("exchange") or ""),
            str(row.get("segment") or ""),
            str(row.get("instrument_type") or ""),
        ]
        for row in instruments
    ]
    return hashlib.sha256(
        json.dumps(canonical, separators=(",", ":")).encode()
    ).hexdigest()


def validate_candidate(
    raw_instruments: Sequence[Dict[str, Any]],
    previous_cache: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Validate a full NSE instrument response before it can be promoted."""
    instruments: List[Dict[str, Any]] = []
    parse_failures = 0
    unsupported = 0
    tokens: Dict[int, str] = {}
    symbols: Dict[str, int] = {}
    duplicate_tokens: List[int] = []
    duplicate_symbols: List[str] = []
    nse_count = 0
    nse_eq_count = 0

    for raw in raw_instruments:
        if not isinstance(raw, dict):
            parse_failures += 1
            continue
        row = _normalise_instrument(raw)
        symbol = row["symbol"]
        try:
            token = int(row.get("token") or 0)
        except (TypeError, ValueError):
            token = 0
        exchange = str(row.get("exchange") or "").upper()
        segment = str(row.get("segment") or "").upper()
        instrument_type = str(row.get("instrument_type") or "").upper()
        if not symbol or token <= 0 or exchange != "NSE" or not segment.startswith("NSE"):
            parse_failures += 1
            continue
        row["token"] = token
        row["exchange"] = exchange
        row["segment"] = segment
        row["instrument_type"] = instrument_type
        instruments.append(row)
        nse_count += 1
        if instrument_type == "EQ":
            nse_eq_count += 1
        else:
            unsupported += 1
        if token in tokens:
            duplicate_tokens.append(token)
        else:
            tokens[token] = symbol
        if symbol in symbols:
            duplicate_symbols.append(symbol)
        else:
            symbols[symbol] = token

    errors: List[str] = []
    if len(raw_instruments) < MIN_TOTAL_INSTRUMENTS:
        errors.append("instrument_count_below_minimum")
    if len(instruments) < MIN_TOTAL_INSTRUMENTS:
        errors.append("valid_nse_count_below_minimum")
    if nse_eq_count < MIN_NSE_EQ_INSTRUMENTS:
        errors.append("nse_eq_count_below_minimum")
    previous_count = len((previous_cache or {}).get("instruments", []))
    previous_complete = (previous_cache or {}).get("complete") is True
    minimum_relative_count = (
        int(previous_count * MIN_PREVIOUS_COUNT_RATIO)
        if previous_complete and previous_count >= MIN_TOTAL_INSTRUMENTS
        else 0
    )
    if minimum_relative_count and len(instruments) < minimum_relative_count:
        errors.append("material_count_regression")
    if parse_failures:
        errors.append("parse_failures_present")
    if duplicate_tokens:
        errors.append("duplicate_tokens_present")
    if duplicate_symbols:
        errors.append("duplicate_symbols_present")

    return {
        "complete": not errors,
        "provider": "ZERODHA_KITE",
        "raw_count": len(raw_instruments),
        "row_count": len(instruments),
        "nse_count": nse_count,
        "nse_eq_count": nse_eq_count,
        "parse_failures": parse_failures,
        "duplicate_token_count": len(set(duplicate_tokens)),
        "duplicate_symbol_count": len(set(duplicate_symbols)),
        "unsupported_instrument_count": unsupported,
        "previous_row_count": previous_count,
        "minimum_relative_count": minimum_relative_count,
        "errors": errors,
        "exact_set_hash": _candidate_hash(instruments),
        "instruments": instruments,
    }


def _ensure_audit_schema(cur: Any) -> None:
    cur.execute(f"""
        CREATE TABLE IF NOT EXISTS {_AUDIT_TABLE} (
            id BIGSERIAL PRIMARY KEY,
            attempted_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            completed_at TIMESTAMPTZ,
            provider TEXT NOT NULL,
            status TEXT NOT NULL CHECK (status IN ('SUCCESS', 'FAILED', 'SKIPPED')),
            previous_row_count INTEGER NOT NULL,
            candidate_row_count INTEGER,
            promoted_row_count INTEGER,
            candidate_hash TEXT,
            failure_reason TEXT,
            evidence JSONB NOT NULL
        )
    """)
    cur.execute("""
        CREATE OR REPLACE FUNCTION reject_kite_instrument_sync_audit_mutation()
        RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'Kite instrument sync audit is append-only';
        END;
        $$ LANGUAGE plpgsql
    """)
    cur.execute(f"""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_trigger
                WHERE tgname = 'trg_kite_instrument_sync_audit_immutable'
            ) THEN
                CREATE TRIGGER trg_kite_instrument_sync_audit_immutable
                BEFORE UPDATE OR DELETE ON {_AUDIT_TABLE}
                FOR EACH ROW
                EXECUTE FUNCTION reject_kite_instrument_sync_audit_mutation();
            END IF;
        END
        $$;
    """)


def _upsert_kv(cur: Any, key: str, value: Dict[str, Any]) -> None:
    import phase20_store
    phase20_store._ensure_kv_table(cur)
    cur.execute("""
        INSERT INTO phase20_kv (key, value, updated_at)
        VALUES (%s, %s, NOW())
        ON CONFLICT (key) DO UPDATE
        SET value = EXCLUDED.value, updated_at = NOW()
    """, (key, json.dumps(value, default=str)))


def _insert_audit(
    cur: Any,
    *,
    status: str,
    previous_count: int,
    candidate_count: Optional[int],
    promoted_count: Optional[int],
    candidate_hash: Optional[str],
    failure_reason: Optional[str],
    evidence: Dict[str, Any],
) -> None:
    _ensure_audit_schema(cur)
    cur.execute(f"""
        INSERT INTO {_AUDIT_TABLE} (
            completed_at, provider, status, previous_row_count,
            candidate_row_count, promoted_row_count, candidate_hash,
            failure_reason, evidence
        ) VALUES (NOW(), 'ZERODHA_KITE', %s, %s, %s, %s, %s, %s, %s)
    """, (
        status, previous_count, candidate_count, promoted_count,
        candidate_hash, failure_reason, json.dumps(evidence, default=str),
    ))


def _promote_cache(
    promoted: Dict[str, Any],
    status: Dict[str, Any],
    previous_count: int,
) -> None:
    """Commit authority, status, and audit in one durable transaction."""
    import phase20_store
    if phase20_store.db_available():
        conn = phase20_store._durable_kv_connection()
        try:
            with conn.cursor() as cur:
                _upsert_kv(cur, _DURABLE_CACHE_KEY, promoted)
                _upsert_kv(cur, _DURABLE_STATUS_KEY, status)
                _insert_audit(
                    cur,
                    status="SUCCESS",
                    previous_count=previous_count,
                    candidate_count=promoted["count"],
                    promoted_count=promoted["count"],
                    candidate_hash=promoted["exact_set_hash"],
                    failure_reason=None,
                    evidence=status,
                )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
        try:
            _write_file_cache(promoted)
        except Exception as exc:
            logger.warning("Durable instrument cache saved; local warm failed: %s", exc)
        return
    _write_file_cache(promoted)


def _persist_failure(
    status: Dict[str, Any],
    *,
    previous_count: int,
    candidate_count: Optional[int],
    candidate_hash: Optional[str],
    failure_reason: str,
) -> None:
    """Commit failure status and audit without touching active authority."""
    import phase20_store
    if not phase20_store.db_available():
        return
    conn = phase20_store._durable_kv_connection()
    try:
        with conn.cursor() as cur:
            _upsert_kv(cur, _DURABLE_STATUS_KEY, status)
            _insert_audit(
                cur,
                status="FAILED",
                previous_count=previous_count,
                candidate_count=candidate_count,
                promoted_count=None,
                candidate_hash=candidate_hash,
                failure_reason=failure_reason,
                evidence=status,
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@contextmanager
def _sync_guard() -> Iterator[bool]:
    """Serialize refreshes locally and across Autoscale instances."""
    fd = None
    conn = None
    acquired = False
    try:
        fd = os.open(_LOCK_PATH, os.O_CREAT | os.O_RDWR, 0o644)
        fcntl.flock(fd, fcntl.LOCK_EX)
        if _durable_store_available():
            import phase20_store
            conn = phase20_store._durable_kv_connection()
            with conn.cursor() as cur:
                cur.execute("SELECT pg_try_advisory_lock(hashtext(%s))", (_SYNC_LOCK_NAME,))
                acquired = bool(cur.fetchone()[0])
        else:
            acquired = True
    except Exception as exc:
        logger.warning("Instrument sync lock unavailable: %s", exc)
        if conn is not None:
            conn.close()
            conn = None
        if fd is not None:
            os.close(fd)
            fd = None
        yield False
        return
    try:
        yield acquired
    finally:
        if conn is not None:
            if acquired:
                try:
                    with conn.cursor() as cur:
                        cur.execute("SELECT pg_advisory_unlock(hashtext(%s))", (_SYNC_LOCK_NAME,))
                    conn.commit()
                except Exception:
                    pass
            conn.close()
        if fd is not None:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)


# ── Instrument fetch ──────────────────────────────────────────────────────────

def _fetch_from_kite() -> List[Dict[str, Any]]:
    """Fetch NSE instrument list from Kite. Raises on failure."""
    from kiteconnect import KiteConnect
    api_key = os.environ.get("ZERODHA_API_KEY") or ""
    try:
        import kite_token_store
        token, _ = kite_token_store.resolve_preferred_token()
    except Exception:
        token = os.environ.get("ZERODHA_ACCESS_TOKEN") or ""
    if not api_key or not token:
        raise ValueError("Kite credentials not set")
    kite = KiteConnect(api_key=api_key)
    kite.set_access_token(token)
    instruments = kite.instruments("NSE")
    if not isinstance(instruments, list):
        raise TypeError("Kite instruments response is not a list")
    # Return every provider row. Filtering here would hide malformed rows from
    # the completeness validator and could permit a partial response.
    return instruments


# ── Public API ────────────────────────────────────────────────────────────────

def refresh(force: bool = False) -> Dict[str, Any]:
    """
    Refresh the instrument cache if stale (or if force=True).
    Returns a status dict. Never raises.
    """
    with _sync_guard() as acquired:
        if not acquired:
            return {
                "success": False,
                "refreshed": False,
                "error": "instrument_sync_already_running",
            }
        cache = _load_cache()
        previous_count = len(cache.get("instruments", []))
        if not force and _cache_is_fresh(cache):
            return {
                "success": True,
                "refreshed": False,
                "reason": "cache_fresh",
                **cache_status(),
            }

        attempted_at = _now_utc()
        try:
            raw_instruments = _fetch_from_kite()
            validation = validate_candidate(raw_instruments, previous_cache=cache)
            if not validation["complete"]:
                reason = ",".join(validation["errors"])
                status = {
                    "provider": "ZERODHA_KITE",
                    "sync_status": "FAILED",
                    "last_attempted_sync": attempted_at,
                    "last_successful_sync": cache.get("last_successful_sync")
                        or cache.get("fetched_at"),
                    "failure_reason": reason,
                    "candidate": {k: v for k, v in validation.items() if k != "instruments"},
                    "previous_row_count": previous_count,
                }
                try:
                    _persist_failure(
                        status,
                        previous_count=previous_count,
                        candidate_count=validation["row_count"],
                        candidate_hash=validation["exact_set_hash"],
                        failure_reason=reason,
                    )
                except Exception as audit_exc:
                    logger.warning("Failed to persist instrument sync failure: %s", audit_exc)
                return {
                    "success": False,
                    "refreshed": False,
                    "error": "instrument_candidate_incomplete",
                    "validation": {k: v for k, v in validation.items() if k != "instruments"},
                    "preserved_count": previous_count,
                    "date": cache.get("date"),
                }

            completed_at = _now_utc()
            promoted = {
                "date": _today_iso(),
                "fetched_at": completed_at,
                "provider": "ZERODHA_KITE",
                "complete": True,
                "count": validation["row_count"],
                "raw_count": validation["raw_count"],
                "nse_count": validation["nse_count"],
                "nse_eq_count": validation["nse_eq_count"],
                "parse_failures": validation["parse_failures"],
                "duplicate_token_count": validation["duplicate_token_count"],
                "duplicate_symbol_count": validation["duplicate_symbol_count"],
                "unsupported_instrument_count": validation["unsupported_instrument_count"],
                "exact_set_hash": validation["exact_set_hash"],
                "last_attempted_sync": attempted_at,
                "last_successful_sync": completed_at,
                "sync_status": "SUCCESS",
                "failure_reason": None,
                "instruments": validation["instruments"],
            }
            status = {
                key: value for key, value in promoted.items()
                if key != "instruments"
            }
            _promote_cache(promoted, status, previous_count)
            return {
                "success": True,
                "refreshed": True,
                **status,
            }
        except Exception as exc:
            error = str(exc)[:300]
            logger.warning("Instrument cache refresh failed: %s", error)
            status = {
                "provider": "ZERODHA_KITE",
                "sync_status": "FAILED",
                "last_attempted_sync": attempted_at,
                "last_successful_sync": cache.get("last_successful_sync")
                    or cache.get("fetched_at"),
                "failure_reason": error,
                "previous_row_count": previous_count,
            }
            try:
                _persist_failure(
                    status,
                    previous_count=previous_count,
                    candidate_count=None,
                    candidate_hash=None,
                    failure_reason=error,
                )
            except Exception as audit_exc:
                logger.warning("Failed to persist instrument sync failure: %s", audit_exc)
            return {
                "success": False,
                "refreshed": False,
                "error": error,
                "preserved_count": previous_count,
                "date": cache.get("date"),
            }


def get_token(symbol: str) -> Optional[int]:
    """Return the Kite instrument token for an NSE symbol, or None."""
    cache = _load_cache()
    sym = symbol.upper().strip()
    for inst in get_cached_instruments():
        if inst.get("symbol", "").upper() == sym:
            return inst.get("token")
    return None


def search(query: str, limit: int = MAX_SEARCH_RESULTS) -> List[Dict[str, Any]]:
    """
    Fuzzy search instruments by symbol or name.
    Returns up to `limit` matching instruments, ranked by relevance.
    Falls back to empty list when cache is unavailable.
    """
    if not query or len(query) < 1:
        return []

    cache = _load_cache()
    instruments = get_cached_instruments()
    q = query.upper().strip()

    exact: List[Dict[str, Any]] = []
    prefix: List[Dict[str, Any]] = []
    contains: List[Dict[str, Any]] = []

    for inst in instruments:
        sym = inst.get("symbol", "").upper()
        name = inst.get("name", "").upper()
        if sym == q:
            exact.append(inst)
        elif sym.startswith(q) or name.startswith(q):
            prefix.append(inst)
        elif q in sym or q in name:
            contains.append(inst)

    ranked = (exact + prefix + contains)[:limit]
    return [
        {
            "symbol": r.get("symbol"),
            "name": r.get("name"),
            "token": r.get("token"),
            "exchange": r.get("exchange"),
            "instrument_type": r.get("instrument_type"),
            "lot_size": r.get("lot_size"),
        }
        for r in ranked
    ]


def cache_status() -> Dict[str, Any]:
    """Return a summary of the current cache state."""
    cache = _load_cache()
    status = _load_sync_status()
    return {
        "date": cache.get("date"),
        "fetched_at": cache.get("fetched_at"),
        "count": len(cache.get("instruments", [])),
        "is_fresh": _cache_is_fresh(cache),
        "complete": cache.get("complete") is True,
        "provider": cache.get("provider"),
        "raw_count": cache.get("raw_count"),
        "nse_count": cache.get("nse_count"),
        "nse_eq_count": cache.get("nse_eq_count"),
        "parse_failures": cache.get("parse_failures"),
        "duplicate_token_count": cache.get("duplicate_token_count"),
        "duplicate_symbol_count": cache.get("duplicate_symbol_count"),
        "exact_set_hash": cache.get("exact_set_hash"),
        "last_attempted_sync": status.get("last_attempted_sync")
            or cache.get("last_attempted_sync"),
        "last_successful_sync": status.get("last_successful_sync")
            or cache.get("last_successful_sync")
            or cache.get("fetched_at"),
        "sync_status": status.get("sync_status")
            or cache.get("sync_status")
            or "UNVALIDATED",
        "failure_reason": status.get("failure_reason"),
        "authority": "durable_postgres"
            if _durable_store_available()
            else "local_offline_cache",
        "path": _CACHE_PATH,
    }


def get_cached_instruments() -> List[Dict[str, Any]]:
    """Return normalized cached instruments without triggering a broker request."""
    cache = _load_cache()
    return [
        _normalise_instrument(row)
        for row in (cache.get("instruments") or [])
        if isinstance(row, dict)
    ]


if __name__ == "__main__":
    import json as _json
    print("Cache status:", _json.dumps(cache_status(), indent=2))
    print("Search TCS:", _json.dumps(search("TCS"), indent=2))
