from __future__ import annotations
import ast
from dataclasses import dataclass
from typing import Optional

STOPWORDS = {
    "the", "and", "for", "that", "with", "this", "from", "have",
    "will", "your", "are", "not", "but", "been", "has", "into",
}

@dataclass
class ValidationResult:
    valid: bool
    reason: str
    check_name: str
    original_size: int
    output_size: int
    action: str

class PreWriteValidator:
    def __init__(self, max_new_file_lines: int = 150, max_size_ratio: float = 2.5) -> None:
        self.max_new_file_lines = max_new_file_lines
        self.max_size_ratio = max_size_ratio

    def validate(
        self,
        proposed_content: str,
        task_description: str,
        target_file_path: str,
        existing_content: Optional[str] = None,
    ) -> ValidationResult:
        orig_sz = len(existing_content.splitlines()) if existing_content is not None else 0
        out_sz = len(proposed_content.splitlines())

        if str(target_file_path).endswith(".py"):
            try:
                ast.parse(proposed_content)
            except SyntaxError as e:
                return ValidationResult(False, f"Syntax error: {e}", "syntax", orig_sz, out_sz, "RETRY_ONCE")

        if existing_content is None:
            if out_sz > self.max_new_file_lines:
                return ValidationResult(False, f"Exceeds max lines", "size", 0, out_sz, "DISCARD")
        else:
            ratio = out_sz / max(orig_sz, 1)
            if ratio > self.max_size_ratio:
                return ValidationResult(False, f"Exceeds max ratio", "size_ratio", orig_sz, out_sz, "DISCARD")

        words = task_description.lower().split()
        seen = set()
        key_nouns = []
        for w in words:
            w_clean = "".join(c for c in w if c.isalnum())
            if len(w_clean) > 4 and w_clean not in STOPWORDS and w_clean not in seen:
                seen.add(w_clean)
                key_nouns.append(w_clean)

        if len(key_nouns) >= 2:
            match_rate = sum(1 for n in key_nouns if n in proposed_content.lower()) / len(key_nouns)
            if match_rate < 0.20:
                return ValidationResult(False, f"Low relevance", "relevance", orig_sz, out_sz, "DISCARD")

        return ValidationResult(True, "", "", orig_sz, out_sz, "WRITE")

    def retry_with_constraint(
        self,
        original_prompt: str,
        validation_result: ValidationResult,
        task_description: str = "",
    ) -> str:
        name = validation_result.check_name
        if name == "syntax":
            return f"{original_prompt}\n\nCRITICAL: Previous output had syntax error: {validation_result.reason}. Output valid Python only."
        if name in ("size", "size_ratio"):
            return f"{original_prompt}\n\nCRITICAL: Output must be under {self.max_new_file_lines} lines. Be concise."
        if name == "relevance":
            desc = task_description or "the task description"
            return f"{original_prompt}\n\nCRITICAL: Output must specifically address: {desc}. Stay focused."
        return original_prompt
