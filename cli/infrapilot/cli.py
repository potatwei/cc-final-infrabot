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

        if payload.get("status") != "success":
            display.failure(payload.get("message", "Backend returned an error."))
            continue

        display.show_payload(payload)

        requires_confirm = (payload.get("metadata") or {}).get("requires_confirmation", True)
        approved = True
        if requires_confirm:
            approved = display.confirm()

        try:
            result = client.confirm(payload["task_id"], approved)
        except Exception as e:
            display.failure(f"Confirmation failed: {e}")
            continue

        display.show_result(result)


if __name__ == "__main__":
    main()
