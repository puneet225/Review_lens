"""
HDBSCAN clusterer.

Groups reduced embeddings into clusters.
Returns a dict of {cluster_id: [Review]} with noise reviews
assigned to cluster label -1.

Handles the "all noise" edge case by triggering the fallback pipeline.
"""

from __future__ import annotations

import logging
from typing import Dict, List, Tuple

from review_pulse.store.models import Review

logger = logging.getLogger(__name__)


class ClusteringResult:
    """Output of the HDBSCAN clustering step."""

    def __init__(
        self,
        clusters: Dict[int, List[Review]],
        labels: np.ndarray,
        noise_count: int,
    ) -> None:
        self.clusters = clusters           # {cluster_id: [Review]}
        self.labels = labels               # raw HDBSCAN labels array
        self.noise_count = noise_count     # count of label == -1

    @property
    def cluster_count(self) -> int:
        """Number of real clusters (excludes noise cluster -1)."""
        return len([k for k in self.clusters if k != -1])

    @property
    def is_all_noise(self) -> bool:
        """True if HDBSCAN found no real clusters."""
        return self.cluster_count == 0


def cluster_reviews(
    reduced: np.ndarray,
    reviews: List[Review],
    min_cluster_size: int = 5,
    min_samples: int = 3,
) -> ClusteringResult:
    """
    Cluster reduced embeddings using HDBSCAN.

    Args:
        reduced: Float32 array of shape (n_reviews, n_components).
        reviews: List of Review objects (same order as reduced rows).
        min_cluster_size: HDBSCAN min_cluster_size.
        min_samples: HDBSCAN min_samples.

    Returns:
        ClusteringResult with cluster assignments.

    Raises:
        ImportError: If hdbscan is not installed.
        ValueError: If len(reviews) != reduced.shape[0].
    """
    if len(reviews) != reduced.shape[0]:
        raise ValueError(
            f"reviews ({len(reviews)}) and reduced embeddings ({reduced.shape[0]}) must have the same length"
        )

    # Clamp parameters to valid ranges
    effective_min_cluster = min(min_cluster_size, max(2, len(reviews) // 4))
    effective_min_samples = min(min_samples, effective_min_cluster)

    try:
        import hdbscan
        import numpy as np
    except ImportError as e:
        raise ImportError(f"Missing ML library: {e}. Run: pip install hdbscan numpy")

    logger.info(
        "Running HDBSCAN: %d samples, min_cluster_size=%d, min_samples=%d",
        len(reviews),
        effective_min_cluster,
        effective_min_samples,
    )

    clusterer = hdbscan.HDBSCAN(
        min_cluster_size=effective_min_cluster,
        min_samples=effective_min_samples,
        metric="euclidean",
        cluster_selection_method="eom",
        prediction_data=False,
    )
    labels: np.ndarray = clusterer.fit_predict(reduced)

    # Group reviews by cluster
    clusters: Dict[int, List[Review]] = {}
    for label, review in zip(list(labels), reviews):
        clusters.setdefault(label, []).append(review)

    noise_count = len(clusters.get(-1, []))
    real_clusters = {k: v for k, v in clusters.items() if k != -1}
    n_clusters = len(real_clusters)

    logger.info(
        "HDBSCAN result: %d clusters, %d noise points",
        n_clusters,
        noise_count,
    )

    return ClusteringResult(clusters=clusters, labels=labels, noise_count=noise_count)
