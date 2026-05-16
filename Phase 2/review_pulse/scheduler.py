"""
APScheduler cron wrapper — triggers weekly runs per product.

Stub for Phase 1; will be completed in Phase 5.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def start_scheduler(config_path: str | None = None) -> None:
    """Start the APScheduler cron job for weekly runs.

    This is a Phase 1 stub. Full implementation in Phase 5.
    """
    logger.info("Scheduler stub — not yet implemented. Use CLI 'run' command for now.")
    raise NotImplementedError("Scheduler will be implemented in Phase 5")
