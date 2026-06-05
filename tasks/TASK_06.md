# TASK_06: Test Agent + Documentation Agent

## Deliverables

### 1. agents/test_agent.py

Implement TestAgent(BaseAgent):

**System Prompt**:
"You are a senior QA engineer and Python testing expert.
You write comprehensive pytest unit tests.
Rules:
- Every test has a clear docstring explaining what it tests
- Use pytest fixtures, not unittest
- Mock all external calls (HTTP, file system where appropriate)
- Test both happy path and failure cases
- Output ONLY valid Python test code, no markdown"

**handle() method**
Input: CODE_WRITTEN or CODE_CHANGED event
payload: file_path, task_id (optional)

Process:
1. Read source file at file_path
2. Generate test file path: tests/test_[filename].py
3. If test file exists, read it (context for additions, not replacement)
4. Generate tests via model
5. Write to test file
6. Run tests: subprocess.run(["python3", "-m", "pytest", test_file])
7. Parse pytest output for pass/fail count
8. Emit TESTS_DONE event with payload: 
   {passed, failed, test_file, source_file}
9. If failed > 0 → escalate=True

### 2. agents/docs_agent.py

Implement DocsAgent(BaseAgent):

**System Prompt**:
"You are a technical writer and senior engineer.
You update documentation to reflect code changes.
Rules:
- Never remove existing documentation
- Add docstrings to any function missing them
- Update README sections that reference changed code
- Output ONLY the updated file content, no explanation"

**handle() method**
Input: TESTS_DONE or CODE_WRITTEN or DOCS_UPDATED request
payload: file_path, readme_sections (optional list)

Process:
1. Read source file
2. Identify missing docstrings
3. Add docstrings via model
4. Write updated file
5. If README.md exists and readme_sections provided, update those
6. Emit DOCS_UPDATED event
7. Log: "Updated docs for [file_path], added [N] docstrings"

### 3. tests/test_test_agent.py
- test_generates_test_file_for_source
- test_runs_pytest_after_generating
- test_failed_tests_set_escalate
- test_emits_tests_done_event_with_counts

### 4. tests/test_docs_agent.py
- test_adds_missing_docstrings
- test_never_removes_existing_docs
- test_emits_docs_updated_event

## Verification
Full test suite. All agents importable.

## Result Template → TASK_06_RESULT.md
