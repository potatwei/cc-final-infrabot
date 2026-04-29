"""Integration-level checks for workflow-core adapter tools."""

from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from langchain_core.messages import AIMessage, ToolMessage

from agents.bedrock_graph import _formatter_node, _route_after_action
from run_agent import demo_workflow_payload
from tools.workflow_tools import (
    plan_deploy_service,
    plan_scale_service,
    plan_setup_infra,
    plan_stop_service,
    plan_teardown_infra,
    plan_teardown_service,
)


def sample_infrastructure() -> dict[str, object]:
    return {
        "cluster_arn": "arn:aws:ecs:us-east-1:123456789012:cluster/demo",
        "vpc_id": "vpc-123",
        "private_subnet_ids": ["subnet-123", "subnet-456"],
        "alb_listener_arn": (
            "arn:aws:elasticloadbalancing:us-east-1:123456789012:"
            "listener/app/demo/1/2"
        ),
        "ecs_task_security_group_id": "sg-123",
        "ecs_task_execution_role_arn": (
            "arn:aws:iam::123456789012:role/demo-project-ecs-task-execution-role"
        ),
        "ecr_url": "123456789012.dkr.ecr.us-east-1.amazonaws.com/demo",
    }


def sample_service_state() -> dict[str, object]:
    return {
        "port": 3000,
        "cpu": 256,
        "memory": 512,
        "replicas": 2,
        "image_tag": "v1",
        "environment_variables": {"NODE_ENV": "production"},
    }


class WorkflowAdapterToolTests(unittest.TestCase):
    def test_plan_setup_infra_returns_structured_plan(self) -> None:
        result = plan_setup_infra.invoke({"project_name": "demo-project"})

        self.assertEqual("success", result["status"])
        self.assertEqual("setup_infra", result["intent"])
        self.assertEqual(["infra/main.tf"], [item["path"] for item in result["files"]])
        self.assertTrue(result["requires_confirmation"])
        self.assertEqual(["setup_infrastructure"], [step["name"] for step in result["steps"]])
        self.assertEqual([], result["commands"])

    def test_plan_deploy_service_returns_structured_plan(self) -> None:
        result = plan_deploy_service.invoke(
            {
                "project_name": "demo-project",
                "infrastructure": sample_infrastructure(),
                "service_name": "api",
                "port": 3000,
                "cpu": 256,
                "memory": 512,
                "replicas": 2,
                "image_tag": "v1",
                "environment_variables": {"NODE_ENV": "production"},
            }
        )

        self.assertEqual("success", result["status"])
        self.assertEqual("deploy_service", result["intent"])
        self.assertEqual(["service/api/main.tf"], [item["path"] for item in result["files"]])
        self.assertEqual(
            [
                "build_container_image",
                "authenticate_to_ecr",
                "push_container_image",
                "apply_service_infrastructure",
            ],
            [step["name"] for step in result["steps"]],
        )
        self.assertEqual([], result["commands"])
        for step in result["steps"][:3]:
            self.assertNotIn("execution_payload", step)
        self.assertNotIn("execution_payload", result["steps"][3])

    def test_plan_deploy_service_returns_structured_error(self) -> None:
        result = plan_deploy_service.invoke(
            {
                "project_name": "demo-project",
                "infrastructure": {
                    "cluster_arn": sample_infrastructure()["cluster_arn"],
                },
            }
        )

        self.assertEqual("needs_input", result["status"])
        self.assertEqual("deploy_service", result["intent"])
        self.assertEqual([], result["files"])
        self.assertEqual([], result["steps"])
        self.assertIn("project_state.infrastructure keys", result["error"])
        self.assertEqual(["infrastructure"], result["missing_parameters"])

    def test_plan_deploy_service_without_infrastructure_returns_needs_input(self) -> None:
        result = plan_deploy_service.invoke({"project_name": "demo-project"})

        self.assertEqual("needs_input", result["status"])
        self.assertEqual("deploy_service", result["intent"])
        self.assertEqual(["infrastructure"], result["missing_parameters"])

    def test_plan_scale_service_returns_structured_plan(self) -> None:
        result = plan_scale_service.invoke(
            {
                "project_name": "demo-project",
                "infrastructure": sample_infrastructure(),
                "services": {"api": sample_service_state()},
                "service_name": "api",
                "replicas": 4,
            }
        )

        self.assertEqual("success", result["status"])
        self.assertEqual("scale_service", result["intent"])
        self.assertEqual(["service/api/main.tf"], [item["path"] for item in result["files"]])
        self.assertEqual(["scale_service"], [step["name"] for step in result["steps"]])

    def test_plan_stop_service_returns_structured_plan(self) -> None:
        result = plan_stop_service.invoke(
            {
                "project_name": "demo-project",
                "infrastructure": sample_infrastructure(),
                "services": {"api": sample_service_state()},
                "service_name": "api",
            }
        )

        self.assertEqual("success", result["status"])
        self.assertEqual("stop_service", result["intent"])
        self.assertEqual(["service/api/main.tf"], [item["path"] for item in result["files"]])
        self.assertEqual(["stop_service"], [step["name"] for step in result["steps"]])
        self.assertEqual([], result["commands"])

    def test_plan_teardown_service_accepts_sparse_service_state(self) -> None:
        result = plan_teardown_service.invoke(
            {
                "project_name": "demo-project",
                "infrastructure": sample_infrastructure(),
                "services": {"api": {}},
                "service_name": "api",
            }
        )

        self.assertEqual("success", result["status"])
        self.assertEqual("teardown_service", result["intent"])
        self.assertEqual(["service/api/main.tf"], [item["path"] for item in result["files"]])
        self.assertEqual(["teardown_service"], [step["name"] for step in result["steps"]])
        self.assertEqual([], result["commands"])
        self.assertTrue(
            any("filled missing stored service fields" in note for note in result["notes"])
        )

    def test_plan_teardown_infra_returns_structured_plan(self) -> None:
        result = plan_teardown_infra.invoke({"project_name": "demo-project"})

        self.assertEqual("success", result["status"])
        self.assertEqual("teardown_infra", result["intent"])
        self.assertEqual(["infra/main.tf"], [item["path"] for item in result["files"]])
        self.assertEqual(["teardown_infrastructure"], [step["name"] for step in result["steps"]])
        self.assertEqual([], result["commands"])

    def test_plan_stop_service_requires_explicit_service_name(self) -> None:
        result = plan_stop_service.invoke(
            {
                "project_name": "demo-project",
                "infrastructure": sample_infrastructure(),
                "services": {"api": sample_service_state()},
                "service_name": "",
            }
        )

        self.assertEqual("needs_input", result["status"])
        self.assertEqual("stop_service", result["intent"])
        self.assertIn("requires entities['service_name']", result["error"])
        self.assertEqual(["service_name"], result["missing_parameters"])

    def test_plan_stop_service_without_state_returns_structured_needs_input(self) -> None:
        result = plan_stop_service.invoke(
            {
                "project_name": "demo-project",
                "service_name": "api",
            }
        )

        self.assertEqual("needs_input", result["status"])
        self.assertEqual("stop_service", result["intent"])
        self.assertEqual(["infrastructure", "services"], result["missing_parameters"])

    def test_plan_teardown_service_without_state_returns_structured_needs_input(self) -> None:
        result = plan_teardown_service.invoke(
            {
                "project_name": "demo-project",
                "service_name": "api",
            }
        )

        self.assertEqual("needs_input", result["status"])
        self.assertEqual("teardown_service", result["intent"])
        self.assertIn("project_state.infrastructure", result["error"])

    @patch("tools.workflow_tools.build_execution_plan", side_effect=RuntimeError("boom"))
    def test_internal_planning_failure_returns_generic_error(self, _mock_plan) -> None:
        result = plan_setup_infra.invoke({"project_name": "demo-project"})

        self.assertEqual("error", result["status"])
        self.assertEqual("setup_infra", result["intent"])
        self.assertEqual([], result["files"])
        self.assertEqual([], result["steps"])
        self.assertEqual("Internal workflow planning failure.", result["error"])
        self.assertEqual([], result["missing_parameters"])


class FormatterNodeTests(unittest.TestCase):
    def test_formatter_preserves_workflow_plan_fields(self) -> None:
        tool_result = plan_setup_infra.invoke({"project_name": "demo-project"})
        state = {
            "task_id": "task-123",
            "messages": [
                ToolMessage(
                    content=json.dumps(tool_result),
                    tool_call_id="tool-1",
                    name="plan_setup_infra",
                ),
                AIMessage(content="Planned infrastructure setup."),
            ]
        }

        formatted = _formatter_node(state)["final_payload"]

        self.assertEqual("success", formatted["status"])
        self.assertEqual("task-123", formatted["task_id"])
        self.assertEqual("setup_infra", formatted["intent"])
        self.assertEqual(tool_result["files"], formatted["files"])
        self.assertEqual(tool_result["commands"], formatted["commands"])
        self.assertEqual(tool_result["steps"], formatted["steps"])
        self.assertEqual(tool_result["notes"], formatted["notes"])
        self.assertTrue(formatted["requires_confirmation"])
        self.assertIsNone(formatted["error"])

    def test_formatter_preserves_deploy_commands(self) -> None:
        tool_result = plan_deploy_service.invoke(
            {
                "project_name": "demo-project",
                "infrastructure": sample_infrastructure(),
                "service_name": "api",
                "port": 3000,
                "cpu": 256,
                "memory": 512,
                "replicas": 2,
                "image_tag": "v1",
                "environment_variables": {"NODE_ENV": "production"},
            }
        )
        state = {
            "task_id": "task-456",
            "messages": [
                ToolMessage(
                    content=json.dumps(tool_result),
                    tool_call_id="tool-1b",
                    name="plan_deploy_service",
                ),
                AIMessage(content="Planned service deploy."),
            ]
        }

        formatted = _formatter_node(state)["final_payload"]

        self.assertEqual("success", formatted["status"])
        self.assertEqual("task-456", formatted["task_id"])
        self.assertEqual(tool_result["commands"], formatted["commands"])
        self.assertEqual([], formatted["commands"])

    def test_formatter_marks_structured_tool_errors(self) -> None:
        tool_result = plan_deploy_service.invoke(
            {
                "project_name": "demo-project",
                "infrastructure": {
                    "cluster_arn": sample_infrastructure()["cluster_arn"],
                },
            }
        )
        state = {
            "messages": [
                ToolMessage(
                    content=json.dumps(tool_result),
                    tool_call_id="tool-2",
                    name="plan_deploy_service",
                ),
                AIMessage(content="Planning failed."),
            ]
        }

        formatted = _formatter_node(state)["final_payload"]

        self.assertEqual("needs_input", formatted["status"])
        self.assertEqual("deploy_service", formatted["intent"])
        self.assertEqual([], formatted["files"])
        self.assertEqual([], formatted["steps"])
        self.assertEqual(tool_result["error"], formatted["error"])
        self.assertEqual(["infrastructure"], formatted["missing_parameters"])
        self.assertIn("setup_infra first", formatted["explanation"])

    def test_formatter_preserves_internal_error_status(self) -> None:
        tool_result = {
            "status": "error",
            "intent": "deploy_service",
            "files": [],
            "commands": [],
            "notes": [],
            "requires_confirmation": False,
            "steps": [],
            "error": "Internal workflow planning failure.",
            "missing_parameters": [],
        }
        state = {
            "messages": [
                ToolMessage(
                    content=json.dumps(tool_result),
                    tool_call_id="tool-3",
                    name="plan_deploy_service",
                ),
                AIMessage(content="Planning failed internally."),
            ]
        }

        formatted = _formatter_node(state)["final_payload"]

        self.assertEqual("error", formatted["status"])
        self.assertEqual("deploy_service", formatted["intent"])
        self.assertEqual("Internal workflow planning failure.", formatted["error"])
        self.assertEqual([], formatted["missing_parameters"])
        self.assertEqual("Internal workflow planning failure.", formatted["explanation"])

    def test_formatter_guides_missing_service_name(self) -> None:
        tool_result = plan_stop_service.invoke(
            {
                "project_name": "demo-project",
                "infrastructure": sample_infrastructure(),
                "services": {"api": sample_service_state()},
                "service_name": "",
            }
        )
        state = {
            "messages": [
                ToolMessage(
                    content=json.dumps(tool_result),
                    tool_call_id="tool-4",
                    name="plan_stop_service",
                ),
                AIMessage(content="Planning failed."),
            ]
        }

        formatted = _formatter_node(state)["final_payload"]

        self.assertEqual("needs_input", formatted["status"])
        self.assertEqual(["service_name"], formatted["missing_parameters"])
        self.assertIn("explicit service_name", formatted["explanation"])

    def test_formatter_discards_mixed_artifacts_after_blocking_deploy_failure(self) -> None:
        blocking_tool_result = {
            "status": "needs_input",
            "intent": "deploy_service",
            "files": [],
            "commands": [],
            "notes": [],
            "requires_confirmation": False,
            "steps": [],
            "error": "intent 'deploy_service' requires non-empty project_state.infrastructure",
            "missing_parameters": [],
        }
        misleading_tool_result = {
            "status": "success",
            "intent": "deploy_service",
            "files": [{"path": "service/demo/main.tf", "content": "fake", "source_step": "x"}],
            "commands": [{"step_name": "build_container_image", "command": {"binary": "docker"}}],
            "notes": ["fake success"],
            "requires_confirmation": True,
            "steps": [{"name": "apply_service_infrastructure"}],
            "error": None,
            "missing_parameters": [],
        }
        state = {
            "messages": [
                ToolMessage(
                    content=json.dumps(blocking_tool_result),
                    tool_call_id="tool-5",
                    name="plan_deploy_service",
                ),
                ToolMessage(
                    content=json.dumps(misleading_tool_result),
                    tool_call_id="tool-6",
                    name="plan_deploy_service",
                ),
                AIMessage(content="Deployment plan succeeded."),
            ]
        }

        formatted = _formatter_node(state)["final_payload"]

        self.assertEqual("needs_input", formatted["status"])
        self.assertEqual("deploy_service", formatted["intent"])
        self.assertEqual([], formatted["files"])
        self.assertEqual([], formatted["commands"])
        self.assertEqual([], formatted["steps"])
        self.assertEqual(["infrastructure"], formatted["missing_parameters"])
        self.assertIn("setup_infra first", formatted["explanation"])

    def test_route_after_action_stops_on_structured_needs_input(self) -> None:
        tool_result = plan_deploy_service.invoke({"project_name": "demo-project"})
        state = {
            "messages": [
                ToolMessage(
                    content=json.dumps(tool_result),
                    tool_call_id="tool-7",
                    name="plan_deploy_service",
                )
            ]
        }

        self.assertEqual("formatter", _route_after_action(state))


class RunAgentDemoTests(unittest.TestCase):
    def test_demo_workflow_payload_deploy_success(self) -> None:
        payload = demo_workflow_payload("deploy-success")

        self.assertEqual("success", payload["status"])
        self.assertEqual("deploy_service", payload["intent"])
        self.assertEqual([], payload["commands"])

    def test_demo_workflow_payload_deploy_needs_infra(self) -> None:
        payload = demo_workflow_payload("deploy-needs-infra")

        self.assertEqual("needs_input", payload["status"])
        self.assertEqual(["infrastructure"], payload["missing_parameters"])

    def test_demo_workflow_payload_stop_needs_service_name(self) -> None:
        payload = demo_workflow_payload("stop-needs-service-name")

        self.assertEqual("needs_input", payload["status"])
        self.assertEqual(["service_name"], payload["missing_parameters"])


if __name__ == "__main__":
    unittest.main()
