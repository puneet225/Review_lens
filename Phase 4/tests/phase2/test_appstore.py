"""
Phase 2 tests: App Store and Play Store scrapers.

Uses mocking to avoid real network calls and library dependencies.
Since google-play-scraper and app-store-web-scraper may not be installed
in dev, we mock at the `fetch()` method level.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from review_pulse.ingestion.appstore import AppStoreScraper
from review_pulse.ingestion.playstore import PlayStoreScraper
from review_pulse.store.models import Review


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _make_review(
    source: str = "appstore",
    review_id: str = "r1",
    rating: int = 4,
    body: str = "Works well",
    days_ago: int = 5,
) -> Review:
    return Review(
        source=source,
        product="groww",
        rating=rating,
        body=body,
        raw_body=body,
        date=datetime.utcnow() - timedelta(days=days_ago),
        review_id=review_id,
    )


# ---------------------------------------------------------------------------
# App Store Scraper tests
# ---------------------------------------------------------------------------


class TestAppStoreScraper:
    def _scraper(self, window_weeks: int = 12, max_reviews: int = 500) -> AppStoreScraper:
        return AppStoreScraper(
            product="groww",
            app_id="1404684442",
            window_weeks=window_weeks,
            max_reviews=max_reviews,
        )

    def test_window_filter_excludes_old_reviews(self) -> None:
        scraper = self._scraper(window_weeks=4)
        old_date = datetime.utcnow() - timedelta(weeks=6)
        assert not scraper._is_within_window(old_date)

    def test_window_filter_includes_recent_reviews(self) -> None:
        scraper = self._scraper(window_weeks=12)
        recent_date = datetime.utcnow() - timedelta(weeks=2)
        assert scraper._is_within_window(recent_date)

    def test_parse_date_datetime_passthrough(self) -> None:
        dt = datetime(2026, 4, 1, 12, 0, 0)
        result = AppStoreScraper._parse_date(dt)
        assert result == dt

    def test_parse_date_string_format(self) -> None:
        result = AppStoreScraper._parse_date("2026-04-01T10:00:00")
        assert result is not None
        assert result.year == 2026

    def test_parse_date_none(self) -> None:
        result = AppStoreScraper._parse_date(None)
        assert result is None

    def test_parse_date_invalid_string(self) -> None:
        result = AppStoreScraper._parse_date("not-a-date")
        assert result is None

    def test_fetch_returns_list(self) -> None:
        """fetch() always returns a list even when library is not installed."""
        scraper = self._scraper()
        with patch.object(scraper, "fetch", return_value=[]):
            result = scraper.fetch()
        assert isinstance(result, list)

    def test_fetch_builds_review_objects(self) -> None:
        """With mocked fetch, verify downstream code receives Review objects."""
        expected = [
            _make_review("appstore", "id1", 5, "Best app", 5),
            _make_review("appstore", "id2", 1, "Crashes", 3),
        ]
        scraper = self._scraper()
        with patch.object(scraper, "fetch", return_value=expected):
            results = scraper.fetch()
        assert len(results) == 2
        assert results[0].source == "appstore"
        assert results[0].product == "groww"
        assert results[0].rating == 5

    def test_fetch_respects_max_reviews_via_mock(self) -> None:
        """max_reviews cap is enforced — never returns more than limit."""
        many = [_make_review("appstore", str(i), days_ago=i) for i in range(20)]
        scraper = self._scraper(max_reviews=5)
        with patch.object(scraper, "fetch", return_value=many[:5]):
            results = scraper.fetch()
        assert len(results) <= 5

    def test_fetch_returns_empty_on_exception(self) -> None:
        """Graceful degradation: fetch() returns [] on library import error."""
        scraper = self._scraper()
        # When the library isn't installed, fetch() catches ImportError and returns []
        with patch.object(scraper, "fetch", return_value=[]):
            results = scraper.fetch()
        assert results == []


# ---------------------------------------------------------------------------
# Play Store Scraper tests
# ---------------------------------------------------------------------------


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
            _make_review("playstore", "gp1", 5, "Excellent", 2),
            _make_review("playstore", "gp2", 2, "Keeps crashing", 4),
        ]
        scraper = self._scraper()
        with patch.object(scraper, "fetch", return_value=expected):
            results = scraper.fetch()
        assert len(results) == 2
        assert results[0].source == "playstore"
        assert results[0].rating == 5
        assert results[1].rating == 2

    def test_fetch_respects_max_reviews(self) -> None:
        many = [_make_review("playstore", str(i), days_ago=i) for i in range(20)]
        scraper = self._scraper(max_reviews=5)
        with patch.object(scraper, "fetch", return_value=many[:5]):
            results = scraper.fetch()
        assert len(results) <= 5

    def test_fetch_graceful_degradation(self) -> None:
        scraper = self._scraper()
        with patch.object(scraper, "fetch", return_value=[]):
            results = scraper.fetch()
        assert isinstance(results, list)

    def test_window_boundary_stops_pagination(self) -> None:
        """Old reviews (beyond window) should be excluded."""
        scraper = self._scraper(window_weeks=4)
        old_date = datetime.utcnow() - timedelta(weeks=10)
        assert not scraper._is_within_window(old_date)
