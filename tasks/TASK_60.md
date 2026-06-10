# TASK_60: Multi-Project Rotation + Daily UX

## Engineering Context

Aryan has 5+ projects. ProjectOS needs to work on them in rotation,
not all simultaneously. Simultaneous multi-project execution
burns tokens rapidly and produces unfocused output.

Rotation strategy: one project at a time, one phase at a time.
When a phase completes: rotate to next project's pending phase.
Return to first project when all projects have had a turn.

Daily UX adds the morning brief and evening digest that
Aryan reads every day.

## Pre-conditions
Read core/phase_manager.py from TASK_59.
Read core/notifications/telegram_notifier.py from TASK_57.
Read core/project_config.py from TASK_19 (multi-project scaffold).
Read AGENTS.md.

## Deliverables

### 1. core/project_scheduler.py

class ProjectScheduler:
  """
  Rotates ProjectOS attention across multiple projects.
  
  Strategy: round-robin per phase completion
  - Project A Phase 1 → complete → notify Aryan
  - While waiting for approval: Project B Phase 1
  - Project A approved → resume Project A Phase 2
  - Otherwise continue Project B
  
  Never works on two projects simultaneously.
  Never starts next phase without approval.
  """
  
  __init__(
    phase_manager: PhaseManager,
    notifier: TelegramNotifier,
    state_dir: Path
  )
  
  register_project(
    project_name: str,
    project_root: Path,
    priority: int = 1
  ) -> None:
    Add project to rotation.
    Higher priority = more frequent attention.
  
  get_next_project() -> Optional[str]:
    Returns the project name that should receive attention next.
    Logic:
      Filter to projects with an IN_PROGRESS or APPROVED phase.
      If none: filter to projects with PENDING phases.
      Sort by: least recently worked on first.
      Return first.
  
  record_work_done(project_name: str) -> None:
    Update last_worked_at for project.
    Used by get_next_project() for fair rotation.

### 2. core/notifications/brief_generator.py

class BriefGenerator:
  """
  Generates morning brief and evening digest.
  Reads from: decisions.log, tasks/README.md equivalent per project,
  escalation_queue.md, blocked_tasks.md, token_usage.jsonl.
  """
  
  __init__(
    notifier: TelegramNotifier,
    state_dir: Path,
    project_roots: List[Path]
  )
  
  generate_morning_brief() -> str:
    Reads activity since last brief (stored in .projectos_state/last_brief.txt).
    For each active project:
      Count tasks completed overnight.
      Count files changed.
      Get current phase status.
    Count pending approvals across all projects.
    Count blocked tasks.
    Check token budget alerts.
    
    Send via notifier.send_morning_brief()
    Write to morning_brief.md in project root.
    Update last_brief.txt with current timestamp.
    Return formatted brief text.
  
  generate_evening_digest() -> str:
    Reads activity since morning brief.
    Collects: completed tasks, changed files,
    architectural decisions from docs/adr/,
    escalations that need attention.
    
    Send via notifier.send_evening_digest()
    Write to evening_digest.md in project root.
    Return formatted digest text.
  
  schedule_briefs(
    morning_time: str = "08:00",
    evening_time: str = "21:00"
  ) -> None:
    Use threading.Timer to schedule daily briefs.
    Morning brief at configured time.
    Evening digest at configured time.
    Times from config/projectos.yaml under new section:
      notifications:
        morning_brief_time: "08:00"
        evening_digest_time: "21:00"
        timezone: "Asia/Kolkata"

### 3. Add to config/projectos.yaml

```yaml
notifications:
  telegram_enabled: true
  morning_brief_time: "08:00"
  evening_digest_time: "21:00"
  timezone: "Asia/Kolkata"

projects:
  active:
    - name: tender_iq
      path: ~/June-2026/TenderIQ
      priority: 1
    - name: content_creation
      path: ~/June-2026/Content-Creation-Automation
      priority: 2
```

### 4. Update core/projectos.py
  Initialize ProjectScheduler with registered projects.
  Initialize BriefGenerator.
  Schedule briefs on start().
  
  Modify main event loop:
    After phase completion:
      scheduler.record_work_done(current_project)
      next_project = scheduler.get_next_project()
      If different project: switch context to next_project.

### 5. New CLI commands
  projectos projects list
    Shows all registered projects with their phase status.
  
  projectos projects add --name [name] --path [path]
    Registers a new project for ProjectOS attention.
  
  projectos brief
    Triggers morning brief generation immediately.
  
  projectos digest
    Triggers evening digest generation immediately.

### 6. tests/test_scheduler.py
  - test_round_robin_rotation
  - test_priority_affects_frequency
  - test_blocked_project_skipped
  - test_get_next_returns_none_when_nothing_active

### 7. tests/test_brief_generator.py
  - test_morning_brief_sent_via_notifier
  - test_evening_digest_sent_via_notifier
  - test_brief_written_to_file
  - test_last_brief_timestamp_updated
  - test_brief_handles_no_activity

## Constraints
- Never work on two projects simultaneously
- Brief generation must complete in < 10 seconds
- Scheduled briefs use threading.Timer (no external scheduler)
- If no projects registered: send brief with "No active projects"
- Brief time configuration is in IST (Asia/Kolkata)

## Verification
Full test suite. Write TASK_60_RESULT.md. Update tasks/README.md.
