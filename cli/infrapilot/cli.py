"""InfraPilot CLI.

This is a thin chat client: it sends the user's natural-language input to the
backend, displays the response, and sends a confirmation back. Nothing is
executed locally — the backend owns all infrastructure work.
"""

import click

from . import api, config, display, history, lookups


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


@main.group()
def lookup() -> None:
    """Look up valid AWS values to paste into prompts."""


@lookup.command("regions")
def lookup_regions() -> None:
    """List common AWS regions."""
    for code, name in lookups.REGIONS:
        click.echo(f"  {code:<18} {name}")


@lookup.command("instance-types")
@click.argument("family", required=False)
def lookup_instance_types(family: str | None) -> None:
    """List EC2 instance types. Optionally filter by FAMILY (e.g. t3, m5)."""
    rows = lookups.INSTANCE_TYPES
    if family:
        prefix = f"{family.lower()}."
        rows = [r for r in rows if r[0].lower().startswith(prefix)]
        if not rows:
            click.echo(f"  no types matched '{family}'")
            click.echo("  try one of:")
            for fam, descr in lookups.INSTANCE_FAMILIES:
                click.echo(f"    {fam:<5} {descr}")
            return
    for code, descr in rows:
        click.echo(f"  {code:<14} {descr}")


@lookup.command("families")
def lookup_families() -> None:
    """List EC2 instance families with short descriptions."""
    for fam, descr in lookups.INSTANCE_FAMILIES:
        click.echo(f"  {fam:<5} {descr}")


@main.command("tasks")
@click.option("-n", "--limit", default=20, show_default=True,
              help="Number of recent tasks to show.")
@click.option("--refresh/--no-refresh", default=False,
              help="Fetch live status from the backend for each task.")
def tasks(limit: int, refresh: bool) -> None:
    """List tasks submitted from this CLI (local history)."""
    entries = history.recent(limit)
    if not entries:
        click.echo("  No tasks recorded yet. Submit one with `infrapilot chat`.")
        return

    if refresh:
        cfg = config.load_user_config()
        client = api.get_client(cfg)
        if isinstance(client, api.FakeClient):
            display.warn(
                "  No api_url configured — showing recorded statuses without refresh."
            )
        else:
            for e in entries:
                try:
                    payload = client.get_task(e["task_id"])
                    e["status"] = payload.get("status") or e.get("status", "")
                except Exception as ex:
                    e["status"] = f"lookup-failed: {ex.__class__.__name__}"

    click.echo("  timestamp                  task_id                                 status                  prompt")
    click.echo("  " + "-" * 110)
    for e in entries:
        ts = e.get("timestamp", "?")
        tid = e.get("task_id", "?")
        st = e.get("status", "")
        prompt = (e.get("prompt") or "").replace("\n", " ")
        if len(prompt) > 50:
            prompt = prompt[:47] + "..."
        click.echo(f"  {ts:<26} {tid:<38} [{st:<20}]  {prompt}")


@main.command("show")
@click.argument("task_id")
def show(task_id: str) -> None:
    """Look up a task by id and render the current payload from the backend."""
    cfg = config.load_user_config()
    client = api.get_client(cfg)
    if isinstance(client, api.FakeClient):
        display.warn(
            "No api_url configured. Run `infrapilot config --api-url ... --api-key ...` "
            "to query the real backend."
        )
    try:
        payload = client.get_task(task_id)
    except Exception as e:
        display.failure(f"Lookup failed: {e}")
        return
    display.show_payload(payload)


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

        history.record(payload.get("task_id", ""), text, payload.get("status", ""))
        _drive_task(client, payload, original_prompt=text)


def _drive_task(client, payload: dict, original_prompt: str = "",
                max_turns: int = 8) -> None:
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
                required = set(payload.get("required_inputs") or [])
                recommended = set(payload.get("recommended_inputs") or [])
                optional = set(payload.get("optional_inputs") or [])
                defaults = payload.get("defaults") or {}
                display.info(
                    "  Please provide (Enter to accept default; "
                    "see `infrapilot lookup --help` for valid values):"
                )
                for name in missing:
                    if name in required:
                        cls = "required"
                    elif name in recommended:
                        cls = "recommended"
                    elif name in optional:
                        cls = "optional"
                    else:
                        cls = None
                    default = defaults.get(name)
                    label = display.build_prompt_label(name, cls, default)
                    val = click.prompt(
                        label,
                        default=str(default) if default is not None else "",
                        show_default=False,
                    )
                    if val.strip():
                        provided[name.strip()] = val.strip()
            else:
                free = click.prompt("  More detail", default="", show_default=False)
                if not free.strip():
                    return

            # Backend can't dispatch /continue without selected_tool, so when the
            # agent didn't pick one we re-submit a new task with the prompt
            # enriched by the user's answers instead.
            selected_tool = payload.get("selected_tool")
            try:
                if not selected_tool and original_prompt:
                    enriched = _enriched_prompt(original_prompt, provided, free)
                    display.info(f"  Re-submitting with provided values...")
                    payload = client.submit(enriched)
                    history.record(
                        payload.get("task_id", ""),
                        enriched,
                        payload.get("status", ""),
                    )
                    original_prompt = enriched
                else:
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


def _enriched_prompt(original: str, provided: dict, free_text: str = "") -> str:
    """Compose a follow-up prompt that bakes the user's answers into the text."""
    parts = [original.strip()]
    if free_text and free_text.strip():
        parts.append(free_text.strip())
    if provided:
        kv = "; ".join(f"{k}={v}" for k, v in provided.items() if v != "")
        if kv:
            parts.append(f"Use these values: {kv}.")
    return " ".join(parts)


if __name__ == "__main__":
    main()
