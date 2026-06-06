"""Schema validation for ProjectOS agent outputs."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Mapping


MAX_INPUT_SAMPLE_CHARS = 300
UNKNOWN_SCHEMA_REASON = "schema_not_registered"
NON_MAPPING_REASON = "expected mapping output"

AGENT_CODE_REVIEW = "code_review"
AGENT_PLANNING = "planning"
AGENT_CODE_WRITING = "code_writing"
AGENT_ARCHITECTURE = "architecture"
AGENT_DOCS = "docs"
AGENT_TEST = "test"

FIELD_ISSUES = "issues"
FIELD_TASKS = "tasks"
FIELD_FILE_PATH = "file_path"
FIELD_LINE_COUNT = "line_count"
FIELD_ADR_PATH = "adr_path"
FIELD_ADDED_DOCSTRINGS = "added_docstrings"
FIELD_README_UPDATED = "readme_updated"
FIELD_TEST_FILE = "test_file"
FIELD_PASSED = "passed"
FIELD_FAILED = "failed"
FIELD_SEVERITY = "severity"
FIELD_DESCRIPTION = "description"
FIELD_ID = "id"
FIELD_ACCEPTANCE_CRITERIA = "acceptance_criteria"


@dataclass
class OutputSchema:
    """Defines the expected structure of an agent's output."""

    agent_name: str
    required_fields: List[str]
    field_types: Dict[str, type]
    optional_fields: List[str] = field(default_factory=list)
    custom_validators: List[Callable[[Any], bool]] = field(default_factory=list)


@dataclass
class ValidationResult:
    """Result returned by SchemaValidator."""

    valid: bool
    agent_name: str
    missing_fields: List[str]
    type_errors: Dict[str, str]
    custom_validator_failures: List[str]
    input_sample: str


class SchemaValidator:
    """Validate agent outputs against registered output schemas."""

    def __init__(self, schemas: Dict[str, OutputSchema]) -> None:
        """Initialize validator with schemas keyed by agent name."""
        self.schemas = dict(schemas)

    def validate(self, agent_name: str, output: Any) -> ValidationResult:
        """Validate one output mapping without raising on malformed input."""
        schema = self.schemas.get(agent_name)
        input_sample = self._input_sample(output)
        if schema is None:
            return ValidationResult(
                valid=False,
                agent_name=agent_name,
                missing_fields=[],
                type_errors={},
                custom_validator_failures=[UNKNOWN_SCHEMA_REASON],
                input_sample=input_sample,
            )
        if not isinstance(output, Mapping):
            return ValidationResult(
                valid=False,
                agent_name=agent_name,
                missing_fields=list(schema.required_fields),
                type_errors={},
                custom_validator_failures=[NON_MAPPING_REASON],
                input_sample=input_sample,
            )

        missing_fields = self._missing_fields(schema, output)
        type_errors = self._type_errors(schema, output)
        validator_failures = self._validator_failures(schema, output)
        return ValidationResult(
            valid=not missing_fields and not type_errors and not validator_failures,
            agent_name=agent_name,
            missing_fields=missing_fields,
            type_errors=type_errors,
            custom_validator_failures=validator_failures,
            input_sample=input_sample,
        )

    def register_schema(self, schema: OutputSchema) -> None:
        """Register or replace one agent output schema."""
        self.schemas[schema.agent_name] = schema

    def has_schema(self, agent_name: str) -> bool:
        """Return whether a schema is registered for an agent."""
        return agent_name in self.schemas

    def _missing_fields(
        self,
        schema: OutputSchema,
        output: Mapping[str, Any],
    ) -> List[str]:
        """Return required fields absent from output."""
        return [field_name for field_name in schema.required_fields if field_name not in output]

    def _type_errors(
        self,
        schema: OutputSchema,
        output: Mapping[str, Any],
    ) -> Dict[str, str]:
        """Return type mismatch messages by field name."""
        errors: Dict[str, str] = {}
        for field_name, expected_type in schema.field_types.items():
            if field_name not in output:
                continue
            value = output[field_name]
            if not isinstance(value, expected_type):
                errors[field_name] = (
                    f"expected {expected_type.__name__} got "
                    f"{type(value).__name__}"
                )
        return errors

    def _validator_failures(
        self,
        schema: OutputSchema,
        output: Mapping[str, Any],
    ) -> List[str]:
        """Return custom validator failure labels."""
        failures: List[str] = []
        for index, custom_validator in enumerate(schema.custom_validators, start=1):
            try:
                passed = bool(custom_validator(output))
            except Exception as error:
                failures.append(f"custom_validator_{index}: {error}")
                continue
            if not passed:
                failures.append(f"custom_validator_{index}")
        return failures

    def _input_sample(self, output: Any) -> str:
        """Return the first 300 characters of validated content."""
        try:
            serialized = json.dumps(output, sort_keys=True, default=str)
        except TypeError:
            serialized = str(output)
        return serialized[:MAX_INPUT_SAMPLE_CHARS]


CODE_REVIEW_SCHEMA = OutputSchema(
    agent_name=AGENT_CODE_REVIEW,
    required_fields=[FIELD_ISSUES],
    field_types={FIELD_ISSUES: list},
    custom_validators=[
        lambda output: all(
            isinstance(issue, Mapping) and FIELD_SEVERITY in issue
            for issue in output.get(FIELD_ISSUES, [])
        ),
        lambda output: all(
            isinstance(issue, Mapping) and FIELD_DESCRIPTION in issue
            for issue in output.get(FIELD_ISSUES, [])
        ),
    ],
)

PLANNING_SCHEMA = OutputSchema(
    agent_name=AGENT_PLANNING,
    required_fields=[FIELD_TASKS],
    field_types={FIELD_TASKS: list},
    custom_validators=[
        lambda output: all(
            isinstance(task, Mapping) and FIELD_ID in task
            for task in output.get(FIELD_TASKS, [])
        ),
        lambda output: all(
            isinstance(task, Mapping) and FIELD_ACCEPTANCE_CRITERIA in task
            for task in output.get(FIELD_TASKS, [])
        ),
    ],
)

CODE_WRITING_SCHEMA = OutputSchema(
    agent_name=AGENT_CODE_WRITING,
    required_fields=[FIELD_FILE_PATH, FIELD_LINE_COUNT],
    field_types={FIELD_FILE_PATH: str, FIELD_LINE_COUNT: int},
)

ARCHITECTURE_SCHEMA = OutputSchema(
    agent_name=AGENT_ARCHITECTURE,
    required_fields=[FIELD_ADR_PATH],
    field_types={FIELD_ADR_PATH: str},
)

DOCS_SCHEMA = OutputSchema(
    agent_name=AGENT_DOCS,
    required_fields=[FIELD_FILE_PATH, FIELD_ADDED_DOCSTRINGS, FIELD_README_UPDATED],
    field_types={
        FIELD_FILE_PATH: str,
        FIELD_ADDED_DOCSTRINGS: int,
        FIELD_README_UPDATED: bool,
    },
)

TEST_SCHEMA = OutputSchema(
    agent_name=AGENT_TEST,
    required_fields=[FIELD_TEST_FILE, FIELD_PASSED, FIELD_FAILED],
    field_types={FIELD_TEST_FILE: str, FIELD_PASSED: int, FIELD_FAILED: int},
)

DEFAULT_SCHEMAS = {
    schema.agent_name: schema
    for schema in (
        CODE_REVIEW_SCHEMA,
        PLANNING_SCHEMA,
        CODE_WRITING_SCHEMA,
        ARCHITECTURE_SCHEMA,
        DOCS_SCHEMA,
        TEST_SCHEMA,
    )
}


__all__ = [
    "ARCHITECTURE_SCHEMA",
    "CODE_REVIEW_SCHEMA",
    "CODE_WRITING_SCHEMA",
    "DEFAULT_SCHEMAS",
    "DOCS_SCHEMA",
    "OutputSchema",
    "PLANNING_SCHEMA",
    "SchemaValidator",
    "TEST_SCHEMA",
    "ValidationResult",
]
