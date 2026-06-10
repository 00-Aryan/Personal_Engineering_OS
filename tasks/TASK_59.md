# TASK_59: Project Intake Agent + Phase Manager

## Engineering Context

When project_description.md appears in a project directory,
ProjectOS must:
1. Read it
2. Ask Aryan clarifying questions via Telegram
3. Wait for answers
4. Generate a phased plan
5. Send plan to Aryan for approval
6. Wait for approval
7. Execute Phase 1

This is the most important flow in Phase 9.
It's what transforms ProjectOS from a reactive tool into a
proactive project manager.

## Pre-conditions
Read core/notifications/telegram_notifier.py (TASK_57).
Read core/notifications/command_registry.py (TASK_58).
Read agents/planning_agent.py.
Read core/trigger_system.py.
Read AGENTS.md.

## Deliverables

### 1. agents/project_intake_agent.py

class ProjectIntakeAgent(BaseAgent):
  """
  Handles new project onboarding.
  
  Triggered when: project_description.md or project_context.md 
  appears in any watched directory.
  
  Flow:
  1. Read the description file
  2. Extract: project name, description, tech stack, goals
  3. Identify missing information
  4. Send questions to Aryan via Telegram
  5. Wait for /answer command (poll answers file, timeout: 24 hours)
  6. Generate phased plan using PlanningAgent logic
  7. Send plan to Aryan for approval
  8. Wait for /approve or /reject (timeout: 48 hours)
  9. On approval: write approved_plan.md and emit plan_approved event
  10. On reject: ask what to change, regenerate
  """
  
  SYSTEM_PROMPT = """
  You are a senior engineering project manager onboarding a new project.
  Your role is to understand the project deeply before planning.
  
  ALWAYS:
  - Ask for clarification on ambiguous requirements
  - Identify unstated technical constraints
  - Suggest phasing that delivers value incrementally
  - Keep phases to 5-7 tasks maximum
  
  NEVER:
  - Assume the tech stack if not stated
  - Plan more than 4 phases initially (add more later)
  - Include tasks that depend on unavailable resources
  
  {project_context}
  """
  
  INTAKE_QUESTIONS = [
    "What is the primary user of this system? (e.g. yourself, end users, API consumers)",
    "What is the most important thing to get working first?",
    "Are there existing files I should build on, or is this from scratch?",
    "What should I absolutely not change or break?",
    "Any deadline or time pressure on any part of this?",
  ]
  
  __init__(
    model_provider, logger, notifier, 
    memory_manager=None, context_retriever=None, 
    context_loader=None
  )
  
  handle(event: AgentEvent) -> AgentResult:
    Only handles event_type == NEW_PROJECT (new EventType to add)
    
    file_path = event.payload["context_file_path"]
    content = Path(file_path).read_text()
    
    # Generate intake_id
    intake_id = str(uuid.uuid4())[:8]
    
    # Ask questions
    notifier.send_project_started(
      project_name=detected_name,
      questions=self.INTAKE_QUESTIONS,
      intake_id=intake_id
    )
    
    # Poll for answers (check every 30s, timeout 24h)
    answers = self._wait_for_answers(intake_id, timeout_hours=24)
    If no answers after timeout:
      Send Telegram: "⏰ No answers received for {project_name}. 
                     Will proceed with best-effort planning."
      answers = {}
    
    # Generate plan
    plan = self._generate_phased_plan(content, answers)
    
    # Send plan for approval
    approval_id = str(uuid.uuid4())[:8]
    notifier.send_phase_complete(  # reuse for plan approval
      project_name=detected_name,
      phase_number=0,  (0 = planning phase)
      phase_name="Project Plan",
      files_changed=0,
      tests_passing=0,
      next_phase_summary=plan_summary,
      approval_id=approval_id
    )
    
    # Write plan to file regardless of approval
    Write .projectos/{project_name}/plan.md
    Write .projectos/{project_name}/phases.yaml
    
    Return AgentResult(success=True, output={"plan": plan, "approval_id": approval_id})
  
  _wait_for_answers(intake_id: str, timeout_hours: int) -> Dict:
    Check .projectos_state/intake_answers/{intake_id}.txt every 30s.
    Return parsed answers when file appears.
    Return {} on timeout.
  
  _generate_phased_plan(description: str, answers: Dict) -> Dict:
    Build prompt from description + answers.
    Call model to generate phases.
    Each phase: name, goal, tasks (5-7 max), success criteria.
    Return structured plan dict.

### 2. core/phase_manager.py

class PhaseStatus(Enum):
  PENDING = "pending"
  AWAITING_APPROVAL = "awaiting_approval"
  APPROVED = "approved"
  IN_PROGRESS = "in_progress"
  COMPLETE = "complete"
  REJECTED = "rejected"

@dataclass
class Phase:
  phase_id: str
  project_name: str
  phase_number: int
  phase_name: str
  goal: str
  tasks: List[Task]
  status: PhaseStatus
  approval_id: Optional[str]
  created_at: datetime
  started_at: Optional[datetime]
  completed_at: Optional[datetime]
  rejection_reason: Optional[str]

class PhaseManager:
  """
  Manages the lifecycle of project phases.
  
  State stored in .projectos/{project_name}/phase_state.yaml
  Updated atomically on every state transition.
  """
  
  __init__(
    notifier: TelegramNotifier,
    state_dir: Path,
    task_queue: TaskQueue
  )
  
  create_phases_from_plan(project_name: str, plan: Dict) -> List[Phase]:
    Convert plan dict to Phase objects.
    Write to phase_state.yaml.
    Return Phase list.
  
  get_current_phase(project_name: str) -> Optional[Phase]:
    Returns the first phase with status IN_PROGRESS or APPROVED.
  
  complete_phase(project_name: str, phase_id: str) -> None:
    Mark phase as COMPLETE.
    Find next phase.
    Set next phase to AWAITING_APPROVAL.
    Send Telegram notification.
  
  approve_phase(approval_id: str) -> bool:
    Find phase with this approval_id.
    Set status to APPROVED.
    Submit phase tasks to TaskQueue.
    Log: "Phase approved via Telegram: {approval_id}"
    Return True if found, False if not.
  
  reject_phase(approval_id: str, reason: str) -> bool:
    Find phase with this approval_id.
    Set status to REJECTED with reason.
    Send Telegram: "Phase rejected. Reason: {reason}. Replanning..."
    Emit NEW_PROJECT event to trigger replanning.
    Return True if found, False if not.
  
  get_all_phases_status(project_name: str) -> List[Dict]:
    Returns status summary for all phases.

### 3. Add NEW_PROJECT EventType

Update core/events.py:
  Add to EventType enum:
  NEW_PROJECT = "NEW_PROJECT"
  PLAN_APPROVED = "PLAN_APPROVED"
  PHASE_COMPLETE = "PHASE_COMPLETE"

### 4. Update core/trigger_system.py

Watch for project context files:
  In FileChangeHandler.on_created() (add if not exists):
    If filename in ["project_description.md", "project_context.md"]:
      Create AgentEvent(
        event_type=EventType.NEW_PROJECT,
        source_agent="trigger_system",
        payload={"context_file_path": str(event.src_path)}
      )
      Put on dispatcher queue.

### 5. Update core/clone_agent.py dispatch()

Add routing:
  NEW_PROJECT → project_intake_agent
  PLAN_APPROVED → phase_manager.approve_phase()
  PHASE_COMPLETE → phase_manager.complete_phase()

### 6. Update core/projectos.py
  Initialize ProjectIntakeAgent with notifier.
  Initialize PhaseManager with notifier and task_queue.
  Register both in AgentRegistry.
  Pass PhaseManager to CommandRegistry (wire /approve to phase approval).

### 7. tests/test_project_intake.py
  Mock notifier and model provider:
  - test_new_project_event_triggers_intake
  - test_intake_sends_questions_via_telegram
  - test_intake_waits_for_answers
  - test_intake_generates_plan_after_answers
  - test_intake_proceeds_on_timeout
  - test_phase_manager_creates_phases_from_plan
  - test_approve_phase_submits_tasks_to_queue
  - test_reject_phase_triggers_replanning
  - test_trigger_system_detects_project_description_file

## Constraints
- _wait_for_answers must NOT block the main thread
  Use threading.Event with timeout
- Phase state file must be updated atomically
- If notifier not configured: intake still works (no Telegram)
  Questions written to .projectos/{project}/questions.md instead
- Maximum 4 phases in initial plan
- Maximum 7 tasks per phase

## Verification
Full test suite. Write TASK_59_RESULT.md. Update tasks/README.md.
