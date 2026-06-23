"""
Analysis pipeline — orchestrates the full analysis flow:

  Reviews
    → Embedder      (all-MiniLM-L6-v2, 384-dim)
    → UMAP Reducer  (384-dim → 15-dim)
    → HDBSCAN       (cluster labels)
    → Gemini LLM    (theme name, description, quotes, action per cluster)
    → Validator     (exact-substring quote check)
    → AnalysisResult

Falls back to TF-IDF when:
  - Too few reviews for UMAP / HDBSCAN
  - All reviews are HDBSCAN noise
  - Heavy library import errors

Entry point: run_analysis(reviews, config) -> AnalysisResult
"""

from __future__ import annotations

import logging
from typing import List, Optional

from review_pulse.agent.config import AnalysisConfig
from review_pulse.analysis.fallback import run_fallback
from review_pulse.analysis.fee_explainer import enrich_themes
from review_pulse.analysis.validator import validate_quotes
from review_pulse.store.models import AnalysisResult, Review, Theme

# ---------------------------------------------------------------------------
# Lazy top-level imports — allows patch() to intercept in tests.
# Each raises ImportError at call-time if the library is missing.
# ---------------------------------------------------------------------------
try:
    from review_pulse.analysis.embedder import generate_embeddings
except Exception:
    def generate_embeddings(*a, **k):  # type: ignore[misc]
        raise ImportError("sentence-transformers not installed")

try:
    from review_pulse.analysis.summariser import summarise_cluster
except Exception:
    def summarise_cluster(*a, **k):  # type: ignore[misc]
        raise ImportError("google-generativeai not installed")

try:
    from review_pulse.analysis.classifier import group_by_category, display_name_for, OTHER_KEY
except Exception:
    OTHER_KEY = "other"
    def display_name_for(key):  # type: ignore[misc]
        return key
    def group_by_category(*a, **k):  # type: ignore[misc]
        raise ImportError("classifier unavailable")

logger = logging.getLogger(__name__)


class AnalysisError(Exception):
    """Raised when analysis fails completely (not just fallback triggered)."""


def run_analysis(
    reviews: List[Review],
    config: AnalysisConfig,
    product: Optional[str] = None,
) -> AnalysisResult:
    """
    Run the full analysis pipeline for a list of ingested reviews.

    Args:
        reviews: Deduplicated, PII-scrubbed reviews from ingestion pipeline.
        config: Analysis configuration (model names, UMAP/HDBSCAN params, LLM settings).
        product: Product slug, used to look up data/fee_facts/{product}.yaml for
            the Fee Explainer enrichment. If None, fee enrichment is skipped.

    Returns:
        AnalysisResult with themes, quotes, and metadata.
    """
    if not reviews:
        raise AnalysisError("No reviews to analyse")

    total_reviews = len(reviews)
    logger.info("Starting analysis pipeline on %d reviews", total_reviews)

    # -----------------------------------------------------------------------
    # STEP 1: Embedding
    # -----------------------------------------------------------------------
    try:
        embeddings = generate_embeddings(reviews, model_name=config.embedding_model)
    except (ImportError, Exception) as exc:
        logger.warning("Embedding step failed (%s) — activating TF-IDF fallback", exc)
        themes, noise_count = run_fallback(reviews, max_themes=config.max_themes)
        return AnalysisResult(
            themes=themes,
            total_reviews=total_reviews,
            noise_count=noise_count,
            tokens_used=0,
            fallback_used=True,
        )

    # -----------------------------------------------------------------------
    # STEP 2: Classify reviews into the fixed category taxonomy
    # -----------------------------------------------------------------------
    grouped: dict = {}
    try:
        grouped = group_by_category(
            reviews,
            embeddings,
            model_name=config.embedding_model,
            threshold=config.category_match_threshold,
        )
    except (ImportError, Exception) as exc:
        logger.warning("Classification failed (%s) — activating TF-IDF fallback", exc)

    if not grouped:
        themes, _ = run_fallback(reviews, max_themes=config.max_themes)
        return AnalysisResult(
            themes=themes,
            total_reviews=total_reviews,
            noise_count=0,
            tokens_used=0,
            fallback_used=True,
        )

    noise_count = len(grouped.get(OTHER_KEY, []))

    # Order: real categories by size desc, then Other last.
    non_other = [(k, v) for k, v in grouped.items() if k != OTHER_KEY]
    non_other.sort(key=lambda kv: len(kv[1]), reverse=True)
    ordered = non_other + ([(OTHER_KEY, grouped[OTHER_KEY])] if OTHER_KEY in grouped else [])
    top_categories = ordered[: config.max_themes]

    # -----------------------------------------------------------------------
    # STEP 3: LLM summarisation per category
    # -----------------------------------------------------------------------
    themes: List[Theme] = []
    total_tokens = 0
    tokens_remaining = config.max_tokens_per_run
    is_partial = False

    for category_key, category_reviews in top_categories:
        if tokens_remaining <= 0:
            logger.warning("Token budget exhausted after %d themes", len(themes))
            is_partial = True
            break

        display_name = display_name_for(category_key)
        summary = summarise_cluster(
            reviews=category_reviews,
            fixed_name=display_name,
            model_name=config.llm_model,
            token_budget_remaining=tokens_remaining,
        )

        tokens_remaining -= summary.tokens_used
        total_tokens += summary.tokens_used

        validated_quotes = validate_quotes(
            raw_quotes=summary.raw_quotes,
            reviews=category_reviews,
            max_quotes=3,
        )

        themes.append(
            Theme(
                name=display_name,
                description=summary.description,
                sentiment=summary.sentiment,
                quotes=validated_quotes,
                action=summary.action,
                review_count=len(category_reviews),
                category_key=category_key,
            )
        )

    # -----------------------------------------------------------------------
    # STEP 6: Fee Explainer enrichment (curated, never LLM-generated text)
    # -----------------------------------------------------------------------
    if product:
        try:
            enrich_themes(themes, product)
        except Exception as exc:
            logger.warning("Fee explainer enrichment failed (%s) — continuing without it", exc)

    logger.info(
        "Analysis complete: %d themes, %d total tokens, fallback=%s, partial=%s",
        len(themes),
        total_tokens,
        False,
        is_partial,
    )

    return AnalysisResult(
        themes=themes,
        total_reviews=total_reviews,
        noise_count=noise_count,
        tokens_used=total_tokens,
        is_partial=is_partial,
        fallback_used=False,
    )
