"""
Fixed-category classifier.

Assigns each review to one of a small fixed taxonomy of aspect categories by
cosine similarity against per-category seed-phrase embeddings (max over seeds,
argmax over categories). Reviews matching no category fall to OTHER_KEY.

Embeddings are assumed unit-normalised (cosine == dot product).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Dict, List

from review_pulse.store.models import Review

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Category:
    key: str
    display_name: str
    seeds: tuple


DEFAULT_CATEGORIES: List[Category] = [
    Category("loved", "💚 What Users Love", (
        "easy to use", "clean and simple interface", "best investing app",
        "smooth experience", "user friendly", "love this app",
        "great for beginners", "good app",
    )),
    Category("bugs", "⚡ App Problems & Bugs", (
        "app keeps crashing", "full of bugs", "very slow and laggy",
        "app not working", "app freezes", "stopped working after update",
        "charts not loading", "technical glitch",
    )),
    Category("fees", "💸 Fees & Charges", (
        "high brokerage charges", "too many hidden charges", "expensive fees",
        "account maintenance charge", "DP charges", "charged extra money",
    )),
    Category("account", "🔐 Account, Funds & Support", (
        "KYC verification problem", "unable to login", "OTP not received",
        "withdrawal not working", "my money is stuck", "deposit failed",
        "no response from customer support", "account opening issue",
    )),
]

OTHER_KEY = "other"
OTHER_DISPLAY = "📦 Other"

_DISPLAY = {c.key: c.display_name for c in DEFAULT_CATEGORIES}
_DISPLAY[OTHER_KEY] = OTHER_DISPLAY


def display_name_for(key: str) -> str:
    return _DISPLAY.get(key, key)


def classify_reviews(
    reviews: List[Review],
    review_embeddings: "object",  # np.ndarray (n, dim), unit-normalised
    seed_embeddings: Dict[str, "object"],  # {key: np.ndarray (num_seeds, dim)}
    threshold: float,
    categories: List[Category] = DEFAULT_CATEGORIES,
) -> Dict[str, List[Review]]:
    """Group reviews by best-matching category key (or OTHER_KEY). Empty groups omitted."""
    import numpy as np

    grouped: Dict[str, List[Review]] = {}
    if not reviews:
        return grouped

    emb = np.asarray(review_embeddings)
    keys = [c.key for c in categories]
    scores = np.full((len(reviews), len(keys)), -1.0, dtype=np.float32)
    for j, key in enumerate(keys):
        seeds = np.asarray(seed_embeddings[key])
        sims = emb @ seeds.T  # (n, num_seeds)
        scores[:, j] = sims.max(axis=1)

    best_idx = scores.argmax(axis=1)
    best_score = scores.max(axis=1)

    for i, review in enumerate(reviews):
        if best_score[i] < threshold:
            grouped.setdefault(OTHER_KEY, []).append(review)
        else:
            grouped.setdefault(keys[int(best_idx[i])], []).append(review)
    return grouped


# Module-level reference so patch.object(classifier, "embed_texts") works in tests.
try:
    from review_pulse.analysis.embedder import embed_texts
except ImportError:  # pragma: no cover
    embed_texts = None  # type: ignore[assignment]


def group_by_category(
    reviews: List[Review],
    review_embeddings: "object",
    model_name: str,
    threshold: float,
    categories: List[Category] = DEFAULT_CATEGORIES,
) -> Dict[str, List[Review]]:
    """Embed category seeds, then classify reviews into the fixed taxonomy."""
    seed_embeddings: Dict[str, object] = {}
    for c in categories:
        seed_embeddings[c.key] = embed_texts(list(c.seeds), model_name=model_name)
    grouped = classify_reviews(reviews, review_embeddings, seed_embeddings, threshold, categories)
    logger.info(
        "Classified %d reviews into %d categories (other=%d)",
        len(reviews), len([k for k in grouped if k != OTHER_KEY]),
        len(grouped.get(OTHER_KEY, [])),
    )
    return grouped
