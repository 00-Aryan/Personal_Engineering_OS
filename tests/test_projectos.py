import sys
import unittest
from unittest.mock import Mock, patch
from pathlib import Path
from core.projectos import ProjectOS

class TestProjectOSGracefulShutdown(unittest.TestCase):
    @patch("sys.exit")
    def test_shutdown_handler_cleans_up_and_exits(self, exit_mock: Mock) -> None:
        with patch("core.projectos.TriggerSystem"), \
             patch("core.projectos.PersistenceManager"), \
             patch("core.projectos.ProviderHealthMonitor"), \
             patch("core.projectos.AlertManager"), \
             patch("core.projectos.TaskQueue"), \
             patch("core.projectos.CloneAgent"), \
             patch("core.projectos.ProjectOS._initialize_providers") as init_provs_mock, \
             patch("core.projectos.ProjectOS._load_config") as load_config_mock:
             
            load_config_mock.return_value = {
                "project": {
                    "name": "test-project",
                },
                "agents": {
                    agent_name: {
                        "provider": "gemini",
                        "model": "gemini-1.5-flash",
                    }
                    for agent_name in ["clone", "planning", "code_writing", "code_review", "architecture", "test", "docs", "project_intake"]
                }
            }
            mock_provider = Mock()
            init_provs_mock.return_value = {
                agent_name: mock_provider
                for agent_name in ["clone", "planning", "code_writing", "code_review", "architecture", "test", "docs", "project_intake"]
            }
            
            
            runtime = ProjectOS(config_path=Path("fake_config.yaml"), project_name="test-project")
            runtime._shutdown_handler(15, None)
            
            runtime.trigger_system.stop.assert_called_once()
            runtime.provider_health_monitor.stop.assert_called_once()
            runtime.task_queue.shutdown.assert_called_once_with(wait=True)
            runtime.alert_manager.stop.assert_called_once()
            runtime.persistence_manager.snapshot_status.assert_called_once()
            
            exit_mock.assert_called_once_with(0)

if __name__ == "__main__":
    unittest.main()
