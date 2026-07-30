"""
preopen_engine.py — Phase 5A Pre-Open Intelligence main engine.

Orchestrates: provider → analytics → classification → watchlist → DB storage.

Feature flag: PREOPEN_INTELLIGENCE_ENABLED must be truthy or every call
returns {"status": "DISABLED", ...} without touching the provider.

PAPER TRADING / ADVISORY ONLY.
Pre-open data CANNOT submit orders or bypass the risk engine.
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from preopen_data_model import (
    PreOpenSnapshot, PreOpenSession, ProviderState, Classification, now_ist_str,
)
from preopen_analytics import enrich_universe
import preopen_db as db

_ENABLED_VAR = "PREOPEN_INTELLIGENCE_ENABLED"


def _is_enabled() -> bool:
    return os.environ.get(_ENABLED_VAR, "false").lower() in ("1", "true", "yes")


def _disabled_response(extra: dict | None = None) -> dict:
    resp = {
        "status": "DISABLED",
        "feature_flag": _ENABLED_VAR,
        "message": f"Pre-Open Intelligence is disabled. "
                   f"Set {_ENABLED_VAR}=true to enable.",
        "label": "PAPER / ADVISORY ONLY",
    }
    if extra:
        resp.update(extra)
    return resp


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _today_ist() -> str:
    from datetime import timedelta
    # IST = UTC+5:30
    return (datetime.now(timezone.utc) + timedelta(hours=5, minutes=30)).strftime("%Y-%m-%d")


def _get_provider(symbols=None):
    """
    Get the best available provider via the priority chain:
      1. NSE Official  (full auction data: IEP, buy/sell qty, imbalance)
      2. Zerodha Kite  (IEP + prev close; no order-book quantities)
      3. Yahoo Finance (prev close + open; fallback only)

    PREOPEN_PROVIDER env var can force a specific provider:
      mock    — fixture data (unit tests only)
      yfinance — Yahoo Finance only
      auto    — priority chain (default)
    """
    provider_name = os.environ.get("PREOPEN_PROVIDER", "auto").lower()
    if provider_name == "mock":
        from preopen_provider import MockPreOpenProvider
        return MockPreOpenProvider()
    if provider_name == "yfinance":
        from preopen_provider import YFinancePreOpenProvider
        return YFinancePreOpenProvider()
    # Default: auto-select via priority chain (NSE → Kite → Yahoo)
    from preopen_provider_manager import get_best_provider
    provider, _label = get_best_provider()
    return provider


# ── Status ────────────────────────────────────────────────────────────────────

def get_status() -> dict:
    if not _is_enabled():
        return _disabled_response()
    try:
        from preopen_intelligence_tick import get_tick_status
        session  = db.get_latest_session()
        provider = _get_provider()
        health   = provider.health_check()
        today    = _today_ist()
        snaps    = db.get_latest_snapshots(today)
        ts       = get_tick_status()
        return {
            "status":           "ENABLED",
            "feature_flag":     _ENABLED_VAR,
            "trading_date":     today,
            "provider_status":  health.get("status", ProviderState.UNAVAILABLE),
            "provider_message": health.get("message", ""),
            "provider_label":   health.get("provider", getattr(provider, "PROVIDER_LABEL", "Unknown")),
            "session":          session,
            "symbols_analysed": len(snaps),
            "valid_records":    sum(1 for s in snaps if not s.get("is_stale")),
            "stale_records":    sum(1 for s in snaps if s.get("is_stale")),
            "last_updated":     snaps[0].get("created_at") if snaps else None,
            "scheduler": {
                "registered":     True,
                "auto_tick":      True,
                "active":         ts.get("active", False),
                "ist_time":       ts.get("ist_time"),
                "trading_day":    ts.get("trading_day"),
                "active_phase":   ts.get("active_phase"),
                "next_phase":     ts.get("next_phase"),
                "collect_count":  ts.get("collect_count", 0),
                "phases_done":    ts.get("phases_done", []),
                "all_phases":     ts.get("all_phases", []),
                "session_id":     ts.get("session_id"),
            },
            "label":            "PAPER / ADVISORY ONLY",
        }
    except Exception as e:
        return {"status": "ERROR", "error": str(e), "label": "PAPER / ADVISORY ONLY"}


def get_health() -> dict:
    if not _is_enabled():
        return _disabled_response()
    try:
        provider = _get_provider()
        health = provider.health_check()
        today = _today_ist()
        db.save_provider_health(None, today, type(provider).__name__, health)
        return {
            "success": True,
            "provider_health": health,
            "trading_date": today,
            "label": "PAPER / ADVISORY ONLY",
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


# ── Snapshot collection ───────────────────────────────────────────────────────

def _ensure_session(trading_date: str, session_id: str) -> str:
    """Upsert a session record and return its session_id."""
    db.upsert_session({
        "session_id": session_id,
        "trading_date": trading_date,
        "status": "COLLECTING",
        "provider_status": ProviderState.LIVE,
    })
    return session_id


def collect_snapshot(session_id: Optional[str] = None) -> dict:
    """
    Collect one pre-open snapshot across the watchlist.
    Safe to call repeatedly; each call stores a new batch of snapshots.
    """
    if not _is_enabled():
        return _disabled_response()

    today = _today_ist()
    session_id = session_id or f"preopen-{today}-{uuid.uuid4().hex[:8]}"
    _ensure_session(today, session_id)

    try:
        provider = _get_provider()
        health = provider.health_check()

        # Provider unavailable — do not crash, mark module unavailable
        if health.get("status") == ProviderState.UNAVAILABLE:
            db.upsert_session({
                "session_id": session_id,
                "trading_date": today,
                "status": "COLLECTING",
                "provider_status": ProviderState.UNAVAILABLE,
                "error": health.get("message", "Provider unavailable"),
            })
            return {
                "success": False,
                "status": "PROVIDER_UNAVAILABLE",
                "provider_health": health,
                "session_id": session_id,
                "label": "PAPER / ADVISORY ONLY",
            }

        raw_snapshots = provider.fetch_market_snapshot()
        if not raw_snapshots:
            return {
                "success": False,
                "status": "NO_DATA",
                "session_id": session_id,
                "label": "PAPER / ADVISORY ONLY",
            }

        # Analytics enrichment
        enriched = enrich_universe(raw_snapshots)

        snaps_dicts = [s.to_dict() for s in enriched]
        db.save_snapshots(session_id, snaps_dicts)

        valid = sum(1 for s in enriched if not s.is_stale)
        stale = sum(1 for s in enriched if s.is_stale)
        db.upsert_session({
            "session_id": session_id,
            "trading_date": today,
            "status": "COLLECTING",
            "symbol_count": len(enriched),
            "valid_count": valid,
            "stale_count": stale,
            "provider_status": health.get("status", ProviderState.DELAYED),
        })

        return {
            "success": True,
            "status": "COLLECTED",
            "session_id": session_id,
            "symbol_count": len(enriched),
            "valid_count": valid,
            "stale_count": stale,
            "provider_status": health.get("status"),
            "provider_label": health.get("provider", getattr(provider, "PROVIDER_LABEL", "Unknown")),
            "label": "PAPER / ADVISORY ONLY",
        }
    except Exception as e:
        db.upsert_session({
            "session_id": session_id,
            "trading_date": today,
            "status": "ERROR",
            "error": str(e),
        })
        return {"success": False, "error": str(e), "session_id": session_id}


# ── Snapshot retrieval ────────────────────────────────────────────────────────

def get_snapshot() -> dict:
    if not _is_enabled():
        return _disabled_response()
    today = _today_ist()
    snaps = db.get_latest_snapshots(today)
    session = db.get_latest_session()
    # Derive the active provider label from the stored snapshots (avoids an
    # extra provider health-check on every poll).  Falls back to the current
    # provider's label when no snapshots exist yet.
    provider_label: str = "Unknown"
    if snaps:
        provider_label = snaps[0].get("provider_label") or "Unknown"
    if provider_label == "Unknown":
        try:
            p = _get_provider()
            provider_label = getattr(p, "PROVIDER_LABEL", "Unknown")
        except Exception:
            pass
    return {
        "success": True,
        "trading_date": today,
        "session": session,
        "snapshots": snaps,
        "count": len(snaps),
        "valid_count": sum(1 for s in snaps if not s.get("is_stale")),
        "stale_count": sum(1 for s in snaps if s.get("is_stale")),
        "provider_label": provider_label,
        "label": "PAPER / ADVISORY ONLY",
    }


def get_symbol_snapshot(symbol: str) -> dict:
    if not _is_enabled():
        return _disabled_response({"symbol": symbol})
    today = _today_ist()
    snaps = db.get_latest_snapshots(today)
    sym = symbol.upper()
    match = [s for s in snaps if str(s.get("symbol", "")).upper() == sym]
    if not match:
        return {"success": False, "error": f"No pre-open snapshot found for {sym}",
                "symbol": sym, "label": "PAPER / ADVISORY ONLY"}
    return {"success": True, "symbol": sym, "snapshot": match[0],
            "label": "PAPER / ADVISORY ONLY"}


# ── Rankings ──────────────────────────────────────────────────────────────────

def get_rankings() -> dict:
    if not _is_enabled():
        return _disabled_response()
    today = _today_ist()
    snaps = db.get_latest_snapshots(today)
    ranked = sorted(snaps, key=lambda s: -(s.get("opportunity_score") or 0))
    return {
        "success": True,
        "trading_date": today,
        "rankings": ranked,
        "count": len(ranked),
        "label": "PAPER / ADVISORY ONLY",
    }


# ── Sectors ───────────────────────────────────────────────────────────────────

def get_sectors() -> dict:
    if not _is_enabled():
        return _disabled_response()
    today = _today_ist()
    snaps = db.get_latest_snapshots(today)
    sectors: Dict[str, dict] = {}
    for s in snaps:
        sec = s.get("sector") or "Unknown"
        if sec not in sectors:
            sectors[sec] = {"sector": sec, "count": 0, "avg_gap": 0, "avg_score": 0,
                            "gaps": [], "scores": []}
        g = s.get("gap_percent")
        sc = s.get("opportunity_score")
        if g is not None:
            sectors[sec]["gaps"].append(g)
        if sc is not None:
            sectors[sec]["scores"].append(sc)
        sectors[sec]["count"] += 1

    result = []
    for sec, data in sectors.items():
        gaps = data.pop("gaps")
        scores = data.pop("scores")
        data["avg_gap"] = round(sum(gaps) / len(gaps), 4) if gaps else 0
        data["avg_score"] = round(sum(scores) / len(scores), 2) if scores else 0
        data["leading"] = data["avg_gap"] > 0
        result.append(data)
    result.sort(key=lambda x: -abs(x["avg_gap"]))
    return {"success": True, "trading_date": today, "sectors": result,
            "label": "PAPER / ADVISORY ONLY"}


# ── Report ────────────────────────────────────────────────────────────────────

def get_watchlists() -> dict:
    """Return the 8 pre-open watchlists for today."""
    if not _is_enabled():
        return _disabled_response()
    today = _today_ist()
    watchlists = db.get_latest_watchlists(today)
    return {
        "success": True,
        "trading_date": today,
        "watchlists": watchlists,
        "label": "PAPER / ADVISORY ONLY",
        "note": "Pre-open watchlists are advisory only. No trades are generated.",
    }


def get_report() -> dict:
    if not _is_enabled():
        return _disabled_response()
    today = _today_ist()
    session = db.get_latest_session()
    snaps = db.get_latest_snapshots(today)
    watchlists = db.get_latest_watchlists(today)
    recon = db.get_reconciliation(today)
    ranked = sorted(snaps, key=lambda s: -(s.get("opportunity_score") or 0))

    return {
        "success": True,
        "trading_date": today,
        "session": session,
        "summary": {
            "symbols_analysed": len(snaps),
            "valid_records": sum(1 for s in snaps if not s.get("is_stale")),
            "stale_records": sum(1 for s in snaps if s.get("is_stale")),
            "strong_gap_up": sum(1 for s in snaps if s.get("classification") == "STRONG_GAP_UP"),
            "strong_gap_down": sum(1 for s in snaps if s.get("classification") == "STRONG_GAP_DOWN"),
            "data_incomplete": sum(1 for s in snaps if s.get("classification") == "DATA_INCOMPLETE"),
        },
        "top_ranked": ranked[:10],
        "watchlists": watchlists,
        "reconciliation": recon,
        "label": "PAPER / ADVISORY ONLY",
        "note": "Pre-open intelligence is advisory only. "
                "No trades are generated from this data.",
    }


# ── Refresh (POST) ────────────────────────────────────────────────────────────

def refresh() -> dict:
    """Trigger a fresh snapshot collection manually."""
    if not _is_enabled():
        return _disabled_response()
    today = _today_ist()
    session_id = f"preopen-{today}-manual-{uuid.uuid4().hex[:6]}"
    return collect_snapshot(session_id=session_id)


# ── Signal hints (Trade Decisions integration) ────────────────────────────────

def get_signal_hints(min_score: float = 70.0) -> dict:
    """
    Return pre-open signal hints for the Trade Decisions feed.

    Filters today's snapshots to STRONG_GAP_UP candidates with
    opportunity_score >= min_score and non-stale data.  Each hint is
    labelled "PRE-OPEN ADVISORY" so operators can distinguish them from
    live-scan signals.

    Advisory only — this function never generates or implies an order.
    """
    if not _is_enabled():
        return _disabled_response()

    today = _today_ist()
    snaps = db.get_latest_snapshots(today)

    hints: List[dict] = []
    for s in snaps:
        if (
            s.get("classification") == Classification.STRONG_GAP_UP
            and (s.get("opportunity_score") or 0) >= min_score
            and not s.get("is_stale", True)
        ):
            factors = s.get("factor_scores") or {}
            # Normalise factor_scores — may be stored as JSON string
            if isinstance(factors, str):
                try:
                    import json as _json
                    factors = _json.loads(factors)
                except Exception:
                    factors = {}

            hints.append({
                "symbol": s.get("symbol"),
                "sector": s.get("sector"),
                "classification": s.get("classification"),
                "opportunity_score": s.get("opportunity_score"),
                "gap_percent": s.get("gap_percent"),
                "imbalance_percent": s.get("imbalance_percent"),
                "buy_sell_imbalance": s.get("buy_sell_imbalance"),
                "order_book_available": s.get("order_book_available", False),
                "executed_quantity": s.get("final_executed_quantity"),
                "liquidity_score": s.get("liquidity_score"),
                "previous_close": s.get("previous_close"),
                "indicative_price": (
                    s.get("indicative_equilibrium_price")
                    or s.get("indicative_open_price")
                ),
                "factor_scores": factors,
                "data_source": s.get("data_source", "unknown"),
                "provider_label": s.get("provider_label", "Unknown"),
                "label": "PRE-OPEN ADVISORY",
                "advisory_only": True,
            })

    hints.sort(key=lambda h: -(h.get("opportunity_score") or 0))

    return {
        "success": True,
        "trading_date": today,
        "signal_hints": hints,
        "count": len(hints),
        "min_score_threshold": min_score,
        "classification_filter": Classification.STRONG_GAP_UP,
        "label": "PRE-OPEN ADVISORY",
        "advisory_only": True,
        "note": (
            "Pre-open signal hints are advisory only. "
            "No orders are generated automatically from this data."
        ),
    }
