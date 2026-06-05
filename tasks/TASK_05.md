# TASK_05: Code Writing Agent + Code Review Agent

## Pre-conditions
Read all agents/ files, core/ files, backlog.md structure before coding.

## Note
Two agents in one task because they are tightly coupled in the 
review loop. Writing without review is incomplete.

## Deliverables

### 1. agents/code_writing_agent.py

Implement CodeWritingAgent(BaseAgent):

**System Prompt for Model**:
"You are a senior Python software engineer with strong principles.
You write clean, well-structured, documented Python code.
You follow these rules strictly:
- Every function has a docstring
- Every function has type hints
- No hardcoded values — use config or environment
- Write the simplest code that satisfies requirements
- Output ONLY the code block, no explanation, no markdown fences"

**handle() method**
Input: AgentEvent with payload containing:
  task_id, file_path, task_description, acceptance_criteria, 
  existing_code (optional, for modifications)

Process:
1. If file_path exists, read it as existing_code context
2. Build prompt: task + criteria + existing code context
3. Call model_provider.complete()
4. Write output to file_path
5. Emit CODE_WRITTEN event with affected_files=[file_path]
6. Log decision: "Wrote [N] lines to [file_path] for task [task_id]"

### 2. agents/code_review_agent.py

Implement CodeReviewAgent(BaseAgent):

**System Prompt for Model**:
"You are a principal engineer conducting code review.
You are strict, thorough, and direct. No praise. Only issues.
For every issue found, output JSON with:
severity (CRITICAL/HIGH/MEDIUM/LOW),
category (security/logic/performance/style/test_coverage/docs),
line_number (or null),
description,
suggested_fix
Output a JSON array of issues. If no issues, output empty array []."

**handle() method**
Input: AgentEvent CODE_WRITTEN or CODE_CHANGED
payload contains: file_path, task_id (optional)

Process:
1. Read file at file_path
2. Call model_provider.complete() with file content
3. Parse JSON array of issues
4. Write review to reviews/[file_name]_[timestamp]_review.md
5. If any CRITICAL issues → set escalate=True in result
6. Emit REVIEW_DONE event
7. Update backlog task status if task_id provided

**Review report format**:
# Code Review: [filename]
Timestamp: [iso]
Task: [task_id or N/A]
Model: [model name from config]

## CRITICAL Issues
## HIGH Issues  
## MEDIUM Issues
## LOW Issues
## Summary
Total issues: X | Blockers: Y

### 3. reviews/ directory
Create empty directory with .gitkeep

### 4. tests/test_code_agents.py
- test_code_writing_creates_file
- test_code_writing_emits_code_written_event
- test_code_review_parses_issues_correctly
- test_code_review_critical_sets_escalate_true
- test_code_review_empty_array_no_escalation
- test_code_review_invalid_json_graceful
- test_review_report_written_to_reviews_dir

## Constraints
- CodeWritingAgent never overwrites without reading existing first
- CodeReviewAgent never modifies code — read only
- Review reports are immutable once written
- reviews/ directory must exist before any review runs

## Verification
Full test suite. Total count. Import checks for both agents.

## Result Template → TASK_05_RESULT.md
