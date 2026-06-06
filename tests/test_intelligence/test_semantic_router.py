"""Tests for ProjectOS semantic routing."""

from __future__ import annotations

import json
from pathlib import Path

from core.intelligence.embedder import TFIDFEmbedder
from core.intelligence.semantic_router import (
    ROUTING_DECISIONS_FILE_NAME,
    ROUTING_EXAMPLES_COLLECTION,
    RoutingExample,
    SemanticRouter,
)
from core.intelligence.vector_store import NumpyVectorStore


CATEGORY_AUTONOMOUS = "AUTONOMOUS"
CATEGORY_ESCALATE = "ESCALATE"
CATEGORY_DEFER_PARALLEL = "DEFER_PARALLEL"
CATEGORY_PLANNING = "planning"
ROUTING_METHOD_SEMANTIC = "semantic"
ROUTING_METHOD_FALLBACK = "keyword_fallback"


def test_route_docstring_update_autonomous(tmp_path: Path) -> None:
    """Verify docstring update examples route to AUTONOMOUS."""
    router = _router(tmp_path)

    decision = router.route("updated function docstring")

    assert decision.category == CATEGORY_AUTONOMOUS
    assert decision.routing_method == ROUTING_METHOD_SEMANTIC


def test_route_new_dependency_escalate(tmp_path: Path) -> None:
    """Verify dependency examples route to ESCALATE."""
    router = _router(tmp_path)

    decision = router.route("new external package dependency added")

    assert decision.category == CATEGORY_ESCALATE
    assert decision.routing_method == ROUTING_METHOD_SEMANTIC


def test_route_permission_blocked_defer(tmp_path: Path) -> None:
    """Verify permission-blocked examples route to DEFER_PARALLEL."""
    router = _router(tmp_path)

    decision = router.route("waiting for permission to write file")

    assert decision.category == CATEGORY_DEFER_PARALLEL
    assert decision.routing_method == ROUTING_METHOD_SEMANTIC


def test_route_new_feature_to_planning(tmp_path: Path) -> None:
    """Verify feature request examples route to the planning agent."""
    router = _router(tmp_path)

    decision = router.route("new feature request for the system")

    assert decision.category == CATEGORY_PLANNING
    assert decision.routing_method == ROUTING_METHOD_SEMANTIC


def test_low_confidence_falls_back_to_keywords(tmp_path: Path) -> None:
    """Verify low semantic confidence uses keyword fallback."""
    router = _router(tmp_path, min_confidence=1.1)

    decision = router.route("payload includes new_dependency key")

    assert decision.category == CATEGORY_ESCALATE
    assert decision.confidence == 0.0
    assert decision.routing_method == ROUTING_METHOD_FALLBACK


def test_new_dependency_phrase_falls_back_to_escalate(tmp_path: Path) -> None:
    """Verify natural dependency wording falls back to ESCALATE."""
    router = _router(tmp_path, min_confidence=1.1)

    decision = router.route("added requests library as new dependency")

    assert decision.category == CATEGORY_ESCALATE
    assert decision.routing_method == ROUTING_METHOD_FALLBACK


def test_add_example_affects_routing_immediately(tmp_path: Path) -> None:
    """Verify added examples are available for immediate semantic routing."""
    router = _router(tmp_path)

    router.add_example(RoutingExample("triage billing incident", CATEGORY_ESCALATE))
    decision = router.route("triage billing incident")

    assert decision.category == CATEGORY_ESCALATE
    assert decision.routing_method == ROUTING_METHOD_SEMANTIC
    assert decision.nearest_example == "triage billing incident"


def test_routing_stats_tracked_correctly(tmp_path: Path) -> None:
    """Verify routing stats are computed from the JSONL decision log."""
    router = _router(tmp_path, min_confidence=1.1)
    router.route("payload includes new_dependency key")
    router.min_confidence = 0.0
    router.route("updated function docstring")

    stats = router.get_routing_stats()

    assert stats["total_decisions"] == 2
    assert stats["fallback_pct"] == 0.5
    assert stats["semantic_pct"] == 0.5
    assert stats["decisions_by_category"][CATEGORY_ESCALATE] == 1
    assert stats["decisions_by_category"][CATEGORY_AUTONOMOUS] == 1


def test_routing_logged_to_jsonl(tmp_path: Path) -> None:
    """Verify every route call writes a JSONL routing decision."""
    router = _router(tmp_path)

    router.route("updated function docstring")

    log_path = tmp_path / ROUTING_DECISIONS_FILE_NAME
    records = [
        json.loads(line)
        for line in log_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(records) == 1
    assert records[0]["category"] == CATEGORY_AUTONOMOUS
    assert records[0]["routing_method"] == ROUTING_METHOD_SEMANTIC


def test_route_with_empty_payload_does_not_crash(tmp_path: Path) -> None:
    """Verify empty event descriptions safely return a fallback route."""
    router = _router(tmp_path)

    decision = router.route("")

    assert decision.category == CATEGORY_AUTONOMOUS
    assert decision.routing_method == ROUTING_METHOD_FALLBACK


def _router(tmp_path: Path, min_confidence: float = 0.60) -> SemanticRouter:
    """Return a semantic router backed by local deterministic storage."""
    embedder = TFIDFEmbedder(vocab_size=128, state_dir=tmp_path / "embedder")
    vector_store = NumpyVectorStore(ROUTING_EXAMPLES_COLLECTION, tmp_path)
    return SemanticRouter(
        embedder,
        vector_store,
        min_confidence=min_confidence,
        log_path=tmp_path / ROUTING_DECISIONS_FILE_NAME,
    )
