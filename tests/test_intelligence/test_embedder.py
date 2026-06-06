"""Tests for ProjectOS embedding abstractions."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any
from unittest.mock import patch

from core.intelligence.embedder import (
    DEFAULT_TFIDF_VOCAB_SIZE,
    EmbedderFactory,
    GeminiEmbedder,
    TFIDFEmbedder,
)


def test_tfidf_embed_returns_correct_dimension(tmp_path: Path) -> None:
    """Verify TF-IDF embeddings use the configured dimension."""
    embedder = TFIDFEmbedder(vocab_size=16, state_dir=tmp_path)

    vector = embedder.embed("alpha beta beta")

    assert len(vector) == 16


def test_tfidf_embed_batch_consistent_with_single(tmp_path: Path) -> None:
    """Verify batch and single embedding match for equivalent initial state."""
    text = "alpha beta gamma"
    single_embedder = TFIDFEmbedder(vocab_size=16, state_dir=tmp_path / "single")
    batch_embedder = TFIDFEmbedder(vocab_size=16, state_dir=tmp_path / "batch")

    single_vector = single_embedder.embed(text)
    batch_vector = batch_embedder.embed_batch([text])[0]

    assert batch_vector == single_vector


def test_tfidf_zero_vector_never_raised_on_empty_input(tmp_path: Path) -> None:
    """Verify empty text returns a zero vector instead of raising."""
    embedder = TFIDFEmbedder(vocab_size=8, state_dir=tmp_path)

    vector = embedder.embed("")

    assert vector == [0.0] * 8


def test_tfidf_vocab_saved_and_loaded(tmp_path: Path) -> None:
    """Verify TF-IDF vocabulary persists across embedder instances."""
    first_embedder = TFIDFEmbedder(vocab_size=16, state_dir=tmp_path)
    first_embedder.embed("persisted token")

    second_embedder = TFIDFEmbedder(vocab_size=16, state_dir=tmp_path)

    assert "persisted" in second_embedder.vocabulary
    assert "token" in second_embedder.vocabulary


@patch.dict(os.environ, {}, clear=True)
def test_gemini_embedder_falls_back_on_missing_key(tmp_path: Path) -> None:
    """Verify direct Gemini usage falls back locally without an API key."""
    embedder = GeminiEmbedder(dimension=16)

    vector = embedder.embed("local fallback text")

    assert len(vector) == 16
    assert any(value != 0.0 for value in vector)


@patch.dict(os.environ, {"GEMINI_API_KEY": "fake-key"}, clear=True)
@patch("core.intelligence.embedder.requests.post")
def test_gemini_embedder_returns_zero_vector_on_http_error(post_mock: Any) -> None:
    """Verify HTTP errors never escape Gemini embedding calls."""
    post_mock.side_effect = RuntimeError("network unavailable")
    embedder = GeminiEmbedder(dimension=12)

    vector = embedder.embed("remote text")

    assert vector == [0.0] * 12


@patch.dict(os.environ, {}, clear=True)
def test_embedder_factory_returns_tfidf_without_api_key(tmp_path: Path) -> None:
    """Verify the factory chooses TF-IDF when Gemini is not configured."""
    embedder = EmbedderFactory.create(tmp_path)

    assert isinstance(embedder, TFIDFEmbedder)
    assert embedder.get_dimension() == DEFAULT_TFIDF_VOCAB_SIZE
