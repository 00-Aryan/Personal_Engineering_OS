"""Safety policies for ProjectOS file writes."""

from __future__ import annotations

import difflib
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional


ENCODING = "utf-8"
DEFAULT_MAX_FILE_SIZE_BYTES = 100_000
DELETION_WARNING_THRESHOLD = 0.5

REASON_ALLOWED = "write allowed"
REASON_OUTSIDE_ALLOWED_DIRS = "file path is outside allowed directories"
REASON_PROTECTED_FILE = "file path is protected"
REASON_OVERSIZED_CONTENT = "content exceeds maximum file size"
WARNING_LARGE_DELETION = "write removes more than 50% of existing lines"

DIR_AGENTS = "agents"
DIR_TESTS = "tests"
DIR_DOCS = "docs"
DIR_REVIEWS = "reviews"
DIR_CORE = "core"
DIR_CONFIG = "config"
FILE_BASE_AGENT = "base_agent.py"
FILE_EVENTS = "events.py"
FILE_MODEL_PROVIDER = "model_provider.py"
FILE_MODELS_YAML = "models.yaml"
FILE_AGENTS_MD = "AGENTS.md"


@dataclass
class SafetyResult:
    """Result returned by write safety validation."""

    allowed: bool
    reason: str
    diff_preview: Optional[str] = None
    warnings: List[str] = field(default_factory=list)


class SafetyPolicy:
    """Validate candidate file writes before they touch disk."""

    def __init__(
        self,
        allowed_dirs: List[Path],
        protected_files: List[Path],
        max_file_size_bytes: int = DEFAULT_MAX_FILE_SIZE_BYTES,
        require_diff_preview: bool = True,
    ) -> None:
        """Initialize allowlists, protected files, and size limits."""
        self.allowed_dirs = [Path(path).resolve() for path in allowed_dirs]
        self.protected_files = [Path(path).resolve() for path in protected_files]
        self.max_file_size_bytes = max_file_size_bytes
        self.require_diff_preview = require_diff_preview

    def validate_write(self, file_path: Path, content: str) -> SafetyResult:
        """Validate a candidate write and return a non-raising result."""
        try:
            resolved_path = Path(file_path).resolve()
            diff_preview = self._diff_preview(resolved_path, content)
            warnings = self._warnings(resolved_path, content)

            if not self._is_inside_allowed_dir(resolved_path):
                return SafetyResult(
                    allowed=False,
                    reason=REASON_OUTSIDE_ALLOWED_DIRS,
                    diff_preview=diff_preview,
                    warnings=warnings,
                )
            if resolved_path in self.protected_files:
                return SafetyResult(
                    allowed=False,
                    reason=REASON_PROTECTED_FILE,
                    diff_preview=diff_preview,
                    warnings=warnings,
                )
            if len(content.encode(ENCODING)) > self.max_file_size_bytes:
                return SafetyResult(
                    allowed=False,
                    reason=REASON_OVERSIZED_CONTENT,
                    diff_preview=diff_preview,
                    warnings=warnings,
                )
            return SafetyResult(
                allowed=True,
                reason=REASON_ALLOWED,
                diff_preview=diff_preview,
                warnings=warnings,
            )
        except Exception as error:
            return SafetyResult(
                allowed=False,
                reason=str(error),
                diff_preview=None,
                warnings=[],
            )

    def _is_inside_allowed_dir(self, resolved_path: Path) -> bool:
        """Return whether a resolved path is inside an allowed directory."""
        return any(self._is_relative_to(resolved_path, allowed_dir) for allowed_dir in self.allowed_dirs)

    def _warnings(self, resolved_path: Path, content: str) -> List[str]:
        """Return non-blocking warnings for a candidate write."""
        if not resolved_path.exists():
            return []
        existing_lines = resolved_path.read_text(encoding=ENCODING).splitlines()
        if not existing_lines:
            return []
        new_line_count = len(content.splitlines())
        if new_line_count < len(existing_lines) * DELETION_WARNING_THRESHOLD:
            return [WARNING_LARGE_DELETION]
        return []

    def _diff_preview(self, resolved_path: Path, content: str) -> Optional[str]:
        """Return a unified diff when policy requires one and a file exists."""
        if not resolved_path.exists():
            return None
        if not self.require_diff_preview and not self._is_core_path(resolved_path):
            return None
        original_lines = resolved_path.read_text(encoding=ENCODING).splitlines(
            keepends=True
        )
        new_lines = content.splitlines(keepends=True)
        return "".join(
            difflib.unified_diff(
                original_lines,
                new_lines,
                fromfile=str(resolved_path),
                tofile=str(resolved_path),
            )
        )

    def _is_core_path(self, resolved_path: Path) -> bool:
        """Return whether a path is inside a directory named core."""
        return DIR_CORE in resolved_path.parts

    def _is_relative_to(self, path: Path, parent: Path) -> bool:
        """Return whether a path is under a parent path."""
        try:
            path.relative_to(parent)
            return True
        except ValueError:
            return False


class DefaultSafetyPolicy(SafetyPolicy):
    """Default ProjectOS write policy for code generation."""

    def __init__(self, project_root: Path | str = Path(".")) -> None:
        """Initialize the default ProjectOS allowlist and protected files."""
        root = Path(project_root).resolve()
        super().__init__(
            allowed_dirs=[
                root / DIR_AGENTS,
                root / DIR_TESTS,
                root / DIR_DOCS,
                root / DIR_REVIEWS,
            ],
            protected_files=[
                root / DIR_CORE / FILE_BASE_AGENT,
                root / DIR_CORE / FILE_EVENTS,
                root / DIR_CORE / FILE_MODEL_PROVIDER,
                root / DIR_CONFIG / FILE_MODELS_YAML,
                root / FILE_AGENTS_MD,
            ],
            max_file_size_bytes=DEFAULT_MAX_FILE_SIZE_BYTES,
            require_diff_preview=False,
        )


__all__ = ["DefaultSafetyPolicy", "SafetyPolicy", "SafetyResult"]
