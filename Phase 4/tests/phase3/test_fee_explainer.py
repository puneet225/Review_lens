"""
Regression tests for fee_explainer.enrich_themes.

All tests are offline: Chroma and Gemini/Groq calls are mocked so no
network or model artefacts are required.
"""

from __future__ import annotations

from datetime import date, datetime
from unittest.mock import MagicMock, patch

import pytest

from review_pulse.analysis import fee_explainer as fe_module
from review_pulse.analysis.classifier import OTHER_KEY
from review_pulse.store.models import FeeExplainer, Theme, ValidatedQuote


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _theme(
    name: str = "Test theme",
    sentiment: str = "NEGATIVE",
    category_key: str | None = "fees",
) -> Theme:
    return Theme(
        name=name,
        sentiment=sentiment,
        category_key=category_key,
        quotes=[
            ValidatedQuote(
                text="some charge detail",
                source_review_id="r1",
                store="appstore",
                rating=2,
            )
        ],
    )


def _fake_collection(top_distance: float = 0.2) -> MagicMock:
    """Return a mock Chroma collection whose .query() returns one chunk within threshold."""
    col = MagicMock()
    col.query.return_value = {
        "ids": [["chunk-1"]],
        "documents": [["Groww charges 0.1% brokerage."]],
        "metadatas": [[{"url": "https://groww.in/fees", "section_path": "brokerage", "scraped_at": "2026-01-01T00:00:00"}]],
        "distances": [[top_distance]],
    }
    return col


def _fake_synthesis() -> dict:
    return {
        "title": "Brokerage Charges",
        "bullets": ["Groww charges 0.1% brokerage per trade."],
        "used_chunk_ids": ["chunk-1"],
    }


# ---------------------------------------------------------------------------
# Core regression: Other bucket must NEVER be enriched
# ---------------------------------------------------------------------------

class TestOtherBucketNeverEnriched:
    """The Other bucket must be skipped even when sentiment and distance would
    normally allow enrichment."""

    def test_other_theme_skipped_no_collection_query(self):
        """A theme with category_key == OTHER_KEY must not trigger a Chroma query
        even when _embed_query would succeed (simulated by mocking it)."""
        theme = _theme(category_key=OTHER_KEY, sentiment="NEGATIVE")
        mock_col = _fake_collection(top_distance=0.2)  # well within _MAX_DISTANCE

        with (
            patch.object(fe_module, "_get_collection", return_value=mock_col),
            patch.object(fe_module, "_embed_query", return_value=[0.1] * 768),
        ):
            result = fe_module.enrich_themes([theme], product="groww")

        # fee_explainer must remain None
        assert result[0].fee_explainer is None, (
            "Other-bucket theme must never receive a fee_explainer"
        )
        # Chroma collection.query must NOT have been called at all
        mock_col.query.assert_not_called()

    def test_other_theme_skipped_regardless_of_sentiment(self):
        """Covers all gated sentiments to ensure neither NEGATIVE nor MIXED
        bypasses the Other-bucket guard."""
        for sentiment in ("NEGATIVE", "MIXED"):
            theme = _theme(category_key=OTHER_KEY, sentiment=sentiment)
            mock_col = _fake_collection(top_distance=0.1)  # very close match

            with (
                patch.object(fe_module, "_get_collection", return_value=mock_col),
                patch.object(fe_module, "_embed_query", return_value=[0.1] * 768),
            ):
                result = fe_module.enrich_themes([theme], product="groww")

            assert result[0].fee_explainer is None, (
                f"Other theme with sentiment={sentiment} must not be enriched"
            )
            mock_col.query.assert_not_called()


# ---------------------------------------------------------------------------
# Positive case: real fee category still gets enriched
# ---------------------------------------------------------------------------

class TestRealCategoryStillEnriched:
    """Ensures the fix does NOT break enrichment for genuine fee themes."""

    def test_fees_category_theme_enriched(self):
        """A theme with category_key='fees', NEGATIVE sentiment, and a close
        Chroma match MUST receive a fee_explainer."""
        theme = _theme(category_key="fees", sentiment="NEGATIVE")
        mock_col = _fake_collection(top_distance=0.2)

        with (
            patch.object(fe_module, "_get_collection", return_value=mock_col),
            patch.object(fe_module, "_embed_query", return_value=[0.1] * 768),
            patch.object(fe_module, "_synthesise", return_value=_fake_synthesis()),
        ):
            result = fe_module.enrich_themes([theme], product="groww")

        assert result[0].fee_explainer is not None, (
            "A fees-category theme with a close Chroma match must be enriched"
        )

    def test_none_category_key_still_enriched(self):
        """Themes produced by the TF-IDF fallback have category_key=None.
        They should not be blocked by the Other-bucket guard."""
        theme = _theme(category_key=None, sentiment="NEGATIVE")
        mock_col = _fake_collection(top_distance=0.2)

        with (
            patch.object(fe_module, "_get_collection", return_value=mock_col),
            patch.object(fe_module, "_embed_query", return_value=[0.1] * 768),
            patch.object(fe_module, "_synthesise", return_value=_fake_synthesis()),
        ):
            result = fe_module.enrich_themes([theme], product="groww")

        assert result[0].fee_explainer is not None, (
            "A fallback theme (category_key=None) with a close match must still be enriched"
        )


# ---------------------------------------------------------------------------
# Mixed batch: Other theme in a list with a real fees theme
# ---------------------------------------------------------------------------

class TestMixedBatch:
    def test_only_fees_theme_enriched_in_mixed_list(self):
        """When both an Other theme and a fees theme appear in the same batch,
        only the fees theme should be enriched."""
        other_theme = _theme(name="Random other", category_key=OTHER_KEY, sentiment="NEGATIVE")
        fees_theme = _theme(name="High charges", category_key="fees", sentiment="NEGATIVE")
        mock_col = _fake_collection(top_distance=0.2)

        with (
            patch.object(fe_module, "_get_collection", return_value=mock_col),
            patch.object(fe_module, "_embed_query", return_value=[0.1] * 768),
            patch.object(fe_module, "_synthesise", return_value=_fake_synthesis()),
        ):
            result = fe_module.enrich_themes([other_theme, fees_theme], product="groww")

        other_result = next(t for t in result if t.name == "Random other")
        fees_result = next(t for t in result if t.name == "High charges")

        assert other_result.fee_explainer is None
        assert fees_result.fee_explainer is not None
