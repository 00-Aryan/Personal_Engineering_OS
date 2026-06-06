"""Tests for ProjectOS output schema validation."""

from __future__ import annotations

from typing import Any

from core.evaluation.schema_validator import (
    CODE_REVIEW_SCHEMA,
    OutputSchema,
    SchemaValidator,
)


AGENT_CODE_REVIEW = "code_review"
AGENT_CUSTOM = "custom"
AGENT_UNKNOWN = "unknown"
FIELD_ISSUES = "issues"
FIELD_VALUE = "value"
SEVERITY_HIGH = "HIGH"
DESCRIPTION = "Specific issue."


def test_valid_output_passes_code_review_schema() -> None:
    """Verify a valid code-review output passes validation."""
    validator = SchemaValidator({AGENT_CODE_REVIEW: CODE_REVIEW_SCHEMA})

    result = validator.validate(AGENT_CODE_REVIEW, _valid_review_output())

    assert result.valid is True
    assert result.missing_fields == []
    assert result.type_errors == {}
    assert result.custom_validator_failures == []


def test_missing_required_field_fails() -> None:
    """Verify missing required fields fail validation."""
    validator = SchemaValidator({AGENT_CODE_REVIEW: CODE_REVIEW_SCHEMA})

    result = validator.validate(AGENT_CODE_REVIEW, {})

    assert result.valid is False
    assert result.missing_fields == [FIELD_ISSUES]


def test_wrong_type_fails_with_message() -> None:
    """Verify wrong field types are reported with expected/got text."""
    validator = SchemaValidator({AGENT_CODE_REVIEW: CODE_REVIEW_SCHEMA})

    result = validator.validate(AGENT_CODE_REVIEW, {FIELD_ISSUES: "not-list"})

    assert result.valid is False
    assert result.type_errors[FIELD_ISSUES] == "expected list got str"


def test_custom_validator_failure_reported() -> None:
    """Verify custom validator failures are reported."""
    validator = SchemaValidator({AGENT_CODE_REVIEW: CODE_REVIEW_SCHEMA})

    result = validator.validate(AGENT_CODE_REVIEW, {FIELD_ISSUES: [{}]})

    assert result.valid is False
    assert result.custom_validator_failures == [
        "custom_validator_1",
        "custom_validator_2",
    ]


def test_unknown_agent_returns_valid_false_not_crash() -> None:
    """Verify unknown agents return invalid without raising."""
    validator = SchemaValidator({})

    result = validator.validate(AGENT_UNKNOWN, _valid_review_output())

    assert result.valid is False
    assert result.agent_name == AGENT_UNKNOWN
    assert result.custom_validator_failures == ["schema_not_registered"]


def test_register_new_schema_works() -> None:
    """Verify registering a schema allows later validation."""
    validator = SchemaValidator({})
    schema = OutputSchema(
        agent_name=AGENT_CUSTOM,
        required_fields=[FIELD_VALUE],
        field_types={FIELD_VALUE: int},
    )

    validator.register_schema(schema)
    result = validator.validate(AGENT_CUSTOM, {FIELD_VALUE: 1})

    assert result.valid is True


def _valid_review_output() -> dict[str, Any]:
    """Return a valid code-review output."""
    return {
        FIELD_ISSUES: [
            {
                "severity": SEVERITY_HIGH,
                "description": DESCRIPTION,
            }
        ]
    }
