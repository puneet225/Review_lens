"""
Phase 3 tests: Analysis & Clustering Engine.

All heavy ML libraries (sentence-transformers, umap-learn, hdbscan,
google-generativeai, numpy, scikit-learn) are mocked so tests run
offline without GPU, API keys, or installed ML packages.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import List
from unittest.mock import MagicMock, patch, ANY
import sys
import types

import pytest

# ---------------------------------------------------------------------------
# Stub numpy before any analysis imports attempt to use it in test fixtures
# ---------------------------------------------------------------------------
# If numpy is installed, great; if not, create a minimal stub that satisfies
# the test helper functions (which only create arrays for passing to mocks).
try:
    import numpy as np
except ModuleNotFoundError:
    # Build a minimal numpy stub that satisfies test fixture code
    class _FakeArray:
        def __init__(self, data):
            self._data = data
            if isinstance(data, list) and data and isinstance(data[0], list):
                self.shape = (len(data), len(data[0]))
            elif isinstance(data, list):
                self.shape = (len(data),)
            else:
                self.shape = ()

        def astype(self, dtype):
            return self  # no-op: tests just pass this to mocks

        def tolist(self):
            return self._data

        def __iter__(self):
            return iter(self._data)

        def __len__(self):
            return len(self._data) if isinstance(self._data, list) else 1

        def __getitem__(self, idx):
            return self._data[idx]

    def _fake_rand(*shape):
        if len(shape) == 2:
            return _FakeArray([[0.0] * shape[1]] * shape[0])
        return _FakeArray([0.0] * shape[0])

    def _fake_full(size, val):
        return _FakeArray([val] * size)

    def _fake_array(x, **k):
        return _FakeArray(x) if not isinstance(x, _FakeArray) else x

    np = types.ModuleType("numpy")
    np.ndarray = _FakeArray  # type: ignore[attr-defined]
    np.random = types.SimpleNamespace(rand=_fake_rand)  # type: ignore
    np.float32 = float  # type: ignore
    np.full = _fake_full  # type: ignore
    np.array = _fake_array  # type: ignore
    sys.modules["numpy"] = np  # type: ignore

from review_pulse.analysis.clusterer import ClusteringResult, cluster_reviews
from review_pulse.analysis.fallback import run_fallback
from review_pulse.analysis.pipeline import AnalysisError, run_analysis
from review_pulse.analysis.validator import validate_quote, validate_quotes
from review_pulse.agent.config import AnalysisConfig
from review_pulse.store.models import AnalysisResult, Review, Theme, ValidatedQuote


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_reviews(n: int = 20, source: str = "appstore") -> List[Review]:
    """Generate synthetic reviews for testing."""
    bodies = [
        "The app freezes exactly when the market opens, very frustrating.",
        "Support takes days to reply and doesn't solve the issue.",
        "Good for beginners but lacks detailed analysis tools.",
        "Login keeps timing out, have to restart the app constantly.",
        "UPI payments fail randomly without any error message.",
        "Charts are confusing and hard to read on smaller screens.",
        "Great overall experience, very smooth and intuitive.",
        "Portfolio view doesn't show unrealised gains correctly.",
        "The notification system is broken and delayed by hours.",
        "Customer care chat is unresponsive even on weekdays.",
    ]
    reviews = []
    for i in range(n):
        body = bodies[i % len(bodies)]
        reviews.append(
            Review(
                source=source,
                product="groww",
                rating=(i % 5) + 1,
                body=f"{body} (review {i})",
                raw_body=f"{body} (review {i})",
                date=datetime.utcnow() - timedelta(days=i),
                review_id=f"r{i}",
            )
        )
    return reviews


def _make_analysis_config(**overrides) -> AnalysisConfig:
    defaults = {
        "embedding_model": "all-MiniLM-L6-v2",
        "umap_n_components": 5,
        "umap_n_neighbors": 5,
        "umap_min_dist": 0.0,
        "umap_metric": "cosine",
        "hdbscan_min_cluster_size": 3,
        "hdbscan_min_samples": 2,
        "llm_model": "gemini-2.0-flash",
        "max_tokens_per_run": 50000,
        "max_themes": 5,
    }
    defaults.update(overrides)
    return AnalysisConfig(**defaults)


# ---------------------------------------------------------------------------
# Quote Validator Tests
# ---------------------------------------------------------------------------


class TestQuoteValidator:
    def _make_reviews_with_body(self, bodies: List[str]) -> List[Review]:
        return [
            Review(
                source="appstore", product="groww", rating=3,
                body=b, raw_body=b, date=datetime.utcnow(), review_id=f"r{i}"
            )
            for i, b in enumerate(bodies)
        ]

    def test_exact_match_returns_validated_quote(self) -> None:
        reviews = self._make_reviews_with_body([
            "The app freezes exactly when the market opens, very frustrating."
        ])
        vq = validate_quote("app freezes exactly when the market opens", reviews)
        assert vq is not None
        assert vq.text == "app freezes exactly when the market opens"
        assert vq.source_review_id == "r0"

    def test_hallucinated_quote_returns_none(self) -> None:
        reviews = self._make_reviews_with_body(["The app is great and fast."])
        vq = validate_quote("This text does not exist in any review whatsoever", reviews)
        assert vq is None

    def test_too_short_quote_rejected(self) -> None:
        reviews = self._make_reviews_with_body(["Short review text here"])
        vq = validate_quote("Short", reviews)  # < 15 chars
        assert vq is None

    def test_validate_quotes_returns_max(self) -> None:
        bodies = [
            "The app freezes exactly when the market opens, very frustrating.",
            "Support takes days to reply and doesn't solve the issue.",
            "Good for beginners but lacks detailed analysis tools.",
            "Login keeps timing out, have to restart the app constantly.",
        ]
        reviews = self._make_reviews_with_body(bodies)
        raw = [
            "app freezes exactly when the market opens",
            "Support takes days to reply",
            "lacks detailed analysis tools",
            "Login keeps timing out",
        ]
        result = validate_quotes(raw, reviews, max_quotes=3)
        assert len(result) <= 3
        assert all(isinstance(q, ValidatedQuote) for q in result)

    def test_validate_quotes_filters_hallucinated(self) -> None:
        reviews = self._make_reviews_with_body(["The app is smooth and responsive."])
        raw = [
            "app is smooth and responsive",         # valid
            "This quote was completely made up by the LLM",  # hallucinated
        ]
        result = validate_quotes(raw, reviews, max_quotes=3)
        assert len(result) == 1
        assert result[0].text == "app is smooth and responsive"

    def test_validate_quotes_no_duplicates_from_same_review(self) -> None:
        reviews = self._make_reviews_with_body(["The app freezes and crashes constantly during peak hours."])
        raw = [
            "app freezes and crashes constantly",
            "crashes constantly during peak hours",
        ]
        result = validate_quotes(raw, reviews, max_quotes=3)
        # Both match review r0 — only first should be kept
        assert len(result) == 1

    def test_empty_review_list_returns_none(self) -> None:
        vq = validate_quote("some valid looking quote text here", [])
        assert vq is None


# ---------------------------------------------------------------------------
# TF-IDF Fallback Tests
# ---------------------------------------------------------------------------


class TestFallback:
    def test_fallback_returns_themes(self) -> None:
        reviews = _make_reviews(30)
        themes, noise = run_fallback(reviews, max_themes=3)
        assert isinstance(themes, list)
        assert len(themes) > 0
        assert noise == 0

    def test_fallback_themes_are_theme_objects(self) -> None:
        reviews = _make_reviews(20)
        themes, _ = run_fallback(reviews)
        for t in themes:
            assert isinstance(t, Theme)
            assert t.name
            assert t.review_count > 0

    def test_fallback_respects_max_themes(self) -> None:
        reviews = _make_reviews(50)
        themes, _ = run_fallback(reviews, max_themes=2)
        assert len(themes) <= 2

    def test_fallback_empty_reviews(self) -> None:
        themes, noise = run_fallback([])
        assert themes == []
        assert noise == 0

    def test_fallback_rating_bins(self) -> None:
        """Positive and critical reviews should go into separate bins."""
        positive = [
            Review(
                source="appstore", product="groww", rating=5,
                body=f"Excellent smooth experience number {i}",
                raw_body=f"Excellent smooth experience number {i}",
                date=datetime.utcnow(), review_id=f"pos{i}"
            )
            for i in range(10)
        ]
        critical = [
            Review(
                source="playstore", product="groww", rating=1,
                body=f"App crashes frequently this is terrible {i}",
                raw_body=f"App crashes frequently this is terrible {i}",
                date=datetime.utcnow(), review_id=f"neg{i}"
            )
            for i in range(10)
        ]
        themes, _ = run_fallback(positive + critical, max_themes=3)
        theme_names = " ".join(t.name.lower() for t in themes)
        assert "positive" in theme_names or "critical" in theme_names


# ---------------------------------------------------------------------------
# HDBSCAN Clusterer Tests (mocked)
# ---------------------------------------------------------------------------


class TestClusterer:
    def _mock_hdbscan(self, labels):
        """Build a mock hdbscan module that returns the given labels."""
        import sys
        mock_module = MagicMock()
        mock_clusterer = MagicMock()
        mock_clusterer.fit_predict.return_value = labels
        mock_module.HDBSCAN.return_value = mock_clusterer
        return mock_module

    def test_clustering_result_structure(self) -> None:
        reviews = _make_reviews(20)
        reduced = np.random.rand(20, 5).astype(np.float32)

        # Simulate 2 clusters (labels 0 and 1), some noise (-1)
        labels_list = [-1, 0, 0, 1, 1, 0, 1, -1, 0, 1, 0, 1, 0, 1, 0, 1, 0, 1, -1, 0]
        mock_hdbscan = self._mock_hdbscan(labels_list)
        mock_np = MagicMock()
        mock_np.ndarray = object

        with patch.dict("sys.modules", {"hdbscan": mock_hdbscan, "numpy": mock_np}):
            # Patch numpy inside the clusterer call
            mock_np.return_value = labels_list
            result = cluster_reviews(reduced, reviews, min_cluster_size=3, min_samples=2)

        assert result.cluster_count == 2
        assert result.noise_count == 3
        assert not result.is_all_noise
        assert 0 in result.clusters
        assert 1 in result.clusters

    def test_all_noise_detected(self) -> None:
        reviews = _make_reviews(10)
        reduced = np.random.rand(10, 5).astype(np.float32)

        labels_list = [-1] * 10
        mock_hdbscan = self._mock_hdbscan(labels_list)
        mock_np = MagicMock()

        with patch.dict("sys.modules", {"hdbscan": mock_hdbscan, "numpy": mock_np}):
            result = cluster_reviews(reduced, reviews)

        assert result.is_all_noise
        assert result.cluster_count == 0

    def test_mismatched_lengths_raises(self) -> None:
        reviews = _make_reviews(10)
        reduced = np.random.rand(8, 5).astype(np.float32)  # wrong shape

        with pytest.raises(ValueError, match="same length"):
            # ValueError is raised before any library import
            cluster_reviews(reduced, reviews)


# ---------------------------------------------------------------------------
# Full Analysis Pipeline Tests (fully mocked)
# ---------------------------------------------------------------------------


class TestAnalysisPipeline:
    def test_raises_on_empty_reviews(self) -> None:
        config = _make_analysis_config()
        with pytest.raises(AnalysisError, match="No reviews"):
            run_analysis([], config)

    def test_fallback_when_embedding_fails(self) -> None:
        reviews = _make_reviews(20)
        config = _make_analysis_config()

        # Patch where the function is imported inside the pipeline try/except block
        with patch("review_pulse.analysis.pipeline.generate_embeddings", side_effect=ImportError("no lib")):
            result = run_analysis(reviews, config)

        assert isinstance(result, AnalysisResult)
        assert result.fallback_used is True
        assert result.total_reviews == 20

    def test_fallback_when_umap_fails(self) -> None:
        reviews = _make_reviews(20)
        config = _make_analysis_config()
        fake_embeddings = np.random.rand(20, 384).astype(np.float32)

        with patch("review_pulse.analysis.pipeline.generate_embeddings", return_value=fake_embeddings), \
             patch("review_pulse.analysis.pipeline.reduce_dimensions", side_effect=ImportError("no umap")):
            result = run_analysis(reviews, config)

        assert result.fallback_used is True

    def test_fallback_when_all_noise(self) -> None:
        reviews = _make_reviews(20)
        config = _make_analysis_config()
        fake_embeddings = np.random.rand(20, 384).astype(np.float32)
        fake_reduced = np.random.rand(20, 5).astype(np.float32)

        mock_cluster_result = MagicMock()
        mock_cluster_result.is_all_noise = True
        mock_cluster_result.noise_count = 20
        mock_cluster_result.clusters = {-1: reviews}

        # Patch all lazy-imported symbols
        with patch("review_pulse.analysis.pipeline.generate_embeddings", return_value=fake_embeddings), \
             patch("review_pulse.analysis.pipeline.reduce_dimensions", return_value=fake_reduced), \
             patch("review_pulse.analysis.pipeline.cluster_reviews", return_value=mock_cluster_result):
            result = run_analysis(reviews, config)

        assert result.fallback_used is True

    def test_full_pipeline_with_mocked_llm(self) -> None:
        """Happy path: embedding + clustering + LLM summarisation works end-to-end."""
        reviews = _make_reviews(20)
        config = _make_analysis_config()

        fake_embeddings = np.random.rand(20, 384).astype(np.float32)
        fake_reduced = np.random.rand(20, 5).astype(np.float32)

        mock_cluster_result = MagicMock()
        mock_cluster_result.is_all_noise = False
        mock_cluster_result.noise_count = 2
        cluster0 = reviews[:10]
        cluster1 = reviews[10:]
        mock_cluster_result.clusters = {0: cluster0, 1: cluster1}

        from review_pulse.analysis.summariser import SummaryResult

        # Build summaries with quotes that ARE real substrings
        def fake_summarise(cluster_id, reviews, **kwargs):
            sample_body = reviews[0].body
            # Use a real substring from the review body
            quote = sample_body[4:40] if len(sample_body) > 40 else sample_body
            return SummaryResult(
                cluster_id=cluster_id,
                name=f"Theme {cluster_id}",
                description="A real theme",
                raw_quotes=[quote],
                action="Fix this issue",
                tokens_used=500,
            )

        with patch("review_pulse.analysis.pipeline.generate_embeddings", return_value=fake_embeddings), \
             patch("review_pulse.analysis.pipeline.reduce_dimensions", return_value=fake_reduced), \
             patch("review_pulse.analysis.pipeline.cluster_reviews", return_value=mock_cluster_result), \
             patch("review_pulse.analysis.pipeline.summarise_cluster", side_effect=fake_summarise):
            result = run_analysis(reviews, config)

        assert isinstance(result, AnalysisResult)
        assert result.fallback_used is False
        assert len(result.themes) == 2
        assert result.total_reviews == 20
        assert result.tokens_used == 1000  # 2 clusters × 500

    def test_token_budget_enforced(self) -> None:
        """With a tiny token budget, only the first cluster is processed."""
        reviews = _make_reviews(20)
        config = _make_analysis_config(max_tokens_per_run=100)  # tiny budget

        fake_embeddings = np.random.rand(20, 384).astype(np.float32)
        fake_reduced = np.random.rand(20, 5).astype(np.float32)

        mock_cluster_result = MagicMock()
        mock_cluster_result.is_all_noise = False
        mock_cluster_result.noise_count = 0
        mock_cluster_result.clusters = {0: reviews[:5], 1: reviews[5:10], 2: reviews[10:]}

        from review_pulse.analysis.summariser import SummaryResult

        def fake_summarise_heavy(cluster_id, reviews, **kwargs):
            return SummaryResult(
                cluster_id=cluster_id,
                name=f"Theme {cluster_id}",
                raw_quotes=[],
                tokens_used=200,  # Each call costs 200 tokens
            )

        with patch("review_pulse.analysis.pipeline.generate_embeddings", return_value=fake_embeddings), \
             patch("review_pulse.analysis.pipeline.reduce_dimensions", return_value=fake_reduced), \
             patch("review_pulse.analysis.pipeline.cluster_reviews", return_value=mock_cluster_result), \
             patch("review_pulse.analysis.pipeline.summarise_cluster", side_effect=fake_summarise_heavy):
            result = run_analysis(reviews, config)

        assert result.is_partial is True
