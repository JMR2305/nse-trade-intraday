"""RC-10C1: Portfolio domain exceptions."""
from __future__ import annotations


class PortfolioError(Exception):
    """Base class for all portfolio errors."""


class PortfolioNotReadyError(PortfolioError):
    """Operation attempted before portfolio is initialized/recovered."""


class PortfolioNotInitializedError(PortfolioNotReadyError):
    """Portfolio has never been initialized."""


class PortfolioRecoveryRequired(PortfolioNotReadyError):
    """Portfolio requires recovery before accepting orders."""


class InsufficientCapitalError(PortfolioError):
    """Requested capital exceeds available buying power."""
    def __init__(self, requested=None, available=None, msg: str = "") -> None:
        self.requested = requested
        self.available = available
        super().__init__(msg or f"Insufficient capital: requested={requested}, available={available}")


class InsufficientMarginError(PortfolioError):
    """Requested margin exceeds available margin."""


class ExposureLimitBreachedError(PortfolioError):
    """Proposed order would breach an exposure limit."""
    def __init__(self, limit_type: str = "", current=None, proposed=None, limit=None, msg: str = "") -> None:
        self.limit_type = limit_type
        self.current = current
        self.proposed = proposed
        self.limit = limit
        super().__init__(msg or f"Exposure limit breached: type={limit_type} current={current} proposed={proposed} limit={limit}")


class PortfolioLimitBreachedError(PortfolioError):
    """A portfolio-level hard limit has been breached."""
    def __init__(self, limit_name: str = "", current=None, limit=None, severity: str = "CRITICAL") -> None:
        self.limit_name = limit_name
        self.current = current
        self.limit = limit
        self.severity = severity
        super().__init__(f"Portfolio limit breached: {limit_name} current={current} limit={limit} severity={severity}")


class DuplicateEventError(PortfolioError):
    """An event with the same idempotency key has already been applied."""
    def __init__(self, idempotency_key: str = "") -> None:
        self.idempotency_key = idempotency_key
        super().__init__(f"Duplicate event: idempotency_key={idempotency_key}")


class StalePortfolioStateError(PortfolioError):
    """Portfolio state has not been updated within the staleness threshold."""
    def __init__(self, age_seconds: float = 0, threshold_seconds: float = 0) -> None:
        self.age_seconds = age_seconds
        self.threshold_seconds = threshold_seconds
        super().__init__(f"Stale portfolio state: age={age_seconds:.1f}s threshold={threshold_seconds}s")


class ReconciliationRequiredError(PortfolioError):
    """Portfolio has unresolved critical discrepancies — reconciliation required."""


class CorruptSnapshotError(PortfolioError):
    """Portfolio snapshot failed integrity validation."""
    def __init__(self, snapshot_id: str = "", reason: str = "") -> None:
        self.snapshot_id = snapshot_id
        super().__init__(f"Corrupt snapshot: id={snapshot_id} reason={reason}")


class InvalidPositionTransitionError(PortfolioError):
    """Attempted an illegal position state transition."""
    def __init__(self, position_id: str = "", from_status: str = "", to_status: str = "") -> None:
        self.position_id = position_id
        self.from_status = from_status
        self.to_status = to_status
        super().__init__(f"Invalid position transition: id={position_id} {from_status} → {to_status}")


class ReservedCapitalViolationError(PortfolioError):
    """Operation would dip into the configured cash reserve."""


class StaleAllocationError(PortfolioError):
    """Allocation decision has expired and may not be committed."""
    def __init__(self, allocation_id: str = "") -> None:
        self.allocation_id = allocation_id
        super().__init__(f"Stale allocation decision: {allocation_id}")


class PortfolioVersionConflictError(PortfolioError):
    """Optimistic version check failed — state was modified concurrently."""
    def __init__(self, expected: int = 0, actual: int = 0) -> None:
        self.expected = expected
        self.actual = actual
        super().__init__(f"Portfolio version conflict: expected={expected} actual={actual}")


class UnknownInstrumentError(PortfolioError):
    """Instrument token not in the portfolio instrument registry."""
    def __init__(self, instrument_token=None) -> None:
        self.instrument_token = instrument_token
        super().__init__(f"Unknown instrument: token={instrument_token}")


class NegativeQuantityError(PortfolioError):
    """Operation would result in a negative position quantity."""


class PortfolioHaltedError(PortfolioError):
    """Portfolio is halted — no new trade approvals are permitted."""
    def __init__(self, reason: str = "") -> None:
        super().__init__(f"Portfolio halted: {reason}")
