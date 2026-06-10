from __future__ import annotations
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

@dataclass
class ProjectContext:
    """Dataclass holding extracted project metadata."""
    project_name: str
    description: str
    tech_stack: List[str]
    primary_language: str
    domain: str
    key_files: List[str]
    conventions: List[str]
    constraints: List[str]
    context_file_path: str

class ProjectContextLoader:
    """Loads project context from a markdown file in the project root."""
    def __init__(self, project_root: Path | str) -> None:
        self.project_root = Path(project_root)

    def load(self) -> Optional[ProjectContext]:
        """Parse the first found context file. Return None on any error."""
        candidates = ["project_description.md", "project_context.md", ".projectos/context.md"]
        try:
            target = next((self.project_root / c for c in candidates if (self.project_root / c).is_file()), None)
            if not target:
                return None
            raw = target.read_text(encoding="utf-8")
            words = raw.split()
            if len(words) > 2000:
                wc, idx, in_word = 0, 0, False
                for idx, c in enumerate(raw):
                    if c.isspace():
                        if in_word:
                            wc, in_word = wc + 1, False
                            if wc >= 2000:
                                break
                    else:
                        in_word = True
                content = raw[:idx]
            else:
                content = raw
            project_name, description, domain, curr = "", "", "", ""
            lists = {"tech stack": [], "key files": [], "conventions": [], "constraints": []}
            for line in content.splitlines():
                s = line.strip()
                if not s:
                    continue
                if s.startswith("# "):
                    project_name = s[2:].strip()
                elif s.startswith("## "):
                    curr = s[3:].strip().lower()
                elif curr in lists and (s.startswith("- ") or s.startswith("* ")):
                    lists[curr].append(s[2:].strip())
                elif curr == "description":
                    description += ("\n" if description else "") + s
                elif curr == "domain":
                    domain += ("\n" if domain else "") + s
            if not project_name:
                return None
            return ProjectContext(
                project_name=project_name,
                description=description.strip(),
                tech_stack=lists["tech stack"],
                primary_language=lists["tech stack"][0] if lists["tech stack"] else "",
                domain=domain.strip(),
                key_files=lists["key files"],
                conventions=lists["conventions"],
                constraints=lists["constraints"],
                context_file_path=str(target),
            )
        except Exception:
            return None

    def create_template(self, output_path: Path) -> None:
        """Write a blank project_description.md template to output_path."""
        content = (
            "# Project Name\n\n## Description\n[what this project does]\n\n"
            "## Tech Stack\n- Python 3.12\n- FastAPI\n- Supabase\n\n"
            "## Domain\n[business domain — e.g. \"Indian government procurement intelligence\"]\n\n"
            "## Key Files\n- src/main.py: entry point\n- src/search.py: core search logic\n\n"
            "## Conventions\n- Use dataclasses not Pydantic\n- All API responses use standard envelope\n\n"
            "## Constraints\n- Must work on free Gemini tier\n- No Docker dependency\n"
        )
        output_path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=f".tmp_{output_path.name}.", dir=str(output_path.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(content)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, output_path)
        except Exception:
            if os.path.exists(tmp):
                os.unlink(tmp)
            raise

    @staticmethod
    def to_system_prompt_injection(context: ProjectContext) -> str:
        """Return a formatted block for injection into agent system prompts."""
        return (
            f"--- PROJECT CONTEXT ---\n"
            f"Project: {context.project_name}\n"
            f"Domain: {context.domain}\n"
            f"Tech Stack: {', '.join(context.tech_stack)}\n"
            f"Key Files: {', '.join(context.key_files)}\n"
            f"Conventions: {' | '.join(context.conventions)}\n"
            f"Constraints: {' | '.join(context.constraints)}\n"
            f"--- END CONTEXT ---"
        )
