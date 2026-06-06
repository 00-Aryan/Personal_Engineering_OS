"""Embedding provider abstractions for ProjectOS intelligence features."""

from __future__ import annotations

import json
import logging
import math
import os
import re
import tempfile
from abc import ABC, abstractmethod
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests


ENCODING = "utf-8"
STATE_DIR_NAME = ".projectos_state"
TFIDF_VOCAB_FILE_NAME = "tfidf_vocab.json"
GEMINI_API_KEY_ENV = "GEMINI_API_KEY"
GEMINI_EMBEDDING_MODEL = "text-embedding-004"
GEMINI_EMBEDDING_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    f"{GEMINI_EMBEDDING_MODEL}:embedContent"
)
GEMINI_REQUEST_TIMEOUT_SECONDS = 30
DEFAULT_GEMINI_DIMENSION = 768
DEFAULT_TFIDF_VOCAB_SIZE = 512
MIN_VECTOR_NORM = 0.0
TFIDF_EMBEDDER_NAME = "tfidf"
GEMINI_EMBEDDER_NAME = f"gemini:{GEMINI_EMBEDDING_MODEL}"
GEMINI_FALLBACK_STATE_DIR_NAME = "projectos_gemini_fallback"

logger = logging.getLogger(__name__)


class BaseEmbedder(ABC):
    """Abstract embedding interface with swappable implementations."""

    @abstractmethod
    def embed(self, text: str) -> List[float]:
        """Convert text to a dense vector without raising."""

    @abstractmethod
    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        """Convert multiple texts to dense vectors."""

    @abstractmethod
    def get_dimension(self) -> int:
        """Return the stable embedding dimension for this instance."""

    @abstractmethod
    def get_embedder_name(self) -> str:
        """Return an identifier suitable for logs and compatibility checks."""


class GeminiEmbedder(BaseEmbedder):
    """Gemini embedding provider with TF-IDF fallback when no key is present."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        dimension: int = DEFAULT_GEMINI_DIMENSION,
    ) -> None:
        """Initialize Gemini credentials and local fallback embedder."""
        self.api_key = api_key or os.environ.get(GEMINI_API_KEY_ENV)
        self.dimension = dimension
        fallback_state_dir = Path(tempfile.gettempdir()) / GEMINI_FALLBACK_STATE_DIR_NAME
        self.fallback_embedder = TFIDFEmbedder(
            vocab_size=dimension,
            state_dir=fallback_state_dir,
        )
        if not self.api_key:
            logger.warning("GEMINI_API_KEY not set; GeminiEmbedder using TF-IDF fallback.")

    def embed(self, text: str) -> List[float]:
        """Return a Gemini embedding, falling back or zeroing on errors."""
        if not self.api_key:
            return self.fallback_embedder.embed(text)

        try:
            response = requests.post(
                GEMINI_EMBEDDING_URL,
                params={"key": self.api_key},
                json=self._payload(text),
                timeout=GEMINI_REQUEST_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            values = response.json().get("embedding", {}).get("values", [])
            if not isinstance(values, list):
                return self._zero_vector()
            return self._fixed_dimension([float(value) for value in values])
        except Exception as exc:
            logger.warning("Gemini embedding failed; returning zero vector: %s", exc)
            return self._zero_vector()

    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        """Embed each text individually because Gemini has no free batch endpoint."""
        return [self.embed(text) for text in texts]

    def get_dimension(self) -> int:
        """Return Gemini embedding dimension."""
        return self.dimension

    def get_embedder_name(self) -> str:
        """Return the Gemini embedder identifier."""
        return GEMINI_EMBEDDER_NAME

    def _payload(self, text: str) -> Dict[str, Any]:
        """Build a Gemini embedding request payload."""
        return {
            "model": f"models/{GEMINI_EMBEDDING_MODEL}",
            "content": {"parts": [{"text": text or ""}]},
        }

    def _fixed_dimension(self, values: List[float]) -> List[float]:
        """Pad or truncate a provider response to the configured dimension."""
        if len(values) >= self.dimension:
            return values[: self.dimension]
        return values + [0.0] * (self.dimension - len(values))

    def _zero_vector(self) -> List[float]:
        """Return a zero vector matching this instance dimension."""
        return [0.0] * self.dimension


class TFIDFEmbedder(BaseEmbedder):
    """Zero-dependency TF-IDF fallback embedder with persisted vocabulary."""

    def __init__(
        self,
        vocab_size: int = DEFAULT_TFIDF_VOCAB_SIZE,
        state_dir: Optional[Path] = None,
    ) -> None:
        """Load vocabulary state and prepare the fallback embedder."""
        self.vocab_size = vocab_size
        self.state_dir = Path(state_dir) if state_dir else Path(STATE_DIR_NAME)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.vocab_path = self.state_dir / TFIDF_VOCAB_FILE_NAME
        self.vocabulary: Dict[str, int] = {}
        self.document_frequency: Dict[str, int] = {}
        self.document_count = 0
        if self.vocab_path.exists():
            self.load_vocab(self.vocab_path)

    def embed(self, text: str) -> List[float]:
        """Return a normalized TF-IDF vector for one text without raising."""
        try:
            tokens = self._tokenize(text)
            if not tokens:
                return self._zero_vector()
            self._learn_documents([tokens])
            return self._vectorize(tokens)
        except Exception as exc:
            logger.warning("TF-IDF embedding failed; returning zero vector: %s", exc)
            return self._zero_vector()

    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        """Learn a joint vocabulary first, then embed each text."""
        try:
            tokenized_texts = [self._tokenize(text) for text in texts]
            non_empty_texts = [tokens for tokens in tokenized_texts if tokens]
            if non_empty_texts:
                self._learn_documents(non_empty_texts)
            return [
                self._vectorize(tokens) if tokens else self._zero_vector()
                for tokens in tokenized_texts
            ]
        except Exception as exc:
            logger.warning("TF-IDF batch embedding failed; returning zeros: %s", exc)
            return [self._zero_vector() for _ in texts]

    def get_dimension(self) -> int:
        """Return configured vocabulary vector size."""
        return self.vocab_size

    def get_embedder_name(self) -> str:
        """Return the TF-IDF embedder identifier."""
        return TFIDF_EMBEDDER_NAME

    def save_vocab(self, path: Path) -> None:
        """Persist vocabulary state with an atomic file replacement."""
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "vocab_size": self.vocab_size,
            "vocabulary": self.vocabulary,
            "document_frequency": self.document_frequency,
            "document_count": self.document_count,
        }
        _write_text_atomically(path, json.dumps(payload, sort_keys=True))

    def load_vocab(self, path: Path) -> None:
        """Load vocabulary state from disk if it is valid."""
        payload = json.loads(path.read_text(encoding=ENCODING))
        vocabulary = payload.get("vocabulary", {})
        document_frequency = payload.get("document_frequency", {})
        if isinstance(vocabulary, dict) and isinstance(document_frequency, dict):
            self.vocabulary = {
                str(token): int(index)
                for token, index in vocabulary.items()
                if int(index) < self.vocab_size
            }
            self.document_frequency = {
                str(token): int(count)
                for token, count in document_frequency.items()
                if str(token) in self.vocabulary
            }
            self.document_count = int(payload.get("document_count", 0))

    def _learn_documents(self, tokenized_texts: List[List[str]]) -> None:
        """Update vocabulary and document frequency from tokenized documents."""
        changed = False
        for tokens in tokenized_texts:
            for token in tokens:
                if len(self.vocabulary) >= self.vocab_size:
                    break
                if token not in self.vocabulary:
                    self.vocabulary[token] = len(self.vocabulary)
                    changed = True

            known_unique_tokens = set(tokens).intersection(self.vocabulary)
            for token in known_unique_tokens:
                self.document_frequency[token] = self.document_frequency.get(token, 0) + 1
                changed = True
            self.document_count += 1
            changed = True

        if changed:
            self.save_vocab(self.vocab_path)

    def _tokenize(self, text: str) -> List[str]:
        """Split text into lowercase alphanumeric tokens."""
        return re.findall(r"[a-z0-9]+", text.lower())

    def _vectorize(self, tokens: List[str]) -> List[float]:
        """Build a normalized TF-IDF vector from existing vocabulary state."""
        vector = [0.0] * self.vocab_size
        token_counts = Counter(token for token in tokens if token in self.vocabulary)
        if not token_counts:
            return vector

        total_tokens = sum(token_counts.values())
        for token, count in token_counts.items():
            index = self.vocabulary[token]
            term_frequency = count / total_tokens
            document_frequency = self.document_frequency.get(token, 0)
            inverse_document_frequency = (
                math.log((1 + self.document_count) / (1 + document_frequency)) + 1
            )
            vector[index] = term_frequency * inverse_document_frequency

        norm = math.sqrt(sum(value * value for value in vector))
        if norm <= MIN_VECTOR_NORM:
            return self._zero_vector()
        return [value / norm for value in vector]

    def _zero_vector(self) -> List[float]:
        """Return a zero vector matching the configured dimension."""
        return [0.0] * self.vocab_size


class EmbedderFactory:
    """Create the best available embedder for the current environment."""

    @staticmethod
    def create(state_dir: Path) -> BaseEmbedder:
        """Return Gemini when configured, otherwise local TF-IDF."""
        if os.environ.get(GEMINI_API_KEY_ENV):
            logger.info("Selected GeminiEmbedder because GEMINI_API_KEY is set.")
            return GeminiEmbedder()
        logger.info("Selected TFIDFEmbedder because GEMINI_API_KEY is not set.")
        return TFIDFEmbedder(state_dir=state_dir)


def _write_text_atomically(path: Path, text: str) -> None:
    """Write text by replacing the target path atomically."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=str(path.parent),
        text=True,
    )
    temp_path = Path(temp_name)
    try:
        with os.fdopen(fd, "w", encoding=ENCODING) as temp_file:
            temp_file.write(text)
        os.replace(temp_path, path)
    finally:
        if temp_path.exists():
            temp_path.unlink()
