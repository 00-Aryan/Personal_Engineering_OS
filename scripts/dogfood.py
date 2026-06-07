"""Run a dogfooding orchestration cycle of ProjectOS on itself."""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Optional, Sequence

from core.events import AgentEvent, EventType
from core.model_provider import ModelProvider
from core.projectos import ProjectOS
from scripts.provider_setup import (
    CONFIG_PATH,
    PROVIDER_STATUS_PATH,
    available_provider_names,
    load_model_config,
    load_provider_status,
)


def patch_provider_complete() -> None:
    """Wrap all model provider complete() calls with a 15-second timeout."""
    from core.model_provider import GeminiProvider, OllamaProvider, OpenRouterProvider
    
    classes_to_patch = [GeminiProvider, OllamaProvider, OpenRouterProvider, DogfoodMockModelProvider]
    for cls in classes_to_patch:
        if getattr(cls, "_is_patched_for_dogfood", False):
            continue
        cls._is_patched_for_dogfood = True
        original_complete = cls.complete
        
        def make_wrapped(orig):
            def wrapped(self, *args, **kwargs):
                import threading
                import logging
                
                result_holder = []
                exception_holder = []
                event = threading.Event()
                timeout_occurred = False
                
                def target():
                    try:
                        res = orig(self, *args, **kwargs)
                        result_holder.append(res)
                    except Exception as e:
                        exception_holder.append(e)
                    finally:
                        event.set()
                
                thread = threading.Thread(target=target)
                thread.daemon = True
                thread.start()
                
                def on_timeout():
                    nonlocal timeout_occurred
                    timeout_occurred = True
                    agent_name = getattr(self, "agent_name", getattr(self, "_agent_name", "unknown"))
                    logging.getLogger("projectos.dogfood").warning(
                        f"Model provider complete() call for agent '{agent_name}' timed out after 15 seconds."
                    )
                    event.set()
                
                timer = threading.Timer(15.0, on_timeout)
                timer.daemon = True
                timer.start()
                
                event.wait()
                timer.cancel()
                
                if timeout_occurred:
                    return "MOCK_TIMEOUT_RESPONSE"
                
                if exception_holder:
                    raise exception_holder[0]
                
                return result_holder[0]
            return wrapped
            
        cls.complete = make_wrapped(original_complete)


class DogfoodMockModelProvider(ModelProvider):
    """Mock model provider used during ProjectOS dogfooding runs."""

    def __init__(self, agent_name: str, config_path: Any = None) -> None:
        """Initialize the mock provider with agent-specific settings."""
        self.agent_name = agent_name
        self._model_name = f"mock-{agent_name}"
        self._config_path = Path(config_path) if config_path else CONFIG_PATH
        self.token_budget = None
        self.cost_tracker = None
        self.rate_limiter = None
        self.circuit_breaker = None
        self.fallback_router = None
        self.tracer = None

    def get_model_name(self) -> str:
        """Return a deterministic model name."""
        return self._model_name

    def complete(
        self,
        prompt: str,
        system_prompt: str,
        max_tokens: int,
        agent_name: Optional[str] = None,
        token_budget: Optional[Any] = None,
        rate_limiter: Optional[Any] = None,
        circuit_breaker: Optional[Any] = None,
    ) -> str:
        """Return mocked agent completion response with MOCK OUTPUT labels."""
        if self.agent_name == "planning":
            return json.dumps([
                {
                    "id": "dogfood-task",
                    "title": "[MOCK OUTPUT] Dogfooding Task",
                    "type": "implementation",
                    "priority": "HIGH",
                    "estimated_complexity": "S",
                    "dependencies": [],
                    "acceptance_criteria": ["[MOCK OUTPUT] Helper file is generated"],
                    "agent_assignment": "code_writing_agent",
                    "blocked_by": None,
                    "file_path": "agents/dogfood_temp.py",
                }
            ])
        elif self.agent_name == "code_review":
            return json.dumps([
                {
                    "severity": "LOW",
                    "category": "logic",
                    "line_number": 10,
                    "description": "[MOCK OUTPUT] Mock suggestion: add type hints",
                    "suggested_fix": "[MOCK OUTPUT] Add -> None to function"
                }
            ])
        elif self.agent_name == "architecture":
            return json.dumps({
                "decision_required": "REST API vs CLI",
                "risks": ["[MOCK OUTPUT] Risk of over-complexity", "[MOCK OUTPUT] Risk of network overhead"],
                "alternatives": [
                    {"name": "CLI Only", "pros": ["[MOCK OUTPUT] Simple"], "cons": ["[MOCK OUTPUT] No remote access"]}
                ],
                "recommendation": "[MOCK OUTPUT] Expose a REST API for programmatic access",
                "adr_content": "# ADR: REST API vs CLI\n\n## Context\n[MOCK OUTPUT] External integrations need programmatic access.\n\n## Decision\nWe recommend exposing a REST API.\n",
                "confidence": "HIGH"
            })
        elif self.agent_name == "code_writing":
            return "[MOCK OUTPUT] def dogfood_helper() -> str:\n    return 'dogfood'\n"
        elif self.agent_name == "test":
            return "[MOCK OUTPUT] def test_dogfood_helper() -> None:\n    assert True\n"
        elif self.agent_name == "docs":
            return "# Dogfood Temp\n[MOCK OUTPUT] This is a temporary dogfood file."
        return "{}"

    def stream(self, prompt: str, system_prompt: str) -> Iterator[str]:
        """Return empty stream iterator."""
        return iter(())

    def health_check(self) -> bool:
        """Mock health check to always return True."""
        return True


def main(argv: Sequence[str] | None = None) -> int:
    """Run dogfood cycle on ProjectOS."""
    # Patch model providers to wrap complete() with a 15s timeout
    patch_provider_complete()

    parser = argparse.ArgumentParser(description="Run ProjectOS dogfooding check.")
    parser.add_argument("--config", type=Path, default=CONFIG_PATH)
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--state-dir", type=Path, default=None)
    parser.add_argument("--mock", action="store_true", help="Force mock provider mode.")
    parser.add_argument("--mock-only", action="store_true", help="Force mock-only provider mode.")
    args = parser.parse_args(argv)

    # Determine state directory path
    state_dir = args.state_dir if args.state_dir else args.project_root / ".projectos_state"

    # Decide if mock mode should be active
    use_mocks = args.mock or args.mock_only
    provider_name = "mock"
    if not use_mocks:
        status_file = state_dir / "provider_status.json"
        if not status_file.exists():
            use_mocks = True
        else:
            try:
                status = load_provider_status(status_file)
                providers = available_provider_names(status)
                if not providers:
                    use_mocks = True
                else:
                    provider_name = providers[0]
            except Exception:
                use_mocks = True

    print(f"Dogfooding run starting. Mode: {'Mock' if use_mocks else 'Live'} (Provider: {provider_name})")

    # Define model provider factory
    provider_factory = (
        (lambda agent_name, path: DogfoodMockModelProvider(agent_name, path))
        if use_mocks
        else None
    )

    # Report variables
    indexing_report = None
    code_review_findings = "Not executed"
    planning_output = "Not executed"
    architecture_recommendation = "Not executed"
    real_bugs: list[str] = []
    what_worked: list[str] = []
    what_needs_fixing: list[str] = []
    project_os = None

    def write_partial_report_and_exit():
        nonlocal project_os, indexing_report, code_review_findings, planning_output
        nonlocal architecture_recommendation, real_bugs, what_worked, what_needs_fixing
        print("Dogfooding session timed out (90 seconds). Writing partial report and exiting...")
        
        # Stop ProjectOS if running
        if project_os is not None:
            try:
                project_os.stop()
            except Exception as e:
                real_bugs.append(f"Daemon Stop: {e}")
        
        real_bugs.append("Dogfooding session: Timed out after 90 seconds")
        what_needs_fixing.append("Session timed out")

        # Generate dogfood_report.md
        try:
            report_dir = args.project_root / "docs"
            report_dir.mkdir(parents=True, exist_ok=True)
            report_path = report_dir / "dogfood_report.md"

            indexing_summary = "Failed to run indexing"
            if indexing_report:
                indexing_summary = (
                    f"Files indexed: {indexing_report['files_indexed']}\n"
                    f"Chunks created: {indexing_report['chunks_created']}\n"
                    f"Duration: {indexing_report['duration_ms']} ms"
                )

            bugs_section = "\n".join(f"- {b}" for b in real_bugs) if real_bugs else "None"
            worked_section = "\n".join(f"- {w}" for w in what_worked) if what_worked else "None"
            fixing_section = "\n".join(f"- {f}" for f in what_needs_fixing) if what_needs_fixing else "None"

            report_content = f"""# ProjectOS Dogfood Report
Date: {datetime.now(timezone.utc).isoformat()}
Provider: {provider_name}

## Indexing
{indexing_summary}

## Code Review Findings
{code_review_findings}

## Planning Output
{planning_output}

## Architecture Recommendation
{architecture_recommendation}

## Real Bugs Found
{bugs_section}

## What Worked
{worked_section}

## What Needs Fixing
{fixing_section}
"""
            report_path.write_text(report_content, encoding="utf-8")
            print(f"Dogfood partial report successfully written to {report_path}")
        except Exception as e:
            print(f"Failed to write dogfood report: {e}")
        
        os._exit(0)

    session_timer = threading.Timer(90.0, write_partial_report_and_exit)
    session_timer.daemon = True
    session_timer.start()

    # Initialize ProjectOS orchestrator
    project_os = ProjectOS(
        config_path=args.config,
        provider_factory=provider_factory,
        project_root=args.project_root,
        state_dir=state_dir,
    )


    # Phase A — Index own codebase
    try:
        project_os.code_indexer.clear()
        report_core = project_os.code_indexer.index_directory(args.project_root / "core")
        report_agents = project_os.code_indexer.index_directory(args.project_root / "agents")
        report_cli = project_os.code_indexer.index_directory(args.project_root / "cli")

        files_indexed = report_core.files_indexed + report_agents.files_indexed + report_cli.files_indexed
        chunks_created = report_core.chunks_created + report_agents.chunks_created + report_cli.chunks_created
        errors = report_core.errors + report_agents.errors + report_cli.errors
        duration_ms = report_core.duration_ms + report_agents.duration_ms + report_cli.duration_ms

        # Assert according to specs
        assert files_indexed >= 10, f"Expected at least 10 files indexed, got {files_indexed}"
        assert chunks_created >= 50, f"Expected at least 50 chunks created, got {chunks_created}"

        indexing_report = {
            "files_indexed": files_indexed,
            "chunks_created": chunks_created,
            "errors": errors,
            "duration_ms": duration_ms
        }

        # Save to state dir
        state_dir.mkdir(parents=True, exist_ok=True)
        (state_dir / "dogfood_indexing.json").write_text(json.dumps(indexing_report, indent=2), encoding="utf-8")
        what_worked.append("Phase A: Codebase Indexing completed and verified")
    except Exception as e:
        print(f"Phase A failed: {e}")
        real_bugs.append(f"Phase A: {e}")
        what_needs_fixing.append("Phase A: Indexing codebase failed")

    # Start ProjectOS daemon for remaining phases
    try:
        project_os.start()
    except Exception as e:
        print(f"Failed to start ProjectOS daemon: {e}")
        real_bugs.append(f"Daemon Start: {e}")
        what_needs_fixing.append("Daemon start failed")

    # Phase B — Self code review
    if project_os.stop_event.is_set() is False:
        try:
            target_file = args.project_root / "core" / "clone_agent.py"
            # Read decisions log size before triggering
            decisions_log_path = args.project_root / "decisions.log"
            decisions_before = decisions_log_path.read_text(encoding="utf-8") if decisions_log_path.exists() else ""
            decisions_count_before = len(decisions_before.splitlines())

            # Clear any old review files for this run to avoid picking up stale ones
            reviews_dir = args.project_root / "reviews"
            reviews_dir.mkdir(parents=True, exist_ok=True)

            event = AgentEvent(
                event_type=EventType.CODE_CHANGED,
                source_agent="dogfood_script",
                payload={"file_path": str(target_file)},
            )
            project_os.submit_event(event)

            # Wait for completion (timeout 120 seconds)
            timeout = 120.0
            start_time = time.monotonic()
            while time.monotonic() - start_time < timeout:
                if project_os.task_queue.get_pending_count() == 0:
                    break
                time.sleep(0.1)
            else:
                raise TimeoutError("Timeout waiting for self code review to complete")

            # Assertions
            review_files = list(reviews_dir.glob("clone_agent.py_*_review.md"))
            assert len(review_files) > 0, "No review file created in reviews/"
            review_files.sort(key=lambda p: p.stat().st_mtime)
            newest_review_file = review_files[-1]
            review_content = newest_review_file.read_text(encoding="utf-8")

            # Check decisions.log
            decisions_after = decisions_log_path.read_text(encoding="utf-8") if decisions_log_path.exists() else ""
            decisions_count_after = len(decisions_after.splitlines())
            assert decisions_count_after > decisions_count_before, "decisions.log did not record new entries"

            # Log findings
            label = "MOCK OUTPUT" if use_mocks else "REAL OUTPUT"
            code_review_findings = f"({label})\n\n{review_content}"
            what_worked.append("Phase B: Self Code Review completed and verified")
        except Exception as e:
            print(f"Phase B failed: {e}")
            real_bugs.append(f"Phase B: {e}")
            what_needs_fixing.append("Phase B: Self code review failed")
            code_review_findings = f"Failed to execute: {e}"

    # Phase C — Self planning
    if project_os.stop_event.is_set() is False:
        try:
            backlog_path = args.project_root / "backlog.md"
            backlog_before = backlog_path.read_text(encoding="utf-8") if backlog_path.exists() else ""

            event = AgentEvent(
                event_type=EventType.MANUAL_TRIGGER,
                source_agent="dogfood_script",
                payload={
                    "description": "Add structured JSON export for all agent output types so external tools can consume ProjectOS results",
                    "target_agent": "planning_agent",
                },
            )
            project_os.submit_event(event)

            # Wait for completion (timeout 30 seconds)
            timeout = 30.0
            start_time = time.monotonic()
            while time.monotonic() - start_time < timeout:
                if project_os.task_queue.get_pending_count() == 0:
                    break
                time.sleep(0.1)
            else:
                raise TimeoutError("Timeout waiting for self planning to complete")

            # Assertions
            backlog_after = backlog_path.read_text(encoding="utf-8") if backlog_path.exists() else ""
            new_backlog = backlog_after[len(backlog_before):]
            assert "PLAN-" in new_backlog, "backlog.md does not have new PLAN- IDs"

            label = "MOCK OUTPUT" if use_mocks else "REAL OUTPUT"
            planning_output = f"({label})\n\n{new_backlog}"
            what_worked.append("Phase C: Self Planning completed and verified")
        except Exception as e:
            print(f"Phase C failed: {e}")
            real_bugs.append(f"Phase C: {e}")
            what_needs_fixing.append("Phase C: Self planning failed")
            planning_output = f"Failed to execute: {e}"

    # Phase D — Self architecture review
    if project_os.stop_event.is_set() is False:
        try:
            adr_dir = args.project_root / "docs" / "adr"
            adr_dir.mkdir(parents=True, exist_ok=True)
            adr_files_before = set(adr_dir.glob("ADR-*.md"))

            event = AgentEvent(
                event_type=EventType.ARCHITECTURE_QUESTION,
                source_agent="dogfood_script",
                payload={
                    "question": "Should ProjectOS expose a REST API or stick with CLI only?",
                    "context": "Current architecture is CLI + daemon. External integrations need programmatic access.",
                    "target_agent": "architecture_agent",
                },
            )
            project_os.submit_event(event)

            # Wait for completion (timeout 30 seconds)
            timeout = 30.0
            start_time = time.monotonic()
            while time.monotonic() - start_time < timeout:
                if project_os.task_queue.get_pending_count() == 0:
                    break
                time.sleep(0.1)
            else:
                raise TimeoutError("Timeout waiting for architecture review to complete")

            # Assertions
            adr_files_after = set(adr_dir.glob("ADR-*.md"))
            new_adr_files = adr_files_after - adr_files_before
            assert len(new_adr_files) > 0, "No new ADR file created in docs/adr/"
            newest_adr_file = list(new_adr_files)[0]
            adr_content = newest_adr_file.read_text(encoding="utf-8")

            label = "MOCK OUTPUT" if use_mocks else "REAL OUTPUT"
            architecture_recommendation = f"({label})\n\n{adr_content}"
            what_worked.append("Phase D: Self Architecture Review completed and verified")
        except Exception as e:
            print(f"Phase D failed: {e}")
            real_bugs.append(f"Phase D: {e}")
            what_needs_fixing.append("Phase D: Self architecture review failed")
            architecture_recommendation = f"Failed to execute: {e}"

    # Stop ProjectOS
    try:
        project_os.stop()
    except Exception as e:
        print(f"Error stopping ProjectOS: {e}")
        real_bugs.append(f"Daemon Stop: {e}")

    # Generate dogfood_report.md
    try:
        report_dir = args.project_root / "docs"
        report_dir.mkdir(parents=True, exist_ok=True)
        report_path = report_dir / "dogfood_report.md"

        indexing_summary = "Failed to run indexing"
        if indexing_report:
            indexing_summary = (
                f"Files indexed: {indexing_report['files_indexed']}\n"
                f"Chunks created: {indexing_report['chunks_created']}\n"
                f"Duration: {indexing_report['duration_ms']} ms"
            )

        bugs_section = "\n".join(f"- {b}" for b in real_bugs) if real_bugs else "None"
        worked_section = "\n".join(f"- {w}" for w in what_worked) if what_worked else "None"
        fixing_section = "\n".join(f"- {f}" for f in what_needs_fixing) if what_needs_fixing else "None"

        report_content = f"""# ProjectOS Dogfood Report
Date: {datetime.now(timezone.utc).isoformat()}
Provider: {provider_name}

## Indexing
{indexing_summary}

## Code Review Findings
{code_review_findings}

## Planning Output
{planning_output}

## Architecture Recommendation
{architecture_recommendation}

## Real Bugs Found
{bugs_section}

## What Worked
{worked_section}

## What Needs Fixing
{fixing_section}
"""
        report_path.write_text(report_content, encoding="utf-8")
        print(f"Dogfood report successfully written to {report_path}")
    except Exception as e:
        print(f"Failed to write dogfood report: {e}")

    session_timer.cancel()
    return 0


if __name__ == "__main__":
    sys.exit(main())
