"""Reusable evaluation criteria sets for ProjectOS agents."""

from __future__ import annotations

from typing import List

from core.evaluation.base_evaluator import EvaluationCriteria


DEFAULT_CRITERION_THRESHOLD = 0.7

CRITERION_CORRECTNESS = "correctness"
CRITERION_TYPE_SAFETY = "type_safety"
CRITERION_DOCUMENTATION = "documentation"
CRITERION_NO_HARDCODING = "no_hardcoding"
CRITERION_ERROR_HANDLING = "error_handling"

CRITERION_ISSUE_SPECIFICITY = "issue_specificity"
CRITERION_SEVERITY_CALIBRATION = "severity_calibration"
CRITERION_ACTIONABILITY = "actionability"
CRITERION_COMPLETENESS = "completeness"

CRITERION_DECOMPOSITION_QUALITY = "decomposition_quality"
CRITERION_ACCEPTANCE_CRITERIA = "acceptance_criteria"
CRITERION_DEPENDENCY_ACCURACY = "dependency_accuracy"
CRITERION_AGENT_ASSIGNMENT = "agent_assignment"

CRITERION_ACCURACY = "accuracy"
CRITERION_CLARITY = "clarity"


def code_writing_criteria() -> List[EvaluationCriteria]:
    """Return criteria for evaluating code-writing agent outputs."""
    return [
        EvaluationCriteria(
            name=CRITERION_CORRECTNESS,
            description=(
                "Code is syntactically valid Python that implements the described "
                "functionality"
            ),
            weight=0.35,
            passing_threshold=DEFAULT_CRITERION_THRESHOLD,
        ),
        EvaluationCriteria(
            name=CRITERION_TYPE_SAFETY,
            description="All functions have type hints",
            weight=0.15,
            passing_threshold=DEFAULT_CRITERION_THRESHOLD,
        ),
        EvaluationCriteria(
            name=CRITERION_DOCUMENTATION,
            description="All functions have docstrings",
            weight=0.15,
            passing_threshold=DEFAULT_CRITERION_THRESHOLD,
        ),
        EvaluationCriteria(
            name=CRITERION_NO_HARDCODING,
            description=(
                "No hardcoded values, strings, or paths that should be configurable"
            ),
            weight=0.20,
            passing_threshold=DEFAULT_CRITERION_THRESHOLD,
        ),
        EvaluationCriteria(
            name=CRITERION_ERROR_HANDLING,
            description=(
                "Handles expected failure modes gracefully without crashing"
            ),
            weight=0.15,
            passing_threshold=DEFAULT_CRITERION_THRESHOLD,
        ),
    ]


def code_review_criteria() -> List[EvaluationCriteria]:
    """Return criteria for evaluating code-review agent outputs."""
    return [
        EvaluationCriteria(
            name=CRITERION_ISSUE_SPECIFICITY,
            description=(
                "Issues have specific file/line references, not vague general "
                "complaints"
            ),
            weight=0.30,
            passing_threshold=DEFAULT_CRITERION_THRESHOLD,
        ),
        EvaluationCriteria(
            name=CRITERION_SEVERITY_CALIBRATION,
            description=(
                "CRITICAL severity used only for actual breaking issues, not "
                "style preferences"
            ),
            weight=0.25,
            passing_threshold=DEFAULT_CRITERION_THRESHOLD,
        ),
        EvaluationCriteria(
            name=CRITERION_ACTIONABILITY,
            description=(
                "Each issue includes a concrete suggested fix, not just "
                "identification"
            ),
            weight=0.30,
            passing_threshold=DEFAULT_CRITERION_THRESHOLD,
        ),
        EvaluationCriteria(
            name=CRITERION_COMPLETENESS,
            description=(
                "Review covers security, logic, performance, and documentation gaps"
            ),
            weight=0.15,
            passing_threshold=DEFAULT_CRITERION_THRESHOLD,
        ),
    ]


def planning_criteria() -> List[EvaluationCriteria]:
    """Return criteria for evaluating planning agent outputs."""
    return [
        EvaluationCriteria(
            name=CRITERION_DECOMPOSITION_QUALITY,
            description="Tasks are atomic and independently executable",
            weight=0.30,
            passing_threshold=DEFAULT_CRITERION_THRESHOLD,
        ),
        EvaluationCriteria(
            name=CRITERION_ACCEPTANCE_CRITERIA,
            description="Each task has measurable done conditions",
            weight=0.25,
            passing_threshold=DEFAULT_CRITERION_THRESHOLD,
        ),
        EvaluationCriteria(
            name=CRITERION_DEPENDENCY_ACCURACY,
            description=(
                "Task dependencies reflect actual technical constraints"
            ),
            weight=0.25,
            passing_threshold=DEFAULT_CRITERION_THRESHOLD,
        ),
        EvaluationCriteria(
            name=CRITERION_AGENT_ASSIGNMENT,
            description="Each task assigned to the correct agent type",
            weight=0.20,
            passing_threshold=DEFAULT_CRITERION_THRESHOLD,
        ),
    ]


def documentation_criteria() -> List[EvaluationCriteria]:
    """Return criteria for evaluating documentation agent outputs."""
    return [
        EvaluationCriteria(
            name=CRITERION_ACCURACY,
            description="Documentation matches the actual code behavior",
            weight=0.40,
            passing_threshold=DEFAULT_CRITERION_THRESHOLD,
        ),
        EvaluationCriteria(
            name=CRITERION_COMPLETENESS,
            description=(
                "All parameters, returns, and exceptions documented"
            ),
            weight=0.35,
            passing_threshold=DEFAULT_CRITERION_THRESHOLD,
        ),
        EvaluationCriteria(
            name=CRITERION_CLARITY,
            description=(
                "Explanation is understandable without reading the implementation"
            ),
            weight=0.25,
            passing_threshold=DEFAULT_CRITERION_THRESHOLD,
        ),
    ]


__all__ = [
    "code_review_criteria",
    "code_writing_criteria",
    "documentation_criteria",
    "planning_criteria",
]
