from __future__ import annotations
import json
import unittest
from unittest.mock import Mock
from agents.planning_agent import Task
from core.task_decomposer import TaskDecomposer, ComplexityLevel

class TaskDecomposerTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.model_provider = Mock()
        self.decomposer = TaskDecomposer(self.model_provider)

    def test_small_task_not_split(self) -> None:
        task = Task(
            id="PLAN-20260611-001",
            title="Update one line in main.py",
            type="feature",
            priority="MEDIUM",
            complexity="S",
            dependencies=[],
            acceptance_criteria=["Change is made"],
            agent_assignment="code_writing_agent",
            blocked_by=None,
            file_path="main.py",
            created_at="2026-06-11T00:00:00Z",
            status="PENDING"
        )
        self.assertFalse(self.decomposer.should_split(task))
        decomp = self.decomposer.decompose(task)
        self.assertFalse(decomp.was_split)
        self.assertEqual(len(decomp.subtasks), 1)
        self.assertEqual(decomp.subtasks[0].id, "PLAN-20260611-001")
        self.assertEqual(decomp.decomposition_reason, "Task within limits")

    def test_task_with_trigger_word_flagged(self) -> None:
        task = Task(
            id="PLAN-20260611-001",
            title="Refactor the entire authentication system",
            type="feature",
            priority="MEDIUM",
            complexity="S",
            dependencies=[],
            acceptance_criteria=["Refactor done"],
            agent_assignment="code_writing_agent",
            blocked_by=None,
            file_path="auth.py",
            created_at="2026-06-11T00:00:00Z",
            status="PENDING"
        )
        self.assertTrue(self.decomposer.should_split(task))

    def test_task_with_many_criteria_flagged(self) -> None:
        task = Task(
            id="PLAN-20260611-001",
            title="Implement dashboard UI",
            type="feature",
            priority="MEDIUM",
            complexity="S",
            dependencies=[],
            acceptance_criteria=["AC1", "AC2", "AC3", "AC4", "AC5", "AC6"],
            agent_assignment="code_writing_agent",
            blocked_by=None,
            file_path="dashboard.py",
            created_at="2026-06-11T00:00:00Z",
            status="PENDING"
        )
        self.assertTrue(self.decomposer.should_split(task))

    def test_decompose_preserves_original_id_in_subtasks(self) -> None:
        task = Task(
            id="PLAN-20260611-001",
            title="Rewrite database layer and logger",
            type="feature",
            priority="HIGH",
            complexity="L",
            dependencies=[],
            acceptance_criteria=["Done"],
            agent_assignment="code_writing_agent",
            blocked_by=None,
            file_path=None,
            created_at="2026-06-11T00:00:00Z",
            status="PENDING"
        )
        
        mocked_response = json.dumps([
            {
                "title": "Update db.py database layer",
                "type": "feature",
                "complexity": "S",
                "acceptance_criteria": ["db.py updated"],
                "file_path": "db.py"
            },
            {
                "title": "Update logger.py logging layer",
                "type": "feature",
                "complexity": "M",
                "acceptance_criteria": ["logger.py updated"],
                "file_path": "logger.py"
            }
        ])
        self.model_provider.complete.return_value = mocked_response
        
        decomp = self.decomposer.decompose(task)
        self.assertTrue(decomp.was_split)
        self.assertEqual(decomp.original_task_id, "PLAN-20260611-001")
        self.assertEqual(len(decomp.subtasks), 2)
        
        for subtask in decomp.subtasks:
            self.assertEqual(subtask.parent_task_id, "PLAN-20260611-001")
            self.assertEqual(subtask.agent_assignment, "code_writing_agent")

    def test_split_task_gets_sequential_ids(self) -> None:
        task = Task(
            id="PLAN-20260611-005",
            title="Overhaul auth.py and users.py",
            type="feature",
            priority="HIGH",
            complexity="XL",
            dependencies=[],
            acceptance_criteria=["Done"],
            agent_assignment="code_writing_agent",
            blocked_by=None,
            file_path=None,
            created_at="2026-06-11T00:00:00Z",
            status="PENDING"
        )
        
        mocked_response = json.dumps([
            {"title": "Subtask A", "complexity": "S"},
            {"title": "Subtask B", "complexity": "M"},
            {"title": "Subtask C", "complexity": "S"}
        ])
        self.model_provider.complete.return_value = mocked_response
        
        decomp = self.decomposer.decompose(task)
        self.assertTrue(decomp.was_split)
        self.assertEqual(len(decomp.subtasks), 3)
        self.assertEqual(decomp.subtasks[0].id, "PLAN-20260611-005-001")
        self.assertEqual(decomp.subtasks[1].id, "PLAN-20260611-005-002")
        self.assertEqual(decomp.subtasks[2].id, "PLAN-20260611-005-003")

    def test_dependency_preserved_after_split(self) -> None:
        task = Task(
            id="PLAN-20260611-002",
            title="Redesign whole engine.py",
            type="feature",
            priority="HIGH",
            complexity="XL",
            dependencies=["PLAN-20260611-001"],
            acceptance_criteria=["Done"],
            agent_assignment="code_writing_agent",
            blocked_by=None,
            file_path=None,
            created_at="2026-06-11T00:00:00Z",
            status="PENDING"
        )
        
        mocked_response = json.dumps([
            {"title": "Subtask 1", "complexity": "S"},
            {"title": "Subtask 2", "complexity": "S"}
        ])
        self.model_provider.complete.return_value = mocked_response
        
        decomp = self.decomposer.decompose(task)
        self.assertTrue(decomp.was_split)
        
        # Subtask 1 inherits original task dependency
        self.assertEqual(decomp.subtasks[0].dependencies, ["PLAN-20260611-001"])
        # Subtask 2 depends on Subtask 1 to maintain correct order
        self.assertEqual(decomp.subtasks[1].dependencies, ["PLAN-20260611-002-001"])

    def test_decompose_batch_flattens_correctly(self) -> None:
        task_small1 = Task(
            id="PLAN-20260611-001",
            title="Small task 1",
            type="feature",
            priority="MEDIUM",
            complexity="S",
            dependencies=[],
            acceptance_criteria=["AC1"],
            agent_assignment="code_writing_agent",
            blocked_by=None,
            file_path=None,
            created_at="2026-06-11T00:00:00Z",
            status="PENDING"
        )
        task_large = Task(
            id="PLAN-20260611-002",
            title="Redesign complete DB",
            type="feature",
            priority="HIGH",
            complexity="XL",
            dependencies=[],
            acceptance_criteria=["Done"],
            agent_assignment="code_writing_agent",
            blocked_by=None,
            file_path=None,
            created_at="2026-06-11T00:00:00Z",
            status="PENDING"
        )
        task_small2 = Task(
            id="PLAN-20260611-003",
            title="Small task 2",
            type="feature",
            priority="MEDIUM",
            complexity="S",
            dependencies=["PLAN-20260611-002"],
            acceptance_criteria=["AC2"],
            agent_assignment="code_writing_agent",
            blocked_by=None,
            file_path=None,
            created_at="2026-06-11T00:00:00Z",
            status="PENDING"
        )
        
        mocked_response = json.dumps([
            {"title": "Subtask A", "complexity": "S"},
            {"title": "Subtask B", "complexity": "M"}
        ])
        self.model_provider.complete.return_value = mocked_response
        
        batch = [task_small1, task_large, task_small2]
        flattened = self.decomposer.decompose_batch(batch)
        
        # Original: 3 tasks.
        # After split: task_small1 (not split), task_large (split to 2 subtasks), task_small2 (not split).
        # Total: 4 tasks.
        self.assertEqual(len(flattened), 4)
        
        # Check reassigned IDs:
        # Task 1: PLAN-20260611-001
        self.assertEqual(flattened[0].id, "PLAN-20260611-001")
        # Task 2 (split): PLAN-20260611-002-001, PLAN-20260611-002-002
        self.assertEqual(flattened[1].id, "PLAN-20260611-002-001")
        self.assertEqual(flattened[2].id, "PLAN-20260611-002-002")
        # Task 3 (not split): PLAN-20260611-003
        self.assertEqual(flattened[3].id, "PLAN-20260611-003")
        
        # Check dependencies mapping:
        # task_small2 originally depended on PLAN-20260611-002.
        # PLAN-20260611-002 was split, so task_small2 should depend on the last subtask of the split:
        # PLAN-20260611-002-002
        self.assertEqual(flattened[3].dependencies, ["PLAN-20260611-002-002"])

if __name__ == "__main__":
    unittest.main()
