"""
Play Store review scraper using the google-play-scraper library.

Fetches reviews in English and Hindi (in, IN locale) for Indian fintech apps.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime
from typing import List, Optional

from review_pulse.ingestion.base import BaseScraper
from review_pulse.store.models import Review

logger = logging.getLogger(__name__)

# Google Play uses continuation tokens for pagination
_REVIEWS_PER_BATCH = 100
_MAX_BATCHES = 10           # Safety cap: max 1000 reviews per run
_BATCH_DELAY_SECONDS = 0.5  # Polite delay between batches


class PlayStoreScraper(BaseScraper):
    """Scrapes reviews from the Google Play Store."""

    source_name = "playstore"

    def __init__(
        self,
        product: str,
        package_name: str,
        window_weeks: int,
        max_reviews: int,
        country: str = "in",
        lang: str = "en",
    ) -> None:
        super().__init__(product, window_weeks, max_reviews)
        self.package_name = package_name
        self.country = country
        self.lang = lang

    def fetch(self) -> List[Review]:
        """
        Fetch Play Store reviews using pagination.

        Returns a deduplicated list of Review objects within the rolling window.
        """
        try:
            from google_play_scraper import reviews as gps_reviews, Sort
        except ImportError:
            logger.error(
                "google-play-scraper not installed. Run: pip install google-play-scraper"
            )
            return []

        logger.info(
            "🤖 Fetching Play Store reviews — package=%s, country=%s, lang=%s, window=%dw",
            self.package_name,
            self.country,
            self.lang,
            self.window_weeks,
        )

        all_reviews: List[Review] = []
        seen_ids: set = set()
        continuation_token = None
        batch_num = 0
        hit_window_boundary = False

        while batch_num < _MAX_BATCHES and not hit_window_boundary:
            if len(all_reviews) >= self.max_reviews:
                logger.debug("Play Store: reached max_reviews=%d cap", self.max_reviews)
                break

            try:
                raw_batch, continuation_token = gps_reviews(
                    self.package_name,
                    lang=self.lang,
                    country=self.country,
                    sort=Sort.NEWEST,
                    count=_REVIEWS_PER_BATCH,
                    continuation_token=continuation_token,
                )
            except Exception as exc:
                logger.warning("Play Store batch %d failed: %s", batch_num, exc, exc_info=True)
                break

            if not raw_batch:
                logger.debug("Play Store: empty batch at batch_num=%d — done", batch_num)
                break

            for raw in raw_batch:
                # Parse date
                review_date = self._parse_date(raw.get("at"))
                if review_date is None:
                    continue

                # Stop paginating if we've hit the window boundary
                if not self._is_within_window(review_date):
                    hit_window_boundary = True
                    break

                # Deduplication
                review_id = str(raw.get("reviewId", ""))
                if review_id and review_id in seen_ids:
                    continue
                if review_id:
                    seen_ids.add(review_id)

                rating = raw.get("score", 3)
                body = (raw.get("content") or "").strip()
                version = raw.get("appVersion")

                review = Review(
                    source="playstore",
                    product=self.product,
                    rating=rating,
                    title=None,   # Play Store has no title field
                    body=body,
                    raw_body=body,
                    date=review_date,
                    review_id=review_id,
                    version=str(version) if version else None,
                )
                all_reviews.append(review)

                if len(all_reviews) >= self.max_reviews:
                    break

            batch_num += 1

            # No more pages
            if continuation_token is None:
                break

            # Polite delay to avoid rate limiting
            time.sleep(_BATCH_DELAY_SECONDS)

        logger.info(
            "✅ Play Store: fetched %d reviews for %s (batches=%d)",
            len(all_reviews),
            self.product,
            batch_num,
        )
        return all_reviews

    @staticmethod
    def _parse_date(raw_date) -> Optional[datetime]:
        """Parse date from Play Store response (typically a datetime object already)."""
        if raw_date is None:
            return None
        if isinstance(raw_date, datetime):
            return raw_date
        # Fallback string parse
        try:
            return datetime.fromisoformat(str(raw_date))
        except (ValueError, TypeError):
            logger.debug("Could not parse Play Store date: %r", raw_date)
            return None
