"""Per-task working directories for local Terraform runs.

Each task that the user chooses to deploy gets its own dir under
``~/.infrapilot/runs/<task_id>/``. The dir holds the .tf files written from
``code_payload.files``, terraform's local state (``terraform.tfstate``), and
the cached plan (``tfplan``). Re-applying or destroying reuses the same dir
so terraform sees the existing state.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from .config import USER_CONFIG_DIR

RUNS_DIR = USER_CONFIG_DIR / "runs"


def prepare(task_id: str, files: list[dict]) -> Path:
    """Materialize ``files`` under ``RUNS_DIR/<task_id>/`` and return the dir.

    ``files[*]`` are dicts with ``path`` and ``content`` (per the backend's
    CodePayload schema). Nested paths like ``infra/main.tf`` are honored.

    Existing terraform state (.terraform/, terraform.tfstate*) is preserved;
    only the .tf source files are overwritten. Use this when (re-)staging a
    task that may have been applied before.
    """
    if not task_id:
        raise ValueError("task_id is required")
    run_dir = RUNS_DIR / task_id
    run_dir.mkdir(parents=True, exist_ok=True)
    for f in files or []:
        rel = (f.get("path") or "").lstrip("/")
        if not rel:
            continue
        target = run_dir / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(f.get("content") or "", encoding="utf-8")
    return run_dir


def existing(task_id: str) -> Path | None:
    """Return the run dir for ``task_id`` if it has been prepared, else None."""
    if not task_id:
        return None
    p = RUNS_DIR / task_id
    return p if p.is_dir() else None


def delete(task_id: str) -> bool:
    """Remove the run dir entirely. Returns True if something was deleted."""
    p = RUNS_DIR / task_id
    if not p.is_dir():
        return False
    shutil.rmtree(p)
    return True
