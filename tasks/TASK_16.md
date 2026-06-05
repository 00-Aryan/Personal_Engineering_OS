# TASK_16: Git Integration

## Purpose
Auto-commit clean code after review passes. Track what the system
built, when, and why. Create a complete audit trail in git history.

## Pre-conditions
Read agents/code_review_agent.py, core/clone_agent.py fully.

## Deliverables

### 1. core/git_manager.py

class GitManager:
  __init__(repo_path: Path)
  
  is_git_repo() -> bool
  
  stage_file(file_path: Path) -> bool
    git add file_path. Returns False if fails, never raises.
  
  commit(message: str, author: str = "ProjectOS") -> Optional[str]
    git commit -m message --author "ProjectOS <projectos@local>"
    Returns commit hash if successful, None if nothing to commit.
  
  get_diff(file_path: Path) -> str
    git diff HEAD -- file_path. Returns empty string if no diff.
  
  get_last_commit_hash() -> Optional[str]
    Returns short hash of HEAD, None if no commits.
  
  create_branch(name: str) -> bool
    git checkout -b name. Returns False if fails.

### 2. Update agents/code_review_agent.py
  Accept git_manager: Optional[GitManager] = None param.
  After writing review report:
    If no CRITICAL issues AND git_manager present:
      Stage the reviewed file.
      Commit with message:
      "projectos: auto-review passed — [filename] [short_review_summary]"
    If CRITICAL issues:
      Do not commit. Log "commit skipped: critical issues found"

### 3. Update core/projectos.py
  Initialize GitManager(repo_path=Path(".")).
  Only pass to CodeReviewAgent if is_git_repo() returns True.
  Log warning if not a git repo.

### 4. New CLI command: projectos git-log
  Shows last 10 auto-commits made by ProjectOS.
  Filter: git log --author="ProjectOS" --oneline -10
  Print formatted output.

### 5. tests/test_git_manager.py
  Use tmp_path with git init for all tests:
  - test_is_git_repo_true_after_init
  - test_is_git_repo_false_without_init
  - test_stage_file_succeeds
  - test_commit_returns_hash
  - test_commit_returns_none_when_nothing_staged
  - test_get_diff_returns_empty_on_clean
  - test_get_diff_returns_content_after_change

## Constraints
- GitManager uses subprocess.run, never shell=True
- All git commands must have timeout=30
- Never commit to main/master directly if on those branches 
  (log warning and skip commit)
- If git is not installed → is_git_repo() returns False gracefully

## Verification
Full test suite. Write TASK_16_RESULT.md. Update tasks/README.md.
