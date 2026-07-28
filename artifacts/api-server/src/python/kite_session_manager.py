"""
kite_session_manager.py — Phase 19: Zerodha Kite Connect Session Management

Responsibilities
----------------
* Validate the current access token (age, expiry at 6 AM IST daily).
* Cache the last successful connection probe (60-second TTL) to avoid
  hammering the Kite API on every dashboard poll.
* Generate the Kite login URL for manual daily token refresh.
* Mask all credentials in every outward-facing response.
* Never store or log raw credentials anywhere.

Token lifetime
--------------
Kite Connect access tokens expire at 06:00 IST every day.
Users must re-login daily (or use Kite's automated token generation flow).
ZERODHA_TOKEN_TIMESTAMP can optionally record when the current token was set
(ISO-8601 UTC), giving us a precise age. Without it we estimate conservatively.

Safety: read-only by design — this module never places or modifies orders.
"""

from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────

PROBE_CACHE_TTL_S = 60          # seconds between live Kite API probes
TOKEN_DANGER_HOURS = 20.0       # warn if token is older than this
KITE_TOKEN_EXPIRY_HOUR_IST = 6  # tokens expire at 06:00 IST
IST_OFFSET_HOURS = 5.5          # IST = UTC + 5:30

# ── Module-level cache ────────────────────────────────────────────────────────

_probe_cache: Dict[str, Any] = {}
_probe_cache_ts: float = 0.0


# ── Credential helpers ────────────────────────────────────────────────────────

def _mask(s: Optional[str]) -> str:
    if not s:
        return "(not set)"
    if len(s) <= 6:
        return "****"
    return s[:3] + "****" + s[-2:]


def _get_creds() -> tuple[Optional[str], Optional[str]]:
    api_key = os.environ.get("ZERODHA_API_KEY") or None
    token   = os.environ.get("ZERODHA_ACCESS_TOKEN") or None
    if token:
        # An env token whose recorded timestamp shows it past the daily
        # 06:00 IST expiry must not count as an active session.
        try:
            from kite_quote_provider import _env_token_expired
            if _env_token_expired():
                token = None
        except Exception:
            pass
    if not token:
        try:
            import kite_token_store
            data = kite_token_store.load()
            if data:
                token = data.get("access_token") or None
        except Exception:
            pass
    return api_key, token


def _get_secret() -> Optional[str]:
    return os.environ.get("ZERODHA_API_SECRET") or None


def creds_present() -> bool:
    k, t = _get_creds()
    return bool(k and t)


# ── Token age / expiry logic ──────────────────────────────────────────────────

def _token_age_hours() -> Optional[float]:
    """Return token age in hours using ZERODHA_TOKEN_TIMESTAMP if set."""
    ts_str = os.environ.get("ZERODHA_TOKEN_TIMESTAMP") or ""
    if not ts_str:
        try:
            import kite_token_store
            data = kite_token_store.load()
            if data and data.get("created_at"):
                ts_str = data["created_at"]
        except Exception:
            pass
    if ts_str:
        try:
            ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            age = (datetime.now(timezone.utc) - ts).total_seconds() / 3600
            return round(age, 2)
        except Exception:
            pass
    return None


def _seconds_until_kite_expiry() -> float:
    """Seconds until the next 06:00 IST token expiry."""
    now_utc = datetime.now(timezone.utc)
    ist_offset = timedelta(hours=IST_OFFSET_HOURS)
    now_ist = now_utc + ist_offset

    # Next 06:00 IST
    expiry_today = now_ist.replace(hour=KITE_TOKEN_EXPIRY_HOUR_IST,
                                   minute=0, second=0, microsecond=0)
    if now_ist >= expiry_today:
        expiry_next = expiry_today + timedelta(days=1)
    else:
        expiry_next = expiry_today

    diff = (expiry_next - now_ist).total_seconds()
    return max(0.0, diff)


def _token_status(age_hours: Optional[float]) -> str:
    """
    VALID     — token present and age is safe
    WARNING   — token is older than TOKEN_DANGER_HOURS (approaching expiry)
    EXPIRED   — token almost certainly stale (age > 24 h or < 2 h to expiry)
    MISSING   — no credentials set
    """
    if not creds_present():
        return "MISSING"
    ttl_s = _seconds_until_kite_expiry()
    if ttl_s < 7200:      # < 2 hours to next 06:00 IST → danger zone
        return "WARNING"
    if age_hours is not None and age_hours >= 24:
        return "EXPIRED"
    if age_hours is not None and age_hours >= TOKEN_DANGER_HOURS:
        return "WARNING"
    return "VALID"


# ── Login URL ─────────────────────────────────────────────────────────────────

def get_login_url() -> str:
    """Return the Kite Connect login URL for manual daily token refresh."""
    api_key = os.environ.get("ZERODHA_API_KEY") or ""
    if api_key:
        return f"https://kite.zerodha.com/connect/login?api_key={api_key}&v=3"
    return "https://kite.zerodha.com/connect/login?api_key=YOUR_API_KEY&v=3"


# ── Connection states (Phase 19A) ────────────────────────────────────────────
# NOT_CONFIGURED  — API key or secret missing
# LOGIN_REQUIRED  — configured, but no access token stored
# AUTHENTICATING  — transient (callback in flight; set by frontend)
# CONNECTED       — live probe succeeded
# TOKEN_EXPIRED   — token stale / rejected by Kite
# AUTH_FAILED     — login/token exchange failed (transient, via callback)
# API_ERROR       — token present but Kite API call failed (non-auth error)

def _derive_connection_state(base: Dict[str, Any]) -> str:
    api_key = os.environ.get("ZERODHA_API_KEY") or None
    if not api_key or not _get_secret():
        # Legacy env-token setups without a secret can still be CONNECTED
        if base.get("connected"):
            return "CONNECTED"
        if not api_key:
            return "NOT_CONFIGURED"
        if not base.get("credentials_present"):
            return "NOT_CONFIGURED"
    def _recent_auth_failure() -> bool:
        try:
            import kite_token_store
            return (not base.get("token_stored")
                    and kite_token_store.recent_auth_failure())
        except Exception:
            return False

    if not base.get("credentials_present"):
        return "AUTH_FAILED" if _recent_auth_failure() else "LOGIN_REQUIRED"
    if base.get("connected"):
        return "CONNECTED"
    if base.get("token_status") == "EXPIRED":
        return "TOKEN_EXPIRED"
    if base.get("error"):
        return "API_ERROR"
    if _recent_auth_failure():
        return "AUTH_FAILED"
    return "LOGIN_REQUIRED"


# ── Token exchange (Phase 19A) ───────────────────────────────────────────────

def exchange_request_token(request_token: Optional[str]) -> Dict[str, Any]:
    """
    Exchange a Zerodha request_token for an access token.

    The SHA-256 checksum (api_key + request_token + api_secret) is computed
    backend-only inside kiteconnect.generate_session(). Neither the secret,
    the checksum, the request token, nor the access token is ever included
    in the returned dict or logged.
    """
    api_key = os.environ.get("ZERODHA_API_KEY") or None
    api_secret = _get_secret()

    if not api_key:
        return {"success": False, "state": "NOT_CONFIGURED",
                "error": "ZERODHA_API_KEY is not configured"}
    if not api_secret:
        return {"success": False, "state": "NOT_CONFIGURED",
                "error": "ZERODHA_API_SECRET is not configured"}
    if not request_token or not str(request_token).strip():
        return {"success": False, "state": "AUTH_FAILED",
                "error": "Missing request_token"}

    try:
        from kiteconnect import KiteConnect
        kite = KiteConnect(api_key=api_key)
        session = kite.generate_session(str(request_token).strip(), api_secret=api_secret)
        access_token = session.get("access_token")
        if not access_token:
            return {"success": False, "state": "AUTH_FAILED",
                    "error": "Token exchange returned no access token"}
        user_id = str(session.get("user_id") or "")
        import kite_token_store
        kite_token_store.save_token(access_token, user_id=user_id)
        kite_token_store.clear_auth_failure()
        invalidate_cache()
        logger.info("Kite token exchange succeeded for user %s", _mask(user_id))
        return {"success": True, "state": "CONNECTED",
                "user_id_masked": _mask(user_id)}
    except Exception as exc:
        # Never include token material in errors; Kite errors don't echo secrets.
        err = str(exc)[:200]
        logger.warning("Kite token exchange failed: %s", err)
        import kite_token_store
        kite_token_store.record_auth_failure()
        invalidate_cache()
        return {"success": False, "state": "AUTH_FAILED",
                "error": f"Token exchange failed: {err}"}


def disconnect_session() -> Dict[str, Any]:
    """Clear the stored access token (backend-only). Read-only safe."""
    import kite_token_store
    removed = kite_token_store.clear()
    kite_token_store.clear_auth_failure()
    invalidate_cache()
    return {"success": True, "removed": removed, "state": "LOGIN_REQUIRED",
            "message": "Kite session disconnected. Stored token removed."}


# ── Live probe ────────────────────────────────────────────────────────────────

def _probe_kite() -> Dict[str, Any]:
    """Call kite.profile() to verify the token is live. May raise."""
    from kiteconnect import KiteConnect
    api_key, token = _get_creds()
    kite = KiteConnect(api_key=api_key)
    kite.set_access_token(token)
    t0 = time.monotonic()
    profile = kite.profile()
    latency_ms = int((time.monotonic() - t0) * 1000)
    try:
        import kite_token_store
        kite_token_store.record_success(latency_ms)
    except Exception:
        pass
    return {
        "user_id": profile.get("user_id"),
        "user_name": profile.get("user_name", ""),
        "email_masked": _mask(profile.get("email", "")),
        "latency_ms": latency_ms,
    }


# ── Public API ────────────────────────────────────────────────────────────────

def get_status(force_probe: bool = False) -> Dict[str, Any]:
    """
    Return full session status. Uses cached probe unless expired or forced.
    Never raises — on error returns a degraded status dict.
    """
    global _probe_cache, _probe_cache_ts

    api_key, token = _get_creds()
    age_hours = _token_age_hours()
    tok_status = _token_status(age_hours)
    ttl_s = _seconds_until_kite_expiry()

    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    base: Dict[str, Any] = {
        "phase": 19,
        "provider": "Zerodha Kite Connect",
        "credentials_present": creds_present(),
        "api_key_masked": _mask(api_key),
        "access_token_masked": _mask(token),
        "token_status": tok_status,
        "token_age_hours": age_hours,
        "token_expiry_note": (
            f"Kite tokens expire at 06:00 IST daily. "
            f"~{int(ttl_s / 3600)}h {int((ttl_s % 3600) / 60)}m until next expiry."
        ),
        "login_url": get_login_url(),
        "login_endpoint": "/api/kite/login",
        # The callback URL is injected by the TypeScript route layer, which
        # derives it from the live request host (x-forwarded-host).  It can
        # also be overridden via KITE_CALLBACK_URL for fixed deployments.
        # Included here so the Python status dict is self-contained.
        "expected_callback_url": (
            os.environ.get("KITE_CALLBACK_URL")
            or None
        ),
        "api_secret_configured": bool(_get_secret()),
        "paper_trading_default": True,
        "live_order_placement_enabled": False,
        "checked_at": now_utc,
        "is_mock": not creds_present(),
        "connected": False,
        "error": None,
        "probe_cached": False,
        "probe_source": "mock",
        "user_id": None,
        "user_name": None,
        "latency_ms": None,
    }

    if not creds_present():
        base["error"] = "Not connected. Use the Login with Zerodha button to connect."
        base["probe_source"] = "no_credentials"
        return _finalize(base)

    # Check cache
    cache_age = time.monotonic() - _probe_cache_ts
    if not force_probe and cache_age < PROBE_CACHE_TTL_S and _probe_cache:
        base.update(_probe_cache)
        base["probe_cached"] = True
        base["probe_source"] = "cache"
        return _finalize(base)

    # Live probe
    try:
        probe = _probe_kite()
        _probe_cache = {
            "connected": True,
            "user_id": probe["user_id"],
            "user_name": probe["user_name"],
            "email_masked": probe["email_masked"],
            "latency_ms": probe["latency_ms"],
            "error": None,
            "is_mock": False,
            "probe_source": "live",
        }
        _probe_cache_ts = time.monotonic()
        base.update(_probe_cache)
    except Exception as exc:
        err = str(exc)[:300]
        logger.warning("Kite probe failed: %s", err)
        # Invalidate cache on error
        _probe_cache = {}
        _probe_cache_ts = 0.0
        base["connected"] = False
        base["error"] = err
        base["probe_source"] = "live_failed"
        # If error looks like token issue, upgrade status
        lower = err.lower()
        if "token" in lower or "invalid" in lower or "unauthorised" in lower or "401" in lower:
            base["token_status"] = "EXPIRED"

    return _finalize(base)


def _finalize(base: Dict[str, Any]) -> Dict[str, Any]:
    """Attach token metadata, mask the user id, derive connection_state."""
    try:
        import kite_token_store
        meta = kite_token_store.metadata()
    except Exception:
        meta = {"stored": False, "created_at": None,
                "last_success_at": None, "last_latency_ms": None, "user_id": None}
    base["token_stored"] = meta["stored"]
    base["token_expired"] = bool(meta.get("expired"))
    base["token_expires_at"] = meta.get("expires_at")
    base["daily_login_required"] = bool(meta.get("expired")) or not meta["stored"]
    base["token_created_at"] = meta["created_at"]
    base["last_success_at"] = meta["last_success_at"]
    base["last_latency_ms"] = meta["last_latency_ms"]
    # Mask user id in all outward-facing responses.
    raw_user = base.get("user_id") or meta.get("user_id")
    base["user_id_masked"] = _mask(raw_user) if raw_user else None
    base.pop("user_id", None)
    base["connection_state"] = _derive_connection_state(base)
    return base


def invalidate_cache() -> None:
    """Force next get_status() to do a live probe."""
    global _probe_cache, _probe_cache_ts
    _probe_cache = {}
    _probe_cache_ts = 0.0


if __name__ == "__main__":
    import json
    print(json.dumps(get_status(), indent=2))
