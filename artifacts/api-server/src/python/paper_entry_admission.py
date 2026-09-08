"""Shared PostgreSQL lock identity for automatic paper-entry admission.

The capital migration and every OPEN-ledger insert must serialize on this key.
Keep this module dependency-free so safety tests cannot replace the identity
through broader phase20_store stubs.
"""

PAPER_ENTRY_ADMISSION_LOCK_ID = 2_026_081_900_001