"""
phase20_store.py — Phase 20: durable settings, scan-run history, scheduler
health, and notifications.

All state lives in shared PostgreSQL (DATABASE_URL) so Replit Autoscale
instances agree. The JSON file is only a warm cache and is never trusted to
enable automatic paper entries when durable settings are unavailable.

PAPER TRADING / RESEARCH ONLY. This module never places live orders.
Auto paper entries default OFF and can only be enabled through an explicit
confirmation flow (see update_settings).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

from paper_entry_admission import PAPER_ENTRY_ADMISSION_LOCK_ID

from scan_state_store import db_available, _connect  # shared DB helpers

_DIR = os.path.dirname(os.path.abspath(__file__))
_SETTINGS_FILE = os.path.join(_DIR, "phase20_settings.json")
_SCAN_RUNS_FILE = os.path.join(_DIR, "phase20_scan_runs.json")
_SCHED_FILE = os.path.join(_DIR, "phase20_scheduler_state.json")
_NOTIF_FILE = os.path.join(_DIR, "phase20_notifications.json")

_SCHEMA_READY = False
_IST = ZoneInfo("Asia/Kolkata")
JOB_TYPES = (
    "MARKET_SCAN",
    "POSTMARKET_CACHE_REFRESH",
    "PREMARKET_READINESS_CHECK",
    "SYSTEM_HEARTBEAT",
    "MANUAL_SCAN",
    "INTERNAL_DIAGNOSTIC",
)

ALLOWED_INTERVALS = (3, 4, 5, 6, 10, 15)
FILL_MODELS = ("LAST_TRADED_PRICE", "NEXT_QUOTE", "SLIPPAGE_ADJUSTED")

CONFIRMATION_TEXT = (
    "I understand this will automatically create simulated paper trades only. "
    "No real orders will be placed."
)

# Safe defaults per Phase 20 spec. auto_paper_entries MUST default to False.
DEFAULT_SETTINGS: Dict[str, Any] = {
    # Scanner mode is operational configuration, never a broker execution mode.
    # The process environment provides the initial default; operators may select
    # one of these same validated values from Mission Control.
    "active_intraday_universe": (
        os.environ.get("ACTIVE_INTRADAY_UNIVERSE", "NIFTY_50").upper().strip()
        if os.environ.get("ACTIVE_INTRADAY_UNIVERSE", "NIFTY_50").upper().strip()
        in ("NIFTY_50", "CUSTOM_LOW_PRICE_SECTOR") else "NIFTY_50"
    ),
    "auto_scan_enabled": True,
    "scan_interval_minutes": 5,
    "auto_paper_entries": False,
    "auto_paper_entries_confirmed_at": None,
    "auto_paper_exits": True,
    "min_confidence": 60.0,
    "min_opportunity_score": 60.0,
    "min_trade_quality_score": 50.0,
    "min_risk_reward": 2.0,
    "max_trades_per_day": 3,
    "per_stock_exposure_cap_pct": 25.0,
    "sector_exposure_cap_pct": 40.0,
    "portfolio_deployed_cap_pct": 80.0,
    "risk_per_trade_pct": 1.0,
    "daily_loss_limit_pct": 3.0,
    "circuit_breaker_loss_threshold": 3,
    "perf_alert_enabled": True,
    "perf_alert_consecutive_losses": 3,
    "perf_alert_min_win_rate_pct": 40.0,
    "perf_alert_window_trades": 10,
    "fill_model": "SLIPPAGE_ADJUSTED",
    "slippage_pct": 0.15,
    "charges_pct": 0.12,
    "max_holding_days": 10,
    "square_off_before_close": False,
    "cooldown_minutes": 30,
    # Email alerts (opt-in): also email PERFORMANCE_ALERT and
    # CIRCUIT_BREAKER_TRIPPED notifications to this address.
    "email_alerts_enabled": False,
    "email_alert_address": "",
    # Daily performance summary email at market close (opt-in, same address).
    "daily_summary_email_enabled": False,
    # ── Decision engine gate calibration ────────────────────────────────────
    # When final_confidence >= STRONG_BUY_CONF (85), how many simultaneous
    # filter conditions must fail before the risk gate forces AVOID.
    # Default 2: a single minor failure is demoted to WATCH so operators still
    # see the setup; 2+ failures always force AVOID regardless of confidence.
    # For final_confidence < STRONG_BUY_CONF the gate is always strict (1
    # failure → AVOID). Raise this value for illiquid / mid-cap sectors where
    # individual filter noise is higher; lower it to 1 for maximum strictness.
    "high_conf_avoid_gate_min_failures": 2,
    # ── V4.3 Risk Tuning ────────────────────────────────────────────────────────
    # Maximum number of OPEN paper positions at any time.  0 = disabled (no cap).
    "max_concurrent_positions": 5,
    # Minimum average daily traded volume (thousands of shares).  0 = disabled.
    # Stocks below this threshold are filtered at the entry gate.
    "min_liquidity_filter": 0,
    # Maximum allowed ATR as a percentage of the current price.  0.0 = disabled.
    # Stocks above this volatility level are filtered at the entry gate.
    "max_volatility_filter": 0.0,
    # Research failure mode: "fail_open" lets the pipeline continue with
    # market-only data when all research sources are unavailable;
    # "fail_closed" halts new paper entries until research recovers.
    "research_failure_mode": "fail_open",
    # ── Paper Intraday Learning / Exploration Mode ───────────────────────────
    # When enabled, the scheduler runs SIZE_REDUCED_TO_CAP and
    # EXPERIMENTAL_BUY_FROM_WATCH candidates into experimental_paper_trades.
    # This NEVER touches the canonical phase20 portfolio or places live orders.
    "paper_exploration_mode": False,
    "exploration_max_pct_per_trade": 5.0,       # max % of portfolio per exploration trade
    "exploration_max_trades_per_day": 2,         # daily cap on new experimental entries
    "exploration_max_total_exposure_pct": 10.0,  # max % of portfolio in experimental positions
    "exploration_min_rr": 1.2,                  # minimum risk:reward for exploration entries
    "exploration_min_confidence": 60.0,         # minimum confidence score for exploration entries
    # ── Bootstrap paper trading (ledger seeding when backtest evidence is thin) ──
    # Requires auto_paper_entries ON and confirmed. Defaults to False (safe-off).
    # A bootstrap trade is at most ₹15,000, uses the normal exit engine, and emits
    # trigger_source="BOOTSTRAP_AUTO" so it is permanently distinguishable from
    # normal paper entries. Auto-disables when the ledger reaches 20 closed trades.
    "bootstrap_paper_enabled": False,
    # ── Quality allocation override (paper-only controlled 2x / 3x tiers) ────
    # The policy is enabled, but automatic entries remain safe-off by default.
    # Missing evidence always falls back to NORMAL 1x sizing.
    "quality_allocation_override_enabled": True,
    "quality_allocation_2x_enabled": True,
    "quality_allocation_3x_enabled": True,
    "quality_allocation_2x_min_confidence": 85.0,
    "quality_allocation_2x_min_opportunity_score": 80.0,
    "quality_allocation_2x_min_trade_quality_score": 80.0,
    "quality_allocation_2x_min_risk_reward": 2.5,
    "quality_allocation_2x_risk_budget_pct": 1.5,
    "quality_allocation_3x_min_confidence": 90.0,
    "quality_allocation_3x_min_opportunity_score": 85.0,
    "quality_allocation_3x_min_trade_quality_score": 88.0,
    "quality_allocation_3x_min_risk_reward": 3.0,
    "quality_allocation_3x_risk_budget_pct": 2.0,
    "quality_allocation_3x_max_atr_pct": 3.0,
    "quality_allocation_3x_max_stop_distance_pct": 2.5,
    "quality_allocation_absolute_cap": 30_000.0,
    # Disabled by default.  When enabled, only a qualifying 3x request may use
    # sector capacity above the normal cap, and never above 50%.
    "quality_allocation_3x_sector_override_enabled": False,
    "quality_allocation_3x_sector_override_cap_pct": 50.0,
    # ── Stale-scan exit fallback (Task 791) ─────────────────────────────────────
    # When an exit rule fires on a stale scan AND the trade has been held for at
    # least this many days, the exit engine uses the yfinance daily close as the
    # exit price and records the trade as CLOSED immediately — preventing the
    # position from entering EXIT_PENDING where it would accumulate if Kite LTP
    # stays offline.  Set to 0 to disable (always defer to EXIT_PENDING on stale
    # data, the legacy behaviour).
    "exit_on_stale_after_days": 5,
    # ── Starting capital for paper trading sessions ───────────────────────────
    # Amount of cash each paper trading session starts with. Changes take
    # effect from the NEXT daily session reset (each morning at market open).
    # Min ₹10,000; max ₹5,00,000; stored as a multiple of ₹1,000.
    "initial_capital": 100_000.0,
}

# The approved RTV operating baseline is intentionally explicit rather than
# inferred from a potentially overridden runtime setting. This is a reporting
# control only: it never changes the active scanner universe.
APPROVED_OPERATING_UNIVERSE = "NIFTY_50"

# Keys excluded from the reproducibility config hash (meta, not behaviour).
_HASH_EXCLUDE = {"auto_paper_entries_confirmed_at",
                 "email_alerts_enabled", "email_alert_address",
                 "daily_summary_email_enabled",
                 # research_failure_mode is operational meta, not a signal gate
                 "research_failure_mode"}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: Optional[datetime]) -> Optional[str]:
    if dt is None:
        return None
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _read_json(path: str, default: Any) -> Any:
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return default


def _write_json(path: str, data: Any) -> None:
    try:
        with open(path, "w") as f:
            json.dump(data, f, default=str)
    except Exception:
        pass


def _ensure_schema(conn) -> None:
    global _SCHEMA_READY
    if _SCHEMA_READY:
        return
    with conn.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS phase20_settings (
                id INTEGER PRIMARY KEY,
                data JSONB NOT NULL,
                updated_at TIMESTAMPTZ DEFAULT NOW()
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS phase20_scan_runs (
                id BIGSERIAL PRIMARY KEY,
                scan_id TEXT,
                trigger_source TEXT,
                started_at TIMESTAMPTZ,
                completed_at TIMESTAMPTZ,
                duration_s DOUBLE PRECISION,
                symbols_requested INTEGER,
                symbols_received INTEGER,
                missing_symbols JSONB,
                stale_symbols JSONB,
                unavailable_symbols JSONB,
                provider TEXT,
                status TEXT,
                error TEXT,
                created_at TIMESTAMPTZ DEFAULT NOW()
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS phase20_scheduler_state (
                id INTEGER PRIMARY KEY,
                last_attempt_at TIMESTAMPTZ,
                last_success_at TIMESTAMPTZ,
                last_scan_id TEXT,
                next_due_at TIMESTAMPTZ,
                missed_count INTEGER DEFAULT 0,
                status TEXT,
                detail TEXT,
                updated_at TIMESTAMPTZ DEFAULT NOW()
            )
            """
        )
        # Runtime membership is pinned once per natural IST session.  The
        # version tables remain the source of truth; this table only records
        # which already-immutable revision the running session used.
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS runtime_universe_session_pins (
                natural_session TEXT PRIMARY KEY,
                universe_key TEXT NOT NULL,
                universe_id BIGINT NOT NULL,
                universe_version INTEGER NOT NULL,
                universe_symbols JSONB NOT NULL,
                universe_symbol_count INTEGER NOT NULL,
                universe_set_hash TEXT NOT NULL,
                effective_from TIMESTAMPTZ,
                pinned_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        )
        # Phase 22 production-visibility columns (idempotent).
        for col, typ in (("owner", "TEXT"), ("last_trigger", "TEXT"),
                         ("last_error", "TEXT"), ("heartbeat_at", "TIMESTAMPTZ"),
                         ("process_start_at", "TIMESTAMPTZ")):
            cur.execute(
                f"ALTER TABLE phase20_scheduler_state ADD COLUMN IF NOT EXISTS {col} {typ}"
            )
        # Scan-run timing/perf and Task 857 job-classification columns
        # (idempotent; existing records remain readable as legacy MARKET_SCAN
        # rows through record/list defaults).
        for col, typ in (
            ("timings", "JSONB"), ("perf", "TEXT"),
            ("job_type", "TEXT"), ("scan_type", "TEXT"),
            ("market_state", "TEXT"), ("entry_eligible", "BOOLEAN"),
            ("execution_eligible", "BOOLEAN"), ("source", "TEXT"),
            ("started_at_ist", "TEXT"), ("completed_at_ist", "TEXT"),
            ("details", "JSONB"),
        ):
            cur.execute(
                f"ALTER TABLE phase20_scan_runs ADD COLUMN IF NOT EXISTS {col} {typ}"
            )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS phase20_notifications (
                id BIGSERIAL PRIMARY KEY,
                kind TEXT,
                severity TEXT,
                title TEXT,
                body TEXT,
                context JSONB,
                created_at TIMESTAMPTZ DEFAULT NOW(),
                read BOOLEAN DEFAULT FALSE
            )
            """
        )
    conn.commit()
    _SCHEMA_READY = True


def _with_db(fn, fallback):
    if not db_available():
        return fallback()
    try:
        conn = _connect()
        try:
            _ensure_schema(conn)
            return fn(conn)
        finally:
            conn.close()
    except Exception:
        return fallback()


# ── Settings ──────────────────────────────────────────────────────────────────

def _validate_patch(patch: Dict[str, Any], current: Dict[str, Any]) -> Dict[str, Any]:
    """Validate/coerce a settings patch. Raises ValueError on bad input."""
    clean: Dict[str, Any] = {}
    for key, value in patch.items():
        if key not in DEFAULT_SETTINGS:
            raise ValueError(f"Unknown setting: {key}")
        if key == "auto_paper_entries_confirmed_at":
            continue  # server-managed
        default = DEFAULT_SETTINGS[key]
        if key == "active_intraday_universe":
            if value not in ("NIFTY_50", "CUSTOM_LOW_PRICE_SECTOR"):
                raise ValueError(
                    "active_intraday_universe must be NIFTY_50 or "
                    "CUSTOM_LOW_PRICE_SECTOR")
            clean[key] = value
        if key == "scan_interval_minutes":
            iv = int(value)
            if iv not in ALLOWED_INTERVALS:
                raise ValueError(f"scan_interval_minutes must be one of {ALLOWED_INTERVALS}")
            clean[key] = iv
        elif key == "fill_model":
            if value not in FILL_MODELS:
                raise ValueError(f"fill_model must be one of {FILL_MODELS}")
            clean[key] = value
        elif isinstance(default, bool):
            clean[key] = bool(value)
        elif key == "circuit_breaker_loss_threshold":
            iv = int(float(value))
            if iv < 1 or iv > 10:
                raise ValueError(
                    "circuit_breaker_loss_threshold must be between 1 and 10")
            clean[key] = iv
        elif key == "perf_alert_consecutive_losses":
            iv = int(float(value))
            if iv < 1 or iv > 20:
                raise ValueError(
                    "perf_alert_consecutive_losses must be between 1 and 20")
            clean[key] = iv
        elif key == "perf_alert_min_win_rate_pct":
            num = float(value)
            if num < 0 or num > 100:
                raise ValueError(
                    "perf_alert_min_win_rate_pct must be between 0 and 100")
            clean[key] = num
        elif key == "email_alert_address":
            addr = str(value or "").strip()
            if addr:
                from email_alerts import valid_address
                if not valid_address(addr):
                    raise ValueError(
                        "email_alert_address must be a valid email address")
            clean[key] = addr
        elif key == "perf_alert_window_trades":
            iv = int(float(value))
            if iv < 3 or iv > 100:
                raise ValueError(
                    "perf_alert_window_trades must be between 3 and 100")
            clean[key] = iv
        elif key == "high_conf_avoid_gate_min_failures":
            iv = int(float(value))
            if iv < 1 or iv > 10:
                raise ValueError(
                    "high_conf_avoid_gate_min_failures must be between 1 and 10")
            clean[key] = iv
        # ── V4.3 risk-tuning settings with explicit validation ─────────────
        elif key == "max_concurrent_positions":
            # Must be a whole-number integer; fractional values (e.g. 1.5) are
            # rejected to prevent int("1.5") crashes in evaluate_entries().
            try:
                fv = float(value)
                if fv != int(fv):
                    raise ValueError
                iv = int(fv)
            except (TypeError, ValueError):
                raise ValueError(
                    "max_concurrent_positions must be a whole number (integer)")
            if iv < 0 or iv > 50:
                raise ValueError(
                    "max_concurrent_positions must be between 0 and 50 "
                    "(0 = disabled)")
            clean[key] = iv
        elif key == "min_liquidity_filter":
            try:
                fv = float(value)
            except (TypeError, ValueError):
                raise ValueError("min_liquidity_filter must be a number")
            if fv < 0 or fv > 10_000:
                raise ValueError(
                    "min_liquidity_filter must be between 0 and 10000 "
                    "(thousands of shares; 0 = disabled)")
            clean[key] = fv
        elif key == "max_volatility_filter":
            try:
                fv = float(value)
            except (TypeError, ValueError):
                raise ValueError("max_volatility_filter must be a number")
            if fv < 0 or fv > 100:
                raise ValueError(
                    "max_volatility_filter must be between 0 and 100 "
                    "(ATR as % of price; 0 = disabled)")
            clean[key] = fv
        elif key == "research_failure_mode":
            _VALID_FAILURE_MODES = ("fail_open", "fail_closed")
            if value not in _VALID_FAILURE_MODES:
                raise ValueError(
                    f"research_failure_mode must be one of "
                    f"{_VALID_FAILURE_MODES}; got '{value}'")
            clean[key] = value
        # ── Exploration mode numeric bounds ───────────────────────────────────
        elif key == "exploration_max_pct_per_trade":
            fv = float(value)
            if fv < 1.0 or fv > 20.0:
                raise ValueError("exploration_max_pct_per_trade must be between 1 and 20")
            clean[key] = fv
        elif key == "exploration_max_trades_per_day":
            iv = int(float(value))
            if iv < 1 or iv > 10:
                raise ValueError("exploration_max_trades_per_day must be between 1 and 10")
            clean[key] = iv
        elif key == "exploration_max_total_exposure_pct":
            fv = float(value)
            if fv < 1.0 or fv > 50.0:
                raise ValueError("exploration_max_total_exposure_pct must be between 1 and 50")
            clean[key] = fv
        elif key == "exploration_min_rr":
            fv = float(value)
            if fv < 0.5 or fv > 5.0:
                raise ValueError("exploration_min_rr must be between 0.5 and 5.0")
            clean[key] = fv
        elif key == "exploration_min_confidence":
            fv = float(value)
            if fv < 40.0 or fv > 100.0:
                raise ValueError("exploration_min_confidence must be between 40 and 100")
            clean[key] = fv
        elif key == "initial_capital":
            try:
                fv = float(value)
            except (TypeError, ValueError):
                raise ValueError("initial_capital must be a number")
            if fv < 10_000 or fv > 500_000:
                raise ValueError(
                    "initial_capital must be between ₹10,000 and ₹5,00,000")
            # Snap to nearest ₹1,000
            clean[key] = round(fv / 1_000) * 1_000.0
        elif key in {
            "quality_allocation_2x_min_confidence",
            "quality_allocation_2x_min_opportunity_score",
            "quality_allocation_2x_min_trade_quality_score",
            "quality_allocation_3x_min_confidence",
            "quality_allocation_3x_min_opportunity_score",
            "quality_allocation_3x_min_trade_quality_score",
        }:
            fv = float(value)
            if fv < 0 or fv > 100:
                raise ValueError(f"{key} must be between 0 and 100")
            clean[key] = fv
        elif key in {
            "quality_allocation_2x_min_risk_reward",
            "quality_allocation_3x_min_risk_reward",
        }:
            fv = float(value)
            if fv < 1.0 or fv > 10.0:
                raise ValueError(f"{key} must be between 1.0 and 10.0")
            clean[key] = fv
        elif key in {
            "quality_allocation_2x_risk_budget_pct",
            "quality_allocation_3x_risk_budget_pct",
        }:
            fv = float(value)
            if fv < 1.0 or fv > 2.0:
                raise ValueError(f"{key} must be between 1.0 and 2.0")
            clean[key] = fv
        elif key == "quality_allocation_3x_max_atr_pct":
            fv = float(value)
            if fv < 0.1 or fv > 10.0:
                raise ValueError(
                    "quality_allocation_3x_max_atr_pct must be between 0.1 and 10.0")
            clean[key] = fv
        elif key == "quality_allocation_3x_max_stop_distance_pct":
            fv = float(value)
            if fv < 0.1 or fv > 10.0:
                raise ValueError(
                    "quality_allocation_3x_max_stop_distance_pct must be between 0.1 and 10.0")
            clean[key] = fv
        elif key == "quality_allocation_absolute_cap":
            fv = float(value)
            if fv < 1_000 or fv > 500_000:
                raise ValueError(
                    "quality_allocation_absolute_cap must be between ₹1,000 and ₹5,00,000")
            clean[key] = fv
        elif key == "quality_allocation_3x_sector_override_cap_pct":
            fv = float(value)
            if fv < 40.0 or fv > 50.0:
                raise ValueError(
                    "quality_allocation_3x_sector_override_cap_pct must be between 40 and 50")
            clean[key] = fv
        elif isinstance(default, (int, float)) and not isinstance(default, bool):
            num = float(value)
            if num < 0:
                raise ValueError(f"{key} must be >= 0")
            clean[key] = int(num) if isinstance(default, int) else num
        else:
            clean[key] = value

    projected = {**DEFAULT_SETTINGS, **current}
    projected.update(clean)
    ordered_thresholds = (
        ("quality_allocation_2x_min_confidence",
         "quality_allocation_3x_min_confidence"),
        ("quality_allocation_2x_min_opportunity_score",
         "quality_allocation_3x_min_opportunity_score"),
        ("quality_allocation_2x_min_trade_quality_score",
         "quality_allocation_3x_min_trade_quality_score"),
        ("quality_allocation_2x_min_risk_reward",
         "quality_allocation_3x_min_risk_reward"),
        ("quality_allocation_2x_risk_budget_pct",
         "quality_allocation_3x_risk_budget_pct"),
    )
    for lower_key, higher_key in ordered_thresholds:
        if float(projected[lower_key]) > float(projected[higher_key]):
            raise ValueError(
                f"{higher_key} must be greater than or equal to {lower_key}")
    return clean


def get_settings() -> Dict[str, Any]:
    def from_db(conn):
        with conn.cursor() as cur:
            cur.execute("SELECT data FROM phase20_settings WHERE id = 1")
            row = cur.fetchone()
        stored = row[0] if row and row[0] else {}
        if isinstance(stored, str):
            stored = json.loads(stored)
        return stored

    # Automatic entries are a durable-safety control. A stale local cache must
    # never grant permission when Postgres is missing, unreadable, or malformed.
    stored: Any = {}
    if db_available():
        conn = None
        try:
            conn = _connect()
            _ensure_schema(conn)
            stored = from_db(conn)
        except Exception:
            stored = {}
        finally:
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass
    merged = dict(DEFAULT_SETTINGS)
    if isinstance(stored, dict):
        for k, v in stored.items():
            if k in DEFAULT_SETTINGS:
                merged[k] = v
    # Safety invariant: auto entries require a stored confirmation.
    if merged.get("auto_paper_entries") and not merged.get("auto_paper_entries_confirmed_at"):
        merged["auto_paper_entries"] = False

    # V4.3 normalization — coerce persisted V4.3 settings to their correct
    # types.  Persisted JSON may predate validation (legacy values like
    # "1.5" for an integer field, or an unexpected string for failure mode)
    # and must never cause a runtime crash in evaluate_entries().
    def _coerce_whole_int(v, default: int = 0, lo: int = 0, hi: int = 50) -> int:
        try:
            fv = float(v)
            iv = int(fv)
            # Reject fractional values (e.g. "1.5" → fv=1.5, iv=1, 1 != 1.5)
            if fv != iv:
                return default
            return iv if lo <= iv <= hi else default
        except (TypeError, ValueError):
            return default

    def _coerce_bounded_float(v, default: float = 0.0,
                              lo: float = 0.0, hi: float = 10_000.0) -> float:
        try:
            fv = float(v)
            return fv if lo <= fv <= hi else default
        except (TypeError, ValueError):
            return default

    merged["max_concurrent_positions"] = _coerce_whole_int(
        merged.get("max_concurrent_positions"), default=0, lo=0, hi=50
    )
    merged["min_liquidity_filter"] = _coerce_bounded_float(
        merged.get("min_liquidity_filter"), default=0.0, lo=0.0, hi=10_000.0
    )
    merged["max_volatility_filter"] = _coerce_bounded_float(
        merged.get("max_volatility_filter"), default=0.0, lo=0.0, hi=100.0
    )
    if merged.get("research_failure_mode") not in ("fail_open", "fail_closed"):
        merged["research_failure_mode"] = "fail_open"  # safe default

    merged["config_hash"] = config_hash(merged)
    merged["confirmation_text"] = CONFIRMATION_TEXT
    return merged


def operating_universe_verification(
    settings: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Report whether the active universe matches the approved RTV baseline.

    This is intentionally read-only. A mismatch is an operator-review signal,
    not permission for code to silently switch the scan universe or alter any
    strategy threshold.
    """
    active = str(
        (settings if settings is not None else get_settings()).get(
            "active_intraday_universe", ""
        )
    ).upper().strip()
    valid = active in ("NIFTY_50", "CUSTOM_LOW_PRICE_SECTOR")
    matches = valid and active == APPROVED_OPERATING_UNIVERSE
    return {
        "approved_baseline": APPROVED_OPERATING_UNIVERSE,
        "active_universe": active or None,
        "active_universe_valid": valid,
        "matches_approved_baseline": matches,
        "status": "PASS" if matches else "REVIEW_REQUIRED",
        "detail": (
            "Active universe matches the approved operating baseline."
            if matches else
            "Active universe differs from the approved operating baseline; "
            "review the persisted operator setting before the next session. "
            "No setting was changed by this verification."
        ),
    }


def _persist_settings(data: Dict[str, Any]) -> None:
    payload = {k: v for k, v in data.items() if k in DEFAULT_SETTINGS}

    def to_db(conn):
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO phase20_settings (id, data, updated_at)
                VALUES (1, %s, NOW())
                ON CONFLICT (id) DO UPDATE SET data = EXCLUDED.data, updated_at = NOW()
                """,
                (json.dumps(payload),),
            )
        conn.commit()
        return True

    _with_db(to_db, lambda: None)
    _write_json(_SETTINGS_FILE, payload)  # warm local copy always


def update_settings(patch: Dict[str, Any],
                    confirmation_text: Optional[str] = None) -> Dict[str, Any]:
    """
    Apply a validated settings patch.

    Enabling auto_paper_entries requires the exact confirmation text — the
    manual "simulated paper trades only" acknowledgement. Disabling never
    requires confirmation.
    """
    current = get_settings()
    clean = _validate_patch(patch, current)

    # Capital changes are a portfolio-accounting boundary, not an ordinary
    # settings edit.  They must query the full OPEN + EXIT_PENDING ledger under
    # a database lock and require separate operator confirmation.  Keeping this
    # guard here prevents the generic settings API from bypassing the migration.
    if (
        "initial_capital" in clean
        and float(clean["initial_capital"])
        != float(current.get("initial_capital") or 0.0)
    ):
        raise ValueError(
            "initial_capital changes require the guarded "
            "POST /api/phase20/capital-migration endpoint"
        )

    if clean.get("auto_paper_entries") is True and not current.get("auto_paper_entries"):
        if (confirmation_text or "").strip() != CONFIRMATION_TEXT:
            raise ValueError(
                "Enabling automatic paper entries requires the exact confirmation "
                "statement. No settings were changed."
            )
        current["auto_paper_entries_confirmed_at"] = _iso(_now())
    if clean.get("auto_paper_entries") is False:
        current["auto_paper_entries_confirmed_at"] = None

    current.update(clean)
    _persist_settings(current)
    return get_settings()


def config_hash(settings: Optional[Dict[str, Any]] = None) -> str:
    s = settings if settings is not None else get_settings()
    core = {k: s.get(k, DEFAULT_SETTINGS.get(k)) for k in DEFAULT_SETTINGS
            if k not in _HASH_EXCLUDE}
    blob = json.dumps(core, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


# ── Scan-run history ─────────────────────────────────────────────────────────

def _to_ist_iso(value: Any) -> Optional[str]:
    """Format a persisted UTC-ish timestamp for an operator-facing IST record."""
    if not value:
        return None
    try:
        if isinstance(value, datetime):
            dt = value
        else:
            dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(_IST).isoformat()
    except Exception:
        return None


def _job_type_for(run: Dict[str, Any]) -> str:
    supplied = str(run.get("job_type") or "").upper()
    if supplied in JOB_TYPES:
        return supplied
    trigger = str(run.get("trigger_source") or "").upper()
    return "MANUAL_SCAN" if trigger == "MANUAL" else "MARKET_SCAN"


_SAFE_APPROVAL_CONTEXTS = {
    "OPERATOR_REQUEST",
    "RELEASE_VALIDATION",
    "INCIDENT_RESPONSE",
}
_SAFE_AUDIT_REFERENCE = re.compile(
    r"^(?!API-|KEY-|TOKEN-|SECRET-)[A-Z]{2,12}-(?:\d{1,8}|[A-Z0-9]{1,12}-20\d{2}-\d{2}-\d{2})$"
)
_SAFE_SCAN_AUDIT_ID = re.compile(
    r"^(?:\d{1,20}|scan-[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})$",
    re.I,
)


def sanitize_scan_provenance(provenance: Any) -> Dict[str, Any]:
    """Return a small allowlisted audit record with no credentials or secrets.

    Provenance enters Python through a request boundary, but this second
    validation makes direct CLI callers and future routes equally safe.  Values
    must be short, plain labels; arbitrary nested objects and token-like request
    data are never persisted.
    """
    if not isinstance(provenance, dict):
        return {}
    clean: Dict[str, Any] = {}
    actor = provenance.get("actor")
    if actor in {"authenticated_operator", "anonymous_operator", "system"}:
        clean["actor"] = actor
    actor_source = provenance.get("actor_source")
    if actor_source in {"SESSION_AUTHENTICATED", "UNATTRIBUTED_MANUAL", "SYSTEM"}:
        clean["actor_source"] = actor_source
    request_id = provenance.get("request_id")
    if isinstance(request_id, str) and request_id.isdecimal() and len(request_id) <= 20:
        clean["request_id"] = request_id
    approval_context = provenance.get("approval_context")
    if isinstance(approval_context, str) and approval_context in _SAFE_APPROVAL_CONTEXTS:
        clean["approval_context"] = approval_context
    audit_reference = provenance.get("audit_reference")
    if isinstance(audit_reference, str) and _SAFE_AUDIT_REFERENCE.fullmatch(audit_reference):
        clean["audit_reference"] = audit_reference
    if provenance.get("trigger_route") == "/api/live-data/scan/run":
        clean["trigger_route"] = "/api/live-data/scan/run"
    actor_type = provenance.get("actor_type")
    if actor_type in {
        "operator_api", "operator_cli", "internal_diagnostic", "unknown_legacy",
    }:
        clean["actor_type"] = actor_type
    actor_id_or_label = provenance.get("actor_id_or_label")
    if actor_id_or_label in {"unavailable", "system"}:
        clean["actor_id_or_label"] = actor_id_or_label
    request_endpoint = provenance.get("request_endpoint")
    if request_endpoint in {"/api/live-data/scan/run", "CLI"}:
        clean["request_endpoint"] = request_endpoint
    request_method = provenance.get("request_method")
    if request_method in {"POST", "PROCESS"}:
        clean["request_method"] = request_method
    for field in ("request_id", "correlation_id"):
        value = provenance.get(field)
        if isinstance(value, str) and _SAFE_SCAN_AUDIT_ID.fullmatch(value):
            clean[field] = value
    trigger_source = provenance.get("trigger_source")
    if trigger_source in {
        "MISSION_CONTROL_UI", "API_MANUAL_SCAN", "ADMIN_TOOL",
        "INTERNAL_DIAGNOSTIC", "TEST", "UNKNOWN_LEGACY",
    }:
        clean["trigger_source"] = trigger_source
    if provenance.get("approval_required") is False:
        clean["approval_required"] = False
    approval_status = provenance.get("approval_status")
    if approval_status in {"NOT_REQUIRED", "APPROVED", "REJECTED", "UNKNOWN"}:
        clean["approval_status"] = approval_status
    approval_id = provenance.get("approval_id")
    if (isinstance(approval_id, str)
            and _SAFE_AUDIT_REFERENCE.fullmatch(approval_id)):
        clean["approval_id"] = approval_id
    requested_at = provenance.get("requested_at")
    if isinstance(requested_at, str):
        try:
            stamp = datetime.fromisoformat(requested_at.replace("Z", "+00:00"))
            if stamp.tzinfo is not None:
                clean["requested_at"] = stamp.isoformat()
        except (TypeError, ValueError):
            pass
    return clean


def history_scan_provenance(details: Any, job_type: Any) -> Dict[str, Any]:
    """Return display-safe manual-scan provenance without rewriting old rows."""
    provenance = sanitize_scan_provenance(
        details.get("provenance") if isinstance(details, dict) else None,
    )
    if str(job_type or "").upper() != "MANUAL_SCAN":
        return provenance
    if provenance.get("actor_type"):
        return {**provenance, "legacy": False}
    # This presentation-only fallback preserves the absence of historical
    # evidence. It is never written back to a legacy scan record.
    return {
        "actor_type": None,
        "actor_id_or_label": None,
        "request_endpoint": None,
        "request_method": None,
        "request_id": None,
        "correlation_id": None,
        "trigger_source": "UNKNOWN_LEGACY",
        "approval_required": None,
        "approval_status": "UNKNOWN",
        "approval_id": None,
        "requested_at": None,
        "legacy": True,
    }


def sanitize_scan_details(details: Any) -> Dict[str, Any]:
    """Return history-safe details without exposing raw provenance JSON."""
    safe_details = dict(details) if isinstance(details, dict) else {}
    safe_details.pop("provenance", None)
    provenance = sanitize_scan_provenance(
        details.get("provenance") if isinstance(details, dict) else None,
    )
    if provenance:
        safe_details["provenance"] = provenance
    return safe_details


def record_scan_run(run: Dict[str, Any]) -> None:
    """Append one classified scheduler, scan, or maintenance job record.

    This is the durable operator-facing stream. Existing callers that do not
    yet supply Task 857 metadata remain compatible and are classified from
    their trigger source.
    """
    job_type = _job_type_for(run)
    started_at = run.get("started_at")
    completed_at = run.get("completed_at")
    row = {
        "scan_id": run.get("scan_id"),
        "trigger_source": (run.get("trigger_source") or "MANUAL").upper(),
        "job_type": job_type,
        "scan_type": run.get("scan_type") or (
            "CANONICAL" if job_type == "MARKET_SCAN" else "NON_MARKET"
        ),
        "market_state": str(run.get("market_state") or "UNKNOWN").upper(),
        "entry_eligible": bool(run.get("entry_eligible", False)),
        "execution_eligible": bool(run.get("execution_eligible", False)),
        "source": str(run.get("source") or run.get("trigger_source") or "MANUAL").upper(),
        "started_at": started_at,
        "completed_at": completed_at,
        "started_at_ist": run.get("started_at_ist") or _to_ist_iso(started_at),
        "completed_at_ist": run.get("completed_at_ist") or _to_ist_iso(completed_at),
        "duration_s": run.get("duration_s"),
        "symbols_requested": run.get("symbols_requested"),
        "symbols_received": run.get("symbols_received"),
        "missing_symbols": run.get("missing_symbols") or [],
        "stale_symbols": run.get("stale_symbols") or [],
        "unavailable_symbols": run.get("unavailable_symbols") or [],
        "provider": run.get("provider"),
        "status": run.get("status") or "UNKNOWN",
        "error": (str(run.get("error"))[:500] if run.get("error") else None),
        "timings": run.get("timings") or None,
        "perf": run.get("perf") or None,
        "details": sanitize_scan_details({
            **(run.get("details") or {}),
            **({"universe_context": run.get("universe_context")}
               if run.get("universe_context") else {}),
        }),
        "created_at": _iso(_now()),
    }

    def to_db(conn):
        _ensure_schema(conn)
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO phase20_scan_runs (
                    scan_id, trigger_source, started_at, completed_at, duration_s,
                    symbols_requested, symbols_received, missing_symbols,
                    stale_symbols, unavailable_symbols, provider, status, error,
                    timings, perf, job_type, scan_type, market_state,
                    entry_eligible, execution_eligible, source, started_at_ist,
                    completed_at_ist, details
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                          %s,%s,%s,%s,%s,%s,%s,%s,%s)
                """,
                (
                    row["scan_id"], row["trigger_source"], row["started_at"],
                    row["completed_at"], row["duration_s"],
                    row["symbols_requested"], row["symbols_received"],
                    json.dumps(row["missing_symbols"]),
                    json.dumps(row["stale_symbols"]),
                    json.dumps(row["unavailable_symbols"]),
                    row["provider"], row["status"], row["error"],
                    json.dumps(row["timings"]) if row["timings"] else None,
                    row["perf"],
                    row["job_type"], row["scan_type"], row["market_state"],
                    row["entry_eligible"], row["execution_eligible"], row["source"],
                    row["started_at_ist"], row["completed_at_ist"],
                    json.dumps(row["details"]),
                ),
            )
        conn.commit()
        return True

    def to_file():
        runs = _read_json(_SCAN_RUNS_FILE, [])
        runs.append(row)
        _write_json(_SCAN_RUNS_FILE, runs[-200:])

    _with_db(to_db, to_file)


def list_scan_runs(limit: int = 50) -> List[Dict[str, Any]]:
    def from_db(conn):
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT scan_id, trigger_source, started_at, completed_at,
                       duration_s, symbols_requested, symbols_received,
                       missing_symbols, stale_symbols, unavailable_symbols,
                       provider, status, error, created_at, timings, perf,
                       job_type, scan_type, market_state, entry_eligible,
                       execution_eligible, source, started_at_ist,
                       completed_at_ist, details
                FROM phase20_scan_runs ORDER BY id DESC LIMIT %s
                """,
                (int(limit),),
            )
            rows = cur.fetchall()
        out = []
        for r in rows:
            job_type = r[16] or (
                "MANUAL_SCAN" if str(r[1] or "").upper() == "MANUAL"
                else "MARKET_SCAN"
            )
            out.append({
                "scan_id": r[0], "trigger_source": r[1],
                "started_at": _iso(r[2]) if isinstance(r[2], datetime) else r[2],
                "completed_at": _iso(r[3]) if isinstance(r[3], datetime) else r[3],
                "duration_s": r[4],
                "symbols_requested": r[5], "symbols_received": r[6],
                "missing_symbols": r[7] or [], "stale_symbols": r[8] or [],
                "unavailable_symbols": r[9] or [],
                "provider": r[10], "status": r[11], "error": r[12],
                "created_at": _iso(r[13]) if isinstance(r[13], datetime) else r[13],
                "timings": r[14], "perf": r[15],
                "job_type": job_type,
                "scan_type": r[17] or "CANONICAL",
                "market_state": r[18] or "UNKNOWN",
                "entry_eligible": bool(r[19]),
                "execution_eligible": bool(r[20]),
                "source": r[21] or r[1],
                "started_at_ist": r[22] or _to_ist_iso(r[2]),
                "completed_at_ist": r[23] or _to_ist_iso(r[3]),
                "details": sanitize_scan_details(r[24]),
                "provenance": history_scan_provenance(r[24], job_type),
            })
        return out

    def from_file():
        rows = list(reversed(_read_json(_SCAN_RUNS_FILE, [])))[:limit]
        out = []
        for saved in rows:
            row = dict(saved) if isinstance(saved, dict) else {}
            details = row.get("details")
            row["details"] = sanitize_scan_details(details)
            row["provenance"] = history_scan_provenance(
                details, _job_type_for(row),
            )
            out.append(row)
        return out

    return _with_db(from_db, from_file)


def list_jobs_today_ist(limit: int = 100) -> List[Dict[str, Any]]:
    """Return the classified durable jobs for the current IST calendar day."""
    try:
        from scan_state_store import ist_day_bounds_utc
        start, end = ist_day_bounds_utc()
    except Exception:
        start, end = (_now() - timedelta(days=1), _now() + timedelta(days=1))

    def from_db(conn):
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT scan_id, trigger_source, started_at, completed_at,
                       duration_s, symbols_requested, symbols_received,
                       missing_symbols, stale_symbols, unavailable_symbols,
                       provider, status, error, created_at, timings, perf,
                       job_type, scan_type, market_state, entry_eligible,
                       execution_eligible, source, started_at_ist,
                       completed_at_ist, details
                FROM phase20_scan_runs
                WHERE COALESCE(completed_at, started_at, created_at) >= %s
                  AND COALESCE(completed_at, started_at, created_at) < %s
                ORDER BY COALESCE(completed_at, started_at, created_at) DESC
                LIMIT %s
                """,
                (start, end, int(limit)),
            )
            rows = cur.fetchall()
        # Keep the serialisation contract in exactly one place.
        return _serialize_job_rows(rows)

    def from_file():
        rows = list_scan_runs(limit=200)
        return rows[:limit]

    return _with_db(from_db, from_file)


def _serialize_job_rows(rows: List[Any]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for r in rows:
        trigger = r[1]
        job_type = r[16] or (
            "MANUAL_SCAN" if str(trigger or "").upper() == "MANUAL"
            else "MARKET_SCAN"
        )
        out.append({
            "scan_id": r[0], "trigger_source": trigger,
            "started_at": _iso(r[2]) if isinstance(r[2], datetime) else r[2],
            "completed_at": _iso(r[3]) if isinstance(r[3], datetime) else r[3],
            "duration_s": r[4], "symbols_requested": r[5], "symbols_received": r[6],
            "missing_symbols": r[7] or [], "stale_symbols": r[8] or [],
            "unavailable_symbols": r[9] or [], "provider": r[10],
            "status": r[11], "error": r[12],
            "created_at": _iso(r[13]) if isinstance(r[13], datetime) else r[13],
            "timings": r[14], "perf": r[15],
            "job_type": job_type,
            "scan_type": r[17] or "CANONICAL",
            "market_state": r[18] or "UNKNOWN",
            "entry_eligible": bool(r[19]),
            "execution_eligible": bool(r[20]),
            "source": r[21] or trigger,
            "started_at_ist": r[22] or _to_ist_iso(r[2]),
            "completed_at_ist": r[23] or _to_ist_iso(r[3]),
            "details": sanitize_scan_details(r[24]),
            "provenance": history_scan_provenance(r[24], job_type),
        })
    return out


# ── Scheduler health ─────────────────────────────────────────────────────────

def update_scheduler_state(**fields: Any) -> None:
    """
    Merge scheduler-state fields. Supported: last_attempt_at, last_success_at,
    last_scan_id, next_due_at, missed_increment (int), status, detail.
    """
    now = _now()
    missed_inc = int(fields.pop("missed_increment", 0) or 0)

    def to_db(conn):
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM phase20_scheduler_state WHERE id = 1")
            exists = cur.fetchone() is not None
            if not exists:
                cur.execute(
                    "INSERT INTO phase20_scheduler_state (id, missed_count) VALUES (1, 0)"
                )
            sets = ["updated_at = NOW()"]
            vals: List[Any] = []
            for col in ("last_attempt_at", "last_success_at", "last_scan_id",
                        "next_due_at", "status", "detail",
                        "owner", "last_trigger", "last_error", "heartbeat_at",
                        "process_start_at"):
                if col in fields:
                    sets.append(f"{col} = %s")
                    vals.append(fields[col])
            if missed_inc:
                sets.append("missed_count = COALESCE(missed_count,0) + %s")
                vals.append(missed_inc)
            cur.execute(
                f"UPDATE phase20_scheduler_state SET {', '.join(sets)} WHERE id = 1",
                vals,
            )
        conn.commit()
        return True

    def to_file():
        st = _read_json(_SCHED_FILE, {})
        for col in ("last_attempt_at", "last_success_at", "last_scan_id",
                    "next_due_at", "status", "detail",
                    "owner", "last_trigger", "last_error", "heartbeat_at",
                    "process_start_at"):
            if col in fields:
                st[col] = fields[col]
        if missed_inc:
            st["missed_count"] = int(st.get("missed_count", 0)) + missed_inc
        st["updated_at"] = _iso(now)
        _write_json(_SCHED_FILE, st)

    _with_db(to_db, to_file)


def get_scheduler_health() -> Dict[str, Any]:
    def from_db(conn):
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT last_attempt_at, last_success_at, last_scan_id, next_due_at,
                       missed_count, status, detail, updated_at,
                       owner, last_trigger, last_error, heartbeat_at,
                       process_start_at
                FROM phase20_scheduler_state WHERE id = 1
                """
            )
            row = cur.fetchone()
            cur.execute(
                "SELECT holder, acquired_at, expires_at FROM scan_lock WHERE name = 'phase7_scan'"
            )
            lock = cur.fetchone()
        st: Dict[str, Any] = {}
        if row:
            st = {
                "last_attempt_at": _iso(row[0]) if isinstance(row[0], datetime) else row[0],
                "last_success_at": _iso(row[1]) if isinstance(row[1], datetime) else row[1],
                "last_scan_id": row[2],
                "next_due_at": _iso(row[3]) if isinstance(row[3], datetime) else row[3],
                "missed_count": row[4] or 0,
                "status": row[5],
                "detail": row[6],
                "updated_at": _iso(row[7]) if isinstance(row[7], datetime) else row[7],
                "owner": row[8],
                "last_trigger": row[9],
                "last_error": row[10],
                "heartbeat_at": _iso(row[11]) if isinstance(row[11], datetime) else row[11],
                "process_start_at": _iso(row[12]) if isinstance(row[12], datetime) else row[12],
            }
        if lock:
            st["lock"] = {
                "holder": lock[0],
                "acquired_at": _iso(lock[1]) if isinstance(lock[1], datetime) else lock[1],
                "expires_at": _iso(lock[2]) if isinstance(lock[2], datetime) else lock[2],
            }
        else:
            st["lock"] = None
        return st

    def from_file():
        st = _read_json(_SCHED_FILE, {})
        st.setdefault("missed_count", 0)
        st["lock"] = None
        return st

    health = _with_db(from_db, from_file)
    settings = get_settings()
    interval = int(settings.get("scan_interval_minutes", 5))
    health["interval_minutes"] = interval
    health["auto_scan_enabled"] = bool(settings.get("auto_scan_enabled", True))

    # Derive a health verdict using the canonical enum shared with the
    # validation module and the frontend:
    #   HEALTHY / DEGRADED / DOWN / UNKNOWN / DISABLED
    verdict = "HEALTHY"
    if not health["auto_scan_enabled"]:
        verdict = "DISABLED"
    else:
        last = health.get("last_attempt_at")
        if not last:
            verdict = "UNKNOWN"
        else:
            try:
                last_dt = datetime.fromisoformat(str(last).replace("Z", "+00:00"))
                if _now() - last_dt > timedelta(minutes=interval * 3):
                    verdict = "DOWN"
                elif int(health.get("missed_count") or 0) > 0:
                    verdict = "DEGRADED"
            except Exception:
                verdict = "UNKNOWN"
    health["health"] = verdict
    return health


# ── Generic durable KV (evaluation snapshots, pending-data events, etc.) ─────

def _kv_file_lock():
    """Exclusive cross-process lock for ALL mutations of the KV fallback
    file. Every file-backed KV write (kv_set, kv_claim_once) MUST hold it —
    an unlocked read-modify-write can overwrite claims made concurrently."""
    import fcntl
    from contextlib import contextmanager

    @contextmanager
    def _lock():
        path = os.path.join(_DIR, "phase20_kv.json.lock")
        fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o644)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            try:
                fcntl.flock(fd, fcntl.LOCK_UN)
            finally:
                os.close(fd)

    return _lock()


def _ensure_kv_table(cur) -> None:
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS phase20_kv (
            key TEXT PRIMARY KEY,
            value JSONB,
            updated_at TIMESTAMPTZ DEFAULT NOW()
        )
        """
    )


class DurableKVError(RuntimeError):
    """A required shared-KV operation could not be confirmed."""


def _durable_kv_connection():
    """Open the shared KV database without the normal local-file fallback."""
    if not db_available():
        raise DurableKVError("Phase-20 durable KV is not configured")
    try:
        return _connect()
    except Exception as exc:
        raise DurableKVError("Phase-20 durable KV is unavailable") from exc


def kv_set_durable(key: str, value: Any) -> None:
    """Persist a KV value to PostgreSQL or raise.

    Credential/session flows must not use the regular KV fallback: a local
    file can disappear after an Autoscale restart and cannot confirm that the
    shared state was updated.
    """
    conn = _durable_kv_connection()
    try:
        with conn.cursor() as cur:
            _ensure_kv_table(cur)
            cur.execute(
                """
                INSERT INTO phase20_kv (key, value, updated_at)
                VALUES (%s, %s, NOW())
                ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = NOW()
                """,
                (key, json.dumps(value, default=str)),
            )
        conn.commit()
    except Exception as exc:
        try:
            conn.rollback()
        except Exception:
            pass
        raise DurableKVError("Phase-20 durable KV write failed") from exc
    finally:
        conn.close()


def kv_delete_durable(key: str) -> bool:
    """Delete a shared KV value and confirm the durable deletion.

    A False result means the durable record was already absent; it is still a
    successful confirmation that a fresh instance will not restore the value.
    """
    conn = _durable_kv_connection()
    try:
        with conn.cursor() as cur:
            _ensure_kv_table(cur)
            cur.execute("DELETE FROM phase20_kv WHERE key = %s", (key,))
            removed = cur.rowcount > 0
        conn.commit()
        return removed
    except Exception as exc:
        try:
            conn.rollback()
        except Exception:
            pass
        raise DurableKVError("Phase-20 durable KV delete failed") from exc
    finally:
        conn.close()


def kv_get_durable(key: str, default: Any = None) -> Any:
    """Read shared KV state without accepting the local fallback as truth."""
    conn = _durable_kv_connection()
    try:
        with conn.cursor() as cur:
            _ensure_kv_table(cur)
            cur.execute("SELECT value FROM phase20_kv WHERE key = %s", (key,))
            row = cur.fetchone()
        conn.commit()
    except Exception as exc:
        try:
            conn.rollback()
        except Exception:
            pass
        raise DurableKVError("Phase-20 durable KV read failed") from exc
    finally:
        conn.close()
    if row is None:
        return default
    value = row[0]
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except Exception:
            pass
    return value


def kv_set(key: str, value: Any) -> None:
    def to_db(conn):
        with conn.cursor() as cur:
            _ensure_kv_table(cur)
            cur.execute(
                """
                INSERT INTO phase20_kv (key, value, updated_at)
                VALUES (%s, %s, NOW())
                ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = NOW()
                """,
                (key, json.dumps(value, default=str)),
            )
        conn.commit()
        return True

    def to_file():
        with _kv_file_lock():
            data = _read_json(os.path.join(_DIR, "phase20_kv.json"), {})
            data[key] = value
            _write_json(os.path.join(_DIR, "phase20_kv.json"), data)

    _with_db(to_db, to_file)


def kv_claim_once(key: str, ttl_seconds: int = 0) -> bool:
    """Atomically claim a KV key. Returns True only for the FIRST claimant
    (cross-process safe): DB path uses INSERT ... ON CONFLICT DO NOTHING in a
    single statement; file fallback serialises with flock. Use for
    exactly-once notification guards.

    ``ttl_seconds`` is accepted for forward-compatibility (callers that use
    date-keyed claims for daily-once semantics) but the TTL is currently
    enforced by the caller rotating the key (e.g. including today's date in
    the key).  The parameter is intentionally ignored here so callers can
    document intent without breaking the interface."""
    def to_db(conn):
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS phase20_kv (
                    key TEXT PRIMARY KEY,
                    value JSONB,
                    updated_at TIMESTAMPTZ DEFAULT NOW()
                )
                """
            )
            cur.execute(
                """
                INSERT INTO phase20_kv (key, value, updated_at)
                VALUES (%s, %s, NOW())
                ON CONFLICT (key) DO NOTHING
                """,
                (key, json.dumps(True)),
            )
            claimed = cur.rowcount == 1
        conn.commit()
        return claimed

    def to_file():
        path = os.path.join(_DIR, "phase20_kv.json")
        with _kv_file_lock():
            data = _read_json(path, {})
            if key in data:
                return False
            data[key] = True
            _write_json(path, data)
            return True

    return bool(_with_db(to_db, to_file))


def kv_claim_with_value(key: str, value: Any) -> bool:
    """Like kv_claim_once but stores ``value`` (a JSON-serialisable dict)
    instead of ``True``.  Atomic: exactly one caller succeeds per key.

    Use when callers need to embed metadata (e.g. timestamps, owner tokens)
    inside the claim record itself rather than writing a second key.
    Returns True if this caller successfully created the claim."""

    def to_db(conn):
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS phase20_kv (
                    key TEXT PRIMARY KEY,
                    value JSONB,
                    updated_at TIMESTAMPTZ DEFAULT NOW()
                )
                """
            )
            cur.execute(
                """
                INSERT INTO phase20_kv (key, value, updated_at)
                VALUES (%s, %s, NOW())
                ON CONFLICT (key) DO NOTHING
                """,
                (key, json.dumps(value, default=str)),
            )
            claimed = cur.rowcount == 1
        conn.commit()
        return claimed

    def to_file():
        path = os.path.join(_DIR, "phase20_kv.json")
        with _kv_file_lock():
            data = _read_json(path, {})
            if key in data:
                return False
            data[key] = value
            _write_json(path, data)
            return True

    return bool(_with_db(to_db, to_file))


def kv_acquire_expiring_claim(key: str, value: Any) -> bool:
    """Atomically claim ``key`` or overwrite an EXISTING claim whose
    ``value["expires_at"]`` (ISO-8601 UTC) has already passed.

    This is the crash-safe takeover primitive: a dead owner that never ran
    its cleanup leaves a record with an ``expires_at`` timestamp.  Once that
    time passes, any peer can call this function and, if its INSERT / UPDATE
    succeeds, it becomes the new owner.

    ``value`` must be a dict containing at least ``"token"`` and
    ``"expires_at"`` so callers can later use ``kv_release_if_owned``.

    Returns True if this caller acquired the claim, False if another peer
    holds a still-valid (unexpired) claim.
    """

    def to_db(conn):
        value_json = json.dumps(value, default=str)
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS phase20_kv (
                    key TEXT PRIMARY KEY,
                    value JSONB,
                    updated_at TIMESTAMPTZ DEFAULT NOW()
                )
                """
            )
            # Step 1: try fresh insert (key is absent).
            cur.execute(
                """
                INSERT INTO phase20_kv (key, value, updated_at)
                VALUES (%s, %s, NOW())
                ON CONFLICT (key) DO NOTHING
                """,
                (key, value_json),
            )
            if cur.rowcount == 1:
                conn.commit()
                return True
            # Step 2: try overwriting an expired record.
            cur.execute(
                """
                UPDATE phase20_kv
                SET value = %s, updated_at = NOW()
                WHERE key = %s
                  AND (value::jsonb->>'expires_at')::timestamptz < NOW()
                """,
                (value_json, key),
            )
            won = cur.rowcount == 1
        conn.commit()
        return won

    def to_file():
        path = os.path.join(_DIR, "phase20_kv.json")
        import datetime as _dt
        with _kv_file_lock():
            data = _read_json(path, {})
            existing = data.get(key)
            if existing is not None:
                if isinstance(existing, dict):
                    exp_iso = str(existing.get("expires_at") or "")
                    if exp_iso:
                        try:
                            exp_dt = _dt.datetime.fromisoformat(exp_iso)
                            if exp_dt.tzinfo is None:
                                exp_dt = exp_dt.replace(
                                    tzinfo=_dt.timezone.utc
                                )
                            if _dt.datetime.now(
                                _dt.timezone.utc
                            ).timestamp() < exp_dt.timestamp():
                                return False  # Fresh record; cannot overwrite
                        except Exception:
                            pass
                        # Expired or malformed expires_at → overwrite below
                    else:
                        return False  # No expiry info → treat as permanent
                else:
                    return False  # Non-dict claim → treat as permanent
            data[key] = value
            _write_json(path, data)
            return True

    return bool(_with_db(to_db, to_file))


def kv_release_if_owned(key: str, token: str) -> bool:
    """Delete ``key`` only if the stored ``value["token"]`` matches ``token``.

    Use to release an expiring-claim lease without accidentally deleting a
    new owner's record: if the TTL has passed and another peer already
    overwrote the record with a different token, this call is a no-op.

    Returns True if the key was deleted, False if the token did not match or
    the key did not exist."""

    def to_db(conn):
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS phase20_kv (
                    key TEXT PRIMARY KEY,
                    value JSONB,
                    updated_at TIMESTAMPTZ DEFAULT NOW()
                )
                """
            )
            cur.execute(
                "DELETE FROM phase20_kv WHERE key = %s "
                "AND value::jsonb->>'token' = %s",
                (key, token),
            )
            deleted = cur.rowcount == 1
        conn.commit()
        return deleted

    def to_file():
        path = os.path.join(_DIR, "phase20_kv.json")
        with _kv_file_lock():
            data = _read_json(path, {})
            existing = data.get(key)
            if not (isinstance(existing, dict) and existing.get("token") == token):
                return False
            del data[key]
            _write_json(path, data)
            return True

    return bool(_with_db(to_db, to_file))


def kv_renew_expiring_claim(key: str, token: str, expires_at: str) -> bool:
    """Extend an expiring claim only while its owner token still matches.

    Long-running bounded workers use this heartbeat to prevent a live worker
    from being taken over mid-operation, while a crashed worker naturally
    becomes reclaimable when its last expiry passes.
    """
    def to_db(conn):
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE phase20_kv
                SET value = jsonb_set(value, '{expires_at}', to_jsonb(%s::text)),
                    updated_at = NOW()
                WHERE key = %s AND value::jsonb->>'token' = %s
                """,
                (expires_at, key, token),
            )
            renewed = cur.rowcount == 1
        conn.commit()
        return renewed

    def to_file():
        path = os.path.join(_DIR, "phase20_kv.json")
        with _kv_file_lock():
            data = _read_json(path, {})
            existing = data.get(key)
            if not (isinstance(existing, dict) and existing.get("token") == token):
                return False
            existing["expires_at"] = expires_at
            data[key] = existing
            _write_json(path, data)
            return True

    return bool(_with_db(to_db, to_file))


def kv_release(key: str) -> None:
    """Release a kv_claim_once claim (compensation when the work guarded by
    the claim failed after claiming — e.g. a persist error). The next
    kv_claim_once for the key succeeds again."""
    def to_db(conn):
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS phase20_kv (
                    key TEXT PRIMARY KEY,
                    value JSONB,
                    updated_at TIMESTAMPTZ DEFAULT NOW()
                )
                """
            )
            cur.execute("DELETE FROM phase20_kv WHERE key = %s", (key,))
        conn.commit()

    def to_file():
        path = os.path.join(_DIR, "phase20_kv.json")
        with _kv_file_lock():
            data = _read_json(path, {})
            if key in data:
                del data[key]
                _write_json(path, data)

    _with_db(to_db, to_file)


def kv_list_keys(prefix: str) -> List[str]:
    """All KV keys starting with `prefix` (DB + file fallback)."""
    def from_db(conn):
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS phase20_kv (
                    key TEXT PRIMARY KEY,
                    value JSONB,
                    updated_at TIMESTAMPTZ DEFAULT NOW()
                )
                """
            )
            conn.commit()
            cur.execute("SELECT key FROM phase20_kv WHERE key LIKE %s",
                        (prefix.replace("%", r"\%").replace("_", r"\_") + "%",))
            return [r[0] for r in cur.fetchall()]

    def from_file():
        data = _read_json(os.path.join(_DIR, "phase20_kv.json"), {})
        return [k for k in data if str(k).startswith(prefix)]

    return list(_with_db(from_db, from_file) or [])


def kv_get(key: str, default: Any = None) -> Any:
    def from_db(conn):
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS phase20_kv (
                    key TEXT PRIMARY KEY,
                    value JSONB,
                    updated_at TIMESTAMPTZ DEFAULT NOW()
                )
                """
            )
            conn.commit()
            cur.execute("SELECT value FROM phase20_kv WHERE key = %s", (key,))
            row = cur.fetchone()
        if row is None:
            return default
        val = row[0]
        if isinstance(val, str):
            try:
                val = json.loads(val)
            except Exception:
                pass
        return val

    return _with_db(
        from_db,
        lambda: _read_json(os.path.join(_DIR, "phase20_kv.json"), {}).get(key, default),
    )


# ── Notifications ─────────────────────────────────────────────────────────────

def add_notification(kind: str, title: str, body: str = "",
                     severity: str = "INFO",
                     context: Optional[Dict[str, Any]] = None) -> None:
    def to_db(conn):
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO phase20_notifications (kind, severity, title, body, context)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (kind, severity, title[:300], body[:1000],
                 json.dumps(context or {}, default=str)),
            )
        conn.commit()
        return True

    def to_file():
        items = _read_json(_NOTIF_FILE, [])
        items.append({
            "id": len(items) + 1, "kind": kind, "severity": severity,
            "title": title[:300], "body": body[:1000],
            "context": context or {}, "created_at": _iso(_now()), "read": False,
        })
        _write_json(_NOTIF_FILE, items[-300:])

    _with_db(to_db, to_file)

    # Best-effort email delivery for critical alert kinds (opt-in via
    # settings). Failures are logged inside email_alerts and NEVER raise —
    # a broken email provider must not break notification storage or the
    # scheduler tick.
    try:
        import email_alerts
        if kind in email_alerts.EMAIL_KINDS:
            # Priority 4 (#41): durable queue + immediate processing attempt.
            # A briefly-down email provider no longer loses the alert — the
            # scheduler retries queued rows with bounded backoff.
            import alert_queue
            alert_queue.enqueue_email_alert(kind, title, body, severity)
            alert_queue.process_email_queue()
    except Exception:
        pass


def list_notifications(limit: int = 100) -> List[Dict[str, Any]]:
    def from_db(conn):
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, kind, severity, title, body, context, created_at, read
                FROM phase20_notifications ORDER BY id DESC LIMIT %s
                """,
                (int(limit),),
            )
            rows = cur.fetchall()
        return [{
            "id": r[0], "kind": r[1], "severity": r[2], "title": r[3],
            "body": r[4], "context": r[5] or {},
            "created_at": _iso(r[6]) if isinstance(r[6], datetime) else r[6],
            "read": bool(r[7]),
        } for r in rows]

    return _with_db(from_db,
                    lambda: list(reversed(_read_json(_NOTIF_FILE, [])))[:limit])


def mark_notifications_read(ids: Optional[List[int]] = None) -> int:
    def to_db(conn):
        with conn.cursor() as cur:
            if ids:
                cur.execute(
                    "UPDATE phase20_notifications SET read = TRUE WHERE id = ANY(%s)",
                    (list(map(int, ids)),),
                )
            else:
                cur.execute("UPDATE phase20_notifications SET read = TRUE WHERE read = FALSE")
            n = cur.rowcount
        conn.commit()
        return n

    def to_file():
        items = _read_json(_NOTIF_FILE, [])
        n = 0
        for item in items:
            if (not ids or item.get("id") in ids) and not item.get("read"):
                item["read"] = True
                n += 1
        _write_json(_NOTIF_FILE, items)
        return n

    return _with_db(to_db, to_file)
