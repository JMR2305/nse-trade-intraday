"""
models.py — Phase 8.7 Performance Centre
Feature-flag helpers, grade/trend functions, thresholds, and dataclasses.

READ-ONLY. ADVISORY-ONLY.
"""
from __future__ import annotations
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone

# ── Feature flag ───────────────────────────────────────────────────────────────
_FLAG = "PERFORMANCE_CENTER_ENABLED"


def is_enabled() -> bool:
    return os.environ.get(_FLAG, "false").lower() in ("1", "true", "yes")


def disabled_response() -> dict:
    return {
        "status":       "DISABLED",
        "available":    False,
        "advisory_only": True,
        "read_only":    True,
        "message":      f"Set {_FLAG}=true to enable the Performance Centre.",
    }


# ── Status constants ───────────────────────────────────────────────────────────
STATUS_HEALTHY  = "HEALTHY"
STATUS_DEGRADED = "DEGRADED"
STATUS_DOWN     = "DOWN"
STATUS_UNKNOWN  = "UNKNOWN"


# ── Grade mapping ──────────────────────────────────────────────────────────────
def perf_grade(score: float) -> str:
    if score >= 92: return "A+"
    if score >= 80: return "A"
    if score >= 68: return "B"
    if score >= 50: return "C"
    return "D"


# ── Trend labels ───────────────────────────────────────────────────────────────
def perf_trend(current: float, baseline: float) -> str:
    """Compare current score vs baseline; return IMPROVING / STABLE / DEGRADING."""
    diff = current - baseline
    if diff > 5:  return "IMPROVING"
    if diff < -5: return "DEGRADING"
    return "STABLE"


# ── Performance thresholds ─────────────────────────────────────────────────────
# API
API_TARGET_AVG_MS   = 300      # target avg response < 300 ms
API_TARGET_P95_MS   = 800      # target p95 < 800 ms
API_TARGET_ERROR_PCT = 2.0     # target error rate < 2 %

# Database
DB_TARGET_LATENCY_MS  = 50     # target connection latency < 50 ms
DB_SLOW_QUERY_MS      = 200    # slow query threshold

# Cache
CACHE_TARGET_HIT_PCT  = 80.0   # target cache hit rate ≥ 80 %
CACHE_STALE_WARN_S    = 120    # stale entry threshold (2 min)

# Scheduler
SCAN_FRESH_THRESHOLD_MIN = 60  # scan older than 60 min = degraded

# Resources
MEM_WARN_PCT  = 80.0
CPU_WARN_LOAD = 2.0
DISK_WARN_PCT = 85.0

# Frontend (estimated)
PAGE_TARGET_LOAD_MS = 2000     # target page load < 2 s
BUNDLE_WARN_KB      = 1500     # warn if bundle exceeds 1.5 MB

# Scalability
MAX_SYMBOLS_PER_SCAN   = 500
CONCURRENT_USER_TARGET = 20
SCHEDULER_SLOTS        = 5


# ── Known multi-agent roles (for readiness table) ────────────────────────────
FUTURE_AGENTS = [
    "Market Data Agent",
    "Research Agent",
    "Market Intelligence Agent",
    "Stock Monitoring Agent",
    "Strategy Agent",
    "Risk Agent",
    "AI Decision Agent",
    "Execution Agent",
    "Learning Agent",
    "Supervisor Agent",
]


# ── Dataclasses ───────────────────────────────────────────────────────────────
@dataclass
class PerfRecommendation:
    domain:   str
    severity: str          # INFO | WARNING | CRITICAL
    title:    str
    detail:   str
    advisory_only: bool = True


@dataclass
class BenchmarkRecord:
    label:          str
    score:          float
    api_avg_ms:     float
    db_latency_ms:  float
    cache_hit_pct:  float
    scan_age_min:   float | None
    generated_at:   str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
