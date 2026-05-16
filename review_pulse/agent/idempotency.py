"""
Idempotency checker — prevents duplicate runs for the same (product, iso_week).

A run is considered complete (and blocks re-runs) only if its status is 'success'.
Failed, interrupted, and partial_success runs are retryable.
"""

from __future__ import annotations

import logging
from typing import Optional

from review_pulse.store.run_log import RunLog

logger = logging.getLogger(__name__)

# Statuses that block a re-run (the run already succeeded fully)
_BLOCKING_STATUSES = {"success"}


async def check_run_exists(run_log: RunLog, product: str, iso_week: str) -> bool:
    """
    Check if a successful run already exists for this product + week.

    Returns:
        True if a successful run exists (should skip).
        False if no run exists or previous runs failed (should proceed).
    """
    record = await run_log.get_run(product, iso_week)
    if record is None:
        logger.debug("No prior run found for %s / %s", product, iso_week)
        return False

    if record.status in _BLOCKING_STATUSES:
        logger.info(
            "Idempotent skip: %s / %s already completed (run %s, status=%s)",
            product,
            iso_week,
            record.id,
            record.status,
        )
        return True

    logger.info(
        "Prior run found for %s / %s with status=%s (retryable) — proceeding",
        product,
        iso_week,
        record.status,
    )
    return False
