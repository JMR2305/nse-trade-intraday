"""Portfolio CLI — operator commands for portfolio maintenance.

Usage
-----
    python -m src.portfolio.cli <command> [options]

Commands
--------
rebuild-from-fills
    Rebuild portfolio state from fill-event history.  Use this when the
    snapshot store is corrupt or unavailable.  The command replays every
    ``FILL_RECEIVED`` event and prints the resulting position summary.

Options
-------
--portfolio-id TEXT   Portfolio identifier (default: "default")
--dry-run             Print what would be done without mutating any state.
--verbose             Emit DEBUG-level log output.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from decimal import Decimal


def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-8s %(name)s  %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%SZ",
    )


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

async def _rebuild_from_fills(
    portfolio_id: str,
    dry_run: bool,
    initial_capital: Decimal,
) -> int:
    """Execute the rebuild-from-fills recovery path.

    Returns the OS exit code (0 = success, 1 = failure, 2 = no fills found).
    """
    from src.portfolio.config import PortfolioConfig
    from src.portfolio.repositories.portfolio_event import PortfolioEventRepository
    from src.portfolio.service import PortfolioService

    logger = logging.getLogger(__name__)

    # In the real deployment the event_repo would be database-backed.
    # The CLI bootstraps an in-memory repo here so the command is always
    # runnable; production wiring should inject the DB-backed repo instead.
    event_repo = PortfolioEventRepository()

    config = PortfolioConfig(
        portfolio_id=portfolio_id,
        initial_capital=initial_capital,
    )
    svc = PortfolioService(config=config, event_repo=event_repo)

    if dry_run:
        print(
            f"[DRY-RUN] Would rebuild portfolio '{portfolio_id}' from fill history.\n"
            f"          No event_repo is wired in dry-run mode; 0 fills will be found.\n"
            f"          In production, inject the DB-backed event_repo first."
        )
        return 0

    logger.info("Starting rebuild-from-fills for portfolio '%s'", portfolio_id)

    result = await svc.rebuild_from_fills(portfolio_id=portfolio_id)

    if result is None:
        print(
            f"[WARN] rebuild-from-fills: no FILL_RECEIVED events found for "
            f"portfolio '{portfolio_id}'.  State was NOT rebuilt.\n"
            f"       If this is unexpected, verify that the event_repo is wired "
            f"to the correct database and that events have been persisted."
        )
        return 2

    # Print summary
    positions = result.open_positions
    print(
        f"\n{'='*60}\n"
        f"  rebuild-from-fills COMPLETE\n"
        f"{'='*60}\n"
        f"  Portfolio : {result.portfolio_id}\n"
        f"  Version   : {result.version}\n"
        f"  Status    : {result.status.value}\n"
        f"  Cash      : {result.cash.total} (available={result.cash.available})\n"
        f"  Positions : {len(positions)} open\n"
    )
    if positions:
        print(f"  {'Symbol':<20} {'Side':<6} {'Qty':>8} {'Avg Price':>12}")
        print(f"  {'-'*50}")
        for pos in positions:
            print(
                f"  {pos.instrument_symbol:<20} {pos.side.value:<6} "
                f"{pos.open_quantity:>8} {str(pos.average_entry_price):>12}"
            )
    print()

    logger.info(
        "rebuild-from-fills successful: %d positions, cash=%s",
        len(positions),
        result.cash.total,
    )
    return 0


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m src.portfolio.cli",
        description="Portfolio maintenance CLI for NSE trading platform operators.",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable DEBUG-level logging.",
    )

    sub = parser.add_subparsers(dest="command", required=True)

    # rebuild-from-fills
    rbf = sub.add_parser(
        "rebuild-from-fills",
        help=(
            "Rebuild portfolio state by replaying all fill events from the "
            "event store.  Use when the snapshot store is corrupt or missing."
        ),
    )
    rbf.add_argument(
        "--portfolio-id",
        default="default",
        help="Portfolio identifier to rebuild (default: 'default').",
    )
    rbf.add_argument(
        "--initial-capital",
        type=Decimal,
        default=Decimal("0"),
        help=(
            "Cash baseline used to seed the rebuilt state before fills are "
            "replayed.  Should match the amount deposited before the first "
            "trade.  Defaults to 0 (fills carry their own cash impact)."
        ),
    )
    rbf.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be done without mutating state.",
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    _setup_logging(args.verbose)

    if args.command == "rebuild-from-fills":
        return asyncio.run(
            _rebuild_from_fills(
                portfolio_id=args.portfolio_id,
                dry_run=args.dry_run,
                initial_capital=args.initial_capital,
            )
        )

    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
