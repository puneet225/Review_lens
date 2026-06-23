from datetime import datetime

import numpy as np

from review_pulse.analysis.classifier import (
    DEFAULT_CATEGORIES,
    OTHER_KEY,
    classify_reviews,
    display_name_for,
)
from review_pulse.store.models import Review


def _r(body: str, i: int) -> Review:
    return Review(source="appstore", product="groww", rating=3,
                  body=body, raw_body=body, date=datetime.utcnow(), review_id=f"r{i}")


def test_default_taxonomy_has_four_categories_with_display_names():
    keys = [c.key for c in DEFAULT_CATEGORIES]
    assert keys == ["loved", "bugs", "fees", "account"]
    assert display_name_for("fees") == "💸 Fees & Charges"
    assert display_name_for(OTHER_KEY) == "📦 Other"


def test_assigns_each_review_to_nearest_category():
    reviews = [_r("a", 0), _r("b", 1)]
    # dim=3 unit vectors; review 0 aligns with cat A axis, review 1 with cat B axis
    review_emb = np.array([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]], dtype=np.float32)
    seed_emb = {
        "loved": np.array([[1.0, 0.0, 0.0]], dtype=np.float32),
        "bugs": np.array([[0.0, 1.0, 0.0]], dtype=np.float32),
        "fees": np.array([[0.0, 0.0, 1.0]], dtype=np.float32),
        "account": np.array([[0.0, 0.0, 1.0]], dtype=np.float32),
    }
    grouped = classify_reviews(reviews, review_emb, seed_emb, threshold=0.3)
    assert grouped["loved"][0].review_id == "r0"
    assert grouped["bugs"][0].review_id == "r1"
    assert OTHER_KEY not in grouped


def test_below_threshold_goes_to_other():
    reviews = [_r("x", 0)]
    review_emb = np.array([[0.0, 0.0, 1.0]], dtype=np.float32)  # orthogonal to all seeds
    seed_emb = {
        "loved": np.array([[1.0, 0.0, 0.0]], dtype=np.float32),
        "bugs": np.array([[0.0, 1.0, 0.0]], dtype=np.float32),
        "fees": np.array([[1.0, 0.0, 0.0]], dtype=np.float32),
        "account": np.array([[0.0, 1.0, 0.0]], dtype=np.float32),
    }
    grouped = classify_reviews(reviews, review_emb, seed_emb, threshold=0.3)
    assert grouped[OTHER_KEY][0].review_id == "r0"
    assert "loved" not in grouped


def test_tie_resolves_to_first_category_in_order():
    reviews = [_r("y", 0)]
    review_emb = np.array([[1.0, 0.0]], dtype=np.float32)
    seed_emb = {
        "loved": np.array([[1.0, 0.0]], dtype=np.float32),   # tie
        "bugs": np.array([[1.0, 0.0]], dtype=np.float32),    # tie
        "fees": np.array([[0.0, 1.0]], dtype=np.float32),
        "account": np.array([[0.0, 1.0]], dtype=np.float32),
    }
    grouped = classify_reviews(reviews, review_emb, seed_emb, threshold=0.3)
    assert "loved" in grouped and "bugs" not in grouped


def test_empty_reviews_returns_empty_dict():
    assert classify_reviews([], np.zeros((0, 3), dtype=np.float32), {}, threshold=0.3) == {}


def test_group_by_category_embeds_seeds_then_classifies():
    from unittest.mock import patch
    import numpy as np
    from review_pulse.analysis import classifier

    reviews = [_r("loved it", 0), _r("buggy", 1)]
    review_emb = np.array([[1.0, 0.0], [0.0, 1.0]], dtype=np.float32)

    # Every seed for 'loved' aligns to axis0, every other category to axis1.
    def fake_embed_texts(texts, model_name="x", batch_size=64):
        # Called once per category, in DEFAULT_CATEGORIES order.
        return np.tile(fake_embed_texts.axis.pop(0), (len(texts), 1)).astype(np.float32)
    fake_embed_texts.axis = [
        np.array([1.0, 0.0]),  # loved
        np.array([0.0, 1.0]),  # bugs
        np.array([0.0, 1.0]),  # fees
        np.array([0.0, 1.0]),  # account
    ]

    with patch.object(classifier, "embed_texts", create=True, side_effect=fake_embed_texts), \
         patch("review_pulse.analysis.embedder.embed_texts", side_effect=fake_embed_texts):
        grouped = classifier.group_by_category(reviews, review_emb, model_name="x", threshold=0.3)

    assert grouped["loved"][0].review_id == "r0"
    assert grouped["bugs"][0].review_id == "r1"
