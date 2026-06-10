from __future__ import annotations
import json
import logging
import re
from dataclasses import dataclass
from enum import Enum
from typing import List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from core.model_provider import ModelProvider
    from agents.planning_agent import Task

logger = logging.getLogger("core.task_decomposer")

class ComplexityLevel(Enum):
    S = "S"
    M = "M"
    TOO_LARGE = "TOO_LARGE"

@dataclass
class DecomposedTask:
    original_task_id: str
    subtasks: List[Task]
    decomposition_reason: str
    was_split: bool

class TaskDecomposer:
    """Validates and decomposes tasks from PlanningAgent."""
    
    SPLIT_TRIGGER_WORDS = [
        "entire", "all", "complete", "whole", "full", "every",
        "refactor", "migrate", "redesign", "rewrite", "overhaul"
    ]
    
    MAX_ACCEPTANCE_CRITERIA = 5
    MAX_DEPENDENCIES = 3
    
    def __init__(
        self,
        model_provider: ModelProvider,
        max_criteria: int = 5,
        max_dependencies: int = 3,
    ) -> None:
        self.model_provider = model_provider
        self.max_criteria = max_criteria
        self.max_dependencies = max_dependencies

    def should_split(self, task: Task) -> bool:
        # Check if already a subtask to prevent recursion
        if getattr(task, "parent_task_id", None) is not None:
            return False
        parts = task.id.split("-")
        if len(parts) > 3:
            return False
            
        if len(task.dependencies) > self.max_dependencies:
            return True
            
        if len(task.acceptance_criteria) > self.max_criteria:
            return True
            
        if task.complexity in ("L", "XL"):
            return True
            
        # Clean trigger words in title (case-insensitive whole-word check)
        title_lower = task.title.lower()
        words = set(re.findall(r"\b[a-zA-Z]+\b", title_lower))
        if any(word in words for word in self.SPLIT_TRIGGER_WORDS):
            return True
            
        # Check distinct files mentioned in description (task.title)
        file_candidates = re.findall(r"\b[\w\-./]+\.[a-zA-Z0-9]{2,5}\b", title_lower)
        distinct_files = set()
        for cand in file_candidates:
            # Skip if extension is purely numeric to avoid version numbers (e.g. 1.0, 2.0)
            p = cand.split(".")
            if p[-1].isdigit():
                continue
            distinct_files.add(cand)
            
        if len(distinct_files) > 2:
            return True
            
        return False

    def decompose(self, task: Task) -> DecomposedTask:
        from agents.planning_agent import Task
        
        if not self.should_split(task):
            return DecomposedTask(
                original_task_id=task.id,
                subtasks=[task],
                decomposition_reason="Task within limits",
                was_split=False
            )
            
        prompt = f"""Split this task into smaller subtasks.
Each subtask must:
- Touch exactly ONE file
- Have at most 3 acceptance criteria
- Be completable independently (no shared state)
- Have complexity S or M only

Original task:
{task.to_dict_str()}

Output JSON array of subtasks. Same schema as input."""

        system_prompt = (
            "You are an expert software developer and project manager. "
            "Your job is to split complex tasks into small, bite-sized subtasks "
            "that can be worked on independently. Return valid JSON only, representing "
            "a JSON array of subtasks."
        )
        
        try:
            model_output = self.model_provider.complete(
                prompt,
                system_prompt,
                2048
            )
            try:
                parsed = json.loads(model_output)
            except json.JSONDecodeError:
                cleaned = model_output.strip()
                if cleaned.startswith("```json"):
                    cleaned = cleaned[7:]
                if cleaned.endswith("```"):
                    cleaned = cleaned[:-3]
                parsed = json.loads(cleaned.strip())
                
            if isinstance(parsed, dict) and "tasks" in parsed:
                task_items = parsed["tasks"]
            elif isinstance(parsed, list):
                task_items = parsed
            else:
                raise ValueError("Model did not return a list or tasks dictionary")
                
            if not isinstance(task_items, list):
                raise ValueError("Parsed tasks is not a list")
                
            subtasks = []
            for i, item in enumerate(task_items):
                sub_id = f"{task.id}-{str(i + 1).zfill(3)}"
                
                sub_title = item.get("title") or item.get("description")
                if not sub_title:
                    sub_title = f"Subtask {i + 1} for {task.title}"
                    
                sub_type = item.get("type", task.type).lower()
                sub_priority = item.get("priority", task.priority).upper()
                
                sub_complexity = item.get("complexity") or item.get("estimated_complexity") or "M"
                sub_complexity = sub_complexity.upper()
                if sub_complexity not in ("S", "M"):
                    sub_complexity = "M"
                    
                ac = item.get("acceptance_criteria")
                if not isinstance(ac, list):
                    ac = [ac] if ac else []
                ac = [str(x) for x in ac if x]
                
                agent_assignment = task.agent_assignment
                blocked_by = item.get("blocked_by")
                file_path = item.get("file_path") or task.file_path
                
                if i == 0:
                    deps = task.dependencies.copy()
                else:
                    deps = [f"{task.id}-{str(i).zfill(3)}"]
                    
                sub_task = Task(
                    id=sub_id,
                    title=sub_title,
                    type=sub_type,
                    priority=sub_priority,
                    complexity=sub_complexity,
                    dependencies=deps,
                    acceptance_criteria=ac,
                    agent_assignment=agent_assignment,
                    blocked_by=blocked_by,
                    file_path=file_path,
                    created_at=task.created_at,
                    status=task.status,
                    parent_task_id=task.id
                )
                subtasks.append(sub_task)
                
            return DecomposedTask(
                original_task_id=task.id,
                subtasks=subtasks,
                decomposition_reason="Task exceeded complexity limits",
                was_split=True
            )
            
        except Exception as e:
            logger.error("Failed to decompose task %s: %s", task.id, e)
            return DecomposedTask(
                original_task_id=task.id,
                subtasks=[task],
                decomposition_reason=f"Model decomposition failed: {e}",
                was_split=False
            )

    def decompose_batch(self, tasks: List[Task]) -> List[Task]:
        from agents.planning_agent import Task
        
        if not tasks:
            return []
            
        first_id = tasks[0].id
        parts = first_id.split("-")
        if len(parts) >= 3 and parts[0] == "PLAN":
            date_stamp = parts[1]
            try:
                start_seq = int(parts[2])
            except ValueError:
                start_seq = 1
        else:
            date_stamp = tasks[0].created_at[:10].replace("-", "")
            start_seq = 1
            
        decomposed_tasks = []
        for task in tasks:
            decomposed_tasks.append(self.decompose(task))
            
        final_tasks = []
        id_mapping = {}
        current_seq = start_seq
        
        for decomp in decomposed_tasks:
            old_base_id = decomp.original_task_id
            new_base_id = f"PLAN-{date_stamp}-{str(current_seq).zfill(3)}"
            
            if not decomp.was_split:
                task = decomp.subtasks[0]
                new_task = Task(
                    id=new_base_id,
                    title=task.title,
                    type=task.type,
                    priority=task.priority,
                    complexity=task.complexity,
                    dependencies=task.dependencies.copy(),
                    acceptance_criteria=task.acceptance_criteria.copy(),
                    agent_assignment=task.agent_assignment,
                    blocked_by=task.blocked_by,
                    file_path=task.file_path,
                    created_at=task.created_at,
                    status=task.status,
                    parent_task_id=task.parent_task_id
                )
                final_tasks.append(new_task)
                id_mapping[old_base_id] = new_base_id
            else:
                for i, subtask in enumerate(decomp.subtasks):
                    new_sub_id = f"{new_base_id}-{str(i + 1).zfill(3)}"
                    new_task = Task(
                        id=new_sub_id,
                        title=subtask.title,
                        type=subtask.type,
                        priority=subtask.priority,
                        complexity=subtask.complexity,
                        dependencies=subtask.dependencies.copy(),
                        acceptance_criteria=subtask.acceptance_criteria.copy(),
                        agent_assignment=subtask.agent_assignment,
                        blocked_by=subtask.blocked_by,
                        file_path=subtask.file_path,
                        created_at=subtask.created_at,
                        status=subtask.status,
                        parent_task_id=new_base_id
                    )
                    final_tasks.append(new_task)
                    id_mapping[subtask.id] = new_sub_id
                id_mapping[old_base_id] = f"{new_base_id}-{str(len(decomp.subtasks)).zfill(3)}"
            current_seq += 1
            
        for task in final_tasks:
            task.dependencies = [id_mapping.get(dep, dep) for dep in task.dependencies]
            if task.blocked_by in id_mapping:
                task.blocked_by = id_mapping[task.blocked_by]
                
        return final_tasks
