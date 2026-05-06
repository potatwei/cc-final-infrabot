"""Control tools for the InfraPilot agent.

These tools do not interact with AWS. They allow the agent to emit
structured signals (e.g. missing inputs) so the formatter can produce
accurate, typed payloads without relying on natural-language heuristics.
"""

from __future__ import annotations

from langchain_core.tools import tool


@tool
def report_missing_inputs(
    selected_tool: str,
    missing_parameters: list[str],
    explanation: str,
    provided_inputs: dict | None = None,
) -> dict:
    """REQUIRED: Call this tool whenever required inputs are missing.

    You MUST call this tool — never output plain text alone — when the user's
    request maps to a generation tool (generate_s3_terraform,
    generate_ec2_terraform, or generate_vpc_terraform) but one or more
    required inputs have not been provided. Do NOT call this for completely
    unrelated requests.

    Args:
        selected_tool: Exact name of the generation tool that will run once
            inputs are collected (e.g. "generate_ec2_terraform").
        missing_parameters: Required parameter names the user has not yet
            provided (e.g. ["region", "instance_name"]).
        explanation: Short, user-facing message listing what is needed.
        provided_inputs: Parameter names and values the user HAS already
            provided (e.g. {"bucket_name": "my-bucket"}). Omit or pass
            an empty dict if nothing was provided yet.

    Returns:
        A structured needs_input payload for the formatter.
    """
    return {
        "status": "needs_input",
        "intent": None,
        "selected_tool": selected_tool,
        "provided_inputs": provided_inputs if isinstance(provided_inputs, dict) else {},
        "files": [],
        "commands": [],
        "notes": [],
        "requires_confirmation": False,
        "steps": [],
        "error": None,
        "missing_parameters": missing_parameters,
        "explanation": explanation,
    }
