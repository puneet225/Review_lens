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
    from review_pulse.analysis.reducer import reduce_dimensions
except Exception:
    def reduce_dimensions(*a, **k):  # type: ignore[misc]
        raise ImportError("umap-learn not installed")

try:
    from review_pulse.analysis.clusterer import cluster_reviews
except Exception:
    def cluster_reviews(*a, **k):  # type: ignore[misc]
        raise ImportError("hdbscan not installed")

try:
    from review_pulse.analysis.summariser import summarise_cluster
except Exception:
    def summarise_cluster(*a, **k):  # type: ignore[misc]
        raise ImportError("google-generativeai not installed")

logger = logging.getLogger(__name__)

# Minimum reviews required to attempt embedding + clustering
_MIN_REVIEWS_FOR_CLUSTERING = 10


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
    # STEP 2: UMAP dimensionality reduction
    # -----------------------------------------------------------------------
    reduced = None
    if total_reviews >= _MIN_REVIEWS_FOR_CLUSTERING:
        try:
            reduced = reduce_dimensions(
                embeddings,
                n_components=config.umap_n_components,
                n_neighbors=config.umap_n_neighbors,
                min_dist=config.umap_min_dist,
                metric=config.umap_metric,
            )
        except (ImportError, Exception) as exc:
            logger.warning("UMAP step failed (%s) — will skip to fallback", exc)
    else:
        logger.info(
            "Only %d reviews — skipping UMAP/HDBSCAN (need ≥ %d)",
            total_reviews,
            _MIN_REVIEWS_FOR_CLUSTERING,
        )

    # -----------------------------------------------------------------------
    # STEP 3: HDBSCAN clustering
    # -----------------------------------------------------------------------
    cluster_map: dict = {}
    fallback_used = False
    noise_count = 0

    if reduced is not None:
        try:
            clustering_result = cluster_reviews(
                reduced,
                reviews,
                min_cluster_size=config.hdbscan_min_cluster_size,
                min_samples=config.hdbscan_min_samples,
            )
            noise_count = clustering_result.noise_count

            if clustering_result.is_all_noise:
                logger.warning("HDBSCAN found no clusters — all noise. Activating fallback.")
                fallback_used = True
            else:
                cluster_map = {k: v for k, v in clustering_result.clusters.items() if k != -1}
                logger.info("Using %d HDBSCAN clusters for LLM summarisation", len(cluster_map))
        except (ImportError, Exception) as exc:
            logger.warning("HDBSCAN step failed (%s) — activating fallback", exc)
            fallback_used = True
    else:
        fallback_used = True

    # -----------------------------------------------------------------------
    # STEP 4a: Fallback (TF-IDF)
    # -----------------------------------------------------------------------
    if fallback_used or not cluster_map:
        themes, _ = run_fallback(reviews, max_themes=config.max_themes)
        return AnalysisResult(
            themes=themes,
            total_reviews=total_reviews,
            noise_count=noise_count,
            tokens_used=0,
            fallback_used=True,
        )

    # -----------------------------------------------------------------------
    # STEP 4b: LLM summarisation per cluster
    # -----------------------------------------------------------------------

    # Sort clusters by size descending, take top max_themes
    sorted_clusters = sorted(cluster_map.items(), key=lambda kv: len(kv[1]), reverse=True)
    top_clusters = sorted_clusters[: config.max_themes]

    themes: List[Theme] = []
    total_tokens = 0
    tokens_remaining = config.max_tokens_per_run
    is_partial = False

    for cluster_id, cluster_review_list in top_clusters:
        if tokens_remaining <= 0:
            logger.warning("Token budget exhausted after %d themes", len(themes))
            is_partial = True
            break

        summary = summarise_cluster(
            cluster_id=cluster_id,
            reviews=cluster_review_list,
            model_name=config.llm_model,
            token_budget_remaining=tokens_remaining,
            existing_theme_names=[t.name for t in themes],
        )

        tokens_remaining -= summary.tokens_used
        total_tokens += summary.tokens_used

        # -------------------------------------------------------------------
        # STEP 5: Quote validation
        # -------------------------------------------------------------------
        validated_quotes = validate_quotes(
            raw_quotes=summary.raw_quotes,
            reviews=cluster_review_list,
            max_quotes=3,
        )

        themes.append(
            Theme(
                name=summary.name,
                description=summary.description,
                sentiment=summary.sentiment,
                quotes=validated_quotes,
                action=summary.action,
                review_count=len(cluster_review_list),
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
        fallback_used,
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
