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
        return YFinancePreOpenProvider(symbols)
    # Default: auto-select via priority chain (NSE → Kite → Yahoo)
    from preopen_provider_manager import get_best_provider
    provider, _label = get_best_provider(symbols)
    return provider


def _normalise_symbols(symbols) -> List[str]:
    seen = set()
    result = []
    for symbol in symbols or []:
        value = str(symbol or "").strip().upper()
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result


def _resolve_collection_symbols() -> List[str]:
    """Resolve the authoritative symbol set for this Phase 5A collection.

    The custom universe is durable operator configuration, not a display
    watchlist. An empty or unavailable custom universe must fail closed rather
    than falling back to the legacy ten-symbol default.
    """
    import config

    expected_symbols: List[str] = []
    try:
        active_universe = config.get_active_intraday_universe_strict()
    except Exception:
        # Environment values are only initial defaults; they cannot prove that
        # an operator has not durably selected the custom universe. Therefore a
        # settings read outage is indeterminate and must fail closed.
        return []
    if active_universe == config.UniverseMode.CUSTOM_LOW_PRICE_SECTOR:
        from custom_universe_store import get_active_symbols
        try:
            return _normalise_symbols(get_active_symbols())
        except Exception:
            return []
    return _normalise_symbols(config.DEFAULT_WATCHLIST)


def _coverage_for_serialized_rows(rows, expected_symbols: List[str],
                                  provider_returned_count: Optional[int] = None) -> tuple:
    """Canonicalise the exact rows that will be persisted and account for coverage."""
    expected = _normalise_symbols(expected_symbols)
    expected_set = set(expected)
    accepted_rows = []
    accepted_symbols = set()
    accepted_snapshot_ids = set()
    duplicate_symbols = []
    duplicate_snapshot_ids = []
    unexpected_symbols = []
    malformed_count = 0

    for row in rows or []:
        if not isinstance(row, dict):
            malformed_count += 1
            continue
        normalised = str(row.get("symbol") or "").strip().upper()
        snapshot_id = str(row.get("snapshot_id") or "").strip()
        if not normalised or not snapshot_id:
            malformed_count += 1
        elif normalised not in expected_set:
            unexpected_symbols.append(normalised)
        elif normalised in accepted_symbols:
            duplicate_symbols.append(normalised)
        elif snapshot_id in accepted_snapshot_ids:
            duplicate_snapshot_ids.append(snapshot_id)
        else:
            canonical = dict(row)
            canonical["symbol"] = normalised
            canonical["snapshot_id"] = snapshot_id
            accepted_rows.append(canonical)
            accepted_symbols.add(normalised)
            accepted_snapshot_ids.add(snapshot_id)

    missing_symbols = sorted(expected_set - accepted_symbols)
    coverage = {
        "expected_count": len(expected),
        "provider_returned_count": (
            len(rows or []) if provider_returned_count is None else provider_returned_count
        ),
        "normalized_count": len(accepted_rows),
        "missing_count": len(missing_symbols),
        "duplicate_count": len(duplicate_symbols) + len(duplicate_snapshot_ids),
        "malformed_count": malformed_count,
        "unexpected_count": len(unexpected_symbols),
        "expected_symbols": expected,
        "normalized_symbols": sorted(accepted_symbols),
        "missing_symbols": missing_symbols,
        "duplicate_symbols": sorted(duplicate_symbols),
        "duplicate_snapshot_ids": sorted(duplicate_snapshot_ids),
        "unexpected_symbols": sorted(unexpected_symbols),
        "unusable_count": (
            len(duplicate_symbols) + len(duplicate_snapshot_ids)
            + malformed_count + len(unexpected_symbols)
        ),
    }
    return accepted_rows, coverage


def _coverage_for_expected_symbols(raw_snapshots, expected_symbols: List[str]) -> tuple:
    """Validate provider objects by the exact serialized identity they advertise."""
    serialized = []
    for snapshot in raw_snapshots or []:
        try:
            serialized.append((snapshot, snapshot.to_dict()))
        except Exception:
            serialized.append((snapshot, None))
    accepted_rows, coverage = _coverage_for_serialized_rows(
        [row for _, row in serialized], expected_symbols,
        provider_returned_count=len(raw_snapshots or []),
    )
    remaining = {
        (row["symbol"], row["snapshot_id"])
        for row in accepted_rows
    }
    accepted_snapshots = []
    for snapshot, row in serialized:
        if not isinstance(row, dict):
            continue
        identity = (
            str(row.get("symbol") or "").strip().upper(),
            str(row.get("snapshot_id") or "").strip(),
        )
        if identity in remaining:
            accepted_snapshots.append(snapshot)
            remaining.remove(identity)
    return accepted_snapshots, coverage


def _merge_coverage(initial: dict, final: dict) -> dict:
    """Keep provider-stage rejects and validate the post-enrichment write rows."""
    merged = dict(final)
    for key in ("duplicate_symbols", "duplicate_snapshot_ids", "unexpected_symbols"):
        merged[key] = sorted(set(initial.get(key, []) + final.get(key, [])))
    merged["duplicate_count"] = (
        len(merged["duplicate_symbols"]) + len(merged["duplicate_snapshot_ids"])
    )
    merged["malformed_count"] = (
        int(initial.get("malformed_count") or 0)
        + int(final.get("malformed_count") or 0)
    )
    merged["unexpected_count"] = len(merged["unexpected_symbols"])
    merged["provider_returned_count"] = initial.get("provider_returned_count", 0)
    merged["unusable_count"] = (
        merged["duplicate_count"] + merged["malformed_count"]
        + merged["unexpected_count"]
    )
    return merged


def _outcome_summary(outcomes: List[dict]) -> dict:
    counts: Dict[str, int] = {}
    for outcome in outcomes:
        status = str(outcome.get("outcome_status") or "UNCLASSIFIED")
        counts[status] = counts.get(status, 0) + 1
    return counts


def _coverage_with_outcomes(coverage: dict, outcomes: List[dict],
                            provider_raw_count: Optional[int] = None,
                            provider_scope: Optional[str] = None) -> dict:
    """Attach auditable, non-price outcome evidence to collection coverage."""
    result = dict(coverage)
    expected = _normalise_symbols(result.get("expected_symbols") or [])
    outcome_symbols = {
        str(outcome.get("symbol") or "").strip().upper()
        for outcome in outcomes
        if str(outcome.get("symbol") or "").strip()
    }
    result["provider_raw_count"] = (
        int(provider_raw_count)
        if provider_raw_count is not None
        else int(result.get("provider_returned_count") or 0)
    )
    result["provider_scope"] = provider_scope
    result["outcome_accounted_count"] = len(outcome_symbols)
    result["outcome_status_counts"] = _outcome_summary(outcomes)
    result["outcome_complete"] = (
        bool(expected)
        and len(outcomes) == len(expected)
        and outcome_symbols == set(expected)
    )
    return result


def _generic_provider_outcomes(expected_symbols: List[str],
                               snapshots: List[Any]) -> List[dict]:
    """Provide honest outcomes for providers without a richer evidence API."""
    present = {
        str(getattr(snapshot, "symbol", "") or "").strip().upper(): snapshot
        for snapshot in snapshots or []
        if str(getattr(snapshot, "symbol", "") or "").strip()
    }
    outcomes = []
    for symbol in _normalise_symbols(expected_symbols):
        snapshot = present.get(symbol)
        if snapshot is None:
            outcomes.append({
                "symbol": symbol,
                "outcome_status": "NO_PREOPEN_DATA",
                "reason_code": "SYMBOL_ABSENT_FROM_PROVIDER_RESULT",
                "provider_symbol": symbol,
                "provider_response_present": False,
                "normalization_result": "NOT_OBSERVED",
                "eligibility_status": "UNKNOWN",
            })
        else:
            outcomes.append({
                "symbol": symbol,
                "outcome_status": "LIVE_PREOPEN_DATA",
                "reason_code": "PROVIDER_SNAPSHOT_RETURNED",
                "provider_symbol": symbol,
                "provider_response_present": True,
                "normalization_result": "NORMALIZED",
                "eligibility_status": "UNKNOWN",
                "snapshot_id": getattr(snapshot, "snapshot_id", None),
            })
    return outcomes


def _failure_outcomes(expected_symbols: List[str], outcome_status: str,
                      reason_code: str, provider_scope: Optional[str] = None) -> List[dict]:
    """Record provider failure truth for every expected symbol without a price row."""
    return [{
        "symbol": symbol,
        "outcome_status": outcome_status,
        "reason_code": reason_code,
        "provider_symbol": symbol,
        "provider_response_present": False,
        "normalization_result": "NOT_ATTEMPTED",
        "eligibility_status": "UNKNOWN",
        "provider_scope": provider_scope,
    } for symbol in _normalise_symbols(expected_symbols)]


def _fetch_provider_collection(provider: Any, expected_symbols: List[str]) -> tuple:
    """Read provider snapshots plus optional raw-response diagnostics."""
    evidence_fetcher = getattr(provider, "fetch_collection_evidence", None)
    if callable(evidence_fetcher):
        evidence = evidence_fetcher()
        if not isinstance(evidence, dict):
            raise RuntimeError("Provider collection evidence must be a dictionary")
        snapshots = list(evidence.get("snapshots") or [])
        outcomes = list(evidence.get("outcomes") or [])
        return snapshots, outcomes, evidence.get("provider_raw_count"), evidence.get("provider_scope")

    snapshots = list(provider.fetch_market_snapshot() or [])
    return (
        snapshots,
        _generic_provider_outcomes(expected_symbols, snapshots),
        len(snapshots),
        None,
    )


def _finalise_collection_outcomes(expected_symbols: List[str], outcomes: List[dict],
                                  persisted_rows: List[dict], coverage: dict) -> List[dict]:
    """Keep one immutable, explainable outcome for every expected symbol."""
    expected = _normalise_symbols(expected_symbols)
    base_by_symbol = {
        str(outcome.get("symbol") or "").strip().upper(): dict(outcome)
        for outcome in outcomes or []
        if isinstance(outcome, dict) and str(outcome.get("symbol") or "").strip()
    }
    persisted_by_symbol = {
        str(row.get("symbol") or "").strip().upper(): row
        for row in persisted_rows or []
        if isinstance(row, dict) and str(row.get("symbol") or "").strip()
    }
    duplicate_symbols = {
        str(symbol or "").strip().upper()
        for symbol in coverage.get("duplicate_symbols") or []
        if str(symbol or "").strip()
    }
    final = []
    for symbol in expected:
        row = persisted_by_symbol.get(symbol)
        base = base_by_symbol.get(symbol, {})
        if row is not None:
            final.append({
                **base,
                "symbol": symbol,
                "outcome_status": "LIVE_PREOPEN_DATA",
                "reason_code": "PERSISTENCE_CANDIDATE_READY",
                "provider_symbol": base.get("provider_symbol") or symbol,
                "provider_response_present": bool(
                    base.get("provider_response_present", True)
                ),
                "normalization_result": "NORMALIZED",
                "eligibility_status": base.get("eligibility_status") or "UNKNOWN",
                "snapshot_id": row.get("snapshot_id"),
            })
        elif symbol in duplicate_symbols:
            final.append({
                **base,
                "symbol": symbol,
                "outcome_status": "DUPLICATE_RESPONSE",
                "reason_code": "DUPLICATE_SYMBOL_OR_SNAPSHOT_ID",
                "provider_symbol": base.get("provider_symbol") or symbol,
                "provider_response_present": bool(base.get("provider_response_present")),
                "normalization_result": "REJECTED",
                "eligibility_status": base.get("eligibility_status") or "UNKNOWN",
                "snapshot_id": None,
            })
        elif base:
            final.append({
                **base,
                "symbol": symbol,
                "snapshot_id": None,
            })
        else:
            final.append({
                "symbol": symbol,
                "outcome_status": "PROVIDER_OMITTED",
                "reason_code": "NO_DURABLE_PROVIDER_OUTCOME",
                "provider_symbol": symbol,
                "provider_response_present": False,
                "normalization_result": "NOT_OBSERVED",
                "eligibility_status": "UNKNOWN",
                "snapshot_id": None,
            })
    return final


# ── Status ────────────────────────────────────────────────────────────────────

def get_status() -> dict:
    if not _is_enabled():
        return _disabled_response()
    try:
        from preopen_intelligence_tick import get_tick_status
        session  = db.get_latest_session()
        symbols = _resolve_collection_symbols()
        if not symbols:
            raise RuntimeError("Active custom pre-open universe is unavailable or empty")
        provider = _get_provider(symbols)
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
        symbols = _resolve_collection_symbols()
        if not symbols:
            return {
                "success": False,
                "status": "UNIVERSE_UNAVAILABLE",
                "error": "Active custom pre-open universe is unavailable or empty",
                "trading_date": _today_ist(),
                "label": "PAPER / ADVISORY ONLY",
            }
        provider = _get_provider(symbols)
        health = provider.health_check()
        today = _today_ist()
        return {
            "success": True,
            "provider_health": health,
            "trading_date": today,
            "label": "PAPER / ADVISORY ONLY",
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


# ── Snapshot collection ───────────────────────────────────────────────────────

def _ensure_session(trading_date: str, session_id: str) -> bool:
    """Create/refresh the durable session and report whether that write landed."""
    return bool(db.upsert_session({
        "session_id": session_id,
        "trading_date": trading_date,
        "status": "COLLECTING",
        "provider_status": ProviderState.LIVE,
    }))


def collect_snapshot(session_id: Optional[str] = None) -> dict:
    """
    Collect one pre-open snapshot across the watchlist.
    Safe to call repeatedly; each call stores a new batch of snapshots.
    """
    if not _is_enabled():
        return _disabled_response()

    today = _today_ist()
    session_id = session_id or f"preopen-{today}-{uuid.uuid4().hex[:8]}"
    collection_batch_id = f"collection-{uuid.uuid4().hex}"
    if not _ensure_session(today, session_id):
        return {
            "success": False,
            "status": "PERSISTENCE_UNAVAILABLE",
            "session_id": session_id,
            "provider_collected_count": None,
            "persisted_count": None,
            "persistence_status": "PERSISTENCE_UNAVAILABLE",
            "error": "Cannot create a durable pre-open session",
            "label": "PAPER / ADVISORY ONLY",
        }

    try:
        expected_symbols = _resolve_collection_symbols()
        if not expected_symbols:
            coverage = {
                "expected_count": 0,
                "provider_returned_count": 0,
                "normalized_count": 0,
                "missing_count": 0,
                "duplicate_count": 0,
                "malformed_count": 0,
                "unexpected_count": 0,
                "expected_symbols": [],
                "normalized_symbols": [],
                "missing_symbols": [],
                "duplicate_symbols": [],
                "unexpected_symbols": [],
                "unusable_count": 0,
            }
            db.record_collection_failure(
                session_id,
                "UNIVERSE_UNAVAILABLE",
                "Active custom pre-open universe is unavailable or empty",
                coverage=coverage,
            )
            return {
                "success": False,
                "status": "UNIVERSE_UNAVAILABLE",
                "session_id": session_id,
                "collection_batch_id": collection_batch_id,
                **coverage,
                "label": "PAPER / ADVISORY ONLY",
            }

        try:
            provider = _get_provider(expected_symbols)
            health = provider.health_check()
        except Exception as exc:
            coverage = {
                "expected_count": len(expected_symbols),
                "provider_returned_count": 0,
                "normalized_count": 0,
                "missing_count": len(expected_symbols),
                "duplicate_count": 0,
                "malformed_count": 0,
                "unexpected_count": 0,
                "expected_symbols": expected_symbols,
                "normalized_symbols": [],
                "missing_symbols": expected_symbols,
                "duplicate_symbols": [],
                "unexpected_symbols": [],
                "unusable_count": 0,
            }
            outcomes = _failure_outcomes(
                expected_symbols, "PROVIDER_UNAVAILABLE", "PROVIDER_INITIALIZATION_FAILED",
            )
            coverage = _coverage_with_outcomes(coverage, outcomes, 0, None)
            db.record_collection_failure(
                session_id, "PROVIDER_UNAVAILABLE", str(exc),
                coverage=coverage,
                outcomes=outcomes,
                collection_batch_id=collection_batch_id,
            )
            return {
                "success": False,
                "status": "PROVIDER_UNAVAILABLE",
                "session_id": session_id,
                "collection_batch_id": collection_batch_id,
                **coverage,
                "error": str(exc),
                "label": "PAPER / ADVISORY ONLY",
            }

        # Provider unavailable — do not crash, mark module unavailable
        if health.get("status") == ProviderState.UNAVAILABLE:
            coverage = {
                "expected_count": len(expected_symbols),
                "provider_returned_count": 0,
                "normalized_count": 0,
                "missing_count": len(expected_symbols),
                "duplicate_count": 0,
                "malformed_count": 0,
                "unexpected_count": 0,
                "expected_symbols": expected_symbols,
                "normalized_symbols": [],
                "missing_symbols": expected_symbols,
                "duplicate_symbols": [],
                "unexpected_symbols": [],
                "unusable_count": 0,
            }
            outcomes = _failure_outcomes(
                expected_symbols, "PROVIDER_UNAVAILABLE", "PROVIDER_HEALTH_UNAVAILABLE",
                health.get("provider_scope"),
            )
            coverage = _coverage_with_outcomes(
                coverage, outcomes, 0, health.get("provider_scope"),
            )
            db.record_collection_failure(
                session_id, "PROVIDER_UNAVAILABLE",
                health.get("message", "Provider unavailable"),
                coverage=coverage,
                outcomes=outcomes,
                collection_batch_id=collection_batch_id,
            )
            return {
                "success": False,
                "status": "PROVIDER_UNAVAILABLE",
                "provider_health": health,
                "session_id": session_id,
                "collection_batch_id": collection_batch_id,
                **coverage,
                "label": "PAPER / ADVISORY ONLY",
            }

        try:
            raw_snapshots, provider_outcomes, provider_raw_count, provider_scope = (
                _fetch_provider_collection(provider, expected_symbols)
            )
        except Exception as exc:
            coverage = {
                "expected_count": len(expected_symbols),
                "provider_returned_count": 0,
                "normalized_count": 0,
                "missing_count": len(expected_symbols),
                "duplicate_count": 0,
                "malformed_count": 0,
                "unexpected_count": 0,
                "expected_symbols": expected_symbols,
                "normalized_symbols": [],
                "missing_symbols": expected_symbols,
                "duplicate_symbols": [],
                "unexpected_symbols": [],
                "unusable_count": 0,
            }
            outcomes = _failure_outcomes(
                expected_symbols, "PROVIDER_UNAVAILABLE", "PROVIDER_FETCH_FAILED",
            )
            coverage = _coverage_with_outcomes(coverage, outcomes, 0, None)
            db.record_collection_failure(
                session_id, "PROVIDER_UNAVAILABLE", str(exc),
                coverage=coverage,
                outcomes=outcomes,
                collection_batch_id=collection_batch_id,
            )
            return {
                "success": False,
                "status": "PROVIDER_UNAVAILABLE",
                "session_id": session_id,
                "collection_batch_id": collection_batch_id,
                **coverage,
                "error": str(exc),
                "label": "PAPER / ADVISORY ONLY",
            }
        if not raw_snapshots:
            coverage = {
                "expected_count": len(expected_symbols),
                "provider_returned_count": 0,
                "normalized_count": 0,
                "missing_count": len(expected_symbols),
                "duplicate_count": 0,
                "malformed_count": 0,
                "unexpected_count": 0,
                "expected_symbols": expected_symbols,
                "normalized_symbols": [],
                "missing_symbols": expected_symbols,
                "duplicate_symbols": [],
                "unexpected_symbols": [],
                "unusable_count": 0,
            }
            outcomes = _finalise_collection_outcomes(
                expected_symbols, provider_outcomes, [], coverage,
            )
            coverage = _coverage_with_outcomes(
                coverage, outcomes, provider_raw_count, provider_scope,
            )
            db.record_collection_failure(
                session_id, "NO_DATA",
                "Provider returned no pre-open snapshots",
                coverage=coverage,
                outcomes=outcomes,
                collection_batch_id=collection_batch_id,
            )
            return {
                "success": False,
                "status": "NO_DATA",
                "session_id": session_id,
                "collection_batch_id": collection_batch_id,
                **coverage,
                "label": "PAPER / ADVISORY ONLY",
            }

        accepted_snapshots, coverage = _coverage_for_expected_symbols(
            raw_snapshots, expected_symbols,
        )

        # Analytics enrichment
        enriched = enrich_universe(accepted_snapshots)

        serialized_enriched = []
        for snapshot in enriched:
            try:
                serialized_enriched.append(snapshot.to_dict())
            except Exception:
                serialized_enriched.append(None)
        snaps_dicts, final_coverage = _coverage_for_serialized_rows(
            serialized_enriched, expected_symbols,
            provider_returned_count=coverage["provider_returned_count"],
        )
        coverage = _merge_coverage(coverage, final_coverage)
        outcomes = _finalise_collection_outcomes(
            expected_symbols, provider_outcomes, snaps_dicts, coverage,
        )
        coverage = _coverage_with_outcomes(
            coverage, outcomes, provider_raw_count, provider_scope,
        )
        valid = sum(1 for s in enriched if not s.is_stale)
        stale = sum(1 for s in enriched if s.is_stale)
        persisted = db.persist_collection(
            session_id=session_id,
            trading_date=today,
            snapshots=snaps_dicts,
            provider_status=health.get("status", ProviderState.DELAYED),
            valid_count=valid,
            stale_count=stale,
            source="SCHEDULED",
            collection_batch_id=collection_batch_id,
            coverage=coverage,
            outcomes=outcomes,
        )
        if not persisted.get("success"):
            return {
                "success": False,
                "status": (
                    "COVERAGE_INCOMPLETE"
                    if persisted.get("persistence_status") == "COVERAGE_INCOMPLETE"
                    else "PERSISTENCE_FAILED"
                ),
                "session_id": session_id,
                "symbol_count": len(enriched),
                "valid_count": valid,
                "stale_count": stale,
                "provider_status": health.get("status"),
                **coverage,
                **persisted,
                "label": "PAPER / ADVISORY ONLY",
            }

        return {
            "success": True,
            "status": "COLLECTED",
            "session_id": session_id,
            "collection_batch_id": collection_batch_id,
            "symbol_count": len(enriched),
            "valid_count": valid,
            "stale_count": stale,
            "provider_status": health.get("status"),
            "provider_label": health.get("provider", getattr(provider, "PROVIDER_LABEL", "Unknown")),
            **coverage,
            **persisted,
            "label": "PAPER / ADVISORY ONLY",
        }
    except Exception as e:
        if expected_symbols:
            coverage = {
                "expected_count": len(expected_symbols),
                "provider_returned_count": 0,
                "normalized_count": 0,
                "missing_count": len(expected_symbols),
                "duplicate_count": 0,
                "malformed_count": 0,
                "unexpected_count": 0,
                "expected_symbols": expected_symbols,
                "normalized_symbols": [],
                "missing_symbols": expected_symbols,
                "duplicate_symbols": [],
                "unexpected_symbols": [],
                "unusable_count": 0,
            }
            outcomes = _failure_outcomes(
                expected_symbols,
                "COLLECTION_PROCESSING_FAILED",
                "POST_RESOLUTION_COLLECTION_ERROR",
            )
            coverage = _coverage_with_outcomes(coverage, outcomes, 0, None)
            db.record_collection_failure(
                session_id, "ERROR", str(e),
                coverage=coverage,
                outcomes=outcomes,
                collection_batch_id=collection_batch_id,
            )
            return {
                "success": False,
                "status": "COLLECTION_PROCESSING_FAILED",
                "error": str(e),
                "session_id": session_id,
                "collection_batch_id": collection_batch_id,
                **coverage,
                "label": "PAPER / ADVISORY ONLY",
            }
        db.record_collection_failure(session_id, "ERROR", str(e))
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
            p = _get_provider(_resolve_collection_symbols())
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
