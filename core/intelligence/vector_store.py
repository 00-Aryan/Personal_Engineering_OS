"""Vector store abstractions for ProjectOS intelligence features."""

from __future__ import annotations

import json
import logging
import math
import os
import tempfile
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.intelligence.embedder import BaseEmbedder


ENCODING = "utf-8"
CHROMA_DB_DIR_NAME = "chroma_db"
VECTOR_STORE_FILE_TEMPLATE = "vector_store_{collection_name}.json"
CHROMA_INSTALL_INSTRUCTIONS = "Install chromadb>=0.5.0 to use ChromaVectorStore."
MIN_SIMILARITY = 0.0
MAX_SIMILARITY = 1.0

logger = logging.getLogger(__name__)


@dataclass
class VectorRecord:
    """One persisted text embedding and its retrieval metadata."""

    text: str
    embedding: List[float]
    metadata: Dict[str, Any]
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        """Ensure every record has a valid UUID4 identifier."""
        try:
            parsed_uuid = uuid.UUID(str(self.id))
            if parsed_uuid.version != 4:
                self.id = str(uuid.uuid4())
        except (TypeError, ValueError, AttributeError):
            self.id = str(uuid.uuid4())


@dataclass
class SearchResult:
    """Ranked vector search result."""

    record: VectorRecord
    similarity_score: float
    rank: int


class BaseVectorStore(ABC):
    """Abstract vector store interface."""

    @abstractmethod
    def add(self, record: VectorRecord) -> None:
        """Add a vector record to the store."""

    @abstractmethod
    def search(
        self,
        query_embedding: List[float],
        k: int = 5,
        filter_metadata: Optional[Dict[str, Any]] = None,
    ) -> List[SearchResult]:
        """Return the top matching records without raising."""

    @abstractmethod
    def delete(self, record_id: str) -> bool:
        """Delete a record by ID and return whether it existed."""

    @abstractmethod
    def count(self) -> int:
        """Return the number of records in the collection."""

    @abstractmethod
    def get_collection_name(self) -> str:
        """Return the collection name backing this store."""


class ChromaVectorStore(BaseVectorStore):
    """Persistent ChromaDB-backed vector store."""

    def __init__(
        self,
        collection_name: str,
        state_dir: Path,
        embedder: BaseEmbedder,
    ) -> None:
        """Create or open one ChromaDB collection."""
        try:
            import chromadb
        except ImportError as exc:
            raise ImportError(CHROMA_INSTALL_INSTRUCTIONS) from exc

        self.collection_name = collection_name
        self.state_dir = Path(state_dir)
        self.embedder = embedder
        self.chroma_path = self.state_dir / CHROMA_DB_DIR_NAME
        self.chroma_path.mkdir(parents=True, exist_ok=True)
        self.client = chromadb.PersistentClient(path=str(self.chroma_path))
        self.collection = self.client.get_or_create_collection(name=collection_name)
        try:
            # Proactive dimension mismatch check by running a test query
            dim = self.embedder.get_dimension()
            self.collection.query(
                query_embeddings=[[0.0] * dim],
                n_results=1
            )
        except Exception as exc:
            exc_str = str(exc)
            if "dimension" in exc_str or "Collection expecting" in exc_str:
                logger.warning(
                    "Embedding dimension mismatch in collection %s: Recreating.",
                    collection_name
                )
                try:
                    self.client.delete_collection(name=collection_name)
                    self.collection = self.client.create_collection(name=collection_name)
                except Exception as del_exc:
                    logger.error("Failed to delete/recreate collection %s: %s", collection_name, del_exc)
            else:
                logger.warning("Failed to validate collection %s dimension: %s", collection_name, exc)

    def add(self, record: VectorRecord) -> None:
        """Store a record in ChromaDB."""
        try:
            self.collection.add(
                ids=[record.id],
                embeddings=[record.embedding],
                documents=[record.text],
                metadatas=[self._metadata(record)],
            )
        except Exception as exc:
            exc_str = str(exc)
            if "dimension" in exc_str or "Collection expecting" in exc_str:
                logger.warning("Dimension mismatch during add. Recreating collection %s...", self.collection_name)
                try:
                    self.client.delete_collection(name=self.collection_name)
                    self.collection = self.client.create_collection(name=self.collection_name)
                    self.collection.add(
                        ids=[record.id],
                        embeddings=[record.embedding],
                        documents=[record.text],
                        metadatas=[self._metadata(record)],
                    )
                except Exception as del_exc:
                    logger.error("Failed to recreate and retry add for %s: %s", self.collection_name, del_exc)
                    raise exc
            else:
                raise exc

    def search(
        self,
        query_embedding: List[float],
        k: int = 5,
        filter_metadata: Optional[Dict[str, Any]] = None,
    ) -> List[SearchResult]:
        """Search ChromaDB and convert results to ProjectOS dataclasses."""
        try:
            if not query_embedding or k <= 0:
                return []
            response = self.collection.query(
                query_embeddings=[query_embedding],
                n_results=k,
                where=filter_metadata,
                include=["documents", "metadatas", "embeddings", "distances"],
            )
            return self._search_results(response)
        except Exception as exc:
            exc_str = str(exc)
            if "dimension" in exc_str or "Collection expecting" in exc_str:
                logger.warning("Dimension mismatch during search. Recreating collection %s...", self.collection_name)
                try:
                    self.client.delete_collection(name=self.collection_name)
                    self.collection = self.client.create_collection(name=self.collection_name)
                except Exception as del_exc:
                    logger.error("Failed to delete/recreate collection %s: %s", self.collection_name, del_exc)
            else:
                logger.warning("Chroma vector search failed: %s", exc)
            return []

    def delete(self, record_id: str) -> bool:
        """Delete one ChromaDB record by ID."""
        try:
            self.collection.delete(ids=[record_id])
            return True
        except Exception as exc:
            logger.warning("Chroma delete failed for %s: %s", record_id, exc)
            return False

    def count(self) -> int:
        """Return Chroma collection count."""
        try:
            return int(self.collection.count())
        except Exception:
            return 0

    def get_collection_name(self) -> str:
        """Return the Chroma collection name."""
        return self.collection_name

    def _metadata(self, record: VectorRecord) -> Dict[str, Any]:
        """Return Chroma-safe metadata for a vector record."""
        metadata: Dict[str, Any] = {
            key: value
            for key, value in record.metadata.items()
            if isinstance(value, (str, int, float, bool)) and value is not None
        }
        metadata["created_at"] = record.created_at.isoformat()
        metadata["embedder"] = self.embedder.get_embedder_name()
        return metadata

    def _search_results(self, response: Dict[str, Any]) -> List[SearchResult]:
        """Convert raw Chroma query response to ranked search results."""
        ids = response.get("ids", [[]])[0]
        documents = response.get("documents", [[]])[0]
        metadatas = response.get("metadatas", [[]])[0]
        embeddings = response.get("embeddings", [[]])[0]
        distances = response.get("distances", [[]])[0]
        results: List[SearchResult] = []
        for index, record_id in enumerate(ids):
            metadata = dict(metadatas[index] or {})
            created_at = _datetime_from_value(metadata.pop("created_at", None))
            embedding = list(embeddings[index]) if index < len(embeddings) else []
            distance = distances[index] if index < len(distances) else 1.0
            score = _bounded_similarity(1.0 - float(distance))
            record = VectorRecord(
                id=str(record_id),
                text=str(documents[index] or ""),
                embedding=[float(value) for value in embedding],
                metadata=metadata,
                created_at=created_at,
            )
            results.append(SearchResult(record=record, similarity_score=score, rank=index + 1))
        return results


class NumpyVectorStore(BaseVectorStore):
    """Numpy-backed vector store with JSON persistence."""

    def __init__(self, collection_name: str, state_dir: Path) -> None:
        """Load existing records for one collection from JSON."""
        self.collection_name = collection_name
        self.state_dir = Path(state_dir)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.path = self.state_dir / VECTOR_STORE_FILE_TEMPLATE.format(
            collection_name=collection_name
        )
        self.records: List[VectorRecord] = []
        self._load()

    def add(self, record: VectorRecord) -> None:
        """Append a record and persist the collection."""
        self.records.append(record)
        self._save()

    def search(
        self,
        query_embedding: List[float],
        k: int = 5,
        filter_metadata: Optional[Dict[str, Any]] = None,
    ) -> List[SearchResult]:
        """Return the top k records by cosine similarity."""
        try:
            if not query_embedding or k <= 0:
                return []
            filtered_records = [
                record
                for record in self.records
                if _metadata_matches(record.metadata, filter_metadata)
            ]
            scored_records = [
                (record, _cosine_similarity(query_embedding, record.embedding))
                for record in filtered_records
            ]
            scored_records.sort(key=lambda item: item[1], reverse=True)
            return [
                SearchResult(
                    record=record,
                    similarity_score=_bounded_similarity(score),
                    rank=index + 1,
                )
                for index, (record, score) in enumerate(scored_records[:k])
            ]
        except Exception as exc:
            logger.warning("Numpy vector search failed: %s", exc)
            return []

    def delete(self, record_id: str) -> bool:
        """Delete a record by ID and persist the collection."""
        original_count = len(self.records)
        self.records = [record for record in self.records if record.id != record_id]
        deleted = len(self.records) != original_count
        if deleted:
            self._save()
        return deleted

    def count(self) -> int:
        """Return the number of in-memory records."""
        return len(self.records)

    def get_collection_name(self) -> str:
        """Return the collection name backing this JSON file."""
        return self.collection_name

    def _load(self) -> None:
        """Load records from disk if the JSON file exists."""
        if not self.path.exists():
            return
        try:
            payload = json.loads(self.path.read_text(encoding=ENCODING))
            records = payload.get("records", []) if isinstance(payload, dict) else []
            self.records = [_record_from_payload(item) for item in records]
        except Exception as exc:
            logger.warning("Could not load vector store %s: %s", self.path, exc)
            self.records = []

    def _save(self) -> None:
        """Persist records with an atomic file replacement."""
        payload = {
            "collection_name": self.collection_name,
            "records": [_record_payload(record) for record in self.records],
        }
        _write_text_atomically(self.path, json.dumps(payload, sort_keys=True))


class VectorStoreFactory:
    """Create the best available vector store implementation."""

    @staticmethod
    def create(
        collection_name: str,
        state_dir: Path,
        embedder: BaseEmbedder,
    ) -> BaseVectorStore:
        """Prefer ChromaDB and fall back to the local numpy store."""
        try:
            store = ChromaVectorStore(collection_name, state_dir, embedder)
            logger.info("Selected ChromaVectorStore for %s.", collection_name)
            return store
        except ImportError:
            logger.info("Selected NumpyVectorStore for %s; ChromaDB unavailable.", collection_name)
            return NumpyVectorStore(collection_name, state_dir)


def _metadata_matches(
    metadata: Dict[str, Any],
    filter_metadata: Optional[Dict[str, Any]],
) -> bool:
    """Return whether record metadata satisfies an exact-match filter."""
    if not filter_metadata:
        return True
    return all(metadata.get(key) == value for key, value in filter_metadata.items())


def _cosine_similarity(left: List[float], right: List[float]) -> float:
    """Compute cosine similarity with numpy when available."""
    if not left or not right:
        return 0.0
    try:
        import numpy as np

        limit = min(len(left), len(right))
        left_array = np.array(left[:limit], dtype=float)
        right_array = np.array(right[:limit], dtype=float)
        denominator = float(np.linalg.norm(left_array) * np.linalg.norm(right_array))
        if denominator == 0.0:
            return 0.0
        return float(np.dot(left_array, right_array) / denominator)
    except Exception:
        limit = min(len(left), len(right))
        left_values = [float(value) for value in left[:limit]]
        right_values = [float(value) for value in right[:limit]]
        numerator = sum(a * b for a, b in zip(left_values, right_values))
        left_norm = math.sqrt(sum(value * value for value in left_values))
        right_norm = math.sqrt(sum(value * value for value in right_values))
        denominator = left_norm * right_norm
        if denominator == 0.0:
            return 0.0
        return numerator / denominator


def _bounded_similarity(value: float) -> float:
    """Clamp similarity into the public 0.0 to 1.0 range."""
    return min(max(float(value), MIN_SIMILARITY), MAX_SIMILARITY)


def _record_payload(record: VectorRecord) -> Dict[str, Any]:
    """Serialize one vector record to JSON-safe data."""
    return {
        "id": record.id,
        "text": record.text,
        "embedding": record.embedding,
        "metadata": record.metadata,
        "created_at": record.created_at.isoformat(),
    }


def _record_from_payload(payload: Dict[str, Any]) -> VectorRecord:
    """Deserialize one vector record from JSON-safe data."""
    return VectorRecord(
        id=str(payload.get("id", "")),
        text=str(payload.get("text", "")),
        embedding=[float(value) for value in payload.get("embedding", [])],
        metadata=dict(payload.get("metadata", {})),
        created_at=_datetime_from_value(payload.get("created_at")),
    )


def _datetime_from_value(value: Any) -> datetime:
    """Parse a datetime value or return the current UTC timestamp."""
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value)
            if parsed.tzinfo is None:
                return parsed.replace(tzinfo=timezone.utc)
            return parsed
        except ValueError:
            pass
    return datetime.now(timezone.utc)


def _write_text_atomically(path: Path, text: str) -> None:
    """Write text by atomically replacing the target path."""
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
