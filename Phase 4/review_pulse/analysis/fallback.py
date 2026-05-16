"""
TF-IDF fallback analyser.

Used when UMAP/HDBSCAN fails (too few reviews, all noise, or library errors).
Groups reviews into N synthetic themes based on TF-IDF keyword extraction
and simple rating-based stratification.

Does NOT call the LLM — produces keyword-based theme names directly.
"""

from __future__ import annotations

import logging
from typing import Dict, List, Tuple

from review_pulse.store.models import Review, Theme

logger = logging.getLogger(__name__)

# Number of themes to create in fallback mode
_FALLBACK_THEMES = 3
# Top N keywords per theme
_TOP_KEYWORDS = 5
# Reviews per fallback theme (reviews are binned by rating)
_RATING_BINS: Dict[str, List[int]] = {
    "Positive": [4, 5],
    "Critical": [1, 2],
    "Mixed": [3],
}


def _tfidf_keywords(texts: List[str], top_n: int = 5) -> List[str]:
    """Extract top TF-IDF keywords from a list of texts."""
    if not texts:
        return []
    try:
        from sklearn.feature_extraction.text import TfidfVectorizer
        import numpy as np

        vectorizer = TfidfVectorizer(
            stop_words="english",
            max_features=100,
            ngram_range=(1, 2),
            min_df=1,
        )
        matrix = vectorizer.fit_transform(texts)
        feature_names = vectorizer.get_feature_names_out()
        # Sum TF-IDF scores across documents
        scores = np.asarray(matrix.sum(axis=0)).flatten()
        top_indices = scores.argsort()[::-1][:top_n]
        return [feature_names[i] for i in top_indices]
    except Exception as exc:
        logger.warning("TF-IDF keyword extraction failed: %s", exc)
        return []


def run_fallback(
    reviews: List[Review],
    max_themes: int = _FALLBACK_THEMES,
) -> Tuple[List[Theme], int]:
    """
    Produce synthetic themes using TF-IDF keyword extraction.

    Args:
        reviews: All ingested reviews.
        max_themes: Maximum number of themes to generate.

    Returns:
        Tuple of (list of Theme objects, noise_count).
        noise_count is always 0 for fallback (all reviews are assigned).
    """
    logger.info("Running TF-IDF fallback analyser on %d reviews", len(reviews))

    themes: List[Theme] = []

    # Bin by rating
    bins: Dict[str, List[Review]] = {label: [] for label in _RATING_BINS}
    for r in reviews:
        for label, ratings in _RATING_BINS.items():
            if r.rating in ratings:
                bins[label].append(r)
                break

    processed = 0
    for label, bin_reviews in bins.items():
        if not bin_reviews or processed >= max_themes:
            break

        texts = [r.body for r in bin_reviews if r.body.strip()]
        keywords = _tfidf_keywords(texts, top_n=_TOP_KEYWORDS)
        keyword_str = ", ".join(keywords[:3]) if keywords else "no keywords"

        name = f"{label} Feedback — {keyword_str}"[:60]
        description = (
            f"{len(bin_reviews)} reviews with ratings "
            f"{_RATING_BINS[label]} — top terms: {keyword_str}"
        )
        action = (
            "Review keyword clusters and address top recurring concerns "
            f"in {label.lower()} feedback."
        )

        themes.append(
            Theme(
                name=name,
                description=description,
                quotes=[],        # No LLM-validated quotes in fallback
                action=action,
                review_count=len(bin_reviews),
            )
        )
        processed += 1

    logger.info(
        "TF-IDF fallback produced %d themes (fallback_used=True)", len(themes)
    )
    return themes, 0
