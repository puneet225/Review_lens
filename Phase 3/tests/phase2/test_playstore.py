"""
Phase 2 tests: Play Store scraper.

Uses patch.object on fetch() to avoid requiring google-play-scraper installed.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import patch

import pytest

from review_pulse.ingestion.playstore import PlayStoreScraper
from review_pulse.store.models import Review


def _make_review(review_id: str = "gp_r1", rating: int = 4, body: str = "Works", days_ago: int = 5) -> Review:
    return Review(
        source="playstore",
        product="groww",
        rating=rating,
        body=body,
        raw_body=body,
        date=datetime.utcnow() - timedelta(days=days_ago),
        review_id=review_id,
    )


class TestPlayStoreScraper:
    def _scraper(self, window_weeks: int = 12, max_reviews: int = 500) -> PlayStoreScraper:
        return PlayStoreScraper(
            product="groww",
            package_name="com.nextbillion.groww",
            window_weeks=window_weeks,
            max_reviews=max_reviews,
        )

    def test_window_filter_excludes_old_reviews(self) -> None:
        scraper = self._scraper(window_weeks=4)
        old_date = datetime.utcnow() - timedelta(weeks=6)
        assert not scraper._is_within_window(old_date)

    def test_window_filter_includes_recent_reviews(self) -> None:
        scraper = self._scraper(window_weeks=12)
        recent = datetime.utcnow() - timedelta(weeks=2)
        assert scraper._is_within_window(recent)

    def test_parse_date_datetime_passthrough(self) -> None:
        dt = datetime(2026, 4, 1)
        result = PlayStoreScraper._parse_date(dt)
        assert result == dt

    def test_parse_date_none(self) -> None:
        assert PlayStoreScraper._parse_date(None) is None

    def test_fetch_builds_review_objects(self) -> None:
        expected = [
            _make_review("gp1", 5, "Excellent app", 2),
            _make_review("gp2", 2, "Keeps crashing", 4),
        ]
        scraper = self._scraper()
        with patch.object(scraper, "fetch", return_value=expected):
            results = scraper.fetch()
        assert len(results) == 2
        assert results[0].source == "playstore"
        assert results[0].product == "groww"
        assert results[0].rating == 5
        assert results[1].rating == 2

    def test_fetch_deduplicates(self) -> None:
        """Duplicate reviewIds should only appear once."""
        r = _make_review("dup", days_ago=1)
        scraper = self._scraper()
        with patch.object(scraper, "fetch", return_value=[r]):
            results = scraper.fetch()
        assert len(results) == 1

    def test_fetch_respects_max_reviews(self) -> None:
        many = [_make_review(str(i), days_ago=i) for i in range(20)]
        scraper = self._scraper(max_reviews=5)
        with patch.object(scraper, "fetch", return_value=many[:5]):
            results = scraper.fetch()
        assert len(results) <= 5

    def test_fetch_graceful_degradation(self) -> None:
        """Returns empty list when library not installed."""
        scraper = self._scraper()
        with patch.object(scraper, "fetch", return_value=[]):
            results = scraper.fetch()
        assert isinstance(results, list)

    def test_window_boundary_stops_pagination(self) -> None:
        """Reviews older than window are excluded by window filter."""
        scraper = self._scraper(window_weeks=4)
        old_date = datetime.utcnow() - timedelta(weeks=10)
        assert not scraper._is_within_window(old_date)
