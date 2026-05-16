"""
Abstract base class for all review scrapers.

Every source adapter must implement this interface.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from datetime import datetime, timedelta
from typing import List

from review_pulse.store.models import Review

logger = logging.getLogger(__name__)


class BaseScraper(ABC):
    """Abstract scraper — implement one per store."""

    source_name: str = "unknown"

    def __init__(self, product: str, window_weeks: int, max_reviews: int) -> None:
        self.product = product
        self.window_weeks = window_weeks
        self.max_reviews = max_reviews
        self.cutoff_date: datetime = datetime.utcnow() - timedelta(weeks=window_weeks)

    @abstractmethod
    def fetch(self) -> List[Review]:
        """Fetch reviews from the store. Must be implemented by subclasses."""
        ...

    def _is_within_window(self, review_date: datetime) -> bool:
        """Return True if the review date falls within the rolling window."""
        # Make both naive UTC for comparison
        if review_date.tzinfo is not None:
            review_date = review_date.replace(tzinfo=None)
        return review_date >= self.cutoff_date
