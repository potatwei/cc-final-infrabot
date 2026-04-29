"""Simple interactive CLI for driving the InfraPilot backend."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any
from urllib import error, request


DEFAULT_BACKEND_URL = "http://127.0.0.1:8000"


class BackendApiError(RuntimeError):
    """Raised when the backend returns a non-success response."""


def api_request(
    *,
    method: str,
    path: str,
    base_url: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Call the backend JSON API with the standard library only."""
    body = None
    headers = {}
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"

    req = request.Request(
        url=f"{base_url.rstrip('/')}{path}",
        data=body,
        headers=headers,
        method=method,
    )
    try:
        with request.urlopen(req) as response:
            return json.loads(response.read().decode("utf-8"))
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8")
        raise BackendApiError(f"{exc.code} {exc.reason}: {detail}") from exc
    except error.URLError as exc:
        raise BackendApiError(f"Could not reach backend at {base_url}: {exc.reason}") from exc


def create_discovery_task(prompt: str, *, base_url: str) -> dict[str, Any]:
    return api_request(
        method="POST",
        path="/api/task",
        base_url=base_url,
        payload={"user_prompt": prompt, "mode": "discovery"},
    )


def continue_task(
    task_id: str,
    *,
    base_url: str,
    provided_inputs: dict[str, str] | None = None,
    user_input: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    if provided_inputs:
        payload["provided_inputs"] = provided_inputs
    if user_input:
        payload["user_input"] = user_input
    return api_request(
        method="POST",
        path=f"/api/task/{task_id}/continue",
        base_url=base_url,
        payload=payload,
    )


def get_task(task_id: str, *, base_url: str) -> dict[str, Any]:
    return api_request(method="GET", path=f"/api/task/{task_id}", base_url=base_url)


def confirm_task(task_id: str, *, base_url: str) -> dict[str, Any]:
    return api_request(method="POST", path=f"/api/task/{task_id}/confirm", base_url=base_url)


def determine_next_step(response: dict[str, Any]) -> str:
    """Classify the next CLI action from a backend task payload."""
    task_status = response.get("status")
    code_payload = response.get("code_payload") or {}
    if task_status == "collecting_input":
        return "collect_input"
    if task_status == "ready_to_execute" or code_payload.get("ready_to_execute") is True:
        return "execute"
    if task_status in {"awaiting_confirmation", "planned", "complete"}:
        return "done"
    if task_status == "failed":
        return "error"
    return "done"


def print_response_summary(response: dict[str, Any]) -> None:
    """Render the most useful fields from a task response."""
    code_payload = response.get("code_payload") or {}
    print(f"task_id: {response.get('task_id')}")
    print(f"task_status: {response.get('status')}")
    print(f"code_status: {code_payload.get('status')}")
    notes = code_payload.get("notes") or []

    if code_payload.get("mode") == "discovery":
        print(f"selected_tool: {code_payload.get('selected_tool')}")
        missing_inputs = code_payload.get("missing_inputs") or []
        if missing_inputs:
            print("missing_inputs: " + ", ".join(missing_inputs))
        provided_inputs = code_payload.get("provided_inputs") or {}
        if provided_inputs:
            print("provided_inputs:")
            for key, value in provided_inputs.items():
                print(f"  - {key}: {value}")
    else:
        files = code_payload.get("files") or []
        commands = code_payload.get("commands") or []
        regions = code_payload.get("regions") or []
        instance_types = code_payload.get("instance_types") or []
        suggestions = code_payload.get("suggestions") or []
        if "valid" in code_payload:
            print(f"valid: {code_payload.get('valid')}")
        if "available_in_region" in code_payload:
            print(f"available_in_region: {code_payload.get('available_in_region')}")
        if regions:
            print("regions:")
            for region in regions[:10]:
                print(f"  - {region}")
            if len(regions) > 10:
                print(f"  - ... ({len(regions)} total)")
        if instance_types:
            print("instance_types:")
            for instance_type in instance_types[:10]:
                print(f"  - {instance_type}")
            if len(instance_types) > 10:
                print(f"  - ... ({len(instance_types)} total)")
        if suggestions:
            print("suggestions:")
            for suggestion in suggestions[:10]:
                print(f"  - {suggestion}")
        if files:
            print("files:")
            for entry in files:
                print(f"  - {entry.get('path')}")
        if commands:
            print("commands:")
            for entry in commands:
                command = entry.get("command") or {}
                binary = command.get("binary", "")
                args = " ".join(command.get("args") or [])
                print(f"  - {binary} {args}".strip())

    if notes:
        print("notes:")
        for note in notes:
            print(f"  - {note}")

    explanation = code_payload.get("explanation")
    if explanation:
        print("explanation:")
        print(f"  {explanation}")


def prompt_for_missing_inputs(response: dict[str, Any]) -> dict[str, str]:
    """Prompt once for every missing field on a collecting_input task."""
    code_payload = response.get("code_payload") or {}
    updates: dict[str, str] = {}
    for field_name in code_payload.get("missing_inputs") or []:
        value = input(f"{field_name}: ").strip()
        if not value:
            raise KeyboardInterrupt(f"No value provided for {field_name}.")
        if value.lower() in {"exit", "quit", "cancel"}:
            raise KeyboardInterrupt(f"Input collection cancelled at {field_name}.")
        updates[field_name] = value
    return updates


def run_deploy(prompt: str, *, base_url: str, auto_confirm: bool = False) -> int:
    """Drive discovery, continuation, and final confirmation through the backend."""
    response = create_discovery_task(prompt, base_url=base_url)

    while True:
        print_response_summary(response)
        next_step = determine_next_step(response)

        if next_step == "collect_input":
            updates = prompt_for_missing_inputs(response)
            response = continue_task(
                response["task_id"],
                base_url=base_url,
                provided_inputs=updates,
            )
            continue

        if next_step == "execute":
            response = continue_task(response["task_id"], base_url=base_url)
            continue

        if next_step == "error":
            return 1
        break

    if response.get("status") == "awaiting_confirmation":
        if auto_confirm:
            answer = "y"
        else:
            answer = input(
                "Mark this task as confirmed and complete? "
                "(This does not run Terraform yet) [y/N]: "
            ).strip().lower()
        if answer == "y":
            confirmation = confirm_task(response["task_id"], base_url=base_url)
            print(confirmation.get("message", "Task marked complete."))

    return 0


def run_chat(*, base_url: str, auto_confirm: bool = False) -> int:
    """Open a simple REPL for repeated deploy requests."""
    print("InfraPilot chat mode. Type a request, or 'exit' to quit.")
    while True:
        try:
            prompt = input("infrapilot> ").strip()
        except EOFError:
            print()
            return 0

        if not prompt:
            continue
        if prompt.lower() in {"exit", "quit"}:
            return 0

        result = run_deploy(prompt, base_url=base_url, auto_confirm=auto_confirm)
        if result != 0:
            return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="InfraPilot backend CLI")
    parser.add_argument(
        "--backend-url",
        default=DEFAULT_BACKEND_URL,
        help=f"Backend base URL (default: {DEFAULT_BACKEND_URL})",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    deploy_parser = subparsers.add_parser("deploy", help="Run discovery and execution")
    deploy_parser.add_argument("prompt", help="Natural-language infrastructure request")
    deploy_parser.add_argument(
        "--auto-confirm",
        action="store_true",
        help="Mark awaiting_confirmation tasks as complete without prompting.",
    )

    show_parser = subparsers.add_parser("show", help="Fetch one task by id")
    show_parser.add_argument("task_id", help="Task id returned by the backend")

    confirm_parser = subparsers.add_parser("confirm", help="Mark one task as complete")
    confirm_parser.add_argument("task_id", help="Task id returned by the backend")

    chat_parser = subparsers.add_parser("chat", help="Open an interactive request prompt")
    chat_parser.add_argument(
        "--auto-confirm",
        action="store_true",
        help="Mark awaiting_confirmation tasks as complete without prompting.",
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        if args.command == "deploy":
            return run_deploy(
                args.prompt,
                base_url=args.backend_url,
                auto_confirm=args.auto_confirm,
            )
        if args.command == "show":
            response = get_task(args.task_id, base_url=args.backend_url)
            print_response_summary(response)
            return 0
        if args.command == "confirm":
            response = confirm_task(args.task_id, base_url=args.backend_url)
            print(response.get("message", "Task marked complete."))
            return 0
        if args.command == "chat":
            return run_chat(
                base_url=args.backend_url,
                auto_confirm=args.auto_confirm,
            )
        parser.error("Unknown command")
        return 2
    except KeyboardInterrupt as exc:
        print(f"\nStopped: {exc}", file=sys.stderr)
        return 130
    except BackendApiError as exc:
        print(f"Backend error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
