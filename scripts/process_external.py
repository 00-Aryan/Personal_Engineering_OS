"""Run verification of processing an external project using ProjectOS."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from pathlib import Path
from typing import Any, Iterator, Optional, Sequence
from unittest.mock import patch

from core.events import AgentEvent, EventType
from core.model_provider import ModelProvider
from core.project_config import ProjectConfig, ProjectRegistry
from core.projectos import MultiProjectOS, ProjectOS
from scripts.dogfood import DogfoodMockModelProvider


def main(argv: Sequence[str] | None = None) -> int:
    """Run external project verification."""
    parser = argparse.ArgumentParser(description="Process a simulated external project.")
    parser.add_argument("--config", type=Path, default=Path("config/models.yaml").resolve())
    parser.add_argument("--scratch-dir", type=Path, default=Path("scratch").resolve())
    args = parser.parse_args(argv)

    args.scratch_dir.mkdir(parents=True, exist_ok=True)
    temp_project_root = args.scratch_dir / "external_project_temp"
    temp_registry_path = args.scratch_dir / "projects_temp.yaml"

    # Clean up any residual files
    if temp_project_root.exists():
        shutil.rmtree(temp_project_root)
    if temp_registry_path.exists():
        temp_registry_path.unlink()

    temp_project_root.mkdir(parents=True, exist_ok=True)
    (temp_project_root / "agents").mkdir(parents=True, exist_ok=True)
    (temp_project_root / "reviews").mkdir(parents=True, exist_ok=True)
    (temp_project_root / "tests").mkdir(parents=True, exist_ok=True)

    print("Registering external project...")
    registry = ProjectRegistry(temp_registry_path)
    project_config = ProjectConfig.create(
        name="external_temp",
        root_path=temp_project_root,
        models_config=args.config,
    )
    registry.add_project(project_config)

    # Patch from_project_config to use DogfoodMockModelProvider
    original_from_config = ProjectOS.from_project_config

    def custom_from_config(config: ProjectConfig, provider_factory: Any = None) -> ProjectOS:
        return original_from_config(
            config,
            provider_factory=lambda agent_name, path: DogfoodMockModelProvider(agent_name, path),
        )

    print("Starting MultiProjectOS daemon...")
    with patch.object(ProjectOS, "from_project_config", side_effect=custom_from_config):
        multi_os = MultiProjectOS(registry)
        multi_os.start()

        time.sleep(1)
        instance = multi_os.instances.get("external_temp")
        if not instance:
            print("Error: external_temp instance did not start.")
            multi_os.stop()
            return 1

        try:
            # Write a dummy code file in the external project root
            code_file = temp_project_root / "agents" / "helper.py"
            code_file.write_text("def assist() -> str:\n    return 'help'\n", encoding="utf-8")

            # Submit CODE_CHANGED event to the external project instance
            event = AgentEvent(
                event_type=EventType.CODE_CHANGED,
                source_agent="process_external_script",
                payload={"file_path": str(code_file)},
            )
            print(f"Submitting event {event.event_id} to external project...")
            instance.submit_event(event)

            # Wait for queue to become idle
            timeout = 15.0
            start_time = time.monotonic()
            while time.monotonic() - start_time < timeout:
                if instance.task_queue.get_pending_count() == 0:
                    break
                time.sleep(0.1)
            else:
                print("Timeout waiting for task queue to become idle.")
                multi_os.stop()
                return 1

            # Brief sleep to ensure completion finalization
            time.sleep(0.5)

        except Exception as error:
            print(f"Error during execution: {error}")
            multi_os.stop()
            return 1

        finally:
            multi_os.stop()

    # Verification checks
    reviews_dir = temp_project_root / "reviews"
    review_reports = list(reviews_dir.glob("helper.py*_review.md"))
    state_dir = temp_project_root / ".projectos_state"

    if not review_reports:
        print("Verification failed: review report was not generated inside external project.")
        _cleanup(temp_project_root, temp_registry_path)
        return 1

    if not state_dir.exists():
        print("Verification failed: .projectos_state was not created inside external project.")
        _cleanup(temp_project_root, temp_registry_path)
        return 1

    # Cleanup temporary directories and registry
    _cleanup(temp_project_root, temp_registry_path)

    print("EXTERNAL PROJECT RUN: PASSED")
    return 0


def _cleanup(project_root: Path, registry_path: Path) -> None:
    """Clean up files created during processing."""
    if project_root.exists():
        shutil.rmtree(project_root)
    if registry_path.exists():
        registry_path.unlink()


if __name__ == "__main__":
    sys.exit(main())
