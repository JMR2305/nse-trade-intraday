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
    return api_key, token


def creds_present() -> bool:
    k, t = _get_creds()
    return bool(k and t)


# ── Token age / expiry logic ──────────────────────────────────────────────────

def _token_age_hours() -> Optional[float]:
    """Return token age in hours using ZERODHA_TOKEN_TIMESTAMP if set."""
    ts_str = os.environ.get("ZERODHA_TOKEN_TIMESTAMP") or ""
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
        "refresh_instructions": (
            "1. Click Login URL above.\n"
            "2. Log in to Zerodha.\n"
            "3. Copy the access_token from the redirect URL.\n"
            "4. Update ZERODHA_ACCESS_TOKEN secret.\n"
            "5. Set ZERODHA_TOKEN_TIMESTAMP to current UTC ISO timestamp."
        ),
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
        base["error"] = "Credentials not set. Add ZERODHA_API_KEY and ZERODHA_ACCESS_TOKEN secrets."
        base["probe_source"] = "no_credentials"
        return base

    # Check cache
    cache_age = time.monotonic() - _probe_cache_ts
    if not force_probe and cache_age < PROBE_CACHE_TTL_S and _probe_cache:
        base.update(_probe_cache)
        base["probe_cached"] = True
        base["probe_source"] = "cache"
        return base

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

    return base


def invalidate_cache() -> None:
    """Force next get_status() to do a live probe."""
    global _probe_cache, _probe_cache_ts
    _probe_cache = {}
    _probe_cache_ts = 0.0


if __name__ == "__main__":
    import json
    print(json.dumps(get_status(), indent=2))
