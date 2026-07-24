"""RC-10C1 Portfolio Core — Portfolio Health Monitor.

Derives a PortfolioHealth snapshot by combining portfolio state, limit checks,
broker snapshot freshness, and reconciliation metadata.

No broker calls, no order placement.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from decimal import Decimal

from .config import PortfolioConfig
from .contracts import (
    LimitSeverity,
    PortfolioHealth,
    PortfolioHealthStatus,
    PortfolioSnapshot,
    PortfolioStatus,
)
from .limits import check_all_limits

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def compute_health(
    snapshot: PortfolioSnapshot,
    config: PortfolioConfig,
    unresolved_discrepancies: int = 0,
    last_reconciliation_at: datetime | None = None,
    broker_snapshot_at: datetime | None = None,
) -> PortfolioHealth:
    """Compute a PortfolioHealth snapshot from the current portfolio state.

    Health dimensions:
      - State freshness: is the local snapshot too old?
      - Broker snapshot freshness: is the broker data too old?
      - Critical limit breaches: any CRITICAL limits currently violated?
      - Reconciliation: any unresolved discrepancies?

    Combined into:
      - liveness  = status not in {HALTED, UNAVAILABLE}
      - readiness = READY AND fresh state AND fresh broker AND
                    no discrepancies AND no critical breaches
      - health    = HEALTHY if ready; DEGRADED if live; DOWN otherwise

    Args:
        snapshot: Current authoritative portfolio snapshot.
        config: Validated portfolio configuration.
        unresolved_discrepancies: Count of discrepancies not yet resolved.
        last_reconciliation_at: Timestamp of the most recent reconciliation.
        broker_snapshot_at: Timestamp of the most recent broker snapshot.

    Returns:
        PortfolioHealth with all readiness, liveness, and status fields.
    """
    now = datetime.now(timezone.utc)

    # State freshness.
    state_freshness_s = (now - snapshot.snapshotted_at).total_seconds()
    stale_state = state_freshness_s > config.stale_state_threshold_s
    if stale_state:
        logger.warning(
            "portfolio_health|stale_state|age_s=%.1f|threshold_s=%.1f",
            state_freshness_s, config.stale_state_threshold_s,
        )

    # Broker snapshot freshness.
    broker_freshness_s: float | None = None
    stale_broker = False
    if broker_snapshot_at is not None:
        broker_freshness_s = (now - broker_snapshot_at).total_seconds()
        stale_broker = broker_freshness_s > config.stale_broker_threshold_s
        if stale_broker:
            logger.warning(
                "portfolio_health|stale_broker|age_s=%.1f|threshold_s=%.1f",
                broker_freshness_s, config.stale_broker_threshold_s,
            )

    # Critical limit breaches (zero proposed value = current state only).
    limit_report = check_all_limits(
        snapshot=snapshot,
        proposed_instrument_token=None,
        proposed_value=Decimal("0"),
        proposed_strategy_id=None,
        proposed_sector=None,
        config=config,
    )
    critical_breaches = sum(
        1
        for r in limit_report.results
        if r.severity == LimitSeverity.CRITICAL and not r.allowed
    )

    # Liveness & readiness.
    liveness = snapshot.status not in {
        PortfolioStatus.HALTED,
        PortfolioStatus.UNAVAILABLE,
    }
    readiness = (
        snapshot.status == PortfolioStatus.READY
        and not stale_state
        and not stale_broker
        and unresolved_discrepancies == 0
        and critical_breaches == 0
    )

    # Degraded flag.
    degraded = (
        snapshot.status == PortfolioStatus.DEGRADED
        or unresolved_discrepancies > 0
    )

    # Overall health status.
    if readiness:
        health_status = PortfolioHealthStatus.HEALTHY
    elif liveness:
        health_status = PortfolioHealthStatus.DEGRADED
    else:
        health_status = PortfolioHealthStatus.DOWN

    # First actionable failure reason.
    failure_reason: str | None = None
    if not readiness:
        if snapshot.status == PortfolioStatus.HALTED:
            failure_reason = "Portfolio is HALTED"
        elif snapshot.status == PortfolioStatus.UNAVAILABLE:
            failure_reason = "Portfolio is UNAVAILABLE"
        elif stale_state:
            failure_reason = (
                f"Local state stale ({state_freshness_s:.0f}s > "
                f"{config.stale_state_threshold_s}s)"
            )
        elif stale_broker:
            failure_reason = (
                f"Broker snapshot stale ({broker_freshness_s:.0f}s > "
                f"{config.stale_broker_threshold_s}s)"
            )
        elif unresolved_discrepancies > 0:
            failure_reason = (
                f"{unresolved_discrepancies} unresolved reconciliation discrepancy/ies"
            )
        elif critical_breaches > 0:
            first_breach = next(
                (
                    r.limit_name
                    for r in limit_report.results
                    if r.severity == LimitSeverity.CRITICAL and not r.allowed
                ),
                None,
            )
            failure_reason = (
                f"{critical_breaches} critical limit breach(es); first: {first_breach}"
            )
        elif snapshot.status != PortfolioStatus.READY:
            failure_reason = f"Portfolio status is {snapshot.status.value}"

    logger.info(
        "portfolio_health|status=%s|liveness=%s|readiness=%s|degraded=%s|"
        "critical_breaches=%d|discrepancies=%d|stale_state=%s|stale_broker=%s",
        health_status.value, liveness, readiness, degraded,
        critical_breaches, unresolved_discrepancies, stale_state, stale_broker,
    )

    return PortfolioHealth(
        status=health_status,
        initialized=snapshot.status
        not in {PortfolioStatus.INITIALISING, PortfolioStatus.UNAVAILABLE},
        recovered=snapshot.status
        not in {
            PortfolioStatus.INITIALISING,
            PortfolioStatus.RECOVERING,
            PortfolioStatus.UNAVAILABLE,
        },
        reconciled=(
            snapshot.status not in {PortfolioStatus.RECONCILING}
            and unresolved_discrepancies == 0
        ),
        liveness=liveness,
        readiness=readiness,
        degraded=degraded,
        failure_reason=failure_reason,
        paper_mode=snapshot.paper_mode,
        state_freshness_s=state_freshness_s,
        broker_freshness_s=broker_freshness_s,
        unresolved_discrepancies=unresolved_discrepancies,
        critical_limit_breaches=critical_breaches,
        last_snapshot_at=snapshot.snapshotted_at,
        last_reconciliation_at=last_reconciliation_at,
        portfolio_status=snapshot.status,
        checked_at=now,
    )


# ---------------------------------------------------------------------------
# PortfolioHealthMonitor class — injectable façade for PortfolioService
# ---------------------------------------------------------------------------

class PortfolioHealthMonitor:
    """Object-oriented façade around the module-level compute_health function.

    Maintains reconciliation state between calls so that PortfolioService
    can use dependency injection for testing and composition.
    """

    def __init__(self, config: PortfolioConfig | None = None) -> None:
        from .config import DEFAULT_CONFIG as _DEFAULT_CONFIG
        self.config: PortfolioConfig = config or _DEFAULT_CONFIG
        self._last_reconciliation_at: datetime | None = None
        self._unresolved_discrepancies: int = 0
        self._reconciled: bool = False
        self._recovered: bool = False
        self._broker_snapshot_at: datetime | None = None

    def record_reconciliation(
        self,
        critical_count: int,
        warning_count: int,
        completed_at: datetime | None = None,
    ) -> None:
        """Record the outcome of a reconciliation run.

        Parameters
        ----------
        critical_count:
            Number of critical discrepancies found.
        warning_count:
            Number of warning discrepancies found.
        completed_at:
            Timestamp the reconciliation completed.
        """
        self._last_reconciliation_at = completed_at or datetime.now(timezone.utc)
        self._unresolved_discrepancies = critical_count + warning_count
        self._reconciled = critical_count == 0

    def record_recovery(self, success: bool) -> None:
        """Record the outcome of a recovery attempt.

        Parameters
        ----------
        success:
            Whether recovery succeeded.
        """
        self._recovered = success

    def record_broker_snapshot(self, as_of: datetime) -> None:
        """Record when the latest broker snapshot was received."""
        self._broker_snapshot_at = as_of

    async def compute_health(
        self, snapshot: PortfolioSnapshot
    ) -> PortfolioHealth:
        """Compute the current health of the portfolio service.

        Parameters
        ----------
        snapshot:
            Current portfolio state.

        Returns
        -------
        PortfolioHealth
        """
        return compute_health(
            snapshot=snapshot,
            config=self.config,
            unresolved_discrepancies=self._unresolved_discrepancies,
            last_reconciliation_at=self._last_reconciliation_at,
            broker_snapshot_at=self._broker_snapshot_at,
        )
