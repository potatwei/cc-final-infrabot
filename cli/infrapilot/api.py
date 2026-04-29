"""Backend client.

Part 1 uses ``FakeClient``, which returns hand-written canned payloads so the
CLI can be demo'd end-to-end without Person A's server. Part 2 will add an
``HttpClient`` that swaps these two methods for real httpx calls:

    POST   /task                 -> submit(user_prompt) -> payload
    POST   /task/<id>/confirm    -> confirm(task_id, approved) -> result

The CLI only ever talks to the interface below; it has no knowledge of
Terraform, Docker, or AWS.
"""

from __future__ import annotations

import uuid
from typing import Protocol


class Client(Protocol):
    def submit(self, user_prompt: str) -> dict: ...
    def continue_task(self, task_id: str, user_input: str | None = None,
                      provided_inputs: dict | None = None,
                      execute: bool = False) -> dict: ...
    def confirm(self, task_id: str, approved: bool) -> dict: ...


# ---------------------------------------------------------------------------
# Part 1 — fake backend
# ---------------------------------------------------------------------------

def _canned_payload(user_prompt: str, task_id: str) -> dict:
    """Return a payload in the shape Person A's backend uses (see TaskResponse)."""
    text = user_prompt.lower()

    if "tear" in text or "destroy" in text or "remove" in text:
        intent = "teardown_all"
        explanation = "Destroy all resources previously created for this project."
        commands = [
            {"step_name": "tf_init", "description": "Initializing Terraform",
             "command": "terraform init", "critical": True},
            {"step_name": "tf_destroy", "description": "Destroying resources",
             "command": "terraform destroy -auto-approve", "critical": True},
        ]
        files = []
    elif "scale" in text or "stop" in text:
        intent = "scale_service"
        explanation = "Update the desired task count for the service."
        files = [{
            "path": "main.tf", "type": "terraform",
            "content": 'resource "null_resource" "svc" { triggers = { count = 1 } }',
        }]
        commands = [
            {"step_name": "tf_apply", "description": "Re-applying service",
             "command": "terraform apply -auto-approve", "critical": True},
        ]
    elif "deploy" in text or "launch" in text:
        intent = "deploy_service"
        explanation = "Build the image, push to ECR, and run an ECS service behind an ALB."
        files = [{
            "path": "main.tf", "type": "terraform",
            "content": 'resource "aws_s3_bucket" "demo" { bucket = "demo" }',
        }]
        commands = [
            {"step_name": "tf_init", "description": "Initializing Terraform",
             "command": "terraform init", "critical": True},
            {"step_name": "tf_apply", "description": "Deploying service",
             "command": "terraform apply -auto-approve", "critical": True},
        ]
    else:
        intent = "setup_infra"
        explanation = "Provision an S3 bucket as demo infrastructure in us-east-1."
        files = [{
            "path": "main.tf", "type": "terraform",
            "content": 'resource "aws_s3_bucket" "b" { bucket = "my-data-bucket" }',
        }]
        commands = [
            {"step_name": "tf_init", "description": "Initializing Terraform",
             "command": "terraform init", "critical": True},
            {"step_name": "tf_apply", "description": "Deploying S3 Bucket",
             "command": "terraform apply -auto-approve", "critical": True},
        ]

    return {
        "status": "success",
        "task_id": task_id,
        "intent": intent,
        "files": files,
        "commands": commands,
        "notes": [],
        "requires_confirmation": True,
        "steps": [],
        "missing_parameters": [],
        "explanation": explanation,
    }


class FakeClient:
    """Part 1 stand-in for the backend. Returns canned payloads; no network."""

    def __init__(self) -> None:
        self._tasks: dict[str, dict] = {}

    def submit(self, user_prompt: str) -> dict:
        task_id = f"fake-{uuid.uuid4().hex[:8]}"
        payload = _canned_payload(user_prompt, task_id)
        self._tasks[task_id] = payload
        return payload

    def continue_task(self, task_id: str, user_input: str | None = None,
                      provided_inputs: dict | None = None,
                      execute: bool = False) -> dict:
        # Offline mode does not support multi-turn; return the existing payload.
        return self._tasks.get(task_id) or {
            "status": "error", "task_id": task_id, "message": "unknown task_id"
        }

    def confirm(self, task_id: str, approved: bool) -> dict:
        payload = self._tasks.get(task_id)
        if payload is None:
            return {"status": "error", "task_id": task_id, "message": "unknown task_id"}
        if not approved:
            return {"status": "cancelled", "task_id": task_id,
                    "message": "User declined. No resources were changed."}
        return {
            "status": "executed",
            "task_id": task_id,
            "message": (
                f"[fake] Backend would now execute "
                f"{len(payload.get('commands') or [])} command(s) on the cloud."
            ),
        }


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def get_client(user_config: dict) -> Client:
    """Return a backend client.

    Part 1: always returns FakeClient.
    Part 2: if ``user_config`` has ``api_url``/``api_key``, return an HttpClient.
    """
    if user_config.get("api_url"):
        from .http_client import HttpClient
        return HttpClient(user_config["api_url"], user_config.get("api_key", ""))
    return FakeClient()
