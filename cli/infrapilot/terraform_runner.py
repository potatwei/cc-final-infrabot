"""Subprocess wrappers for the local Terraform binary.

All commands stream output line-by-line so the user sees `terraform` work in
real time instead of waiting for a final dump. The same env (with optional
AWS_REGION pinning) is passed through to every step so credentials and region
flow consistently from boto3's resolution into terraform's AWS provider.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path


_PLAN_SUMMARY_RE = re.compile(
    r"^Plan:\s+(\d+)\s+to add,\s+(\d+)\s+to change,\s+(\d+)\s+to destroy",
    re.MULTILINE,
)
_NO_CHANGES_RE = re.compile(r"No changes\.\s+Your infrastructure matches the configuration")


def check_binary() -> str | None:
    """Return ``terraform`` version string (e.g. "Terraform v1.7.4"), or None.

    Returning None means the user needs to install terraform.
    """
    if shutil.which("terraform") is None:
        return None
    try:
        r = subprocess.run(
            ["terraform", "version"],
            capture_output=True, text=True, check=False, timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    line = (r.stdout or "").splitlines()[0:1]
    return line[0].strip() if line else "terraform"


def _stream(cmd: list[str], cwd: Path, env: dict[str, str]) -> tuple[int, str]:
    """Run ``cmd`` in ``cwd`` with ``env``, streaming combined stdout+stderr.

    Returns ``(exit_code, captured_text)``. Captured text is also kept so the
    caller can grep it for things like the plan-summary line.
    """
    proc = subprocess.Popen(
        cmd, cwd=str(cwd), env=env,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, bufsize=1,
    )
    captured: list[str] = []
    assert proc.stdout is not None
    for line in proc.stdout:
        print(line, end="")
        captured.append(line)
    rc = proc.wait()
    return rc, "".join(captured)


def init(run_dir: Path, env: dict[str, str]) -> int:
    rc, _ = _stream(
        ["terraform", "init", "-input=false", "-no-color"],
        run_dir, env,
    )
    return rc


def plan(run_dir: Path, env: dict[str, str]) -> tuple[int, str]:
    """Run ``terraform plan -out=tfplan``. Returns ``(rc, summary_line)``.

    summary_line is one of:
      - ``"Plan: X to add, Y to change, Z to destroy."``
      - ``"No changes. Your infrastructure matches the configuration."``
      - ``""`` if neither pattern was found (rare; usually means plan errored)
    """
    rc, output = _stream(
        ["terraform", "plan", "-out=tfplan", "-input=false",
         "-lock-timeout=30s", "-no-color"],
        run_dir, env,
    )
    if rc != 0:
        return rc, ""
    m = _PLAN_SUMMARY_RE.search(output)
    if m:
        add, change, destroy = m.groups()
        return rc, f"Plan: {add} to add, {change} to change, {destroy} to destroy."
    if _NO_CHANGES_RE.search(output):
        return rc, "No changes. Your infrastructure matches the configuration."
    return rc, ""


def apply(run_dir: Path, env: dict[str, str]) -> int:
    rc, _ = _stream(
        ["terraform", "apply", "-input=false", "-lock-timeout=30s",
         "-no-color", "tfplan"],
        run_dir, env,
    )
    return rc


def outputs(run_dir: Path, env: dict[str, str]) -> dict:
    """Return ``terraform output -json`` flattened to ``{name: value}``."""
    try:
        r = subprocess.run(
            ["terraform", "output", "-json"],
            cwd=str(run_dir), env=env,
            capture_output=True, text=True, check=False, timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return {}
    if r.returncode != 0 or not r.stdout.strip():
        return {}
    try:
        raw = json.loads(r.stdout)
    except json.JSONDecodeError:
        return {}
    return {k: v.get("value") for k, v in raw.items() if isinstance(v, dict)}


def destroy(run_dir: Path, env: dict[str, str]) -> int:
    rc, _ = _stream(
        ["terraform", "destroy", "-auto-approve", "-input=false",
         "-lock-timeout=30s", "-no-color"],
        run_dir, env,
    )
    return rc
