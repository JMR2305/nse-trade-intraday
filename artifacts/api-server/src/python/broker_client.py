"""
broker_client.py  —  Phase 8: Broker Integration & Live Execution Readiness
Abstract broker client + Zerodha implementation (read-only by default) + Mock.

Design principles
-----------------
* Default is MOCK mode — no real connection until credentials are provided and
  the user explicitly enables LIVE_ASSISTED execution mode.
* Credentials are ONLY read from environment variables (ZERODHA_API_KEY,
  ZERODHA_ACCESS_TOKEN). They are NEVER written to disk, logged, or returned
  in API responses. They are masked in all output with "****".
* The client is READ-ONLY for account data (profile, margins, holdings,
  positions, orders). Order placement is guarded by ExecutionEngine.
* Zerodha Kite Connect is used if available + credentials present; otherwise
  falls back to MockBrokerClient automatically.
* All timestamps are UTC ISO-8601.

PAPER TRADING DEFAULT — no real orders placed without explicit user confirmation
in LIVE_ASSISTED mode with all safety checks passing and kill switch off.
"""

from __future__ import annotations

import logging
import os
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ── Credential helpers ────────────────────────────────────────────────────────

def _mask(s: Optional[str]) -> str:
    """Mask a credential for display. Never expose real values."""
    if not s:
        return "(not set)"
    if len(s) <= 6:
        return "****"
    return s[:3] + "****" + s[-2:]


def _get_creds() -> tuple[Optional[str], Optional[str]]:
    """Read Zerodha credentials from environment. Never cache to disk."""
    api_key = os.environ.get("ZERODHA_API_KEY") or None
    token   = os.environ.get("ZERODHA_ACCESS_TOKEN") or None
    return api_key, token


def creds_present() -> bool:
    k, t = _get_creds()
    return bool(k and t)


def masked_creds() -> Dict[str, str]:
    k, t = _get_creds()
    return {
        "api_key_masked": _mask(k),
        "access_token_masked": _mask(t),
        "api_key_set": bool(k),
        "access_token_set": bool(t),
    }


# ── Data structures ───────────────────────────────────────────────────────────

@dataclass
class BrokerProfile:
    broker: str
    user_id: str
    user_name: str
    email: str
    exchanges: List[str]
    products: List[str]
    order_types: List[str]
    fetched_at: str


@dataclass
class BrokerMargin:
    available_cash: float
    collateral: float
    intraday_payin: float
    used_margin: float
    available_margin: float
    net: float
    fetched_at: str


@dataclass
class BrokerHolding:
    symbol: str
    exchange: str
    quantity: int
    avg_price: float
    ltp: float
    pnl: float
    pnl_pct: float
    day_change: float
    day_change_pct: float


@dataclass
class BrokerPosition:
    symbol: str
    exchange: str
    product: str
    quantity: int
    avg_price: float
    ltp: float
    pnl: float
    unrealised: float
    realised: float


@dataclass
class BrokerOrder:
    order_id: str
    symbol: str
    exchange: str
    transaction_type: str   # BUY | SELL
    order_type: str         # MARKET | LIMIT | SL | SL-M
    product: str            # CNC | MIS | NRML
    quantity: int
    price: float
    trigger_price: float
    status: str
    status_message: str
    placed_at: str
    filled_quantity: int
    pending_quantity: int
    average_price: float


@dataclass
class BrokerConnectionStatus:
    connected: bool
    broker: str
    user_id: Optional[str]
    token_status: str       # VALID | EXPIRED | MISSING | ERROR
    token_age_hours: Optional[float]
    last_successful_call: Optional[str]
    error: Optional[str]
    latency_ms: Optional[int]
    is_mock: bool
    credentials_present: bool
    note: str


# ── Abstract base ─────────────────────────────────────────────────────────────

class BrokerClient(ABC):
    """Abstract broker interface. Swap ZerodhaClient → KiteConnect production."""

    @property
    @abstractmethod
    def is_mock(self) -> bool: ...

    @abstractmethod
    def test_connection(self) -> BrokerConnectionStatus: ...

    @abstractmethod
    def get_profile(self) -> BrokerProfile: ...

    @abstractmethod
    def get_margins(self) -> BrokerMargin: ...

    @abstractmethod
    def get_holdings(self) -> List[BrokerHolding]: ...

    @abstractmethod
    def get_positions(self) -> List[BrokerPosition]: ...

    @abstractmethod
    def get_orders(self, limit: int = 50) -> List[BrokerOrder]: ...

    @abstractmethod
    def place_order_live(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Submit a real order. Only callable from ExecutionEngine after ALL
        safety checks, kill-switch verification, and explicit user confirmation.
        Never call this directly.
        """
        ...


# ── Mock client (always safe, no credentials needed) ─────────────────────────

class MockBrokerClient(BrokerClient):
    """
    Mock Zerodha client for development, paper-trading, and testing.
    Returns realistic-looking static data. Never touches real broker APIs.
    """

    def __init__(self, scenario: str = "ok"):
        self._scenario = scenario  # ok | expired_token | insufficient_funds | disconnected

    @property
    def is_mock(self) -> bool:
        return True

    def test_connection(self) -> BrokerConnectionStatus:
        t0 = time.monotonic()
        time.sleep(0.05)  # simulate latency
        lat = int((time.monotonic() - t0) * 1000)
        if self._scenario == "disconnected":
            return BrokerConnectionStatus(
                connected=False, broker="Zerodha (Mock)", user_id=None,
                token_status="ERROR", token_age_hours=None,
                last_successful_call=None, error="Connection refused (mock)",
                latency_ms=None, is_mock=True, credentials_present=False,
                note="MOCK — no real broker connected",
            )
        if self._scenario == "expired_token":
            return BrokerConnectionStatus(
                connected=False, broker="Zerodha (Mock)", user_id="ZW0001",
                token_status="EXPIRED", token_age_hours=25.0,
                last_successful_call=None, error="Token expired",
                latency_ms=lat, is_mock=True, credentials_present=True,
                note="MOCK — token expired scenario",
            )
        return BrokerConnectionStatus(
            connected=True, broker="Zerodha (Mock)", user_id="ZW0001",
            token_status="VALID", token_age_hours=2.5,
            last_successful_call=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            error=None, latency_ms=lat, is_mock=True, credentials_present=False,
            note="MOCK — paper trading mode; no real orders placed",
        )

    def get_profile(self) -> BrokerProfile:
        return BrokerProfile(
            broker="Zerodha (Mock)", user_id="ZW0001",
            user_name="Research Trader", email="***@***.com",
            exchanges=["NSE", "BSE", "NFO"],
            products=["CNC", "MIS", "NRML"],
            order_types=["MARKET", "LIMIT", "SL", "SL-M"],
            fetched_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        )

    def get_margins(self) -> BrokerMargin:
        if self._scenario == "insufficient_funds":
            return BrokerMargin(
                available_cash=0.0, collateral=0.0, intraday_payin=0.0,
                used_margin=5000.0, available_margin=0.0, net=0.0,
                fetched_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            )
        return BrokerMargin(
            available_cash=5000.0, collateral=0.0, intraday_payin=0.0,
            used_margin=0.0, available_margin=5000.0, net=5000.0,
            fetched_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        )

    def get_holdings(self) -> List[BrokerHolding]:
        return [
            BrokerHolding("WIPRO", "NSE", 2, 445.50, 449.10, 7.20, 0.81, 3.60, 0.81),
        ]

    def get_positions(self) -> List[BrokerPosition]:
        return []

    def get_orders(self, limit: int = 50) -> List[BrokerOrder]:
        return []

    def place_order_live(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Mock order placement — never touches real API."""
        if self._scenario == "rejected":
            return {"success": False, "status": "REJECTED",
                    "order_id": None, "message": "RMS: Insufficient funds (mock)",
                    "is_mock": True}
        if self._scenario == "partial_fill":
            return {"success": True, "status": "PARTIALLY_FILLED",
                    "order_id": "MOCK-ORD-002", "filled_quantity": 1,
                    "pending_quantity": 1, "message": "Partial fill (mock)",
                    "is_mock": True}
        return {"success": True, "status": "SUBMITTED",
                "order_id": f"MOCK-ORD-{int(time.time())}", "message": "Order submitted (mock)",
                "is_mock": True}


# ── Zerodha Kite Connect client (real, read-only by default) ──────────────────

class ZerodhaClient(BrokerClient):
    """
    Real Zerodha Kite Connect client.
    Credentials read ONLY from environment variables — never stored anywhere else.
    Raises on import failure so caller falls back to MockBrokerClient.
    """

    def __init__(self):
        try:
            from kiteconnect import KiteConnect
        except ImportError:
            raise ImportError("kiteconnect not installed. Run: pip install kiteconnect")

        api_key, token = _get_creds()
        if not api_key or not token:
            raise ValueError("ZERODHA_API_KEY and ZERODHA_ACCESS_TOKEN env vars required")

        from kiteconnect import KiteConnect as _KC
        self._kite = _KC(api_key=api_key)
        self._kite.set_access_token(token)
        self._token_set_at = datetime.now(timezone.utc)

    @property
    def is_mock(self) -> bool:
        return False

    def _now(self) -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    def test_connection(self) -> BrokerConnectionStatus:
        t0 = time.monotonic()
        try:
            profile = self._kite.profile()
            lat = int((time.monotonic() - t0) * 1000)
            age = (datetime.now(timezone.utc) - self._token_set_at).total_seconds() / 3600
            return BrokerConnectionStatus(
                connected=True, broker="Zerodha Kite Connect",
                user_id=profile.get("user_id", "unknown"),
                token_status="VALID", token_age_hours=round(age, 2),
                last_successful_call=self._now(), error=None,
                latency_ms=lat, is_mock=False, credentials_present=True,
                note="Connected to Zerodha. Read-only until LIVE_ASSISTED enabled.",
            )
        except Exception as exc:
            msg = str(exc)
            lat = int((time.monotonic() - t0) * 1000)
            expired = "token" in msg.lower() or "access_token" in msg.lower()
            return BrokerConnectionStatus(
                connected=False, broker="Zerodha Kite Connect", user_id=None,
                token_status="EXPIRED" if expired else "ERROR",
                token_age_hours=None, last_successful_call=None,
                error=msg[:200], latency_ms=lat, is_mock=False,
                credentials_present=True,
                note="Connection failed. Re-login to Zerodha to refresh access token.",
            )

    def get_profile(self) -> BrokerProfile:
        p = self._kite.profile()
        return BrokerProfile(
            broker="Zerodha Kite Connect", user_id=p.get("user_id", ""),
            user_name=p.get("user_name", ""), email="***@***.com",
            exchanges=p.get("exchanges", []), products=p.get("products", []),
            order_types=p.get("order_types", []), fetched_at=self._now(),
        )

    def get_margins(self) -> BrokerMargin:
        m = self._kite.margins("equity")
        net = m.get("net", 0.0)
        avail = m.get("available", {})
        util = m.get("utilised", {})
        return BrokerMargin(
            available_cash=avail.get("cash", 0.0),
            collateral=avail.get("collateral", 0.0),
            intraday_payin=avail.get("intraday_payin", 0.0),
            used_margin=util.get("debits", 0.0),
            available_margin=avail.get("cash", 0.0),
            net=net, fetched_at=self._now(),
        )

    def get_holdings(self) -> List[BrokerHolding]:
        raw = self._kite.holdings()
        return [BrokerHolding(
            symbol=h.get("tradingsymbol", ""), exchange=h.get("exchange", "NSE"),
            quantity=int(h.get("quantity", 0)),
            avg_price=float(h.get("average_price", 0.0)),
            ltp=float(h.get("last_price", 0.0)),
            pnl=float(h.get("pnl", 0.0)),
            pnl_pct=round(float(h.get("pnl", 0.0)) / max(float(h.get("average_price", 1.0)) * max(int(h.get("quantity", 1)), 1), 1) * 100, 2),
            day_change=float(h.get("day_change", 0.0)),
            day_change_pct=float(h.get("day_change_percentage", 0.0)),
        ) for h in raw]

    def get_positions(self) -> List[BrokerPosition]:
        raw = self._kite.positions()
        out = []
        for p in raw.get("net", []):
            out.append(BrokerPosition(
                symbol=p.get("tradingsymbol", ""), exchange=p.get("exchange", "NSE"),
                product=p.get("product", "CNC"), quantity=int(p.get("quantity", 0)),
                avg_price=float(p.get("average_price", 0.0)),
                ltp=float(p.get("last_price", 0.0)),
                pnl=float(p.get("pnl", 0.0)),
                unrealised=float(p.get("unrealised", 0.0)),
                realised=float(p.get("realised", 0.0)),
            ))
        return out

    def get_orders(self, limit: int = 50) -> List[BrokerOrder]:
        raw = self._kite.orders()[-limit:]
        return [BrokerOrder(
            order_id=o.get("order_id", ""), symbol=o.get("tradingsymbol", ""),
            exchange=o.get("exchange", "NSE"),
            transaction_type=o.get("transaction_type", ""),
            order_type=o.get("order_type", ""), product=o.get("product", "CNC"),
            quantity=int(o.get("quantity", 0)),
            price=float(o.get("price", 0.0)),
            trigger_price=float(o.get("trigger_price", 0.0)),
            status=o.get("status", ""), status_message=o.get("status_message", ""),
            placed_at=str(o.get("order_timestamp", "")),
            filled_quantity=int(o.get("filled_quantity", 0)),
            pending_quantity=int(o.get("pending_quantity", 0)),
            average_price=float(o.get("average_price", 0.0)),
        ) for o in raw]

    def place_order_live(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Place a real order. Called ONLY by ExecutionEngine after all checks."""
        try:
            order_id = self._kite.place_order(
                variety=params.get("variety", "regular"),
                exchange=params.get("exchange", "NSE"),
                tradingsymbol=params.get("symbol", ""),
                transaction_type=params.get("transaction_type", "BUY"),
                quantity=int(params.get("quantity", 1)),
                product=params.get("product", "CNC"),
                order_type=params.get("order_type", "LIMIT"),
                price=params.get("price"),
                trigger_price=params.get("trigger_price"),
                tag=params.get("tag", "nse_algo"),
            )
            return {"success": True, "status": "SUBMITTED", "order_id": str(order_id),
                    "message": "Order submitted to Zerodha", "is_mock": False}
        except Exception as exc:
            return {"success": False, "status": "REJECTED", "order_id": None,
                    "message": str(exc)[:300], "is_mock": False}


# ── Factory ───────────────────────────────────────────────────────────────────

def get_broker_client(scenario: str = "ok") -> BrokerClient:
    """
    Return the appropriate broker client.
    Tries ZerodhaClient if credentials present, falls back to MockBrokerClient.
    'scenario' only applies to MockBrokerClient.
    """
    if creds_present():
        try:
            return ZerodhaClient()
        except Exception as exc:
            logger.warning("ZerodhaClient unavailable (%s) — using mock", exc)
    return MockBrokerClient(scenario=scenario)
