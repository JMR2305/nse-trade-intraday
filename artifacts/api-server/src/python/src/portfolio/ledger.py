"""RC-10C1 Portfolio Core — PortfolioEventLedger.

Append-only, in-memory ordered event log with idempotency guarantees.
Persistence is handled by the repository layer — this module is pure
in-process state.
"""
from __future__ import annotations

import asyncio
import logging
from decimal import Decimal
from typing import TYPE_CHECKING

from .contracts import PortfolioEvent, PortfolioEventType
from .exceptions import DuplicateEventError

if TYPE_CHECKING:
    from .state import PortfolioStateManager

logger = logging.getLogger(__name__)


class PortfolioEventLedger:
    """Append-only in-memory ordered portfolio event log.

    Sequence numbers are 1-based and strictly monotonically increasing.
    The ledger does **not** write to any database; that responsibility
    belongs to the repository layer (RC-10C2 or later).

    Concurrency:
        All public methods are protected by ``_lock``.  Because the
        implementation is purely in-memory (no I/O awaits inside locked
        sections), the lock is always released promptly.
    """

    def __init__(self, portfolio_id: str = "default") -> None:
        self._portfolio_id: str = portfolio_id
        self._events: list[PortfolioEvent] = []
        self._idempotency_set: set[str] = set()
        self._lock: asyncio.Lock = asyncio.Lock()
        logger.info("PortfolioEventLedger created [portfolio_id=%s]", portfolio_id)

    # ── Public API ───────────────────────────────────────────────────

    async def append(self, event: PortfolioEvent) -> PortfolioEvent:
        """Append an event to the ledger.

        Assigns the next 1-based monotonic sequence number to the event
        and stores it.

        Args:
            event: The PortfolioEvent to append.

        Returns:
            A new PortfolioEvent instance with ``sequence`` set.

        Raises:
            DuplicateEventError: If ``event.idempotency_key`` has already
                been recorded in this ledger.
        """
        async with self._lock:
            if event.idempotency_key in self._idempotency_set:
                raise DuplicateEventError(
                    f"Event with idempotency_key={event.idempotency_key!r} "
                    f"already exists in ledger [portfolio_id={self._portfolio_id}]"
                )

            next_seq = len(self._events) + 1
            # PortfolioEvent is frozen; use model_copy to assign sequence.
            sequenced_event = event.model_copy(update={"sequence": next_seq})
            self._events.append(sequenced_event)
            self._idempotency_set.add(event.idempotency_key)

            logger.debug(
                "Ledger append [seq=%d, type=%s, idem=%s]",
                next_seq,
                event.event_type.value,
                event.idempotency_key,
            )
            return sequenced_event

    async def get_events_after(self, sequence: int) -> list[PortfolioEvent]:
        """Return all events with sequence number strictly greater than *sequence*.

        Args:
            sequence: Lower-bound sequence number (exclusive).

        Returns:
            Ordered list of PortfolioEvent instances.
        """
        async with self._lock:
            return [e for e in self._events if (e.sequence or 0) > sequence]

    async def get_all(self) -> list[PortfolioEvent]:
        """Return all events in ledger order.

        Returns:
            Complete ordered list of PortfolioEvent instances.
        """
        async with self._lock:
            return list(self._events)

    async def replay(
        self,
        events: list[PortfolioEvent],
        state_manager: "PortfolioStateManager",
    ) -> int:
        """Replay a list of events onto *state_manager*.

        Events whose idempotency keys have already been applied to the
        state manager are silently skipped (idempotent).

        Only FILL_RECEIVED events carry enough information to mutate
        position state via ``state_manager.apply_fill``.  All other event
        types are recorded in the ledger but do not drive additional state
        changes (the state was already set during the original write path).

        Args:
            events: Ordered list of events to replay.
            state_manager: Target state manager to apply fills to.

        Returns:
            Count of events actually applied (not skipped).
        """
        applied = 0
        for event in events:
            # Skip if already in ledger
            async with self._lock:
                already_recorded = event.idempotency_key in self._idempotency_set

            if already_recorded:
                logger.debug(
                    "Replay skip (already in ledger) [idem=%s]",
                    event.idempotency_key,
                )
                continue

            # Skip if already applied to state manager.
            # The state manager tracks applied events in _seen_idempotency_keys.
            if event.idempotency_key in state_manager._seen_idempotency_keys:
                logger.debug(
                    "Replay skip (already in state) [idem=%s]",
                    event.idempotency_key,
                )
                # Still record in ledger so the sequence is durable
                try:
                    await self.append(event)
                except DuplicateEventError:
                    pass
                continue

            # Apply fill events to state using the state manager's keyword API.
            # instrument_token lives on the event top-level field; all other
            # fill fields are stored in the payload (including instrument_symbol
            # which was added to the payload in service.apply_fill after this fix).
            if event.event_type == PortfolioEventType.FILL_RECEIVED:
                payload = event.payload
                side_raw = str(payload.get("side", "BUY")).upper()
                from .contracts import PositionSide as _PS
                side = _PS.LONG if side_raw == "BUY" else _PS.SHORT
                from .exceptions import InvalidPositionTransitionError as _IPTE
                try:
                    await state_manager.apply_fill(
                        idempotency_key=event.idempotency_key,
                        instrument_token=int(
                            event.instrument_token
                            or payload.get("instrument_token", 0)
                        ),
                        instrument_symbol=str(
                            payload.get("instrument_symbol", "UNKNOWN")
                        ),
                        side=side,
                        quantity=int(payload.get("quantity", 0)),
                        price=Decimal(str(payload.get("price", "0"))),
                        fill_id=str(
                            payload.get("fill_id", event.idempotency_key)
                        ),
                        filled_at=event.occurred_at,
                        order_id=payload.get("order_id") or None,
                        fees=Decimal(str(payload.get("fees", "0"))),
                        strategy_id=event.strategy_id,
                        sector=payload.get("sector") or None,
                    )
                    logger.info(
                        "Replay applied fill [idem=%s]",
                        event.idempotency_key,
                    )
                except DuplicateEventError:
                    # Fast-path dedup: idempotency_key already seen in state.
                    logger.debug(
                        "Replay fill already in state (idempotency_key) [idem=%s]",
                        event.idempotency_key,
                    )
                except _IPTE:
                    # Belt-and-suspenders: fill_id already present in position
                    # lots (can happen when idempotency_key != fill_id and the
                    # snapshot seeded _seen_idempotency_keys from fill_ids).
                    # Treated as a safe no-op — the fill was already applied.
                    logger.debug(
                        "Replay fill already applied (fill_id dup) [idem=%s]",
                        event.idempotency_key,
                    )

            # Replay reservation mutations — a snapshot-write failure after a
            # durable reservation event must not lose the reservation on
            # restart. Release is idempotent in the state manager (missing
            # order_id is a no-op), and a replayed fill for the same order_id
            # consumes its reservation, so ordering stays consistent.
            elif event.event_type == PortfolioEventType.ORDER_RESERVED:
                payload = event.payload or {}
                order_id = str(payload.get("order_id", ""))
                if order_id:
                    await state_manager.reserve_order_capital(
                        order_id,
                        Decimal(str(payload.get("amount", "0"))),
                        during_recovery=True,
                    )
                    state_manager._seen_idempotency_keys.add(
                        event.idempotency_key
                    )
                    logger.info(
                        "Replay applied reservation [idem=%s]",
                        event.idempotency_key,
                    )
            elif event.event_type == PortfolioEventType.ORDER_RESERVATION_RELEASED:
                payload = event.payload or {}
                order_id = str(payload.get("order_id", ""))
                if order_id:
                    await state_manager.release_order_capital(order_id)
                    state_manager._seen_idempotency_keys.add(
                        event.idempotency_key
                    )
                    logger.info(
                        "Replay applied reservation release [idem=%s]",
                        event.idempotency_key,
                    )

            # Record in ledger
            try:
                await self.append(event)
                applied += 1
            except DuplicateEventError:
                pass

        logger.info(
            "Replay complete [total=%d, applied=%d, portfolio_id=%s]",
            len(events),
            applied,
            self._portfolio_id,
        )
        return applied

    def event_count(self) -> int:
        """Return the total number of events in the ledger.

        Returns:
            Non-negative integer event count.
        """
        return len(self._events)

    def last_sequence(self) -> int | None:
        """Return the sequence number of the most recent event, or None.

        Returns:
            Sequence number (int ≥ 1) or None if ledger is empty.
        """
        if not self._events:
            return None
        last = self._events[-1]
        return last.sequence
