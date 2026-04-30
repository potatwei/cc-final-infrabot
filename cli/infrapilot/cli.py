"""InfraPilot CLI.

This is a thin chat client: it sends the user's natural-language input to the
backend, displays the response, and sends a confirmation back. Nothing is
executed locally — the backend owns all infrastructure work.
"""

import click

from . import api, config, display


@click.group()
@click.version_option()
def main() -> None:
    """InfraPilot — natural-language DevOps (chat client)."""


@main.command("config")
@click.option("--api-url", required=True, help="Backend base URL, e.g. https://...")
@click.option("--api-key", required=True, help="Backend API key.")
def set_config(api_url: str, api_key: str) -> None:
    """Store backend URL and API key in ~/.infrapilot/config.yaml."""
    cfg = config.load_user_config()
    cfg["api_url"] = api_url
    cfg["api_key"] = api_key
    config.save_user_config(cfg)
    display.success(f"Saved {config.USER_CONFIG}")


@main.command()
def chat() -> None:
    """Interactive REPL — type a request, review the plan, confirm."""
    user_cfg = config.load_user_config()
    client = api.get_client(user_cfg)

    if isinstance(client, api.FakeClient):
        display.warn(
            "Using fake backend (no api_url configured). "
            "Run `infrapilot config --api-url ... --api-key ...` to connect to the real backend."
        )

    display.info("Type a request. Ctrl-C or 'exit' to quit.\n")

    while True:
        try:
            user_input = click.prompt("›", prompt_suffix=" ", default="", show_default=False)
        except (KeyboardInterrupt, EOFError):
            display.info("\nbye")
            return
        text = user_input.strip()
        if not text:
            continue
        if text.lower() in {"exit", "quit"}:
            display.info("bye")
            return

        try:
            payload = client.submit(text)
        except Exception as e:
            display.failure(f"Request failed: {e}")
            continue

        _drive_task(client, payload)


def _drive_task(client, payload: dict, max_turns: int = 8) -> None:
    """Run the multi-turn lifecycle for one user prompt."""
    user_approved = False
    for _ in range(max_turns):
        display.show_payload(payload)
        status = (payload.get("status") or "").lower()
        task_id = payload["task_id"]

        if status == "needs_input":
            missing = (payload.get("missing_parameters")
                       or payload.get("missing_inputs")
                       or [])
            provided: dict = {}
            free = ""
            if missing:
                display.info("  Please provide:")
                for name in missing:
                    val = click.prompt(f"    {name}", default="", show_default=False)
                    if val.strip():
                        provided[name.strip()] = val.strip()
            else:
                free = click.prompt("  More detail", default="", show_default=False)
                if not free.strip():
                    return
            try:
                payload = client.continue_task(
                    task_id,
                    user_input=None if missing else free,
                    provided_inputs=provided,
                    execute=False,
                )
            except Exception as e:
                display.failure(f"Continue failed: {e}")
                return
            continue

        if status in ("awaiting_confirmation", "planned"):
            if not display.confirm("Execute this plan?"):
                display.info("  Execution declined.")
                return
            user_approved = True
            try:
                payload = client.continue_task(task_id, execute=True)
            except Exception as e:
                display.failure(f"Execute failed: {e}")
                return
            continue

        if status in ("failed", "error"):
            return

        # success / complete / anything else with content → /confirm to mark done.
        # If we never went through awaiting_confirmation (e.g. offline FakeClient),
        # ask the user once before marking complete.
        approved = user_approved
        if not approved:
            if not (payload.get("commands") or payload.get("files")):
                return
            approved = display.confirm()
        try:
            result = client.confirm(task_id, approved=approved)
        except Exception as e:
            display.failure(f"Confirmation failed: {e}")
            return
        display.show_result(result)
        return

    display.failure("  Too many turns; aborting this task.")


if __name__ == "__main__":
    main()
