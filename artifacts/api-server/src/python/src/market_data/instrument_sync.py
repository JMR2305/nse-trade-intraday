"""Instrument synchronisation with the broker instrument master.

Fetches exchange-level instruments, validates them, performs batch
upsert/deactivate, and returns a structured summary.

Repository interface compatibility:
  - Tries get_all_for_exchange(exchange) first, falls back to get_all()
  - Tries insert(item) first, falls back to upsert(item)
  - Tries update_by_uq(key, item) first, falls back to update(token, item)
  - Tries deactivate(token) first, falls back to update(token, {"is_tradable": False})
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from src.market_data.provider import MarketDataProvider


@dataclass(frozen=True)
class InstrumentSyncResult:
    """Summary of an instrument sync operation."""
    exchange: str
    inserted: int = 0
    updated: int = 0
    deactivated: int = 0
    rejected: int = 0
    errors: list[str] = field(default_factory=list)
    refreshed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class InstrumentSync:
    """Synchronises the local instrument master with the broker.

    Args:
        provider: MarketDataProvider (read-only)
        instrument_repo: existing instrument repository from the project.
            Supports flexible interface detection (get_all_for_exchange or get_all,
            insert or upsert, update_by_uq or update, deactivate or update).
    """

    def __init__(
        self,
        provider: MarketDataProvider,
        instrument_repo: Any,
    ) -> None:
        self._provider = provider
        self._instrument_repo = instrument_repo

    async def sync(self, exchange: str = "NSE") -> InstrumentSyncResult:
        """Fetch, validate, and sync instruments for an exchange.

        Returns:
            InstrumentSyncResult with counts and any validation errors.
        """
        result = InstrumentSyncResult(exchange=exchange)

        # 1. Fetch from provider
        raw_instruments = await self._provider.get_instruments(exchange)

        # 2. Validate
        valid_items: list[dict[str, Any]] = []
        for raw in raw_instruments:
            validated, error = self._validate(raw, exchange)
            if error:
                result = InstrumentSyncResult(
                    exchange=exchange,
                    inserted=result.inserted,
                    updated=result.updated,
                    deactivated=result.deactivated,
                    rejected=result.rejected + 1,
                    errors=result.errors + [error],
                    refreshed_at=result.refreshed_at,
                )
            else:
                valid_items.append(validated)

        # 3. Get existing instruments
        existing = await self._get_existing(exchange)
        existing_by_token: dict[int, Any] = {}
        for inst in existing:
            # Support both ORM objects and dicts
            token = getattr(inst, "instrument_token", inst.get("instrument_token") if isinstance(inst, dict) else None)
            if token:
                existing_by_token[token] = inst

        fetched_tokens: set[int] = set()
        for item in valid_items:
            token = item["instrument_token"]
            fetched_tokens.add(token)

            if token in existing_by_token:
                # Update existing
                await self._update_item(token, item, existing_by_token[token])
                result = InstrumentSyncResult(
                    exchange=exchange,
                    inserted=result.inserted,
                    updated=result.updated + 1,
                    deactivated=result.deactivated,
                    rejected=result.rejected,
                    errors=result.errors,
                    refreshed_at=result.refreshed_at,
                )
            else:
                # Insert new
                await self._insert_item(item)
                result = InstrumentSyncResult(
                    exchange=exchange,
                    inserted=result.inserted + 1,
                    updated=result.updated,
                    deactivated=result.deactivated,
                    rejected=result.rejected,
                    errors=result.errors,
                    refreshed_at=result.refreshed_at,
                )

        # 4. Deactivate instruments no longer returned by the broker
        for token, inst in existing_by_token.items():
            if token not in fetched_tokens:
                await self._deactivate(inst)
                result = InstrumentSyncResult(
                    exchange=exchange,
                    inserted=result.inserted,
                    updated=result.updated,
                    deactivated=result.deactivated + 1,
                    rejected=result.rejected,
                    errors=result.errors,
                    refreshed_at=result.refreshed_at,
                )

        # Update refresh timestamp if repository supports it
        if hasattr(self._instrument_repo, "update_refresh_timestamp"):
            await self._instrument_repo.update_refresh_timestamp(exchange)

        return result

    # ------------------------------------------------------------------
    # Deactivation helper
    # ------------------------------------------------------------------
    # ------------------------------------------------------------------
    # Repository interface adapters
    # ------------------------------------------------------------------
    async def _get_existing(self, exchange: str) -> list[Any]:
        """Fetch existing instruments, trying multiple repository interfaces."""
        if hasattr(self._instrument_repo, "get_all_for_exchange"):
            return await self._instrument_repo.get_all_for_exchange(exchange)
        if hasattr(self._instrument_repo, "get_all"):
            return await self._instrument_repo.get_all()
        raise RuntimeError(
            "Repository has no get_all_for_exchange() or get_all() method"
        )

    async def _insert_item(self, item: dict[str, Any]) -> None:
        """Insert a new instrument, trying multiple repository interfaces."""
        if hasattr(self._instrument_repo, "insert"):
            await self._instrument_repo.insert(item)
            return
        if hasattr(self._instrument_repo, "upsert"):
            await self._instrument_repo.upsert(item)
            return
        raise RuntimeError(
            "Repository has no insert() or upsert() method"
        )

    async def _update_item(self, token: int, item: dict[str, Any], existing: Any) -> None:
        """Update an existing instrument, trying multiple repository interfaces."""
        if hasattr(self._instrument_repo, "update_by_uq"):
            key = (
                item["exchange"],
                item["tradingsymbol"],
                item.get("expiry"),
                item.get("strike"),
            )
            await self._instrument_repo.update_by_uq(key, item)
            return
        if hasattr(self._instrument_repo, "update"):
            await self._instrument_repo.update(token, item)
            return
        raise RuntimeError(
            "Repository has no update_by_uq() or update() method"
        )

    async def _deactivate(self, inst: Any) -> None:
        """Deactivate an instrument, trying multiple repository interfaces.

        Works with both ORM objects and dict-like rows.
        """
        token = getattr(inst, "instrument_token", inst.get("instrument_token") if isinstance(inst, dict) else None)
        if token is None:
            return
        if hasattr(self._instrument_repo, "deactivate"):
            await self._instrument_repo.deactivate(token)
            return
        if hasattr(self._instrument_repo, "update"):
            await self._instrument_repo.update(token, {"is_tradable": False})
            return
        raise RuntimeError(
            "Repository has no deactivate() or update() method"
        )

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------
    def _validate(
        self,
        raw: dict[str, Any],
        expected_exchange: str,
    ) -> tuple[dict[str, Any] | None, str | None]:
        """Validate a raw instrument dict.

        Returns (validated_dict, None) on success, (None, error_message) on failure.
        """
        errors: list[str] = []

        token = raw.get("instrument_token")
        if not isinstance(token, int) or token <= 0:
            errors.append("invalid instrument_token")

        exch = raw.get("exchange", "").upper()
        if exch != expected_exchange.upper():
            errors.append(f"exchange mismatch: {exch} != {expected_exchange}")

        symbol = raw.get("tradingsymbol", "")
        if not symbol or not isinstance(symbol, str):
            errors.append("missing or invalid tradingsymbol")

        lot_size = raw.get("lot_size", 1)
        if not isinstance(lot_size, int) or lot_size <= 0:
            errors.append("invalid lot_size")

        tick_size = raw.get("tick_size", Decimal("0.05"))
        try:
            ts = Decimal(str(tick_size))
            if ts <= 0:
                errors.append("invalid tick_size")
        except Exception:
            errors.append("invalid tick_size")

        if errors:
            return None, "; ".join(errors)

        # Normalise
        return {
            "instrument_token": token,
            "exchange": exch,
            "tradingsymbol": symbol,
            "name": raw.get("name"),
            "instrument_type": raw.get("instrument_type"),
            "segment": raw.get("segment"),
            "expiry": raw.get("expiry"),
            "strike": raw.get("strike"),
            "lot_size": lot_size,
            "tick_size": Decimal(str(tick_size)),
            "is_tradable": raw.get("is_tradable", True),
        }, None
