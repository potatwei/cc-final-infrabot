"""Route-level tests for backend task creation flows."""

from __future__ import annotations

import os
import sys
import unittest
import uuid
from dataclasses import dataclass
from typing import Any
from unittest.mock import patch

BACKEND_ROOT = os.path.join(
    os.path.dirname(__file__),
    "..",
    "infrapilot-backend",
)
if BACKEND_ROOT not in sys.path:
    sys.path.append(BACKEND_ROOT)

try:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api.routes import tasks as tasks_route

    FASTAPI_AVAILABLE = True
except ModuleNotFoundError:  # pragma: no cover - environment dependent
    FastAPI = None
    TestClient = None
    tasks_route = None
    FASTAPI_AVAILABLE = False


@dataclass
class FakeTask:
    """Simple task stand-in for route tests without a real database."""

    user_prompt: str
    status: str = "pending"
    code_payload: dict[str, Any] | None = None
    task_id: str = ""
    created_at: Any = None

    def __post_init__(self) -> None:
        if not self.task_id:
            self.task_id = str(uuid.uuid4())


class FakeSession:
    """Minimal session double for create_task route tests."""

    def __init__(self) -> None:
        self.added: list[FakeTask] = []

    def add(self, obj: FakeTask) -> None:
        self.added.append(obj)

    def commit(self) -> None:
        return None

    def refresh(self, obj: FakeTask) -> None:
        return None

    def query(self, _model):
        return FakeQuery(self.added)


class FakeQuery:
    """Tiny query object that ignores SQLAlchemy filter expressions."""

    def __init__(self, items: list[FakeTask]) -> None:
        self.items = items

    def filter(self, *_args, **_kwargs):
        return self

    def first(self):
        return self.items[0] if self.items else None


class FakeTool:
    """Small invoke wrapper for patching lookup/validation tools in tests."""

    def __init__(self, result: dict[str, Any]) -> None:
        self.result = result

    def invoke(self, _payload: dict[str, Any]) -> dict[str, Any]:
        return dict(self.result)


@unittest.skipUnless(FASTAPI_AVAILABLE, "fastapi backend dependencies are not installed")
class BackendTaskRouteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.app = FastAPI()
        self.app.include_router(tasks_route.router, prefix="/api")
        self.fake_db = FakeSession()
        self.app.dependency_overrides[tasks_route.get_db] = lambda: self.fake_db
        self.client = TestClient(self.app)

    def tearDown(self) -> None:
        self.app.dependency_overrides.clear()

    @patch.object(tasks_route, "Task", FakeTask)
    @patch.object(tasks_route, "build_graph")
    def test_post_task_discovery_mode_returns_collecting_input(
        self,
        mock_build_graph,
    ) -> None:
        graph_calls: list[dict[str, Any]] = []

        class FakeGraph:
            def invoke(self, payload: dict[str, Any]) -> dict[str, Any]:
                graph_calls.append(payload)
                return {
                    "final_payload": {
                        "status": "needs_input",
                        "task_id": payload["task_id"],
                        "mode": "discovery",
                        "intent": "deploy_ec2_instance",
                        "selected_tool": "generate_ec2_terraform",
                        "required_inputs": ["instance_type"],
                        "recommended_inputs": ["region"],
                        "optional_inputs": ["instance_name", "vpc_cidr", "public_subnet_cidr"],
                        "defaults": {"region": "us-east-1"},
                        "provided_inputs": {"region": "us-east-1"},
                        "missing_inputs": ["instance_type"],
                        "missing_parameters": ["instance_type"],
                        "ready_to_execute": False,
                        "precheck_tool": None,
                        "files": [],
                        "commands": [],
                        "notes": [],
                        "requires_confirmation": False,
                        "steps": [],
                        "error": None,
                        "explanation": "Need the EC2 instance type before execution.",
                    }
                }

        mock_build_graph.return_value = FakeGraph()

        with patch.dict(
            tasks_route.CORE_TOOLS_BY_NAME,
            {
                "validate_aws_region": FakeTool(
                    {
                        "status": "success",
                        "intent": "validate_aws_region",
                        "valid": True,
                        "notes": [],
                        "explanation": "valid",
                    }
                )
            },
            clear=False,
        ):
            response = self.client.post(
                "/api/task",
                json={"user_prompt": "Create an EC2 instance in us-east-1", "mode": "discovery"},
            )

        self.assertEqual(200, response.status_code)
        body = response.json()
        self.assertEqual("collecting_input", body["status"])
        self.assertEqual("discovery", body["code_payload"]["mode"])
        self.assertEqual(["instance_type"], body["code_payload"]["missing_inputs"])
        self.assertFalse(body["code_payload"]["ready_to_execute"])
        self.assertEqual("discovery", graph_calls[0]["mode"])
        self.assertEqual(body["task_id"], graph_calls[0]["task_id"])

    @patch.object(tasks_route, "Task", FakeTask)
    @patch.object(tasks_route, "build_graph")
    def test_discovery_normalization_extracts_region_and_validates_inputs(
        self,
        mock_build_graph,
    ) -> None:
        class FakeGraph:
            def invoke(self, payload: dict[str, Any]) -> dict[str, Any]:
                return {
                    "final_payload": {
                        "status": "needs_input",
                        "task_id": payload["task_id"],
                        "mode": "discovery",
                        "intent": "deploy_ec2_instance",
                        "selected_tool": "generate_ec2_terraform",
                        "provided_inputs": {"instance_type": "t3.micro"},
                        "missing_inputs": ["region"],
                        "ready_to_execute": False,
                        "precheck_tool": None,
                        "files": [],
                        "commands": [],
                        "notes": [],
                        "requires_confirmation": False,
                        "steps": [],
                        "error": None,
                        "explanation": "Region is missing.",
                    }
                }

        mock_build_graph.return_value = FakeGraph()

        with patch.dict(
            tasks_route.CORE_TOOLS_BY_NAME,
            {
                "validate_aws_region": FakeTool(
                    {
                        "status": "success",
                        "intent": "validate_aws_region",
                        "valid": True,
                        "notes": [],
                        "explanation": "valid region",
                    }
                ),
                "validate_ec2_instance_type": FakeTool(
                    {
                        "status": "success",
                        "intent": "validate_ec2_instance_type",
                        "valid": True,
                        "available_in_region": True,
                        "notes": [],
                        "explanation": "valid instance type",
                    }
                ),
            },
            clear=False,
        ):
            response = self.client.post(
                "/api/task",
                json={
                    "user_prompt": "create a t3.micro ec2 instance in us-east-1",
                    "mode": "discovery",
                },
            )

        self.assertEqual(200, response.status_code)
        body = response.json()
        self.assertEqual("ready_to_execute", body["status"])
        self.assertTrue(body["code_payload"]["ready_to_execute"])
        self.assertEqual(
            {"instance_type": "t3.micro", "region": "us-east-1"},
            body["code_payload"]["provided_inputs"],
        )
        self.assertEqual([], body["code_payload"]["missing_inputs"])

    @patch.object(tasks_route, "Task", FakeTask)
    @patch.object(tasks_route, "build_graph")
    def test_discovery_normalization_rejects_invalid_region(
        self,
        mock_build_graph,
    ) -> None:
        class FakeGraph:
            def invoke(self, payload: dict[str, Any]) -> dict[str, Any]:
                return {
                    "final_payload": {
                        "status": "needs_input",
                        "task_id": payload["task_id"],
                        "mode": "discovery",
                        "intent": "deploy_vpc_network",
                        "selected_tool": "generate_vpc_terraform",
                        "provided_inputs": {"region": "east-1"},
                        "missing_inputs": [],
                        "ready_to_execute": True,
                        "precheck_tool": None,
                        "files": [],
                        "commands": [],
                        "notes": [],
                        "requires_confirmation": False,
                        "steps": [],
                        "error": None,
                        "explanation": "Ready.",
                    }
                }

        mock_build_graph.return_value = FakeGraph()

        with patch.dict(
            tasks_route.CORE_TOOLS_BY_NAME,
            {
                "validate_aws_region": FakeTool(
                    {
                        "status": "success",
                        "intent": "validate_aws_region",
                        "valid": False,
                        "notes": ["Try one of: us-east-1"],
                        "explanation": "east-1 is not valid.",
                    }
                )
            },
            clear=False,
        ):
            response = self.client.post(
                "/api/task",
                json={"user_prompt": "create vpc in east-1", "mode": "discovery"},
            )

        self.assertEqual(200, response.status_code)
        body = response.json()
        self.assertEqual("collecting_input", body["status"])
        self.assertEqual("east-1", body["code_payload"]["provided_inputs"]["region"])
        self.assertIn("region", body["code_payload"]["missing_inputs"])
        self.assertIn("does not look valid", body["code_payload"]["explanation"])

    @patch.object(tasks_route, "Task", FakeTask)
    @patch.object(tasks_route, "build_graph")
    def test_discovery_extracts_invalid_region_candidate_from_prompt(
        self,
        mock_build_graph,
    ) -> None:
        class FakeGraph:
            def invoke(self, payload: dict[str, Any]) -> dict[str, Any]:
                return {
                    "final_payload": {
                        "status": "needs_input",
                        "task_id": payload["task_id"],
                        "mode": "discovery",
                        "intent": "deploy_vpc_network",
                        "selected_tool": "generate_vpc_terraform",
                        "provided_inputs": {},
                        "missing_inputs": [],
                        "ready_to_execute": True,
                        "precheck_tool": None,
                        "files": [],
                        "commands": [],
                        "notes": [],
                        "requires_confirmation": False,
                        "steps": [],
                        "error": None,
                        "explanation": "Ready.",
                    }
                }

        mock_build_graph.return_value = FakeGraph()

        with patch.dict(
            tasks_route.CORE_TOOLS_BY_NAME,
            {
                "validate_aws_region": FakeTool(
                    {
                        "status": "success",
                        "intent": "validate_aws_region",
                        "valid": False,
                        "notes": ["Try one of: us-east-1"],
                        "explanation": "east-1 is not valid.",
                    }
                )
            },
            clear=False,
        ):
            response = self.client.post(
                "/api/task",
                json={"user_prompt": "create vpc in east-1", "mode": "discovery"},
            )

        self.assertEqual(200, response.status_code)
        body = response.json()
        self.assertEqual("collecting_input", body["status"])
        self.assertEqual("east-1", body["code_payload"]["provided_inputs"]["region"])
        self.assertIn("region", body["code_payload"]["missing_inputs"])
        self.assertIn("does not look valid", body["code_payload"]["explanation"])

    @patch.object(tasks_route, "Task", FakeTask)
    @patch.object(tasks_route, "build_graph")
    def test_post_task_execution_mode_returns_awaiting_confirmation(
        self,
        mock_build_graph,
    ) -> None:
        graph_calls: list[dict[str, Any]] = []

        class FakeGraph:
            def invoke(self, payload: dict[str, Any]) -> dict[str, Any]:
                graph_calls.append(payload)
                return {
                    "final_payload": {
                        "status": "success",
                        "task_id": payload["task_id"],
                        "intent": "deploy_vpc_network",
                        "files": [{"path": "main.tf", "content": "resource {}", "type": "terraform"}],
                        "commands": [],
                        "notes": [],
                        "requires_confirmation": True,
                        "steps": [],
                        "error": None,
                        "missing_parameters": [],
                        "explanation": "Prepared the VPC plan.",
                    }
                }

        mock_build_graph.return_value = FakeGraph()

        response = self.client.post(
            "/api/task",
            json={"user_prompt": "Create a VPC in us-east-1"},
        )

        self.assertEqual(200, response.status_code)
        body = response.json()
        self.assertEqual("awaiting_confirmation", body["status"])
        self.assertEqual("deploy_vpc_network", body["code_payload"]["intent"])
        self.assertEqual("execution", graph_calls[0]["mode"])
        self.assertEqual(body["task_id"], graph_calls[0]["task_id"])

    @patch.object(tasks_route, "Task", FakeTask)
    def test_continue_task_with_partial_inputs_keeps_collecting_input(self) -> None:
        existing_task = FakeTask(
            user_prompt="Create an EC2 instance",
            status="collecting_input",
            code_payload={
                "status": "needs_input",
                "task_id": "task-continue-1",
                "mode": "discovery",
                "intent": "deploy_ec2_instance",
                "selected_tool": "generate_ec2_terraform",
                "required_inputs": ["instance_type", "region", "instance_name"],
                "recommended_inputs": [],
                "optional_inputs": ["vpc_cidr", "public_subnet_cidr"],
                "defaults": {"custom_context": "demo"},
                "provided_inputs": {},
                "missing_inputs": ["instance_type", "region", "instance_name"],
                "missing_parameters": ["instance_type", "region", "instance_name"],
                "ready_to_execute": False,
                "precheck_tool": None,
                "files": [],
                "commands": [],
                "notes": [],
                "requires_confirmation": False,
                "steps": [],
                "error": None,
                "explanation": "Need more information.",
            },
            task_id="task-continue-1",
        )
        self.fake_db.add(existing_task)

        response = self.client.post(
            "/api/task/task-continue-1/continue",
            json={"provided_inputs": {"instance_type": "t3.micro"}},
        )

        self.assertEqual(200, response.status_code)
        body = response.json()
        self.assertEqual("collecting_input", body["status"])
        self.assertEqual(
            {"instance_type": "t3.micro"},
            body["code_payload"]["provided_inputs"],
        )
        self.assertEqual(
            ["region", "instance_name"],
            body["code_payload"]["missing_inputs"],
        )
        self.assertFalse(body["code_payload"]["ready_to_execute"])

    @patch.object(tasks_route, "Task", FakeTask)
    def test_continue_task_with_structured_input_executes_tool(self) -> None:
        existing_task = FakeTask(
            user_prompt="Create an EC2 instance in us-east-1",
            status="collecting_input",
            code_payload={
                "status": "needs_input",
                "task_id": "task-continue-2",
                "mode": "discovery",
                "intent": "deploy_ec2_instance",
                "selected_tool": "generate_ec2_terraform",
                "required_inputs": ["instance_type"],
                "recommended_inputs": ["region"],
                "optional_inputs": ["instance_name", "vpc_cidr", "public_subnet_cidr"],
                "defaults": {
                    "region": "us-east-1",
                    "instance_name": "infrapilot-ec2",
                    "vpc_cidr": "10.50.0.0/16",
                    "public_subnet_cidr": "10.50.1.0/24",
                },
                "provided_inputs": {"region": "us-east-1"},
                "missing_inputs": ["instance_type"],
                "missing_parameters": ["instance_type"],
                "ready_to_execute": False,
                "precheck_tool": None,
                "files": [],
                "commands": [],
                "notes": [],
                "requires_confirmation": False,
                "steps": [],
                "error": None,
                "explanation": "Need the EC2 instance type.",
            },
            task_id="task-continue-2",
        )
        self.fake_db.add(existing_task)

        response = self.client.post(
            "/api/task/task-continue-2/continue",
            json={"provided_inputs": {"instance_type": "t3.micro"}},
        )

        self.assertEqual(200, response.status_code)
        body = response.json()
        self.assertEqual("awaiting_confirmation", body["status"])
        self.assertEqual("success", body["code_payload"]["status"])
        self.assertEqual("deploy_ec2_instance", body["code_payload"]["intent"])
        self.assertEqual("task-continue-2", body["code_payload"]["task_id"])
        self.assertEqual(1, len(body["code_payload"]["files"]))
        self.assertEqual(2, len(body["code_payload"]["commands"]))

    @patch.object(tasks_route, "Task", FakeTask)
    def test_continue_task_uses_raw_user_input_for_first_missing_field(self) -> None:
        existing_task = FakeTask(
            user_prompt="Create an EC2 instance in us-east-1",
            status="collecting_input",
            code_payload={
                "status": "needs_input",
                "task_id": "task-continue-3",
                "mode": "discovery",
                "intent": "deploy_ec2_instance",
                "selected_tool": "generate_ec2_terraform",
                "required_inputs": ["instance_type"],
                "recommended_inputs": ["region"],
                "optional_inputs": ["instance_name", "vpc_cidr", "public_subnet_cidr"],
                "defaults": {"region": "us-east-1"},
                "provided_inputs": {"region": "us-east-1"},
                "missing_inputs": ["instance_type"],
                "missing_parameters": ["instance_type"],
                "ready_to_execute": False,
                "precheck_tool": None,
                "files": [],
                "commands": [],
                "notes": [],
                "requires_confirmation": False,
                "steps": [],
                "error": None,
                "explanation": "Need the EC2 instance type.",
            },
            task_id="task-continue-3",
        )
        self.fake_db.add(existing_task)

        response = self.client.post(
            "/api/task/task-continue-3/continue",
            json={"user_input": "t3.micro"},
        )

        self.assertEqual(200, response.status_code)
        body = response.json()
        self.assertEqual("awaiting_confirmation", body["status"])
        self.assertEqual("task-continue-3", body["code_payload"]["task_id"])


if __name__ == "__main__":
    unittest.main()
