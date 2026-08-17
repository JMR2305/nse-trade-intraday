"""
phase20_store.py — Phase 20: durable settings, scan-run history, scheduler
health, and notifications.

All state lives in shared PostgreSQL (DATABASE_URL) so Replit Autoscale
instances agree; JSON-file fallback keeps local dev/tests working.

PAPER TRADING / RESEARCH ONLY. This module never places live orders.
Auto paper entries default OFF and can only be enabled through an explicit
confirmation flow (see update_settings).
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

from scan_state_store import db_available, _connect  # shared DB helpers

_DIR = os.path.dirname(os.path.abspath(__file__))
_SETTINGS_FILE = os.path.join(_DIR, "phase20_settings.json")
_SCAN_RUNS_FILE = os.path.join(_DIR, "phase20_scan_runs.json")
_SCHED_FILE = os.path.join(_DIR, "phase20_scheduler_state.json")
_NOTIF_FILE = os.path.join(_DIR, "phase20_notifications.json")

_SCHEMA_READY = False

ALLOWED_INTERVALS = (3, 4, 5, 6, 10, 15)
FILL_MODELS = ("LAST_TRADED_PRICE", "NEXT_QUOTE", "SLIPPAGE_ADJUSTED")

CONFIRMATION_TEXT = (
    "I understand this will automatically create simulated paper trades only. "
    "No real orders will be placed."
)

# Safe defaults per Phase 20 spec. auto_paper_entries MUST default to False.
DEFAULT_SETTINGS: Dict[str, Any] = {
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
    # A bootstrap trade is at most ₹1,500, uses the normal exit engine, and emits
    # trigger_source="BOOTSTRAP_AUTO" so it is permanently distinguishable from
    # normal paper entries. Auto-disables when the ledger reaches 20 closed trades.
    "bootstrap_paper_enabled": False,
}

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
        # Phase 22 production-visibility columns (idempotent).
        for col, typ in (("owner", "TEXT"), ("last_trigger", "TEXT"),
                         ("last_error", "TEXT"), ("heartbeat_at", "TIMESTAMPTZ")):
            cur.execute(
                f"ALTER TABLE phase20_scheduler_state ADD COLUMN IF NOT EXISTS {col} {typ}"
            )
        # Phase 22 scan-run timing/perf columns (idempotent).
        for col, typ in (("timings", "JSONB"), ("perf", "TEXT")):
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
        elif isinstance(default, (int, float)) and not isinstance(default, bool):
            num = float(value)
            if num < 0:
                raise ValueError(f"{key} must be >= 0")
            clean[key] = int(num) if isinstance(default, int) else num
        else:
            clean[key] = value
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

    stored = _with_db(from_db, lambda: _read_json(_SETTINGS_FILE, {}))
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

def record_scan_run(run: Dict[str, Any]) -> None:
    """Append one scan-run record (SCHEDULED or MANUAL, success or failure)."""
    row = {
        "scan_id": run.get("scan_id"),
        "trigger_source": (run.get("trigger_source") or "MANUAL").upper(),
        "started_at": run.get("started_at"),
        "completed_at": run.get("completed_at"),
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
        "created_at": _iso(_now()),
    }

    def to_db(conn):
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO phase20_scan_runs (
                    scan_id, trigger_source, started_at, completed_at, duration_s,
                    symbols_requested, symbols_received, missing_symbols,
                    stale_symbols, unavailable_symbols, provider, status, error,
                    timings, perf
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
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
                       provider, status, error, created_at, timings, perf
                FROM phase20_scan_runs ORDER BY id DESC LIMIT %s
                """,
                (int(limit),),
            )
            rows = cur.fetchall()
        out = []
        for r in rows:
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
            })
        return out

    return _with_db(from_db,
                    lambda: list(reversed(_read_json(_SCAN_RUNS_FILE, [])))[:limit])


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
                        "owner", "last_trigger", "last_error", "heartbeat_at"):
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
                    "owner", "last_trigger", "last_error", "heartbeat_at"):
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
                       owner, last_trigger, last_error, heartbeat_at
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


def kv_set(key: str, value: Any) -> None:
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


def kv_claim_once(key: str) -> bool:
    """Atomically claim a KV key. Returns True only for the FIRST claimant
    (cross-process safe): DB path uses INSERT ... ON CONFLICT DO NOTHING in a
    single statement; file fallback serialises with flock. Use for
    exactly-once notification guards."""
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
