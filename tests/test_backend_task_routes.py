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


if __name__ == "__main__":
    unittest.main()
