"""
UMAP dimensionality reducer.

Reduces high-dimensional embeddings (384-dim) to a lower-dimensional
space (default 15-dim) suitable for HDBSCAN clustering.

Handles the case where too few samples exist for UMAP
(must have at least n_neighbors + 1 samples).
"""

from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)

# Minimum samples needed to run UMAP (must exceed n_neighbors)
_MIN_SAMPLES_FOR_UMAP = 2


def reduce_dimensions(
    embeddings: np.ndarray,
    n_components: int = 15,
    n_neighbors: int = 20,
    min_dist: float = 0.0,
    metric: str = "cosine",
    random_state: int = 42,
) -> Optional[np.ndarray]:
    """
    Reduce embedding dimensionality using UMAP.

    Args:
        embeddings: Float32 array of shape (n_reviews, embed_dim).
        n_components: Target dimensionality.
        n_neighbors: UMAP n_neighbors parameter.
        min_dist: UMAP min_dist parameter.
        metric: Distance metric.
        random_state: For reproducibility.

    Returns:
        Reduced array of shape (n_reviews, n_components), or None if
        there are too few samples to run UMAP.

    Raises:
        ImportError: If umap-learn is not installed.
    """
    n_samples = embeddings.shape[0]

    # Clamp n_neighbors to avoid UMAP error: n_neighbors must be < n_samples
    effective_neighbors = min(n_neighbors, n_samples - 1)

    if n_samples < _MIN_SAMPLES_FOR_UMAP or effective_neighbors < 2:
        logger.warning(
            "Too few samples (%d) for UMAP (need ≥ %d). Skipping dimensionality reduction.",
            n_samples,
            _MIN_SAMPLES_FOR_UMAP,
        )
        return None

    try:
        import umap
        import numpy as _np
    except ImportError as e:
        raise ImportError(f"Missing ML library: {e}. Run: pip install umap-learn numpy")

    # Use _np alias so type checkers don't complain about the dynamic import
    np = _np

    logger.info(
        "Running UMAP: %d samples, %d→%d dims, n_neighbors=%d",
        n_samples,
        embeddings.shape[1],
        n_components,
        effective_neighbors,
    )

    reducer = umap.UMAP(
        n_components=n_components,
        n_neighbors=effective_neighbors,
        min_dist=min_dist,
        metric=metric,
        random_state=random_state,
        low_memory=False,
    )
    reduced: np.ndarray = reducer.fit_transform(embeddings)
    logger.info("UMAP done: output shape %s", reduced.shape)
    return reduced.astype(np.float32)
