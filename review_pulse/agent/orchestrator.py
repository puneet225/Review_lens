"""
Orchestrator stub — coordinates all pipeline phases.

This is a Phase 1 skeleton. Each phase method will be fleshed out
in subsequent phases.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional, List

from review_pulse.agent.config import AppConfig
from review_pulse.agent.idempotency import check_run_exists
from review_pulse.store.models import RunRecord
from review_pulse.store.run_log import RunLog

logger = logging.getLogger(__name__)


class Orchestrator:
    """Main agent loop — coordinates ingest → analyse → render → deliver."""

    def __init__(self, config: AppConfig, run_log: RunLog) -> None:
        self.config = config
        self.run_log = run_log

    async def run(self, product: str, iso_week: str, *, dry_run: bool = False) -> RunRecord:
        """
        Execute a full pipeline run for one product and one ISO week.

        Args:
            product: Product name (must exist in config).
            iso_week: ISO week string, e.g. '2026-W18'.
            dry_run: If True, skip MCP delivery.

        Returns:
            RunRecord with final status.
        """
        # Validate product exists in config
        product_config = self.config.get_product(product)

        # Idempotency check
        if await check_run_exists(self.run_log, product, iso_week):
            logger.info("⏭️  Skipping %s / %s — already completed", product, iso_week)
            existing = await self.run_log.get_run(product, iso_week)
            assert existing is not None
            return existing

        # Create run record
        record = RunRecord(product=product, iso_week=iso_week)
        if dry_run:
            record = record.model_copy(update={"status": "dry_run"})

        logger.info("🚀 Starting run for %s / %s (run_id=%s, dry_run=%s)", product, iso_week, record.id, dry_run)

        try:
            await self.run_log.insert_run(record)
        except Exception:
            # May fail if a previous failed run exists — update instead
            existing = await self.run_log.get_run(product, iso_week)
            if existing:
                record = existing.model_copy(update={"status": "pending"})
                await self.run_log.update_run(record.id, status="pending")

        try:
            # Phase 2: Ingestion (stub)
            logger.info("📥 Phase: Ingestion (product=%s, window=%dw)", product, self.config.ingestion.window_weeks)
            reviews: List = []  # Will be: await self._ingest(product_config)
            review_count = len(reviews)
            await self.run_log.update_run(record.id, reviews_count=review_count)

            # Phase 3: Analysis (stub)
            logger.info("🔬 Phase: Analysis (%d reviews)", review_count)
            # analysis_result = await self._analyse(reviews)

            # Phase 5: Rendering (stub)
            logger.info("📝 Phase: Rendering")
            # doc_payload = self._render_doc(analysis_result)
            # email_payload = self._render_email(analysis_result, doc_link)

            # Phase 4: Delivery (stub)
            if not dry_run:
                logger.info("📤 Phase: Delivery via MCP")
                # doc_result = await self._deliver_doc(doc_payload)
                # email_result = await self._deliver_email(email_payload)
            else:
                logger.info("🏜️  Dry run — skipping MCP delivery")

            # Mark success
            status = "dry_run" if dry_run else "success"
            now = datetime.utcnow()
            await self.run_log.update_run(
                record.id,
                status=status,
                completed_at=now,
            )
            logger.info("✅ Run completed: %s / %s → %s", product, iso_week, status)

            return (await self.run_log.get_run(product, iso_week)) or record

        except Exception as exc:
            logger.exception("❌ Run failed: %s / %s", product, iso_week)
            await self.run_log.update_run(
                record.id,
                status="failed",
                error_message=str(exc),
                completed_at=datetime.utcnow(),
            )
            return (await self.run_log.get_run(product, iso_week)) or record
