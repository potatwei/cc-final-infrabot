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
    execute: bool = False,
) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    if provided_inputs:
        payload["provided_inputs"] = provided_inputs
    if user_input:
        payload["user_input"] = user_input
    if execute:
        payload["execute"] = True
    return api_request(
        method="POST",
        path=f"/api/task/{task_id}/continue",
        base_url=base_url,
        payload=payload,
    )


def get_task(task_id: str, *, base_url: str) -> dict[str, Any]:
    return api_request(method="GET", path=f"/api/task/{task_id}", base_url=base_url)


def list_tasks(*, base_url: str, limit: int = 10) -> list[dict[str, Any]]:
    return api_request(method="GET", path=f"/api/tasks?limit={limit}", base_url=base_url)


def confirm_task(task_id: str, *, base_url: str) -> dict[str, Any]:
    return api_request(method="POST", path=f"/api/task/{task_id}/confirm", base_url=base_url)


def determine_next_step(response: dict[str, Any]) -> str:
    """Classify the next CLI action from a backend task payload."""
    task_status = response.get("status")
    code_payload = response.get("code_payload") or {}
    if code_payload.get("mode") == "discovery":
        return "review"
    if task_status == "collecting_input":
        return "collect_input"
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
        display_inputs = _build_discovery_display_inputs(code_payload)
        if display_inputs:
            print("provided_inputs:")
            for key, value in display_inputs.items():
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


def _build_discovery_display_inputs(code_payload: dict[str, Any]) -> dict[str, Any]:
    provided_inputs = code_payload.get("provided_inputs") or {}
    defaults = code_payload.get("defaults") or {}
    ordered_keys = []
    for key in (
        code_payload.get("required_inputs") or []
    ) + (
        code_payload.get("recommended_inputs") or []
    ) + (
        code_payload.get("optional_inputs") or []
    ):
        if key not in ordered_keys:
            ordered_keys.append(key)

    display_inputs: dict[str, Any] = {}
    for key in ordered_keys:
        if key in provided_inputs and provided_inputs[key] not in (None, ""):
            display_inputs[key] = provided_inputs[key]
        elif key in defaults:
            display_inputs[key] = defaults[key]
        else:
            display_inputs[key] = "(missing)"
    return display_inputs


def prompt_for_discovery_input(response: dict[str, Any]) -> tuple[str, str | None]:
    """Read one free-form review/update command from the user."""
    code_payload = response.get("code_payload") or {}
    if code_payload.get("ready_to_execute"):
        prompt = "review> type 'confirm' to generate the plan, or enter updates: "
    else:
        prompt = "review> enter updates like 'instance_type: t3.micro' (or 'cancel'): "

    value = input(prompt).strip()
    if not value:
        raise KeyboardInterrupt("No review input provided.")
    normalized = value.lower()
    if normalized in {"exit", "quit", "cancel"}:
        raise KeyboardInterrupt("Review cancelled.")
    if normalized == "confirm":
        return ("confirm", None)
    return ("update", value)


def print_task_table(tasks: list[dict[str, Any]]) -> None:
    if not tasks:
        print("No tasks found.")
        return
    for task in tasks:
        print(
            f"{task.get('task_id')} | {task.get('status')} | "
            f"{(task.get('user_prompt') or '').strip()}"
        )


def print_chat_help() -> None:
    print("Commands:")
    print("  /help                Show available chat commands")
    print("  /lookup <query>      Run a read-only lookup without changing the active task")
    print("  /show [task_id]      Show the active task or one specific task")
    print("  /tasks [limit]       List recent tasks")
    print("  /confirm             Execute the active ready-to-execute discovery task")
    print("  /cancel              Clear the active task from the chat session")
    print("Examples:")
    print("  /lookup regions")
    print("  /lookup instance_types")
    print("  /show")
    print("  /tasks 5")


def _active_discovery_values(response: dict[str, Any] | None) -> dict[str, Any]:
    if not response:
        return {}
    code_payload = response.get("code_payload") or {}
    return _build_discovery_display_inputs(code_payload) if code_payload.get("mode") == "discovery" else {}


def _resolve_lookup_prompt(query: str, active_response: dict[str, Any] | None) -> str:
    normalized = query.strip().lower()
    active_values = _active_discovery_values(active_response)
    region = active_values.get("region")

    if normalized in {"regions", "region"}:
        return "what aws regions are available"
    if normalized in {"instance_types", "instance type", "instance types"}:
        if isinstance(region, str) and region not in {"(missing)", ""}:
            return f"what instance types are available in {region}"
        return "what instance types are available in us-east-1"
    return query


def _handle_chat_command(
    raw_input: str,
    *,
    active_response: dict[str, Any] | None,
    base_url: str,
) -> tuple[dict[str, Any] | None, bool]:
    parts = raw_input.strip().split(maxsplit=1)
    command = parts[0].lower()
    argument = parts[1].strip() if len(parts) > 1 else ""

    if command == "/help":
        print_chat_help()
        return active_response, False

    if command == "/lookup":
        if not argument:
            print("Usage: /lookup <query>")
            return active_response, False
        lookup_prompt = _resolve_lookup_prompt(argument, active_response)
        lookup_response = create_discovery_task(lookup_prompt, base_url=base_url)
        print_response_summary(lookup_response)
        return active_response, False

    if command == "/show":
        if argument:
            response = get_task(argument, base_url=base_url)
            print_response_summary(response)
            return active_response, False
        if active_response:
            print_response_summary(active_response)
        else:
            print("No active task in this chat session.")
        return active_response, False

    if command == "/tasks":
        limit = 10
        if argument:
            try:
                limit = int(argument)
            except ValueError:
                print("Usage: /tasks [limit]")
                return active_response, False
        print_task_table(list_tasks(base_url=base_url, limit=limit))
        return active_response, False

    if command == "/confirm":
        if not active_response:
            print("No active task to confirm.")
            return active_response, False
        code_payload = active_response.get("code_payload") or {}
        if code_payload.get("mode") == "discovery" and code_payload.get("ready_to_execute"):
            response = continue_task(
                active_response["task_id"],
                base_url=base_url,
                execute=True,
            )
            print_response_summary(response)
            return response, False
        if active_response.get("status") == "awaiting_confirmation":
            confirmation = confirm_task(active_response["task_id"], base_url=base_url)
            print(confirmation.get("message", "Task marked complete."))
            refreshed = get_task(active_response["task_id"], base_url=base_url)
            return refreshed, False
        print("The active task is not ready for /confirm.")
        return active_response, False

    if command == "/cancel":
        if active_response:
            print(f"Cancelled active task {active_response.get('task_id')}.")
        else:
            print("No active task to cancel.")
        return None, False

    print(f"Unknown command: {command}. Use /help.")
    return active_response, False


def run_deploy(prompt: str, *, base_url: str, auto_confirm: bool = False) -> int:
    """Drive discovery, continuation, and final confirmation through the backend."""
    response = create_discovery_task(prompt, base_url=base_url)

    while True:
        print_response_summary(response)
        next_step = determine_next_step(response)

        if next_step == "review":
            if auto_confirm and response.get("code_payload", {}).get("ready_to_execute"):
                action = "confirm"
                user_value = None
            else:
                action, user_value = prompt_for_discovery_input(response)
            if action == "confirm":
                response = continue_task(
                    response["task_id"],
                    base_url=base_url,
                    execute=True,
                )
            else:
                response = continue_task(
                    response["task_id"],
                    base_url=base_url,
                    user_input=user_value,
                )
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
    active_response: dict[str, Any] | None = None
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

        if prompt.startswith("/"):
            active_response, should_exit = _handle_chat_command(
                prompt,
                active_response=active_response,
                base_url=base_url,
            )
            if should_exit:
                return 0
            continue

        if active_response and (active_response.get("code_payload") or {}).get("mode") == "discovery":
            try:
                active_response = continue_task(
                    active_response["task_id"],
                    base_url=base_url,
                    user_input=prompt,
                )
            except BackendApiError:
                raise
            print_response_summary(active_response)
            continue

        active_response = create_discovery_task(prompt, base_url=base_url)
        print_response_summary(active_response)


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
