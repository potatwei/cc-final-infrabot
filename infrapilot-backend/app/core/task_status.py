"""Backend task lifecycle status helpers."""

from __future__ import annotations


def map_task_status(payload: dict) -> str:
    """Translate agent/tool status into backend task lifecycle status."""
    payload_status = payload.get("status")
    payload_mode = payload.get("mode")

    if payload_mode == "discovery":
        if payload_status == "success":
            return "ready_to_execute"
        if payload_status == "needs_input":
            return "collecting_input"
        return "failed"

    if payload_status == "success":
        if payload.get("requires_confirmation"):
            return "awaiting_confirmation"
        return "planned"
    if payload_status == "needs_input":
        return "needs_input"
    return "failed"
