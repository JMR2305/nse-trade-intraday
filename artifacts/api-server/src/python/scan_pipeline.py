"""
scan_pipeline.py — Phase 22 post-scan regeneration pipeline + atomic publish.

After every successful canonical scan (scheduled OR manual), regenerate every
scan-derived dataset from that same scan_id, validate cross-page consistency,
and atomically publish a "bundle" record. The "latest successful bundle"
pointer (durable, Postgres phase20_kv) is only advanced when every required
derived module succeeded AND the consistency check reports 0 hard mismatches.

If any derived module fails:
  - the previous published bundle pointer is retained,
  - the failed attempt is recorded durably (scan_bundle_last_attempt),
  - the bundle status is DEGRADED/FAILED and the scan is NOT marked fully
    synchronized (pages keep showing the previous complete bundle metadata).

PAPER TRADING / RESEARCH ONLY. This module never places orders and never
touches activation state. Never raises out of run_post_scan_pipeline().
"""

from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

import phase20_store as store

MODEL_VERSION = "p22.1"      # bump when scoring/AI decision logic changes
RULE_VERSION = "p22.1"       # bump when gate/eligibility rules change

BUNDLE_KEY = "scan_bundle_latest"          # published pointer (atomic)
ATTEMPT_KEY = "scan_bundle_last_attempt"   # most recent attempt (any status)

# Modules that MUST succeed for the bundle to be published as SYNCHRONIZED.
REQUIRED_MODULES = [
    "warm_cache", "intelligence", "phase13", "phase14",
    "copilot_alerts", "copilot_briefing", "entry_evaluation",
    "derived_sync", "consistency",
]


def _iso_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _config_hash() -> str:
    """Stable hash of the automation-relevant configuration."""
    try:
        settings = store.get_settings()
        basis = {k: settings.get(k) for k in sorted(settings)
                 if not str(k).endswith("_at")}
        basis["model_version"] = MODEL_VERSION
        basis["rule_version"] = RULE_VERSION
        return hashlib.sha256(
            json.dumps(basis, sort_keys=True, default=str).encode()
        ).hexdigest()[:16]
    except Exception:
        return "unavailable"


def _provider_breakdown(snap: Dict[str, Any]) -> Dict[str, Any]:
    """Per-scan provider clarity: requested/received/missing/stale/fallback
    symbol counts by provider role. Never labels data Zerodha-derived unless
    the scan actually used Kite."""
    health = snap.get("provider_health") or {}
    safety = snap.get("safety") or {}
    recs = snap.get("recommendations") or []
    by_source: Dict[str, int] = {}
    for r in recs:
        src = str(r.get("data_source") or r.get("provider") or
                  safety.get("data_provider") or "unknown").lower()
        by_source[src] = by_source.get(src, 0) + 1
    kite_used = any("kite" in s for s in by_source)
    return {
        "full_scan_provider": safety.get("data_provider") or health.get("provider")
                              or "yfinance",
        "historical_data_provider": "yfinance (OHLCV history — no lookahead)",
        "fallback_provider": "yfinance",
        "kite_used_in_this_scan": kite_used,
        "symbol_counts_by_source": by_source,
        "symbols_requested": health.get("symbols_requested"),
        "symbols_received": health.get("symbols_succeeded"),
        "symbols_missing": len(health.get("unavailable_symbols") or []),
        "symbols_stale": len(health.get("stale_symbols") or []),
    }


def _run_module(name: str, fn: Callable[[], Any]) -> Dict[str, Any]:
    t0 = time.time()
    try:
        out = fn()
        return {"module": name, "status": "OK",
                "generated_at": _iso_now(),
                "duration_s": round(time.time() - t0, 2),
                "summary": out if isinstance(out, (str, int, float)) else None,
                "error": None}
    except Exception as exc:
        return {"module": name, "status": "FAILED",
                "generated_at": _iso_now(),
                "duration_s": round(time.time() - t0, 2),
                "summary": None, "error": str(exc)[:300]}


def run_post_scan_pipeline(snap: Dict[str, Any],
                           trigger: str = "SCHEDULED") -> Dict[str, Any]:
    """Regenerate all derived datasets from the given canonical snapshot,
    validate consistency, and atomically publish the bundle pointer.
    Never raises."""
    try:
        if not isinstance(snap, dict) or not snap.get("scan_id") \
                or not snap.get("snapshot_ts"):
            attempt = {"status": "FAILED",
                       "error": "no canonical snapshot (missing scan_id/snapshot_ts)",
                       "scan_id": (snap or {}).get("scan_id"),
                       "generated_at": _iso_now(), "trigger_source": trigger}
            try:
                store.kv_set(ATTEMPT_KEY, attempt)
            except Exception:
                pass
            return attempt
        return _run(snap, trigger)
    except Exception as exc:  # absolute last resort — record and move on
        attempt = {"status": "FAILED", "error": str(exc)[:300],
                   "scan_id": (snap or {}).get("scan_id"),
                   "generated_at": _iso_now(), "trigger_source": trigger}
        try:
            store.kv_set(ATTEMPT_KEY, attempt)
        except Exception:
            pass
        return attempt


def _run(snap: Dict[str, Any], trigger: str) -> Dict[str, Any]:
    scan_id = snap.get("scan_id")
    snapshot_ts = snap.get("snapshot_ts")
    started = _iso_now()
    modules: List[Dict[str, Any]] = []
    consistency_result: Dict[str, Any] = {}

    # A) Warm local cache: derived generators read phase7_scan_cache.json, so
    # make sure this instance's warm copy IS the canonical snapshot.
    def warm_cache():
        from scan_state_store import FALLBACK_SNAPSHOT_FILE
        clean = {k: v for k, v in snap.items() if not str(k).startswith("_")}
        with open(FALLBACK_SNAPSHOT_FILE, "w") as f:
            json.dump(clean, f, default=str)
        return "canonical snapshot warmed"
    modules.append(_run_module("warm_cache", warm_cache))

    # B) Intelligence pipeline — regenerates signals_cache, ai_decisions_cache,
    # opportunity_cache, market_context_cache, intelligence_cache.
    # execute_trades=False ALWAYS: the pipeline must never create trades;
    # paper entries are exclusively the Phase 20/22 executor's job.
    def intelligence():
        from intelligence import run_intelligence_scan
        import config
        watchlist = None
        try:
            import signals_store
            watchlist = signals_store.load_watchlist()
        except Exception:
            pass
        if watchlist is None:
            try:
                with open("watchlist.json") as f:
                    wl = json.load(f)
                watchlist = wl.get("symbols") if isinstance(wl, dict) else wl
            except Exception:
                watchlist = None
        if watchlist is None:
            watchlist = config.DEFAULT_WATCHLIST
        from paper_trader import get_portfolio
        try:
            cash = float(getattr(get_portfolio(), "cash", 5000.0))
        except Exception:
            cash = 5000.0
        run_intelligence_scan(list(watchlist), available_cash=cash,
                              execute_trades=False)
        return "signals/ai/opportunity/market-context regenerated"
    modules.append(_run_module("intelligence", intelligence))

    # C) Phase 13 deep intelligence (reads the warmed canonical snapshot).
    def phase13():
        from phase13_intelligence import run_phase13_analysis
        run_phase13_analysis(force=True)
        return "phase13_cache regenerated"
    modules.append(_run_module("phase13", phase13))

    # D) Phase 14 adaptive adjustments (advisory; freeze state respected inside).
    def phase14():
        from phase14_adjustments import compute_adjustments
        compute_adjustments(force=True)
        return "phase14_adjustments regenerated"
    modules.append(_run_module("phase14", phase14))

    # E) AI Copilot alerts + cached briefing.
    def copilot_alerts():
        from copilot_engine import generate_alerts
        generate_alerts()
        return "phase9 alerts regenerated"
    modules.append(_run_module("copilot_alerts", copilot_alerts))

    def copilot_briefing():
        from copilot_engine import daily_briefing
        daily_briefing()
        return "phase9 briefing regenerated"
    modules.append(_run_module("copilot_briefing", copilot_briefing))

    # F) Paper-entry candidate evaluation snapshot (read-only gate evaluation;
    # NEVER creates trades here — recorded for display + audit).
    def entry_evaluation():
        from phase20_gates import evaluate_entries
        ev = evaluate_entries()
        store.kv_set("entry_evaluation_latest", {
            "scan_id": scan_id, "snapshot_ts": snapshot_ts,
            "generated_at": _iso_now(),
            "evaluation": ev,
        })
        return "entry evaluation snapshot stored"
    modules.append(_run_module("entry_evaluation", entry_evaluation))

    # G) Overlay canonical values onto derived caches (idempotent).
    def derived_sync():
        from phase15_sync import sync_derived_caches
        sync_derived_caches()
        return "derived caches overlaid with canonical values"
    modules.append(_run_module("derived_sync", derived_sync))

    # H) Validate cross-page consistency AFTER regeneration.
    def consistency():
        from phase15_consistency import run_consistency_check
        nonlocal consistency_result
        consistency_result = run_consistency_check()
        hard = int(consistency_result.get("hard_mismatch_count") or 0)
        stale = int(consistency_result.get("stale_source_count") or 0)
        if hard > 0:
            raise RuntimeError(f"{hard} hard mismatches after regeneration")
        return f"consistency PASS ({stale} stale-source values)"
    modules.append(_run_module("consistency", consistency))

    # I) Research Lab snapshot cache invalidation — best-effort, non-blocking.
    # Deletes _snapshot_cache.json so the Executive Dashboard Research Lab tile
    # shows fresh data on its next poll instead of data up to 5 minutes stale.
    # Not in REQUIRED_MODULES: a cache-flush failure never blocks bundle publish.
    def research_lab_cache_flush():
        from research_lab.shared_services import invalidate_snapshot_cache
        return invalidate_snapshot_cache()
    modules.append(_run_module("research_lab_cache_flush", research_lab_cache_flush))

    failed = [m["module"] for m in modules if m["status"] != "OK"]
    required_failed = [m for m in failed if m in REQUIRED_MODULES]
    synchronized = not required_failed
    status = "SYNCHRONIZED" if synchronized else (
        "FAILED" if len(required_failed) >= len(REQUIRED_MODULES) - 1 else "DEGRADED")

    bundle = {
        "scan_id": scan_id,
        "snapshot_ts": snapshot_ts,
        "trigger_source": trigger,
        "started_at": started,
        "generated_at": _iso_now(),
        "model_version": MODEL_VERSION,
        "rule_version": RULE_VERSION,
        "config_hash": _config_hash(),
        "status": status,
        "modules": modules,
        "failed_modules": failed,
        "providers": _provider_breakdown(snap),
        "consistency": {
            "verdict": consistency_result.get("verdict"),
            "checks_performed": consistency_result.get("checks_performed"),
            "hard_mismatch_count": consistency_result.get("hard_mismatch_count"),
            "stale_source_count": consistency_result.get("stale_source_count"),
        } if consistency_result else None,
        "source_status": "LIVE" if synchronized else "DEGRADED",
        "label": "PAPER / RESEARCH ONLY",
    }

    # Record the attempt ALWAYS; advance the published pointer ONLY when the
    # bundle is fully synchronized (atomic single-key JSONB upsert) AND newer
    # than the currently published bundle (monotonic — a slow older pipeline
    # must never overwrite a newer published bundle).
    store.kv_set(ATTEMPT_KEY, bundle)
    if synchronized and _is_newer_than_published(bundle):
        store.kv_set(BUNDLE_KEY, bundle)
    return bundle


def _is_newer_than_published(bundle: Dict[str, Any]) -> bool:
    try:
        current = store.kv_get(BUNDLE_KEY) or {}
        cur_ts = str(current.get("snapshot_ts") or "")
        new_ts = str(bundle.get("snapshot_ts") or "")
        if not cur_ts:
            return True
        if current.get("scan_id") == bundle.get("scan_id"):
            return True  # re-publish of the same scan is idempotent
        return new_ts >= cur_ts  # ISO-8601 strings compare chronologically
    except Exception:
        return True


def bundle_status() -> Dict[str, Any]:
    """Published bundle + last attempt, for UI/API display."""
    published = store.kv_get(BUNDLE_KEY) or None
    attempt = store.kv_get(ATTEMPT_KEY) or None
    current = None
    try:
        from phase15_scan_context import build_scan_context
        ctx = build_scan_context()
        current = {"scan_id": ctx.get("scan_id"),
                   "snapshot_ts": ctx.get("snapshot_ts"),
                   "available": ctx.get("available")}
    except Exception:
        pass
    in_sync = bool(published and current and
                   published.get("scan_id") == current.get("scan_id"))
    return {
        "published_bundle": published,
        "last_attempt": attempt,
        "canonical_scan": current,
        "bundle_matches_canonical_scan": in_sync,
        "label": "PAPER / RESEARCH ONLY",
    }
