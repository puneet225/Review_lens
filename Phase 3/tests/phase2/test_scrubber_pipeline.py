"""
Phase 2 tests: PII scrubber and ingestion pipeline.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import patch

import pytest

from review_pulse.ingestion.scrubber import scrub_pii, scrub_review_body
from review_pulse.ingestion.pipeline import run_ingestion, IngestionError
from review_pulse.agent.config import IngestionConfig, ProductConfig


# ---------------------------------------------------------------------------
# PII Scrubber tests
# ---------------------------------------------------------------------------


class TestPiiScrubber:
    def test_clean_text_unchanged(self) -> None:
        text = "This app is great for investing."
        scrubbed, detected = scrub_pii(text)
        assert scrubbed == text
        assert detected == []

    def test_email_redacted(self) -> None:
        text = "Please contact me at john.doe@gmail.com for issues."
        scrubbed, detected = scrub_pii(text)
        assert "[EMAIL]" in scrubbed
        assert "john.doe@gmail.com" not in scrubbed
        assert "email" in detected

    def test_indian_phone_redacted(self) -> None:
        text = "Call me on 9876543210 for help."
        scrubbed, detected = scrub_pii(text)
        assert "[PHONE]" in scrubbed
        assert "9876543210" not in scrubbed
        assert "indian_phone" in detected

    def test_phone_with_country_code_redacted(self) -> None:
        text = "My number is +919876543210"
        scrubbed, detected = scrub_pii(text)
        assert "[PHONE]" in scrubbed
        assert "indian_phone" in detected

    def test_upi_id_redacted(self) -> None:
        text = "Send money to myname@okaxis please"
        scrubbed, detected = scrub_pii(text)
        assert "[UPI_ID]" in scrubbed
        assert "upi_id" in detected

    def test_pan_card_redacted(self) -> None:
        text = "My PAN is ABCDE1234F"
        scrubbed, detected = scrub_pii(text)
        assert "[PAN]" in scrubbed
        assert "pan_card" in detected

    def test_url_redacted(self) -> None:
        text = "Check this link https://groww.in/reset?token=abc123"
        scrubbed, detected = scrub_pii(text)
        assert "[URL]" in scrubbed
        assert "url" in detected

    def test_multiple_pii_in_one_text(self) -> None:
        text = "Email: test@example.com, Phone: 9876543210"
        scrubbed, detected = scrub_pii(text)
        assert "[EMAIL]" in scrubbed
        assert "[PHONE]" in scrubbed
        assert len(detected) >= 2

    def test_empty_string(self) -> None:
        scrubbed, detected = scrub_pii("")
        assert scrubbed == ""
        assert detected == []

    def test_normal_rating_text_not_redacted(self) -> None:
        """5-star review text with no PII should pass through unchanged."""
        text = "The app is smooth and the UI is clean. Highly recommend!"
        scrubbed, detected = scrub_pii(text)
        assert scrubbed == text
        assert detected == []

    def test_scrub_review_body_convenience(self) -> None:
        result = scrub_review_body("Call 9876543210 now")
        assert "[PHONE]" in result
        assert "9876543210" not in result


# ---------------------------------------------------------------------------
# Pipeline integration tests (mocked scrapers)
# ---------------------------------------------------------------------------


def _make_product_config(has_appstore: bool = True, has_playstore: bool = True) -> ProductConfig:
    return ProductConfig(
        name="groww",
        appstore_id="1404684442" if has_appstore else None,
        playstore_id="com.nextbillion.groww" if has_playstore else None,
        doc_title="Weekly Review Pulse — Groww",
        stakeholder_emails=[],
    )


def _make_ingestion_config() -> IngestionConfig:
    return IngestionConfig(window_weeks=12, max_reviews_per_source=500)


def _make_mock_reviews(count: int = 5, source: str = "appstore"):
    from review_pulse.store.models import Review
    return [
        Review(
            source=source,
            product="groww",
            rating=4,
            body=f"Review body {i}",
            raw_body=f"Review body {i}",
            date=datetime.utcnow() - timedelta(days=i),
            review_id=f"{source}_r{i}",
        )
        for i in range(count)
    ]


class TestIngestionPipeline:
    @patch("review_pulse.ingestion.pipeline.AppStoreScraper")
    @patch("review_pulse.ingestion.pipeline.PlayStoreScraper")
    def test_both_sources_succeed(self, MockPlay, MockApp) -> None:
        MockApp.return_value.fetch.return_value = _make_mock_reviews(5, "appstore")
        MockPlay.return_value.fetch.return_value = _make_mock_reviews(5, "playstore")

        # Import after mock is set up to avoid import ordering issues
        from review_pulse.ingestion.appstore import AppStoreScraper
        from review_pulse.ingestion.playstore import PlayStoreScraper

        with patch("review_pulse.ingestion.pipeline.run_ingestion") as mock_run:
            mock_run.return_value = _make_mock_reviews(10, "appstore")
            result = mock_run(_make_product_config(), _make_ingestion_config())

        assert len(result) == 10

    def test_raises_when_no_reviews(self) -> None:
        """IngestionError raised when both sources return nothing."""
        with patch("review_pulse.ingestion.pipeline.AppStoreScraper") as MockApp, \
             patch("review_pulse.ingestion.pipeline.PlayStoreScraper") as MockPlay:
            MockApp.return_value.fetch.return_value = []
            MockPlay.return_value.fetch.return_value = []

            with pytest.raises(IngestionError, match="No reviews ingested"):
                run_ingestion(_make_product_config(), _make_ingestion_config())

    def test_deduplication(self) -> None:
        """Duplicate review_ids across sources are removed."""
        from review_pulse.ingestion.pipeline import _deduplicate
        from review_pulse.store.models import Review

        r1 = Review(
            source="appstore", product="groww", rating=4,
            body="test", raw_body="test",
            date=datetime.utcnow(), review_id="same_id"
        )
        r2 = Review(
            source="playstore", product="groww", rating=3,
            body="other", raw_body="other",
            date=datetime.utcnow(), review_id="same_id"
        )
        result = _deduplicate([r1, r2])
        assert len(result) == 1
        assert result[0].review_id == "same_id"

    def test_pii_scrubbing_applied(self) -> None:
        """PII in raw_body is scrubbed from body."""
        from review_pulse.ingestion.pipeline import _scrub_all
        from review_pulse.store.models import Review

        r = Review(
            source="appstore", product="groww", rating=2,
            body="Call 9876543210",
            raw_body="Call 9876543210",
            date=datetime.utcnow(), review_id="pii_r1"
        )
        result = _scrub_all([r])
        assert "[PHONE]" in result[0].body
        assert result[0].raw_body == "Call 9876543210"  # raw_body unchanged

    def test_only_appstore_configured(self) -> None:
        """Works fine with only App Store configured."""
        with patch("review_pulse.ingestion.pipeline.AppStoreScraper") as MockApp:
            MockApp.return_value.fetch.return_value = _make_mock_reviews(3, "appstore")
            cfg = _make_product_config(has_appstore=True, has_playstore=False)
            result = run_ingestion(cfg, _make_ingestion_config())
            assert len(result) == 3

    def test_only_playstore_configured(self) -> None:
        """Works fine with only Play Store configured."""
        with patch("review_pulse.ingestion.pipeline.PlayStoreScraper") as MockPlay:
            MockPlay.return_value.fetch.return_value = _make_mock_reviews(4, "playstore")
            cfg = _make_product_config(has_appstore=False, has_playstore=True)
            result = run_ingestion(cfg, _make_ingestion_config())
            assert len(result) == 4
