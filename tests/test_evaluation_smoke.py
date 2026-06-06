"""Tests for the evaluation smoke script."""

from __future__ import annotations

from pathlib import Path

from scripts.evaluation_smoke import SMOKE_PASS_TEXT, run_smoke


def test_evaluation_smoke_passes(tmp_path: Path) -> None:
    """Verify the mocked end-to-end evaluation smoke succeeds."""
    passed, message = run_smoke(tmp_path)

    assert passed is True
    assert message == SMOKE_PASS_TEXT
