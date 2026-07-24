"""RC-10C1 Portfolio Core — typed domain exceptions.

All exceptions derive from PortfolioError so callers can catch at any
granularity they choose.  No exception here triggers a broker call or
order action; that authority remains with RC-8 and RC-7.
"""
from __future__ import annotations


class PortfolioError(Exception):
    """Base class for all portfolio domain errors."""


class PortfolioNotReadyError(PortfolioError):
    """Portfolio has not finished initialisation / recovery / reconciliation.

    No new order should be approved until readiness is restored.
    """


class InsufficientCapitalError(PortfolioError):
    """Requested capital exceeds available buying power or free cash."""


class ExposureLimitBreachedError(PortfolioError):
    """The proposed position would exceed an instrument, sector, or strategy
    exposure limit configured in PortfolioConfig."""


class PortfolioLimitBreachedError(PortfolioError):
    """A portfolio-level limit (e.g. max open positions, max gross exposure)
    would be breached by the proposed action."""


class DuplicateEventError(PortfolioError):
    """An event with the same idempotency key has already been applied to
    the ledger.  The caller should treat this as a no-op, not an error."""


class StalePortfolioStateError(PortfolioError):
    """The portfolio snapshot or event stream is older than
    PortfolioConfig.stale_state_threshold_s seconds.  New order approvals
    must be blocked until a fresh snapshot is obtained."""


class ReconciliationRequiredError(PortfolioError):
    """A critical discrepancy was detected between local state and the broker
    snapshot.  The portfolio is degraded; new orders are blocked."""


class CorruptSnapshotError(PortfolioError):
    """A persisted portfolio snapshot failed integrity / checksum validation
    and cannot be used for recovery."""


class InvalidPositionTransitionError(PortfolioError):
    """An event would cause an illegal position transition (e.g. negative
    quantity on a long-only position, or side reversal without explicit
    close-and-open)."""


class ReservedCapitalViolationError(PortfolioError):
    """An action would reduce the cash reserve below the configured minimum
    (PortfolioConfig.cash_reserve_percentage)."""


class StaleAllocationError(PortfolioError):
    """An AllocationDecision has passed its expires_at timestamp and must
    not be committed."""


class PortfolioVersionConflictError(PortfolioError):
    """An optimistic-concurrency check failed: the state version at commit
    time differs from the version at decision time."""


class UnknownInstrumentError(PortfolioError):
    """An event or order references an instrument token not known to the
    portfolio (not in any open or pending position)."""


class NegativeQuantityError(PortfolioError):
    """A quantity value resolved to zero or negative after rounding, making
    the resulting order value below the minimum threshold."""


class PortfolioHaltedError(PortfolioError):
    """The portfolio has been halted (e.g. via kill-switch or critical limit
    breach).  No new order reservations are accepted until manually resumed."""
