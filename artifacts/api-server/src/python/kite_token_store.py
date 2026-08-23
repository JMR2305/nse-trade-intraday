"""
kite_token_store.py — Phase 19A: backend-only Kite access-token storage.

Stores the daily Kite Connect access token obtained via the OAuth-style
request_token exchange. The file lives next to the Python modules, is
chmod 0600, and is NEVER exposed through any API response, log line,
export, or frontend state.

Precedence: authoritative Phase-20 KV > local warm file > ZERODHA_ACCESS_TOKEN.
`apply_to_env()` is called at process start (main.py) so every existing
module that reads ZERODHA_ACCESS_TOKEN from the environment transparently
picks up the stored token.
"""

from __future__ import annotations

import json
import os
import stat
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

_STORE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".kite_token.json")
_process_env_before_apply: Optional[tuple[Optional[str], Optional[str]]] = None

# Durable storage key (Postgres phase20_kv). The local file is only a warm
# cache — Autoscale instances have ephemeral disks and each deploy starts
# with a fresh filesystem, so the DB copy is authoritative.
_KV_KEY = "kite_token_v1"


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# Kite Connect access tokens expire at 06:00 IST (00:30 UTC) every day.
_IST_OFFSET = timedelta(hours=5, minutes=30)
_EXPIRY_HOUR_IST = 6


def token_expiry_utc(created_at_iso: str) -> Optional[datetime]:
    """Return the UTC datetime when a token created at `created_at_iso`
    expires (the first 06:00 IST strictly after creation). None if unparseable."""
    try:
        created = datetime.fromisoformat(created_at_iso.replace("Z", "+00:00"))
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        created_ist = created + _IST_OFFSET
        expiry_ist = created_ist.replace(hour=_EXPIRY_HOUR_IST, minute=0,
                                         second=0, microsecond=0)
        if created_ist >= expiry_ist:
            expiry_ist += timedelta(days=1)
        return expiry_ist - _IST_OFFSET
    except Exception:
        return None


def is_expired(record: Optional[Dict[str, Any]]) -> bool:
    """True if the stored token record is past its daily 06:00 IST expiry.
    Fail-safe: a record without a parseable created_at is treated as expired
    (a token of unknown age must never be trusted as a live session)."""
    if not record or not record.get("access_token"):
        return True
    expiry = token_expiry_utc(str(record.get("created_at") or ""))
    if expiry is None:
        return True
    return datetime.now(timezone.utc) >= expiry


def _write_file(record: Dict[str, Any]) -> None:
    tmp = _STORE_PATH + ".tmp"
    with open(tmp, "w") as f:
        json.dump(record, f)
    os.chmod(tmp, stat.S_IRUSR | stat.S_IWUSR)  # 0600
    os.replace(tmp, _STORE_PATH)


def _db_load() -> tuple[bool, Optional[Dict[str, Any]]]:
    """Return (authoritative_store_available, record).

    The local cache is only acceptable when Postgres is not configured for
    local/offline development. Once the authoritative store is reachable, an
    absent record is an explicit logout and must override any stale file.
    """
    import phase20_store
    try:
        data = phase20_store.kv_get_durable(_KV_KEY)
    except phase20_store.DurableKVError:
        if phase20_store.db_available():
            raise
        return False, None
    return True, data if isinstance(data, dict) and data.get("access_token") else None


def _db_save(record: Optional[Dict[str, Any]]) -> Optional[bool]:
    """Durably write/delete the token. Failure is intentionally propagated."""
    import phase20_store
    if record is None:
        return phase20_store.kv_delete_durable(_KV_KEY)
    phase20_store.kv_set_durable(_KV_KEY, record)
    return True


def load(include_expired: bool = False) -> Optional[Dict[str, Any]]:
    """Load the stored token record, or None. Never raises.

    Order: durable DB first (survives redeploys / new Autoscale instances),
    then local warm-cache file only for local/offline development. A durable
    DB hit re-warms the local file; an authoritative missing record removes a
    stale cache so logout and token rotation cannot be masked.

    By default an EXPIRED token (past its daily 06:00 IST expiry) is treated
    as absent — callers see "no active session" and must trigger the daily
    login flow. Pass include_expired=True only for metadata/status display.
    """
    try:
        durable_available, durable_record = _db_load()
    except Exception:
        # A configured-but-unreachable authority cannot safely be replaced by
        # an instance-local credential cache.
        return None

    if durable_available:
        if durable_record is None:
            try:
                os.remove(_STORE_PATH)
            except FileNotFoundError:
                pass
            except Exception:
                pass
            return None
        try:
            _write_file(durable_record)
        except Exception:
            pass
        record = durable_record
    else:
        record: Optional[Dict[str, Any]] = None
        try:
            with open(_STORE_PATH, "r") as f:
                data = json.load(f)
            if isinstance(data, dict) and data.get("access_token"):
                record = data
        except Exception:
            pass
    if record is None:
        return None
    if not include_expired and is_expired(record):
        return None
    return record


def resolve_preferred_token() -> tuple[Optional[str], bool]:
    """Resolve a token for a live Kite consumer.

    Returns ``(token, from_store)``. A process token injected by
    :func:`apply_to_env` is never allowed to outlive an authoritative durable
    logout or rotation: every resolution rechecks the shared record. Explicit
    deployment-provided environment tokens remain supported when this process
    has not hydrated one from the store.
    """
    try:
        data = load()
    except Exception:
        data = None
    if data:
        return data.get("access_token") or None, True
    try:
        durable_available, _ = _db_load()
    except Exception:
        # A configured shared authority that cannot be read must fail closed;
        # it is not safe to revive a legacy or instance-local token.
        return None, True
    if durable_available:
        # A reachable shared store that has no valid record is an
        # authoritative logout, not permission to reuse an environment token.
        return None, True
    if _process_env_before_apply is not None:
        return None, True
    return os.environ.get("ZERODHA_ACCESS_TOKEN") or None, False


def save_token(access_token: str, user_id: str = "") -> None:
    """Persist the access token durably (DB) + local warm cache (chmod 600)."""
    if not access_token:
        raise ValueError("access_token required")
    record = {
        "access_token": access_token,
        "user_id": user_id or "",
        "created_at": _now_iso(),
        "last_success_at": None,
        "last_latency_ms": None,
    }
    # The shared copy must commit before a success can be reported. Writing the
    # file first would leave an Autoscale-instance-only "success" that vanishes
    # on the next restart.
    _db_save(record)
    try:
        _write_file(record)
    except Exception:
        # The DB record is sufficient and will re-warm a future instance.
        pass


def record_success(latency_ms: Optional[int] = None) -> None:
    """Record a successful Kite API call (timestamp + latency). Never raises."""
    try:
        data = load()
        if not data:
            return
        data["last_success_at"] = _now_iso()
        if latency_ms is not None:
            data["last_latency_ms"] = latency_ms
        _db_save(data)
        try:
            _write_file(data)
        except Exception:
            pass
    except Exception:
        pass


def clear() -> bool:
    """Delete the stored token (file + durable DB copy)."""
    # Confirm deletion from shared storage before dropping local credentials.
    # If this raises, the caller must not claim the disconnect succeeded.
    durable_removed = _db_save(None)
    try:
        os.remove(_STORE_PATH)
        return True
    except FileNotFoundError:
        # The durable delete was still confirmed, but preserve the historical
        # meaning of `removed`: no local or durable record existed to remove.
        return False


def apply_to_env() -> None:
    """
    Load the stored token into the process environment so all existing
    env-based readers (broker_client, kite_quote_provider, etc.) use it.
    Stored token takes precedence over any static env token.

    An expired token is never exported — a stale env token would make
    presence checks look "configured" while every real call fails.
    """
    global _process_env_before_apply
    data = load()
    if not data:
        return
    if _process_env_before_apply is None:
        # This process-only marker lets disconnect undo a store hydration
        # without changing deployment-provided environment configuration.
        _process_env_before_apply = (
            os.environ.get("ZERODHA_ACCESS_TOKEN"),
            os.environ.get("ZERODHA_TOKEN_TIMESTAMP"),
        )
    os.environ["ZERODHA_ACCESS_TOKEN"] = data["access_token"]
    if data.get("created_at"):
        os.environ["ZERODHA_TOKEN_TIMESTAMP"] = data["created_at"]


def clear_process_hydrated_env() -> None:
    """Undo only credentials injected by apply_to_env(); never touch secrets."""
    global _process_env_before_apply
    if _process_env_before_apply is None:
        return
    token, timestamp = _process_env_before_apply
    if token is None:
        os.environ.pop("ZERODHA_ACCESS_TOKEN", None)
    else:
        os.environ["ZERODHA_ACCESS_TOKEN"] = token
    if timestamp is None:
        os.environ.pop("ZERODHA_TOKEN_TIMESTAMP", None)
    else:
        os.environ["ZERODHA_TOKEN_TIMESTAMP"] = timestamp
    _process_env_before_apply = None


_AUTH_STATE_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), ".kite_auth_state.json")

AUTH_FAILURE_TTL_MINUTES = 10


def record_auth_failure() -> None:
    """Persist a (non-secret) marker that the last token exchange failed."""
    try:
        tmp = _AUTH_STATE_PATH + ".tmp"
        with open(tmp, "w") as f:
            json.dump({"failed_at": _now_iso()}, f)
        os.chmod(tmp, stat.S_IRUSR | stat.S_IWUSR)
        os.replace(tmp, _AUTH_STATE_PATH)
    except Exception:
        pass


def clear_auth_failure() -> None:
    try:
        os.remove(_AUTH_STATE_PATH)
    except FileNotFoundError:
        pass
    except Exception:
        pass


def recent_auth_failure() -> bool:
    """True if a token exchange failed within the last AUTH_FAILURE_TTL_MINUTES."""
    try:
        with open(_AUTH_STATE_PATH, "r") as f:
            data = json.load(f)
        failed_at = datetime.strptime(data["failed_at"], "%Y-%m-%dT%H:%M:%SZ")
        failed_at = failed_at.replace(tzinfo=timezone.utc)
        age_min = (datetime.now(timezone.utc) - failed_at).total_seconds() / 60.0
        return age_min <= AUTH_FAILURE_TTL_MINUTES
    except Exception:
        return False


def metadata() -> Dict[str, Any]:
    """Non-secret metadata about the stored token (no token material).

    `stored` is True only for a VALID (unexpired) token. An expired record
    is reported with stored=False + expired=True so the UI can show
    "Daily Zerodha login required" instead of a silent LOGIN_REQUIRED.
    """
    data = load(include_expired=True)
    if not data:
        return {"stored": False, "expired": False, "created_at": None,
                "expires_at": None, "last_success_at": None,
                "last_latency_ms": None, "user_id": None}
    expired = is_expired(data)
    expiry = token_expiry_utc(str(data.get("created_at") or ""))
    return {
        "stored": not expired,
        "expired": expired,
        "created_at": data.get("created_at"),
        "expires_at": expiry.strftime("%Y-%m-%dT%H:%M:%SZ") if expiry else None,
        "last_success_at": data.get("last_success_at"),
        "last_latency_ms": data.get("last_latency_ms"),
        "user_id": data.get("user_id") or None,
    }
