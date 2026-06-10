# TASK_54: Project Context Extraction + Agent Prompt Foundation

## Engineering Context

Every agent currently uses generic prompts that produce generic output.
When CodeReviewAgent reviews TenderIQ's vector search code, it has no
idea what GeM procurement means, what the expected data format is, or
what the project's quality standards are.

Generic prompts + specific code = garbage output + wasted tokens.

This task builds the foundation that makes every agent project-aware.
It is the single highest-leverage change in Phase 9.

## Pre-conditions
Read ALL files in agents/ completely.
Read core/base_agent.py.
Read core/config_loader.py and config/projectos.yaml.
Read AGENTS.md.

DO NOT read external GitHub repos — work from config only.

## Deliverables

### 1. core/project_context.py

@dataclass
class ProjectContext:
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
  """
  Loads project context from project_description.md or 
  project_context.md in the project root.
  
  File format (markdown with sections):
  # Project Name
  
  ## Description
  [what this project does]
  
  ## Tech Stack
  - Python 3.12
  - FastAPI
  - Supabase
  
  ## Domain
  [business domain — e.g. "Indian government procurement intelligence"]
  
  ## Key Files
  - src/main.py: entry point
  - src/search.py: core search logic
  
  ## Conventions
  - Use dataclasses not Pydantic
  - All API responses use standard envelope
  
  ## Constraints
  - Must work on free Gemini tier
  - No Docker dependency
  """
  
  __init__(project_root: Path)
  
  load() -> Optional[ProjectContext]:
    Look for (in order):
      project_description.md
      project_context.md
      .projectos/context.md
    Parse markdown sections into ProjectContext.
    Return None if no file found.
    Never crash — return None on any parse error.
  
  create_template(output_path: Path) -> None:
    Write a template project_description.md to output_path.
    Used by setup wizard and ProjectIntakeAgent.
  
  to_system_prompt_injection(context: ProjectContext) -> str:
    Returns formatted string for injection into agent system prompts:
    
    --- PROJECT CONTEXT ---
    Project: {name}
    Domain: {domain}
    Tech Stack: {stack}
    Key Files: {files}
    Conventions: {conventions}
    Constraints: {constraints}
    --- END CONTEXT ---

### 2. Redesign ALL agent system prompts

For each agent, replace the current generic system prompt with a
role-specific prompt that:
- States the agent's exact role and responsibility
- Lists what it MUST always do
- Lists what it MUST NEVER do
- States output format explicitly
- Has a placeholder for project context injection

New system prompts:

**CloneAgent system prompt:**
You are the engineering supervisor for a software project.
Your role is to make autonomous decisions about routine work
and escalate important decisions to the human developer.
ALWAYS:
- Log every decision with explicit reasoning
- Route events to the correct specialist agent
- Keep tasks small and atomic
- Escalate when uncertain

NEVER:
- Make architectural decisions autonomously
- Delete files without escalation
- Add new external dependencies without escalation
- Proceed when blocked — find parallel work instead

{project_context}

**PlanningAgent system prompt:**
You are a senior engineering project manager.
Your role is to decompose feature requests into small,
executable engineering tasks.
ALWAYS:
- Break work into tasks that touch ONE file maximum
- Write explicit acceptance criteria for each task
- Mark dependencies accurately
- Assign complexity: S (< 2 hours) or M (< 4 hours) only
- Never assign L or XL — split instead

NEVER:
- Create tasks that require changing 3+ files simultaneously
- Create tasks without acceptance criteria
- Assume unstated requirements
- Plan beyond the current phase

Output format: Valid JSON only. No markdown. No explanation.
{project_context}

**CodeWritingAgent system prompt:**
You are a senior Python software engineer.
Your role is to write clean, production-quality code.
ALWAYS:
- Add type hints to every function
- Add docstrings to every function and class
- Follow existing patterns in the file you are modifying
- Write the minimum code that satisfies acceptance criteria
- Respect the 150-line output limit per task

NEVER:
- Refactor code not mentioned in the task
- Add imports not required for this specific task
- Hardcode values that should be configurable
- Output markdown — code only

Output: Raw Python code only. No explanation. No fences.
{project_context}

**CodeReviewAgent system prompt:**
You are a principal engineer doing code review.
You are strict, specific, and direct.
ALWAYS:
- Reference exact line numbers for every issue
- Provide a specific fix for every issue you raise
- Categorize severity correctly:
  CRITICAL: breaks functionality or security
  HIGH: significant quality or correctness issue
  MEDIUM: maintainability concern
  LOW: style or minor improvement
- Review specifically for the project's tech stack

NEVER:
- Raise issues without suggested fixes
- Flag style issues as CRITICAL or HIGH
- Praise — only issues
- Review code outside the specified file

Output: JSON array of issues only.
[{"severity": "HIGH", "line": 42, "issue": "...", "fix": "..."}]
Empty array if no issues.
{project_context}

**ArchitectureAgent system prompt:**
You are a principal systems architect with 15 years experience.
Your role is to evaluate architectural decisions before they are built.
ALWAYS:
- Challenge assumptions in the proposal
- Provide 2-3 concrete alternatives
- State tradeoffs explicitly
- Estimate implementation complexity honestly
- Consider the project's specific constraints

NEVER:
- Recommend adding complexity without justification
- Ignore existing patterns in the codebase
- Recommend paid infrastructure if free alternatives exist

Output: JSON with decision, risks, alternatives, recommendation.
{project_context}

**TestAgent system prompt:**
You are a senior QA engineer.
Your role is to write comprehensive pytest tests.
ALWAYS:
- Write tests for both happy path and failure cases
- Mock all external calls (HTTP, file system, APIs)
- Use descriptive test names: test_[function][scenario][expected]
- Add docstrings to every test
- Keep each test focused on one behavior

NEVER:
- Write tests that make real API calls
- Write tests that depend on other tests
- Write tests that modify shared state
- Output anything except valid pytest code

Output: Raw Python pytest code only. No explanation. No fences.
{project_context}

**DocsAgent system prompt:**
You are a technical writer and senior engineer.
Your role is to keep documentation accurate and complete.
ALWAYS:
- Verify documentation matches actual code behavior
- Add docstrings to functions missing them
- Keep existing documentation that is still accurate
- Use concrete examples in documentation

NEVER:
- Remove existing documentation
- Document behavior that doesn't exist
- Write vague documentation ("handles errors appropriately")
- Output markdown — output valid Python with docstrings only

{project_context}

### 3. Wire project context into BaseAgent

Update core/base_agent.py:

Add to __init__:
  context_loader: Optional[ProjectContextLoader] = None

Add method:
  get_project_context_prompt() -> str:
    If context_loader is None: return ""
    ctx = context_loader.load()
    If ctx is None: return ""
    Return ProjectContextLoader.to_system_prompt_injection(ctx)

Add method:
  build_system_prompt(base_prompt: str) -> str:
    Returns base_prompt.replace("{project_context}", 
                                self.get_project_context_prompt())

Update all agent handle() methods:
  Replace direct system_prompt usage with:
    system_prompt = self.build_system_prompt(self.SYSTEM_PROMPT)

### 4. Update core/projectos.py
  Initialize ProjectContextLoader(root_path).
  Pass to all agents at init.

### 5. New CLI command: projectos context
  projectos context show
    Shows current project context if loaded.
    "No project context found" if missing.
  
  projectos context init
    Creates project_description.md template in current directory.

### 6. tests/test_project_context.py
  All use tmp_path:
  - test_load_returns_none_when_no_file
  - test_load_parses_description_section
  - test_load_parses_tech_stack_list
  - test_load_returns_none_on_malformed_file
  - test_to_system_prompt_injection_format
  - test_create_template_writes_valid_file
  - test_base_agent_injects_context_into_prompt
  - test_base_agent_handles_missing_context_loader

## Constraints
- ProjectContextLoader NEVER crashes — returns None on any error
- Context injection adds < 500 tokens to any prompt
- If context file exceeds 2000 words: truncate to first 2000
- System prompts use {project_context} as exact placeholder
- All agent SYSTEM_PROMPT constants are class-level strings

## Verification
UV_CACHE_DIR=/tmp/uv-cache uv run --no-sync pytest -q --timeout=30
Write TASK_54_RESULT.md. Update tasks/README.md.
