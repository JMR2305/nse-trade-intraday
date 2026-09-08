"""Phase 2B advisory-only multi-bot analysis package.

This package intentionally has no execution, broker, scheduler, position, or
settings-write dependency.  It produces analysis records only.
"""

from .contracts import ADVISORY_DECISIONS, advisory_output, assert_advisory_output

__all__ = [
    "ADVISORY_DECISIONS",
    "advisory_output",
    "assert_advisory_output",
]