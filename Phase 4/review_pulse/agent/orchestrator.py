"""
Orchestrator — Phase 3 update: analysis pipeline wired in.

Pipeline:  ingest → analyse → render (stub) → deliver (stub)
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import List, Optional

from review_pulse.agent.config import AppConfig
from review_pulse.agent.idempotency import check_run_exists
from review_pulse.analysis.pipeline import AnalysisError, run_analysis
from review_pulse.ingestion.pipeline import IngestionError, run_ingestion
from review_pulse.store.models import AnalysisResult, Review, RunRecord
from review_pulse.store.run_log import RunLog

logger = logging.getLogger(__name__)


class Orchestrator:
    """Main agent loop — coordinates ingest → analyse → render → deliver."""

    def __init__(self, config: AppConfig, run_log: RunLog) -> None:
        self.config = config
        self.run_log = run_log
        # Stored after each run — used by the API layer for on-demand delivery
        self._last_analysis: Optional[AnalysisResult] = None
        self._last_review_count: int = 0
        self._last_theme_count: int = 0
        self._last_tokens: int = 0

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

        # Idempotency guard
        if await check_run_exists(self.run_log, product, iso_week):
            logger.info("⏭️  Skipping %s / %s — already completed", product, iso_week)
            existing = await self.run_log.get_run(product, iso_week)
            assert existing is not None
            return existing

        record = RunRecord(product=product, iso_week=iso_week)
        if dry_run:
            record = record.model_copy(update={"status": "dry_run"})

        logger.info("🚀 Starting run: %s / %s (run_id=%s, dry_run=%s)", product, iso_week, record.id, dry_run)

        try:
            await self.run_log.insert_run(record)
        except Exception:
            existing = await self.run_log.get_run(product, iso_week)
            if existing:
                record = existing.model_copy(update={"status": "pending"})
                await self.run_log.update_run(record.id, status="pending")

        try:
            # -------------------------------------------------------------------
            # Phase 2: INGESTION
            # -------------------------------------------------------------------
            logger.info("📥 [Phase 2] Ingestion — product=%s, window=%dw", product, self.config.ingestion.window_weeks)
            reviews: List[Review] = run_ingestion(product_config, self.config.ingestion)
            await self.run_log.update_run(record.id, reviews_count=len(reviews))
            logger.info("📥 Ingested %d reviews", len(reviews))

            # -------------------------------------------------------------------
            # Phase 3: ANALYSIS
            # -------------------------------------------------------------------
            logger.info("🔬 [Phase 3] Analysis — clustering %d reviews", len(reviews))
            analysis: AnalysisResult = run_analysis(reviews, self.config.analysis)
            # Store for API access
            self._last_analysis = analysis
            self._last_review_count = len(reviews)
            self._last_theme_count = len(analysis.themes)
            self._last_tokens = analysis.tokens_used
            await self.run_log.update_run(
                record.id,
                themes_count=len(analysis.themes),
                tokens_used=analysis.tokens_used,
            )
            logger.info(
                "🔬 Analysis complete — %d themes, %d tokens used, fallback=%s",
                len(analysis.themes),
                analysis.tokens_used,
                analysis.fallback_used,
            )

            # -------------------------------------------------------------------
            # Phase 5: RENDERING + DELIVERY
            # -------------------------------------------------------------------
            if not dry_run:
                logger.info("📄 [Phase 4] Creating Google Doc report...")
                from review_pulse.delivery.google_docs import create_google_doc
                from review_pulse.delivery.gmail import send_gmail_notification

                doc_id = create_google_doc(product, iso_week, analysis)
                await self.run_log.update_run(
                    record.id,
                    doc_id=doc_id,
                    doc_heading=f"Review Pulse — {product.title()} — {iso_week}",
                )

                # Send Gmail notification
                logger.info("📧 [Phase 4] Sending Gmail notification...")
                recipients = product_config.stakeholder_emails
                msg_id = send_gmail_notification(
                    product, iso_week, analysis, recipients, doc_id
                )
                if msg_id:
                    await self.run_log.update_run(record.id, gmail_msg_id=msg_id)
            else:
                logger.info("🏜️  Dry run — skipping delivery")

            status = "dry_run" if dry_run else "success"
            await self.run_log.update_run(record.id, status=status, completed_at=datetime.utcnow())
            logger.info("✅ Run completed: %s / %s → %s", product, iso_week, status)
            return (await self.run_log.get_run(product, iso_week)) or record

        except IngestionError as exc:
            logger.error("❌ Ingestion failed: %s", exc)
            await self.run_log.update_run(
                record.id, status="failed",
                error_message=f"Ingestion failed: {exc}",
                completed_at=datetime.utcnow(),
            )
            return (await self.run_log.get_run(product, iso_week)) or record

        except AnalysisError as exc:
            logger.error("❌ Analysis failed: %s", exc)
            await self.run_log.update_run(
                record.id, status="failed",
                error_message=f"Analysis failed: {exc}",
                completed_at=datetime.utcnow(),
            )
            return (await self.run_log.get_run(product, iso_week)) or record

        except Exception as exc:
            logger.exception("❌ Run failed: %s / %s", product, iso_week)
            await self.run_log.update_run(
                record.id, status="failed",
                error_message=str(exc),
                completed_at=datetime.utcnow(),
            )
            return (await self.run_log.get_run(product, iso_week)) or record
