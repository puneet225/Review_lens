from unittest.mock import MagicMock, patch
import pytest


def test_embed_texts_encodes_and_returns_array():
    import numpy as np
    from review_pulse.analysis import embedder

    fake_model = MagicMock()
    fake_model.encode.return_value = np.array([[1.0, 0.0], [0.0, 1.0]], dtype=np.float32)

    with patch.object(embedder, "_get_model", return_value=fake_model):
        out = embedder.embed_texts(["hello", "world"], model_name="all-MiniLM-L6-v2")

    fake_model.encode.assert_called_once()
    assert out.shape == (2, 2)


def test_embed_texts_empty_raises():
    from review_pulse.analysis import embedder
    with pytest.raises(ValueError):
        embedder.embed_texts([])
