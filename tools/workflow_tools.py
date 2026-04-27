"""Workflow-core adapter tools exposed to the LangGraph agent."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any, cast

from infrapilot_workflow import ProjectState, WorkflowInput, build_execution_plan
from langchain_core.tools import tool


def _build_project_state(
    *,
    project_name: str,
    region: str | None,
    infrastructure: dict[str, object] | None,
    services: dict[str, object] | None,
) -> ProjectState:
    """Normalize agent arguments into the workflow-core project state model."""
    return ProjectState(
        project_name=project_name,
        region=region,
        infrastructure=infrastructure or {},
        services=services or {},
    )


def _flatten_generated_files(steps: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Flatten step-level generated files into the agent-facing file list."""
    files: list[dict[str, str]] = []

    for step in steps:
        step_name = str(step["name"])
        generated_files = step.get("generated_files", {})
        if not isinstance(generated_files, dict):
            continue

        for path, content in generated_files.items():
            files.append(
                {
                    "path": str(path),
                    "content": str(content),
                    "source_step": step_name,
                }
            )

    return files


def _extract_commands(steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Mirror workflow-core shell steps into top-level agent command entries."""
    commands: list[dict[str, Any]] = []

    for step in steps:
        if step.get("type") != "shell_command":
            continue

        execution_payload = step.get("execution_payload")
        if not isinstance(execution_payload, dict):
            continue

        command_entry: dict[str, Any] = {
            "step_name": str(step["name"]),
            "description": str(step["description"]),
            "command": execution_payload.get("command"),
        }
        if "stdin_source" in execution_payload:
            command_entry["stdin_source"] = execution_payload.get("stdin_source")

        commands.append(command_entry)

    return commands


def _plan_to_tool_output(plan: Any) -> dict[str, Any]:
    """Convert the workflow-core plan model into agent-facing output."""
    steps = [step.model_dump(mode="python") for step in plan.steps]

    return {
        "intent": plan.intent,
        "files": _flatten_generated_files(steps),
        "commands": _extract_commands(steps),
        "notes": list(plan.notes),
        "requires_confirmation": bool(plan.requires_confirmation),
        "steps": steps,
        "status": "success",
        "error": None,
        "missing_parameters": [],
    }


def _build_workflow_input(
    *,
    intent: str,
    project_name: str,
    region: str | None,
    entities: dict[str, object] | None = None,
    infrastructure: dict[str, object] | None = None,
    services: dict[str, object] | None = None,
) -> WorkflowInput:
    """Build workflow-core input from agent-facing tool arguments."""
    project_state = _build_project_state(
        project_name=project_name,
        region=region,
        infrastructure=infrastructure,
        services=services,
    )
    return WorkflowInput(
        intent=cast(Any, intent),
        entities=entities or {},
        project_state=project_state,
    )


def _run_workflow_intent(
    *,
    intent: str,
    project_name: str,
    region: str | None,
    entities: dict[str, object] | None = None,
    infrastructure: dict[str, object] | None = None,
    services: dict[str, object] | None = None,
) -> dict[str, Any]:
    """Execute one workflow-core planning intent and normalize the result."""
    workflow_input = _build_workflow_input(
        intent=intent,
        project_name=project_name,
        region=region,
        entities=entities,
        infrastructure=infrastructure,
        services=services,
    )

    try:
        return _plan_to_tool_output(build_execution_plan(workflow_input))
    except ValueError as exc:
        return _validation_error_output(intent=intent, error=exc)
    except Exception:
        return _internal_error_output(intent=intent)


def _dedupe_strings(values: Iterable[str]) -> list[str]:
    """Preserve order while removing duplicate parameter names."""
    seen: set[str] = set()
    deduped: list[str] = []

    for value in values:
        if value in seen:
            continue
        seen.add(value)
        deduped.append(value)

    return deduped


def _extract_missing_parameters(message: str) -> list[str]:
    """Extract likely missing user inputs from workflow-core validation text."""
    missing: list[str] = []

    if "entities['service_name']" in message:
        missing.append("service_name")
    if "entities['replicas']" in message:
        missing.append("replicas")
    if "project_state.infrastructure keys:" in message:
        missing.append("infrastructure")
    if "project_state.services['" in message:
        missing.append("services")

    return _dedupe_strings(missing)


def _validation_error_output(*, intent: str, error: ValueError) -> dict[str, Any]:
    """Return a structured tool response for expected validation failures."""
    message = str(error)
    return {
        "intent": intent,
        "files": [],
        "commands": [],
        "notes": [],
        "requires_confirmation": False,
        "steps": [],
        "status": "needs_input",
        "error": message,
        "missing_parameters": _extract_missing_parameters(message),
    }


def _internal_error_output(*, intent: str) -> dict[str, Any]:
    """Return a structured tool response for unexpected planning failures."""
    return {
        "intent": intent,
        "files": [],
        "commands": [],
        "notes": [],
        "requires_confirmation": False,
        "steps": [],
        "status": "error",
        "error": "Internal workflow planning failure.",
        "missing_parameters": [],
    }


@tool
def plan_setup_infra(
    project_name: str,
    region: str = "us-east-1",
    vpc_cidr: str = "10.0.0.0/16",
    infrastructure: dict[str, object] | None = None,
    services: dict[str, object] | None = None,
) -> dict[str, Any]:
    """Build a deterministic setup_infra plan via the workflow-core package.

    Use this when the user wants to provision baseline ECS/Fargate platform
    infrastructure. The tool returns a structured planning payload and does not
    execute Terraform.
    """
    return _run_workflow_intent(
        intent="setup_infra",
        project_name=project_name,
        region=region,
        entities={"region": region, "vpc_cidr": vpc_cidr},
        infrastructure=infrastructure,
        services=services,
    )


@tool
def plan_deploy_service(
    project_name: str,
    infrastructure: dict[str, object],
    region: str = "us-east-1",
    service_name: str | None = None,
    port: int = 3000,
    cpu: int = 256,
    memory: int = 512,
    replicas: int = 2,
    image_tag: str = "latest",
    environment_variables: dict[str, str] | None = None,
    services: dict[str, object] | None = None,
) -> dict[str, Any]:
    """Build a deterministic deploy_service plan via the workflow-core package.

    Expected infrastructure keys include cluster, networking, ALB listener, ECS
    task security group, task execution role, and ECR metadata already known to
    the agent layer. Workflow-core still plans one intent at a time, so shared
    infrastructure must already exist before deploy_service can succeed.
    """
    entities: dict[str, object] = {
        "region": region,
        "port": port,
        "cpu": cpu,
        "memory": memory,
        "replicas": replicas,
        "image_tag": image_tag,
        "environment_variables": environment_variables or {},
    }
    if service_name:
        entities["service_name"] = service_name

    return _run_workflow_intent(
        intent="deploy_service",
        project_name=project_name,
        region=region,
        entities=entities,
        infrastructure=infrastructure,
        services=services,
    )


@tool
def plan_scale_service(
    project_name: str,
    infrastructure: dict[str, object],
    services: dict[str, object],
    replicas: int,
    region: str = "us-east-1",
    service_name: str | None = None,
) -> dict[str, Any]:
    """Build a deterministic scale_service plan via the workflow-core package.

    Use this when service infrastructure already exists and only the desired
    replica count should change. Workflow-core may fall back to
    project_name for service_name when the upstream request omits it.
    """
    entities: dict[str, object] = {
        "region": region,
        "replicas": replicas,
    }
    if service_name:
        entities["service_name"] = service_name

    return _run_workflow_intent(
        intent="scale_service",
        project_name=project_name,
        region=region,
        entities=entities,
        infrastructure=infrastructure,
        services=services,
    )


@tool
def plan_stop_service(
    project_name: str,
    infrastructure: dict[str, object],
    services: dict[str, object],
    service_name: str,
    region: str = "us-east-1",
) -> dict[str, Any]:
    """Build a deterministic stop_service plan via the workflow-core package.

    Use this when a service should remain defined in Terraform but be scaled
    down to zero running tasks. workflow-core requires an explicit
    service_name for this operational intent.
    """
    return _run_workflow_intent(
        intent="stop_service",
        project_name=project_name,
        region=region,
        entities={
            "region": region,
            "service_name": service_name,
        },
        infrastructure=infrastructure,
        services=services,
    )


@tool
def plan_teardown_service(
    project_name: str,
    infrastructure: dict[str, object],
    services: dict[str, object],
    service_name: str,
    region: str = "us-east-1",
) -> dict[str, Any]:
    """Build a deterministic teardown_service plan via the workflow-core package.

    Use this when a single service should be destroyed while shared platform
    infrastructure remains in place. workflow-core requires an explicit
    service_name for this destroy intent.
    """
    return _run_workflow_intent(
        intent="teardown_service",
        project_name=project_name,
        region=region,
        entities={
            "region": region,
            "service_name": service_name,
        },
        infrastructure=infrastructure,
        services=services,
    )


@tool
def plan_teardown_infra(
    project_name: str,
    region: str = "us-east-1",
    vpc_cidr: str = "10.0.0.0/16",
    infrastructure: dict[str, object] | None = None,
    services: dict[str, object] | None = None,
) -> dict[str, Any]:
    """Build a deterministic teardown_infra plan via the workflow-core package.

    Use this when the shared ECS/Fargate platform should be destroyed. The
    tool generates Terraform destroy input only; it does not execute anything.
    workflow-core requires project_state.services to be empty before this plan
    can succeed.
    """
    return _run_workflow_intent(
        intent="teardown_infra",
        project_name=project_name,
        region=region,
        entities={"region": region, "vpc_cidr": vpc_cidr},
        infrastructure=infrastructure,
        services=services,
    )
