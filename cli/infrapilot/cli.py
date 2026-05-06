"""InfraPilot CLI.

Two-stage tool. The CLI sends a natural-language prompt to the backend, drives
the multi-turn planning lifecycle until a Terraform plan is returned, then —
locally on the user's machine — verifies AWS identity, runs ``terraform init``
/ ``plan`` / ``apply`` against the generated HCL, and finally pings the backend
to mark the task complete. The CLI deploys; the backend only plans.
"""

from __future__ import annotations

from pathlib import Path

import click

from . import (
    api,
    aws_auth,
    config,
    display,
    history,
    lookups,
    runs,
    terraform_runner,
)


@click.group()
@click.version_option()
def main() -> None:
    """InfraPilot — natural-language DevOps."""


# ---------------------------------------------------------------------------
# config
# ---------------------------------------------------------------------------

@main.command("config")
@click.option("--api-url", help="Backend base URL, e.g. https://...")
@click.option("--api-key", help="Backend API key.")
@click.option("--aws-region",
              help="Pin AWS_REGION/AWS_DEFAULT_REGION when running terraform.")
@click.option("--expected-account",
              help="12-digit AWS account id; deployment aborts if STS reports something else.")
def set_config(api_url: str | None, api_key: str | None,
               aws_region: str | None, expected_account: str | None) -> None:
    """Save backend + AWS settings to ~/.infrapilot/config.yaml."""
    cfg = config.load_user_config()
    if api_url is not None:
        cfg["api_url"] = api_url
    if api_key is not None:
        cfg["api_key"] = api_key
    if aws_region is not None:
        cfg["aws_region"] = aws_region
    if expected_account is not None:
        cfg["expected_account"] = expected_account
    if not any([api_url, api_key, aws_region, expected_account]):
        display.failure("No options provided; nothing to save.")
        return
    config.save_user_config(cfg)
    display.success(f"Saved {config.USER_CONFIG}")


# ---------------------------------------------------------------------------
# lookups
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# task history / lookup
# ---------------------------------------------------------------------------

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

    click.echo("  timestamp                  task_id                                 status                  apply           prompt")
    click.echo("  " + "-" * 130)
    for e in entries:
        ts = e.get("timestamp", "?")
        tid = e.get("task_id", "?")
        st = e.get("status", "")
        apply_status = e.get("apply_status", "")
        prompt = (e.get("prompt") or "").replace("\n", " ")
        if len(prompt) > 40:
            prompt = prompt[:37] + "..."
        click.echo(
            f"  {ts:<26} {tid:<38} [{st:<20}]  [{apply_status:<13}]  {prompt}"
        )


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


# ---------------------------------------------------------------------------
# AWS identity
# ---------------------------------------------------------------------------

@main.command("whoami")
def whoami() -> None:
    """Print the AWS identity boto3 would use for `apply`."""
    try:
        identity = aws_auth.resolve_identity()
    except aws_auth.AwsAuthError as e:
        display.failure(str(e))
        return
    display.show_caller_identity(identity)


# ---------------------------------------------------------------------------
# apply / destroy against an existing run dir
# ---------------------------------------------------------------------------

@main.command("apply")
@click.argument("task_id")
def apply_cmd(task_id: str) -> None:
    """Re-run terraform apply against the saved run dir for TASK_ID."""
    run_dir = runs.existing(task_id)
    if run_dir is None:
        display.failure(
            f"No run dir for task {task_id}. "
            f"Submit a task with `infrapilot chat` first."
        )
        return
    user_cfg = config.load_user_config()
    if not _aws_identity_gate(user_cfg):
        return
    if not _ensure_terraform_binary():
        return
    if not _init_plan_and_confirm(run_dir, user_cfg, task_id):
        return
    _run_apply(run_dir, user_cfg, task_id, client=None)


@main.command("destroy")
@click.argument("task_id")
def destroy_cmd(task_id: str) -> None:
    """Run terraform destroy against TASK_ID's saved run dir."""
    run_dir = runs.existing(task_id)
    if run_dir is None:
        display.failure(f"No run dir for task {task_id}; nothing to destroy.")
        return
    user_cfg = config.load_user_config()
    if not _aws_identity_gate(user_cfg):
        return
    if not _ensure_terraform_binary():
        return
    sentinel = f"destroy {task_id[:8]}"
    display.warn(
        f"  Destructive action. Type '{sentinel}' to confirm, anything else to abort."
    )
    typed = input("  > ").strip()
    if typed != sentinel:
        display.info("  Aborted.")
        return
    env = aws_auth.terraform_env(user_cfg.get("aws_region"))
    rc = terraform_runner.destroy(run_dir, env)
    if rc != 0:
        display.failure(f"  terraform destroy failed (exit {rc}).")
        history.update(task_id, apply_status="destroy-failed")
        return
    display.success(f"  Resources for {task_id} destroyed.")
    history.update(task_id, apply_status="destroyed")


# ---------------------------------------------------------------------------
# chat (the main flow)
# ---------------------------------------------------------------------------

@main.command()
def chat() -> None:
    """Interactive REPL — prompt the backend, then deploy locally."""
    user_cfg = config.load_user_config()
    client = api.get_client(user_cfg)

    if isinstance(client, api.FakeClient):
        display.warn(
            "Using fake backend (no api_url configured). "
            "Run `infrapilot config --api-url ... --api-key ...` to connect to the real backend. "
            "Local terraform deployment is skipped in this mode."
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
        _drive_task(client, payload, user_cfg, original_prompt=text)


# ---------------------------------------------------------------------------
# core lifecycle
# ---------------------------------------------------------------------------

def _drive_task(client, payload: dict, user_cfg: dict,
                original_prompt: str = "", max_turns: int = 8) -> None:
    """Loop through the planning lifecycle and dispatch deployment when ready."""
    for _ in range(max_turns):
        display.show_payload(payload)
        status = (payload.get("status") or "").lower()
        task_id = payload["task_id"]

        if status == "needs_input":
            payload = _handle_needs_input(client, payload, original_prompt)
            if payload is None:
                return
            original_prompt = payload.get("_resubmitted_prompt") or original_prompt
            continue

        if status in ("failed", "error"):
            history.update(task_id, status=status)
            return

        if status in ("awaiting_confirmation", "planned", "success", "complete"):
            history.update(task_id, status=status)
            if isinstance(client, api.FakeClient):
                _fake_finalize(client, payload)
                return
            _deploy_locally(client, payload, user_cfg)
            return

        # Unknown / pending leak — bail.
        display.warn(f"  Unexpected status '{status}'; stopping.")
        return

    display.failure("  Too many turns; aborting this task.")


def _handle_needs_input(client, payload: dict, original_prompt: str) -> dict | None:
    """Collect user inputs, then either /continue or resubmit-fallback. Returns
    new payload or None to abort."""
    task_id = payload["task_id"]
    missing = (payload.get("missing_parameters")
               or payload.get("missing_inputs")
               or [])
    provided: dict = {}
    free = ""
    if missing:
        required = set(payload.get("required_inputs") or [])
        recommended = set(payload.get("recommended_inputs") or [])
        optional = set(payload.get("optional_inputs") or [])
        defaults = lookups.defaults_for(payload)
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
            return None

    selected_tool = payload.get("selected_tool")
    try:
        if not selected_tool and original_prompt:
            enriched = _enriched_prompt(original_prompt, provided, free)
            display.info("  Re-submitting with provided values...")
            new_payload = client.submit(enriched)
            history.record(
                new_payload.get("task_id", ""), enriched,
                new_payload.get("status", ""),
            )
            new_payload["_resubmitted_prompt"] = enriched
            return new_payload
        return client.continue_task(
            task_id,
            user_input=None if missing else free,
            provided_inputs=provided,
            execute=False,
        )
    except Exception as e:
        display.failure(f"Continue failed: {e}")
        return None


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


# ---------------------------------------------------------------------------
# offline / fake finalize
# ---------------------------------------------------------------------------

def _fake_finalize(client, payload: dict) -> None:
    """Offline confirm — no terraform run."""
    if not (payload.get("commands") or payload.get("files")):
        return
    if not display.confirm("Proceed (offline; nothing will be deployed)?"):
        return
    try:
        result = client.confirm(payload["task_id"], approved=True)
    except Exception as e:
        display.failure(f"Confirmation failed: {e}")
        return
    display.show_result(result)


# ---------------------------------------------------------------------------
# local deployment (phases 2-4)
# ---------------------------------------------------------------------------

def _deploy_locally(client, payload: dict, user_cfg: dict) -> None:
    task_id = payload["task_id"]
    files = payload.get("files") or []
    if not files:
        display.warn("  Backend returned no files to deploy; skipping terraform.")
        return

    if not _aws_identity_gate(user_cfg):
        history.update(task_id, apply_status="skipped")
        return
    if not _ensure_terraform_binary():
        history.update(task_id, apply_status="skipped")
        return

    run_dir = runs.prepare(task_id, files)
    history.update(task_id, run_dir=str(run_dir))

    if not _init_plan_and_confirm(run_dir, user_cfg, task_id):
        return

    _run_apply(run_dir, user_cfg, task_id, client=client)


def _aws_identity_gate(user_cfg: dict) -> bool:
    """Resolve identity, optionally enforce expected_account, ask user."""
    expected = user_cfg.get("expected_account")
    try:
        ok, identity = aws_auth.verify_account(expected)
    except aws_auth.AwsAuthError as e:
        display.failure(str(e))
        return False
    display.show_caller_identity(identity)
    if not ok:
        display.failure(
            f"  Expected account {expected}, got {identity['account']}; aborting."
        )
        return False
    return display.confirm("Use this AWS identity?")


def _ensure_terraform_binary() -> bool:
    version = terraform_runner.check_binary()
    if version is None:
        display.failure(
            "  terraform not found on PATH. Install it from https://terraform.io/downloads"
        )
        return False
    display.info(f"  Using {version}")
    return True


def _init_plan_and_confirm(run_dir: Path, user_cfg: dict, task_id: str) -> bool:
    env = aws_auth.terraform_env(user_cfg.get("aws_region"))
    if terraform_runner.init(run_dir, env) != 0:
        display.failure("  terraform init failed; see output above.")
        history.update(task_id, apply_status="init-failed")
        return False
    rc, summary = terraform_runner.plan(run_dir, env)
    if rc != 0:
        display.failure("  terraform plan failed; see output above.")
        history.update(task_id, apply_status="plan-failed")
        return False
    display.show_terraform_summary(summary)
    if "0 to add, 0 to change, 0 to destroy" in summary or summary.startswith("No changes"):
        display.info("  Nothing to apply.")
        history.update(task_id, apply_status="skipped")
        return False
    if not display.confirm("Apply this plan?"):
        history.update(task_id, apply_status="skipped")
        return False
    return True


def _run_apply(run_dir: Path, user_cfg: dict, task_id: str, client) -> None:
    env = aws_auth.terraform_env(user_cfg.get("aws_region"))
    if terraform_runner.apply(run_dir, env) != 0:
        display.failure("  terraform apply failed; see output above.")
        history.update(task_id, apply_status="apply-failed")
        return
    outputs = terraform_runner.outputs(run_dir, env)
    display.show_apply_outputs(outputs)
    if client is not None:
        try:
            result = client.confirm(task_id, approved=True)
            display.show_result(result)
        except Exception:
            display.warn("  Backend confirm failed; resources are still applied locally.")
    history.update(task_id, apply_status="deployed", outputs=outputs)


if __name__ == "__main__":
    main()
