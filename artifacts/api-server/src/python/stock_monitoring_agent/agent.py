"""
agent.py — Phase 10B
Stock Monitoring Agent.

Responsibilities:
  - Priority-based monitoring of the stock universe (P1–P5)
  - Detect 12 event types per symbol evaluation
  - Publish stock_monitoring snapshot per cycle
  - NEVER recommend trades. NEVER modify portfolio.

Priority Engine:
  P1 = Open Positions (highest frequency)
  P2 = High-Conviction Watchlist
  P3 = Today's Candidates
  P4 = NIFTY 50
  P5 = Background Universe

READ-ONLY · ADVISORY-ONLY
"""
from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from agent_framework.base_agent import BaseAgent


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _safe(fn, default=None):
    try:
        return fn()
    except Exception:
        return default


def _f(v) -> Optional[float]:
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


# ── Smart Priority Engine ─────────────────────────────────────────────────────

class SmartPriorityEngine:
    """
    Assigns monitoring priority to symbols.
    P1 = Open Positions (most critical — highest frequency)
    P2 = High-conviction watchlist
    P3 = Today's trading candidates
    P4 = NIFTY 50 universe
    P5 = Background universe (scan universe)
    """

    PRIORITY_LABELS = {1: "OPEN_POSITIONS", 2: "HIGH_CONVICTION", 3: "TODAY_CANDIDATES",
                       4: "NIFTY_50", 5: "BACKGROUND"}
    EVAL_FREQUENCY = {1: 60, 2: 120, 3: 300, 4: 600, 5: 900}  # seconds between evaluations

    def build_priority_queue(
        self,
        open_positions: List[str],
        watchlist: List[str],
        candidates: List[str],
        nifty50: List[str],
        universe: List[str],
    ) -> List[Dict[str, Any]]:
        """Return ordered list of (symbol, priority, frequency_s)."""
        seen = set()
        queue = []

        def add(symbols: List[str], priority: int) -> None:
            for sym in symbols:
                if sym not in seen:
                    seen.add(sym)
                    queue.append({
                        "symbol":      sym,
                        "priority":    priority,
                        "priority_label": self.PRIORITY_LABELS[priority],
                        "eval_frequency_s": self.EVAL_FREQUENCY[priority],
                    })

        add(open_positions, 1)
        add(watchlist,      2)
        add(candidates,     3)
        add(nifty50,        4)
        add(universe,       5)
        return queue

    def summary(self, queue: List[Dict[str, Any]]) -> Dict[str, Any]:
        from collections import Counter
        counts = Counter(item["priority"] for item in queue)
        return {
            "total_symbols":     len(queue),
            "p1_open_positions": counts.get(1, 0),
            "p2_high_conviction":counts.get(2, 0),
            "p3_candidates":     counts.get(3, 0),
            "p4_nifty50":        counts.get(4, 0),
            "p5_background":     counts.get(5, 0),
        }


# ── Event Detectors ───────────────────────────────────────────────────────────

class EventDetector:
    """
    Detects 12 event types from symbol scan data.
    All detection is read-only and advisory. No signals generated.
    """

    EVENT_TYPES = [
        "BREAKOUT", "BREAKDOWN", "GAP_UP", "GAP_DOWN",
        "VWAP_CROSS", "VOLUME_SPIKE", "DELIVERY_SPIKE",
        "MOMENTUM_SHIFT", "TREND_REVERSAL", "NEW_HIGH",
        "NEW_LOW", "UNUSUAL_ACTIVITY",
    ]

    def detect(self, symbol: str, data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Detect events for a single symbol. Returns list of event dicts."""
        events = []
        chg = _f(data.get("change_pct")) or 0.0
        vol_ratio = _f(data.get("volume_ratio")) or 1.0
        delivery_pct = _f(data.get("delivery_pct"))
        signal = data.get("signal", "")
        near_high = bool(data.get("near_52w_high"))
        near_low  = bool(data.get("near_52w_low"))
        rsi = _f(data.get("rsi")) or 50.0
        vwap_cross = bool(data.get("vwap_above"))

        # GAP_UP / GAP_DOWN (opening gap)
        if chg > 2.0:
            events.append(self._event(symbol, "GAP_UP", "HIGH",
                f"Gap up {chg:.1f}%", {"change_pct": chg}))
        elif chg < -2.0:
            events.append(self._event(symbol, "GAP_DOWN", "HIGH",
                f"Gap down {chg:.1f}%", {"change_pct": chg}))

        # BREAKOUT / BREAKDOWN from signal
        if signal in ("BUY", "STRONG_BUY") and near_high:
            events.append(self._event(symbol, "BREAKOUT", "MEDIUM",
                f"Near 52-week high with {signal} signal", {"signal": signal}))
        elif signal in ("SELL", "STRONG_SELL") and near_low:
            events.append(self._event(symbol, "BREAKDOWN", "MEDIUM",
                f"Near 52-week low with {signal} signal", {"signal": signal}))

        # NEW_HIGH / NEW_LOW
        if near_high and chg > 0.5:
            events.append(self._event(symbol, "NEW_HIGH", "LOW",
                "Near 52-week high", {"near_52w_high": True}))
        elif near_low and chg < -0.5:
            events.append(self._event(symbol, "NEW_LOW", "LOW",
                "Near 52-week low", {"near_52w_low": True}))

        # VWAP_CROSS
        if vwap_cross and abs(chg) > 0.3:
            events.append(self._event(symbol, "VWAP_CROSS", "LOW",
                "Price above VWAP", {"vwap_above": True}))

        # VOLUME_SPIKE
        if vol_ratio > 2.5:
            sev = "HIGH" if vol_ratio > 4.0 else "MEDIUM"
            events.append(self._event(symbol, "VOLUME_SPIKE", sev,
                f"Volume {vol_ratio:.1f}x average", {"volume_ratio": vol_ratio}))

        # DELIVERY_SPIKE
        if delivery_pct is not None and delivery_pct > 70:
            events.append(self._event(symbol, "DELIVERY_SPIKE", "MEDIUM",
                f"Delivery {delivery_pct:.1f}% of volume", {"delivery_pct": delivery_pct}))

        # MOMENTUM_SHIFT
        if rsi > 70 and chg > 1.0:
            events.append(self._event(symbol, "MOMENTUM_SHIFT", "MEDIUM",
                f"RSI overbought {rsi:.0f}", {"rsi": rsi}))
        elif rsi < 30 and chg < -1.0:
            events.append(self._event(symbol, "MOMENTUM_SHIFT", "MEDIUM",
                f"RSI oversold {rsi:.0f}", {"rsi": rsi}))

        # TREND_REVERSAL
        if (signal in ("BUY", "STRONG_BUY") and rsi < 40) or \
           (signal in ("SELL", "STRONG_SELL") and rsi > 60):
            events.append(self._event(symbol, "TREND_REVERSAL", "HIGH",
                "Signal/RSI divergence", {"rsi": rsi, "signal": signal}))

        # UNUSUAL_ACTIVITY (combination of signals)
        if vol_ratio > 2.0 and abs(chg) > 1.5:
            events.append(self._event(symbol, "UNUSUAL_ACTIVITY", "MEDIUM",
                f"High volume ({vol_ratio:.1f}x) + large move ({chg:.1f}%)",
                {"volume_ratio": vol_ratio, "change_pct": chg}))

        return events

    @staticmethod
    def _event(symbol: str, event_type: str, severity: str,
               description: str, data: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "symbol":      symbol,
            "event_type":  event_type,
            "severity":    severity,
            "description": description,
            "data":        data,
            "advisory_only": True,
            "detected_at": _now_iso(),
        }


# ── Stock Monitoring Agent ────────────────────────────────────────────────────

class StockMonitoringAgent(BaseAgent):
    """
    Monitors configured stock universe with priority-based evaluation.
    Detects 12 event types per symbol. Publishes stock_monitoring snapshot.

    READ-ONLY: reads from portfolio_store, scan_state_store, config only.
    ADVISORY-ONLY: publishes snapshots; never places orders.
    """

    HEARTBEAT_INTERVAL_S: float = 60.0

    def __init__(self) -> None:
        super().__init__(
            agent_id="stock-monitoring-agent",
            name="Stock Monitoring Agent",
            version="1.0.0",
            owner="ApexQuant AI",
            priority=2,
            dependencies=["market-data-agent"],
            capabilities=[
                "breakout_detection", "breakdown_detection",
                "gap_analysis", "vwap_monitoring", "volume_spike",
                "delivery_spike", "momentum_shift", "trend_reversal",
                "new_high_low", "unusual_activity", "priority_engine",
            ],
        )
        self._priority_engine = SmartPriorityEngine()
        self._event_detector  = EventDetector()
        self._last_snapshot: Optional[Dict[str, Any]] = None
        self._all_events: List[Dict[str, Any]] = []

    @property
    def default_topic(self) -> str:
        return "stock_monitoring"

    def execute_task(self) -> Optional[Dict[str, Any]]:
        start_ms = time.monotonic() * 1000

        # Load universe (read-only)
        open_positions = _safe(self._load_open_positions) or []
        watchlist      = _safe(self._load_watchlist)      or []
        scan_items     = _safe(self._load_scan_items)     or []
        nifty50        = _safe(self._load_nifty50)        or []

        # Build priority queue — handle both string items and dict items
        all_symbols_set: list = []
        seen_syms: set = set()
        for item in scan_items[:150]:
            sym = item if isinstance(item, str) else (
                item.get("symbol") or item.get("Symbol") if isinstance(item, dict) else None
            )
            if sym and sym not in seen_syms:
                seen_syms.add(sym)
                all_symbols_set.append(sym)
        all_symbols = all_symbols_set
        queue = self._priority_engine.build_priority_queue(
            open_positions, watchlist, [], nifty50, all_symbols
        )

        # Build symbol data map from scan
        sym_map = _safe(lambda: self._build_sym_map(scan_items)) or {}

        # Evaluate symbols and collect events
        events: List[Dict[str, Any]] = []
        evaluated = 0
        for item in queue[:60]:  # cap per cycle to keep latency < 5s
            sym = item["symbol"]
            data = sym_map.get(sym) or {}
            detected = self._event_detector.detect(sym, data)
            events.extend(detected)
            evaluated += 1

        # Keep rolling event list (last 200)
        self._all_events = (events + self._all_events)[:200]

        priority_summary = self._priority_engine.summary(queue)
        elapsed_ms = round((time.monotonic() * 1000) - start_ms, 1)

        payload = {
            "agent_id":   "stock-monitoring-agent",
            "agent_name": "Stock Monitoring Agent",
            "advisory_only": True,
            "read_only":     True,

            # Universe
            "symbols_monitored":  len(queue),
            "symbols_evaluated":  evaluated,
            "open_positions_count": len(open_positions),
            "watchlist_count":    len(watchlist),
            "scan_universe_count":len(all_symbols),

            # Priority queue summary
            "priority_summary":   priority_summary,
            "priority_queue":     queue[:50],  # top 50 for display

            # Events from this cycle
            "events_this_cycle":  len(events),
            "events":             events[:50],  # top 50 events

            # Event type breakdown
            "event_breakdown":    self._event_breakdown(events),

            # Breakouts/breakdowns highlight
            "breakouts":  [e for e in events if e["event_type"] == "BREAKOUT"][:10],
            "breakdowns": [e for e in events if e["event_type"] == "BREAKDOWN"][:10],
            "gap_events": [e for e in events
                           if e["event_type"] in ("GAP_UP", "GAP_DOWN")][:10],
            "volume_spikes": [e for e in events if e["event_type"] == "VOLUME_SPIKE"][:10],

            "evaluation_latency_ms": elapsed_ms,
            "generated_at": _now_iso(),
        }
        self._last_snapshot = payload
        return payload

    # ── Data loaders (all read-only) ──────────────────────────────────────────

    @staticmethod
    def _load_open_positions() -> List[str]:
        from portfolio_store import load_state
        state = load_state() or {}
        positions = state.get("positions") or []
        return [p.get("symbol", "") for p in positions if p.get("symbol")]

    @staticmethod
    def _load_watchlist() -> List[str]:
        try:
            import signals_store
            wl = signals_store.load_watchlist()
            if wl:
                return list(wl)
        except Exception:
            pass
        try:
            import config
            return list(config.DEFAULT_WATCHLIST)
        except Exception:
            return []

    @staticmethod
    def _load_scan_items() -> List[Any]:
        from scan_state_store import load_latest_snapshot
        snap = load_latest_snapshot() or {}
        return snap.get("items") or snap.get("watchlist") or []

    @staticmethod
    def _load_nifty50() -> List[str]:
        """Load NIFTY 50 symbols from config or return well-known set."""
        try:
            import config
            nifty = getattr(config, "NIFTY50_SYMBOLS", None)
            if nifty:
                return list(nifty)
        except Exception:
            pass
        # Minimal well-known set
        return [
            "RELIANCE", "TCS", "INFY", "HDFCBANK", "ICICIBANK",
            "HINDUNILVR", "SBIN", "BHARTIARTL", "KOTAKBANK", "LT",
            "AXISBANK", "ASIANPAINT", "MARUTI", "SUNPHARMA", "TITAN",
            "WIPRO", "NESTLEIND", "BAJFINANCE", "HCLTECH", "TECHM",
        ]

    @staticmethod
    def _build_sym_map(items: List[Any]) -> Dict[str, Dict[str, Any]]:
        sym_map = {}
        for item in items:
            if isinstance(item, dict):
                sym = item.get("symbol") or item.get("Symbol")
                if sym:
                    sym_map[sym] = item
            elif isinstance(item, str):
                sym_map[item] = {}
        return sym_map

    @staticmethod
    def _event_breakdown(events: List[Dict]) -> Dict[str, int]:
        from collections import Counter
        c = Counter(e["event_type"] for e in events)
        return dict(c)

    def get_all_events(self) -> List[Dict[str, Any]]:
        return list(self._all_events)

    def last_snapshot(self) -> Optional[Dict[str, Any]]:
        return self._last_snapshot
