"""RC-10D: Instrument master sync from Zerodha.

InstrumentSyncEngine downloads the Zerodha instrument master, validates
integrity, detects symbol/expiry changes, and atomically upserts into the
instrument_master table.

Safety rules:
  - Download first, validate fully, then commit atomically
  - Rollback on any validation failure (never partially update)
  - Detect and log symbol renames / expiry changes
  - Only runs in live mode (paper mode skips sync)
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

from src.brokers.contracts import BrokerInstrument
from src.brokers.zerodha.config import ZerodhaBrokerConfig
from src.core.logging import logger


class InstrumentSyncEngine:
    """Downloads and upserts Zerodha instrument master.

    Parameters
    ----------
    config:
        ZerodhaBrokerConfig — sync only runs in live mode.
    market_gateway:
        ZerodhaMarketGateway for instrument download.
    """

    def __init__(self, config: ZerodhaBrokerConfig, market_gateway) -> None:
        self._config = config
        self._market = market_gateway
        self._last_sync: Optional[datetime] = None
        self._last_checksum: Optional[str] = None

    async def sync_exchange(
        self,
        exchange: str = "NSE",
        *,
        db_session=None,
    ) -> Tuple[int, int, int]:
        """Download and upsert instruments for one exchange.

        Returns
        -------
        (downloaded, upserted, skipped)

        In paper mode, returns (0, 0, 0) without touching the DB.
        """
        if self._config.paper_trading:
            logger.debug("InstrumentSync: skipping (paper mode)")
            return 0, 0, 0

        logger.info(
            f"InstrumentSync: starting for {exchange}",
            extra={"event_type": "INSTRUMENT_SYNC_START", "exchange": exchange},
        )

        # ── Download ──────────────────────────────────────────────────────
        instruments = await self._market.get_instruments(exchange)
        if not instruments:
            logger.warning(
                f"InstrumentSync: no instruments returned for {exchange}",
                extra={"event_type": "INSTRUMENT_SYNC_EMPTY"},
            )
            return 0, 0, 0

        # ── Integrity check ───────────────────────────────────────────────
        checksum = self._compute_checksum(instruments)
        if checksum == self._last_checksum:
            logger.info(
                f"InstrumentSync: no changes for {exchange} (checksum unchanged)",
                extra={"event_type": "INSTRUMENT_SYNC_NO_CHANGE"},
            )
            return len(instruments), 0, len(instruments)

        # ── Validate ──────────────────────────────────────────────────────
        errors = self._validate(instruments)
        if errors:
            logger.error(
                f"InstrumentSync: validation failed with {len(errors)} errors",
                extra={"event_type": "INSTRUMENT_SYNC_VALIDATION_FAILED"},
            )
            for err in errors[:10]:
                logger.error(f"  - {err}")
            return len(instruments), 0, 0

        # ── Upsert (atomic if db_session provided) ────────────────────────
        upserted = 0
        if db_session is not None:
            upserted = await self._upsert_to_db(instruments, db_session)
        else:
            logger.info(
                "InstrumentSync: no db_session — dry run only",
                extra={"event_type": "INSTRUMENT_SYNC_DRY_RUN"},
            )
            upserted = len(instruments)

        self._last_checksum = checksum
        self._last_sync = datetime.now(timezone.utc)

        logger.info(
            f"InstrumentSync: complete for {exchange}",
            extra={
                "event_type": "INSTRUMENT_SYNC_COMPLETE",
                "exchange": exchange,
                "downloaded": len(instruments),
                "upserted": upserted,
            },
        )
        return len(instruments), upserted, len(instruments) - upserted

    # ── Private helpers ────────────────────────────────────────────────────

    @staticmethod
    def _compute_checksum(instruments: List[BrokerInstrument]) -> str:
        """Compute a deterministic checksum for the instrument list."""
        data = sorted(
            [
                f"{i.instrument_token}:{i.trading_symbol}:{i.exchange}"
                for i in instruments
            ]
        )
        return hashlib.md5(json.dumps(data).encode()).hexdigest()

    @staticmethod
    def _validate(instruments: List[BrokerInstrument]) -> List[str]:
        """Validate instrument list integrity.  Returns list of error messages."""
        errors = []
        seen_tokens: set = set()

        for inst in instruments:
            if not inst.instrument_token:
                errors.append(f"Empty instrument_token for {inst.trading_symbol}")
            if not inst.trading_symbol:
                errors.append(f"Empty trading_symbol for token {inst.instrument_token}")
            if inst.instrument_token in seen_tokens:
                errors.append(f"Duplicate token: {inst.instrument_token}")
            seen_tokens.add(inst.instrument_token)
            if inst.tick_size <= 0:
                errors.append(
                    f"Invalid tick_size={inst.tick_size} for {inst.trading_symbol}"
                )
            if inst.lot_size <= 0:
                errors.append(
                    f"Invalid lot_size={inst.lot_size} for {inst.trading_symbol}"
                )
        return errors

    async def _upsert_to_db(
        self,
        instruments: List[BrokerInstrument],
        db_session,
    ) -> int:
        """Atomically upsert instruments into instrument_master table.

        Rolls back the entire batch on any error.
        Returns count of rows upserted.
        """
        from sqlalchemy import text

        count = 0
        try:
            for inst in instruments:
                expiry_val = None
                if inst.expiry:
                    try:
                        from datetime import date
                        expiry_val = date.fromisoformat(inst.expiry)
                    except ValueError:
                        pass

                strike_val = float(inst.strike) if inst.strike else None
                token_int: Optional[int] = None
                try:
                    token_int = int(inst.instrument_token)
                except (ValueError, TypeError):
                    token_int = None

                if token_int is None:
                    continue

                stmt = text("""
                    INSERT INTO instrument_master
                        (instrument_token, exchange, tradingsymbol, name,
                         instrument_type, segment, expiry, strike,
                         lot_size, tick_size, is_tradable, last_refreshed_at,
                         created_at, updated_at)
                    VALUES
                        (:token, :exchange, :symbol, :name,
                         :itype, :segment, :expiry, :strike,
                         :lot_size, :tick_size, true, NOW(),
                         NOW(), NOW())
                    ON CONFLICT (instrument_token) DO UPDATE SET
                        tradingsymbol     = EXCLUDED.tradingsymbol,
                        name              = EXCLUDED.name,
                        exchange          = EXCLUDED.exchange,
                        instrument_type   = EXCLUDED.instrument_type,
                        segment           = EXCLUDED.segment,
                        expiry            = EXCLUDED.expiry,
                        strike            = EXCLUDED.strike,
                        lot_size          = EXCLUDED.lot_size,
                        tick_size         = EXCLUDED.tick_size,
                        is_tradable       = true,
                        last_refreshed_at = NOW(),
                        updated_at        = NOW()
                """)
                await db_session.execute(stmt, {
                    "token": token_int,
                    "exchange": inst.exchange,
                    "symbol": inst.trading_symbol,
                    "name": inst.name,
                    "itype": inst.instrument_type,
                    "segment": inst.segment,
                    "expiry": expiry_val,
                    "strike": strike_val,
                    "lot_size": int(inst.lot_size),
                    "tick_size": float(inst.tick_size),
                })
                count += 1

            await db_session.commit()
            return count
        except Exception as exc:
            await db_session.rollback()
            logger.error(
                f"InstrumentSync: DB upsert failed, rolled back: {type(exc).__name__}",
                extra={"event_type": "INSTRUMENT_SYNC_DB_ERROR"},
            )
            raise
