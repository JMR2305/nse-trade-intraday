"""
preopen_scheduler.py — Phase 5A IST-aware pre-open scheduler.

Cadence:
  08:45 — initialise, validate provider + DB, load prev-close refs
  08:55 — readiness check
  09:00–09:08 — snapshots every 30s
  09:08–09:12 — snapshots every 15s (where supported)
  09:12–09:15 — final capture
  09:15 — freeze + generate watchlists
  09:20 — reconcile indicative vs actual prices

Only collects data within the pre-open window (or in test/replay mode).
Uses the existing NSE market calendar where available.

PAPER TRADING / ADVISORY ONLY.
"""
from __future__ import annotations

import os
import time
import uuid
import threading
from datetime import datetime, timezone, timedelta
from typing import Optional, Callable, Dict, Any

_IST = timezone(timedelta(hours=5, minutes=30))
_ENABLED_VAR = "PREOPEN_INTELLIGENCE_ENABLED"


def _is_enabled() -> bool:
    return os.environ.get(_ENABLED_VAR, "false").lower() in ("1", "true", "yes")


def _now_ist() -> datetime:
    return datetime.now(_IST)


def _today_ist() -> str:
    return _now_ist().strftime("%Y-%m-%d")


def _is_market_holiday(date_str: str) -> bool:
    """Check NSE market calendar if available."""
    try:
        from market_hours import is_holiday
        return is_holiday(date_str)
    except Exception:
        return False


def _is_preopen_window() -> bool:
    """Return True if current IST time is in the 08:45–09:35 window (includes post-open recon)."""
    now = _now_ist()
    start = now.replace(hour=8, minute=45, second=0, microsecond=0)
    end   = now.replace(hour=9,  minute=35, second=0, microsecond=0)
    return start <= now <= end


def _collection_interval_seconds() -> int:
    """Return the collection interval for current time in the pre-open window."""
    now = _now_ist()
    t = (now.hour, now.minute)
    if (9, 8) <= t < (9, 12):
        return 15    # high-frequency phase
    if (9, 0) <= t < (9, 8):
        return 30    # main collection phase
    return 60        # early or final capture


# ── Phase states ──────────────────────────────────────────────────────────────

class SchedulerPhase:
    IDLE       = "IDLE"
    INIT       = "INIT"
    READY      = "READY"
    COLLECTING = "COLLECTING"
    FROZEN     = "FROZEN"
    RECON      = "RECONCILING"
    DONE       = "DONE"
    ERROR      = "ERROR"
    DISABLED   = "DISABLED"


class PreOpenScheduler:
    """
    Single-session IST-aware scheduler.
    Run in a background thread during the pre-open window.
    """

    def __init__(self, session_id: Optional[str] = None,
                 test_mode: bool = False,
                 on_status: Optional[Callable[[str, dict], None]] = None):
        self.session_id = session_id or f"preopen-{_today_ist()}-{uuid.uuid4().hex[:6]}"
        self.test_mode = test_mode          # if True, skip window checks
        self.on_status = on_status          # optional callback for status updates
        self.phase = SchedulerPhase.IDLE
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._log: list = []

    def _emit(self, phase: str, detail: dict = {}) -> None:
        self.phase = phase
        msg = {"phase": phase, "ts": _now_ist().isoformat(), **detail}
        self._log.append(msg)
        if self.on_status:
            try:
                self.on_status(phase, msg)
            except Exception:
                pass

    def _should_run(self) -> bool:
        if not _is_enabled():
            self._emit(SchedulerPhase.DISABLED, {"reason": f"{_ENABLED_VAR}=false"})
            return False
        if not self.test_mode:
            today = _today_ist()
            if _is_market_holiday(today):
                self._emit(SchedulerPhase.IDLE, {"reason": f"Market holiday: {today}"})
                return False
        return True

    def _phase_08_45_init(self) -> bool:
        """08:45 — initialise provider and DB."""
        self._emit(SchedulerPhase.INIT)
        try:
            import preopen_db as db_mod
            import preopen_engine as engine
            health = engine.get_health()
            db_mod.upsert_session({
                "session_id": self.session_id,
                "trading_date": _today_ist(),
                "status": "INITIALISING",
                "provider_status": health.get("provider_health", {}).get("status", "UNKNOWN"),
            })
            self._emit(SchedulerPhase.INIT, {"health": health})
            return True
        except Exception as e:
            self._emit(SchedulerPhase.ERROR, {"error": str(e)})
            return False

    def _phase_08_55_readiness(self) -> bool:
        """08:55 — readiness check."""
        try:
            import preopen_engine as engine
            status = engine.get_status()
            ok = status.get("provider_status") not in ("UNAVAILABLE", None)
            self._emit(SchedulerPhase.READY, {"ready": ok, "status": status})
            return ok
        except Exception as e:
            self._emit(SchedulerPhase.ERROR, {"error": str(e)})
            return False

    def _collect_one(self) -> dict:
        """Single snapshot collection pass."""
        try:
            import preopen_engine as engine
            return engine.collect_snapshot(session_id=self.session_id)
        except Exception as e:
            return {"success": False, "error": str(e)}

    def _phase_09_15_freeze(self) -> bool:
        """09:15 — freeze only a complete, durably persisted collection."""
        try:
            import preopen_db as db_mod
            import preopen_engine as engine
            from preopen_watchlist import generate_watchlists

            today = _today_ist()
            session = db_mod.get_session(self.session_id)
            collected = (session or {}).get("provider_collected_count")
            persisted = (session or {}).get("persisted_count")
            expected = (session or {}).get("expected_count")
            failed = (session or {}).get("failed_count")
            persistence_status = str((session or {}).get("persistence_status") or "")
            collection_batch_id = (session or {}).get("verified_collection_batch_id")
            if (
                not session
                or persistence_status != "MATCH"
                or collected is None
                or persisted is None
                or expected is None
                or int(collected) != int(persisted)
                or int(collected) != int(expected)
                or int(failed or 0) != 0
                or not collection_batch_id
            ):
                reason = (
                    "Freeze blocked: Phase 5A collection is not durably complete "
                    f"(expected={expected}, provider={collected}, persisted={persisted}, "
                    f"failed={failed}, "
                    f"status={persistence_status or 'UNKNOWN'}, "
                    f"batch={collection_batch_id or 'UNKNOWN'})."
                )
                db_mod.record_collection_failure(
                    self.session_id, "FREEZE_BLOCKED", reason,
                )
                self._emit(SchedulerPhase.ERROR, {"error": reason})
                return False

            snaps_raw = db_mod.get_session_snapshots(
                self.session_id, str(collection_batch_id),
            )
            snapshot_ids = {
                str(s.get("snapshot_id") or "") for s in snaps_raw
                if s.get("snapshot_id")
            }
            symbols = {
                str(s.get("symbol") or "").strip().upper() for s in snaps_raw
                if s.get("symbol")
            }
            coverage = session.get("collection_coverage") or {}
            expected_symbols = {
                str(symbol or "").strip().upper()
                for symbol in coverage.get("expected_symbols") or []
                if str(symbol or "").strip()
            }
            if (
                not snaps_raw
                or len(snaps_raw) != int(persisted)
                or len(snapshot_ids) != int(persisted)
                or len(symbols) != int(persisted)
                or len(expected_symbols) != int(expected)
                or symbols != expected_symbols
            ):
                reason = (
                    "Freeze blocked: exact verified collection batch does not "
                    f"match its persisted proof (batch={collection_batch_id}, "
                    f"rows={len(snaps_raw)}, snapshots={len(snapshot_ids)}, "
                    f"symbols={len(symbols)}, expected_symbols={len(expected_symbols)}, "
                    f"persisted={persisted})."
                )
                db_mod.record_collection_failure(
                    self.session_id, "FREEZE_BLOCKED", reason,
                )
                self._emit(SchedulerPhase.ERROR, {"error": reason})
                return False

            # Rebuild PreOpenSnapshot objects for watchlist generation
            from preopen_data_model import PreOpenSnapshot
            snap_objs = []
            for s in snaps_raw:
                try:
                    obj = PreOpenSnapshot(
                        snapshot_id=s.get("snapshot_id", ""),
                        trading_date=s.get("trading_date", today),
                        timestamp_ist=s.get("timestamp_ist", ""),
                        symbol=s.get("symbol", ""),
                        company_name=s.get("company_name", ""),
                        sector=s.get("sector", "Unknown"),
                        previous_close=float(s.get("previous_close") or 0),
                        gap_percent=s.get("gap_percent"),
                        total_buy_quantity=int(s.get("total_buy_quantity") or 0),
                        total_sell_quantity=int(s.get("total_sell_quantity") or 0),
                        matched_quantity=int(s.get("matched_quantity") or 0),
                        final_executed_quantity=int(s.get("final_executed_quantity") or 0),
                        total_traded_value=float(s.get("total_traded_value") or 0),
                        buy_sell_imbalance=int(s.get("buy_sell_imbalance") or 0),
                        imbalance_percent=float(s.get("imbalance_percent") or 0),
                        liquidity_score=float(s.get("liquidity_score") or 0),
                        classification=s.get("classification", "DATA_INCOMPLETE"),
                        opportunity_score=float(s.get("opportunity_score") or 0),
                        factor_scores=s.get("factor_scores") or {},
                        data_source=s.get("data_source", "unknown"),
                        data_freshness_seconds=int(s.get("data_freshness_seconds") or 0),
                        source_status=s.get("source_status", "UNAVAILABLE"),
                        is_stale=bool(s.get("is_stale", True)),
                        validation_status=s.get("validation_status", "UNVALIDATED"),
                    )
                    snap_objs.append(obj)
                except Exception:
                    continue

            watchlists = generate_watchlists(snap_objs)
            for list_type, items in watchlists.items():
                db_mod.save_watchlist(self.session_id, today, list_type, items)

            db_mod.save_rankings(
                self.session_id, today,
                [s.to_dict() for s in sorted(snap_objs, key=lambda x: -(x.opportunity_score or 0))],
                {"symbol_count": len(snap_objs),
                 "valid_count": sum(1 for s in snap_objs if not s.is_stale)},
            )
            if not db_mod.upsert_session({
                "session_id": self.session_id,
                "trading_date": today,
                "status": "FROZEN",
                "frozen_collection_batch_id": collection_batch_id,
                "frozen_at": _now_ist().isoformat(),
            }):
                raise RuntimeError("Could not durably mark pre-open session FROZEN")
            self._emit(SchedulerPhase.FROZEN, {
                "watchlists_generated": list(watchlists.keys()),
                "symbols": len(snap_objs),
            })
            return True
        except Exception as e:
            self._emit(SchedulerPhase.ERROR, {"error": f"freeze failed: {e}"})
            return False

    def _phase_09_20_reconcile(self) -> bool:
        """09:20 — reconcile indicative vs actual prices (best-effort)."""
        self._emit(SchedulerPhase.RECON)
        try:
            import preopen_db as db_mod
            today = _today_ist()
            session = db_mod.get_session(self.session_id) or {}
            if session.get("status") not in ("FROZEN", "RECONCILED", "RECONCILED_0930"):
                reason = (
                    "Reconcile blocked: durable FROZEN prerequisite is missing "
                    f"(session status={session.get('status') or 'UNKNOWN'})."
                )
                db_mod.record_collection_failure(
                    self.session_id, "RECONCILE_BLOCKED", reason,
                )
                self._emit(SchedulerPhase.ERROR, {"error": reason})
                return False
            collection_batch_id = session.get("frozen_collection_batch_id")
            if not collection_batch_id:
                reason = "Reconcile blocked: no durable frozen collection batch is recorded."
                db_mod.record_collection_failure(
                    self.session_id, "RECONCILE_BLOCKED", reason,
                )
                self._emit(SchedulerPhase.ERROR, {"error": reason})
                return False
            snaps = db_mod.get_session_snapshots(self.session_id, str(collection_batch_id))

            # Attempt to get actual prices from live quote service
            try:
                from live_quote_service import get_quotes
                symbols = [s.get("symbol") for s in snaps if s.get("symbol")]
                quotes = get_quotes(symbols, force=True)
                actual = {sym: float(q.get("price", 0))
                          for sym, q in (quotes.get("quotes") or {}).items()
                          if q.get("price")}
            except Exception:
                actual = {}

            from preopen_reconciliation import reconcile_session

            # Watchlist symbols from the frozen watchlists
            wl = db_mod.get_session_watchlists(self.session_id)
            wl_syms = set()
            for items in wl.values():
                for item in items:
                    if isinstance(item, dict) and item.get("symbol"):
                        wl_syms.add(item["symbol"])

            result = reconcile_session(
                self.session_id, snaps,
                actual_prices=actual,
                prices_0920=actual,   # best-effort: same quotes
                prices_0930={},
                watchlist_symbols=wl_syms,
            )
            if not db_mod.upsert_session({
                "session_id": self.session_id,
                "trading_date": today,
                "status": "RECONCILED",
                "reconciled_at": _now_ist().isoformat(),
            }):
                raise RuntimeError("Could not durably mark pre-open session RECONCILED")
            self._emit(SchedulerPhase.DONE, {"reconciliation": result})
            return True
        except Exception as e:
            self._emit(SchedulerPhase.ERROR, {"error": f"reconcile failed: {e}"})
            return False

    def _phase_09_30_post_open_reconcile(self) -> bool:
        """
        09:30 — enrich reconciliation records with actual 09:30 prices.

        The 09:20 step captures prices immediately after open. By 09:30 the
        opening auction has fully cleared and prices are more reliable. This
        step patches price_at_0930 on existing records and updates the session
        status so the accuracy report can surface the enriched data.
        """
        self._emit(SchedulerPhase.RECON, {"step": "0930"})
        try:
            import preopen_db as db_mod
            today = _today_ist()
            session = db_mod.get_session(self.session_id) or {}
            if session.get("status") not in ("RECONCILED", "RECONCILED_0930"):
                reason = (
                    "09:30 reconcile blocked: durable RECONCILED prerequisite "
                    f"is missing (session status={session.get('status') or 'UNKNOWN'})."
                )
                db_mod.record_collection_failure(
                    self.session_id, "RECONCILE_0930_BLOCKED", reason,
                )
                self._emit(SchedulerPhase.ERROR, {"error": reason})
                return False
            collection_batch_id = session.get("frozen_collection_batch_id")
            if not collection_batch_id:
                reason = "09:30 reconcile blocked: no durable frozen collection batch is recorded."
                db_mod.record_collection_failure(
                    self.session_id, "RECONCILE_0930_BLOCKED", reason,
                )
                self._emit(SchedulerPhase.ERROR, {"error": reason})
                return False
            snaps = db_mod.get_session_snapshots(self.session_id, str(collection_batch_id))

            # Fetch live quotes at 09:30
            try:
                from live_quote_service import get_quotes
                symbols = [s.get("symbol") for s in snaps if s.get("symbol")]
                quotes = get_quotes(symbols, force=True)
                prices_0930 = {sym: float(q.get("price", 0))
                               for sym, q in (quotes.get("quotes") or {}).items()
                               if q.get("price")}
            except Exception:
                prices_0930 = {}

            if prices_0930:
                db_mod.update_reconciliation_0930(self.session_id, prices_0930)

            if not db_mod.upsert_session({
                "session_id": self.session_id,
                "trading_date": today,
                "status": "RECONCILED_0930",
            }):
                raise RuntimeError("Could not durably mark pre-open session RECONCILED_0930")
            self._emit(SchedulerPhase.DONE, {
                "step": "0930",
                "prices_patched": len(prices_0930),
            })
            return True
        except Exception as e:
            self._emit(SchedulerPhase.ERROR, {"error": f"09:30 reconcile failed: {e}"})
            return False

    def run_once(self) -> Dict[str, Any]:
        """Run the full pre-open cycle synchronously (for testing / manual trigger)."""
        if not self._should_run():
            return {"ran": False, "phase": self.phase}
        self._phase_08_45_init()
        self._phase_08_55_readiness()
        result = self._collect_one()
        froze = self._phase_09_15_freeze()
        reconciled = self._phase_09_20_reconcile() if froze else False
        if reconciled:
            self._phase_09_30_post_open_reconcile()
        return {"ran": True, "session_id": self.session_id, "log": self._log}

    def status(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "phase": self.phase,
            "enabled": _is_enabled(),
            "ist_time": _now_ist().isoformat(),
            "in_preopen_window": _is_preopen_window(),
            "log": self._log[-20:],
        }


# ── Module-level singleton ────────────────────────────────────────────────────

_scheduler: Optional[PreOpenScheduler] = None


def get_scheduler_status() -> dict:
    if _scheduler is None:
        return {"active": False, "enabled": _is_enabled()}
    return {"active": True, **_scheduler.status()}


def run_preopen_cycle_now(test_mode: bool = False) -> dict:
    """
    Trigger a full pre-open cycle immediately.
    Used for manual refresh and testing.
    """
    if not _is_enabled():
        return {
            "ran": False,
            "status": "DISABLED",
            "message": f"Set {_ENABLED_VAR}=true to enable pre-open intelligence",
        }
    s = PreOpenScheduler(test_mode=test_mode)
    return s.run_once()
