"""Tests for Pydantic data models."""

from __future__ import annotations

from datetime import datetime

import pytest
from pydantic import ValidationError

from review_pulse.store.models import (
    AnalysisResult,
    Review,
    RunRecord,
    Theme,
    ValidatedQuote,
)


# ---------------------------------------------------------------------------
# E1.3 — Review Model
# ---------------------------------------------------------------------------


class TestReviewModel:
    def test_valid_review(self) -> None:
        r = Review(
            source="appstore",
            product="groww",
            rating=5,
            title="Great app",
            body="Love this app!",
            date=datetime(2026, 5, 1),
            review_id="abc123",
            raw_body="Love this app!",
        )
        assert r.rating == 5
        assert r.review_id == "abc123"

    def test_rating_out_of_range(self) -> None:
        with pytest.raises(ValidationError):
            Review(source="appstore", product="groww", rating=0, body="bad", date=datetime.now())
        with pytest.raises(ValidationError):
            Review(source="appstore", product="groww", rating=6, body="bad", date=datetime.now())

    def test_float_rating_coerced(self) -> None:
        r = Review(source="appstore", product="groww", rating=4.7, body="ok", date=datetime.now())
        assert r.rating == 5
        assert isinstance(r.rating, int)

    def test_empty_body_allowed(self) -> None:
        r = Review(source="playstore", product="groww", rating=3, body="", date=datetime.now())
        assert r.body == ""

    def test_auto_generated_review_id(self) -> None:
        r = Review(source="playstore", product="groww", rating=3, body="test", date=datetime(2026, 5, 1))
        assert len(r.review_id) == 16  # SHA256 hex[:16]

    def test_json_round_trip(self) -> None:
        r = Review(
            source="appstore",
            product="groww",
            rating=4,
            body="test body",
            date=datetime(2026, 5, 1),
            review_id="test123",
            raw_body="test body",
        )
        json_str = r.model_dump_json()
        r2 = Review.model_validate_json(json_str)
        assert r.review_id == r2.review_id
        assert r.body == r2.body

    def test_long_body_truncated(self) -> None:
        long_text = "a" * 6000
        r = Review(source="playstore", product="groww", rating=1, body=long_text, date=datetime.now())
        assert len(r.body) <= 5012  # 5000 + " [TRUNCATED]"
        assert r.body.endswith("[TRUNCATED]")

    def test_unicode_normalisation(self) -> None:
        # Zero-width characters should be stripped
        r = Review(
            source="appstore", product="groww", rating=3,
            body="hello\u200bworld\ufeff",
            date=datetime.now(),
        )
        assert "\u200b" not in r.body
        assert "\ufeff" not in r.body
        assert "helloworld" in r.body


# ---------------------------------------------------------------------------
# E1.3 — Theme / AnalysisResult
# ---------------------------------------------------------------------------


class TestThemeModel:
    def test_valid_theme(self) -> None:
        t = Theme(
            name="App crashes",
            description="Users report crashes during market hours",
            quotes=[
                ValidatedQuote(text="App freezes", source_review_id="r1", store="appstore", rating=1)
            ],
            action="Fix crash bugs",
            review_count=42,
        )
        assert t.name == "App crashes"
        assert len(t.quotes) == 1

    def test_analysis_result_defaults(self) -> None:
        ar = AnalysisResult()
        assert ar.themes == []
        assert ar.total_reviews == 0
        assert ar.is_partial is False


# ---------------------------------------------------------------------------
# E1.3 — RunRecord
# ---------------------------------------------------------------------------


class TestRunRecordModel:
    def test_valid_run_record(self) -> None:
        rr = RunRecord(product="groww", iso_week="2026-W18")
        assert rr.status == "pending"
        assert len(rr.id) == 32  # UUID hex
        assert rr.iso_week == "2026-W18"

    def test_iso_week_normalisation(self) -> None:
        rr = RunRecord(product="groww", iso_week="2026-W8")
        assert rr.iso_week == "2026-W08"

    def test_invalid_iso_week(self) -> None:
        with pytest.raises(ValidationError):
            RunRecord(product="groww", iso_week="2026-W99")
        with pytest.raises(ValidationError):
            RunRecord(product="groww", iso_week="invalid")

    def test_run_record_fields(self) -> None:
        rr = RunRecord(
            product="groww",
            iso_week="2026-W18",
            status="success",
            reviews_count=100,
            themes_count=5,
            doc_id="doc123",
            doc_heading="Week 2026-W18",
            gmail_msg_id="msg456",
            tokens_used=25000,
            cost_usd=0.05,
        )
        assert rr.reviews_count == 100
        assert rr.cost_usd == 0.05
