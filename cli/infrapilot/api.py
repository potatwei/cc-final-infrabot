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
    def confirm(self, task_id: str, approved: bool) -> dict: ...


# ---------------------------------------------------------------------------
# Part 1 — fake backend
# ---------------------------------------------------------------------------

def _canned_payload(user_prompt: str, task_id: str) -> dict:
    """Return a payload in the shape Person A's backend uses (see TaskResponse)."""
    text = user_prompt.lower()

    if "tear" in text or "destroy" in text or "remove" in text:
        intent, risk, explanation = (
            "teardown_all",
            "high",
            "Destroy all resources previously created for this project.",
        )
        commands = [
            {"step": 1, "label": "Initializing Terraform", "binary": "terraform",
             "args": ["init"], "critical": True},
            {"step": 2, "label": "Destroying resources", "binary": "terraform",
             "args": ["destroy", "-auto-approve"], "critical": True},
        ]
        files = []
    elif "scale" in text or "stop" in text:
        intent, risk, explanation = (
            "scale_service",
            "low",
            "Update the desired task count for the service.",
        )
        files = [{
            "path": "main.tf", "type": "terraform",
            "content": 'resource "null_resource" "svc" { triggers = { count = 1 } }',
        }]
        commands = [
            {"step": 1, "label": "Re-applying service", "binary": "terraform",
             "args": ["apply", "-auto-approve"], "critical": True},
        ]
    elif "deploy" in text or "launch" in text:
        intent, risk, explanation = (
            "deploy_service",
            "medium",
            "Build the image, push to ECR, and run an ECS service behind an ALB.",
        )
        files = [{
            "path": "main.tf", "type": "terraform",
            "content": 'resource "aws_s3_bucket" "demo" { bucket = "demo" }',
        }]
        commands = [
            {"step": 1, "label": "Initializing Terraform", "binary": "terraform",
             "args": ["init"], "critical": True},
            {"step": 2, "label": "Deploying service", "binary": "terraform",
             "args": ["apply", "-auto-approve"], "critical": True},
        ]
    else:
        intent, risk, explanation = (
            "setup_infra",
            "low",
            "Provision an S3 bucket as demo infrastructure in us-east-1.",
        )
        files = [{
            "path": "main.tf", "type": "terraform",
            "content": 'resource "aws_s3_bucket" "b" { bucket = "my-data-bucket" }',
        }]
        commands = [
            {"step": 1, "label": "Initializing Terraform", "binary": "terraform",
             "args": ["init"], "critical": True},
            {"step": 2, "label": "Deploying S3 Bucket", "binary": "terraform",
             "args": ["apply", "-auto-approve"], "critical": True},
        ]

    return {
        "status": "success",
        "task_id": task_id,
        "metadata": {
            "intent": intent,
            "provider": "aws",
            "region": "us-east-1",
            "requires_confirmation": True,
            "estimated_risk": risk,
        },
        "infrastructure": {"files": files, "commands": commands},
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
                f"{len(payload['infrastructure']['commands'])} command(s) on the cloud."
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
