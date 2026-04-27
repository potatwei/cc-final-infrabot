"""Local smoke test utilities for the InfraPilot agent (no FastAPI).

Builds the LangGraph workflow directly, runs it against a natural-language
query, and prints:

  1. each node's update as it happens (the agent's "thinking trace"), and
  2. the final ``final_payload`` that would be returned to the API client.

Usage (from the Infrapilot/ directory):
    python run_agent.py "deploy an api service named demo"
    python run_agent.py --demo deploy-success
    python run_agent.py --demo deploy-needs-infra
    python run_agent.py --demo stop-needs-service-name
    python run_agent.py                # uses DEFAULT_QUERY below

Requires AWS credentials with Bedrock + (optionally) S3 HeadBucket access,
e.g. via `aws configure` or AWS_PROFILE / AWS_ACCESS_KEY_ID env vars.
"""

from __future__ import annotations

import json
import sys

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from agents.bedrock_graph import build_graph
from tools.workflow_tools import plan_deploy_service, plan_stop_service

DEFAULT_QUERY = "Plan deployment of an API service named demo in us-east-1."


def _sample_infrastructure() -> dict[str, object]:
    """Return a minimal infrastructure state accepted by workflow-core."""
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


def _sample_service_state() -> dict[str, object]:
    """Return a minimal stored service state for stop/scale examples."""
    return {
        "port": 3000,
        "cpu": 256,
        "memory": 512,
        "replicas": 2,
        "image_tag": "v1",
        "environment_variables": {"NODE_ENV": "production"},
    }


def demo_workflow_payload(name: str) -> dict:
    """Run one local workflow-tool scenario without invoking Bedrock."""
    if name == "deploy-success":
        return plan_deploy_service.invoke(
            {
                "project_name": "demo-project",
                "infrastructure": _sample_infrastructure(),
                "service_name": "api",
                "port": 3000,
                "cpu": 256,
                "memory": 512,
                "replicas": 2,
                "image_tag": "v1",
                "environment_variables": {"NODE_ENV": "production"},
            }
        )
    if name == "deploy-needs-infra":
        return plan_deploy_service.invoke(
            {
                "project_name": "demo-project",
                "infrastructure": {
                    "cluster_arn": _sample_infrastructure()["cluster_arn"],
                },
            }
        )
    if name == "stop-needs-service-name":
        return plan_stop_service.invoke(
            {
                "project_name": "demo-project",
                "infrastructure": _sample_infrastructure(),
                "services": {"api": _sample_service_state()},
                "service_name": "",
            }
        )

    raise ValueError(
        "Unknown demo scenario. Use one of: deploy-success, deploy-needs-infra, "
        "stop-needs-service-name."
    )


def _format_message(msg) -> str:
    """Render a single LangChain message as a one-liner for the trace."""
    if isinstance(msg, AIMessage):
        text = msg.content if isinstance(msg.content, str) else str(msg.content)
        lines = [f"[AI] {text}".rstrip()] if text else []
        for tc in getattr(msg, "tool_calls", None) or []:
            lines.append(f"  -> tool_call: {tc.get('name')}({tc.get('args')})")
        return "\n".join(lines) or "[AI] (empty)"
    if isinstance(msg, ToolMessage):
        name = getattr(msg, "name", "?")
        content = msg.content
        if isinstance(content, str) and len(content) > 400:
            content = content[:400] + "...<truncated>"
        return f"[TOOL/{name}] {content}"
    return f"[{type(msg).__name__}] {getattr(msg, 'content', msg)!r}"


def run(query: str) -> dict | None:
    graph = build_graph()
    inputs = {"messages": [HumanMessage(content=f"User request: {query}")]}

    print("=" * 72)
    print(f"USER QUERY: {query}")
    print("=" * 72)

    final_payload: dict | None = None

    for step, update in enumerate(graph.stream(inputs, stream_mode="updates"), start=1):
        for node_name, delta in update.items():
            print(f"\n--- step {step}: node = {node_name} ---")

            for msg in delta.get("messages", []) or []:
                print(_format_message(msg))

            if "final_payload" in delta:
                final_payload = delta["final_payload"]
                print("[formatter] final_payload set "
                      f"(status={final_payload.get('status')}, "
                      f"files={len(final_payload.get('files', []))}, "
                      f"commands={len(final_payload.get('commands', []))})")

    print("\n" + "=" * 72)
    print("FINAL PAYLOAD")
    print("=" * 72)
    if final_payload:
        print(json.dumps(final_payload, indent=2))
    else:
        print("(no final_payload was produced)")

    return final_payload


def run_demo(name: str) -> dict:
    """Print one direct workflow-tool scenario without Bedrock."""
    payload = demo_workflow_payload(name)
    print("=" * 72)
    print(f"LOCAL DEMO: {name}")
    print("=" * 72)
    print(json.dumps(payload, indent=2))
    return payload


if __name__ == "__main__":
    args = sys.argv[1:]
    if len(args) >= 2 and args[0] == "--demo":
        run_demo(args[1])
    else:
        cli_query = " ".join(args).strip()
        run(cli_query or DEFAULT_QUERY)
