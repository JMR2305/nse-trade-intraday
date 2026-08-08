"""portfolio_config_overrides.py — durable, cross-process session overrides
for PortfolioConfig limits.

Operators edit limits via PATCH /api/portfolio/config on the Node API server.
Node persists the validated overrides here (Postgres, file fallback) so that
EVERY Python process — the per-request snapshot endpoints AND the running
strategy/execution coordinator (portfolio_bridge pre-check gate) — reads the
merged (env + override) config on its next decision cycle instead of the
frozen env-only PortfolioConfig singleton.

Precedence: env defaults < caller kwargs < operator overrides.
"""
from __future__ import annotations

import json
import logging
import os
from decimal import Decimal
from typing import Any, Dict

logger = logging.getLogger(__name__)

_DIR = os.path.dirname(os.path.abspath(__file__))
_FALLBACK_FILE = os.path.join(_DIR, "portfolio_overrides.json")

# Whitelist of operator-mutable PortfolioConfig fields (mirror of
# MUTABLE_FIELDS in routes/portfolio.ts).  int fields stay int; the rest are
# passed to PortfolioConfig as Decimal via str().
MUTABLE_FIELDS = {
    "max_open_positions": "int",
    "max_pending_orders": "int",
    "max_daily_loss_pct": "dec",
    "max_drawdown_pct": "dec",
    "max_capital_per_strategy_pct": "dec",
    "min_order_value": "dec",
    "max_order_value": "dec",
    "max_instrument_exposure_pct": "dec",
    "max_sector_exposure_pct": "dec",
    "max_strategy_exposure_pct": "dec",
    "max_portfolio_exposure_pct": "dec",
    "cash_reserve_pct": "dec",
    "default_risk_per_trade_pct": "dec",
}

_SCHEMA_READY = False


def _db_available() -> bool:
    try:
        from scan_state_store import db_available
        return db_available()
    except Exception:
        return False


def _connect():
    from scan_state_store import _connect
    return _connect()


def _ensure_schema(conn) -> None:
    global _SCHEMA_READY
    if _SCHEMA_READY:
        return
    with conn.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS portfolio_config_overrides (
                portfolio_id TEXT PRIMARY KEY,
                overrides JSONB NOT NULL,
                updated_at TIMESTAMPTZ DEFAULT NOW()
            )
            """
        )
    conn.commit()
    _SCHEMA_READY = True


def _sanitise(raw: Dict[str, Any]) -> Dict[str, float]:
    """Keep only whitelisted, finite numeric fields."""
    out: Dict[str, float] = {}
    for k, v in (raw or {}).items():
        if k not in MUTABLE_FIELDS:
            continue
        try:
            num = float(v)
        except (TypeError, ValueError):
            continue
        if num != num or num in (float("inf"), float("-inf")):
            continue
        out[k] = int(num) if MUTABLE_FIELDS[k] == "int" else num
    return out


def get_overrides(portfolio_id: str = "default") -> Dict[str, float]:
    """Read persisted overrides. Fail-open to {} — a broken store must never
    take the trading pipeline down (env config still applies)."""
    if os.environ.get("PORTFOLIO_OVERRIDES_DISABLED") == "1":
        return {}  # hermetic-test kill switch
    if _db_available():
        try:
            conn = _connect()
            try:
                _ensure_schema(conn)
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT overrides FROM portfolio_config_overrides "
                        "WHERE portfolio_id = %s",
                        (portfolio_id,),
                    )
                    row = cur.fetchone()
            finally:
                conn.close()
            if row and row[0]:
                payload = row[0] if isinstance(row[0], dict) else json.loads(row[0])
                return _sanitise(payload)
            return {}
        except Exception as exc:
            logger.warning("override DB read failed: %s", exc)
    try:
        with open(_FALLBACK_FILE) as f:
            return _sanitise(json.load(f))
    except Exception:
        return {}


def set_overrides(patch: Dict[str, Any],
                  portfolio_id: str = "default") -> Dict[str, Any]:
    """Merge *patch* into the persisted overrides after validating the merged
    config actually constructs (PortfolioConfig validators are the source of
    truth for ranges/consistency). Raises ValueError on invalid input."""
    clean = _sanitise(patch)
    unknown = [k for k in (patch or {}) if k not in MUTABLE_FIELDS]
    if unknown:
        raise ValueError(f"Unknown or read-only field(s): {', '.join(unknown)}")
    if not clean:
        raise ValueError("No valid override fields supplied")

    if _db_available():
        conn = _connect()
        try:
            _ensure_schema(conn)
            with conn.cursor() as cur:
                from psycopg2.extras import Json
                # Atomic field-level JSONB merge (`||`) so concurrent PATCHes
                # for different fields never overwrite each other. The merged
                # result is validated INSIDE the same transaction: if two
                # individually-valid concurrent patches combine into an
                # invalid config, we roll back rather than persist it.
                cur.execute(
                    """
                    INSERT INTO portfolio_config_overrides (portfolio_id, overrides, updated_at)
                    VALUES (%s, %s, NOW())
                    ON CONFLICT (portfolio_id)
                    DO UPDATE SET
                        overrides = portfolio_config_overrides.overrides || EXCLUDED.overrides,
                        updated_at = NOW()
                    RETURNING overrides
                    """,
                    (portfolio_id, Json(clean)),
                )
                row = cur.fetchone()
            merged = _sanitise(row[0] if isinstance(row[0], dict)
                               else json.loads(row[0])) if row and row[0] else clean
            try:
                build_config(merged)  # raises on invalid combined state
            except Exception:
                conn.rollback()
                raise
            conn.commit()
        finally:
            conn.close()
    else:
        merged = {**get_overrides(portfolio_id), **clean}
        build_config(merged)  # raises on invalid/inconsistent combinations
        with open(_FALLBACK_FILE, "w") as f:
            json.dump(merged, f)
    return merged


def clear_overrides(portfolio_id: str = "default") -> None:
    """Remove all persisted overrides. Raises on DB failure — a clear that
    silently fails would leave running strategies enforcing limits the
    operator believes are gone (no false success)."""
    if _db_available():
        conn = _connect()
        try:
            _ensure_schema(conn)
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM portfolio_config_overrides WHERE portfolio_id = %s",
                    (portfolio_id,),
                )
            conn.commit()
        finally:
            conn.close()
    try:
        os.remove(_FALLBACK_FILE)
    except FileNotFoundError:
        pass


def effective_overrides(portfolio_id: str = "default") -> Dict[str, float]:
    """Overrides that are ACTUALLY enforced by the running bridge: if the
    persisted set no longer constructs a valid config, merged_config()
    fail-opens to env — so report {} here too, never overrides the strategy
    is not enforcing."""
    ov = get_overrides(portfolio_id)
    if not ov:
        return {}
    try:
        build_config(ov)
        return ov
    except Exception as exc:
        logger.warning("persisted overrides invalid; reporting none active: %s", exc)
        return {}


def get_overrides_stamp(portfolio_id: str = "default") -> str | None:
    """Cheap change-detection stamp for long-lived processes: the store's
    updated_at (DB) or file mtime. None = no overrides / store unavailable."""
    if os.environ.get("PORTFOLIO_OVERRIDES_DISABLED") == "1":
        return None
    if _db_available():
        try:
            conn = _connect()
            try:
                _ensure_schema(conn)
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT updated_at FROM portfolio_config_overrides "
                        "WHERE portfolio_id = %s",
                        (portfolio_id,),
                    )
                    row = cur.fetchone()
            finally:
                conn.close()
            return row[0].isoformat() if row and row[0] else None
        except Exception as exc:
            logger.warning("override stamp read failed: %s", exc)
            return None
    try:
        return str(os.path.getmtime(_FALLBACK_FILE))
    except OSError:
        return None


def _to_kwargs(overrides: Dict[str, float]) -> Dict[str, Any]:
    kwargs: Dict[str, Any] = {}
    for k, v in overrides.items():
        kind = MUTABLE_FIELDS.get(k)
        if kind == "int":
            kwargs[k] = int(v)
        elif kind == "dec":
            kwargs[k] = Decimal(str(v))
    return kwargs


def build_config(overrides: Dict[str, float] | None = None, **base_kwargs):
    """Construct a validated PortfolioConfig with operator overrides applied
    on top of *base_kwargs* (which themselves sit on top of env defaults)."""
    from src.portfolio.config import PortfolioConfig
    ov = overrides if overrides is not None else get_overrides(
        str(base_kwargs.get("portfolio_id") or "default"))
    return PortfolioConfig(**{**base_kwargs, **_to_kwargs(ov)})


def merged_config(**base_kwargs):
    """Env + persisted operator overrides. Fail-open: if the persisted
    overrides no longer construct a valid config, fall back to base config
    (env only) with a warning rather than blocking the pipeline."""
    try:
        return build_config(None, **base_kwargs)
    except Exception as exc:
        logger.warning("invalid persisted overrides ignored: %s", exc)
        from src.portfolio.config import PortfolioConfig
        return PortfolioConfig(**base_kwargs)
