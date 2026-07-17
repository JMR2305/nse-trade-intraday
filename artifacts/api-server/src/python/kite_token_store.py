"""
kite_token_store.py — Phase 19A: backend-only Kite access-token storage.

Stores the daily Kite Connect access token obtained via the OAuth-style
request_token exchange. The file lives next to the Python modules, is
chmod 0600, and is NEVER exposed through any API response, log line,
export, or frontend state.

Precedence: stored token file > ZERODHA_ACCESS_TOKEN env var.
`apply_to_env()` is called at process start (main.py) so every existing
module that reads ZERODHA_ACCESS_TOKEN from the environment transparently
picks up the stored token.
"""

from __future__ import annotations

import json
import os
import stat
from datetime import datetime, timezone
from typing import Any, Dict, Optional

_STORE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".kite_token.json")

# Durable storage key (Postgres phase20_kv). The local file is only a warm
# cache — Autoscale instances have ephemeral disks and each deploy starts
# with a fresh filesystem, so the DB copy is authoritative.
_KV_KEY = "kite_token_v1"


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _write_file(record: Dict[str, Any]) -> None:
    tmp = _STORE_PATH + ".tmp"
    with open(tmp, "w") as f:
        json.dump(record, f)
    os.chmod(tmp, stat.S_IRUSR | stat.S_IWUSR)  # 0600
    os.replace(tmp, _STORE_PATH)


def _db_load() -> Optional[Dict[str, Any]]:
    try:
        import phase20_store
        data = phase20_store.kv_get(_KV_KEY)
        if isinstance(data, dict) and data.get("access_token"):
            return data
    except Exception:
        pass
    return None


def _db_save(record: Optional[Dict[str, Any]]) -> None:
    try:
        import phase20_store
        phase20_store.kv_set(_KV_KEY, record)
    except Exception:
        pass


def load() -> Optional[Dict[str, Any]]:
    """Load the stored token record, or None. Never raises.

    Order: local warm-cache file first (fast path), then the durable DB
    record (survives redeploys / new Autoscale instances). A DB hit
    re-warms the local file.
    """
    try:
        with open(_STORE_PATH, "r") as f:
            data = json.load(f)
        if isinstance(data, dict) and data.get("access_token"):
            return data
    except Exception:
        pass
    data = _db_load()
    if data:
        try:
            _write_file(data)
        except Exception:
            pass
        return data
    return None


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
    _write_file(record)
    _db_save(record)


def record_success(latency_ms: Optional[int] = None) -> None:
    """Record a successful Kite API call (timestamp + latency). Never raises."""
    try:
        data = load()
        if not data:
            return
        data["last_success_at"] = _now_iso()
        if latency_ms is not None:
            data["last_latency_ms"] = latency_ms
        _write_file(data)
        _db_save(data)
    except Exception:
        pass


def clear() -> bool:
    """Delete the stored token (file + durable DB copy)."""
    _db_save(None)
    try:
        os.remove(_STORE_PATH)
        return True
    except FileNotFoundError:
        return False


def apply_to_env() -> None:
    """
    Load the stored token into the process environment so all existing
    env-based readers (broker_client, kite_quote_provider, etc.) use it.
    Stored token takes precedence over any static env token.
    """
    data = load()
    if not data:
        return
    os.environ["ZERODHA_ACCESS_TOKEN"] = data["access_token"]
    if data.get("created_at"):
        os.environ["ZERODHA_TOKEN_TIMESTAMP"] = data["created_at"]


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
    """Non-secret metadata about the stored token (no token material)."""
    data = load()
    if not data:
        return {"stored": False, "created_at": None,
                "last_success_at": None, "last_latency_ms": None, "user_id": None}
    return {
        "stored": True,
        "created_at": data.get("created_at"),
        "last_success_at": data.get("last_success_at"),
        "last_latency_ms": data.get("last_latency_ms"),
        "user_id": data.get("user_id") or None,
    }
