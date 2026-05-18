"""
App Store review scraper using the app-store-web-scraper library.

Targets the Indian App Store (country='in') for Groww and other fintech apps.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import List, Optional

from collections import Counter

from review_pulse.ingestion.base import BaseScraper
from review_pulse.ingestion.quality import assess as assess_quality
from review_pulse.store.models import Review

logger = logging.getLogger(__name__)


class AppStoreScraper(BaseScraper):
    """Scrapes reviews from the Apple App Store."""

    source_name = "appstore"

    def __init__(
        self,
        product: str,
        app_id: str,
        window_weeks: int,
        max_reviews: int,
        country: str = "in",
    ) -> None:
        super().__init__(product, window_weeks, max_reviews)
        self.app_id = app_id
        self.country = country

    def fetch(self) -> List[Review]:
        """
        Fetch App Store reviews for the configured app.

        Returns a deduplicated list of Review objects within the rolling window.
        """
        try:
            from app_store_web_scraper import AppStoreEntry
        except ImportError:
            logger.error(
                "app-store-web-scraper not installed. Run: pip install app-store-web-scraper"
            )
            return []

        logger.info(
            "📱 Fetching App Store reviews — app_id=%s, country=%s, window=%dw",
            self.app_id,
            self.country,
            self.window_weeks,
        )

        reviews: List[Review] = []
        seen_ids: set = set()
        rejected: Counter = Counter()

        try:
            entry = AppStoreEntry(app_id=int(self.app_id), country=self.country)

            # The library sometimes has .reviews as a method instead of a property
            raw_reviews = entry.reviews() if callable(entry.reviews) else entry.reviews
            for raw in raw_reviews:
                if len(reviews) >= self.max_reviews:
                    logger.debug("App Store: reached max_reviews=%d cap", self.max_reviews)
                    break

                # Parse date
                review_date = self._parse_date(raw.get("date"))
                if review_date is None:
                    continue

                # Window filter
                if not self._is_within_window(review_date):
                    continue

                # Deduplication
                review_id = str(raw.get("id", ""))
                if review_id and review_id in seen_ids:
                    continue
                if review_id:
                    seen_ids.add(review_id)

                # Build Review
                rating = raw.get("rating", 3)
                title = (raw.get("title") or "").strip() or None
                body = (raw.get("review") or raw.get("body") or "").strip()
                version = raw.get("version")

                # App Store reviews can carry signal in the title even when the
                # body is sparse, so assess the combined text.
                verdict = assess_quality(f"{title or ''} {body}".strip())
                if not verdict.keep:
                    rejected[verdict.reason] += 1
                    continue

                review = Review(
                    source="appstore",
                    product=self.product,
                    rating=rating,
                    title=title,
                    body=body,
                    raw_body=body,
                    date=review_date,
                    review_id=review_id,
                    version=str(version) if version else None,
                )
                reviews.append(review)

        except Exception as exc:
            logger.warning("App Store scraper failed: %s", exc, exc_info=True)
            return reviews  # Return partial results

        if rejected:
            logger.info(
                "🧹 App Store: filtered out %d low-quality reviews for %s (%s)",
                sum(rejected.values()),
                self.product,
                ", ".join(f"{r}={n}" for r, n in rejected.most_common()),
            )
        logger.info("✅ App Store: fetched %d reviews for %s", len(reviews), self.product)
        return reviews

    @staticmethod
    def _parse_date(raw_date) -> Optional[datetime]:
        """Parse various date formats from the scraper into a datetime."""
        if raw_date is None:
            return None
        if isinstance(raw_date, datetime):
            return raw_date
        # Try common string formats
        for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d", "%d/%m/%Y"):
            try:
                return datetime.strptime(str(raw_date), fmt)
            except ValueError:
                continue
        logger.debug("Could not parse App Store date: %r", raw_date)
        return None
