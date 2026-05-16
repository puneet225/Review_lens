"""
Ingestion pipeline — coordinates scrapers, deduplication, and PII scrubbing.

Entry point: `run_ingestion(product_config, ingestion_config) -> List[Review]`
"""

from __future__ import annotations

import logging
from typing import List, Optional

from review_pulse.agent.config import IngestionConfig, ProductConfig
from review_pulse.ingestion.scrubber import scrub_review_body
from review_pulse.store.models import Review

try:
    from review_pulse.ingestion.appstore import AppStoreScraper
except ImportError:  # pragma: no cover
    AppStoreScraper = None  # type: ignore[assignment,misc]

try:
    from review_pulse.ingestion.playstore import PlayStoreScraper
except ImportError:  # pragma: no cover
    PlayStoreScraper = None  # type: ignore[assignment,misc]

logger = logging.getLogger(__name__)


class IngestionError(Exception):
    """Raised when no reviews could be ingested from any source."""


def run_ingestion(
    product_config: ProductConfig,
    ingestion_config: IngestionConfig,
) -> List[Review]:
    """
    Run the full ingestion pipeline for a product.

    Steps:
      1. Scrape each configured store source
      2. Scrub PII from body text (raw_body kept intact)
      3. Cross-source deduplication by review_id
      4. Raise IngestionError if no reviews at all

    Args:
        product_config: Product configuration (store IDs, etc.)
        ingestion_config: Ingestion settings (window, max reviews)

    Returns:
        Deduplicated, PII-scrubbed list of Review objects.

    Raises:
        IngestionError: If all sources failed or returned zero reviews.
    """
    all_reviews: List[Review] = []
    sources_attempted = 0
    sources_succeeded = 0

    # --- App Store ---
    if product_config.appstore_id:
        sources_attempted += 1
        try:
            if AppStoreScraper is None:
                raise ImportError("app-store-web-scraper not installed")
            scraper = AppStoreScraper(
                product=product_config.name,
                app_id=product_config.appstore_id,
                window_weeks=ingestion_config.window_weeks,
                max_reviews=ingestion_config.max_reviews_per_source,
                country="in",
            )
            reviews = scraper.fetch()
            all_reviews.extend(reviews)
            if reviews:
                sources_succeeded += 1
                logger.info("App Store: %d reviews", len(reviews))
            else:
                logger.warning("App Store returned 0 reviews for %s", product_config.name)
        except Exception as exc:
            logger.warning("App Store ingestion failed: %s", exc, exc_info=True)

    # --- Play Store ---
    if product_config.playstore_id:
        sources_attempted += 1
        try:
            if PlayStoreScraper is None:
                raise ImportError("google-play-scraper not installed")
            scraper = PlayStoreScraper(
                product=product_config.name,
                package_name=product_config.playstore_id,
                window_weeks=ingestion_config.window_weeks,
                max_reviews=ingestion_config.max_reviews_per_source,
                country="in",
                lang="en",
            )
            reviews = scraper.fetch()
            all_reviews.extend(reviews)
            if reviews:
                sources_succeeded += 1
                logger.info("Play Store: %d reviews", len(reviews))
            else:
                logger.warning("Play Store returned 0 reviews for %s", product_config.name)
        except Exception as exc:
            logger.warning("Play Store ingestion failed: %s", exc, exc_info=True)

    logger.info(
        "Ingestion: %d total reviews from %d/%d sources",
        len(all_reviews),
        sources_succeeded,
        sources_attempted,
    )

    # --- Cross-source deduplication ---
    all_reviews = _deduplicate(all_reviews)
    logger.info("After deduplication: %d reviews", len(all_reviews))

    # --- PII scrubbing ---
    all_reviews = _scrub_all(all_reviews)

    # --- Guard: nothing ingested ---
    if not all_reviews:
        raise IngestionError(
            f"No reviews ingested for '{product_config.name}' from any source. "
            "Check network access and store IDs in config."
        )

    return all_reviews


def _deduplicate(reviews: List[Review]) -> List[Review]:
    """Remove duplicate reviews by review_id, keeping first occurrence."""
    seen: set = set()
    unique: List[Review] = []
    for r in reviews:
        if r.review_id not in seen:
            seen.add(r.review_id)
            unique.append(r)
    dupes = len(reviews) - len(unique)
    if dupes:
        logger.debug("Deduplication removed %d duplicate reviews", dupes)
    return unique


def _scrub_all(reviews: List[Review]) -> List[Review]:
    """
    Apply PII scrubber to body text.

    raw_body retains the original text.
    body gets the scrubbed version.
    """
    scrubbed_count = 0
    result: List[Review] = []
    for r in reviews:
        scrubbed_body = scrub_review_body(r.raw_body or r.body)
        if scrubbed_body != r.body:
            scrubbed_count += 1
        # model_copy preserves immutability while updating fields
        result.append(r.model_copy(update={"body": scrubbed_body}))

    if scrubbed_count:
        logger.info("PII scrubber redacted content in %d reviews", scrubbed_count)
    return result
