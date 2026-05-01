"""Local task history.

Each task submission is appended to ~/.infrapilot/history.jsonl as one line.
There is no backend list endpoint, so this is the only record of past tasks
that this CLI has submitted from this machine.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from .config import USER_CONFIG_DIR

HISTORY_FILE = USER_CONFIG_DIR / "history.jsonl"


def record(task_id: str, prompt: str, status: str = "") -> None:
    if not task_id:
        return
    HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "task_id": task_id,
        "prompt": (prompt or "").strip(),
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "status": status or "",
    }
    with HISTORY_FILE.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry) + "\n")


def recent(limit: int = 20) -> list[dict]:
    if not HISTORY_FILE.exists():
        return []
    lines = HISTORY_FILE.read_text(encoding="utf-8").splitlines()
    entries: list[dict] = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return entries[-limit:]
