"""Shared helpers for core one-shot planning tools."""

from __future__ import annotations


def command_entry(
    *,
    step_name: str,
    description: str,
    binary: str,
    args: list[str],
) -> dict[str, object]:
    """Build one executor-friendly command record."""
    return {
        "step_name": step_name,
        "description": description,
        "critical": True,
        "command": {
            "binary": binary,
            "args": args,
        },
    }


def terraform_payload(
    *,
    intent: str,
    content: str,
    explanation: str,
    notes: list[str] | None = None,
    file_path: str = "main.tf",
) -> dict[str, object]:
    """Build the common payload shape for core Terraform generation tools."""
    return {
        "status": "success",
        "intent": intent,
        "files": [
            {
                "path": file_path,
                "content": content,
                "type": "terraform",
            }
        ],
        "commands": [
            command_entry(
                step_name="terraform_init",
                description="Initialize Terraform in the generated workspace.",
                binary="terraform",
                args=["init"],
            ),
            command_entry(
                step_name="terraform_apply",
                description="Apply the Terraform plan.",
                binary="terraform",
                args=["apply", "-auto-approve"],
            ),
        ],
        "notes": notes or [],
        "requires_confirmation": True,
        "steps": [],
        "error": None,
        "missing_parameters": [],
        "explanation": explanation,
    }
