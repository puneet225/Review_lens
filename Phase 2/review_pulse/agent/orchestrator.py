"""
Orchestrator — coordinates all pipeline phases.

Phase 2 update: ingestion is now live.
Phases 3–5 (analysis, rendering, delivery) remain stubbed.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import List, Optional

from review_pulse.agent.config import AppConfig
from review_pulse.agent.idempotency import check_run_exists
from review_pulse.ingestion.pipeline import IngestionError, run_ingestion
from review_pulse.store.models import Review, RunRecord
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

        logger.info(
            "🚀 Starting run for %s / %s (run_id=%s, dry_run=%s)",
            product, iso_week, record.id, dry_run,
        )

        # Insert or reset existing failed run
        try:
            await self.run_log.insert_run(record)
        except Exception:
            existing = await self.run_log.get_run(product, iso_week)
            if existing:
                record = existing.model_copy(update={"status": "pending"})
                await self.run_log.update_run(record.id, status="pending")

        try:
            # ---------------------------------------------------------------
            # Phase 2: INGESTION (live)
            # ---------------------------------------------------------------
            logger.info(
                "📥 [Phase 2] Ingestion — product=%s, window=%dw, max=%d/source",
                product,
                self.config.ingestion.window_weeks,
                self.config.ingestion.max_reviews_per_source,
            )
            reviews: List[Review] = run_ingestion(product_config, self.config.ingestion)
            review_count = len(reviews)
            await self.run_log.update_run(record.id, reviews_count=review_count)
            logger.info("📥 Ingested %d reviews total", review_count)

            # ---------------------------------------------------------------
            # Phase 3: Analysis (stub — Phase 3 will implement)
            # ---------------------------------------------------------------
            logger.info("🔬 [Phase 3] Analysis — stub (will cluster %d reviews)", review_count)
            # analysis_result = await self._analyse(reviews)

            # ---------------------------------------------------------------
            # Phase 5: Rendering (stub)
            # ---------------------------------------------------------------
            logger.info("📝 [Phase 5] Rendering — stub")

            # ---------------------------------------------------------------
            # Phase 4: Delivery via MCP (stub)
            # ---------------------------------------------------------------
            if not dry_run:
                logger.info("📤 [Phase 4] Delivery via MCP — stub")
            else:
                logger.info("🏜️  Dry run — skipping MCP delivery")

            # Mark success
            status = "dry_run" if dry_run else "success"
            await self.run_log.update_run(
                record.id,
                status=status,
                completed_at=datetime.utcnow(),
            )
            logger.info("✅ Run completed: %s / %s → %s", product, iso_week, status)
            return (await self.run_log.get_run(product, iso_week)) or record

        except IngestionError as exc:
            logger.error("❌ Ingestion failed for %s / %s: %s", product, iso_week, exc)
            await self.run_log.update_run(
                record.id,
                status="failed",
                error_message=f"Ingestion failed: {exc}",
                completed_at=datetime.utcnow(),
            )
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
