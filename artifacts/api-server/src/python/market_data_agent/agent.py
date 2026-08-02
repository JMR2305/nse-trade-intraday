"""
agent.py — Phase 10A
Market Data Agent.

Responsibilities:
  - Collect NSE OHLC, volume, delivery, India VIX, sector indices,
    pre-open auction, watchlists, and data freshness
  - Normalise all data into a unified MarketSnapshot
  - Publish to SnapshotBus topic "market_data"
  - NO analysis. NO recommendations. NO order placement.

Data sources (all read-only from existing infrastructure):
  - scan_state_store.load_latest_snapshot() — Phase 19B durable scan cache
  - config.DEFAULT_WATCHLIST
  - market_intelligence_hub.shared_services (if available)

READ-ONLY · ADVISORY-ONLY
"""
from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from agent_framework.base_agent import BaseAgent
from agent_framework.models import AgentRecord


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _safe(fn, default=None):
    try:
        return fn()
    except Exception:
        return default


class MarketDataAgent(BaseAgent):
    """
    Collects raw market data from existing scan/config infrastructure,
    normalises it, and publishes a unified MarketSnapshot.

    READ-ONLY: reads from scan_state_store and config only.
    ADVISORY-ONLY: publishes snapshots, never places orders.
    """

    HEARTBEAT_INTERVAL_S: float = 30.0

    def __init__(self) -> None:
        super().__init__(
            agent_id     = "market-data-agent",
            name         = "Market Data Agent",
            version      = "1.0.0",
            owner        = "ApexQuant AI",
            priority     = 1,
            dependencies = [],
            capabilities = [
                "nse_ohlc", "volume", "delivery", "india_vix",
                "sector_indices", "pre_open_auction", "watchlists", "data_freshness",
            ],
        )
        self._last_snapshot: Optional[Dict[str, Any]] = None

    @property
    def default_topic(self) -> str:
        return "market_data"

    def execute_task(self) -> Optional[Dict[str, Any]]:
        """Collect, normalise, and return the MarketSnapshot payload."""
        start_ms = time.monotonic() * 1000

        # Source 1: durable scan snapshot (Phase 19B)
        scan = _safe(self._load_scan_snapshot) or {}

        # Source 2: config watchlist
        watchlist = _safe(self._load_watchlist) or []

        # Source 3: market intelligence hub (optional)
        mi = _safe(self._load_market_intelligence) or {}

        payload = self._normalise(scan, watchlist, mi)
        payload["collection_latency_ms"] = round(
            (time.monotonic() * 1000) - start_ms, 1
        )

        self._last_snapshot = payload
        return payload

    # ── Data collection (all read-only) ───────────────────────────────────────

    @staticmethod
    def _load_scan_snapshot() -> Dict[str, Any]:
        from scan_state_store import load_latest_snapshot, load_latest_meta
        snap = load_latest_snapshot() or {}
        meta = load_latest_meta() or {}
        return {"snapshot": snap, "meta": meta}

    @staticmethod
    def _load_watchlist() -> List[str]:
        try:
            import signals_store
            wl = signals_store.load_watchlist()
            if wl is not None:
                return wl
        except Exception:
            pass
        try:
            import config
            return list(config.DEFAULT_WATCHLIST)
        except Exception:
            return []

    @staticmethod
    def _load_market_intelligence() -> Dict[str, Any]:
        from market_intelligence_hub.shared_services import get_overview
        return get_overview()

    # ── Normalisation (read-only transformation) ───────────────────────────────

    def _normalise(
        self,
        scan_data: Dict[str, Any],
        watchlist: List[str],
        mi: Dict[str, Any],
    ) -> Dict[str, Any]:
        snap     = scan_data.get("snapshot") or {}
        meta     = scan_data.get("meta")     or {}
        safety   = snap.get("safety")        or {}
        ph       = snap.get("provider_health") or {}
        regime   = mi.get("regime")          or {}
        sectors  = mi.get("sectors")         or {}
        indices  = mi.get("indices")         or {}

        # Freshness
        snapshot_ts  = snap.get("snapshot_ts") or meta.get("snapshot_ts")
        freshness_s  = None
        if snapshot_ts:
            try:
                ts = datetime.fromisoformat(snapshot_ts.replace("Z", "+00:00"))
                if ts.tzinfo is None:
                    from datetime import timezone
                    ts = ts.replace(tzinfo=timezone.utc)
                freshness_s = round(
                    (datetime.now(timezone.utc) - ts).total_seconds(), 0
                )
            except Exception:
                pass

        symbols_requested = int(ph.get("symbols_requested") or len(watchlist) or 0)
        symbols_received  = int(ph.get("symbols_succeeded") or 0)

        # Build normalised payload
        return {
            # Metadata
            "agent_id":         "market-data-agent",
            "agent_name":       "Market Data Agent",
            "snapshot_ts":      snapshot_ts,
            "data_freshness_s": freshness_s,
            "data_provider":    safety.get("data_provider") or ph.get("provider") or "unknown",
            "advisory_only":    True,
            "read_only":        True,

            # Coverage
            "symbols_count":       symbols_requested,
            "symbols_received":    symbols_received,
            "coverage_pct":        round((symbols_received / symbols_requested) * 100, 1)
                                   if symbols_requested > 0 else 0.0,

            # Watchlist
            "watchlist":           watchlist[:50],
            "watchlist_count":     len(watchlist),

            # Indices (from market intelligence if available)
            "nifty50_price":       _f(indices.get("nifty50_price") or regime.get("nifty_price")),
            "nifty50_change_pct":  _f(indices.get("nifty50_change") or regime.get("nifty_change_pct")),
            "banknifty_price":     _f(indices.get("banknifty_price") or regime.get("banknifty_price")),
            "banknifty_change_pct":_f(indices.get("banknifty_change") or regime.get("banknifty_change_pct")),
            "india_vix":           _f(regime.get("vix_value")),
            "india_vix_status":    regime.get("vix_status") or "UNKNOWN",

            # Regime
            "market_regime":       regime.get("regime") or "UNKNOWN",
            "market_sub_regime":   regime.get("sub_regime") or "NORMAL",
            "trend_strength":      _f(regime.get("trend_strength")),
            "high_volatility":     bool(regime.get("high_volatility", False)),

            # Sector
            "strongest_sector":    sectors.get("strongest_sector") or "N/A",
            "weakest_sector":      sectors.get("weakest_sector")   or "N/A",
            "sector_count":        len(sectors.get("sectors") or []),

            # Scan health
            "scan_id":             snap.get("scan_id") or meta.get("scan_id"),
            "stale_symbols":       int(ph.get("symbols_stale") or 0),
            "missing_symbols":     max(0, symbols_requested - symbols_received),

            # Generated
            "generated_at":        _now_iso(),
        }

    def last_snapshot(self) -> Optional[Dict[str, Any]]:
        return self._last_snapshot


def _f(v) -> Optional[float]:
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None
