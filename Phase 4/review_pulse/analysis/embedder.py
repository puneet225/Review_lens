"""
Embedding generator using SentenceTransformers.

Wraps all-MiniLM-L6-v2 (384-dim) with:
  - Module-level model singleton (loaded once)
  - Batch encoding for memory efficiency
  - Graceful handling of empty review lists
"""

from __future__ import annotations

import logging
from typing import List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from sentence_transformers import SentenceTransformer as _STModel

from review_pulse.store.models import Review

logger = logging.getLogger(__name__)

_MODEL_CACHE: Optional["_STModel"] = None


def _get_model(model_name: str) -> "_STModel":
    """Load the SentenceTransformer model, caching it for the process lifetime."""
    global _MODEL_CACHE
    if _MODEL_CACHE is None:
        try:
            from sentence_transformers import SentenceTransformer
            logger.info("Loading embedding model: %s", model_name)
            _MODEL_CACHE = SentenceTransformer(model_name)
            logger.info("Embedding model loaded (dim=%d)", _MODEL_CACHE.get_sentence_embedding_dimension())
        except ImportError:
            raise ImportError(
                "sentence-transformers not installed. Run: pip install sentence-transformers"
            )
    return _MODEL_CACHE


def generate_embeddings(
    reviews: List[Review],
    model_name: str = "all-MiniLM-L6-v2",
    batch_size: int = 64,
) -> np.ndarray:
    """
    Generate sentence embeddings for a list of reviews.

    Args:
        reviews: List of Review objects (uses .body for embedding).
        model_name: SentenceTransformer model identifier.
        batch_size: Encoding batch size.

    Returns:
        Float32 numpy array of shape (len(reviews), embedding_dim).

    Raises:
        ValueError: If reviews list is empty.
        ImportError: If sentence-transformers is not installed.
    """
    if not reviews:
        raise ValueError("Cannot generate embeddings for an empty review list")

    import numpy as np

    texts = [r.body.strip() or r.title or "no content" for r in reviews]
    model = _get_model(model_name)

    logger.info("Encoding %d reviews (batch_size=%d)...", len(texts), batch_size)
    embeddings: np.ndarray = model.encode(
        texts,
        batch_size=batch_size,
        show_progress_bar=False,
        convert_to_numpy=True,
        normalize_embeddings=True,  # unit-norm for cosine similarity
    )

    logger.info("Embeddings shape: %s", embeddings.shape)
    return embeddings.astype(np.float32)
