# TASK_56: Task Decomposer

## Engineering Context

PlanningAgent currently creates tasks that are too large.
"Implement authentication for TenderIQ" is one task in the backlog.
That task touches 6+ files, takes hours, and has high hallucination risk.

The TaskDecomposer enforces atomicity: one task = one file maximum.
If PlanningAgent produces a large task, the Decomposer splits it
before it reaches any executing agent.

This is the primary defense against hallucination at the planning stage.

## Pre-conditions
Read agents/planning_agent.py fully.
Read core/events.py (Task dataclass).
Read TASK_55_RESULT.md (understand PreWriteValidator limits).

## Deliverables

### 1. core/task_decomposer.py

class ComplexityLevel(Enum):
  S = "S"  (< 2 hours, single function)
  M = "M"  (< 4 hours, single class or file section)
  TOO_LARGE = "TOO_LARGE"  (needs splitting)

@dataclass
class DecomposedTask:
  original_task_id: str
  subtasks: List[Task]
  decomposition_reason: str
  was_split: bool

class TaskDecomposer:
  """
  Validates and decomposes tasks from PlanningAgent.
  
  A task is TOO_LARGE if ANY of these are true:
  - dependencies list has > 3 items
  - acceptance_criteria list has > 5 items
  - description mentions > 2 distinct files
  - complexity is L or XL
  - description contains words: "entire", "all", "complete",
    "whole", "full", "every", "refactor", "migrate", "redesign"
  
  Splitting strategy:
  - Each file mentioned becomes a separate subtask
  - Each acceptance criterion becomes a candidate subtask
  - Dependencies are redistributed to maintain correct order
  """
  
  SPLIT_TRIGGER_WORDS = [
    "entire", "all", "complete", "whole", "full", "every",
    "refactor", "migrate", "redesign", "rewrite", "overhaul"
  ]
  
  MAX_ACCEPTANCE_CRITERIA = 5
  MAX_DEPENDENCIES = 3
  
  __init__(
    model_provider: ModelProvider,
    max_criteria: int = 5,
    max_dependencies: int = 3
  )
  
  should_split(task: Task) -> bool:
    Check all split conditions above.
    Returns True if ANY condition met.
  
  decompose(task: Task) -> DecomposedTask:
    If not should_split(task):
      Return DecomposedTask(
        original_task_id=task.id,
        subtasks=[task],
        decomposition_reason="Task within limits",
        was_split=False
      )
    
    Use model to split the task:
    prompt = f"""
    Split this task into smaller subtasks.
    Each subtask must:
    - Touch exactly ONE file
    - Have at most 3 acceptance criteria
    - Be completable independently (no shared state)
    - Have complexity S or M only
    
    Original task:
    {task.to_dict_str()}
    
    Output JSON array of subtasks. Same schema as input.
    """
    
    Parse response → List[Task]
    Assign new IDs: PLAN-{date}-{seq}-{sub_seq}
    Set parent_task_id on each subtask
    Return DecomposedTask(was_split=True, subtasks=subtasks)
  
  decompose_batch(tasks: List[Task]) -> List[Task]:
    For each task: decompose if needed
    Flatten all subtasks into single list
    Reassign sequence numbers
    Return flattened list

### 2. Update agents/planning_agent.py

After model returns task list:
  decomposer = TaskDecomposer(self.model_provider)
  all_tasks = decomposer.decompose_batch(generated_tasks)
  
  Log: f"Planning complete: {len(generated_tasks)} original tasks 
       → {len(all_tasks)} after decomposition"
  
  Write decomposed tasks to backlog.md (not originals)
  Emit BACKLOG_CHANGED for each decomposed task

### 3. tests/test_task_decomposer.py
  - test_small_task_not_split
  - test_task_with_trigger_word_flagged
  - test_task_with_many_criteria_flagged
  - test_decompose_preserves_original_id_in_subtasks
  - test_decompose_batch_flattens_correctly
  - test_split_task_gets_sequential_ids
  - test_dependency_preserved_after_split

## Constraints
- TaskDecomposer uses model only for splitting, not for validation
- Validation (should_split) is pure logic — no model calls
- Subtasks must preserve parent task's agent_assignment
- Max depth: tasks can be split once only (no recursive splitting)
- If model returns invalid JSON on split: log error, keep original task

## Verification
Full test suite. Write TASK_56_RESULT.md. Update tasks/README.md.
